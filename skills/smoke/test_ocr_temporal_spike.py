from __future__ import annotations

import numpy as np

from glassbox.cognition import Box, UIElement
from glassbox.perception.source import Frame
from skills.regression.ocr_temporal_spike import collect_ocr_temporal_spike


class _Phone:
    def __init__(self):
        self.action_context = type(
            "Context",
            (),
            {"suppress_ocr_temporal_voting": False, "ocr_temporal_voting_opt_in": True},
        )()
        self.index = 0
        self.last_frame = None

    def invalidate_perceive_cache(self):
        pass

    def perceive(self, *, scope=None):
        _ = scope
        frame = self.snapshot()
        self.last_frame = frame
        return type(
            "SceneLike",
            (),
            {
                "elements": self._recognize_elements(frame),
            },
        )()

    def snapshot(self, *, scope=None):
        _ = scope
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        if self.index >= 2:
            image[0, 0, 0] = 1
        self.index += 1
        return Frame(img=image, ts=float(self.index))

    def _recognize_elements(self, _frame):
        text = "待机显示" if self.index == 2 else "待机見示"
        return [
            UIElement(type="text", box=Box(x=10, y=10, w=80, h=20), text=text, confidence=0.9),
        ]


def test_ocr_temporal_spike_reports_distinct_frames_and_variants():
    phone = _Phone()

    report = collect_ocr_temporal_spike(phone, samples=3, spacing_ms=0)

    assert report.samples_used == 3
    assert report.distinct_frames == 2
    assert report.duplicate_frames == 1
    assert report.variant_clusters == 1
    assert report.variant_region_rate == 1.0
    assert phone.action_context.suppress_ocr_temporal_voting is False
    assert phone.action_context.ocr_temporal_voting_opt_in is True
