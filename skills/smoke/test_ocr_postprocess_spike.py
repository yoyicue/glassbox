from __future__ import annotations

import json

from glassbox.config import AgentConfig
from skills.regression.ocr_postprocess_spike import collect_ocr_postprocess_spike


def _write_ocr(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_ocr_postprocess_spike_measures_settings_closed_set_key_changes(tmp_path):
    ocr_path = tmp_path / "view_0001.ocr.json"
    _write_ocr(
        ocr_path,
        {
            "scene_type": "settings_detail",
            "safe_actions": ["tap_root_row"],
            "evidence": ["ipad_split_view"],
            "elements": [
                {"type": "text", "text": "Bluetdoth", "box": [64, 310, 66, 16], "confidence": 1.0},
                {"type": "text", "text": "Bluetooth", "box": [64, 358, 66, 16], "confidence": 1.0},
                {"type": "text", "text": "Gereral", "box": [64, 412, 54, 14], "confidence": 1.0},
                {"type": "text", "text": "Notifications", "box": [450, 90, 120, 18], "confidence": 1.0},
            ],
            "viewport_size": [744, 1133],
        },
    )

    report = collect_ocr_postprocess_spike(
        [ocr_path],
        config=AgentConfig(language="en", region="HK", phone_model="ipad_mini_7"),
        platform="ipados",
    )

    assert report.settings_annotations == 3
    assert report.springboard_annotations == 0
    assert report.canonical_key_changes == 3
    assert report.canonical_labels_with_multiple_raw_variants == 1
    assert report.raw_variant_excess == 1
    assert report.raw_variants_by_canonical_label["蓝牙"] == {"Bluetdoth": 1, "Bluetooth": 1}
    assert report.raw_variants_by_canonical_label["通用"] == {"Gereral": 1}
    assert {example.intent_label for example in report.examples} == {"蓝牙", "通用"}


def test_ocr_postprocess_spike_measures_springboard_icon_key_changes(tmp_path):
    ocr_path = tmp_path / "view_0001.ocr.json"
    _write_ocr(
        ocr_path,
        {
            "scene_type": "springboard",
            "elements": [
                {"type": "text", "text": "口 Notes", "box": [90, 650, 70, 16], "confidence": 1.0},
                {"type": "text", "text": "Facerime", "box": [210, 650, 70, 16], "confidence": 1.0},
                {"type": "text", "text": "Settings", "box": [330, 650, 70, 16], "confidence": 1.0},
            ],
            "viewport_size": [744, 1133],
        },
    )

    report = collect_ocr_postprocess_spike(
        [ocr_path],
        config=AgentConfig(language="en", region="HK", phone_model="ipad_mini_7"),
        platform="ipados",
    )

    assert report.settings_annotations == 0
    assert report.springboard_annotations >= 2
    assert report.canonical_key_changes >= 2
    assert report.canonical_labels_with_multiple_raw_variants == 0
    assert report.raw_variant_excess == 0
    assert report.raw_variants_by_canonical_label["Notes"] == {"口 Notes": 1}
    assert report.raw_variants_by_canonical_label["FaceTime"] == {"Facerime": 1}
