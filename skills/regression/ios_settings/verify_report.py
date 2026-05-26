"""Verifier for iOS Settings read-only walkthrough reports.

The walkthrough test writes a JSON report via IOS_SETTINGS_REPORT. This module
checks that the report is strong enough to count as a full Settings pass:
no traversal limits, no exception marker, all expected root pages visited, and
no dynamic Wi-Fi/Bluetooth rows accidentally recorded as pages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from glassbox.cognition.text_match import compact_text
from skills.regression.ios_settings.policy import (
    DEFAULT_SETTINGS_POLICY,
    EXPECTED_ROOT_NAV_TEXT_ZH,
    FAILURE_CATEGORY_KEYS,
    ROOT_COVERAGE_ONLY_LABELS,
    detect_device_unavailable_root_labels,
)
from skills.regression.ios_settings.reporting import (
    EXPECTED_BLOCKED_REASONS,
    EXPECTED_MIN_VISITS,
    EXPECTED_NAVIGATION_FAILURE_REASONS,
    EXPECTED_REJECTED_REASONS,
    SOFT_LIMITS,
    blocked_reason_from_texts,
    canonical_root_label_from_text,
    computed_root_coverage,
    path_has_root_label_evidence,
)
from skills.regression.ios_settings.sections import root_section_ids_for_canonical_labels

_canonical_expected_root_label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label

DEVICE_UNAVAILABLE_ENV = "IOS_SETTINGS_DEVICE_UNAVAILABLE_ROOT_LABELS"


def entry_exempt_root_labels(extra: Iterable[str] = ()) -> set[str]:
    """Canonical root labels that need not be ENTERED in an exhaustive pass.

    Two distinct reasons, both legitimate (so an exhaustive run can still pass):
    - ``ROOT_COVERAGE_ONLY_LABELS``: the crawler policy deliberately records
      these as visible but never drills in (e.g. 钱包与 Apple Pay), so requiring
      entry contradicts the crawler's own design.
    - device-unavailable labels: sections this *device* cannot open regardless of
      the crawler (e.g. 蜂窝网络 on a no-SIM iPhone). These are opt-in via
      ``--device-unavailable-root`` / ``IOS_SETTINGS_DEVICE_UNAVAILABLE_ROOT_LABELS``
      and default to none, so a capable device still requires them and a real
      navigation regression is never silently hidden.
    """
    labels: set[str] = set()
    env_value = os.getenv(DEVICE_UNAVAILABLE_ENV, "")
    for raw in (*ROOT_COVERAGE_ONLY_LABELS, *env_value.split(","), *extra):
        text = (raw or "").strip()
        if text:
            labels.add(_canonical_expected_root_label(text) or text)
    return labels

UNSAFE_PATH_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"kacier",
        r"iptv",
        r"aiot",
        r"washer",
        r"LYC/LNJ",
        r"我的网络",
        r"其他网络",
        r"My Networks",
        r"Other Networks",
        r"忽略此网络",
        r"Forget This Network",
        r"自动加入",
        r"Auto-Join",
        r"低数据模式",
        r"Low Data Mode",
        r"配置IP",
        r"Configure IP",
        r"IP地址",
        r"IP Address",
    )
)

CONFIG_INT_KEYS = frozenset({
    "min_pages",
    "max_pages",
    "max_depth",
    "max_scrolls_per_page",
    "max_child_scrolls_per_page",
    "max_candidates_per_page",
})
CONFIG_BOOL_KEYS = frozenset({
    "root_coverage_mode",
    "child_navigation_enabled",
    "strict_child_candidate_audit",
    "require_exhaustive",
    "trace_actions",
    "save_view_snapshots",
    "memory_reuse",
})
CONFIG_OPTIONAL_STRING_KEYS = frozenset({"artifact_dir", "memory_dir"})
CONFIG_DEVICE_STRING_KEYS = frozenset({"phone_model", "platform"})



def validate_report(
    report: dict[str, Any],
    *,
    require_exhaustive: bool = True,
    expected_run_id: str | None = None,
    device_unavailable_root: Iterable[str] = (),
) -> list[str]:
    """Return human-readable validation errors. Empty list means pass."""
    errors: list[str] = []
    entry_exempt = entry_exempt_root_labels(device_unavailable_root)

    if expected_run_id is not None and report.get("run_id") != expected_run_id:
        errors.append("report run_id does not match expected run")
    if require_exhaustive and not isinstance(report.get("run_id"), str):
        errors.append("strict report is missing run_id")
    elif require_exhaustive and not report.get("run_id"):
        errors.append("strict report has empty run_id")

    visits = report.get("visits")
    if not isinstance(visits, list) or not visits:
        errors.append("report has no visits")
        visits = []
    report_locale = report.get("locale")
    locale_code = report_locale if isinstance(report_locale, str) else None

    visit_count = report.get("visit_count")
    if visit_count != len(visits):
        errors.append(f"visit_count mismatch: {visit_count!r} != {len(visits)}")

    config = report.get("config")
    if not isinstance(config, dict):
        errors.append("missing or invalid config")
        config = {}
    else:
        _validate_config_schema(config, errors=errors)
    raw_navigation_failures = report.get("navigation_failures")
    navigation_failures_for_exempt = raw_navigation_failures if isinstance(raw_navigation_failures, list) else []
    # Auto-exempt sections this device demonstrably cannot open (e.g. 蜂窝网络 on a
    # no-SIM phone, or iPad-only no-result roots), inferred from the report's own
    # captured text/failures so capable devices still require those sections.
    entry_exempt |= detect_device_unavailable_root_labels(
        visits,
        navigation_failures_for_exempt,
        platform=_optional_config_str(config.get("platform")),
        phone_model=_optional_config_str(config.get("phone_model")),
    )
    if require_exhaustive:
        if config.get("require_exhaustive") is not True:
            errors.append("report was not produced in exhaustive mode")
        root_coverage_mode = config.get("root_coverage_mode")
        child_navigation_enabled = config.get("child_navigation_enabled")
        if root_coverage_mode is not True and child_navigation_enabled is not True:
            errors.append("strict report must enable root coverage mode or child navigation")
        if root_coverage_mode is True and child_navigation_enabled is not False:
            errors.append("strict root coverage report must not enable child navigation")
        if config.get("max_candidates_per_page") != 0:
            errors.append("exhaustive report must not cap candidates per page")
        expected_min_visits = max(1, EXPECTED_MIN_VISITS - len(entry_exempt))
        for key in ("min_pages", "max_pages"):
            value = config.get(key)
            if not isinstance(value, int) or value < expected_min_visits:
                errors.append(f"config.{key} is too small for expected root coverage")
        for key in ("max_depth", "max_scrolls_per_page"):
            value = config.get(key)
            if not isinstance(value, int) or value <= 0:
                errors.append(f"config.{key} must be positive")
        min_pages = config.get("min_pages")
        if isinstance(min_pages, int) and len(visits) < min_pages:
            errors.append(f"visit count is below configured minimum: {len(visits)} < {min_pages}")

    limits_hit = report.get("limits_hit", [])
    if not isinstance(limits_hit, list):
        errors.append("limits_hit is not a list")
        limits_hit = ["<invalid>"]
    if "exception" in limits_hit:
        errors.append("walkthrough ended with an exception")
    hard_limits = [item for item in limits_hit if item not in SOFT_LIMITS]
    if require_exhaustive and hard_limits:
        errors.append(f"walkthrough hit traversal limits: {hard_limits}")

    root_coverage = report.get("root_coverage")
    if not isinstance(root_coverage, dict):
        errors.append("missing root_coverage")
        root_coverage = {}
    expected = root_coverage.get("expected", [])
    reported_visited = root_coverage.get("visited", [])
    missing = root_coverage.get("missing", [])
    computed_root = computed_root_coverage(visits, locale_code=locale_code)
    if expected != list(EXPECTED_ROOT_NAV_TEXT_ZH):
        errors.append("root_coverage.expected does not match current expected root page list")
    if reported_visited != computed_root["visited"]:
        errors.append("root_coverage.visited does not match visits")
    if missing != computed_root["missing"]:
        errors.append("root_coverage.missing does not match visits")
    _validate_root_coverage_ids(
        root_coverage,
        expected=expected,
        visited=reported_visited,
        missing=missing,
        require_exhaustive=require_exhaustive,
        errors=errors,
    )
    unentered_required = [
        label for label in computed_root["missing"] if label not in entry_exempt
    ]
    if require_exhaustive and unentered_required:
        errors.append(f"missing expected root pages: {unentered_required}")

    blocked_pages = report.get("blocked_pages")
    if not isinstance(blocked_pages, list):
        errors.append("missing or invalid blocked_pages list")
        blocked_pages = []
    rejected_candidates = report.get("rejected_candidates")
    if not isinstance(rejected_candidates, list):
        errors.append("missing or invalid rejected_candidates list")
        rejected_candidates = []
    navigation_failures = report.get("navigation_failures")
    if not isinstance(navigation_failures, list):
        errors.append("missing or invalid navigation_failures list")
        navigation_failures = []

    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("missing or invalid metrics")
        metrics = {}
    else:
        _validate_metrics(
            metrics,
            visits=visits,
            root_coverage=root_coverage,
            blocked_pages=blocked_pages,
            rejected_candidates=rejected_candidates,
            navigation_failures=navigation_failures,
            limits_hit=limits_hit,
            errors=errors,
        )

    known_issues = report.get("known_issues")
    if not isinstance(known_issues, list):
        errors.append("missing or invalid known_issues list")
        known_issues = []
    else:
        _validate_known_issues(
            known_issues,
            limits_hit=limits_hit,
            rejected_candidates=rejected_candidates,
            navigation_failures=navigation_failures,
            require_exhaustive=require_exhaustive,
            strict_child_candidate_audit=config.get("strict_child_candidate_audit") is True,
            errors=errors,
        )
    _validate_failure_categories(
        report.get("failure_categories"),
        known_issues=known_issues,
        errors=errors,
    )

    visit_paths: set[tuple[str, ...]] = set()
    visit_texts_by_path: dict[tuple[str, ...], list[str]] = {}
    for idx, visit in enumerate(visits):
        path = visit.get("path") if isinstance(visit, dict) else None
        if not isinstance(path, list) or not path:
            errors.append(f"visit {idx} has invalid path")
            continue
        title = visit.get("title") if isinstance(visit, dict) else None
        texts = visit.get("texts") if isinstance(visit, dict) else None
        if not isinstance(title, str) or not title:
            errors.append(f"visit {idx} has invalid title")
        if not isinstance(texts, list):
            errors.append(f"visit {idx} has invalid texts")
            texts = []
        elif isinstance(title, str) and title and title not in [str(text) for text in texts]:
            errors.append(f"visit {idx} title was not present in OCR texts: {title}")
        path_key = tuple(str(segment) for segment in path)
        visit_paths.add(path_key)
        aggregated_texts = visit_texts_by_path.setdefault(path_key, [])
        aggregated_texts.extend(str(text) for text in texts)
        if path_key[0] != "Settings":
            errors.append(f"visit {idx} path does not start at Settings: {' > '.join(path_key)}")
        if len(path_key) == 2:
            root_label = canonical_root_label_from_text(path_key[1], locale_code=locale_code)
            if (
                root_label is not None
                and not path_has_root_label_evidence(
                    visits,
                    path_key,
                    root_label,
                    locale_code=locale_code,
                )
            ):
                errors.append(
                    f"visit {idx} root path lacks matching page evidence: "
                    f"{path_key[1]} ({root_label})"
                )
        max_depth = config.get("max_depth")
        if isinstance(max_depth, int) and len(path_key) - 1 > max_depth:
            errors.append(f"visit {idx} path exceeds configured max_depth: {' > '.join(path_key)}")
        for segment in path[1:]:
            text = str(segment)
            if any(pattern.search(text) for pattern in UNSAFE_PATH_PATTERNS):
                errors.append(f"unsafe dynamic/settings row in path: {' > '.join(map(str, path))}")
                break

    blocked_keys: set[tuple[tuple[str, ...], str]] = set()
    for idx, blocked in enumerate(blocked_pages):
        if not isinstance(blocked, dict):
            errors.append(f"blocked_pages[{idx}] is not an object")
            continue
        path = blocked.get("path")
        reason = blocked.get("reason")
        texts = blocked.get("texts")
        if not isinstance(path, list) or not path:
            errors.append(f"blocked_pages[{idx}] has invalid path")
            continue
        path_key = tuple(str(segment) for segment in path)
        if path_key[0] != "Settings":
            errors.append(f"blocked_pages[{idx}] path does not start at Settings: {' > '.join(path_key)}")
        if path_key not in visit_paths:
            errors.append(f"blocked page path was not visited: {' > '.join(path_key)}")
        if not isinstance(reason, str) or reason not in EXPECTED_BLOCKED_REASONS:
            errors.append(f"blocked_pages[{idx}] has invalid reason: {reason!r}")
            continue
        if not isinstance(texts, list):
            errors.append(f"blocked_pages[{idx}] has invalid texts")
            texts = []
        evidence_texts = [str(text) for text in texts]
        if blocked_reason_from_texts(evidence_texts) != reason and (
            blocked_reason_from_texts(visit_texts_by_path.get(path_key, [])) != reason
        ):
            errors.append(
                f"blocked_pages[{idx}] reason lacks matching text evidence: "
                f"{' > '.join(path_key)} ({reason})"
            )
        for segment in path_key[1:]:
            if any(pattern.search(segment) for pattern in UNSAFE_PATH_PATTERNS):
                errors.append(f"unsafe dynamic/settings row in blocked path: {' > '.join(path_key)}")
                break
        blocked_keys.add((path_key, reason))

    for visit in visits:
        if not isinstance(visit, dict):
            continue
        path = visit.get("path")
        if not isinstance(path, list) or not path:
            continue
        reason = blocked_reason_from_texts(visit.get("texts"))
        if reason is None:
            continue
        path_key = tuple(str(segment) for segment in path)
        if not _requires_blocked_visit_evidence(path_key, config):
            continue
        if (path_key, reason) not in blocked_keys:
            errors.append(
                "protected page is missing blocked_pages evidence: "
                f"{' > '.join(path_key)} ({reason})"
            )

    for idx, candidate in enumerate(rejected_candidates):
        if not isinstance(candidate, dict):
            errors.append(f"rejected_candidates[{idx}] is not an object")
            continue
        path = candidate.get("path")
        text = candidate.get("text")
        reason = candidate.get("reason")
        if not isinstance(path, list) or not path:
            errors.append(f"rejected_candidates[{idx}] has invalid path")
            continue
        path_key = tuple(str(segment) for segment in path)
        if path_key[0] != "Settings":
            errors.append(f"rejected_candidates[{idx}] path does not start at Settings: {' > '.join(path_key)}")
        if path_key not in visit_paths:
            errors.append(f"rejected candidate path was not visited: {' > '.join(path_key)}")
        if not isinstance(text, str) or not text:
            errors.append(f"rejected_candidates[{idx}] has invalid text")
        elif not _text_present_in_visit(text, visit_texts_by_path.get(path_key, [])):
            errors.append(
                f"rejected_candidates[{idx}] text was not present in visited page: "
                f"{' > '.join(path_key)} > {text}"
            )
        if not isinstance(reason, str) or reason not in EXPECTED_REJECTED_REASONS:
            errors.append(f"rejected_candidates[{idx}] has invalid reason: {reason!r}")
            continue
        if (
            require_exhaustive
            and config.get("strict_child_candidate_audit") is True
            and reason in {"unknown_navigation_label", "missing_navigation_affordance"}
        ):
            errors.append(
                "navigation candidate requires allowlist, affordance, or explicit safety decision: "
                f"{' > '.join(path_key)} > {text}"
            )

    for idx, failure in enumerate(navigation_failures):
        if not isinstance(failure, dict):
            errors.append(f"navigation_failures[{idx}] is not an object")
            continue
        path = failure.get("path")
        text = failure.get("text")
        reason = failure.get("reason")
        if not isinstance(path, list) or not path:
            errors.append(f"navigation_failures[{idx}] has invalid path")
            continue
        path_key = tuple(str(segment) for segment in path)
        if path_key[0] != "Settings":
            errors.append(f"navigation_failures[{idx}] path does not start at Settings: {' > '.join(path_key)}")
        if path_key not in visit_paths:
            errors.append(f"navigation failure path was not visited: {' > '.join(path_key)}")
        # A failure on an entry-exempt root section (ROOT_COVERAGE_ONLY by design,
        # or device-unavailable like 蜂窝网络 on a no-SIM iPhone) is expected: the
        # row legitimately cannot be entered, so the recovery attempt failing is
        # not a regression. Skip the page-evidence and did-not-open checks for it.
        text_entry_exempt = (
            isinstance(text, str)
            and (_canonical_expected_root_label(text) or text) in entry_exempt
        )
        if not isinstance(text, str) or not text:
            errors.append(f"navigation_failures[{idx}] has invalid text")
        elif (
            not text_entry_exempt
            and reason != "search_no_result"
            and not _text_present_in_visit(text, visit_texts_by_path.get(path_key, []))
        ):
            errors.append(
                f"navigation_failures[{idx}] text was not present in visited page: "
                f"{' > '.join(path_key)} > {text}"
            )
        if not isinstance(reason, str) or reason not in EXPECTED_NAVIGATION_FAILURE_REASONS:
            errors.append(f"navigation_failures[{idx}] has invalid reason: {reason!r}")
            continue
        if require_exhaustive and not text_entry_exempt:
            errors.append(f"navigation candidate did not open: {' > '.join(path_key)} > {text}")

    return errors


def _text_present_in_visit(text: str, visit_texts: Iterable[str]) -> bool:
    if text in visit_texts:
        return True
    target = compact_text(text)
    return bool(target) and any(compact_text(item) == target for item in visit_texts)


def _requires_blocked_visit_evidence(path_key: tuple[str, ...], config: dict[str, Any]) -> bool:
    # The root page can show sibling row labels that happen to match a protected
    # child-page marker pair. The crawler deliberately never treats Settings root
    # itself as blocked; mirror that here so a visible "Notifications" sidebar
    # row cannot require blocked-page evidence for the root.
    if path_key == ("Settings",):
        return False
    # In a depth-limited drill-down run, a visit at max_depth is terminal by
    # configuration. Requiring blocked evidence there would reject a safe sample
    # run even though the crawler is not allowed to traverse child rows.
    max_depth = config.get("max_depth")
    return not (
        config.get("child_navigation_enabled") is True
        and isinstance(max_depth, int)
        and len(path_key) - 1 >= max_depth
    )


def _validate_root_coverage_ids(
    root_coverage: dict[str, Any],
    *,
    expected: Any,
    visited: Any,
    missing: Any,
    require_exhaustive: bool,
    errors: list[str],
) -> None:
    for label_key, id_key, labels in (
        ("expected", "expected_ids", expected),
        ("visited", "visited_ids", visited),
        ("missing", "missing_ids", missing),
    ):
        ids = root_coverage.get(id_key)
        if ids is None and not require_exhaustive:
            continue
        if not isinstance(ids, list):
            errors.append(f"root_coverage.{id_key} is missing or not a list")
            continue
        if not isinstance(labels, list):
            continue
        expected_ids = root_section_ids_for_canonical_labels(str(label) for label in labels)
        if ids != expected_ids:
            errors.append(f"root_coverage.{id_key} does not match root_coverage.{label_key}")


def _validate_config_schema(config: dict[str, Any], *, errors: list[str]) -> None:
    for key in sorted(CONFIG_INT_KEYS):
        value = config.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"config.{key} must be an integer")
    for key in sorted(CONFIG_BOOL_KEYS):
        if not isinstance(config.get(key), bool):
            errors.append(f"config.{key} must be a boolean")
    for key in sorted(CONFIG_OPTIONAL_STRING_KEYS):
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"config.{key} must be null or string")
    for key in sorted(CONFIG_DEVICE_STRING_KEYS):
        if key in config and not isinstance(config.get(key), str):
            errors.append(f"config.{key} must be a string")


def _optional_config_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _validate_metrics(
    metrics: dict[str, Any],
    *,
    visits: list[Any],
    root_coverage: dict[str, Any],
    blocked_pages: list[Any],
    rejected_candidates: list[Any],
    navigation_failures: list[Any],
    limits_hit: list[Any],
    errors: list[str],
) -> None:
    expected_counts = {
        "visit_count": len(visits),
        "root_expected_count": len(root_coverage.get("expected", [])),
        "root_required_expected_count": max(
            0,
            len(root_coverage.get("expected", [])) - len(root_coverage.get("entry_exempt", [])),
        ),
        "root_visited_count": len(root_coverage.get("visited", [])),
        "root_missing_count": len(root_coverage.get("missing", [])),
        "root_required_missing_count": len(
            root_coverage.get("required_missing", root_coverage.get("missing", []))
        ),
        "root_entry_exempt_count": len(root_coverage.get("entry_exempt", [])),
        "root_search_absent_count": len(root_coverage.get("search_absent", [])),
        "blocked_page_count": len(blocked_pages),
        "rejected_candidate_count": len(rejected_candidates),
        "navigation_failure_count": len(navigation_failures),
        "limits_hit_count": len(limits_hit),
    }
    optional_metric_counts = {
        "root_required_expected_count",
        "root_required_missing_count",
        "root_entry_exempt_count",
        "root_search_absent_count",
    }
    for key, expected in expected_counts.items():
        if key not in metrics and key in optional_metric_counts:
            continue
        if metrics.get(key) != expected:
            errors.append(f"metrics.{key} mismatch: {metrics.get(key)!r} != {expected}")

    success_count = metrics.get("navigation_success_proxy_count")
    failure_count = metrics.get("navigation_failure_count")
    attempts = metrics.get("navigation_attempts_proxy_count")
    if not all(isinstance(value, int) and value >= 0 for value in (success_count, failure_count, attempts)):
        errors.append("metrics navigation proxy counts must be non-negative integers")
    elif attempts != success_count + failure_count:
        errors.append("metrics.navigation_attempts_proxy_count does not equal successes + failures")

    rate = metrics.get("navigation_success_proxy_rate")
    if attempts == 0:
        if rate is not None:
            errors.append("metrics.navigation_success_proxy_rate must be null when there are no attempts")
    elif not isinstance(rate, (int, float)) or not 0.0 <= float(rate) <= 1.0:
        errors.append("metrics.navigation_success_proxy_rate must be between 0 and 1")

    if metrics.get("exception_hit") != ("exception" in limits_hit):
        errors.append("metrics.exception_hit does not match limits_hit")
    if metrics.get("max_scrolls_hit") != ("max_scrolls_per_page" in limits_hit):
        errors.append("metrics.max_scrolls_hit does not match limits_hit")
    if not isinstance(metrics.get("unique_visible_signatures"), int) or metrics.get("unique_visible_signatures") < 0:
        errors.append("metrics.unique_visible_signatures must be a non-negative integer")
    if not isinstance(metrics.get("exhaustive_ready"), bool):
        errors.append("metrics.exhaustive_ready must be a boolean")


def _validate_known_issues(
    known_issues: list[Any],
    *,
    limits_hit: list[Any],
    rejected_candidates: list[Any],
    navigation_failures: list[Any],
    require_exhaustive: bool,
    strict_child_candidate_audit: bool,
    errors: list[str],
) -> None:
    issue_ids: set[str] = set()
    for idx, issue in enumerate(known_issues):
        if not isinstance(issue, dict):
            errors.append(f"known_issues[{idx}] is not an object")
            continue
        for key in ("id", "category", "severity", "status", "area", "summary", "next_action"):
            if not isinstance(issue.get(key), str) or not issue.get(key):
                errors.append(f"known_issues[{idx}] has invalid {key}")
        if isinstance(issue.get("category"), str) and issue["category"] not in FAILURE_CATEGORY_KEYS:
            errors.append(f"known_issues[{idx}] has unknown category: {issue['category']!r}")
        evidence = issue.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(item, str) and item for item in evidence):
            errors.append(f"known_issues[{idx}] has invalid evidence")
        if isinstance(issue.get("id"), str):
            issue_ids.add(issue["id"])

    hard_limits = [item for item in limits_hit if item not in SOFT_LIMITS]
    if hard_limits and "ios-settings-traversal-limits-hit" not in issue_ids:
        errors.append("known_issues missing traversal-limits issue for limits_hit")
    if navigation_failures and "ios-settings-navigation-tap-no-transition" not in issue_ids:
        errors.append("known_issues missing navigation failure issue")
    unresolved_rejections = [
        candidate
        for candidate in rejected_candidates
        if isinstance(candidate, dict)
        and candidate.get("reason") in {"unknown_navigation_label", "missing_navigation_affordance"}
    ]
    if unresolved_rejections and "ios-settings-navigation-candidate-policy-gap" not in issue_ids:
        errors.append("known_issues missing candidate policy issue")
    blocking_rejections = unresolved_rejections if strict_child_candidate_audit else []
    if require_exhaustive and not hard_limits and not navigation_failures and not blocking_rejections:
        blocking = [
            issue for issue in known_issues
            if isinstance(issue, dict) and issue.get("severity") == "blocking"
        ]
        if blocking:
            errors.append("strict clean report must not carry blocking known_issues")


def _validate_failure_categories(
    failure_categories: Any,
    *,
    known_issues: list[Any],
    errors: list[str],
) -> None:
    if not isinstance(failure_categories, dict):
        errors.append("missing or invalid failure_categories")
        return
    expected_keys = set(FAILURE_CATEGORY_KEYS)
    if set(failure_categories) != expected_keys:
        errors.append("failure_categories keys do not match expected taxonomy")
        return
    for category, values in failure_categories.items():
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            errors.append(f"failure_categories.{category} must be a list of issue ids")
    known_issue_ids = {
        issue.get("id")
        for issue in known_issues
        if isinstance(issue, dict) and isinstance(issue.get("id"), str)
    }
    for category, values in failure_categories.items():
        if not isinstance(values, list):
            continue
        for issue_id in values:
            if issue_id not in known_issue_ids:
                errors.append(
                    f"failure_categories.{category} references unknown known issue id: {issue_id}"
                )
    for issue in known_issues:
        if not isinstance(issue, dict):
            continue
        issue_id = issue.get("id")
        category = issue.get("category")
        if not isinstance(issue_id, str) or not isinstance(category, str):
            continue
        values = failure_categories.get(category)
        if isinstance(values, list) and issue_id not in values:
            errors.append(f"failure_categories.{category} missing known issue id: {issue_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an iOS Settings walkthrough report")
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Only validate report structure and unsafe paths; allow limits/missing root pages.",
    )
    parser.add_argument(
        "--expected-run-id",
        default=None,
        help="Require the report to have the run_id generated for this run_full invocation.",
    )
    parser.add_argument(
        "--device-unavailable-root",
        action="append",
        default=[],
        metavar="LABEL",
        help="Root section this device cannot open (e.g. 蜂窝网络 on a no-SIM iPhone); "
        "do not count it as a missing/failed page. Repeatable, or comma-separated. "
        f"Also read from ${DEVICE_UNAVAILABLE_ENV}.",
    )
    args = parser.parse_args(argv)

    device_unavailable_root = [
        token
        for value in args.device_unavailable_root
        for token in value.split(",")
    ]
    report = json.loads(args.report.read_text(encoding="utf-8"))
    errors = validate_report(
        report,
        require_exhaustive=not args.allow_partial,
        expected_run_id=args.expected_run_id,
        device_unavailable_root=device_unavailable_root,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
