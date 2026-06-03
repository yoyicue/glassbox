"""Explicit recovery hooks for computer-use runtime readiness failures."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from glassbox.boundaries import action_host_last_frame, action_host_last_scene

RecoveryHook = Callable[[object, str, dict[str, Any]], bool]
_RECOVERY_GUARD_BY_ID: dict[int, int] = {}


def _in_recovery(phone: object) -> bool:
    return _RECOVERY_GUARD_BY_ID.get(id(phone), 0) > 0


@contextlib.contextmanager
def _recovery_guard(phone: object):
    key = id(phone)
    _RECOVERY_GUARD_BY_ID[key] = _RECOVERY_GUARD_BY_ID.get(key, 0) + 1
    try:
        yield
    finally:
        remaining = _RECOVERY_GUARD_BY_ID.get(key, 1) - 1
        if remaining > 0:
            _RECOVERY_GUARD_BY_ID[key] = remaining
        else:
            _RECOVERY_GUARD_BY_ID.pop(key, None)


@dataclass(frozen=True)
class NavigationMeasurementOrigin:
    """Verified task-entry anchor for measuring navigation from Home."""

    attempted: bool
    home_reached: bool
    reason: str
    action_ok: bool | None = None
    semantic_status: str | None = None
    semantic_verifier: str | None = None
    error: str | None = None

    @property
    def can_start_clock(self) -> bool:
        return self.attempted and self.home_reached

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "home_reached": self.home_reached,
            "can_start_clock": self.can_start_clock,
            "reason": self.reason,
            "action_ok": self.action_ok,
            "semantic_status": self.semantic_status,
            "semantic_verifier": self.semantic_verifier,
            "error": self.error,
        }


@dataclass(frozen=True)
class MemoryPathNavigationResult:
    """Result of a proactive UTG path replay toward a remembered page."""

    attempted: bool
    reached: bool
    reason: str
    target_page: str
    from_id: str | None = None
    edge_count: int = 0
    replayed_ops: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "reached": self.reached,
            "reason": self.reason,
            "target_page": self.target_page,
            "from_id": self.from_id,
            "edge_count": self.edge_count,
            "replayed_ops": list(self.replayed_ops),
        }

    def to_event_fields(self) -> dict[str, Any]:
        return {
            "memory_path_attempted": self.attempted,
            "memory_path_reached": self.reached,
            "memory_path_reason": self.reason,
            "memory_path_target_page": self.target_page,
            "memory_path_from_id": self.from_id,
            "memory_path_edge_count": self.edge_count,
            "memory_path_replayed_ops": list(self.replayed_ops),
        }


def prepare_navigation_measurement_origin(phone: object) -> NavigationMeasurementOrigin:
    """Reset to Home and verify it before a navigation metric starts.

    This is the harness/navigation-task entry discipline from
    `docs/goals/computer_use_world_model_spine.md`: a failed or unverified Home
    reset is its own precondition failure, never part of the measured `Home→X`
    trajectory.
    """
    home = getattr(phone, "home", None)
    if not callable(home):
        return NavigationMeasurementOrigin(
            attempted=False,
            home_reached=False,
            reason="home_unavailable",
        )
    with _recovery_guard(phone):
        try:
            result = home()
        except Exception as exc:
            return NavigationMeasurementOrigin(
                attempted=True,
                home_reached=False,
                reason="home_exception",
                error=f"{type(exc).__name__}: {exc}",
            )
    action_ok = bool(getattr(result, "ok", False))
    semantic_status = getattr(result, "semantic_status", None)
    semantic_verifier = getattr(result, "semantic_verifier", None)
    if action_ok and semantic_status == "succeeded":
        return NavigationMeasurementOrigin(
            attempted=True,
            home_reached=True,
            reason="verified_home_reached",
            action_ok=action_ok,
            semantic_status=semantic_status,
            semantic_verifier=semantic_verifier,
        )
    if not action_ok:
        reason = "home_action_failed"
    elif semantic_status is None:
        reason = "home_unverified"
    else:
        reason = f"home_semantic_{semantic_status}"
    return NavigationMeasurementOrigin(
        attempted=True,
        home_reached=False,
        reason=reason,
        action_ok=action_ok,
        semantic_status=semantic_status,
        semantic_verifier=semantic_verifier,
        error=getattr(result, "error", None),
    )


def navigate_via_memory_path(
    phone: object,
    target_page: str,
    *,
    scene_type: str | None = None,
    allowed_actions: set[str] | None = None,
    min_success_rate: float = 0.5,
) -> MemoryPathNavigationResult:
    """Replay a learned UTG path as a normal navigation decision.

    Unlike the recovery hook, this does not fall back to Home. It is the A1
    "navigation in the loop" primitive: recognize the current screen, ask
    memory for a safe-enough path to a semantic page, replay only known generic
    edges, and verify arrival by recognizing the final page.
    """
    page = str(target_page or "").strip()
    if not page:
        return MemoryPathNavigationResult(False, False, "missing_target_page", page)
    memory = getattr(phone, "memory", None)
    recognize = getattr(memory, "recognize", None) if memory is not None else None
    path_to_page = getattr(memory, "path_to_page", None) if memory is not None else None
    if not callable(recognize) or not callable(path_to_page):
        return MemoryPathNavigationResult(False, False, "memory_unavailable", page)
    scene = _current_scene(phone)
    if scene is None:
        return MemoryPathNavigationResult(True, False, "current_scene_unavailable", page)
    node = recognize(scene, _current_frame_img(phone))
    if node is None:
        return MemoryPathNavigationResult(True, False, "current_screen_unrecognized", page)
    from_id = str(getattr(node, "screen_id", "") or "")
    allowed = set(allowed_actions) if allowed_actions else {"home", "back"}
    try:
        path = path_to_page(
            from_id,
            page,
            scene_type=scene_type,
            allowed_actions=allowed,
            min_success_rate=min_success_rate,
        )
    except Exception:
        return MemoryPathNavigationResult(True, False, "path_lookup_failed", page, from_id=from_id)
    if path is None:
        return MemoryPathNavigationResult(True, False, "no_path", page, from_id=from_id)
    if not path:
        return MemoryPathNavigationResult(
            True,
            True,
            "already_at_target",
            page,
            from_id=from_id,
            edge_count=0,
        )
    replayed: list[str] = []
    with _recovery_guard(phone):
        for edge in path:
            op = str(getattr(edge, "action_op", "") or "")
            if not _replay_edge(phone, edge):
                return MemoryPathNavigationResult(
                    True,
                    False,
                    "replay_failed",
                    page,
                    from_id=from_id,
                    edge_count=len(path),
                    replayed_ops=tuple(replayed),
                )
            replayed.append(op)
    after = _current_scene(phone)
    if after is None:
        return MemoryPathNavigationResult(
            True,
            False,
            "arrival_scene_unavailable",
            page,
            from_id=from_id,
            edge_count=len(path),
            replayed_ops=tuple(replayed),
        )
    arrived = recognize(after, _current_frame_img(phone))
    reached = arrived is not None and getattr(arrived, "page_id", None) == page
    return MemoryPathNavigationResult(
        True,
        reached,
        "reached" if reached else "arrival_unconfirmed",
        page,
        from_id=from_id,
        edge_count=len(path),
        replayed_ops=tuple(replayed),
    )


def recover_to_home_then_renavigate(phone: object, reason: str, payload: dict[str, Any]) -> bool:
    """Default universal recovery hook (invariant #4 / P3).

    The deterministic safety net: when the stuck detector trips, all semantic
    strategies are exhausted, or preflight fails, drive the device back to the
    Home anchor so the next step starts from a known clean state instead of
    looping on a dead-end screen. Returns True only if Home is reached.

    The hook is duck-typed against ``Phone`` (it only calls ``phone.home()`` and
    optionally ``phone.memory.path_to_page``) so it carries no import-time
    dependency on the runtime. A re-entrancy guard prevents the recovery's own
    ``home()`` call -- which itself runs through the orchestrator -- from
    triggering nested recovery.

    The "re-navigate" half is attempted only when ``payload`` names a
    ``target_page`` reachable in screen memory; otherwise reaching the anchor is
    the recovery (a generic memory-pathed re-navigation hook is tracked
    separately as CUQ-0.5).
    """
    del reason
    recovery_kind = str(payload.get("recovery") or "recover_to_home_then_renavigate")
    if recovery_kind != "recover_to_home_then_renavigate":
        return False
    if _in_recovery(phone):
        return False
    home = getattr(phone, "home", None)
    if not callable(home):
        return False
    with _recovery_guard(phone):
        result = home()
        reached_home = bool(getattr(result, "ok", False)) and getattr(
            result, "semantic_status", None
        ) in {None, "succeeded"}
        if not reached_home:
            return False
        target_page = payload.get("target_page")
        memory = getattr(phone, "memory", None)
        path_to_page = getattr(memory, "path_to_page", None) if memory is not None else None
        if target_page and callable(path_to_page):
            # Best-effort re-navigation toward an in-progress target; reaching
            # the anchor already counts as recovered, so a failed replay does
            # not flip the verdict back to not-recovered.
            with contextlib.suppress(Exception):
                path_to_page(str(target_page))
        return True


def _current_scene(phone: object) -> Any | None:
    """Best-effort fresh scene for memory recognition; None if unavailable."""
    perceive = getattr(phone, "perceive", None)
    if callable(perceive):
        try:
            return perceive(fresh=True)
        except TypeError:
            with contextlib.suppress(Exception):
                return perceive()
        except Exception:
            return None
    return action_host_last_scene(phone)


def _current_frame_img(phone: object) -> Any | None:
    frame = action_host_last_frame(phone)
    return getattr(frame, "img", None) if frame is not None else None


def _replay_result_ok(result: Any) -> bool:
    # Lenient per-edge: a transport-failed step aborts, but a verified-unknown
    # step may still have navigated — the final arrival check is the real gate.
    if getattr(result, "ok", True) is False:
        return False
    return getattr(result, "semantic_status", None) not in {"failed", "blocked", "exception"}


def _edge_action_kwargs(edge: Any) -> dict[str, Any]:
    raw = getattr(edge, "action_kwargs", None)
    return raw if isinstance(raw, dict) else {}


def _replay_tap_edge(phone: object, edge: Any) -> bool:
    action = getattr(edge, "action", None)
    kwargs = _edge_action_kwargs(edge)
    x = getattr(action, "x", None) if action is not None else None
    y = getattr(action, "y", None) if action is not None else None
    if x is None:
        x = kwargs.get("x")
    if y is None:
        y = kwargs.get("y")
    if x is not None and y is not None:
        fn = getattr(phone, "tap_xy", None)
        if not callable(fn):
            return False
        coordinate_space = (
            getattr(action, "coordinate_space", None) if action is not None else None
        ) or kwargs.get("coordinate_space")
        try:
            if coordinate_space is None:
                result = fn(int(x), int(y))
            else:
                result = fn(int(x), int(y), coordinate_space=coordinate_space)
        except Exception:
            return False
        return _replay_result_ok(result)
    target = (getattr(action, "target", None) if action is not None else None) or kwargs.get("target")
    if not target:
        return False
    fn = getattr(phone, "tap_text", None)
    if not callable(fn):
        return False
    try:
        result = fn(str(target))
    except Exception:
        return False
    return _replay_result_ok(result)


# CUQ-0.5: navigation ops the generic memory-path recovery can replay on ANY
# backend — each maps a learned edge to a backend-agnostic Phone primitive. An
# edge whose op is outside this set fails the replay cleanly (the caller then
# falls back to the home-anchor hook), so the replay never improvises an action.
def _replay_edge(phone: object, edge: Any) -> bool:
    op = str(getattr(edge, "action_op", "") or "")
    if op in {"tap", "tap_xy", "target_tap"}:
        return _replay_tap_edge(phone, edge)
    if op == "home":
        fn = getattr(phone, "home", None)
    elif op in {"back", "back_gesture"}:
        fn = getattr(phone, "back_gesture", None)
    elif op in {"swipe_up", "scroll", "scroll_down"}:
        fn = getattr(phone, "swipe_up", None)
    elif op in {"swipe_down", "scroll_up"}:
        fn = getattr(phone, "swipe_down", None)
    else:
        return False
    if not callable(fn):
        return False
    try:
        result = fn()
    except Exception:
        return False
    return _replay_result_ok(result)


def _delegate_fallback(
    fallback: RecoveryHook | None, phone: object, reason: str, payload: dict[str, Any]
) -> bool:
    if fallback is None:
        return False
    try:
        return bool(fallback(phone, reason, payload))
    except Exception:
        return False


def make_try_memory_path_hook(
    *,
    target_page: str,
    scene_type: str | None = None,
    allowed_actions: set[str] | None = None,
    min_success_rate: float = 0.5,
    fallback: RecoveryHook | None = recover_to_home_then_renavigate,
) -> RecoveryHook:
    """Generic UTG-pathed recovery hook (CUQ-0.5).

    Closes leak #7: the UTG graph (`recognize` / `path_to_page` / reliability-
    weighted BFS) had no caller outside the Settings skill, so "explore once,
    reuse the path" was dormant for every other app. This factory builds a
    default-installable hook that, on a stuck/exhausted recovery, recognizes the
    current screen, asks screen memory for the shortest safe-enough learned path
    to ``target_page``, and replays that edge chain to re-navigate in place —
    rather than always resetting to the Home anchor.

    Parameterized by ``target_page`` + ``allowed_actions`` (the safety gate —
    only these ops are pathed and replayed) + ``min_success_rate`` (skip
    low-success edges), all honored by `path_to_page`. ``allowed_actions``
    defaults to the safe back-out set ``{"home", "back"}``.

    Falls back to ``fallback`` (the home-anchor hook by default) when memory is
    absent, the screen is unrecognized, no path exists, or a replay/arrival check
    fails — so installing this hook never makes recovery *worse* than home-reset.
    """
    allowed = set(allowed_actions) if allowed_actions else {"home", "back"}

    def hook(phone: object, reason: str, payload: dict[str, Any]) -> bool:
        if _in_recovery(phone):
            return False
        page = str(payload.get("target_page") or target_page or "")
        memory = getattr(phone, "memory", None)
        recognize = getattr(memory, "recognize", None) if memory is not None else None
        path_to_page = getattr(memory, "path_to_page", None) if memory is not None else None
        recovered = False
        if page and callable(recognize) and callable(path_to_page):
            result = navigate_via_memory_path(
                phone,
                page,
                scene_type=scene_type,
                allowed_actions=allowed,
                min_success_rate=min_success_rate,
            )
            recovered = result.reached
        if recovered:
            return True
        # The fallback sets its own re-entrancy guard, so it must run only after
        # this hook has cleared `_in_recovery` (above).
        return _delegate_fallback(fallback, phone, reason, payload)

    return hook


@dataclass(frozen=True)
class RecoveryResult:
    attempted: bool
    recovered: bool
    reason: str
    attempts: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "recovered": self.recovered,
            "reason": self.reason,
            "attempts": self.attempts,
            "error": self.error,
        }


class RuntimeRecoveryPolicy:
    """Owns explicit runtime recovery hooks.

    Verifiers only classify states. This policy decides whether a run is allowed
    to try recovery, and delegates the actual operation to a configured hook.
    """

    def __init__(self, hook: RecoveryHook | None = None, *, max_attempts: int = 1):
        self.hook = hook
        self.max_attempts = max(0, int(max_attempts))

    def recover(self, phone: object, reason: str, payload: dict[str, Any]) -> RecoveryResult:
        if self.hook is None or self.max_attempts <= 0:
            return RecoveryResult(
                attempted=False,
                recovered=False,
                reason=reason,
                attempts=0,
            )
        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                if self.hook(phone, reason, payload):
                    return RecoveryResult(
                        attempted=True,
                        recovered=True,
                        reason=reason,
                        attempts=attempt,
                    )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        return RecoveryResult(
            attempted=True,
            recovered=False,
            reason=reason,
            attempts=self.max_attempts,
            error=last_error,
        )
