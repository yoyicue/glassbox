"""App-policy discovery for pipeline-A hooks.

App policies are not core seams, but they can contribute cognition-stage facts
such as app-specific scene classification. Runtime asks this registry for the
active bundle id instead of hard-coding app knowledge in the assembler.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from importlib.metadata import entry_points
from typing import Protocol

from glassbox.cognition.contracts import SceneClassification
from glassbox.ios.scene import classify_ios_scene


class AppSceneClassifier(Protocol):
    def classify(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> SceneClassification | None: ...


@dataclass(frozen=True)
class AppPolicyRegistration:
    bundle_id: str
    scene_classifier: AppSceneClassifier | None = None
    crawl_policy: str | None = None
    priority: int = 0


class IOSSettingsSceneClassifier:
    def classify(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> SceneClassification | None:
        return replace(
            classify_ios_scene(scene, viewport_size=viewport_size).to_scene_classification(),
            source="app",
        )


def ios_settings_app_policy() -> AppPolicyRegistration:
    return AppPolicyRegistration(
        bundle_id="com.apple.Preferences",
        scene_classifier=IOSSettingsSceneClassifier(),
        crawl_policy="ios_settings",
        priority=0,
    )


class AppPolicyRegistry:
    def __init__(
        self,
        registrations: Iterable[AppPolicyRegistration] | None = None,
        *,
        load_entry_points: bool = True,
    ):
        self._by_bundle: dict[str, AppPolicyRegistration] = {}
        self._entry_points_loaded = not load_entry_points
        for registration in registrations or ():
            self.register(registration)

    def register(self, registration: AppPolicyRegistration) -> None:
        current = self._by_bundle.get(registration.bundle_id)
        if current is None or registration.priority >= current.priority:
            self._by_bundle[registration.bundle_id] = registration

    def scene_classifier_for(self, bundle_id: str | None) -> AppSceneClassifier | None:
        registration = self.registration_for(bundle_id)
        return None if registration is None else registration.scene_classifier

    def crawl_policy_for(self, bundle_id: str | None) -> str | None:
        registration = self.registration_for(bundle_id)
        return None if registration is None else registration.crawl_policy

    def registration_for(self, bundle_id: str | None) -> AppPolicyRegistration | None:
        if not bundle_id:
            return None
        self._load_entry_points_once()
        return self._by_bundle.get(bundle_id)

    def _load_entry_points_once(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        try:
            selected = entry_points(group="glassbox.app_policies")
        except TypeError:
            selected = entry_points().get("glassbox.app_policies", ())
        for entry_point in selected:
            loaded = entry_point.load()
            for registration in _coerce_registrations(loaded):
                self.register(registration)


def _coerce_registrations(value) -> Iterable[AppPolicyRegistration]:
    if isinstance(value, AppPolicyRegistration):
        return (value,)
    if callable(value):
        return _coerce_registrations(value())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        registrations: list[AppPolicyRegistration] = []
        for item in value:
            if not isinstance(item, AppPolicyRegistration):
                raise TypeError(f"app-policy entry point returned unsupported item: {item!r}")
            registrations.append(item)
        return tuple(registrations)
    raise TypeError(f"app-policy entry point returned unsupported value: {value!r}")


DEFAULT_APP_POLICY_REGISTRY = AppPolicyRegistry(
    registrations=(ios_settings_app_policy(),),
)


__all__ = [
    "DEFAULT_APP_POLICY_REGISTRY",
    "AppPolicyRegistration",
    "AppPolicyRegistry",
    "AppSceneClassifier",
    "IOSSettingsSceneClassifier",
    "ios_settings_app_policy",
]
