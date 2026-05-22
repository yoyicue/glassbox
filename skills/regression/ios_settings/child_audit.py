"""High-value child-page audit for the iOS Settings eval.

Root coverage is the long, strict gate. This probe is intentionally smaller:
it samples a few stable root pages and lets the existing crawler go one level
deeper, so child navigation/recovery can be measured without turning Settings
into a growing rule repository.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from skills.regression.ios_settings import crawler as settings_crawler
from skills.regression.ios_settings import reporting as settings_reporting

DEFAULT_TARGET_ROOT_LABELS = ("通用", "辅助功能")


def probe_high_value_child_audit(
    phone,
    *,
    target_root_labels: Iterable[str] = DEFAULT_TARGET_ROOT_LABELS,
    max_depth: int = 2,
    max_pages: int = 24,
    max_child_scrolls_per_page: int = 1,
    max_candidates_per_page: int = 2,
    strict_child_candidate_audit: bool = False,
) -> dict[str, Any]:
    """Sample child Settings pages using the existing readonly crawler."""
    result = settings_crawler.crawl_high_value_child_settings(
        phone,
        target_root_labels=target_root_labels,
        max_depth=max_depth,
        max_pages=max_pages,
        max_child_scrolls_per_page=max_child_scrolls_per_page,
        max_candidates_per_page=max_candidates_per_page,
        strict_child_candidate_audit=strict_child_candidate_audit,
    )
    return _build_report(
        target_root_labels=result.target_root_labels,
        opened_targets=result.opened_targets,
        target_failures=result.target_failures,
        return_root_failed=result.return_root_failed,
        visits=result.visits,
        limits_hit=result.limits_hit,
        blocked_pages=result.blocked_pages,
        rejected_candidates=result.rejected_candidates,
        navigation_failures=result.navigation_failures,
        trace_payload=result.trace_payload,
        sample_limits_hit=result.sample_limits_hit,
        config=result.config,
    )


def _build_report(
    *,
    target_root_labels: tuple[str, ...],
    opened_targets: list[str],
    target_failures: list[dict[str, str]],
    return_root_failed: bool,
    visits: list[settings_reporting.PageVisit],
    limits_hit: set[str],
    blocked_pages: list[settings_reporting.BlockedPage],
    rejected_candidates: list[settings_reporting.RejectedCandidate],
    navigation_failures: list[settings_reporting.NavigationFailure],
    trace_payload: dict[str, Any] | None,
    sample_limits_hit: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    root_coverage = settings_reporting.computed_root_coverage(visits)
    metrics = settings_reporting.report_metrics(
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=root_coverage,
        require_exhaustive=False,
        min_pages=0,
    )
    if trace_payload is not None:
        settings_reporting.add_trace_metrics(metrics, trace_payload)
    child_paths = [
        visit.path
        for visit in visits
        if len(visit.path) >= 3
    ]
    metrics.update({
        "target_root_count": len(target_root_labels),
        "opened_target_root_count": len(opened_targets),
        "target_failure_count": len(target_failures),
        "child_visit_count": len(child_paths),
        "return_root_failed": return_root_failed,
        "sample_budget_hit": bool(sample_limits_hit),
    })
    known_issues = settings_reporting.known_harness_issues(
        limits_hit=limits_hit,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        metrics=metrics,
        require_exhaustive=False,
    )
    known_issues.extend(_child_audit_issues(
        target_failures=target_failures,
        child_visit_count=len(child_paths),
        return_root_failed=return_root_failed,
    ))
    failure_categories = settings_reporting.failure_categories(known_issues)
    status = "passed" if _passed(
        target_root_labels=target_root_labels,
        opened_targets=opened_targets,
        child_visit_count=len(child_paths),
        limits_hit=limits_hit,
        navigation_failures=navigation_failures,
        return_root_failed=return_root_failed,
    ) else "failed"
    return {
        "probe": "ios_settings_high_value_child_audit",
        "status": status,
        "config": config,
        "target_root_labels": list(target_root_labels),
        "opened_target_roots": opened_targets,
        "target_failures": target_failures,
        "visited_child_paths": [list(path) for path in child_paths],
        "trace": trace_payload,
        "limits_hit": sorted(limits_hit),
        "sample_limits_hit": sample_limits_hit,
        "metrics": metrics,
        "failure_categories": failure_categories,
        "known_issues": known_issues,
        "blocked_pages": [
            {
                "path": list(blocked.path),
                "title": blocked.title,
                "reason": blocked.reason,
                "texts": list(blocked.texts),
            }
            for blocked in blocked_pages
        ],
        "rejected_candidates": [
            {
                "path": list(candidate.path),
                "title": candidate.title,
                "text": candidate.text,
                "reason": candidate.reason,
            }
            for candidate in rejected_candidates
        ],
        "navigation_failures": [
            {
                "path": list(failure.path),
                "title": failure.title,
                "text": failure.text,
                "reason": failure.reason,
            }
            for failure in navigation_failures
        ],
        "visits": [
            {
                "path": list(visit.path),
                "title": visit.title,
                "texts": list(visit.texts),
            }
            for visit in visits
        ],
    }


def _passed(
    *,
    target_root_labels: tuple[str, ...],
    opened_targets: list[str],
    child_visit_count: int,
    limits_hit: set[str],
    navigation_failures: list[settings_reporting.NavigationFailure],
    return_root_failed: bool,
) -> bool:
    return (
        set(opened_targets) == set(target_root_labels)
        and child_visit_count > 0
        and not limits_hit
        and not navigation_failures
        and not return_root_failed
    )


def _child_audit_issues(
    *,
    target_failures: list[dict[str, str]],
    child_visit_count: int,
    return_root_failed: bool,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if target_failures:
        issues.append({
            "id": "ios-settings-child-audit-target-root-unopened",
            "category": "recovery",
            "severity": "blocking",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "A target root page could not be opened for child audit.",
            "evidence": [item["label"] for item in target_failures],
            "next_action": "Use action trace to classify whether foreground, scrolling, search, or tap precision failed.",
        })
    if child_visit_count == 0:
        issues.append({
            "id": "ios-settings-child-audit-no-child-depth",
            "category": "operation",
            "severity": "blocking",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "Child audit opened root targets but did not reach a deeper readonly child page.",
            "evidence": ["visited_child_paths is empty"],
            "next_action": "Inspect candidate typing and safe navigation affordance detection on the target root pages.",
        })
    if return_root_failed:
        issues.append({
            "id": "ios-settings-child-audit-return-root-failed",
            "category": "recovery",
            "severity": "blocking",
            "status": "open",
            "area": "glassbox/ios_recovery",
            "summary": "Child audit could not recover back to Settings root after sampling a child page.",
            "evidence": ["return_root_failed"],
            "next_action": "Review the last action trace and add a generic recovery primitive instead of a page-specific rule.",
        })
    return issues


def write_report(report: dict[str, Any], path: str | Path | None) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
