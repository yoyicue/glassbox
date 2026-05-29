"""skills/smoke/test_icon_detect.py — visual detection of the modal close button + synthetic nav_back.

Fully offline (synthetic images) + real images (assets/walkthroughs/demoapp_v1/).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.cognition.heuristic import HeuristicTyper
from glassbox.cognition.icon_detect import find_modal_close

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASSETS = _REPO_ROOT / "assets" / "walkthroughs" / "demoapp_v1"


def _white_canvas(h=900, w=400) -> np.ndarray:
    """A white BGR canvas."""
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _draw_gray_circle(img, cx, cy, r=15, color=(232, 232, 232)):
    """Draw an iOS-style gray-circle close button background."""
    cv2.circle(img, (cx, cy), r, color, -1)
    # × strokes
    cv2.line(img, (cx - 5, cy - 5), (cx + 5, cy + 5), (130, 130, 130), 2)
    cv2.line(img, (cx + 5, cy - 5), (cx - 5, cy + 5), (130, 130, 130), 2)


# ─── detector unit tests ─────────────────────────────────────────────
@pytest.mark.smoke
def test_detect_synthetic_close_top_right():
    img = _white_canvas()
    _draw_gray_circle(img, cx=370, cy=50, r=15)
    bbox = find_modal_close(img)
    assert bbox is not None
    x, y, w, h = bbox
    assert 350 < x + w / 2 < 390
    assert 35 < y + h / 2 < 65
    assert 20 <= w <= 40


@pytest.mark.smoke
def test_no_detection_on_blank_canvas():
    img = _white_canvas()
    assert find_modal_close(img) is None


@pytest.mark.smoke
def test_no_detection_when_outside_top_right():
    img = _white_canvas()
    # top-left — close is not at this position
    _draw_gray_circle(img, cx=50, cy=50)
    # bottom
    _draw_gray_circle(img, cx=370, cy=850)
    assert find_modal_close(img) is None


@pytest.mark.smoke
def test_rejects_colorful_widget_in_top_right():
    """A colorful widget (blue Wi-Fi adapter style) should not be typed as close."""
    img = _white_canvas()
    cv2.rectangle(img, (340, 30), (390, 80), (255, 100, 50), -1)   # bright blue
    assert find_modal_close(img) is None


@pytest.mark.smoke
def test_rejects_too_large_blob():
    img = _white_canvas()
    cv2.circle(img, (370, 50), 40, (232, 232, 232), -1)   # diameter 80, too large
    assert find_modal_close(img) is None


@pytest.mark.smoke
def test_rejects_too_small_blob():
    img = _white_canvas()
    cv2.circle(img, (370, 50), 5, (232, 232, 232), -1)   # diameter 10, too small
    assert find_modal_close(img) is None


# ─── HeuristicTyper integration ──────────────────────────────────────
@pytest.mark.smoke
def test_typer_synthesizes_close_when_detected():
    img = _white_canvas()
    _draw_gray_circle(img, cx=370, cy=50)
    scene = Scene(frame_id=0, timestamp=0.0, elements=[])
    typer = HeuristicTyper(frame_size=(img.shape[1], img.shape[0]))
    typer.upgrade(scene, frame_img=img)
    close = [e for e in scene.elements if e.type == "nav_back"]
    assert len(close) == 1
    assert close[0].text == "×"
    assert close[0].suggested_actions == ["tap"]


@pytest.mark.smoke
def test_typer_does_not_double_synthesize():
    """An element already covers the bbox → do not synthesize a duplicate."""
    img = _white_canvas()
    _draw_gray_circle(img, cx=370, cy=50)
    existing = UIElement(
        type="text", box=Box(x=350, y=30, w=40, h=40),
        text="forbidden", confidence=0.9, element_id=0,
    )
    scene = Scene(frame_id=0, timestamp=0.0, elements=[existing])
    typer = HeuristicTyper(frame_size=(img.shape[1], img.shape[0]))
    typer.upgrade(scene, frame_img=img)
    # there should be only the original element, with no new close added
    assert len(scene.elements) == 1
    assert scene.elements[0].text == "forbidden"


@pytest.mark.smoke
def test_typer_synthesize_off_when_disabled():
    img = _white_canvas()
    _draw_gray_circle(img, cx=370, cy=50)
    scene = Scene(frame_id=0, timestamp=0.0, elements=[])
    typer = HeuristicTyper(frame_size=(img.shape[1], img.shape[0]),
                            synthesize_modal_close=False)
    typer.upgrade(scene, frame_img=img)
    assert scene.elements == []


# ─── real-image regression ──────────────────────────────────────────
@pytest.mark.smoke
@pytest.mark.skipif(not (_ASSETS / "02_control.png").exists(),
                    reason="asset missing")
def test_real_no_false_positive_on_control_page():
    """The control page has a Wi-Fi widget in the top-right; it should not be a false hit."""
    from glassbox.perception.device import IPHONE_17_PRO_MAX
    from glassbox.perception.letterbox import LetterboxCrop

    img = cv2.imread(str(_ASSETS / "02_control.png"))
    lc = LetterboxCrop.auto_detect(img, phone_size=IPHONE_17_PRO_MAX)
    assert find_modal_close(lc.crop(img)) is None


@pytest.mark.smoke
@pytest.mark.skipif(not (_ASSETS / "03_settings.png").exists(),
                    reason="asset missing")
def test_real_no_false_positive_on_settings_page():
    from glassbox.perception.device import IPHONE_17_PRO_MAX
    from glassbox.perception.letterbox import LetterboxCrop

    img = cv2.imread(str(_ASSETS / "03_settings.png"))
    lc = LetterboxCrop.auto_detect(img, phone_size=IPHONE_17_PRO_MAX)
    assert find_modal_close(lc.crop(img)) is None


@pytest.mark.smoke
@pytest.mark.skipif(not (_ASSETS / "01_home.png").exists(),
                    reason="asset missing")
def test_real_no_false_positive_on_home_screen():
    from glassbox.perception.device import IPHONE_17_PRO_MAX
    from glassbox.perception.letterbox import LetterboxCrop

    img = cv2.imread(str(_ASSETS / "01_home.png"))
    lc = LetterboxCrop.auto_detect(img, phone_size=IPHONE_17_PRO_MAX)
    assert find_modal_close(lc.crop(img)) is None


# ─── general detect_icons (no-text icon-region detection) ────────────────
from glassbox.cognition.icon_detect import (  # noqa: E402
    detect_icons,
    detect_icons_voted,
)


def _blank_icon_canvas() -> np.ndarray:
    return np.full((400, 200, 3), 255, np.uint8)   # 200w x 400h white


def _draw_plus(img: np.ndarray) -> np.ndarray:
    """Draw a black '+' icon centred at (100, 100)."""
    cv2.rectangle(img, (95, 85), (105, 115), (0, 0, 0), -1)
    cv2.rectangle(img, (85, 95), (115, 105), (0, 0, 0), -1)
    return img


def _near_icon(regions, x: int, y: int, tol: int = 28) -> bool:
    return any(abs(r.center[0] - x) < tol and abs(r.center[1] - y) < tol for r in regions)


@pytest.mark.smoke
def test_detect_icons_finds_a_drawn_icon():
    regions = detect_icons(_draw_plus(_blank_icon_canvas()))
    assert regions
    assert _near_icon(regions, 100, 100)


@pytest.mark.smoke
def test_detect_icons_masks_text_boxes():
    """图标区域被当作 text_box 扣掉 → 不再作为图标返回。"""
    regions = detect_icons(_draw_plus(_blank_icon_canvas()), text_boxes=((80, 80, 40, 40),))
    assert not _near_icon(regions, 100, 100)


@pytest.mark.smoke
def test_detect_icons_empty_on_blank_frame():
    assert detect_icons(_blank_icon_canvas()) == []


@pytest.mark.smoke
def test_detect_icons_handles_none():
    assert detect_icons(None) == []


@pytest.mark.smoke
def test_detect_icons_voted_keeps_recurring_icon():
    """同一图标出现在多帧 → 投票保留。"""
    frames = [_draw_plus(_blank_icon_canvas()) for _ in range(3)]
    regions = detect_icons_voted(frames, min_frames=2)
    assert _near_icon(regions, 100, 100)


@pytest.mark.smoke
def test_detect_icons_voted_drops_one_frame_noise():
    """只在单帧出现的形状(噪点)→ 投票滤掉;复现的图标留下。"""
    frames = [_draw_plus(_blank_icon_canvas()) for _ in range(3)]
    cv2.rectangle(frames[0], (40, 250), (70, 280), (0, 0, 0), -1)   # 仅 frame 0
    regions = detect_icons_voted(frames, min_frames=2)
    assert _near_icon(regions, 100, 100)            # 复现的 + 留下
    assert not _near_icon(regions, 55, 265)         # 单帧噪点被滤


@pytest.mark.smoke
def test_detect_icons_falls_back_to_classical_for_unknown_backend():
    """A requested-but-unavailable backend (e.g. omniparser without its AGPL deps)
    must degrade to the always-present classical detector, never raise."""
    from glassbox.cognition.icon_detect import detect_icons
    out = detect_icons(np.zeros((40, 40, 3), dtype=np.uint8), backend="nope_not_real")
    assert isinstance(out, list)


@pytest.mark.smoke
def test_perceive_injects_icon_elements_only_when_flag_on(mock_phone, monkeypatch):
    """CUQ-2.1: with the flag on, perceive() injects detected no-text icon
    regions as tappable image elements (default off injects none). Scene
    classification is unaffected — icons are added after the classifiers."""
    from glassbox.cognition.icon_detect import IconRegion

    mock_phone.ocr.elements = [
        UIElement(type="text", box=Box(x=10, y=10, w=60, h=20),
                  text="标题", confidence=0.9, element_id=0),
    ]
    monkeypatch.setattr(
        "glassbox.cognition.icon_detect.detect_icons",
        lambda frame_img, *, text_boxes=(), **kw: [IconRegion(box=(120, 40, 30, 30))],
    )

    # Default (flag off): no injected icon elements.
    scene_off = mock_phone.perceive()
    assert all(e.type != "image" for e in scene_off.elements)

    # Flag on: the detected region is injected as a tappable image element.
    mock_phone._detect_icons_in_perceive = True
    mock_phone.invalidate_perceive_cache()  # force a cache-miss so detection runs
    scene_on = mock_phone.perceive()
    icons = [e for e in scene_on.elements if e.type == "image"]
    assert len(icons) == 1
    assert icons[0].text is None
    assert icons[0].box.center == (135, 55)
    assert icons[0].element_id == 1  # past the OCR element's id
