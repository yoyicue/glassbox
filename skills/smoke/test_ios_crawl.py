from __future__ import annotations

import pytest

from glassbox.ios.crawl import (
    ActionTraceObserver,
    CrawlMetrics,
    NavigationCandidate,
    NavigationResult,
    call_scroll_method,
    classify_scroll_attempt,
    phone_supports,
)


@pytest.mark.smoke
def test_action_trace_observer_closes_pending_events():
    trace = ActionTraceObserver()
    trace.start("tap", before={"texts": ["A"]})
    trace.start("key", before={"texts": ["B"]})
    trace.finish({"texts": ["C"]})

    assert [event.op for event in trace.events] == ["tap", "key"]
    assert trace.events[0].status == "no_after_scene"
    assert trace.events[1].status == "ok"


@pytest.mark.smoke
def test_action_trace_observer_records_result_and_error():
    trace = ActionTraceObserver()
    trace.start("tap", before={"texts": ["A"]})
    trace.set_result({"action_ok": False, "action_error": "executor failed"})
    trace.finish(None, status="action_failed", error="executor failed")

    event = trace.events[0]
    assert event.status == "action_failed"
    assert event.result == {"action_ok": False, "action_error": "executor failed"}
    assert event.error == "executor failed"


@pytest.mark.smoke
def test_scroll_attempt_result_tracks_overshoot_and_retry():
    before = ["设置", "无线局域网", "蓝牙", "通用", "辅助功能"]
    after = ["显示", "墙纸", "电池", "隐私", "钱包"]

    result = classify_scroll_attempt(before, after)

    assert result.outcome == "overshoot"
    assert result.attempts == 1


@pytest.mark.smoke
def test_call_scroll_method_handles_ticks_optional():
    calls: list[int | str] = []

    def with_ticks(*, ticks):
        calls.append(ticks)

    def without_ticks():
        calls.append("none")

    call_scroll_method(with_ticks, 7)
    call_scroll_method(without_ticks, 9)

    assert calls == [7, "none"]


@pytest.mark.smoke
def test_phone_supports_uses_capability_method():
    class Phone:
        def supports(self, action):
            return action == "scroll_wheel"

    assert phone_supports(Phone(), "scroll_wheel") is True
    assert phone_supports(Phone(), "drag") is False


@pytest.mark.smoke
def test_navigation_and_metric_schemas_are_serializable():
    candidate = NavigationCandidate(label="通用", page_id="settings/通用")
    result = NavigationResult(candidate=candidate, status="ok", returned_to_origin=True)
    metrics = CrawlMetrics(pages_visited=2, actions=3, scroll_overshoots=1)

    assert result.candidate.safe is True
    assert metrics.to_dict() == {
        "pages_visited": 2,
        "actions": 3,
        "no_progress_actions": 0,
        "scroll_overshoots": 1,
        "navigation_failures": 0,
    }
