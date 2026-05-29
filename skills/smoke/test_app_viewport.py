from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from glassbox.effector import MockEffector
from glassbox.perception.app_viewport import ViewportCrop, detect_iphone_compat_viewport
from glassbox.perception.letterbox import LetterboxCrop
from glassbox.perception.source import Frame
from glassbox.phone import Phone


class ImageSource:
    coordinate_space = "frame_px"

    def __init__(self, img: np.ndarray):
        self.img = img
        self.resolution = (img.shape[1], img.shape[0])
        self.ts = 0.0

    def snapshot(self):
        self.ts += 1.0
        return Frame(img=self.img.copy(), ts=self.ts)


class SequenceSource:
    coordinate_space = "frame_px"

    def __init__(self, imgs: list[np.ndarray]):
        self.imgs = imgs
        self.resolution = (imgs[0].shape[1], imgs[0].shape[0])
        self.index = 0
        self.ts = 0.0

    def snapshot(self):
        self.ts += 1.0
        img = self.imgs[min(self.index, len(self.imgs) - 1)]
        self.index += 1
        return Frame(img=img.copy(), ts=self.ts)


class ShapeOCR:
    def __init__(self):
        self.shapes: list[tuple[int, int]] = []

    def recognize(self, img):
        self.shapes.append((img.shape[1], img.shape[0]))
        return []


@pytest.mark.smoke
def test_ipad_mini_6_shares_ipad_mini_7_geometry():
    # iPad mini 6 and 7 ship the identical 8.3" panel and both use USB-C; the mini 6
    # profile must resolve to the same pixel + point geometry so
    # GLASSBOX_PHONE_MODEL=ipad_mini_6 works (same screen, different SoC only).
    from glassbox.perception import device

    assert device.get("ipad_mini_6") == device.get("ipad_mini_7") == (1488, 2266)
    assert device.get_points("ipad_mini_6") == device.get_points("ipad_mini_7") == (744, 1133)


@pytest.mark.smoke
def test_app_scope_snapshot_crops_inner_viewport_and_records_projection_chain():
    img = np.arange(80 * 100 * 3, dtype=np.uint8).reshape((80, 100, 3))
    crop = LetterboxCrop(crop_bbox=(10, 5, 50, 40), frame_size=(100, 80), phone_size=(500, 400))
    app_viewport = ViewportCrop(
        name="app",
        parent_coordinate_space="cropped_px",
        coordinate_space="app_px",
        bbox=(20, 6, 10, 8),
    )
    phone = Phone(
        source=ImageSource(img),
        ocr=ShapeOCR(),
        effector=MockEffector(),
        crop=crop,
        app_viewport=app_viewport,
    )

    frame = phone.snapshot(scope="app")

    assert frame.shape == (10, 8)
    np.testing.assert_array_equal(frame.img, img[11:19, 30:40, :])
    assert frame.context.coordinate_space == "app_px"
    assert frame.context.source_coordinate_space == "frame_px"
    assert frame.context.source_shape == (100, 80)
    assert frame.context.crop_bbox == (20, 6, 10, 8)
    assert [projection.name for projection in frame.context.projection_chain] == ["device", "app"]
    assert [projection.crop_bbox for projection in frame.context.projection_chain] == [
        (10, 5, 50, 40),
        (20, 6, 10, 8),
    ]


@pytest.mark.smoke
def test_app_scope_coordinates_project_back_to_outer_device_frame():
    img = np.zeros((80, 100, 3), dtype=np.uint8)
    crop = LetterboxCrop(crop_bbox=(10, 5, 50, 40), frame_size=(100, 80), phone_size=(500, 400))
    app_viewport = ViewportCrop(
        name="app",
        parent_coordinate_space="cropped_px",
        coordinate_space="app_px",
        bbox=(20, 6, 10, 8),
    )
    effector = MockEffector()
    phone = Phone(
        source=ImageSource(img),
        ocr=ShapeOCR(),
        effector=effector,
        crop=crop,
        app_viewport=app_viewport,
    )

    phone.snapshot(scope="app")
    phone.tap_xy(3, 4)

    assert effector.last().kwargs["x"] == 33
    assert effector.last().kwargs["y"] == 15


@pytest.mark.smoke
def test_cross_scope_tap_requires_explicit_coordinate_space():
    img = np.zeros((80, 100, 3), dtype=np.uint8)
    crop = LetterboxCrop(crop_bbox=(10, 5, 50, 40), frame_size=(100, 80), phone_size=(500, 400))
    app_viewport = ViewportCrop(
        name="app",
        parent_coordinate_space="cropped_px",
        coordinate_space="app_px",
        bbox=(20, 6, 10, 8),
    )
    effector = MockEffector()
    phone = Phone(
        source=ImageSource(img),
        ocr=ShapeOCR(),
        effector=effector,
        crop=crop,
        app_viewport=app_viewport,
    )

    phone.perceive(scope="app")
    phone.snapshot(scope="device")

    with pytest.raises(ValueError, match="coordinate_space"):
        phone.tap_xy(3, 4)

    phone.tap_xy(3, 4, coordinate_space="app_px")

    assert effector.last().kwargs["x"] == 33
    assert effector.last().kwargs["y"] == 15


@pytest.mark.smoke
def test_default_app_observation_scope_feeds_ocr_the_inner_viewport():
    img = np.zeros((80, 100, 3), dtype=np.uint8)
    app_viewport = ViewportCrop(
        name="app",
        parent_coordinate_space="frame_px",
        coordinate_space="app_px",
        bbox=(30, 10, 20, 30),
    )
    ocr = ShapeOCR()
    phone = Phone(
        source=ImageSource(img),
        ocr=ocr,
        effector=MockEffector(),
        app_viewport=app_viewport,
        default_observation_scope="app",
    )

    scene = phone.perceive()

    assert ocr.shapes == [(20, 30)]
    assert scene.viewport_size == (20, 30)


@pytest.mark.smoke
def test_detect_iphone_compat_viewport_finds_centered_non_background_window():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[9:91, 31:69, :] = 240

    viewport = detect_iphone_compat_viewport(img)

    assert viewport is not None
    assert viewport.coordinate_space == "app_px"
    assert viewport.bbox == (31, 9, 38, 82)
    assert viewport.source == "detected"


@pytest.mark.smoke
def test_detect_iphone_compat_viewport_accepts_se_8_aspect():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[10:90, 27:72, :] = 240

    viewport = detect_iphone_compat_viewport(img)

    assert viewport is not None
    assert viewport.bbox == (27, 10, 45, 80)


@pytest.mark.smoke
def test_auto_detected_app_viewport_updates_when_window_moves():
    first = np.zeros((100, 120, 3), dtype=np.uint8)
    second = np.zeros((100, 120, 3), dtype=np.uint8)
    first[9:91, 41:79, :] = 240
    second[9:91, 47:85, :] = 240
    phone = Phone(
        source=SequenceSource([first, second]),
        ocr=ShapeOCR(),
        effector=MockEffector(),
        device_geometry=SimpleNamespace(model="ipad_mini_7"),
        app_viewport_mode="iphone_compat",
    )

    first_frame = phone.snapshot(scope="app")
    second_frame = phone.snapshot(scope="app")

    assert first_frame.shape == (38, 82)
    assert second_frame.shape == (38, 82)
    assert phone.app_viewport is not None
    assert phone.app_viewport.bbox == (47, 9, 38, 82)
    assert phone.app_viewport.source == "detected"


@pytest.mark.smoke
def test_auto_detected_app_viewport_expires_when_detection_misses():
    first = np.zeros((100, 120, 3), dtype=np.uint8)
    second = np.zeros((100, 120, 3), dtype=np.uint8)
    first[9:91, 41:79, :] = 240
    phone = Phone(
        source=SequenceSource([first, second]),
        ocr=ShapeOCR(),
        effector=MockEffector(),
        device_geometry=SimpleNamespace(model="ipad_mini_7"),
        app_viewport_mode="iphone_compat",
    )

    first_frame = phone.snapshot(scope="app")
    second_frame = phone.snapshot(scope="app")

    assert first_frame.shape == (38, 82)
    assert second_frame.shape == (120, 100)
    assert phone.app_viewport is None
