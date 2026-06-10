"""Offline tests for the Clock-tabs walkthrough (the second app eval cell).

The walkthrough only *executes* on a rig (main → open_phone); the task
definition, the read-only tap allowlist, the manifest assembly, and the
terminal expectation are pure and unit-tested here.
"""
from __future__ import annotations

import pytest

from skills.regression.clock_tabs import (
    CLOCK_TAB_VISITS,
    TASK_SET,
    TERMINAL_EXPECTED_STATE,
    build_clock_tabs_manifest,
    run_clock_tabs_walkthrough,
)
from skills.regression.computer_use_success_rate import (
    _terminal_expected_state_met,
    _validate_expected_state,
)


class _MockAIPhone:
    def __init__(self):
        self.calls: list[tuple] = []

    def launch_app(self, app, *, aliases=()):
        self.calls.append(("launch_app", app, tuple(aliases)))
        return type("O", (), {"ok": True})()

    def tap(self, text=None, *, intent=None, expect_visible=None, expect_page=None):
        self.calls.append(("tap", text, tuple(expect_visible or ())))
        return type("O", (), {"ok": True})()


@pytest.mark.smoke
def test_walkthrough_taps_only_the_four_tabs_with_anchored_expectations():
    phone = _MockAIPhone()
    outcomes = run_clock_tabs_walkthrough(phone)

    assert phone.calls[0] == ("launch_app", "时钟", ("Clock",))
    taps = [c for c in phone.calls if c[0] == "tap"]
    # read-only allowlist: exactly the four tab labels, nothing else
    assert [t[1] for t in taps] == ["Alarms", "Stopwatch", "Timers", "World Clock"]
    # every tap declares a tab-specific anchor (threads expected_state -> P1/P2)
    for (_, tab, anchors), (visit_tab, visit_anchors) in zip(taps, CLOCK_TAB_VISITS, strict=True):
        assert tab == visit_tab
        assert anchors == tuple(visit_anchors)
        assert anchors, f"{tab} tap carries no expectation"
    assert [tab for tab, _ in outcomes] == [tab for tab, _ in CLOCK_TAB_VISITS]


@pytest.mark.smoke
def test_dangerous_controls_are_not_in_the_allowlist():
    targets = {tab for tab, _ in CLOCK_TAB_VISITS}
    for forbidden in ("+", "Start", "Edit", "Delete", "Lap"):
        assert forbidden not in targets


@pytest.mark.smoke
def test_terminal_expected_state_validates_and_matches_world_clock():
    errors: list[str] = []
    _validate_expected_state(TERMINAL_EXPECTED_STATE, "terminal", errors)
    assert errors == []
    # substring semantics against a realistic World Clock final state
    met = _terminal_expected_state_met(
        {"visible_texts": ["World Clock", "Sunrise: 5:47 AM", "Sunset: 9:53 PM"]},
        TERMINAL_EXPECTED_STATE,
    )
    assert met is True
    not_met = _terminal_expected_state_met(
        {"visible_texts": ["No Alarms", "Stopwatch"]},
        TERMINAL_EXPECTED_STATE,
    )
    assert not_met is False


@pytest.mark.smoke
def test_anchor_texts_are_tab_specific():
    """No tab's anchor may be satisfied by another tab's recon texts — else a
    mis-navigation could verify as success."""
    recon = {
        "Alarms": ["World Clock", "Alarms", "Stopwatch", "Timers", "No Alarms"],
        "Stopwatch": ["World Clock", "Alarms", "Stopwatch", "Timers", "00:00.00", "LAP NO.", "Start"],
        "Timers": ["World Clock", "Alarms", "Stopwatch", "Timers", "0 hours", "15 min", "0sec"],
        "World Clock": ["World Clock", "Alarms", "Stopwatch", "Timers", "Sunrise: 5:47AM", "Moscow"],
    }
    for tab, anchors in CLOCK_TAB_VISITS:
        for other_tab, texts in recon.items():
            if other_tab == tab:
                assert any(any(a in t for t in texts) for a in anchors), (
                    f"{tab} anchors {anchors} not satisfied by its own recon texts"
                )
            else:
                assert not any(any(a in t for t in texts) for a in anchors), (
                    f"{tab} anchor matches {other_tab}'s texts — not tab-specific"
                )


@pytest.mark.smoke
def test_manifest_assembly():
    manifest = build_clock_tabs_manifest(["/tmp/run-a", "/tmp/run-b"], rounds=2)
    assert manifest["config"]["task_set"] == TASK_SET
    assert manifest["config"]["rounds"] == 2
    assert [t["round"] for t in manifest["tasks"]] == [0, 1]
    for task in manifest["tasks"]:
        assert task["task"] == "clock_tabs_walkthrough"
        assert task["terminal_expected_state"] == TERMINAL_EXPECTED_STATE
