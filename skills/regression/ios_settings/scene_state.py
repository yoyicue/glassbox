"""Pure scene classification helpers for the iOS Settings crawler.

This module must stay side-effect free: no taps, no sleeps, no device mutation.
It centralizes policy-backed scene predicates so navigation, recovery, and
records can share the same interpretation without importing ``core.py``.
"""

from __future__ import annotations

from glassbox.cognition import UIElement
from glassbox.ios.progress import same_visible_page, stable_visible_texts
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY


def phone_viewport_size(phone) -> tuple[int, int] | None:
    try:
        w, h = phone._viewport_size()
        return int(w), int(h)
    except Exception:
        return None


def scene_type(scene) -> str:
    return DEFAULT_SETTINGS_POLICY.scene_type(scene)


def classify_ios_scene(scene, phone=None):
    viewport_size = phone_viewport_size(phone) if phone is not None else None
    return DEFAULT_SETTINGS_POLICY.classify_scene(scene, viewport_size=viewport_size)


def scene_kind(scene, phone=None) -> str:
    viewport_size = phone_viewport_size(phone) if phone is not None else None
    return DEFAULT_SETTINGS_POLICY.scene_kind(scene, viewport_size=viewport_size)


def return_state_signature(scene, phone=None) -> tuple[str, tuple[str, ...]]:
    return scene_kind(scene, phone=phone), tuple(sorted(stable_visible_texts(texts(scene)))[:12])


def is_settings_root(phone) -> bool:
    scene = phone.perceive()
    return scene_is_settings_root(scene)


def scene_is_settings_root(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.scene_is_settings_root(scene)


def has_visible_back_affordance(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.has_visible_back_affordance(scene)


def scene_looks_like_settings_detail(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.scene_looks_like_settings_detail(scene)


def texts(scene) -> list[str]:
    out: list[str] = []
    for element in scene.elements:
        text = (element.text or "").strip()
        if text:
            out.append(text)
    return out


def same_page_after_tap(before_scene, after_scene, *, expected_title: str | None = None) -> bool:
    before_title = page_title(before_scene)
    after_title = page_title(after_scene)
    if (
        expected_title
        and before_title != "?"
        and after_title != "?"
        and before_title != after_title
        and title_matches_navigation_label(after_title, expected_title)
    ):
        return False
    return same_visible_page(texts(before_scene), texts(after_scene))


def title_matches_navigation_label(title: str, label: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(title, label)


def page_title(scene) -> str:
    return DEFAULT_SETTINGS_POLICY.page_title(scene)


def safe_navigation_candidates(
    scene,
    *,
    allow_sensitive_root_labels: bool = False,
    allow_known_without_affordance: bool = True,
) -> list[UIElement]:
    return DEFAULT_SETTINGS_POLICY.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
        allow_known_without_affordance=allow_known_without_affordance,
    )


def potential_navigation_row_text(element: UIElement) -> str | None:
    return DEFAULT_SETTINGS_POLICY.potential_navigation_row_text(element)


def is_settings_section_header(scene, element: UIElement) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_settings_section_header(scene, element)


def is_safe_known_navigation_label(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_safe_known_navigation_label(text)


def has_navigation_affordance(scene, element: UIElement) -> bool:
    return DEFAULT_SETTINGS_POLICY.has_navigation_affordance(scene, element)


def is_unsafe_navigation_text(text: str, *, allow_sensitive_root_labels: bool = False) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text(
        text,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
    )


def matches_label(text: str, label: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.matches_label(text, label)


def is_exact_safe_navigation_label(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_exact_safe_navigation_label(text)


def is_root_only_unsafe_override(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_root_only_unsafe_override(text)


def canonical_expected_root_label(text: str) -> str | None:
    return DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(text)


def blocked_child_navigation_reason(scene) -> str | None:
    return DEFAULT_SETTINGS_POLICY.blocked_child_navigation_reason(scene)


def blocks_child_navigation(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.blocks_child_navigation(scene)


def is_safe_top_left_back_fallback_scene(scene, phone=None) -> bool:
    viewport_size = phone_viewport_size(phone) if phone is not None else None
    return DEFAULT_SETTINGS_POLICY.is_safe_top_left_back_fallback_scene(scene, viewport_size=viewport_size)


def is_settings_search_scene(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_settings_search_scene(scene)


def settings_search_has_bottom_chrome(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.settings_search_has_bottom_chrome(scene)


def looks_like_settings_search_results(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.looks_like_settings_search_results(scene)


def is_settings_search_affordance_text(text: str) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_settings_search_affordance_text(text)


def settings_search_has_query_text(scene) -> bool:
    return DEFAULT_SETTINGS_POLICY.settings_search_has_query_text(scene)


def find_search_result(scene, label: str) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_result(scene, label)


def find_search_query_suggestion(scene, label: str) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_query_suggestion(scene, label)


def find_search_clear_button(scene) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_clear_button(scene)


def find_search_field(scene) -> UIElement | None:
    return DEFAULT_SETTINGS_POLICY.find_search_field(scene)


def is_visible_back_element(element: UIElement) -> bool:
    return DEFAULT_SETTINGS_POLICY.is_visible_back_element(element)
