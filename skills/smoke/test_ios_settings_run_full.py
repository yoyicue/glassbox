"""Contract tests for run_full mode overrides (--quick / --drill-down)."""

from __future__ import annotations

import pytest

from skills.regression.ios_settings.run_full import (
    _DRILL_DOWN_ENV_OVERRIDES,
    _QUICK_ENV_OVERRIDES,
)


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
