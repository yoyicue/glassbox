from __future__ import annotations

import pytest

from glassbox.cognition.vlm_gate import VLMEscalationGate, VLMGateInput, escalation_triggers


@pytest.mark.parametrize(
    ("input_", "trigger"),
    [
        (VLMGateInput(ocr_confidence=0.2), "low_confidence"),
        (VLMGateInput(ocr_confidence=None), "confidence_missing"),
        (VLMGateInput(ocr_confidence=float("nan")), "confidence_missing"),
        (VLMGateInput(target_found=False, ocr_confidence=0.95), "target_missing"),
        (VLMGateInput(classifier_conflict=True, ocr_confidence=0.95), "classifier_conflict"),
        (VLMGateInput(verification_status="unknown", ocr_confidence=0.95), "verify_unknown"),
    ],
)
def test_each_p1_trigger_forces_escalation(input_, trigger):
    gate = VLMEscalationGate()
    calls = []

    result = gate.escalate(input_, lambda: calls.append("vlm") or "ok")

    assert result == "ok"
    assert calls == ["vlm"]
    assert trigger in gate.audit_fields()["vlm_triggers"]


def test_absence_of_triggers_stays_on_ocr_fast_path():
    gate = VLMEscalationGate()

    result = gate.escalate(VLMGateInput(ocr_confidence=0.95), lambda: "vlm")

    assert result is None
    assert gate.audit_fields() == {
        "vlm_calls": 0,
        "vlm_triggers": [],
        "last_vlm_trigger": None,
        "vlm_budget_exhausted": False,
    }


def test_disabled_gate_degrades_to_ocr_without_calling_vlm():
    gate = VLMEscalationGate(enabled=False)
    calls = []

    result = gate.escalate(VLMGateInput(target_found=False), lambda: calls.append("vlm"))

    assert result is None
    assert calls == []
    assert gate.audit_fields()["vlm_calls"] == 0
    assert gate.audit_fields()["vlm_triggers"] == ["confidence_missing", "target_missing"]


def test_budget_prevents_unknown_vlm_unknown_loop():
    gate = VLMEscalationGate(max_calls_per_action=1, max_calls_per_attempt=1)
    calls = []

    assert gate.escalate(
        VLMGateInput(verification_status="unknown", ocr_confidence=0.95),
        lambda: calls.append("first") or "unknown",
    ) == "unknown"
    assert gate.escalate(
        VLMGateInput(verification_status="unknown", ocr_confidence=0.95),
        lambda: calls.append("second") or "unknown",
    ) is None

    assert calls == ["first"]
    assert gate.audit_fields()["vlm_calls"] == 1
    assert gate.audit_fields()["vlm_budget_exhausted"] is True


def test_attempt_budget_is_enforced_even_when_action_budget_remains():
    gate = VLMEscalationGate(max_calls_per_action=3, max_calls_per_attempt=1)

    assert gate.escalate(VLMGateInput(target_found=False), lambda: "first", attempt_index=0) == "first"
    assert gate.escalate(VLMGateInput(target_found=False), lambda: "second", attempt_index=0) is None
    assert gate.escalate(VLMGateInput(target_found=False), lambda: "third", attempt_index=1) == "third"
    assert gate.audit_fields()["vlm_calls"] == 2


def test_vlm_call_exception_degrades_without_raising():
    gate = VLMEscalationGate()

    def broken_call():
        raise RuntimeError("vlm unavailable")

    result = gate.escalate(VLMGateInput(target_found=False), broken_call)

    assert result is None
    assert gate.audit_fields()["vlm_calls"] == 1


def test_escalation_triggers_reports_multiple_reasons_in_order():
    triggers = escalation_triggers(
        VLMGateInput(
            ocr_confidence=None,
            target_found=False,
            classifier_conflict=True,
            verification_status="unknown",
        )
    )

    assert triggers == [
        "confidence_missing",
        "target_missing",
        "classifier_conflict",
        "verify_unknown",
    ]
