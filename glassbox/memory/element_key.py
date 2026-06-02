"""glassbox/memory/element_key.py — stable per-element identity + merge.

An element needs an id that survives across visits to a screen, so the UTG can
say "the login button, last seen at box X". See docs/design/screen_memory.md §4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from glassbox.cognition.base import Box
from glassbox.cognition.text_match import norm_text
from glassbox.memory.schema import RememberedElement

if TYPE_CHECKING:
    from glassbox.cognition.base import UIElement

_BOX_EMA_ALPHA = 0.4          # weight of the newest observation in box smoothing
_GRID_COLS = 6
_GRID_ROW_PX = 160            # ~one grid row band per 160 px of height
_CANONICAL_TEXT_INTENT_SOURCES = frozenset({
    "springboard_lexicon",
    "settings_root_lexicon",
})


def is_volatile(el: UIElement) -> bool:
    """Whether an element's content/position is unreliable as a memory anchor.

    List rows churn (scrolling, changing content) — their text must not enter a
    screen signature and their box is only a weak position prior.
    """
    return el.type == "list_item"


def element_key(
    el: UIElement,
    frame_size: tuple[int, int],
    *,
    use_canonical_text_intents: bool = True,
) -> str:
    """A node-stable id for an element.

    Closed-set canonicalizers may override noisy OCR text with an intent label;
    otherwise the identity follows design §4: own text > whitebox asset >
    accessibility id > coarse grid cell.
    """
    t = _text_identity(el, use_canonical_text_intents=use_canonical_text_intents)
    if t:
        return f"text:{t}"
    wb = el.whitebox_hint
    if wb is not None and wb.asset_match:
        return f"asset:{wb.asset_match}"
    if wb is not None and wb.accessibility_id:
        return f"aid:{wb.accessibility_id}"
    w, h = frame_size
    cx, cy = el.box.center
    col = min(_GRID_COLS - 1, max(0, cx * _GRID_COLS // max(1, w)))
    rows = max(1, h // _GRID_ROW_PX)
    row = min(rows - 1, max(0, cy * rows // max(1, h)))
    return f"{el.type}@{col},{row}"


def _text_identity(el: UIElement, *, use_canonical_text_intents: bool = True) -> str:
    intent = norm_text(el.intent_label)
    if use_canonical_text_intents and intent and el.intent_source in _CANONICAL_TEXT_INTENT_SOURCES:
        return intent
    return norm_text(el.text)


def to_remembered(el: UIElement, key: str) -> RememberedElement:
    """A fresh single-observation RememberedElement from a perceived element."""
    return RememberedElement(
        key=key, box=el.box, type=el.type, text=el.text,
        intent_label=el.intent_label, whitebox_hint=el.whitebox_hint,
        volatile=is_volatile(el), visit_count=1,
    )


def merge_element(
    old: RememberedElement,
    new: RememberedElement,
    *,
    clear_missing_intent: bool = False,
    clear_missing_whitebox: bool = False,
) -> RememberedElement:
    """Merge a fresh observation into a remembered element with the same key.

    Stable elements get an EMA-smoothed box; volatile elements take the latest
    box as-is (averaging a moving list row is meaningless).
    """
    if old.volatile or new.volatile:
        box = new.box
    else:
        a = _BOX_EMA_ALPHA
        box = Box(
            x=round(a * new.box.x + (1 - a) * old.box.x),
            y=round(a * new.box.y + (1 - a) * old.box.y),
            w=round(a * new.box.w + (1 - a) * old.box.w),
            h=round(a * new.box.h + (1 - a) * old.box.h),
        )
    return RememberedElement(
        key=old.key,
        box=box,
        type=new.type or old.type,
        text=new.text or old.text,
        intent_label=(
            new.intent_label
            if (clear_missing_intent or new.intent_label is not None)
            else old.intent_label
        ),
        whitebox_hint=(
            new.whitebox_hint
            if (clear_missing_whitebox or new.whitebox_hint is not None)
            else old.whitebox_hint
        ),
        volatile=old.volatile or new.volatile,
        visit_count=old.visit_count + 1,
        present=True,
        missing_count=0,
        last_seen_visit=max(old.last_seen_visit, new.last_seen_visit),
    )
