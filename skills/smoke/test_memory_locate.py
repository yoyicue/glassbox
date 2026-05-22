"""skills/smoke/test_memory_locate.py

Phase b — element-layout memory: element keys, box merging, locate. Offline.

Coverage:
  - element_key priority: own text > whitebox asset > accessibility id > grid
  - a stable element's box is EMA-smoothed across visits
  - a volatile (list-item) element takes the latest box, not an average
  - locate returns the remembered box; None for an unknown screen/element
  - expected_elements returns the merged layout
"""

from __future__ import annotations

import pytest

from glassbox.cognition.base import Box, Scene, UIElement, WhiteboxHint
from glassbox.memory import UTG, ScreenMemory
from glassbox.memory.element_key import element_key


def _el(eid, text, *, type_="button", box=(0, 0, 80, 30), whitebox=None):
    return UIElement(type=type_, box=Box(x=box[0], y=box[1], w=box[2], h=box[3]),
                     text=text, confidence=0.9, element_id=eid, whitebox_hint=whitebox)


def _scene(*elements):
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


# ─── element_key priority ────────────────────────────────────────────
@pytest.mark.smoke
def test_element_key_prefers_text():
    assert element_key(_el(0, "登录"), (750, 1334)) == "text:登录"


@pytest.mark.smoke
def test_element_key_falls_back_to_asset_then_aid():
    asset = _el(0, None, type_="image", whitebox=WhiteboxHint(asset_match="cold_icon"))
    assert element_key(asset, (750, 1334)) == "asset:cold_icon"
    aid = _el(1, None, type_="button", whitebox=WhiteboxHint(accessibility_id="loginBtn"))
    assert element_key(aid, (750, 1334)) == "aid:loginBtn"


@pytest.mark.smoke
def test_element_key_grid_fallback_for_anonymous_icon():
    icon = _el(0, None, type_="image", box=(20, 20, 40, 40))
    key = element_key(icon, (750, 1334))
    assert key.startswith("image@") and "," in key


# ─── box merging ─────────────────────────────────────────────────────
@pytest.mark.smoke
def test_stable_element_box_is_ema_smoothed():
    """Same screen twice, the '登录' button shifts 100→200 → EMA(α=0.4)=140."""
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene(_el(0, "登录", box=(100, 500, 80, 30)), _el(1, "密码")))
    node = mem.observe(_scene(_el(0, "登录", box=(200, 500, 80, 30)), _el(1, "密码")))
    box = mem.locate(node.screen_id, "text:登录")
    assert box is not None and box.x == 140


@pytest.mark.smoke
def test_volatile_element_takes_latest_box_not_average():
    """A list row that scrolled keeps its newest box (averaging is meaningless)."""
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    # two stable anchors keep it the same screen across both observes
    def anchors():
        return (_el(8, "设备列表", type_="text"), _el(9, "重新扫描", type_="button"))
    mem.observe(_scene(*anchors(), _el(0, "usg-pro-4", type_="list_item", box=(40, 200, 600, 70))))
    node = mem.observe(_scene(*anchors(), _el(0, "usg-pro-4", type_="list_item", box=(40, 900, 600, 70))))
    row = node.element("text:usg-pro-4")
    assert row is not None and row.volatile is True
    assert row.box.y == 900                     # latest, not 0.4*900+0.6*200


# ─── locate / expected_elements ──────────────────────────────────────
@pytest.mark.smoke
def test_locate_returns_none_for_unknown():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    node = mem.observe(_scene(_el(0, "登录")))
    assert mem.locate("no_such_screen", "text:登录") is None
    assert mem.locate(node.screen_id, "text:不存在") is None


@pytest.mark.smoke
def test_expected_elements_returns_merged_layout():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene(_el(0, "登录"), _el(1, "密码"), _el(2, "忘记密码")))
    node = mem.observe(_scene(_el(0, "登录"), _el(1, "密码"), _el(2, "忘记密码")))
    keys = {e.key for e in mem.expected_elements(node.screen_id)}
    assert keys == {"text:登录", "text:密码", "text:忘记密码"}
    assert all(e.visit_count == 2 for e in mem.expected_elements(node.screen_id))
