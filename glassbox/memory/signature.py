"""glassbox/memory/signature.py — structural screen fingerprint + similarity.

Screen identity is *structural*, not pixel-exact (unlike CachedKimi's
byte-hash). Two frames of the same screen — different status-bar clock, a
spinner mid-animation — must hash close. See docs/design/screen_memory.md §3.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from glassbox.cognition.text_match import norm_text
from glassbox.memory.element_key import is_volatile
from glassbox.memory.schema import ScreenSignature

if TYPE_CHECKING:
    import numpy as np

    from glassbox.cognition.base import Scene

# two signatures with similarity >= this are treated as the same screen
SIGNATURE_MATCH_THRESHOLD = 0.82
_HASH_SIZE = 8                       # dhash → _HASH_SIZE**2 = 64 bits


def dhash(img: np.ndarray | None) -> str:
    """64-bit difference hash of a frame as a 64-char '0'/'1' string.

    Downsamples to 9x8 then compares adjacent columns — robust to small
    pixel noise. Returns "" for a missing or too-small image.
    """
    if img is None:
        return ""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if getattr(img, "ndim", 0) == 3 else img
    if gray.shape[0] < 2 or gray.shape[1] < 2:
        return ""
    small = cv2.resize(gray, (_HASH_SIZE + 1, _HASH_SIZE), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    return "".join("1" if b else "0" for b in diff.flatten())


def _hamming(a: str, b: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(a, b, strict=False))


def compute_signature(scene: Scene, phash: str = "") -> ScreenSignature:
    """Structural fingerprint of a scene. `phash` is supplied separately
    because the Scene carries no frame image."""
    stable = {
        norm_text(e.text)
        for e in scene.elements
        if e.text and norm_text(e.text) and e.type != "status_bar" and not is_volatile(e)
    }
    hist: Counter[str] = Counter()
    for e in scene.elements:
        if _counts_for_signature_histogram(e):
            hist[e.type] += 1
    return ScreenSignature(
        stable_texts=sorted(stable),
        type_histogram=dict(hist),
        phash=phash,
    )


def _counts_for_signature_histogram(element: object) -> bool:
    element_type = getattr(element, "type", None)
    if element_type == "status_bar":
        return False
    if element_type != "image":
        return True
    if norm_text(getattr(element, "text", None)):
        return True
    if norm_text(getattr(element, "intent_label", None)):
        return True
    if getattr(element, "suggested_actions", None):
        return True
    whitebox = getattr(element, "whitebox_hint", None)
    return bool(
        whitebox is not None
        and (
            getattr(whitebox, "asset_match", None)
            or getattr(whitebox, "accessibility_id", None)
        )
    )


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _hist_sim(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    l1 = sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)
    total = sum(a.values()) + sum(b.values())
    return 1.0 - l1 / max(1, total)


def similarity(a: ScreenSignature, b: ScreenSignature) -> float:
    """Screen similarity in [0, 1]. Text Jaccard + type-histogram + phash.

    phash is a soft signal — when either side lacks it (offline build, tiny
    test frame) the weight is redistributed onto text + histogram.
    """
    jac = _jaccard(a.stable_texts, b.stable_texts)
    hist = _hist_sim(a.type_histogram, b.type_histogram)
    if a.phash and b.phash and len(a.phash) == len(b.phash):
        ham = 1.0 - _hamming(a.phash, b.phash) / len(a.phash)
        return 0.55 * jac + 0.30 * hist + 0.15 * ham
    return 0.65 * jac + 0.35 * hist
