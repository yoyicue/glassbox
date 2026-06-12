"""Contract tests for run_full mode overrides (--quick / --drill-down)."""

from __future__ import annotations

import json

import pytest

from glassbox.memory.schema import UTG, ScreenEdge, ScreenNode, ScreenSignature
from glassbox.memory.store import save_utg
from skills.regression.ios_settings.policy import EXPECTED_ROOT_NAV_TEXT_ZH
from skills.regression.ios_settings.report_writer import _active_device_report_config
from skills.regression.ios_settings.reporting import EXPECTED_MIN_VISITS, refresh_report_summaries
from skills.regression.ios_settings.run_full import (
    _DRILL_DOWN_ENV_OVERRIDES,
    _QUICK_ENV_OVERRIDES,
    _verify_report,
)
from skills.regression.ios_settings.sections import root_section_ids_for_canonical_labels


@pytest.mark.smoke
def test_drill_down_enters_child_pages_and_snapshots():
    overrides = _DRILL_DOWN_ENV_OVERRIDES
    # Real entry into each section's detail page, not root-row visibility.
    assert overrides["IOS_SETTINGS_CHILD_NAVIGATION_ENABLED"] == "1"
    assert overrides["IOS_SETTINGS_ROOT_COVERAGE_MODE"] == "0"
    # Per-page screenshot evidence.
    assert overrides["IOS_SETTINGS_SAVE_VIEW_SNAPSHOTS"] == "1"
    # Depth 1: open the section detail pages, not their sub-children.
    assert overrides["IOS_SETTINGS_MAX_DEPTH"] == "1"


@pytest.mark.smoke
def test_quick_stays_shallow_and_non_exhaustive():
    assert _QUICK_ENV_OVERRIDES["IOS_SETTINGS_REQUIRE_EXHAUSTIVE"] == "0"
    assert _QUICK_ENV_OVERRIDES["IOS_SETTINGS_MAX_DEPTH"] == "1"


@pytest.mark.smoke
def test_report_config_records_ocr_layout_ab_switches(monkeypatch):
    from glassbox.config import get_config

    monkeypatch.setenv("GLASSBOX_PHONE_MODEL", "ipad_mini_7")
    monkeypatch.setenv("GLASSBOX_PLATFORM", "ipados")
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    monkeypatch.setenv("GLASSBOX_OCR_MINIMUM_TEXT_HEIGHT", "0")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_ENABLED", "1")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_ROWS", "3")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_COLS", "4")
    monkeypatch.setenv("GLASSBOX_OCR_TILING_OVERLAP", "0.2")
    monkeypatch.setenv("GLASSBOX_UI_LAYOUT_SEGMENTATION_ENABLED", "1")
    monkeypatch.setenv("GLASSBOX_IOS_CLOSED_SET_CANONICALIZATION_ENABLED", "0")
    get_config.cache_clear()
    try:
        report_config = _active_device_report_config()
    finally:
        get_config.cache_clear()

    assert report_config["phone_model"] == "ipad_mini_7"
    assert report_config["platform"] == "ipados"
    assert report_config["language"] == "en"
    assert report_config["region"] == "HK"
    assert report_config["ocr"] == "vision"
    assert report_config["text_detector"] == "vision"
    assert report_config["ocr_minimum_text_height"] == 0.0
    assert report_config["ocr_tiling_enabled"] is True
    assert report_config["ocr_tiling_rows"] == 3
    assert report_config["ocr_tiling_cols"] == 4
    assert report_config["ocr_tiling_overlap"] == 0.2
    assert report_config["ui_layout_segmentation_enabled"] is True
    assert report_config["ios_closed_set_canonicalization_enabled"] is False


@pytest.mark.smoke
def test_verify_report_can_run_state_machine_acceptance(tmp_path):
    memory_dir = tmp_path / "memory"
    report_path = tmp_path / "report.json"
    report = _state_machine_report(memory_dir)
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    save_utg(_state_machine_utg(), memory_dir=memory_dir)

    assert _verify_report(
        report_path,
        expected_run_id="run-test",
        require_exhaustive=True,
        state_machine_acceptance=True,
        state_machine_min_detail_to_root_edges=1,
        state_machine_require_sidebar_exhaustive=True,
    ) == 0


def _state_machine_report(memory_dir):
    visits = [
        {"path": ["Settings"], "title": "Settings", "texts": ["Settings"]},
        *[
            {"path": ["Settings", label], "title": label, "texts": [label, "body line"]}
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
        ],
    ]
    root_coverage = {
        "expected": list(EXPECTED_ROOT_NAV_TEXT_ZH),
        "visited": list(EXPECTED_ROOT_NAV_TEXT_ZH),
        "missing": [],
        "entered_graph": ["蓝牙"],
        "required_missing": [],
        "sidebar_exhaustive": ["true"],
        "expected_ids": root_section_ids_for_canonical_labels(EXPECTED_ROOT_NAV_TEXT_ZH),
        "visited_ids": root_section_ids_for_canonical_labels(EXPECTED_ROOT_NAV_TEXT_ZH),
        "missing_ids": [],
    }
    report = {
        "run_id": "run-test",
        "config": {
            "require_exhaustive": True,
            "min_pages": EXPECTED_MIN_VISITS,
            "max_pages": 240,
            "max_depth": 4,
            "max_scrolls_per_page": 12,
            "root_coverage_mode": False,
            "max_child_scrolls_per_page": 1,
            "child_navigation_enabled": True,
            "strict_child_candidate_audit": False,
            "max_candidates_per_page": 0,
            "trace_actions": True,
            "save_view_snapshots": False,
            "artifact_dir": None,
            "memory_dir": str(memory_dir),
            "memory_reuse": False,
        },
        "locale": "zh-Hans",
        "limits_hit": [],
        "visit_count": len(visits),
        "root_coverage": root_coverage,
        "blocked_pages": [],
        "rejected_candidates": [],
        "navigation_failures": [],
        "visits": visits,
    }
    refresh_report_summaries(report)
    return report


def _state_machine_utg() -> UTG:
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
                success_count=1,
                count=1,
                success_rate=1.0,
            ),
            ScreenEdge(
                from_id=detail.screen_id,
                to_id=root.screen_id,
                action_op="back",
                policy_action="back",
                success_count=1,
                count=1,
                success_rate=1.0,
            ),
        ],
    )


@pytest.mark.smoke
def test_retain_existing_report_preserves_prior_evidence(tmp_path):
    """S6/C5 (docs/design/iphone_settings_transition.md): run_full used to
    unlink the report on every invocation — a retry that reused the path
    destroyed the 144-action run's report (2026-06-12 forensics). Prior
    reports must survive under unique names, including collisions."""
    from skills.regression.ios_settings.run_full import _retain_existing_report

    report = tmp_path / "ios-settings-000.json"

    # nothing to retain: no-op
    _retain_existing_report(report)
    assert list(tmp_path.iterdir()) == []

    report.write_text('{"attempt": 1}', encoding="utf-8")
    _retain_existing_report(report)
    assert not report.exists()
    (first_kept,) = tmp_path.iterdir()
    assert first_kept.name.startswith("ios-settings-000.prev-")
    assert first_kept.read_text(encoding="utf-8") == '{"attempt": 1}'

    # same-mtime collision: second retention picks a distinct sibling name
    report.write_text('{"attempt": 2}', encoding="utf-8")
    import os
    os.utime(report, (first_kept.stat().st_mtime, first_kept.stat().st_mtime))
    _retain_existing_report(report)
    kept = sorted(p.name for p in tmp_path.iterdir())
    assert len(kept) == 2 and all(".prev-" in name for name in kept)
