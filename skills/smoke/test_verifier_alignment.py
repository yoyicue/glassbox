"""Offline tests for the verifier-alignment harness (extract/score/validate).

The committed alignment fixture (if present) must validate and its recorded
metrics must exactly match recomputation — same discipline as human_baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.regression.verifier_alignment import (
    build_manifest,
    score_manifest,
    validate_manifest,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "fixtures"
    / "verifier_alignment_settings_v1.json"
)


def _sample(sid, status, annotation, *, verifier="expected_state", rationale="r"):
    return {
        "sample_id": sid,
        "run_dir": "run_x",
        "action_id": sid,
        "op": "tap",
        "intent": None,
        "target": "General",
        "expected_state": {"kind": "page_id", "payload": {"any_of": ["settings/General"]}},
        "verifier": verifier,
        "verifier_status": status,
        "verifier_reason": "reason",
        "before_frame": "frm_000001",
        "after_frame": "frm_000002",
        "annotation": annotation,
        "annotation_rationale": rationale,
    }


def _manifest(samples):
    payload = {
        "schema_version": 1,
        "annotation_source": "synthetic test annotation",
        "samples": samples,
        "metrics": None,
    }
    payload["metrics"] = score_manifest(payload)
    return payload


@pytest.mark.smoke
def test_score_success_assertion_prf():
    samples = (
        [_sample(f"s{i}", "succeeded", "achieved") for i in range(8)]
        + [_sample("s8", "succeeded", "not_achieved")]      # FP: asserted success wrongly
        + [_sample("s9", "unknown", "achieved")]            # FN: declined a real success
        + [_sample("s10", "failed", "not_achieved")]        # true failure assertion
        + [_sample("s11", "unknown", "cant_tell")]          # excluded from binary
    )
    metrics = score_manifest(_manifest(samples))
    assert metrics["n_annotated"] == 12
    assert metrics["n_decided"] == 11
    sa = metrics["success_assertion"]
    assert (sa["tp"], sa["fp"], sa["fn"]) == (8, 1, 1)
    assert sa["precision"] == pytest.approx(8 / 9)
    assert sa["recall"] == pytest.approx(8 / 9)
    fa = metrics["failure_assertion"]
    assert (fa["tp"], fa["fp"], fa["fn"]) == (1, 0, 1)
    assert metrics["confusion"]["succeeded"]["achieved"] == 8
    assert metrics["confusion"]["unknown"]["cant_tell"] == 1


@pytest.mark.smoke
def test_validate_rejects_missing_annotation_and_pii():
    bad = _manifest([_sample("a", "succeeded", "achieved")])
    bad["samples"][0]["annotation"] = None
    errors = validate_manifest(bad, min_samples=1)
    assert any("annotation must be one of" in e for e in errors)

    pii = _manifest([_sample("a", "succeeded", "achieved", rationale="email me @ x")])
    errors = validate_manifest(pii, min_samples=1)
    assert any("direct-identifier" in e for e in errors)


@pytest.mark.smoke
def test_validate_requires_exact_metrics_match():
    manifest = _manifest([_sample(f"s{i}", "succeeded", "achieved") for i in range(25)])
    assert validate_manifest(manifest) == []
    manifest["metrics"]["success_assertion"]["f1"] = 0.5
    errors = validate_manifest(manifest)
    assert any("metrics do not match recomputation" in e for e in errors)


@pytest.mark.smoke
def test_validate_rejects_duplicate_sample_ids_and_bad_status():
    manifest = _manifest(
        [_sample("dup", "succeeded", "achieved"), _sample("dup", "succeeded", "achieved")]
    )
    errors = validate_manifest(manifest, min_samples=1)
    assert any("duplicate sample_id" in e for e in errors)
    bad = _manifest([_sample("a", "exploded", "achieved")])
    errors = validate_manifest(bad, min_samples=1)
    assert any("verifier_status" in e for e in errors)


@pytest.mark.smoke
def test_extract_from_synthetic_run_dir(tmp_path):
    run = tmp_path / "run_t"
    run.mkdir()
    records = [
        {
            "attempt_id": "act_000000",
            "op": "tap",
            "intent": {"name": None},
            "command": {"target": "General", "expected_state": {"kind": "page_id", "payload": {}}},
            "before_command": {"frame_id": "frm_000001"},
            "semantic": {
                "status": "succeeded",
                "verifier": "expected_state",
                "reason": "page_id matched",
                "matched_frame_id": "frm_000002",
            },
        },
        {"attempt_id": "act_000001", "op": "tap", "semantic": "not-a-dict"},
        {"attempt_id": "act_000002", "op": "tap", "semantic": {"status": "weird"}},
    ]
    (run / "actions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    manifest = build_manifest([run])
    assert len(manifest["samples"]) == 1  # non-dict + unscorable statuses dropped
    sample = manifest["samples"][0]
    assert sample["verifier_status"] == "succeeded"
    assert sample["target"] == "General"
    assert sample["after_frame"] == "frm_000002"
    assert sample["annotation"] is None


@pytest.mark.smoke
def test_committed_alignment_fixture_validates_and_metrics_reproduce():
    if not _FIXTURE.exists():
        pytest.skip("no committed verifier-alignment fixture yet")
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert validate_manifest(payload) == []
    assert payload["metrics"] == score_manifest(payload)
    # provenance must be explicit about the annotation method
    assert payload["annotation_source"]
