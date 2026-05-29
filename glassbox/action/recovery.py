"""Explicit recovery hooks for computer-use runtime readiness failures."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RecoveryHook = Callable[[object, str, dict[str, Any]], bool]


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
    if getattr(phone, "_in_recovery", False):
        return False
    home = getattr(phone, "home", None)
    if not callable(home):
        return False
    phone._in_recovery = True  # type: ignore[attr-defined]
    try:
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
    finally:
        phone._in_recovery = False  # type: ignore[attr-defined]


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
