from __future__ import annotations

import json

import pytest

from glassbox.action import StuckLoopDetector, StuckSample
from glassbox.memory.schema import ScreenSignature


def _sig(texts: list[str], hist: dict[str, int] | None = None, phash: str = "") -> str:
    """A JSON-encoded ScreenSignature exactly as the orchestrator emits one."""
    sig = ScreenSignature(
        stable_texts=sorted(texts),
        type_histogram=hist or {"text": len(texts)},
        phash=phash,
    )
    return json.dumps(sig.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


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


def test_stuck_detector_tolerates_ocr_jitter_in_structural_signature():
    """CUQ-1.6: a genuinely-stuck screen with minor OCR jitter (one token
    flickering, a spinner counted as an element) must still accumulate to the
    threshold instead of resetting the counter on every wobble."""
    detector = StuckLoopDetector(threshold=3)
    base = ["设置", "无线局域网", "蓝牙", "通用", "电池", "隐私与安全性", "辅助功能"]
    samples = [
        StuckSample(_sig(base), "no progress"),
        StuckSample(_sig([*base, "2:03"], {"text": len(base) + 1}), "no progress"),  # clock token
        StuckSample(_sig(base, {"text": len(base), "image": 1}), "no progress"),  # spinner element
    ]

    decisions = [detector.observe(s) for s in samples]

    # Exact-equality would have reset to count=1 on each wobble and never fired;
    # similarity-based matching keeps the run alive to the threshold.
    assert [d.should_recover for d in decisions] == [False, False, True]
    assert decisions[-1].count == 3


def test_stuck_detector_rearm_lets_dead_end_fire_again():
    """CUQ-0.9: re-arm after a failed recovery so a persistent dead-end fires
    again once it survives another `threshold` samples, instead of disarming
    forever after one no-op recovery."""
    detector = StuckLoopDetector(threshold=2)
    sample = StuckSample("sig-a", "no progress")

    assert detector.observe(sample).should_recover is False
    assert detector.observe(sample).should_recover is True  # fires, anchor marked
    assert detector.observe(sample).should_recover is False  # stays disarmed...
    detector.rearm()  # ...recovery failed -> re-arm
    assert detector.observe(sample).should_recover is False  # counter reset, 1
    assert detector.observe(sample).should_recover is True  # fires again


def test_stuck_detector_still_resets_on_genuinely_different_screen():
    """Dissimilar screens must NOT be collapsed into one stuck run."""
    detector = StuckLoopDetector(threshold=2)
    page_a = _sig(["设置", "无线局域网", "蓝牙", "通用"])
    page_b = _sig(["相机", "照片", "录屏", "实况文本", "保留正常曝光"])

    assert detector.observe(StuckSample(page_a, "no progress")).should_recover is False
    assert detector.observe(StuckSample(page_b, "no progress")).should_recover is False
    assert detector.observe(StuckSample(page_b, "no progress")).should_recover is True
