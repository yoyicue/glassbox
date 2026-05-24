"""skills/smoke/test_heuristic.py

Unit tests for Layer 2 heuristic typing. One test per rule + integration tests.

Synthesize a Scene (pure OCR output, all elements type='text'), run HeuristicTyper,
and assert that type / suggested_actions are upgraded to the expected values.

Fully offline; no OCR / hardware needed.
"""

from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition import (
    Box,
    HeuristicTyper,
    Scene,
    UIElement,
    find_button,
)

# ─── frame size convention for tests ────────────────────────────────
FRAME_W, FRAME_H = 1170, 2532   # iPhone 13 Pro


def _scene(elements: list[UIElement]) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=elements)


def _text_el(x, y, w, h, text, *, eid=0) -> UIElement:
    return UIElement(
        type="text",
        box=Box(x=x, y=y, w=w, h=h),
        text=text,
        confidence=0.95,
        element_id=eid,
    )


# ─── rule_status_bar ─────────────────────────────────────────────────
@pytest.mark.smoke
def test_status_bar_time_top_left():
    """Status bar time 00:15 should be typed as status_bar, not nav_back."""
    el = _text_el(60, 30, 80, 28, "00:15")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "status_bar"
    assert el.suggested_actions == []


@pytest.mark.smoke
def test_status_bar_time_with_trailing_glyph():
    """OCR appends a moon emoji after the time → 23:56C still counts as a time format."""
    el = _text_el(60, 30, 90, 28, "23:56C")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "status_bar"


@pytest.mark.smoke
@pytest.mark.parametrize("clock", ["8:55", "8:55C", "9:30"])
def test_status_bar_single_digit_hour_not_nav_back(clock):
    """A 1-digit-hour clock (e.g. 8:55) must type as status_bar, never nav_back —
    otherwise return-to-root recovery taps the clock instead of the chevron."""
    el = _text_el(60, 30, 80, 28, clock)
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "status_bar"


@pytest.mark.smoke
@pytest.mark.parametrize("glyph", ["<", "‹", "Back", "返回"])
def test_real_back_glyph_still_nav_back(glyph):
    """The time guard must not swallow genuine top-left Back affordances."""
    el = _text_el(20, 70, 40, 30, glyph)
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "nav_back"


@pytest.mark.smoke
def test_status_bar_battery_percent():
    el = _text_el(FRAME_W - 100, 30, 60, 28, "87%")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "status_bar"


@pytest.mark.smoke
def test_status_bar_5g_label():
    el = _text_el(FRAME_W - 200, 30, 40, 28, "5G")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "status_bar"


@pytest.mark.smoke
def test_status_bar_does_not_steal_modal_close_x():
    """The modal's top-right ✕ sits within the status bar strip, but status_bar
    must not steal it — it should stay nav_back."""
    el = _text_el(FRAME_W - 50, 30, 30, 30, "×")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "nav_back"   # keep the original modal_dismiss behavior


@pytest.mark.smoke
def test_status_bar_does_not_match_below_strip():
    """An element in the nav bar region (below the status bar) is not status_bar."""
    # 60 > FRAME_H * 0.06 = 151.92? No: 60 < 151.  Use real "below status" position:
    el = _text_el(60, int(FRAME_H * 0.07), 80, 30, "00:15")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type != "status_bar"


@pytest.mark.smoke
def test_status_bar_does_not_steal_nav_back():
    """A plain back button (text/arrow) should not be intercepted by status_bar — it stays nav_back."""
    el = _text_el(20, 40, 30, 24, "<")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "nav_back"   # unchanged


# ─── rule_nav_back ───────────────────────────────────────────────────
@pytest.mark.smoke
def test_nav_back_chevron_top_left():
    el = _text_el(20, 40, 30, 24, "<")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "nav_back"
    assert el.suggested_actions == ["tap"]


@pytest.mark.smoke
def test_nav_back_chinese_label():
    el = _text_el(20, 40, 50, 30, "返回")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "nav_back"


@pytest.mark.smoke
def test_nav_back_skipped_when_in_middle():
    el = _text_el(FRAME_W // 2, 40, 80, 30, "标题")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    # not in the top-left, so it should not be nav_back
    assert el.type != "nav_back"


# ─── rule_modal_dismiss ─────────────────────────────────────────────
@pytest.mark.smoke
def test_modal_dismiss_top_right_x():
    el = _text_el(FRAME_W - 50, 30, 30, 30, "×")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "nav_back"
    assert el.confidence == 0.95
    assert el.type_confidence == pytest.approx(0.9)
    assert el.type_source == "rule_modal_dismiss"


# ─── rule_tab_bar_item ───────────────────────────────────────────────
@pytest.mark.smoke
def test_tab_bar_three_items_at_bottom():
    """Three short, equal-height labels at the bottom → all typed as tab_bar_item."""
    y = FRAME_H - 40
    els = [
        _text_el(100, y, 60, 18, "首页", eid=0),
        _text_el(500, y, 60, 18, "发现", eid=1),
        _text_el(900, y, 60, 18, "我的", eid=2),
    ]
    scene = _scene(els)
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert [e.type for e in els] == ["tab_bar_item"] * 3


@pytest.mark.smoke
def test_tab_bar_skipped_when_single_text():
    """Only one label at the bottom should not be misjudged as a tab bar (no neighbors)."""
    el = _text_el(100, FRAME_H - 40, 60, 18, "继续")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type != "tab_bar_item"


# ─── rule_list_item ──────────────────────────────────────────────────
@pytest.mark.smoke
def test_list_item_text_plus_chevron():
    """Text on the left with a '>' chevron on the right at the same y range → list_item."""
    label = _text_el(40, 800, 200, 32, "账号设置", eid=0)
    chevron = _text_el(FRAME_W - 60, 800, 20, 30, ">", eid=1)
    scene = _scene([label, chevron])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert label.type == "list_item"
    assert label.suggested_actions == ["tap"]


@pytest.mark.smoke
def test_list_item_no_chevron_stays_text():
    label = _text_el(40, 800, 200, 32, "账号设置")
    scene = _scene([label])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert label.type == "text"


# ─── rule_button_by_colored_fill ────────────────────────────────────
@pytest.mark.smoke
def test_button_detected_when_colored_fill():
    """Blue fill inside the text box, white around it → primary button.

    The OCR box hugs the text, so the button fill area ≈ box, and the surrounding
    pad lands on the white background.
    """
    img = np.full((FRAME_H, FRAME_W, 3), 255, dtype=np.uint8)   # white background
    # the button's blue fill exactly equals the text box (180..400, 230..260)
    img[230:260, 180:400] = (50, 100, 220)
    el = _text_el(180, 230, 220, 30, "登录")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene, frame_img=img)
    assert el.type == "button"
    assert el.suggested_actions == ["tap"]


@pytest.mark.smoke
def test_button_skipped_when_uniform_background():
    """Pure white background + black text, inner / outer color diff < threshold → not a button."""
    img = np.full((FRAME_H, FRAME_W, 3), 255, dtype=np.uint8)
    el = _text_el(180, 230, 220, 30, "Hello")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene, frame_img=img)
    # no color contrast, so it should not be upgraded to button (no other rule hits either)
    assert el.type == "text"


@pytest.mark.smoke
def test_button_skipped_when_no_image_no_position():
    """Without img, plain mid-screen text → stays text + a default action is added."""
    el = _text_el(400, 1000, 200, 30, "普通文字")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)   # no frame_img passed
    assert el.type == "text"
    assert el.suggested_actions == ["tap"]   # default tap added


# ─── rule_text_input_placeholder ────────────────────────────────────
@pytest.mark.smoke
def test_text_input_zh_placeholder():
    el = _text_el(40, 500, 800, 44, "请输入手机号")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "input"
    assert "type" in el.suggested_actions
    assert "tap" in el.suggested_actions


@pytest.mark.smoke
def test_text_input_en_placeholder():
    el = _text_el(40, 500, 800, 44, "Enter password")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type == "input"


@pytest.mark.smoke
def test_text_input_skipped_when_narrow():
    """Box too narrow (<40% of screen width) → not an input."""
    el = _text_el(40, 500, 200, 24, "请输入")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    assert el.type != "input"


# ─── integration ─────────────────────────────────────────────────────
@pytest.mark.smoke
def test_full_scene_settings_page():
    """Simulate a settings page: nav_back + 3 list_items + chevrons."""
    els = [
        _text_el(30, 40, 20, 24, "<", eid=0),                  # back
        _text_el(40, 200, 120, 30, "账号", eid=1),
        _text_el(FRAME_W - 50, 200, 20, 30, ">", eid=2),
        _text_el(40, 280, 120, 30, "订阅", eid=3),
        _text_el(FRAME_W - 50, 280, 20, 30, ">", eid=4),
        _text_el(40, 360, 120, 30, "关于", eid=5),
        _text_el(FRAME_W - 50, 360, 20, 30, ">", eid=6),
    ]
    scene = _scene(els)
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)

    assert els[0].type == "nav_back"
    # all 3 labels are list_item
    assert els[1].type == "list_item"
    assert els[3].type == "list_item"
    assert els[5].type == "list_item"
    # the chevron itself is type='text' (it should not be upgraded: length 1 + not at left/bottom)
    assert els[2].type == "text"


@pytest.mark.smoke
def test_find_button_after_upgrade():
    """After the typer upgrades, find_button('登录') should return that button."""
    img = np.full((FRAME_H, FRAME_W, 3), 255, dtype=np.uint8)
    img[430:460, 280:520] = (60, 120, 230)   # blue fill area = box
    el = _text_el(280, 430, 240, 30, "登录")
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene, frame_img=img)
    found = find_button(scene.elements, "登录")
    assert found is not None
    assert found.text == "登录"


@pytest.mark.smoke
def test_already_typed_elements_untouched():
    """The typer should not touch an element whose type is not text."""
    el = UIElement(
        type="button",
        box=Box(x=100, y=100, w=200, h=44),
        text="登录",
        confidence=0.9,
        suggested_actions=["tap"],
    )
    scene = _scene([el])
    HeuristicTyper(frame_size=(FRAME_W, FRAME_H)).upgrade(scene)
    # type was not overwritten
    assert el.type == "button"
    assert el.suggested_actions == ["tap"]
