"""Foreground/bootstrap helpers for starting iOS Settings crawler runs.

Owns only app foregrounding and "are we back at Settings root?" recovery
selection. It receives concrete taps, scene predicates, and app-opening helpers
through ``SettingsBootstrapActions`` so it can be tested without importing the
large compatibility facade.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

ActionIntent = Callable[..., AbstractContextManager[Any]]


@dataclass(frozen=True)
class SettingsBootstrapActions:
    action_intent: ActionIntent
    wait_settings_root: Callable[..., bool]
    is_settings_root: Callable[[Any], bool]
    scene_looks_like_settings_detail: Callable[[Any], bool]
    try_return_to_settings_root: Callable[[Any], bool]
    match_any: Callable[..., Any | None]
    harness_app_markers: Iterable[str]
    root_title: Any
    open_app_from_springboard: Callable[..., bool]
    ensure_settings_root: Callable[[Any], bool]
    is_settings_search_scene: Callable[[Any], bool]
    return_to_settings_root: Callable[[Any], None]
    scene_kind: Callable[..., str]
    tap_visible_settings_root_result_from_system_search: Callable[[Any, Any], bool]
    unavailable_error: Callable[[str], Exception]


def wait_settings_root(phone, actions: SettingsBootstrapActions, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if actions.is_settings_root(phone):
            return True
        time.sleep(0.5)
    return False


def open_settings_from_home_if_visible(phone, actions: SettingsBootstrapActions) -> None:
    """Keep Settings if already foregrounded, otherwise open it via SpringBoard."""
    if actions.wait_settings_root(phone):
        return

    scene = phone.perceive()
    if actions.scene_looks_like_settings_detail(scene) and actions.try_return_to_settings_root(phone):
        return
    if actions.match_any(scene.elements, actions.harness_app_markers, fuzzy=0.7) is not None:
        with actions.action_intent(phone, "foreground.open_settings_from_harness_app", labels=actions.root_title):
            opened = actions.open_app_from_springboard(phone, actions.root_title, max_pages=8)
        if opened and actions.ensure_settings_root(phone):
            return

    if (
        (actions.is_settings_search_scene(scene) or any(element.type == "nav_back" for element in scene.elements))
        and actions.try_return_to_settings_root(phone)
        and actions.is_settings_root(phone)
    ):
        return
    if (
        actions.scene_kind(scene, phone=phone) == "system_search"
        and actions.tap_visible_settings_root_result_from_system_search(phone, scene)
    ):
        time.sleep(1.2)
        phone.invalidate_perceive_cache()
        if actions.ensure_settings_root(phone):
            return

    with actions.action_intent(phone, "foreground.open_settings_from_springboard", labels=actions.root_title):
        opened = actions.open_app_from_springboard(phone, actions.root_title, max_pages=8)
    if opened and actions.ensure_settings_root(phone):
        return

    scene = phone.perceive()
    if (
        actions.scene_kind(scene, phone=phone) == "system_search"
        and actions.tap_visible_settings_root_result_from_system_search(phone, scene)
    ):
        time.sleep(1.2)
        phone.invalidate_perceive_cache()
        if actions.ensure_settings_root(phone):
            return
    if actions.scene_looks_like_settings_detail(scene) and actions.try_return_to_settings_root(phone):
        return

    raise actions.unavailable_error(
        "Settings root could not be foregrounded using glassbox SpringBoard scan"
    )


def ensure_settings_root(phone, actions: SettingsBootstrapActions) -> bool:
    if actions.wait_settings_root(phone, timeout=8.0):
        return True
    scene = phone.perceive()
    kind = actions.scene_kind(scene, phone=phone)
    if (
        kind in {
            "settings_search_home",
            "settings_search_results",
            "settings_detail",
            "settings_blocked_safety",
            "system_search",
            "unknown",
        }
        or actions.is_settings_search_scene(scene)
        or any(element.type == "nav_back" for element in scene.elements)
        or actions.scene_looks_like_settings_detail(scene)
    ):
        return actions.try_return_to_settings_root(phone)
    return False
