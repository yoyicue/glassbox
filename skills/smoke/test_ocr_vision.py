"""skills/smoke/test_ocr_vision.py — VisionOCR (direct PyObjC calls) + minus glyph normalization tests.

Fully offline (text_match units + synthetic images) + a self-check on the real
cap_ctrl.png image (if present).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from glassbox.cognition import Box, UIElement
from glassbox.cognition.text_match import (
    MINUS_ALIASES,
    canonical_label,
    compact_text,
    fuzzy_ratio,
    norm_text,
    ocr_compact_text,
    text_contains,
    texts_match,
)


# ─── text_match ──────────────────────────────────────────────────────
@pytest.mark.smoke
def test_norm_text_strips_minus_aliases():
    for alias in MINUS_ALIASES:
        assert norm_text(alias) == "-"
        assert norm_text(f" {alias} ") == "-"


@pytest.mark.smoke
def test_norm_text_handles_none_and_empty():
    assert norm_text(None) == ""
    assert norm_text("") == ""
    assert norm_text("   ") == ""


@pytest.mark.smoke
def test_compact_text_removes_internal_whitespace():
    assert compact_text(" Face ID 与 密码 ") == "FaceID与密码"


@pytest.mark.smoke
def test_ocr_compact_text_normalizes_zero_letter_confusion():
    assert ocr_compact_text(" S0S ") == "SOS"
    assert ocr_compact_text("S〇S") == "SOS"


@pytest.mark.smoke
def test_texts_match_ascii_hyphen_vs_em_dash():
    """OCR returns `—` (em-dash); the walkthrough script writes `-`, and they must match."""
    assert texts_match("—", "-") is True
    assert texts_match("-", "−") is True   # ASCII vs U+2212 MINUS SIGN
    assert texts_match("hello", "world") is False
    assert texts_match("", "") is False    # an empty string does not count as a match


@pytest.mark.smoke
def test_text_contains_normalizes_both_sides():
    assert text_contains("press — to confirm", "-") is True
    assert text_contains("升高温度", "升温") is False   # substring does not exist
    assert text_contains("确认登录", "登录") is True


@pytest.mark.smoke
def test_fuzzy_ratio_normalizes_minus():
    """Normalize before the fuzzy comparison; em-dash and hyphen score 1.0."""
    assert fuzzy_ratio("—", "-") == 1.0
    assert fuzzy_ratio("登录", "登入") > 0.4


@pytest.mark.smoke
def test_canonical_label_tolerates_single_leading_ocr_noise():
    labels = ("通用", "蓝牙")

    assert canonical_label("必通用", labels, max_leading_noise_chars=1) == "通用"
    assert canonical_label("多多通用", labels, max_leading_noise_chars=1) is None


@pytest.mark.smoke
def test_canonical_label_normalizes_ocr_confusions_for_aliases():
    aliases = {"SOS": "紧急 SOS"}

    assert canonical_label("S0S", ("紧急 SOS",), aliases=aliases) == "紧急 SOS"


# ─── find_text / find_button integration ─────────────────────────────
@pytest.mark.smoke
def test_find_text_ambiguity_guard_prefers_closest_and_escalates():
    """CUQ-1.5: the ambiguity guard prefers the closest-length containing row
    and returns None on a near-tie fuzzy read; default (off) keeps first-match."""
    from glassbox.cognition import find_text

    substr = [
        UIElement(type="text", box=Box(x=0, y=0, w=200, h=10),
                  text="系统通用设置项", confidence=0.9, element_id=0),  # long, contains 通用
        UIElement(type="text", box=Box(x=0, y=20, w=90, h=10),
                  text="通用网络", confidence=0.9, element_id=1),          # closer to "通用"
    ]
    assert find_text(substr, "通用").element_id == 0  # default: first containing
    assert find_text(substr, "通用", ambiguity_guard=True).element_id == 1  # closest length

    ambiguous = [
        UIElement(type="text", box=Box(x=0, y=0, w=80, h=10),
                  text="abcdefgX", confidence=0.9, element_id=0),
        UIElement(type="text", box=Box(x=0, y=20, w=80, h=10),
                  text="abcdefXh", confidence=0.9, element_id=1),
    ]
    assert find_text(ambiguous, "abcdefgh") is not None  # default: guesses one
    assert find_text(ambiguous, "abcdefgh", ambiguity_guard=True) is None  # near-tie -> escalate


@pytest.mark.smoke
def test_find_text_matches_em_dash_with_hyphen_query():
    from glassbox.cognition.ocr_vision import find_text
    elements = [
        UIElement(type="text", box=Box(x=10, y=10, w=20, h=10),
                  text="—", confidence=0.3, element_id=0),
        UIElement(type="text", box=Box(x=10, y=50, w=20, h=10),
                  text="+", confidence=0.3, element_id=1),
    ]
    el = find_text(elements, "-")
    assert el is not None
    assert el.element_id == 0


@pytest.mark.smoke
def test_find_button_normalizes_minus_for_tap():
    from glassbox.cognition.heuristic import find_button
    elements = [
        UIElement(type="button", box=Box(x=10, y=10, w=20, h=10),
                  text="—", confidence=0.3, element_id=0),
    ]
    btn = find_button(elements, "-")
    assert btn is not None and btn.element_id == 0


# ─── VisionOCR behavior ─────────────────────────────────────────────
def _ocrmac_or_skip():
    """Some CI machines do not have pyobjc-vision installed; skip these tests."""
    try:
        from glassbox.cognition.ocr_vision import VisionOCR
        return VisionOCR
    except ImportError:
        pytest.skip("pyobjc-framework-Vision not installed")


@pytest.mark.smoke
def test_vision_ocr_init_defaults_have_unsharp_on():
    VisionOCR = _ocrmac_or_skip()
    ocr = VisionOCR()
    assert ocr.unsharp_mask is True
    assert ocr.unsharp_sigma == pytest.approx(1.5)
    assert ocr.unsharp_amount == pytest.approx(1.6)
    assert ocr.uses_language_correction is False
    assert ocr.recognition_level == "accurate"


@pytest.mark.smoke
def test_vision_ocr_rejects_invalid_recognition_level():
    VisionOCR = _ocrmac_or_skip()
    with pytest.raises(ValueError, match="recognition_level"):
        VisionOCR(recognition_level="ultra")


@pytest.mark.smoke
def test_vision_ocr_apply_unsharp_returns_ndarray():
    """_apply_unsharp given an ndarray should return an ndarray of the same shape."""
    VisionOCR = _ocrmac_or_skip()
    ocr = VisionOCR()
    img = (np.random.rand(100, 200, 3) * 255).astype(np.uint8)
    out = ocr._apply_unsharp(img)
    assert isinstance(out, np.ndarray)
    assert out.shape == img.shape


@pytest.mark.smoke
def test_vision_ocr_recognize_white_image_returns_empty():
    VisionOCR = _ocrmac_or_skip()
    ocr = VisionOCR()
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    els = ocr.recognize(img)
    assert els == []


# ─── real-image self-check ──────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
CAP_CTRL = _REPO_ROOT / "assets" / "walkthroughs" / "demoapp_v1" / "02_control.png"


@pytest.mark.smoke
@pytest.mark.skipif(not CAP_CTRL.exists(),
                    reason="assets/walkthroughs/demoapp_v1/02_control.png missing")
def test_real_cap_ctrl_picks_up_minus_button():
    """Real verification: on cap_ctrl.png (after letterbox crop), the default VisionOCR
    must recognize the - button (as - or em-dash) and it must be hit by find_text('-')."""
    import cv2

    from glassbox.cognition.ocr_vision import find_text
    from glassbox.perception.device import IPHONE_17_PRO_MAX
    from glassbox.perception.letterbox import LetterboxCrop

    VisionOCR_ = _ocrmac_or_skip()
    img = cv2.imread(str(CAP_CTRL))
    lc = LetterboxCrop.auto_detect(img, phone_size=IPHONE_17_PRO_MAX)
    cropped = lc.crop(img)

    ocr = VisionOCR_()
    elements = ocr.recognize(cropped)

    el = find_text(elements, "-")
    assert el is not None, f"- button not found; current element texts={[e.text for e in elements]}"
    cx, _ = el.box.center
    # `-` is near x≈150 in the cropped frame (autoresearch data)
    assert 100 < cx < 200, f"- position out of range x={cx}"


@pytest.mark.smoke
@pytest.mark.skipif(not CAP_CTRL.exists(),
                    reason="assets/walkthroughs/demoapp_v1/02_control.png missing")
def test_real_cap_ctrl_unsharp_off_loses_minus():
    """Counter-evidence: with unsharp off, - should not be picked up (autoresearch baseline)."""
    import cv2

    from glassbox.cognition.ocr_vision import VisionOCR
    from glassbox.perception.device import IPHONE_17_PRO_MAX
    from glassbox.perception.letterbox import LetterboxCrop

    _ocrmac_or_skip()
    img = cv2.imread(str(CAP_CTRL))
    lc = LetterboxCrop.auto_detect(img, phone_size=IPHONE_17_PRO_MAX)
    cropped = lc.crop(img)

    ocr = VisionOCR(unsharp_mask=False)
    elements = ocr.recognize(cropped)

    # the `-` button is near x∈[120,200] y∈[420,460] in the cropped frame
    # with unsharp off, this position should have no OCR text
    in_minus_zone = [
        e for e in elements
        if 120 < e.box.center[0] < 200 and 420 < e.box.center[1] < 460
    ]
    assert in_minus_zone == [], (
        f"got an OCR result at the - position with unsharp off? retest and retune. "
        f"in_minus_zone={[(e.text, e.box.center) for e in in_minus_zone]}"
    )
