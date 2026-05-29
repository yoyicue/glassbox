"""Smoke tests for tap-candidate strategies (glassbox/cognition/candidates.py)."""
from __future__ import annotations

import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.candidates import (
    TapCandidate,
    annotation_tap_candidates,
    ocr_tap_candidates,
)
from glassbox.cognition.coldstart import fuse


def _el(kind: str, text: str, y: int) -> UIElement:
    return UIElement(type=kind, box=Box(x=20, y=y, w=400, h=44), text=text, confidence=1.0)


@pytest.mark.smoke
def test_ocr_tap_candidates_keeps_actionable_and_text_rows():
    scene = Scene(frame_id=1, timestamp=0.0, elements=[
        _el("button", "登录", 100),
        _el("list_item", "无线局域网", 200),
        _el("text", "蓝牙", 300),
        _el("status_bar", "14:28", 10),     # 系统状态栏 — 不是候选
        _el("image", "", 400),              # 无文字 — 不是候选
    ])
    cands = ocr_tap_candidates(scene)
    labels = {c.label for c in cands}
    assert labels == {"登录", "无线局域网", "蓝牙"}
    assert all(c.source == "ocr" for c in cands)


@pytest.mark.smoke
def test_ocr_tap_candidates_skips_status_bar_clock_typed_as_text():
    """CUQ-2.7: a status-bar clock OCR'd as plain 'text' (not status_bar) must
    not be picked as a tap candidate."""
    scene = Scene(frame_id=1, timestamp=0.0, elements=[
        _el("text", "9:41", 10),        # clock mis-typed as text
        _el("text", "2:03 C", 12),      # clock + OCR noise
        _el("list_item", "无线局域网", 200),
    ])
    labels = {c.label for c in ocr_tap_candidates(scene)}
    assert labels == {"无线局域网"}


@pytest.mark.smoke
def test_annotation_tap_candidates_keeps_only_navigable():
    parsed = {
        "scene": "x", "scroll_axis": "vertical",
        "elements": [
            {"label": "无线局域网", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.2},
            {"label": "欢迎使用", "role": "header", "navigable": False, "x_frac": 0.3, "y_frac": 0.1},
            {"label": "加号按钮", "role": "icon", "navigable": True, "x_frac": 0.9, "y_frac": 0.07},
        ],
    }
    ocr = [_el("text", "无线局域网", 200)]
    annotation = fuse("scr_1", parsed, ocr, frame_size=(440, 956))
    cands = annotation_tap_candidates(annotation)
    labels = {c.label for c in cands}
    assert labels == {"无线局域网", "加号按钮"}        # header 不可导航 → 排除


@pytest.mark.smoke
def test_annotation_candidate_source_marks_anchored_vs_vlm_only():
    parsed = {
        "scene": "x", "scroll_axis": "vertical",
        "elements": [
            {"label": "无线局域网", "role": "cell", "navigable": True, "x_frac": 0.5, "y_frac": 0.2},
            {"label": "加号按钮", "role": "icon", "navigable": True, "x_frac": 0.9, "y_frac": 0.07},
        ],
    }
    ocr = [_el("text", "无线局域网", 200)]    # 只有第一个有 OCR 行可锚
    annotation = fuse("scr_1", parsed, ocr, frame_size=(440, 956))
    by_label = {c.label: c for c in annotation_tap_candidates(annotation)}
    assert by_label["无线局域网"].source == "vlm_anchored"
    assert by_label["加号按钮"].source == "vlm_only"


@pytest.mark.smoke
def test_tap_candidate_is_uniform_across_strategies():
    """两条策略产出同一种 TapCandidate 类型 —— explorer 才能直接换策略。"""
    scene = Scene(frame_id=1, timestamp=0.0, elements=[_el("button", "登录", 100)])
    assert isinstance(ocr_tap_candidates(scene)[0], TapCandidate)
