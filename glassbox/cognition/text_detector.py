"""Conditional text detector seam.

The DBNet/CRAFT goal is intentionally closed until on-rig evidence proves the
Apple Vision OCR levers cannot recover the missing text. This module gives that
future work a core-owned selector while keeping today's runtime path explicitly
Vision-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from glassbox.config import AgentConfig

TextDetectorBackend = Literal["vision"]


def select_text_detector_backend(cfg: AgentConfig) -> TextDetectorBackend:
    """Return the configured text detector backend.

    ``AgentConfig`` currently validates this to ``"vision"`` only. Future DBNet
    work should widen the config literal here after the trigger in
    docs/goals/text_detector_dbnet_craft.md has fired.
    """
    return cfg.text_detector


__all__ = ["TextDetectorBackend", "select_text_detector_backend"]
