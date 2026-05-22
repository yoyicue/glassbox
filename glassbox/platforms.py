"""Platform provider registry.

Platform is a composite boundary: one selected provider can contribute multiple
optional sub-capabilities such as safe-area geometry and SpringBoard control.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from glassbox.boundaries import Platform
from glassbox.config import AgentConfig

PlatformFactory = Callable[..., Platform]


@dataclass(frozen=True)
class PlatformRegistration:
    name: str
    factory: PlatformFactory
    priority: int = 0


class PlatformRegistry:
    def __init__(
        self,
        registrations: Iterable[PlatformRegistration] | None = None,
        *,
        load_entry_points: bool = True,
    ):
        self._by_name: dict[str, PlatformRegistration] = {}
        self._entry_points_loaded = not load_entry_points
        for registration in registrations or ():
            self.register(registration)

    def register(self, registration: PlatformRegistration) -> None:
        current = self._by_name.get(registration.name)
        if current is None or registration.priority >= current.priority:
            self._by_name[registration.name] = registration

    def names(self) -> tuple[str, ...]:
        self._load_entry_points_once()
        return tuple(sorted(self._by_name))

    def resolve(self, name: str) -> PlatformRegistration:
        self._load_entry_points_once()
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown platform {name!r}; registered={sorted(self._by_name)}") from exc

    def create(self, name: str, **kwargs) -> Platform:
        return self.resolve(name).factory(**kwargs)

    def _load_entry_points_once(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        try:
            selected = entry_points(group="glassbox.platforms")
        except TypeError:
            selected = entry_points().get("glassbox.platforms", ())
        for entry_point in selected:
            loaded = entry_point.load()
            for registration in _coerce_registrations(loaded):
                self.register(registration)


def _coerce_registrations(value) -> Iterable[PlatformRegistration]:
    if isinstance(value, PlatformRegistration):
        return (value,)
    if callable(value):
        return _coerce_registrations(value())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        registrations: list[PlatformRegistration] = []
        for item in value:
            if not isinstance(item, PlatformRegistration):
                raise TypeError(f"platform entry point returned unsupported item: {item!r}")
            registrations.append(item)
        return tuple(registrations)
    raise TypeError(f"platform entry point returned unsupported value: {value!r}")


def _make_ios_safe_area_provider():
    from glassbox.ios.safe_area import IOSSafeAreaProvider

    return IOSSafeAreaProvider()


def _make_ios_springboard_provider():
    from glassbox.ios.springboard import IOSSpringboardProvider

    return IOSSpringboardProvider()


def _make_ios_recovery_provider():
    from glassbox.ios.recovery import IOSRecoveryProvider

    return IOSRecoveryProvider()


class IOSSceneClassifier:
    def classify(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ):
        from glassbox.ios.scene import classify_ios_scene

        return classify_ios_scene(scene, viewport_size=viewport_size).to_scene_classification()


@dataclass
class IOSPlatform:
    scene_classifier: Any | None = field(default_factory=IOSSceneClassifier)
    safe_area: Any | None = field(default_factory=_make_ios_safe_area_provider)
    recovery: Any | None = field(default_factory=_make_ios_recovery_provider)
    springboard: Any | None = field(default_factory=_make_ios_springboard_provider)
    name: str = "ios"

    def supports(self, capability: str) -> bool:
        return getattr(self, capability, None) is not None

    def create_springboard_icon_map(self):
        from glassbox.ios.springboard_map import SpringboardIconMap

        return SpringboardIconMap()


def ios_platform_registration() -> PlatformRegistration:
    return PlatformRegistration(name="ios", factory=_ios_platform_factory, priority=0)


def _ios_platform_factory(*, cfg: AgentConfig):
    _ = cfg
    return IOSPlatform()


def select_platform_backend(cfg: AgentConfig, *, bundle_id: str | None = None) -> str:
    _ = bundle_id
    return getattr(cfg, "platform", None) or "ios"


DEFAULT_PLATFORM_REGISTRY = PlatformRegistry(
    registrations=(ios_platform_registration(),),
)


__all__ = [
    "DEFAULT_PLATFORM_REGISTRY",
    "IOSPlatform",
    "PlatformRegistration",
    "PlatformRegistry",
    "ios_platform_registration",
    "select_platform_backend",
]
