"""Pytest adapter for the read-only iOS Settings crawler."""

from __future__ import annotations

import pytest

from skills.regression.ios_settings import core as settings_core
from skills.regression.ios_settings.config import SettingsRunConfig
from skills.regression.ios_settings.crawler import (
    SettingsCrawlerUnavailable,
    SettingsCrawlResult,
    crawl_readonly_settings,
)


def run_ios_settings_readonly_walkthrough(
    phone,
    *,
    config: SettingsRunConfig | None = None,
    require_real_effector: bool = True,
) -> SettingsCrawlResult:
    """Backward-compatible alias for the public crawler API."""
    return crawl_readonly_settings(
        phone,
        config=config,
        require_real_effector=require_real_effector,
    )


def _assert_readonly_walkthrough_result(result: SettingsCrawlResult) -> None:
    assert len(result.visits) >= settings_core.MIN_PAGES_VISITED, (
        f"visited only {len(result.visits)} Settings pages: {[v.path for v in result.visits]}"
    )
    if settings_core.REQUIRE_EXHAUSTIVE:
        root_coverage = settings_core._root_coverage(result.visits)
        hard_limits = result.limits_hit - settings_core._SOFT_LIMITS
        assert not hard_limits, (
            "Settings walkthrough hit traversal limits before exhausting visible pages: "
            f"{sorted(hard_limits)} (soft: {sorted(result.limits_hit & settings_core._SOFT_LIMITS)})"
        )
        assert not root_coverage["missing"], (
            "Settings walkthrough did not cover all expected root pages: "
            f"{root_coverage['missing']}"
        )


@pytest.mark.regression
@pytest.mark.feature("ios_settings")
def test_ios_settings_readonly_walkthrough(phone):
    try:
        result = crawl_readonly_settings(phone)
    except SettingsCrawlerUnavailable as exc:
        pytest.skip(str(exc))
    _assert_readonly_walkthrough_result(result)
