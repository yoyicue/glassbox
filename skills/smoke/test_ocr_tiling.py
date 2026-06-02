from __future__ import annotations

import pytest

from glassbox.cognition import Box, TextRegion
from glassbox.cognition.ocr_tiling import merge_text_regions


def _region(text: str, x: int, y: int, *, confidence: float = 0.8) -> TextRegion:
    return TextRegion(
        text=text,
        box=Box(x=x, y=y, w=40, h=18),
        confidence=confidence,
    )


@pytest.mark.smoke
def test_merge_text_regions_deduplicates_same_text_seam_duplicate():
    regions = [
        _region("Wi-Fi", 10, 20, confidence=0.6),
        _region("Wi-Fi", 12, 21, confidence=0.9),
        _region("Bluetooth", 10, 70, confidence=0.7),
    ]

    merged = merge_text_regions(regions, iou_threshold=0.55)

    assert [region.text for region in merged] == ["Wi-Fi", "Bluetooth"]
    assert next(region for region in merged if region.text == "Wi-Fi").confidence == pytest.approx(0.9)


@pytest.mark.smoke
def test_merge_text_regions_does_not_drop_label_for_overlapping_empty_text():
    regions = [
        _region("", 10, 20, confidence=0.95),
        _region("Wi-Fi", 10, 20, confidence=0.6),
    ]

    merged = merge_text_regions(regions, iou_threshold=0.55)

    assert "Wi-Fi" in [region.text for region in merged]
