"""VLM row-level OCR fallback (F).

When on-device OCR of a single row is too noisy for B/C confusion matching to
resolve it against any known label, crop just that row and let the VLM read
it. Slow + billed, so this is a *fallback* — gate it on a real OCR miss and
cache by crop signature so the same row is not re-billed across scroll frames.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol

from glassbox.cognition.base import Box
from glassbox.cognition.text_match import canonical_label


class _TextRegionReader(Protocol):
    def read_text_region(self, *, region_image: bytes) -> str: ...


class _ChatClient(Protocol):
    def chat(self, **kwargs) -> Any: ...


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


def horizontal_band_box(
    frame_img: Any,
    box: Any,
    *,
    x: int = 0,
    width: int | None = None,
    pad_y: int = 8,
    min_height: int = 34,
) -> Box:
    """Return a shallow horizontal band around an element.

    This is useful when OCR split a list row into noisy fragments. The crop is
    wider than the element but remains local vertically, so a VLM sees row
    context without receiving the whole screen.
    """
    frame_h, frame_w = frame_img.shape[:2]
    crop_w = frame_w - x if width is None else width
    crop_w = max(1, min(crop_w, frame_w - max(0, x)))
    raw_h = max(min_height, int(box.h) + pad_y * 2)
    h = min(frame_h, raw_h)
    cy = int(box.y) + int(box.h) // 2
    y = cy - h // 2
    y = max(0, min(y, frame_h - h))
    return Box(x=max(0, x), y=y, w=crop_w, h=h)


def encode_crop_png(frame_img: Any, box: Any, *, pad: int = 6) -> bytes | None:
    """Encode a local crop as PNG bytes for VLM requests."""
    import cv2

    crop = crop_box(frame_img, box, pad=pad)
    if crop is None or crop.size == 0:
        return None
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        return None
    return png.tobytes()


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
    data = encode_crop_png(frame_img, box, pad=pad)
    if data is None:
        return ""
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


def choose_label_from_region(
    client: _ChatClient,
    frame_img: Any,
    box: Any,
    labels: Iterable[str],
    *,
    pad: int = 0,
    cache: dict[str, str] | None = None,
    aliases: Mapping[str, str] | None = None,
    fuzzy: float = 0.82,
    system: str | None = None,
    user_prefix: str | None = None,
    normalizer: Callable[[str], str | None] | None = None,
) -> str | None:
    """Ask a VLM to choose one label from a closed set using only a local crop.

    The VLM never receives the full screen. The caller supplies the closed set,
    and this helper validates the raw answer against it before returning.
    """
    if not hasattr(client, "chat"):
        return None
    label_tuple = tuple(labels)
    if not label_tuple:
        return None
    data = encode_crop_png(frame_img, box, pad=pad)
    if data is None:
        return None
    key = "choice:" + hashlib.sha1(data).hexdigest()
    if cache is not None and key in cache:
        cached = cache[key]
        return cached if cached != "NONE" else None
    choices = "、".join(label_tuple)
    try:
        response = client.chat(
            system=system or (
                "You are a UI text recognizer. The image is a local crop, not a full screen. "
                "Choose exactly one label from the provided candidates, or output NONE."
            ),
            user_text=(
                f"{user_prefix.rstrip()}\n" if user_prefix else ""
            ) + f"候选标签 / Candidate labels: {choices}\nReturn only one candidate label, or NONE.",
            image=data,
            json_object=False,
        )
    except Exception:
        return None
    raw = str(getattr(response, "raw_content", "") or "").strip()
    label = normalizer(raw) if normalizer is not None else None
    if label is not None and label not in label_tuple:
        label = None
    if label is None:
        label = canonical_label(raw, label_tuple, aliases=aliases, fuzzy=fuzzy)
    if label is None and raw in label_tuple:
        label = raw
    if cache is not None:
        cache[key] = label or "NONE"
    return label
