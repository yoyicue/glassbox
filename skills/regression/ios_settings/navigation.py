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
from typing import Any

from glassbox.cognition import Box, UIElement
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings.recovery import SettingsRootUnreachable

PageVisit = settings_reporting.PageVisit
BlockedPage = settings_reporting.BlockedPage
RejectedCandidate = settings_reporting.RejectedCandidate
NavigationFailure = settings_reporting.NavigationFailure

ActionIntent = Callable[..., AbstractContextManager[Any]]
ActionResultRecorder = Callable[[Any, Any], bool]
ViewportKey = tuple[tuple[str, ...], tuple[str, ...]]


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
    root_coverage: Callable[[list[PageVisit]], dict[str, list[str]]]
    entry_exempt_sections: Callable[[list[PageVisit]], set[str]]
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


def open_root_label_via_search(phone, label: str, actions: SettingsNavigationActions) -> bool:
    query = actions.root_search_query(label)
    if query is None:
        return False
    if not actions.enter_settings_search(phone):
        return False
    for attempt in range(2):
        if not actions.clear_settings_search(phone):
            return False
        scene = phone.perceive()
        if not actions.tap_search_field(phone, scene):
            return False
        time.sleep(0.3)
        if attempt == 1 and not getattr(phone, "_ios_settings_search_input_toggled", False):
            with actions.action_intent(phone, "keyboard.switch_input_method", attempt=attempt + 1):
                result = phone.key(0x01, 0x2C)
            if not actions.record_action_verdict(phone, result):
                return False
            phone._ios_settings_search_input_toggled = True
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
        time.sleep(1.6)
        phone.invalidate_perceive_cache()
        scene = phone.perceive()
        hit = actions.find_search_result(scene, label)
        if hit is None:
            suggestion = actions.find_search_query_suggestion(scene, label)
            if suggestion is not None:
                cx, cy = suggestion.box.center
                with actions.action_intent(
                    phone,
                    "settings_search.tap_query_suggestion",
                    label=label,
                    text=suggestion.text,
                    x=cx,
                    y=cy,
                ):
                    result = phone.tap_xy(cx, cy)
                if not actions.record_action_verdict(phone, result):
                    return False
                time.sleep(0.8)
                phone.invalidate_perceive_cache()
                scene = phone.perceive()
                hit = actions.find_search_result(scene, label)
        if hit is None:
            continue
        cx, cy = hit.box.center
        with actions.action_intent(
            phone,
            "settings_search.tap_root_result",
            label=label,
            text=hit.text,
            x=cx,
            y=cy,
        ):
            result = phone.tap_xy(cx, cy)
        if not actions.record_action_verdict(phone, result):
            return False
        time.sleep(1.2)
        phone.invalidate_perceive_cache()
        opened = phone.perceive()
        if not actions.is_settings_search_scene(opened) and not actions.scene_is_settings_root(opened):
            return True
    return False


def open_visible_or_scroll_to_row(
    phone,
    labels: Iterable[str],
    actions: SettingsNavigationActions,
) -> UIElement | None:
    labels = tuple(labels)
    if not labels:
        return None
    for attempt in range(5):
        scene = phone.perceive()
        hit = actions.match_any(scene.elements, labels)
        if hit is not None:
            return hit
        vlm_hit = actions.vlm_point_for_label(
            phone,
            labels[0],
            scene_kind=actions.scene_kind(scene, phone=phone),
        )
        if vlm_hit is not None:
            return vlm_hit
        print(f"[scroll] seek-row attempt={attempt}", flush=True)
        if attempt == 2:
            actions.wheel_scroll_up(phone)
        else:
            actions.wheel_scroll_down(phone)
        time.sleep(1.0)
    return None


def settings_row_tap_point(phone, row_hit: UIElement) -> tuple[int, int]:
    w, _ = phone._viewport_size()
    _, row_y = row_hit.box.center
    if _backend_pointer_kind(phone) == "external_mouse":
        return int(w * 0.5), row_y
    row_x = max(row_hit.box.center[0], int(w * 0.28))
    x = min(row_x, int(w * 0.45))
    return x, row_y


def settings_row_target_element(phone, scene, row_hit: UIElement) -> UIElement:
    x, y = settings_row_tap_point(phone, row_hit)
    w, h = phone._viewport_size()
    pointer_kind = _backend_pointer_kind(phone)
    row_box = _settings_row_target_box(scene, row_hit, viewport_width=w, viewport_height=h)
    if pointer_kind != "external_mouse":
        row_box = _touch_digitizer_row_target_box(row_box, x=x, viewport_width=w)
    return row_hit.model_copy(update={
        "type": "list_item",
        "box": row_box,
        "preferred_tap_point": (x, y),
    })


def tap_settings_row(phone, row_hit: UIElement, actions: SettingsNavigationActions) -> bool:
    label = (row_hit.text or "").strip()
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
        )
        return actions.record_action_verdict(phone, result)
    # Fallback for phones without the actuation path (e.g. MockEffector in tests).
    x, row_y = settings_row_tap_point(phone, row_hit)
    with actions.action_intent(phone, "settings.tap_row", text=row_hit.text, x=x, y=row_y):
        result = phone.tap_xy(x, row_y)
    return actions.record_action_verdict(phone, result)


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
        if requested_root_label is not None:
            return requested_root_label
    return requested_label


def _backend_pointer_kind(phone) -> str:
    capabilities = getattr(phone, "_backend_capabilities", None)
    if callable(capabilities):
        with contextlib.suppress(Exception):
            backend_capabilities = capabilities()
            if backend_capabilities is not None:
                return str(getattr(backend_capabilities, "pointer_kind", "unknown"))
    effector = getattr(phone, "effector", None)
    effector_capabilities = getattr(effector, "capabilities", None)
    if callable(effector_capabilities):
        with contextlib.suppress(Exception):
            backend_capabilities = effector_capabilities()
            return str(getattr(backend_capabilities, "pointer_kind", "unknown"))
    return "unknown"


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
    if getattr(phone, "_ios_settings_search_unavailable", False):
        limits_hit.add("settings_search_unavailable")
        return
    exempt = actions.entry_exempt_sections(visits)
    for label in actions.expected_root_labels:
        if label not in actions.root_coverage(visits)["missing"] or label in exempt:
            continue  # device-unavailable / coverage-only → never searchable
        print(f"[ios_settings] search root page {label}", flush=True)
        if not actions.open_root_label_via_search(phone, label):
            actions.record_navigation_failure(
                navigation_failures,
                path=("Settings",),
                scene=phone.perceive(),
                text=label,
                reason="tap_no_navigation",
            )
            if getattr(phone, "_ios_settings_search_unavailable", False):
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
        actions.return_to_settings_root(phone)
        scene = phone.perceive()
    actions.record_visible_page(scene=scene, path=path, visits=visits, seen_sigs=seen_sigs, depth=depth)
    if depth == 0:
        actions.record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen_sigs, phone=phone)
    blocked_reason = actions.blocked_child_navigation_reason(scene)
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
            actions.return_to_settings_root(phone)
            scene = actions.root_coverage_perceive(phone, depth)
        actions.record_visible_page(scene=scene, path=path, visits=visits, seen_sigs=seen_sigs, depth=depth)
        if depth == 0:
            actions.record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen_sigs, phone=phone)
        if len(visits) >= actions.max_pages_visited:
            limits_hit.add("max_pages")
            return
        blocked_reason = actions.blocked_child_navigation_reason(scene)
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
                relocated = None
                for element in current.elements:
                    etext = (element.text or "").strip()
                    if not etext or actions.is_settings_section_header(current, element):
                        continue
                    if etext == label or (
                        candidate_canon is not None
                        and actions.canonical_expected_root_label(etext) == candidate_canon
                    ):
                        relocated = element
                        break
                if relocated is None:
                    rows = [
                        e for e in current.elements
                        if (e.text or "").strip()
                        and not actions.is_settings_section_header(current, e)
                    ]
                    relocated = actions.match_any(rows, [label])
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

        before_scroll_texts = actions.texts(scene)
        outcome, _after_scroll = actions.scroll_down_confirmed(
            phone,
            before_scroll_texts,
            depth=depth,
            idx=scroll_idx,
        )
        if outcome == "overshoot":
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
            required_missing = [
                label
                for label in actions.root_coverage(visits)["missing"]
                if label not in actions.entry_exempt_sections(visits)
            ]
            if (
                depth == 0
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
