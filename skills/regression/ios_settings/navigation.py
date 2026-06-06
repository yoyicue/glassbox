"""Navigation and traversal helpers for the iOS Settings crawler.

Owns root search, row opening, and recursive candidate traversal. Runtime
policy/config decisions are injected through ``SettingsNavigationActions`` so
the public crawler can call this module directly while ``core.py`` remains only
a compatibility facade.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from glassbox.boundaries import action_host_backend_capabilities
from glassbox.cognition import Box, UIElement
from glassbox.cognition.text_match import compact_text
from glassbox.ios.progress import is_time_text
from glassbox.target_planner import TargetPlanner
from skills.regression.ios_settings import context as settings_context
from skills.regression.ios_settings import graph_state as settings_graph_state
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings.recovery import SettingsRootUnreachable

PageVisit = settings_reporting.PageVisit
BlockedPage = settings_reporting.BlockedPage
RejectedCandidate = settings_reporting.RejectedCandidate
NavigationFailure = settings_reporting.NavigationFailure

ActionIntent = Callable[..., AbstractContextManager[Any]]
ActionResultRecorder = Callable[[Any, Any], bool]
ViewportKey = tuple[tuple[str, ...], tuple[str, ...]]
PAGE_ID_ROUTE_ALLOWED_ACTIONS = frozenset({
    "tap",
    "tap_xy",
    "settings.tap_row",
    "target_tap",
    "back",
    "back_gesture",
    "home",
    "scroll",
    "scroll_down",
    "scroll_up",
    "swipe_up",
    "swipe_down",
    "wheel_scroll_down",
    "wheel_scroll_up",
})


@dataclass(frozen=True)
class SettingsNavigationActions:
    action_intent: ActionIntent
    record_action_verdict: ActionResultRecorder
    root_search_query: Callable[[str], str | None]
    enter_settings_search: Callable[[Any], bool]
    clear_settings_search: Callable[[Any], bool]
    tap_search_field: Callable[[Any, Any], bool]
    find_search_result: Callable[[Any, str], UIElement | None]
    find_search_query_suggestion: Callable[[Any, str], UIElement | None]
    is_settings_search_scene: Callable[[Any], bool]
    scene_is_settings_root: Callable[[Any], bool]
    scene_kind: Callable[[Any], str]
    match_any: Callable[..., UIElement | None]
    vlm_point_for_label: Callable[..., UIElement | None]
    wheel_scroll_up: Callable[[Any], None]
    wheel_scroll_down: Callable[[Any], None]
    root_coverage: Callable[..., dict[str, list[str]]]
    entry_exempt_sections: Callable[..., set[str]]
    open_root_label_via_search: Callable[[Any, str], bool]
    record_navigation_failure: Callable[..., None]
    crawl_current_page: Callable[..., None]
    crawl_missing_root_pages_via_search: Callable[..., None]
    return_to_settings_root: Callable[[Any], None]
    expected_root_labels: Sequence[str]
    max_pages_visited: int
    root_coverage_perceive: Callable[[Any, int], Any]
    record_visible_page: Callable[..., bool]
    record_visible_root_row_visits: Callable[..., None]
    blocked_child_navigation_reason: Callable[[Any], str | None]
    record_blocked_page: Callable[..., None]
    should_audit_candidates: Callable[[int], bool]
    record_rejected_candidates: Callable[..., None]
    should_traverse_candidates: Callable[[int], bool]
    safe_navigation_candidates: Callable[..., list[UIElement]]
    max_candidates_per_page: int
    texts: Callable[[Any], list[str]]
    tap_settings_row: Callable[[Any, UIElement], bool]
    same_page_after_tap: Callable[..., bool]
    is_settings_section_header: Callable[[Any, UIElement], bool]
    page_title: Callable[[Any], str]
    canonical_expected_root_label: Callable[[str], str | None]
    return_one_level: Callable[..., bool]
    scroll_down_confirmed: Callable[..., tuple[str, Any]]
    child_sampling_mode: Callable[[int], bool]
    scroll_budget_for_depth: Callable[[int], int]
    # Closed-loop overshoot recovery: scroll the root list back to the top so a
    # fresh forward pass can land on rows the previous fling jumped past. When
    # None (e.g. minimal test facades) the multi-pass reset is skipped.
    scroll_to_top: Callable[[Any], None] | None = None
    max_root_scroll_resets: int = 2
    page_id_route_enabled: bool = False
    page_id_route_allowed_actions: frozenset[str] = PAGE_ID_ROUTE_ALLOWED_ACTIONS
    page_id_route_min_success_rate: float = 0.5
    page_id_route_label_candidates: Callable[[str], Sequence[str]] | None = None


def open_root_label_via_search(phone, label: str, actions: SettingsNavigationActions) -> bool:
    query = actions.root_search_query(label)
    if query is None:
        return False
    if not actions.enter_settings_search(phone):
        return False
    max_attempts = 1 if _is_ipad_target(phone) else 2
    for attempt in range(max_attempts):
        if not actions.clear_settings_search(phone):
            if _is_ipad_target(phone):
                settings_context.set_search_unavailable(phone)
            return False
        if _is_ipad_target(phone):
            scene = phone.perceive()
            if actions.is_settings_search_scene(scene):
                hit = actions.find_search_result(scene, label)
                if hit is not None and _tap_search_result(
                    phone,
                    label,
                    hit,
                    actions,
                    intent_name="settings_search.tap_existing_root_result",
                ):
                    return True
        scene = phone.perceive()
        if not actions.tap_search_field(phone, scene):
            return False
        time.sleep(0.3)
        if attempt == 1 and not settings_context.search_input_toggled(phone):
            with actions.action_intent(phone, "keyboard.switch_input_method", attempt=attempt + 1):
                result = phone.key(0x01, 0x2C)
            if not actions.record_action_verdict(phone, result):
                return False
            settings_context.set_search_input_toggled(phone)
            time.sleep(0.8)
        with actions.action_intent(
            phone,
            "settings_search.type_root_query",
            label=label,
            query=query,
            attempt=attempt + 1,
        ):
            result = phone.type(query)
        if not actions.record_action_verdict(phone, result):
            return False
        with contextlib.suppress(Exception):
            phone.invalidate_perceive_cache()
        _scene, hit, suggestion = _wait_for_search_result_or_suggestion(phone, label, actions)
        if hit is None and suggestion is None and _is_ipad_target(phone):
            with contextlib.suppress(Exception):
                phone.invalidate_perceive_cache()
            scene = phone.perceive()
            if actions.tap_search_field(phone, scene):
                time.sleep(0.5)
                with contextlib.suppress(Exception):
                    phone.invalidate_perceive_cache()
                _scene, hit, suggestion = _wait_for_search_result_or_suggestion(
                    phone,
                    label,
                    actions,
                    polls=12,
                )
        if hit is None and suggestion is not None:
            result = _tap_search_element(
                phone,
                suggestion,
                actions,
                intent_name="settings_search.tap_query_suggestion",
                label=label,
                target=suggestion.text or label,
                expected_state=None,
            )
            if not actions.record_action_verdict(phone, result):
                return False
            time.sleep(0.8)
            with contextlib.suppress(Exception):
                phone.invalidate_perceive_cache()
            _scene, hit, _suggestion = _wait_for_search_result_or_suggestion(
                phone,
                label,
                actions,
                polls=6,
            )
        if hit is None:
            continue
        if _tap_search_result(
            phone,
            label,
            hit,
            actions,
            intent_name="settings_search.tap_root_result",
        ):
            return True
    return False


def _sidebar_root_fallback_enabled() -> bool:
    from glassbox.config import get_config

    return bool(getattr(get_config(), "settings_search_root_fallback_sidebar", False))


def _decouple_exemption_enabled() -> bool:
    from glassbox.config import get_config

    return bool(getattr(get_config(), "settings_search_recovery_decouple_exempt", False))


# Cap on consecutive return-to-root failures tolerated before giving up the search
# recovery (Part A: a flaky back-nav skips one root, not all later roots).
_MAX_RETURN_TO_ROOT_FAILURES = 3


def _open_root_via_sidebar_fallback(
    phone, label: str, actions: SettingsNavigationActions
) -> bool:
    """Fix 3b: recover a root that Settings search cannot open via the sidebar.

    The iPad deep-search for some roots (Accessibility) surfaces ONLY deep-child
    results — every row is a `Root → Child` breadcrumb (some with the arrow
    dropped by OCR), so there is no tappable root result. This one-shot fallback
    returns to the root list, scrolls the sidebar to the root row, taps it, and
    verifies the opened title. It reuses the existing wheel-scroll seek,
    landing-retry tap, and title-check — no new primitive."""
    with contextlib.suppress(Exception):
        actions.return_to_settings_root(phone)
    # Backing out of a wrongly-opened deep search child (e.g. a breadcrumb tap
    # opened Accessibility → … → Top Button) can land directly on the target
    # root's own detail page — its parent. On the iPad the sidebar stays visible,
    # so `return_to_settings_root` treats that as "at root" and stops there. If we
    # are already on the target, verify it instead of scrolling the sidebar away.
    with contextlib.suppress(Exception):
        phone.invalidate_perceive_cache()
    if _scene_title_matches_requested_label(phone.perceive(), label, actions):
        return True
    row = open_visible_or_scroll_to_row(phone, (label,), actions)
    if row is None:
        return False
    if not tap_settings_row(phone, row, actions):
        return False
    with contextlib.suppress(Exception):
        phone.invalidate_perceive_cache()
    return _scene_title_matches_requested_label(phone.perceive(), label, actions)


def _tap_search_result(
    phone,
    label: str,
    hit: UIElement,
    actions: SettingsNavigationActions,
    *,
    intent_name: str,
) -> bool:
    result = _tap_search_element(
        phone,
        hit,
        actions,
        intent_name=intent_name,
        label=label,
        target=label,
        expected_state=_settings_row_expected_state(label, actions),
    )
    if not actions.record_action_verdict(phone, result):
        return False
    time.sleep(1.2)
    phone.invalidate_perceive_cache()
    opened = phone.perceive()
    if _scene_title_matches_requested_label(opened, label, actions):
        if _is_ipad_target(phone) and actions.is_settings_search_scene(opened):
            if not actions.clear_settings_search(phone):
                return False
            time.sleep(0.8)
            with contextlib.suppress(Exception):
                phone.invalidate_perceive_cache()
            return _scene_title_matches_requested_label(phone.perceive(), label, actions)
        return True
    if _is_ipad_target(phone):
        return False
    return not actions.is_settings_search_scene(opened) and not actions.scene_is_settings_root(opened)


def _scene_title_matches_requested_label(
    scene,
    label: str,
    actions: SettingsNavigationActions,
) -> bool:
    title = actions.page_title(scene)
    opened_label = actions.canonical_expected_root_label(title)
    requested_label = actions.canonical_expected_root_label(label) or label
    if opened_label == requested_label:
        return True
    if opened_label is not None:
        return False
    return compact_text(title).casefold() == compact_text(label).casefold()


def _tap_search_element(
    phone,
    element: UIElement,
    actions: SettingsNavigationActions,
    *,
    intent_name: str,
    label: str,
    target: str,
    expected_state: dict[str, Any] | None,
) -> Any:
    cx, cy = element.box.center
    with actions.action_intent(
        phone,
        intent_name,
        label=label,
        text=element.text,
        x=cx,
        y=cy,
    ):
        tap_element = getattr(phone, "tap_element", None)
        if callable(tap_element):
            return tap_element(
                element,
                intent=intent_name,
                target=target,
                via=intent_name,
                expected_state=expected_state,
                idempotent=True,
                recovery=None,
            )
        return phone.tap_xy(cx, cy)


def _wait_for_search_result_or_suggestion(
    phone,
    label: str,
    actions: SettingsNavigationActions,
    *,
    polls: int = 10,
    interval_s: float = 0.35,
) -> tuple[Any, UIElement | None, UIElement | None]:
    scene = phone.perceive()
    hit = actions.find_search_result(scene, label)
    suggestion = actions.find_search_query_suggestion(scene, label)
    for poll in range(max(1, polls)):
        if hit is not None or suggestion is not None:
            return scene, hit, suggestion
        if poll + 1 >= polls:
            break
        time.sleep(interval_s)
        with contextlib.suppress(Exception):
            phone.invalidate_perceive_cache()
        scene = phone.perceive()
        hit = actions.find_search_result(scene, label)
        suggestion = actions.find_search_query_suggestion(scene, label)
    return scene, hit, suggestion


def open_visible_or_scroll_to_row(
    phone,
    labels: Iterable[str],
    actions: SettingsNavigationActions,
) -> UIElement | None:
    labels = tuple(labels)
    if not labels:
        return None
    planner = getattr(phone, "target_planner", None) or TargetPlanner(phone)
    region = "ipados_settings_sidebar" if _is_ipad_target(phone) else None

    def fallback_locator(scene):
        return actions.vlm_point_for_label(
            phone,
            labels[0],
            scene_kind=actions.scene_kind(scene, phone=phone),
        )

    def log_seek_attempt(attempt: int) -> None:
        print(f"[scroll] seek-row attempt={attempt}", flush=True)

    hit = planner.scroll_to_visible_label(
        labels,
        region=region,
        canonicalizer=actions.canonical_expected_root_label,
        match_any=actions.match_any,
        fallback_locator=fallback_locator,
        perceive=phone.perceive,
        scroll_down=lambda: actions.wheel_scroll_down(phone),
        scroll_up=lambda: actions.wheel_scroll_up(phone),
        max_attempts=5,
        upward_attempt=2,
        settle_s=1.0,
        on_seek_attempt=log_seek_attempt,
    )
    if hit is not None and actions.canonical_expected_root_label(labels[0]) is not None:
        settings_scene_state.annotate_root_row_intent(hit)
    return hit


def settings_row_tap_point(phone, row_hit: UIElement) -> tuple[int, int]:
    w, _ = phone.viewport_size()
    _, row_y = row_hit.box.center
    if _is_ipad_target(phone):
        from glassbox.ipados.scene import sidebar_right_x

        sidebar_right = sidebar_right_x(w)
        row_x = row_hit.box.center[0]
        if row_x <= sidebar_right:
            return min(max(row_x, int(w * 0.10)), max(int(w * 0.10), sidebar_right - 44)), row_y
        detail_x = min(
            max(int(sidebar_right + (w - sidebar_right) * 0.34), sidebar_right + 64),
            w - 44,
        )
        return min(max(row_x, detail_x), w - 44), row_y
    if _backend_pointer_kind(phone) == "external_mouse":
        return int(w * 0.5), row_y
    row_x = max(row_hit.box.center[0], int(w * 0.28))
    x = min(row_x, int(w * 0.45))
    return x, row_y


def settings_row_target_element(phone, scene, row_hit: UIElement) -> UIElement:
    x, y = settings_row_tap_point(phone, row_hit)
    w, h = phone.viewport_size()
    pointer_kind = _backend_pointer_kind(phone)
    row_box = _settings_row_target_box(scene, row_hit, viewport_width=w, viewport_height=h)
    if pointer_kind != "external_mouse":
        row_box = _touch_digitizer_row_target_box(row_box, x=x, viewport_width=w)
    return row_hit.model_copy(update={
        "type": "list_item",
        "box": row_box,
        "preferred_tap_point": (x, y),
    })


def _settings_row_page_id(label: str) -> str | None:
    text = str(label or "").strip()
    if not text:
        return None
    if text.startswith("settings/"):
        return text
    return f"settings/{text}"


def _settings_row_page_id_candidates(
    label: str,
    actions: SettingsNavigationActions,
) -> tuple[str, ...]:
    label_candidates = getattr(actions, "page_id_route_label_candidates", None)
    if label_candidates is None:
        labels: Sequence[str] = (label,)
    else:
        labels = label_candidates(label)
    candidates: list[str] = []
    for candidate_label in labels:
        page_id = _settings_row_page_id(str(candidate_label))
        if page_id is not None and page_id not in candidates:
            candidates.append(page_id)
    return tuple(candidates)


def _settings_row_expected_state(
    label: str,
    actions: SettingsNavigationActions,
) -> dict[str, Any] | None:
    page_ids = _settings_row_page_id_candidates(label, actions)
    if not page_ids:
        return None
    if len(page_ids) == 1:
        return {"kind": "page_id", "payload": {"page_id": page_ids[0]}}
    return {"kind": "page_id", "payload": {"any_of": list(page_ids)}}


def _try_settings_row_page_id_route(
    phone,
    label: str,
    actions: SettingsNavigationActions,
) -> bool | None:
    """Return True on routed arrival, False on unsafe replay failure, None to fallback."""
    if not actions.page_id_route_enabled:
        return None
    page_ids = _settings_row_page_id_candidates(label, actions)
    if not page_ids:
        return None
    navigate_to_page = getattr(phone, "navigate_to_page", None)
    if not callable(navigate_to_page):
        return None
    allowed_actions = set(actions.page_id_route_allowed_actions)
    for index, page_id in enumerate(page_ids):
        with actions.action_intent(
            phone,
            "settings.page_id_route",
            text=label,
            page_id=page_id,
            candidate_index=index,
            candidate_count=len(page_ids),
            allowed_actions=sorted(allowed_actions),
        ):
            try:
                result = navigate_to_page(
                    page_id,
                    allowed_actions=allowed_actions,
                    min_success_rate=actions.page_id_route_min_success_rate,
                )
            except Exception:
                return False
        if getattr(result, "reached", False):
            settings_context.record_action_verdict(
                phone,
                SimpleNamespace(
                    accepted=True,
                    status="succeeded",
                    reason=getattr(result, "reason", None),
                    transport_ok=True,
                ),
            )
            settings_scene_state.record_settings_row_tap(phone, label)
            return True
        # A no-path lookup leaves the screen unchanged, so the normal row tap can
        # still use the live row hit. A replayed-but-failed path may have moved
        # the UI, so do not continue with stale coordinates.
        if getattr(result, "edge_count", 0) or tuple(getattr(result, "replayed_ops", ()) or ()):
            return False
    return None


def tap_settings_row(phone, row_hit: UIElement, actions: SettingsNavigationActions) -> bool:
    label = settings_scene_state.row_label(row_hit)
    page_id_routed = _try_settings_row_page_id_route(phone, label, actions)
    if page_id_routed is not None:
        return page_id_routed
    expected_state = _settings_row_expected_state(label, actions)
    tap_element = getattr(phone, "tap_element", None)
    if callable(tap_element):
        # Delegate to glassbox's actuation: same settings-aware first tap, but it
        # verifies the effect and, on a landing retry, re-perceives and
        # re-locates the row (robust to drag-scroll overshoot). The reliability
        # lives in glassbox, not here.
        result = tap_element(
            row_hit,
            intent=f"settings.row:{label}",
            target=label,
            via="settings.tap_row",
            landing_retry_allowed=True,
            landing_retry_budget=2,
            # A row tap that leaves us on the same page (no navigation) scores
            # `unknown`; retry it (re-grounding to the row's current position).
            # Real navigations score `succeeded`, so they are never retried.
            retry_budget=2,
            unknown_policy="retry",
            idempotent=True,
            expected_state=expected_state,
            recovery=None,
        )
        accepted = actions.record_action_verdict(phone, result)
        if accepted:
            settings_scene_state.record_settings_row_tap(phone, label)
        return accepted
    # Fallback for phones without the actuation path (e.g. MockEffector in tests).
    x, row_y = settings_row_tap_point(phone, row_hit)
    with actions.action_intent(phone, "settings.tap_row", text=label, x=x, y=row_y):
        result = phone.tap_xy(x, row_y)
    accepted = actions.record_action_verdict(phone, result)
    if accepted:
        settings_scene_state.record_settings_row_tap(phone, label)
    return accepted


def _observed_path_label(
    actions: SettingsNavigationActions,
    *,
    requested_label: str,
    after_scene,
    depth: int,
) -> str:
    observed_title = (actions.page_title(after_scene) or "").strip()
    if not observed_title or observed_title == "?":
        return requested_label
    if depth == 0:
        observed_root_label = actions.canonical_expected_root_label(observed_title)
        if observed_root_label is not None:
            return observed_root_label
        requested_root_label = actions.canonical_expected_root_label(requested_label)
        if requested_root_label is not None and (
            actions.page_title(after_scene) == requested_label
            or settings_scene_state.title_matches_navigation_label(observed_title, requested_label)
            or compact_text(observed_title).casefold() in {"settings", "设置"}
            or _observed_title_missing_or_noise(observed_title)
        ):
            # Root-row intent is more stable than the detail title OCR. Live iPad
            # Settings has produced titles such as "Bluetgoth"; treating that as
            # a new path makes coverage think the root was never entered and
            # triggers wasteful search recovery back to an already-visited row.
            return requested_root_label
    return observed_title or requested_label


def _observed_title_missing_or_noise(title: str) -> bool:
    text = (title or "").strip()
    return (
        not text
        or text == "?"
        or text in {"<", "‹", "〈", "返回", "Back"}
        or is_time_text(text)
        or settings_scene_state.is_status_bar_clock_text(text)
    )


def _last_action_succeeded(phone) -> bool:
    verdict = settings_context.last_action_verdict(phone)
    return str(getattr(verdict, "status", "")).lower() == "succeeded"


def _backend_pointer_kind(phone) -> str:
    backend_capabilities = action_host_backend_capabilities(phone)
    if backend_capabilities is not None:
        return str(getattr(backend_capabilities, "pointer_kind", "unknown"))
    effector = getattr(phone, "effector", None)
    effector_capabilities = getattr(effector, "capabilities", None)
    if callable(effector_capabilities):
        with contextlib.suppress(Exception):
            backend_capabilities = effector_capabilities()
            return str(getattr(backend_capabilities, "pointer_kind", "unknown"))
    return "unknown"


def _is_ipad_target(phone) -> bool:
    model = str(getattr(getattr(phone, "device_geometry", None), "model", "") or "")
    return model.lower().replace("-", "_").startswith("ipad")


def _settings_row_target_box(
    scene,
    row_hit: UIElement,
    *,
    viewport_width: int,
    viewport_height: int,
) -> Box:
    _, row_y = row_hit.box.center
    centers = sorted({
        element.box.center[1]
        for element in getattr(scene, "elements", []) or []
        if element.text and 0 <= element.box.center[1] <= viewport_height
    })
    prev_y = max((cy for cy in centers if cy < row_y - 8), default=None)
    next_y = min((cy for cy in centers if cy > row_y + 8), default=None)
    default_h = max(48, min(76, int(row_hit.box.h * 2.6)))
    top = row_y - default_h // 2 if prev_y is None else (prev_y + row_y) // 2
    bottom = row_y + default_h // 2 if next_y is None else (row_y + next_y) // 2
    if bottom - top < 44:
        top = row_y - default_h // 2
        bottom = row_y + default_h // 2
    top = max(0, top)
    bottom = min(viewport_height, max(top + 44, bottom))
    return Box(x=0, y=top, w=viewport_width, h=bottom - top)


def _touch_digitizer_row_target_box(row_box: Box, *, x: int, viewport_width: int) -> Box:
    half_width = max(44, min(96, int(viewport_width * 0.16)))
    left = max(0, x - half_width)
    right = min(viewport_width, x + half_width)
    return Box(x=left, y=row_box.y, w=max(44, right - left), h=row_box.h)


def crawl_missing_root_pages_via_search(
    phone,
    *,
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    max_depth: int,
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    actions: SettingsNavigationActions,
) -> None:
    if settings_context.search_unavailable(phone):
        limits_hit.add("settings_search_unavailable")
        return
    exempt = actions.entry_exempt_sections(visits, phone=phone)
    return_to_root_failures = 0
    for label in actions.expected_root_labels:
        if label not in actions.root_coverage(visits, phone=phone)["missing"] or label in exempt:
            continue  # device-unavailable / coverage-only → never searchable
        print(f"[ios_settings] search root page {label}", flush=True)
        if not actions.open_root_label_via_search(phone, label):
            if _sidebar_root_fallback_enabled() and _open_root_via_sidebar_fallback(
                phone, label, actions
            ):
                print(f"[ios_settings] sidebar fallback opened {label}", flush=True)
            else:
                actions.record_navigation_failure(
                    navigation_failures,
                    path=("Settings",),
                    scene=phone.perceive(),
                    text=label,
                    reason="search_no_result",
                )
                if settings_context.search_unavailable(phone):
                    limits_hit.add("settings_search_unavailable")
                    return
                continue
        try:
            actions.crawl_current_page(
                phone,
                path=("Settings", label),
                visits=visits,
                seen_sigs=seen_sigs,
                depth=1,
                max_depth=max_depth,
                limits_hit=limits_hit,
                blocked_pages=blocked_pages,
                rejected_candidates=rejected_candidates,
                navigation_failures=navigation_failures,
            )
            actions.return_to_settings_root(phone)
        except SettingsRootUnreachable:
            # Intermittent back-nav left us off-root after this searched section.
            # Don't crash the whole crawl (it would discard all coverage gathered
            # so far). Record it (soft), try one more re-ground, and stop search
            # recovery if root is still unreachable.
            limits_hit.add("return_to_root_failed")
            try:
                actions.return_to_settings_root(phone)
            except SettingsRootUnreachable:
                # Part A (decouple): a flaky back-nav must not starve the roots
                # AFTER this one of their search attempt — the device-unavailable
                # roots still need a real search_no_result to be exempted. Skip
                # only THIS root and keep searching the rest (bounded, so a truly
                # stuck crawl still gives up). Default off → byte-identical early
                # return.
                return_to_root_failures += 1
                if (
                    _decouple_exemption_enabled()
                    and return_to_root_failures <= _MAX_RETURN_TO_ROOT_FAILURES
                ):
                    continue
                return
        if len(visits) >= actions.max_pages_visited:
            limits_hit.add("max_pages")
            return


def crawl_current_page(
    phone,
    *,
    path: tuple[str, ...],
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    depth: int,
    max_depth: int,
    limits_hit: set[str],
    blocked_pages: list[BlockedPage],
    rejected_candidates: list[RejectedCandidate],
    navigation_failures: list[NavigationFailure],
    actions: SettingsNavigationActions,
) -> None:
    scene = phone.perceive()
    if depth == 0 and not actions.scene_is_settings_root(scene):
        try:
            actions.return_to_settings_root(phone)
        except SettingsRootUnreachable:
            limits_hit.add("return_to_root_failed")
            return
        scene = phone.perceive()
    actions.record_visible_page(scene=scene, path=path, visits=visits, seen_sigs=seen_sigs, depth=depth)
    if depth == 0:
        actions.record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen_sigs, phone=phone)
    blocked_reason = _blocked_child_navigation_reason_for_depth(actions, scene, depth=depth, phone=phone)
    if blocked_reason is not None:
        actions.record_blocked_page(blocked_pages, path=path, scene=scene, reason=blocked_reason)
    if actions.should_audit_candidates(depth):
        actions.record_rejected_candidates(
            rejected_candidates,
            path=path,
            scene=scene,
            allow_sensitive_root_labels=depth == 0,
            allow_known_without_affordance=depth == 0,
            phone=phone,
        )
    if len(visits) >= actions.max_pages_visited:
        limits_hit.add("max_pages")
        return
    if blocked_reason is not None:
        return
    if depth >= max_depth:
        if actions.should_traverse_candidates(depth) and actions.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=depth == 0,
            allow_known_without_affordance=depth == 0,
        ):
            limits_hit.add("max_depth")
        return

    attempted: set[str] = set()
    root_resets = 0
    scroll_budget = actions.scroll_budget_for_depth(depth)
    if scroll_budget <= 0 and depth > 0:
        return
    for scroll_idx in range(scroll_budget):
        scene = actions.root_coverage_perceive(phone, depth)
        if depth == 0 and not actions.scene_is_settings_root(scene):
            try:
                actions.return_to_settings_root(phone)
            except SettingsRootUnreachable:
                limits_hit.add("return_to_root_failed")
                return
            scene = actions.root_coverage_perceive(phone, depth)
        actions.record_visible_page(scene=scene, path=path, visits=visits, seen_sigs=seen_sigs, depth=depth)
        if depth == 0:
            actions.record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen_sigs, phone=phone)
        if len(visits) >= actions.max_pages_visited:
            limits_hit.add("max_pages")
            return
        blocked_reason = _blocked_child_navigation_reason_for_depth(actions, scene, depth=depth, phone=phone)
        if blocked_reason is not None:
            actions.record_blocked_page(blocked_pages, path=path, scene=scene, reason=blocked_reason)
            return
        if actions.should_audit_candidates(depth):
            actions.record_rejected_candidates(
                rejected_candidates,
                path=path,
                scene=scene,
                allow_sensitive_root_labels=depth == 0,
                allow_known_without_affordance=depth == 0,
                phone=phone,
            )
        if actions.should_traverse_candidates(depth):
            all_candidates = actions.safe_navigation_candidates(
                scene,
                allow_sensitive_root_labels=depth == 0,
                allow_known_without_affordance=depth == 0,
            )
        else:
            all_candidates = []
        if actions.max_candidates_per_page > 0 and len(all_candidates) > actions.max_candidates_per_page:
            limits_hit.add("max_candidates_per_page")
            candidates = all_candidates[:actions.max_candidates_per_page]
        else:
            candidates = all_candidates
        for cand in candidates:
            label = (cand.text or "").strip()
            if label in attempted:
                continue
            if depth == 0 and _root_label_entered_by_graph(phone, actions, label):
                attempted.add(label)
                continue
            if depth == 0 and settings_graph_state.is_inert_root_label(phone, label):
                _record_inert_root_candidate(rejected_candidates, actions=actions, path=path, scene=scene, label=label)
                attempted.add(label)
                continue
            if depth == 0:
                # Re-ground before each root tap. Entering/returning from a prior
                # row — or a row that navigated but was mis-scored as same-page —
                # can leave us off-root with the remaining candidates' captured
                # coordinates stale, which silently dropped whole mid-band batches
                # (a single bad row cascaded into the rest of the screen). Re-confirm
                # we are on root and re-locate this row by its label in the live
                # scene. If it has scrolled off, skip WITHOUT marking it attempted
                # so the scroll/multi-pass recovery can still reach it.
                current = phone.perceive()
                if not actions.scene_is_settings_root(current):
                    actions.return_to_settings_root(phone)
                    current = phone.perceive()
                # Re-locate this row in the live scene. Match by canonical section
                # first (a garbled/variant OCR of e.g. "Bluetooth" still maps to
                # the same row), then exact text, then a fuzzy fallback. Exact-text
                # only dropped mid-band rows whose OCR drifted between frames
                # (notably under English OCR) — the cascade this re-ground exists
                # to prevent.
                candidate_canon = actions.canonical_expected_root_label(label)
                live_root_candidates = actions.safe_navigation_candidates(
                    current,
                    allow_sensitive_root_labels=True,
                    allow_known_without_affordance=True,
                )
                relocated = None
                for element in live_root_candidates:
                    etext = (element.text or "").strip()
                    if not etext:
                        continue
                    if etext == label or (
                        candidate_canon is not None
                        and actions.canonical_expected_root_label(etext) == candidate_canon
                    ):
                        relocated = element
                        break
                if relocated is None:
                    relocated = actions.match_any(live_root_candidates, [label])
                if relocated is None:
                    relocated = actions.vlm_point_for_label(
                        phone,
                        label,
                        scene_kind=actions.scene_kind(current, phone=phone),
                    )
                if relocated is None:
                    continue
                cand = relocated
                scene = current
            elif depth > 0:
                # Child samples can stale just like root rows: returning from a
                # prior detail page may settle with slightly shifted right-pane
                # rows. Re-ground the remaining child label in the live parent
                # scene before tapping, instead of trusting captured coordinates.
                with contextlib.suppress(Exception):
                    phone.invalidate_perceive_cache()
                current = phone.perceive()
                relocated = _relocate_detail_candidate(actions, current, label)
                if relocated is None:
                    continue
                cand = relocated
                scene = current
            attempted.add(label)
            before_texts = actions.texts(scene)
            if not actions.tap_settings_row(phone, cand):
                if depth == 0 and actions.canonical_expected_root_label(label) is not None:
                    continue
                actions.record_navigation_failure(
                    navigation_failures,
                    path=path,
                    scene=scene,
                    text=label,
                    reason="tap_no_navigation",
                )
                continue
            time.sleep(1.0)
            phone.invalidate_perceive_cache()
            after = phone.perceive()
            same_page_after_tap = actions.same_page_after_tap(scene, after, expected_title=label)
            if (
                same_page_after_tap
                and depth == 0
                and actions.canonical_expected_root_label(label) is not None
                and _last_action_succeeded(phone)
            ):
                same_page_after_tap = False
            if same_page_after_tap and depth == 0:
                retry_cand = next(
                    (element for element in after.elements if (element.text or "").strip() == label),
                    None,
                )
                if (
                    retry_cand is not None
                    and not actions.is_settings_section_header(after, retry_cand)
                    and actions.tap_settings_row(phone, retry_cand)
                ):
                    time.sleep(1.0)
                    phone.invalidate_perceive_cache()
                    retry_after = phone.perceive()
                    if not actions.same_page_after_tap(after, retry_after, expected_title=label):
                        after = retry_after
                        same_page_after_tap = False
            if same_page_after_tap:
                cand_in_after = next(
                    (e for e in after.elements if (e.text or "").strip() == label),
                    cand,
                )
                if actions.is_settings_section_header(after, cand_in_after):
                    rejected_candidates.append(RejectedCandidate(
                        path=path,
                        title=actions.page_title(after) or (path[-1] if path else ""),
                        text=label,
                        reason="section_header",
                    ))
                elif not (depth == 0 and actions.canonical_expected_root_label(label) is not None):
                    actions.record_navigation_failure(
                        navigation_failures,
                        path=path,
                        scene=scene,
                        text=label,
                        reason="tap_no_navigation",
                    )
                continue
            observed_label = _observed_path_label(
                actions,
                requested_label=label,
                after_scene=after,
                depth=depth,
            )
            actions.crawl_current_page(
                phone,
                path=(*path, observed_label),
                visits=visits,
                seen_sigs=seen_sigs,
                depth=depth + 1,
                max_depth=max_depth,
                limits_hit=limits_hit,
                blocked_pages=blocked_pages,
                rejected_candidates=rejected_candidates,
                navigation_failures=navigation_failures,
            )
            if depth == 0:
                if not actions.return_one_level(
                    phone,
                    parent_texts=before_texts,
                    parent_title=actions.page_title(scene),
                    parent_is_root=True,
                ):
                    actions.return_to_settings_root(phone)
            else:
                if not actions.return_one_level(
                    phone,
                    parent_texts=before_texts,
                    parent_title=actions.page_title(scene),
                    parent_is_root=False,
                ):
                    limits_hit.add("lost_parent")
                    actions.return_to_settings_root(phone)
                    return
            if len(visits) >= actions.max_pages_visited:
                limits_hit.add("max_pages")
                return

        required_missing = (
            _required_missing_root_labels(actions, visits, phone)
            if depth == 0 else []
        )
        if depth == 0 and not required_missing:
            break
        before_scroll_texts = actions.texts(scene)
        scroll_metadata: dict[str, Any] = {}
        outcome, _after_scroll = actions.scroll_down_confirmed(
            phone,
            before_scroll_texts,
            depth=depth,
            idx=scroll_idx,
            scene=scene,
            target_labels=required_missing,
            canonical_expected_root_label=actions.canonical_expected_root_label,
            scroll_metadata=scroll_metadata,
        )
        if depth == 0 and not actions.scene_is_settings_root(_after_scroll):
            try:
                actions.return_to_settings_root(phone)
            except SettingsRootUnreachable:
                limits_hit.add("return_to_root_failed")
                return
            continue
        if outcome in {"overshoot", "top-overshoot"}:
            limits_hit.add("scroll_overshoot")
        elif outcome == "stuck":
            # Reached the bottom (or a jammed fling). On the root list the
            # momentum fling overshoots non-deterministically, so a single
            # top→bottom pass can skip a whole mid-band batch. If expected root
            # sections are still missing, reset to the top and pass again: each
            # pass's fling lands on different rows, and `attempted` dedups the
            # rows already entered, so the union converges without depending on
            # the brittle Settings-search recovery. Bounded by max_root_scroll_resets.
            # Only required sections drive another pass. Coverage-only (e.g. 钱包)
            # and device-unavailable (e.g. 蜂窝网络 on a no-SIM phone, detected
            # from seen text) can never be entered, so re-scanning for them is pure
            # waste — stop once only those remain.
            if (
                depth == 0
                and (not _is_ipad_target(phone) or _supports_wheel_scroll(phone))
                and actions.scroll_to_top is not None
                and root_resets < actions.max_root_scroll_resets
                and required_missing
            ):
                root_resets += 1
                print(
                    f"[ios_settings] root scroll reset pass={root_resets} "
                    f"missing={required_missing}",
                    flush=True,
                )
                actions.scroll_to_top(phone)
                continue
            if (
                depth == 0
                and scroll_metadata.get("row_tracked") is True
                and _is_ipad_target(phone)
            ):
                settings_context.mark_root_sidebar_exhaustive(phone)
                if required_missing:
                    settings_context.record_sidebar_absent_root_labels(phone, required_missing)
            break
    else:
        if depth > 0 and not actions.child_sampling_mode(depth):
            limits_hit.add("max_scrolls_per_page")

    if depth == 0:
        actions.crawl_missing_root_pages_via_search(
            phone,
            visits=visits,
            seen_sigs=seen_sigs,
            max_depth=max_depth,
            limits_hit=limits_hit,
            blocked_pages=blocked_pages,
            rejected_candidates=rejected_candidates,
            navigation_failures=navigation_failures,
        )


def _record_inert_root_candidate(
    rejected_candidates: list[RejectedCandidate],
    *,
    actions: SettingsNavigationActions,
    path: tuple[str, ...],
    scene,
    label: str,
) -> None:
    key = (path, label, "inert_self_loop")
    if any((candidate.path, candidate.text, candidate.reason) == key for candidate in rejected_candidates):
        return
    rejected_candidates.append(RejectedCandidate(
        path=path,
        title=actions.page_title(scene) or (path[-1] if path else ""),
        text=label,
        reason="inert_self_loop",
    ))


def _supports_wheel_scroll(phone) -> bool:
    supports = getattr(phone, "supports", None)
    if not callable(supports):
        return False
    try:
        return bool(supports("scroll_wheel"))
    except Exception:
        return False


def _blocked_child_navigation_reason_for_depth(
    actions: SettingsNavigationActions,
    scene,
    *,
    depth: int,
    phone,
) -> str | None:
    reason = actions.blocked_child_navigation_reason(scene)
    if (
        reason is not None
        and depth == 0
        and _is_ipad_target(phone)
        and actions.scene_is_settings_root(scene)
    ):
        return None
    return reason


def _root_label_entered_by_graph(phone, actions: SettingsNavigationActions, label: str) -> bool:
    canonical = actions.canonical_expected_root_label(label)
    return canonical is not None and canonical in settings_graph_state.root_entered_labels(phone)


def _required_missing_root_labels(
    actions: SettingsNavigationActions,
    visits: list[PageVisit],
    phone,
) -> list[str]:
    exempt = actions.entry_exempt_sections(visits, phone=phone)
    return [
        label
        for label in actions.root_coverage(visits, phone=phone)["missing"]
        if label not in exempt
    ]


def _relocate_detail_candidate(
    actions: SettingsNavigationActions,
    scene,
    label: str,
) -> UIElement | None:
    live_candidates = actions.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )
    exact = next(
        (element for element in live_candidates if (element.text or "").strip() == label),
        None,
    )
    if exact is not None:
        return exact
    return actions.match_any(live_candidates, [label])
