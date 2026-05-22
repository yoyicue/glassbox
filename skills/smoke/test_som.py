"""skills/smoke/test_som.py

Unit tests for the visual Set-of-Mark renderer. Fully offline — synthesizes a
blank image with PIL, annotates it, and decodes the result back with cv2.

Coverage:
  - annotated output is a valid, decodable PNG of the same dimensions
  - elements with a missing / malformed box are skipped, never crash
  - an undecodable image is returned unchanged (best-effort, never fatal)
  - empty element list → valid image, no marks
"""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

from glassbox.cognition.som import render_set_of_mark


def _blank_png(w: int = 400, h: int = 600) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _decode(png: bytes):
    import cv2
    return cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)


@pytest.mark.smoke
def test_render_returns_valid_png_same_size():
    src = _blank_png(400, 600)
    out = render_set_of_mark(src, [
        {"id": 0, "box": [20, 20, 200, 60]},
        {"id": 1, "box": [20, 100, 380, 160]},
    ])
    img = _decode(out)
    assert img is not None
    assert img.shape[:2] == (600, 400)


@pytest.mark.smoke
def test_render_draws_something():
    """A marked image must differ from the blank source (red pixels added)."""
    src = _blank_png()
    out = render_set_of_mark(src, [{"id": 7, "box": [10, 10, 100, 50]}])
    assert _decode(out) is not None
    assert out != src


@pytest.mark.smoke
@pytest.mark.parametrize("bad", [
    {"id": 0},                          # no box
    {"id": 1, "box": None},
    {"id": 2, "box": [1, 2, 3]},         # wrong arity
    {"id": 3, "box": "nope"},
    {"id": 4, "box": [0, 0, 0, 0]},      # degenerate
    {"id": 5, "box": ["a", "b", "c", "d"]},  # non-numeric
])
def test_render_skips_malformed_boxes(bad):
    out = render_set_of_mark(_blank_png(), [bad])
    assert _decode(out) is not None


@pytest.mark.smoke
def test_render_empty_elements_ok():
    src = _blank_png()
    out = render_set_of_mark(src, [])
    assert _decode(out) is not None


@pytest.mark.smoke
def test_render_undecodable_image_returned_unchanged():
    junk = b"not an image"
    assert render_set_of_mark(junk, [{"id": 0, "box": [1, 1, 9, 9]}]) is junk


@pytest.mark.smoke
def test_render_box_outside_bounds_clamped():
    """A box larger than the image must be clamped, not crash."""
    out = render_set_of_mark(_blank_png(100, 100), [{"id": 0, "box": [-50, -50, 999, 999]}])
    assert _decode(out) is not None
