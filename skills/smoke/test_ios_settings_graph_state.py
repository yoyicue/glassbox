from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.ios.scene import apply_ios_classification
from glassbox.memory import UTG, ScreenMemory
from glassbox.memory.store import load_utg, save_utg
from skills.regression.ios_settings import core as walkthrough
from skills.regression.ios_settings import graph_state as settings_graph_state
from skills.regression.ios_settings import navigation as settings_navigation
from skills.regression.ios_settings import page_records as settings_page_records
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state


def _el(text: str, x: int, y: int, w: int = 80, h: int = 20, *, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


def _settings_root_scene() -> Scene:
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    apply_ios_classification(scene, viewport_size=(448, 973))
    return scene


def _ambiguous_child_scene() -> Scene:
    return _scene(_el("Loading", 160, 320, w=90))


def _settings_root_scene_variant() -> Scene:
    # A second, distinct root-signature node that still classifies settings_root
    # (e.g. the root scrolled to a different band). Different visible rows ⇒ a
    # different ScreenMemory node, but the same scene_type.
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("通用", 80, 300, w=40),
        _el("辅助功能", 80, 360, w=72),
        _el("操作按钮", 80, 420, w=72),
    )
    apply_ios_classification(scene, viewport_size=(448, 973))
    return scene


class _Phone:
    def __init__(self, memory: ScreenMemory | None):
        self.memory = memory
        self._last_frame = None

    def viewport_size(self):

        return self._viewport_size()

    def _viewport_size(self):
        return 448, 973


def _memory_with_root_edge(label: str = "Bluetooth") -> tuple[ScreenMemory, Scene]:
    memory = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    root = _settings_root_scene()
    child = _ambiguous_child_scene()
    memory.observe(root)
    memory.observe(child, last_action=("tap", {
        "via": "settings.tap_row",
        "target": label,
        "action_ok": True,
    }))
    return memory, child


@pytest.mark.smoke
def test_graph_scene_kind_marks_root_row_child_as_settings_detail():
    memory, child = _memory_with_root_edge("Bluetooth")
    phone = _Phone(memory)

    assert settings_scene_state.scene_kind(child, phone=phone) == "settings_detail"
    assert child.classification_source == "utg"
    assert "utg_root_detail_edge" in child.classification_evidence


@pytest.mark.smoke
def test_graph_scene_kind_respects_strong_home_counter_evidence():
    memory = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    root = _settings_root_scene()
    home = _scene(
        _el("FaceTime", 54, 400, w=90),
        _el("Calendar", 164, 400, w=78),
        _el("Photos", 276, 400, w=64),
        _el("Camera", 386, 400, w=68),
        _el("Notes", 54, 510, w=54),
        _el("Clock", 164, 510, w=54),
        _el("Settings", 164, 620, w=72),
        _el("Q Search", 198, 900, w=82),
    )
    memory.observe(root)
    memory.observe(home, last_action=("tap", {
        "via": "settings.tap_row",
        "target": "Bluetooth",
        "action_ok": True,
    }))
    phone = _Phone(memory)

    assert settings_scene_state.scene_kind(home, phone=phone) == "springboard"
    assert home.classification_source is None


@pytest.mark.smoke
def test_graph_root_coverage_uses_successful_root_outbound_edges():
    memory, _child = _memory_with_root_edge("Bluetooth")
    phone = _Phone(memory)

    coverage = settings_page_records.root_coverage([], phone=phone)
    enriched = settings_reporting.classify_root_coverage(coverage, [], [])

    assert "蓝牙" in coverage["visited"]
    assert "蓝牙" not in coverage["missing"]
    assert "蓝牙" in enriched["entered"]
    assert "蓝牙" in enriched["entered_graph"]


@pytest.mark.smoke
def test_graph_entered_root_does_not_suppress_visible_row_visit():
    memory, _child = _memory_with_root_edge("Bluetooth")
    phone = _Phone(memory)
    root = _settings_root_scene()
    visits: list[settings_reporting.PageVisit] = []
    seen: set[settings_page_records.ViewportKey] = set()

    settings_page_records.record_visible_root_row_visits(
        scene=root,
        visits=visits,
        seen_sigs=seen,
        phone=phone,
    )

    assert any(visit.path == ("Settings", "蓝牙") for visit in visits)


@pytest.mark.smoke
def test_graph_root_coverage_excludes_root_to_root_edges():
    # A no-SIM inert row (e.g. Mobile Service / 蜂窝网络) can tap and coincide with
    # a root re-render, producing a successful tap edge to a DIFFERENT root-
    # signature node. Both ends are settings_root, so this is NOT entering a detail
    # page and must never be credited as coverage (regression for the false
    # "16/17" en-HK credit).
    memory = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    root = _settings_root_scene()
    root_variant = _settings_root_scene_variant()
    memory.observe(root)
    memory.observe(root_variant, last_action=("tap", {
        "via": "settings.tap_row",
        "target": "蜂窝网络",
        "action_ok": True,
    }))
    phone = _Phone(memory)

    assert settings_graph_state.root_entered_labels(phone) == set()
    coverage = settings_page_records.root_coverage([], phone=phone)
    enriched = settings_reporting.classify_root_coverage(coverage, [], [])
    assert "蜂窝网络" not in coverage["visited"]
    assert "蜂窝网络" not in enriched["entered_graph"]
    assert "蜂窝网络" in coverage["missing"]


@pytest.mark.smoke
def test_graph_root_coverage_survives_persisted_memory(tmp_path):
    memory, child = _memory_with_root_edge("Bluetooth")
    save_utg(memory.utg, memory_dir=tmp_path)
    loaded = ScreenMemory(load_utg("com.apple.Preferences", memory_dir=tmp_path))
    phone = _Phone(loaded)

    assert "蓝牙" in settings_page_records.root_coverage([], phone=phone)["visited"]
    assert settings_scene_state.scene_kind(child, phone=phone) == "settings_detail"


@pytest.mark.smoke
def test_graph_inert_root_labels_come_from_repeated_self_loop_edges():
    memory = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    root = _settings_root_scene()
    memory.observe(root)
    for _ in range(2):
        memory.observe(root, last_action=("tap", {
            "via": "settings.tap_row",
            "target": "蜂窝网络",
            "action_ok": True,
            "action_outcome": "no_progress",
        }))
    phone = _Phone(memory)

    assert settings_graph_state.inert_root_labels(phone) == {"蜂窝网络"}
    assert "蜂窝网络" in walkthrough._entry_exempt_sections([], phone=phone)


@pytest.mark.smoke
def test_entry_exempt_sections_include_ipad_static_device_profile():
    phone = SimpleNamespace(device_geometry=SimpleNamespace(model="ipad_mini_7"))

    exempt = walkthrough._entry_exempt_sections([], phone=phone)

    assert {"蜂窝网络", "操作按钮", "待机显示", "紧急 SOS"} <= exempt


@pytest.mark.smoke
def test_crawl_skips_graph_inert_root_candidate_without_tapping():
    memory = ScreenMemory(UTG(bundle_id="com.apple.Preferences"))
    root = _settings_root_scene()
    memory.observe(root)
    for _ in range(2):
        memory.observe(root, last_action=("tap", {
            "via": "settings.tap_row",
            "target": "蜂窝网络",
            "action_ok": True,
            "action_outcome": "no_progress",
        }))

    class Phone(_Phone):
        def __init__(self):
            super().__init__(memory)
            self.scene = root
            self.taps = 0

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self):
            pass

    def tap_row(phone, _row):
        phone.taps += 1
        raise AssertionError("graph-inert root row should not be tapped")

    phone = Phone()
    rejected: list[settings_reporting.RejectedCandidate] = []
    actions = replace(
        walkthrough._navigation_actions(),
        scene_is_settings_root=lambda _scene: True,
        root_coverage_perceive=lambda phone, _depth: phone.perceive(),
        record_visible_page=lambda **_kwargs: True,
        record_visible_root_row_visits=lambda **_kwargs: None,
        blocked_child_navigation_reason=lambda _scene: None,
        should_audit_candidates=lambda _depth: False,
        record_rejected_candidates=lambda *_args, **_kwargs: None,
        should_traverse_candidates=lambda _depth: True,
        safe_navigation_candidates=lambda _scene, **_kwargs: [
            _el("蜂窝网络", 80, 424, w=72),
        ],
        tap_settings_row=tap_row,
        scroll_budget_for_depth=lambda _depth: 1,
        scroll_down_confirmed=lambda *_args, **_kwargs: ("stuck", root),
        scroll_to_top=None,
        crawl_missing_root_pages_via_search=lambda *_args, **_kwargs: None,
    )

    settings_navigation.crawl_current_page(
        phone,
        path=("Settings",),
        visits=[],
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=rejected,
        navigation_failures=[],
        actions=actions,
    )

    assert phone.taps == 0
    assert [(item.text, item.reason) for item in rejected] == [("蜂窝网络", "inert_self_loop")]
