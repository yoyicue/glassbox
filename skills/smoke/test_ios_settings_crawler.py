from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings import core as settings_core
from skills.regression.ios_settings import crawler
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings.config import SettingsRunConfig
from skills.regression.ios_settings.policy import IPadSettingsPolicy


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


@pytest.mark.smoke
def test_child_audit_records_initial_return_root_failed_not_exception(monkeypatch):
    monkeypatch.setattr(settings_core, "_wrap_phone_with_trace_if_enabled", lambda phone: (phone, None))
    monkeypatch.setattr(crawler, "_open_settings_from_home_if_visible", lambda phone: None)

    def _return(_phone):
        raise crawler.settings_recovery.SettingsRootUnreachable("dirty start")

    monkeypatch.setattr(crawler, "_return_to_settings_root", _return)

    result = crawler.crawl_high_value_child_settings(
        object(),
        target_root_labels=["Apple Pencil"],
        max_depth=1,
        max_pages=8,
        max_child_scrolls_per_page=0,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
    )

    assert result.target_failures == [
        {"label": "Apple Pencil", "reason": "settings_root_unreachable"}
    ]
    assert result.return_root_failed is True
    assert result.limits_hit == {"return_root_failed"}
    assert "exception" not in result.limits_hit


@pytest.mark.smoke
def test_child_audit_records_return_root_failed_after_unopened_target(monkeypatch):
    """Unopened targets can leave a dirty search state; report both facts."""
    monkeypatch.setattr(settings_core, "_wrap_phone_with_trace_if_enabled", lambda phone: (phone, None))
    monkeypatch.setattr(crawler, "_open_settings_from_home_if_visible", lambda phone: None)
    monkeypatch.setattr(crawler, "_open_target_root_page", lambda phone, label: False)

    calls = {"n": 0}

    def _return(_phone):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # initial reset to root succeeds
        raise crawler.settings_recovery.SettingsRootUnreachable("dirty search after miss")

    monkeypatch.setattr(crawler, "_return_to_settings_root", _return)

    result = crawler.crawl_high_value_child_settings(
        object(),
        target_root_labels=["Missing"],
        max_depth=1,
        max_pages=8,
        max_child_scrolls_per_page=0,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
        allow_root_only_target_roots=True,
    )
    assert result.target_failures == [{"label": "Missing", "reason": "target_root_not_opened"}]
    assert result.return_root_failed is True
    assert "return_root_failed" in result.limits_hit
    assert "exception" not in result.limits_hit


@pytest.mark.smoke
def test_child_audit_assume_settings_open_skips_foregrounding(monkeypatch):
    monkeypatch.setattr(settings_core, "_wrap_phone_with_trace_if_enabled", lambda phone: (phone, None))
    monkeypatch.setattr(crawler, "_current_scene_is_settings_context", lambda phone: True)
    monkeypatch.setattr(
        crawler,
        "_open_settings_from_home_if_visible",
        lambda phone: pytest.fail("assume_settings_open must not foreground Settings"),
    )
    monkeypatch.setattr(crawler, "_return_to_settings_root", lambda phone: None)
    monkeypatch.setattr(crawler, "_open_target_root_page", lambda phone, label: True)
    monkeypatch.setattr(crawler, "_crawl_current_page", lambda phone, **kwargs: None)

    result = crawler.crawl_high_value_child_settings(
        object(),
        target_root_labels=["Apple Pencil"],
        max_depth=1,
        max_pages=4,
        max_child_scrolls_per_page=0,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
        assume_settings_open=True,
    )

    assert result.opened_targets == ["Apple Pencil"]
    assert result.config["assume_settings_open"] is True
    assert not result.limits_hit


@pytest.mark.smoke
def test_child_audit_assume_settings_open_reports_non_settings_start(monkeypatch):
    monkeypatch.setattr(settings_core, "_wrap_phone_with_trace_if_enabled", lambda phone: (phone, None))
    monkeypatch.setattr(crawler, "_current_scene_is_settings_context", lambda phone: False)
    monkeypatch.setattr(
        crawler,
        "_open_settings_from_home_if_visible",
        lambda phone: pytest.fail("assume_settings_open must not foreground Settings"),
    )
    monkeypatch.setattr(
        crawler,
        "_return_to_settings_root",
        lambda phone: pytest.fail("non-Settings starts should fail before Settings recovery"),
    )

    result = crawler.crawl_high_value_child_settings(
        object(),
        target_root_labels=["Apple Pencil"],
        max_depth=1,
        max_pages=4,
        max_child_scrolls_per_page=0,
        max_candidates_per_page=0,
        strict_child_candidate_audit=False,
        assume_settings_open=True,
    )

    assert result.target_failures == [
        {"label": "Apple Pencil", "reason": "settings_not_foregrounded"}
    ]
    assert result.limits_hit == {"startup_not_settings"}
    assert result.config["assume_settings_open"] is True


@pytest.mark.smoke
def test_ipad_child_audit_matches_visible_root_rows_by_canonical_label(monkeypatch):
    policy = IPadSettingsPolicy()
    monkeypatch.setattr(settings_core, "DEFAULT_SETTINGS_POLICY", policy)
    monkeypatch.setattr(settings_scene_state, "DEFAULT_SETTINGS_POLICY", policy)
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            UIElement(type="text", box=Box(x=48, y=72, w=72, h=28), text="Settings", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=220, w=52, h=24), text="WLAN", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=276, w=76, h=24), text="General", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=332, w=112, h=24), text="Accessibility", confidence=0.9),
            UIElement(type="text", box=Box(x=418, y=76, w=96, h=28), text="VoiceOver", confidence=0.9),
            UIElement(type="text", box=Box(x=384, y=180, w=86, h=24), text="Verbosity", confidence=0.9),
        ],
    )
    phone = SimpleNamespace(
        device_geometry=SimpleNamespace(model="ipad_mini_7"),
        perceive=lambda: scene,
    )

    candidate = crawler._visible_root_candidate_for_label(phone, "辅助功能")

    assert candidate is not None
    assert candidate.text == "Accessibility"


@pytest.mark.smoke
def test_child_audit_accepts_current_requested_root_before_search(monkeypatch):
    policy = IPadSettingsPolicy()
    monkeypatch.setattr(settings_core, "DEFAULT_SETTINGS_POLICY", policy)
    monkeypatch.setattr(settings_scene_state, "DEFAULT_SETTINGS_POLICY", policy)
    monkeypatch.setattr(crawler, "_return_to_settings_root", lambda phone: None)
    monkeypatch.setattr(crawler, "_scroll_to_vertical_boundary", lambda phone, *, direction: None)
    monkeypatch.setattr(crawler, "_visible_root_candidate_for_label", lambda phone, label: pytest.fail("row lookup should not run"))
    monkeypatch.setattr(
        crawler.settings_navigation,
        "open_root_label_via_search",
        lambda phone, label, actions: pytest.fail("search fallback should not run"),
    )
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=34, y=90, w=72, h=18), text="Q Search", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=167, w=76, h=16), text="Battery", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=335, w=92, h=16), text="Screen Time", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=368, w=112, h=16), text="Accessibility", confidence=0.9),
            UIElement(type="text", box=Box(x=300, y=34, w=88, h=16), text="Daily Average", confidence=0.9),
            UIElement(type="text", box=Box(x=302, y=60, w=78, h=22), text="47h 19m", confidence=0.9),
            UIElement(type="text", box=Box(x=482, y=65, w=146, h=16), text="© 19% from last week", confidence=0.9),
            UIElement(type="text", box=Box(x=320, y=348, w=76, h=18), text="Downtime", confidence=0.9),
            UIElement(type="text", box=Box(x=320, y=403, w=78, h=18), text="App Limits", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=456, w=112, h=18), text="Always Allowed", confidence=0.9),
        ],
    )
    phone = SimpleNamespace(
        device_geometry=SimpleNamespace(model="ipad_mini_7"),
        perceive=lambda: scene,
    )

    assert crawler._open_target_root_page(phone, "屏幕使用时间") is True


@pytest.mark.smoke
def test_child_audit_rechecks_target_root_after_failed_fallback(monkeypatch):
    policy = IPadSettingsPolicy()
    monkeypatch.setattr(settings_core, "DEFAULT_SETTINGS_POLICY", policy)
    monkeypatch.setattr(settings_scene_state, "DEFAULT_SETTINGS_POLICY", policy)
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(crawler, "_return_to_settings_root", lambda phone: None)
    monkeypatch.setattr(crawler, "_scroll_to_vertical_boundary", lambda phone, *, direction: None)
    monkeypatch.setattr(crawler, "_visible_root_candidate_for_label", lambda phone, label: None)
    monkeypatch.setattr(
        crawler.settings_navigation,
        "open_visible_or_scroll_to_row",
        lambda phone, labels, actions: None,
    )
    monkeypatch.setattr(
        crawler.settings_navigation,
        "open_root_label_via_search",
        lambda phone, label, actions: False,
    )
    initial = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=34, y=90, w=72, h=18), text="Q Search", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=335, w=122, h=16), text="Privacy & Security", confidence=0.9),
            UIElement(type="text", box=Box(x=364, y=203, w=164, h=22), text="Privacy & Security", confidence=0.9),
        ],
    )
    target = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=34, y=90, w=72, h=18), text="Q Search", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=335, w=92, h=16), text="Screen Time", confidence=0.9),
            UIElement(type="text", box=Box(x=300, y=34, w=88, h=16), text="Daily Average", confidence=0.9),
            UIElement(type="text", box=Box(x=302, y=60, w=78, h=22), text="47h 19m", confidence=0.9),
            UIElement(type="text", box=Box(x=482, y=65, w=146, h=16), text="© 19% from last week", confidence=0.9),
            UIElement(type="text", box=Box(x=320, y=348, w=76, h=18), text="Downtime", confidence=0.9),
            UIElement(type="text", box=Box(x=320, y=403, w=78, h=18), text="App Limits", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=456, w=112, h=18), text="Always Allowed", confidence=0.9),
        ],
    )
    scenes = iter([initial, target])

    class _Phone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def perceive(self):
            return next(scenes, target)

        def invalidate_perceive_cache(self):
            pass

    assert crawler._open_target_root_page(_Phone(), "屏幕使用时间") is True
