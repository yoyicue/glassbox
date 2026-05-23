"""Recovery state machines for returning the iOS Settings crawler to root.

Owns back/search/system-search recovery sequencing. Concrete actions and scene
predicates are injected through ``SettingsRecoveryActions`` to avoid coupling
the recovery state machine to crawler runtime globals.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from typing import Any

from glassbox.action.semantics import action_verdict
from glassbox.ios.recovery import dismiss_system_search

ActionIntent = Callable[..., AbstractContextManager[Any]]


def _record_action_verdict(phone, result: Any) -> bool:
    verdict = action_verdict(result)
    with suppress(Exception):
        phone._ios_settings_last_action_verdict = verdict
    return verdict.accepted


def _last_semantic_action_rejected(phone) -> bool:
    verdict = getattr(phone, "_ios_settings_last_action_verdict", None)
    status = getattr(verdict, "status", None)
    return bool(
        verdict is not None
        and getattr(verdict, "accepted", True) is False
        and status not in {None, "legacy_no_result", "transport_only", "transport_failed"}
    )


@dataclass(frozen=True)
class SettingsRecoveryActions:
    action_intent: ActionIntent
    is_settings_root: Callable[[Any], bool]
    scene_is_settings_root: Callable[[Any], bool]
    scene_kind: Callable[..., str]
    scene_looks_like_settings_detail: Callable[[Any], bool]
    is_safe_top_left_back_fallback_scene: Callable[..., bool]
    is_settings_search_scene: Callable[[Any], bool]
    return_state_signature: Callable[..., tuple[str, tuple[str, ...]]]
    open_app_from_springboard: Callable[..., bool]
    root_title: Any
    settle_settings_root_or_exit_search: Callable[..., bool]
    return_from_settings_search_state: Callable[[Any, Any], bool]
    return_from_system_search_state: Callable[[Any, Any], bool]
    return_from_blocked_settings_state: Callable[[Any, Any], bool]
    return_from_settings_detail_state: Callable[[Any, Any], bool]
    return_from_unknown_settings_state: Callable[[Any, Any], bool]
    exit_settings_search_if_needed: Callable[[Any], bool]
    dismiss_settings_search: Callable[[Any, Any], bool]
    press_ios_back_shortcut: Callable[[Any], bool]
    tap_visible_root_result_from_search: Callable[[Any, Any], bool]
    tap_settings_tab_from_search: Callable[..., bool]
    tap_visible_settings_root_result_from_system_search: Callable[[Any, Any], bool]
    tap_visible_back: Callable[[Any, Any], bool]
    meaningful_return_progress: Callable[..., bool]
    tap_top_left_back_fallback: Callable[[Any], bool]
    try_memory_return_to_settings_root: Callable[[Any, Any], bool]
    looks_like_settings_search_results: Callable[[Any], bool]
    settings_search_has_bottom_chrome: Callable[[Any], bool]


class SettingsRootUnreachable(RuntimeError):
    """Raised when the Settings root cannot be re-grounded after all fallbacks.

    A distinct (catchable) type so callers — e.g. missing-page search recovery —
    can skip one section instead of aborting the whole crawl. Back navigation is
    intermittent on AssistiveTouch, so a single return failure is recoverable."""


def return_to_settings_root(phone, actions: SettingsRecoveryActions) -> None:
    last_state: tuple[str, tuple[str, ...]] | None = None
    repeated_state_count = 0

    for retry_index in range(12):
        scene = phone.perceive()
        kind = actions.scene_kind(scene, phone=phone)
        if kind == "settings_root" or actions.scene_is_settings_root(scene):
            return

        state = actions.return_state_signature(scene, phone=phone)
        if state == last_state:
            repeated_state_count += 1
        else:
            repeated_state_count = 0
            last_state = state

        with actions.action_intent(
            phone,
            "return_to_settings_root.retry",
            retry_index=retry_index + 1,
            scene_kind=kind,
            repeated_state_count=repeated_state_count,
        ):
            if kind in {"settings_search_home", "settings_search_results"} or actions.is_settings_search_scene(scene):
                did_action = actions.return_from_settings_search_state(phone, scene)
            elif kind == "system_search":
                did_action = actions.return_from_system_search_state(phone, scene)
            elif kind == "settings_blocked_safety":
                did_action = actions.return_from_blocked_settings_state(phone, scene)
            elif (
                kind == "settings_detail"
                or actions.scene_looks_like_settings_detail(scene)
                or actions.is_safe_top_left_back_fallback_scene(scene, phone=phone)
            ):
                did_action = actions.return_from_settings_detail_state(phone, scene)
            elif kind in {"springboard", "app_library", "springboard_or_app_library"}:
                with actions.action_intent(
                    phone,
                    "foreground.open_settings_from_springboard",
                    labels=actions.root_title,
                    scene_kind=kind,
                ):
                    did_action = actions.open_app_from_springboard(phone, actions.root_title, max_pages=8)
            else:
                did_action = actions.return_from_unknown_settings_state(phone, scene)

        if not did_action:
            break
        if actions.settle_settings_root_or_exit_search(phone):
            return
        if repeated_state_count >= 2:
            current = phone.perceive()
            if actions.return_state_signature(current, phone=phone) == state:
                break

    if actions.is_settings_root(phone):
        return
    # Raise a distinct, catchable type (not a bare assert) so callers can choose
    # to skip one section and keep the coverage gathered so far, instead of the
    # whole crawl aborting on intermittent back-navigation. (Deliberately no
    # extra aggressive fallback here — a semantically-rejected back action, e.g.
    # a permission dialog, is a real stop, not something to hammer past.)
    raise SettingsRootUnreachable("failed to return to the Settings root page")


def settle_settings_root_or_exit_search(
    phone,
    actions: SettingsRecoveryActions,
    *,
    delay: float = 1.0,
    try_exit_search: bool = True,
) -> bool:
    time.sleep(delay)
    phone.invalidate_perceive_cache()
    if actions.is_settings_root(phone):
        return True
    if not try_exit_search:
        return False
    return actions.exit_settings_search_if_needed(phone)


def return_from_settings_search_state(phone, scene, actions: SettingsRecoveryActions) -> bool:
    if actions.dismiss_settings_search(phone, scene):
        if actions.settle_settings_root_or_exit_search(phone, try_exit_search=False):
            return True
        scene = phone.perceive()
    if actions.is_settings_search_scene(scene):
        if actions.press_ios_back_shortcut(phone):
            if actions.settle_settings_root_or_exit_search(phone, try_exit_search=False):
                return True
            scene = phone.perceive()
            if not actions.is_settings_search_scene(scene):
                return True
        elif _last_semantic_action_rejected(phone):
            return False
        if actions.tap_visible_root_result_from_search(phone, scene):
            return True
        return bool(actions.tap_settings_tab_from_search(phone, scene, allow_fallback=True))
    return True


def return_from_system_search_state(phone, scene, actions: SettingsRecoveryActions) -> bool:
    if actions.tap_visible_settings_root_result_from_system_search(phone, scene):
        return True
    return dismiss_system_search(
        phone,
        scene,
        action_context=lambda name, **metadata: actions.action_intent(phone, name, **metadata),
        fallback_back=lambda: actions.press_ios_back_shortcut(phone),
    )


def return_from_settings_detail_state(phone, scene, actions: SettingsRecoveryActions) -> bool:
    before = scene
    if actions.tap_visible_back(phone, scene):
        return True
    if actions.press_ios_back_shortcut(phone):
        if actions.settle_settings_root_or_exit_search(phone):
            return True
        scene = phone.perceive()
        if actions.meaningful_return_progress(before, scene, phone=phone):
            return True
    elif _last_semantic_action_rejected(phone):
        return False
    if hasattr(phone, "back_gesture"):
        with actions.action_intent(phone, "return.detail.back_gesture"):
            result = phone.back_gesture()
        if not _record_action_verdict(phone, result):
            return False
        if actions.settle_settings_root_or_exit_search(phone):
            return True
        scene = phone.perceive()
        if actions.meaningful_return_progress(before, scene, phone=phone):
            return True
    if actions.is_safe_top_left_back_fallback_scene(scene, phone=phone):
        return actions.tap_top_left_back_fallback(phone)
    return False


def return_from_blocked_settings_state(phone, scene, actions: SettingsRecoveryActions) -> bool:
    before = scene
    if actions.tap_visible_back(phone, scene):
        return True
    if actions.press_ios_back_shortcut(phone):
        if actions.settle_settings_root_or_exit_search(phone):
            return True
        scene = phone.perceive()
        if actions.meaningful_return_progress(before, scene, phone=phone):
            return True
    elif _last_semantic_action_rejected(phone):
        return False
    if hasattr(phone, "back_gesture"):
        with actions.action_intent(phone, "return.blocked.back_gesture"):
            result = phone.back_gesture()
        if not _record_action_verdict(phone, result):
            return False
        if actions.settle_settings_root_or_exit_search(phone):
            return True
        scene = phone.perceive()
        if actions.meaningful_return_progress(before, scene, phone=phone):
            return True
    return False


def return_from_unknown_settings_state(phone, scene, actions: SettingsRecoveryActions) -> bool:
    before = scene
    if actions.try_memory_return_to_settings_root(phone, scene):
        if actions.settle_settings_root_or_exit_search(phone):
            return True
        scene = phone.perceive()
        if actions.meaningful_return_progress(before, scene, phone=phone):
            return True
    if actions.press_ios_back_shortcut(phone):
        if actions.settle_settings_root_or_exit_search(phone):
            return True
        scene = phone.perceive()
        if actions.meaningful_return_progress(before, scene, phone=phone):
            return True
    elif _last_semantic_action_rejected(phone):
        return False
    if hasattr(phone, "back_gesture"):
        with actions.action_intent(phone, "return.unknown.back_gesture"):
            result = phone.back_gesture()
        return _record_action_verdict(phone, result)
    return False


def exit_settings_search_if_needed(phone, actions: SettingsRecoveryActions) -> bool:
    scene = phone.perceive()
    if not actions.is_settings_search_scene(scene):
        return False
    if (
        actions.looks_like_settings_search_results(scene)
        and not actions.settings_search_has_bottom_chrome(scene)
        and actions.dismiss_settings_search(phone, scene)
    ):
        time.sleep(1.0)
        phone.invalidate_perceive_cache()
        if actions.is_settings_root(phone):
            return True
        scene = phone.perceive()
    if not actions.tap_settings_tab_from_search(phone, scene, allow_fallback=False):
        return False
    time.sleep(1.0)
    phone.invalidate_perceive_cache()
    return actions.is_settings_root(phone)
