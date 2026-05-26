"""High-value child-page audit for the iOS Settings eval.

Root coverage is the long, strict gate. This probe is intentionally smaller:
it samples a few stable root pages and lets the existing crawler go one level
deeper, so child navigation/recovery can be measured without turning Settings
into a growing rule repository.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from glassbox.config import get_config
from glassbox.runtime import RuntimeUnavailable, build_phone, make_source
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
    allow_blocked_target_roots: bool = False,
    allow_root_only_target_roots: bool = False,
    assume_settings_open: bool = False,
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
        allow_root_only_target_roots=allow_root_only_target_roots,
        assume_settings_open=assume_settings_open,
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
        allow_blocked_target_roots=allow_blocked_target_roots,
        allow_root_only_target_roots=allow_root_only_target_roots,
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
    allow_blocked_target_roots: bool = False,
    allow_root_only_target_roots: bool = False,
) -> dict[str, Any]:
    root_coverage = _target_root_coverage(target_root_labels, visits)
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
    target_roots_with_child, target_roots_missing_child = _target_child_coverage(
        target_root_labels,
        child_paths,
    )
    target_roots_blocked = _target_blocked_coverage(target_root_labels, blocked_pages)
    opened_target_set = set(opened_targets)
    target_roots_unresolved = [
        label for label in target_roots_missing_child
        if not allow_blocked_target_roots or label not in target_roots_blocked
    ]
    if allow_root_only_target_roots:
        target_roots_unresolved = [
            label for label in target_roots_unresolved
            if label not in opened_target_set
        ]
    metrics.update({
        "target_root_count": len(target_root_labels),
        "opened_target_root_count": len(opened_targets),
        "target_failure_count": len(target_failures),
        "child_visit_count": len(child_paths),
        "target_roots_with_child_count": len(target_roots_with_child),
        "target_roots_blocked_count": len(target_roots_blocked),
        "target_roots_missing_child_count": len(target_roots_unresolved),
        "target_roots_without_child_count": len(target_roots_missing_child),
        "return_root_failed": return_root_failed,
        "sample_budget_hit": bool(sample_limits_hit),
        "allow_blocked_target_roots": allow_blocked_target_roots,
        "allow_root_only_target_roots": allow_root_only_target_roots,
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
        target_roots_missing_child=target_roots_unresolved,
        target_roots_blocked=target_roots_blocked,
        return_root_failed=return_root_failed,
        allow_root_only_target_roots=allow_root_only_target_roots,
    ))
    failure_categories = settings_reporting.failure_categories(known_issues)
    status = "passed" if _passed(
        target_root_labels=target_root_labels,
        opened_targets=opened_targets,
        child_visit_count=len(child_paths),
        target_roots_missing_child=target_roots_unresolved,
        target_roots_blocked=target_roots_blocked,
        limits_hit=limits_hit,
        navigation_failures=navigation_failures,
        return_root_failed=return_root_failed,
        allow_root_only_target_roots=allow_root_only_target_roots,
    ) else "failed"
    return {
        "probe": "ios_settings_high_value_child_audit",
        "status": status,
        "config": config,
        "target_root_labels": list(target_root_labels),
        "opened_target_roots": opened_targets,
        "target_failures": target_failures,
        "visited_child_paths": [list(path) for path in child_paths],
        "target_roots_with_child": target_roots_with_child,
        "target_roots_blocked": target_roots_blocked,
        "target_roots_missing_child": target_roots_unresolved,
        "target_roots_without_child": target_roots_missing_child,
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
    target_roots_missing_child: list[str],
    target_roots_blocked: list[str],
    limits_hit: set[str],
    navigation_failures: list[settings_reporting.NavigationFailure],
    return_root_failed: bool,
    allow_root_only_target_roots: bool = False,
) -> bool:
    outcome_count = child_visit_count + len(target_roots_blocked)
    if allow_root_only_target_roots:
        outcome_count += len(opened_targets)
    return (
        set(opened_targets) == set(target_root_labels)
        and outcome_count > 0
        and not target_roots_missing_child
        and not limits_hit
        and not navigation_failures
        and not return_root_failed
    )


def _child_audit_issues(
    *,
    target_failures: list[dict[str, str]],
    child_visit_count: int,
    target_roots_missing_child: list[str],
    target_roots_blocked: list[str],
    return_root_failed: bool,
    allow_root_only_target_roots: bool = False,
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
    if child_visit_count == 0 and not target_roots_blocked and not allow_root_only_target_roots:
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
    if target_roots_missing_child:
        issues.append({
            "id": "ios-settings-child-audit-target-root-no-child-depth",
            "category": "operation",
            "severity": "blocking",
            "status": "open",
            "area": "skills/regression/ios_settings",
            "summary": "One or more target root pages did not reach a deeper readonly child page.",
            "evidence": target_roots_missing_child,
            "next_action": "Inspect safe navigation candidates on each missing target root and add generic iPad split-view handling.",
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


def _target_child_coverage(
    target_root_labels: Iterable[str],
    child_paths: list[tuple[str, ...]],
) -> tuple[list[str], list[str]]:
    expected: list[tuple[str, str]] = []
    for label in target_root_labels:
        canonical = settings_reporting.canonical_root_label_from_text(label) or str(label)
        expected.append((str(label), canonical))
    child_roots = {
        settings_reporting.canonical_root_label_from_text(path[1]) or str(path[1])
        for path in child_paths
        if len(path) >= 3
    }
    with_child = [label for label, canonical in expected if canonical in child_roots]
    missing_child = [label for label, canonical in expected if canonical not in child_roots]
    return with_child, missing_child


def _target_blocked_coverage(
    target_root_labels: Iterable[str],
    blocked_pages: list[settings_reporting.BlockedPage],
) -> list[str]:
    expected: list[tuple[str, str]] = []
    for label in target_root_labels:
        canonical = settings_reporting.canonical_root_label_from_text(label) or str(label)
        expected.append((str(label), canonical))
    blocked_roots = {
        settings_reporting.canonical_root_label_from_text(blocked.path[1]) or str(blocked.path[1])
        for blocked in blocked_pages
        if len(blocked.path) >= 2
    }
    return [label for label, canonical in expected if canonical in blocked_roots]


def _target_root_coverage(
    target_root_labels: Iterable[str],
    visits: list[settings_reporting.PageVisit],
) -> dict[str, list[str]]:
    full_coverage = settings_reporting.computed_root_coverage(visits)
    full_visited = set(full_coverage.get("visited", ()))
    expected: list[str] = []
    expected_with_canonical: list[tuple[str, str | None]] = []
    for label in target_root_labels:
        canonical = settings_reporting.canonical_root_label_from_text(label)
        expected_label = canonical or str(label)
        if expected_label not in expected:
            expected.append(expected_label)
            expected_with_canonical.append((expected_label, canonical))
    noncanonical_visited = _noncanonical_target_root_visits(visits)
    visited = [
        label for label, canonical in expected_with_canonical
        if (label in full_visited if canonical is not None else label in noncanonical_visited)
    ]
    missing = [label for label in expected if label not in visited]
    return {
        "expected": expected,
        "visited": visited,
        "missing": missing,
        "required_missing": missing,
    }


def _noncanonical_target_root_visits(visits: list[settings_reporting.PageVisit]) -> set[str]:
    visited: set[str] = set()
    for visit in visits:
        path = _visit_path(visit)
        if len(path) < 2 or path[0] != "Settings":
            continue
        label = str(path[1])
        if settings_reporting.canonical_root_label_from_text(label) is not None:
            continue
        if _visit_has_noncanonical_label_evidence(visit, label):
            visited.add(label)
    return visited


def _visit_has_noncanonical_label_evidence(
    visit: settings_reporting.PageVisit,
    label: str,
) -> bool:
    label_key = _compact_label(label)
    return (
        _compact_label(_visit_title(visit)) == label_key
        or any(_compact_label(text) == label_key for text in _visit_texts(visit))
    )


def _visit_path(visit: settings_reporting.PageVisit) -> tuple[str, ...]:
    if isinstance(visit, dict):
        return tuple(str(part) for part in visit.get("path", ()))
    return tuple(str(part) for part in getattr(visit, "path", ()))


def _visit_title(visit: settings_reporting.PageVisit) -> str:
    if isinstance(visit, dict):
        return str(visit.get("title", ""))
    return str(getattr(visit, "title", ""))


def _visit_texts(visit: settings_reporting.PageVisit) -> tuple[str, ...]:
    raw = visit.get("texts", ()) if isinstance(visit, dict) else getattr(visit, "texts", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(text) for text in raw)


def _compact_label(text: str) -> str:
    return "".join(str(text or "").casefold().split())


def write_report(report: dict[str, Any], path: str | Path | None) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


@contextlib.contextmanager
def _temporary_env(env: dict[str, str]) -> Iterator[None]:
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(env)
        get_config.cache_clear()
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)
        get_config.cache_clear()


def _run_live_child_audit(args: argparse.Namespace) -> int:
    report_path = args.report.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.unlink()

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("GLASSBOX_PICOKVM", "1")
    env.setdefault("IOS_SETTINGS_TRACE_ACTIONS", "1")
    if args.language is not None:
        env["GLASSBOX_LANGUAGE"] = args.language
    if args.region is not None:
        env["GLASSBOX_REGION"] = args.region
    if args.phone_model is not None:
        env["GLASSBOX_PHONE_MODEL"] = args.phone_model
    if args.platform is not None:
        env["GLASSBOX_PLATFORM"] = args.platform

    runtime = None
    source = None
    try:
        with _temporary_env(env):
            cfg = get_config()
            source = make_source(cfg=cfg)
            runtime = build_phone(source=source, cfg=cfg)
            if args.startup_settle_s > 0:
                time.sleep(args.startup_settle_s)
                with contextlib.suppress(Exception):
                    runtime.phone.invalidate_perceive_cache()
            report = probe_high_value_child_audit(
                runtime.phone,
                target_root_labels=tuple(args.target_root),
                max_depth=args.max_depth,
                max_pages=args.max_pages,
                max_child_scrolls_per_page=args.max_child_scrolls_per_page,
                max_candidates_per_page=args.max_candidates_per_page,
                strict_child_candidate_audit=args.strict_child_candidate_audit,
                allow_blocked_target_roots=args.allow_blocked_target_roots,
                allow_root_only_target_roots=args.allow_root_only_target_roots,
                assume_settings_open=args.assume_settings_open,
            )
    except (RuntimeUnavailable, settings_crawler.SettingsCrawlerUnavailable) as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        if runtime is not None:
            runtime.close(close_source=True)
        elif source is not None and hasattr(source, "close"):
            with contextlib.suppress(Exception):
                source.close()

    write_report(report, report_path)
    print(f"report: {report_path}")
    print(f"status: {report['status']}")
    return 0 if report["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded iOS Settings child audit")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("/tmp/ios-settings-child-audit.json"),
        help="JSON report path written by the probe.",
    )
    parser.add_argument(
        "--target-root",
        action="append",
        default=[],
        help="Settings root label to audit. Repeat for multiple roots. Defaults to the built-in high-value pair.",
    )
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-pages", type=int, default=24)
    parser.add_argument("--max-child-scrolls-per-page", type=int, default=1)
    parser.add_argument("--max-candidates-per-page", type=int, default=2)
    parser.add_argument(
        "--startup-settle-s",
        type=float,
        default=0.0,
        help="Seconds to wait after opening the live source before the first perception.",
    )
    parser.add_argument("--strict-child-candidate-audit", action="store_true")
    parser.add_argument("--allow-blocked-target-roots", action="store_true")
    parser.add_argument("--allow-root-only-target-roots", action="store_true")
    parser.add_argument(
        "--assume-settings-open",
        action="store_true",
        help=(
            "Do not foreground Settings from Home/SpringBoard; fail with a report "
            "if the current screen is not already a Settings root/detail/search surface."
        ),
    )
    parser.add_argument("--language", default=None)
    parser.add_argument("--region", default=None)
    parser.add_argument("--phone-model", default=None)
    parser.add_argument("--platform", default=None)
    args = parser.parse_args(argv)
    if not args.target_root:
        args.target_root = list(DEFAULT_TARGET_ROOT_LABELS)
    return _run_live_child_audit(args)


if __name__ == "__main__":
    raise SystemExit(main())
