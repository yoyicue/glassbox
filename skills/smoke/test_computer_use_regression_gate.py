"""Offline reliability-regression merge gate (the CI-runnable half of Step 0).

`docs/design/computer_use_success_rate.md` requires that "no reliability change
merges without" a non-regression check on the success-rate harness, and the
roadmap's CUQ-3.3 makes `make check` that gate. The on-rig numbers need
hardware, but the *gate logic itself* — `compare_benchmarks` and the committed
baseline fixture — must hold offline, or a silent change to the comparator (or a
schema drift that quietly invalidates the floor) would let a regression through
unnoticed.

These tests pin three things without any device:
  1. the committed baseline fixture stays schema-valid as the harness evolves,
  2. the comparator passes parity / improvement and fails a real regression, and
  3. an unparseable/invalid candidate is rejected (rc 2), never silently passed.

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
def test_gate_fails_on_unknown_rate_spike():
    baseline = _baseline()
    regressed = _flip_task_action_verdicts(baseline, "unknown", count=3)
    assert regressed["metrics"]["unknown_rate"] > baseline["metrics"]["unknown_rate"]
    rc, lines = compare_benchmarks(baseline, regressed)
    assert rc == 1
    assert any(line.startswith("unknown_rate:") and "delta=+" in line for line in lines)


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
