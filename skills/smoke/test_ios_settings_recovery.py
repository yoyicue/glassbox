# ruff: noqa: F403,F405,I001,RUF012

from __future__ import annotations

from types import SimpleNamespace

from glassbox.effector import ActionResult
from skills.regression.ios_settings import context as settings_context
from skills.regression.ios_settings.recovery import SettingsRootUnreachable
from skills.smoke.ios_settings_walkthrough_support import *

@pytest.mark.smoke
def test_siri_page_suggestions_are_not_treated_as_settings_search():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("Siri", 198, 78, w=48),
        _el("建议", 70, 620, w=40),
        _el("搜索前建议 App", 80, 680, w=130),
    )

    assert not _is_settings_search_scene(scene)

@pytest.mark.smoke
def test_enter_settings_search_accepts_ocr_prefixed_bottom_search(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("通知", 80, 210, w=40),
        _el("专注模式", 80, 318, w=72),
        _el("Q 搜索", 198, 900, w=54),
    )
    search = _scene(
        _el("Q", 46, 906, w=24),
        _el("×", 382, 910, w=24, ty="button"),
    )

    class SearchPhone:
        def __init__(self):
            self.scene = root
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = search

        def invalidate_perceive_cache(self):
            pass

    phone = SearchPhone()

    assert _enter_settings_search(phone)
    assert phone.taps == [(225, 910)]


@pytest.mark.smoke
def test_enter_settings_search_uses_ipad_top_search_pill_hit_point(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    root = _scene(_el("Q Search", 34, 90, w=72), _el("Battery", 70, 226, w=48))
    search = _scene(_el("Q Search", 34, 90, w=72), _el("Select", 96, 132, w=40))
    field = root.elements[0]

    class SearchPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self):
            self.scene = root
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = search

        def invalidate_perceive_cache(self):
            pass

    phone = SearchPhone()
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: scene is root)
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda scene: scene is search)
    monkeypatch.setattr(walkthrough, "_find_root_search_tab", lambda _scene: field)

    assert _enter_settings_search(phone)
    assert phone.taps == [(151, 100)]


@pytest.mark.smoke
def test_ipad_top_search_detection_scales_with_pixel_viewport():
    field = _el("Q Search", 68, 184, w=144, h=40)

    phone = SimpleNamespace(
        device_geometry=SimpleNamespace(model="ipad_mini_7"),
        viewport_size=lambda: (1488, 2266),
    )

    assert walkthrough._is_ipad_top_search_field(phone, field)


@pytest.mark.smoke
def test_enter_settings_search_accepts_ipad_top_search_focus_without_scene_change(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    root = _scene(_el("Q Search", 34, 90, w=72), _el("Battery", 70, 226, w=48))
    field = root.elements[0]

    class SearchPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self):
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

        def invalidate_perceive_cache(self):
            pass

    phone = SearchPhone()
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: scene is root)
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda _scene: False)
    monkeypatch.setattr(walkthrough, "_find_root_search_tab", lambda _scene: field)

    assert _enter_settings_search(phone)
    assert phone.taps == [(151, 100)]


@pytest.mark.smoke
def test_return_to_settings_root_dismisses_settings_search(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    search = _scene(
        _el("建议", 18, 98, w=36),
        _el("Q通知", 46, 906, w=68),
        _el("×", 382, 910, w=24, ty="button"),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    phone = _SearchDismissPhone(search, root)

    _return_to_settings_root(phone)

    assert phone.taps == [(394, 920)]
    assert phone.keys == []

@pytest.mark.smoke
def test_return_to_settings_root_dismisses_search_when_clear_button_ocr_is_missing(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    search = _scene(
        _el("通知", 78, 126, w=36),
        _el("Q Tongzhi", 46, 908, w=94),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("通知", 80, 210, w=40),
        _el("专注模式", 80, 318, w=72),
        _el("Q 搜索", 198, 900, w=54),
    )
    phone = _SearchDismissPhone(search, root)

    _return_to_settings_root(phone)

    assert phone.taps == [(394, 924)]
    assert phone.keys == []


@pytest.mark.smoke
def test_dismiss_settings_search_does_not_bottom_tap_ipad_top_search_without_clear(monkeypatch):
    scene = _scene(_el("Battery", 56, 90, w=50))

    class Phone:
        def __init__(self):
            self.taps: list[tuple[int, int]] = []

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

    phone = Phone()
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_clear_button", lambda _scene: None)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda _scene: scene.elements[0])
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda _scene: True)

    assert not walkthrough._dismiss_settings_search(phone, scene)
    assert phone.taps == []


@pytest.mark.smoke
def test_dismiss_settings_search_clears_ipad_top_query_with_keyboard(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    scene = _scene(_el("Q Battery", 34, 90, w=90))
    cleared = _scene(_el("Q Search", 34, 90, w=72))

    class Phone:
        def __init__(self):
            self.scene = scene
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self):
            pass

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))
            if (modifier, keycode) == (0, 0x2A):
                self.scene = cleared

    phone = Phone()
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda _scene: True)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_clear_button", lambda _scene: None)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda _scene: scene.elements[0])
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda current: current is not cleared)

    assert walkthrough._dismiss_settings_search(phone, scene)
    assert phone.taps == [scene.elements[0].box.center]
    assert phone.keys == [(0x08, 0x04), (0, 0x2A)]


@pytest.mark.smoke
def test_dismiss_settings_search_clears_ipad_top_query_via_edit_menu(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    query = _scene(_el("Q Battery", 34, 90, w=90))
    select_all_menu = _scene(
        _el("Q Battery", 34, 90, w=90),
        _el("Select", 54, 132, w=42),
        _el("Select All", 118, 132, w=60),
        _el("AutoFill", 202, 132, w=48),
    )
    cut_menu = _scene(
        _el("Q", 34, 90, w=16),
        _el("Battery", 52, 80, w=98),
        _el("Cut Copy", 36, 132, w=80),
        _el("AutoFill", 140, 132, w=48),
    )
    cleared = _scene(_el("Q Search", 34, 90, w=72))

    class Phone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self):
            self.scene = query
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []
            self.long_presses: list[tuple[int, int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self):
            pass

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            if self.scene is cut_menu:
                self.scene = cleared
            elif self.scene is select_all_menu:
                self.scene = cut_menu

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def long_press_xy(self, x: int, y: int, *, hold_ms: int = 500, target: str | None = None):
            _ = target
            self.long_presses.append((x, y, hold_ms))
            self.scene = select_all_menu

    phone = Phone()
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda _scene: True)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_clear_button", lambda _scene: None)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda _scene: query.elements[0])
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda current: current is not cleared)

    assert walkthrough._dismiss_settings_search(phone, query)
    assert phone.keys == []
    assert phone.long_presses == [(121, 100, 1600)]
    assert phone.taps[-2:] == [(148, 142), (52, 142)]


@pytest.mark.smoke
def test_clear_settings_search_fails_when_ipad_top_query_does_not_clear(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    scene = _scene(_el("Q Battery", 34, 90, w=90))

    class Phone:
        def __init__(self):
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return scene

        def invalidate_perceive_cache(self):
            pass

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

    phone = Phone()
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda _scene: True)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_clear_button", lambda _scene: None)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda _scene: scene.elements[0])
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda _scene: True)

    assert not walkthrough._clear_settings_search(phone)
    assert phone.taps
    assert phone.keys


@pytest.mark.smoke
def test_clear_settings_search_handles_ipad_top_query_even_when_scene_not_search(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    query = _scene(_el("Q Battery", 34, 90, w=90), _el("Battery", 404, 44, w=90))
    cleared = _scene(_el("Q Search", 34, 90, w=72), _el("Battery", 404, 44, w=90))

    class Phone:
        def __init__(self):
            self.scene = query
            self.keys: list[tuple[int, int]] = []
            self.entered_search = False

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self):
            pass

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, _x: int, _y: int):
            pass

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))
            if (modifier, keycode) == (0, 0x2A):
                self.scene = cleared

    phone = Phone()
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda _scene: False)
    monkeypatch.setattr(walkthrough, "_enter_settings_search", lambda _phone: setattr(phone, "entered_search", True) or False)
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda scene: scene.elements[0])
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda scene: scene is query)

    assert walkthrough._clear_settings_search(phone)
    assert phone.keys == [(0x08, 0x04), (0, 0x2A)]
    assert phone.entered_search is False


@pytest.mark.smoke
def test_clear_settings_search_focuses_hidden_ipad_top_query_before_clear(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    hidden = _scene(_el("No Results for", 72, 520, w=120), _el('"Baer"', 72, 548, w=80))
    focused = _scene(_el("Baer", 54, 90, w=42))
    cleared = _scene(_el("Q Search", 34, 90, w=72), _el("Suggestions", 40, 134, w=66))

    class Phone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self):
            self.scene = hidden
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self):
            pass

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            if self.scene is hidden:
                self.scene = focused

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))
            if (modifier, keycode) == (0, 0x2A):
                self.scene = cleared

    phone = Phone()
    monkeypatch.setattr(
        walkthrough.settings_scene_state,
        "find_search_field",
        lambda scene: scene.elements[0] if scene is focused or scene is cleared else None,
    )
    monkeypatch.setattr(walkthrough, "_is_settings_search_scene", lambda scene: scene is hidden or scene is focused)
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda scene: scene is not cleared)

    assert walkthrough._clear_settings_search(phone)
    assert phone.taps[0] == (151, 99)
    assert phone.keys == [(0x08, 0x04), (0, 0x2A)]


@pytest.mark.smoke
def test_clear_settings_search_accepts_empty_ipad_top_search_with_edit_menu(monkeypatch):
    scene = _scene(
        _el("Q Search", 34, 90, w=72),
        _el("Paste", 62, 132, w=42),
        _el("AutoFill", 126, 132, w=48),
    )

    class Phone:
        def perceive(self):
            return scene

    phone = Phone()
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda _scene: scene.elements[0])
    monkeypatch.setattr(walkthrough, "_settings_search_has_query_text", lambda _scene: True)

    assert walkthrough._clear_settings_search(phone)


@pytest.mark.smoke
def test_return_to_settings_root_can_leave_search_via_settings_tab(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    search = _scene(
        _el("通知", 90, 265, w=40),
        _el("Q通知", 46, 906, w=68),
        _el("×", 382, 910, w=24, ty="button"),
    )
    search_empty = _scene(
        _el("搜索", 46, 906, w=68),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    phone = _SearchTabFallbackPhone(search, search_empty, root)

    _return_to_settings_root(phone)

    assert phone.taps == [(394, 920), (112, 885)]
    assert phone.keys == [(0x08, 0x2F)]

@pytest.mark.smoke
def test_return_to_settings_root_recovers_from_system_search_via_home(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    system_search = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("AI办公", 56, 212, w=54, ty="button"),
        _el("最近1", 18, 410, w=46),
        _el("DemoApp", 56, 708, w=78),
        _el("TestFlight", 56, 764, w=82),
        _el("Q 搜索", 48, 912, w=62),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class SystemSearchPhone:
        def __init__(self):
            self.scene = system_search
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []
            self.homes = 0

        def perceive(self):
            return self.scene

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def home(self):
            self.homes += 1
            self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = SystemSearchPhone()

    _return_to_settings_root(phone)

    assert phone.homes == 1
    assert phone.taps == []
    assert phone.keys == []

@pytest.mark.smoke
def test_system_search_bootstrap_taps_safe_settings_root_result_row_lead(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("通用", 56, 212, w=36, ty="button"),
        _el("Bluetooth", 56, 274, w=78, ty="button"),
        _el("面容ID与密码", 58, 710, w=106, ty="button"),
        _el("Q 搜索", 48, 912, w=62),
    )
    root = _scene(_el("设置", 196, 72, w=48), _el("无线局域网", 54, 218, w=88))
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda current: current is root)

    class OpeningSystemSearchPhone(_NoNavigationPhone):
        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = root
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="succeeded",
            )

    phone = OpeningSystemSearchPhone(scene)

    assert _tap_visible_settings_root_result_from_system_search(phone, scene)
    assert phone.taps == [(32, 222)]


@pytest.mark.smoke
def test_system_search_bootstrap_taps_settings_icon_above_label():
    label = _el("Settings", 108, 238, w=44, h=10)

    assert walkthrough._system_search_root_result_tap_point(
        label,
        label="Settings",
        viewport_size=(644, 984),
    ) == (130, 199)


@pytest.mark.smoke
def test_system_search_bootstrap_rejects_no_progress_after_semantic_success(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("通用", 56, 212, w=36, ty="button"),
        _el("Q 搜索", 48, 912, w=62),
    )

    class NoProgressSystemSearchPhone(_NoNavigationPhone):
        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="succeeded",
                semantic_reason="scene changed after action",
            )

    phone = NoProgressSystemSearchPhone(scene)

    assert not _tap_visible_settings_root_result_from_system_search(phone, scene)
    assert phone.taps == [(32, 222)]

@pytest.mark.smoke
def test_system_search_bootstrap_rejects_unsafe_settings_result():
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("面容ID与密码", 58, 212, w=106, ty="button"),
        _el("Q 搜索", 48, 912, w=62),
    )
    phone = _NoNavigationPhone(scene)

    assert not _tap_visible_settings_root_result_from_system_search(phone, scene)
    assert phone.taps == []

@pytest.mark.smoke
def test_enter_settings_search_marks_global_system_search_unavailable(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    root = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
        _el("Q 搜索", 48, 912, w=62),
    )
    system_search = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("通用", 56, 212, w=36, ty="button"),
        _el("Q 搜索", 48, 912, w=62),
    )

    class SearchPhone:
        def __init__(self):
            self.scene = root
            self.taps: list[tuple[int, int]] = []

        def perceive(self) -> Scene:
            return self.scene

        def tap_xy(self, x: int, y: int) -> None:
            self.taps.append((x, y))
            self.scene = system_search

        def invalidate_perceive_cache(self) -> None:
            pass

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

    phone = SearchPhone()

    assert not _enter_settings_search(phone)
    assert settings_context.search_unavailable(phone) is True
    assert phone.taps == [(79, 922)]

@pytest.mark.smoke
def test_settings_search_results_scene_without_bottom_ocr_is_detected():
    search_results = _scene(
        _el("通知", 76, 126, w=40, ty="button"),
        _el("显示通知", 78, 180, w=68, ty="button"),
        _el("待机显示", 76, 198, w=54),
        _el("通知样式", 78, 244, w=72, ty="button"),
        _el("通知", 76, 262, w=40),
        _el("耳机通知", 78, 496, w=72, ty="button"),
        _el("辅助功能～音频与视觉", 78, 514, w=160),
    )

    assert _is_settings_search_scene(search_results)

@pytest.mark.smoke
def test_settings_app_search_chrome_is_not_settings_tab_search():
    settings_app_list = _scene(
        _el("默认 App", 80, 118, w=70),
        _el("管理iPhone上的默认 App", 82, 140, w=142),
        _el("App Store", 80, 301, w=80),
        _el("启用听写？", 90, 361, w=80, ty="button"),
        _el("使用你的声音在可键入的位置听写文", 90, 388, w=244),
        _el("Q", 48, 911, w=18, ty="tab_bar_item"),
        _el("搜索 App", 74, 910, w=72, ty="tab_bar_item"),
        _el("X", 384, 911, w=20, ty="tab_bar_item"),
    )

    assert not _is_settings_search_scene(settings_app_list)

@pytest.mark.smoke
def test_scrolled_app_settings_detail_is_not_settings_search_results():
    scene = _scene(
        _el("通讯录", 40, 230, w=66, h=24, ty="button"),
        _el("添加或移除账户、管理“Siri与搜索”", 38, 256, w=277, h=31),
        _el("联系人的显示方式。进一步了解…", 40, 284, w=262, h=22),
        _el("通讯录账户", 38, 337, w=88, ty="button"),
        _el("1>", 380, 338, w=26),
        _el("允许“通讯录”访问", 40, 402, w=144),
        _el("Siri", 80, 448, w=26, ty="button"),
        _el("搜索", 80, 499, w=38, ty="button"),
        _el("共享姓名和照片", 40, 591, w=120, ty="button"),
        _el("关闭＞", 352, 591, w=56),
        _el("选择姓名和照片以及谁可以看到你共享的内容，来个性化信息。", 38, 635, w=366),
        _el("提供商", 38, 693, w=54, ty="button"),
        _el("显示联系人照片", 40, 783, w=120, ty="button"),
        _el("排列顺序", 38, 837, w=72, ty="button"),
        _el("显示顺序", 38, 893, w=72, ty="button"),
        _el("短名称", 38, 947, w=54, ty="button"),
        _el("名，姓＞", 334, 891, w=74),
    )

    assert not _is_settings_search_scene(scene)

@pytest.mark.smoke
def test_return_to_settings_root_exits_search_results_after_back(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    notification_page = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通知", 198, 78, w=48),
        _el("显示为", 80, 240, w=54),
    )
    search_results = _scene(
        _el("通知", 76, 126, w=40, ty="button"),
        _el("显示通知", 78, 180, w=68, ty="button"),
        _el("待机显示", 76, 198, w=54),
        _el("通知样式", 78, 244, w=72, ty="button"),
        _el("通知", 76, 262, w=40),
        _el("耳机通知", 78, 496, w=72, ty="button"),
        _el("辅助功能～音频与视觉", 78, 514, w=160),
    )
    search_empty = _scene(
        _el("搜索", 46, 906, w=68),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class SearchBackPhone:
        def __init__(self):
            self.scene = notification_page
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            if len(self.taps) == 1:
                self.scene = search_results
            elif len(self.taps) == 2:
                self.scene = search_empty
            else:
                self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = SearchBackPhone()

    _return_to_settings_root(phone)

    assert phone.taps == [(25, 82), (112, 885), (112, 885)]
    assert phone.keys == [(0x08, 0x2F), (0x08, 0x2F)]

@pytest.mark.smoke
def test_return_to_settings_root_exits_search_results_without_tapping_result(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    search_results = _scene(
        _el("通知", 76, 126, w=40, ty="button"),
        _el("显示通知", 78, 180, w=68, ty="button"),
        _el("待机显示", 76, 198, w=54),
        _el("通知样式", 78, 244, w=72, ty="button"),
        _el("通知", 76, 262, w=40),
        _el("耳机通知", 78, 496, w=72, ty="button"),
        _el("辅助功能～音频与视觉", 78, 514, w=160),
    )
    search_empty = _scene(_el("搜索", 46, 906, w=68))
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    deep_result = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("音频与视觉", 168, 78, w=96),
        _el("耳机通知", 78, 260, w=72),
    )

    class SearchResultsPhone:
        def __init__(self):
            self.scene = search_results
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            if y < 850:
                self.scene = deep_result
            elif len(self.taps) == 1:
                self.scene = search_empty
            else:
                self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = SearchResultsPhone()

    _return_to_settings_root(phone)

    assert phone.taps == [(112, 885), (112, 885)]
    assert phone.keys == [(0x08, 0x2F), (0x08, 0x2F)]
    assert phone.perceive() == root

@pytest.mark.smoke
def test_settings_tab_from_search_taps_upper_hit_region():
    search = _scene(
        _el("Q通知", 46, 906, w=68),
        _el("设置", 300, 929, w=22, h=10, ty="tab_bar_item"),
        _el("搜索", 126, 929, w=22, h=10, ty="tab_bar_item"),
    )
    phone = _NoNavigationPhone(search)

    assert _tap_settings_tab_from_search(phone, search)

    assert phone.taps == [(311, 885)]

@pytest.mark.smoke
def test_settings_tab_from_search_rejects_semantic_failure():
    search = _scene(
        _el("Q通知", 46, 906, w=68),
        _el("设置", 300, 929, w=22, h=10, ty="tab_bar_item"),
        _el("搜索", 126, 929, w=22, h=10, ty="tab_bar_item"),
    )

    class SemanticFailedSettingsTabPhone:
        def __init__(self):
            self.taps: list[tuple[int, int]] = []

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="failed",
                semantic_reason="tab tap did not navigate",
            )

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

    phone = SemanticFailedSettingsTabPhone()

    assert not _tap_settings_tab_from_search(phone, search)
    assert phone.taps == [(311, 885)]


@pytest.mark.smoke
def test_tap_search_field_rejects_semantic_failure():
    search = _scene(_el("搜索", 46, 906, w=68))

    class SemanticFailedSearchFieldPhone:
        def __init__(self):
            self.taps: list[tuple[int, int]] = []

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="approval_required",
                semantic_reason="permission dialog is visible",
            )

    phone = SemanticFailedSearchFieldPhone()

    assert not walkthrough._tap_search_field(phone, search)
    assert phone.taps == [(80, 916)]


@pytest.mark.smoke
def test_tap_search_field_uses_ipad_top_search_pill_hit_point(monkeypatch):
    search = _scene(_el("Q Search", 34, 90, w=72))

    class SearchFieldPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self):
            self.taps: list[tuple[int, int]] = []

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 640, 990

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

    phone = SearchFieldPhone()
    monkeypatch.setattr(walkthrough.settings_scene_state, "find_search_field", lambda _scene: search.elements[0])

    assert walkthrough._tap_search_field(phone, search)
    assert phone.taps == [(151, 100)]


@pytest.mark.smoke
def test_tap_settings_row_rejects_semantic_failure():
    row = _el("蓝牙", 80, 424, w=40)

    class SemanticFailedRowPhone:
        def __init__(self):
            self.taps: list[tuple[int, int]] = []

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="failed",
                semantic_reason="row tap did not navigate",
            )

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

    phone = SemanticFailedRowPhone()

    assert not walkthrough._tap_settings_row(phone, row)
    assert phone.taps == [(125, 434)]

@pytest.mark.smoke
def test_return_to_settings_root_uses_fixed_top_left_back_fallback(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    child = _scene(
        _el("辅助功能", 176, 78, w=76),
        _el("触控", 80, 320, w=40),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    phone = _TopLeftBackFallbackPhone(child, root)

    _return_to_settings_root(phone)

    assert phone.keys == [(0x08, 0x2F)]
    assert phone.taps == [(24, 82)]

@pytest.mark.smoke
def test_return_to_settings_root_does_not_blind_tap_blocked_safety(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    blocked = _scene(
        _el("退出登录", 18, 78, w=72, ty="button"),
        _el("欢迎来到 Game Center", 92, 160, w=220),
        _el("继续", 188, 835, w=80, ty="button"),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class BlockedPhone:
        def __init__(self):
            self.scene = blocked
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []
            self.back_gestures = 0

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

        def back_gesture(self):
            self.back_gestures += 1
            self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = BlockedPhone()

    _return_to_settings_root(phone)

    assert phone.keys == [(0x08, 0x2F)]
    assert phone.back_gestures == 1
    assert phone.taps == []

@pytest.mark.smoke
def test_return_to_settings_root_uses_back_for_settings_app_search_page(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    app_list = _scene(
        _el("默认 App", 80, 118, w=70),
        _el("管理iPhone上的默认 App", 82, 140, w=142),
        _el("App Store", 80, 301, w=80),
        _el("启用听写？", 90, 361, w=80, ty="button"),
        _el("使用你的声音在可键入的位置听写文", 90, 388, w=244),
        _el("电话", 80, 687, w=36, ty="button"),
        _el("Q", 48, 911, w=18, ty="tab_bar_item"),
        _el("搜索 App", 74, 910, w=72, ty="tab_bar_item"),
        _el("X", 384, 911, w=20, ty="tab_bar_item"),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class AppListPhone:
        def __init__(self):
            self.scene = app_list
            self.keys: list[tuple[int, int]] = []
            self.taps: list[tuple[int, int]] = []
            self.back_gestures = 0

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))

        def back_gesture(self):
            self.back_gestures += 1
            self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = AppListPhone()

    _return_to_settings_root(phone)

    assert phone.keys == [(0x08, 0x2F)]
    assert phone.back_gestures == 1
    assert phone.taps == []

@pytest.mark.smoke
def test_return_to_settings_root_uses_edge_back_when_unknown_page_only_has_ocr_noise(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    unknown_a = _scene(
        _el("••0•。", 182, 572, w=86),
        _el("静音模式", 166, 606, w=112, ty="button"),
        _el("为通话和提醒切換静音和响铃。", 120, 646, w=210),
    )
    unknown_b = _scene(
        _el("••〇•o", 182, 572, w=86),
        _el("静音模式", 166, 606, w=112, ty="button"),
        _el("为通话和提醒切換静音和响铃。", 120, 646, w=210),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class UnknownPhone:
        def __init__(self):
            self.scene = unknown_a
            self.keys: list[tuple[int, int]] = []
            self.back_gestures = 0

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))
            self.scene = unknown_b

        def back_gesture(self):
            self.back_gestures += 1
            self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = UnknownPhone()

    _return_to_settings_root(phone)

    assert phone.keys == [(0x08, 0x2F)]
    assert phone.back_gestures == 1


@pytest.mark.smoke
def test_return_to_settings_root_reopens_settings_from_weather_surface(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    weather = _scene(
        _el("Q Search for a city or ai...0", 36, 94, w=188),
        _el("MY LOCATION", 408, 130, w=80),
        _el("Daxing", 401, 148, w=92),
        _el("34°", 402, 184, w=112),
        _el("Sunny conditions will continue for the rest of the day.", 292, 402, w=280),
        _el("10-DAY FORECAST", 294, 576, w=120),
        _el("Today", 290, 614, w=50),
        _el("Tue", 292, 662, w=32),
    )
    root = _scene(
        _el("Settings", 198, 72, w=64),
        _el("WLAN", 80, 370, w=46),
        _el("Bluetooth", 80, 424, w=78),
        _el("General", 80, 725, w=62),
    )

    class WeatherPhone:
        def __init__(self):
            self.scene = weather
            self.open_calls: list[tuple[str, tuple[str, ...]]] = []
            self.keys: list[tuple[int, int]] = []
            self.back_gestures = 0

        def perceive(self):
            return self.scene

        def open_app(self, label, *, aliases=(), max_pages=8, settle_s=0.8):
            self.open_calls.append((label, tuple(aliases)))
            self.scene = root
            return True

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def back_gesture(self):
            self.back_gestures += 1

        def viewport_size(self):
            return 640, 989

        def invalidate_perceive_cache(self):
            pass

    phone = WeatherPhone()

    _return_to_settings_root(phone)

    assert phone.open_calls == [("设置", ("Settings",))]
    assert phone.keys == []
    assert phone.back_gestures == 0


@pytest.mark.smoke
def test_return_to_settings_root_stops_when_back_shortcut_semantically_fails(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    unknown = _scene(
        _el("静音模式", 166, 606, w=112, ty="button"),
        _el("为通话和提醒切換静音和响铃。", 120, 646, w=210),
    )

    class SemanticFailedBackPhone:
        def __init__(self):
            self.scene = unknown
            self.keys: list[tuple[int, int]] = []
            self.back_gestures = 0

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="approval_required",
                semantic_reason="permission dialog is visible",
            )

        def back_gesture(self):
            self.back_gestures += 1
            raise AssertionError("back_gesture should not run after semantic rejection")

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    with pytest.raises(SettingsRootUnreachable, match="failed to return"):
        _return_to_settings_root(SemanticFailedBackPhone())


@pytest.mark.smoke
def test_return_to_settings_root_can_use_safe_utg_home_edge(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    unknown = _scene(
        _el("••0•。", 182, 572, w=86),
        _el("静音模式", 166, 606, w=112, ty="button"),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class Node:
        screen_id = "unknown"

    class Edge:
        action_op = "home"
        action_kwargs: ClassVar[dict[str, int]] = {}
        success_rate = 1.0

    class Memory:
        def recognize(self, scene):
            return Node()

        def path_to_page(self, *args, **kwargs):
            assert kwargs["allowed_actions"] == {"home", "back"}
            assert kwargs["min_success_rate"] == 0.5
            return [Edge()]

    class UnknownPhone:
        def __init__(self):
            self.scene = unknown
            self.memory = Memory()
            self.homes = 0
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def home(self):
            self.homes += 1
            self.scene = root

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = UnknownPhone()

    _return_to_settings_root(phone)

    assert phone.homes == 1
    assert phone.keys == []


@pytest.mark.smoke
def test_tap_top_left_back_fallback_rejects_semantic_failure():
    child = _scene(
        _el("Game Center", 178, 78, w=110),
        _el("邀请朋友", 80, 160, w=72),
    )

    class SemanticFailedTapPhone:
        def __init__(self):
            self.scene = child
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="failed",
                semantic_reason="tap did not navigate",
            )

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

    phone = SemanticFailedTapPhone()

    assert not walkthrough._tap_top_left_back_fallback(phone)
    assert phone.taps == [(24, 82)]

@pytest.mark.smoke
def test_ensure_settings_root_returns_from_detail_without_back_ocr(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    child = _scene(
        _el("Game Center", 178, 78, w=110),
        _el("邀请朋友", 80, 160, w=72),
        _el("共享朋友列表", 80, 250, w=110, ty="button"),
        _el("允许 App访问你的GameCenter朋友列表，改进游戏体验。", 32, 292, w=360),
        _el("是否对他人可见", 80, 328, w=126),
        _el("帮助朋友找到你", 80, 376, w=124, ty="button"),
        _el("使用 Apple账户关联的电子邮件地址和电话号码，让Game", 32, 420, w=360),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    phone = _TopLeftBackFallbackPhone(child, root)

    assert _ensure_settings_root(phone)
    assert phone.taps == [(24, 82)]

@pytest.mark.smoke
def test_ensure_settings_root_returns_from_unknown_restored_settings_page(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "_wait_settings_root", lambda phone, timeout=8.0: False)
    unknown = _scene(
        _el("静音模式", 166, 606, w=112, ty="button"),
        _el("为通话和提醒切換静音和响铃。", 120, 646, w=210),
    )
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    class UnknownRestoredPhone:
        def __init__(self):
            self.scene = unknown
            self.keys: list[tuple[int, int]] = []
            self.back_gestures = 0

        def perceive(self):
            return self.scene

        def key(self, modifier: int, keycode: int):
            self.keys.append((modifier, keycode))

        def back_gesture(self):
            self.back_gestures += 1
            self.scene = root

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self):
            return 448, 973

        def invalidate_perceive_cache(self):
            pass

    phone = UnknownRestoredPhone()

    assert _ensure_settings_root(phone)
    assert phone.keys == [(0x08, 0x2F)]
    assert phone.back_gestures == 1

@pytest.mark.smoke
def test_open_settings_helper_skips_when_springboard_does_not_reach_settings(monkeypatch):
    scene = _scene(
        _el("其他App", 196, 78, w=70),
        _el("不是设置", 80, 340, w=90),
    )
    phone = _Phone(scene)

    monkeypatch.setattr(walkthrough, "_wait_settings_root", lambda phone, timeout=10.0: False)
    monkeypatch.setattr(walkthrough, "_ensure_settings_root", lambda phone: False)
    monkeypatch.setattr(walkthrough, "open_app_from_springboard", lambda phone, labels, max_pages=8: True)

    with pytest.raises(SettingsCrawlerUnavailable):
        _open_settings_from_home_if_visible(phone)

# ── modal-dismiss rung: auto-presented card sheets (Apple Account family) ─────
# Evidence: iphone_transition_n1 (2026-06-12). The sheet ate every escape rung
# (back_gesture, tap_xy(24,83) top-LEFT mirror miss, tap_xy(394,938) next to
# the bottom "Change trusted number" button, back_gesture) until recovery
# exhausted. The rung below taps ONLY the top-right close-X, bounded at 2
# attempts per recovery episode, then abstains to the existing ladder.
# Scenes constructed from the recorded shape with synthetic values.


def _modal_safety_sheet_scene():
    return _scene(
        _el("X", 394, 102, w=20, h=18, ty="button"),
        _el("Is this still your phone number?", 36, 155, w=328, h=147, ty="button"),
        _el("Current trusted number:", 38, 308, w=248, h=22),
        _el("+1 (555) 010-4477", 38, 336, w=192, h=24),
        _el("It is important to make sure your", 36, 457, w=314, h=23),
        _el("trusted phone number is correct so", 36, 486, w=340, h=22),
        _el("number is used to verify your identity.", 38, 648, w=361, h=22),
        _el("Messaging and data rates may apply.", 38, 676, w=358, h=24),
        _el("Keep using +1 (555) 010-4477", 98, 838, w=252, ty="button"),
        _el("Change trusted number", 128, 902, w=194, h=18, ty="button"),
    )


class _ModalSheetPhone:
    def __init__(self, sheet, root, *, dismiss_on_close_tap: bool):
        self.scene = sheet
        self._root = root
        self._dismiss_on_close_tap = dismiss_on_close_tap
        self.taps: list[tuple[int, int]] = []
        self.keys: list[tuple[int, int]] = []
        self.back_gestures = 0

    def perceive(self):
        return self.scene

    def tap_xy(self, x: int, y: int):
        self.taps.append((x, y))
        if self._dismiss_on_close_tap and x >= 448 * 0.75 and y <= 973 * 0.20:
            self.scene = self._root

    def key(self, modifier: int, keycode: int):
        self.keys.append((modifier, keycode))

    def back_gesture(self):
        self.back_gestures += 1

    def viewport_size(self):
        return 448, 973

    def invalidate_perceive_cache(self):
        pass


def _zh_root_scene():
    return _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )


@pytest.mark.smoke
def test_return_to_settings_root_dismisses_modal_sheet_via_close_x(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    phone = _ModalSheetPhone(_modal_safety_sheet_scene(), _zh_root_scene(), dismiss_on_close_tap=True)

    _return_to_settings_root(phone)

    # Exactly one tap, at the OCR'd close-X — no back shortcut, no springboard
    # climb, no blind corner/bottom taps.
    assert phone.taps == [(404, 111)]
    assert phone.keys == []
    assert phone.back_gestures == 0


@pytest.mark.smoke
def test_return_to_settings_root_modal_dismiss_is_bounded_and_read_only(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    phone = _ModalSheetPhone(_modal_safety_sheet_scene(), _zh_root_scene(), dismiss_on_close_tap=False)

    with pytest.raises(SettingsRootUnreachable):
        _return_to_settings_root(phone)

    # Bounded: at most 2 close-X dismiss attempts per recovery episode, then
    # the existing unknown-state ladder takes over (back shortcut), and the
    # episode ends in the catchable SettingsRootUnreachable — never a blind
    # bottom tap.
    close_region_taps = [(x, y) for x, y in phone.taps if x >= 448 * 0.75 and y <= 973 * 0.20]
    assert len(close_region_taps) == 2
    # READ-ONLY pin: button rows ("Keep using …" / "Change trusted number")
    # are visible, so EVERY tap must stay inside the top-right close band —
    # the live failure's tap_xy(394,938) landed beside "Change trusted number".
    assert phone.taps == close_region_taps
    assert phone.keys  # existing ladder (back shortcut) still ran after abstain


@pytest.mark.smoke
def test_return_one_level_abstains_on_modal_sheet_instead_of_corner_tap(monkeypatch):
    """The live failure's first two wasted rungs came from `_return_one_level`
    on the sheet: an inert back shortcut, then the top-LEFT corner fallback
    tap_xy(24,83) — a mirror miss on the sheet's top-RIGHT close-X. On modal
    evidence the helper must abstain immediately (no key, no tap) so the
    caller falls through to `return_to_settings_root`'s bounded modal rung."""
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    phone = _ModalSheetPhone(_modal_safety_sheet_scene(), _zh_root_scene(), dismiss_on_close_tap=True)

    assert not _return_one_level(
        phone,
        parent_texts=["Settings", "General"],
        parent_title="Settings",
        parent_is_root=True,
    )
    assert phone.taps == []
    assert phone.keys == []
    assert phone.back_gestures == 0
