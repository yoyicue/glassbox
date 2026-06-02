from __future__ import annotations

import json

import numpy as np

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.icon_detect import IconRegion
from skills.regression.ui_layout_segmentation_spike import (
    UiLayoutSpikeCase,
    collect_ui_layout_segmentation_spike,
    derive_frame_path,
    load_expected_texts,
)


def _scene(*elements: UIElement, size: tuple[int, int] = (440, 956)) -> Scene:
    return Scene(frame_id=1, timestamp=0.0, elements=list(elements), viewport_size=size)


def _text(
    text: str,
    *,
    x: int = 88,
    y: int = 252,
    w: int = 120,
    h: int = 20,
) -> UIElement:
    return UIElement(
        type="text",
        box=Box(x=x, y=y, w=w, h=h),
        text=text,
        confidence=0.9,
    )


def _image(
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    confidence: float = 0.9,
) -> UIElement:
    return UIElement(
        type="image",
        box=Box(x=x, y=y, w=w, h=h),
        text=None,
        confidence=confidence,
    )


def test_ui_layout_segmentation_spike_promotes_clean_actionable_recovery():
    frame = np.zeros((956, 440, 3), dtype=np.uint8)
    case = UiLayoutSpikeCase(
        name="settings_row",
        scene=_scene(_text("WLAN")),
        frame_img=frame,
    )

    report = collect_ui_layout_segmentation_spike(
        [case],
        expected_texts=["WLAN"],
        icon_detector=lambda _img, **_kwargs: [IconRegion(box=(52, 250, 24, 24))],
        max_no_text_actionables=0,
        max_unexpected_actionable_texts=0,
    )

    result = report.cases[0]
    assert result.icons_detected == 1
    assert result.baseline.expected_texts_found == ["WLAN"]
    assert result.baseline.expected_actionable_texts_found == []
    assert result.candidate.expected_actionable_texts_found == ["WLAN"]
    assert result.expected_actionable_recovered == ["WLAN"]
    assert result.candidate.no_text_actionable_count == 0
    assert result.unexpected_actionable_texts == {}
    assert result.offline_decision == "promote_to_rig"
    assert result.decision_reasons == ["expected_actionables_recovered"]


def test_ui_layout_segmentation_spike_rejects_no_text_actionable_noise():
    frame = np.zeros((956, 440, 3), dtype=np.uint8)
    case = UiLayoutSpikeCase(
        name="settings_row_with_noise",
        scene=_scene(
            _text("WLAN"),
            _image(x=340, y=620, w=28, h=28, confidence=0.9),
        ),
        frame_img=frame,
    )

    report = collect_ui_layout_segmentation_spike(
        [case],
        expected_texts=["WLAN"],
        icon_detector=lambda _img, **_kwargs: [
            IconRegion(box=(52, 250, 24, 24)),
        ],
        max_no_text_actionables=0,
        max_unexpected_actionable_texts=0,
    )

    result = report.cases[0]
    assert result.candidate.expected_actionable_texts_found == ["WLAN"]
    assert result.candidate.no_text_actionable_count == 1
    assert result.offline_decision == "reject_offline"
    assert "too_many_no_text_actionables" in result.decision_reasons


def test_ui_layout_segmentation_spike_suppresses_unpaired_low_confidence_detector_icons():
    frame = np.zeros((956, 440, 3), dtype=np.uint8)
    case = UiLayoutSpikeCase(
        name="settings_row_with_detector_noise",
        scene=_scene(_text("WLAN")),
        frame_img=frame,
    )

    report = collect_ui_layout_segmentation_spike(
        [case],
        expected_texts=["WLAN"],
        icon_detector=lambda _img, **_kwargs: [
            IconRegion(box=(52, 250, 24, 24)),
            IconRegion(box=(340, 620, 28, 28)),
        ],
        max_no_text_actionables=0,
        max_unexpected_actionable_texts=0,
    )

    result = report.cases[0]
    assert result.candidate.expected_actionable_texts_found == ["WLAN"]
    assert result.candidate.no_text_actionable_count == 0
    assert result.offline_decision == "promote_to_rig"


def test_ui_layout_segmentation_spike_loads_expected_texts_and_derives_frame_path(tmp_path):
    text_file = tmp_path / "expected.txt"
    text_file.write_text("# comment\nWLAN\nBluetooth\n", encoding="utf-8")
    json_file = tmp_path / "expected.json"
    json_file.write_text(json.dumps({"expected_texts": ["Bluetooth", "General"]}), encoding="utf-8")

    expected = load_expected_texts([text_file, json_file], ["WLAN"])

    assert expected == ["WLAN", "Bluetooth", "General"]
    assert derive_frame_path(tmp_path / "run" / "scenes" / "scn_000042.json") == (
        tmp_path / "run" / "frames" / "frm_000042.png"
    )
