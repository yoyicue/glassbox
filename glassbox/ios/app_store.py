"""App Store-specific OCR/layout annotations."""

from __future__ import annotations

import re

from glassbox.cognition.base import Scene, UIElement
from glassbox.ios._scene_common import scene_size_with_default

APP_STORE_INTENT_SOURCE = "appstore_chrome"
APP_STORE_SEARCH_LABEL = "Search"
_APP_STORE_TAB_LABELS = {"today", "games", "apps", "arcade"}


def annotate_app_store_search_intents(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> int:
    """Attach a Search intent to the unlabeled App Store search icon.

    The iPad App Store top chrome can expose the search glyph as an unlabeled
    image after layout segmentation. OCR-only baseline sees only the text tabs,
    so this annotation is intentionally gated on the platform classifier's
    App Store chrome evidence plus a top-band icon candidate.
    """
    if "appstore_chrome" not in set(scene.classification_evidence or ()):
        return 0
    w, h = scene_size_with_default(scene, viewport_size, default_size=(448, 973))
    if not _has_top_app_store_tabs(scene, viewport_size=(w, h)):
        return 0
    candidate = _top_search_icon_candidate(scene, viewport_size=(w, h))
    if candidate is None:
        return 0
    if candidate.intent_label and candidate.intent_source != APP_STORE_INTENT_SOURCE:
        return 0

    evidence = list(candidate.type_evidence)
    evidence.extend([APP_STORE_INTENT_SOURCE, "appstore_search_icon"])
    candidate.intent_label = APP_STORE_SEARCH_LABEL
    candidate.intent_source = APP_STORE_INTENT_SOURCE
    candidate.intent_confidence = 0.86
    candidate.type = "button"
    candidate.type_confidence = max(candidate.type_confidence or 0.0, 0.82)
    candidate.type_source = APP_STORE_INTENT_SOURCE
    candidate.type_evidence = list(dict.fromkeys(evidence))
    if "tap" not in candidate.suggested_actions:
        candidate.suggested_actions = [*candidate.suggested_actions, "tap"]
    return 1


def _has_top_app_store_tabs(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    w, h = viewport_size
    hits: set[str] = set()
    for element in scene.elements:
        text = _compact(element.text or "")
        if text not in _APP_STORE_TAB_LABELS:
            continue
        cx, cy = element.box.center
        if h * 0.04 <= cy <= h * 0.18 and w * 0.20 <= cx <= w * 0.82:
            hits.add(text)
    return len(hits) >= 3


def _top_search_icon_candidate(scene: Scene, *, viewport_size: tuple[int, int]) -> UIElement | None:
    w, h = viewport_size
    candidates: list[UIElement] = []
    for element in scene.elements:
        if (element.text or "").strip():
            continue
        if element.type not in {"image", "button"}:
            continue
        cx, cy = element.box.center
        if not (h * 0.04 <= cy <= h * 0.18):
            continue
        if not (w * 0.35 <= cx <= w * 0.60):
            continue
        if not (w * 0.010 <= element.box.w <= w * 0.080):
            continue
        if not (h * 0.010 <= element.box.h <= h * 0.080):
            continue
        candidates.append(element)
    if not candidates:
        return None
    return min(candidates, key=lambda element: (abs(element.box.center[1] - h * 0.09), element.box.x))


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


__all__ = [
    "APP_STORE_INTENT_SOURCE",
    "APP_STORE_SEARCH_LABEL",
    "annotate_app_store_search_intents",
]
