"""skills/smoke/test_effector_integration.py

Verify the Phone → Effector path is correct (runs offline with MockEffector, no hardware needed).
"""

from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition import Box, UIElement
from glassbox.effector import ActionResult
from glassbox.perception.source import Frame


@pytest.mark.smoke
def test_swipe_xy_threads_picokvm_fresh_verify(mock_phone, monkeypatch):
    """CUQ-3.12: swipe_xy defaults to the PicoKVM fresh-frame verify reopen
    (no-op off-PicoKVM), without overriding a caller-set settle strategy."""
    captured: dict = {}

    def fake_execute(op, call, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return ActionResult(ok=True, backend="mock", connected=True)

    monkeypatch.setattr(mock_phone, "_execute_action", fake_execute)
    monkeypatch.setattr(
        mock_phone,
        "_picokvm_fresh_verify_kwargs",
        lambda action: {"settle_strategy": "stream_until_match", "fresh_source_reopen": True},
    )

    mock_phone.swipe_xy(10, 20, 10, 200)
    assert captured["settle_strategy"] == "stream_until_match"
    assert captured["fresh_source_reopen"] is True

    # A caller-set settle strategy is respected (not overridden by the default).
    mock_phone.swipe_xy(10, 20, 10, 200, settle_strategy="fixed_delay_after")
    assert captured["settle_strategy"] == "fixed_delay_after"


# ─── Phone.tap_text → MockEffector.tap end-to-end ────────────────────
@pytest.mark.smoke
def test_phone_tap_text_drives_effector(mock_phone):
    """phone.tap_text('登录') should make effector.tap receive the correct center-point coordinates."""
    # setup: have the mock OCR return a '登录' element with box=(100, 200, 80, 44)
    mock_phone.ocr.elements = [
        UIElement(
            type="text",
            box=Box(x=100, y=200, w=80, h=44),
            text="登录",
            confidence=0.95,
            element_id=0,
        )
    ]

    # one line of a walkthrough script:
    mock_phone.tap_text("登录")

    # verify effector.tap was called, with coordinates = box.center
    last = mock_phone.effector.last()
    assert last is not None, "effector received no action"
    assert last.op == "tap"
    assert last.kwargs == {"x": 140, "y": 222}, (
        f"expected tap(140, 222) (box center), got {last.kwargs}"
    )


@pytest.mark.smoke
def test_target_tap_entrypoints_record_action_plan_contract(mock_phone):
    """P6: high-level tap entrypoints preserve plan metadata in ActionRecord."""

    def assert_last_action(*, x: int, y: int, via: str, target: str) -> None:
        last = mock_phone.effector.last()
        assert last is not None
        assert last.op == "tap"
        assert last.kwargs == {"x": x, "y": y}
        record = mock_phone._pending_actions_for_memory[-1]
        assert record.op == "tap"
        assert record.via == via
        assert record.target == target
        assert record.x == x
        assert record.y == y
        assert record.coordinate_space == "frame_px"
        assert record.params["target_point"] == {"x": x, "y": y, "space": "frame_px"}
        assert record.params["target_point_frame"] == {"x": x, "y": y, "space": "frame_px"}
        assert record.params["actuation_attempt_index"] == 0
        assert record.params["regrounded"] is False
        assert record.params["action_ok"] is True

    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=10, y=20, w=20, h=10), text="Login", confidence=0.95)
    ]
    mock_phone.tap_text("Login")
    assert_last_action(x=20, y=25, via="tap_text", target="Login")

    element = UIElement(type="text", box=Box(x=30, y=40, w=20, h=10), text="Next", confidence=0.95)
    mock_phone.tap_element(element)
    assert_last_action(x=40, y=45, via="tap_element", target="Next")

    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=50, y=60, w=30, h=12), text="Save", confidence=0.95)
    ]
    mock_phone.tap_button("Save")
    assert_last_action(x=65, y=66, via="tap_button", target="Save")

    mock_phone.ocr.elements = [
        UIElement(
            type="button",
            box=Box(x=70, y=80, w=30, h=12),
            text="Pay",
            confidence=0.95,
            intent_label="Confirm Payment",
        )
    ]
    mock_phone.tap_intent("Confirm Payment")
    assert_last_action(x=85, y=86, via="tap_intent", target="Confirm Payment")
    assert mock_phone._pending_actions_for_memory[-1].params["selection_source"] == "vlm"


@pytest.mark.smoke
def test_phone_tap_text_hits_tab_bar_upper_region(mock_phone, monkeypatch):
    """Bottom tab OCR labels sit low; tap the tab's upper hit region instead."""
    monkeypatch.setattr(mock_phone, "_viewport_size", lambda: (448, 973))
    mock_phone.ocr.elements = [
        UIElement(
            type="tab_bar_item",
            box=Box(x=300, y=929, w=22, h=10),
            text="设置",
            confidence=0.95,
            element_id=0,
        )
    ]

    mock_phone.tap_text("设置")

    last = mock_phone.effector.last()
    assert last is not None
    assert last.op == "tap"
    assert last.kwargs == {"x": 311, "y": 885}


@pytest.mark.smoke
def test_phone_tap_text_hits_springboard_icon_not_label(mock_phone, monkeypatch):
    """SpringBoard OCR returns the app label below the icon; tap the icon cell."""
    monkeypatch.setattr(mock_phone, "_viewport_size", lambda: (452, 986))
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=54, y=280, w=38, h=24), text="天气", confidence=0.95),
        UIElement(type="text", box=Box(x=154, y=390, w=38, h=24), text="日历", confidence=0.95),
        UIElement(type="text", box=Box(x=256, y=390, w=38, h=24), text="照片", confidence=0.95),
        UIElement(type="text", box=Box(x=358, y=390, w=38, h=24), text="相机", confidence=0.95),
        UIElement(type="text", box=Box(x=154, y=500, w=38, h=24), text="时钟", confidence=0.95),
        UIElement(type="text", box=Box(x=356, y=500, w=54, h=24), text="App Store", confidence=0.95),
        UIElement(type="text", box=Box(x=154, y=610, w=38, h=24), text="设置", confidence=0.95),
        UIElement(type="text", box=Box(x=200, y=790, w=52, h=24), text="搜索", confidence=0.95),
    ]

    mock_phone.tap_text("设置")

    last = mock_phone.effector.last()
    assert last is not None
    assert last.op == "tap"
    assert last.kwargs == {"x": 173, "y": 566}


@pytest.mark.smoke
def test_phone_tap_text_prefers_row_over_nav_title(mock_phone, monkeypatch):
    """Same text as the centered nav-bar title and a list row → tap the row.

    The nav title is non-interactive; tapping it no-ops (regression seen
    navigating Settings → 通用 → 键盘 → 键盘)."""
    monkeypatch.setattr(mock_phone, "_viewport_size", lambda: (448, 972))
    mock_phone.ocr.elements = [
        # nav-bar title: top band, horizontally centered — comes first in OCR order
        UIElement(type="text", box=Box(x=200, y=70, w=48, h=30),
                  text="键盘", confidence=0.95, element_id=0),
        # tappable list row: lower, left-aligned
        UIElement(type="text", box=Box(x=40, y=150, w=120, h=40),
                  text="键盘", confidence=0.95, element_id=1),
    ]

    mock_phone.tap_text("键盘")

    last = mock_phone.effector.last()
    assert last is not None and last.op == "tap"
    assert last.kwargs == {"x": 100, "y": 170}, (
        f"expected the list row (100,170), got {last.kwargs} — likely the nav title"
    )


@pytest.mark.smoke
def test_phone_action_invalidates_perception_cache(mock_phone):
    """After an action, the next perceive must not reuse the pre-action Scene."""
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=50, h=20),
                  text="设置", confidence=0.9, element_id=0)
    ]
    mock_phone.perceive()
    assert mock_phone.perceive_cache_stats == {"hits": 0, "misses": 1}

    mock_phone.tap_xy(10, 20)
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=80, h=20),
                  text="通用", confidence=0.9, element_id=0)
    ]
    scene = mock_phone.perceive()

    assert [e.text for e in scene.elements] == ["通用"]
    assert mock_phone.perceive_cache_stats == {"hits": 0, "misses": 2}


@pytest.mark.smoke
def test_phone_system_and_gesture_wrappers_drive_effector(mock_phone):
    """Walkthrough-level wrappers should record the expected effector ops."""
    mock_phone._last_frame = Frame(img=np.zeros((200, 100, 3), dtype=np.uint8), ts=0.0)
    mock_phone.home()
    mock_phone.recents()
    mock_phone.control_center()
    mock_phone.notification_center()
    assert mock_phone.swipe_up().ok is True
    mock_phone.swipe_down()
    mock_phone.swipe_left()
    mock_phone.swipe_right()
    assert mock_phone.back_gesture().ok is True
    mock_phone.type("abc", verify=False)  # verify needs OCR; covered separately
    mock_phone.key(0x08, 0x19)
    mock_phone.paste()

    ops = [a.op for a in mock_phone.effector.actions]
    # back_gesture is Cmd+[ (a key action), not a swipe — see Phone.back_gesture.
    assert ops == [
        "home", "recents", "control_center", "notification_center",
        "swipe", "swipe", "drag", "drag", "key", "type", "key", "paste",
    ]
    assert mock_phone.effector.actions[4].kwargs["y1"] > mock_phone.effector.actions[4].kwargs["y2"]
    assert mock_phone.effector.actions[5].kwargs["y1"] < mock_phone.effector.actions[5].kwargs["y2"]
    assert mock_phone.effector.actions[6].kwargs["x1"] > mock_phone.effector.actions[6].kwargs["x2"]
    assert mock_phone.effector.actions[7].kwargs["x1"] < mock_phone.effector.actions[7].kwargs["x2"]
    assert mock_phone.effector.actions[6].kwargs["y1"] == mock_phone.effector.actions[6].kwargs["y2"] == 90
    assert mock_phone.effector.actions[7].kwargs["y1"] == mock_phone.effector.actions[7].kwargs["y2"] == 90
    assert mock_phone.effector.actions[6].kwargs["x1"] == 92
    assert mock_phone.effector.actions[6].kwargs["x2"] == 8
    assert mock_phone.effector.actions[7].kwargs["x1"] == 8
    assert mock_phone.effector.actions[7].kwargs["x2"] == 92
    assert mock_phone.effector.actions[6].kwargs["down_hold_ms"] == 350
    assert mock_phone.effector.actions[6].kwargs["up_hold_ms"] == 150


@pytest.mark.smoke
def test_phone_gesture_wrappers_record_policy_actions(tmp_path, mock_phone):
    from glassbox.obs import Recorder
    from glassbox.obs.recorder import iter_events

    mock_phone._last_frame = Frame(img=np.zeros((200, 100, 3), dtype=np.uint8), ts=0.0)
    mock_phone.recorder = Recorder(tmp_path)

    mock_phone.swipe_up()
    mock_phone.swipe_left()
    mock_phone.back_gesture()
    mock_phone.recorder.close()

    actions = [e for e in iter_events(tmp_path) if e["type"] == "action"]
    assert [(a["via"], a["policy_action"]) for a in actions] == [
        ("swipe_up", "scroll"),
        ("swipe_left", "page"),
        ("back_gesture", "back"),
    ]


@pytest.mark.smoke
def test_switch_input_source_emits_ctrl_space(mock_phone):
    mock_phone.switch_input_source()
    last = mock_phone.effector.last()
    assert last.op == "key"
    assert (last.kwargs["modifier"], last.kwargs["keycode"]) == (0x01, 0x2C)


@pytest.mark.smoke
def test_type_verify_switches_input_source_on_ime_mismatch(mock_phone, monkeypatch):
    """ASCII type sees a CJK candidate bar → cycle IME, clear the field, retype."""
    calls = iter([True, False])  # first: composing detected; second: clean
    monkeypatch.setattr(mock_phone, "_ime_composing", lambda: next(calls))

    mock_phone.type("hello")

    ops = [a.op for a in mock_phone.effector.actions]
    assert ops.count("type") == 2  # original + one retype
    keys = [a for a in mock_phone.effector.actions if a.op == "key"]
    # first key after the mismatch is Ctrl+Space (input-source cycle)
    assert (keys[0].kwargs["modifier"], keys[0].kwargs["keycode"]) == (0x01, 0x2C)


@pytest.mark.smoke
def test_type_cjk_routes_via_clipboard(mock_phone):
    """CJK cannot be HID-typed: route through set_clipboard + paste (⌘V)."""
    mock_phone.type("蓝牙")
    ops = [a.op for a in mock_phone.effector.actions]
    assert ops == ["set_clipboard", "paste"]
    assert mock_phone.effector.actions[0].kwargs["text"] == "蓝牙"


@pytest.mark.smoke
def test_phone_wheel_scroll_wrappers_are_not_swipes(mock_phone):
    mock_phone._last_frame = Frame(img=np.zeros((200, 100, 3), dtype=np.uint8), ts=0.0)

    mock_phone.wheel_scroll_down(ticks=5)
    mock_phone.wheel_scroll_up(ticks=7)

    actions = mock_phone.effector.actions
    assert [a.op for a in actions] == ["scroll_wheel", "scroll_wheel"]
    assert actions[0].kwargs == {
        "ticks": 5,
        "horizontal": 0,
        "interval_ms": 40,
        "focus": True,
        "focus_x": 50,
        "focus_y": 110,
    }
    assert actions[1].kwargs["ticks"] == -7


@pytest.mark.smoke
def test_phone_expect_text_no_effector_call(mock_phone):
    """expect_text is just an assertion; it should not trigger any effector action."""
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=0, y=0, w=50, h=20),
                  text="已登录", confidence=0.9, element_id=0)
    ]
    mock_phone.expect_text("已登录")
    assert len(mock_phone.effector.actions) == 0


@pytest.mark.smoke
def test_phone_expect_text_timeout(mock_phone):
    """expect_text on timeout should raise AssertionError (so pytest marks it red)."""
    mock_phone.ocr.elements = []   # nothing at all
    with pytest.raises(AssertionError, match="expect_text"):
        mock_phone.expect_text("登录", timeout=0.1, poll_interval=0.05)


@pytest.mark.smoke
def test_phone_fuzzy_match(mock_phone):
    """An occasional OCR error ('登陆' instead of '登录') should be hit by fuzzy matching."""
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=10, y=10, w=50, h=20),
                  text="登陆", confidence=0.85, element_id=0)
    ]
    el = mock_phone.find_text("登录", fuzzy_ratio=0.5)
    assert el is not None
    assert el.text == "登陆"


# ─── Effector interface completeness ────────────────────────────────
@pytest.mark.smoke
def test_mock_effector_records_all_ops():
    """MockEffector should fully record all public effector operations."""
    from glassbox.effector import MockEffector

    eff = MockEffector()
    result = eff.tap(100, 200)
    eff.swipe(0, 0, 100, 100, steps=10)
    eff.type("hello")
    eff.key(0x08, 0x19)              # Cmd+V
    eff.home()
    eff.recents()
    eff.control_center()
    eff.notification_center()
    eff.paste()
    eff.long_press(50, 50, hold_ms=800)
    eff.double_tap(60, 60)
    eff.drag(0, 0, 100, 100)
    eff.scroll_wheel(-3, horizontal=1, interval_ms=7)

    ops = [a.op for a in eff.actions]
    assert ops == [
        "tap", "swipe", "type", "key", "home", "recents",
        "control_center", "notification_center",
        "paste", "long_press", "double_tap", "drag", "scroll_wheel",
    ]
    assert result.ok is True
    assert result.backend == "mock"
    assert result.synthetic is False
    assert eff.actions[0].result == result


@pytest.mark.smoke
def test_effector_capabilities_reject_unknown_actions():
    from glassbox.effector import EFFECTOR_ACTIONS, MockEffector, NoOpEffector

    mock = MockEffector()
    noop = NoOpEffector()

    for action in EFFECTOR_ACTIONS:
        assert mock.supports(action) is True
    for action in ("launch_app", "taptext", "touch_swipe"):
        assert mock.supports(action) is False
        assert noop.supports(action) is False


@pytest.mark.smoke
def test_noop_effector_safe_when_no_bridge():
    """With no bridge, all NoOpEffector methods do not raise, and is_connected is False."""
    from glassbox.effector import NoOpEffector

    eff = NoOpEffector()
    assert eff.is_connected() is False
    # no method should raise
    result = eff.tap(1, 2)
    eff.swipe(0, 0, 1, 1)
    eff.type("x")
    eff.key(0, 0)
    eff.home()
    eff.control_center()
    eff.notification_center()
    eff.scroll_wheel(1)
    eff.connect()                    # idempotent
    eff.close()
    assert result.ok is False
    assert result.backend == "noop"
    assert result.connected is False


@pytest.mark.smoke
def test_phone_records_action_result_status(tmp_path, mock_phone):
    from glassbox.obs import Recorder
    from glassbox.obs.recorder import iter_events

    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.tap_xy(10, 20)
    mock_phone.recorder.close()

    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert action["action_ok"] is True
    assert action["action_backend"] == "mock"
    assert action["action_connected"] is True
    assert action["action_synthetic"] is False
    assert action["coordinate_space"] == "frame_px"


@pytest.mark.smoke
def test_phone_records_failed_action_when_effector_raises(tmp_path, mock_phone):
    from glassbox.obs import Recorder
    from glassbox.obs.recorder import iter_events

    class RaisingEffector:
        coordinate_space = "frame_px"

        def is_connected(self):
            return True

        def supports(self, action):
            return True

        def tap(self, x, y):
            raise RuntimeError("tap failed")

    mock_phone.effector = RaisingEffector()
    mock_phone.recorder = Recorder(tmp_path)

    with pytest.raises(RuntimeError, match="tap failed"):
        mock_phone.tap_xy(10, 20)
    mock_phone.recorder.close()

    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert action["action_ok"] is False
    assert action["action_error"] == "RuntimeError: tap failed"
    assert action["action_synthetic"] is False
    assert mock_phone._cache_scene is None


@pytest.mark.smoke
def test_phone_scroll_wheel_records_unsupported_without_call(tmp_path, mock_phone):
    from glassbox.obs import Recorder
    from glassbox.obs.recorder import iter_events

    class NoWheelEffector:
        coordinate_space = "frame_px"
        called = False

        def is_connected(self):
            return True

        def supports(self, action):
            return action != "scroll_wheel"

        def scroll_wheel(self, *args, **kwargs):
            self.called = True
            raise AssertionError("should not call unsupported wheel")

    eff = NoWheelEffector()
    mock_phone.effector = eff
    mock_phone._last_frame = Frame(img=np.zeros((200, 100, 3), dtype=np.uint8), ts=0.0)
    mock_phone.recorder = Recorder(tmp_path)

    result = mock_phone.scroll_wheel(5)
    mock_phone.recorder.close()

    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert result.ok is False
    assert result.unsupported is True
    assert action["action_unsupported"] is True
    assert eff.called is False


@pytest.mark.smoke
def test_phone_fail_fast_raises_after_recording_failed_result(tmp_path, mock_phone):
    from glassbox.obs import Recorder
    from glassbox.obs.recorder import iter_events

    class FailingEffector:
        coordinate_space = "frame_px"

        def is_connected(self):
            return False

        def supports(self, action):
            return False

    mock_phone.effector = FailingEffector()
    mock_phone.action_fail_fast = True
    mock_phone._last_frame = Frame(img=np.zeros((200, 100, 3), dtype=np.uint8), ts=0.0)
    mock_phone.recorder = Recorder(tmp_path)

    with pytest.raises(RuntimeError, match="unsupported action"):
        mock_phone.scroll_wheel(5)
    mock_phone.recorder.close()

    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert action["action_ok"] is False
    assert action["action_unsupported"] is True
