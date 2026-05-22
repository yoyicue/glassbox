"""Shared device geometry contract assembly."""

from __future__ import annotations

from glassbox.boundaries import DeviceGeometry
from glassbox.config import AgentConfig


def make_device_geometry(
    cfg: AgentConfig,
    *,
    frame_size: tuple[int, int] | None = None,
) -> DeviceGeometry:
    return DeviceGeometry(
        model=getattr(cfg, "phone_model", "unknown"),
        frame_size=frame_size,
        phone_size=cfg.phone_size(),
        phone_points=cfg.phone_points(),
    )


def content_size_for_crop(cfg: AgentConfig, geometry: DeviceGeometry) -> tuple[int, int]:
    _ = cfg
    if geometry.phone_size is None:
        raise ValueError("DeviceGeometry.phone_size is required for crop detection")
    return geometry.phone_size


def effector_frame_resolution(
    cfg: AgentConfig,
    geometry: DeviceGeometry,
    *,
    crop_present: bool,
) -> tuple[int, int] | None:
    _ = cfg
    if not crop_present:
        return None
    return geometry.phone_size


__all__ = [
    "content_size_for_crop",
    "effector_frame_resolution",
    "make_device_geometry",
]
