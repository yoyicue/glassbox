from __future__ import annotations

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


class ShapeOCR:
    def __init__(self):
        self.shapes: list[tuple[int, int]] = []

    def recognize(self, img):
        self.shapes.append((img.shape[1], img.shape[0]))
        return []


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
