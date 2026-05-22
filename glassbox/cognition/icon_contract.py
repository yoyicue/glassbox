"""Adapters for the public IconDetector boundary contract."""

from __future__ import annotations

from dataclasses import dataclass

from glassbox.cognition.base import Box
from glassbox.cognition.contracts import IconBox, TextRegion
from glassbox.cognition.icon_detect import detect_icons
from glassbox.perception.source import Frame


@dataclass
class IconDetectFunctionAdapter:
    backend: str = "classical"
    confidence: float = 1.0

    def detect(
        self,
        image: Frame,
        *,
        text_regions: list[TextRegion] | None = None,
        roi: Box | None = None,
    ) -> tuple[IconBox, ...]:
        frame, offset = _frame_for_roi(image, roi)
        text_boxes = _text_boxes_for_roi(text_regions or [], roi)
        regions = detect_icons(
            frame.img,
            text_boxes=tuple(text_boxes),
            backend=self.backend,
        )
        return tuple(
            IconBox(
                box=_offset_box(Box(x=x, y=y, w=w, h=h), offset),
                label=None,
                confidence=self.confidence,
            )
            for x, y, w, h in (region.box for region in regions)
        )


def _frame_for_roi(frame: Frame, roi: Box | None) -> tuple[Frame, tuple[int, int]]:
    if roi is None:
        return frame, (0, 0)
    x = max(0, int(roi.x))
    y = max(0, int(roi.y))
    w = max(0, int(roi.w))
    h = max(0, int(roi.h))
    y2 = min(frame.img.shape[0], y + h)
    x2 = min(frame.img.shape[1], x + w)
    return Frame(img=frame.img[y:y2, x:x2], ts=frame.ts, context=frame.context), (x, y)


def _text_boxes_for_roi(regions: list[TextRegion], roi: Box | None) -> list[tuple[int, int, int, int]]:
    boxes = []
    for region in regions:
        box = region.box
        if roi is None:
            boxes.append((box.x, box.y, box.w, box.h))
            continue
        ix1 = max(box.x, roi.x)
        iy1 = max(box.y, roi.y)
        ix2 = min(box.x2, roi.x2)
        iy2 = min(box.y2, roi.y2)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        boxes.append((ix1 - roi.x, iy1 - roi.y, ix2 - ix1, iy2 - iy1))
    return boxes


def _offset_box(box: Box, offset: tuple[int, int]) -> Box:
    dx, dy = offset
    return Box(x=box.x + dx, y=box.y + dy, w=box.w, h=box.h)


__all__ = ["IconDetectFunctionAdapter"]
