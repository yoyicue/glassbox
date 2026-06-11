"""Offline guard for the committed Clock-tabs cell floor (second app cell).

Same discipline as the Settings completion floor: the committed fixture must
be schema-valid, must prove completed work (execution-based, not ACK), and
must carry the cell identity so it can never be confused with the Settings
floor (FLOOR_IDENTITY includes task_set).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.regression.computer_use_success_rate import validate_benchmark

_FLOOR = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "fixtures"
    / "clock_tabs_baseline.json"
)


@pytest.mark.smoke
def test_committed_clock_tabs_floor_is_valid_and_completed():
    if not _FLOOR.exists():
        pytest.fail(
            f"committed clock-tabs floor missing: {_FLOOR} — it is gate-load-bearing; "
            "deleting it must not merge green (was a silent pytest.skip)"
        )
    payload = json.loads(_FLOOR.read_text(encoding="utf-8"))
    assert validate_benchmark(payload) == []
    assert payload["config"]["task_set"] == "ipados_clock_tabs"
    assert payload["config"]["rounds"] >= 5
    assert len(payload["tasks"]) >= 5
    # execution-based completion floor, not an ACK floor. The first committed
    # floor is honestly 4/5 (one round's launch landed in the wrong app) — the
    # failed round stays visible; the gate asserts completion, not perfection.
    assert payload["metrics"]["task_completion_rate"] > 0
    assert sum(1 for task in payload["tasks"] if task.get("outcome") == "succeeded") >= 4
    # the tab taps carry expectations (the cell's whole point)
    assert payload["metrics"]["expected_state_coverage"] > 0
    # cell profile assumptions are recorded (anchors depend on device state)
    assert payload["config"].get("cell_profile")
    # scrubbed like the L2 snapshot: no raw OCR dumps in final states
    assert all((task.get("final_state") or {}).get("visible_texts") == [] for task in payload["tasks"])
