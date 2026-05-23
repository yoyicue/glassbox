"""Shared report summaries for iOS Settings probes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from glassbox.ios.progress import screen_signature
from skills.regression.ios_settings.policy import (
    BLOCKED_CHILD_NAVIGATION_MARKERS,
    DEFAULT_SETTINGS_POLICY,
    EXPECTED_ROOT_NAV_TEXT_ZH,
    FAILURE_CATEGORY_KEYS,
)

# Soft limits are reportable perception/budget signals, not strict traversal blockers.
SOFT_LIMITS = frozenset({"max_depth", "scroll_overshoot"})
EXPECTED_BLOCKED_REASONS = frozenset(
    reason
    for _, _, reason in BLOCKED_CHILD_NAVIGATION_MARKERS
)
EXPECTED_REJECTED_REASONS = frozenset({
    "unsafe_text",
    "unknown_navigation_label",
    "missing_navigation_affordance",
    "section_header",
})
EXPECTED_NAVIGATION_FAILURE_REASONS = frozenset({"tap_no_navigation"})
EXPECTED_MIN_VISITS = len(EXPECTED_ROOT_NAV_TEXT_ZH) + 1
TRACE_METRIC_KEYS = (
    "hid_call_count",
    "hid_op_counts",
    "hid_no_progress_count",
    "hid_no_progress_op_counts",
    "hid_progress_count",
    "hid_progress_op_counts",
    "hid_no_after_count",
    "hid_no_after_op_counts",
    "hid_intent_counts",
    "hid_no_progress_intent_counts",
)


@dataclass
class PageVisit:
    path: tuple[str, ...]
    title: str
    texts: tuple[str, ...]


@dataclass
class BlockedPage:
    path: tuple[str, ...]
    title: str
    reason: str
    texts: tuple[str, ...]


@dataclass
class RejectedCandidate:
    path: tuple[str, ...]
    title: str
    text: str
    reason: str


@dataclass
class NavigationFailure:
    path: tuple[str, ...]
    title: str
    text: str
    reason: str


def add_trace_metrics(metrics: dict[str, object], trace_payload: Mapping[str, Any]) -> None:
    metrics.update(trace_metric_updates(trace_payload))


def trace_metric_updates(trace_payload: Mapping[str, Any]) -> dict[str, object]:
    return {key: trace_payload.get(key) for key in TRACE_METRIC_KEYS}


def blocked_reason_from_texts(texts: Any) -> str | None:
    if not isinstance(texts, list):
        return None
    joined = "\n".join(str(text) for text in texts)
    for page_marker, row_markers, reason in BLOCKED_CHILD_NAVIGATION_MARKERS:
        if page_marker in joined and (not row_markers or any(marker in joined for marker in row_markers)):
            return reason
    return None


def computed_root_coverage(visits: Sequence[Any]) -> dict[str, list[str]]:
    visited: set[str] = set()
    for visit in visits:
        path = _path(visit)
        if len(path) < 2 or path[0] != "Settings":
            continue
        label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(path[1])
        if label is not None and root_visit_has_label_evidence(visit, label):
            visited.add(label)
    expected = list(EXPECTED_ROOT_NAV_TEXT_ZH)
    return {
        "expected": expected,
        "visited": [label for label in expected if label in visited],
        "missing": [label for label in expected if label not in visited],
    }


def _label_entered(label: str, visits: Sequence[Any]) -> bool:
    """A label is *entered* when a visit captured the section's own detail page,
    not just its row label on the scrolled root list.

    The root-row visibility record is ``PageVisit(texts=(label,))`` — a single
    text equal to the label. A real entry has the page's own content (many
    texts), so we require more than the bare row label plus label evidence.
    """
    for visit in visits:
        path = _path(visit)
        if len(path) < 2 or path[0] != "Settings":
            continue
        if DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(path[1]) != label:
            continue
        texts = _value(visit, "texts")
        nonempty = (
            [str(t).strip() for t in texts if str(t).strip()]
            if isinstance(texts, (list, tuple))
            else []
        )
        # The bare root-row visibility record is exactly one text (the row label);
        # any richer page record means the section's detail page was opened.
        if len(nonempty) > 1:
            return True
    return False


def classify_root_coverage(
    base: Mapping[str, Sequence[str]],
    visits: Sequence[Any],
    rejected_candidates: Sequence[Any],
) -> dict[str, list[str]]:
    """Enrich root_coverage with entered / visible_only / blocked.

    Additive: keeps ``expected``/``visited``/``missing`` (``visited`` = "seen" =
    entered ∪ visible_only ∪ blocked) and adds the breakdown so callers can tell
    a real section entry from a row merely seen on the root list, and from a page
    deliberately not entered for safety.
    """
    expected = list(base.get("expected", EXPECTED_ROOT_NAV_TEXT_ZH))
    visited = set(base.get("visited", ()))
    entered = {label for label in expected if _label_entered(label, visits)}
    blocked: set[str] = set()
    for candidate in rejected_candidates:
        label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(str(_value(candidate, "text") or ""))
        if label in expected and label not in entered:
            blocked.add(label)
    enriched = {key: list(value) for key, value in base.items()}
    enriched["entered"] = [label for label in expected if label in entered]
    enriched["blocked"] = [label for label in expected if label in blocked]
    enriched["visible_only"] = [
        label for label in expected if label in visited and label not in entered and label not in blocked
    ]
    return enriched


def root_visit_has_label_evidence(visit: Any, label: str) -> bool:
    title = _value(visit, "title")
    if isinstance(title, str) and (
        DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(title) == label
        or DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(title, label)
    ):
        return True
    texts = _value(visit, "texts")
    if not isinstance(texts, list):
        return False
    if label in {"Face ID与密码", "密码"} and blocked_reason_from_texts(texts) == "authentication required":
        return True
    return any(
        DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(str(text)) == label
        or DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(str(text), label)
        for text in texts
    )


def path_has_root_label_evidence(visits: Sequence[Any], path_key: tuple[str, ...], label: str) -> bool:
    return any(
        _path(visit) == path_key and root_visit_has_label_evidence(visit, label)
        for visit in visits
    )


def report_metrics(
    *,
    visits: Sequence[Any],
    limits_hit: Iterable[str],
    blocked_pages: Sequence[Any],
    rejected_candidates: Sequence[Any],
    navigation_failures: Sequence[Any],
    root_coverage: Mapping[str, Sequence[str]],
    require_exhaustive: bool,
    min_pages: int,
) -> dict[str, object]:
    limits = set(limits_hit)
    text_signatures = {
        screen_signature(_texts(visit))
        for visit in visits
    }
    navigation_success_proxy = sum(1 for visit in visits if len(_path(visit)) > 1)
    navigation_failure_count = len(navigation_failures)
    navigation_attempts_proxy = navigation_success_proxy + navigation_failure_count
    if navigation_attempts_proxy:
        navigation_success_proxy_rate = navigation_success_proxy / navigation_attempts_proxy
    else:
        navigation_success_proxy_rate = None
    missing = list(root_coverage.get("missing", ()))
    return {
        "visit_count": len(visits),
        "unique_visible_signatures": len(text_signatures),
        "root_expected_count": len(root_coverage.get("expected", ())),
        "root_visited_count": len(root_coverage.get("visited", ())),
        "root_missing_count": len(missing),
        "blocked_page_count": len(blocked_pages),
        "rejected_candidate_count": len(rejected_candidates),
        "navigation_failure_count": navigation_failure_count,
        "navigation_success_proxy_count": navigation_success_proxy,
        "navigation_attempts_proxy_count": navigation_attempts_proxy,
        "navigation_success_proxy_rate": navigation_success_proxy_rate,
        "limits_hit_count": len(limits),
        "exception_hit": "exception" in limits,
        "max_scrolls_hit": "max_scrolls_per_page" in limits,
        "exhaustive_ready": (
            require_exhaustive
            and not (limits - SOFT_LIMITS)
            and not missing
            and len(visits) >= min_pages
        ),
    }


def known_harness_issues(
    *,
    limits_hit: Iterable[str],
    rejected_candidates: Sequence[Any],
    navigation_failures: Sequence[Any],
    metrics: Mapping[str, object],
    require_exhaustive: bool,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    limits = set(limits_hit)
    hard_limits = limits - SOFT_LIMITS
    if hard_limits:
        issues.append({
            "id": "ios-settings-traversal-limits-hit",
            "category": "efficiency",
            "severity": "blocking" if require_exhaustive else "warning",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "Walkthrough stopped with traversal limits before exhaustive completion.",
            "evidence": sorted(hard_limits),
            "next_action": "Inspect the limit-specific paths and improve navigation, scrolling, or page budgets before strict acceptance.",
        })
    soft_limits = limits & SOFT_LIMITS
    if soft_limits:
        issues.append({
            "id": "ios-settings-scroll-overshoot",
            "category": "perception",
            "severity": "warning",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "Walkthrough completed with bounded-depth or scroll-overshoot signals.",
            "evidence": sorted(soft_limits),
            "next_action": "Track these as glassbox efficiency/perception signals; they are not strict-acceptance blockers.",
        })
    if navigation_failures:
        issues.append({
            "id": "ios-settings-navigation-tap-no-transition",
            "category": "operation",
            "severity": "blocking" if require_exhaustive else "warning",
            "status": "open",
            "area": "glassbox/effectors/picokvm",
            "summary": "One or more safe-looking navigation taps did not open a new page.",
            "evidence": [
                " > ".join((*_path(failure), str(_value(failure, "text", ""))))
                for failure in navigation_failures[:8]
            ],
            "next_action": "Reproduce each failed row and classify as tap precision, stale perception, or allowlist issue.",
        })
    unresolved_rejections = [
        candidate
        for candidate in rejected_candidates
        if _value(candidate, "reason") in {"unknown_navigation_label", "missing_navigation_affordance"}
    ]
    if unresolved_rejections:
        issues.append({
            "id": "ios-settings-navigation-candidate-policy-gap",
            "category": "safety",
            "severity": "blocking" if require_exhaustive else "warning",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "Some row-like texts need an explicit safety/affordance decision.",
            "evidence": [
                f"{' > '.join(_path(candidate))} > {_value(candidate, 'text', '')} ({_value(candidate, 'reason', '')})"
                for candidate in unresolved_rejections[:8]
            ],
            "next_action": "Add explicit allowlist/blocklist evidence or improve chevron/list-item perception.",
        })
    if metrics.get("exception_hit") is True:
        issues.append({
            "id": "ios-settings-walkthrough-exception",
            "category": "recovery",
            "severity": "blocking",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "Walkthrough raised an exception before report completion.",
            "evidence": ["limits_hit contains exception"],
            "next_action": "Inspect pytest traceback and harden the failing glassbox path.",
        })
    return issues


def failure_categories(known_issues: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {key: [] for key in FAILURE_CATEGORY_KEYS}
    for issue in known_issues:
        category = str(issue.get("category") or "")
        issue_id = str(issue.get("id") or "")
        if category in categories and issue_id:
            categories[category].append(issue_id)
    return {key: sorted(set(values)) for key, values in categories.items()}


def refresh_report_summaries(report: dict[str, Any]) -> dict[str, Any]:
    config = report.get("config")
    if not isinstance(config, Mapping):
        config = {}
    require_exhaustive = config.get("require_exhaustive") is True
    min_pages = config.get("min_pages")
    if not isinstance(min_pages, int):
        min_pages = 0
    visits = _list_value(report.get("visits"))
    root_coverage = report.get("root_coverage")
    if not isinstance(root_coverage, Mapping):
        root_coverage = {}
    blocked_pages = _list_value(report.get("blocked_pages"))
    rejected_candidates = _list_value(report.get("rejected_candidates"))
    navigation_failures = _list_value(report.get("navigation_failures"))
    limits_hit = [str(item) for item in _list_value(report.get("limits_hit"))]
    metrics = report_metrics(
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=root_coverage,
        require_exhaustive=require_exhaustive,
        min_pages=min_pages,
    )
    issues = known_harness_issues(
        limits_hit=limits_hit,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        metrics=metrics,
        require_exhaustive=require_exhaustive,
    )
    report["metrics"] = metrics
    report["known_issues"] = issues
    report["failure_categories"] = failure_categories(issues)
    return report


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _path(item: Any) -> tuple[str, ...]:
    path = _value(item, "path", ())
    if isinstance(path, (list, tuple)):
        return tuple(str(segment) for segment in path)
    return ()


def _texts(item: Any) -> tuple[str, ...]:
    texts = _value(item, "texts", ())
    if isinstance(texts, (list, tuple)):
        return tuple(str(text) for text in texts)
    return ()
