"""Verifier registry for semantic action outcomes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from glassbox.verification.verifiers import (
    ForegroundAppMatchesVerifier,
    IOSAppSwitcherOpenedVerifier,
    IOSControlCenterOpenedVerifier,
    IOSHomeScreenVisibleVerifier,
    IOSNotificationCenterOpenedVerifier,
    NavigationBackVerifier,
    SceneProgressedVerifier,
    TapTargetEffectVerifier,
    TextInsertedVerifier,
    Verifier,
)


@dataclass(frozen=True)
class VerifierRegistration:
    verifier: Verifier
    handles_actions: tuple[str, ...]
    priority: int = 0


class VerifierRegistry:
    """Action/op keyed verifier registry.

    v1 intentionally verifies op-level effects. Intent-level verification is a
    later contract, but callers can override the verifier through action
    metadata when they have stronger domain knowledge.
    """

    def __init__(self, *, load_entry_points: bool = True):
        self._by_name: dict[str, Verifier] = {}
        self._by_action: dict[str, str] = {}
        self._action_priority: dict[str, int] = {}
        self._entry_points_loaded = not load_entry_points
        for registration in builtin_verifier_registrations():
            self.register_registration(registration)
        self._load_entry_points_once()

    def register(self, verifier: Verifier) -> None:
        self._by_name[verifier.name] = verifier

    def register_registration(self, registration: VerifierRegistration) -> None:
        self.register(registration.verifier)
        for action in registration.handles_actions:
            current_priority = self._action_priority.get(action)
            if current_priority is None or registration.priority >= current_priority:
                self.map_action(action, registration.verifier.name, priority=registration.priority)

    def map_action(self, action: str, verifier_name: str, *, priority: int = 0) -> None:
        if verifier_name not in self._by_name:
            raise KeyError(f"unknown verifier: {verifier_name}")
        self._by_action[action] = verifier_name
        self._action_priority[action] = priority

    def resolve(self, action: str, metadata: dict[str, Any] | None = None) -> Verifier:
        metadata = metadata or {}
        override = metadata.get("verifier")
        if override:
            return self._by_name[str(override)]
        policy_action = metadata.get("policy_action")
        if policy_action and str(policy_action) in self._by_action:
            return self._by_name[self._by_action[str(policy_action)]]
        return self._by_name[self._by_action.get(action, "scene_progressed")]

    def _load_entry_points_once(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        try:
            selected = entry_points(group="glassbox.verifiers")
        except TypeError:
            selected = entry_points().get("glassbox.verifiers", ())
        for entry_point in selected:
            loaded = entry_point.load()
            for registration in _coerce_registrations(loaded):
                self.register_registration(registration)


def _coerce_registrations(value) -> Iterable[VerifierRegistration]:
    if isinstance(value, VerifierRegistration):
        return (value,)
    if callable(value):
        return _coerce_registrations(value())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        registrations: list[VerifierRegistration] = []
        for item in value:
            if not isinstance(item, VerifierRegistration):
                raise TypeError(f"verifier entry point returned unsupported item: {item!r}")
            registrations.append(item)
        return tuple(registrations)
    raise TypeError(f"verifier entry point returned unsupported value: {value!r}")


def ios_control_center_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=IOSControlCenterOpenedVerifier(),
        handles_actions=("control_center",),
    )


def ios_notification_center_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=IOSNotificationCenterOpenedVerifier(),
        handles_actions=("notification_center",),
    )


def ios_app_switcher_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=IOSAppSwitcherOpenedVerifier(),
        handles_actions=("recents",),
    )


def ios_home_screen_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=IOSHomeScreenVisibleVerifier(),
        handles_actions=("home",),
    )


def text_inserted_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=TextInsertedVerifier(),
        handles_actions=("type",),
    )


def foreground_app_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=ForegroundAppMatchesVerifier(),
        handles_actions=("open_app",),
    )


def scene_progressed_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=SceneProgressedVerifier(),
        handles_actions=("scroll", "scroll_wheel", "swipe", "drag"),
    )


def navigation_back_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=NavigationBackVerifier(),
        handles_actions=("back", "back_gesture"),
    )


def tap_target_effect_verifier_registration() -> VerifierRegistration:
    return VerifierRegistration(
        verifier=TapTargetEffectVerifier(),
        handles_actions=("tap", "double_tap", "long_press"),
    )


def builtin_verifier_registrations() -> tuple[VerifierRegistration, ...]:
    return (
        ios_control_center_verifier_registration(),
        ios_notification_center_verifier_registration(),
        ios_app_switcher_verifier_registration(),
        ios_home_screen_verifier_registration(),
        text_inserted_verifier_registration(),
        foreground_app_verifier_registration(),
        scene_progressed_verifier_registration(),
        navigation_back_verifier_registration(),
        tap_target_effect_verifier_registration(),
    )


DEFAULT_REGISTRY = VerifierRegistry()
