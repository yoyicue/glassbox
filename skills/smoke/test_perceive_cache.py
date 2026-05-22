"""skills/smoke/test_perceive_cache.py — tests for Phone.perceive's frame diff cache.

Fully offline. A FakeOCR counts calls and we verify:
  - repeated perceive on the same frame → cache hit, OCR runs only once
  - a significantly different frame → cache miss
  - invalidate_perceive_cache forces a refresh
  - perceive_cache_diff=0 disables the cache entirely
  - frame_id / timestamp are updated even on a hit
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from glassbox.cognition import Box, KimiResponse, UIElement
from glassbox.cognition.heuristic import HeuristicTyper
from glassbox.effector import MockEffector
from glassbox.obs import Recorder
from glassbox.obs.recorder import iter_events
from glassbox.perception.source import Frame
from glassbox.perception.stable import StabilityPolicy
from glassbox.phone import Phone


class CountingOCR:
    """Counts each recognize call; returns a controllable set of elements."""

    def __init__(self):
        self.calls = 0
        self.elements: list[UIElement] = [
            UIElement(type="text", box=Box(x=10, y=10, w=20, h=10),
                      text="hello", confidence=0.9, element_id=0),
        ]

    def recognize(self, image):
        self.calls += 1
        return list(self.elements)


class StepSource:
    """Each snapshot returns frames[i]; i increments and then holds at the list's end."""

    def __init__(self, frames):
        self.frames = frames
        self.i = 0
        self.resolution = (frames[0].img.shape[1], frames[0].img.shape[0])

    def snapshot(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        # also update ts each time (simulating the actual grab-a-frame time)
        return Frame(img=f.img, ts=time.monotonic())

    def close(self):
        pass


def _frame(value=0):
    """Build a 100x100 BGR frame as a single solid color block."""
    return Frame(img=np.full((100, 100, 3), value, dtype=np.uint8), ts=0.0)


def _make_phone(frames):
    ocr = CountingOCR()
    src = StepSource(frames)
    eff = MockEffector()
    return Phone(source=src, ocr=ocr, effector=eff), ocr


# ─── tests ───────────────────────────────────────────────────────────
@pytest.mark.smoke
def test_cache_hit_same_frame():
    """Running the same frame twice in a row calls OCR only once."""
    frame = _frame(80)
    phone, ocr = _make_phone([frame, frame])
    s1 = phone.perceive()
    time.sleep(0.002)   # spread out monotonic so frame_id differs
    s2 = phone.perceive()
    assert ocr.calls == 1
    assert phone.perceive_cache_stats == {"hits": 1, "misses": 1}
    # on a cache hit, frame_id / timestamp should follow the fresh frame, not reuse the cached one
    assert s2.timestamp >= s1.timestamp
    assert s1.elements == s2.elements   # same content


@pytest.mark.smoke
def test_cache_miss_different_frame():
    """A significantly different frame → cache miss, OCR reruns."""
    f1 = _frame(0)
    f2 = _frame(200)
    phone, ocr = _make_phone([f1, f2])
    phone.perceive()
    phone.perceive()
    assert ocr.calls == 2
    assert phone.perceive_cache_stats == {"hits": 0, "misses": 2}


@pytest.mark.smoke
def test_invalidate_forces_re_ocr():
    frame = _frame(100)
    phone, ocr = _make_phone([frame, frame, frame])
    phone.perceive()
    phone.invalidate_perceive_cache()
    phone.perceive()
    phone.perceive()
    # first miss, then a second miss after invalidate, third is a hit
    assert ocr.calls == 2
    assert phone.perceive_cache_stats == {"hits": 1, "misses": 2}


@pytest.mark.smoke
def test_cache_disabled_with_threshold_zero():
    frame = _frame(60)
    phone, ocr = _make_phone([frame, frame, frame])
    phone.perceive_cache_diff = 0.0
    phone.perceive()
    phone.perceive()
    phone.perceive()
    assert ocr.calls == 3
    assert phone.perceive_cache_stats["hits"] == 0


@pytest.mark.smoke
def test_perceive_waits_for_stable_frame_after_action(tmp_path):
    class MeanOCR(CountingOCR):
        def __init__(self):
            super().__init__()
            self.means: list[int] = []

        def recognize(self, image):
            self.means.append(int(image.mean()))
            return super().recognize(image)

    frames = [_frame(0), _frame(40), _frame(80), _frame(80)]
    ocr = MeanOCR()
    phone = Phone(
        source=StepSource(frames),
        ocr=ocr,
        effector=MockEffector(),
        recorder=Recorder(tmp_path),
        stability_policy=StabilityPolicy(
            enabled=True,
            timeout=1.0,
            consecutive=1,
            poll_interval=0.0,
        ),
    )

    phone.perceive()
    phone.tap_xy(1, 1)
    scene = phone.perceive()
    phone.recorder.close()

    assert ocr.means == [0, 80]
    assert scene.observation_mode == "stable"
    assert scene.stable_frame is True
    scene_events = [e for e in iter_events(tmp_path) if e["type"] == "scene"]
    assert scene_events[-1]["observation_mode"] == "stable"
    assert scene_events[-1]["stable_frame"] is True


@pytest.mark.smoke
def test_cache_returns_typed_scene():
    """Heuristic typing should be preserved on a cache hit too."""
    f = _frame(70)
    phone, _ocr = _make_phone([f, f])
    # give it a typer to ensure the cache does not lose type
    phone.typer = HeuristicTyper(frame_size=(100, 100))
    s1 = phone.perceive()
    types_before = [e.type for e in s1.elements]
    s2 = phone.perceive()
    types_after = [e.type for e in s2.elements]
    assert types_before == types_after


@pytest.mark.smoke
def test_cache_handles_shape_change():
    """The frame size changed (device switch / crop changed) → must miss."""
    f_small = Frame(img=np.zeros((50, 50, 3), dtype=np.uint8), ts=0.0)
    f_big = Frame(img=np.zeros((100, 100, 3), dtype=np.uint8), ts=0.0)
    phone, ocr = _make_phone([f_small, f_big])
    phone.perceive()
    phone.perceive()
    assert ocr.calls == 2


@pytest.mark.smoke
def test_mutating_returned_scene_does_not_poison_cache():
    frame = _frame(90)
    phone, _ocr = _make_phone([frame, frame])
    s1 = phone.perceive()
    s1.elements[0].intent_label = "确认登录"

    s2 = phone.perceive()

    assert s2.elements[0].intent_label is None


@pytest.mark.smoke
def test_mutating_cache_hit_scene_does_not_poison_cache():
    frame = _frame(90)
    phone, _ocr = _make_phone([frame, frame, frame])
    phone.perceive()
    hit = phone.perceive()
    hit.elements[0].intent_label = "确认登录"

    next_hit = phone.perceive()

    assert next_hit.elements[0].intent_label is None


@pytest.mark.smoke
def test_describe_after_cache_hit_persists_top_level_layer3_fields():
    class FakeKimi:
        model = "fake"

        def describe_scene(self, *, frame_image, elements, scene_hint=None):
            return KimiResponse(
                raw_content="{}",
                parsed={
                    "scene_type": "login_form",
                    "app_state": {"auth": "logged_out"},
                    "elements": [{"id": 0, "intent_label": "确认登录"}],
                },
                usage={},
                model="fake",
                elapsed_ms=1,
            )

    frame = _frame(90)
    phone, _ocr = _make_phone([frame, frame, frame])
    phone.kimi = FakeKimi()
    phone.perceive()   # miss: cache_scene has no Layer 3 fields yet
    phone.perceive()   # hit: _last_scene is a model_copy of cache_scene

    described = phone.describe()
    assert described.scene_type == "login_form"
    assert described.app_state == {"auth": "logged_out"}

    cached = phone.perceive()
    assert cached.scene_type == "login_form"
    assert cached.app_state == {"auth": "logged_out"}
    assert cached.elements[0].intent_label == "确认登录"
