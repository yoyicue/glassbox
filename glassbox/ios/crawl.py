"""Generic iOS crawl control primitives.

Settings regression supplies the app-specific policy (which rows are safe,
which pages count as root/detail). This module owns reusable control contracts:
read/settle policy, scroll outcome/retry, navigation candidate/result records,
and report metric shape. Generic action tracing lives in glassbox.crawl.trace
and is re-exported here for compatibility.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from glassbox.crawl.trace import ActionTraceEvent, ActionTraceObserver
from glassbox.ios.progress import scroll_outcome

# Backward-compatible re-export for callers that still import these from
# glassbox.ios.crawl.
_ACTION_TRACE_REEXPORTS = (ActionTraceEvent, ActionTraceObserver)


@dataclass(frozen=True)
class ReadPolicy:
    settle_seconds: float = 0.8
    voted_root_reads: bool = True
    root_vote_frames: int = 2


@dataclass(frozen=True)
class ScrollResult:
    outcome: str
    retry_outcome: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class NavigationCandidate:
    label: str
    page_id: str | None = None
    safe: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class NavigationResult:
    candidate: NavigationCandidate
    status: str
    returned_to_origin: bool = False
    error: str | None = None


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


def settle_then_read(phone, *, policy: ReadPolicy, root: bool = False):
    time.sleep(max(0.0, policy.settle_seconds))
    invalidate = getattr(phone, "invalidate_perceive_cache", None)
    if callable(invalidate):
        invalidate()
    if root and policy.voted_root_reads and hasattr(phone, "perceive_voted"):
        return phone.perceive_voted(policy.root_vote_frames)
    return phone.perceive()
