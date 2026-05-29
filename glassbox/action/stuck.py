"""Stuck/loop detection for computer-use recovery."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from glassbox.memory.schema import ScreenSignature
from glassbox.memory.signature import SIGNATURE_MATCH_THRESHOLD, similarity


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


def _parse_signature(text: str) -> ScreenSignature | None:
    """Parse a JSON-encoded ScreenSignature; None for opaque/plain strings."""
    try:
        return ScreenSignature.model_validate(json.loads(text))
    except Exception:
        return None


class StuckLoopDetector:
    """Detect N near-identical (screen signature, failure reason) steps.

    The detector fires once per repeated run. A different failure reason or a
    screen that is no longer *similar* to the run's anchor resets the counter,
    matching the P3 minimal trigger.

    CUQ-1.6: comparison is by structural ``similarity()`` against the run's
    anchor signature, not exact string equality. Real HDMI-capture OCR jitter
    (one token flickering, a spinner counted as an element, a per-type histogram
    wobble) would otherwise reset the counter on exactly the noisy screens the
    detector exists to catch, so recovery would under-fire. Opaque/plain
    signature strings (e.g. unit-test fixtures) fall back to exact equality.
    """

    def __init__(
        self,
        *,
        threshold: int = 3,
        recovery: str = "recover_to_home_then_renavigate",
        match_threshold: float = SIGNATURE_MATCH_THRESHOLD,
    ):
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self.threshold = threshold
        self.recovery = recovery
        self.match_threshold = match_threshold
        # Anchor of the current run: kept fixed while the run continues so a
        # slow drift cannot accumulate far past the threshold under fuzziness.
        self._anchor: StuckSample | None = None
        self._anchor_sig: ScreenSignature | None = None
        self._count = 0
        self._fired_anchors: set[tuple[str, str]] = set()

    def _same_screen(self, anchor: StuckSample, anchor_sig: ScreenSignature | None,
                     sample: StuckSample) -> bool:
        if anchor.screen_signature == sample.screen_signature:
            return True
        sample_sig = _parse_signature(sample.screen_signature)
        if anchor_sig is None or sample_sig is None:
            return False
        return similarity(anchor_sig, sample_sig) >= self.match_threshold

    def _matches_anchor(self, sample: StuckSample) -> bool:
        if self._anchor is None:
            return False
        return (
            self._anchor.failure_reason == sample.failure_reason
            and self._same_screen(self._anchor, self._anchor_sig, sample)
        )

    def observe(self, sample: StuckSample) -> StuckDecision:
        if self._matches_anchor(sample):
            self._count += 1
        else:
            self._anchor = sample
            self._anchor_sig = _parse_signature(sample.screen_signature)
            self._count = 1
        anchor_key = (self._anchor.screen_signature, self._anchor.failure_reason)
        should_recover = self._count >= self.threshold and anchor_key not in self._fired_anchors
        if should_recover:
            self._fired_anchors.add(anchor_key)
        return StuckDecision(
            should_recover=should_recover,
            count=self._count,
            screen_signature=sample.screen_signature,
            failure_reason=sample.failure_reason,
            recovery=self.recovery,
            fired=should_recover,
        )

    def rearm(self) -> None:
        """Re-arm the current anchor after a failed recovery (CUQ-0.9).

        ``observe`` provisionally marks an anchor fired when it crosses the
        threshold. If the recovery it triggered did not actually recover, the
        caller calls ``rearm`` to drop that mark and reset the run counter, so a
        persistent dead-end can fire recovery again once it survives another
        ``threshold`` samples -- instead of disarming forever after a single
        no-op recovery and looping the failed action silently.
        """
        if self._anchor is not None:
            key = (self._anchor.screen_signature, self._anchor.failure_reason)
            self._fired_anchors.discard(key)
        self._count = 0

    def observe_and_recover(
        self,
        sample: StuckSample,
        recover: Callable[[str, StuckDecision], bool],
    ) -> StuckDecision:
        decision = self.observe(sample)
        if decision.should_recover and not recover(decision.recovery, decision):
            # Recovery reported failure -> re-arm so the dead-end can fire again.
            self.rearm()
        return decision

    def reset(self) -> None:
        self._anchor = None
        self._anchor_sig = None
        self._count = 0
        self._fired_anchors.clear()


__all__ = ["StuckDecision", "StuckLoopDetector", "StuckSample"]
