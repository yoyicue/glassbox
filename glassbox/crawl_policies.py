"""CrawlPolicy registry and provisional Settings adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from glassbox.cognition.candidates import ocr_tap_candidates


@dataclass(frozen=True)
class CrawlPolicyRegistration:
    name: str
    factory: Callable[..., Any]
    priority: int = 0


class CrawlPolicyRegistry:
    def __init__(
        self,
        registrations: Iterable[CrawlPolicyRegistration] | None = None,
        *,
        load_entry_points: bool = True,
    ):
        self._by_name: dict[str, CrawlPolicyRegistration] = {}
        self._entry_points_loaded = not load_entry_points
        for registration in registrations or ():
            self.register(registration)

    def register(self, registration: CrawlPolicyRegistration) -> None:
        current = self._by_name.get(registration.name)
        if current is None or registration.priority >= current.priority:
            self._by_name[registration.name] = registration

    def names(self) -> tuple[str, ...]:
        self._load_entry_points_once()
        return tuple(sorted(self._by_name))

    def create(self, name: str, **kwargs):
        self._load_entry_points_once()
        try:
            registration = self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown crawl policy {name!r}; registered={sorted(self._by_name)}") from exc
        return registration.factory(**kwargs)

    def _load_entry_points_once(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        try:
            selected = entry_points(group="glassbox.crawl_policies")
        except TypeError:
            selected = entry_points().get("glassbox.crawl_policies", ())
        for entry_point in selected:
            loaded = entry_point.load()
            for registration in _coerce_registrations(loaded):
                self.register(registration)


def _coerce_registrations(value) -> Iterable[CrawlPolicyRegistration]:
    if isinstance(value, CrawlPolicyRegistration):
        return (value,)
    if callable(value):
        return _coerce_registrations(value())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        registrations: list[CrawlPolicyRegistration] = []
        for item in value:
            if not isinstance(item, CrawlPolicyRegistration):
                raise TypeError(f"crawl-policy entry point returned unsupported item: {item!r}")
            registrations.append(item)
        return tuple(registrations)
    raise TypeError(f"crawl-policy entry point returned unsupported value: {value!r}")


@dataclass
class GenericCrawlPolicyAdapter:
    """App-agnostic OCR/heuristic crawl policy.

    This is useful for generic crawler/explorer drivers, but it is not an app
    specific second implementation for the CrawlPolicy graduation gate.
    """

    def classify(self, scene) -> str:
        return str(
            getattr(scene, "semantic_scene_type", None)
            or getattr(scene, "scene_type", None)
            or getattr(scene, "platform_scene_kind", None)
            or "generic"
        )

    def candidates(self, scene) -> list[dict[str, Any]]:
        out = []
        for candidate in ocr_tap_candidates(scene):
            out.append({
                "action": "tap",
                "text": candidate.label,
                "label": candidate.label,
                "center": [int(candidate.center[0]), int(candidate.center[1])],
                "role": candidate.role,
                "safe": True,
                "source": f"generic_{candidate.source}",
            })
        return out

    def is_safe(self, action: dict[str, Any], scene) -> bool:
        _ = scene
        return (
            action.get("action") == "tap"
            and bool(str(action.get("label") or action.get("text") or "").strip())
            and str(action.get("source") or "").startswith("generic_")
        )

    def should_stop(self, scene, history: list[dict[str, Any]]) -> bool:
        _ = history
        return not self.candidates(scene)


@dataclass
class SettingsCrawlPolicyAdapter:
    settings_policy: Any

    def classify(self, scene) -> str:
        return str(self.settings_policy.scene_type(scene))

    def candidates(self, scene) -> list[dict[str, Any]]:
        out = []
        for element in self.settings_policy.safe_navigation_candidates(scene):
            text = (element.text or "").strip()
            out.append({
                "action": "tap",
                "text": text,
                "label": text,
                "element_id": int(element.element_id),
                "box": [element.box.x, element.box.y, element.box.x2, element.box.y2],
                "safe": True,
                "source": "ios_settings",
            })
        return out

    def is_safe(self, action: dict[str, Any], scene) -> bool:
        _ = scene
        if action.get("safe") is True:
            return True
        text = str(action.get("text") or action.get("label") or "").strip()
        if not text:
            return False
        return (
            self.settings_policy.is_safe_known_navigation_label(text)
            and not self.settings_policy.is_unsafe_navigation_text(text)
        )

    def should_stop(self, scene, history: list[dict[str, Any]]) -> bool:
        _ = history
        return self.classify(scene) in {"springboard_or_app_library", "settings_blocked_safety"}


def ios_settings_crawl_policy_registration() -> CrawlPolicyRegistration:
    return CrawlPolicyRegistration(name="ios_settings", factory=_ios_settings_crawl_policy_factory)


def generic_crawl_policy_registration() -> CrawlPolicyRegistration:
    return CrawlPolicyRegistration(name="generic", factory=_generic_crawl_policy_factory)


def _generic_crawl_policy_factory(**_kwargs) -> GenericCrawlPolicyAdapter:
    return GenericCrawlPolicyAdapter()


def _ios_settings_crawl_policy_factory(**_kwargs) -> SettingsCrawlPolicyAdapter:
    from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

    return SettingsCrawlPolicyAdapter(DEFAULT_SETTINGS_POLICY)


DEFAULT_CRAWL_POLICY_REGISTRY = CrawlPolicyRegistry(
    registrations=(
        generic_crawl_policy_registration(),
        ios_settings_crawl_policy_registration(),
    ),
)


__all__ = [
    "DEFAULT_CRAWL_POLICY_REGISTRY",
    "CrawlPolicyRegistration",
    "CrawlPolicyRegistry",
    "GenericCrawlPolicyAdapter",
    "SettingsCrawlPolicyAdapter",
    "generic_crawl_policy_registration",
    "ios_settings_crawl_policy_registration",
]
