"""Offline reliability-regression merge gate (the CI-runnable half of Step 0).

`docs/design/computer_use_success_rate.md` requires that "no reliability change
merges without" a non-regression check on the success-rate harness, and the
roadmap's CUQ-3.3 makes `make check` that gate. The on-rig numbers need
hardware, but the *gate logic itself* — `compare_benchmarks` and the committed
baseline fixture — must hold offline, or a silent change to the comparator (or a
schema drift that quietly invalidates the floor) would let a regression through
unnoticed.

These tests pin the comparator without any device:
  1. the committed baseline fixture is an honest floor with completed work,
  2. the committed baseline fixture stays schema-valid as the harness evolves,
  3. the comparator passes parity / improvement and fails a real regression, and
  4. coverage/process/scroll regression metrics have rc1 teeth once the floor is
     non-zero, while invalid candidates are rejected (rc 2), never silently passed.

A degraded/regressed benchmark is derived at runtime from the fixture (flip
non-scroll task-action verdicts, then recompute metrics with the harness's own
`_metrics`) so there is exactly one committed fixture, it can never drift from
the metric logic, and the tests stay valid regardless of the fixture's own
verdict mix (a healthy floor has no `failed` actions to start from).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skills.regression.computer_use_success_rate import (
    _SCROLL_FILLER_OPS,
    _metrics,
    compare_benchmarks,
    validate_benchmark,
)

_BASELINE_PATH = Path(__file__).resolve().parents[1] / "regression" / "fixtures" / "reliability_baseline.json"


def _baseline() -> dict[str, Any]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def _flip_task_action_verdicts(
    payload: dict[str, Any], to_verdict: str, count: int, *, from_verdict: str = "succeeded"
) -> dict[str, Any]:
    """Return a self-consistent copy with `count` primary NON-scroll task-actions
    flipped from_verdict→to_verdict and metrics recomputed (so it still
    validates). Non-scroll because action_success_rate / unknown_rate are
    computed over task-actions only (scroll fillers are excluded), so flipping a
    scroll op would not move the gated metric."""
    out = copy.deepcopy(payload)
    flipped = 0
    for task in out["tasks"]:
        for action in task["actions"]:
            if flipped >= count:
                break
            if (
                action.get("role") == "primary"
                and str(action.get("op", "")) not in _SCROLL_FILLER_OPS
                and action.get("verdict") == from_verdict
            ):
                action["verdict"] = to_verdict
                flipped += 1
    assert flipped == count, (
        f"fixture lacks {count} primary non-scroll {from_verdict!r} task-actions to flip (found {flipped})"
    )
    out["metrics"] = _metrics(out["tasks"])
    return out


def _flip_task_outcomes(payload: dict[str, Any], to_outcome: str, count: int) -> dict[str, Any]:
    """Return a self-consistent copy with completed task outcomes regressed.

    This isolates the task-level compass itself from lower-level action verdicts:
    a run that no longer completes the task must fail the comparator even if its
    action ACK mix remains unchanged.
    """
    out = copy.deepcopy(payload)
    flipped = 0
    for task in out["tasks"]:
        if flipped >= count:
            break
        if task.get("outcome") == "succeeded":
            task["outcome"] = to_outcome
            flipped += 1
    assert flipped == count, (
        f"fixture lacks {count} succeeded tasks to flip (found {flipped})"
    )
    out["metrics"] = _metrics(out["tasks"])
    return out


def _primary_actions(payload: dict[str, Any], *, scroll: bool) -> list[dict[str, Any]]:
    return [
        action
        for task in payload["tasks"]
        for action in task["actions"]
        if action.get("role") == "primary"
        and (str(action.get("op", "")) in _SCROLL_FILLER_OPS) is scroll
    ]


def _with_expected_state_coverage(payload: dict[str, Any], count: int) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    actions = _primary_actions(out, scroll=False)
    assert len(actions) >= count
    for action in actions:
        action["expected_state"] = {"kind": "unknown", "payload": {}}
    for action in actions[:count]:
        action["expected_state"] = {"kind": "page_id", "payload": {"page_id": "settings/test"}}
    out["metrics"] = _metrics(out["tasks"])
    return out


def _with_vlm_action_coverage(payload: dict[str, Any], count: int) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    actions = _primary_actions(out, scroll=False)
    assert len(actions) >= count
    for action in actions:
        action["vlm_calls"] = 0
        action["vlm_triggers"] = []
        action["last_vlm_trigger"] = None
    for action in actions[:count]:
        action["vlm_calls"] = 1
        action["vlm_triggers"] = ["verify_unknown"]
        action["last_vlm_trigger"] = "verify_unknown"
    out["metrics"] = _metrics(out["tasks"])
    return out


def _with_strategy_switches(payload: dict[str, Any], count: int) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    actions = _primary_actions(out, scroll=False)
    assert len(actions) >= count
    for action in actions:
        action["strategy_switches"] = 0
    for action in actions[:count]:
        action["strategy_switches"] = 1
    out["metrics"] = _metrics(out["tasks"])
    return out


def _with_recoveries(payload: dict[str, Any], count: int) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    actions = _primary_actions(out, scroll=False)
    assert len(actions) >= count
    for action in actions:
        action["recovered"] = False
    for action in actions[:count]:
        action["recovered"] = True
    out["metrics"] = _metrics(out["tasks"])
    return out


def _with_scroll_success(payload: dict[str, Any], count: int) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    actions = _primary_actions(out, scroll=True)
    assert len(actions) >= count
    for action in actions:
        action["verdict"] = "unknown"
    for action in actions[:count]:
        action["verdict"] = "succeeded"
        action["raw_semantic_status"] = "succeeded"
    out["metrics"] = _metrics(out["tasks"])
    return out


def _without_scroll_actions(payload: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    for task in out["tasks"]:
        task["actions"] = [
            action
            for action in task["actions"]
            if not (
                action.get("role") == "primary"
                and str(action.get("op", "")) in _SCROLL_FILLER_OPS
            )
        ]
    out["metrics"] = _metrics(out["tasks"])
    return out


@pytest.mark.smoke
def test_committed_baseline_floor_completed_a_task():
    """The committed floor must prove at least one end-to-end task completed.

    Schema validity is not enough: a failed run with a high low-level action ACK
    rate is not a reliability floor.
    """
    baseline = _baseline()
    assert baseline["metrics"]["task_completion_rate"] > 0
    assert all(task.get("outcome") != "failed" for task in baseline["tasks"])


@pytest.mark.smoke
def test_committed_baseline_fixture_is_schema_valid():
    """The committed regression floor must stay schema-valid as the harness
    evolves — otherwise `compare` silently returns rc 2 and gates nothing."""
    assert validate_benchmark(_baseline()) == []


@pytest.mark.smoke
def test_gate_passes_on_parity():
    rc, _ = compare_benchmarks(_baseline(), _baseline())
    assert rc == 0


@pytest.mark.smoke
def test_gate_fails_on_action_success_regression():
    baseline = _baseline()
    regressed = _flip_task_action_verdicts(baseline, "failed", count=3)
    assert regressed["metrics"]["action_success_rate"] < baseline["metrics"]["action_success_rate"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("action_success_rate:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_on_task_completion_regression():
    baseline = _baseline()
    regressed = _flip_task_outcomes(baseline, "failed", count=1)
    assert regressed["metrics"]["task_completion_rate"] < baseline["metrics"]["task_completion_rate"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("task_completion_rate:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_on_unknown_rate_spike():
    baseline = _baseline()
    regressed = _flip_task_action_verdicts(baseline, "unknown", count=3)
    assert regressed["metrics"]["unknown_rate"] > baseline["metrics"]["unknown_rate"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("unknown_rate:") and "delta=+" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_when_expected_state_coverage_drops():
    baseline = _with_expected_state_coverage(_baseline(), count=3)
    regressed = _with_expected_state_coverage(baseline, count=0)
    assert validate_benchmark(baseline) == []
    assert validate_benchmark(regressed) == []
    assert regressed["metrics"]["expected_state_coverage"] < baseline["metrics"]["expected_state_coverage"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("expected_state_coverage:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_when_vlm_action_coverage_drops():
    baseline = _with_vlm_action_coverage(_baseline(), count=3)
    regressed = _with_vlm_action_coverage(baseline, count=0)
    assert validate_benchmark(baseline) == []
    assert validate_benchmark(regressed) == []
    assert regressed["metrics"]["vlm_action_coverage"] < baseline["metrics"]["vlm_action_coverage"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("vlm_action_coverage:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_when_strategy_switches_drop():
    baseline = _with_strategy_switches(_baseline(), count=2)
    regressed = _with_strategy_switches(baseline, count=0)
    assert validate_benchmark(baseline) == []
    assert validate_benchmark(regressed) == []
    assert regressed["metrics"]["strategy_switches"] < baseline["metrics"]["strategy_switches"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("strategy_switches:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_when_recoveries_drop():
    baseline = _with_recoveries(_baseline(), count=2)
    regressed = _with_recoveries(baseline, count=0)
    assert validate_benchmark(baseline) == []
    assert validate_benchmark(regressed) == []
    assert regressed["metrics"]["recoveries"] < baseline["metrics"]["recoveries"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("recoveries:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_fails_when_scroll_success_rate_drops_with_scroll_samples():
    baseline = _with_scroll_success(_baseline(), count=3)
    regressed = _with_scroll_success(baseline, count=0)
    assert validate_benchmark(baseline) == []
    assert validate_benchmark(regressed) == []
    assert baseline["metrics"]["scroll_action_count"] > 0
    assert regressed["metrics"]["scroll_action_count"] > 0
    assert regressed["metrics"]["scroll_success_rate"] < baseline["metrics"]["scroll_success_rate"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("scroll_success_rate:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_does_not_scroll_gate_without_scroll_samples():
    baseline = _with_scroll_success(_baseline(), count=3)
    no_scroll_candidate = _without_scroll_actions(baseline)
    assert validate_benchmark(baseline) == []
    assert validate_benchmark(no_scroll_candidate) == []
    assert baseline["metrics"]["scroll_action_count"] > 0
    assert no_scroll_candidate["metrics"]["scroll_action_count"] == 0
    assert no_scroll_candidate["metrics"]["scroll_success_rate"] < baseline["metrics"]["scroll_success_rate"]
    rc, lines = compare_benchmarks(baseline, no_scroll_candidate)
    assert rc == 0
    assert any(line.startswith("scroll_success_rate:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_gate_passes_on_improvement():
    """A genuine improvement must NOT be flagged as a regression — the gate is
    one-sided. We model it by treating a degraded copy as the baseline and the
    real (better) fixture as the candidate, so the test holds for any fixture
    (even one with no pre-existing `failed` actions)."""
    fixture = _baseline()
    worse_baseline = _flip_task_action_verdicts(fixture, "failed", count=3)
    assert fixture["metrics"]["action_success_rate"] > worse_baseline["metrics"]["action_success_rate"]
    rc, _ = compare_benchmarks(worse_baseline, fixture)
    assert rc == 0


@pytest.mark.smoke
def test_gate_rejects_invalid_candidate_with_rc2():
    """A malformed candidate must hard-fail (rc 2), never pass as a non-regression."""
    invalid = _baseline()
    del invalid["run_id"]
    rc, lines = compare_benchmarks(_baseline(), invalid)
    assert rc == 2
    assert any("run_id" in line for line in lines)


@pytest.mark.smoke
def test_gate_tolerance_absorbs_a_small_drop_but_not_a_large_one():
    baseline = _baseline()
    regressed = _flip_task_action_verdicts(baseline, "failed", count=1)
    drop = baseline["metrics"]["action_success_rate"] - regressed["metrics"]["action_success_rate"]
    assert drop > 0
    # A tolerance wider than the drop absorbs it; zero tolerance catches it.
    rc_loose, _ = compare_benchmarks(baseline, regressed, tolerance=drop + 1e-6)
    rc_strict, _ = compare_benchmarks(baseline, regressed, tolerance=0.0)
    assert rc_loose == 0
    assert rc_strict == 1
