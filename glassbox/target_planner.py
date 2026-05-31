"""Target-to-actuation planning for Phone facade methods."""

from __future__ import annotations

from typing import Any

from loguru import logger

from glassbox.action.actuation import (
    ActuationCommand,
    ActuationPlan,
    CandidatePointGenerator,
    Point,
    Rect,
    control_bucket_for_element,
    target_identity_for_element,
)
from glassbox.cognition import UIElement

_KEY_RETURN = 0x28
_REGROUND_MIN_SHIFT_PX = 24


class TargetPlanner:
    """Plan where and how a resolved UI target should be actuated."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def _viewport_size(self) -> tuple[int, int]:
        return self._phone.viewport_size()

    def _last_scene(self):
        return getattr(self._phone, "last_scene", None)

    def _last_scene_coordinate_space(self) -> str | None:
        coordinate_space = getattr(self._phone, "last_scene_coordinate_space", None)
        if coordinate_space is not None:
            return coordinate_space
        context = getattr(self._phone, "action_context", None)
        return getattr(context, "last_scene_coordinate_space", None)

    def _effector_backend(self) -> str:
        return self._phone.effector_backend()

    def _infer_input_coordinate_space(self) -> str:
        return self._phone.infer_input_coordinate_space()

    def _to_phone(self, x: float, y: float, *, coordinate_space: str | None = None) -> tuple[int, int]:
        return self._phone.to_phone_coordinates(x, y, coordinate_space=coordinate_space)

    def _classify_platform_scene_now(self, scene, *, viewport_size: tuple[int, int] | None):
        classify = getattr(self._phone, "classify_platform_scene_now", None)
        if not callable(classify):
            return None
        return classify(scene, viewport_size=viewport_size)

    def _locate_in_last_scene(self, target: str) -> UIElement | None:
        locate = getattr(self._phone, "locate_in_last_scene", None)
        if not callable(locate):
            return None
        return locate(target)

    def _fresh_verify_kwargs(self, action: str) -> dict:
        fresh_kwargs = getattr(self._phone, "picokvm_fresh_verify_kwargs", None)
        if not callable(fresh_kwargs):
            return {}
        return fresh_kwargs(action)

    def tap_point_for_element(self, el: UIElement) -> tuple[int, int]:
        phone = self._phone
        settings_row_point = self.picokvm_settings_row_tap_point_for_element(el)
        if settings_row_point is not None:
            return settings_row_point
        springboard_icon_point = self.springboard_icon_tap_point_for_element(el)
        if springboard_icon_point is not None:
            return springboard_icon_point
        if el.preferred_tap_point is not None:
            return el.preferred_tap_point
        cx, cy = el.box.center
        if el.type == "tab_bar_item" and phone.safe_area_provider is not None:
            return phone.safe_area_provider.bottom_hit_point(
                self._viewport_size(),
                x=cx,
                y=cy,
                element_type=el.type,
            )
        return cx, cy

    def springboard_icon_tap_point_for_element(self, el: UIElement) -> tuple[int, int] | None:
        phone = self._phone
        scene = self._last_scene()
        if not el.text or scene is None:
            return None
        try:
            viewport_size = self._viewport_size()
        except Exception:
            viewport_size = None
        try:
            from glassbox.ios.springboard import find_springboard_icon, is_ios_home_screen

            if not is_ios_home_screen(
                scene,
                viewport_size=viewport_size,
                strict_springboard=phone.require_home_icon_grid_enabled,
            ):
                return None
            icon = find_springboard_icon(scene, (el.text,), viewport_size=viewport_size)
        except Exception:
            return None
        if icon is None:
            return None
        if icon.element.box != el.box or icon.element.text != el.text:
            return None
        return icon.tap_point

    def picokvm_settings_row_tap_point_for_element(self, el: UIElement) -> tuple[int, int] | None:
        phone = self._phone
        scene = self._last_scene()
        if self._effector_backend() != "picokvm" or scene is None:
            return None
        if el.type not in {"list_item", "button", "text"} or not el.text:
            return None
        scene_kind = str(scene.platform_scene_kind or scene.semantic_scene_type or scene.scene_type or "")
        page_id = str(scene.page_id or "")
        width, height = self._viewport_size()
        safe_actions = set(scene.safe_actions or [])
        if not (scene_kind or page_id or safe_actions):
            try:
                classified = self._classify_platform_scene_now(scene, viewport_size=(width, height))
            except Exception:
                classified = None
            if classified is not None:
                scene_kind = classified.platform_scene_kind or ""
                page_id = classified.page_id or ""
                safe_actions = set(classified.safe_actions or ())
        if not (
            scene_kind.startswith("settings")
            or page_id.startswith("settings")
            or "tap_root_row" in safe_actions
        ):
            return None
        cx, cy = el.box.center
        if cy < int(height * 0.18) or cy > int(height * 0.94):
            return None
        model = str(getattr(getattr(phone, "device_geometry", None), "model", "") or "").lower().replace("-", "_")
        if model.startswith("ipad"):
            from glassbox.ipados.scene import sidebar_right_x

            sidebar_right = sidebar_right_x(width)
            if cx <= sidebar_right:
                return min(max(cx, int(width * 0.10)), max(int(width * 0.10), sidebar_right - 44)), cy
            detail_x = min(
                max(int(sidebar_right + (width - sidebar_right) * 0.34), sidebar_right + 64),
                width - 44,
            )
            return min(max(cx, detail_x), width - 44), cy
        if el.box.x > int(width * 0.45):
            return None
        if el.box.w > int(width * 0.65):
            return None
        return int(width * 0.5), cy

    @staticmethod
    def pop_actuation_options(kwargs: dict) -> dict:
        option_keys = {
            "landing_retry_allowed",
            "forbid_landing_retry",
            "landing_retry_budget",
            "landing_diff_threshold",
            "landing_window_frames",
            "landing_sample_interval_ms",
            "ignore_actuation_profile_skip",
        }
        return {key: kwargs.pop(key) for key in list(kwargs) if key in option_keys}

    def scene_ref_for_target(self) -> dict | None:
        scene = self._last_scene()
        if scene is None:
            return None
        return {
            "frame_id": scene.frame_id,
            "page_id": scene.page_id,
            "scene_type": scene.semantic_scene_type or scene.scene_type,
        }

    def reground_tap_point(self, *, target: str):
        phone = self._phone
        if not target:
            return None
        try:
            element = self._locate_in_last_scene(target)
            if element is None and phone.kimi is not None:
                phone.describe()
                element = self._locate_in_last_scene(target)
        except Exception as exc:
            logger.warning(f"reground tap target {target!r} failed: {exc}")
            return None
        if element is None:
            return None
        px, py = self.tap_point_for_element(element)
        return Point(px, py)

    def target_tap_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        actuation_options: dict | None = None,
    ) -> tuple[ActuationPlan, dict]:
        phone = self._phone
        preferred = self.tap_point_for_element(element)
        control_bucket = control_bucket_for_element(element, viewport_size=self._viewport_size())
        offset = self.actuation_offset(control_bucket)
        if offset is not None and offset.space == "frame_px":
            preferred = (
                round(preferred[0] + offset.mean[0]),
                round(preferred[1] + offset.mean[1]),
            )
        candidates = CandidatePointGenerator().generate(element, preferred_point=preferred)
        coordinate_space = phone.effector_coordinate_space()
        source_coordinate_space = self._last_scene_coordinate_space() or self._infer_input_coordinate_space()

        def build_command(point: Point, attempt_index: int) -> ActuationCommand:
            regrounded = False
            tap_point = point
            tap_point_space = source_coordinate_space
            if attempt_index > 0:
                fresh = self.reground_tap_point(target=target)
                if fresh is not None:
                    orig_cx, orig_cy = element.box.center
                    if abs(fresh.x - orig_cx) + abs(fresh.y - orig_cy) > _REGROUND_MIN_SHIFT_PX:
                        tap_point = fresh
                        tap_point_space = self._last_scene_coordinate_space() or source_coordinate_space
                        regrounded = True
            px, py = self._to_phone(tap_point.x, tap_point.y, coordinate_space=tap_point_space)
            return ActuationCommand(
                call=lambda px=px, py=py: phone.effector.tap(px, py),
                kwargs={
                    "x": px,
                    "y": py,
                    "coordinate_space": coordinate_space,
                    "target_point": {"x": px, "y": py, "space": coordinate_space},
                    "target_point_frame": tap_point.to_dict(space=tap_point_space),
                    "actuation_attempt_index": attempt_index,
                    "regrounded": regrounded,
                },
            )

        plan = ActuationPlan(
            target_identity=target_identity_for_element(
                intent=intent,
                element=element,
                via=via,
                scene_ref=self.scene_ref_for_target(),
            ),
            method="mouse_tap",
            control_bucket=control_bucket,
            target_roi=Rect.from_box(element.box),
            roi_space=source_coordinate_space,
            candidate_target_points=candidates,
            build_command=build_command,
        )
        metadata = {
            "via": via,
            "target": target,
            "coordinate_space": coordinate_space,
            **self._fresh_verify_kwargs("tap"),
            **(actuation_options or {}),
        }
        return plan, metadata

    def target_actuation_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        actuation_options: dict | None = None,
        selection_source: str | None = None,
    ) -> tuple[str, ActuationPlan, dict]:
        control_bucket = control_bucket_for_element(element, viewport_size=self._viewport_size())
        if self.preferred_actuation_method(control_bucket) == "keyboard_focus_activate":
            op, (plan, metadata) = "key", self.target_keyboard_focus_plan(
                element=element,
                intent=intent,
                via=f"{via}:keyboard_focus_activate",
                target=target,
                modifier=0,
                keycode=_KEY_RETURN,
                actuation_options=actuation_options,
            )
        else:
            op, (plan, metadata) = "tap", self.target_tap_plan(
                element=element,
                intent=intent,
                via=via,
                target=target,
                actuation_options=actuation_options,
            )
        if selection_source:
            metadata = {**metadata, "selection_source": selection_source}
        return op, plan, metadata

    def actuation_offset(self, control_bucket: dict[str, str]):
        profile = getattr(self._phone.action_orchestrator, "actuation_profile", None)
        if profile is None:
            return None
        offset_for_bucket = getattr(profile, "offset_for_bucket", None)
        if not callable(offset_for_bucket):
            return None
        return offset_for_bucket(control_bucket)

    def preferred_actuation_method(self, control_bucket: dict[str, str]) -> str:
        profile = getattr(self._phone.action_orchestrator, "actuation_profile", None)
        if profile is None:
            return "mouse_tap"
        best_method_for_bucket = getattr(profile, "best_method_for_bucket", None)
        if not callable(best_method_for_bucket):
            return "mouse_tap"
        method = str(best_method_for_bucket(control_bucket, default="mouse_tap"))
        if method == "keyboard_focus_activate" and self._phone.supports("key"):
            return method
        return "mouse_tap"

    def target_keyboard_focus_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        modifier: int,
        keycode: int,
        actuation_options: dict | None = None,
    ) -> tuple[ActuationPlan, dict]:
        phone = self._phone
        control_bucket = control_bucket_for_element(element, viewport_size=self._viewport_size())

        def build_command(point: Point, attempt_index: int) -> ActuationCommand:
            del point
            return ActuationCommand(
                call=lambda modifier=modifier, keycode=keycode: phone.effector.key(modifier, keycode),
                kwargs={
                    "modifier": modifier,
                    "keycode": keycode,
                    "actuation_attempt_index": attempt_index,
                },
            )

        plan = ActuationPlan(
            target_identity=target_identity_for_element(
                intent=intent,
                element=element,
                via=via,
                scene_ref=self.scene_ref_for_target(),
            ),
            method="keyboard_focus_activate",
            control_bucket=control_bucket,
            target_roi=Rect.from_box(element.box),
            roi_space="focus_evidence",
            candidate_target_points=(Point(*element.box.center),),
            build_command=build_command,
        )
        metadata = {
            "via": via,
            "target": target,
            "policy_action": "tap",
            "coordinate_space": "keyboard_focus",
            **(actuation_options or {}),
        }
        return plan, metadata


__all__ = ["TargetPlanner"]
