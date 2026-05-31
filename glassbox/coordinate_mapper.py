"""Coordinate-space mapping for Phone-owned interaction surfaces."""

from __future__ import annotations

from typing import Any


class CoordinateMapper:
    """Map observation coordinates into the active effector coordinate space."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone

    def to_phone(
        self,
        x: float,
        y: float,
        *,
        coordinate_space: str | None = None,
    ) -> tuple[int, int]:
        phone = self._phone
        context = phone.action_context
        if coordinate_space is None and context.implicit_coordinate_space_error is not None:
            previous, current = context.implicit_coordinate_space_error
            raise ValueError(
                "implicit coordinate space is ambiguous after observation scope changed "
                f"from {previous!r} to {current!r}; pass coordinate_space explicitly"
            )
        input_space = self.normalize_input_coordinate_space(coordinate_space)
        if input_space == "app_px":
            if phone.app_viewport is None:
                raise ValueError("coordinate_space='app_px' requires an app_viewport")
            x, y = phone.app_viewport.child_to_parent(x, y)
            input_space = phone.app_viewport.parent_coordinate_space
        if input_space == "frame_px":
            return self.frame_to_effector(x, y)
        if input_space == "cropped_px":
            return self.cropped_to_effector(x, y)
        raise ValueError(f"unsupported coordinate_space for phone input: {coordinate_space!r}")

    def normalize_input_coordinate_space(self, coordinate_space: str | None) -> str:
        if coordinate_space is None:
            return self.infer_input_coordinate_space()
        normalized = str(coordinate_space).strip().lower().replace("-", "_")
        if normalized in {"app", "app_px"}:
            return "app_px"
        if normalized in {"device", "cropped", "cropped_px"}:
            return "cropped_px" if self._phone.crop is not None else "frame_px"
        if normalized in {"frame", "frame_px", "raw", "raw_frame"}:
            return "frame_px"
        return normalized

    def infer_input_coordinate_space(self) -> str:
        phone = self._phone
        context = phone.action_context
        if context.last_scene_coordinate_space is not None:
            return context.last_scene_coordinate_space
        if context.last_frame is not None:
            return context.last_frame.context.coordinate_space
        return "cropped_px" if phone.crop is not None else "frame_px"

    def cropped_to_effector(self, x: float, y: float) -> tuple[int, int]:
        phone = self._phone
        if phone.crop is None:
            return round(x), round(y)
        effector_space = getattr(phone.effector, "coordinate_space", None)
        if effector_space == "frame_px":
            return phone.crop.cropped_to_frame(x, y)
        return phone.crop.cropped_to_phone(x, y)

    def frame_to_effector(self, x: float, y: float) -> tuple[int, int]:
        phone = self._phone
        if phone.crop is None:
            return round(x), round(y)
        effector_space = getattr(phone.effector, "coordinate_space", None)
        if effector_space == "frame_px":
            return round(x), round(y)
        cx, cy, _w, _h = phone.crop.crop_bbox
        return phone.crop.cropped_to_phone(float(x) - cx, float(y) - cy)

    def effector_coordinate_space(self) -> str:
        phone = self._phone
        if phone.coordinate_space != "auto":
            return phone.coordinate_space
        effector_space = getattr(phone.effector, "coordinate_space", None)
        if phone.crop is not None and effector_space != "frame_px":
            return "phone_pt" if effector_space == "phone_pt" else "phone_px"
        return str(effector_space or "frame_px")


__all__ = ["CoordinateMapper"]
