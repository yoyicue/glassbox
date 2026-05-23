"""glassbox/cognition/text_match.py — text matching helpers

Mainly handles two classes of glyphs that are not "strictly equal" but are
in practice equivalent:

1. **Minus glyph aliases** — under a zh+en dictionary, Vision OCR recognizes
   the ASCII `-` as an em-dash `—` (U+2014) or another dash variant. A
   walkthrough script writing `tap_button("-")` should not fail because of
   this OCR glyph difference.
   See experiments/visionocr_minus/README §3.

2. **Whitespace / fullwidth symbols** — fullwidth/halfwidth differences in
   Chinese UIs, e.g. `获取!` vs `获取!`. For now we just strip; more elaborate
   compatibility can be added later.

Provides:
- the `MINUS_ALIASES` set (all characters treated as `-`)
- `norm_text(s)` normalizes minus aliases / leading-trailing whitespace
- `texts_match(a, b)` overall equality check (based on norm_text)
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Mapping

# these glyphs are all treated as equivalent to ASCII `-` in OCR / UI text
MINUS_ALIASES: frozenset[str] = frozenset({
    "-",      # ASCII U+002D HYPHEN-MINUS
    "—",      # U+2014 EM DASH (Vision often emits this under zh-Hans+en-US)
    "−",      # U+2212 MINUS SIGN
    "–",      # U+2013 EN DASH
    "‒",      # U+2012 FIGURE DASH
    "─",      # U+2500 BOX DRAWINGS LIGHT HORIZONTAL (OCR emits this occasionally)
    "ー",     # U+30FC KATAKANA-HIRAGANA PROLONGED SOUND MARK (shows up occasionally with Asian fonts)
})

# replace minus aliases with ASCII `-` across the whole text
_MINUS_TRANS = str.maketrans({c: "-" for c in MINUS_ALIASES})
# Fold the full "O0〇o" confusion class (see _CONFUSION_CLASSES below) to its
# representative "O". Crucially this includes lowercase o→O: live English iOS
# OCR flips case on round glyphs ("Bluetooth"→"BluetOOth", "Passcode"→
# "PasscOde", "Developer"→"DevelOper"), and without folding it the alias path in
# canonical_label() failed to credit those entered sections in coverage.
_OCR_CONFUSABLE_TRANS = str.maketrans({"0": "O", "〇": "O", "o": "O"})
_SPACE_RE = re.compile(r"\s+")

# —— OCR 形近字混淆类 ——————————————————————————————————————————————
# 每组内的字符 OCR 时相互误认;归一时全部映射到组首(代表字)。
# 这些组是**经验派生**的 —— 来自 iOS 设置走查真机 OCR 记录的变体
# (待机显示→待机見示/待机貝示/待机昰示/侍机显示/伴机息示,紧急SOS→S0S),
# 不是穷举猜测。新增前应先在真机产物里见过该误认。
#
# 注意:混淆类必须窄,且不能让两个真实标签归一后相撞 —— 由
# test_text_match 的 distinct-labels 用例守卫。
_CONFUSION_CLASSES: tuple[str, ...] = (
    "显見貝昰息晃",    # “显”被读成 見/貝/昰/息/晃
    "待侍伴传",        # “待”被读成 侍/伴/传(彳/亻 左偏旁形近)
    "财財",            # “财”被读成繁体 財(App 资源库分类「效率与財务」实测)
    "O0〇o",           # 0/O/〇/o(并入旧 _OCR_CONFUSABLE_TRANS)
)
_CONFUSION_TRANS = str.maketrans({
    ch: cls[0] for cls in _CONFUSION_CLASSES for ch in cls
})
TextNormalizer = Callable[[str | None], str]


# Public, single-source name for the zh (CJK) confusion folds. Locale packs
# reference THIS — never copy the tuple — so there is one source of truth.
DEFAULT_CONFUSION_CLASSES: tuple[str, ...] = _CONFUSION_CLASSES


def _confusion_trans(classes: Iterable[str]):
    return str.maketrans({ch: cls[0] for cls in classes for ch in cls})


class Normalizer:
    """Parameterized confusion-fold normalizer (locale-bound).

    `Normalizer(classes)` builds a compactor that folds each OCR visual-confusion
    class to its representative. This is the locale-driven replacement for the
    module-global `confusion_compact`; the global stays as the zh compatibility
    default (Phase 1), call sites migrate to a locale-bound `Normalizer` later.
    An empty `classes` (e.g. English) means compact-only, no folding.
    """

    def __init__(self, classes: Iterable[str] = DEFAULT_CONFUSION_CLASSES) -> None:
        self.classes: tuple[str, ...] = tuple(classes)
        self._trans = _confusion_trans(self.classes)

    def __call__(self, s: str | None) -> str:
        return compact_text(s).translate(self._trans)


def confusion_compact(s: str | None) -> str:
    """Compact text with OCR visual-confusion characters folded to a canonical
    representative (see `_CONFUSION_CLASSES`).

    `待机見示` / `侍机显示` → `待机显示`;`S0S` → `SOS`. Lets a single confused
    glyph in a short label still match exactly instead of dropping below a
    fuzzy threshold. (zh compatibility default; prefer a locale-bound
    `Normalizer` in new code.)"""
    return compact_text(s).translate(_CONFUSION_TRANS)


def norm_text(s: str | None) -> str:
    """Replace minus aliases in the string with `-`, strip leading/trailing whitespace.

    None / empty string both return an empty string.
    """
    if not s:
        return ""
    return s.translate(_MINUS_TRANS).strip()


def compact_text(s: str | None) -> str:
    """Normalize text and remove internal whitespace."""
    return _SPACE_RE.sub("", norm_text(s))


def ocr_compact_text(s: str | None) -> str:
    """Compact text with common OCR glyph confusions normalized."""
    return compact_text(s).translate(_OCR_CONFUSABLE_TRANS)


def texts_match(a: str | None, b: str | None) -> bool:
    """Exact equality check (after normalization)."""
    return norm_text(a) == norm_text(b) and norm_text(a) != ""


def text_contains(haystack: str | None, needle: str | None) -> bool:
    """Substring containment (after normalization)."""
    h = norm_text(haystack)
    n = norm_text(needle)
    return bool(n) and (n in h)


def fuzzy_ratio(a: str | None, b: str | None) -> float:
    """SequenceMatcher similarity (after normalization)."""
    return difflib.SequenceMatcher(None, norm_text(a), norm_text(b)).ratio()


def canonical_label(
    text: str | None,
    labels: Iterable[str],
    *,
    aliases: Mapping[str, str] | None = None,
    fuzzy: float = 0.82,
    max_leading_noise_chars: int = 0,
) -> str | None:
    """Return the canonical label matched by OCR text.

    `max_leading_noise_chars` handles a common OCR failure where a small icon
    or glyph is glued to the beginning of a row label. Keep it small; this is
    only for visual noise, not substring search.
    """
    stripped = norm_text(text)
    if not stripped:
        return None
    label_set = tuple(labels)
    if aliases is not None:
        alias = aliases.get(stripped)
        if alias in label_set:
            return alias
        normalized_alias = compact_text(stripped)
        ocr_normalized_alias = ocr_compact_text(stripped)
        for alias_text, canonical in aliases.items():
            if canonical not in label_set:
                continue
            if (
                normalized_alias == compact_text(alias_text)
                or ocr_normalized_alias == ocr_compact_text(alias_text)
            ):
                return canonical
    normalized = compact_text(stripped)
    label_pairs = tuple((label, compact_text(label)) for label in label_set)
    for label, candidate in label_pairs:
        if normalized == candidate or fuzzy_ratio(normalized, candidate) >= fuzzy:
            return label
    if max_leading_noise_chars > 0:
        for label, candidate in label_pairs:
            if len(candidate) < 2 or not normalized.endswith(candidate):
                continue
            prefix = normalized[: -len(candidate)]
            if 0 < len(prefix) <= max_leading_noise_chars:
                return label
    # final tier: OCR visual-confusion tolerant closed-set match (B/C)
    return match_known_label(
        stripped,
        label_set,
        min_score=fuzzy,
        max_leading_noise=max_leading_noise_chars,
    )


def vote_ocr_texts(
    readings: Iterable[str | None],
    *,
    normalizer: TextNormalizer | None = None,
) -> str:
    """Consensus of several OCR readings of the *same* logical row (D).

    Each frame OCRs a scrolling row slightly differently (`待机見示` /
    `待机显示` / `侍机昰示`). Normalizes each reading, then does per-position
    majority voting over the readings whose length equals the modal length. A
    glyph that flips frame-to-frame is decided by the majority instead of
    whichever frame happened to be sampled.

    Generic callers default to `norm_text`, preserving app text such as
    "Game Center" / "logout". Closed-set Settings flows may pass
    `normalizer=confusion_compact` to opt into narrow OCR visual-confusion
    folding.

    Returns "" when there is nothing usable.
    """
    normalize = normalizer or norm_text
    norms = [n for n in (normalize(r) for r in readings) if n]
    if not norms:
        return ""
    from collections import Counter

    modal_len = Counter(len(n) for n in norms).most_common(1)[0][0]
    same_len = [n for n in norms if len(n) == modal_len]
    if not same_len:
        return Counter(norms).most_common(1)[0][0]
    return "".join(
        Counter(n[i] for n in same_len).most_common(1)[0][0]
        for i in range(modal_len)
    )


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def match_known_label(
    text: str | None,
    labels: Iterable[str],
    *,
    min_score: float = 0.72,
    margin: float = 0.15,
    max_leading_noise: int = 4,
) -> str | None:
    """Match noisy OCR text to the single closest label in a known closed set.

    Tolerates OCR visual-confusion glyphs (`confusion_compact`) and a short
    *non-CJK* leading icon-glyph prefix. Returns the best label only when it
    clears `min_score` AND beats the second-best by `margin` — an ambiguous
    read returns None rather than guessing between two similar labels.

    A CJK leading prefix is *not* stripped: extra Chinese characters could be
    a genuinely different label rather than icon noise.
    """
    norm = confusion_compact(text)
    if not norm:
        return None
    scored: list[tuple[float, str]] = []
    for label in labels:
        ln = confusion_compact(label)
        if not ln:
            continue
        score = difflib.SequenceMatcher(None, norm, ln).ratio()
        # leading icon-glyph noise: norm ends with the label and the extra
        # prefix is short and non-CJK (Latin/digit/symbol) → treat as a hit.
        if norm != ln and norm.endswith(ln):
            prefix = norm[: len(norm) - len(ln)]
            if 0 < len(prefix) <= max_leading_noise and not any(_is_cjk(c) for c in prefix):
                score = 1.0
        scored.append((score, label))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_label = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= min_score and best_score - second_score >= margin:
        return best_label
    return None
