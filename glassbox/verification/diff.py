"""GUI diff helpers for computer-use action verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from glassbox.cognition.base import Scene
from glassbox.perception.stable import frame_diff_ratio


@dataclass(frozen=True)
class FrameDiff:
    diff_ratio: float | None
    changed_bbox: tuple[int, int, int, int] | None
    changed: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diff_ratio": self.diff_ratio,
            "changed_bbox": list(self.changed_bbox) if self.changed_bbox is not None else None,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class SceneDiff:
    texts_added: list[str]
    texts_removed: list[str]
    texts_common: list[str]
    page_id_before: str | None
    page_id_after: str | None
    scene_type_before: str | None
    scene_type_after: str | None
    element_count_delta: int
    changed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "texts_added": self.texts_added,
            "texts_removed": self.texts_removed,
            "texts_common": self.texts_common,
            "page_id_before": self.page_id_before,
            "page_id_after": self.page_id_after,
            "scene_type_before": self.scene_type_before,
            "scene_type_after": self.scene_type_after,
            "element_count_delta": self.element_count_delta,
            "changed": self.changed,
        }


def _changed_bbox(a: np.ndarray, b: np.ndarray, *, threshold: int = 12) -> tuple[int, int, int, int] | None:
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        return (0, 0, w, h)
    g_a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if a.ndim == 3 else a
    g_b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    mask = cv2.absdiff(g_a, g_b) > threshold
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None
    x1 = int(xs.min())
    y1 = int(ys.min())
    x2 = int(xs.max()) + 1
    y2 = int(ys.max()) + 1
    return (x1, y1, x2 - x1, y2 - y1)


def compute_frame_diff(before: np.ndarray | None, after: np.ndarray | None) -> FrameDiff | None:
    if before is None or after is None:
        return None
    if getattr(before, "shape", None) != getattr(after, "shape", None):
        # CUQ-1.7: a shape mismatch is a garbled / partial decode (or a mid-run
        # crop change), not reliable evidence that the screen "fully changed".
        # Returning ratio=1.0 here would score a garbled frame as a confident
        # landed/progress signal. Mark it indeterminate (None) instead so the
        # landing/verification path treats it as "can't tell" rather than
        # "everything changed" (a None diff_ratio maps to an indeterminate
        # landing signal, and changed=None is falsey for progress checks).
        return FrameDiff(diff_ratio=None, changed_bbox=_changed_bbox(before, after), changed=None)
    ratio = frame_diff_ratio(before, after)
    bbox = _changed_bbox(before, after)
    return FrameDiff(diff_ratio=ratio, changed_bbox=bbox, changed=ratio > 0.001)


def _texts(scene: Scene | None) -> set[str]:
    if scene is None:
        return set()
    return {str(e.text).strip() for e in scene.elements if e.text and str(e.text).strip()}


def compute_scene_diff(before: Scene | None, after: Scene | None) -> SceneDiff | None:
    if before is None or after is None:
        return None
    before_texts = _texts(before)
    after_texts = _texts(after)
    added = sorted(after_texts - before_texts)
    removed = sorted(before_texts - after_texts)
    common = sorted(before_texts & after_texts)
    page_changed = before.page_id != after.page_id
    scene_type_changed = (
        (before.semantic_scene_type or before.scene_type)
        != (after.semantic_scene_type or after.scene_type)
    )
    element_delta = len(after.elements) - len(before.elements)
    return SceneDiff(
        texts_added=added,
        texts_removed=removed,
        texts_common=common,
        page_id_before=before.page_id,
        page_id_after=after.page_id,
        scene_type_before=before.semantic_scene_type or before.scene_type,
        scene_type_after=after.semantic_scene_type or after.scene_type,
        element_count_delta=element_delta,
        changed=bool(added or removed or page_changed or scene_type_changed or element_delta),
    )
