"""Offline tests for the Voice Control overlay PRODUCER (A11Y-VC-1).

The producer is the flag-gated perceive() step that writes matched
``vc:item-name:<slug>`` ids into ``WhiteboxHint.accessibility_id``. Contract:

- flag OFF (default): byte-identical default path — the overlay module is not
  even imported, the scene is untouched;
- flag ON: parse runs with the dark-badge frame gate (frame_img required) and
  ONLY item names are applied — Item Numbers/Grid never enter UTG identity;
- the a11y evaluation cell carries the clean environment with
  ``voice_control_overlay: item_names``, and the floor validator keeps
  rejecting that cell from default floor promotion.
"""
from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.config import AgentConfig
from glassbox.perceptor import Perceptor
from skills.regression.computer_use_success_rate import (
    IOS_SETTINGS_A11Y_VOICE_CONTROL_ENVIRONMENT,
    IOS_SETTINGS_A11Y_VOICE_CONTROL_EVALUATION_CELL,
    IOS_SETTINGS_CLEAN_HDMI_ENVIRONMENT,
    _evaluation_environment_for_cell,
)


class _Host:
    def __init__(self, enabled: bool):
        self._enabled = enabled

    @property
    def voice_control_overlay_hints_enabled(self) -> bool:
        return self._enabled


def _perceptor(enabled: bool) -> Perceptor:
    perceptor = Perceptor.__new__(Perceptor)
    perceptor._phone = _Host(enabled)
    return perceptor


def _badge_frame(scene: Scene, badge_ids: tuple[int, ...] = (1,)) -> np.ndarray:
    """Light frame with a dark pill under the BADGE elements only, so the
    dark-badge pixel gate passes for badges and fails for plain row text."""
    img = np.full((400, 640, 3), 245, dtype=np.uint8)
    for el in scene.elements:
        if el.element_id in badge_ids:
            img[el.box.y - 4 : el.box.y + el.box.h + 4, el.box.x - 4 : el.box.x + el.box.w + 4] = 60
    return img


def _scene() -> Scene:
    return Scene(
        frame_id=1,
        timestamp=1.0,
        viewport_size=(640, 400),
        elements=[
            # badge (dark pill in the frame) above the row it names
            UIElement(text="General", type="text", box=Box(x=420, y=120, w=60, h=14), confidence=0.9, element_id=1),
            # the target row
            UIElement(text="General", type="text", box=Box(x=320, y=150, w=70, h=18), confidence=0.9, element_id=2),
            # an unrelated text-less image element
            UIElement(text="", type="image", box=Box(x=30, y=300, w=40, h=40), confidence=0.9, element_id=3),
        ],
    )


@pytest.mark.smoke
def test_flag_off_leaves_scene_untouched():
    scene = _scene()
    frame = _badge_frame(scene)
    _perceptor(False).maybe_apply_voice_control_overlay(scene, frame)
    assert all(
        not (el.whitebox_hint and el.whitebox_hint.accessibility_id) for el in scene.elements
    )


@pytest.mark.smoke
def test_flag_on_requires_frame_img():
    scene = _scene()
    _perceptor(True).maybe_apply_voice_control_overlay(scene, None)
    assert all(
        not (el.whitebox_hint and el.whitebox_hint.accessibility_id) for el in scene.elements
    )


@pytest.mark.smoke
def test_flag_on_writes_item_name_id_to_matched_target():
    scene = _scene()
    frame = _badge_frame(scene)
    _perceptor(True).maybe_apply_voice_control_overlay(scene, frame)
    ids = {el.element_id: (el.whitebox_hint.accessibility_id if el.whitebox_hint else None) for el in scene.elements}
    # the row gains the vc id; the badge itself and the unrelated image do not
    assert ids[2] == "vc:item-name:general"
    assert not ids[1]
    assert not ids[3]


@pytest.mark.smoke
def test_numbers_are_never_produced():
    """Even if the screen shows numeric badges, the producer parses item_names
    mode only — numeric/grid ids must never be written (frame-local anchors)."""
    scene = Scene(
        frame_id=1,
        timestamp=1.0,
        viewport_size=(640, 400),
        elements=[
            UIElement(text="7", type="text", box=Box(x=30, y=100, w=16, h=14), confidence=0.9, element_id=1),
            UIElement(text="WLAN", type="text", box=Box(x=60, y=100, w=60, h=16), confidence=0.9, element_id=2),
        ],
    )
    img = np.full((400, 640, 3), 245, dtype=np.uint8)
    img[94:120, 24:50] = 60  # dark pill under the digit badge
    _perceptor(True).maybe_apply_voice_control_overlay(scene, img)
    assert all(
        not (el.whitebox_hint and el.whitebox_hint.accessibility_id) for el in scene.elements
    )


@pytest.mark.smoke
def test_a11y_cell_environment_is_clean_env_with_overlay_on():
    env = _evaluation_environment_for_cell(IOS_SETTINGS_A11Y_VOICE_CONTROL_EVALUATION_CELL)
    assert env == IOS_SETTINGS_A11Y_VOICE_CONTROL_ENVIRONMENT
    assert env["voice_control_overlay"] == "item_names"
    # everything else matches the clean cell (only the overlay key differs)
    assert {k: v for k, v in env.items() if k != "voice_control_overlay"} == {
        k: v for k, v in IOS_SETTINGS_CLEAN_HDMI_ENVIRONMENT.items() if k != "voice_control_overlay"
    }
    # unknown labels still yield no environment (pinned behavior)
    assert _evaluation_environment_for_cell("nonexistent_cell") is None


@pytest.mark.smoke
def test_config_flag_defaults_off():
    assert AgentConfig(_env_file=None).voice_control_overlay_hints_enabled is False
    assert (
        AgentConfig(_env_file=None, voice_control_overlay_hints_enabled=True).voice_control_overlay_hints_enabled
        is True
    )
