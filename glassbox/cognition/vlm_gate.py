"""Gated VLM escalation policy for reliability-first computer use."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

VLMTrigger = Literal[
    "low_confidence",
    "confidence_missing",
    "target_missing",
    "classifier_conflict",
    "verify_unknown",
]


@dataclass(frozen=True)
class VLMGateInput:
    ocr_confidence: float | None = None
    confidence_threshold: float = 0.75
    target_found: bool = True
    classifier_conflict: bool = False
    verification_status: str | None = None


@dataclass
class VLMGateState:
    enabled: bool = True
    max_calls_per_action: int = 1
    max_calls_per_attempt: int = 1
    action_calls: int = 0
    attempt_calls: dict[int, int] = field(default_factory=dict)
    triggers: list[VLMTrigger] = field(default_factory=list)
    budget_exhausted: bool = False

    def reset_action(self) -> None:
        self.action_calls = 0
        self.attempt_calls.clear()
        self.triggers.clear()
        self.budget_exhausted = False

    def audit_fields(self) -> dict[str, Any]:
        return {
            "vlm_calls": self.action_calls,
            "vlm_triggers": list(self.triggers),
            "last_vlm_trigger": self.triggers[-1] if self.triggers else None,
            "vlm_budget_exhausted": self.budget_exhausted,
        }


def escalation_triggers(input_: VLMGateInput) -> list[VLMTrigger]:
    triggers: list[VLMTrigger] = []
    if input_.ocr_confidence is None:
        triggers.append("confidence_missing")
    else:
        try:
            confidence = float(input_.ocr_confidence)
        except (TypeError, ValueError):
            triggers.append("confidence_missing")
        else:
            if not math.isfinite(confidence):
                triggers.append("confidence_missing")
            elif confidence < input_.confidence_threshold:
                triggers.append("low_confidence")
    if not input_.target_found:
        triggers.append("target_missing")
    if input_.classifier_conflict:
        triggers.append("classifier_conflict")
    if input_.verification_status == "unknown":
        triggers.append("verify_unknown")
    return triggers


class VLMEscalationGate:
    def __init__(
        self,
        *,
        enabled: bool = True,
        max_calls_per_action: int = 1,
        max_calls_per_attempt: int = 1,
    ):
        self.state = VLMGateState(
            enabled=enabled,
            max_calls_per_action=max(0, max_calls_per_action),
            max_calls_per_attempt=max(0, max_calls_per_attempt),
        )

    def should_escalate(self, input_: VLMGateInput, *, attempt_index: int = 0) -> bool:
        triggers = escalation_triggers(input_)
        if not triggers:
            return False
        for trigger in triggers:
            if trigger not in self.state.triggers:
                self.state.triggers.append(trigger)
        if not self.state.enabled:
            return False
        if self.state.action_calls >= self.state.max_calls_per_action:
            self.state.budget_exhausted = True
            return False
        attempt_calls = self.state.attempt_calls.get(attempt_index, 0)
        if attempt_calls >= self.state.max_calls_per_attempt:
            self.state.budget_exhausted = True
            return False
        return True

    def escalate(
        self,
        input_: VLMGateInput,
        call: Callable[[], Any],
        *,
        attempt_index: int = 0,
    ) -> Any | None:
        if not self.should_escalate(input_, attempt_index=attempt_index):
            return None
        self.state.action_calls += 1
        self.state.attempt_calls[attempt_index] = self.state.attempt_calls.get(attempt_index, 0) + 1
        try:
            return call()
        except Exception:
            return None

    def audit_fields(self) -> dict[str, Any]:
        return self.state.audit_fields()


__all__ = [
    "VLMEscalationGate",
    "VLMGateInput",
    "VLMGateState",
    "VLMTrigger",
    "escalation_triggers",
]
