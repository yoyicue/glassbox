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
    ROOT_COVERAGE_ONLY_LABELS,
    detect_device_unavailable_root_labels,
)
from skills.regression.ios_settings.sections import (
    RootSection,
    SectionVocab,
    root_section_for_canonical_label,
    root_section_ids_for_canonical_labels,
    section_vocab_for,
)


def _section_ids(labels: Iterable[str]) -> list[str]:
    """Project Chinese canonical labels to stable RootSection id values.

    Unknown labels are skipped — the id list is the language-neutral view of the
    same coverage (report wire format v0.2, additive alongside the zh labels)."""
    return root_section_ids_for_canonical_labels(labels)


def _active_section_vocab() -> SectionVocab:
    """SectionVocab for the run's active locale (display labels live here).

    Compatibility bridge: reads language/region off the global config — same
    pattern as policy._active_root_aliases — so the report's display labels track
    the run's locale (en-HK → "Mobile Service") without threading a DI'd vocab
    through the whole crawl. zh stays the internal coverage pivot."""
    from glassbox.config import get_config

    cfg = get_config()
    return section_vocab_for(cfg.language, cfg.region)


def _section_vocab_for_locale_code(locale_code: str | None) -> SectionVocab | None:
    if not locale_code:
        return None
    language, sep, region = locale_code.partition("-")
    if not language:
        return None
    return section_vocab_for(language, region if sep and region else None)


def _canonical_label_for_section(section: RootSection) -> str | None:
    for label in EXPECTED_ROOT_NAV_TEXT_ZH:
        if root_section_for_canonical_label(label) is section:
            return label
    return None


def canonical_root_label_from_text(text: str | None, *, locale_code: str | None = None) -> str | None:
    """Resolve OCR/report text to the internal Chinese canonical root label."""
    label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(str(text or ""))
    if label is not None:
        return label
    vocab = _section_vocab_for_locale_code(locale_code)
    if vocab is None:
        return None
    section = vocab.resolve(text)
    return _canonical_label_for_section(section) if section is not None else None


def _section_display(labels: Iterable[str], vocab: SectionVocab) -> list[str]:
    """Project Chinese canonical labels to the active locale's display labels.

    Additive, parallel to `_section_ids`: same coverage rendered in the run's own
    language (so an en-HK report reads in English). Unknown labels are skipped."""
    out: list[str] = []
    for label in labels:
        section = root_section_for_canonical_label(label)
        if section is None:
            continue
        try:
            out.append(vocab.label(section))
        except KeyError:
            continue
    return out

# Soft limits are reportable perception/budget signals, not strict traversal blockers.
# `settings_search_unavailable` is the Settings-search fallback degrading (it can
# open iOS Spotlight and self-disable); it is soft because root coverage is now
# carried by candidate re-grounding + the multi-pass reset, not by that fallback,
# so its loss does not by itself mean an incomplete pass.
SOFT_LIMITS = frozenset({
    "max_depth", "scroll_overshoot", "settings_search_unavailable",
    # search recovery skipped a section because intermittent back-nav left us
    # off-root; coverage gathered so far is preserved, so it's soft not fatal.
    "return_to_root_failed",
})
EXPECTED_BLOCKED_REASONS = frozenset(
    reason
    for _, _, reason in BLOCKED_CHILD_NAVIGATION_MARKERS
)
EXPECTED_REJECTED_REASONS = frozenset({
    "unsafe_text",
    "unknown_navigation_label",
    "missing_navigation_affordance",
    "section_header",
    "inert_self_loop",
})
EXPECTED_NAVIGATION_FAILURE_REASONS = frozenset({"tap_no_navigation", "search_no_result"})
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


def computed_root_coverage(visits: Sequence[Any], *, locale_code: str | None = None) -> dict[str, list[str]]:
    visited: set[str] = set()
    for visit in visits:
        path = _path(visit)
        if len(path) < 2 or path[0] != "Settings":
            continue
        label = canonical_root_label_from_text(path[1], locale_code=locale_code)
        if label is not None and root_visit_has_label_evidence(visit, label, locale_code=locale_code):
            visited.add(label)
    expected = list(EXPECTED_ROOT_NAV_TEXT_ZH)
    visited_labels = [label for label in expected if label in visited]
    missing_labels = [label for label in expected if label not in visited]
    return {
        "expected": expected,
        "visited": visited_labels,
        "missing": missing_labels,
        # Additive stable section ids (report wire format v0.2). The Chinese
        # `expected`/`visited`/`missing` stay primary for zh compatibility; these
        # parallel `*_ids` make en/zh reports comparable by language-neutral id.
        "expected_ids": _section_ids(expected),
        "visited_ids": _section_ids(visited_labels),
        "missing_ids": _section_ids(missing_labels),
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
    navigation_failures: Sequence[Any] = (),
    *,
    platform: str | None = None,
    phone_model: str | None = None,
) -> dict[str, list[str]]:
    """Enrich root_coverage with entered / visible_only / blocked.

    Additive: keeps ``expected``/``visited``/``missing`` (``visited`` = "seen" =
    entered ∪ visible_only ∪ blocked) and adds the breakdown so callers can tell
    a real section entry from a row merely seen on the root list, and from a page
    deliberately not entered for safety. ``entry_exempt`` is the subset that is
    not required to be opened by design/device capability; ``search_absent`` is
    the subset that Settings search explicitly reported as absent on this run.
    """
    expected = list(base.get("expected", EXPECTED_ROOT_NAV_TEXT_ZH))
    visited = set(base.get("visited", ()))
    missing = set(base.get("missing", ()))
    graph_entered = set(base.get("entered_graph", ()))
    entered = {label for label in expected if _label_entered(label, visits)} | graph_entered
    blocked: set[str] = set()
    for candidate in rejected_candidates:
        label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(str(_value(candidate, "text") or ""))
        if label in expected and label not in entered:
            blocked.add(label)
    coverage_only = _expected_labels(ROOT_COVERAGE_ONLY_LABELS, expected=expected)
    device_unavailable = detect_device_unavailable_root_labels(
        visits,
        navigation_failures,
        platform=platform,
        phone_model=phone_model,
    ) & set(expected)
    entry_exempt = coverage_only | device_unavailable
    search_absent = {
        label
        for label in (
            canonical_root_label_from_text(str(_value(failure, "text") or ""))
            for failure in navigation_failures
            if _value(failure, "reason") == "search_no_result"
        )
        if label in missing
    }
    enriched = {key: list(value) for key, value in base.items()}
    enriched["entered"] = [label for label in expected if label in entered]
    enriched["entered_graph"] = [label for label in expected if label in graph_entered]
    enriched["blocked"] = [label for label in expected if label in blocked]
    enriched["device_unavailable"] = [label for label in expected if label in device_unavailable]
    enriched["entry_exempt"] = [label for label in expected if label in entry_exempt]
    enriched["search_absent"] = [label for label in expected if label in search_absent]
    enriched["required_missing"] = [label for label in expected if label in missing and label not in entry_exempt]
    enriched["visible_only"] = [
        label for label in expected if label in visited and label not in entered and label not in blocked
    ]
    # Additive language-neutral ids + active-locale display labels (zh stays the
    # internal coverage pivot). `*_ids` make en/zh reports comparable by stable
    # RootSection token; `*_display` renders the same coverage in the run's own
    # language so an en-HK report reads "Mobile Service", not "蜂窝网络".
    vocab = _active_section_vocab()
    for key in (
        "expected", "visited", "missing", "entered", "entered_graph", "blocked",
        "visible_only", "device_unavailable", "entry_exempt", "search_absent",
        "required_missing",
    ):
        labels = enriched.get(key, [])
        enriched[f"{key}_ids"] = _section_ids(labels)
        enriched[f"{key}_display"] = _section_display(labels, vocab)
    return enriched


def _expected_labels(labels: Iterable[str], *, expected: Sequence[str]) -> set[str]:
    expected_set = set(expected)
    out: set[str] = set()
    for raw in labels:
        label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(str(raw))
        if label in expected_set:
            out.add(label)
    return out


def root_visit_has_label_evidence(visit: Any, label: str, *, locale_code: str | None = None) -> bool:
    title = _value(visit, "title")
    if isinstance(title, str) and (
        canonical_root_label_from_text(title, locale_code=locale_code) == label
        or DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(title, label)
    ):
        return True
    texts = _value(visit, "texts")
    if not isinstance(texts, list):
        return False
    if label in {"Face ID与密码", "密码"} and blocked_reason_from_texts(texts) == "authentication required":
        return True
    return any(
        canonical_root_label_from_text(str(text), locale_code=locale_code) == label
        or DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(str(text), label)
        for text in texts
    )


def path_has_root_label_evidence(
    visits: Sequence[Any],
    path_key: tuple[str, ...],
    label: str,
    *,
    locale_code: str | None = None,
) -> bool:
    return any(
        _path(visit) == path_key and root_visit_has_label_evidence(
            visit,
            label,
            locale_code=locale_code,
        )
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
    expected = list(root_coverage.get("expected", ()))
    missing = list(root_coverage.get("missing", ()))
    required_missing = list(root_coverage.get("required_missing", missing))
    entry_exempt = list(root_coverage.get("entry_exempt", ()))
    return {
        "visit_count": len(visits),
        "unique_visible_signatures": len(text_signatures),
        "root_expected_count": len(expected),
        "root_required_expected_count": max(0, len(expected) - len(entry_exempt)),
        "root_visited_count": len(root_coverage.get("visited", ())),
        "root_missing_count": len(missing),
        "root_required_missing_count": len(required_missing),
        "root_entry_exempt_count": len(entry_exempt),
        "root_search_absent_count": len(root_coverage.get("search_absent", ())),
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
            and not required_missing
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
    strict_child_candidate_audit: bool = True,
    entry_exempt_labels: Iterable[str] = (),
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
    entry_exempt = set(entry_exempt_labels)
    blocking_navigation_failures = [
        failure for failure in navigation_failures
        if canonical_root_label_from_text(str(_value(failure, "text") or "")) not in entry_exempt
    ]
    if navigation_failures:
        issues.append({
            "id": "ios-settings-navigation-tap-no-transition",
            "category": "operation",
            "severity": "blocking" if require_exhaustive and blocking_navigation_failures else "warning",
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
            "severity": "blocking" if require_exhaustive and strict_child_candidate_audit else "warning",
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
        strict_child_candidate_audit=config.get("strict_child_candidate_audit") is True,
        entry_exempt_labels=root_coverage.get("entry_exempt", ()),
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
