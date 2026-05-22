"""Public crawler API for read-only iOS Settings runs.

Boundary: this module owns externally callable Settings crawl entry points and
high-level run assembly. It wires runtime config and trace state from
``core.py`` into focused helper modules, but concrete UI behavior should stay
inside ``bootstrap``, ``navigation``, ``recovery``, ``scrolling``, and
``scene_state``.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from skills.regression.ios_settings import bootstrap as settings_bootstrap
from skills.regression.ios_settings import core as settings_core
from skills.regression.ios_settings import navigation as settings_navigation
from skills.regression.ios_settings import recovery as settings_recovery
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings import scrolling as settings_scrolling
from skills.regression.ios_settings import vlm_rows as settings_vlm_rows
from skills.regression.ios_settings.config import SettingsRunConfig

SettingsCrawlerUnavailable = settings_core.SettingsCrawlerUnavailable


@dataclass
class SettingsCrawlResult:
    visits: list[settings_reporting.PageVisit]
    limits_hit: set[str]
    blocked_pages: list[settings_reporting.BlockedPage]
    rejected_candidates: list[settings_reporting.RejectedCandidate]
    navigation_failures: list[settings_reporting.NavigationFailure]


@dataclass
class SettingsChildCrawlResult:
    target_root_labels: tuple[str, ...]
    opened_targets: list[str]
    target_failures: list[dict[str, str]]
    return_root_failed: bool
    visits: list[settings_reporting.PageVisit]
    limits_hit: set[str]
    blocked_pages: list[settings_reporting.BlockedPage]
    rejected_candidates: list[settings_reporting.RejectedCandidate]
    navigation_failures: list[settings_reporting.NavigationFailure]
    trace_payload: dict[str, Any] | None
    sample_limits_hit: list[str]
    config: dict[str, Any]


def crawl_readonly_settings(
    phone,
    *,
    config: SettingsRunConfig | None = None,
    require_real_effector: bool = True,
) -> SettingsCrawlResult:
    """Run the read-only Settings crawler without pytest fixture semantics."""
    if require_real_effector:
        has_real_effector = getattr(phone, "has_real_effector", None)
        if not callable(has_real_effector) or not has_real_effector():
            raise SettingsCrawlerUnavailable(
                "requires a connected PicoKVM/real effector and HDMI capture"
            )

    with _temporary_run_config(config):
        return _run_core_crawl(phone)


def crawl_high_value_child_settings(
    phone,
    *,
    target_root_labels: Iterable[str],
    max_depth: int,
    max_pages: int,
    max_child_scrolls_per_page: int,
    max_candidates_per_page: int,
    strict_child_candidate_audit: bool,
) -> SettingsChildCrawlResult:
    """Sample stable child Settings pages without exposing walkthrough internals."""
    target_labels = tuple(target_root_labels)
    run_config = SettingsRunConfig.for_child_audit(
        max_depth=max_depth,
        max_pages=max_pages,
        max_child_scrolls_per_page=max_child_scrolls_per_page,
        max_candidates_per_page=max_candidates_per_page,
        strict_child_candidate_audit=strict_child_candidate_audit,
    )
    visits: list[settings_reporting.PageVisit] = []
    blocked_pages: list[settings_reporting.BlockedPage] = []
    rejected_candidates: list[settings_reporting.RejectedCandidate] = []
    navigation_failures: list[settings_reporting.NavigationFailure] = []
    limits_hit: set[str] = set()
    target_failures: list[dict[str, str]] = []
    opened_targets: list[str] = []
    return_root_failed = False

    previous_trace = settings_core._ACTIVE_TRACE
    traced_phone, trace = settings_core._wrap_phone_with_trace_if_enabled(phone)
    settings_core._ACTIVE_TRACE = trace
    try:
        with _temporary_run_config(run_config):
            _open_settings_from_home_if_visible(traced_phone)
            _return_to_settings_root(traced_phone)
            for label in target_labels:
                if len(visits) >= max_pages:
                    limits_hit.add("max_pages")
                    break
                if not _open_target_root_page(traced_phone, label):
                    target_failures.append({"label": label, "reason": "target_root_not_opened"})
                    _return_to_settings_root(traced_phone)
                    continue
                opened_targets.append(label)
                _crawl_current_page(
                    traced_phone,
                    path=("Settings", label),
                    visits=visits,
                    seen_sigs=set(),
                    depth=1,
                    max_depth=max_depth,
                    limits_hit=limits_hit,
                    blocked_pages=blocked_pages,
                    rejected_candidates=rejected_candidates,
                    navigation_failures=navigation_failures,
                )
                try:
                    _return_to_settings_root(traced_phone)
                except AssertionError:
                    return_root_failed = True
                    limits_hit.add("return_root_failed")
                    break
    except BaseException:
        limits_hit.add("exception")
        raise
    finally:
        if trace is not None:
            trace.close()
        settings_core._ACTIVE_TRACE = previous_trace

    sample_limits_hit = sorted(
        limit for limit in limits_hit
        if limit in {"max_candidates_per_page", "max_depth", "max_scrolls_per_page"}
    )
    limits_hit.difference_update(sample_limits_hit)
    return SettingsChildCrawlResult(
        target_root_labels=target_labels,
        opened_targets=opened_targets,
        target_failures=target_failures,
        return_root_failed=return_root_failed,
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        trace_payload=trace.payload if trace is not None else None,
        sample_limits_hit=sample_limits_hit,
        config=run_config.to_child_audit_report_config(),
    )


@contextmanager
def _temporary_run_config(config: SettingsRunConfig | None) -> Iterator[None]:
    if config is None:
        yield
        return
    values = config.to_walkthrough_runtime_globals()
    old_values = {name: getattr(settings_core, name) for name in values}
    try:
        for name, value in values.items():
            setattr(settings_core, name, value)
        yield
    finally:
        for name, value in old_values.items():
            setattr(settings_core, name, value)


def _run_core_crawl(phone) -> SettingsCrawlResult:
    previous_trace = settings_core._ACTIVE_TRACE
    phone, settings_core._ACTIVE_TRACE = settings_core._wrap_phone_with_trace_if_enabled(phone)
    trace = settings_core._ACTIVE_TRACE
    settings_vlm_rows.reset_row_state()

    visits: list[settings_reporting.PageVisit] = []
    blocked_pages: list[settings_reporting.BlockedPage] = []
    rejected_candidates: list[settings_reporting.RejectedCandidate] = []
    navigation_failures: list[settings_reporting.NavigationFailure] = []
    limits_hit: set[str] = set()
    trace_payload: dict[str, Any] | None = None
    report_written = False
    try:
        _open_settings_from_home_if_visible(phone)
        _scroll_to_vertical_boundary(phone, direction="up")
        _crawl_current_page(
            phone,
            path=("Settings",),
            visits=visits,
            seen_sigs=set(),
            depth=0,
            max_depth=settings_core.MAX_DEPTH,
            limits_hit=limits_hit,
            blocked_pages=blocked_pages,
            rejected_candidates=rejected_candidates,
            navigation_failures=navigation_failures,
        )
        _return_to_settings_root(phone)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        limits_hit.add("startup_skip" if isinstance(exc, SettingsCrawlerUnavailable) else "exception")
        if trace is not None:
            trace.close()
            trace_payload = trace.payload
        settings_core._write_report(
            visits,
            limits_hit,
            blocked_pages,
            rejected_candidates,
            navigation_failures,
            trace_payload=trace_payload,
        )
        report_written = True
        raise
    finally:
        if not report_written and trace is not None:
            trace.close()
            trace_payload = trace.payload
        settings_core._ACTIVE_TRACE = previous_trace
    settings_core._write_report(
        visits,
        limits_hit,
        blocked_pages,
        rejected_candidates,
        navigation_failures,
        trace_payload=trace_payload,
    )
    return SettingsCrawlResult(
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
    )


def _open_target_root_page(phone, label: str) -> bool:
    _return_to_settings_root(phone)
    _scroll_to_vertical_boundary(phone, direction="up")
    row = settings_navigation.open_visible_or_scroll_to_row(
        phone,
        (label,),
        settings_core._navigation_actions(),
    )
    if row is not None:
        before = phone.perceive()
        settings_navigation.tap_settings_row(phone, row, settings_core._navigation_actions())
        time.sleep(1.0)
        phone.invalidate_perceive_cache()
        after = phone.perceive()
        if not settings_scene_state.same_page_after_tap(before, after, expected_title=label):
            return True
    return bool(settings_navigation.open_root_label_via_search(
        phone,
        label,
        settings_core._navigation_actions(),
    ))


def _open_settings_from_home_if_visible(phone) -> None:
    settings_bootstrap.open_settings_from_home_if_visible(phone, settings_core._bootstrap_actions())


def _return_to_settings_root(phone) -> None:
    settings_recovery.return_to_settings_root(phone, settings_core._recovery_actions())


def _scroll_to_vertical_boundary(phone, *, direction: str) -> None:
    settings_scrolling.scroll_to_vertical_boundary(
        phone,
        direction=direction,
        action_intent=settings_core._action_intent,
        texts=settings_scene_state.texts,
    )


def _crawl_current_page(phone, **kwargs) -> None:
    settings_navigation.crawl_current_page(
        phone,
        actions=settings_core._navigation_actions(),
        **kwargs,
    )
