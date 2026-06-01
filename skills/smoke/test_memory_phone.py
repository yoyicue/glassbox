"""skills/smoke/test_memory_phone.py

Phase c — ScreenMemory wired into Phone.perceive(). Offline (mock_phone).

Coverage:
  - perceive → tap → perceive grows the UTG by 2 nodes + 1 transition edge
  - the cache-hit branch of perceive() also folds into memory (visit_count++)
"""

from __future__ import annotations

import pytest

from glassbox.cognition import VLMResponse
from glassbox.cognition.base import Box, UIElement
from glassbox.effector import ActionResult
from glassbox.memory import UTG, ActionRecord, ScreenMemory
from glassbox.obs import Recorder
from glassbox.obs.recorder import iter_events


def _el(eid, text):
    return UIElement(type="button", box=Box(x=eid * 40 + 20, y=eid * 60 + 100, w=120, h=44),
                     text=text, confidence=0.9, element_id=eid)


@pytest.mark.smoke
def test_perceive_tap_perceive_grows_utg(mock_phone):
    """perceive (login) → tap → perceive (settings) → 2 nodes, 1 edge."""
    mock_phone.perceive_cache_diff = 0          # force the OCR (cache-miss) path
    mock_phone.memory = ScreenMemory(UTG(bundle_id="com.test"))

    mock_phone.ocr.elements = [_el(0, "登录"), _el(1, "密码"), _el(2, "忘记密码")]
    mock_phone.perceive()
    mock_phone.tap_xy(50, 120)
    mock_phone.ocr.elements = [_el(0, "设置"), _el(1, "隐私"), _el(2, "关于"), _el(3, "帮助")]
    mock_phone.perceive()

    utg = mock_phone.memory.utg
    assert len(utg.nodes) == 2
    assert len(utg.edges) == 1
    assert utg.edges[0].action_op == "tap"
    assert isinstance(utg.edges[0].action, ActionRecord)
    assert utg.edges[0].action_identity == "coord:frame_px:0:1"
    assert utg.edges[0].action.coordinate_space == "frame_px"
    assert utg.edges[0].action.params["action_backend"] == "mock"
    assert utg.edges[0].action.params["action_synthetic"] is False


@pytest.mark.smoke
def test_multiple_actions_before_perceive_do_not_learn_single_edge(mock_phone):
    mock_phone.perceive_cache_diff = 0
    mock_phone.memory = ScreenMemory(UTG(bundle_id="com.test"))

    mock_phone.ocr.elements = [_el(0, "登录"), _el(1, "密码")]
    mock_phone.perceive()
    mock_phone.tap_xy(50, 120)
    mock_phone.tap_xy(80, 180)
    mock_phone.ocr.elements = [_el(0, "设置"), _el(1, "隐私"), _el(2, "关于")]
    mock_phone.perceive()

    utg = mock_phone.memory.utg
    assert len(utg.nodes) == 2
    assert utg.edges == []


@pytest.mark.smoke
def test_failed_diagnostic_action_does_not_block_successful_memory_action(mock_phone):
    mock_phone.perceive_cache_diff = 0
    mock_phone.memory = ScreenMemory(UTG(bundle_id="com.test"))

    mock_phone.ocr.elements = [_el(0, "A")]
    mock_phone.perceive()
    mock_phone._record_action(
        "scroll_wheel",
        result=ActionResult.failed(
            backend="noop",
            connected=False,
            error="diagnostic unsupported",
            synthetic=True,
            unsupported=True,
        ),
        via="diagnose",
    )
    mock_phone.tap_xy(50, 120)
    mock_phone.ocr.elements = [_el(0, "B")]
    mock_phone.perceive()

    assert len(mock_phone.memory.utg.edges) == 1
    edge = mock_phone.memory.utg.edges[0]
    assert edge.action_op == "tap"
    assert edge.action is not None
    assert edge.action.via == "tap_xy"


@pytest.mark.smoke
def test_cache_hit_branch_folds_into_memory(mock_phone):
    """Two perceives of an unchanged screen (cache hit) → one node, visit_count 2."""
    mock_phone.memory = ScreenMemory(UTG(bundle_id="com.test"))
    mock_phone.ocr.elements = [_el(0, "登录"), _el(1, "密码")]
    mock_phone.perceive()
    mock_phone.perceive()                       # identical 1px frame → cache hit
    assert mock_phone.perceive_cache_stats["hits"] >= 1
    utg = mock_phone.memory.utg
    assert len(utg.nodes) == 1
    assert next(iter(utg.nodes.values())).visit_count == 2


@pytest.mark.smoke
def test_memory_none_is_noop(mock_phone):
    """Default mock_phone has no memory — perceive must not crash."""
    assert mock_phone.memory is None
    mock_phone.ocr.elements = [_el(0, "登录")]
    mock_phone.perceive()                       # no error


@pytest.mark.smoke
def test_describe_merges_layer3_fields_into_live_memory(mock_phone):
    class FakeKimi:
        model = "fake"

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            return VLMResponse(
                raw_content="{}",
                parsed={
                    "scene_type": "login_form",
                    "context": "等待用户登录",
                    "available_intents": ["确认登录", "找回密码"],
                    "app_state": {"auth": "logged_out"},
                    "elements": [{"id": 0, "intent_label": "确认登录"}],
                },
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    mock_phone.perceive_cache_diff = 0
    mock_phone.memory = ScreenMemory(UTG(bundle_id="com.test"))
    mock_phone.kimi = FakeKimi()
    mock_phone.ocr.elements = [_el(0, "登录"), _el(1, "忘记密码")]

    mock_phone.perceive()
    mock_phone.describe()

    utg = mock_phone.memory.utg
    assert len(utg.nodes) == 1
    assert utg.edges == []
    node = next(iter(utg.nodes.values()))
    assert node.visit_count == 1
    assert node.scene_type == "login_form"
    assert node.context == "等待用户登录"
    assert node.available_intents == ["确认登录", "找回密码"]
    assert node.app_state == {"auth": "logged_out"}
    login = node.element("text:登录")
    assert login is not None
    assert login.intent_label == "确认登录"


@pytest.mark.smoke
def test_describe_reruns_scene_classifiers_before_memory_and_recorder(tmp_path, mock_phone):
    class FakeKimi:
        model = "fake"

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            return VLMResponse(
                raw_content="{}",
                parsed={"scene_type": "vlm_login", "elements": []},
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    def classify_after_vlm(scene, viewport_size):
        if scene.scene_type != "vlm_login":
            return
        scene.page_id = "login/vlm"
        scene.safe_actions = ["tap_login"]
        scene.classification_source = "test"
        scene.classification_confidence = 0.9
        scene.classification_evidence = ["scene_type"]

    mock_phone.perceive_cache_diff = 0
    mock_phone.memory = ScreenMemory(UTG(bundle_id="com.test"))
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.kimi = FakeKimi()
    mock_phone.scene_classifiers = [classify_after_vlm]
    mock_phone.ocr.elements = [_el(0, "登录")]

    mock_phone.perceive()
    mock_phone.describe()
    mock_phone.recorder.close()

    node = next(iter(mock_phone.memory.utg.nodes.values()))
    assert node.scene_type == "vlm_login"
    assert node.page_id == "login/vlm"
    assert node.safe_actions == ["tap_login"]
    assert node.classification_source == "test"
    assert node.classification_confidence == 0.9
    assert node.classification_evidence == ["scene_type"]

    scene_events = [e for e in iter_events(tmp_path) if e["type"] == "scene"]
    assert len(scene_events) == 2
    assert scene_events[0]["page_id"] is None
    assert scene_events[-1]["page_id"] == "login/vlm"
    assert scene_events[-1]["safe_actions"] == ["tap_login"]
    assert scene_events[-1]["classification_source"] == "test"
    events = list(iter_events(tmp_path))
    event_timestamps = [e["ts"] for e in events]
    assert event_timestamps == sorted(event_timestamps)
    assert scene_events[-1]["scene_timestamp"] == 0.0
