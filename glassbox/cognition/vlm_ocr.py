"""VLM row-level OCR fallback (F).

When on-device OCR of a single row is too noisy for B/C confusion matching to
resolve it against any known label, crop just that row and let the VLM read
it. Slow + billed, so this is a *fallback* — gate it on a real OCR miss and
cache by crop signature so the same row is not re-billed across scroll frames.
"""
from __future__ import annotations

import hashlib
from typing import Any, Protocol


class _TextRegionReader(Protocol):
    def read_text_region(self, *, region_image: bytes) -> str: ...


def crop_box(frame_img: Any, box: Any, *, pad: int = 6) -> Any | None:
    """Crop a UIElement.box region (x/y/w/h) out of a BGR frame, with padding.

    Returns None when the box lands fully outside the frame.
    """
    h, w = frame_img.shape[:2]
    x1 = max(0, int(box.x) - pad)
    y1 = max(0, int(box.y) - pad)
    x2 = min(w, int(box.x) + int(box.w) + pad)
    y2 = min(h, int(box.y) + int(box.h) + pad)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame_img[y1:y2, x1:x2]


def read_row_text(
    client: _TextRegionReader,
    frame_img: Any,
    box: Any,
    *,
    pad: int = 6,
    cache: dict[str, str] | None = None,
) -> str:
    """Crop the row at `box` from `frame_img` and have the VLM read its text.

    `cache` (a plain dict) keyed by crop image hash avoids re-billing the same
    row seen across multiple scroll frames. Returns "" on any failure.
    """
    import cv2

    crop = crop_box(frame_img, box, pad=pad)
    if crop is None or crop.size == 0:
        return ""
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        return ""
    data = png.tobytes()
    key = hashlib.sha1(data).hexdigest()
    if cache is not None and key in cache:
        return cache[key]
    try:
        text = client.read_text_region(region_image=data)
    except Exception:
        # VLM fallback must never break the caller — degrade to empty.
        return ""
    if cache is not None and text:
        cache[key] = text
    return text
