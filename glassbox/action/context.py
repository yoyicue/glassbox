"""Mutable action/perception state owned by a Phone session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from glassbox.cognition import Scene
    from glassbox.perception.source import Frame


@dataclass
class ActionContext:
    """Shared mutable state for action execution and perception caches."""

    pending_actions_for_memory: list[Any] = field(default_factory=list)
    last_frame: Frame | None = None
    last_scene: Scene | None = None
    last_scene_coordinate_space: str | None = None
    implicit_coordinate_space_error: tuple[str, str] | None = None
    cache_frame: Frame | None = None
    cache_scene: Scene | None = None
    cache_scope: str = "device"
    needs_stable_frame: bool = False
    fresh_source_reopened_after_action: bool = False
    last_stable_frame: bool | None = None
    last_stability_score: float | None = None
    last_stability_policy: dict[str, Any] | None = None
    last_observation_mode: str = "raw"
    last_ocr_timeout_hit: bool = False
    pending_crop_bbox: tuple[int, int, int, int] | None = None
    pending_crop_count: int = 0
    suppress_ocr_temporal_voting: bool = False
    ocr_temporal_voting_opt_in: bool = False


__all__ = ["ActionContext"]
