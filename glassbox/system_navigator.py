"""System navigation primitives owned by the Phone facade."""

from __future__ import annotations

from typing import Any

from glassbox.boundaries import AppLaunchTarget
from glassbox.effector import ActionResult

_MOD_META_LEFT = 0x08


class SystemNavigator:
    """Home/back/app-launch and system-surface navigation."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def close_foreground_app(self) -> ActionResult:
        host = self._phone
        if not host.supports("close_foreground_app"):
            return host.unsupported_action("close_foreground_app")
        close_app = getattr(host.effector, "close_foreground_app", None)
        if not callable(close_app):
            return host.unsupported_action("close_foreground_app", strategy="missing_effector_method")
        return host.execute_action(
            "close_foreground_app",
            close_app,
            policy_action="close_foreground_app",
            strategy="home_indicator_drag",
            **host.picokvm_fresh_verify_kwargs("drag"),
        )

    def back_gesture(self) -> ActionResult:
        host = self._phone
        if host.uses_semantic_plan("back"):
            return host.run_semantic_plan(
                "back",
                via="back_gesture",
                policy_action="back",
                **host.picokvm_fresh_verify_kwargs("back"),
            )
        strategy = host.system_action_strategy("back")
        if strategy == "unsupported":
            return host.unsupported_action("back_gesture", strategy=strategy)
        allowed, guard_reason, nav_back_point = host.picokvm_back_context()
        if not allowed:
            result = host.failed_action_result(
                error="unsupported action: back_gesture",
                unsupported=True,
            )
            host.record_action(
                "back_gesture",
                result=result,
                strategy=strategy,
                guard=guard_reason,
            )
            return result
        if nav_back_point is not None:
            x, y = nav_back_point
            px, py = host.to_phone_coordinates(x, y)
            coordinate_space = host.effector_coordinate_space()
            return host.execute_action(
                "back",
                lambda: host.effector.tap(px, py),
                x=px,
                y=py,
                coordinate_space=coordinate_space,
                target_point={"x": px, "y": py, "space": coordinate_space},
                target_point_frame={"x": x, "y": y, "space": "frame_px"},
                via="back_gesture",
                policy_action="back",
                strategy="nav_back_tap",
                guard=guard_reason,
                **host.picokvm_fresh_verify_kwargs("back"),
            )
        back = getattr(host.effector, "back", None)
        if callable(back):
            return host.execute_action(
                "back",
                back,
                via="back_gesture",
                policy_action="back",
                strategy=strategy,
                **host.picokvm_fresh_verify_kwargs("back"),
            )
        return host.execute_action(
            "key",
            lambda: host.effector.key(_MOD_META_LEFT, 0x2F),
            modifier=_MOD_META_LEFT,
            keycode=0x2F,
            via="back_gesture",
            policy_action="back",
            strategy=strategy,
        )

    def home(self) -> ActionResult:
        host = self._phone
        strategy = host.system_action_strategy("home")
        if strategy in {"direct", "keyboard_combo"}:
            result = host.execute_action(
                "home",
                lambda: host.effector.home(),
                strategy=strategy,
                **host.picokvm_fresh_verify_kwargs("home"),
            )
            if self.picokvm_home_needs_fallback(result):
                return self.picokvm_home_pointer_fallback(
                    fallback_from=strategy, last_result=result
                )
            return result
        if strategy == "assistive_touch":
            return self.home_via_assistive_touch_menu()
        return host.unsupported_action("home", strategy=strategy)

    def picokvm_home_needs_fallback(self, result: ActionResult) -> bool:
        return (
            self._phone.effector_backend() == "picokvm"
            and result.semantic_verifier == "ios_home_screen_visible"
            and result.semantic_status != "succeeded"
        )

    def home_via_assistive_touch_menu(self) -> ActionResult:
        return self._phone.assistive_touch_tap_menu_item(
            "主屏幕",
            open_menu=True,
            settle_s=0.9,
            primitive_name="assistive_touch.home",
        )

    def expects_assistive_touch(self) -> bool:
        capabilities = self._phone.backend_capabilities()
        return bool(capabilities is not None and getattr(capabilities, "requires_assistive_touch", False))

    def picokvm_home_pointer_fallback(
        self, *, fallback_from: str, last_result: ActionResult
    ) -> ActionResult:
        host = self._phone
        result = last_result
        if self.expects_assistive_touch():
            at_result = self.verified_pointer_home(
                self.home_via_assistive_touch_menu,
                strategy="assistive_touch_home_fallback",
                fallback_from=fallback_from,
            )
            if self.home_reached(at_result):
                return at_result
            result = at_result
        close_app = getattr(host.effector, "close_foreground_app", None)
        if callable(close_app):
            drag_result = host.execute_action(
                "home",
                close_app,
                strategy="home_indicator_drag_fallback",
                fallback_from=fallback_from,
                **host.picokvm_fresh_verify_kwargs("home"),
            )
            if self.home_reached(drag_result):
                return drag_result
            result = drag_result
        return result

    @staticmethod
    def home_reached(result: ActionResult) -> bool:
        return result is not None and getattr(result, "semantic_status", None) == "succeeded"

    def verified_pointer_home(self, call, **metadata) -> ActionResult:
        host = self._phone
        verify_kwargs = host.picokvm_fresh_verify_kwargs("home")
        before_frame = host.last_frame
        before_scene = host.last_scene
        result = call()
        if not verify_kwargs or result is None or not getattr(result, "ok", True):
            return result
        return host.verify_fresh_action_result(
            "home",
            result,
            metadata={**metadata, **verify_kwargs},
            before_frame=before_frame,
            before_scene=before_scene,
            delay_ms=int(verify_kwargs.get("_semantic_verify_delay_ms", 0) or 0),
            reopen_source=bool(verify_kwargs.get("_semantic_verify_reopen_source", False)),
        )

    def recents(self) -> ActionResult:
        host = self._phone
        strategy = host.system_action_strategy("recents")
        if strategy in {"direct", "keyboard_combo"}:
            return host.execute_action("recents", lambda: host.effector.recents(), strategy=strategy)
        return host.unsupported_action("recents", strategy=strategy)

    def control_center(self) -> ActionResult:
        host = self._phone
        strategy = host.system_action_strategy("control_center")
        if strategy == "unsupported":
            return host.unsupported_action("control_center", strategy=strategy)
        return host.execute_action(
            "control_center", lambda: host.effector.control_center(), strategy=strategy)

    def notification_center(self) -> ActionResult:
        host = self._phone
        strategy = host.system_action_strategy("notification_center")
        if strategy == "unsupported":
            return host.unsupported_action("notification_center", strategy=strategy)
        return host.execute_action(
            "notification_center", lambda: host.effector.notification_center(), strategy=strategy)

    def open_app(
        self,
        label: str,
        *,
        aliases: tuple[str, ...] = (),
        max_pages: int = 8,
        settle_s: float = 0.8,
    ) -> ActionResult:
        host = self._phone
        if host.springboard_provider is None:
            return host.unsupported_action(
                "open_app",
                app=label,
                aliases=list(aliases),
                max_pages=max_pages,
                settle_s=settle_s,
            )
        target = AppLaunchTarget(bundle_id="", labels=(label,), aliases=aliases)

        def _open() -> ActionResult:
            orchestrator = host.action_orchestrator
            host.action_orchestrator = None
            try:
                ok = host.springboard_provider.open_app(
                    host,
                    target,
                    max_pages=max_pages,
                    settle_s=settle_s,
                    icon_map=host.icon_map,
                )
            finally:
                host.action_orchestrator = orchestrator
            return ActionResult(
                ok=bool(ok),
                backend="phone",
                connected=host.has_real_effector(),
                synthetic=True,
                error=None if ok else f"app not opened: {label}",
            )

        return host.execute_action(
            "open_app",
            _open,
            app=label,
            aliases=list(aliases),
            max_pages=max_pages,
            settle_s=settle_s,
        )


__all__ = ["SystemNavigator"]
