"""Offline tests for the machinery-probe fault-injection benchmark.

The suite only *executes* on a rig (main → open_phone), but the injection
contract (tap a present row with an UNREACHABLE expected page), the manifest
assembly, and the "machine fired" gate are pure and unit-tested here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from skills.regression.computer_use_success_rate import _validate_expected_state
from skills.regression.computer_use_success_rate import main as cli_main
from skills.regression.machinery_probe import (
    MACHINERY_PROBE_TASKS,
    UNREACHABLE_PAGE_ID,
    build_machinery_probe_manifest,
    machinery_fired_reasons,
    run_probe,
)


class _Element:
    def __init__(self, text, type="list_item"):
        self.text = text
        self.type = type


class _MockAIPhone:
    """Records the AIPhone calls a machinery-probe task makes."""

    def __init__(self, elements=None):
        self.calls: list[tuple] = []
        self._elements = elements if elements is not None else [
            _Element("Wi-Fi"),
            _Element("Bluetooth"),
        ]

    def launch_app(self, app, *, aliases=()):
        self.calls.append(("launch_app", app, tuple(aliases)))
        return type("O", (), {"ok": True})()

    def elements(self, *, refresh=False):
        self.calls.append(("elements",))
        return tuple(self._elements)

    def tap(self, text=None, *, intent=None, expect_visible=None, expect_page=None):
        self.calls.append(("tap", text, expect_page))
        return type("O", (), {"ok": False})()


@pytest.mark.smoke
def test_probe_injects_unreachable_expectation_on_a_present_row():
    phone = _MockAIPhone(elements=[_Element("Wi-Fi"), _Element("General")])
    run_probe(phone, MACHINERY_PROBE_TASKS[0])

    # It anchors on Settings, reads the screen, then taps a PRESENT row while
    # declaring the unreachable page — the controlled verification failure.
    assert ("launch_app", "设置", ("Settings",)) in phone.calls
    tap_calls = [c for c in phone.calls if c[0] == "tap"]
    assert len(tap_calls) == 1
    _, target, expect_page = tap_calls[0]
    assert target == "Wi-Fi"  # a present, readable row (not a fixed locale label)
    assert expect_page == UNREACHABLE_PAGE_ID


@pytest.mark.smoke
def test_probe_prefers_list_item_rows_then_falls_back_to_any_text():
    # No list_items present → fall back to any readable text rather than crash.
    phone = _MockAIPhone(elements=[_Element("Settings", type="text")])
    run_probe(phone, MACHINERY_PROBE_TASKS[0])
    tap_calls = [c for c in phone.calls if c[0] == "tap"]
    assert tap_calls and tap_calls[0][1] == "Settings"


@pytest.mark.smoke
def test_probe_manifest_assembly_and_terminal_state_validates():
    manifest = build_machinery_probe_manifest(
        {"wrong_expectation_tap": ["/tmp/run-a", "/tmp/run-b"]}, rounds=2
    )
    assert manifest["config"]["task_set"] == "machinery_probe"
    assert manifest["config"]["rounds"] == 2
    assert [t["task"] for t in manifest["tasks"]] == [
        "wrong_expectation_tap",
        "wrong_expectation_tap",
    ]
    assert [t["round"] for t in manifest["tasks"]] == [0, 1]
    # Each task's terminal_expected_state must be a valid expected-state.
    for task in manifest["tasks"]:
        errors: list[str] = []
        _validate_expected_state(task["terminal_expected_state"], "terminal", errors)
        assert errors == []


@pytest.mark.smoke
def test_machine_fired_gate_passes_only_when_ladder_and_recovery_both_fired():
    fired = {"metrics": {"strategy_switches": 2, "recoveries": 1}}
    assert machinery_fired_reasons(fired) == []


@pytest.mark.smoke
def test_machine_fired_gate_fails_when_ladder_did_not_advance():
    no_ladder = {"metrics": {"strategy_switches": 0, "recoveries": 1}}
    reasons = machinery_fired_reasons(no_ladder)
    assert any("strategy_switches=0 < 1" in r for r in reasons)
    assert not any("recoveries" in r for r in reasons)


@pytest.mark.smoke
def test_machine_fired_gate_fails_when_recovery_did_not_fire():
    no_recovery = {"metrics": {"strategy_switches": 3, "recoveries": 0}}
    reasons = machinery_fired_reasons(no_recovery)
    assert any("recoveries=0 < 1" in r for r in reasons)
    assert not any("strategy_switches" in r for r in reasons)


@pytest.mark.smoke
def test_machine_fired_gate_fails_when_both_dead():
    dead = {"metrics": {"strategy_switches": 0, "recoveries": 0}}
    assert len(machinery_fired_reasons(dead)) == 2


@pytest.mark.smoke
def test_machine_fired_gate_handles_missing_metrics():
    assert machinery_fired_reasons({}) == ["benchmark has no metrics block"]


_L2_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "fixtures"
    / "l2_settings_expected_state_snapshot.json"
)


@pytest.mark.smoke
def test_validate_machinery_probe_cli_rejects_a_non_probe_benchmark(capsys):
    # The committed L2 snapshot is a Settings run (strategy_switches>0 but
    # recoveries=0), not a fault-injection probe — the CLI gate must reject it
    # rc 1, proving the wiring over a real schema-valid benchmark.
    rc = cli_main(["validate-machinery-probe", str(_L2_SNAPSHOT)])
    assert rc == 1
    assert "P3 recovery regressed" in capsys.readouterr().out
