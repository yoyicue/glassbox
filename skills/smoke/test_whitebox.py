"""skills/smoke/test_whitebox.py

Unit tests for Tier 1+ white-box icon matching — asset_match.match_asset and
whitebox.apply_whitebox. A synthetic frame is built by compositing a real
asset-catalog PNG onto a blank canvas at a known box, so the matcher can be
verified end-to-end without a device.

The asset workspace (projects/demoapp/reverse/...) is an external optional
dependency — every test skips cleanly when it is not present.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

from glassbox.cognition.asset_match import match_asset
from glassbox.cognition.base import Box, Scene, UIElement, WhiteboxHint
from glassbox.cognition.whitebox import apply_whitebox
from glassbox.profile import Profile

_DEMOAPP = pathlib.Path(__file__).resolve().parents[2] / "profiles" / "demoapp" / "profile.yaml"


@pytest.fixture(scope="module")
def profile() -> Profile:
    if not _DEMOAPP.exists():
        pytest.skip("demoapp profile absent (App-specific content, gitignored)")
    return Profile.from_yaml(_DEMOAPP)


@pytest.fixture(scope="module")
def candidates(profile):
    cands = profile.vc_asset_candidates("MainViewController")
    if not cands:
        pytest.skip("demoapp asset workspace not present — skipping whitebox tests")
    return cands


def _asset(profile: Profile, name: str) -> pathlib.Path:
    p = profile.asset_path(name)
    if p is None:
        pytest.skip(f"asset {name} not present")
    return p


def _frame_with(asset_png: pathlib.Path, box: tuple[int, int, int, int],
                canvas: tuple[int, int] = (900, 900)) -> np.ndarray:
    """Composite an asset PNG onto a light-grey canvas at `box` → BGR frame."""
    import cv2

    frame = np.full((canvas[1], canvas[0], 3), 245, dtype=np.uint8)
    x, y, w, h = box
    a = cv2.resize(cv2.imread(str(asset_png), cv2.IMREAD_UNCHANGED), (w, h))
    if a.ndim == 3 and a.shape[2] == 4:
        bgr = a[:, :, :3].astype(np.float32)
        alpha = a[:, :, 3:4].astype(np.float32) / 255.0
        region = frame[y:y + h, x:x + w].astype(np.float32)
        frame[y:y + h, x:x + w] = (bgr * alpha + region * (1 - alpha)).astype(np.uint8)
    else:
        frame[y:y + h, x:x + w] = a[:, :, :3] if a.ndim == 3 else a[:, :, None]
    return frame


def _scene_with_icon(box: tuple[int, int, int, int], vc: str | None) -> Scene:
    x, y, w, h = box
    el = UIElement(type="image", box=Box(x=x, y=y, w=w, h=h),
                   text="", confidence=0.9, element_id=0)
    return Scene(frame_id=0, timestamp=0.0, elements=[el], current_vc=vc)


# ─── match_asset ─────────────────────────────────────────────────────
@pytest.mark.smoke
def test_match_asset_finds_pasted_icon(profile, candidates):
    box = (300, 300, 120, 120)
    frame = _frame_with(_asset(profile, "cold_selected_icon"), box)
    hit = match_asset(frame, box, candidates)
    assert hit is not None
    name, score = hit
    assert name.startswith("cold_")          # cold_selected / cold_deselected
    assert score >= 0.6


@pytest.mark.smoke
def test_match_asset_rejects_blank_region(candidates):
    """A flat region with no icon must not produce a confident match."""
    frame = np.full((900, 900, 3), 245, dtype=np.uint8)
    assert match_asset(frame, (300, 300, 120, 120), candidates) is None


# ─── apply_whitebox ──────────────────────────────────────────────────
@pytest.mark.smoke
def test_apply_whitebox_populates_hint(profile, candidates):
    box = (300, 300, 120, 120)
    frame = _frame_with(_asset(profile, "cold_selected_icon"), box)
    scene = _scene_with_icon(box, vc="MainViewController")
    apply_whitebox(scene, frame, profile)

    hint = scene.elements[0].whitebox_hint
    assert hint is not None
    assert hint.vc_name == "MainViewController"
    ke = profile.element_for_asset("MainViewController", hint.asset_match)
    assert ke is not None and ke.id == "mode_cold"


@pytest.mark.smoke
def test_apply_whitebox_discriminates_between_icons(profile, candidates):
    box = (300, 300, 120, 120)
    frame = _frame_with(_asset(profile, "heat_selected_icon"), box)
    scene = _scene_with_icon(box, vc="MainViewController")
    apply_whitebox(scene, frame, profile)

    hint = scene.elements[0].whitebox_hint
    assert hint is not None
    ke = profile.element_for_asset("MainViewController", hint.asset_match)
    assert ke is not None and ke.id == "mode_heat"


@pytest.mark.smoke
def test_apply_whitebox_noop_without_current_vc(profile, candidates):
    box = (300, 300, 120, 120)
    frame = _frame_with(_asset(profile, "cold_selected_icon"), box)
    scene = _scene_with_icon(box, vc=None)          # VC not identified
    apply_whitebox(scene, frame, profile)
    assert scene.elements[0].whitebox_hint is None


@pytest.mark.smoke
def test_apply_whitebox_clears_stale_hint_without_current_vc(profile, candidates):
    box = (300, 300, 120, 120)
    frame = _frame_with(_asset(profile, "cold_selected_icon"), box)
    scene = _scene_with_icon(box, vc=None)
    scene.elements[0].whitebox_hint = WhiteboxHint(
        vc_name="MainViewController",
        asset_match="cold_selected_icon",
    )

    apply_whitebox(scene, frame, profile)

    assert scene.elements[0].whitebox_hint is None


@pytest.mark.smoke
def test_apply_whitebox_clears_hint_when_vc_changes(profile):
    box = (300, 300, 120, 120)
    frame = np.full((900, 900, 3), 245, dtype=np.uint8)
    scene = _scene_with_icon(box, vc="SettingsViewController")
    scene.elements[0].whitebox_hint = WhiteboxHint(
        vc_name="MainViewController",
        asset_match="cold_selected_icon",
    )

    apply_whitebox(scene, frame, profile)

    assert scene.elements[0].whitebox_hint is None


@pytest.mark.smoke
def test_apply_whitebox_noop_without_frame(profile, candidates):
    scene = _scene_with_icon((300, 300, 120, 120), vc="MainViewController")
    apply_whitebox(scene, None, profile)
    assert scene.elements[0].whitebox_hint is None


@pytest.mark.smoke
def test_apply_whitebox_noop_on_vc_without_known_elements(profile):
    """SettingsViewController is a known VC but has no known_elements."""
    box = (300, 300, 120, 120)
    frame = np.full((900, 900, 3), 245, dtype=np.uint8)
    scene = _scene_with_icon(box, vc="SettingsViewController")
    apply_whitebox(scene, frame, profile)
    assert scene.elements[0].whitebox_hint is None
