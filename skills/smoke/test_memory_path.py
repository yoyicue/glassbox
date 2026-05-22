"""skills/smoke/test_memory_path.py

Phase d — path() transition planning (BFS over edges). Fully offline.

Coverage:
  - A→B→C chain: path(A, C) returns the 2 ordered edges
  - path(X, X) → [] (already there)
  - an unreachable target → None
  - an unknown node → None
"""

from __future__ import annotations

import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.memory import UTG, ScreenMemory


def _scene(*texts):
    els = [UIElement(type="button", box=Box(x=i * 10, y=i * 10, w=80, h=30),
                     text=t, confidence=0.9, element_id=i) for i, t in enumerate(texts)]
    return Scene(frame_id=0, timestamp=0.0, elements=els)


@pytest.fixture
def chain():
    """A→B→C built by observation, plus an isolated node D."""
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("a1", "a2", "a3"))
    b = mem.observe(_scene("b1", "b2", "b3", "b4"), last_action=("tap", {"target": "to_b"}))
    c = mem.observe(_scene("c1", "c2", "c3", "c4", "c5"), last_action=("tap", {"target": "to_c"}))
    mem._last_node_id = None                                  # break the chain
    d = mem.observe(_scene("d1", "d2", "d3", "d4", "d5", "d6"))  # isolated, no edge
    return mem, a.screen_id, b.screen_id, c.screen_id, d.screen_id


@pytest.mark.smoke
def test_path_finds_chain(chain):
    mem, a, b, c, _d = chain
    p = mem.path(a, c)
    assert p is not None and len(p) == 2
    assert [e.from_id for e in p] == [a, b]
    assert [e.to_id for e in p] == [b, c]


@pytest.mark.smoke
def test_path_to_self_is_empty(chain):
    mem, a, *_ = chain
    assert mem.path(a, a) == []


@pytest.mark.smoke
def test_path_unreachable_is_none(chain):
    mem, a, _b, _c, d = chain
    assert mem.path(a, d) is None                # nothing transitions into D


@pytest.mark.smoke
def test_path_unknown_node_is_none(chain):
    mem, a, *_ = chain
    assert mem.path(a, "no_such_screen") is None
    assert mem.path("no_such_screen", a) is None


@pytest.mark.smoke
def test_path_to_page_finds_semantic_target_with_safety_filters():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("a1", "a2", "a3"))
    b = mem.observe(_scene("b1", "b2", "b3", "b4"), last_action=("tap", {"target": "to_b"}))
    root = mem.observe(_scene("设置", "无线局域网", "蓝牙", "通用"), last_action=("home", {}))
    root.page_id = "settings/root"
    root.scene_type = "settings_root"

    path = mem.path_to_page(
        a.screen_id,
        "settings/root",
        scene_type="settings_root",
        allowed_actions={"tap", "home"},
        min_success_rate=0.5,
    )

    assert path is not None
    assert [edge.from_id for edge in path] == [a.screen_id, b.screen_id]
    assert [edge.to_id for edge in path] == [b.screen_id, root.screen_id]
    assert mem.path_to_page(a.screen_id, "settings/root", allowed_actions={"home"}) is None


@pytest.mark.smoke
def test_path_to_page_filters_low_success_edges():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("a1", "a2", "a3"))
    root = mem.observe(_scene("设置", "无线局域网", "蓝牙", "通用"), last_action=("tap", {"target": "设置"}))
    root.page_id = "settings/root"
    edge = mem.utg.edges[0]
    edge.success_count = 0
    edge.no_progress_count = edge.count
    edge.success_rate = 0.0
    edge.last_outcome = "no_progress"

    assert mem.path_to_page(a.screen_id, "settings/root", min_success_rate=0.5) is None
    assert mem.path_to_page(a.screen_id, "settings/root", min_success_rate=0.0) is not None


@pytest.mark.smoke
def test_path_to_page_accepts_platform_scene_kind_and_policy_action():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("child", "detail"))
    root = mem.observe(_scene("设置", "无线局域网", "蓝牙", "通用"), last_action=("key", {
        "modifier": 0x08,
        "keycode": 0x2F,
        "action_ok": True,
        "action_synthetic": False,
    }))
    root.page_id = "settings/root"
    root.platform_scene_kind = "settings_root"

    path = mem.path_to_page(
        a.screen_id,
        "settings/root",
        scene_type="settings_root",
        allowed_actions={"back"},
        min_success_rate=0.5,
    )

    assert path is not None
    assert path[0].action_op == "key"
    assert path[0].policy_action == "back"
