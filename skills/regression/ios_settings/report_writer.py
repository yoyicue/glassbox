"""Report payload assembly for iOS Settings crawler runs.

Owns only JSON payload construction and file writing. Traversal code provides
already collected records, run config, trace payload, and root coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings.config import SettingsRunConfig

PageVisit = settings_reporting.PageVisit
BlockedPage = settings_reporting.BlockedPage
RejectedCandidate = settings_reporting.RejectedCandidate
NavigationFailure = settings_reporting.NavigationFailure


def write_report(
    *,
    report_path: str | Path | None,
    run_config: SettingsRunConfig,
    visits: list[PageVisit],
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    root_coverage: dict[str, list[str]],
    trace_payload: dict[str, Any] | None,
) -> None:
    if not report_path:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_report_payload(
        run_config=run_config,
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=root_coverage,
        trace_payload=trace_payload,
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report_payload(
    *,
    run_config: SettingsRunConfig,
    visits: list[PageVisit],
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    root_coverage: dict[str, list[str]],
    trace_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    root_coverage = settings_reporting.classify_root_coverage(
        root_coverage, visits, rejected_candidates
    )
    metrics = report_metrics(
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=root_coverage,
        require_exhaustive=run_config.require_exhaustive,
        min_pages=run_config.min_pages,
    )
    if trace_payload is not None:
        add_trace_metrics(metrics, trace_payload)
    known_issues = known_harness_issues(
        limits_hit=limits_hit,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        metrics=metrics,
        require_exhaustive=run_config.require_exhaustive,
    )
    return {
        "run_id": run_config.run_id,
        "config": run_config.to_report_config(),
        "trace": trace_payload,
        "limits_hit": sorted(limits_hit),
        "visit_count": len(visits),
        "root_coverage": root_coverage,
        "metrics": metrics,
        "failure_categories": failure_categories(known_issues),
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


def add_trace_metrics(metrics: dict[str, object], trace_payload: dict[str, Any]) -> None:
    settings_reporting.add_trace_metrics(metrics, trace_payload)


def report_metrics(
    *,
    visits: list[PageVisit],
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    root_coverage: dict[str, list[str]],
    require_exhaustive: bool,
    min_pages: int,
) -> dict[str, object]:
    return settings_reporting.report_metrics(
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=root_coverage,
        require_exhaustive=require_exhaustive,
        min_pages=min_pages,
    )


def known_harness_issues(
    *,
    limits_hit: set[str],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    metrics: dict[str, object],
    require_exhaustive: bool,
) -> list[dict[str, object]]:
    return settings_reporting.known_harness_issues(
        limits_hit=limits_hit,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        metrics=metrics,
        require_exhaustive=require_exhaustive,
    )


def failure_categories(known_issues: list[dict[str, object]]) -> dict[str, list[str]]:
    return settings_reporting.failure_categories(known_issues)
