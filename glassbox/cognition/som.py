"""glassbox/cognition/som.py — visual Set-of-Mark annotation.

Draws a numbered box onto the screenshot for every candidate element, so the
VLM references elements by a mark it can *see* — instead of mentally aligning
text-form box coordinates against image regions (which it does poorly).

This is the gold-standard VLM prompt shape; see docs/design/gui_understanding.md
§6.1. The number drawn equals the element's `id`, so the VLM's reply ("id=3
is the login button") maps straight back to our own element table for exact
coordinates — the VLM never has to emit a pixel coordinate itself.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# cv2 uses BGR ordering
_MARK_BGR = (60, 60, 230)        # red box + red number tag
_TEXT_BGR = (255, 255, 255)      # white number


def render_set_of_mark(image: bytes, elements: list[dict[str, Any]]) -> bytes:
    """Draw a numbered red box for each element; return annotated PNG bytes.

    elements: [{"id": int, "box": [x1, y1, x2, y2], ...}, ...]
    An element without a usable 4-tuple box is skipped (it still appears in the
    text element list). If the image cannot be decoded the input is returned
    unchanged — annotation is best-effort, never fatal.
    """
    import cv2

    img = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return image

    h, w = img.shape[:2]
    thickness = max(2, round(min(h, w) / 600))
    font = cv2.FONT_HERSHEY_SIMPLEX
    base_scale = max(0.5, min(h, w) / 1400)

    for el in elements:
        box = el.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x1, y1, x2, y2 = (int(v) for v in box)
        except (TypeError, ValueError):
            continue
        x1, x2 = sorted((_clamp(x1, w), _clamp(x2, w)))
        y1, y2 = sorted((_clamp(y1, h), _clamp(y2, h)))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue

        cv2.rectangle(img, (x1, y1), (x2, y2), _MARK_BGR, thickness)

        # tag scales with the box so a small control gets a small mark; placed
        # OUTSIDE the box (just above its top-left, or below if there is no room
        # above) — the tag never occludes the element it labels, which matters
        # for tiny icon-only controls where the icon IS the only semantic cue.
        label = str(el.get("id", "?"))
        scale = max(0.4, min(base_scale, min(x2 - x1, y2 - y1) / 40))
        (tw, th), bl = cv2.getTextSize(label, font, scale, thickness)
        tag_w, tag_h = tw + 8, th + bl + 6
        ty1 = y1 - tag_h if y1 - tag_h >= 0 else y2          # above, else below
        cv2.rectangle(img, (x1, ty1), (x1 + tag_w, ty1 + tag_h), _MARK_BGR, -1)
        cv2.putText(img, label, (x1 + 4, ty1 + th + 3), font, scale,
                    _TEXT_BGR, thickness, cv2.LINE_AA)

    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else image


def _clamp(v: int, hi: int) -> int:
    return max(0, min(v, hi))
