from __future__ import annotations

import pytest

from glassbox.action import StuckLoopDetector, StuckSample


def test_stuck_detector_fires_once_at_threshold_for_same_signature_and_reason():
    detector = StuckLoopDetector(threshold=3)
    sample = StuckSample(screen_signature="sig-a", failure_reason="no scene progress")

    decisions = [detector.observe(sample) for _ in range(5)]

    assert [decision.should_recover for decision in decisions] == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert decisions[2].recovery == "recover_to_home_then_renavigate"


def test_stuck_detector_resets_when_signature_changes():
    detector = StuckLoopDetector(threshold=2)

    assert detector.observe(StuckSample("sig-a", "unknown")).should_recover is False
    assert detector.observe(StuckSample("sig-b", "unknown")).should_recover is False
    assert detector.observe(StuckSample("sig-b", "unknown")).should_recover is True


def test_stuck_detector_resets_when_failure_reason_changes():
    detector = StuckLoopDetector(threshold=2)

    assert detector.observe(StuckSample("sig-a", "unknown")).should_recover is False
    assert detector.observe(StuckSample("sig-a", "transport_failed")).should_recover is False
    assert detector.observe(StuckSample("sig-a", "transport_failed")).should_recover is True


def test_stuck_detector_observe_and_recover_invokes_callback_once():
    detector = StuckLoopDetector(threshold=2, recovery="home_anchor")
    calls = []

    detector.observe_and_recover(StuckSample("sig-a", "unknown"), lambda name, decision: calls.append((name, decision.count)) or True)
    detector.observe_and_recover(StuckSample("sig-a", "unknown"), lambda name, decision: calls.append((name, decision.count)) or True)
    detector.observe_and_recover(StuckSample("sig-a", "unknown"), lambda name, decision: calls.append((name, decision.count)) or True)

    assert calls == [("home_anchor", 2)]


def test_stuck_detector_reset_allows_same_pair_to_fire_again():
    detector = StuckLoopDetector(threshold=2)
    sample = StuckSample("sig-a", "unknown")

    assert detector.observe(sample).should_recover is False
    assert detector.observe(sample).should_recover is True
    detector.reset()

    assert detector.observe(sample).should_recover is False
    assert detector.observe(sample).should_recover is True


def test_stuck_detector_rejects_invalid_threshold():
    with pytest.raises(ValueError):
        StuckLoopDetector(threshold=0)
