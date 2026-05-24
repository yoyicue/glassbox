from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings import scene_state as settings_scene_state


def _el(text: str, x: int, y: int, w: int = 80, h: int = 20, *, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


class _Phone:
    def __init__(self, *, kimi=None):
        self.kimi = kimi
        self._last_frame = SimpleNamespace(img=np.zeros((80, 80, 3), dtype=np.uint8))

    def _viewport_size(self):
        return 448, 973


class _FakeKimi:
    def __init__(self, kind: str):
        self.kind = kind
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(parsed={"scene_kind": self.kind}, raw_content="")


@pytest.mark.smoke
def test_settings_scene_kind_uses_recent_row_tap_transition_prior():
    settings_scene_state.reset_scene_context_state()
    scene = _scene(_el("Loading", 160, 320, w=90))
    phone = _Phone(kimi=None)
    settings_scene_state.record_settings_row_tap(phone, "Bluetooth")

    assert settings_scene_state.scene_kind(scene, phone=phone) == "settings_detail"
    assert scene.scene_type == "settings_detail"
    assert scene.classification_source == "transition"
    assert "settings.tap_row_prior" in scene.classification_evidence


@pytest.mark.smoke
def test_settings_scene_kind_transition_prior_respects_strong_home_evidence():
    settings_scene_state.reset_scene_context_state()
    scene = _scene(
        _el("FaceTime", 54, 400, w=90),
        _el("Calendar", 164, 400, w=78),
        _el("Photos", 276, 400, w=64),
        _el("Camera", 386, 400, w=68),
        _el("Notes", 54, 510, w=54),
        _el("Clock", 164, 510, w=54),
        _el("Settings", 164, 620, w=72),
        _el("Q Search", 198, 900, w=82),
    )
    phone = _Phone(kimi=None)
    settings_scene_state.record_settings_row_tap(phone, "Bluetooth")

    assert settings_scene_state.scene_kind(scene, phone=phone) == "springboard"
    assert scene.platform_scene_kind is None
    assert phone._ios_settings_scene_classifications[-1]["override"] is False


@pytest.mark.smoke
def test_settings_scene_kind_vlm_verifier_can_confirm_transition_detail():
    settings_scene_state.reset_scene_context_state()
    scene = _scene(_el("Loading", 160, 320, w=90))
    kimi = _FakeKimi("settings_detail")
    phone = _Phone(kimi=kimi)
    settings_scene_state.record_settings_row_tap(phone, "Bluetooth")

    assert settings_scene_state.scene_kind(scene, phone=phone) == "settings_detail"
    assert settings_scene_state.scene_kind(scene, phone=phone) == "settings_detail"
    assert kimi.calls == 1
    assert scene.classification_source == "vlm"
    assert "vlm:settings_detail" in scene.classification_evidence


@pytest.mark.smoke
def test_settings_scene_kind_vlm_verifier_can_reject_transition_detail():
    settings_scene_state.reset_scene_context_state()
    scene = _scene(_el("Loading", 160, 320, w=90))
    kimi = _FakeKimi("springboard")
    phone = _Phone(kimi=kimi)
    settings_scene_state.record_settings_row_tap(phone, "Bluetooth")

    assert settings_scene_state.scene_kind(scene, phone=phone) == "unknown"
    assert kimi.calls == 1
    assert scene.platform_scene_kind is None
    assert phone._ios_settings_scene_classifications[-1]["source"] == "vlm"
    assert phone._ios_settings_scene_classifications[-1]["override"] is False
