"""Adapters for the public OCR boundary contract."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from glassbox.cognition.base import Box, UIElement
from glassbox.cognition.contracts import TextRegion
from glassbox.perception.source import Frame


def text_region_to_element(region: TextRegion, *, element_id: int) -> UIElement:
    return UIElement(
        type="text",
        box=region.box,
        text=region.text,
        confidence=region.confidence,
        suggested_actions=[],
        element_id=element_id,
    )


def text_regions_to_elements(regions: Iterable[TextRegion]) -> list[UIElement]:
    return [
        text_region_to_element(region, element_id=i)
        for i, region in enumerate(regions)
    ]


def ocr_results_to_elements(results: Iterable[TextRegion | UIElement]) -> list[UIElement]:
    elements: list[UIElement] = []
    for i, item in enumerate(results):
        if isinstance(item, UIElement):
            elements.append(item)
        elif isinstance(item, TextRegion):
            elements.append(text_region_to_element(item, element_id=i))
        else:
            raise TypeError(f"OCR returned unsupported item: {item!r}")
    return elements


@dataclass
class LegacyUIElementOCRAdapter:
    """Adapt existing UIElement OCR engines to `recognize(Frame) -> TextRegion`."""

    inner: Any
    contract: str = "TextRegionOCR"

    def recognize(self, image: Frame, *, roi: Box | None = None) -> list[TextRegion]:
        frame, offset = _frame_for_roi(image, roi)
        elements = self.inner.recognize(frame.img)
        regions = []
        for item in elements:
            if isinstance(item, TextRegion):
                region = item
            else:
                region = TextRegion(
                    text=item.text or "",
                    box=item.box,
                    confidence=float(item.confidence),
                )
            if offset != (0, 0):
                region = _offset_region(region, offset)
            regions.append(region)
        return regions


def _frame_for_roi(frame: Frame, roi: Box | None) -> tuple[Frame, tuple[int, int]]:
    if roi is None:
        return frame, (0, 0)
    x = max(0, int(roi.x))
    y = max(0, int(roi.y))
    w = max(0, int(roi.w))
    h = max(0, int(roi.h))
    if w == 0 or h == 0:
        return Frame(img=frame.img[0:0, 0:0], ts=frame.ts, context=frame.context), (x, y)
    y2 = min(frame.img.shape[0], y + h)
    x2 = min(frame.img.shape[1], x + w)
    return Frame(img=frame.img[y:y2, x:x2], ts=frame.ts, context=frame.context), (x, y)


def _offset_region(region: TextRegion, offset: tuple[int, int]) -> TextRegion:
    dx, dy = offset
    box = region.box
    return TextRegion(
        text=region.text,
        box=Box(x=box.x + dx, y=box.y + dy, w=box.w, h=box.h),
        confidence=region.confidence,
    )


__all__ = [
    "LegacyUIElementOCRAdapter",
    "ocr_results_to_elements",
    "text_region_to_element",
    "text_regions_to_elements",
]
