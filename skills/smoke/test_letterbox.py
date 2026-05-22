"""skills/smoke/test_letterbox.py — LetterboxCrop unit tests. Fully offline.

Coverage:
  - detect_letterbox measures the letterbox
  - all-black raises ValueError
  - no letterbox → the whole image is the bbox
  - LetterboxCrop coordinate round-trip
  - LetterboxCrop.crop returns the correct size
  - validates against real data on /tmp/cap2.png (if present)
  - once Phone uses crop, the effector sees phone logical coordinates
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from glassbox.obs import Recorder
from glassbox.obs.recorder import iter_events
from glassbox.perception.letterbox import LetterboxCrop, detect_letterbox


# ─── detect_letterbox ────────────────────────────────────────────────
@pytest.mark.smoke
def test_detect_letterbox_with_borders():
    """A 1920x1080 image with 448x972 content in the center; the letterbox is measured exactly."""
    H, W = 1080, 1920
    cw, ch = 448, 972
    cx, cy = (W - cw) // 2, (H - ch) // 2
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[cy:cy + ch, cx:cx + cw] = 200

    x, y, w, h = detect_letterbox(img)
    assert (x, y, w, h) == (cx, cy, cw, ch)


@pytest.mark.smoke
def test_detect_letterbox_full_content():
    """For an image with no letterbox, the bbox equals the whole image."""
    img = np.full((100, 100, 3), 150, dtype=np.uint8)
    assert detect_letterbox(img) == (0, 0, 100, 100)


@pytest.mark.smoke
def test_detect_letterbox_all_black_raises():
    """An all-black image (lock screen / no signal) raises ValueError."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="threshold"):
        detect_letterbox(img)


@pytest.mark.smoke
def test_detect_letterbox_threshold_filters_noise():
    """Noise below the threshold is not treated as content."""
    img = np.full((100, 100, 3), 10, dtype=np.uint8)   # whole image at brightness 10
    img[40:60, 40:60] = 100                             # bright 20x20 in the center
    x, y, w, h = detect_letterbox(img, threshold=50)
    assert (x, y, w, h) == (40, 40, 20, 20)


@pytest.mark.smoke
def test_detect_letterbox_grayscale_image():
    """A grayscale 2D array works too (not limited to BGR)."""
    img = np.zeros((50, 80), dtype=np.uint8)
    img[10:30, 20:60] = 200
    assert detect_letterbox(img) == (20, 10, 40, 20)


# ─── LetterboxCrop ──────────────────────────────────────────────────
@pytest.mark.smoke
def test_letterbox_crop_auto_detect_iphone17pm_like():
    """Simulate an iPhone 17 Pro Max inside a 1920x1080 letterbox."""
    H, W = 1080, 1920
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[54:54 + 972, 736:736 + 448] = 128
    lc = LetterboxCrop.auto_detect(img, phone_size=(1320, 2868))
    assert lc.crop_bbox == (736, 54, 448, 972)
    assert lc.frame_size == (W, H)
    assert lc.phone_size == (1320, 2868)
    assert lc.cropped_size == (448, 972)
    # scale factor is about 2.946
    assert lc.scale_x == pytest.approx(2.946, abs=0.01)
    assert lc.scale_y == pytest.approx(2.951, abs=0.01)


@pytest.mark.smoke
def test_letterbox_auto_detect_rejects_tiny_dark_content_bbox():
    """Dark apps with only bright text must not shrink the crop to the text bbox."""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[500:540, 900:1020] = 255

    with pytest.raises(ValueError, match="too small"):
        LetterboxCrop.auto_detect(img, phone_size=(1320, 2868))


@pytest.mark.smoke
def test_letterbox_crop_returns_correct_size():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    img[20:80, 50:150] = 200
    lc = LetterboxCrop.auto_detect(img, phone_size=(500, 300))
    cropped = lc.crop(img)
    assert cropped.shape == (60, 100, 3)


@pytest.mark.smoke
def test_letterbox_coord_roundtrip():
    """cropped → phone → cropped should return close to the origin (rounding error ≤ 1px)."""
    lc = LetterboxCrop(
        crop_bbox=(736, 54, 448, 972),
        frame_size=(1920, 1080),
        phone_size=(1320, 2868),
    )
    for cx, cy in [(0, 0), (100, 200), (224, 486), (447, 971)]:
        px, py = lc.cropped_to_phone(cx, cy)
        rx, ry = lc.phone_to_cropped(px, py)
        assert abs(rx - cx) <= 1
        assert abs(ry - cy) <= 1


@pytest.mark.smoke
def test_letterbox_known_demoapp_pixel():
    """On cap2.png, OCR sees the DemoApp label center at roughly (873+33, 554+7) = (906, 561)
    in frame coordinates. Transformed to cropped coordinates: cx = 906 - 736 = 170,
    cy = 561 - 54 = 507. Transformed further to phone logical coordinates: about (501, 1496).
    """
    lc = LetterboxCrop(
        crop_bbox=(736, 54, 448, 972),
        frame_size=(1920, 1080),
        phone_size=(1320, 2868),
    )
    px, py = lc.cropped_to_phone(170, 507)
    assert 490 <= px <= 510
    assert 1480 <= py <= 1510


@pytest.mark.smoke
def test_letterbox_cropped_to_frame():
    lc = LetterboxCrop(
        crop_bbox=(736, 54, 448, 972),
        frame_size=(1920, 1080),
        phone_size=(1320, 2868),
    )
    fx, fy = lc.cropped_to_frame(170, 507)
    assert fx == 736 + 170
    assert fy == 54 + 507


# ─── real data ───────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
CAP_HOME = _REPO_ROOT / "assets" / "walkthroughs" / "demoapp_v1" / "01_home.png"


@pytest.mark.smoke
@pytest.mark.skipif(not CAP_HOME.exists(),
                    reason="assets/walkthroughs/demoapp_v1/01_home.png missing")
def test_real_capture_detects_iphone17pm_bbox():
    """Run auto_detect on a real captured frame; the bbox should match the previously
    hand-measured (736, 54, 448, 972) within ±2px."""
    import cv2
    img = cv2.imread(str(CAP_HOME))
    lc = LetterboxCrop.auto_detect(img, phone_size=(1320, 2868))
    x, y, w, h = lc.crop_bbox
    assert abs(x - 736) <= 2
    assert abs(y - 54) <= 2
    assert abs(w - 448) <= 2
    assert abs(h - 972) <= 2


# ─── Phone integration ──────────────────────────────────────────────
@pytest.mark.smoke
def test_phone_with_crop_converts_tap_xy_to_frame_coords_for_frame_px_effector(tmp_path, mock_phone):
    """With a frame-px effector, cropped tap coords are projected back into the HDMI frame."""
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.crop = LetterboxCrop(
        crop_bbox=(736, 54, 448, 972),
        frame_size=(1920, 1080),
        phone_size=(1320, 2868),
    )
    mock_phone.tap_xy(100, 200)
    mock_phone.recorder.close()
    last = mock_phone.effector.last()
    assert last.op == "tap"
    assert last.kwargs["x"] == 836
    assert last.kwargs["y"] == 254
    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert action["coordinate_space"] == "frame_px"


@pytest.mark.smoke
def test_phone_with_crop_converts_tap_xy_to_phone_coords_for_phone_px_effector(tmp_path, mock_phone):
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.effector.coordinate_space = "phone_px"
    mock_phone.crop = LetterboxCrop(
        crop_bbox=(736, 54, 448, 972),
        frame_size=(1920, 1080),
        phone_size=(1320, 2868),
    )
    mock_phone.tap_xy(100, 200)
    mock_phone.recorder.close()
    last = mock_phone.effector.last()
    assert last.op == "tap"
    assert 290 <= last.kwargs["x"] <= 300
    assert 585 <= last.kwargs["y"] <= 595
    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert action["coordinate_space"] == "phone_px"


@pytest.mark.smoke
def test_phone_with_frame_space_records_phone_pt(tmp_path, mock_phone):
    mock_phone.recorder = Recorder(tmp_path)
    mock_phone.effector.coordinate_space = "phone_pt"
    mock_phone.crop = LetterboxCrop(
        crop_bbox=(0, 0, 1320, 2868),
        frame_size=(1320, 2868),
        phone_size=(440, 956),
    )

    mock_phone.tap_xy(660, 1434)
    mock_phone.recorder.close()

    last = mock_phone.effector.last()
    assert last.kwargs == {"x": 220, "y": 478}
    action = next(e for e in iter_events(tmp_path) if e["type"] == "action")
    assert action["coordinate_space"] == "phone_pt"


@pytest.mark.smoke
def test_phone_without_crop_passthrough(mock_phone):
    """No crop set → tap_xy passes through, behaving as before the change."""
    assert mock_phone.crop is None
    mock_phone.tap_xy(123, 456)
    last = mock_phone.effector.last()
    assert (last.kwargs["x"], last.kwargs["y"]) == (123, 456)
