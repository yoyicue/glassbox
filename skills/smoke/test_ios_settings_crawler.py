from __future__ import annotations

import json

import pytest

from skills.regression.ios_settings import core as settings_core
from skills.regression.ios_settings import crawler
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings.config import SettingsRunConfig


@pytest.mark.smoke
def test_crawl_readonly_settings_delegates_to_non_pytest_runner(monkeypatch):
    phone = object()
    config = SettingsRunConfig.from_env({"IOS_SETTINGS_MAX_PAGES": "9"})
    previous_max_pages = settings_core.MAX_PAGES_VISITED
    expected = crawler.SettingsCrawlResult(
        visits=[settings_reporting.PageVisit(path=("Settings",), title="设置", texts=("设置",))],
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )
    calls = []

    def fake_run(actual_phone):
        calls.append((actual_phone, settings_core.MAX_PAGES_VISITED))
        return expected

    monkeypatch.setattr(crawler, "_run_core_crawl", fake_run)

    result = crawler.crawl_readonly_settings(
        phone,
        config=config,
        require_real_effector=False,
    )

    assert result is expected
    assert calls == [(phone, 9)]
    assert previous_max_pages == settings_core.MAX_PAGES_VISITED


@pytest.mark.smoke
def test_readonly_settings_runner_raises_unavailable_without_real_effector():
    with pytest.raises(crawler.SettingsCrawlerUnavailable):
        crawler.crawl_readonly_settings(object())


@pytest.mark.smoke
def test_crawl_readonly_settings_report_keeps_trace_payload_after_success(monkeypatch, tmp_path):
    report_path = tmp_path / "settings.json"
    config = SettingsRunConfig.from_env({
        "IOS_SETTINGS_REPORT": str(report_path),
        "IOS_SETTINGS_RUN_ID": "trace-success",
        "IOS_SETTINGS_TRACE_ACTIONS": "1",
        "IOS_SETTINGS_ARTIFACT_DIR": str(tmp_path / "artifacts"),
    })

    class Trace:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        @property
        def payload(self):
            return {
                "artifact_dir": str(tmp_path / "artifacts"),
                "actions_jsonl": str(tmp_path / "artifacts" / "actions.jsonl"),
                "views_dir": None,
                "unique_view_count": 0,
                "action_count": 1 if self.closed else 0,
                "hid_call_count": 1 if self.closed else 0,
            }

    trace = Trace()
    monkeypatch.setattr(settings_core, "_wrap_phone_with_trace_if_enabled", lambda phone: (phone, trace))
    monkeypatch.setattr(crawler, "_open_settings_from_home_if_visible", lambda phone: None)
    monkeypatch.setattr(crawler, "_scroll_to_vertical_boundary", lambda phone, *, direction: None)
    monkeypatch.setattr(crawler, "_return_to_settings_root", lambda phone: None)

    def fake_crawl_current_page(
        phone,
        *,
        path,
        visits,
        seen_sigs,
        depth,
        max_depth,
        limits_hit,
        blocked_pages,
        rejected_candidates,
        navigation_failures,
    ):
        del phone, seen_sigs, depth, max_depth, limits_hit, blocked_pages, rejected_candidates
        del navigation_failures
        visits.append(settings_reporting.PageVisit(path=path, title="设置", texts=("设置",)))

    monkeypatch.setattr(crawler, "_crawl_current_page", fake_crawl_current_page)

    crawler.crawl_readonly_settings(object(), config=config, require_real_effector=False)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["trace"]["action_count"] == 1
    assert payload["metrics"]["hid_call_count"] == 1


@pytest.mark.smoke
def test_try_return_to_settings_root_absorbs_unreachable(monkeypatch):
    """The "try" variant must report False (not propagate) when the recovery
    raises its distinct SettingsRootUnreachable — return_to_settings_root no
    longer raises AssertionError, so the old catch was dead."""
    def _raise(_phone):
        raise settings_core.settings_recovery.SettingsRootUnreachable("nope")

    monkeypatch.setattr(settings_core, "_return_to_settings_root", _raise)
    assert settings_core._try_return_to_settings_root(object()) is False


@pytest.mark.smoke
def test_child_audit_records_return_root_failed_not_exception(monkeypatch):
    """Child audit's soft return_root_failed path must catch the distinct
    SettingsRootUnreachable; otherwise it falls through to exception + re-raise."""
    monkeypatch.setattr(settings_core, "_wrap_phone_with_trace_if_enabled", lambda phone: (phone, None))
    monkeypatch.setattr(crawler, "_open_settings_from_home_if_visible", lambda phone: None)
    monkeypatch.setattr(crawler, "_open_target_root_page", lambda phone, label: True)
    monkeypatch.setattr(crawler, "_crawl_current_page", lambda phone, **kwargs: None)

    calls = {"n": 0}

    def _return(_phone):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # initial reset to root succeeds
        raise crawler.settings_recovery.SettingsRootUnreachable("stranded after target")

    monkeypatch.setattr(crawler, "_return_to_settings_root", _return)

    result = crawler.crawl_high_value_child_settings(
        object(),
        target_root_labels=["蓝牙"],
        max_depth=1,
        max_pages=8,
        max_child_scrolls_per_page=1,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
    )
    assert result.return_root_failed is True
    assert "return_root_failed" in result.limits_hit
    assert "exception" not in result.limits_hit
