"""Foreground app viewport helpers.

The controlled device can be an iPad while the foreground app renders in an
iPhone-compatibility window. In that case perception may want the inner app
window, while actuation must still target the outer iPad coordinate system.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

IPHONE_COMPAT_ASPECTS = (
    393 / 852,
    402 / 874,
    430 / 932,
    440 / 956,
)


@dataclass(frozen=True)
class ViewportCrop:
    """A rectangular child viewport inside a parent frame."""

    name: str
    parent_coordinate_space: str
    coordinate_space: str
    bbox: tuple[int, int, int, int]

    @property
    def size(self) -> tuple[int, int]:
        _x, _y, w, h = self.bbox
        return w, h

    def crop(self, img: np.ndarray) -> np.ndarray:
        x, y, w, h = self.bbox
        return img[y:y + h, x:x + w]

    def child_to_parent(self, x: float, y: float) -> tuple[int, int]:
        bx, by, _w, _h = self.bbox
        return round(float(x) + bx), round(float(y) + by)


def detect_iphone_compat_viewport(
    img: np.ndarray,
    *,
    threshold: int = 24,
    min_area_ratio: float = 0.18,
    aspect_tolerance: float = 0.12,
    center_tolerance: float = 0.20,
) -> ViewportCrop | None:
    """Detect a centered iPhone-shaped app window inside an iPad frame.

    This intentionally handles only the easy, safe case: a foreground region
    that differs from the surrounding background and has an iPhone-like aspect.
    Dark-on-dark apps or heavily blurred backgrounds should use an explicit
    configured bbox instead of guessing.
    """
    if img.ndim != 3 or img.shape[0] <= 0 or img.shape[1] <= 0:
        return None
    h, w = img.shape[:2]
    bg = _edge_median_color(img)
    diff = np.max(np.abs(img.astype(np.int16) - bg.astype(np.int16)), axis=2)
    ys, xs = np.where(diff > int(threshold))
    if xs.size == 0 or ys.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bbox = _trim_bbox((x0, y0, x1 - x0 + 1, y1 - y0 + 1), frame_size=(w, h))
    _x, _y, bw, bh = bbox
    if bw <= 0 or bh <= 0:
        return None
    if (bw * bh) / max(1, w * h) < float(min_area_ratio):
        return None
    aspect = bw / bh
    if min(abs(aspect - target) / target for target in IPHONE_COMPAT_ASPECTS) > float(aspect_tolerance):
        return None
    center_x = _x + bw / 2
    if abs(center_x - w / 2) > w * float(center_tolerance):
        return None
    return ViewportCrop(
        name="app",
        parent_coordinate_space="cropped_px",
        coordinate_space="app_px",
        bbox=bbox,
    )


def _edge_median_color(img: np.ndarray) -> np.ndarray:
    top = img[:1, :, :]
    bottom = img[-1:, :, :]
    left = img[:, :1, :]
    right = img[:, -1:, :]
    edges = np.concatenate(
        [
            top.reshape(-1, img.shape[2]),
            bottom.reshape(-1, img.shape[2]),
            left.reshape(-1, img.shape[2]),
            right.reshape(-1, img.shape[2]),
        ],
        axis=0,
    )
    return np.median(edges, axis=0)


def _trim_bbox(
    bbox: tuple[int, int, int, int],
    *,
    frame_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    fw, fh = frame_size
    x = max(0, min(int(x), fw))
    y = max(0, min(int(y), fh))
    w = max(0, min(int(w), fw - x))
    h = max(0, min(int(h), fh - y))
    return x, y, w, h


__all__ = ["ViewportCrop", "detect_iphone_compat_viewport"]
