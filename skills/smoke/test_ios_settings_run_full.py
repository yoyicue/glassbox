"""Contract tests for run_full mode overrides (--quick / --drill-down)."""

from __future__ import annotations

import json

import pytest

from glassbox.memory.schema import UTG, ScreenEdge, ScreenNode, ScreenSignature
from glassbox.memory.store import save_utg
from skills.regression.ios_settings.policy import EXPECTED_ROOT_NAV_TEXT_ZH
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
            "en_ocr_correction": False,
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
