"""glassbox/cognition/heuristic.py — Layer 2 heuristic UIElement typing

Upgrades `type='text'` elements from OCR into concrete types — button /
input / list_item / tab_bar_item / nav_back / image, etc. — based on
**position + surrounding pixel features**, and fills in default
`suggested_actions`.

The rule set corresponds to the heuristic recipe table in
docs/design/gui_understanding.md §4.

Design:
- each rule is a stateless function, easy to test and add/remove
- tried by priority, the first match wins
- without frame_img (pure OCR mode), only position + text rules run
- with frame_img, color / edge / surrounding sampling is added and rules are more accurate
- **no semantic recognition in Layer 2** ("this is a login button" is a Layer 3 / VLM job)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from glassbox.cognition.base import ActionType, ElementType, Scene, UIElement

if TYPE_CHECKING:
    pass


# ─── rule result ──────────────────────────────────────────────────────
@dataclass
class TypeGuess:
    """Output of one rule."""

    type: ElementType
    actions: list[ActionType]
    confidence: float                # 0..1
    source: str | None = None


RuleFn = Callable[..., "TypeGuess | None"]


# ─── individual rule set ─────────────────────────────────────────────
def rule_status_bar(el: UIElement, frame_w: int, frame_h: int, **_) -> TypeGuess | None:
    """iOS status bar content (time / Wi-Fi / battery / signal / Dynamic Island text).

    The status bar is fixed at ~50pt at the top of the screen (iPhone X+),
    roughly 5% of frame_h. These are not interaction targets during a
    walkthrough, but if not marked explicitly they get mistakenly grabbed by
    the nav_back / short-text rules.

    Match conditions (any one suffices):
      - y2 within the top 6% of the screen + text is a time format (HH:MM)
      - y2 within the top 6% + text contains % (battery level)
      - y2 within the top 6% + text is a known signal abbreviation ('5G' / '4G' / 'LTE' / '3G')

    Deliberately does not use "on the right" as a fallback, to avoid clashing
    with the X close button at the top of a modal.
    """
    in_top_strip = el.box.y2 < frame_h * 0.06
    if not in_top_strip:
        return None
    text = (el.text or "").strip()
    # time: 00:15, 23:56, 23:56C (a trailing moon emoji gets concatenated in by OCR)
    is_time = (
        len(text) >= 4
        and text[:2].isdigit() and text[2] == ":" and text[3:5].isdigit()
    )
    has_percent = "%" in text
    has_signal = text.upper() in {"5G", "4G", "LTE", "3G"}
    if is_time or has_percent or has_signal:
        return TypeGuess(type="status_bar", actions=[], confidence=0.95)
    return None


def rule_nav_back(el: UIElement, frame_w: int, frame_h: int, **_) -> TypeGuess | None:
    """top-left short text / arrow glyph → back button

    The iOS nav bar is usually within status (44pt) + nav (44pt) ≈ the top 0-100pt.
    """
    in_top_bar = el.box.y2 < 110
    on_left = el.box.x < frame_w * 0.15
    text = (el.text or "").strip()
    is_back_glyph = text in ("<", "‹", "←", "Back", "返回", "取消", "Cancel", "Close", "×", "✕", "X")
    short_label = 0 < len(text) <= 5
    if in_top_bar and on_left and (is_back_glyph or short_label):
        return TypeGuess(type="nav_back", actions=["tap"], confidence=0.85 if is_back_glyph else 0.7)
    return None


def rule_modal_dismiss(el: UIElement, frame_w: int, frame_h: int, **_) -> TypeGuess | None:
    """top-right X / close → modal sheet close button (classified as nav_back)"""
    in_top = el.box.y2 < 110
    on_right = el.box.x > frame_w * 0.85
    text = (el.text or "").strip()
    is_close = text in ("×", "✕", "X", "x", "✗", "关闭", "Close")
    if in_top and on_right and is_close:
        return TypeGuess(type="nav_back", actions=["tap"], confidence=0.9)
    return None


def rule_tab_bar_item(el: UIElement, frame_w: int, frame_h: int, scene: Scene = None, **_) -> TypeGuess | None:
    """49-83pt-tall horizontal bar at the bottom + evenly spaced short text labels → tab bar item

    Needs scene context: there must be ≥2 neighbors within the same y band to count as a tab bar (avoids misjudging isolated text).
    """
    # bottom ~120pt (tab bar 49-83 + home indicator 34)
    in_tab_bar_zone = el.box.y > frame_h - 120
    short = 0 < len(el.text or "") <= 8
    if not (in_tab_bar_zone and short):
        return None
    if scene is not None:
        neighbors = [
            e for e in scene.elements
            if e is not el
            and abs(e.box.y - el.box.y) < 20
            and 0 < len(e.text or "") <= 8
        ]
        if len(neighbors) < 2:
            return None
    return TypeGuess(type="tab_bar_item", actions=["tap"], confidence=0.75)


def rule_list_item(el: UIElement, frame_w: int, frame_h: int, scene: Scene = None, **_) -> TypeGuess | None:
    """Horizontal layout: left-aligned text + chevron/arrow on the right → ListItem."""
    # text in the left 1/3 (wide-screen padding 16-20pt)
    on_left = el.box.x < frame_w * 0.4
    # a chevron character on the right within the same y range
    if scene is None:
        return None
    chevron_neighbor = any(
        (e.text or "").strip() in (">", "›", "→", "❯", "˃")
        and abs(e.box.y - el.box.y) < 30
        and e.box.x > frame_w * 0.85
        for e in scene.elements
    )
    if on_left and chevron_neighbor:
        return TypeGuess(type="list_item", actions=["tap"], confidence=0.7)
    return None


def rule_button_by_colored_fill(
    el: UIElement,
    frame_w: int,
    frame_h: int,
    frame_img=None,
    **_,
) -> TypeGuess | None:
    """Sample around the text: strong contrast between **inner fill vs outer background** → primary button.

    Needs frame_img (np.ndarray). Returns None when there is no img, letting other rules take over.
    """
    if frame_img is None:
        return None
    try:
        import numpy as np
    except ImportError:
        return None

    # at least 17pt tall (iOS HIG minimum tappable button)
    if el.box.h < 17:
        return None

    h_img, w_img = frame_img.shape[:2]
    bx, by, bw, bh = el.box.x, el.box.y, el.box.w, el.box.h

    # safe cropping
    pad = max(6, bh // 3)
    inner_y1, inner_y2 = max(0, by), min(h_img, by + bh)
    inner_x1, inner_x2 = max(0, bx), min(w_img, bx + bw)
    if inner_x2 - inner_x1 < 4 or inner_y2 - inner_y1 < 4:
        return None

    inner = frame_img[inner_y1:inner_y2, inner_x1:inner_x2]
    inner_mean = inner.reshape(-1, inner.shape[2]).mean(axis=0)

    # outer-ring sampling (a pad-pixel ring outside the box)
    outer_x1, outer_x2 = max(0, bx - pad), min(w_img, bx + bw + pad)
    outer_y1, outer_y2 = max(0, by - pad), min(h_img, by + bh + pad)
    outer = frame_img[outer_y1:outer_y2, outer_x1:outer_x2].copy()
    # zero out the inner region to avoid contamination
    outer[
        max(0, by - outer_y1): max(0, by - outer_y1) + bh,
        max(0, bx - outer_x1): max(0, bx - outer_x1) + bw,
    ] = 0
    nonzero = outer[outer.sum(axis=2) > 0]
    if len(nonzero) < 10:
        return None
    outer_mean = nonzero.mean(axis=0)

    # color difference (L1 distance), threshold 50/channel → most likely has a filled background
    diff = float(np.abs(inner_mean - outer_mean).mean())
    if diff > 40:
        # further check: button text is usually centered and short
        return TypeGuess(type="button", actions=["tap"], confidence=min(0.95, 0.6 + diff / 200))
    return None


def rule_text_input_placeholder(el: UIElement, frame_w: int, frame_h: int, **_) -> TypeGuess | None:
    """Placeholder feature: short phrases like '请输入...' / 'Enter ...' / 'Search...'."""
    text = (el.text or "").strip()
    placeholder_hints = [
        "请输入", "请填写", "请选择", "搜索", "请",
        "Enter ", "Search", "Type ", "Email", "Password", "Username",
    ]
    # box is fairly wide (an input field is usually > 50% of screen width)
    if any(text.startswith(h) for h in placeholder_hints) and el.box.w > frame_w * 0.4:
        return TypeGuess(type="input", actions=["tap", "type"], confidence=0.65)
    return None


# ─── default rule set + order ───────────────────────────────────────
DEFAULT_RULES: list[RuleFn] = [
    rule_status_bar,              # strip the status bar first, so nav_back doesn't grab it
    rule_modal_dismiss,           # high confidence + strong positional constraint
    rule_nav_back,
    rule_tab_bar_item,
    rule_list_item,
    rule_button_by_colored_fill,  # needs frame_img
    rule_text_input_placeholder,
]


# ─── main typer class ────────────────────────────────────────────────
class HeuristicTyper:
    """Run the rule set to upgrade all type='text' elements in a Scene.

    Usage:
        typer = HeuristicTyper()
        typer.upgrade(scene, frame_img=frame.img)
        # now the types in scene.elements have been differentiated

    Custom rules can be injected:
        typer = HeuristicTyper(rules=[my_rule, *DEFAULT_RULES])
    """

    def __init__(
        self,
        rules: list[RuleFn] | None = None,
        frame_size: tuple[int, int] | None = None,
        synthesize_modal_close: bool = True,
    ):
        """rules: the rule set (default DEFAULT_RULES).
        frame_size: (frame_w, frame_h). The basis for positional decision
                    thresholds. Pass it explicitly for unit tests / walkthroughs
                    without frame_img; otherwise it is inferred from
                    frame_img.shape; failing that, it falls back to iPhone 13 Pro.
        synthesize_modal_close: after upgrade() runs visual detection, if there
                    is a standard iOS gray-circle close button at the top-right
                    (which OCR cannot see) → synthesize a type='nav_back'
                    text='×' element. Default True.
        """
        self.rules = rules if rules is not None else DEFAULT_RULES
        self.default_frame_size = frame_size
        self.synthesize_modal_close = synthesize_modal_close

    def upgrade(self, scene: Scene, frame_img=None) -> Scene:
        """Upgrade scene.elements in place. Returns the same scene (for chaining)."""
        # estimate the frame size: img > explicit default > inferred from boxes
        if frame_img is not None:
            try:
                frame_h, frame_w = frame_img.shape[:2]
            except (AttributeError, ValueError):
                frame_w, frame_h = self.default_frame_size or self._guess_frame_size(scene)
        elif self.default_frame_size is not None:
            frame_w, frame_h = self.default_frame_size
        elif scene.viewport_size is not None:
            frame_w, frame_h = scene.viewport_size
        else:
            frame_w, frame_h = self._guess_frame_size(scene)

        for el in scene.elements:
            if el.type != "text":
                continue   # leave already-classified elements alone
            guess = self._first_match(el, frame_w, frame_h, scene=scene, frame_img=frame_img)
            if guess is not None:
                el.type = guess.type
                el.suggested_actions = guess.actions
                el.type_confidence = guess.confidence
                el.type_source = guess.source
            else:
                # leave it as type='text', but add a default action
                if not el.suggested_actions:
                    el.suggested_actions = ["tap"]

        # —— post-pass: synthesize icon buttons that OCR cannot see ——
        if self.synthesize_modal_close and frame_img is not None:
            self._maybe_synthesize_modal_close(scene, frame_img)

        return scene

    @staticmethod
    def _maybe_synthesize_modal_close(scene: Scene, frame_img) -> None:
        """top-right gray-circle close → synthesize a type='nav_back' text='×' element.

        For X buttons OCR cannot see (pure graphics), use visual detection as a
        fallback so walkthrough scripts can hit them with
        `tap_text('×')` / `tap_button('×')` / `find_by_intent('关闭')`.
        Does not synthesize again if an element already covers that bbox (IoU > 0.3).
        """
        from glassbox.cognition.base import Box, UIElement
        from glassbox.cognition.icon_detect import find_modal_close

        bbox = find_modal_close(frame_img)
        if bbox is None:
            return
        x, y, w, h = bbox
        # overlaps an existing element → don't synthesize (avoids duplicates)
        for el in scene.elements:
            eb = el.box
            iw = max(0, min(x + w, eb.x2) - max(x, eb.x))
            ih = max(0, min(y + h, eb.y2) - max(y, eb.y))
            inter = iw * ih
            if inter > 0:
                au = w * h
                bu = eb.w * eb.h
                if inter / (au + bu - inter) > 0.3:
                    return

        next_id = max((e.element_id for e in scene.elements), default=-1) + 1
        scene.elements.append(UIElement(
            type="nav_back",
            box=Box(x=x, y=y, w=w, h=h),
            text="×",
            confidence=0.7,
            suggested_actions=["tap"],
            element_id=next_id,
        ))

    def _first_match(
        self,
        el: UIElement,
        frame_w: int,
        frame_h: int,
        *,
        scene: Scene,
        frame_img,
    ) -> TypeGuess | None:
        for rule in self.rules:
            guess = rule(
                el,
                frame_w=frame_w,
                frame_h=frame_h,
                scene=scene,
                frame_img=frame_img,
            )
            if guess is not None:
                if guess.source is None:
                    guess.source = rule.__name__
                return guess
        return None

    @staticmethod
    def _guess_frame_size(scene: Scene) -> tuple[int, int]:
        """Without frame_img, infer the frame size from all element boxes."""
        if not scene.elements:
            return 1170, 2532   # iPhone 13 Pro default
        max_x = max(e.box.x2 for e in scene.elements)
        max_y = max(e.box.y2 for e in scene.elements)
        # leave 10% padding
        return int(max_x * 1.1), int(max_y * 1.1)


# ─── query convenience functions (used by Phone) ────────────────────
def find_by_type(elements: list[UIElement], element_type: ElementType) -> list[UIElement]:
    """Return all elements of the given type."""
    return [e for e in elements if e.type == element_type]


def find_button(elements: list[UIElement], text: str, *, fuzzy_ratio: float = 0.8) -> UIElement | None:
    """Find the button (already typed) with the given text. Minus glyph aliases are normalized automatically."""
    from glassbox.cognition.text_match import (
        fuzzy_ratio as _fr,
    )
    from glassbox.cognition.text_match import (
        text_contains,
        texts_match,
    )

    buttons = [e for e in elements if e.type == "button" and e.text]
    # exact
    for b in buttons:
        if texts_match(b.text, text):
            return b
    # substring
    for b in buttons:
        if text_contains(b.text, text):
            return b
    # fuzzy
    best, best_r = None, fuzzy_ratio
    for b in buttons:
        r = _fr(text, b.text)
        if r >= best_r:
            best, best_r = b, r
    return best


def find_by_intent(
    elements: list[UIElement],
    intent: str,
    *,
    fuzzy_ratio: float = 0.7,
) -> UIElement | None:
    """Find an element by the intent_label populated by Layer 3.

    Match order: exact → substring → substring (swapped) → fuzzy ratio.
    intent is shorter than text, so the fuzzy threshold is relaxed to 0.7.
    """
    from glassbox.cognition.text_match import (
        fuzzy_ratio as _fr,
    )
    from glassbox.cognition.text_match import (
        text_contains,
        texts_match,
    )

    candidates = [e for e in elements if e.intent_label]
    # exact
    for e in candidates:
        if texts_match(e.intent_label, intent):
            return e
    # substring (intent is short, may be a substring of intent_label)
    for e in candidates:
        if text_contains(e.intent_label, intent) or text_contains(intent, e.intent_label):
            return e
    # fuzzy
    best, best_r = None, fuzzy_ratio
    for e in candidates:
        r = _fr(intent, e.intent_label)
        if r >= best_r:
            best, best_r = e, r
    return best
