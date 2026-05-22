"""Actuation feedback primitives for target-bearing control actions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from glassbox.cognition import Box, UIElement
from glassbox.effector import ActionResult

ActuationMethod = Literal["mouse_tap", "keyboard_focus_activate"]
LandingSignal = Literal["landed", "missed", "indeterminate"]
AttributionLabel = Literal[
    "landed_ok",
    "landed_noop",
    "missed",
    "wrong_target",
    "blocked",
    "unknown",
]


@dataclass(frozen=True)
class Point:
    x: int
    y: int

    def to_dict(self, *, space: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"x": self.x, "y": self.y}
        if space:
            payload["space"] = space
        return payload


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_box(cls, box: Box) -> Rect:
        return cls(x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h))

    @property
    def center(self) -> Point:
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    def clamp(self, point: Point) -> Point:
        x2 = self.x + max(0, self.w - 1)
        y2 = self.y + max(0, self.h - 1)
        return Point(
            min(max(point.x, self.x), x2),
            min(max(point.y, self.y), y2),
        )

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class ActuationCommand:
    call: Callable[[], ActionResult]
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class ActuationPlan:
    target_identity: dict[str, Any]
    method: ActuationMethod
    control_bucket: dict[str, str]
    target_roi: Rect
    roi_space: str
    candidate_target_points: tuple[Point, ...]
    build_command: Callable[[Point, int], ActuationCommand]

    def command_for_attempt(self, attempt_index: int) -> ActuationCommand:
        if not self.candidate_target_points:
            raise ValueError("ActuationPlan requires at least one candidate point")
        point = self.candidate_target_points[min(attempt_index, len(self.candidate_target_points) - 1)]
        return self.build_command(point, attempt_index)

    def metadata(self) -> dict[str, Any]:
        return {
            "actuation_method": self.method,
            "target_identity": self.target_identity,
            "control_bucket": self.control_bucket,
            "target_roi": self.target_roi.to_dict(),
            "roi_space": self.roi_space,
            "candidate_target_points": [
                point.to_dict(space=self.roi_space) for point in self.candidate_target_points
            ],
        }


class CandidatePointGenerator:
    """Deterministic, non-learning candidate source for M1 landing retries."""

    def generate(
        self,
        element: UIElement,
        *,
        preferred_point: tuple[int, int] | None = None,
    ) -> tuple[Point, ...]:
        roi = Rect.from_box(element.box)
        center = Point(*(preferred_point or element.box.center))
        points: list[Point] = [center]

        if element.type in {"switch", "slider"}:
            points.append(roi.clamp(Point(roi.x + int(roi.w * 0.75), roi.center.y)))
        elif element.type in {"tab_bar_item", "button", "list_item"}:
            points.append(roi.clamp(Point(roi.center.x, roi.y + int(roi.h * 0.55))))
        elif element.text:
            points.append(roi.clamp(Point(roi.x + int(roi.w * 0.45), roi.center.y)))

        inset = max(2, int(min(roi.w, roi.h) * 0.2))
        if roi.w >= roi.h:
            points.append(roi.clamp(Point(roi.center.x, roi.y + inset)))
        else:
            points.append(roi.clamp(Point(roi.x + inset, roi.center.y)))

        step = max(2, int(min(roi.w, roi.h) * 0.12))
        points.extend((
            roi.clamp(Point(roi.center.x + step, roi.center.y)),
            roi.clamp(Point(roi.center.x - step, roi.center.y)),
            roi.clamp(Point(roi.center.x, roi.center.y + step)),
            roi.clamp(Point(roi.center.x, roi.center.y - step)),
        ))
        return tuple(_dedupe_points(points))


def _dedupe_points(points: list[Point]) -> list[Point]:
    seen: set[tuple[int, int]] = set()
    result: list[Point] = []
    for point in points:
        key = (point.x, point.y)
        if key in seen:
            continue
        seen.add(key)
        result.append(point)
    return result


def control_bucket_for_element(
    element: UIElement,
    *,
    viewport_size: tuple[int, int] | None,
) -> dict[str, str]:
    min_edge = min(element.box.w, element.box.h)
    if min_edge < 32:
        size_bucket = "small"
    elif min_edge < 80:
        size_bucket = "medium"
    else:
        size_bucket = "large"
    return {
        "control_role": str(element.type or "unknown"),
        "size_bucket": size_bucket,
        "region_zone": _region_zone(element.box, viewport_size),
    }


def target_identity_for_element(
    *,
    intent: str,
    element: UIElement,
    via: str,
    scene_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intent_hash = hashlib.sha256(f"{via}:{intent}".encode()).hexdigest()[:16]
    whitebox = element.whitebox_hint
    source_element_ref = {
        "element_id": element.element_id,
        "type": element.type,
        "whitebox_accessibility_id": whitebox.accessibility_id if whitebox else None,
        "whitebox_asset_match": whitebox.asset_match if whitebox else None,
    }
    roi_lineage = {
        "box": Rect.from_box(element.box).to_dict(),
        "scene_ref": scene_ref or {},
        "confidence": element.confidence,
        "type_confidence": element.type_confidence,
    }
    stable_hash = hashlib.sha256(
        repr((intent_hash, source_element_ref, roi_lineage["box"])).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": f"tid_{stable_hash}",
        "intent_hash": intent_hash,
        "source_element_ref": source_element_ref,
        "before_command_roi_lineage": roi_lineage,
    }


def _region_zone(box: Box, viewport_size: tuple[int, int] | None) -> str:
    if not viewport_size:
        return "unknown"
    width, height = viewport_size
    if width <= 0 or height <= 0:
        return "unknown"
    cx, cy = box.center
    x_edge = cx < width * 0.15 or cx > width * 0.85
    y_edge = cy < height * 0.15 or cy > height * 0.85
    if cy < height * 0.08:
        return "status_bar"
    if cy > height * 0.92:
        return "gesture_region"
    if x_edge and y_edge:
        return "corner"
    if x_edge or y_edge:
        return "edge"
    return "center"
