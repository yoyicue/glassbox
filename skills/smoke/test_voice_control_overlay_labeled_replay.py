from __future__ import annotations

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.cognition.voice_control_overlay import VoiceControlOverlayMarker
from skills.regression.voice_control_overlay_labeled_replay import (
    VoiceControlOverlayReplayLabel,
    VoiceControlOverlayReplayLabelSet,
    evaluate_voice_control_overlay_labels,
)


def _el(
    text: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    element_id: int,
) -> UIElement:
    return UIElement(
        type="text",
        box=Box(x=x, y=y, w=w, h=h),
        text=text,
        confidence=0.9,
        element_id=element_id,
    )


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=1, timestamp=1.0, elements=list(elements))


def _marker(
    text: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    source_element_id: int,
    accessibility_id: str,
) -> VoiceControlOverlayMarker:
    return VoiceControlOverlayMarker(
        kind="item_name",
        text=text,
        box=Box(x=x, y=y, w=w, h=h),
        confidence=0.9,
        source_element_id=source_element_id,
        accessibility_id=accessibility_id,
    )


@pytest.mark.smoke
def test_labeled_replay_reports_item_name_mapping_pass():
    target = _el("Wallpaper", x=64, y=442, w=70, h=16, element_id=33)
    badge = _el("Wallpaper)", x=98, y=468, w=64, h=18, element_id=34)
    marker = _marker(
        "Wallpaper)",
        x=98,
        y=468,
        w=64,
        h=18,
        source_element_id=34,
        accessibility_id="vc:item-name:wallpaper",
    )
    label_set = VoiceControlOverlayReplayLabelSet(
        labels=[
            VoiceControlOverlayReplayLabel(
                name="sidebar_wallpaper",
                marker_text="Wallpaper",
                marker_center=marker.center,
                target_text="Wallpaper",
                target_center=target.box.center,
            )
        ]
    )

    report = evaluate_voice_control_overlay_labels(
        _scene(target, badge),
        [marker],
        label_set,
    )

    assert report.total == 1
    assert report.passed == 1
    assert report.failed == 0
    assert report.cases[0].reason == "matched"
    assert report.cases[0].actual_element_id == 33


@pytest.mark.smoke
def test_labeled_replay_reports_target_text_mismatch():
    target = _el("Wallpaper", x=64, y=442, w=70, h=16, element_id=33)
    badge = _el("Wallpaper)", x=98, y=468, w=64, h=18, element_id=34)
    marker = _marker(
        "Wallpaper)",
        x=98,
        y=468,
        w=64,
        h=18,
        source_element_id=34,
        accessibility_id="vc:item-name:wallpaper",
    )
    label_set = VoiceControlOverlayReplayLabelSet(
        labels=[
            VoiceControlOverlayReplayLabel(
                marker_text="Wallpaper",
                marker_center=marker.center,
                target_text="Notifications",
            )
        ]
    )

    report = evaluate_voice_control_overlay_labels(
        _scene(target, badge),
        [marker],
        label_set,
    )

    assert report.failed == 1
    assert report.cases[0].reason == "target_text_mismatch"
    assert report.cases[0].actual_target_text == "Wallpaper"


@pytest.mark.smoke
def test_labeled_replay_reports_expected_unmapped_pass():
    dictate = _marker(
        "Dictate",
        x=192,
        y=78,
        w=46,
        h=12,
        source_element_id=2,
        accessibility_id="vc:item-name:dictate",
    )
    search = _el("Search", x=36, y=90, w=70, h=16, element_id=3)
    label_set = VoiceControlOverlayReplayLabelSet(
        labels=[
            VoiceControlOverlayReplayLabel(
                marker_text="Dictate",
                marker_center=dictate.center,
                expect_mapped=False,
            )
        ]
    )

    report = evaluate_voice_control_overlay_labels(
        _scene(search),
        [dictate],
        label_set,
    )

    assert report.passed == 1
    assert report.cases[0].reason == "unmapped_as_expected"
