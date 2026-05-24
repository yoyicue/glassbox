"""glassbox/cognition/icon_detect.py — visually detect icon elements that OCR cannot see

Apple Vision OCR cannot produce candidates for **pure graphic buttons**
(no text / strokes too thin), and downstream params like NL / customWords
cannot rescue them either. The same class of problem:
  - the `-` minus sign (only a 29×3 stroke; but an unsharp mask makes Vision
    misrecognize it as an em-dash, which rescues it)
  - the `×` close button at the top-right of a modal sheet (gray circle + a
    small × stroke, completely ignored by Vision)
  - assorted SVG icon buttons (share / settings / delete)

`-` is already solved at the OCR layer via unsharp; `×` cannot be rescued
even with morphology (its stroke is as thin as `-` but has no symmetry
reference). This module provides a **visual feature detection** fallback,
synthesizing a UIElement so walkthrough scripts can hit it with
`tap_button("×")` / `tap_intent("关闭")`.

Current implementation:
  find_modal_close(cropped_img) — iOS standard gray circular close button (top-right)

A new detector follows the same idea:
  1. restrict the search region (top-right / top-left / bottom, etc.)
  2. threshold + connected components
  3. filter by size / shape / color saturation
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def find_modal_close(
    cropped_img: np.ndarray,
    *,
    top_strip: float = 0.15,
    right_strip: float = 0.25,
    min_dim: int = 18,
    max_dim: int = 50,
    min_fill: float = 0.5,
    max_saturation: float = 40.0,
    thresh: int = 240,
) -> tuple[int, int, int, int] | None:
    """Find the iOS standard gray circular close button at the top-right of a cropped frame.

    Returns the (x, y, w, h) bbox (cropped coordinate system), or None if not found.

    Parameters (all have sensible defaults, tuned on a reference iOS app):
      top_strip:    top N% height of the search region
      right_strip:  right N% width of the search region
      min/max_dim:  button width/height range (px)
      min_fill:     blob area / bbox area ≥ this value (filters out sparse contours)
      max_saturation: upper bound on mean HSV.S (the close circle is gray,
                    almost no saturation; colored icon widgets usually have S > 100)
      thresh:       grayscale threshold, circle backgrounds < thresh count as a blob

    Design:
      The key to distinguishing the close button from colored icon widgets is
      **color saturation**. The iOS gray circle has sat ≈ 10; colored widgets
      have sat ≈ 130+.
    """
    import cv2

    H, W = cropped_img.shape[:2]
    y_end = int(H * top_strip)
    x_start = int(W * (1 - right_strip))
    region = cropped_img[:y_end, x_start:]
    if region.size == 0:
        return None
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY_INV)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    candidates: list[tuple[int, int, int, int, float]] = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (min_dim <= w <= max_dim and min_dim <= h <= max_dim):
            continue
        if area / max(w * h, 1) < min_fill:
            continue
        aspect = w / max(h, 1)
        if not (0.7 <= aspect <= 1.4):
            continue
        s_mean = float(hsv[y:y + h, x:x + w, 1].mean())
        if s_mean > max_saturation:
            continue   # colored — not a close button
        # back to the cropped coordinate system
        candidates.append((x + x_start, y, w, h, s_mean))

    if not candidates:
        return None
    # with multiple candidates, take the one closest to the right edge (the close button is usually nearest the right edge)
    candidates.sort(key=lambda c: -(c[0] + c[2]))
    x, y, w, h, _ = candidates[0]
    return x, y, w, h


# ─── general no-text icon-region detection ───────────────────────────────
# `find_modal_close` is one tuned detector; the cold-start chain needs the
# general case: any compact no-text icon a VLM identified semantically but
# could only place at a rough coordinate. This detector gives such regions a
# precise box to anchor onto — the icon-side equivalent of OCR.


@dataclass
class IconRegion:
    """A detected no-text icon region, in cropped-frame pixels."""

    box: tuple[int, int, int, int]   # x, y, w, h

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.box
        return (x + w // 2, y + h // 2)


# ─── pluggable detector backends ─────────────────────────────────────────
# `detect_icons` dispatches to a named backend. The built-in `classical`
# backend (this module) needs no extra dependencies. Extra backends are
# drop-in plugins loaded from the `icon_backends/` directory next to this
# file — each plugin module calls `register_icon_backend()` at import time.
# That directory is git-ignored on purpose: the core stays dependency-clean
# and permissively (MIT) licensed, while heavier or differently-licensed
# detectors can be dropped in locally without entering version control.
# See glassbox/cognition/icon_backends/README.md.

IconBackend = Callable[..., "list[IconRegion]"]
_BACKENDS: dict[str, IconBackend] = {}
_PLUGINS_LOADED = False
_PLUGIN_DIR = Path(__file__).resolve().parent / "icon_backends"


def register_icon_backend(name: str, fn: IconBackend) -> None:
    """Register an icon-detection backend under `name` (called by plugins)."""
    _BACKENDS[name] = fn


def active_icon_backend() -> str:
    """The backend `detect_icons` uses when none is passed explicitly.

    Env-driven (`GLASSBOX_ICON_DETECTOR`), default ``classical``. Exposed so the
    Home icon-map cache can segment entries by the detector that built them — a
    classical-built map (one cell set) must not be served to omniparser (a
    different, usually larger cell set) and vice versa."""
    return os.environ.get("GLASSBOX_ICON_DETECTOR", "classical").strip().lower()


def _load_plugins() -> None:
    """Import every ``*.py`` under icon_backends/ once; each self-registers."""
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED:
        return
    _PLUGINS_LOADED = True
    if not _PLUGIN_DIR.is_dir():
        return
    import importlib.util

    for path in sorted(_PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"glassbox.cognition.icon_backends.{path.stem}", path)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        except Exception as exc:        # a broken plugin must never break the core
            from loguru import logger
            logger.warning(f"icon_detect: plugin {path.name} failed to load: {exc}")


def detect_icons(
    frame_img: np.ndarray,
    *,
    text_boxes: tuple[tuple[int, int, int, int], ...] = (),
    min_side: int = 14,
    max_side: int = 90,
    min_edge_fill: float = 0.04,
    backend: str | None = None,
) -> list[IconRegion]:
    """Detect compact icon regions in a cropped phone frame.

    The backend is selected by `backend`, or env `GLASSBOX_ICON_DETECTOR`,
    default ``classical`` (the built-in OpenCV detector — no extra deps). Any
    other name resolves to a drop-in plugin under ``icon_backends/`` (see that
    directory's README). Backend-specific kwargs a backend does not understand
    are ignored, so all backends share this one signature.
    """
    name = backend or active_icon_backend()
    if name != "classical":
        _load_plugins()
    fn = _BACKENDS.get(name)
    if fn is None:
        # A requested-but-unavailable backend (e.g. ``omniparser`` set in the
        # env on a machine that lacks the AGPL plugin/deps) must never break a
        # run — fall back to the always-present classical detector.
        from loguru import logger
        logger.warning(
            f"icon-detection backend {name!r} unavailable "
            f"(have {sorted(_BACKENDS)}); falling back to classical"
        )
        fn = _BACKENDS["classical"]
    return fn(frame_img, text_boxes=text_boxes, min_side=min_side,
              max_side=max_side, min_edge_fill=min_edge_fill)


def _detect_icons_classical(
    frame_img: np.ndarray,
    *,
    text_boxes: tuple[tuple[int, int, int, int], ...] = (),
    min_side: int = 14,
    max_side: int = 90,
    min_edge_fill: float = 0.04,
) -> list[IconRegion]:
    """Built-in OpenCV no-text icon detector — the default ``classical`` backend.

    `text_boxes` (OCR element boxes) are masked out — icons are, by definition,
    what OCR did not see. Returns icon-like regions: compact, roughly square,
    with real edge content, deduplicated by containment.
    """
    import cv2

    if frame_img is None or getattr(frame_img, "ndim", 0) < 2:
        return []
    gray = cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY) if frame_img.ndim == 3 else frame_img
    edges = cv2.Canny(gray, 60, 160)
    for x, y, w, h in text_boxes:                       # icons are the non-text remainder
        edges[max(0, y):y + h, max(0, x):x + w] = 0
    # close an icon's separate strokes into one blob before contouring
    closed = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    )
    found = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = found[0] if len(found) == 2 else found[1]

    regions: list[IconRegion] = []
    for contour in contours:
        x, y, w, h = (int(v) for v in cv2.boundingRect(contour))
        if not (min_side <= w <= max_side and min_side <= h <= max_side):
            continue
        if not (0.33 <= w / h <= 3.0):                  # reject lines / text remnants
            continue
        roi = edges[y:y + h, x:x + w]
        if roi.size == 0 or float((roi > 0).mean()) < min_edge_fill:
            continue                                    # reject near-empty boxes
        regions.append(IconRegion(box=(x, y, w, h)))

    # dedup: drop a region whose center sits inside a larger kept region
    regions.sort(key=lambda r: r.box[2] * r.box[3], reverse=True)
    kept: list[IconRegion] = []
    for r in regions:
        cx, cy = r.center
        if any(kx <= cx <= kx + kw and ky <= cy <= ky + kh
               for kx, ky, kw, kh in (k.box for k in kept)):
            continue
        kept.append(r)
    return kept


register_icon_backend("classical", _detect_icons_classical)


def detect_icons_voted(
    frames: list[np.ndarray],
    *,
    text_boxes: tuple[tuple[int, int, int, int], ...] = (),
    min_frames: int = 2,
    merge_dist: int = 16,
    **detect_kwargs,
) -> list[IconRegion]:
    """Multi-frame `detect_icons`: keep only regions seen in `min_frames` frames.

    A faint icon (a thin-stroke glyph on a near-white button) wobbles in and
    out of single-frame detection. Running several capture frames and keeping
    regions that recur across them both stabilizes faint icons and drops
    one-frame noise specks. Returns each surviving region's median box.
    """
    tagged: list[tuple[int, IconRegion]] = [
        (fi, r)
        for fi, frame in enumerate(frames)
        for r in detect_icons(frame, text_boxes=text_boxes, **detect_kwargs)
    ]
    clusters: list[list[tuple[int, IconRegion]]] = []
    for fi, r in tagged:
        cx, cy = r.center
        for cluster in clusters:
            kx, ky = cluster[0][1].center
            if abs(cx - kx) <= merge_dist and abs(cy - ky) <= merge_dist:
                cluster.append((fi, r))
                break
        else:
            clusters.append([(fi, r)])

    out: list[IconRegion] = []
    for cluster in clusters:
        if len({fi for fi, _ in cluster}) < min_frames:
            continue                                    # not seen in enough frames
        mid = len(cluster) // 2
        boxes = [r.box for _, r in cluster]
        out.append(IconRegion(box=(
            sorted(b[0] for b in boxes)[mid],
            sorted(b[1] for b in boxes)[mid],
            sorted(b[2] for b in boxes)[mid],
            sorted(b[3] for b in boxes)[mid],
        )))
    return out
