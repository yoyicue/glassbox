"""Stuck/loop detection for computer-use recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StuckSample:
    screen_signature: str
    failure_reason: str
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class StuckDecision:
    should_recover: bool
    count: int
    screen_signature: str
    failure_reason: str
    recovery: str = "recover_to_home_then_renavigate"
    fired: bool = False


class StuckLoopDetector:
    """Detect N identical (screen signature, failure reason) steps.

    The detector fires once per repeated pair. A different signature or failure
    reason resets the counter, matching the P3 minimal trigger.
    """

    def __init__(self, *, threshold: int = 3, recovery: str = "recover_to_home_then_renavigate"):
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self.threshold = threshold
        self.recovery = recovery
        self._last_key: tuple[str, str] | None = None
        self._count = 0
        self._fired_keys: set[tuple[str, str]] = set()

    def observe(self, sample: StuckSample) -> StuckDecision:
        key = (sample.screen_signature, sample.failure_reason)
        if key == self._last_key:
            self._count += 1
        else:
            self._last_key = key
            self._count = 1
        should_recover = self._count >= self.threshold and key not in self._fired_keys
        if should_recover:
            self._fired_keys.add(key)
        return StuckDecision(
            should_recover=should_recover,
            count=self._count,
            screen_signature=sample.screen_signature,
            failure_reason=sample.failure_reason,
            recovery=self.recovery,
            fired=should_recover,
        )

    def observe_and_recover(
        self,
        sample: StuckSample,
        recover: Callable[[str, StuckDecision], bool],
    ) -> StuckDecision:
        decision = self.observe(sample)
        if decision.should_recover:
            recover(decision.recovery, decision)
        return decision

    def reset(self) -> None:
        self._last_key = None
        self._count = 0
        self._fired_keys.clear()


__all__ = ["StuckDecision", "StuckLoopDetector", "StuckSample"]
