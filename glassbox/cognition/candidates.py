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


def ocr_tap_candidates(scene: Any) -> list[TapCandidate]:
    """Baseline strategy: tap-candidates from OCR + Layer-2 heuristic typing."""
    out: list[TapCandidate] = []
    for el in scene.elements:
        if el.type not in _OCR_TAPPABLE_TYPES:
            continue
        label = (el.text or "").strip()
        if not label:
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
