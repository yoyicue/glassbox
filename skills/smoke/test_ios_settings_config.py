from __future__ import annotations

from pathlib import Path

import pytest

from skills.regression.ios_settings.config import SettingsRunConfig, build_full_run_env
from skills.regression.ios_settings.policy import EXPECTED_ROOT_NAV_TEXT_ZH


@pytest.mark.smoke
def test_settings_run_config_preserves_dependent_env_defaults():
    root_mode = SettingsRunConfig.from_env({})
    child_mode = SettingsRunConfig.from_env({"IOS_SETTINGS_ROOT_COVERAGE_MODE": "0"})

    assert root_mode.root_coverage_mode is True
    assert root_mode.max_child_scrolls_per_page == 1
    assert root_mode.child_navigation_enabled is False
    assert root_mode.strict_child_candidate_audit is False
    assert child_mode.root_coverage_mode is False
    assert child_mode.max_child_scrolls_per_page == child_mode.max_scrolls_per_page
    assert child_mode.child_navigation_enabled is True
    assert child_mode.strict_child_candidate_audit is True


@pytest.mark.smoke
def test_settings_run_config_report_dict_matches_walkthrough_contract():
    config = SettingsRunConfig.from_env({
        "IOS_SETTINGS_MIN_PAGES": "17",
        "IOS_SETTINGS_MAX_PAGES": "44",
        "IOS_SETTINGS_MAX_DEPTH": "3",
        "IOS_SETTINGS_REPORT": "/tmp/settings.json",
        "IOS_SETTINGS_RUN_ID": "run-1",
        "IOS_SETTINGS_REQUIRE_EXHAUSTIVE": "1",
        "IOS_SETTINGS_TRACE_ACTIONS": "1",
        "IOS_SETTINGS_MEMORY_DIR": "/tmp/memory",
        "IOS_SETTINGS_MEMORY_REUSE": "1",
    })

    assert config.run_id == "run-1"
    assert config.report_path == "/tmp/settings.json"
    assert config.to_report_config() == {
        "min_pages": 17,
        "max_pages": 44,
        "max_depth": 3,
        "max_scrolls_per_page": 8,
        "root_coverage_mode": True,
        "max_child_scrolls_per_page": 1,
        "child_navigation_enabled": False,
        "strict_child_candidate_audit": False,
        "max_candidates_per_page": 3,
        "require_exhaustive": True,
        "trace_actions": True,
        "save_view_snapshots": False,
        "artifact_dir": None,
        "memory_dir": "/tmp/memory",
        "memory_reuse": True,
    }
    assert config.to_walkthrough_runtime_globals() == {
        "MIN_PAGES_VISITED": 17,
        "MAX_PAGES_VISITED": 44,
        "MAX_DEPTH": 3,
        "MAX_SCROLLS_PER_PAGE": 8,
        "ROOT_COVERAGE_MODE": True,
        "MAX_CHILD_SCROLLS_PER_PAGE": 1,
        "CHILD_NAVIGATION_ENABLED": False,
        "STRICT_CHILD_CANDIDATE_AUDIT": False,
        "MAX_CANDIDATES_PER_PAGE": 3,
        "REQUIRE_EXHAUSTIVE": True,
        "REPORT_PATH": "/tmp/settings.json",
        "RUN_ID": "run-1",
        "TRACE_ACTIONS": True,
        "SAVE_VIEW_SNAPSHOTS": False,
        "ARTIFACT_DIR": None,
        "MEMORY_DIR": "/tmp/memory",
        "MEMORY_REUSE": True,
    }


@pytest.mark.smoke
def test_full_run_env_uses_settings_run_contract_defaults(tmp_path):
    report = tmp_path / "full.json"
    env = build_full_run_env(report, base_env={}, run_id="abc")

    assert env["IOS_SETTINGS_RUN_ID"] == "abc"
    assert env["IOS_SETTINGS_REQUIRE_EXHAUSTIVE"] == "1"
    assert env["IOS_SETTINGS_REPORT"] == str(report)
    assert env["IOS_SETTINGS_MIN_PAGES"] == str(len(EXPECTED_ROOT_NAV_TEXT_ZH) + 1)
    assert env["IOS_SETTINGS_MAX_PAGES"] == "800"
    assert env["IOS_SETTINGS_MAX_DEPTH"] == "6"
    assert env["IOS_SETTINGS_MAX_SCROLLS_PER_PAGE"] == "16"
    assert env["IOS_SETTINGS_ROOT_COVERAGE_MODE"] == "1"
    assert env["IOS_SETTINGS_MAX_CHILD_SCROLLS_PER_PAGE"] == "1"
    assert env["IOS_SETTINGS_CHILD_NAVIGATION_ENABLED"] == "0"
    assert env["IOS_SETTINGS_MAX_CANDIDATES_PER_PAGE"] == "0"
    assert env["IOS_SETTINGS_TRACE_ACTIONS"] == "1"
    assert env["GLASSBOX_VLM_CACHE_DIR"] == str(Path.home() / ".cache" / "glassbox" / "vlm_describe")
    assert env["IOS_SETTINGS_MEMORY_REUSE"] == "0"
    assert env["GLASSBOX_MEMORY_DIR"] == str(report.with_suffix(".artifacts") / "abc" / "memory")


@pytest.mark.smoke
def test_full_run_env_preserves_explicit_vlm_cache_dir(tmp_path):
    report = tmp_path / "full.json"
    env = build_full_run_env(
        report,
        base_env={"GLASSBOX_VLM_CACHE_DIR": "/tmp/custom-vlm-cache"},
        run_id="abc",
    )

    assert env["GLASSBOX_VLM_CACHE_DIR"] == "/tmp/custom-vlm-cache"


@pytest.mark.smoke
def test_full_run_env_can_reuse_explicit_memory_dir(tmp_path):
    memory_dir = Path("/tmp/shared-settings-memory")
    env = build_full_run_env(
        tmp_path / "full.json",
        base_env={},
        memory_dir=memory_dir,
        reuse_memory=True,
    )

    assert env["GLASSBOX_MEMORY_DIR"] == str(memory_dir)
    assert env["IOS_SETTINGS_MEMORY_DIR"] == str(memory_dir)
    assert env["IOS_SETTINGS_MEMORY_REUSE"] == "1"
