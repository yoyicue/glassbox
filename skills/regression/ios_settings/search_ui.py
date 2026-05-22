"""Settings Search UI actions shared by recovery and tests.

Owns small, concrete interactions inside the Settings Search tab. Callers
inject action-intent tracing so this module does not depend on crawler globals.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from glassbox.cognition import UIElement
from glassbox.ios.safe_area import IOSSafeArea
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

ActionIntent = Callable[..., AbstractContextManager[Any]]
ActionResultRecorder = Callable[[Any, Any], bool]


def _accepted(
    phone,
    result: Any,
    record_action_verdict: ActionResultRecorder | None,
) -> bool:
    if record_action_verdict is None:
        return True
    return record_action_verdict(phone, result)


def tap_settings_tab_from_search(
    phone,
    scene,
    *,
    action_intent: ActionIntent,
    allow_fallback: bool = True,
    record_action_verdict: ActionResultRecorder | None = None,
) -> bool:
    if not DEFAULT_SETTINGS_POLICY.is_settings_search_scene(scene):
        return False
    tab = DEFAULT_SETTINGS_POLICY.find_settings_tab_in_search(scene)
    if tab is not None:
        cx, cy = bottom_tab_hit_point(phone, tab)
        with action_intent(phone, "settings_search.tap_settings_tab", text=tab.text, x=cx, y=cy):
            result = phone.tap_xy(cx, cy)
        return _accepted(phone, result, record_action_verdict)
    if not allow_fallback:
        return False
    x, y = bottom_tab_hit_point(phone, fallback_x_fraction=0.25)
    with action_intent(phone, "settings_search.tap_settings_tab_fallback", x=x, y=y):
        result = phone.tap_xy(x, y)
    return _accepted(phone, result, record_action_verdict)


def bottom_tab_hit_point(
    phone,
    element: UIElement | None = None,
    *,
    fallback_x_fraction: float = 0.5,
) -> tuple[int, int]:
    try:
        w, h = phone._viewport_size()
    except Exception:
        w, h = 448, 973
    safe = IOSSafeArea.from_viewport((w, h))
    if element is not None:
        x, y = element.box.center
        return safe.bottom_hit_point(x=x, y=y, element_type=element.type)
    return safe.bottom_hit_point(fallback_x_fraction=fallback_x_fraction)
