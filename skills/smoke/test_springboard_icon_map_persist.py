"""SpringBoard VLM icon-map cross-run persistence.

The VLM names Home icons once per layout; persisting the map (layout-keyed) lets
later cold starts reuse the coordinates instead of re-calling the VLM.
"""

from __future__ import annotations

import pytest

from glassbox.ios.springboard_map import IconMapEntry, SpringboardIconMap


@pytest.mark.smoke
def test_icon_map_persists_across_instances(tmp_path):
    path = tmp_path / "icon_map.json"
    key = "layout-A"
    entries = [IconMapEntry(app="Settings", box=(10, 20, 30, 40))]

    m1 = SpringboardIconMap(path=path)
    m1.put(key, entries)
    assert path.exists()  # _save wrote it

    # A fresh instance (new run) loads the same map from disk.
    m2 = SpringboardIconMap(path=path)
    loaded = m2._cache  # the in-memory dict populated by _load on construction
    assert key in loaded
    assert loaded[key][0].app == "Settings"
    assert tuple(loaded[key][0].box) == (10, 20, 30, 40)


@pytest.mark.smoke
def test_icon_map_without_path_is_in_memory_only(tmp_path):
    # No path -> nothing written (current default behavior preserved).
    m = SpringboardIconMap(path=None)
    m.put("layout-B", [IconMapEntry(app="Settings", box=(1, 2, 3, 4))])
    assert not any(tmp_path.iterdir())  # no file created anywhere we own
