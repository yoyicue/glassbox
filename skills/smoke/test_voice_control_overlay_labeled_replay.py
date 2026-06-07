from __future__ import annotations

import re
from pathlib import Path

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.cognition.voice_control_overlay import VoiceControlOverlayMarker
from skills.regression.voice_control_overlay_labeled_replay import (
    VoiceControlOverlayReplayLabel,
    VoiceControlOverlayReplayLabelSet,
    evaluate_voice_control_overlay_labels,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ITEM_NAMES_LABELS = (
    REPO_ROOT
    / "skills"
    / "regression"
    / "fixtures"
    / "voice_control_overlay_itemnames_labels_v1.json"
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


def _box_from_center(center: tuple[int, int], *, text: str, height: int = 16) -> Box:
    width = max(24, min(140, len(text) * 8))
    return Box(
        x=int(center[0] - width / 2),
        y=int(center[1] - height / 2),
        w=width,
        h=height,
    )


def _item_name_accessibility_id(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "-", text.lower()).strip("-")
    return f"vc:item-name:{slug or 'label'}"


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


@pytest.mark.smoke
def test_committed_item_names_fixture_replays_against_labeled_mapping_contract():
    label_set = VoiceControlOverlayReplayLabelSet.model_validate_json(
        ITEM_NAMES_LABELS.read_text(encoding="utf-8")
    )
    elements: list[UIElement] = []
    markers: list[VoiceControlOverlayMarker] = []
    next_id = 1
    for label in label_set.labels:
        marker_center = label.marker_center
        assert marker_center is not None, f"{label.name or label.marker_text} lacks marker_center"
        marker_box = _box_from_center(marker_center, text=label.marker_text)
        markers.append(
            VoiceControlOverlayMarker(
                kind="item_name",
                text=label.marker_text,
                box=marker_box,
                confidence=0.9,
                source_element_id=10_000 + next_id,
                accessibility_id=_item_name_accessibility_id(label.marker_text),
            )
        )
        if label.expect_mapped:
            assert label.target_text is not None
            assert label.target_center is not None
            target_box = _box_from_center(label.target_center, text=label.target_text)
            elements.append(
                UIElement(
                    type="text",
                    box=target_box,
                    text=label.target_text,
                    confidence=0.9,
                    element_id=next_id,
                )
            )
            next_id += 1

    report = evaluate_voice_control_overlay_labels(
        Scene(frame_id=1, timestamp=1.0, elements=elements),
        markers,
        label_set,
    )

    assert report.total == 12
    assert report.failed == 0
    assert report.passed == report.total
