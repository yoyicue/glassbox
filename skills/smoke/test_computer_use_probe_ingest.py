from __future__ import annotations

import json

import pytest

from glassbox.action import ActionOrchestrator
from glassbox.effector import MockEffector
from glassbox.obs.artifacts import ArtifactStore
from glassbox.phone import Phone
from glassbox.verification.probe_ingest import (
    golden_case_from_action,
    load_actions,
    write_golden_case,
)
from skills.smoke.test_computer_use_runtime import _OCR, _Source


@pytest.mark.smoke
def test_probe_ingest_writes_golden_case_from_runtime_artifact(tmp_path):
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["主屏幕"], ["主屏幕"], ["勿扰模式", "未在播放"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )
    phone.control_center()
    orchestrator.close()

    action = load_actions(store.run_dir)[0]
    golden = golden_case_from_action(
        store.run_dir,
        action,
        case_id="runtime_control_center_positive",
    )
    out = tmp_path / "golden" / "case.json"
    write_golden_case(out, golden)

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["case_id"] == "runtime_control_center_positive"
    assert saved["action"] == "control_center"
    assert saved["verifier"] == "ios_control_center_opened"
    assert saved["expected_status"] == "succeeded"
    assert saved["before_texts"] == ["主屏幕"]
    assert saved["after_texts"] == ["勿扰模式", "未在播放"]
