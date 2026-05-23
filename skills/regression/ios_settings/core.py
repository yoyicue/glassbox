"""Compatibility facade for the read-only iOS Settings crawler.

Run on real hardware:

    GLASSBOX_PICOKVM=1 pytest skills/regression/ios_settings/test_readonly_walkthrough.py

For a full audit run, write a report and verify it:

    IOS_SETTINGS_REQUIRE_EXHAUSTIVE=1 IOS_SETTINGS_REPORT=/tmp/ios-settings-full.json \
      GLASSBOX_PICOKVM=1 pytest skills/regression/ios_settings/test_readonly_walkthrough.py
    python -m skills.regression.ios_settings.verify_report /tmp/ios-settings-full.json

The test intentionally avoids modifying settings. It only uses glassbox/PicoKVM
touch to foreground Settings, open navigation rows, observe page text, and
return through the visible back affordance.

Design boundary: crawler orchestration lives in ``crawler.py``. Concrete
behaviors live in focused modules: ``bootstrap`` for foregrounding,
``scene_state`` for pure scene decisions, ``page_records`` for visit/report
inputs, ``navigation`` for traversal, ``recovery`` for return-to-root,
``scrolling`` for HID scroll handling, and ``report_writer`` for JSON output.
This module keeps runtime globals, trace glue, and private compatibility
wrappers for existing callers while new code should call the focused modules.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from glassbox.action.semantics import action_verdict
from glassbox.cognition import UIElement, find_text
from glassbox.effector import ActionResult
from glassbox.ios.progress import (
    screen_signature as _screen_signature,
)
from glassbox.ios.progress import (
    scroll_outcome as _scroll_outcome,
)
from glassbox.ios.progress import (
    trace_payload_no_progress as _trace_payload_no_progress,
)
from glassbox.ios.safe_area import IOSSafeArea
from glassbox.ios.springboard import open_app_from_springboard
from skills.regression.ios_settings import bootstrap as settings_bootstrap
from skills.regression.ios_settings import navigation as settings_navigation
from skills.regression.ios_settings import page_records as settings_page_records
from skills.regression.ios_settings import policy as settings_policy
from skills.regression.ios_settings import recovery as settings_recovery
from skills.regression.ios_settings import report_writer as settings_report_writer
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings import scrolling as settings_scrolling
from skills.regression.ios_settings import search_ui as settings_search_ui
from skills.regression.ios_settings import trace as settings_trace
from skills.regression.ios_settings import vlm_rows as settings_vlm_rows
from skills.regression.ios_settings.config import SettingsRunConfig

DEFAULT_SETTINGS_POLICY = settings_policy.DEFAULT_SETTINGS_POLICY
BLOCKED_CHILD_NAVIGATION_MARKERS = settings_policy.BLOCKED_CHILD_NAVIGATION_MARKERS
EXPECTED_ROOT_NAV_TEXT = settings_policy.EXPECTED_ROOT_NAV_TEXT
EXPECTED_ROOT_NAV_TEXT_ZH = settings_policy.EXPECTED_ROOT_NAV_TEXT_ZH
FAILURE_CATEGORY_KEYS = settings_policy.FAILURE_CATEGORY_KEYS
HARNESS_APP_MARKERS = settings_policy.HARNESS_APP_MARKERS
ROOT_LABEL_ALIASES = settings_policy.ROOT_LABEL_ALIASES
ROOT_SEARCH_QUERIES = settings_policy.ROOT_SEARCH_QUERIES
ROOT_TITLE = settings_policy.ROOT_TITLE
SAFE_NAV_TEXT = settings_policy.SAFE_NAV_TEXT

RUN_CONFIG = SettingsRunConfig.from_env()
MIN_PAGES_VISITED = RUN_CONFIG.min_pages
MAX_PAGES_VISITED = RUN_CONFIG.max_pages
MAX_DEPTH = RUN_CONFIG.max_depth
MAX_SCROLLS_PER_PAGE = RUN_CONFIG.max_scrolls_per_page
ROOT_COVERAGE_MODE = RUN_CONFIG.root_coverage_mode
MAX_CHILD_SCROLLS_PER_PAGE = RUN_CONFIG.max_child_scrolls_per_page
# Times the root crawl may reset to the top and re-pass when expected sections
# remain missing after a fling overshoot. Each reset is one extra top→bottom
# pass; the union of passes converges on full coverage despite fling variance.
MAX_ROOT_SCROLL_RESETS = int(os.getenv("IOS_SETTINGS_MAX_ROOT_SCROLL_RESETS", "2"))
CHILD_NAVIGATION_ENABLED = RUN_CONFIG.child_navigation_enabled
STRICT_CHILD_CANDIDATE_AUDIT = RUN_CONFIG.strict_child_candidate_audit
MAX_CANDIDATES_PER_PAGE = RUN_CONFIG.max_candidates_per_page
REQUIRE_EXHAUSTIVE = RUN_CONFIG.require_exhaustive
REPORT_PATH = RUN_CONFIG.report_path
RUN_ID = RUN_CONFIG.run_id
TRACE_ACTIONS = RUN_CONFIG.trace_actions
SAVE_VIEW_SNAPSHOTS = RUN_CONFIG.save_view_snapshots
ARTIFACT_DIR = RUN_CONFIG.artifact_dir
MEMORY_DIR = RUN_CONFIG.memory_dir
MEMORY_REUSE = RUN_CONFIG.memory_reuse

_SOFT_LIMITS = settings_reporting.SOFT_LIMITS
# 滚动类 HID op:有效/无效要按 scroll_outcome 判,不能用 same_visible_page
# (一次正常半屏滚动重叠本就 >72%,会被 same_visible_page 冤判成无进展)。
IOS_BACK_MOD = 0x08
IOS_BACK_KEY = 0x2F

PageVisit = settings_reporting.PageVisit
BlockedPage = settings_reporting.BlockedPage
RejectedCandidate = settings_reporting.RejectedCandidate
NavigationFailure = settings_reporting.NavigationFailure

ViewportKey = tuple[tuple[str, ...], tuple[str, ...]]
_ACTIVE_TRACE: SettingsRunTrace | None = None


class SettingsCrawlerUnavailable(RuntimeError):
    """Raised when the Settings crawler cannot acquire the required device state."""


def _default_artifact_dir() -> Path | None:
    if ARTIFACT_DIR:
        return Path(ARTIFACT_DIR)
    if REPORT_PATH:
        report = Path(REPORT_PATH)
        return report.with_suffix(".artifacts")
    return None


def _current_run_config() -> SettingsRunConfig:
    return SettingsRunConfig(
        min_pages=MIN_PAGES_VISITED,
        max_pages=MAX_PAGES_VISITED,
        max_depth=MAX_DEPTH,
        max_scrolls_per_page=MAX_SCROLLS_PER_PAGE,
        root_coverage_mode=ROOT_COVERAGE_MODE,
        max_child_scrolls_per_page=MAX_CHILD_SCROLLS_PER_PAGE,
        child_navigation_enabled=CHILD_NAVIGATION_ENABLED,
        strict_child_candidate_audit=STRICT_CHILD_CANDIDATE_AUDIT,
        max_candidates_per_page=MAX_CANDIDATES_PER_PAGE,
        require_exhaustive=REQUIRE_EXHAUSTIVE,
        report_path=REPORT_PATH,
        run_id=RUN_ID,
        trace_actions=TRACE_ACTIONS,
        save_view_snapshots=SAVE_VIEW_SNAPSHOTS,
        artifact_dir=ARTIFACT_DIR,
        memory_dir=MEMORY_DIR,
        memory_reuse=MEMORY_REUSE,
    )


def _scene_type(scene) -> str:
    return settings_scene_state.scene_type(scene)


def _phone_viewport_size(phone) -> tuple[int, int] | None:
    return settings_scene_state.phone_viewport_size(phone)


def _classify_ios_scene(scene, phone=None):
    return settings_scene_state.classify_ios_scene(scene, phone=phone)


def _scene_kind(scene, phone=None) -> str:
    return settings_scene_state.scene_kind(scene, phone=phone)


def _return_state_signature(scene, phone=None) -> tuple[str, tuple[str, ...]]:
    return settings_scene_state.return_state_signature(scene, phone=phone)


TracedSettingsPhone = settings_trace.TracedSettingsPhone


def _trace_callbacks() -> settings_trace.SettingsTraceCallbacks:
    return settings_trace.SettingsTraceCallbacks(
        texts=_texts,
        classify_scene=_classify_ios_scene,
        scene_type=_scene_type,
        page_title=_page_title,
        screen_signature=_screen_signature,
        scroll_outcome=_scroll_outcome,
        trace_payload_no_progress=_trace_payload_no_progress,
    )


class SettingsRunTrace(settings_trace.SettingsRunTrace):
    def __init__(self, artifact_dir: Path, *, trace_actions: bool, save_view_snapshots: bool):
        super().__init__(
            artifact_dir,
            trace_actions=trace_actions,
            save_view_snapshots=save_view_snapshots,
            run_id=RUN_ID,
            callbacks=_trace_callbacks(),
        )


def _wrap_phone_with_trace_if_enabled(phone):
    if not (TRACE_ACTIONS or SAVE_VIEW_SNAPSHOTS):
        return phone, None
    artifact_dir = _default_artifact_dir()
    return settings_trace.wrap_phone_with_trace(
        phone,
        artifact_dir=artifact_dir,
        trace_actions=TRACE_ACTIONS,
        save_view_snapshots=SAVE_VIEW_SNAPSHOTS,
        run_id=RUN_ID,
        callbacks=_trace_callbacks(),
    )


def _action_intent(phone, name: str, **metadata: Any):
    return settings_trace.action_intent(phone, name, **metadata)


def _record_action_verdict(phone, result: Any) -> bool:
    verdict = action_verdict(result)
    with suppress(Exception):
        phone._ios_settings_last_action_verdict = verdict
    return verdict.accepted


def _accept_tolerating_unknown(phone, result: Any) -> bool:
    """Accept a Settings Search focus/open tap unless it semantically failed.

    These taps frequently score `unknown`: the search scene (search field +
    keyboard) resembles the root closely, and focusing a field has no
    verifiable scene change. Treat `unknown` as continue because each step is
    confirmed by a downstream check (search scene appears, a query types, a
    result matches). A genuine failure (transport error, `failed`, `partial`,
    `approval_required`) is still rejected.
    """
    verdict = action_verdict(result, unknown_policy="continue")
    with suppress(Exception):
        phone._ios_settings_last_action_verdict = verdict
    return verdict.accepted


def _match_any(elements: Iterable[UIElement], labels: Iterable[str], *, fuzzy: float = 0.72):
    for label in labels:
        hit = find_text(elements, label, fuzzy_ratio=fuzzy)
        if hit is not None:
            return hit
    return None


def _wait_any_text(phone, labels: Iterable[str], *, timeout: float = 4.0) -> UIElement | None:
    deadline = time.monotonic() + timeout
    last: UIElement | None = None
    while time.monotonic() < deadline:
        scene = phone.perceive()
        last = _match_any(scene.elements, labels)
        if last is not None:
            return last
        time.sleep(0.35)
    return last


def _is_settings_root(phone) -> bool:
    return settings_scene_state.is_settings_root(phone)


def _scene_is_settings_root(scene) -> bool:
    return settings_scene_state.scene_is_settings_root(scene)


def _has_visible_back_affordance(scene) -> bool:
    return settings_scene_state.has_visible_back_affordance(scene)


def _scene_looks_like_settings_detail(scene) -> bool:
    return settings_scene_state.scene_looks_like_settings_detail(scene)


def _open_app_from_springboard(phone, labels, *, max_pages: int = 8, settle_s: float = 0.8) -> bool:
    labels = tuple(labels)
    if labels:
        opener = getattr(phone, "open_app", None)
        if callable(opener):
            try:
                opened = opener(labels[0], aliases=labels[1:], max_pages=max_pages, settle_s=settle_s)
            except Exception:
                opened = False
            if bool(getattr(opened, "ok", opened)):
                return True
    try:
        return open_app_from_springboard(
            phone,
            labels,
            max_pages=max_pages,
            settle_s=settle_s,
            icon_map=getattr(phone, "icon_map", None),
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return open_app_from_springboard(phone, labels, max_pages=max_pages)


def _bootstrap_actions() -> settings_bootstrap.SettingsBootstrapActions:
    return settings_bootstrap.SettingsBootstrapActions(
        action_intent=_action_intent,
        wait_settings_root=_wait_settings_root,
        is_settings_root=_is_settings_root,
        scene_looks_like_settings_detail=_scene_looks_like_settings_detail,
        try_return_to_settings_root=_try_return_to_settings_root,
        match_any=_match_any,
        harness_app_markers=HARNESS_APP_MARKERS,
        root_title=ROOT_TITLE,
        open_app_from_springboard=_open_app_from_springboard,
        ensure_settings_root=_ensure_settings_root,
        is_settings_search_scene=_is_settings_search_scene,
        return_to_settings_root=_return_to_settings_root,
        scene_kind=_scene_kind,
        tap_visible_settings_root_result_from_system_search=_tap_visible_settings_root_result_from_system_search,
        unavailable_error=SettingsCrawlerUnavailable,
    )


def _wait_settings_root(phone, *, timeout: float = 10.0) -> bool:
    return settings_bootstrap.wait_settings_root(phone, _bootstrap_actions(), timeout=timeout)


def _texts(scene) -> list[str]:
    return settings_scene_state.texts(scene)


def _same_page_after_tap(before_scene, after_scene, *, expected_title: str | None = None) -> bool:
    return settings_scene_state.same_page_after_tap(
        before_scene,
        after_scene,
        expected_title=expected_title,
    )


def _same_visible_page(before_texts, after_texts) -> bool:
    return settings_scene_state.same_visible_page(before_texts, after_texts)


def _title_matches_navigation_label(title: str, label: str) -> bool:
    return settings_scene_state.title_matches_navigation_label(title, label)


def _page_title(scene) -> str:
    return settings_scene_state.page_title(scene)


def _open_settings_from_home_if_visible(phone) -> None:
    settings_bootstrap.open_settings_from_home_if_visible(phone, _bootstrap_actions())


def _ensure_settings_root(phone) -> bool:
    return settings_bootstrap.ensure_settings_root(phone, _bootstrap_actions())


def _try_return_to_settings_root(phone) -> bool:
    try:
        _return_to_settings_root(phone)
    except AssertionError:
        return False
    return _is_settings_root(phone)


def _recovery_actions() -> settings_recovery.SettingsRecoveryActions:
    return settings_recovery.SettingsRecoveryActions(
        action_intent=_action_intent,
        is_settings_root=_is_settings_root,
        scene_is_settings_root=_scene_is_settings_root,
        scene_kind=_scene_kind,
        scene_looks_like_settings_detail=_scene_looks_like_settings_detail,
        is_safe_top_left_back_fallback_scene=_is_safe_top_left_back_fallback_scene,
        is_settings_search_scene=_is_settings_search_scene,
        return_state_signature=_return_state_signature,
        open_app_from_springboard=_open_app_from_springboard,
        root_title=ROOT_TITLE,
        settle_settings_root_or_exit_search=_settle_settings_root_or_exit_search,
        return_from_settings_search_state=_return_from_settings_search_state,
        return_from_system_search_state=_return_from_system_search_state,
        return_from_blocked_settings_state=_return_from_blocked_settings_state,
        return_from_settings_detail_state=_return_from_settings_detail_state,
        return_from_unknown_settings_state=_return_from_unknown_settings_state,
        exit_settings_search_if_needed=_exit_settings_search_if_needed,
        dismiss_settings_search=_dismiss_settings_search,
        press_ios_back_shortcut=_press_ios_back_shortcut,
        tap_visible_root_result_from_search=_tap_visible_root_result_from_search,
        tap_settings_tab_from_search=_tap_settings_tab_from_search,
        tap_visible_settings_root_result_from_system_search=_tap_visible_settings_root_result_from_system_search,
        tap_visible_back=_tap_visible_back,
        meaningful_return_progress=_meaningful_return_progress,
        tap_top_left_back_fallback=_tap_top_left_back_fallback,
        try_memory_return_to_settings_root=_try_memory_return_to_settings_root,
        looks_like_settings_search_results=_looks_like_settings_search_results,
        settings_search_has_bottom_chrome=_settings_search_has_bottom_chrome,
    )


def _return_to_settings_root(phone) -> None:
    settings_recovery.return_to_settings_root(phone, _recovery_actions())


def _settle_settings_root_or_exit_search(
    phone,
    *,
    delay: float = 1.0,
    try_exit_search: bool = True,
) -> bool:
    return settings_recovery.settle_settings_root_or_exit_search(
        phone,
        _recovery_actions(),
        delay=delay,
        try_exit_search=try_exit_search,
    )


def _return_from_settings_search_state(phone, scene) -> bool:
    return settings_recovery.return_from_settings_search_state(phone, scene, _recovery_actions())


def _return_from_system_search_state(phone, scene) -> bool:
    return settings_recovery.return_from_system_search_state(phone, scene, _recovery_actions())


def _tap_visible_settings_root_result_from_system_search(phone, scene) -> bool:
    viewport_size = _phone_viewport_size(phone)
    result = DEFAULT_SETTINGS_POLICY.find_system_search_root_result(scene, viewport_size=viewport_size)
    if result is None:
        return False
    target, label = result
    cx, cy = target.box.center
    with _action_intent(phone, "settings_bootstrap.tap_system_search_root_result", label=label, text=target.text, x=cx, y=cy):
        result = phone.tap_xy(cx, cy)
    return _record_action_verdict(phone, result)


def _return_from_settings_detail_state(phone, scene) -> bool:
    return settings_recovery.return_from_settings_detail_state(phone, scene, _recovery_actions())


def _return_from_blocked_settings_state(phone, scene) -> bool:
    return settings_recovery.return_from_blocked_settings_state(phone, scene, _recovery_actions())


def _return_from_unknown_settings_state(phone, scene) -> bool:
    return settings_recovery.return_from_unknown_settings_state(phone, scene, _recovery_actions())


def _try_memory_return_to_settings_root(phone, scene) -> bool:
    memory = getattr(phone, "memory", None)
    if memory is None:
        return False
    try:
        node = memory.recognize(scene)
        if node is None:
            return False
        path = memory.path_to_page(
            node.screen_id,
            "settings/root",
            scene_type="settings_root",
            allowed_actions={"home", "back"},
            min_success_rate=0.5,
        )
    except Exception:
        return False
    if not path:
        return False
    edge = path[0]
    if edge.action_op == "home" and hasattr(phone, "home"):
        with _action_intent(phone, "return.memory.home", edge_success_rate=edge.success_rate):
            result = phone.home()
        return _record_action_verdict(phone, result)
    if edge.action_op == "key" and hasattr(phone, "key"):
        modifier = edge.action_kwargs.get("modifier")
        keycode = edge.action_kwargs.get("keycode")
        if modifier == IOS_BACK_MOD and keycode == IOS_BACK_KEY:
            with _action_intent(phone, "return.memory.back_shortcut", edge_success_rate=edge.success_rate):
                result = _send_ios_back_action(phone)
            return _record_action_verdict(phone, result)
    return False


def _send_ios_back_action(phone):
    """Send the backend-native iOS back primitive.

    PicoKVM needs a pointer-focus primer before Meta+[; Phone.back_gesture()
    owns that backend-specific sequence. Other backends can keep using the raw
    keyboard shortcut.
    """
    backend = getattr(phone, "_effector_backend", None)
    if callable(backend) and backend() == "picokvm" and hasattr(phone, "back_gesture"):
        try:
            return phone.back_gesture()
        except RuntimeError as exc:
            if "unsupported action" not in str(exc):
                raise
            return ActionResult.failed(
                backend="picokvm",
                connected=True,
                error=str(exc),
                unsupported=True,
            )
    return phone.key(IOS_BACK_MOD, IOS_BACK_KEY)


def _press_ios_back_shortcut(phone) -> bool:
    if not hasattr(phone, "key"):
        return False
    with _action_intent(phone, "return.back_shortcut", modifier=IOS_BACK_MOD, keycode=IOS_BACK_KEY):
        result = _send_ios_back_action(phone)
    return _record_action_verdict(phone, result)


def _meaningful_return_progress(before_scene, after_scene, phone=None) -> bool:
    before_kind = _scene_kind(before_scene, phone=phone)
    after_kind = _scene_kind(after_scene, phone=phone)
    if before_kind != after_kind and after_kind != "unknown":
        return True
    return not settings_scene_state.same_visible_page(_texts(before_scene), _texts(after_scene))


def _is_safe_top_left_back_fallback_scene(scene, phone=None) -> bool:
    return settings_scene_state.is_safe_top_left_back_fallback_scene(scene, phone=phone)


def _exit_settings_search_if_needed(phone) -> bool:
    return settings_recovery.exit_settings_search_if_needed(phone, _recovery_actions())


def _tap_settings_tab_from_search(phone, scene, *, allow_fallback: bool = True) -> bool:
    return settings_search_ui.tap_settings_tab_from_search(
        phone,
        scene,
        action_intent=_action_intent,
        allow_fallback=allow_fallback,
        record_action_verdict=_record_action_verdict,
    )


def _tap_visible_root_result_from_search(phone, scene) -> bool:
    target = DEFAULT_SETTINGS_POLICY.find_visible_root_result_from_search(scene)
    if target is None:
        return False
    cx, cy = target.box.center
    with _action_intent(phone, "settings_search.tap_visible_root_result", text=target.text, x=cx, y=cy):
        result = phone.tap_xy(cx, cy)
    return _record_action_verdict(phone, result)


def _bottom_tab_hit_point(phone, element: UIElement | None = None, *, fallback_x_fraction: float = 0.5) -> tuple[int, int]:
    return settings_search_ui.bottom_tab_hit_point(
        phone,
        element,
        fallback_x_fraction=fallback_x_fraction,
    )


def _is_settings_search_scene(scene) -> bool:
    return settings_scene_state.is_settings_search_scene(scene)


def _settings_search_has_bottom_chrome(scene) -> bool:
    return settings_scene_state.settings_search_has_bottom_chrome(scene)


def _looks_like_settings_search_results(scene) -> bool:
    return settings_scene_state.looks_like_settings_search_results(scene)


def _is_settings_search_affordance_text(text: str) -> bool:
    return settings_scene_state.is_settings_search_affordance_text(text)


def _dismiss_settings_search(phone, scene) -> bool:
    if not _is_settings_search_scene(scene):
        return False
    clear_button = settings_scene_state.find_search_clear_button(scene)
    if clear_button is None:
        if not _settings_search_has_query_text(scene):
            return False
        try:
            w, h = phone._viewport_size()
        except Exception:
            w, h = 448, 973
        safe = IOSSafeArea.from_viewport((w, h))
        x, y = int(w * 0.88), safe.bottom_control_y
        with _action_intent(phone, "settings_search.clear_query_geometry", x=x, y=y):
            result = phone.tap_xy(x, y)
        return _record_action_verdict(phone, result)
    cx, cy = clear_button.box.center
    with _action_intent(phone, "settings_search.clear_query_button", text=clear_button.text, x=cx, y=cy):
        result = phone.tap_xy(cx, cy)
    return _record_action_verdict(phone, result)


def _settings_search_has_query_text(scene) -> bool:
    return settings_scene_state.settings_search_has_query_text(scene)


def _enter_settings_search(phone) -> bool:
    scene = phone.perceive()
    if _is_settings_search_scene(scene):
        return True
    if getattr(phone, "_ios_settings_search_unavailable", False):
        return False
    if not _scene_is_settings_root(scene):
        _return_to_settings_root(phone)
        scene = phone.perceive()
    search_tab = DEFAULT_SETTINGS_POLICY.find_root_search_tab(scene)
    if search_tab is None:
        return False
    cx, cy = _bottom_tab_hit_point(phone, search_tab)
    with _action_intent(phone, "settings_root.open_search_tab", text=search_tab.text, x=cx, y=cy):
        result = phone.tap_xy(cx, cy)
    # Opening Settings Search commonly scores `unknown`: the search scene
    # resembles the root closely enough that the semantic verifier cannot
    # confirm the transition. Tolerate that and trust the re-perceived scene
    # below; only a genuine failure aborts. Without this, an `unknown` verdict
    # aborted the whole missing-page search recovery before a query was ever
    # typed (observed live: 8/8 root searches lost).
    if not _accept_tolerating_unknown(phone, result):
        return False
    time.sleep(1.0)
    phone.invalidate_perceive_cache()
    opened = phone.perceive()
    if _scene_kind(opened, phone=phone) == "system_search":
        phone._ios_settings_search_unavailable = True
        # The Settings-search tap opened iOS Spotlight instead. Dismiss it (Home)
        # so we are not stranded on Spotlight — the caller's
        # return_to_settings_root can then re-ground via SpringBoard rather than
        # failing to back out of a system surface.
        with suppress(Exception), _action_intent(phone, "settings_search.dismiss_spotlight_via_home"):
            phone.home()
        phone.invalidate_perceive_cache()
        return False
    return _is_settings_search_scene(opened)


def _tap_search_field(phone, scene) -> bool:
    field = settings_scene_state.find_search_field(scene)
    if field is not None:
        cx, cy = field.box.center
        with _action_intent(phone, "settings_search.focus_search_field", text=field.text, x=cx, y=cy):
            result = phone.tap_xy(cx, cy)
        return _accept_tolerating_unknown(phone, result)
    w, h = phone._viewport_size()
    x, y = int(w * 0.22), int(h * 0.94)
    with _action_intent(phone, "settings_search.focus_search_field_fallback", x=x, y=y):
        result = phone.tap_xy(x, y)
    return _accept_tolerating_unknown(phone, result)


def _clear_settings_search(phone) -> bool:
    for _ in range(2):
        scene = phone.perceive()
        if not _is_settings_search_scene(scene):
            if not _enter_settings_search(phone):
                return False
            scene = phone.perceive()
        if not _dismiss_settings_search(phone, scene):
            break
        time.sleep(0.8)
        phone.invalidate_perceive_cache()
    if not _is_settings_search_scene(phone.perceive()) and not _enter_settings_search(phone):
        return False
    scene = phone.perceive()
    if _is_settings_search_scene(scene):
        if not _tap_search_field(phone, scene):
            return False
        time.sleep(0.2)
        with _action_intent(phone, "settings_search.select_query_text", modifier=0x08, keycode=0x04):
            result = phone.key(0x08, 0x04)  # Cmd+A
        if not _record_action_verdict(phone, result):
            return False
        time.sleep(0.1)
        with _action_intent(phone, "settings_search.delete_query_text", modifier=0, keycode=0x2A):
            result = phone.key(0, 0x2A)     # Backspace
        if not _record_action_verdict(phone, result):
            return False
        time.sleep(0.4)
        phone.invalidate_perceive_cache()
    return True


def _find_search_result(scene, label: str) -> UIElement | None:
    return settings_scene_state.find_search_result(scene, label)


def _find_search_query_suggestion(scene, label: str) -> UIElement | None:
    return settings_scene_state.find_search_query_suggestion(scene, label)


def _wait_screen_settled(
    phone,
    *,
    attempts: int = 5,
    settle_s: float = 0.35,
    diff_thresh: float = 0.012,
) -> None:
    settings_scrolling.wait_screen_settled(
        phone,
        attempts=attempts,
        settle_s=settle_s,
        diff_thresh=diff_thresh,
    )


def _root_coverage_perceive(phone, depth: int):
    return settings_scrolling.root_coverage_perceive(phone, depth)


def _wheel_scroll_down(phone, ticks: int | None = None) -> None:
    settings_scrolling.wheel_scroll_down(phone, action_intent=_action_intent, ticks=ticks)


def _scroll_down_confirmed(phone, before_texts, *, depth=0, idx=0):
    return settings_scrolling.scroll_down_confirmed(
        phone,
        before_texts,
        action_intent=_action_intent,
        texts=_texts,
        depth=depth,
        idx=idx,
    )


def _wheel_scroll_up(phone) -> None:
    settings_scrolling.wheel_scroll_up(phone, action_intent=_action_intent)


def _call_wheel_scroll(method, ticks: int) -> None:
    settings_scrolling.call_wheel_scroll(method, ticks)


def _settings_wheel_ticks_per_swipe() -> int:
    return settings_scrolling.settings_wheel_ticks_per_swipe()


def _scroll_to_vertical_boundary(phone, *, direction: str, max_steps: int = 5) -> None:
    settings_scrolling.scroll_to_vertical_boundary(
        phone,
        direction=direction,
        action_intent=_action_intent,
        texts=_texts,
        max_steps=max_steps,
    )


def _navigation_actions() -> settings_navigation.SettingsNavigationActions:
    return settings_navigation.SettingsNavigationActions(
        action_intent=_action_intent,
        record_action_verdict=_record_action_verdict,
        root_search_query=DEFAULT_SETTINGS_POLICY.root_search_query,
        enter_settings_search=_enter_settings_search,
        clear_settings_search=_clear_settings_search,
        tap_search_field=_tap_search_field,
        find_search_result=_find_search_result,
        find_search_query_suggestion=_find_search_query_suggestion,
        is_settings_search_scene=_is_settings_search_scene,
        scene_is_settings_root=_scene_is_settings_root,
        match_any=_match_any,
        wheel_scroll_up=_wheel_scroll_up,
        wheel_scroll_down=_wheel_scroll_down,
        root_coverage=_root_coverage,
        open_root_label_via_search=_open_root_label_via_search,
        record_navigation_failure=_record_navigation_failure,
        crawl_current_page=_crawl_current_page,
        crawl_missing_root_pages_via_search=_crawl_missing_root_pages_via_search,
        return_to_settings_root=_return_to_settings_root,
        expected_root_labels=EXPECTED_ROOT_NAV_TEXT_ZH,
        max_pages_visited=MAX_PAGES_VISITED,
        root_coverage_perceive=_root_coverage_perceive,
        record_visible_page=_record_visible_page,
        record_visible_root_row_visits=_record_visible_root_row_visits,
        blocked_child_navigation_reason=_blocked_child_navigation_reason,
        record_blocked_page=_record_blocked_page,
        should_audit_candidates=_should_audit_candidates,
        record_rejected_candidates=_record_rejected_candidates,
        should_traverse_candidates=_should_traverse_candidates,
        safe_navigation_candidates=_safe_navigation_candidates,
        max_candidates_per_page=MAX_CANDIDATES_PER_PAGE,
        texts=_texts,
        tap_settings_row=_tap_settings_row,
        same_page_after_tap=_same_page_after_tap,
        is_settings_section_header=_is_settings_section_header,
        page_title=_page_title,
        canonical_expected_root_label=_canonical_expected_root_label,
        return_one_level=_return_one_level,
        scroll_down_confirmed=_scroll_down_confirmed,
        child_sampling_mode=_child_sampling_mode,
        scroll_budget_for_depth=_scroll_budget_for_depth,
        scroll_to_top=_scroll_to_settings_root_top,
        max_root_scroll_resets=MAX_ROOT_SCROLL_RESETS,
    )


def _scroll_to_settings_root_top(phone) -> None:
    _scroll_to_vertical_boundary(phone, direction="up", max_steps=6)


def _open_root_label_via_search(phone, label: str) -> bool:
    return settings_navigation.open_root_label_via_search(phone, label, _navigation_actions())


def _open_visible_or_scroll_to_row(phone, labels: Iterable[str]) -> UIElement | None:
    return settings_navigation.open_visible_or_scroll_to_row(phone, labels, _navigation_actions())


def _safe_navigation_candidates(
    scene,
    *,
    allow_sensitive_root_labels: bool = False,
    allow_known_without_affordance: bool = True,
) -> list[UIElement]:
    return settings_scene_state.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
        allow_known_without_affordance=allow_known_without_affordance,
    )


def _potential_navigation_row_text(element: UIElement) -> str | None:
    return settings_scene_state.potential_navigation_row_text(element)


def _is_settings_section_header(scene, element: UIElement) -> bool:
    return settings_scene_state.is_settings_section_header(scene, element)


def _is_safe_known_navigation_label(text: str) -> bool:
    return settings_scene_state.is_safe_known_navigation_label(text)


def _has_navigation_affordance(scene, element: UIElement) -> bool:
    return settings_scene_state.has_navigation_affordance(scene, element)


def _is_unsafe_navigation_text(text: str, *, allow_sensitive_root_labels: bool = False) -> bool:
    return settings_scene_state.is_unsafe_navigation_text(
        text,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
    )


def _matches_label(text: str, label: str) -> bool:
    return settings_scene_state.matches_label(text, label)


def _is_exact_safe_navigation_label(text: str) -> bool:
    return settings_scene_state.is_exact_safe_navigation_label(text)


def _is_root_only_unsafe_override(text: str) -> bool:
    return settings_scene_state.is_root_only_unsafe_override(text)


def _canonical_expected_root_label(text: str) -> str | None:
    return settings_scene_state.canonical_expected_root_label(text)


def _root_coverage(visits: list[PageVisit]) -> dict[str, list[str]]:
    return settings_page_records.root_coverage(visits)


def _blocked_child_navigation_reason(scene) -> str | None:
    return settings_scene_state.blocked_child_navigation_reason(scene)


def _blocks_child_navigation(scene) -> bool:
    return settings_scene_state.blocks_child_navigation(scene)


def _record_blocked_page(
    blocked_pages: list[BlockedPage],
    *,
    path: tuple[str, ...],
    scene,
    reason: str,
) -> None:
    settings_page_records.record_blocked_page(blocked_pages, path=path, scene=scene, reason=reason)


def _record_rejected_candidates(
    rejected_candidates: list[RejectedCandidate],
    *,
    path: tuple[str, ...],
    scene,
    allow_sensitive_root_labels: bool,
    allow_known_without_affordance: bool,
    phone=None,
) -> None:
    settings_page_records.record_rejected_candidates(
        rejected_candidates,
        path=path,
        scene=scene,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
        allow_known_without_affordance=allow_known_without_affordance,
        phone=phone,
    )


def _record_navigation_failure(
    navigation_failures: list[NavigationFailure],
    *,
    path: tuple[str, ...],
    scene,
    text: str,
    reason: str,
) -> None:
    settings_page_records.record_navigation_failure(
        navigation_failures,
        path=path,
        scene=scene,
        text=text,
        reason=reason,
    )


def _should_audit_candidates(depth: int) -> bool:
    return depth == 0 or STRICT_CHILD_CANDIDATE_AUDIT


def _should_traverse_candidates(depth: int) -> bool:
    if depth == 0 and ROOT_COVERAGE_MODE:
        return False
    return depth == 0 or CHILD_NAVIGATION_ENABLED


def _scroll_budget_for_depth(depth: int) -> int:
    if depth == 0:
        return MAX_SCROLLS_PER_PAGE
    return max(0, MAX_CHILD_SCROLLS_PER_PAGE)


def _child_sampling_mode(depth: int) -> bool:
    return depth > 0 and ROOT_COVERAGE_MODE and not CHILD_NAVIGATION_ENABLED


def _tap_settings_row(phone, row_hit: UIElement) -> bool:
    return settings_navigation.tap_settings_row(phone, row_hit, _navigation_actions())


def _record_visible_page(
    *,
    scene,
    path: tuple[str, ...],
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    depth: int,
    title_override: str | None = None,
) -> bool:
    return settings_page_records.record_visible_page(
        scene=scene,
        path=path,
        visits=visits,
        seen_sigs=seen_sigs,
        depth=depth,
        title_override=title_override,
    )


def _reset_vlm_row_state() -> None:
    settings_vlm_rows.reset_row_state()


def _vlm_recover_root_label(phone, element) -> str | None:
    return settings_vlm_rows.recover_root_label(phone, element)


def _record_visible_root_row_visits(
    *,
    scene,
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    phone=None,
) -> None:
    # In drill-down (child navigation) mode every root section is meant to be
    # opened, so do NOT pre-mark a visible row as "visited" — that would remove
    # it from the tap candidates and the section would never be entered (it would
    # show up as visible_only, not entered). Root-row visibility recording is only
    # for the default root-coverage mode that does not enter sections.
    if CHILD_NAVIGATION_ENABLED:
        return
    settings_page_records.record_visible_root_row_visits(
        scene=scene,
        visits=visits,
        seen_sigs=seen_sigs,
        phone=phone,
    )


def _crawl_missing_root_pages_via_search(
    phone,
    *,
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    max_depth: int,
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
) -> None:
    settings_navigation.crawl_missing_root_pages_via_search(
        phone,
        visits=visits,
        seen_sigs=seen_sigs,
        max_depth=max_depth,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        actions=_navigation_actions(),
    )


def _verify_section_readonly(phone, *, row, title, markers) -> None:
    row_hit = _open_visible_or_scroll_to_row(phone, row)
    if row_hit is None:
        raise SettingsCrawlerUnavailable(f"Settings row not visible after scrolling: {row}")

    if not _tap_settings_row(phone, row_hit):
        raise SettingsCrawlerUnavailable(f"Settings row tap was semantically rejected: {row}")
    time.sleep(1.0)
    phone.invalidate_perceive_cache()
    assert _wait_any_text(phone, title, timeout=5.0) is not None, (
        f"did not reach expected Settings page: {title}"
    )
    assert _wait_any_text(phone, markers, timeout=5.0) is not None, (
        f"page {title} opened, but expected read-only markers were not recognized"
    )


def _crawl_current_page(phone, *, path: tuple[str, ...], visits: list[PageVisit],
                        seen_sigs: set[ViewportKey], depth: int, max_depth: int,
                        limits_hit: set[str], blocked_pages: list[BlockedPage],
                        rejected_candidates: list[RejectedCandidate],
                        navigation_failures: list[NavigationFailure]) -> None:
    settings_navigation.crawl_current_page(
        phone,
        path=path,
        visits=visits,
        seen_sigs=seen_sigs,
        depth=depth,
        max_depth=max_depth,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        actions=_navigation_actions(),
    )


def _return_one_level(
    phone,
    *,
    parent_texts: Iterable[str] | None = None,
    parent_title: str | None = None,
    parent_is_root: bool = False,
) -> bool:
    with _action_intent(phone, "return.one_level.back_shortcut", parent_title=parent_title):
        result = _send_ios_back_action(phone)
    if _action_semantically_failed(phone, result):
        return False
    time.sleep(1.0)
    phone.invalidate_perceive_cache()
    if parent_texts is None:
        return True
    returned, last_scene = _wait_returned_to_parent(
        phone,
        parent_texts=parent_texts,
        parent_title=parent_title,
        parent_is_root=parent_is_root,
    )
    if returned:
        return True
    if last_scene is not None and _tap_visible_back(phone, last_scene):
        time.sleep(1.0)
        phone.invalidate_perceive_cache()
        returned, _ = _wait_returned_to_parent(
            phone,
            parent_texts=parent_texts,
            parent_title=parent_title,
            parent_is_root=parent_is_root,
        )
        if returned:
            return True
    if last_scene is not None and _tap_top_left_back_fallback(phone):
        time.sleep(1.0)
        phone.invalidate_perceive_cache()
        returned, _ = _wait_returned_to_parent(
            phone,
            parent_texts=parent_texts,
            parent_title=parent_title,
            parent_is_root=parent_is_root,
        )
        if returned:
            return True
    return False


def _action_semantically_failed(phone, result: Any) -> bool:
    if getattr(result, "unsupported", False):
        return False
    verdict = action_verdict(result)
    with suppress(Exception):
        phone._ios_settings_last_action_verdict = verdict
    status = getattr(verdict, "status", None)
    return bool(not verdict.accepted and status in {"failed", "transport_failed"})


def _wait_returned_to_parent(
    phone,
    *,
    parent_texts: Iterable[str],
    parent_title: str | None,
    parent_is_root: bool,
    timeout: float = 3.0,
) -> tuple[bool, Any | None]:
    deadline = time.monotonic() + timeout
    last_scene = None
    while time.monotonic() < deadline:
        scene = phone.perceive()
        last_scene = scene
        if _returned_to_parent_scene(
            scene,
            parent_texts=parent_texts,
            parent_title=parent_title,
            parent_is_root=parent_is_root,
        ):
            return True, scene
        time.sleep(0.4)
        phone.invalidate_perceive_cache()
    return False, last_scene


def _returned_to_parent_scene(
    scene,
    *,
    parent_texts: Iterable[str],
    parent_title: str | None,
    parent_is_root: bool,
) -> bool:
    if parent_is_root:
        return _scene_is_settings_root(scene)
    if parent_title and _title_matches_navigation_label(_page_title(scene), parent_title):
        return True
    return settings_scene_state.same_visible_page(parent_texts, _texts(scene))


def _tap_visible_back(phone, scene) -> bool:
    back = DEFAULT_SETTINGS_POLICY.find_visible_back(scene)
    if back is None:
        return False
    cx, cy = back.box.center
    x = max(20, cx)
    with _action_intent(phone, "return.tap_visible_back", text=back.text, x=x, y=cy):
        result = phone.tap_xy(x, cy)
    return _record_action_verdict(phone, result)


def _tap_top_left_back_fallback(phone) -> bool:
    try:
        w, h = phone._viewport_size()
    except Exception:
        w, h = 448, 973
    x, y = max(18, int(w * 0.055)), max(56, int(h * 0.085))
    with _action_intent(phone, "return.tap_top_left_fallback", x=x, y=y):
        result = phone.tap_xy(x, y)
    return _record_action_verdict(phone, result)


def _is_visible_back_element(element: UIElement) -> bool:
    return settings_scene_state.is_visible_back_element(element)


def _write_report(
    visits: list[PageVisit],
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    *,
    trace_payload: dict[str, Any] | None = None,
) -> None:
    if not REPORT_PATH:
        return
    if trace_payload is None and _ACTIVE_TRACE is not None:
        trace_payload = _ACTIVE_TRACE.payload
    settings_report_writer.write_report(
        report_path=REPORT_PATH,
        run_config=_current_run_config(),
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=_root_coverage(visits),
        trace_payload=trace_payload,
    )


def _add_trace_metrics(metrics: dict[str, object], trace_payload: dict[str, Any]) -> None:
    settings_report_writer.add_trace_metrics(metrics, trace_payload)


def _report_metrics(
    visits: list[PageVisit],
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    root_coverage: dict[str, list[str]],
) -> dict[str, object]:
    return settings_report_writer.report_metrics(
        visits=visits,
        limits_hit=limits_hit,
        blocked_pages=blocked_pages,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        root_coverage=root_coverage,
        require_exhaustive=REQUIRE_EXHAUSTIVE,
        min_pages=MIN_PAGES_VISITED,
    )


def _known_harness_issues(
    limits_hit: set[str],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    metrics: dict[str, object],
) -> list[dict[str, object]]:
    return settings_report_writer.known_harness_issues(
        limits_hit=limits_hit,
        rejected_candidates=rejected_candidates,
        navigation_failures=navigation_failures,
        metrics=metrics,
        require_exhaustive=REQUIRE_EXHAUSTIVE,
    )


def _failure_categories(
    limits_hit: set[str],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    metrics: dict[str, object],
    known_issues: list[dict[str, object]],
) -> dict[str, list[str]]:
    del limits_hit, rejected_candidates, navigation_failures, metrics
    return settings_report_writer.failure_categories(known_issues)
