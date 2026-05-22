"""glassbox/perception/letterbox.py — HDMI letterbox detection + coordinate transform

When the iPhone screen mirror goes through HDMI into the capture card, the
card outputs a fixed 16:9 landscape signal (e.g. 1920x1080) with the phone
content letterboxed in the middle (black bars on both sides). We need to:

1. Auto-detect the letterbox to obtain the content bbox (the cropped frame
   size is roughly the phone's aspect ratio)
2. Feed the cropped frame to OCR / VLM (saves tokens and time, avoids
   spurious detections on the black bars)
3. On tap, transform "cropped frame coordinates" into "iPhone logical
   coordinates" before feeding them to the HID bridge

LetterboxCrop is a read-only value object; measure the letterbox once at
startup and reuse it for the whole run.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def detect_letterbox(img: np.ndarray, *, threshold: int = 20) -> tuple[int, int, int, int]:
    """Measure the bbox of the non-black content, returning (x, y, w, h).

    threshold: grayscale threshold; any pixel brighter than threshold counts
    as content. If the whole image is below the threshold (the phone may be
    locked, or the signal may be disconnected), raise ValueError.
    """
    if img.ndim == 3:
        gray = img.max(axis=2)              # faster than cvtColor, and per-pixel max(R,G,B) is more sensitive
    elif img.ndim == 2:
        gray = img
    else:
        raise ValueError(f"unexpected img shape: {img.shape}")

    col_max = gray.max(axis=0)
    row_max = gray.max(axis=1)
    nonblack_cols = np.where(col_max > threshold)[0]
    nonblack_rows = np.where(row_max > threshold)[0]

    if nonblack_cols.size == 0 or nonblack_rows.size == 0:
        raise ValueError(
            f"detect_letterbox: the entire image is below threshold={threshold}; "
            f"the phone may be locked or there is no HDMI signal"
        )

    x0, x1 = int(nonblack_cols.min()), int(nonblack_cols.max())
    y0, y1 = int(nonblack_rows.min()), int(nonblack_rows.max())
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


@dataclass(frozen=True)
class LetterboxCrop:
    """Coordinate transform between capture card frames and phone logical
    coordinates.

    crop_bbox: the content region's (x, y, w, h) within the source frame
    frame_size: source frame (W, H) -- sanity check only
    phone_size: iPhone logical screen (W, H), e.g. 17 Pro Max = (1320, 2868)

    The cropped frame is the crop_bbox region of the image; the coordinate
    systems are:
      - cropped coordinates: the cropped frame's own (0..w-1, 0..h-1)
      - phone coordinates: iPhone logical pixels (0..phone_w-1, 0..phone_h-1)
      - the two are related by a linear scale, no rotation (the capture card
        outputs in the phone's original orientation)
    """

    crop_bbox: tuple[int, int, int, int]
    frame_size: tuple[int, int]
    phone_size: tuple[int, int]

    # —— factory ——
    @classmethod
    def auto_detect(
        cls,
        frame: np.ndarray,
        phone_size: tuple[int, int],
        *,
        threshold: int = 20,
        min_area_ratio: float = 0.20,
        aspect_tolerance: float = 0.20,
    ) -> LetterboxCrop:
        h, w = frame.shape[:2]
        bbox = detect_letterbox(frame, threshold=threshold)
        _validate_content_bbox(
            bbox,
            frame_size=(w, h),
            phone_size=phone_size,
            min_area_ratio=min_area_ratio,
            aspect_tolerance=aspect_tolerance,
        )
        return cls(crop_bbox=bbox, frame_size=(w, h), phone_size=phone_size)

    # —— derived properties ——
    @property
    def cropped_size(self) -> tuple[int, int]:
        _, _, w, h = self.crop_bbox
        return w, h

    @property
    def scale_x(self) -> float:
        return self.phone_size[0] / self.crop_bbox[2]

    @property
    def scale_y(self) -> float:
        return self.phone_size[1] / self.crop_bbox[3]

    # —— image ——
    def crop(self, img: np.ndarray) -> np.ndarray:
        """Crop the content region out of the source frame. Returns a numpy
        view (no copy)."""
        x, y, w, h = self.crop_bbox
        return img[y:y + h, x:x + w]

    # —— coordinate transform ——
    def cropped_to_phone(self, x: float, y: float) -> tuple[int, int]:
        """Cropped frame coordinates -> iPhone logical coordinates."""
        return round(x * self.scale_x), round(y * self.scale_y)

    def phone_to_cropped(self, x: float, y: float) -> tuple[int, int]:
        """iPhone logical coordinates -> cropped frame coordinates."""
        return round(x / self.scale_x), round(y / self.scale_y)

    def cropped_to_frame(self, x: float, y: float) -> tuple[int, int]:
        """Cropped frame coordinates -> source frame coordinates (including
        the letterbox)."""
        cx, cy, _, _ = self.crop_bbox
        return round(x) + cx, round(y) + cy


def _validate_content_bbox(
    bbox: tuple[int, int, int, int],
    *,
    frame_size: tuple[int, int],
    phone_size: tuple[int, int],
    min_area_ratio: float,
    aspect_tolerance: float,
) -> None:
    """Reject a bbox that is likely only bright text/icons inside a dark app."""
    _x, _y, bw, bh = bbox
    fw, fh = frame_size
    pw, ph = phone_size
    if bw <= 0 or bh <= 0 or pw <= 0 or ph <= 0:
        raise ValueError("detect_letterbox: invalid frame or phone dimensions")

    frame_area = max(1, fw * fh)
    area_ratio = (bw * bh) / frame_area
    if area_ratio < min_area_ratio:
        raise ValueError(
            "detect_letterbox: detected content bbox is too small to be the "
            f"phone screen ({area_ratio:.3f} < {min_area_ratio:.3f})"
        )

    bbox_aspect = bw / bh
    phone_aspect = pw / ph
    rel_error = abs(bbox_aspect - phone_aspect) / max(phone_aspect, 1e-6)
    if rel_error > aspect_tolerance:
        raise ValueError(
            "detect_letterbox: detected content bbox aspect does not match "
            f"phone aspect ({bbox_aspect:.3f} vs {phone_aspect:.3f})"
        )
