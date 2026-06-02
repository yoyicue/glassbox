from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from glassbox.memory.schema import UTG, ScreenEdge, ScreenNode, ScreenSignature
from skills.regression.ios_settings.ab_extract import main as ab_extract_main


def _utg() -> UTG:
    root = ScreenNode(
        screen_id="scr_root",
        page_id="settings/root",
        platform_scene_kind="settings_root",
        signature=ScreenSignature(
            stable_texts=["settings", "bluetooth"],
            type_histogram={"settings_root": 1},
        ),
    )
    detail = ScreenNode(
        screen_id="scr_bluetooth",
        page_id="settings/Bluetooth",
        platform_scene_kind="settings_detail",
        signature=ScreenSignature(
            stable_texts=["settings/bluetooth"],
            type_histogram={"settings_detail": 1},
        ),
    )
    return UTG(
        bundle_id="com.apple.Preferences",
        nodes={root.screen_id: root, detail.screen_id: detail},
        edges=[
            ScreenEdge(
                from_id=root.screen_id,
                to_id=detail.screen_id,
                action_op="tap",
                policy_action="tap_root_row",
                count=1,
                success_count=1,
                success_rate=1.0,
            ),
            ScreenEdge(
                from_id=detail.screen_id,
                to_id=root.screen_id,
                action_op="back",
                policy_action="back",
                count=1,
                success_count=1,
                success_rate=1.0,
            ),
        ],
    )


def _write_good_report(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "com.apple.Preferences.json").write_text(
        json.dumps(_utg().model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "locale": "en-HK",
                "visit_count": 3,
                "config": {
                    "memory_dir": str(memory_dir),
                    "phone_model": "ipad_mini_7",
                    "platform": "ipados",
                    "language": "en",
                    "region": "HK",
                    "ocr": "vision",
                    "text_detector": "vision",
                    "en_ocr_correction": False,
                    "ios_closed_set_canonicalization_enabled": False,
                    "ocr_minimum_text_height": 0.0,
                    "ocr_tiling_enabled": True,
                    "ocr_tiling_rows": 2,
                    "ocr_tiling_cols": 2,
                    "ocr_tiling_overlap": 0.15,
                    "ocr_tiling_include_full_frame": True,
                    "ocr_tiling_nms_iou": 0.55,
                    "ui_layout_segmentation_enabled": True,
                    "detect_icons_in_perceive": False,
                },
                "metrics": {
                    "exception_hit": False,
                    "navigation_success_proxy_rate": 1.0,
                    "hid_no_progress_count": 2,
                    "root_expected_count": 17,
                    "root_required_expected_count": 12,
                    "root_sidebar_exhaustive": True,
                },
                "root_coverage": {
                    "entered_graph": ["蓝牙"],
                    "entered": ["蓝牙", "通知"],
                    "required_missing": [],
                    "missing": ["通知"],
                    "sidebar_absent": ["通知"],
                    "entry_exempt": ["通知"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report_path


def _run(argv, capsys):
    code = ab_extract_main(argv)
    captured = capsys.readouterr()
    assert code == 0
    lines = captured.out.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


@pytest.mark.smoke
def test_ab_extract_emits_one_complete_line_for_good_report(tmp_path, capsys):
    report_path = _write_good_report(tmp_path)

    row = _run(["B", "1", "en-HK", "0", str(report_path), "ipad_mini_7", "ipados"], capsys)

    assert "extraction_error" not in row
    assert row["arm"] == "B"
    assert row["round"] == 1
    assert row["locale"] == "en-HK"
    assert row["device"] == "ipad_mini_7"
    assert row["platform"] == "ipados"
    assert row["crash"] is False
    assert row["task_completion"] is True
    assert row["entered_graph"] == 1
    assert row["entered"] == 2
    assert row["entered_labels"] == ["蓝牙", "通知"]
    assert row["sidebar_absent"] == ["通知"]
    assert row["entry_exempt"] == ["通知"]
    assert row["root_nodes"] == 1
    assert row["root_sigs"] == 1
    assert row["root_to_detail"] == 1
    assert row["detail_to_root"] == 1
    assert row["cfg_phone_model"] == "ipad_mini_7"
    assert row["cfg_platform"] == "ipados"
    assert row["cfg_language"] == "en"
    assert row["cfg_region"] == "HK"
    assert row["cfg_ocr"] == "vision"
    assert row["cfg_text_detector"] == "vision"
    assert row["cfg_en_ocr_correction"] is False
    assert row["cfg_ios_closed_set_canonicalization_enabled"] is False
    assert row["cfg_ocr_minimum_text_height"] == 0.0
    assert row["cfg_ocr_tiling_enabled"] is True
    assert row["cfg_ocr_tiling_rows"] == 2
    assert row["cfg_ocr_tiling_cols"] == 2
    assert row["cfg_ocr_tiling_overlap"] == 0.15
    assert row["cfg_ocr_tiling_include_full_frame"] is True
    assert row["cfg_ocr_tiling_nms_iou"] == 0.55
    assert row["cfg_ui_layout_segmentation_enabled"] is True
    assert row["cfg_detect_icons_in_perceive"] is False


@pytest.mark.smoke
def test_ab_extract_emits_one_error_line_for_missing_report(tmp_path, capsys):
    report_path = tmp_path / "missing.json"

    row = _run(["A", "2", "zh-CN", "1", str(report_path), "iphone_17_pro_max", "ios"], capsys)

    assert row["arm"] == "A"
    assert row["round"] == 2
    assert row["locale"] == "zh-CN"
    assert row["device"] == "iphone_17_pro_max"
    assert row["platform"] == "ios"
    assert row["rc"] == 1
    assert row["crash"] is True
    assert row["extraction_error"] == "report_missing"


@pytest.mark.smoke
def test_ab_extract_emits_one_error_line_for_truncated_json(tmp_path, capsys):
    report_path = tmp_path / "truncated.json"
    report_path.write_text('{"metrics": ', encoding="utf-8")

    row = _run(["B", "3", "en-HK", "0", str(report_path)], capsys)

    assert row["arm"] == "B"
    assert row["round"] == 3
    assert row["locale"] == "en-HK"
    assert row["extraction_error"] == "json_decode_error"


@pytest.mark.smoke
def test_ab_matrix_shell_syntax_is_valid():
    script = Path("skills/regression/ios_settings/ab_matrix.sh")

    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


@pytest.mark.smoke
def test_ab_matrix_records_rows_for_each_configured_device_without_hardware(tmp_path):
    script = Path("skills/regression/ios_settings/ab_matrix.sh")
    env = {
        **os.environ,
        "IPAD_SETTINGS_AB_DIR": str(tmp_path),
        "IPAD_SETTINGS_AB_STAMP": "device_smoke",
        "IPAD_SETTINGS_AB_ROUNDS": "1",
        "IPAD_SETTINGS_AB_LOCALES": "en:HK",
        "IPAD_SETTINGS_AB_ARMS": "unknown_arm",
        "IPAD_SETTINGS_AB_DEVICES": "ipad_mini_7:ipados:state_machine iphone_17_pro_max:ios:none",
    }

    result = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "MATRIX_DONE device_smoke - rows: 2 / expected: 2" in result.stdout
    rows = [
        json.loads(line)
        for line in (tmp_path / "results_device_smoke.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(row["device"], row["platform"]) for row in rows] == [
        ("ipad_mini_7", "ipados"),
        ("iphone_17_pro_max", "ios"),
    ]
    assert all(row["arm"] == "unknown_arm" for row in rows)
    assert all(row["extraction_error"] == "report_missing" for row in rows)


@pytest.mark.smoke
def test_ab_matrix_accepts_raw_no_canonical_ui_layout_arm_without_hardware(tmp_path):
    script = Path("skills/regression/ios_settings/ab_matrix.sh")
    env = {
        **os.environ,
        "IPAD_SETTINGS_AB_DIR": str(tmp_path),
        "IPAD_SETTINGS_AB_STAMP": "raw_layout_smoke",
        "IPAD_SETTINGS_AB_ROUNDS": "1",
        "IPAD_SETTINGS_AB_LOCALES": "en:HK",
        "IPAD_SETTINGS_AB_ARMS": "raw_no_canonical raw_no_canonical_ui_layout",
        "IPAD_SETTINGS_AB_DEVICES": "iphone_17_pro_max:ios:none",
        "IPAD_SETTINGS_AB_EXTRA_ARGS": "--help",
    }

    result = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "MATRIX_DONE raw_layout_smoke - rows: 2 / expected: 2" in result.stdout
    rows = [
        json.loads(line)
        for line in (tmp_path / "results_raw_layout_smoke.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["arm"] for row in rows] == ["raw_no_canonical", "raw_no_canonical_ui_layout"]
    assert all(row["extraction_error"] == "report_missing" for row in rows)
