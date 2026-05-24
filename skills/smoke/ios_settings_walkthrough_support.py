# ruff: noqa: F401

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings import bootstrap as settings_bootstrap
from skills.regression.ios_settings import core as walkthrough
from skills.regression.ios_settings import navigation as settings_navigation
from skills.regression.ios_settings import page_records as settings_page_records
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings import scrolling as settings_scrolling
from skills.regression.ios_settings import search_ui as settings_search_ui
from skills.regression.ios_settings import vlm_rows as settings_vlm_rows
from skills.regression.ios_settings.crawler import SettingsCrawlerUnavailable
from skills.regression.ios_settings.policy import (
    DEFAULT_SETTINGS_POLICY,
    EXPECTED_ROOT_NAV_TEXT,
    EXPECTED_ROOT_NAV_TEXT_ZH,
    ROOT_LABEL_ALIASES,
    ROOT_SEARCH_QUERIES,
    SAFE_NAV_TEXT,
)
from skills.regression.ios_settings.reporting import (
    BlockedPage,
    NavigationFailure,
    PageVisit,
    RejectedCandidate,
)

_blocked_child_navigation_reason = settings_scene_state.blocked_child_navigation_reason
_canonical_expected_root_label = settings_scene_state.canonical_expected_root_label
_find_search_query_suggestion = settings_scene_state.find_search_query_suggestion
_find_search_result = settings_scene_state.find_search_result
_is_settings_root = settings_scene_state.is_settings_root
_is_settings_search_scene = settings_scene_state.is_settings_search_scene
_is_settings_section_header = settings_scene_state.is_settings_section_header
_is_unsafe_navigation_text = settings_scene_state.is_unsafe_navigation_text
_record_blocked_page = settings_page_records.record_blocked_page
_record_rejected_candidates = settings_page_records.record_rejected_candidates
_record_visible_page = settings_page_records.record_visible_page
_record_visible_root_row_visits = settings_page_records.record_visible_root_row_visits
_root_coverage = settings_page_records.root_coverage
_safe_navigation_candidates = settings_scene_state.safe_navigation_candidates
_same_page_after_tap = settings_scene_state.same_page_after_tap
_same_visible_page = settings_scene_state.same_visible_page
_scene_looks_like_settings_detail = settings_scene_state.scene_looks_like_settings_detail
_settings_wheel_ticks_per_swipe = settings_scrolling.settings_wheel_ticks_per_swipe
_wait_screen_settled = settings_scrolling.wait_screen_settled
_reset_vlm_row_state = settings_vlm_rows.reset_row_state
_vlm_recover_root_label = settings_vlm_rows.recover_root_label
_vlm_point_for_label = settings_vlm_rows.vlm_point_for_label


def _crawl_current_page(phone, **kwargs):
    return settings_navigation.crawl_current_page(
        phone,
        actions=walkthrough._navigation_actions(),
        **kwargs,
    )


def _open_settings_from_home_if_visible(phone) -> None:
    settings_bootstrap.open_settings_from_home_if_visible(phone, walkthrough._bootstrap_actions())


def _return_to_settings_root(phone) -> None:
    walkthrough._return_to_settings_root(phone)


def _scroll_to_vertical_boundary(phone, *, direction: str, max_steps: int = 5) -> None:
    settings_scrolling.scroll_to_vertical_boundary(
        phone,
        direction=direction,
        action_intent=walkthrough._action_intent,
        texts=settings_scene_state.texts,
        max_steps=max_steps,
    )


def _wheel_scroll_down(phone, ticks: int | None = None) -> None:
    settings_scrolling.wheel_scroll_down(
        phone,
        action_intent=walkthrough._action_intent,
        ticks=ticks,
    )


_enter_settings_search = walkthrough._enter_settings_search
def _ensure_settings_root(phone) -> bool:
    return settings_bootstrap.ensure_settings_root(phone, walkthrough._bootstrap_actions())


_return_one_level = walkthrough._return_one_level
_should_traverse_candidates = walkthrough._should_traverse_candidates
def _tap_settings_tab_from_search(phone, scene, *, allow_fallback: bool = True) -> bool:
    return walkthrough._tap_settings_tab_from_search(phone, scene, allow_fallback=allow_fallback)


_tap_visible_settings_root_result_from_system_search = (
    walkthrough._tap_visible_settings_root_result_from_system_search
)


def _el(text: str, x: int, y: int, w: int = 80, h: int = 20, *, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


def _scene_from_texts(texts: list[str]) -> Scene:
    return _scene(*[_el(text, 70, 260 + idx * 32, w=min(220, max(40, len(text) * 12)))
                    for idx, text in enumerate(texts)])


class _Phone:
    def __init__(self, scene: Scene):
        self.scene = scene

    def perceive(self) -> Scene:
        return self.scene


class _ScrollingPhone:
    def __init__(self, scenes: list[Scene]):
        self.scenes = scenes
        self.index = 0
        self.down_ticks: list[int | None] = []
        self.up_ticks: list[int | None] = []

    def perceive(self) -> Scene:
        return self.scenes[self.index]

    def swipe_up(self, *, fraction: float = 0.55) -> None:
        self.index = min(self.index + 1, len(self.scenes) - 1)

    def wheel_scroll_down(self, *, ticks: int | None = None) -> None:
        self.down_ticks.append(ticks)
        self.index = min(self.index + 1, len(self.scenes) - 1)

    def wheel_scroll_up(self, *, ticks: int | None = None) -> None:
        self.up_ticks.append(ticks)
        self.index = max(self.index - 1, 0)

    def invalidate_perceive_cache(self) -> None:
        pass


class _NoNavigationPhone:
    def __init__(self, scene: Scene):
        self.scene = scene
        self.taps: list[tuple[int, int]] = []

    def perceive(self) -> Scene:
        return self.scene

    def _viewport_size(self):
        return 448, 973

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def invalidate_perceive_cache(self) -> None:
        pass

    def swipe_up(self, *, fraction: float = 0.55) -> None:
        pass


class _BackFallbackPhone:
    def __init__(self, child: Scene, parent: Scene):
        self.child = child
        self.parent = parent
        self.did_tap_back = False
        self.keys: list[tuple[int, int]] = []
        self.taps: list[tuple[int, int]] = []

    def perceive(self) -> Scene:
        return self.parent if self.did_tap_back else self.child

    def key(self, modifier: int, keycode: int) -> None:
        self.keys.append((modifier, keycode))

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        self.did_tap_back = True

    def invalidate_perceive_cache(self) -> None:
        pass


class _SearchDismissPhone:
    def __init__(self, search_scene: Scene, root_scene: Scene):
        self.scene = search_scene
        self.root_scene = root_scene
        self.taps: list[tuple[int, int]] = []
        self.keys: list[tuple[int, int]] = []

    def perceive(self) -> Scene:
        return self.scene

    def key(self, modifier: int, keycode: int) -> None:
        self.keys.append((modifier, keycode))

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        self.scene = self.root_scene

    def invalidate_perceive_cache(self) -> None:
        pass


class _SearchTabFallbackPhone:
    def __init__(self, search_scene: Scene, search_empty_scene: Scene, root_scene: Scene):
        self.scene = search_scene
        self.search_empty_scene = search_empty_scene
        self.root_scene = root_scene
        self.taps: list[tuple[int, int]] = []
        self.keys: list[tuple[int, int]] = []

    def perceive(self) -> Scene:
        return self.scene

    def key(self, modifier: int, keycode: int) -> None:
        self.keys.append((modifier, keycode))

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        if len(self.taps) == 1:
            self.scene = self.search_empty_scene
        else:
            self.scene = self.root_scene

    def _viewport_size(self):
        return 448, 973

    def invalidate_perceive_cache(self) -> None:
        pass


class _TopLeftBackFallbackPhone:
    def __init__(self, child: Scene, root: Scene):
        self.scene = child
        self.root = root
        self.keys: list[tuple[int, int]] = []
        self.taps: list[tuple[int, int]] = []

    def perceive(self) -> Scene:
        return self.scene

    def key(self, modifier: int, keycode: int) -> None:
        self.keys.append((modifier, keycode))

    def tap_xy(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        self.scene = self.root

    def _viewport_size(self):
        return 448, 973

    def invalidate_perceive_cache(self) -> None:
        pass

__all__ = [name for name in globals() if not name.startswith("__")]
