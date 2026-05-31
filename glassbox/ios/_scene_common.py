"""Shared scene-classification helpers for iOS-family platforms."""

from __future__ import annotations

from collections.abc import Iterable

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.text_match import (
    confusion_compact,
    fuzzy_ratio,
    text_contains,
    texts_match,
)


def scene_size_with_default(
    scene: Scene,
    viewport_size: tuple[int, int] | None,
    *,
    default_size: tuple[int, int],
) -> tuple[int, int]:
    if viewport_size is not None:
        return viewport_size
    if scene.viewport_size is not None:
        return scene.viewport_size
    default_width, default_height = default_size
    width = max((element.box.x2 for element in scene.elements), default=default_width)
    height = max((element.box.y2 for element in scene.elements), default=default_height)
    return max(width, default_width), max(height, default_height)


def element_text(element: UIElement) -> str:
    return (element.text or "").strip()


def matches_label(text: str, labels: Iterable[str], *, fuzzy: float = 0.78) -> bool:
    norm = confusion_compact(text)
    for label in labels:
        if texts_match(text, label) or text_contains(text, label):
            return True
        if fuzzy_ratio(text, label) >= fuzzy:
            return True
        if norm and norm == confusion_compact(label):
            return True
    return False


def marker_hits(joined_casefold: str, markers: Iterable[str]) -> int:
    hits = 0
    seen: set[str] = set()
    for marker in markers:
        compact = marker.casefold()
        if compact and compact not in seen and compact in joined_casefold:
            seen.add(compact)
            hits += 1
    return hits
