"""Shared device geometry contract assembly."""

from __future__ import annotations

from glassbox.boundaries import DeviceGeometry
from glassbox.config import AgentConfig
from glassbox.effector import BackendCapabilities


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


def content_size_for_crop(
    cfg: AgentConfig,
    geometry: DeviceGeometry,
    *,
    capabilities: BackendCapabilities | None = None,
) -> tuple[int, int]:
    _ = cfg
    if capabilities is not None and capabilities.coordinate_space == "phone_pt":
        if geometry.phone_points is None:
            raise ValueError("DeviceGeometry.phone_points is required for point-space crop detection")
        return geometry.phone_points
    if geometry.phone_size is None:
        raise ValueError("DeviceGeometry.phone_size is required for crop detection")
    return geometry.phone_size


def effector_frame_resolution(
    cfg: AgentConfig,
    geometry: DeviceGeometry,
    *,
    crop_present: bool,
    capabilities: BackendCapabilities | None = None,
) -> tuple[int, int] | None:
    _ = cfg
    if not crop_present:
        return None
    if capabilities is not None and capabilities.coordinate_space == "phone_pt":
        return geometry.phone_points
    return geometry.phone_size


__all__ = [
    "content_size_for_crop",
    "effector_frame_resolution",
    "make_device_geometry",
]
