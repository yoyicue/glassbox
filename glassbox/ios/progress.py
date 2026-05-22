"""Generic iOS OCR progress helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Status-bar clock. The minute slot tolerates digit-confused glyphs (O/o/l/B/
# S/I) so an OCR-mangled time like ``13:3O4`` is still recognised as noise.
_TIME_RE = re.compile(r"^\d{1,2}[:：.]?[\dOolBSI]{2,4}[A-Za-z>]*$")
_OCR_NOISE_TEXTS = {"<", "下", "Q", "の", "劣", "巴", "AA", "t"}
_CJK_RE = re.compile(r"[一-鿿]")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_WS_RE = re.compile(r"\s+")


def _norm_row(text: str) -> str:
    """Canonical form for comparing a row across frames.

    OCR is inconsistent about intra-row whitespace (``Game Center`` vs
    ``GameCenter``) and letter case (``iCloud`` vs ``iClOud``). Two perceive
    paths can emit the same physical row in different forms; comparing raw
    strings then reports a still list as "half the rows changed" and defeats
    scroll stuck-detection. Strip all whitespace and casefold.
    """
    return _WS_RE.sub("", text).casefold()


def _is_symbol_fragment(text: str) -> bool:
    """True for punctuation/symbol-only OCR noise (e.g. ``（②``, ``-）``).

    Real list rows always carry a CJK character or a real word; a fragment
    with no CJK and fewer than two alphanumerics is OCR garbage — chevrons,
    arrows, badges misread as glyphs — and must not count as a stable row,
    or it fakes "new content" and defeats scroll stuck-detection.
    """
    return not _CJK_RE.search(text) and len(_ALNUM_RE.findall(text)) < 2


def screen_signature(texts: Iterable[str], *, limit: int = 12) -> tuple[str, ...]:
    return tuple(list(dict.fromkeys(texts))[:limit])


def is_time_text(text: str) -> bool:
    return bool(_TIME_RE.match(text.strip()))


def stable_visible_texts(texts: Iterable[str]) -> set[str]:
    stable: set[str] = set()
    for text in texts:
        t = text.strip()
        if not t or t in _OCR_NOISE_TEXTS:
            continue
        if is_time_text(t):
            continue
        if re.search(r"(最近|[取蕺]近)\d*$", t):
            continue
        if len(t) == 1:
            continue
        if _is_symbol_fragment(t):
            continue
        if any(ch in t for ch in "•。〇◎") and len(_ALNUM_RE.findall(t)) <= 2:
            continue
        stable.add(_norm_row(t))
    return stable


def same_visible_page(before_texts: Iterable[str], after_texts: Iterable[str]) -> bool:
    before = stable_visible_texts(before_texts)
    after = stable_visible_texts(after_texts)
    if min(len(before), len(after)) < 5:
        if before and before == after:
            return True
        return screen_signature(before_texts) == screen_signature(after_texts)
    overlap = len(before & after) / min(len(before), len(after))
    return overlap >= 0.72


# 相邻帧稳定行重叠率的两个判据。率(而非「零重叠 / 严格子集」)对 OCR
# 抖动稳健 —— 持久 chrome 贡献的重叠不会把整列表跳变伪装成重叠;少数
# OCR 变体行也不会把一动不动的列表伪装成「出现新行」。
_SCROLL_OVERSHOOT_OVERLAP = 0.34   # 低于此 = 跳过了 >1 屏
_SCROLL_STUCK_OVERLAP = 0.80       # 高于此 = 几乎没动(差异仅 OCR 噪声)


def scroll_outcome(before_texts: Iterable[str], after_texts: Iterable[str]) -> str:
    """Classify a scroll by the stable-row overlap between before/after frames.

    A correct partial scroll keeps a meaningful slice of rows visible (overlap)
    AND reveals new ones. Three outcomes drive a closed-loop scroll controller:

    - ``"overshoot"`` — overlap ratio below `_SCROLL_OVERSHOOT_OVERLAP`: the
      scroll jumped more than a screenful, so rows in between were never OCR'd.
    - ``"stuck"``     — overlap ratio at or above `_SCROLL_STUCK_OVERLAP`: the
      list barely moved; the residual difference is OCR noise, not new rows.
    - ``"progress"``  — healthy partial scroll: overlap AND new rows.

    A ratio (not a strict ``after ⊆ before`` subset) decides ``"stuck"`` so a
    couple of OCR-variant rows cannot flip a still list to ``"progress"``.
    Sparse frames (< 3 stable rows either side) carry too little signal to
    judge and default to ``"progress"``.
    """
    before = stable_visible_texts(before_texts)
    after = stable_visible_texts(after_texts)
    if len(before) < 3 or len(after) < 3:
        return "progress"
    ratio = len(before & after) / min(len(before), len(after))
    if ratio < _SCROLL_OVERSHOOT_OVERLAP:
        return "overshoot"
    if ratio >= _SCROLL_STUCK_OVERLAP:
        return "stuck"
    return "progress"


def scroll_overshot(before_texts: Iterable[str], after_texts: Iterable[str]) -> bool:
    """True when a scroll jumped more than a screenful (see `scroll_outcome`)."""
    return scroll_outcome(before_texts, after_texts) == "overshoot"


def trace_payload_no_progress(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if before.get("scene_type") != after.get("scene_type"):
        return False
    before_texts = before.get("texts")
    after_texts = after.get("texts")
    if not isinstance(before_texts, list) or not isinstance(after_texts, list):
        return before.get("signature") == after.get("signature")
    return same_visible_page(before_texts, after_texts)
