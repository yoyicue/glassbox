"""Scroll and settle helpers for the iOS Settings crawler.

Owns HID wheel/swipe fallback and scroll progress classification. Callers
inject action-intent tracing and scene text extraction so this module can stay
independent of crawler globals.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any

from glassbox.cognition.text_match import confusion_compact
from glassbox.ios.crawl import call_scroll_method as _call_scroll_method_generic
from glassbox.ios.crawl import classify_scroll_attempt as _classify_scroll_attempt
from glassbox.ios.crawl import phone_supports as _phone_supports
from glassbox.ios.progress import is_time_text as _is_time_text
from glassbox.ios.progress import screen_signature as _screen_signature
from skills.regression.ios_settings.config import DEFAULT_SETTINGS_WHEEL_TICKS_PER_SWIPE

ActionIntent = Callable[..., AbstractContextManager[Any]]
TextsFn = Callable[[Any], Iterable[str]]


def wait_screen_settled(
    phone,
    *,
    attempts: int = 5,
    settle_s: float = 0.35,
    diff_thresh: float = 0.012,
) -> None:
    """Wait for page transition animation to settle before reading geometry."""
    from glassbox.perception.stable import frame_diff_ratio

    snapshot = getattr(phone, "snapshot", None)
    if not callable(snapshot):
        return
    try:
        prev = snapshot()
        for _ in range(attempts):
            time.sleep(settle_s)
            cur = snapshot()
            if prev.img.shape == cur.img.shape and frame_diff_ratio(prev.img, cur.img) < diff_thresh:
                return
            prev = cur
    except Exception:
        return


def root_coverage_perceive(phone, depth: int):
    """Use settle and root-only OCR voting before crawler candidate selection."""
    wait_screen_settled(phone)
    if depth == 0 and hasattr(phone, "perceive_voted"):
        return phone.perceive_voted(2, text_normalizer=confusion_compact)
    return phone.perceive()


def wheel_scroll_down(
    phone,
    *,
    action_intent: ActionIntent,
    ticks: int | None = None,
) -> None:
    if _phone_supports(phone, "scroll_wheel") and hasattr(phone, "wheel_scroll_down"):
        with action_intent(phone, "scroll.down.wheel"):
            _settings_wheel_scroll(phone, settings_wheel_ticks_per_swipe() if ticks is None else ticks)
    elif _is_ipad_target(phone):
        with action_intent(phone, "scroll.down.ipad_unavailable"):
            return
    else:
        with action_intent(phone, "scroll.down.swipe_fallback"):
            phone.swipe_up()


def scroll_down_confirmed(
    phone,
    before_texts: Iterable[str],
    *,
    action_intent: ActionIntent,
    texts: TextsFn,
    depth: int = 0,
    idx: int = 0,
):
    """Scroll once, settle, then classify progress/stuck/overshoot."""
    ticks = settings_wheel_ticks_per_swipe()
    wheel_scroll_down(phone, action_intent=action_intent, ticks=ticks)
    time.sleep(0.8)
    phone.invalidate_perceive_cache()
    after = phone.perceive()
    outcome = _classify_scene_scroll_outcome(_classify_scroll_attempt(before_texts, texts(after)).outcome, after)
    print(f"[scroll] depth={depth} idx={idx} ticks={ticks} probe={outcome}", flush=True)
    if outcome != "stuck":
        return outcome, after
    if _is_ipad_target(phone):
        return "stuck", after
    retry_ticks = settings_wheel_ticks_per_swipe()
    wheel_scroll_down(phone, action_intent=action_intent, ticks=retry_ticks)
    time.sleep(0.8)
    phone.invalidate_perceive_cache()
    retry = phone.perceive()
    retry_result = _classify_scroll_attempt(before_texts, texts(after), retry_texts=texts(retry))
    retry_outcome = _classify_scene_scroll_outcome(retry_result.retry_outcome or retry_result.outcome, retry)
    print(f"[scroll] depth={depth} idx={idx} ticks={retry_ticks} retry={retry_outcome}", flush=True)
    if retry_outcome == "stuck":
        return "stuck", retry
    if retry_outcome in {"overshoot", "top-overshoot"}:
        return retry_outcome, retry
    return "progress", retry


def wheel_scroll_up(phone, *, action_intent: ActionIntent) -> None:
    if _phone_supports(phone, "scroll_wheel") and hasattr(phone, "wheel_scroll_up"):
        with action_intent(phone, "scroll.up.wheel"):
            _settings_wheel_scroll(phone, -settings_wheel_ticks_per_swipe())
    elif _is_ipad_target(phone):
        with action_intent(phone, "scroll.up.ipad_unavailable"):
            return
    else:
        with action_intent(phone, "scroll.up.swipe_fallback"):
            phone.swipe_down()


def call_wheel_scroll(method, ticks: int) -> None:
    _call_scroll_method_generic(method, ticks)


def _settings_wheel_scroll(phone, ticks: int) -> None:
    focus = _settings_wheel_focus(phone)
    if focus is not None and hasattr(phone, "scroll_wheel"):
        phone.scroll_wheel(ticks, focus_x=focus[0], focus_y=focus[1], focus_click=True)
        return
    method = phone.wheel_scroll_down if ticks > 0 else phone.wheel_scroll_up
    call_wheel_scroll(method, abs(ticks))


def _settings_wheel_focus(phone) -> tuple[int, int] | None:
    if not _is_ipad_target(phone):
        return None
    try:
        w, h = phone.viewport_size()
    except Exception:
        return None
    return int(w * 0.23), int(h * 0.55)


def _is_ipad_target(phone) -> bool:
    model = str(getattr(getattr(phone, "device_geometry", None), "model", "") or "")
    return model.lower().replace("-", "_").startswith("ipad")


def settings_wheel_ticks_per_swipe() -> int:
    raw = (
        os.getenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE")
        or os.getenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL")
        or str(DEFAULT_SETTINGS_WHEEL_TICKS_PER_SWIPE)
    )
    try:
        ticks = int(raw)
    except (TypeError, ValueError):
        ticks = DEFAULT_SETTINGS_WHEEL_TICKS_PER_SWIPE
    return max(1, ticks)


def _classify_scene_scroll_outcome(outcome: str, scene) -> str:
    if outcome == "overshoot" and _has_top_status_bar_time(scene):
        return "top-overshoot"
    return outcome


def _has_top_status_bar_time(scene) -> bool:
    for element in getattr(scene, "elements", []) or []:
        text = str(getattr(element, "text", "") or "").strip()
        box = getattr(element, "box", None)
        if not text or box is None or not _is_time_text(text):
            continue
        try:
            if box.center[1] < 100:
                return True
        except Exception:
            continue
    return False


def scroll_to_vertical_boundary(
    phone,
    *,
    direction: str,
    action_intent: ActionIntent,
    texts: TextsFn,
    max_steps: int = 5,
) -> None:
    seen: set[tuple[str, ...]] = set()
    for _ in range(max_steps):
        scene = phone.perceive()
        sig = _screen_signature(texts(scene))
        if sig in seen:
            return
        seen.add(sig)
        print(f"[scroll] boundary {direction}", flush=True)
        if direction == "up":
            wheel_scroll_up(phone, action_intent=action_intent)
        elif direction == "down":
            wheel_scroll_down(phone, action_intent=action_intent)
        else:
            raise ValueError(f"unknown vertical boundary direction: {direction!r}")
        time.sleep(0.8)
        phone.invalidate_perceive_cache()
        next_sig = _screen_signature(texts(phone.perceive()))
        if next_sig == sig:
            return
