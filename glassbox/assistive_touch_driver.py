"""AssistiveTouch menu driver owned by the Phone facade."""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from glassbox.effector import ActionResult


class AssistiveTouchDriver:
    """Open and drive the AssistiveTouch menu through visual detection."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def open_menu(self, *, settle_s: float = 0.9) -> ActionResult:
        """Open the visible AssistiveTouch floating menu by visual detection."""
        from glassbox.ios.assistive_touch import detect_assistive_touch_button

        host = self._phone
        frame = host.snapshot(stable=True if host.stability_policy is not None else None)
        candidate = detect_assistive_touch_button(frame.img)
        if candidate is None:
            return self.record_failure(
                "AssistiveTouch floating button was not detected",
                via="assistive_touch.open_menu",
                target="AssistiveTouch",
            )
        x, y = candidate.center
        px, py = host.to_phone_coordinates(x, y)
        result = host.execute_action(
            "tap",
            lambda: host.effector.tap(px, py),
            x=px,
            y=py,
            coordinate_space=host.effector_coordinate_space(),
            target_point={"x": px, "y": py, "space": host.effector_coordinate_space()},
            target_point_frame={"x": x, "y": y, "space": "frame_px"},
            via="assistive_touch.open_menu",
            target="AssistiveTouch",
            policy_action="assistive_touch",
            assistive_touch_candidate=candidate.to_report(),
        )
        if settle_s > 0:
            time.sleep(settle_s)
        return result

    def tap_menu_item(
        self,
        label: str,
        *,
        path: tuple[str, ...] = (),
        open_menu: bool = True,
        allow_unsafe: bool = False,
        settle_s: float = 0.9,
        primitive_name: str | None = None,
    ) -> ActionResult:
        """Tap an AssistiveTouch menu item by current visual menu geometry."""
        from glassbox.ios.assistive_touch import (
            canonical_assistive_touch_label,
            is_assistive_touch_unsafe,
        )

        labels = (*path, label)
        unsafe = [
            canonical_assistive_touch_label(item)
            for item in labels
            if is_assistive_touch_unsafe(item)
        ]
        if unsafe and not allow_unsafe:
            return self.record_failure(
                f"unsafe AssistiveTouch action blocked: {unsafe[-1]}",
                via="assistive_touch.blocked",
                target=canonical_assistive_touch_label(label),
                path=path,
                safety_blocked=True,
                primitive_name=primitive_name,
            )
        last_result = None
        if open_menu:
            last_result = self.open_menu(settle_s=settle_s)
            if not getattr(last_result, "ok", False):
                return last_result
        for segment in path:
            last_result = self.tap_visible_item(
                segment,
                via="assistive_touch.navigate",
                path=(),
                settle_s=settle_s,
                allow_unsafe=allow_unsafe,
                primitive_name=primitive_name,
            )
            if not getattr(last_result, "ok", False):
                return last_result
        return self.tap_visible_item(
            label,
            via="assistive_touch.menu_item",
            path=path,
            settle_s=settle_s,
            allow_unsafe=allow_unsafe,
            primitive_name=primitive_name,
        )

    def run_primitive(
        self,
        name: str,
        *,
        open_menu: bool = True,
        settle_s: float = 0.9,
    ) -> ActionResult:
        """Execute a named safe AssistiveTouch menu primitive."""
        from glassbox.ios.assistive_touch import assistive_touch_primitive

        primitive = assistive_touch_primitive(name)
        if primitive is None:
            return self.record_failure(
                f"unknown AssistiveTouch primitive: {name}",
                via="assistive_touch.primitive",
                target=name,
                unsupported=True,
                primitive_name=name,
            )
        return self.tap_menu_item(
            primitive.label,
            path=primitive.path,
            open_menu=open_menu,
            allow_unsafe=False,
            settle_s=settle_s,
            primitive_name=primitive.name,
        )

    def tap_visible_item(
        self,
        label: str,
        *,
        via: str,
        path: tuple[str, ...],
        settle_s: float,
        allow_unsafe: bool,
        primitive_name: str | None = None,
    ) -> ActionResult:
        from glassbox.ios.assistive_touch import (
            canonical_assistive_touch_label,
            find_assistive_touch_menu_item,
            is_assistive_touch_unsafe,
        )

        host = self._phone
        canonical = canonical_assistive_touch_label(label)
        if is_assistive_touch_unsafe(canonical) and not allow_unsafe:
            return self.record_failure(
                f"unsafe AssistiveTouch action blocked: {canonical}",
                via="assistive_touch.blocked",
                target=canonical,
                path=path,
                safety_blocked=True,
                primitive_name=primitive_name,
            )
        scene = host.perceive(stable=True if host.stability_policy is not None else None)
        item = find_assistive_touch_menu_item(scene, canonical)
        if item is None and host.kimi is not None:
            try:
                scene = host.describe(scene_hint=f"AssistiveTouch menu item: {canonical}")
            except Exception as exc:
                logger.warning(f"AssistiveTouch VLM fallback failed for {canonical!r}: {exc}")
            else:
                item = find_assistive_touch_menu_item(scene, canonical)
        if item is None:
            return self.record_failure(
                f"AssistiveTouch menu item not found: {canonical}",
                via=via,
                target=canonical,
                path=path,
                primitive_name=primitive_name,
            )
        if item.unsafe and not allow_unsafe:
            return self.record_failure(
                f"unsafe AssistiveTouch action blocked: {canonical}",
                via="assistive_touch.blocked",
                target=canonical,
                path=path,
                safety_blocked=True,
                primitive_name=primitive_name,
            )
        x, y = item.tap_point
        px, py = host.to_phone_coordinates(x, y)
        metadata = {
            "x": px,
            "y": py,
            "coordinate_space": host.effector_coordinate_space(),
            "target_point": {"x": px, "y": py, "space": host.effector_coordinate_space()},
            "target_point_frame": {"x": x, "y": y, "space": "frame_px"},
            "via": via,
            "target": canonical,
            "policy_action": "assistive_touch",
            "assistive_touch_path": list(path),
            "assistive_touch_item": item.to_report(),
        }
        if primitive_name is not None:
            metadata["assistive_touch_primitive"] = primitive_name
        metadata.update(host.picokvm_fresh_verify_kwargs("tap"))
        result = host.execute_action(
            "tap",
            lambda: host.effector.tap(px, py),
            **metadata,
        )
        if settle_s > 0:
            time.sleep(settle_s)
        return result

    def record_failure(
        self,
        error: str,
        *,
        via: str,
        target: str,
        path: tuple[str, ...] = (),
        safety_blocked: bool = False,
        unsupported: bool = False,
        primitive_name: str | None = None,
    ) -> ActionResult:
        host = self._phone
        result = host.failed_action_result(
            error=error,
            unsupported=safety_blocked or unsupported,
        )
        metadata = {
            "via": via,
            "target": target,
            "policy_action": "assistive_touch",
            "assistive_touch_path": list(path),
            "safety_blocked": safety_blocked,
        }
        if primitive_name is not None:
            metadata["assistive_touch_primitive"] = primitive_name
        host.record_action("assistive_touch", result=result, **metadata)
        return result


__all__ = ["AssistiveTouchDriver"]
