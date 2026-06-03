"""glassbox/cognition/candidates.py — tap-candidate selection strategies.

Two ways to decide which on-screen elements are worth tapping to explore an
app, used head-to-head by the cold-start A/B experiment:

- `ocr_tap_candidates`        — the OCR + Layer-2 heuristic baseline: anything
  typed as actionable (or plain text, since iOS list rows often stay `text`).
- `annotation_tap_candidates` — the cold-start VLM strategy: exactly the
  elements the VLM marked `navigable`.

Both return a uniform `TapCandidate` list so an explorer can swap strategies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from glassbox.cognition.text_match import looks_like_status_bar_clock

# Layer-2 element types worth a tap when exploring. `text` is included because
# iOS list rows frequently survive heuristic typing as plain text; status bar /
# images / back buttons / modal chrome are not forward-navigation candidates.
_OCR_TAPPABLE_TYPES = {"button", "list_item", "tab_bar_item", "input", "switch", "text"}


@dataclass
class TapCandidate:
    """One element an explorer may tap, normalized across strategies."""

    label: str
    center: tuple[int, int]
    source: str            # "ocr" | "vlm_anchored" | "vlm_only"
    role: str = ""
    page_id: str | None = None


def ocr_tap_candidates(scene: Any) -> list[TapCandidate]:
    """Baseline strategy: tap-candidates from OCR + Layer-2 heuristic typing."""
    out: list[TapCandidate] = []
    viewport = getattr(scene, "viewport_size", None)
    h = int(viewport[1]) if viewport else 0
    for el in scene.elements:
        if el.type not in _OCR_TAPPABLE_TYPES:
            continue
        label = (el.text or "").strip()
        if not label:
            continue
        # CUQ-2.7 (+audit fix): a status-bar clock (often OCR'd as plain 'text')
        # is never a navigation target. Skip a clock-shaped label ONLY when it
        # sits in the top status-bar band — a body time row (alarm "5:00 AM",
        # track duration "3:45", calendar "12:30 PM") is shape-identical and must
        # stay tappable. When the viewport height is unknown, fall back to the
        # text-only skip (CUQ-2.7's original behavior).
        if looks_like_status_bar_clock(label) and (h <= 0 or el.box.center[1] <= h * 0.06):
            continue
        out.append(TapCandidate(label=label, center=el.box.center, source="ocr"))
    return out


def annotation_tap_candidates(annotation: Any) -> list[TapCandidate]:
    """Cold-start strategy: tap-candidates are the VLM's `navigable` elements.

    Anchored elements carry a precise OCR-box center; VLM-only elements (no-text
    icons OCR cannot see) carry the VLM's rougher predicted center.
    """
    out: list[TapCandidate] = []
    for e in annotation.elements:
        if not e.navigable:
            continue
        out.append(TapCandidate(
            label=e.label,
            center=e.center,
            source="vlm_anchored" if e.anchored else "vlm_only",
            role=e.role,
        ))
    return out
