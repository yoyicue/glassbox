"""Generic iOS crawl control primitives.

Settings regression supplies the app-specific policy (which rows are safe,
which pages count as root/detail). This module owns reusable control contracts:
scroll outcome/retry and report metric shape. Generic action tracing lives in
glassbox.crawl.trace and is re-exported here for compatibility.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from glassbox.crawl.trace import ActionTraceEvent, ActionTraceObserver
from glassbox.ios.progress import scroll_outcome

# Backward-compatible re-export for callers that still import these from
# glassbox.ios.crawl.
_ACTION_TRACE_REEXPORTS = (ActionTraceEvent, ActionTraceObserver)


@dataclass(frozen=True)
class ScrollResult:
    outcome: str
    retry_outcome: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class CrawlMetrics:
    pages_visited: int = 0
    actions: int = 0
    no_progress_actions: int = 0
    scroll_overshoots: int = 0
    navigation_failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "pages_visited": self.pages_visited,
            "actions": self.actions,
            "no_progress_actions": self.no_progress_actions,
            "scroll_overshoots": self.scroll_overshoots,
            "navigation_failures": self.navigation_failures,
        }


def phone_supports(phone, action: str) -> bool:
    supports = getattr(phone, "supports", None)
    if callable(supports):
        try:
            return bool(supports(action))
        except Exception:
            return False
    if action == "scroll_wheel":
        return any(
            hasattr(phone, name)
            for name in ("scroll_wheel", "wheel_scroll_down", "wheel_scroll_up")
        )
    return hasattr(phone, action)


def call_scroll_method(method: Callable, ticks: int) -> None:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        method(ticks=ticks)
        return
    parameters = signature.parameters.values()
    if any(p.kind == inspect.Parameter.VAR_KEYWORD or p.name == "ticks" for p in parameters):
        method(ticks=ticks)
    else:
        method()


def classify_scroll_attempt(
    before_texts: Iterable[str],
    after_texts: Iterable[str],
    *,
    retry_texts: Iterable[str] | None = None,
) -> ScrollResult:
    outcome = scroll_outcome(before_texts, after_texts)
    if outcome != "stuck" or retry_texts is None:
        return ScrollResult(outcome=outcome)
    retry_outcome = scroll_outcome(before_texts, retry_texts)
    if retry_outcome == "stuck":
        return ScrollResult(outcome="stuck", retry_outcome=retry_outcome, attempts=2)
    return ScrollResult(outcome="progress", retry_outcome=retry_outcome, attempts=2)
