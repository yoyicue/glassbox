"""Target-to-actuation planning for Phone facade methods."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
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
from glassbox.cognition.text_match import compact_text
from glassbox.ios.settings_rows import visible_settings_root_row_label

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

    def find_visible_label(
        self,
        scene,
        labels: Iterable[str],
        *,
        region: str | None = None,
        canonicalizer: Callable[[str], str | None] | None = None,
        match_any: Callable[..., UIElement | None] | None = None,
    ) -> UIElement | None:
        """Find a visible UI element by label, optionally scoped to a platform region."""
        labels = tuple(label for label in labels if label)
        if not labels:
            return None
        elements = self._elements_in_region(scene, region=region)
        target_canonicals = self._target_canonicals(labels, canonicalizer)
        for element in elements:
            text = (element.text or "").strip()
            if not text:
                continue
            if text in labels:
                return element
            if target_canonicals and canonicalizer is not None and canonicalizer(text) in target_canonicals:
                return element
            if any(self._matches_split_row_label(text, label) for label in labels):
                return element
        if match_any is not None:
            return match_any(elements, labels)
        return None

    def scroll_to_visible_label(
        self,
        labels: Iterable[str],
        *,
        region: str | None = None,
        canonicalizer: Callable[[str], str | None] | None = None,
        match_any: Callable[..., UIElement | None] | None = None,
        fallback_locator: Callable[[Any], UIElement | None] | None = None,
        perceive: Callable[[], Any] | None = None,
        scroll_down: Callable[[], None],
        scroll_up: Callable[[], None] | None = None,
        max_attempts: int = 5,
        upward_attempt: int | None = 2,
        settle_s: float = 1.0,
        on_seek_attempt: Callable[[int], None] | None = None,
    ) -> UIElement | None:
        """Seek a label by repeated perception, optional fallback locating, and scrolling."""
        labels = tuple(label for label in labels if label)
        if not labels:
            return None
        perceive = perceive or self._phone.perceive
        for attempt in range(max(1, max_attempts)):
            scene = perceive()
            hit = self.find_visible_label(
                scene,
                labels,
                region=region,
                canonicalizer=canonicalizer,
                match_any=match_any,
            )
            if hit is not None:
                return hit
            if fallback_locator is not None:
                fallback_hit = fallback_locator(scene)
                if fallback_hit is not None:
                    return fallback_hit
            if on_seek_attempt is not None:
                on_seek_attempt(attempt)
            if upward_attempt is not None and attempt == upward_attempt and scroll_up is not None:
                scroll_up()
            else:
                scroll_down()
            if settle_s > 0:
                time.sleep(settle_s)
        return None

    def _elements_in_region(self, scene, *, region: str | None) -> list[UIElement]:
        elements = list(getattr(scene, "elements", ()) or ())
        if region is None:
            return elements
        if region == "ipados_settings_sidebar":
            width, _height = self._viewport_size()
            from glassbox.ipados.scene import sidebar_right_x

            sidebar_right = sidebar_right_x(width)
            return [
                element for element in elements
                if element.box.center[0] <= sidebar_right + 24
            ]
        raise ValueError(f"unknown target region: {region}")

    @staticmethod
    def _target_canonicals(
        labels: tuple[str, ...],
        canonicalizer: Callable[[str], str | None] | None,
    ) -> set[str]:
        if canonicalizer is None:
            return set()
        return {
            canonical for canonical in (canonicalizer(label) for label in labels)
            if canonical is not None
        }

    @staticmethod
    def _matches_split_row_label(text: str, label: str) -> bool:
        """Match OCR split rows such as ``Home Screen &`` to their full label."""
        text = (text or "").strip()
        label = (label or "").strip()
        if not text.endswith("&") or len(label) <= len(text):
            return False
        return compact_text(label).casefold().startswith(compact_text(text).casefold())

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
            if self._is_ipad_sidebar_root_row_target(el, viewport_size=(width, height)):
                preferred = el.preferred_tap_point
                hint_x = int(preferred[0]) if preferred is not None else min(cx, sidebar_right - 44)
                return min(
                    max(hint_x, int(width * 0.10)),
                    max(int(width * 0.10), sidebar_right - 44),
                ), cy
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

    def _is_ipad_sidebar_root_row_target(
        self,
        el: UIElement,
        *,
        viewport_size: tuple[int, int],
    ) -> bool:
        model = str(
            getattr(getattr(self._phone, "device_geometry", None), "model", "") or ""
        ).lower().replace("-", "_")
        if not model.startswith("ipad"):
            return False
        width, height = viewport_size
        if el.box.x > max(16, int(width * 0.04)):
            return False
        return visible_settings_root_row_label(el, viewport_size=(width, height)) is not None

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
        viewport_size = self._viewport_size()
        preferred = self.tap_point_for_element(element)
        control_bucket = control_bucket_for_element(element, viewport_size=viewport_size)
        skip_offset = via == "settings.tap_row" and self._is_ipad_sidebar_root_row_target(
            element,
            viewport_size=viewport_size,
        )
        offset = None if skip_offset else self.actuation_offset(control_bucket)
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
