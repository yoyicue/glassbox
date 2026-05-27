from __future__ import annotations

import pytest

from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig


@pytest.mark.smoke
def test_picokvm_config_defaults_match_bringup():
    cfg = PicoKVMEffectorConfig(_env_file=None)

    assert cfg.base_url == "http://picokvm.local"
    assert cfg.auth_mode == "nopassword"
    assert cfg.session_id == "codex-glassbox"
    assert cfg.trust_env is False
    assert cfg.wheel_enabled is False
    assert cfg.ipad_wheel_activation == "required"
    assert cfg.ipad_wheel_activation_ssh_user == "root"
    assert cfg.ipad_wheel_activation_marker == "/tmp/glassbox_ipad_wheel_armed"
    assert cfg.ipad_wheel_activation_udc == "ffb00000.usb"
    assert cfg.ipad_wheel_activation_wait_s == 25.0
    assert cfg.assistive_touch_home_enabled is False
    assert cfg.keyboard_home_enabled is True
    assert cfg.keyboard_back_enabled is True
    assert cfg.click_move_settle_ms == 250
    assert cfg.click_press_ms == 100
    assert cfg.long_press_min_hold_ms == 1500
    assert cfg.close_app_drag_start_x == 16102
    assert cfg.close_app_drag_start_y == 32506
    assert cfg.close_app_drag_end_x == 16728
    assert cfg.close_app_drag_end_y == 651
    assert cfg.list_scroll_x_fraction == 0.50
    assert cfg.list_scroll_start_y_fraction == 0.78
    assert cfg.list_scroll_end_y_fraction == 0.23
    assert cfg.page_slide_start_edge_fraction == 0.92
    assert cfg.page_slide_end_edge_fraction == 0.08
    assert cfg.page_slide_y_fraction == 0.45
    assert cfg.preset_drag_down_hold_ms == 350
    assert cfg.preset_drag_up_hold_ms == 150
    assert cfg.keyboard_shortcut_gap_ms == 500
    assert cfg.semantic_verify_enabled is True
    assert cfg.semantic_verify_delay_ms == 800
    assert cfg.semantic_verify_reopen_source is True
    assert cfg.abs_to_phone_scale_x > 0
    assert cfg.abs_to_phone_scale_y > 0


@pytest.mark.smoke
def test_picokvm_config_env_overrides(monkeypatch):
    monkeypatch.setenv("GLASSBOX_PICOKVM_BASE_URL", "http://unit.test/")
    monkeypatch.setenv("GLASSBOX_PICOKVM_WHEEL_ENABLED", "true")
    monkeypatch.setenv("GLASSBOX_PICOKVM_AUTH_MODE", "password")
    monkeypatch.setenv("GLASSBOX_PICOKVM_SESSION_ID", "unit-session")
    monkeypatch.setenv("GLASSBOX_PICOKVM_IPAD_WHEEL_ACTIVATION", "warn")
    monkeypatch.setenv("GLASSBOX_PICOKVM_IPAD_WHEEL_ACTIVATION_WAIT_S", "3")

    cfg = PicoKVMEffectorConfig(_env_file=None)

    assert cfg.base_url == "http://unit.test"
    assert cfg.wheel_enabled is True
    assert cfg.auth_mode == "password"
    assert cfg.session_id == "unit-session"
    assert cfg.ipad_wheel_activation == "warn"
    assert cfg.ipad_wheel_activation_wait_s == 3.0
