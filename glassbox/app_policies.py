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

from glassbox.cognition.contracts import SceneClassification, SceneClassificationPrior


class AppSceneClassifier(Protocol):
    def classify(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None: ...


@dataclass(frozen=True)
class AppPolicyRegistration:
    bundle_id: str
    scene_classifier: AppSceneClassifier | None = None
    crawl_policy: str | None = None
    platform: str | None = None
    priority: int = 0


class IOSSettingsSceneClassifier:
    def classify(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None:
        # Lazy, matching IPadOSSettingsSceneClassifier below: the registry
        # module stays platform-neutral at import time (snapshot item 5).
        from glassbox.ios.scene import classify_ios_scene

        return replace(
            classify_ios_scene(scene, viewport_size=viewport_size, prior=prior).to_scene_classification(),
            source="app",
        )


class IPadOSSettingsSceneClassifier:
    def classify(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None:
        from glassbox.ipados.scene import classify_ipados_scene

        return replace(
            classify_ipados_scene(scene, viewport_size=viewport_size, prior=prior).to_scene_classification(),
            source="app",
        )


def ios_settings_app_policy() -> AppPolicyRegistration:
    return AppPolicyRegistration(
        bundle_id="com.apple.Preferences",
        scene_classifier=IOSSettingsSceneClassifier(),
        crawl_policy="ios_settings",
        platform="ios",
        priority=0,
    )


def ipados_settings_app_policy() -> AppPolicyRegistration:
    return AppPolicyRegistration(
        bundle_id="com.apple.Preferences",
        scene_classifier=IPadOSSettingsSceneClassifier(),
        crawl_policy="ipados_settings",
        platform="ipados",
        priority=10,
    )


class AppPolicyRegistry:
    def __init__(
        self,
        registrations: Iterable[AppPolicyRegistration] | None = None,
        *,
        load_entry_points: bool = True,
    ):
        self._by_bundle: dict[tuple[str, str | None], AppPolicyRegistration] = {}
        self._entry_points_loaded = not load_entry_points
        for registration in registrations or ():
            self.register(registration)

    def register(self, registration: AppPolicyRegistration) -> None:
        key = (registration.bundle_id, _platform_key(registration.platform))
        current = self._by_bundle.get(key)
        if current is None or registration.priority >= current.priority:
            self._by_bundle[key] = registration

    def scene_classifier_for(
        self,
        bundle_id: str | None,
        *,
        platform: str | None = None,
    ) -> AppSceneClassifier | None:
        registration = self.registration_for(bundle_id, platform=platform)
        return None if registration is None else registration.scene_classifier

    def crawl_policy_for(
        self,
        bundle_id: str | None,
        *,
        platform: str | None = None,
    ) -> str | None:
        registration = self.registration_for(bundle_id, platform=platform)
        return None if registration is None else registration.crawl_policy

    def registration_for(
        self,
        bundle_id: str | None,
        *,
        platform: str | None = None,
    ) -> AppPolicyRegistration | None:
        if not bundle_id:
            return None
        self._load_entry_points_once()
        platform_key = _platform_key(platform)
        keys = [(bundle_id, platform_key), (bundle_id, None)]
        if platform_key is None:
            keys.append((bundle_id, "ios"))
        for key in keys:
            registration = self._by_bundle.get(key)
            if registration is not None:
                return registration
        return None

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


def _platform_key(platform: str | None) -> str | None:
    key = str(platform or "").strip().lower().replace("-", "_")
    return key or None


DEFAULT_APP_POLICY_REGISTRY = AppPolicyRegistry(
    registrations=(ios_settings_app_policy(), ipados_settings_app_policy()),
)


__all__ = [
    "DEFAULT_APP_POLICY_REGISTRY",
    "AppPolicyRegistration",
    "AppPolicyRegistry",
    "AppSceneClassifier",
    "IOSSettingsSceneClassifier",
    "IPadOSSettingsSceneClassifier",
    "ios_settings_app_policy",
    "ipados_settings_app_policy",
]
