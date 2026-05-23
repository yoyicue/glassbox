"""VLM-assisted row text recovery for iOS Settings root rows.

Owns the small amount of state needed for row-level OCR fallback: per-run
budgeting and crop cache. The crawler resets this module at run start.
"""

from __future__ import annotations

from glassbox.cognition import Box
from glassbox.cognition.vlm_ocr import choose_label_from_region, horizontal_band_box
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY, EXPECTED_ROOT_NAV_TEXT_ZH

_ROW_TEXT_CACHE: dict[str, str] = {}
_ROW_CALL_BUDGET = 20
_row_calls = 0


def reset_row_state() -> None:
    global _row_calls
    _row_calls = 0
    _ROW_TEXT_CACHE.clear()


def recover_root_label(
    phone,
    element,
    *,
    force: bool = False,
    candidate_labels: tuple[str, ...] | None = None,
) -> str | None:
    """Use VLM OCR for root-row labels only when Kimi is enabled."""
    global _row_calls
    kimi = getattr(phone, "kimi", None) if phone is not None else None
    frame = getattr(phone, "_last_frame", None) if phone is not None else None
    if kimi is None or frame is None or not (
        hasattr(kimi, "chat") or hasattr(kimi, "read_text_region")
    ):
        return None
    if not DEFAULT_SETTINGS_POLICY.should_recover_root_row_ocr(element):
        return None
    if not force and _row_calls >= _ROW_CALL_BUDGET:
        return None
    _row_calls += 1
    from glassbox.cognition.vlm_ocr import read_row_text

    row_box = _row_band_box(frame.img, element.box)
    labels = candidate_labels or EXPECTED_ROOT_NAV_TEXT_ZH
    vlm_label = _choose_root_label_from_row(kimi, frame.img, row_box, labels)
    if vlm_label is not None:
        return vlm_label
    if not hasattr(kimi, "read_text_region"):
        return None
    vlm_text = read_row_text(kimi, frame.img, row_box, cache=_ROW_TEXT_CACHE)
    if not vlm_text:
        return None
    return DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(vlm_text)


def _choose_root_label_from_row(
    client,
    frame_img,
    row_box: Box,
    labels: tuple[str, ...],
) -> str | None:
    """Ask the VLM to choose an exact Settings root label from a local row crop."""
    return choose_label_from_region(
        client,
        frame_img,
        row_box,
        labels,
        pad=0,
        cache=_ROW_TEXT_CACHE,
        system=(
            "你是 iOS 设置列表行识别器。输入是一条局部裁剪的设置列表行，"
            "只能从给定候选中选择一个最匹配的根页面标签。"
            "只输出候选标签原文；如果不是这些候选，输出 NONE。"
        ),
        user_prefix="请识别这条局部截图对应哪一个候选标签。",
        normalizer=DEFAULT_SETTINGS_POLICY.canonical_expected_root_label,
    )


def _row_band_box(frame_img, box) -> Box:
    """Crop a horizontal row band, not a full screen and not just one noisy OCR glyph.

    Settings row labels can be split into multiple OCR elements. A single glyph
    crop often lacks enough context for VLM OCR; a shallow row band keeps the
    request local while preserving the visible label fragments.
    """
    return horizontal_band_box(frame_img, box, pad_y=8, min_height=34)
