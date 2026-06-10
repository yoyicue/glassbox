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

import json
from pathlib import Path

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
def test_flag_on_writes_item_name_id_and_subtracts_the_badge():
    scene = _scene()
    frame = _badge_frame(scene)
    _perceptor(True).maybe_apply_voice_control_overlay(scene, frame)
    ids = {el.element_id: (el.whitebox_hint.accessibility_id if el.whitebox_hint else None) for el in scene.elements}
    # the row gains the vc id; the unrelated image is untouched
    assert ids[2] == "vc:item-name:general"
    assert not ids[3]
    # the badge OCR artifact is SUBTRACTED from the element stream (overlay
    # layer vs content layer): downstream row matching / verifiers / signatures
    # must not see the duplicate text.
    assert 1 not in ids
    assert len(scene.elements) == 2


@pytest.mark.smoke
def test_unmatched_badges_are_also_subtracted():
    """A badge with no text target (e.g. the Dictate pill) is still an overlay
    artifact — it must leave the element stream even though nothing gains an id."""
    scene = Scene(
        frame_id=1,
        timestamp=1.0,
        viewport_size=(640, 400),
        elements=[
            UIElement(text="Dictate", type="text", box=Box(x=420, y=120, w=50, h=14), confidence=0.9, element_id=1),
            UIElement(text="Battery", type="text", box=Box(x=80, y=300, w=70, h=18), confidence=0.9, element_id=2),
        ],
    )
    frame = _badge_frame(scene)  # dark pill under element 1 only
    _perceptor(True).maybe_apply_voice_control_overlay(scene, frame)
    remaining = [el.element_id for el in scene.elements]
    assert remaining == [2]


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


_A11Y_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "regression"
    / "fixtures"
    / "a11y_voice_control_cell_snapshot.json"
)


@pytest.mark.smoke
def test_committed_a11y_cell_snapshot_is_labeled_scrubbed_and_honest():
    """The a11y-cell snapshot must stay what it claims to be: the overlay-ON
    cell (correct label + environment), scrubbed (no raw OCR dumps), and
    honest (it records the overlay's measured COST — it must never quietly
    morph into a success story or a floor candidate)."""
    if not _A11Y_SNAPSHOT.exists():
        pytest.skip("no committed a11y cell snapshot yet")
    payload = json.loads(_A11Y_SNAPSHOT.read_text(encoding="utf-8"))
    raw = _A11Y_SNAPSHOT.read_text(encoding="utf-8")

    from skills.regression.computer_use_success_rate import validate_benchmark

    assert validate_benchmark(payload) == []
    assert payload["config"]["evaluation_cell"] == IOS_SETTINGS_A11Y_VOICE_CONTROL_EVALUATION_CELL
    assert payload["config"]["environment"] == IOS_SETTINGS_A11Y_VOICE_CONTROL_ENVIRONMENT
    assert payload["config"]["rounds"] >= 5
    assert len(payload["tasks"]) >= 5
    # scrubbed like the L2 snapshot
    assert all((t.get("final_state") or {}).get("visible_texts") == [] for t in payload["tasks"])
    assert all("elements" not in (t.get("final_state") or {}) for t in payload["tasks"])
    for forbidden in ("Da Li", "Apple Account and password"):
        assert forbidden not in raw
    # honest-coverage invariant: the run exercised the semantic path for real.
    # (Loop-1's baseline had strategy_switches=21/recoveries=7 because the
    # machinery was rescuing a collapsing run; loop-2's badge-aware perception
    # made rescue unnecessary — recoveries=0 is an honest zero, so the guard
    # asserts the expected-state path only, not rescue counts.)
    assert payload["metrics"]["expected_state_coverage"] > 0
    # the cell's reason to exist: its completion must be tracked honestly
    assert "task_completion_rate" in payload["metrics"]
