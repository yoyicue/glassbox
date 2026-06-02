from __future__ import annotations

import json

import numpy as np

from glassbox.cognition import Box, UIElement
from glassbox.perception.source import Frame
from skills.regression.ocr_vision_levers_spike import (
    collect_ocr_vision_levers_spike,
    load_expected_texts,
)


class _LeverOCR:
    def __init__(self, *, minimum_text_height=None):
        self.minimum_text_height = minimum_text_height

    def recognize(self, image):
        height, width = image.shape[:2]
        items = [
            UIElement(
                type="text",
                box=Box(x=10, y=10, w=60, h=18),
                text="WLAN",
                confidence=0.9,
            )
        ]
        if self.minimum_text_height == 0.0:
            items.append(
                UIElement(
                    type="text",
                    box=Box(x=20, y=max(0, height - 8), w=32, h=4),
                    text="Tiny",
                    confidence=0.8,
                )
            )
        if width < 100 or height < 100:
            items.append(
                UIElement(
                    type="text",
                    box=Box(x=4, y=4, w=28, h=8),
                    text="Tile",
                    confidence=0.75,
                )
            )
        return items


def _factory(**kwargs):
    return _LeverOCR(**kwargs)


def test_ocr_vision_levers_spike_reports_minheight_recovery_and_json_payload():
    frame = Frame(img=np.zeros((120, 120, 3), dtype=np.uint8), ts=1.0)

    report = collect_ocr_vision_levers_spike(
        [frame],
        frame_names=["settings_dense.png"],
        ocr_factory=_factory,
        include_tiling_arm=False,
        expected_texts=["WLAN", "Tiny"],
    )

    assert [arm.name for arm in report.arms] == ["baseline", "minimum_text_height=0"]
    comparison = report.comparisons[0]
    assert comparison.recovered_texts == {"Tiny": 1}
    assert comparison.lost_texts == {}
    assert comparison.expected_recovered_texts == ["Tiny"]
    assert comparison.expected_lost_texts == []
    assert comparison.unexpected_recovered_texts == {}
    assert comparison.offline_decision == "promote_to_rig"
    assert comparison.decision_reasons == ["expected_texts_recovered"]
    assert comparison.small_region_delta == 1
    assert report.arms[0].expected_texts_found == ["WLAN"]
    assert report.arms[0].expected_texts_missing == ["Tiny"]
    assert report.arms[1].expected_texts_found == ["WLAN", "Tiny"]
    assert report.arms[0].texts == {"WLAN": 1}
    assert report.arms[1].texts == {"Tiny": 1, "WLAN": 1}
    assert json.loads(json.dumps(report.to_dict()))["frames"] == ["settings_dense.png"]


def test_ocr_vision_levers_spike_reports_tiling_recovery():
    frame = Frame(img=np.zeros((120, 120, 3), dtype=np.uint8), ts=1.0)

    report = collect_ocr_vision_levers_spike(
        [frame],
        ocr_factory=_factory,
        include_minimum_text_height_arm=False,
        include_tiling_arm=True,
        tiling_rows=2,
        tiling_cols=2,
        tiling_overlap=0.0,
        tiling_include_full_frame=False,
        expected_texts=["Tile"],
        max_unexpected_recovered_texts=0,
    )

    assert [arm.name for arm in report.arms] == [
        "baseline",
        "tiling_2x2_overlap=0_minimum_text_height=0",
    ]
    comparison = report.comparisons[0]
    assert comparison.recovered_texts["Tile"] == 4
    assert comparison.recovered_texts["Tiny"] == 4
    assert comparison.expected_recovered_texts == ["Tile"]
    assert comparison.unexpected_recovered_texts["Tiny"] == 4
    assert comparison.offline_decision == "reject_offline"
    assert "too_many_unexpected_recoveries" in comparison.decision_reasons
    assert comparison.region_delta == 11


def test_ocr_vision_levers_spike_loads_expected_text_files(tmp_path):
    text_file = tmp_path / "expected.txt"
    text_file.write_text("# comment\nWLAN\nTiny\n", encoding="utf-8")
    json_file = tmp_path / "expected.json"
    json_file.write_text(json.dumps({"expected_texts": ["Tiny", "Tile"]}), encoding="utf-8")

    expected = load_expected_texts([text_file, json_file], ["WLAN"])

    assert expected == ["WLAN", "Tiny", "Tile"]
