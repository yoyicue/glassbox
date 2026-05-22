from __future__ import annotations

import json

import pytest

from glassbox.crawl.trace import ActionRunTrace, TracedPhone
from glassbox.effector import ActionResult


class _TextTrace(ActionRunTrace):
    def scene_payload(self, phone, scene) -> dict:
        del phone
        return {"texts": list(scene)}


class _Phone:
    def __init__(self, scenes: list[list[str]]):
        self.scenes = scenes
        self.index = 0

    def perceive(self) -> list[str]:
        return self.scenes[self.index]

    def tap_xy(self, x: int, y: int) -> None:
        del x, y
        self.index = min(self.index + 1, len(self.scenes) - 1)

    def key(self, modifier: int, keycode: int) -> dict:
        del modifier, keycode
        return {"ok": False, "backend": "fake", "err": "rejected", "seq": 7}


@pytest.mark.smoke
def test_action_run_trace_records_result_intent_and_progress(tmp_path):
    trace = _TextTrace(tmp_path, trace_actions=True)
    phone = TracedPhone(_Phone([["A"], ["B"]]), trace)

    with trace.intent("open.detail", label="B"):
        phone.tap_xy(10, 20)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8"))
    assert action["op"] == "tap_xy"
    assert action["before"] == {"texts": ["A"]}
    assert action["after"] == {"texts": ["B"]}
    assert action["intent"] == {"name": "open.detail", "label": "B"}
    assert trace.payload["hid_progress_count"] == 1


@pytest.mark.smoke
def test_action_run_trace_records_failed_action_result(tmp_path):
    trace = _TextTrace(tmp_path, trace_actions=True)
    phone = TracedPhone(_Phone([["A"]]), trace)

    phone.key(1, 2)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8"))
    assert action["status"] == "action_failed"
    assert action["action_result"]["action_ok"] is False
    assert action["action_result"]["action_error"] == "rejected"
    assert action["action_result"]["action_ack_seq"] == 7
    assert trace.payload["hid_action_failure_count"] == 1


@pytest.mark.smoke
def test_action_run_trace_records_semantic_rejected_result(tmp_path):
    class SemanticRejectedPhone(_Phone):
        def tap_xy(self, x: int, y: int):
            super().tap_xy(x, y)
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="approval_required",
                semantic_reason="permission dialog is visible",
            )

    trace = _TextTrace(tmp_path, trace_actions=True)
    phone = TracedPhone(SemanticRejectedPhone([["A"], ["B"]]), trace)

    phone.tap_xy(10, 20)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8"))
    assert action["status"] == "semantic_approval_required"
    assert action["action_result"]["action_ok"] is True
    assert action["action_result"]["semantic_status"] == "approval_required"
    assert trace.payload["hid_semantic_rejected_count"] == 1
    assert trace.payload["hid_semantic_status_counts"] == {"approval_required": 1}


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("semantic_status", "verification_skipped", "expected_status", "expected_rejected"),
    [
        ("transport_failed", None, "semantic_transport_failed", 1),
        ("exception", None, "semantic_exception", 1),
        ("no_after_scene", True, "semantic_no_after_skipped", 0),
        ("no_after_scene", False, "semantic_no_after_scene", 1),
    ],
)
def test_action_run_trace_records_terminal_semantic_statuses(
    tmp_path,
    semantic_status,
    verification_skipped,
    expected_status,
    expected_rejected,
):
    class TerminalSemanticPhone(_Phone):
        def tap_xy(self, x: int, y: int):
            super().tap_xy(x, y)
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status=semantic_status,
                semantic_reason=f"{semantic_status} reason",
                semantic_verification_skipped=verification_skipped,
            )

    trace = _TextTrace(tmp_path, trace_actions=True)
    phone = TracedPhone(TerminalSemanticPhone([["A"], ["B"]]), trace)

    phone.tap_xy(10, 20)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8"))
    assert action["status"] == expected_status
    assert action["action_result"]["semantic_status"] == semantic_status
    if verification_skipped is not None:
        assert action["action_result"]["semantic_verification_skipped"] is verification_skipped
    assert trace.payload["hid_semantic_status_counts"] == {semantic_status: 1}
    assert trace.payload["hid_semantic_rejected_count"] == expected_rejected


@pytest.mark.smoke
def test_action_run_trace_records_action_exception(tmp_path):
    class RaisingPhone:
        def perceive(self) -> list[str]:
            return ["A"]

        def tap_xy(self, x: int, y: int) -> None:
            del x, y
            raise RuntimeError("tap failed")

    trace = _TextTrace(tmp_path, trace_actions=True)
    phone = TracedPhone(RaisingPhone(), trace)

    with pytest.raises(RuntimeError, match="tap failed"):
        phone.tap_xy(10, 20)
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8"))
    assert action["status"] == "exception"
    assert action["after"] is None
    assert action["error"] == "RuntimeError: tap failed"
    assert trace.payload["hid_exception_count"] == 1
