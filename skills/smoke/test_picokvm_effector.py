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


def make_eff(*, wheel_enabled=False, semantic_verify_enabled=False, device_geometry=None, crop=None):
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(
        _env_file=None,
        wheel_enabled=wheel_enabled,
        semantic_verify_enabled=semantic_verify_enabled,
        click_move_settle_ms=0,
        click_press_ms=0,
        long_press_min_hold_ms=0,
        keyboard_focus_click_ms=0,
        keyboard_type_key_gap_ms=0,
        keyboard_shortcut_gap_ms=0,
        semantic_verify_delay_ms=0,
        semantic_verify_timeout_ms=200,
        semantic_verify_sample_interval_ms=1,
    )
    return PicoKVMEffector(config=cfg, rpc=rpc, device_geometry=device_geometry, crop=crop), rpc


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
def test_picokvm_ipad_profile_uses_native_pointer_with_default_wheel():
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    eff, rpc = make_eff(device_geometry=geometry)

    caps = eff.capabilities()

    assert caps.requires_assistive_touch is False
    assert caps.home_strategy == "keyboard_combo"
    assert caps.back_strategy == "keyboard_combo"
    assert caps.scroll_strategy == "wheel"
    assert caps.wheel_diagnostic is False
    assert caps.scroll_strategy_validated is True
    assert caps.scroll_evidence is None
    assert eff.supports("scroll_wheel") is True

    result = eff.scroll_wheel(1, interval_ms=0, focus_x=744, focus_y=1133)
    assert result.ok is True
    assert rpc.calls[-2:] == [("wheelReport", {"wheelY": 1}), ("wheelReport", {"wheelY": 0})]


@pytest.mark.smoke
def test_picokvm_ipad_profile_wheel_flag_is_no_longer_diagnostic():
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    eff, rpc = make_eff(device_geometry=geometry, wheel_enabled=True)

    caps = eff.capabilities()

    assert caps.requires_assistive_touch is False
    assert caps.scroll_strategy == "wheel"
    assert caps.wheel_diagnostic is False
    assert caps.scroll_strategy_validated is True
    assert caps.scroll_evidence is None
    assert eff.supports("scroll_wheel") is True

    result = eff.scroll_wheel(1, interval_ms=0, focus_x=744, focus_y=1133)
    assert result.ok is True
    assert rpc.calls[-2:] == [("wheelReport", {"wheelY": 1}), ("wheelReport", {"wheelY": 0})]


@pytest.mark.smoke
def test_picokvm_ipad_connect_runs_wheel_activation_once(monkeypatch):
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(
        _env_file=None,
        base_url="http://picokvm.test:8080",
        ipad_wheel_activation_wait_s=1.0,
    )
    eff = PicoKVMEffector(config=cfg, rpc=rpc, device_geometry=geometry)
    ssh_calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(argv, **_kwargs):
        ssh_calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="bounced\n", stderr="")

    monkeypatch.setattr("glassbox.effectors.picokvm.effector.subprocess.run", fake_run)
    monkeypatch.setattr("glassbox.effectors.picokvm.effector.time.sleep", lambda seconds: sleeps.append(seconds))

    eff.connect()

    assert eff.is_connected() is True
    assert ssh_calls
    assert "root@picokvm.test" in ssh_calls[0]
    assert "glassbox_ipad_wheel_armed" in ssh_calls[0][-1]
    assert "ffb00000.usb" in ssh_calls[0][-1]
    assert "/dev/hidg1" in ssh_calls[0][-1]
    assert "hidg1 not ready after UDC bounce" in ssh_calls[0][-1]
    assert sleeps == [1.0]
    assert [method for method, _params in rpc.calls].count("ping") >= 2


@pytest.mark.smoke
def test_picokvm_ipad_connect_skips_activation_wait_when_remote_marker_exists(monkeypatch):
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(_env_file=None, ipad_wheel_activation_wait_s=1.0)
    eff = PicoKVMEffector(config=cfg, rpc=rpc, device_geometry=geometry)
    sleeps: list[float] = []

    monkeypatch.setattr(
        "glassbox.effectors.picokvm.effector.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="already\n", stderr=""),
    )
    monkeypatch.setattr("glassbox.effectors.picokvm.effector.time.sleep", lambda seconds: sleeps.append(seconds))

    eff.connect()

    assert sleeps == []


@pytest.mark.smoke
def test_picokvm_ipad_connect_fails_when_required_activation_fails(monkeypatch):
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(_env_file=None, ipad_wheel_activation="required")
    eff = PicoKVMEffector(config=cfg, rpc=rpc, device_geometry=geometry)

    monkeypatch.setattr(
        "glassbox.effectors.picokvm.effector.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=255, stdout="", stderr="Host key verification failed"),
    )

    with pytest.raises(RuntimeError, match="picokvm_iPad_wheel_activation_failed"):
        eff.connect()

    assert eff._connected is False


@pytest.mark.smoke
def test_picokvm_iphone_opt_in_wheel_is_diagnostic_until_activation():
    geometry = SimpleNamespace(model="iphone_17", phone_size=(1179, 2556), phone_points=(393, 852))
    eff, _rpc = make_eff(device_geometry=geometry, wheel_enabled=True)

    caps = eff.capabilities()

    assert caps.scroll_strategy == "wheel"
    assert caps.scroll_strategy_validated is False
    assert caps.wheel_diagnostic is True
    assert caps.scroll_evidence == "iphone_opt_in_requires_udc_bounce_warmup_prime"


@pytest.mark.smoke
def test_picokvm_iphone_wheel_opt_in_connect_bounces_and_primes(monkeypatch):
    geometry = SimpleNamespace(model="iphone_17", phone_size=(1179, 2556), phone_points=(393, 852))
    rpc = FakeRpc()
    cfg = PicoKVMEffectorConfig(
        _env_file=None,
        base_url="http://picokvm.test:8080",
        wheel_enabled=True,
        iphone_wheel_activation_wait_s=0.5,
        iphone_wheel_prime_ticks=1,
        iphone_wheel_prime_interval_ms=0,
    )
    eff = PicoKVMEffector(config=cfg, rpc=rpc, device_geometry=geometry)
    ssh_calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(argv, **_kwargs):
        ssh_calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="bounced\n", stderr="")

    monkeypatch.setattr("glassbox.effectors.picokvm.effector.subprocess.run", fake_run)
    monkeypatch.setattr("glassbox.effectors.picokvm.effector.time.sleep", lambda seconds: sleeps.append(seconds))

    eff.connect()

    caps = eff.capabilities()
    assert caps.scroll_strategy == "wheel"
    assert caps.scroll_strategy_validated is True
    assert caps.wheel_diagnostic is False
    assert caps.scroll_evidence == "udc_bounce_warmup_prime"
    assert ssh_calls
    assert "root@picokvm.test" in ssh_calls[0]
    assert "glassbox_iphone_wheel_armed" in ssh_calls[0][-1]
    assert "rm -f \"$marker\"" in ssh_calls[0][-1]
    assert sleeps == [0.5]
    assert [method for method, _params in rpc.calls] == [
        "ping",
        "absMouseReport",
        "wheelReport",
        "wheelReport",
        "ping",
    ]
    assert rpc.calls[1:] == [
        ("absMouseReport", {"x": 16384, "y": 16384, "buttons": 0}),
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 0}),
        ("ping", None),
    ]


@pytest.mark.smoke
def test_picokvm_iphone_wheel_activation_polls_hid_until_ready(monkeypatch):
    class FlakyHidRpc(FakeRpc):
        def __init__(self):
            super().__init__()
            self.failures = 2

        def call(self, method, params=None):
            if method == "absMouseReport" and self.failures > 0:
                self.failures -= 1
                self.next_id += 1
                self.calls.append((method, params))
                raise RuntimeError("hid fd stale")
            return super().call(method, params)

    geometry = SimpleNamespace(model="iphone_17", phone_size=(1179, 2556), phone_points=(393, 852))
    rpc = FlakyHidRpc()
    cfg = PicoKVMEffectorConfig(
        _env_file=None,
        base_url="http://picokvm.test:8080",
        wheel_enabled=True,
        iphone_wheel_activation_wait_s=0,
        iphone_wheel_prime_ticks=0,
    )
    eff = PicoKVMEffector(config=cfg, rpc=rpc, device_geometry=geometry)
    sleeps: list[float] = []

    def fake_run(_argv, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="bounced\n", stderr="")

    monkeypatch.setattr("glassbox.effectors.picokvm.effector.subprocess.run", fake_run)
    monkeypatch.setattr("glassbox.effectors.picokvm.effector.time.sleep", lambda seconds: sleeps.append(seconds))

    eff.connect()

    assert eff.capabilities().scroll_strategy_validated is True
    assert sleeps == [0.25, 0.25]
    assert [method for method, _params in rpc.calls] == [
        "ping",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]


@pytest.mark.smoke
def test_picokvm_iphone_wheel_reprimes_before_each_scroll_even_when_status_says_primed():
    geometry = SimpleNamespace(model="iphone_17", phone_size=(1179, 2556), phone_points=(393, 852))
    eff, rpc = make_eff(wheel_enabled=True, device_geometry=geometry)
    eff._wheel_activation_status = "primed"

    result = eff.scroll_wheel(2, interval_ms=0, focus=False)

    assert result.ok is True
    assert result.executed_count == 3
    assert eff._wheel_activation_status == "primed"
    assert rpc.calls == [
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 0}),
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 0}),
    ]


@pytest.mark.smoke
def test_picokvm_ipad_profile_derives_absolute_calibration_from_crop():
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    crop = SimpleNamespace(crop_bbox=(640, 48, 642, 984))
    cfg = PicoKVMEffectorConfig(_env_file=None)
    eff = PicoKVMEffector(config=cfg, rpc=FakeRpc(), device_geometry=geometry, crop=crop)

    assert eff._abs_origin_offset_x == 640.0
    assert eff._abs_origin_offset_y == 48.0
    assert eff._abs_to_phone_scale_x == pytest.approx(642 / 32767)
    assert eff._abs_to_phone_scale_y == pytest.approx(984 / 32767)
    assert cfg.abs_origin_offset_x == 736.4
    assert cfg.abs_origin_offset_y == 53.8
    assert cfg.abs_to_phone_scale_x == pytest.approx(0.01363)
    assert cfg.abs_to_phone_scale_y == pytest.approx(0.02968)


@pytest.mark.smoke
def test_picokvm_ipad_crop_calibration_does_not_leak_through_shared_config():
    cfg = PicoKVMEffectorConfig(_env_file=None)
    ipad_geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    iphone_geometry = SimpleNamespace(model="iphone_17", phone_size=(1179, 2556), phone_points=(393, 852))
    crop = SimpleNamespace(crop_bbox=(640, 48, 642, 984))

    ipad_eff = PicoKVMEffector(config=cfg, rpc=FakeRpc(), device_geometry=ipad_geometry, crop=crop)
    iphone_eff = PicoKVMEffector(config=cfg, rpc=FakeRpc(), device_geometry=iphone_geometry)

    assert ipad_eff._abs_origin_offset_x == 640.0
    assert iphone_eff._abs_origin_offset_x == 736.4
    assert iphone_eff._abs_origin_offset_y == 53.8
    assert iphone_eff._abs_to_phone_scale_x == pytest.approx(0.01363)
    assert iphone_eff._abs_to_phone_scale_y == pytest.approx(0.02968)


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
def test_picokvm_type_uses_configured_key_gap_to_preserve_repeats(monkeypatch):
    eff, rpc = make_eff()
    eff.config.keyboard_type_key_gap_ms = 7
    sleeps: list[int] = []
    monkeypatch.setattr(eff, "_sleep_ms", sleeps.append)

    result = eff.type("tt")

    assert result.ok is True
    assert sleeps == [7, 7, 7, 7]
    assert rpc.calls == [
        ("keyboardReport", {"modifier": 0, "keys": [0x17]}),
        ("keyboardReport", {"modifier": 0, "keys": []}),
        ("keyboardReport", {"modifier": 0, "keys": [0x17]}),
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
def test_picokvm_wheel_off_by_default_but_hovers_then_scrolls_when_enabled():
    # Wheel is OFF by default on iPhone until the bounce+warmup+prime path is
    # proved in the Settings crawler.
    eff, _ = make_eff()
    assert eff.scroll_wheel(3).unsupported is True

    # When opted in, the corrected mechanism HOVERS (no click) over the focus
    # region then sends report-ID-2 wheel; wheelY=+1 = scroll down.
    eff, rpc = make_eff(wheel_enabled=True)
    enabled = eff.scroll_wheel(2, interval_ms=0, focus_x=960, focus_y=540)
    assert enabled.ok is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 0}),
    ]


@pytest.mark.smoke
def test_picokvm_wheel_can_click_focus_point_before_scroll_when_requested():
    eff, rpc = make_eff(wheel_enabled=True)

    enabled = eff.scroll_wheel(1, interval_ms=0, focus_x=960, focus_y=540, focus_click=True)

    assert enabled.ok is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 1}),
        ("absMouseReport", {"x": 16405, "y": 16381, "buttons": 0}),
        ("wheelReport", {"wheelY": 1}),
        ("wheelReport", {"wheelY": 0}),
    ]


@pytest.mark.smoke
def test_picokvm_wheel_hovers_default_focus_when_no_focus_point():
    eff, rpc = make_eff(wheel_enabled=True)

    enabled = eff.scroll_wheel(1, interval_ms=0)

    assert enabled.ok is True
    assert rpc.calls == [
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("absMouseReport", {"x": 14435, "y": 11905, "buttons": 0}),
        ("wheelReport", {"wheelY": 1}),
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
def test_phone_back_guard_uses_ipad_detail_pane_back_fallback(monkeypatch):
    geometry = SimpleNamespace(model="ipad_mini_7", phone_size=(1488, 2266), phone_points=(744, 1133))
    eff, _rpc = make_eff(device_geometry=geometry)
    phone = Phone(source=object(), ocr=object(), effector=eff, action_fail_fast=False, device_geometry=geometry)
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        platform_scene_kind="settings_detail",
        safe_actions=["back", "edge_back"],
        evidence=("ipad_split_view",),
    )
    monkeypatch.setattr(phone, "perceive", lambda: scene)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (744, 1133))

    allowed, reason, point = phone._picokvm_back_context()

    assert allowed is True
    assert reason == "platform_settings_detail"
    assert point == (335, 62)


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
def test_phone_back_guard_does_not_fail_fast_when_no_back_target():
    """A guard miss (no back target on the current scene) is recoverable, not a
    backend capability gap, so back_gesture must return a soft-failed result
    instead of raising even under action_fail_fast — otherwise a stuck page
    (e.g. the Action-Button carousel) crashes the whole recovery loop."""
    eff, _rpc = make_eff()
    source = FreshFrameSource()
    ocr = SequenceOCR([["通知", "允许通知", "通知分组", "显示预览"]])
    phone = Phone(
        source=source,
        ocr=ocr,
        effector=eff,
        action_fail_fast=True,
        platform_scene_classifier=None,
    )

    result = phone.back_gesture()  # must not raise

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
def test_phone_back_blind_taps_chevron_on_unknown_classified_subpage(monkeypatch):
    """A page the classifier positively tags "unknown" (e.g. the Action-Button
    carousel, whose live camera preview defeats chrome/back detection) still has
    the conventional top-left chevron. back_gesture must climb out via a blind
    inferred-chevron tap rather than stranding the recovery loop — this is the
    core intelligence that keeps a stuck sub-page from crashing a fresh run."""
    eff, rpc = make_eff()

    class _UnknownClassifier:
        def classify(self, _scene, *, viewport_size=None):
            return SceneClassification(
                page_id=None,
                platform_scene_kind="unknown",
                confidence=0.2,
                source="platform",
                safe_actions=(),
            )

    phone = Phone(
        source=object(),
        ocr=object(),
        effector=eff,
        action_fail_fast=True,  # even fail-fast must not raise; it taps instead
        platform_scene_classifier=_UnknownClassifier(),
    )
    carousel = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=166, y=606, w=112, h=24), text="静音模式", confidence=0.9),
            UIElement(type="text", box=Box(x=120, y=646, w=210, h=22), text="为通话和提醒切换静音和响铃。", confidence=0.9),
        ],
    )
    monkeypatch.setattr(phone, "perceive", lambda: carousel)
    monkeypatch.setattr(phone, "_viewport_size", lambda: (448, 990))

    result = phone.back_gesture()

    assert result.ok is True
    # a single blind chevron tap (move/move/down/up), no Meta+[ keyboard fallback
    assert [method for method, _params in rpc.calls] == [
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
        "absMouseReport",
    ]
    assert not any(method == "keyboardReport" for method, _params in rpc.calls)


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
