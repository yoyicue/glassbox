"""Configuration for the Luckfox PicoKVM backend."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PicoKVMEffectorConfig(BaseSettings):
    """Private PicoKVM backend settings.

    Environment variables use the ``GLASSBOX_PICOKVM_`` prefix, for example
    ``GLASSBOX_PICOKVM_BASE_URL``. PicoKVM is a USB HID mouse/keyboard path, not a
    touch digitizer; AssistiveTouch/external pointer must be enabled on iOS.
    """

    model_config = SettingsConfigDict(
        env_prefix="GLASSBOX_PICOKVM_",
        env_file=None,
        extra="ignore",
    )

    base_url: str = "http://picokvm.local"
    request_timeout_s: float = 3.0
    connect_timeout_s: float = 2.0
    retries: int = 1
    session_id: str = "codex-glassbox"
    """HTTP fallback RPC session id, matching the frontend's X-Session-ID shape."""
    trust_env: bool = False
    """Do not route local PicoKVM RPC through host HTTP proxy environment by default."""

    auth_mode: Literal["nopassword", "password"] = "nopassword"
    username: str | None = None
    password: str | None = None

    abs_logical_max: int = 32767

    # Bring-up 2026-05-21 linear fit, mapping PicoKVM logical coordinates to
    # decoded HDMI frame pixels:
    #   frame_x = abs_origin_offset_x + abs_to_phone_scale_x * logical_x
    #   frame_y = abs_origin_offset_y + abs_to_phone_scale_y * logical_y
    abs_to_phone_scale_x: float = 0.01363
    abs_to_phone_scale_y: float = 0.02968
    abs_origin_offset_x: float = 736.4
    abs_origin_offset_y: float = 53.8

    wheel_enabled: bool = False
    """Off by default: iOS's mouse wheel under AssistiveTouch is INTERMITTENT.
    The report-ID-2 wheel on the absolute-mouse interface CAN scroll precisely
    (~1 row/tick, no fling) when the pointer HOVERS over the scrollable region
    (a click breaks it) — verified on-device 2026-05-23 — but it "constantly
    stops working" under AssistiveTouch (Apple's documented limitation; observed:
    worked ~5×, then stayed dead the rest of the session, even fresh at root).
    A drill-down with it enabled regressed (overshoot→stuck→search fallback), so
    the default scroll stays the swipe. The hover+positive-sign mechanism below
    is kept correct for explicit opt-in (set GLASSBOX_PICOKVM_WHEEL_ENABLED=1).
    iPadOS also keeps this behind explicit opt-in: the connected iPad ACKed
    report-ID-2 wheel events but did not semantically scroll the Settings
    sidebar, so wheel remains diagnostic until hardware proof says otherwise."""

    wheel_down_sign: Literal["negative", "positive"] = "positive"
    """wheelY=+1 scrolls content down a notch on iOS (verified on-device)."""

    click_move_settle_ms: int = 250
    """Conservative absolute-pointer settle before pressing.

    The 2026-05-21 PicoKVM matrix proved Settings-icon activation with
    move -> settle >=250ms -> down 100ms -> up. Faster timings are optimization
    work, not the default semantic contract.
    """
    click_press_ms: int = 100
    double_tap_gap_ms: int = 80
    long_press_min_hold_ms: int = 1500
    """Minimum pointer-down duration for PicoKVM long press semantics.

    Live SpringBoard retakes on 2026-05-21 found 900ms inconsistent, while
    1500ms opened the Settings icon quick-action menu after a fresh settle.
    """
    rel_settle_ms: int = 30
    assistive_touch_home_enabled: bool = False
    """Experimental: expose Phone.home() via AssistiveTouch Home.

    This is disabled by default because the 2026-05-21 live probes showed
    AssistiveTouch menu Home can ack and close the menu without returning to
    the iOS home screen.
    """
    keyboard_home_enabled: bool = True
    """Expose Phone.home() via focus primer + two-stage Meta+H.

    The 2026-05-21 retakes proved this path with the captured focus click, two
    Web UI-shaped Meta+H sequences, and fresh-frame semantic verification.
    """
    keyboard_back_enabled: bool = True
    """Expose Phone.back_gesture() via focus primer + Meta+[.

    Phone gates this statefully: callers must be on a scene with a safe back
    action or visible nav-back element before the shortcut is sent. Settings
    root has no back target.
    """
    keyboard_focus_x: int = 14435
    keyboard_focus_y: int = 11905
    keyboard_focus_click_ms: int = 100
    keyboard_type_key_gap_ms: int = 40
    keyboard_shortcut_gap_ms: int = 500
    close_app_drag_start_x: int = 16102
    close_app_drag_start_y: int = 32506
    close_app_drag_end_x: int = 16728
    close_app_drag_end_y: int = 651
    close_app_drag_down_hold_ms: int = 200
    close_app_drag_up_hold_ms: int = 100
    """Captured Web UI-style bottom-home-indicator drag for closing foreground app."""
    list_scroll_x_fraction: float = 0.50
    list_scroll_start_y_fraction: float = 0.78
    list_scroll_end_y_fraction: float = 0.23
    page_slide_start_edge_fraction: float = 0.92
    page_slide_end_edge_fraction: float = 0.08
    page_slide_y_fraction: float = 0.45
    preset_drag_down_hold_ms: int = 350
    preset_drag_up_hold_ms: int = 150
    """Raw HID logical trajectory presets for PicoKVM drag-based gestures."""
    semantic_verify_enabled: bool = True
    """Verify opt-in system shortcuts with a fresh frame instead of ACK only."""
    semantic_verify_delay_ms: int = 800
    semantic_verify_timeout_ms: int = 1800
    semantic_verify_sample_interval_ms: int = 250
    semantic_verify_reopen_source: bool = True

    stream_path: str = "/video/stream"

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("GLASSBOX_PICOKVM_BASE_URL must not be empty")
        return value

    @field_validator(
        "request_timeout_s",
        "connect_timeout_s",
        "abs_to_phone_scale_x",
        "abs_to_phone_scale_y",
        "list_scroll_x_fraction",
        "list_scroll_start_y_fraction",
        "list_scroll_end_y_fraction",
        "page_slide_start_edge_fraction",
        "page_slide_end_edge_fraction",
        "page_slide_y_fraction",
    )
    @classmethod
    def _positive_float(cls, value: float) -> float:
        if float(value) <= 0:
            raise ValueError("value must be > 0")
        return float(value)

    @field_validator(
        "retries",
        "abs_logical_max",
        "click_move_settle_ms",
        "click_press_ms",
        "double_tap_gap_ms",
        "rel_settle_ms",
        "keyboard_focus_x",
        "keyboard_focus_y",
        "keyboard_focus_click_ms",
        "keyboard_type_key_gap_ms",
        "keyboard_shortcut_gap_ms",
        "preset_drag_down_hold_ms",
        "preset_drag_up_hold_ms",
        "semantic_verify_delay_ms",
        "semantic_verify_timeout_ms",
        "semantic_verify_sample_interval_ms",
    )
    @classmethod
    def _non_negative_int(cls, value: int) -> int:
        if int(value) < 0:
            raise ValueError("value must be >= 0")
        return int(value)
