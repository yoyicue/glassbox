"""Parse iOS Voice Control overlay markers from OCR output.

Voice Control's continuous overlay is rendered onto the HDMI frame. This module
keeps the first prototype narrow: consume ordinary OCR ``UIElement`` records and
return the overlay markers that can later be mapped back onto perceived controls.
It is opt-in and does not mutate the default perception pipeline.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from glassbox.cognition.base import Box, Scene, UIElement, WhiteboxHint

VoiceControlOverlayMode = Literal["item_numbers", "item_names", "numbered_grid"]
VoiceControlOverlayKind = Literal["item_number", "item_name", "grid_number"]

_LEADING_NOISE = "([{<|/\\!lI（［【"
_TRAILING_NOISE = ")]}>|/\\!lI）］】"
_TARGET_TYPE_PENALTY = {
    "image": 16.0,
    "status_bar": 1_000.0,
}


class VoiceControlOverlayMarker(BaseModel):
    """One visible Voice Control overlay badge."""

    kind: VoiceControlOverlayKind
    text: str
    box: Box
    confidence: float = Field(ge=0.0, le=1.0)
    source_element_id: int | None = None
    number: int | None = None
    accessibility_id: str

    @property
    def center(self) -> tuple[int, int]:
        return self.box.center


def parse_voice_control_overlay(
    elements: list[UIElement],
    *,
    mode: VoiceControlOverlayMode,
    frame_img: np.ndarray | None = None,
    max_number: int = 99,
) -> list[VoiceControlOverlayMarker]:
    """Return Voice Control overlay markers found in OCR elements.

    ``frame_img`` is optional. When supplied, candidate OCR boxes must sit on a
    dark Voice Control badge, which prevents ordinary UI text from being
    misclassified as an overlay label.
    """

    markers: list[VoiceControlOverlayMarker] = []
    for element in elements:
        text = _clean_text(element.text)
        if not text:
            continue
        if frame_img is not None and _looks_like_status_bar_text(element, frame_img):
            continue
        if (
            frame_img is not None
            and not _looks_like_overlay_badge(frame_img, element.box, mode=mode)
        ):
            continue
        if mode in {"item_numbers", "numbered_grid"}:
            number = _overlay_number_from_element(text, element.box, max_number=max_number)
            if number is None:
                continue
            kind: VoiceControlOverlayKind = (
                "grid_number" if mode == "numbered_grid" else "item_number"
            )
            markers.append(
                VoiceControlOverlayMarker(
                    kind=kind,
                    text=str(number),
                    number=number,
                    box=element.box,
                    confidence=element.confidence,
                    source_element_id=element.element_id,
                    accessibility_id=f"vc:{kind}:{number}",
                )
            )
        elif mode == "item_names" and _looks_like_overlay_name(text):
            normalized = _normalize_name(text)
            markers.append(
                VoiceControlOverlayMarker(
                    kind="item_name",
                    text=normalized,
                    box=element.box,
                    confidence=element.confidence,
                    source_element_id=element.element_id,
                    accessibility_id=f"vc:item-name:{_accessibility_slug(normalized)}",
                )
            )
    return sorted(markers, key=lambda marker: (marker.box.y, marker.box.x))


def apply_voice_control_overlay_hints(
    scene: Scene,
    markers: Sequence[VoiceControlOverlayMarker],
    *,
    include_names: bool = False,
    include_frame_local_numbers: bool = False,
    max_y_delta: int = 36,
    max_center_distance: int = 96,
    preserve_existing_accessibility_id: bool = True,
) -> Scene:
    """Attach Voice Control overlay identities to the nearest scene elements.

    The overlay OCR text itself is not the target. For row-style Settings UIs the
    badge can sit far to the left of the row label, so matching first uses a
    same-y-band score and falls back to center distance for compact controls.
    The mapping geometry is still experimental, so no overlay marker is written
    into ``WhiteboxHint.accessibility_id`` by default. Callers must explicitly
    enable experimental names or frame-local number/grid anchors. The pass is
    opt-in and mutates ``scene`` in place, mirroring ``apply_whitebox``.
    """

    marker_sources = {
        marker.source_element_id
        for marker in markers
        if marker.source_element_id is not None
    }
    claimed_targets: set[int] = set()
    for marker in sorted(markers, key=lambda item: item.confidence, reverse=True):
        if marker.kind == "item_name" and not include_names:
            continue
        if (
            marker.kind in {"item_number", "grid_number"}
            and not include_frame_local_numbers
        ):
            continue
        target = _best_overlay_target(
            scene.elements,
            marker,
            marker_sources=marker_sources,
            claimed_targets=claimed_targets,
            max_y_delta=max_y_delta,
            max_center_distance=max_center_distance,
        )
        if target is None:
            continue
        existing = target.whitebox_hint
        if (
            preserve_existing_accessibility_id
            and existing is not None
            and existing.accessibility_id
        ):
            claimed_targets.add(target.element_id)
            continue
        target.whitebox_hint = _overlay_whitebox_hint(existing, marker.accessibility_id)
        claimed_targets.add(target.element_id)
    return scene


def overlay_number(text: str | None, *, max_number: int = 99) -> int | None:
    """Extract a Voice Control badge number from OCR text.

    Vision sometimes reads the leading dark-badge edge as punctuation or ``1``:
    ``(20``, ``|27`` and ``120`` can all represent badge 20/27. The fallback that
    drops a leading ``1`` only applies when the full number is above
    ``max_number``.
    """

    cleaned = _clean_text(text)
    if not cleaned:
        return None
    if re.fullmatch(r"\d{1,3}", cleaned):
        value = int(cleaned)
        if 0 < value <= max_number:
            return value
        if cleaned.startswith("1") and len(cleaned) == 3:
            fallback = int(cleaned[1:])
            if 0 < fallback <= max_number:
                return fallback
        return None
    stripped = cleaned.strip(f"{_LEADING_NOISE}{_TRAILING_NOISE}")
    if re.fullmatch(r"\d{1,3}", stripped):
        value = int(stripped)
        if 0 < value <= max_number:
            return value
    return None


def _overlay_number_from_element(text: str, box: Box, *, max_number: int) -> int | None:
    number = overlay_number(text, max_number=max_number)
    cleaned = _clean_text(text)
    if (
        number == 99
        and cleaned == "99"
        and box.w <= 18
    ):
        # A real "9" badge can be read as two tightly overlapping 9 glyphs when
        # Vision sees both the dark badge edge and the digit. A genuine "99"
        # badge is wider in current iPad samples.
        return 9
    return number


def _clean_text(text: str | None) -> str:
    if text is None:
        return ""
    return unicodedata.normalize("NFKC", str(text)).strip()


def _looks_like_overlay_name(text: str) -> bool:
    if not (1 <= len(text) <= 40):
        return False
    if any(ch in text for ch in "\n\r\t"):
        return False
    if overlay_number(text) is not None:
        return False
    return any(ch.isalnum() for ch in text)


def _looks_like_status_bar_text(element: UIElement, frame_img: np.ndarray) -> bool:
    height = frame_img.shape[0]
    text = _clean_text(element.text)
    if element.box.y > max(80, int(height * 0.08)):
        return False
    return any(
        token in text
        for token in ("AM", "PM", "100%", "Thu", "Mon", "Tue", "Wed", "Fri", "Sat", "Sun")
    )


def _normalize_name(text: str) -> str:
    return " ".join(_clean_text(text).split())


def _accessibility_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "-", text.lower()).strip("-")
    return slug or "label"


def _best_overlay_target(
    elements: Sequence[UIElement],
    marker: VoiceControlOverlayMarker,
    *,
    marker_sources: set[int],
    claimed_targets: set[int],
    max_y_delta: int,
    max_center_distance: int,
) -> UIElement | None:
    scored: list[tuple[float, UIElement]] = []
    for element in elements:
        if element.element_id in marker_sources or element.element_id in claimed_targets:
            continue
        score = _overlay_target_score(
            marker,
            element,
            max_y_delta=max_y_delta,
            max_center_distance=max_center_distance,
        )
        if score is None:
            continue
        scored.append((score, element))
    if not scored:
        return None
    return min(scored, key=lambda item: item[0])[1]


def _overlay_target_score(
    marker: VoiceControlOverlayMarker,
    element: UIElement,
    *,
    max_y_delta: int,
    max_center_distance: int,
) -> float | None:
    if marker.kind == "item_name":
        return _item_name_target_score(marker, element, max_y_delta=max_y_delta)
    marker_center = marker.center
    element_center = element.box.center
    dx = abs(marker_center[0] - element_center[0])
    dy = abs(marker_center[1] - element_center[1])
    if dy <= max_y_delta:
        return (
            float(dy)
            + 0.1 * _horizontal_gap(marker.box, element.box)
            + _TARGET_TYPE_PENALTY.get(str(element.type), 0.0)
        )
    center_distance = (dx * dx + dy * dy) ** 0.5
    if center_distance <= max_center_distance:
        return center_distance + _TARGET_TYPE_PENALTY.get(str(element.type), 0.0)
    return None


def _item_name_target_score(
    marker: VoiceControlOverlayMarker,
    element: UIElement,
    *,
    max_y_delta: int,
) -> float | None:
    text_match = _name_text_matches(marker.text, element.text)
    if not text_match:
        return None
    vertical_gap = _item_name_vertical_gap(
        marker.box,
        element.box,
        max_y_delta=max_y_delta,
    )
    if vertical_gap is None:
        return None
    dx = abs(marker.center[0] - element.box.center[0])
    if dx > 180:
        return None
    return (
        float(vertical_gap)
        + 0.05 * dx
        + _TARGET_TYPE_PENALTY.get(str(element.type), 0.0)
        - 8.0
    )


def _item_name_vertical_gap(
    marker_box: Box,
    element_box: Box,
    *,
    max_y_delta: int,
) -> int | None:
    gaps: list[int] = []
    marker_above_gap = element_box.y - marker_box.y2
    marker_below_gap = marker_box.y - element_box.y2
    if -2 <= marker_above_gap <= max_y_delta:
        gaps.append(max(0, marker_above_gap))
    if -2 <= marker_below_gap <= max_y_delta:
        gaps.append(max(0, marker_below_gap))
    center_delta = abs(marker_box.center[1] - element_box.center[1])
    if center_delta <= max_y_delta:
        gaps.append(center_delta)
    if not gaps:
        return None
    return min(gaps)


def _name_text_matches(marker_text: str | None, target_text: str | None) -> bool:
    marker = _compact_label(marker_text)
    target = _compact_label(target_text)
    if not marker or not target:
        return False
    marker_variants = {marker}
    if len(marker) > 4:
        marker_variants.add(marker[1:])
    if any(value and (value in target or target in value) for value in marker_variants):
        return True
    marker_tokens = _label_tokens(marker_text)
    target_tokens = _label_tokens(target_text)
    if marker_tokens & target_tokens:
        return True
    return SequenceMatcher(None, marker, target).ratio() >= 0.82


def _compact_label(text: str | None) -> str:
    return re.sub(r"[^0-9a-z]+", "", _clean_text(text).lower())


def _label_tokens(text: str | None) -> set[str]:
    return {
        token
        for token in re.split(r"[^0-9a-z]+", _clean_text(text).lower())
        if len(token) > 2
    }


def _horizontal_gap(left: Box, right: Box) -> int:
    if left.x2 < right.x:
        return right.x - left.x2
    if right.x2 < left.x:
        return left.x - right.x2
    return 0


def _overlay_whitebox_hint(
    existing: WhiteboxHint | None,
    accessibility_id: str,
) -> WhiteboxHint:
    if existing is None:
        return WhiteboxHint(accessibility_id=accessibility_id)
    return existing.model_copy(update={"accessibility_id": accessibility_id})


def _looks_like_dark_badge(frame_img: np.ndarray, box: Box) -> bool:
    # Vision boxes are tight around glyphs; the dark Voice Control badge can sit
    # just outside the OCR box. Try a few pads so real badges are accepted while
    # ordinary dark text on a light Settings row stays below the dark-pixel ratio.
    for pad in (5, 10, 16):
        crop = _padded_crop(frame_img, box, pad=pad)
        if crop.size == 0:
            continue
        if crop.ndim == 3:
            luminance = crop.astype(np.float32).mean(axis=2)
        else:
            luminance = crop.astype(np.float32)
        dark_ratio = float((luminance < 120.0).mean())
        mean = float(luminance.mean())
        if dark_ratio >= 0.28 and mean < 190.0:
            return True
    return False


def _looks_like_overlay_badge(
    frame_img: np.ndarray,
    box: Box,
    *,
    mode: VoiceControlOverlayMode,
) -> bool:
    if _looks_like_dark_badge(frame_img, box):
        return True
    if mode != "numbered_grid":
        return False
    return _looks_like_light_grid_badge(frame_img, box)


def _looks_like_light_grid_badge(frame_img: np.ndarray, box: Box) -> bool:
    for pad in (5, 10):
        crop = _padded_crop(frame_img, box, pad=pad)
        if crop.size == 0:
            continue
        if crop.ndim == 3:
            luminance = crop.astype(np.float32).mean(axis=2)
        else:
            luminance = crop.astype(np.float32)
        dark_ratio = float((luminance < 120.0).mean())
        mean = float(luminance.mean())
        if dark_ratio >= 0.15 and mean < 205.0:
            return True
    return False


def _padded_crop(frame_img: np.ndarray, box: Box, *, pad: int) -> np.ndarray:
    height, width = frame_img.shape[:2]
    x1 = max(0, int(box.x) - pad)
    y1 = max(0, int(box.y) - pad)
    x2 = min(width, int(box.x2) + pad)
    y2 = min(height, int(box.y2) + pad)
    if x2 <= x1 or y2 <= y1:
        return frame_img[0:0, 0:0]
    return frame_img[y1:y2, x1:x2]


__all__ = [
    "VoiceControlOverlayKind",
    "VoiceControlOverlayMarker",
    "VoiceControlOverlayMode",
    "apply_voice_control_overlay_hints",
    "overlay_number",
    "parse_voice_control_overlay",
]
