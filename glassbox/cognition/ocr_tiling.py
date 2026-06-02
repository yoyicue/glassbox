"""ROI tiling helpers for OCR experiments.

The production default remains a single full-frame OCR pass. These helpers are
used only when the opt-in tiling pass is enabled.
"""

from __future__ import annotations

from statistics import median

from glassbox.cognition.base import Box
from glassbox.cognition.contracts import TextRegion
from glassbox.cognition.text_match import norm_text


def tile_boxes(
    width: int,
    height: int,
    *,
    rows: int,
    cols: int,
    overlap: float,
) -> list[Box]:
    rows = max(1, int(rows))
    cols = max(1, int(cols))
    overlap = min(0.8, max(0.0, float(overlap)))
    if width <= 0 or height <= 0:
        return []
    tile_w = float(width) / cols
    tile_h = float(height) / rows
    boxes: list[Box] = []
    for row in range(rows):
        for col in range(cols):
            x1 = col * tile_w
            y1 = row * tile_h
            x2 = (col + 1) * tile_w
            y2 = (row + 1) * tile_h
            if col > 0:
                x1 -= tile_w * overlap
            if col < cols - 1:
                x2 += tile_w * overlap
            if row > 0:
                y1 -= tile_h * overlap
            if row < rows - 1:
                y2 += tile_h * overlap
            x = max(0, round(x1))
            y = max(0, round(y1))
            x2_i = min(width, round(x2))
            y2_i = min(height, round(y2))
            if x2_i > x and y2_i > y:
                boxes.append(Box(x=x, y=y, w=x2_i - x, h=y2_i - y))
    return boxes


def merge_text_regions(
    regions: list[TextRegion],
    *,
    iou_threshold: float = 0.55,
) -> list[TextRegion]:
    """Deduplicate overlapping tile OCR regions and return reading order."""
    kept: list[TextRegion] = []
    for region in sorted(regions, key=lambda item: float(item.confidence), reverse=True):
        if any(_duplicate_region(region, existing, iou_threshold=iou_threshold) for existing in kept):
            continue
        kept.append(region)
    return _reading_order(kept)


def _duplicate_region(a: TextRegion, b: TextRegion, *, iou_threshold: float) -> bool:
    text_a = norm_text(a.text)
    text_b = norm_text(b.text)
    if not text_a or not text_b:
        return False
    if text_a != text_b:
        return False
    return _box_iou(a.box, b.box) >= iou_threshold


def _box_iou(a: Box, b: Box) -> float:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0, a.w) * max(0, a.h)
    area_b = max(0, b.w) * max(0, b.h)
    denom = area_a + area_b - inter
    return float(inter) / float(denom) if denom > 0 else 0.0


def _reading_order(regions: list[TextRegion]) -> list[TextRegion]:
    if not regions:
        return []
    heights = [max(1, region.box.h) for region in regions]
    band_h = max(1.0, float(median(heights)) * 0.75)
    return sorted(regions, key=lambda region: (round(region.box.center[1] / band_h), region.box.x))


__all__ = ["merge_text_regions", "tile_boxes"]
