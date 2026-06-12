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
    IOS_SETTINGS_CLEAN_HDMI_ENVIRONMENT,
    IOS_SETTINGS_CLEAN_HDMI_EVALUATION_CELL,
    _metrics,
    compare_benchmarks,
    main,
    validate_benchmark,
    validate_floor_candidate,
)

_BASELINE_PATH = Path(__file__).resolve().parents[1] / "regression" / "fixtures" / "reliability_baseline.json"
_EXPECTED_STATE_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "fixtures"
    / "l2_settings_expected_state_snapshot.json"
)


def _baseline() -> dict[str, Any]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def _expected_state_snapshot() -> dict[str, Any]:
    return json.loads(_EXPECTED_STATE_SNAPSHOT_PATH.read_text(encoding="utf-8"))


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
def test_l2_expected_state_snapshot_fixture_is_load_bearing_and_scrubbed():
    """The coverage-bearing L2 snapshot must stay real, multi-sample, and safe to
    commit. It complements the 1.0 completion floor; it does not replace it.

    It is the ONLY committed fixture that exercises the P1 VLM gate and the P2
    strategy ladder (the clean completion floor has both at 0 by design), so it
    must keep non-zero vlm_action_coverage and strategy_switches — otherwise the
    coverage path could be silently replaced with a degraded, zero-coverage run.
    """
    payload = _expected_state_snapshot()
    raw = _EXPECTED_STATE_SNAPSHOT_PATH.read_text(encoding="utf-8")

    assert validate_benchmark(payload) == []
    assert payload["config"]["phone_model"] == "ipad_mini_7"
    assert payload["config"]["rounds"] >= 5
    assert len(payload["tasks"]) >= 5
    assert payload["metrics"]["task_completion_rate"] > 0
    assert payload["metrics"]["expected_state_coverage"] > 0
    assert payload["metrics"]["vlm_action_coverage"] > 0
    assert payload["metrics"]["strategy_switches"] > 0
    assert any(
        action.get("expected_state", {}).get("kind") == "page_id"
        for task in payload["tasks"]
        for action in task["actions"]
    )
    assert all((task.get("final_state") or {}).get("visible_texts") == [] for task in payload["tasks"])
    assert all("elements" not in (task.get("final_state") or {}) for task in payload["tasks"])
    for forbidden in ("Jo Doe", "Apple Account and password", "You must enter both your"):
        assert forbidden not in raw


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
def test_gate_fails_when_real_l2_expected_state_snapshot_coverage_drops():
    baseline = _expected_state_snapshot()
    regressed = _with_expected_state_coverage(baseline, count=0)
    assert baseline["metrics"]["expected_state_coverage"] > 0
    assert validate_benchmark(regressed) == []
    assert regressed["metrics"]["expected_state_coverage"] == 0

    rc, lines = compare_benchmarks(baseline, regressed)

    assert rc == 1
    assert any(line.startswith("expected_state_coverage:") and "delta=-" in line for line in lines)


@pytest.mark.smoke
def test_floor_candidate_rejects_current_l2_snapshot_until_completion_non_regresses():
    rc, lines = validate_floor_candidate(_baseline(), _expected_state_snapshot())

    assert rc == 1
    assert any(line.startswith("task_completion_rate would drop:") for line in lines)
    assert any(line.startswith("root_pages_coverage would drop:") for line in lines)
    assert any(line.startswith("unknown_rate would rise:") for line in lines)
    assert not any("expected_state_coverage must be > 0" in line for line in lines)


@pytest.mark.smoke
def test_floor_candidate_accepts_non_regressing_coverage_bearing_candidate():
    # The committed floor now bears real expected-state coverage, so a
    # non-regressing candidate is one that holds (or exceeds) it. An identical
    # copy of the floor is coverage-bearing and trivially non-regressing.
    baseline = _baseline()
    candidate = _baseline()
    assert candidate["metrics"]["expected_state_coverage"] > 0

    rc, lines = validate_floor_candidate(baseline, candidate)

    assert rc == 0
    assert lines == ["OK"]


@pytest.mark.smoke
def test_floor_candidate_requires_expected_state_coverage_by_default():
    # A zero-coverage candidate must be rejected by default. The committed floor
    # now bears coverage, so derive a zero-coverage payload to exercise the rule.
    zero_coverage = _with_expected_state_coverage(_baseline(), count=0)
    assert zero_coverage["metrics"]["expected_state_coverage"] == 0

    rc, lines = validate_floor_candidate(zero_coverage, zero_coverage)

    assert rc == 1
    assert lines == ["expected_state_coverage must be > 0 for a promoted L2 floor"]
    rc, lines = validate_floor_candidate(
        zero_coverage, zero_coverage, require_expected_state_coverage=False
    )
    assert rc == 0
    assert lines == ["OK"]


@pytest.mark.smoke
def test_floor_candidate_requires_clean_hdmi_settings_cell():
    baseline = _baseline()
    candidate = _with_expected_state_coverage(baseline, count=3)
    candidate["config"]["evaluation_cell"] = "ios_settings_a11y_voice_control"
    candidate["config"]["environment"] = {
        **IOS_SETTINGS_CLEAN_HDMI_ENVIRONMENT,
        "voice_control_overlay": "item_numbers",
    }

    rc, lines = validate_floor_candidate(baseline, candidate)

    assert rc == 1
    assert any(
        line
        == (
            "config.evaluation_cell must be "
            f"{IOS_SETTINGS_CLEAN_HDMI_EVALUATION_CELL!r} for promoted Settings floors"
        )
        for line in lines
    )
    assert any(
        line == "config.environment.voice_control_overlay must be 'off'; got 'item_numbers'"
        for line in lines
    )


@pytest.mark.smoke
def test_floor_candidate_rejects_observed_voice_control_numeric_overlay():
    baseline = _baseline()
    candidate = _with_expected_state_coverage(baseline, count=3)
    candidate["tasks"][0]["final_state"]["elements"] = [
        {
            "type": "text",
            "box": {"x": 8, "y": 80 + i * 24, "w": 14, "h": 12},
            "text": str(i + 1),
            "confidence": 1.0,
            "element_id": i,
        }
        for i in range(6)
    ]

    rc, lines = validate_floor_candidate(baseline, candidate)

    assert rc == 1
    assert any(
        line
        == (
            "tasks[0].final_state has 6 numeric Voice Control overlay markers; "
            "default Settings floor requires Voice Control overlay off"
        )
        for line in lines
    )


@pytest.mark.smoke
def test_floor_candidate_cli_rejects_current_l2_snapshot(capsys):
    rc = main(
        [
            "validate-floor-candidate",
            str(_BASELINE_PATH),
            str(_EXPECTED_STATE_SNAPSHOT_PATH),
        ]
    )

    assert rc == 1
    assert "task_completion_rate would drop" in capsys.readouterr().out


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
    # The committed floor's recovery events occur on scroll actions, so dropping
    # all scroll actions would also drop `recoveries` (a gated metric) and mask
    # what this test isolates. Zero recoveries first so removing scroll moves
    # only the scroll axis.
    for task in baseline["tasks"]:
        for action in task["actions"]:
            action["recovered"] = False
    baseline["metrics"] = _metrics(baseline["tasks"])
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


@pytest.mark.smoke
def test_gate_refuses_cross_config_comparison_by_default():
    """Gating a candidate from a different device/locale against the floor
    compares two observation distributions — the verdict is meaningless either
    way it falls (snapshot item 2: the nightly zh-iPhone lane used to do
    exactly this against the en-iPad floor)."""
    baseline = _baseline()
    cross = copy.deepcopy(baseline)
    cross["config"]["phone_model"] = "iphone_17_pro_max"
    cross["config"]["language"] = "zh-Hans"

    rc, lines = compare_benchmarks(baseline, cross)
    assert rc == 2
    assert any("config.phone_model mismatch" in line for line in lines)
    assert any("not comparable for gating" in line for line in lines)


@pytest.mark.smoke
def test_gate_allows_cross_config_comparison_as_labelled_advisory():
    baseline = _baseline()
    cross = copy.deepcopy(baseline)
    cross["config"]["phone_model"] = "iphone_17_pro_max"

    rc, lines = compare_benchmarks(baseline, cross, allow_config_mismatch=True)
    assert rc == 0  # identical metrics — only the config identity differs
    assert any("advisory readout" in line for line in lines)
    assert any("config.phone_model mismatch" in line for line in lines)


@pytest.mark.smoke
def test_gate_count_metrics_compare_per_round_not_raw():
    """Raw run-total counts are only scale-comparable per round: a 2-round
    candidate with 1 recovery (0.5/round) must NOT read as a regression against
    a 5-round floor with 2 (0.4/round) — and a same-rounds candidate with fewer
    recoveries per round still must."""
    baseline = _with_recoveries(_baseline(), count=2)
    assert int(baseline["config"]["rounds"]) == 5

    fewer_rounds = _with_recoveries(baseline, count=1)
    fewer_rounds["config"]["rounds"] = 2
    assert validate_benchmark(fewer_rounds) == []
    rc, lines = compare_benchmarks(baseline, fewer_rounds)
    assert rc == 0
    assert any(line.startswith("recoveries:") and "/round" in line for line in lines)

    same_rounds_regressed = _with_recoveries(baseline, count=1)
    rc, _ = compare_benchmarks(baseline, same_rounds_regressed)
    assert rc == 1


@pytest.mark.smoke
def test_gate_says_so_when_a_drop_gate_is_vacuous():
    """The committed floor has strategy_switches=0 and vlm_action_coverage=0 —
    their drop-gates cannot fire. "Printed and gated" must not read as
    "protected": the comparator now says so explicitly on every run."""
    baseline = _baseline()
    assert float(baseline["metrics"]["strategy_switches"]) == 0.0

    rc, lines = compare_benchmarks(baseline, copy.deepcopy(baseline))
    assert rc == 0
    assert any("strategy_switches drop-gate is vacuous" in line for line in lines)
    assert any("vlm_action_coverage drop-gate is vacuous" in line for line in lines)


@pytest.mark.smoke
def test_duration_metrics_are_printed_but_never_gated():
    """Speed is visible in every compare (snapshot item 2: latency could
    regress through every gate invisibly) but never gates — observed action
    duration is host/rig-dependent and reliability-first explicitly buys it."""
    from skills.regression.computer_use_success_rate import (
        GATE_DROP_METRICS,
        GATE_RISE_METRICS,
    )

    assert "action_duration_ms_total" not in GATE_DROP_METRICS | GATE_RISE_METRICS
    assert "action_duration_ms_per_task" not in GATE_DROP_METRICS | GATE_RISE_METRICS

    baseline = _baseline()
    slower = copy.deepcopy(baseline)
    slower["tasks"][0]["actions"][0]["duration_ms"] += 600_000  # +10 min, way past any tolerance
    slower["metrics"] = _metrics(slower["tasks"])
    assert validate_benchmark(slower) == []
    assert (
        slower["metrics"]["action_duration_ms_total"]
        > baseline["metrics"]["action_duration_ms_total"]
    )

    rc, lines = compare_benchmarks(baseline, slower)
    assert rc == 0
    assert any(line.startswith("action_duration_ms_total:") for line in lines)
