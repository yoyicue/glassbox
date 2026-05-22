"""glassbox/cognition/asset_match.py — match an on-screen icon to an asset.

Given a detected element's region and a small candidate set of asset-catalog
PNGs (scoped to the current VC's known_elements — see glassbox/profile.py),
multi-scale template-matches the region against each asset and returns the
best name. This is how a perceived element gets its `whitebox_hint.asset_match`
(docs/design/gui_understanding.md §6.4 — the known-app anchor cache).

Best-effort by construction: assets are exported @1x and the on-screen icon
may be tinted / scaled, so matching is correlation-based with a conservative
threshold. A miss simply leaves the element at Tier 0 (pure vision).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

# correlation below this is treated as "no confident match"
DEFAULT_THRESHOLD = 0.6
# template sizes tried, as a fraction of the element's shorter side
_SCALES = (0.6, 0.75, 0.9, 1.0)


@lru_cache(maxsize=256)
def _load_gray(path_str: str) -> np.ndarray | None:
    """Load an asset PNG as grayscale, compositing any alpha over white (so a
    transparent-background icon matches a rendered one). Handles L / LA / BGR /
    BGRA PNGs. Returns None for an unreadable or degenerate (flat) asset."""
    import cv2

    img = cv2.imread(path_str, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    if img.ndim == 2:                                   # L — already grayscale
        gray = img
    else:
        ch = img.shape[2]
        if ch == 2:                                     # LA — gray + alpha
            base = img[:, :, 0].astype(np.float32)
            alpha = img[:, :, 1].astype(np.float32) / 255.0
        elif ch == 4:                                   # BGRA
            base = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
            alpha = img[:, :, 3].astype(np.float32) / 255.0
        else:                                           # BGR
            base = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
            alpha = np.ones(img.shape[:2], dtype=np.float32)
        gray = (base * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)

    # a flat icon carries no shape signal — correlation against it is meaningless
    if float(gray.std()) < 1.0:
        return None
    return gray


def match_asset(
    frame_bgr: np.ndarray,
    box: tuple[int, int, int, int],
    candidates: list[tuple[str, Path]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str, float] | None:
    """Best asset name + correlation score for the element at `box`, or None.

    box: (x, y, w, h). candidates: (asset_name, png_path) pairs.
    """
    import cv2

    if not candidates:
        return None
    x, y, w, h = box
    if w < 6 or h < 6:
        return None

    H, W = frame_bgr.shape[:2]
    pad = max(4, min(w, h) // 6)
    crop = frame_bgr[max(0, y - pad):min(H, y + h + pad),
                     max(0, x - pad):min(W, x + w + pad)]
    if crop.size == 0:
        return None
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # a flat crop (no icon, e.g. plain background) → nothing to correlate against
    if float(crop_gray.std()) < 1.0:
        return None
    ch, cw = crop_gray.shape
    base = min(w, h)

    best_name: str | None = None
    best_score = 0.0
    for name, path in candidates:
        asset = _load_gray(str(path))
        if asset is None:
            continue
        for s in _SCALES:
            side = max(8, int(base * s))
            if side >= ch or side >= cw:
                continue
            tmpl = cv2.resize(asset, (side, side), interpolation=cv2.INTER_AREA)
            score = float(cv2.matchTemplate(crop_gray, tmpl, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score and -1.0 <= score <= 1.0:
                best_name, best_score = name, score

    if best_name is not None and best_score >= threshold:
        return best_name, best_score
    return None
