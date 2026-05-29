"""Smoke tests for the cold-start VLM annotator (glassbox/cognition/coldstart.py)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.coldstart import (
    ColdStartAnnotator,
    ScreenAnnotation,
    apply_annotation_to_scene,
    fuse,
)


# —— lightweight stand-ins (decoupled from glassbox.cognition.base) ——
@dataclass
class _Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass
class _El:
    text: str
    box: _Box


@dataclass
class _Node:
    screen_id: str
    visit_count: int


@dataclass
class _Scene:
    elements: list


@dataclass
class _VLMResp:
    parsed: dict | None
    model: str = "fake-vlm"
    elapsed_ms: int = 123


class _FakeVLM:
    """Records call count; returns a canned parsed annotation."""

    def __init__(self, parsed: dict | None):
        self._parsed = parsed
        self.calls = 0

    def chat(self, **_kw) -> _VLMResp:
        self.calls += 1
        return _VLMResp(parsed=self._parsed)


def _ann(elements: list[dict], scene: str = "测试界面", scroll: str = "vertical") -> dict:
    return {"scene": scene, "scroll_axis": scroll, "elements": elements}


@pytest.mark.smoke
def test_fuse_anchors_navigable_element_to_ocr_box():
    """VLM 给语义 + 粗位置,label 命中 OCR 行 → 锚定到精确 OCR 框。"""
    ocr = [_El("无线局域网", _Box(20, 200, 400, 44))]
    parsed = _ann([
        {"label": "无线局域网", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.18},
    ])
    result = fuse("scr_1", parsed, ocr, frame_size=(440, 956))
    el = result.elements[0]
    assert el.anchored is True
    assert el.box == (20, 200, 400, 44)
    assert el.center == (220, 222)   # OCR box center, not the VLM frac
    assert el.role == "cell" and el.navigable is True


@pytest.mark.smoke
def test_fuse_keeps_vlm_only_when_no_ocr_match():
    """无文字图标(OCR 认不出)→ 无可锚行 → 保留 VLM 粗坐标。"""
    parsed = _ann([
        {"label": "加号按钮", "role": "icon", "navigable": True, "x_frac": 0.92, "y_frac": 0.07},
    ])
    result = fuse("scr_1", parsed, [], frame_size=(440, 956))
    el = result.elements[0]
    assert el.anchored is False
    assert el.box is None
    assert el.center == (404, 66)    # 0.92*440, 0.07*956


@pytest.mark.smoke
def test_fuse_disambiguates_duplicate_label_by_predicted_center():
    """同名行出现两次 → 用 VLM 粗位置挑最近的那个 OCR 框。"""
    ocr = [
        _El("打开", _Box(300, 100, 80, 40)),
        _El("打开", _Box(300, 700, 80, 40)),
    ]
    parsed = _ann([
        {"label": "打开", "role": "button", "navigable": True, "x_frac": 0.77, "y_frac": 0.75},
    ])
    result = fuse("scr_1", parsed, ocr, frame_size=(440, 956))
    el = result.elements[0]
    assert el.anchored is True
    assert el.box == (300, 700, 80, 40)   # the lower one — nearest predicted y


@pytest.mark.smoke
def test_fuse_matches_across_whitespace_and_case():
    """VLM 'Game Center' 与 OCR 'GameCenter' 是同一行 —— 空白/大小写不敏感。"""
    ocr = [_El("GameCenter", _Box(20, 300, 400, 44))]
    parsed = _ann([
        {"label": "Game Center", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.32},
    ])
    result = fuse("scr_1", parsed, ocr, frame_size=(440, 956))
    assert result.elements[0].anchored is True


@pytest.mark.smoke
def test_fuse_rejects_weak_containment_match():
    """无文字图标的描述性 label('新建信息按钮')不能因共享片段('信息')错锚到标题框。"""
    ocr = [_El("信息", _Box(20, 126, 66, 36))]
    parsed = _ann([
        {"label": "新建信息按钮", "role": "button", "navigable": True, "x_frac": 0.9, "y_frac": 0.93},
    ])
    result = fuse("scr_1", parsed, ocr, frame_size=(440, 956))
    el = result.elements[0]
    assert el.anchored is False        # 子串重叠不足 → 不锚定
    assert el.box is None


@pytest.mark.smoke
def test_fuse_handles_missing_parsed():
    """VLM 没回出 JSON → 空标注,不炸。"""
    result = fuse("scr_1", None, [], frame_size=(440, 956))
    assert isinstance(result, ScreenAnnotation)
    assert result.elements == []
    assert result.scroll_axis == "none"


@pytest.mark.smoke
def test_annotator_fires_once_per_new_node_then_serves_cache():
    """新 UTG 节点(visit_count==1)触发一次 VLM;重访同节点走缓存,不再调用。"""
    vlm = _FakeVLM(_ann([
        {"label": "通知", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.2},
    ]))
    annotator = ColdStartAnnotator(vlm)
    frame = np.zeros((956, 440, 3), dtype=np.uint8)
    scene = _Scene([_El("通知", _Box(20, 180, 400, 44))])

    fresh = annotator.observe(node=_Node("scr_7", visit_count=1), scene=scene, frame_img=frame)
    assert fresh is not None and fresh.anchored_count == 1
    assert vlm.calls == 1

    revisit = annotator.observe(node=_Node("scr_7", visit_count=2), scene=scene, frame_img=frame)
    assert revisit is fresh        # served from cache
    assert vlm.calls == 1          # no second VLM call


@pytest.mark.smoke
def test_annotator_skips_known_unannotated_node():
    """已知节点但从没标注过(visit_count>1,缓存里没有)→ 不调用 VLM。"""
    vlm = _FakeVLM(_ann([]))
    annotator = ColdStartAnnotator(vlm)
    frame = np.zeros((956, 440, 3), dtype=np.uint8)
    out = annotator.observe(node=_Node("scr_9", visit_count=3), scene=_Scene([]), frame_img=frame)
    assert out is None
    assert vlm.calls == 0


@pytest.mark.smoke
def test_apply_annotation_to_scene_writes_live_only_type_evidence():
    """锚定元素的冷启动语义是 live-only hint,不占用 intent_label。"""
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="text", box=Box(x=20, y=200, w=400, h=44), text="无线局域网", confidence=1.0),
            UIElement(type="text", box=Box(x=20, y=300, w=400, h=44), text="蓝牙", confidence=1.0),
        ],
    )
    annotation = fuse(
        "scr_1",
        _ann([
            {"label": "无线局域网", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.2},
        ]),
        scene.elements,
        frame_size=(440, 956),
    )
    updated = apply_annotation_to_scene(scene, annotation)
    assert updated == 1
    assert scene.elements[0].intent_label is None
    assert scene.elements[0].intent_source is None
    assert "coldstart_role:cell" in scene.elements[0].type_evidence
    assert "coldstart_navigable:true" in scene.elements[0].type_evidence
    assert "tap" in scene.elements[0].suggested_actions
    assert scene.elements[1].intent_label is None   # 未被标注的元素不动


def _toggle_scene_and_annotation():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(440, 956),
        elements=[
            UIElement(type="text", box=Box(x=20, y=200, w=200, h=44), text="蓝牙", confidence=1.0),
        ],
    )
    annotation = fuse(
        "scr_t",
        _ann([
            {"label": "蓝牙", "role": "toggle", "navigable": True, "x_frac": 0.3, "y_frac": 0.2},
        ]),
        scene.elements,
        frame_size=(440, 956),
    )
    return scene, annotation


@pytest.mark.smoke
def test_promote_controls_types_toggle_as_switch_and_aims_tap_right():
    """CUQ-2.3: with promote_controls on, a VLM `toggle` role becomes a `switch`
    element whose tap point is the row's right-margin control (not the label box,
    where a tap only highlights the row)."""
    scene, annotation = _toggle_scene_and_annotation()
    apply_annotation_to_scene(scene, annotation, promote_controls=True)
    el = scene.elements[0]
    assert el.type == "switch"
    assert el.preferred_tap_point is not None
    tap_x, tap_y = el.preferred_tap_point
    assert tap_x > el.box.x + el.box.w   # to the RIGHT of the label box
    assert tap_x == int(440 * 0.92)
    assert tap_y == el.box.center[1]
    assert "tap" in el.suggested_actions


@pytest.mark.smoke
def test_promote_controls_off_keeps_toggle_as_text():
    """CUQ-2.3 (default): without the flag the toggle stays `text` (only the
    evidence tag is written), so the default cold-start path is unchanged."""
    scene, annotation = _toggle_scene_and_annotation()
    apply_annotation_to_scene(scene, annotation)
    el = scene.elements[0]
    assert el.type == "text"
    assert el.preferred_tap_point is None
    assert "coldstart_role:toggle" in el.type_evidence


@pytest.mark.smoke
def test_phone_observe_memory_runs_coldstart_on_new_node():
    """Phone._observe_memory 接住 memory.observe 的节点 → 新节点驱动冷启动标注 → 写回 Scene。"""
    from glassbox.phone import Phone

    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[UIElement(type="text", box=Box(x=20, y=200, w=400, h=44),
                            text="无线局域网", confidence=1.0)],
    )
    node = _Node("scr_1", visit_count=1)

    class _Mem:
        def observe(self, _scene, _action, frame_img=None):
            return node

    vlm = _FakeVLM(_ann([
        {"label": "无线局域网", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.2},
    ]))
    phone = Phone(source=None, ocr=None, effector=None,
                  memory=_Mem(), coldstart=ColdStartAnnotator(vlm))
    phone._observe_memory(scene, np.zeros((956, 440, 3), dtype=np.uint8))

    assert vlm.calls == 1
    assert scene.elements[0].intent_label is None
    assert "coldstart_role:cell" in scene.elements[0].type_evidence


@pytest.mark.smoke
def test_phone_perceive_records_and_caches_coldstart_annotation(tmp_path):
    from glassbox.effector import MockEffector
    from glassbox.memory import UTG, ScreenMemory
    from glassbox.obs import Recorder
    from glassbox.obs.recorder import iter_events
    from glassbox.perception.source import Frame
    from glassbox.phone import Phone

    class FakeSource:
        resolution = (440, 956)

        def snapshot(self):
            return Frame(img=np.zeros((956, 440, 3), dtype=np.uint8), ts=1.0)

    class FakeOCR:
        def recognize(self, _image):
            return [
                UIElement(
                    type="text",
                    box=Box(x=20, y=200, w=400, h=44),
                    text="无线局域网",
                    confidence=1.0,
                )
            ]

    vlm = _FakeVLM(_ann([
        {"label": "无线局域网", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.2},
    ]))
    recorder = Recorder(tmp_path, save_frames=False)
    phone = Phone(
        source=FakeSource(),
        ocr=FakeOCR(),
        effector=MockEffector(),
        memory=ScreenMemory(UTG(bundle_id="com.apple.Preferences")),
        coldstart=ColdStartAnnotator(vlm),
        recorder=recorder,
    )

    first = phone.perceive()
    second = phone.perceive()
    recorder.close()

    assert "coldstart_role:cell" in first.elements[0].type_evidence
    assert "coldstart_role:cell" in second.elements[0].type_evidence
    assert phone.perceive_cache_stats == {"hits": 1, "misses": 1}
    scene_events = [e for e in iter_events(tmp_path) if e["type"] == "scene"]
    assert len(scene_events) == 2
    assert "coldstart_role:cell" in scene_events[0]["elements"][0]["type_evidence"]
    assert "coldstart_role:cell" in scene_events[1]["elements"][0]["type_evidence"]


@pytest.mark.smoke
def test_annotator_respects_call_budget():
    """超出 per-run VLM 预算 → 新节点也不再调用。"""
    vlm = _FakeVLM(_ann([]))
    annotator = ColdStartAnnotator(vlm, max_calls=1)
    frame = np.zeros((956, 440, 3), dtype=np.uint8)
    scene = _Scene([])
    annotator.observe(node=_Node("scr_1", visit_count=1), scene=scene, frame_img=frame)
    out = annotator.observe(node=_Node("scr_2", visit_count=1), scene=scene, frame_img=frame)
    assert out is None
    assert vlm.calls == 1


@pytest.mark.smoke
def test_fuse_anchors_no_text_icon_to_detected_region():
    """无 OCR 行可锚的图标 → 锚到附近 CV 检测到的图标区域(精确框)。"""
    from glassbox.cognition.icon_detect import IconRegion

    parsed = _ann([
        {"label": "加号按钮", "role": "icon", "navigable": True, "x_frac": 0.9, "y_frac": 0.1},
    ])
    icons = [IconRegion(box=(380, 80, 40, 40))]   # 中心 (400,100),离预测 (396,95) 很近
    result = fuse("scr_1", parsed, [], frame_size=(440, 956), icon_regions=icons)
    el = result.elements[0]
    assert el.anchored is True
    assert el.box == (380, 80, 40, 40)
    assert el.center == (400, 100)


@pytest.mark.smoke
def test_fuse_keeps_vlm_only_when_icon_region_too_far():
    """检测到的图标区域离 VLM 预测中心太远 → 不锚,保留 VLM 粗坐标。"""
    from glassbox.cognition.icon_detect import IconRegion

    parsed = _ann([
        {"label": "加号按钮", "role": "icon", "navigable": True, "x_frac": 0.9, "y_frac": 0.1},
    ])
    icons = [IconRegion(box=(0, 0, 40, 40))]      # 中心 (20,20),远离预测 (396,95)
    result = fuse("scr_1", parsed, [], frame_size=(440, 956), icon_regions=icons)
    assert result.elements[0].anchored is False
