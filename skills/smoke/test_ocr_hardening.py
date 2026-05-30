"""skills/smoke/test_ocr_hardening.py — live-camera OCR hardening.

A live camera preview (e.g. the 操作按钮 Action-Button carousel) makes OCR emit
chaotic, high-volume text; feeding that to every downstream scene/text regex is
what once stalled perceive (a rare regex hang inside OCR text handling). Two
defenses, both anchored at the OCR→element chokepoint in Phone:

  - input bounding (default-on, generous): cap element count + per-element text
    length so no real iOS screen is affected while pathological frames are clipped
  - recognize() watchdog (opt-in, ocr_timeout>0): time-box one OCR call so a hang
    yields an empty scene (→ unknown → recovery) instead of blocking

Fully offline; no hardware.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from glassbox.cognition import Box, UIElement
from glassbox.effector import MockEffector
from glassbox.perception.source import Frame
from glassbox.phone import Phone


def _frame(value: int = 0) -> Frame:
    return Frame(img=np.full((100, 100, 3), value, dtype=np.uint8), ts=0.0)


class _Source:
    resolution = (100, 100)

    def snapshot(self):
        return _frame()

    def close(self):
        pass


class _ListOCR:
    """Returns a fixed element list; counts calls."""

    def __init__(self, elements: list[UIElement]):
        self.elements = elements
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return list(self.elements)


class _SleepOCR:
    """Blocks for `delay` seconds before returning (simulates a hung recognize)."""

    def __init__(self, delay: float, elements: list[UIElement] | None = None):
        self.delay = delay
        self.elements = elements or []
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        time.sleep(self.delay)
        return list(self.elements)


class _RaiseOCR:
    def recognize(self, image):
        raise RuntimeError("boom")


def _el(i: int, text: str = "x") -> UIElement:
    return UIElement(
        type="text", box=Box(x=0, y=i, w=10, h=10),
        text=text, confidence=0.9, element_id=i,
    )


def _phone(ocr, **kw) -> Phone:
    return Phone(source=_Source(), ocr=ocr, effector=MockEffector(), **kw)


# ─── input bounding ──────────────────────────────────────────────────
@pytest.mark.smoke
def test_bounding_is_noop_on_normal_frame():
    ocr = _ListOCR([_el(i) for i in range(5)])
    phone = _phone(ocr)
    out = phone._recognize_elements(_frame())
    assert len(out) == 5
    assert [e.text for e in out] == ["x"] * 5


@pytest.mark.smoke
def test_element_count_cap_clips_pathological_frame():
    ocr = _ListOCR([_el(i) for i in range(1000)])
    phone = _phone(ocr, max_ocr_elements=10)
    out = phone._recognize_elements(_frame())
    assert len(out) == 10
    # kept the first N in OCR order
    assert [e.element_id for e in out] == list(range(10))


@pytest.mark.smoke
def test_default_element_cap_is_generous_but_active():
    # 801 > the default cap of 800 → clipped; 800 normal-frame elements pass.
    phone = _phone(_ListOCR([_el(i) for i in range(801)]))
    assert len(phone._recognize_elements(_frame())) == 800


@pytest.mark.smoke
def test_per_element_text_is_truncated():
    huge = "a" * 5000
    ocr = _ListOCR([_el(0, text=huge), _el(1, text="short")])
    phone = _phone(ocr, max_ocr_text_chars=64)
    out = phone._recognize_elements(_frame())
    assert len(out[0].text) == 64
    assert out[1].text == "short"  # untouched


@pytest.mark.smoke
def test_caps_disabled_with_zero():
    ocr = _ListOCR([_el(i, text="a" * 100) for i in range(50)])
    phone = _phone(ocr, max_ocr_elements=0, max_ocr_text_chars=0)
    out = phone._recognize_elements(_frame())
    assert len(out) == 50
    assert len(out[0].text) == 100


# ─── recognize() watchdog ────────────────────────────────────────────
@pytest.mark.smoke
def test_watchdog_disabled_by_default_passes_through():
    # ocr_timeout defaults to 0 → no thread, recognize result returned verbatim.
    ocr = _ListOCR([_el(0), _el(1)])
    phone = _phone(ocr)  # default ocr_timeout=0.0
    out = phone._recognize_elements(_frame())
    assert len(out) == 2
    assert ocr.calls == 1


@pytest.mark.smoke
def test_watchdog_returns_empty_on_timeout_without_blocking():
    ocr = _SleepOCR(delay=2.0, elements=[_el(0)])
    phone = _phone(ocr, ocr_timeout=0.1)
    start = time.monotonic()
    out = phone._recognize_elements(_frame())
    elapsed = time.monotonic() - start
    assert out == []                 # empty → scene classifies unknown → recovery
    assert elapsed < 1.0             # gave up at the watchdog, did not wait 2s


@pytest.mark.smoke
def test_watchdog_passes_through_fast_ocr():
    ocr = _SleepOCR(delay=0.0, elements=[_el(0), _el(1), _el(2)])
    phone = _phone(ocr, ocr_timeout=2.0)
    out = phone._recognize_elements(_frame())
    assert len(out) == 3


@pytest.mark.smoke
def test_watchdog_reraises_ocr_error():
    phone = _phone(_RaiseOCR(), ocr_timeout=2.0)
    with pytest.raises(RuntimeError, match="boom"):
        phone._recognize_elements(_frame())
