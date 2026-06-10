from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skills.regression import human_baseline

pytestmark = pytest.mark.smoke

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "fixtures"
    / "human_baseline_settings_template.json"
)


def _trial(
    round_index: int,
    *,
    outcome: str = "succeeded",
    missing: tuple[str, ...] = (),
    blocked: tuple[str, ...] | None = None,
    duration_ms: int = 30_000,
) -> dict[str, Any]:
    pages = human_baseline.expected_root_pages()
    blocked_labels = tuple(blocked) if blocked is not None else (pages[-1],)
    missing_labels = missing if outcome == "succeeded" else (missing or (pages[-2],))
    reachable = len(pages) - len(blocked_labels)
    covered = reachable if outcome == "succeeded" else reachable - len(missing_labels)
    return {
        "trial_id": f"T{round_index:03d}",
        "participant_id": "P001",
        "started_at": f"2026-06-06T10:{round_index:02d}:00Z",
        "ended_at": f"2026-06-06T10:{round_index:02d}:30Z",
        "outcome": outcome,
        "round": round_index,
        "duration_ms": duration_ms + round_index,
        "root_pages_expected": len(pages),
        "root_pages_covered": covered,
        "root_pages_blocked": len(blocked_labels),
        "root_pages_blocked_labels": list(blocked_labels),
        "root_pages_missing": list(missing_labels),
        "notes": "",
    }


def _valid_payload() -> dict[str, Any]:
    payload = human_baseline.template_payload()
    payload["participants"] = [
        {
            "participant_id": "P001",
            "role": "human",
            "experience": "familiar",
        }
    ]
    pages = human_baseline.expected_root_pages()
    payload["trials"] = [
        _trial(1, outcome="succeeded"),
        _trial(2, outcome="succeeded"),
        _trial(3, outcome="succeeded"),
        _trial(4, outcome="succeeded"),
        _trial(5, outcome="failed", missing=(pages[-2],)),
    ]
    payload["metrics"] = human_baseline._metrics(payload["trials"])
    return payload


def test_template_uses_settings_policy_expected_pages():
    payload = human_baseline.template_payload()
    pages = payload["protocol"]["expected_root_pages"]

    assert pages == human_baseline.expected_root_pages()
    assert len(pages) == len(set(pages))
    assert {"无线局域网", "辅助功能", "隐私与安全性"} <= set(pages)


def test_template_validates_only_when_explicitly_allowed():
    payload = human_baseline.template_payload()

    assert human_baseline.validate_human_baseline(payload, allow_template=True) == []
    errors = human_baseline.validate_human_baseline(payload)
    assert any("trials must contain at least" in error for error in errors)


def test_valid_human_baseline_metrics_are_recomputed():
    payload = _valid_payload()

    assert human_baseline.validate_human_baseline(payload) == []
    assert payload["metrics"]["trial_count"] == 5
    assert payload["metrics"]["task_completion_rate"] == 0.8
    assert payload["metrics"]["task_completion_variance"] == pytest.approx(0.16)
    assert payload["metrics"]["root_pages_coverage"] == pytest.approx(79 / 80)


def test_validate_rejects_metric_drift():
    payload = _valid_payload()
    payload["metrics"] = copy.deepcopy(payload["metrics"])
    payload["metrics"]["task_completion_rate"] = 1.0

    errors = human_baseline.validate_human_baseline(payload)

    assert any("metrics.task_completion_rate mismatch" in error for error in errors)


def test_validate_rejects_protocol_scope_drift():
    payload = _valid_payload()
    payload["protocol"]["device"]["phone_model"] = "iphone"
    payload["protocol"]["expected_root_pages"] = payload["protocol"]["expected_root_pages"][:-1]

    errors = human_baseline.validate_human_baseline(payload)

    assert any("protocol.device.phone_model must be 'ipad_mini_7'" in error for error in errors)
    assert any("protocol.expected_root_pages must equal" in error for error in errors)


def test_validate_rejects_direct_identifiers():
    payload = _valid_payload()
    payload["participants"][0]["email"] = "person@example.test"
    payload["trials"][0]["notes"] = "Saw Apple Account password modal."

    errors = human_baseline.validate_human_baseline(payload)

    assert any("participants[0].email must not be recorded" in error for error in errors)
    assert any("trials[0].notes must not contain direct identifiers" in error for error in errors)


def test_validate_rejects_success_with_missing_or_incomplete_pages():
    payload = _valid_payload()
    payload["trials"][0]["root_pages_missing"] = ["辅助功能"]
    payload["trials"][1]["root_pages_covered"] -= 1
    payload["metrics"] = human_baseline._metrics(payload["trials"])

    errors = human_baseline.validate_human_baseline(payload)

    assert any("root_pages_missing must be empty for succeeded trials" in error for error in errors)
    assert any("root_pages_covered must equal reachable pages" in error for error in errors)


def test_validate_rejects_unknown_or_mismatched_blocked_labels():
    payload = _valid_payload()
    payload["trials"][0]["root_pages_blocked_labels"] = ["Not A Settings Page"]
    payload["trials"][1]["root_pages_blocked_labels"] = []
    payload["metrics"] = human_baseline._metrics(payload["trials"])

    errors = human_baseline.validate_human_baseline(payload)

    assert any("outside protocol expected_root_pages" in error for error in errors)
    assert any("root_pages_blocked must match" in error for error in errors)


def test_committed_template_fixture_is_valid_and_blank():
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    assert human_baseline.validate_human_baseline(payload, allow_template=True) == []
    assert payload["participants"] == []
    assert payload["trials"] == []
    assert payload["metrics"] == human_baseline._metrics([])


def test_cli_template_validate_and_summarize(tmp_path: Path):
    out = tmp_path / "human-template.json"

    assert human_baseline.main(["template", "--out", str(out)]) == 0
    assert out.exists()
    assert human_baseline.main(["validate", str(out), "--allow-template"]) == 0
    assert human_baseline.main(["summarize", str(out)]) == 0
