"""skills/smoke/test_memory_observe.py

Phase c — transition edges from observe(). Fully offline.

Coverage:
  - observe(prev) then observe(next, action) → one A→B edge labelled by the action
  - repeating the same transition bumps count, does not duplicate the edge
  - observe with no preceding action → no edge
  - current_vc is retained as node metadata, not used as the whole node identity
"""

from __future__ import annotations

import pytest

from glassbox.cognition.base import Box, Scene, UIElement, WhiteboxHint
from glassbox.ios.scene import apply_ios_classification
from glassbox.memory import UTG, ScreenMemory


def _el(eid, text):
    return UIElement(type="button", box=Box(x=eid * 10, y=eid * 10, w=80, h=30),
                     text=text, confidence=0.9, element_id=eid)


def _scene(*texts, current_vc=None):
    return Scene(frame_id=0, timestamp=0.0,
                 elements=[_el(i, t) for i, t in enumerate(texts)],
                 current_vc=current_vc)


@pytest.mark.smoke
def test_observe_records_transition_edge():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("登录", "密码", "忘记密码"))
    b = mem.observe(_scene("设置", "隐私", "关于", "帮助"),
                    last_action=("tap", {"via": "tap_text", "target": "设置"}))
    assert len(mem.utg.edges) == 1
    e = mem.utg.edges[0]
    assert (e.from_id, e.to_id) == (a.screen_id, b.screen_id)
    assert e.action_op == "tap" and e.element_key == "text:设置" and e.count == 1
    assert e.action_kwargs == {"via": "tap_text", "target": "设置"}
    assert e.success_count == 1
    assert e.no_progress_count == 0
    assert e.success_rate == 1.0
    assert e.last_outcome == "progress"


@pytest.mark.smoke
def test_repeated_transition_bumps_count():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    for _ in range(3):
        mem.observe(_scene("登录", "密码", "忘记密码"))
        mem.observe(_scene("设置", "隐私", "关于", "帮助"),
                    last_action=("tap", {"target": "设置"}))
    assert len(mem.utg.edges) == 1
    assert mem.utg.edges[0].count == 3
    assert mem.utg.edges[0].success_count == 3
    assert mem.utg.edges[0].no_progress_count == 0
    assert mem.utg.edges[0].success_rate == 1.0


@pytest.mark.smoke
def test_no_progress_transition_records_action_outcome():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("登录", "密码", "忘记密码"))
    same = mem.observe(_scene("登录", "密码", "忘记密码"),
                       last_action=("tap", {"target": "登录"}))

    assert a.screen_id == same.screen_id
    assert len(mem.utg.edges) == 1
    e = mem.utg.edges[0]
    assert (e.from_id, e.to_id) == (a.screen_id, a.screen_id)
    assert e.action_op == "tap"
    assert e.element_key == "text:登录"
    assert e.count == 1
    assert e.success_count == 0
    assert e.no_progress_count == 1
    assert e.success_rate == 0.0
    assert e.last_outcome == "no_progress"


@pytest.mark.smoke
def test_same_node_scroll_can_record_explicit_progress_outcome():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("设置", "通知", "声效与触感", "专注模式", "屏幕时间"))
    same = mem.observe(
        _scene("设置", "通知", "声效与触感", "专注模式", "屏幕时间"),
        last_action=("scroll_wheel", {"ticks": 30, "outcome": "progress"}),
    )

    assert same.screen_id == a.screen_id
    assert len(mem.utg.edges) == 1
    e = mem.utg.edges[0]
    assert (e.from_id, e.to_id) == (a.screen_id, a.screen_id)
    assert e.action_op == "scroll_wheel"
    assert e.success_count == 1
    assert e.no_progress_count == 0
    assert e.success_rate == 1.0
    assert e.last_outcome == "progress"


@pytest.mark.smoke
def test_failed_or_synthetic_action_does_not_teach_edge():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene("A"))
    mem.observe(_scene("B"), last_action=("tap", {"target": "B", "action_ok": False}))
    mem.observe(_scene("B"))
    mem.observe(_scene("C"), last_action=("tap", {
        "target": "C",
        "action_ok": True,
        "action_synthetic": True,
    }))

    assert mem.utg.edges == []


@pytest.mark.smoke
def test_policy_action_classifies_back_and_page_swipes_without_scroll():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene("child"))
    mem.observe(_scene("root"), last_action=("swipe", {
        "x1": 4,
        "y1": 500,
        "x2": 350,
        "y2": 500,
        "via": "back_gesture",
        "action_ok": True,
        "action_synthetic": False,
    }))
    mem.observe(_scene("page1"))
    mem.observe(_scene("page2"), last_action=("swipe", {
        "x1": 380,
        "y1": 700,
        "x2": 40,
        "y2": 700,
        "via": "swipe_left",
        "action_ok": True,
        "action_synthetic": False,
    }))
    mem.observe(_scene("list1"))
    mem.observe(_scene("list2"), last_action=("swipe", {
        "x1": 220,
        "y1": 800,
        "x2": 220,
        "y2": 300,
        "via": "swipe_up",
        "action_ok": True,
        "action_synthetic": False,
    }))

    policies = [edge.policy_action for edge in mem.utg.edges]
    assert policies == ["back", "page", "scroll"]
    assert mem.path_to_page(
        mem.utg.edges[0].from_id,
        "root",
        allowed_actions={"back"},
    ) is None


@pytest.mark.smoke
def test_physical_success_action_teaches_edge():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("A"))
    b = mem.observe(_scene("B"), last_action=("tap", {
        "target": "B",
        "action_ok": True,
        "action_synthetic": False,
    }))

    assert len(mem.utg.edges) == 1
    assert (mem.utg.edges[0].from_id, mem.utg.edges[0].to_id) == (a.screen_id, b.screen_id)


@pytest.mark.smoke
def test_swipe_identity_includes_geometry_and_coordinate_space():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene("A"))
    mem.observe(_scene("B"), last_action=("swipe", {
        "x1": 200,
        "y1": 800,
        "x2": 200,
        "y2": 200,
        "coordinate_space": "phone_pt",
        "action_ok": True,
        "action_synthetic": False,
    }))
    mem.observe(_scene("A"))
    mem.observe(_scene("B"), last_action=("swipe", {
        "x1": 200,
        "y1": 800,
        "x2": 200,
        "y2": 500,
        "coordinate_space": "phone_pt",
        "action_ok": True,
        "action_synthetic": False,
    }))

    identities = {edge.action_identity for edge in mem.utg.edges}
    assert len(identities) == 2
    assert all(identity and identity.startswith("gesture:phone_pt:up:") for identity in identities)


@pytest.mark.smoke
def test_scroll_overshoot_is_quality_penalty_not_success():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene("设置", "通知", "通用"))
    mem.observe(
        _scene("设置", "通知", "通用"),
        last_action=("scroll_wheel", {"ticks": 30, "outcome": "overshoot"}),
    )

    edge = mem.utg.edges[0]
    assert edge.count == 1
    assert edge.success_count == 0
    assert edge.no_progress_count == 0
    assert edge.overshoot_count == 1
    assert edge.success_rate == 0.0
    assert edge.last_outcome == "overshoot"


@pytest.mark.smoke
def test_legacy_phone_coordinate_space_normalizes_to_frame_px():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene("A"))
    mem.observe(_scene("B"), last_action=("tap", {
        "x": 160,
        "y": 240,
        "coordinate_space": "phone",
    }))

    edge = mem.utg.edges[0]
    assert edge.action is not None
    assert edge.action.coordinate_space == "frame_px"
    assert edge.action_identity == "coord:frame_px:2:3"


@pytest.mark.smoke
def test_observe_without_action_adds_no_edge():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    mem.observe(_scene("登录", "密码", "忘记密码"))
    mem.observe(_scene("设置", "隐私", "关于", "帮助"))      # no last_action
    assert mem.utg.edges == []


@pytest.mark.smoke
def test_merge_scene_metadata_rebinds_current_transition_source():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    pre_describe = mem.observe(_scene("登录", "密码"))

    enriched_scene = _scene("登录", "密码", current_vc="LoginViewController")
    enriched = mem.merge_scene_metadata(enriched_scene)
    assert enriched.screen_id != pre_describe.screen_id

    after_tap = mem.observe(
        _scene("首页", "设置", current_vc="HomeViewController"),
        last_action=("tap", {"target": "登录"}),
    )

    assert len(mem.utg.edges) == 1
    edge = mem.utg.edges[0]
    assert (edge.from_id, edge.to_id) == (enriched.screen_id, after_tap.screen_id)


@pytest.mark.smoke
def test_current_vc_is_metadata_not_node_id():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    n = mem.observe(_scene("设备列表", current_vc="ListViewController"))
    assert n.screen_id.startswith("scr_")
    assert n.screen_id != "ListViewController"
    assert n.vc_name == "ListViewController"
    assert mem.utg.nodes[n.screen_id] is n


@pytest.mark.smoke
def test_same_vc_distinct_screen_signatures_do_not_collapse():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    list_node = mem.observe(_scene("设备列表", "重新扫描", current_vc="ListViewController"))
    detail_node = mem.observe(_scene("设备详情", "序列号", "返回", current_vc="ListViewController"))

    assert list_node.screen_id != detail_node.screen_id
    assert list_node.vc_name == detail_node.vc_name == "ListViewController"
    assert len(mem.utg.nodes) == 2


@pytest.mark.smoke
def test_same_vc_same_screen_signature_collapses():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    first = mem.observe(_scene("设备列表", "重新扫描", current_vc="ListViewController"))
    second = mem.observe(_scene("设备列表", "重新扫描", current_vc="ListViewController"))

    assert first.screen_id == second.screen_id
    assert first.visit_count == 2


@pytest.mark.smoke
def test_same_vc_conflicting_app_state_does_not_collapse():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    logged_out = _scene("账户", "会员", current_vc="AccountViewController")
    logged_out.app_state = {"auth": "logged_out"}
    logged_in = _scene("账户", "会员", current_vc="AccountViewController")
    logged_in.app_state = {"auth": "logged_in"}

    out_node = mem.observe(logged_out)
    in_node = mem.observe(logged_in)

    assert out_node.screen_id != in_node.screen_id
    assert len(mem.utg.nodes) == 2


@pytest.mark.smoke
def test_observe_records_ios_scene_classification_metadata():
    mem = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=190, y=58, w=70, h=34), text="设置", confidence=0.9),
            UIElement(type="button", box=Box(x=78, y=360, w=86, h=28), text="无线局域网", confidence=0.9),
            UIElement(type="button", box=Box(x=78, y=420, w=50, h=28), text="蓝牙", confidence=0.9),
            UIElement(type="button", box=Box(x=78, y=480, w=70, h=28), text="通用", confidence=0.9),
        ],
    )

    apply_ios_classification(scene, viewport_size=(448, 973))
    node = mem.observe(scene)

    assert node.scene_type == "settings_root"
    assert node.page_id == "settings/root"
    assert "scroll" in node.safe_actions
    assert node.classification_source == "ios"
    assert "root_markers" in node.classification_evidence


@pytest.mark.smoke
def test_merge_scene_metadata_clears_authoritative_stale_fields():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    initial = _scene("账户", "会员")
    initial.page_id = "account/main"
    initial.safe_actions = ["tap_upgrade"]
    initial.classification_source = "test"
    initial.app_state = {"auth": "logged_in"}
    node = mem.observe(initial)

    refreshed = _scene("账户", "会员")
    refreshed.classification_source = "test"
    refreshed.classification_confidence = 0.8
    refreshed.classification_evidence = ["no_safe_action"]
    refreshed.app_state = {"auth": "unknown"}

    same = mem.merge_scene_metadata(refreshed)

    assert same.screen_id == node.screen_id
    assert same.page_id is None
    assert same.safe_actions == []
    assert same.classification_source == "test"
    assert same.classification_confidence == 0.8
    assert same.classification_evidence == ["no_safe_action"]
    assert same.app_state == {}


@pytest.mark.smoke
def test_merge_element_metadata_clears_authoritative_missing_intent_and_whitebox():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    initial = Scene(frame_id=0, timestamp=0.0, elements=[
        UIElement(
            type="button",
            box=Box(x=20, y=100, w=120, h=40),
            text="登录",
            confidence=0.9,
            intent_label="确认登录",
            whitebox_hint=WhiteboxHint(vc_name="LoginVC", asset_match="login_button"),
        ),
    ])
    node = mem.observe(initial)

    refreshed = Scene(frame_id=1, timestamp=1.0, vlm_status="ok", elements=[
        UIElement(
            type="button",
            box=Box(x=20, y=100, w=120, h=40),
            text="登录",
            confidence=0.9,
            intent_label=None,
            whitebox_hint=None,
        ),
    ])
    refreshed.whitebox_evaluated = True
    same = mem.merge_scene_metadata(refreshed)
    remembered = same.element("text:登录")

    assert same.screen_id == node.screen_id
    assert remembered is not None
    assert remembered.intent_label is None
    assert remembered.whitebox_hint is None


@pytest.mark.smoke
def test_authoritative_refresh_marks_disappeared_elements_stale():
    mem = ScreenMemory(UTG(bundle_id="com.x"), match_threshold=0.0)
    initial = Scene(frame_id=0, timestamp=0.0, elements=[
        UIElement(
            type="button",
            box=Box(x=20, y=100, w=120, h=40),
            text=None,
            confidence=0.9,
            intent_label="确认登录",
            whitebox_hint=WhiteboxHint(vc_name="LoginVC", asset_match="login_button"),
        ),
        UIElement(type="text", box=Box(x=20, y=160, w=120, h=40), text="说明", confidence=0.9),
    ])
    node = mem.observe(initial)

    refreshed = Scene(
        frame_id=1,
        timestamp=1.0,
        vlm_status="ok",
        elements=[
            UIElement(type="text", box=Box(x=20, y=160, w=120, h=40), text="说明", confidence=0.9),
        ],
    )
    refreshed.whitebox_evaluated = True

    same = mem.merge_scene_metadata(refreshed)
    stale = same.element("asset:login_button")

    assert same.screen_id == node.screen_id
    assert stale is not None
    assert stale.present is False
    assert stale.missing_count == 1
    assert stale.intent_label is None
    assert stale.whitebox_hint is None
    assert [e.key for e in mem.expected_elements(node.screen_id)] == ["text:说明"]
    assert {e.key for e in mem.expected_elements(node.screen_id, include_stale=True)} == {
        "asset:login_button",
        "text:说明",
    }


@pytest.mark.smoke
def test_observe_keeps_ios_page_metadata_when_layer3_scene_type_exists():
    mem = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        scene_type="settings_root",
        elements=[
            UIElement(type="button", box=Box(x=190, y=58, w=70, h=34), text="设置", confidence=0.9),
            UIElement(type="button", box=Box(x=78, y=360, w=86, h=28), text="无线局域网", confidence=0.9),
            UIElement(type="button", box=Box(x=78, y=420, w=50, h=28), text="蓝牙", confidence=0.9),
        ],
    )

    apply_ios_classification(scene, viewport_size=(448, 973))
    node = mem.observe(scene)

    assert node.scene_type == "settings_root"
    assert node.page_id == "settings/root"
    assert "tap_root_row" in node.safe_actions


@pytest.mark.smoke
def test_observe_preserves_layer3_scene_type_over_ios_back_heuristic():
    mem = ScreenMemory(UTG(bundle_id="com.example.app"))
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        scene_type="login_form",
        elements=[
            UIElement(type="nav_back", box=Box(x=18, y=64, w=24, h=24), text="返回", confidence=0.9),
            UIElement(type="button", box=Box(x=170, y=80, w=90, h=30), text="登录", confidence=0.9),
            UIElement(type="input", box=Box(x=40, y=180, w=360, h=44), text="邮箱", confidence=0.9),
            UIElement(type="input", box=Box(x=40, y=240, w=360, h=44), text="密码", confidence=0.9),
        ],
    )

    node = mem.observe(scene)

    assert node.scene_type == "login_form"
    assert "back" not in node.safe_actions


@pytest.mark.smoke
def test_observe_does_not_write_settings_metadata_for_generic_app_scene():
    mem = ScreenMemory(UTG(bundle_id="com.example.app"))
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        scene_type="paywall",
        elements=[
            UIElement(type="button", box=Box(x=180, y=78, w=110, h=24), text="音频与视觉", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=132, w=220, h=24), text="使左右扬声器播放同一内容。", confidence=0.9),
            UIElement(type="button", box=Box(x=70, y=190, w=140, h=28), text="始终显示音量控制", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=234, w=330, h=28), text="在锁定屏幕上显示耳机和内建扬声器的音量控制。", confidence=0.9),
            UIElement(type="button", box=Box(x=70, y=294, w=110, h=28), text="添加语音突显", confidence=0.9),
            UIElement(type="text", box=Box(x=42, y=338, w=330, h=28), text="将分离人声添加为突显对话的额外选项。", confidence=0.9),
        ],
    )

    node = mem.observe(scene)

    assert node.scene_type == "paywall"
    assert node.page_id is None
    assert node.safe_actions == []


@pytest.mark.smoke
def test_coordinate_actions_use_distinct_edge_identities():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("登录", "密码", "忘记密码"))
    b = mem.observe(_scene("设置", "隐私", "关于", "帮助"),
                    last_action=("tap", {"via": "tap_xy", "x": 40, "y": 80}))
    mem._last_node_id = a.screen_id
    mem.observe(_scene("设置", "隐私", "关于", "帮助"),
                last_action=("tap", {"via": "tap_xy", "x": 260, "y": 80}))

    assert len(mem.utg.edges) == 2
    identities = {edge.action_identity for edge in mem.utg.edges}
    assert identities == {"coord:frame_px:0:1", "coord:frame_px:3:1"}
    assert {edge.to_id for edge in mem.utg.edges} == {b.screen_id}


@pytest.mark.smoke
def test_key_actions_use_modifier_and_keycode_identity():
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    a = mem.observe(_scene("登录", "密码", "忘记密码"))
    mem.observe(_scene("设置", "隐私", "关于", "帮助"),
                last_action=("key", {"modifier": 8, "keycode": 47}))
    mem._last_node_id = a.screen_id
    mem.observe(_scene("设置", "隐私", "关于", "帮助"),
                last_action=("key", {"modifier": 8, "keycode": 40}))

    assert len(mem.utg.edges) == 2
    assert {edge.action_identity for edge in mem.utg.edges} == {"key:8:47", "key:8:40"}


@pytest.mark.smoke
def test_autosave_persists_every_n_observations():
    """CUQ-3.22: incremental persistence fires every N observations so a mid-run
    crash keeps the learned graph (not only on close)."""
    saved: list[int] = []
    mem = ScreenMemory(
        UTG(bundle_id="com.x"),
        autosave=lambda utg: saved.append(len(utg.nodes)),
        autosave_every=2,
    )

    mem.observe(_scene("登录", "密码"))
    assert saved == []  # below threshold
    mem.observe(_scene("设置", "隐私", "关于"),
                last_action=("tap", {"via": "tap_text", "target": "设置"}))
    assert len(saved) == 1  # fired at the 2nd observation
    mem.observe(_scene("通用", "辅助功能"))
    assert len(saved) == 1  # counter reset; below threshold again
    mem.observe(_scene("电池", "隐私与安全性"))
    assert len(saved) == 2


@pytest.mark.smoke
def test_autosave_off_by_default_and_tolerates_save_errors():
    # Default (no autosave): never persists mid-run.
    mem = ScreenMemory(UTG(bundle_id="com.x"))
    for _ in range(5):
        mem.observe(_scene("登录", "密码"))  # must not raise

    # A failing autosave callback must not break observe().
    def boom(_utg):
        raise OSError("disk full")

    noisy = ScreenMemory(UTG(bundle_id="com.x"), autosave=boom, autosave_every=1)
    node = noisy.observe(_scene("设置"))
    assert node is not None
