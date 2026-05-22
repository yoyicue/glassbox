"""Explicit recovery hooks for computer-use runtime readiness failures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RecoveryHook = Callable[[object, str, dict[str, Any]], bool]


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
