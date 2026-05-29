"""skills/smoke/test_tap_intent.py

Unit tests for Phone.tap_intent + find_by_intent. Fully offline, FakeKimi injected.

Coverage:
  - find_by_intent exact / substring / fuzzy / empty
  - tap_intent does not call Kimi when intent_label already exists
  - tap_intent with no intent_label + no Kimi → falls back to tap_button
  - tap_intent with no intent_label + Kimi present → runs describe then taps
  - tap_intent with no match → AssertionError
"""

from __future__ import annotations

import pytest

from glassbox.cognition import (
    Box,
    KimiResponse,
    UIElement,
    find_by_intent,
)


def _el(eid: int, *, text=None, intent_label=None, type_="text",
        box=(100, 200, 80, 40)) -> UIElement:
    x, y, w, h = box
    return UIElement(
        type=type_, box=Box(x=x, y=y, w=w, h=h),
        text=text, confidence=0.9, element_id=eid,
        intent_label=intent_label,
    )


# ─── find_by_intent ─────────────────────────────────────────────────
@pytest.mark.smoke
def test_find_by_intent_exact():
    els = [_el(0, intent_label="确认登录"), _el(1, intent_label="找回密码")]
    assert find_by_intent(els, "确认登录") is els[0]


@pytest.mark.smoke
def test_find_by_intent_substring_either_way():
    """intent="登录" hits intent_label="确认登录", and the reverse works too."""
    els = [_el(0, intent_label="确认登录")]
    assert find_by_intent(els, "登录") is els[0]

    els2 = [_el(0, intent_label="登录")]
    assert find_by_intent(els2, "确认登录") is els2[0]


@pytest.mark.smoke
def test_find_by_intent_fuzzy():
    """intent_label "前往注册" should be fuzzy-matched by "去注册"."""
    els = [_el(0, intent_label="前往注册")]
    assert find_by_intent(els, "去注册", fuzzy_ratio=0.4) is els[0]


@pytest.mark.smoke
def test_find_by_intent_no_match():
    els = [_el(0, intent_label="找回密码")]
    assert find_by_intent(els, "购买套餐") is None


@pytest.mark.smoke
def test_find_by_intent_skips_unlabeled():
    """Elements without an intent_label do not participate in matching."""
    els = [
        _el(0, text="登录", intent_label=None),
        _el(1, text="X", intent_label="确认登录"),
    ]
    found = find_by_intent(els, "确认登录")
    assert found is els[1]


# ─── Phone.tap_intent ───────────────────────────────────────────────
@pytest.mark.smoke
def test_tap_intent_uses_existing_label_no_kimi_call(mock_phone):
    """The scene already has an intent_label, so tap_intent should not trigger describe."""
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=100, y=200, w=200, h=44),
                  text="登录", confidence=0.9, element_id=0,
                  intent_label="确认登录"),
    ]
    # deliberately give mock_phone a kimi that blows up, to verify it is never called
    class BoomKimi:
        def describe_scene(self, **kw):
            raise RuntimeError("should not be called")
    mock_phone.kimi = BoomKimi()

    mock_phone.tap_intent("确认登录")
    last = mock_phone.effector.last()
    assert last.op == "tap"
    # box.center = (100 + 100, 200 + 22) = (200, 222)
    assert last.kwargs == {"x": 200, "y": 222}


@pytest.mark.smoke
def test_tap_intent_falls_back_to_tap_button_when_no_kimi(mock_phone):
    """With no kimi and the scene also lacking an intent_label → take the tap_button path.

    The mock OCR provides a type='text' "登录", and we run tap_intent("确认登录").
    Layer 2 + a simple synthetic setup: here we directly give type='button' +
    text="确认登录" so tap_button can hit it.
    """
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=100, y=200, w=200, h=44),
                  text="确认登录", confidence=0.9, element_id=0),
    ]
    mock_phone.kimi = None

    mock_phone.tap_intent("确认登录")
    last = mock_phone.effector.last()
    assert last.op == "tap"
    assert last.kwargs == {"x": 200, "y": 222}


@pytest.mark.smoke
def test_tap_intent_runs_describe_when_kimi_present(mock_phone):
    """Scene has no intent_label + kimi is wired in → tap_intent runs describe first, then taps."""
    # OCR provides a "登录" not upgraded by Layer 2
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=100, y=200, w=200, h=44),
                  text="登录", confidence=0.9, element_id=0),
    ]

    captured: dict = {}

    class FakeKimi:
        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            captured["called"] = True
            captured["hint"] = scene_hint
            captured["element_ids"] = [e["id"] for e in elements]
            return KimiResponse(
                raw_content="(fake)",
                parsed={
                    "scene_type": "login_form",
                    "elements": [
                        {"id": 0, "intent_label": "确认登录", "confidence": 0.95},
                    ],
                },
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="fake",
                elapsed_ms=1,
            )

    mock_phone.kimi = FakeKimi()
    mock_phone.tap_intent("确认登录", scene_hint="登录走查")

    assert captured.get("called") is True
    assert captured["hint"] == "登录走查"
    assert captured["element_ids"] == [0]
    last = mock_phone.effector.last()
    assert last.op == "tap"
    assert last.kwargs == {"x": 200, "y": 222}


@pytest.mark.smoke
def test_tap_intent_refreshes_when_existing_labels_do_not_cover_request(mock_phone):
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=100, y=200, w=200, h=44),
                  text="登录", confidence=0.9, element_id=0,
                  intent_label="确认登录"),
    ]
    captured: dict = {}

    class FakeKimi:
        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            captured["called"] = True
            return KimiResponse(
                raw_content="(fake)",
                parsed={
                    "scene_type": "paywall",
                    "elements": [{"id": 0, "intent_label": "购买年度套餐"}],
                },
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    mock_phone.kimi = FakeKimi()
    mock_phone.tap_intent("购买年度套餐")

    assert captured["called"] is True
    last = mock_phone.effector.last()
    assert last.op == "tap"
    assert last.kwargs == {"x": 200, "y": 222}


@pytest.mark.smoke
def test_tap_intent_retries_even_after_prior_vlm_ok_without_target(mock_phone):
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=100, y=200, w=200, h=44),
                  text="购买", confidence=0.9, element_id=0,
                  intent_label="查看详情"),
    ]
    scene = mock_phone.perceive()
    scene.vlm_status = "ok"
    scene.vlm_requested_element_ids = [0]
    scene.vlm_returned_element_ids = [0]
    scene.vlm_missing_element_ids = []
    scene.vlm_intent_coverage = 1.0
    calls = {"n": 0}

    class FakeKimi:
        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            calls["n"] += 1
            return KimiResponse(
                raw_content="(fake)",
                parsed={
                    "scene_type": "paywall",
                    "elements": [{"id": 0, "intent_label": "购买年度套餐"}],
                },
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    mock_phone.kimi = FakeKimi()

    mock_phone.tap_intent("购买年度套餐")

    assert calls["n"] == 1
    assert mock_phone.effector.last().op == "tap"


@pytest.mark.smoke
def test_tap_intent_reperceives_after_prior_action(mock_phone):
    """After an action, tap_intent must not reuse the pre-action semantic scene."""
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=10, y=20, w=100, h=40),
                  text="旧页面", confidence=0.9, element_id=0,
                  intent_label="旧动作"),
    ]
    mock_phone.perceive()
    mock_phone.tap_xy(1, 1)

    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=120, y=220, w=160, h=44),
                  text="继续", confidence=0.9, element_id=0),
    ]
    captured: dict = {}

    class FakeKimi:
        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            captured["texts"] = [e["text"] for e in elements]
            return KimiResponse(
                raw_content="(fake)",
                parsed={
                    "scene_type": "next_screen",
                    "elements": [{"id": 0, "intent_label": "继续操作"}],
                },
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    mock_phone.kimi = FakeKimi()
    mock_phone.tap_intent("继续操作")

    assert captured["texts"] == ["继续"]
    last = mock_phone.effector.last()
    assert last.op == "tap"
    assert last.kwargs == {"x": 200, "y": 242}


@pytest.mark.smoke
def test_tap_intent_raises_when_no_match(mock_phone):
    """Neither an intent_label hit nor a fallback match → AssertionError."""
    mock_phone.ocr.elements = [
        UIElement(type="button", box=Box(x=100, y=200, w=200, h=44),
                  text="登录", confidence=0.9, element_id=0,
                  intent_label="确认登录"),
    ]
    mock_phone.kimi = None

    with pytest.raises(AssertionError, match="tap_intent"):
        mock_phone.tap_intent("购买年度套餐")


@pytest.mark.smoke
def test_reground_tap_point_relocates_target_via_fresh_ocr(mock_phone):
    mock_phone.ocr.elements = [
        UIElement(type="list_item", box=Box(x=100, y=400, w=240, h=44), text="无线局域网", confidence=0.9),
    ]
    mock_phone.perceive()  # populate _last_scene the re-ground reads from
    point = mock_phone._reground_tap_point(target="无线局域网")
    assert point is not None
    # the re-located point lands inside the element's box
    assert 100 <= point.x <= 340
    assert 400 <= point.y <= 444


@pytest.mark.smoke
def test_reground_tap_point_returns_none_when_target_missing(mock_phone):
    mock_phone.ocr.elements = []
    mock_phone.perceive()
    assert mock_phone._reground_tap_point(target="不存在") is None


@pytest.mark.smoke
def test_expect_text_escalates_to_vlm_when_ocr_misses(mock_phone):
    """CUQ-0.4: when OCR cannot locate the target, expect_text escalates to the
    VLM (find-by-description) and resolves via the enriched intent label instead
    of hard-failing. A VLM-disabled run keeps the hard-fail behavior."""
    # OCR reads a garbled label that matches the target by neither text nor fuzzy.
    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=80, y=300, w=120, h=30),
                  text="xQz9", confidence=0.4, element_id=0),
    ]

    # VLM disabled -> hard fail (default behavior preserved).
    mock_phone.kimi = None
    with pytest.raises(AssertionError):
        mock_phone.expect_text("通用", timeout=0.2, poll_interval=0.1)

    class FakeKimi:
        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            return KimiResponse(
                raw_content="(fake)",
                parsed={
                    "scene_type": "settings_detail",
                    "elements": [{"id": 0, "intent_label": "通用", "confidence": 0.95}],
                },
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="fake",
                elapsed_ms=1,
            )

    # VLM enabled -> the gated grounding pass resolves the target by intent.
    mock_phone.kimi = FakeKimi()
    el = mock_phone.expect_text("通用", timeout=0.2, poll_interval=0.1)
    assert el.element_id == 0
