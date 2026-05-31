"""Low-level pointer, drag, wheel, and page gesture execution."""

from __future__ import annotations

from typing import Any

from glassbox.effector import ActionResult


def _add_optional_action_metadata(target: dict[str, Any], **items: Any) -> None:
    for key, value in items.items():
        if value is not None:
            target[key] = value


class GestureExecutor:
    """Execute coordinate-based gestures for the Phone facade."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def tap_xy(self, x: int, y: int, *, coordinate_space: str | None = None) -> ActionResult:
        host = self._phone
        input_space = host.normalize_input_coordinate_space(coordinate_space)
        px, py = host.to_phone_coordinates(x, y, coordinate_space=coordinate_space)
        coordinate_space_out = host.effector_coordinate_space()
        return host.execute_action(
            "tap",
            lambda: host.effector.tap(px, py),
            x=px,
            y=py,
            coordinate_space=coordinate_space_out,
            target_point={"x": px, "y": py, "space": coordinate_space_out},
            target_point_frame={"x": x, "y": y, "space": input_space},
            via="tap_xy",
            **host.picokvm_fresh_verify_kwargs("tap"),
        )

    def double_tap_xy(
        self,
        x: int,
        y: int,
        *,
        coordinate_space: str | None = None,
        target: str | None = None,
    ) -> ActionResult:
        host = self._phone
        input_space = host.normalize_input_coordinate_space(coordinate_space)
        px, py = host.to_phone_coordinates(x, y, coordinate_space=coordinate_space)
        coordinate_space_out = host.effector_coordinate_space()
        metadata = {"target": target} if target else {}
        return host.execute_action(
            "double_tap",
            lambda: host.effector.double_tap(px, py),
            x=px,
            y=py,
            coordinate_space=coordinate_space_out,
            target_point={"x": px, "y": py, "space": coordinate_space_out},
            target_point_frame={"x": x, "y": y, "space": input_space},
            via="double_tap_xy",
            **metadata,
            **host.picokvm_fresh_verify_kwargs("double_tap"),
        )

    def long_press_xy(
        self,
        x: int,
        y: int,
        *,
        coordinate_space: str | None = None,
        hold_ms: int = 500,
        target: str | None = None,
    ) -> ActionResult:
        host = self._phone
        input_space = host.normalize_input_coordinate_space(coordinate_space)
        px, py = host.to_phone_coordinates(x, y, coordinate_space=coordinate_space)
        coordinate_space_out = host.effector_coordinate_space()
        metadata = {"target": target} if target else {}
        return host.execute_action(
            "long_press",
            lambda: host.effector.long_press(px, py, hold_ms=hold_ms),
            x=px,
            y=py,
            coordinate_space=coordinate_space_out,
            target_point={"x": px, "y": py, "space": coordinate_space_out},
            target_point_frame={"x": x, "y": y, "space": input_space},
            hold_ms=hold_ms,
            via="long_press_xy",
            **metadata,
            **host.picokvm_fresh_verify_kwargs("long_press"),
        )

    def swipe_xy(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        coordinate_space: str | None = None,
        steps: int = 20,
        end_hold_ms: int = 100,
        via: str = "swipe_xy",
        policy_action: str | None = None,
        settle_strategy: str | None = None,
        fixed_delay_ms: int | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        fresh_delay_ms: int | None = None,
        fresh_source_reopen: bool | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        host = self._phone
        px1, py1 = host.to_phone_coordinates(x1, y1, coordinate_space=coordinate_space)
        px2, py2 = host.to_phone_coordinates(x2, y2, coordinate_space=coordinate_space)
        action_kwargs = {
            "x1": px1,
            "y1": py1,
            "x2": px2,
            "y2": py2,
            "coordinate_space": host.effector_coordinate_space(),
            "steps": steps,
            "end_hold_ms": end_hold_ms,
            "via": via,
        }
        if policy_action:
            action_kwargs["policy_action"] = policy_action
        _add_optional_action_metadata(
            action_kwargs,
            settle_strategy=settle_strategy,
            fixed_delay_ms=fixed_delay_ms,
            window_duration_ms=window_duration_ms,
            stream_timeout_ms=stream_timeout_ms,
            sample_interval_ms=sample_interval_ms,
            max_stream_frames=max_stream_frames,
            fresh_delay_ms=fresh_delay_ms,
            fresh_source_reopen=fresh_source_reopen,
            expected_state=expected_state,
            expect_visible=expect_visible,
            expect_page=expect_page,
        )
        for key, value in host.picokvm_fresh_verify_kwargs("swipe").items():
            action_kwargs.setdefault(key, value)
        return host.execute_action(
            "swipe",
            lambda: host.effector.swipe(
                px1, py1, px2, py2, steps=steps, end_hold_ms=end_hold_ms,
            ),
            **action_kwargs,
        )

    def drag_xy(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        coordinate_space: str | None = None,
        down_hold_ms: int = 200,
        up_hold_ms: int = 100,
        settle_strategy: str | None = None,
        fixed_delay_ms: int | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        fresh_delay_ms: int | None = None,
        fresh_source_reopen: bool | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        host = self._phone
        px1, py1 = host.to_phone_coordinates(x1, y1, coordinate_space=coordinate_space)
        px2, py2 = host.to_phone_coordinates(x2, y2, coordinate_space=coordinate_space)
        action_kwargs = {
            "x1": px1,
            "y1": py1,
            "x2": px2,
            "y2": py2,
            "coordinate_space": host.effector_coordinate_space(),
            "down_hold_ms": down_hold_ms,
            "up_hold_ms": up_hold_ms,
            "via": "drag_xy",
        }
        _add_optional_action_metadata(
            action_kwargs,
            settle_strategy=settle_strategy,
            fixed_delay_ms=fixed_delay_ms,
            window_duration_ms=window_duration_ms,
            stream_timeout_ms=stream_timeout_ms,
            sample_interval_ms=sample_interval_ms,
            max_stream_frames=max_stream_frames,
            fresh_delay_ms=fresh_delay_ms,
            fresh_source_reopen=fresh_source_reopen,
            expected_state=expected_state,
            expect_visible=expect_visible,
            expect_page=expect_page,
        )
        return host.execute_action(
            "drag",
            lambda: host.effector.drag(
                px1, py1, px2, py2,
                down_hold_ms=down_hold_ms, up_hold_ms=up_hold_ms,
            ),
            **action_kwargs,
        )

    def scroll_wheel(
        self,
        ticks: int,
        *,
        horizontal: int = 0,
        focus_x: int | None = None,
        focus_y: int | None = None,
        focus_click: bool = False,
        interval_ms: int | None = None,
    ) -> ActionResult:
        host = self._phone
        width, height = host.viewport_size()
        cx = width // 2 if focus_x is None else int(focus_x)
        cy = int(height * 0.55) if focus_y is None else int(focus_y)
        px, py = host.to_phone_coordinates(cx, cy)
        kwargs = {
            "horizontal": int(horizontal),
            "focus_x": px,
            "focus_y": py,
        }
        if focus_click:
            kwargs["focus_click"] = True
        if interval_ms is not None:
            kwargs["interval_ms"] = int(interval_ms)
        if not host.supports("scroll_wheel"):
            unsupported_kwargs = {
                "ticks": int(ticks),
                "horizontal": int(horizontal),
                "focus_x": px,
                "focus_y": py,
                "coordinate_space": host.effector_coordinate_space(),
                "via": "scroll_wheel",
            }
            if focus_click:
                unsupported_kwargs["focus_click"] = True
            return host.unsupported_action(
                "scroll_wheel",
                **unsupported_kwargs,
            )
        action_kwargs = {
            "ticks": int(ticks),
            "horizontal": int(horizontal),
            "focus_x": px,
            "focus_y": py,
            "coordinate_space": host.effector_coordinate_space(),
            "via": "scroll_wheel",
        }
        if focus_click:
            action_kwargs["focus_click"] = True
        action_kwargs.update(host.picokvm_fresh_verify_kwargs("scroll_wheel"))
        return host.execute_action(
            "scroll_wheel",
            lambda: host.effector.scroll_wheel(int(ticks), **kwargs),
            **action_kwargs,
        )

    def default_wheel_ticks(self) -> int:
        ticks = int(self._phone.gesture_config.wheel_ticks_per_scroll)
        return max(1, ticks)

    def wheel_scroll_down(self, *, ticks: int | None = None) -> ActionResult:
        host = self._phone
        amount = self.default_wheel_ticks() if ticks is None else int(ticks)
        if host.gesture_config.wheel_invert:
            amount *= -1
        return self.scroll_wheel(amount)

    def wheel_scroll_up(self, *, ticks: int | None = None) -> ActionResult:
        host = self._phone
        amount = self.default_wheel_ticks() if ticks is None else int(ticks)
        if host.gesture_config.wheel_invert:
            amount *= -1
        return self.scroll_wheel(-amount)

    def picokvm_drag_preset(
        self,
        method_name: str,
        *,
        via: str,
        policy_action: str,
        **metadata: Any,
    ) -> ActionResult | None:
        host = self._phone
        if host.effector_backend() != "picokvm":
            return None
        method = getattr(host.effector, method_name, None)
        if not callable(method):
            return None
        action_metadata = {
            **host.picokvm_fresh_verify_kwargs("drag"),
            **{key: value for key, value in metadata.items() if value is not None},
        }
        return host.execute_action(
            "drag",
            method,
            via=via,
            policy_action=policy_action,
            preset=f"picokvm.{method_name}",
            strategy="raw_hid_logical_drag",
            **action_metadata,
        )

    def swipe_up(
        self,
        *,
        fraction: float = 0.55,
        settle_strategy: str | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        metadata = {
            "settle_strategy": settle_strategy,
            "window_duration_ms": window_duration_ms,
            "stream_timeout_ms": stream_timeout_ms,
            "sample_interval_ms": sample_interval_ms,
            "max_stream_frames": max_stream_frames,
            "expected_state": expected_state,
            "expect_visible": expect_visible,
            "expect_page": expect_page,
        }
        preset = self.picokvm_drag_preset("list_scroll_up", via="swipe_up", policy_action="scroll", **metadata)
        if preset is not None:
            return preset
        width, height = self._phone.viewport_size()
        x = width // 2
        return self.swipe_xy(
            x,
            int(height * 0.78),
            x,
            int(height * max(0.15, 0.78 - fraction)),
            via="swipe_up",
            policy_action="scroll",
            **metadata,
        )

    def swipe_down(
        self,
        *,
        fraction: float = 0.55,
        settle_strategy: str | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        metadata = {
            "settle_strategy": settle_strategy,
            "window_duration_ms": window_duration_ms,
            "stream_timeout_ms": stream_timeout_ms,
            "sample_interval_ms": sample_interval_ms,
            "max_stream_frames": max_stream_frames,
            "expected_state": expected_state,
            "expect_visible": expect_visible,
            "expect_page": expect_page,
        }
        preset = self.picokvm_drag_preset("list_scroll_down", via="swipe_down", policy_action="scroll", **metadata)
        if preset is not None:
            return preset
        width, height = self._phone.viewport_size()
        x = width // 2
        return self.swipe_xy(
            x,
            int(height * 0.30),
            x,
            int(height * min(0.90, 0.30 + fraction)),
            via="swipe_down",
            policy_action="scroll",
            **metadata,
        )

    def page_drag_xy(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        via: str,
        down_hold_ms: int = 350,
        up_hold_ms: int = 150,
    ) -> ActionResult:
        host = self._phone
        px1, py1 = host.to_phone_coordinates(x1, y1)
        px2, py2 = host.to_phone_coordinates(x2, y2)
        return host.execute_action(
            "drag",
            lambda: host.effector.drag(
                px1, py1, px2, py2,
                down_hold_ms=down_hold_ms,
                up_hold_ms=up_hold_ms,
            ),
            x1=px1,
            y1=py1,
            x2=px2,
            y2=py2,
            coordinate_space=host.effector_coordinate_space(),
            down_hold_ms=down_hold_ms,
            up_hold_ms=up_hold_ms,
            via=via,
            policy_action="page",
        )

    def swipe_left(self, *, fraction: float = 0.84, y_fraction: float = 0.45) -> ActionResult:
        preset = self.picokvm_drag_preset("page_slide_left", via="swipe_left", policy_action="page")
        if preset is not None:
            return preset
        width, height = self._phone.viewport_size()
        y = int(height * y_fraction)
        return self.page_drag_xy(
            int(width * 0.92),
            y,
            int(width * max(0.08, 0.92 - fraction)),
            y,
            via="swipe_left",
        )

    def swipe_right(self, *, fraction: float = 0.84, y_fraction: float = 0.45) -> ActionResult:
        preset = self.picokvm_drag_preset("page_slide_right", via="swipe_right", policy_action="page")
        if preset is not None:
            return preset
        width, height = self._phone.viewport_size()
        y = int(height * y_fraction)
        return self.page_drag_xy(
            int(width * 0.08),
            y,
            int(width * min(0.92, 0.08 + fraction)),
            y,
            via="swipe_right",
        )


__all__ = ["GestureExecutor"]
