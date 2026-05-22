"""glassbox/cognition/whitebox.py — Tier 1+ white-box enrichment.

When the perceived Scene has been identified as a known VC (Phone._apply_profile
→ profile.match_vc), this pass icon-matches the VC's known_elements against the
detected on-screen elements and writes the result onto `UIElement.whitebox_hint`.

This is the cross-cutting "(whitebox)" layer from docs/design/gui_understanding.md §7
— it runs beside Layer 1/2/3, not inside them, and is a no-op at Tier 0 (no
profile) or when the current VC has no known_elements / no asset workspace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from glassbox.cognition.asset_match import match_asset
from glassbox.cognition.base import WhiteboxHint

if TYPE_CHECKING:
    import numpy as np

    from glassbox.cognition.base import Scene, UIElement
    from glassbox.profile import Profile

# element types worth icon-matching (text-heavy elements are skipped)
_ICON_TYPES = {"image", "button", "unknown", "tab_bar_item"}


def _is_icon_like(el: UIElement) -> bool:
    return el.type in _ICON_TYPES


def apply_whitebox(scene: Scene, frame_bgr: np.ndarray | None, profile: Profile) -> Scene:
    """Icon-match the current VC's known_elements onto scene.elements.

    For each icon-like element that confidently matches a known asset, sets
    `element.whitebox_hint` (vc_name + asset_match). Modifies the scene in
    place and returns it. No-op unless a VC is identified AND it has
    resolvable known-element assets.
    """
    vc = scene.current_vc
    for el in scene.elements:
        if not _is_icon_like(el):
            continue
        if el.whitebox_hint is not None and el.whitebox_hint.vc_name != vc:
            el.whitebox_hint = None

    if vc is None or frame_bgr is None:
        return scene
    candidates = profile.vc_asset_candidates(vc)
    if not candidates:
        for el in scene.elements:
            if _is_icon_like(el):
                el.whitebox_hint = None
        return scene

    for el in scene.elements:
        if not _is_icon_like(el):
            continue
        hit = match_asset(frame_bgr, (el.box.x, el.box.y, el.box.w, el.box.h), candidates)
        if hit is None:
            el.whitebox_hint = None
            continue
        asset_name, _score = hit
        el.whitebox_hint = WhiteboxHint(vc_name=vc, asset_match=asset_name)

    return scene
