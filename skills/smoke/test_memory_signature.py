"""skills/smoke/test_memory_signature.py

Phase a — structural screen signature + recognition. Fully offline.

Coverage:
  - dhash: stable for one image, differs for different images, "" for tiny/None
  - compute_signature: list-item text excluded from stable_texts; status_bar
    excluded from the type histogram
  - similarity: self == 1.0; a list-row-only difference stays "same screen";
    structurally different scenes fall below threshold
  - recognize: two frames of one screen collapse to one node; unseen → None
"""

from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.memory import UTG, ScreenMemory, ScreenNode, compute_signature, dhash, similarity
from glassbox.memory.signature import SIGNATURE_MATCH_THRESHOLD


def _el(eid, text, *, type_="button", x=0, y=0):
    return UIElement(type=type_, box=Box(x=x, y=y, w=80, h=30),
                     text=text, confidence=0.9, element_id=eid)


def _scene(*elements, scene_type=None, current_vc=None):
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements),
                 scene_type=scene_type, current_vc=current_vc)


# ─── dhash ───────────────────────────────────────────────────────────
@pytest.mark.smoke
def test_dhash_stable_and_64bit():
    img = np.random.RandomState(0).randint(0, 256, (400, 300, 3), dtype=np.uint8)
    h1, h2 = dhash(img), dhash(img.copy())
    assert h1 == h2 and len(h1) == 64 and set(h1) <= {"0", "1"}


@pytest.mark.smoke
def test_dhash_differs_for_different_images():
    a = np.zeros((400, 300, 3), np.uint8)
    b = np.random.RandomState(1).randint(0, 256, (400, 300, 3), dtype=np.uint8)
    assert dhash(a) != dhash(b)


@pytest.mark.smoke
def test_dhash_empty_for_missing_or_tiny():
    assert dhash(None) == ""
    assert dhash(np.zeros((1, 1, 3), np.uint8)) == ""


# ─── compute_signature ───────────────────────────────────────────────
@pytest.mark.smoke
def test_signature_excludes_list_item_text():
    """List rows churn — their text must not enter the stable signature."""
    sig = compute_signature(_scene(
        _el(0, "设备列表", type_="text"),
        _el(1, "usg-pro-4", type_="list_item"),
        _el(2, "unifi", type_="list_item"),
        _el(3, "重新扫描", type_="button"),
    ))
    assert "设备列表" in sig.stable_texts
    assert "重新扫描" in sig.stable_texts
    assert "usg-pro-4" not in sig.stable_texts and "unifi" not in sig.stable_texts


@pytest.mark.smoke
def test_signature_excludes_status_bar_from_histogram():
    sig = compute_signature(_scene(
        _el(0, "9:41", type_="status_bar"),
        _el(1, "登录", type_="button"),
    ))
    assert "status_bar" not in sig.type_histogram
    assert sig.type_histogram.get("button") == 1
    assert "9:41" not in sig.stable_texts


@pytest.mark.smoke
def test_similarity_tolerates_status_bar_clock_churn():
    a = compute_signature(_scene(
        _el(0, "9:41", type_="status_bar"),
        _el(1, "登录", type_="button"),
    ))
    b = compute_signature(_scene(
        _el(0, "9:42", type_="status_bar"),
        _el(1, "登录", type_="button"),
    ))
    assert similarity(a, b) >= SIGNATURE_MATCH_THRESHOLD


# ─── similarity ──────────────────────────────────────────────────────
@pytest.mark.smoke
def test_similarity_self_is_one():
    sig = compute_signature(_scene(_el(0, "登录"), _el(1, "注册")))
    assert similarity(sig, sig) == 1.0


@pytest.mark.smoke
def test_similarity_tolerates_list_row_churn():
    """Same device-list screen, different rows → still recognized as same."""
    a = compute_signature(_scene(
        _el(0, "设备列表", type_="text"), _el(1, "重新扫描", type_="button"),
        _el(2, "usg-pro-4", type_="list_item"),
    ))
    b = compute_signature(_scene(
        _el(0, "设备列表", type_="text"), _el(1, "重新扫描", type_="button"),
        _el(2, "totally-different-device", type_="list_item"),
    ))
    assert similarity(a, b) >= SIGNATURE_MATCH_THRESHOLD


@pytest.mark.smoke
def test_similarity_low_for_different_screens():
    a = compute_signature(_scene(_el(0, "登录"), _el(1, "密码"), _el(2, "忘记密码")))
    b = compute_signature(_scene(_el(0, "设置"), _el(1, "隐私"), _el(2, "关于"), _el(3, "帮助")))
    assert similarity(a, b) < SIGNATURE_MATCH_THRESHOLD


# ─── recognize ───────────────────────────────────────────────────────
@pytest.mark.smoke
def test_recognize_collapses_one_screen_to_one_node():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    s1 = _scene(_el(0, "登录"), _el(1, "密码"), _el(2, "忘记密码"))
    s2 = _scene(_el(0, "登录"), _el(1, "密码"), _el(2, "忘记密码"))
    n1 = mem.observe(s1)
    n2 = mem.observe(s2)
    assert n1.screen_id == n2.screen_id
    assert len(mem.utg.nodes) == 1
    assert n1.visit_count == 2


@pytest.mark.smoke
def test_recognize_returns_none_for_unseen():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene(_el(0, "登录"), _el(1, "密码")))
    unseen = _scene(_el(0, "设置"), _el(1, "隐私"), _el(2, "关于"), _el(3, "帮助"))
    assert mem.recognize(unseen) is None
    assert len(mem.utg.nodes) == 1          # recognize must not mutate


@pytest.mark.smoke
def test_recognize_uses_current_vc_when_present():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    n = mem.observe(_scene(_el(0, "x"), current_vc="ListViewController"))
    assert n.screen_id.startswith("scr_") and n.vc_name == "ListViewController"
    same = mem.recognize(_scene(_el(0, "x"), current_vc="ListViewController"))
    assert same is not None and same.screen_id == n.screen_id
    other_vc = mem.recognize(_scene(_el(0, "x"), current_vc="DetailViewController"))
    assert other_vc is None


@pytest.mark.smoke
def test_recognize_falls_back_when_current_vc_is_missing():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    n = mem.observe(_scene(_el(0, "x"), current_vc="ListViewController"))

    same_without_vc = mem.recognize(_scene(_el(0, "x"), current_vc=None))

    assert same_without_vc is not None
    assert same_without_vc.screen_id == n.screen_id


@pytest.mark.smoke
def test_current_vc_does_not_collapse_distinct_signatures():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    list_node = mem.observe(_scene(
        _el(0, "设备列表"),
        _el(1, "重新扫描"),
        current_vc="ListViewController",
    ))
    detail_node = mem.observe(_scene(
        _el(0, "设备详情"),
        _el(1, "序列号"),
        _el(2, "返回"),
        current_vc="ListViewController",
    ))

    assert list_node.screen_id != detail_node.screen_id
    assert len(mem.utg.nodes) == 2


@pytest.mark.smoke
def test_legacy_vc_keyed_node_still_recognizes_by_signature():
    scene = _scene(_el(0, "设备列表"), current_vc="ListViewController")
    legacy = ScreenNode(
        screen_id="ListViewController",
        vc_name="ListViewController",
        signature=compute_signature(scene),
    )
    mem = ScreenMemory(UTG(bundle_id="com.x", nodes={legacy.screen_id: legacy}))

    hit = mem.recognize(scene)

    assert hit is not None and hit.screen_id == "ListViewController"
