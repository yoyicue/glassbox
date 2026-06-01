"""Generic iOS foreground recovery helpers.

These helpers are intentionally app-agnostic. App-specific walkthroughs can
wrap them with their own tracing, but the recovery policy should live here when
it applies to iOS surfaces rather than a particular app.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any, Protocol

from glassbox.boundaries import RecoverySignal, StepContext
from glassbox.cognition.base import Scene
from glassbox.ios.scene import classify_ios_scene
from glassbox.ios.weather_surface import looks_like_weather_app_surface


class _HomeCapable(Protocol):
    def home(self) -> None: ...


ActionContext = Callable[..., Any]
FallbackAction = Callable[[], bool]


def _null_action_context(_name: str, **_metadata: Any):
    return nullcontext()


def dismiss_system_search(
    phone: object,
    scene: Scene | None = None,
    *,
    action_context: ActionContext | None = None,
    fallback_back: FallbackAction | None = None,
) -> bool:
    """Dismiss the global iOS search/suggestions surface.

    This is a foreground recovery primitive, not a Settings rule. The preferred
    action is Home because Spotlight/global search is outside the current app.
    Callers may pass an action_context factory to attach run-specific tracing.
    """

    title = None
    if scene is not None:
        classified = classify_ios_scene(scene)
        if classified.kind != "system_search":
            return False
        title = classified.title

    trace = action_context or _null_action_context
    home = getattr(phone, "home", None)
    if callable(home):
        with trace("system_search.home_dismiss", title=title):
            home()
        return True

    if fallback_back is not None:
        return bool(fallback_back())
    return False


def should_foreground_target_app_instead_of_back(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> bool:
    """Return True for iOS surfaces where Back is not a sane app recovery move.

    When a task is trying to re-ground a target app, Home/App Library/global
    search and known wrong-app surfaces should launch the target again. Pressing
    Back on these surfaces can reopen an unrelated foreground app or walk deeper
    into its navigation stack.
    """

    classified = classify_ios_scene(scene, viewport_size=viewport_size)
    if classified.kind in {"springboard", "app_library", "springboard_or_app_library", "system_search"}:
        return True
    if looks_like_weather_app_surface(scene):
        return True
    try:
        from glassbox.ios.springboard import is_ios_home_screen

        return is_ios_home_screen(scene, viewport_size=viewport_size)
    except Exception:
        return False


class IOSRecoveryProvider:
    """iOS Platform recovery sub-capability."""

    def detect(self, scene: Scene) -> RecoverySignal | None:
        classified = classify_ios_scene(scene)
        if classified.kind != "system_search":
            return None
        evidence = (classified.title,) if classified.title else ()
        return RecoverySignal(
            kind="system_search",
            confidence=classified.confidence,
            evidence=evidence,
        )

    def recover(self, ctx: StepContext) -> bool:
        metadata = ctx.metadata or {}
        phone = metadata.get("phone") or getattr(ctx, "phone", None)
        scene = metadata.get("scene")
        action_context = metadata.get("action_context")
        fallback_back = metadata.get("fallback_back")
        if phone is None:
            return False
        return dismiss_system_search(
            phone,
            scene if isinstance(scene, Scene) else None,
            action_context=action_context if callable(action_context) else None,
            fallback_back=fallback_back if callable(fallback_back) else None,
        )
