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
