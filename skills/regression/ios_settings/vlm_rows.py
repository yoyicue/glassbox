"""VLM-assisted row text recovery for iOS Settings root rows.

Owns the small amount of state needed for row-level OCR fallback: per-run
budgeting and crop cache. The crawler resets this module at run start.
"""

from __future__ import annotations

from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

_ROW_TEXT_CACHE: dict[str, str] = {}
_ROW_CALL_BUDGET = 20
_row_calls = 0


def reset_row_state() -> None:
    global _row_calls
    _row_calls = 0
    _ROW_TEXT_CACHE.clear()


def recover_root_label(phone, element) -> str | None:
    """Use VLM OCR for root-row labels only when Kimi is enabled."""
    global _row_calls
    kimi = getattr(phone, "kimi", None) if phone is not None else None
    frame = getattr(phone, "_last_frame", None) if phone is not None else None
    if kimi is None or frame is None or not hasattr(kimi, "read_text_region"):
        return None
    if not DEFAULT_SETTINGS_POLICY.should_recover_root_row_ocr(element):
        return None
    if _row_calls >= _ROW_CALL_BUDGET:
        return None
    _row_calls += 1
    from glassbox.cognition.vlm_ocr import read_row_text

    vlm_text = read_row_text(kimi, frame.img, element.box, cache=_ROW_TEXT_CACHE)
    if not vlm_text:
        return None
    return DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(vlm_text)
