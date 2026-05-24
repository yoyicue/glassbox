"""Home-screen icon map — VLM names detected icon cells, cached for reuse.

OCR cannot reliably read iOS Home screen icon labels (small, low-contrast), so
`find_springboard_icon`'s OCR-label path misses. This builds a map instead:

  1. ``detect_icons`` → precise icon-cell boxes (geometry, no names)
  2. set-of-marks the cells, ask the VLM to name each one
  3. map = ``{app_name: IconRegion}``, cached keyed by the cell layout

VLMs are unreliable at coordinates, so the VLM only *names* cells — all
geometry comes from ``detect_icons``. The Home screen is static, so one VLM
call builds a map reused for the whole session (and persisted across sessions);
a layout change or a tap that fails to leave Home rebuilds it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glassbox.cognition.icon_detect import (
    IconRegion,
    active_icon_backend,
    detect_icons_voted,
)
from glassbox.cognition.som import render_set_of_mark
from glassbox.cognition.text_match import fuzzy_ratio, text_contains, texts_match

_SYSTEM = (
    "You label iOS Home screen app icons. The image is an iPhone Home screen "
    "with red numbered boxes drawn over candidate app icons."
)
_USER = (
    "Each red numbered box marks one app icon. For every box you can identify, "
    "return the app's name. Use the app's common name (Chinese if the device is "
    "Chinese, e.g. 设置, 相机, App Store). Reply JSON only: "
    '{"icons": [{"id": <box number>, "app": "<app name>"}, ...]}. '
    "Omit boxes that are not app icons (widgets, dock blanks, the search pill)."
)


def _quantize_center(region: IconRegion, grid: int = 20) -> tuple[int, int]:
    cx, cy = region.center
    return (cx // grid, cy // grid)


def layout_key(regions: list[IconRegion], *, backend: str | None = None) -> str:
    """A layout fingerprint, tolerant of a few px of detector wobble.

    Keyed on quantized cell centers — independent of OCR. A changed Home layout
    (icons added / removed / rearranged) changes the key, so the cache for the
    old layout is simply never hit again.

    The key is **namespaced by the detector backend** (default: the active one)
    because different detectors find different cell sets on the same Home screen
    (classical ≈ 11 cells, omniparser ≈ 17). Without the namespace, a map built
    by one detector could be served to another; with it, the on-disk JSON keys
    also self-document which detector built each entry (e.g. ``omniparser:1a2b…``).
    """
    tag = backend or active_icon_backend()
    pts = sorted(_quantize_center(r) for r in regions)
    return f"{tag}:{hashlib.sha1(repr(pts).encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True)
class IconMapEntry:
    """One named Home screen icon."""

    app: str
    box: tuple[int, int, int, int]   # x, y, w, h — cropped-frame px

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.box
        return (x + w // 2, y + h // 2)


def build_icon_map(
    frames: list[Any],
    *,
    vlm,
    text_boxes: tuple[tuple[int, int, int, int], ...] = (),
) -> tuple[str, list[IconMapEntry]]:
    """Detect Home icon cells, have the VLM name them. Returns (layout_key, entries).

    ``frames`` are cropped Home-screen frames (BGR ndarrays); multiple frames
    feed ``detect_icons_voted`` for a stable cell set. Raises if no icons are
    detected or the VLM call fails — callers fall back to the OCR-label path.
    """
    import cv2

    regions = detect_icons_voted(list(frames), text_boxes=text_boxes,
                                 min_frames=1 if len(frames) == 1 else 2)
    if not regions:
        raise RuntimeError("no Home icon cells detected")

    ok, png = cv2.imencode(".png", frames[-1])
    if not ok:
        raise RuntimeError("could not encode Home frame")
    elements = [
        {"id": i, "box": [r.box[0], r.box[1], r.box[0] + r.box[2], r.box[1] + r.box[3]]}
        for i, r in enumerate(regions)
    ]
    marked = render_set_of_mark(png.tobytes(), elements)

    resp = vlm.chat(system=_SYSTEM, user_text=_USER, image=marked, json_object=True)
    parsed = resp.parsed or {}
    entries: list[IconMapEntry] = []
    seen: set[str] = set()
    for item in parsed.get("icons", []):
        if not isinstance(item, dict):
            continue
        idx = item.get("id")
        app = str(item.get("app") or "").strip()
        if not isinstance(idx, int) or not (0 <= idx < len(regions)) or not app:
            continue
        if app in seen:                       # one name → one cell (first wins)
            continue
        seen.add(app)
        entries.append(IconMapEntry(app=app, box=regions[idx].box))
    return layout_key(regions), entries


def match_entry(entries: list[IconMapEntry], labels) -> IconMapEntry | None:
    """Find the entry whose app name best matches any of ``labels`` (fuzzy)."""
    labels = [str(label) for label in labels]
    best: IconMapEntry | None = None
    best_ratio = 0.72
    for entry in entries:
        for label in labels:
            if texts_match(entry.app, label) or text_contains(entry.app, label) \
                    or text_contains(label, entry.app):
                return entry
            ratio = fuzzy_ratio(entry.app, label)
            if ratio >= best_ratio:
                best, best_ratio = entry, ratio
    return best


class SpringboardIconMap:
    """Cache of Home-screen icon maps, keyed by cell layout.

    Persisted as JSON so the Home map survives across glassbox runs on the same
    device. ``invalidate`` drops a layout's map (call it when a tap on a mapped
    icon failed to leave the Home screen — the layout drifted).
    """

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else None
        self._cache: dict[str, list[IconMapEntry]] = {}
        if self._path and self._path.exists():
            self._load()

    def get(self, regions: list[IconRegion]) -> list[IconMapEntry] | None:
        return self._cache.get(layout_key(regions))

    def put(self, key: str, entries: list[IconMapEntry]) -> None:
        self._cache[key] = entries
        self._save()

    def invalidate(self, regions: list[IconRegion]) -> None:
        if self._cache.pop(layout_key(regions), None) is not None:
            self._save()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for key, items in raw.items():
            self._cache[key] = [
                IconMapEntry(app=it["app"], box=tuple(it["box"])) for it in items
            ]

    def _save(self) -> None:
        if self._path is None:
            return
        data = {
            key: [{"app": e.app, "box": list(e.box)} for e in entries]
            for key, entries in self._cache.items()
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")
