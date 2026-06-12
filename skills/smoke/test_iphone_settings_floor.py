"""Offline guard for the committed iPhone Settings floor (first device-matched
iPhone fixture; closes project_health_snapshot item "iPhone floor").

First committed floor: 2026-06-12, iPhone 17 Pro Max (en/CN), n=5, produced by
the post-#99/#100 transition-recognition stack. task_completion 0.0 — an HONEST
floor, not a success story (precedent: the a11y loop-1 snapshot was committed at
0.0). The zero is deterministic and forensically attributed: the REQUIRED root
row 操作按钮 stays missing in every round, so the root_coverage_complete
terminal can never pass; this guard pins that attribution so the fixture cannot
silently be swapped for an *unexplained* zero. Round 4 ended early on a PicoKVM
stream-open exception and stays visible. The on-rig comparison lane lives in
rig-nightly.yml (iPhone lane, config-matched, blocking).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from skills.regression.computer_use_success_rate import (
    IOS_SETTINGS_CLEAN_HDMI_ENVIRONMENT,
    IOS_SETTINGS_CLEAN_HDMI_EVALUATION_CELL,
    compare_benchmarks,
    validate_benchmark,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "regression" / "fixtures"
_FLOOR = _FIXTURES / "iphone_settings_baseline.json"
_IPAD_FLOOR = _FIXTURES / "reliability_baseline.json"


def _floor() -> dict:
    return json.loads(_FLOOR.read_text(encoding="utf-8"))


@pytest.mark.smoke
def test_committed_iphone_floor_is_valid_with_cell_identity():
    if not _FLOOR.exists():
        pytest.fail(
            f"committed iPhone Settings floor missing: {_FLOOR} — it is gate-load-bearing; "
            "deleting it must not merge green"
        )
    payload = _floor()
    assert validate_benchmark(payload) == []
    # Full config identity: this is what the nightly comparator matches on, and
    # what refuses cross-device/locale gating.
    assert payload["config"]["task_set"] == "ios_settings"
    assert payload["config"]["phone_model"] == "iphone_17_pro_max"
    assert payload["config"]["language"] == "en"
    assert payload["config"]["region"] == "CN"
    assert payload["config"]["evaluation_cell"] == IOS_SETTINGS_CLEAN_HDMI_EVALUATION_CELL
    assert payload["config"]["environment"] == IOS_SETTINGS_CLEAN_HDMI_ENVIRONMENT
    assert payload["config"]["rounds"] >= 5
    assert len(payload["tasks"]) >= 5


@pytest.mark.smoke
def test_committed_iphone_floor_zero_completion_is_attributed_not_noise():
    """An honest 0.0 floor is only committable while the zero stays explained:
    every round fails AND the named residual (the REQUIRED root row 操作按钮,
    dead-band + search miss, #99 insufficient live) is the recorded cause. If a
    regenerated fixture no longer misses that row, this test forces the floor —
    and its completion value — to be re-examined instead of silently replaced.
    """
    payload = _floor()
    assert payload["metrics"]["task_completion_rate"] == 0.0
    assert all(task.get("outcome") == "failed" for task in payload["tasks"])
    assert all("操作按钮" in (task.get("root_pages_missing") or []) for task in payload["tasks"])
    # The floor still proves real work: this is a near-complete crawl that
    # deterministically misses one required row, not a dead run.
    assert payload["metrics"]["action_success_rate"] > 0.8
    assert payload["metrics"]["root_pages_coverage"] > 0.8
    assert payload["metrics"]["expected_state_coverage"] > 0


@pytest.mark.smoke
def test_committed_iphone_floor_is_scrubbed():
    """Public-fixture scrub convention (canonical floor / L2 snapshot): no raw
    OCR dumps in committed final states."""
    payload = _floor()
    for task in payload["tasks"]:
        final_state = task.get("final_state") or {}
        assert final_state.get("visible_texts") == []
        assert final_state.get("elements") == []


@pytest.mark.smoke
def test_iphone_floor_refuses_ipad_floor_comparison():
    """The comparator's config-identity refusal must cover this fixture pair:
    gating either device's candidate against the other's floor compares two
    observation distributions (exactly the old zh-iPhone-vs-en-iPad hole)."""
    ipad = json.loads(_IPAD_FLOOR.read_text(encoding="utf-8"))
    rc, lines = compare_benchmarks(_floor(), ipad)
    assert rc == 2
    assert any("config.phone_model mismatch" in line for line in lines)
    assert any("not comparable for gating" in line for line in lines)


@pytest.mark.smoke
def test_iphone_floor_parity_passes_and_completion_gate_is_declared_vacuous():
    """Same machinery, no new semantics: a config-matched parity candidate
    passes, and the comparator says out loud that the task_completion_rate
    drop-gate cannot fire against a 0.0 floor — "printed and gated" must not
    read as "protected"."""
    floor = _floor()
    rc, lines = compare_benchmarks(floor, copy.deepcopy(floor))
    assert rc == 0
    assert any("task_completion_rate drop-gate is vacuous" in line for line in lines)
    # Non-zero on this floor — these drop-gates have real teeth here.
    assert floor["metrics"]["strategy_switches"] > 0
    assert floor["metrics"]["vlm_action_coverage"] > 0
    assert not any("strategy_switches drop-gate is vacuous" in line for line in lines)
    assert not any("vlm_action_coverage drop-gate is vacuous" in line for line in lines)
