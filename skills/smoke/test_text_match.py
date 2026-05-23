"""OCR 视觉混淆容忍匹配(text_match B/C)。"""
from __future__ import annotations

import pytest

from glassbox.cognition.text_match import (
    canonical_label,
    confusion_compact,
    match_known_label,
    vote_ocr_texts,
)

# iOS 26.5 设置严格根入口(与 test_readonly_walkthrough.EXPECTED_ROOT_NAV_TEXT_ZH 对齐)
_ROOTS = (
    "无线局域网", "蓝牙", "蜂窝网络", "通知", "声音与触感", "专注模式",
    "屏幕使用时间", "通用", "辅助功能", "Siri", "操作按钮", "待机显示",
    "Face ID与密码", "紧急 SOS", "隐私与安全性", "电池", "钱包与 Apple Pay",
)


@pytest.mark.smoke
def test_confusion_compact_folds_known_lookalikes():
    assert confusion_compact("待机見示") == confusion_compact("待机显示")
    assert confusion_compact("侍机显示") == confusion_compact("待机显示")
    assert confusion_compact("S0S") == confusion_compact("SOS")


@pytest.mark.smoke
def test_root_labels_stay_distinct_under_confusion_normalization():
    """混淆类不能让两个真实根标签归一后相撞 —— B 的安全护栏。"""
    norms = [confusion_compact(r) for r in _ROOTS]
    assert len(set(norms)) == len(norms)


@pytest.mark.smoke
@pytest.mark.parametrize("variant", [
    "待机見示", "待机貝示", "侍机显示", "伴机息示", "待机昰示", "传机見示",
])
def test_match_known_label_resolves_standby_ocr_variants(variant):
    assert match_known_label(variant, _ROOTS) == "待机显示"


@pytest.mark.smoke
@pytest.mark.parametrize("variant", ["ET 操作按钮", "O 操作按钮"])
def test_match_known_label_tolerates_leading_icon_glyph(variant):
    assert match_known_label(variant, _ROOTS) == "操作按钮"


@pytest.mark.smoke
def test_match_known_label_rejects_ambiguous_and_junk():
    # 无意义噪声 → None
    assert match_known_label("xyz乱码", _ROOTS) is None
    assert match_known_label("", _ROOTS) is None
    # 单字不足以在 margin 守卫下判定
    assert match_known_label("通", _ROOTS) is None


@pytest.mark.smoke
def test_canonical_label_falls_through_to_confusion_match():
    """canonical_label 末档接 match_known_label —— 1 字混淆也能命中。"""
    assert canonical_label("待机見示", _ROOTS) == "待机显示"


@pytest.mark.smoke
@pytest.mark.parametrize("garbled,canonical", [
    ("BluetOOth", "蓝牙"),          # "Bluetooth": lowercase oo read as OO
    ("FaceID&PasscOde", "Face ID与密码"),  # "Passcode": o read as O (+ spacing)
    ("DevelOper", "Developer"),     # "Developer": o read as O
])
def test_canonical_label_credits_case_flipped_english_aliases(garbled, canonical):
    """Live English iOS OCR flips case on round glyphs (o↔O); the alias path
    must still canonicalize so coverage credits the entered section. Guards the
    o→O fold in ocr_compact_text — without it en-HK undercounted 蓝牙 / Face ID."""
    aliases = {"Bluetooth": "蓝牙", "Face ID & Passcode": "Face ID与密码", "Developer": "Developer"}
    labels = ("蓝牙", "Face ID与密码", "Developer")
    assert canonical_label(garbled, labels, aliases=aliases) == canonical


@pytest.mark.smoke
def test_canonical_label_confusion_fallback_respects_fuzzy_threshold():
    assert canonical_label("隐私与安全", ("隐私与安全性",), fuzzy=0.99) is None


@pytest.mark.smoke
def test_canonical_label_confusion_fallback_respects_noise_limit():
    labels = ("通用", "通知")
    assert canonical_label("A通用", labels, max_leading_noise_chars=1) == "通用"
    assert canonical_label("ABCD通用", labels, max_leading_noise_chars=1) is None


@pytest.mark.smoke
def test_vote_ocr_texts_consensus_across_confused_readings():
    """同一行多帧读数,混淆归一后一致 → 共识。"""
    assert (
        vote_ocr_texts(
            ["待机見示", "待机显示", "侍机昰示"],
            normalizer=confusion_compact,
        )
        == "待机显示"
    )


@pytest.mark.smoke
def test_vote_ocr_texts_per_position_majority():
    """某位字逐帧翻动 → 多数票决定,而非取某一帧。"""
    # 第3位:贝/显/显 → 显(归一后)胜出
    assert (
        vote_ocr_texts(
            ["待机贝示", "待机显示", "待机显示"],
            normalizer=confusion_compact,
        )
        == "待机显示"
    )


@pytest.mark.smoke
def test_vote_ocr_texts_default_preserves_generic_app_text():
    assert vote_ocr_texts(["消息", "消息"]) == "消息"
    assert vote_ocr_texts(["logout", "logout"]) == "logout"
    assert vote_ocr_texts(["Game Center", "Game Center"]) == "Game Center"


@pytest.mark.smoke
def test_vote_ocr_texts_empty():
    assert vote_ocr_texts([]) == ""
    assert vote_ocr_texts([None, "", "  "]) == ""
