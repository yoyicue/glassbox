"""Offline guard for the committed canonical-primitives floor (A/B matrix #9).

First committed floor: 2026-06-11, iPad mini 7 (en/HK rig env), n=5, produced
by the post-#75/#76/#77 stack (stream-open retry, facade home via the verified
ladder, platform-vocabulary terminals). task_completion 0.9 — the one failed +
one unknown scroll round stay visible; the gate asserts an honest floor, not
perfection. The on-rig comparison lane lives in rig-nightly.yml (iPad lane,
config-matched, blocking).
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
    / "canonical_primitives_baseline.json"
)


@pytest.mark.smoke
def test_committed_canonical_floor_is_valid_and_completed():
    if not _FLOOR.exists():
        pytest.fail(
            f"committed canonical floor missing: {_FLOOR} — it is gate-load-bearing; "
            "deleting it must not merge green"
        )
    payload = json.loads(_FLOOR.read_text(encoding="utf-8"))
    assert validate_benchmark(payload) == []
    assert payload["config"]["task_set"] == "canonical_primitives"
    assert payload["config"]["phone_model"] == "ipad_mini_7"
    assert payload["config"]["rounds"] >= 5
    assert len(payload["tasks"]) >= 20
    # Honest completion floor: > 0 and produced by verified-Home preconditions.
    assert payload["metrics"]["task_completion_rate"] > 0
    assert payload["metrics"]["navigation_origin_precondition_failures"] == 0
    # Every navigation-class task carries a verified-Home origin.
    origins = [task.get("navigation_origin") for task in payload["tasks"]]
    assert all(o is None or o.get("can_start_clock") is not False for o in origins)


@pytest.mark.smoke
def test_committed_canonical_floor_is_scrubbed():
    """Public-fixture scrub convention (same as the L2 snapshot): the go_home
    rounds' final scenes are the rig owner's Home screen — widget content
    (city/weather/calendar) must not ship in the repo."""
    payload = json.loads(_FLOOR.read_text(encoding="utf-8"))
    for task in payload["tasks"]:
        final_state = task.get("final_state") or {}
        assert final_state.get("visible_texts") == []
        assert final_state.get("elements") == []
