from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.cognition.contracts import SceneClassification
from glassbox.effector import ActionResult
from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.effectors.picokvm.effector import PicoKVMEffector
from glassbox.effectors.picokvm.rpc import PicoKVMRpcResponse
from glassbox.perception.source import Frame
from glassbox.phone import Phone
from glassbox.platforms import IOSPlatform


class FakeRpc:
    def __init__(self):
        self.calls = []
        self.next_id = 0

    def ping(self):
        return self.call("ping")

    def close(self):
        pass

    def call(self, method, params=None):
        self.next_id += 1
        self.calls.append((method, params))
        if method == "getDeviceID":
            return PicoKVMRpcResponse(id=self.next_id, result="unit-device")
        if method == "getVideoState":
            return PicoKVMRpcResponse(id=self.next_id, result={"ready": True})
        return PicoKVMRpcResponse(id=self.next_id, result=None)


def make_eff(*, wheel_enabled=False, semantic_verify_enabled=False):
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(
        _env_file=None,
        wheel_enabled=wheel_enabled,
        semantic_verify_enabled=semantic_verify_enabled,
        click_move_settle_ms=0,
        click_press_ms=0,
        long_press_min_hold_ms=0,
        keyboard_focus_click_ms=0,
        keyboard_shortcut_gap_ms=0,
        semantic_verify_delay_ms=0,
        semantic_verify_timeout_ms=200,
        semantic_verify_sample_interval_ms=1,
    )
    return PicoKVMEffector(config=cfg, rpc=rpc), rpc


class SequenceOCR:
    def __init__(self, snapshots: list[list[str]]):
        self.snapshots = list(snapshots)
        self.calls = 0

    def recognize(self, _image):
        idx = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return [
            UIElement(
                type="text",
                box=Box(x=0, y=i * 12, w=120, h=10),
                text=text,
                confidence=0.95,
                element_id=i,
            )
            for i, text in enumerate(self.snapshots[idx])
        ]


class FreshFrameSource:
    resolution = (100, 100)

    def __init__(self):
        self.opens = 0
        self.closes = 0
        self.snapshots = 0

    def open(self):
        self.opens += 1

    def close(self):
        self.closes += 1

    def snapshot(self):
        self.snapshots += 1
        return Frame(img=np.full((100, 100, 3), self.snapshots, dtype=np.uint8), ts=float(self.snapshots))


def logical_fraction(value: float) -> int:
    return round(value * 32767)


def ios_scene_classifier():
    return IOSPlatform().scene_classifier


@pytest.mark.smoke
def test_picokvm_effector_preflight_and_supports():
    eff, rpc = make_eff()

    assert eff.preflight().ok is True
    assert ("getDeviceID", None) in rpc.calls
    assert eff.supports("tap") is True
    assert eff.supports("set_clipboard") is False
    assert eff.supports("control_center") is False
    assert eff.supports("home") is True
    assert eff.supports("back_gesture") is True
    assert eff.supports("close_foreground_app") is True
    assert eff.supports("list_scroll_up") is True
    assert eff.supports("page_slide_left") is True
    assert eff.supports("paste") is False
    assert eff.supports("scroll_wheel") is False
    assert eff.capabilities().home_strategy == "keyboard_combo"
    assert eff.capabilities().back_strategy == "keyboard_combo"
    assert eff.capabilities().paste_strategy == "unsupported"
    assert eff.capabilities().switch_input_source_strategy == "unsupported"
    assert eff.capabilities().requires_assistive_touch is True


@pytest.mark.smoke
def test_picokvm_tap_uses_absolute_mouse_down_up_sequence():
    eff, rpc = make_eff()

    result = eff.tap(960, 540)

    assert result.ok is True
    assert result.backend == "picokvm"
    assert [name for name, _ in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]
    assert [params["buttons"] for _, params in rpc.calls] == [0, 0, 1, 0]
    assert all(0 <= params["x"] <= 32767 and 0 <= params["y"] <= 32767 for _, params in rpc.calls)


@pytest.mark.smoke
def test_picokvm_rejects_phone_px_coordinate_space():
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(_env_file=None)
    geometry = SimpleNamespace(phone_size=(1320, 2868))
    eff = PicoKVMEffector(config=cfg, rpc=rpc, coordinate_space="phone_px", device_geometry=geometry)

    result = eff.tap(660, 1434)

    assert result.ok is False
    assert result.error == "tap: picokvm_coordinate_space_unsupported:phone_px"
    assert rpc.calls == []


@pytest.mark.smoke
def test_picokvm_drag_uses_settled_pointer_down_sequence():
    eff, rpc = make_eff()

    result = eff.drag(100, 200, 300, 500, down_hold_ms=0, up_hold_ms=0)

    assert result.ok is True
    assert [params["buttons"] for _, params in rpc.calls[:3]] == [0, 0, 1]
    assert rpc.calls[0] == rpc.calls[1]
    assert rpc.calls[-1][1]["buttons"] == 0
    assert len(rpc.calls) == 24


@pytest.mark.smoke
def test_picokvm_long_press_uses_settled_pointer_down_sequence():
    eff, rpc = make_eff()

    result = eff.long_press(100, 200, hold_ms=0)

    assert result.ok is True
    assert [params["buttons"] for _, params in rpc.calls] == [0, 0, 1, 0]
    assert rpc.calls[0] == rpc.calls[1]
    assert rpc.calls[2][1]["buttons"] == 1
    assert rpc.calls[-1][1]["buttons"] == 0


@pytest.mark.smoke
def test_picokvm_long_press_clamps_to_configured_minimum(monkeypatch):
    eff, _rpc = make_eff()
    eff.config.long_press_min_hold_ms = 1500
    sleeps = []
    monkeypatch.setattr(eff, "_sleep_ms", lambda ms: sleeps.append(ms))

    result = eff.long_press(100, 200, hold_ms=900)

    assert result.ok is True
    assert sleeps == [0, 1500]


@pytest.mark.smoke
def test_picokvm_double_tap_repeats_settled_click_shape():
    eff, rpc = make_eff()

    result = eff.double_tap(100, 200)

    assert result.ok is True
    assert [params["buttons"] for _, params in rpc.calls] == [0, 0, 1, 0, 0, 0, 1, 0]
    assert rpc.calls[0:4] == rpc.calls[4:8]


@pytest.mark.smoke
def test_picokvm_close_foreground_app_uses_captured_home_indicator_drag():
    eff, rpc = make_eff()

    result = eff.close_foreground_app()

    assert result.ok is True
    assert [params["buttons"] for _, params in rpc.calls[:3]] == [0, 0, 1]
    assert rpc.calls[0] == ("absMouseReport", {"x": 16102, "y": 32506, "buttons": 0})
    assert rpc.calls[1] == rpc.calls[0]
    assert rpc.calls[2] == ("absMouseReport", {"x": 16102, "y": 32506, "buttons": 1})
    assert rpc.calls[-1] == ("absMouseReport", {"x": 16728, "y": 651, "buttons": 0})
    assert len(rpc.calls) == 24


@pytest.mark.smoke
def test_picokvm_list_scroll_presets_use_raw_logical_trajectories():
    eff, rpc = make_eff()

    result = eff.list_scroll_up()

    assert result.ok is True
    expected_x = logical_fraction(0.50)
    assert rpc.calls[0] == ("absMouseReport", {"x": expected_x, "y": logical_fraction(0.78), "buttons": 0})
    assert rpc.calls[2] == ("absMouseReport", {"x": expected_x, "y": logical_fraction(0.78), "buttons": 1})
    assert rpc.calls[-1] == ("absMouseReport", {"x": expected_x, "y": logical_fraction(0.23), "buttons": 0})
    assert len(rpc.calls) == 24

    rpc.calls.clear()
    result = eff.list_scroll_down()

    assert result.ok is True
    assert rpc.calls[0] == ("absMouseReport", {"x": expected_x, "y": logical_fraction(0.23), "buttons": 0})
    assert rpc.calls[-1] == ("absMouseReport", {"x": expected_x, "y": logical_fraction(0.78), "buttons": 0})


@pytest.mark.smoke
def test_picokvm_page_slide_presets_use_raw_logical_trajectories():
    eff, rpc = make_eff()

    result = eff.page_slide_left()

    assert result.ok is True
    expected_y = logical_fraction(0.45)
    assert rpc.calls[0] == ("absMouseReport", {"x": logical_fraction(0.92), "y": expected_y, "buttons": 0})
    assert rpc.calls[-1] == ("absMouseReport", {"x": logical_fraction(0.08), "y": expected_y, "buttons": 0})
    assert len(rpc.calls) == 24

    rpc.calls.clear()
    result = eff.page_slide_right()

    assert result.ok is True
    assert rpc.calls[0] == ("absMouseReport", {"x": logical_fraction(0.08), "y": expected_y, "buttons": 0})
    assert rpc.calls[-1] == ("absMouseReport", {"x": logical_fraction(0.92), "y": expected_y, "buttons": 0})


@pytest.mark.smoke
def test_phone_swipes_use_picokvm_raw_logical_drag_presets():
    eff, rpc = make_eff()
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False)

    result = phone.swipe_up()

    assert result.ok is True
    assert rpc.calls[0] == (
        "absMouseReport",
        {"x": logical_fraction(0.50), "y": logical_fraction(0.78), "buttons": 0},
    )
    assert rpc.calls[-1] == (
        "absMouseReport",
        {"x": logical_fraction(0.50), "y": logical_fraction(0.23), "buttons": 0},
    )

    rpc.calls.clear()
    result = phone.swipe_left()

    assert result.ok is True
    assert rpc.calls[0] == (
        "absMouseReport",
        {"x": logical_fraction(0.92), "y": logical_fraction(0.45), "buttons": 0},
    )
    assert rpc.calls[-1] == (
        "absMouseReport",
        {"x": logical_fraction(0.08), "y": logical_fraction(0.45), "buttons": 0},
    )


@pytest.mark.smoke
def test_picokvm_type_ascii_emits_press_release_reports():
    eff, rpc = make_eff()

    result = eff.type("aA")

    assert result.ok is True
    assert rpc.calls == [
        ("keyboardReport", {"modifier": 0, "keys": [0x04]}),
        ("keyboardReport", {"modifier": 0, "keys": []}),
        ("keyboardReport", {"modifier": 0x02, "keys": [0x04]}),
        ("keyboardReport", {"modifier": 0, "keys": []}),
    ]


@pytest.mark.smoke
def test_picokvm_rejects_non_ascii_type_as_unsupported():
    eff, _rpc = make_eff()

    result = eff.type("蓝")

    assert result.ok is False
    assert result.unsupported is True


@pytest.mark.smoke
def test_picokvm_type_reports_partial_when_late_character_is_unsupported():
    eff, rpc = make_eff()

    result = eff.type("A蓝")

    assert result.ok is False
    assert result.unsupported is True
    assert result.partial is True
    assert result.executed_count == 2
    assert result.ack_seqs == (1, 2)
    assert rpc.calls == [
        ("keyboardReport", {"modifier": 0x02, "keys": [0x04]}),
        ("keyboardReport", {"modifier": 0, "keys": []}),
    ]


@pytest.mark.smoke
def test_picokvm_wheel_defaults_to_unsupported_but_experimental_path_primes_pointer():
    eff, rpc = make_eff()
    disabled = eff.scroll_wheel(3)
    assert disabled.ok is False
    assert disabled.unsupported is True

    eff, rpc = make_eff(wheel_enabled=True)
    enabled = eff.scroll_wheel(2, interval_ms=0, focus_x=960, focus_y=540)
    assert enabled.ok is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 1}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("wheelReport", {"wheelY": -1}),
        ("wheelReport", {"wheelY": -1}),
        ("wheelReport", {"wheelY": 0}),
    ]


@pytest.mark.smoke
def test_picokvm_experimental_wheel_uses_captured_focus_click_when_no_focus_point():
    eff, rpc = make_eff(wheel_enabled=True)

    enabled = eff.scroll_wheel(1, interval_ms=0)

    assert enabled.ok is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 1}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("wheelReport", {"wheelY": -1}),
        ("wheelReport", {"wheelY": 0}),
    ]


@pytest.mark.smoke
def test_phone_home_defaults_to_meta_h_for_picokvm():
    eff, rpc = make_eff()
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False)

    result = phone.home()

    assert result.ok is True
    assert phone.supports("home") is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 1}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [0x0B], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [0x0B], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0}),
    ]
    assert eff.recents().ok is False
    assert eff.recents().unsupported is True
    assert eff.paste().ok is False
    assert eff.paste().unsupported is True
    back = phone.back_gesture()
    assert back.ok is False
    assert back.unsupported is True
    assert back.error == "unsupported action: back_gesture"
    paste = phone.paste()
    assert paste.ok is False
    assert paste.unsupported is True
    assert paste.error == "unsupported action: paste"
    switch = phone.switch_input_source()
    assert switch.ok is False
    assert switch.unsupported is True
    assert switch.error == "unsupported action: switch_input_source"
    assert phone.supports("home") is True
    assert phone.supports("recents") is False
    assert phone.supports("back_gesture") is True
    assert phone.supports("paste") is False
    assert phone.supports("switch_input_source") is False


@pytest.mark.smoke
def test_phone_home_can_use_assistive_touch_when_enabled(monkeypatch):
    eff, rpc = make_eff()
    eff.config.assistive_touch_home_enabled = True
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False)
    calls = []

    def fake_assistive_touch_home(label, **kwargs):
        calls.append((label, kwargs))
        return ActionResult(ok=True, backend="picokvm", connected=True)

    monkeypatch.setattr(phone, "assistive_touch_tap_menu_item", fake_assistive_touch_home)

    result = phone.home()

    assert result.ok is True
    assert calls == [(
        "主屏幕",
        {
            "open_menu": True,
            "settle_s": 0.9,
            "primitive_name": "assistive_touch.home",
        },
    )]
    assert not any(method == "keyboardReport" for method, _params in rpc.calls)
    assert phone.supports("home") is True
    assert phone.supports("recents") is False


@pytest.mark.smoke
def test_phone_home_can_use_meta_h_when_assistive_touch_home_is_disabled():
    eff, rpc = make_eff()
    eff.config.keyboard_home_enabled = True
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False)

    result = phone.home()

    assert result.ok is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 1}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [0x0B], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [0x0B], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0}),
    ]
    assert phone.supports("home") is True


@pytest.mark.smoke
def test_phone_back_can_use_picokvm_focus_primer_meta_left_bracket_when_enabled():
    eff, rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["通知", "返回", "允许通知"]])

    def back_allowed(_scene, _viewport_size):
        return SceneClassification(
            page_id="custom/child",
            platform_scene_kind="custom_back_surface",
            confidence=0.9,
            source="platform",
            safe_actions=("back", "edge_back"),
        )

    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        scene_classifiers=[back_allowed],
    )

    result = phone.back_gesture()

    assert result.ok is True
    assert phone.supports("back_gesture") is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 1}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [0x2F], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0x08}),
        ("keyboardReport", {"keys": [], "modifier": 0}),
    ]


@pytest.mark.smoke
def test_phone_back_can_use_injected_platform_scene_classifier_for_picokvm_guard():
    eff, rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["通知", "允许通知", "通知分组", "显示预览"]])

    class PlatformClassifier:
        def __init__(self):
            self.calls = []

        def classify(self, scene, *, viewport_size=None):
            self.calls.append((scene, viewport_size))
            return SceneClassification(
                page_id="settings/通知",
                platform_scene_kind="settings_detail",
                confidence=0.9,
                source="platform",
                safe_actions=("back", "edge_back"),
            )

    classifier = PlatformClassifier()
    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=classifier,
    )

    result = phone.back_gesture()

    assert result.ok is True
    assert classifier.calls
    assert classifier.calls[0][1] == (100, 100)
    assert any(method == "absMouseReport" and params["buttons"] == 1 for method, params in rpc.calls)


@pytest.mark.smoke
def test_phone_back_guard_keeps_platform_settings_detail_reason_after_projection(monkeypatch):
    eff, _rpc = make_eff()
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False)
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        platform_scene_kind="settings_detail",
        safe_actions=["back", "edge_back"],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    allowed, reason, point = phone._picokvm_back_context()

    assert allowed is True
    assert reason == "platform_settings_detail"
    assert point == (40, 89)


@pytest.mark.smoke
def test_phone_back_rejects_picokvm_meta_left_bracket_without_parent_page():
    eff, rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["设置", "通用", "通知"]])

    def no_back(_scene, _viewport_size):
        return SceneClassification(
            page_id="settings/root",
            platform_scene_kind="settings_root",
            confidence=0.9,
            source="platform",
            safe_actions=("tap_root_row", "scroll"),
        )

    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        scene_classifiers=[no_back],
    )

    result = phone.back_gesture()

    assert result.ok is False
    assert result.unsupported is True
    assert result.error == "unsupported action: back_gesture"
    assert phone.supports("back_gesture") is True
    assert not any(method == "keyboardReport" for method, _params in rpc.calls)
    assert not any(method == "absMouseReport" for method, _params in rpc.calls)


@pytest.mark.smoke
def test_phone_back_guard_tolerates_missing_platform_scene_classifier():
    eff, _rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["通知", "允许通知", "通知分组", "显示预览"]])
    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=None,
    )

    result = phone.back_gesture()

    assert result.ok is False
    assert result.unsupported is True
    assert result.error == "unsupported action: back_gesture"


@pytest.mark.smoke
def test_phone_back_allows_picokvm_settings_detail_classifier_fallback_without_nav_ocr(monkeypatch):
    eff, rpc = make_eff()
    phone = Phone(
        source=object(),
        ocr=object(),
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=ios_scene_classifier(),
    )
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=374, y=84, w=36, h=18), text="编辑", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=236, w=108, h=26), text="无线局域网", confidence=0.9),
            UIElement(
                type="text",
                box=Box(x=40, y=268, w=360, h=22),
                text="接入无线局域网、查看可用网络，并管理加入网",
                confidence=0.9,
            ),
            UIElement(type="text", box=Box(x=38, y=290, w=258, h=22), text="络及附近热点设置。进一步了解…", confidence=0.9),
            UIElement(type="text", box=Box(x=58, y=398, w=52, h=18), text="kacier", confidence=0.9),
            UIElement(type="text", box=Box(x=38, y=462, w=72, h=20), text="我的网络", confidence=0.9),
            UIElement(type="text", box=Box(x=58, y=509, w=90, h=24), text="kacier_iptv", confidence=0.9),
            UIElement(type="text", box=Box(x=40, y=576, w=68, h=18), text="其他网络", confidence=0.9),
            UIElement(type="text", box=Box(x=58, y=624, w=90, h=22), text="kacier_aiot", confidence=0.9),
            UIElement(type="text", box=Box(x=58, y=732, w=162, h=22), text="minii_washer_r_91f0", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_phone_back_allows_picokvm_about_page_classifier_fallback_without_nav_ocr(monkeypatch):
    eff, rpc = make_eff()
    phone = Phone(
        source=object(),
        ocr=object(),
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=ios_scene_classifier(),
    )
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=200, y=84, w=92, h=18), text="关于本机", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=216, w=36, h=18), text="名称", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=270, w=68, h=18), text="iOS版本", confidence=0.9),
            UIElement(type="text", box=Box(x=40, y=324, w=68, h=18), text="型号名称", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=378, w=36, h=18), text="型号", confidence=0.9),
            UIElement(type="text", box=Box(x=40, y=432, w=54, h=18), text="序列号", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=522, w=68, h=18), text="有限保修", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=828, w=54, h=18), text="总容量", confidence=0.9),
            UIElement(type="button", box=Box(x=40, y=882, w=68, h=18), text="可用容量", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_phone_back_allows_picokvm_software_update_classifier_fallback_without_nav_ocr(monkeypatch):
    eff, rpc = make_eff()
    phone = Phone(
        source=object(),
        ocr=object(),
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=ios_scene_classifier(),
    )
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=186, y=84, w=86, h=18), text="软件更新", confidence=0.9),
            UIElement(type="button", box=Box(x=42, y=162, w=74, h=20), text="自动更新", confidence=0.9),
            UIElement(type="text", box=Box(x=352, y=162, w=54, h=20), text="打开＞", confidence=0.9),
            UIElement(type="button", box=Box(x=156, y=570, w=138, h=20), text="iOS已是最新版本", confidence=0.9),
            UIElement(type="text", box=Box(x=190, y=598, w=74, h=18), text="IOS 26.5", confidence=0.9),
            UIElement(type="text", box=Box(x=178, y=636, w=92, h=18), text="更多详细信息", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_phone_back_allows_picokvm_iphone_storage_classifier_fallback_without_nav_ocr(monkeypatch):
    eff, rpc = make_eff()
    phone = Phone(
        source=object(),
        ocr=object(),
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=ios_scene_classifier(),
    )
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=172, y=84, w=110, h=18), text="iPhone储存空间", confidence=0.9),
            UIElement(type="text", box=Box(x=44, y=178, w=52, h=18), text="iPhone", confidence=0.9),
            UIElement(type="text", box=Box(x=258, y=178, w=156, h=18), text="已使用27.43 GB/512 GB", confidence=0.9),
            UIElement(type="text", box=Box(x=196, y=210, w=74, h=18), text="484.57 GB", confidence=0.9),
            UIElement(type="text", box=Box(x=100, y=236, w=176, h=18), text="应用程序 iOS •系统数据", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=292, w=36, h=18), text="推荐", confidence=0.9),
            UIElement(type="button", box=Box(x=80, y=346, w=138, h=20), text="卸载未使用的App", confidence=0.9),
            UIElement(type="text", box=Box(x=352, y=490, w=36, h=18), text="大小", confidence=0.9),
            UIElement(type="button", box=Box(x=80, y=546, w=54, h=20), text="库乐队", confidence=0.9),
            UIElement(type="text", box=Box(x=342, y=546, w=58, h=18), text="1.76 GB", confidence=0.9),
            UIElement(type="button", box=Box(x=80, y=600, w=92, h=20), text="iMovie 剪辑", confidence=0.9),
            UIElement(type="text", box=Box(x=336, y=600, w=68, h=18), text="673.4 MB", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_phone_back_allows_picokvm_health_data_classifier_fallback_without_nav_ocr(monkeypatch):
    eff, rpc = make_eff()
    phone = Phone(
        source=object(),
        ocr=object(),
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=ios_scene_classifier(),
    )
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=190, y=84, w=74, h=18), text="健康数据", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=158, w=96, h=20), text="医疗详细信息", confidence=0.9),
            UIElement(type="button", box=Box(x=42, y=204, w=96, h=20), text="健康详细信息", confidence=0.9),
            UIElement(type="button", box=Box(x=42, y=258, w=82, h=20), text="医疗急救卡", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=324, w=36, h=18), text="数据", confidence=0.9),
            UIElement(type="button", box=Box(x=42, y=370, w=114, h=20), text="数据访问与设备", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_phone_back_prefers_visible_nav_back_tap_on_picokvm(monkeypatch):
    eff, rpc = make_eff()
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False)
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="nav_back", box=Box(x=34, y=80, w=16, h=18), text="<", confidence=0.9),
            UIElement(type="button", box=Box(x=190, y=80, w=74, h=18), text="健康数据", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=158, w=96, h=20), text="医疗详细信息", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    assert result.backend == "picokvm"
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_picokvm_meta_h_home_gets_fresh_frame_semantic_verification():
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    eff.config.keyboard_home_enabled = True
    source = FreshFrameSource()
    ocr = SequenceOCR([["天气", "日历", "照片", "App Store"]])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)

    result = phone.home()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "ios_home_screen_visible"
    assert "home screen" in (result.semantic_reason or "")
    assert source.closes == 1
    assert source.opens == 1


@pytest.mark.smoke
def test_picokvm_meta_h_home_reports_failed_semantic_when_fresh_frame_is_not_home():
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    eff.config.keyboard_home_enabled = True
    source = FreshFrameSource()
    ocr = SequenceOCR([["设置", "通用", "通知"]])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)

    result = phone.home()

    assert result.ok is True
    assert result.semantic_status == "failed"
    assert result.semantic_verifier == "ios_home_screen_visible"


@pytest.mark.smoke
def test_picokvm_home_falls_back_to_assistive_touch_when_meta_h_does_not_reach_home(monkeypatch):
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    eff.config.keyboard_home_enabled = True
    eff.config.semantic_verify_timeout_ms = 1
    eff.config.semantic_verify_sample_interval_ms = 100
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["设置", "通用", "通知"],                 # keyboard Cmd-H verify -> not home
        ["天气", "日历", "照片", "App Store"],     # AssistiveTouch menu Home verify -> home
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)
    at_calls: list[tuple] = []
    monkeypatch.setattr(
        phone,
        "assistive_touch_tap_menu_item",
        lambda *a, **k: (at_calls.append((a, k)), ActionResult(ok=True, backend="picokvm", connected=True))[1],
    )
    drag_calls: list[int] = []
    monkeypatch.setattr(
        eff,
        "close_foreground_app",
        lambda: (drag_calls.append(1), ActionResult(ok=True, backend="picokvm", connected=True))[1],
    )

    result = phone.home()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "ios_home_screen_visible"
    assert len(at_calls) == 1            # pure-pointer AssistiveTouch menu Home was used
    assert drag_calls == []              # reliable AssistiveTouch path avoids the indicator drag


@pytest.mark.smoke
def test_picokvm_home_falls_back_to_indicator_drag_when_pointer_home_does_not_reach_home(monkeypatch):
    eff, rpc = make_eff(semantic_verify_enabled=True)
    eff.config.keyboard_home_enabled = True
    eff.config.semantic_verify_timeout_ms = 1
    eff.config.semantic_verify_sample_interval_ms = 100
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["“照片”新功能", "继续"],                 # keyboard Cmd-H verify -> not home
        ["设置", "通用", "通知"],                 # AssistiveTouch menu Home verify -> not home
        ["天气", "日历", "照片", "App Store"],     # indicator drag verify -> home
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)
    # AssistiveTouch is attempted first; force it to miss so the chain falls
    # through to the home-indicator drag.
    monkeypatch.setattr(
        phone,
        "assistive_touch_tap_menu_item",
        lambda *a, **k: ActionResult(ok=True, backend="picokvm", connected=True),
    )

    result = phone.home()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "ios_home_screen_visible"
    # the indicator drag (close_foreground_app) ran: its captured start point appears
    assert any(
        method == "absMouseReport" and params.get("x") == 16102 and params.get("y") == 32506
        for method, params in rpc.calls
    )


@pytest.mark.smoke
def test_picokvm_meta_h_home_polls_until_fresh_frame_semantic_succeeds():
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    eff.config.keyboard_home_enabled = True
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["设置", "通用", "通知"],
        ["设置", "通用", "通知"],
        ["天气", "日历", "照片", "App Store"],
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)

    result = phone.home()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "ios_home_screen_visible"
    assert source.closes >= 3
    assert source.opens >= 3


@pytest.mark.smoke
def test_picokvm_back_gets_fresh_frame_progress_verification():
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["通知", "允许通知"],
        ["设置", "通用", "通知"],
    ])

    def back_allowed(scene, _viewport_size):
        texts = {str(el.text) for el in scene.elements if el.text}
        if "允许通知" not in texts:
            return SceneClassification(
                page_id="settings/root",
                platform_scene_kind="settings_root",
                confidence=0.9,
                source="platform",
                safe_actions=(),
            )
        return SceneClassification(
            page_id="settings/notifications",
            platform_scene_kind="settings_detail",
            confidence=0.9,
            source="platform",
            safe_actions=("back", "edge_back"),
        )

    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        scene_classifiers=[back_allowed],
    )
    phone.perceive()

    result = phone.back_gesture()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "navigation_back"
    assert "changed" in (result.semantic_reason or "")


@pytest.mark.smoke
def test_picokvm_close_foreground_app_gets_fresh_frame_progress_verification():
    eff, rpc = make_eff(semantic_verify_enabled=True)
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["设置", "通用", "通知"],
        ["天气", "日历", "照片", "App Store"],
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)
    phone.perceive()

    result = phone.close_foreground_app()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "scene_progressed"
    assert rpc.calls[0] == ("absMouseReport", {"x": 16102, "y": 32506, "buttons": 0})
    assert rpc.calls[-1] == ("absMouseReport", {"x": 16728, "y": 651, "buttons": 0})


@pytest.mark.smoke
def test_picokvm_target_tap_gets_fresh_frame_effect_verification():
    eff, rpc = make_eff(semantic_verify_enabled=True)
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["设置"],
        ["通用", "关于本机"],
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)

    result = phone.tap_text("设置")

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "tap_target_effect"
    assert "changed" in (result.semantic_reason or "")
    assert source.closes >= 1
    assert source.opens >= 1
    assert rpc.calls[0][0] == "absMouseReport"


@pytest.mark.smoke
def test_picokvm_settings_rows_prefer_row_center_hit_point():
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    source = FreshFrameSource()
    ocr = SequenceOCR([["设置", "通用"]])

    def settings_root(_scene, _viewport_size):
        return SceneClassification(
            page_id="settings/root",
            platform_scene_kind="settings_root",
            confidence=0.9,
            source="platform",
            safe_actions=("tap_root_row", "scroll"),
        )

    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        scene_classifiers=[settings_root],
    )
    scene = phone.perceive()
    row = next(element for element in scene.elements if element.text == "通用")
    row.type = "list_item"
    row.box = Box(x=8, y=72, w=8, h=4)
    row.preferred_tap_point = (8, 68)

    assert phone._tap_point_for_element(row) == (50, 74)


@pytest.mark.smoke
def test_phone_tap_uses_platform_scene_classifier_for_unprojected_settings_row():
    eff, _rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["通用"]])

    class PlatformClassifier:
        def classify(self, _scene, *, viewport_size=None):
            assert viewport_size == (100, 100)
            return SceneClassification(
                page_id="settings/root",
                platform_scene_kind="settings_root",
                confidence=0.9,
                source="platform",
                safe_actions=("tap_root_row",),
            )

    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=PlatformClassifier(),
    )
    scene = phone.perceive()
    row = next(element for element in scene.elements if element.text == "通用")
    row.type = "list_item"
    row.box = Box(x=8, y=72, w=8, h=4)
    row.preferred_tap_point = (8, 68)

    assert phone._tap_point_for_element(row) == (50, 74)


@pytest.mark.smoke
def test_phone_tap_tolerates_missing_platform_scene_classifier_for_unprojected_scene():
    eff, _rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["通用"]])
    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=False,
        platform_scene_classifier=None,
    )
    scene = phone.perceive()
    row = next(element for element in scene.elements if element.text == "通用")
    row.type = "list_item"
    row.box = Box(x=8, y=72, w=8, h=4)
    row.preferred_tap_point = (8, 68)

    assert phone._tap_point_for_element(row) == (8, 68)


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("method", "expected_op"),
    [
        ("tap_xy", "tap"),
        ("double_tap_xy", "double_tap"),
        ("long_press_xy", "long_press"),
    ],
)
def test_picokvm_coordinate_pointer_actions_get_fresh_frame_effect_verification(method, expected_op):
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["设置", "通用"],
        ["通用", "关于本机"],
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)
    phone.perceive()

    action = getattr(phone, method)
    result = action(10, 20, hold_ms=1500) if method == "long_press_xy" else action(10, 20)

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "tap_target_effect"
    assert "changed" in (result.semantic_reason or "")


@pytest.mark.smoke
def test_picokvm_text_long_press_preserves_target_for_verification():
    eff, _rpc = make_eff(semantic_verify_enabled=True)
    source = FreshFrameSource()
    ocr = SequenceOCR([
        ["天气", "日历", "相机", "App Store"],
        ["天气", "日历", "相机", "App Store"],
    ])
    phone = Phone(source=source, ocr=ocr, effector=eff, action_fail_fast=False)
    phone.perceive()

    result = phone.long_press_xy(10, 20, hold_ms=1500, target="相机")

    assert result.ok is True
    assert result.semantic_status == "unknown"
    assert result.semantic_verifier == "tap_target_effect"
    assert "target label still visible" in (result.semantic_reason or "")
