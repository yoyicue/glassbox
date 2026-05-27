"""Effector implementation for Luckfox PicoKVM.

PicoKVM is exposed to iOS as USB HID keyboard + external mouse. It is not a
touch digitizer: taps are pointer moves plus clicks; drags are mouse drags, not
multi-touch swipes; and clipboard/control-center style iOS-private operations
are unsupported.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from glassbox.effector import ActionResult, BackendCapabilities, PreflightResult
from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.effectors.picokvm.keymap import char_to_key
from glassbox.effectors.picokvm.rpc import (
    PicoKVMRpcClient,
    PicoKVMRpcResponse,
    PicoKVMRpcUnsupportedError,
)

_MOD_META_LEFT = 0x08
_KEY_H = 0x0B
_KEY_LEFT_BRACKET = 0x2F
_KEY_UP_ARROW = 0x52
_KEY_V = 0x19
_PICOKVM_DIRECT_ACTIONS = frozenset({
    "tap",
    "long_press",
    "double_tap",
    "swipe",
    "drag",
    "close_foreground_app",
    "list_scroll_up",
    "list_scroll_down",
    "page_slide_left",
    "page_slide_right",
    "type",
    "key",
})


class PicoKVMEffector:
    """Drive iOS through PicoKVM HID RPCs.

    iPhone targets need AssistiveTouch or external pointer support. iPadOS uses
    the native pointer path and advertises PicoKVM wheel scrolling by default
    after the 2026-05-27 Settings-sidebar frame-diff validation.
    """

    coordinate_space = "frame_px"

    def __init__(
        self,
        *,
        config: PicoKVMEffectorConfig | None = None,
        rpc: PicoKVMRpcClient | None = None,
        coordinate_space: str | None = None,
        device_geometry=None,
        crop=None,
        **_kwargs,
    ):
        self.config = config or PicoKVMEffectorConfig()
        self.rpc = rpc or PicoKVMRpcClient(self.config)
        self.coordinate_space = coordinate_space or "frame_px"
        self._phone_size = getattr(device_geometry, "phone_size", None)
        self._device_model = str(getattr(device_geometry, "model", "") or "").lower().replace("-", "_")
        self._apply_ipad_crop_calibration(crop)
        self._connected = False

    def connect(self) -> None:
        self.rpc.ping()
        self._connected = True

    def close(self) -> None:
        self.rpc.close()
        self._connected = False

    def is_connected(self) -> bool:
        try:
            self.rpc.ping()
        except Exception:
            self._connected = False
            return False
        self._connected = True
        return True

    def supports(self, action: str) -> bool:
        return self.capabilities().supports_semantic(action)

    def capabilities(self) -> BackendCapabilities:
        direct_actions = _PICOKVM_DIRECT_ACTIONS
        scroll_strategy = "unsupported"
        scroll_strategy_validated = True
        scroll_evidence = None
        is_ipad = self._is_ipad_target()
        if self._wheel_available():
            direct_actions = direct_actions | frozenset({"scroll_wheel", "wheel_scroll_down", "wheel_scroll_up"})
            scroll_strategy = "wheel"
        home_strategy = "unsupported"
        if self.config.assistive_touch_home_enabled:
            home_strategy = "assistive_touch"
        elif self.config.keyboard_home_enabled:
            home_strategy = "keyboard_combo"
        back_strategy = "keyboard_combo" if self.config.keyboard_back_enabled else "unsupported"
        return BackendCapabilities(
            backend="picokvm",
            coordinate_space=self.coordinate_space,
            pointer_kind="external_mouse",
            direct_actions=direct_actions,
            keyboard=True,
            text=True,
            clipboard=False,
            scroll_strategy=scroll_strategy,
            back_strategy=back_strategy,
            home_strategy=home_strategy,
            recents_strategy="unsupported",
            control_center_strategy="unsupported",
            notification_center_strategy="unsupported",
            switch_input_source_strategy="unsupported",
            paste_strategy="unsupported",
            requires_assistive_touch=not is_ipad,
            requires_connection=True,
            transport_label="picokvm-http",
            scroll_strategy_validated=scroll_strategy_validated,
            scroll_evidence=scroll_evidence,
            wheel_diagnostic=False,
        )

    def _is_ipad_target(self) -> bool:
        return self._device_model.startswith("ipad")

    def _wheel_available(self) -> bool:
        return bool(self.config.wheel_enabled or self._is_ipad_target())

    def _apply_ipad_crop_calibration(self, crop) -> None:
        """Derive a PicoKVM absolute-pointer fit from the detected iPad crop.

        iPhone keeps the historical static fit. For iPad, the USB-C mirror is a
        3:2 pillarboxed region inside a 16:9 HDMI frame, so the least surprising
        default is the current crop bbox. Explicit GLASSBOX_PICOKVM_ABS_* values
        still win for hand-measured calibration.
        """
        if not self._is_ipad_target() or self.coordinate_space != "frame_px" or crop is None:
            return
        fields_set = set(getattr(self.config, "model_fields_set", set()) or ())
        calibration_fields = {
            "abs_to_phone_scale_x",
            "abs_to_phone_scale_y",
            "abs_origin_offset_x",
            "abs_origin_offset_y",
        }
        if fields_set & calibration_fields:
            return
        try:
            x, y, w, h = crop.crop_bbox
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        maxv = max(1, int(self.config.abs_logical_max))
        self.config.abs_origin_offset_x = float(x)
        self.config.abs_origin_offset_y = float(y)
        self.config.abs_to_phone_scale_x = float(w) / maxv
        self.config.abs_to_phone_scale_y = float(h) / maxv

    def preflight(self) -> PreflightResult:
        try:
            device_id = self.rpc.call("getDeviceID").result
        except Exception as exc:
            return PreflightResult(
                ok=False,
                fatal=True,
                code="picokvm_unreachable",
                message=f"PicoKVM RPC unreachable: {exc}",
                config_ref="GLASSBOX_PICOKVM_BASE_URL",
            )
        try:
            video = self.rpc.call("getVideoState").result or {}
        except Exception:
            video = {}
        if isinstance(video, dict) and video.get("ready") is False:
            return PreflightResult(
                ok=True,
                fatal=False,
                code="picokvm_no_video",
                message=f"PicoKVM {device_id!r} reachable, but HDMI video is not ready",
                config_ref="GLASSBOX_PICOKVM",
            )
        return PreflightResult(ok=True, message=f"PicoKVM {device_id!r} reachable")

    def _ok(self, response: PicoKVMRpcResponse, *, op: str) -> ActionResult:
        _ = op
        return ActionResult(
            ok=True,
            backend="picokvm",
            connected=True,
            ack_seq=response.id,
            synthetic=False,
        )

    def _failed(self, op: str, exc: Exception, *, unsupported: bool = False) -> ActionResult:
        return ActionResult.failed(
            backend="picokvm",
            connected=self._connected,
            error=f"{op}: {exc}",
            unsupported=unsupported or isinstance(exc, PicoKVMRpcUnsupportedError),
        )

    def _call(self, method: str, params: dict) -> PicoKVMRpcResponse:
        return self.rpc.call(method, params)

    def _multi_result(self, responses: Iterable[PicoKVMRpcResponse], *, op: str) -> ActionResult:
        seqs = tuple(resp.id for resp in responses)
        return ActionResult(
            ok=True,
            backend="picokvm",
            connected=True,
            ack_seq=seqs[-1] if seqs else None,
            ack_seqs=seqs,
            executed_count=len(seqs),
            synthetic=False,
        )

    def _sleep_ms(self, ms: int) -> None:
        if ms > 0:
            time.sleep(ms / 1000.0)

    def _point_to_logical(self, x: int, y: int) -> tuple[int, int]:
        cfg = self.config
        maxv = int(cfg.abs_logical_max)
        if self.coordinate_space != "frame_px":
            raise ValueError(f"picokvm_coordinate_space_unsupported:{self.coordinate_space}")
        lx = round((int(x) - cfg.abs_origin_offset_x) / cfg.abs_to_phone_scale_x)
        ly = round((int(y) - cfg.abs_origin_offset_y) / cfg.abs_to_phone_scale_y)
        return max(0, min(maxv, lx)), max(0, min(maxv, ly))

    def _abs_report(self, x: int, y: int, buttons: int) -> PicoKVMRpcResponse:
        lx, ly = self._point_to_logical(x, y)
        return self._call("absMouseReport", {"x": lx, "y": ly, "buttons": int(buttons)})

    def _abs_logical_report(self, x: int, y: int, buttons: int) -> PicoKVMRpcResponse:
        maxv = int(self.config.abs_logical_max)
        lx = max(0, min(maxv, int(x)))
        ly = max(0, min(maxv, int(y)))
        return self._call("absMouseReport", {"x": lx, "y": ly, "buttons": int(buttons)})

    def _logical_fraction_point(self, x_fraction: float, y_fraction: float) -> tuple[int, int]:
        maxv = int(self.config.abs_logical_max)
        x = round(max(0.0, min(1.0, float(x_fraction))) * maxv)
        y = round(max(0.0, min(1.0, float(y_fraction))) * maxv)
        return x, y

    def _click_at(self, x: int, y: int) -> list[PicoKVMRpcResponse]:
        responses = [
            self._abs_report(x, y, 0),
            self._abs_report(x, y, 0),
        ]
        self._sleep_ms(self.config.click_move_settle_ms)
        responses.append(self._abs_report(x, y, 1))
        self._sleep_ms(self.config.click_press_ms)
        responses.append(self._abs_report(x, y, 0))
        return responses

    def tap(self, x: int, y: int) -> ActionResult:
        try:
            return self._multi_result(self._click_at(x, y), op="tap")
        except Exception as exc:
            return self._failed("tap", exc)

    def long_press(self, x: int, y: int, hold_ms: int = 500) -> ActionResult:
        try:
            effective_hold_ms = max(int(hold_ms), int(self.config.long_press_min_hold_ms))
            responses = [
                self._abs_report(x, y, 0),
                self._abs_report(x, y, 0),
            ]
            self._sleep_ms(self.config.click_move_settle_ms)
            responses.append(self._abs_report(x, y, 1))
            self._sleep_ms(effective_hold_ms)
            responses.append(self._abs_report(x, y, 0))
            return self._multi_result(responses, op="long_press")
        except Exception as exc:
            return self._failed("long_press", exc)

    def double_tap(self, x: int, y: int) -> ActionResult:
        try:
            responses = self._click_at(x, y)
            self._sleep_ms(self.config.double_tap_gap_ms)
            responses.extend(self._click_at(x, y))
            return self._multi_result(responses, op="double_tap")
        except Exception as exc:
            return self._failed("double_tap", exc)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        steps: int = 20,
        end_hold_ms: int = 100,
    ) -> ActionResult:
        return self._drag_path(x1, y1, x2, y2, steps=steps, down_hold_ms=0, up_hold_ms=end_hold_ms, op="swipe")

    def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        down_hold_ms: int = 200,
        up_hold_ms: int = 100,
    ) -> ActionResult:
        return self._drag_path(x1, y1, x2, y2, steps=20, down_hold_ms=down_hold_ms, up_hold_ms=up_hold_ms, op="drag")

    def close_foreground_app(self) -> ActionResult:
        """Close the foreground iPhone app with the captured home-indicator drag."""
        cfg = self.config
        return self._drag_path(
            cfg.close_app_drag_start_x,
            cfg.close_app_drag_start_y,
            cfg.close_app_drag_end_x,
            cfg.close_app_drag_end_y,
            steps=20,
            down_hold_ms=cfg.close_app_drag_down_hold_ms,
            up_hold_ms=cfg.close_app_drag_up_hold_ms,
            op="close_foreground_app",
            logical=True,
        )

    def list_scroll_up(self) -> ActionResult:
        cfg = self.config
        x1, y1 = self._logical_fraction_point(cfg.list_scroll_x_fraction, cfg.list_scroll_start_y_fraction)
        x2, y2 = self._logical_fraction_point(cfg.list_scroll_x_fraction, cfg.list_scroll_end_y_fraction)
        return self._drag_path(
            x1,
            y1,
            x2,
            y2,
            steps=20,
            down_hold_ms=cfg.preset_drag_down_hold_ms,
            up_hold_ms=cfg.preset_drag_up_hold_ms,
            op="list_scroll_up",
            logical=True,
        )

    def list_scroll_down(self) -> ActionResult:
        cfg = self.config
        x1, y1 = self._logical_fraction_point(cfg.list_scroll_x_fraction, cfg.list_scroll_end_y_fraction)
        x2, y2 = self._logical_fraction_point(cfg.list_scroll_x_fraction, cfg.list_scroll_start_y_fraction)
        return self._drag_path(
            x1,
            y1,
            x2,
            y2,
            steps=20,
            down_hold_ms=cfg.preset_drag_down_hold_ms,
            up_hold_ms=cfg.preset_drag_up_hold_ms,
            op="list_scroll_down",
            logical=True,
        )

    def page_slide_left(self) -> ActionResult:
        cfg = self.config
        x1, y1 = self._logical_fraction_point(cfg.page_slide_start_edge_fraction, cfg.page_slide_y_fraction)
        x2, y2 = self._logical_fraction_point(cfg.page_slide_end_edge_fraction, cfg.page_slide_y_fraction)
        return self._drag_path(
            x1,
            y1,
            x2,
            y2,
            steps=20,
            down_hold_ms=cfg.preset_drag_down_hold_ms,
            up_hold_ms=cfg.preset_drag_up_hold_ms,
            op="page_slide_left",
            logical=True,
        )

    def page_slide_right(self) -> ActionResult:
        cfg = self.config
        x1, y1 = self._logical_fraction_point(cfg.page_slide_end_edge_fraction, cfg.page_slide_y_fraction)
        x2, y2 = self._logical_fraction_point(cfg.page_slide_start_edge_fraction, cfg.page_slide_y_fraction)
        return self._drag_path(
            x1,
            y1,
            x2,
            y2,
            steps=20,
            down_hold_ms=cfg.preset_drag_down_hold_ms,
            up_hold_ms=cfg.preset_drag_up_hold_ms,
            op="page_slide_right",
            logical=True,
        )

    def _drag_path(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        steps: int,
        down_hold_ms: int,
        up_hold_ms: int,
        op: str,
        logical: bool = False,
    ) -> ActionResult:
        try:
            steps = max(1, int(steps))
            report = self._abs_logical_report if logical else self._abs_report
            responses = [
                report(x1, y1, 0),
                report(x1, y1, 0),
            ]
            self._sleep_ms(self.config.click_move_settle_ms)
            responses.append(report(x1, y1, 1))
            self._sleep_ms(down_hold_ms)
            for idx in range(1, steps + 1):
                t = idx / steps
                x = round(x1 + (x2 - x1) * t)
                y = round(y1 + (y2 - y1) * t)
                responses.append(report(x, y, 1))
                self._sleep_ms(self.config.rel_settle_ms)
            self._sleep_ms(up_hold_ms)
            responses.append(report(x2, y2, 0))
            return self._multi_result(responses, op=op)
        except Exception as exc:
            return self._failed(op, exc)

    def scroll_wheel(
        self,
        ticks: int,
        *,
        horizontal: int = 0,
        interval_ms: int = 40,
        focus: bool = True,
        focus_click: bool = False,
        focus_x: int | None = None,
        focus_y: int | None = None,
    ) -> ActionResult:
        if horizontal:
            return self._failed("scroll_wheel", ValueError("picokvm_wheel_horizontal_unsupported"), unsupported=True)
        if not self._wheel_available():
            return self._failed("scroll_wheel", ValueError("picokvm_wheel_unavailable"), unsupported=True)
        try:
            count = abs(int(ticks))
            if count == 0:
                return ActionResult(ok=True, backend="picokvm", connected=True, executed_count=0)
            sign = -1 if self.config.wheel_down_sign == "negative" else 1
            step = sign if ticks > 0 else -sign
            responses: list[PicoKVMRpcResponse] = []
            if focus:
                if focus_x is None or focus_y is None:
                    x = self.config.keyboard_focus_x
                    y = self.config.keyboard_focus_y
                    responses.extend([
                        self._call("absMouseReport", {"x": x, "y": y, "buttons": 0}),
                        self._call("absMouseReport", {"x": x, "y": y, "buttons": 0}),
                    ])
                    self._sleep_ms(self.config.click_move_settle_ms)
                    if focus_click:
                        responses.append(self._call("absMouseReport", {"x": x, "y": y, "buttons": 1}))
                        self._sleep_ms(self.config.click_press_ms)
                        responses.append(self._call("absMouseReport", {"x": x, "y": y, "buttons": 0}))
                        self._sleep_ms(self.config.click_move_settle_ms)
                else:
                    # Default to hover-only: on iPhone AssistiveTouch, clicking
                    # the row can break wheel delivery. iPad Settings opts into
                    # focus_click when native pointer focus needs activation.
                    responses.append(self._abs_report(int(focus_x), int(focus_y), 0))
                    responses.append(self._abs_report(int(focus_x), int(focus_y), 0))
                    self._sleep_ms(self.config.click_move_settle_ms)
                    if focus_click:
                        responses.append(self._abs_report(int(focus_x), int(focus_y), 1))
                        self._sleep_ms(self.config.click_press_ms)
                        responses.append(self._abs_report(int(focus_x), int(focus_y), 0))
                        self._sleep_ms(self.config.click_move_settle_ms)
            for _idx in range(count):
                responses.append(self._call("wheelReport", {"wheelY": step}))
                self._sleep_ms(interval_ms)
            responses.append(self._call("wheelReport", {"wheelY": 0}))
            return self._multi_result(responses, op="scroll_wheel")
        except Exception as exc:
            return self._failed("scroll_wheel", exc)

    def type(self, text: str) -> ActionResult:
        responses: list[PicoKVMRpcResponse] = []
        try:
            for ch in str(text):
                modifier, keycode = char_to_key(ch)
                responses.append(self._call("keyboardReport", {"modifier": modifier, "keys": [keycode]}))
                self._sleep_ms(self.config.keyboard_type_key_gap_ms)
                responses.append(self._call("keyboardReport", {"modifier": 0, "keys": []}))
                self._sleep_ms(self.config.keyboard_type_key_gap_ms)
            return self._multi_result(responses, op="type")
        except Exception as exc:
            if responses:
                seqs = tuple(resp.id for resp in responses)
                return ActionResult.failed(
                    backend="picokvm",
                    connected=self._connected,
                    error=f"type: {exc}",
                    unsupported=isinstance(exc, (ValueError, PicoKVMRpcUnsupportedError)),
                    ack_seq=seqs[-1],
                    ack_seqs=seqs,
                    executed_count=len(seqs),
                    partial=True,
                )
            return self._failed("type", exc, unsupported=isinstance(exc, ValueError))

    def key(self, modifier: int, keycode: int) -> ActionResult:
        try:
            responses = [
                self._call("keyboardReport", {"modifier": int(modifier), "keys": [int(keycode)]}),
                self._call("keyboardReport", {"modifier": 0, "keys": []}),
            ]
            return self._multi_result(responses, op="key")
        except Exception as exc:
            return self._failed("key", exc)

    def _webui_key_combo_reports(self, modifier: int, keycode: int) -> list[PicoKVMRpcResponse]:
        responses = [
            self._call("keyboardReport", {"keys": [], "modifier": int(modifier)}),
            self._call("keyboardReport", {"keys": [], "modifier": int(modifier)}),
        ]
        self._sleep_ms(self.config.keyboard_focus_click_ms)
        responses.append(self._call("keyboardReport", {"keys": [int(keycode)], "modifier": int(modifier)}))
        self._sleep_ms(self.config.keyboard_focus_click_ms)
        responses.append(self._call("keyboardReport", {"keys": [], "modifier": int(modifier)}))
        self._sleep_ms(self.config.keyboard_focus_click_ms)
        responses.append(self._call("keyboardReport", {"keys": [], "modifier": 0}))
        return responses

    def _keyboard_focus_click(self) -> list[PicoKVMRpcResponse]:
        x = self.config.keyboard_focus_x
        y = self.config.keyboard_focus_y
        responses = [
            self._call("absMouseReport", {"x": x, "y": y, "buttons": 0}),
            self._call("absMouseReport", {"x": x, "y": y, "buttons": 0}),
        ]
        self._sleep_ms(self.config.click_move_settle_ms)
        responses.append(self._call("absMouseReport", {"x": x, "y": y, "buttons": 1}))
        self._sleep_ms(self.config.keyboard_focus_click_ms)
        responses.append(self._call("absMouseReport", {"x": x, "y": y, "buttons": 0}))
        return responses

    def set_clipboard(self, text: str) -> ActionResult:
        _ = text
        return self._failed("set_clipboard", ValueError("picokvm_no_clipboard_api"), unsupported=True)

    def home(self) -> ActionResult:
        if not self.config.keyboard_home_enabled:
            return self._failed("home", ValueError("picokvm_home_unverified"), unsupported=True)
        try:
            responses = self._keyboard_focus_click()
            responses.extend(self._webui_key_combo_reports(_MOD_META_LEFT, _KEY_H))
            self._sleep_ms(self.config.keyboard_shortcut_gap_ms)
            responses.extend(self._webui_key_combo_reports(_MOD_META_LEFT, _KEY_H))
            return self._multi_result(responses, op="home")
        except Exception as exc:
            return self._failed("home", exc)

    def back(self) -> ActionResult:
        if not self.config.keyboard_back_enabled:
            return self._failed("back", ValueError("picokvm_back_unverified"), unsupported=True)
        try:
            responses = self._keyboard_focus_click()
            responses.extend(self._webui_key_combo_reports(_MOD_META_LEFT, _KEY_LEFT_BRACKET))
            return self._multi_result(responses, op="back")
        except Exception as exc:
            return self._failed("back", exc)

    def recents(self) -> ActionResult:
        return self._failed("recents", ValueError("picokvm_recents_unverified"), unsupported=True)

    def control_center(self) -> ActionResult:
        return self._failed("control_center", ValueError("picokvm_control_center_unverified"), unsupported=True)

    def notification_center(self) -> ActionResult:
        return self._failed(
            "notification_center",
            ValueError("picokvm_notification_center_unverified"),
            unsupported=True,
        )

    def paste(self) -> ActionResult:
        return self._failed("paste", ValueError("picokvm_paste_unverified"), unsupported=True)
