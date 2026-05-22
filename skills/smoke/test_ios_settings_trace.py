# ruff: noqa: F403,F405,I001

from __future__ import annotations

from skills.smoke.ios_settings_walkthrough_support import *

@pytest.mark.smoke
def test_settings_trace_records_action_and_unique_view(tmp_path):
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    child = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 72, w=48),
        _el("关于本机", 80, 260, w=72),
    )

    class FakePhone:
        def __init__(self):
            self.scene = root
            self.taps: list[tuple[int, int]] = []
            self._last_frame = None

        def perceive(self):
            return self.scene

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = child

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=True,
    )
    phone = walkthrough.TracedSettingsPhone(FakePhone(), trace)

    phone.tap_xy(100, 200)
    phone.perceive()
    trace.close()

    actions = (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(actions) == 1
    assert '"op": "tap_xy"' in actions[0]
    assert trace.payload["hid_call_count"] == 1
    assert trace.payload["hid_op_counts"] == {"tap_xy": 1}
    assert trace.payload["hid_progress_count"] == 1
    assert trace.payload["hid_no_progress_count"] == 0
    assert (tmp_path / "views" / "view_0001.ocr.json").exists()
    assert (tmp_path / "views" / "view_0002.ocr.json").exists()

@pytest.mark.smoke
def test_settings_trace_records_action_intent(tmp_path):
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class FakePhone:
        def __init__(self):
            self.scene = root

        def perceive(self):
            return self.scene

        def tap_xy(self, x: int, y: int):
            pass

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=False,
    )
    phone = walkthrough.TracedSettingsPhone(FakePhone(), trace)

    with trace.intent("settings_search.tap_visible_root_result", text="通用", retry_index=2):
        phone.tap_xy(80, 725)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert action["intent"] == {
        "name": "settings_search.tap_visible_root_result",
        "text": "通用",
        "retry_index": 2,
    }
    assert action["intent_stack"] == [action["intent"]]
    assert trace.payload["hid_intent_counts"] == {"settings_search.tap_visible_root_result": 1}
    assert trace.payload["hid_no_progress_intent_counts"] == {"settings_search.tap_visible_root_result": 1}

@pytest.mark.smoke
def test_settings_trace_records_nested_retry_intent_context(tmp_path):
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class FakePhone:
        def perceive(self):
            return root

        def key(self, modifier: int, keycode: int):
            pass

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=False,
    )
    phone = walkthrough.TracedSettingsPhone(FakePhone(), trace)

    with (
        trace.intent("return_to_settings_root.retry", retry_index=3, scene_kind="settings_search_home"),
        trace.intent("return.back_shortcut", modifier=0x08, keycode=0x2F),
    ):
        phone.key(0x08, 0x2F)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert action["intent"]["name"] == "return.back_shortcut"
    assert action["intent_stack"][0] == {
        "name": "return_to_settings_root.retry",
        "retry_index": 3,
        "scene_kind": "settings_search_home",
    }
    assert action["intent_stack"][1]["name"] == "return.back_shortcut"

@pytest.mark.smoke
def test_settings_trace_counts_no_progress_actions(tmp_path):
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class NoProgressPhone:
        def __init__(self):
            self.scene = root

        def perceive(self):
            return self.scene

        def tap_xy(self, x: int, y: int):
            pass

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=False,
    )
    phone = walkthrough.TracedSettingsPhone(NoProgressPhone(), trace)

    phone.tap_xy(100, 200)
    phone.perceive()
    trace.close()

    assert trace.payload["hid_call_count"] == 1
    assert trace.payload["hid_no_progress_count"] == 1
    assert trace.payload["hid_no_progress_op_counts"] == {"tap_xy": 1}

@pytest.mark.smoke
def test_settings_trace_records_failed_action_result(tmp_path):
    from glassbox.effector import ActionResult

    root = _scene(_el("设置", 198, 72, w=48), _el("通用", 80, 725, w=40))

    class FailingPhone:
        def perceive(self):
            return root

        def tap_xy(self, x: int, y: int):
            return ActionResult.failed(
                backend="picokvm",
                connected=True,
                error="executor failed",
                ack_seq=12,
            )

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=False,
    )
    phone = walkthrough.TracedSettingsPhone(FailingPhone(), trace)

    phone.tap_xy(100, 200)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert action["status"] == "action_failed"
    assert action["action_result"]["action_ok"] is False
    assert action["action_result"]["action_error"] == "executor failed"
    assert action["action_result"]["action_ack_seq"] == 12
    assert trace.payload["hid_action_failure_count"] == 1


@pytest.mark.smoke
def test_settings_trace_records_semantic_unknown_result(tmp_path):
    from glassbox.effector import ActionResult

    root = _scene(_el("设置", 198, 72, w=48), _el("通用", 80, 725, w=40))

    class UnknownPhone:
        def perceive(self):
            return root

        def tap_xy(self, x: int, y: int):
            return ActionResult(
                ok=True,
                backend="picokvm",
                connected=True,
                semantic_status="unknown",
                semantic_reason="after observation captured no frames",
            )

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=False,
    )
    phone = walkthrough.TracedSettingsPhone(UnknownPhone(), trace)

    phone.tap_xy(100, 200)
    phone.perceive()
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert action["status"] == "semantic_unknown"
    assert action["action_result"]["semantic_status"] == "unknown"
    assert trace.payload["hid_semantic_unknown_count"] == 1

@pytest.mark.smoke
def test_settings_trace_records_action_exception_status(tmp_path):
    root = _scene(_el("设置", 198, 72, w=48), _el("通用", 80, 725, w=40))

    class RaisingPhone:
        def perceive(self):
            return root

        def tap_xy(self, x: int, y: int):
            raise RuntimeError("tap exploded")

    trace = walkthrough.SettingsRunTrace(
        tmp_path,
        trace_actions=True,
        save_view_snapshots=False,
    )
    phone = walkthrough.TracedSettingsPhone(RaisingPhone(), trace)

    with pytest.raises(RuntimeError, match="tap exploded"):
        phone.tap_xy(100, 200)
    trace.close()

    action = json.loads((tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert action["status"] == "exception"
    assert action["after"] is None
    assert action["error"] == "RuntimeError: tap exploded"
    assert trace.payload["hid_exception_count"] == 1
