"""Offline tests for the per-session calibration probe (CUQ-3.7).

The probe only TAPS on a rig; its decision + driver logic are pure + tested here."""
from __future__ import annotations

import pytest

from glassbox.action.calibration import (
    run_session_calibration_probe,
    session_calibration_needed,
)


class _Stats:
    def __init__(self, offset):
        self.offset = offset


class _Entry:
    def __init__(self, offset=None):
        self.methods = {"mouse_tap": _Stats(offset)}


class _Profile:
    def __init__(self, entries):
        self.entries = entries


class _Orchestrator:
    def __init__(self, profile):
        self.actuation_profile = profile


class _MockPhone:
    def __init__(self, profile):
        self.action_orchestrator = _Orchestrator(profile)
        self.taps: list[tuple[str, dict]] = []

    def tap_text(self, target, **kw):
        self.taps.append((target, kw))


@pytest.mark.smoke
def test_session_calibration_needed_only_at_cold_start():
    assert session_calibration_needed(_Profile({})) is True  # no entries
    assert session_calibration_needed(_Profile({"k": _Entry(offset=None)})) is True
    assert session_calibration_needed(_Profile({"k": _Entry(offset=(1, 2))})) is False


@pytest.mark.smoke
def test_probe_taps_anchor_when_uncalibrated():
    phone = _MockPhone(_Profile({}))  # cold start
    assert run_session_calibration_probe(phone, "通用") is True
    assert phone.taps == [("通用", {"landing_retry_allowed": True})]


@pytest.mark.smoke
def test_probe_is_noop_without_target_or_when_calibrated():
    # No target -> byte-identical (no tap).
    phone = _MockPhone(_Profile({}))
    assert run_session_calibration_probe(phone, "") is False
    assert run_session_calibration_probe(phone, "   ") is False
    assert phone.taps == []

    # Already calibrated -> no probe.
    calibrated = _MockPhone(_Profile({"k": _Entry(offset=(3, 4))}))
    assert run_session_calibration_probe(calibrated, "通用") is False
    assert calibrated.taps == []
