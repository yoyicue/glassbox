"""Smoke tests for the Home-screen icon map (glassbox/ios/springboard_map.py)."""
from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition.icon_detect import IconRegion
from glassbox.ios.springboard_map import (
    IconMapEntry,
    SpringboardIconMap,
    build_icon_map,
    layout_key,
    match_entry,
)

_REGIONS = [
    IconRegion(box=(40, 300, 60, 60)),
    IconRegion(box=(160, 300, 60, 60)),
    IconRegion(box=(280, 300, 60, 60)),
]


@pytest.mark.smoke
def test_layout_key_tolerates_wobble_but_tracks_changes():
    # a few px of detector wobble stays inside the quantization grid → same key
    wobbled = [IconRegion(box=(x + 3, y - 2, w, h)) for x, y, w, h in
               (r.box for r in _REGIONS)]
    assert layout_key(_REGIONS) == layout_key(wobbled)
    # an added / moved icon → different key (old cache simply never hit again)
    moved = [*_REGIONS, IconRegion(box=(40, 460, 60, 60))]
    assert layout_key(_REGIONS) != layout_key(moved)


@pytest.mark.smoke
def test_match_entry_exact_contains_and_fuzzy():
    entries = [
        IconMapEntry(app="设置", box=(0, 0, 10, 10)),
        IconMapEntry(app="App Store", box=(1, 1, 10, 10)),
    ]
    assert match_entry(entries, ["设置"]).app == "设置"
    assert match_entry(entries, ["Settings", "设置"]).app == "设置"
    assert match_entry(entries, ["App"]).app == "App Store"   # contains
    assert match_entry(entries, ["完全不相干xyz"]) is None


@pytest.mark.smoke
def test_icon_map_cache_put_get_invalidate(tmp_path):
    path = tmp_path / "springboard_map.json"
    cache = SpringboardIconMap(path)
    assert cache.get(_REGIONS) is None

    entries = [IconMapEntry(app="设置", box=(280, 300, 60, 60))]
    cache.put(layout_key(_REGIONS), entries)
    assert cache.get(_REGIONS)[0].app == "设置"

    # persisted: a fresh cache from the same file sees it
    assert SpringboardIconMap(path).get(_REGIONS)[0].box == (280, 300, 60, 60)

    cache.invalidate(_REGIONS)
    assert cache.get(_REGIONS) is None


@pytest.mark.smoke
def test_icon_map_cache_is_segmented_by_backend(tmp_path, monkeypatch):
    """A map built by one detector must never be served to another: classical and
    omniparser find different cell sets on the same Home screen, so reusing one
    under the other would mis-place taps."""
    path = tmp_path / "map.json"
    entries = [IconMapEntry(app="设置", box=(280, 300, 60, 60))]

    # build + persist while classical is active
    monkeypatch.setenv("GLASSBOX_ICON_DETECTOR", "classical")
    cache = SpringboardIconMap(path)
    cache.put(layout_key(_REGIONS), entries)
    assert cache.get(_REGIONS)[0].app == "设置"

    # same regions, omniparser now active → cache miss (no cross-serve)
    monkeypatch.setenv("GLASSBOX_ICON_DETECTOR", "omniparser")
    assert SpringboardIconMap(path).get(_REGIONS) is None

    # keys are namespaced and self-documenting
    assert layout_key(_REGIONS, backend="classical").startswith("classical:")
    assert layout_key(_REGIONS, backend="omniparser").startswith("omniparser:")
    assert layout_key(_REGIONS, backend="classical") != layout_key(_REGIONS, backend="omniparser")
    assert SpringboardIconMap(path).get(_REGIONS) is None


class _FakeVLM:
    def __init__(self, parsed):
        self._parsed = parsed

    def chat(self, **_kw):
        class _Resp:
            parsed = self._parsed
        return _Resp()


@pytest.mark.smoke
def test_build_icon_map_names_cells_from_vlm(monkeypatch):
    monkeypatch.setattr(
        "glassbox.ios.springboard_map.detect_icons_voted", lambda *a, **k: _REGIONS)
    vlm = _FakeVLM({"icons": [
        {"id": 0, "app": "电话"},
        {"id": 2, "app": "设置"},
        {"id": 9, "app": "越界"},          # id out of range → skipped
        {"id": 1, "app": "电话"},          # duplicate name → skipped
    ]})
    frame = np.zeros((600, 360, 3), dtype=np.uint8)

    key, entries = build_icon_map([frame], vlm=vlm)

    assert key == layout_key(_REGIONS)
    got = {e.app: e.box for e in entries}
    assert got == {"电话": (40, 300, 60, 60), "设置": (280, 300, 60, 60)}
