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
from contextlib import contextmanager, suppress
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
    allow_root_only_target_roots: bool = False,
    assume_settings_open: bool = False,
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
    root_only_single_target = (
        allow_root_only_target_roots
        and len(target_labels) == 1
        and max_depth <= 1
        and max_child_scrolls_per_page <= 0
        and max_candidates_per_page <= 0
    )

    previous_trace = settings_core._ACTIVE_TRACE
    trace = None
    try:
        with _temporary_run_config(run_config):
            traced_phone, trace = settings_core._wrap_phone_with_trace_if_enabled(phone)
            settings_core._ACTIVE_TRACE = trace
            startup_not_settings = False
            if assume_settings_open:
                startup_not_settings = not _current_scene_is_settings_context(traced_phone)
                if startup_not_settings:
                    limits_hit.add("startup_not_settings")
                    target_failures.extend(
                        {"label": label, "reason": "settings_not_foregrounded"}
                        for label in target_labels
                    )
            else:
                _open_settings_from_home_if_visible(traced_phone)
            if not startup_not_settings:
                already_open_target = False
                if root_only_single_target and target_labels and hasattr(traced_phone, "perceive"):
                    already_open_target = _opened_requested_root(traced_phone.perceive(), target_labels[0])
                visible_target_root = (
                    _is_ipad_target(traced_phone)
                    and any(_visible_root_candidate_for_label(traced_phone, label) is not None for label in target_labels)
                )
                if not already_open_target and not visible_target_root:
                    try:
                        _return_to_settings_root(traced_phone)
                    except settings_recovery.SettingsRootUnreachable:
                        return_root_failed = True
                        limits_hit.add("return_root_failed")
                        target_failures.extend(
                            {"label": label, "reason": "settings_root_unreachable"}
                            for label in target_labels
                        )
                for label in (() if return_root_failed else target_labels):
                    if len(visits) >= max_pages:
                        limits_hit.add("max_pages")
                        break
                    try:
                        opened_target = _open_target_root_page(traced_phone, label)
                    except settings_recovery.SettingsRootUnreachable:
                        opened_target = False
                        return_root_failed = True
                        limits_hit.add("return_root_failed")
                        target_failures.append({"label": label, "reason": "settings_root_unreachable"})
                        break
                    if not opened_target:
                        target_failures.append({"label": label, "reason": "target_root_not_opened"})
                        try:
                            _return_to_settings_root(traced_phone)
                        except settings_recovery.SettingsRootUnreachable:
                            # Same soft-failure contract as post-visit recovery:
                            # keep the unopened target evidence instead of letting
                            # a dirty Settings search state crash the probe.
                            return_root_failed = True
                            limits_hit.add("return_root_failed")
                            break
                        continue
                    opened_targets.append(label)
                    try:
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
                    except settings_recovery.SettingsRootUnreachable:
                        return_root_failed = True
                        limits_hit.add("return_root_failed")
                        break
                    if not root_only_single_target:
                        try:
                            _return_to_settings_root(traced_phone)
                        except settings_recovery.SettingsRootUnreachable:
                            # Soft return-failure path: record it and stop the child
                            # audit gracefully instead of letting the distinct recovery
                            # exception fall through to the crash/re-raise handler below.
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
    report_config = run_config.to_child_audit_report_config()
    report_config["assume_settings_open"] = assume_settings_open
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
        config=report_config,
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
    settings_scene_state.reset_scene_context_state()

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
        try:
            _return_to_settings_root(phone)
        except settings_recovery.SettingsRootUnreachable:
            # Final cleanup return only; its failure (intermittent back-nav,
            # e.g. stranded on Spotlight) must not mark the whole run as a crash
            # — the crawl already gathered its coverage. Record it soft and let
            # the normal report write proceed.
            limits_hit.add("return_to_root_failed")
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
            phone=phone,
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
        phone=phone,
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
    if hasattr(phone, "perceive"):
        current = phone.perceive()
        if _opened_requested_root(current, label):
            return True
    if _is_ipad_target(phone) and _tap_visible_root_candidate(phone, label):
        return True
    _return_to_settings_root(phone)
    _scroll_to_vertical_boundary(phone, direction="up")
    current = phone.perceive()
    if _opened_requested_root(current, label):
        return True
    row = _visible_root_candidate_for_label(phone, label)
    if row is not None and _tap_root_candidate_and_confirm(phone, label, row):
        return True
    row = settings_navigation.open_visible_or_scroll_to_row(
        phone,
        (label,),
        settings_core._navigation_actions(),
    )
    if row is not None and _tap_root_candidate_and_confirm(phone, label, row):
        return True
    if settings_navigation.open_root_label_via_search(
        phone,
        label,
        settings_core._navigation_actions(),
    ):
        return True
    return _wait_opened_requested_root(phone, label)


def _tap_visible_root_candidate(phone, label: str) -> bool:
    row = _visible_root_candidate_for_label(phone, label)
    if row is None:
        return False
    return _tap_root_candidate_and_confirm(phone, label, row)


def _tap_root_candidate_and_confirm(phone, label: str, row) -> bool:
    before = phone.perceive()
    settings_navigation.tap_settings_row(phone, row, settings_core._navigation_actions())
    time.sleep(1.0)
    phone.invalidate_perceive_cache()
    after = phone.perceive()
    if _opened_requested_root(after, label):
        return True
    if _wait_opened_requested_root(phone, label):
        return True
    return not _is_ipad_target(phone) and not settings_scene_state.same_page_after_tap(
        before,
        after,
        expected_title=label,
    )


def _current_scene_is_settings_context(phone) -> bool:
    if not hasattr(phone, "perceive"):
        return False
    scene = phone.perceive()
    if (
        settings_core._scene_is_settings_root(scene)
        or settings_core._scene_looks_like_settings_detail(scene)
        or settings_core._is_settings_search_scene(scene)
    ):
        return True
    return settings_core._scene_kind(scene, phone=phone) in {
        "settings_root",
        "settings_detail",
        "settings_search",
        "settings_search_home",
        "settings_search_results",
        "settings_blocked_safety",
    }


def _visible_root_candidate_for_label(phone, label: str):
    actions = settings_core._navigation_actions()
    scene = phone.perceive()
    if actions.is_settings_search_scene(scene):
        return None
    if _is_ipad_target(phone):
        sidebar_candidate = _visible_ipad_sidebar_root_candidate_for_label(phone, scene, label)
        if sidebar_candidate is not None:
            return sidebar_candidate
    target = actions.canonical_expected_root_label(label) or label
    candidates = actions.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
    )
    for candidate in candidates:
        text = (candidate.text or "").strip()
        if (
            text == label
            or actions.canonical_expected_root_label(text) == target
            or actions.match_any((candidate,), (label,)) is not None
        ):
            return candidate
    return None


def _visible_ipad_sidebar_root_candidate_for_label(phone, scene, label: str):
    try:
        from glassbox.ipados.scene import sidebar_right_x

        width, height = getattr(scene, "viewport_size", None) or phone.viewport_size()
        sidebar_right = sidebar_right_x(width)
    except Exception:
        return None
    actions = settings_core._navigation_actions()
    target = actions.canonical_expected_root_label(label) or label
    matches = []
    for element in scene.elements:
        text = (element.text or "").strip()
        if not text:
            continue
        cx, cy = element.box.center
        if cx > sidebar_right or cy < int(height * 0.10) or cy > int(height * 0.96):
            continue
        if _is_ipad_sidebar_top_search_affordance(text, cy=cy, height=height):
            continue
        if (
            text == label
            or actions.canonical_expected_root_label(text) == target
            or actions.match_any((element,), (label,)) is not None
        ):
            matches.append(element)
    if not matches:
        return None
    matches.sort(key=lambda element: (element.box.center[1], element.box.center[0]))
    return matches[0]


def _is_ipad_sidebar_top_search_affordance(text: str, *, cy: float, height: int) -> bool:
    if cy > int(height * 0.18):
        return False
    compact = "".join(str(text or "").split()).casefold()
    return compact in {"search", "qsearch", "q搜索", "搜索"} or str(text or "").lower().startswith("q ")


def _opened_requested_root(scene, label: str) -> bool:
    requested = settings_scene_state.canonical_expected_root_label(label) or label
    title = settings_scene_state.page_title(scene)
    return (
        settings_scene_state.canonical_expected_root_label(title) == requested
        or settings_scene_state.title_matches_navigation_label(title, label)
    )


def _wait_opened_requested_root(phone, label: str, *, polls: int = 4, interval_s: float = 0.4) -> bool:
    for _ in range(max(1, polls)):
        time.sleep(interval_s)
        with suppress(Exception):
            phone.invalidate_perceive_cache()
        if _opened_requested_root(phone.perceive(), label):
            return True
    return False


def _is_ipad_target(phone) -> bool:
    model = str(getattr(getattr(phone, "device_geometry", None), "model", "") or "")
    return model.lower().replace("-", "_").startswith("ipad")


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
