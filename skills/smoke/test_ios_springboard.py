from __future__ import annotations

from types import SimpleNamespace

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.ios.springboard import (
    _icon_label_candidates,
    _opened_expected_app_or_recover,
    find_springboard_icon,
    is_ios_home_screen,
    open_app_from_springboard,
    open_app_via_spotlight,
)


def _el(text: str, x: int, y: int, w: int = 54, h: int = 20) -> UIElement:
    return UIElement(type="text", box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


@pytest.mark.smoke
def test_strict_springboard_requires_icon_grid_corroboration():
    """CUQ-2.2: a detail page the single-frame classifier mislabels 'springboard'
    is trusted as Home by default but rejected in strict mode (needs an icon
    grid); a genuine grid is Home in both modes."""
    mislabeled = Scene(
        frame_id=0,
        timestamp=0.0,
        platform_scene_kind="springboard",  # single-frame classifier mislabel
        elements=[_el("详情", 20, 200), _el("一行说明文本内容比较长", 20, 260, w=200)],
    )
    assert is_ios_home_screen(mislabeled, viewport_size=(440, 956))  # default trusts label
    assert not is_ios_home_screen(
        mislabeled, viewport_size=(440, 956), strict_springboard=True
    )  # strict: no icon grid -> not Home

    grid = _scene(
        _el("文件", 42, 176), _el("预览", 154, 176), _el("DemoApp", 252, 176, w=82),
        _el("GlassboxHelper", 42, 316, w=78), _el("搜索", 196, 892, w=48),
    )
    assert is_ios_home_screen(grid, viewport_size=(440, 956))
    assert is_ios_home_screen(grid, viewport_size=(440, 956), strict_springboard=True)


@pytest.mark.smoke
def test_ios_home_screen_recognizes_icon_grid():
    scene = _scene(
        _el("文件", 42, 176),
        _el("预览", 154, 176),
        _el("DemoApp", 252, 176, w=82),
        _el("GlassboxHelper", 42, 316, w=78),
        _el("搜索", 196, 892, w=48),
    )

    assert is_ios_home_screen(scene, viewport_size=(440, 956))


@pytest.mark.smoke
def test_ios_home_screen_accepts_weather_widget_page_misread_as_settings_detail():
    scene = _scene(
        _el("上海市", 52, 118),
        _el("21°", 52, 144, w=64, h=36),
        _el("多云", 52, 212, w=32),
        _el("号27°番19°", 52, 234, w=110),
        _el("今天无日程", 256, 206, w=100),
        _el("FaceTime通话", 54, 400, w=90),
        _el("日历", 164, 400, w=42),
        _el("照片", 276, 400, w=42),
        _el("相机", 386, 400, w=42),
        _el("备忘录", 54, 510, w=54),
        _el("时钟", 164, 510, w=42),
        _el("游戏", 276, 510, w=42),
        _el("App Store", 386, 510, w=82),
        _el("钱包", 54, 620, w=42),
        _el("设置", 164, 620, w=42),
        _el("RustDesk", 276, 620, w=78),
        _el("门", 356, 880, w=38, h=44),
    )

    assert is_ios_home_screen(scene, viewport_size=(448, 973))
    assert find_springboard_icon(scene, ("设置", "Settings"), viewport_size=(448, 973)) is not None


@pytest.mark.smoke
def test_ios_home_screen_rejects_settings_list():
    scene = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
        _el("蜂窝网络", 54, 326, w=72),
        _el("通知", 54, 430, w=42),
        _el("通用", 54, 484, w=42),
    )

    assert not is_ios_home_screen(scene, viewport_size=(440, 956))


@pytest.mark.smoke
def test_ios_home_screen_rejects_scrolled_settings_root_with_bottom_search():
    scene = _scene(
        _el("设置", 196, 72, w=48),
        _el("通知", 54, 218, w=42),
        _el("声效与触感反馈", 54, 272, w=112),
        _el("专注模式", 54, 326, w=72),
        _el("屏幕时间", 54, 380, w=72),
        _el("面容ID与密码", 54, 486, w=108),
        _el("隐私与安全性", 54, 594, w=108),
        _el("钱包与 Apple Pay", 54, 648, w=132),
        _el("Game Center", 54, 702, w=96),
        _el("Q 搜索", 196, 892, w=54),
    )

    assert not is_ios_home_screen(scene, viewport_size=(440, 956))


@pytest.mark.smoke
def test_ios_home_screen_rejects_hidagent_service_page():
    scene = _scene(
        _el("服务", 20, 128, w=66, h=34),
        _el("服务有问题", 170, 290, w=110, h=26),
        _el("Mac 大脑", 68, 577, w=74),
        _el("最近活动", 14, 715, w=62),
        _el("设置", 300, 929, w=22, h=10),
    )

    assert not is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_home_screen_rejects_clock_app_grid_like_world_clock():
    scene = _scene(
        _el("World Clock", 320, 78, w=94),
        _el("Alarms", 410, 78, w=58),
        _el("Stopwatch", 502, 78, w=84),
        _el("Timers", 592, 78, w=54),
        _el("San Francisco", 320, 166, w=110),
        _el("London", 320, 252, w=66),
        _el("Paris", 320, 338, w=48),
        _el("Moscow", 320, 424, w=72),
        _el("Beijing", 320, 510, w=66),
        _el("12", 462, 192, w=20),
        _el("11", 482, 224, w=20),
        _el("10", 502, 256, w=20),
        _el("9", 522, 288, w=20),
        _el("8", 542, 320, w=20),
    )

    assert not is_ios_home_screen(scene, viewport_size=(640, 964))


@pytest.mark.smoke
def test_assistive_touch_menu_labels_are_not_home_icon_candidates():
    scene = _scene(
        _el("Home", 142, 620, w=54),
        _el("Camera", 260, 620, w=62),
        _el("Files", 502, 420, w=50),
        _el("App Switcher", 368, 720, w=92),
        _el("Notification", 462, 656, w=88),
        _el("Centre", 462, 678, w=54),
        _el("Device", 558, 720, w=58),
        _el("Gestures", 368, 824, w=68),
        _el("Control", 558, 824, w=62),
        _el("Centre", 558, 846, w=54),
    )

    labels = [
        (candidate.text or "").strip()
        for candidate in _icon_label_candidates(scene, viewport_size=(640, 984))
    ]

    assert "Home" in labels
    assert "Camera" in labels
    assert "Files" in labels
    assert "App Switcher" not in labels
    assert "Device" not in labels
    assert "Gestures" not in labels
    assert "Control" not in labels
    assert "Centre" not in labels


@pytest.mark.smoke
def test_ios_home_screen_rejects_system_search_surface():
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("通用", 56, 212, w=36),
        _el("最近1", 18, 410, w=46),
        _el("Q", 48, 912, w=16),
        _el("搜索", 68, 910, w=42),
    )

    assert not is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_home_screen_rejects_today_search_with_siri_suggestions():
    scene = _scene(
        _el("Siri建议", 42, 128, w=72),
        _el("设置", 78, 208, w=42),
        _el("App Store", 180, 208, w=82),
        _el("新建手记", 282, 208, w=78),
        _el("早上好", 42, 300, w=54),
        _el("北京市天气", 78, 350, w=88),
        _el("北京市，CN．大部多云", 78, 374, w=170),
        _el("Q 搜索", 82, 917, w=68),
    )

    assert not is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_home_screen_rejects_settings_detail_when_back_ocr_is_missing():
    scene = _scene(
        _el("Game Center", 190, 78, w=100),
        _el("邀请朋友", 54, 152, w=72),
        _el("共享朋友列表", 54, 244, w=108, h=26),
        _el("允许 App访问你的Game Center朋友列表，改进游戏体验。", 52, 286, w=334),
        _el("是否对他人可见", 54, 322, w=126),
        _el("帮助朋友找到你", 54, 368, w=124),
        _el("使用 Apple账户关联的电子邮件地址和电话号码，让Game", 52, 412, w=336),
        _el("交友邀请", 54, 468, w=72),
    )

    assert not is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_home_screen_rejects_scrolled_app_settings_detail_without_nav_ocr():
    scene = _scene(
        _el("通讯录", 40, 230, w=66, h=24),
        _el("添加或移除账户、管理“Siri与搜索”", 38, 256, w=277, h=31),
        _el("联系人的显示方式。进一步了解⋯", 40, 284, w=262, h=24),
        _el("通讯录账户", 38, 336, w=86),
        _el("允许“通讯录”访问", 40, 402, w=144),
        _el("Siri", 80, 448, w=26),
        _el("搜索", 80, 502, w=36),
        _el("共享姓名和照片", 40, 590, w=120),
        _el("关闭＞", 352, 590, w=56),
        _el("选择姓名和照片以及谁可以看到你共享的内容，来个性化信息。", 38, 634, w=366),
        _el("提供商", 38, 692, w=56),
        _el("显示联系人照片", 40, 784, w=120),
        _el("排列顺序", 38, 838, w=72),
        _el("显示顺序", 38, 891, w=72),
        _el("短名称", 38, 946, w=54),
    )

    assert not is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_home_screen_accepts_app_library_even_with_app_names():
    scene = _scene(
        _el("Q App资源库", 88, 112, w=140),
        _el("AI办公", 92, 198, w=60),
        _el("App Store", 94, 272, w=82),
        _el("GlassboxHelper", 94, 790, w=78),
        _el("取消", 370, 112, w=42),
    )

    assert is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_home_screen_accepts_app_library_category_grid_without_title():
    scene = _scene(
        _el("pp资", 196, 86, w=54),
        _el("社交", 72, 168, w=46),
        _el("其他", 292, 168, w=46),
        _el("效率与財务", 92, 486, w=104),
        _el("TestFlight", 112, 548, w=92),
        _el("创意", 292, 486, w=46),
    )

    assert is_ios_home_screen(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_find_springboard_icon_taps_icon_not_label():
    scene = _scene(
        _el("文件", 42, 176),
        _el("设置", 154, 176),
        _el("DemoApp", 252, 176, w=82),
        _el("搜索", 196, 892, w=48),
    )

    icon = find_springboard_icon(scene, ("设置", "Settings"), viewport_size=(440, 956))

    assert icon is not None
    assert icon.element.text == "设置"
    assert icon.tap_point[0] == icon.element.box.center[0]
    assert icon.tap_point[1] < icon.element.box.y


@pytest.mark.smoke
def test_open_app_from_springboard_scans_horizontal_pages(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    pages = [
        _scene(_el("文件", 42, 176), _el("预览", 154, 176), _el("DemoApp", 252, 176), _el("搜索", 196, 892)),
        _scene(_el("邮件", 42, 176), _el("日历", 154, 176), _el("地图", 252, 176), _el("搜索", 196, 892)),
        _scene(_el("照片", 42, 176), _el("设置", 154, 176), _el("健康", 252, 176), _el("搜索", 196, 892)),
    ]

    class FakePhone:
        def __init__(self, index: int = 0):
            self.index = index
            self.opened = False
            self.actions: list[tuple[str, tuple[int, int] | None]] = []

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            if self.opened:
                return _scene(
                    _el("设置", 196, 72, w=48),
                    _el("无线局域网", 54, 218, w=88),
                    _el("蓝牙", 54, 272, w=42),
                )
            return pages[self.index]

        def invalidate_perceive_cache(self):
            pass

        def swipe_right(self):
            self.actions.append(("swipe_right", None))
            self.index = max(0, self.index - 1)

        def swipe_left(self):
            self.actions.append(("swipe_left", None))
            self.index = min(len(pages) - 1, self.index + 1)

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))
            self.opened = True

    phone = FakePhone()

    assert open_app_from_springboard(phone, ("设置", "Settings"), settle_s=0.0)
    assert [op for op, _ in phone.actions] == ["swipe_right", "swipe_left", "swipe_left", "tap"]

    middle_phone = FakePhone(index=1)

    assert open_app_from_springboard(middle_phone, ("设置", "Settings"), settle_s=0.0)
    assert [op for op, _ in middle_phone.actions] == [
        "swipe_right", "swipe_right", "swipe_left", "swipe_left", "tap",
    ]


@pytest.mark.smoke
def test_open_app_from_springboard_opens_target_inside_home_folder(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("文件", 42, 176, w=42),
        _el("其他", 92, 890, w=42),
        _el("DemoApp", 252, 176, w=82),
        _el("搜索", 196, 892, w=48),
    )
    folder_page = _scene(
        _el("其他", 196, 78, w=42),
        _el("设置", 62, 176, w=42),
        _el("快捷指令", 154, 176, w=82),
    )
    settings_page = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple[int, int] | None]] = []
            self.folder_open = False
            self.settings_open = False

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))
            self.folder_open = False

        def perceive(self):
            if self.settings_open:
                return settings_page
            if self.folder_open:
                return folder_page
            return home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))
            if self.folder_open:
                self.settings_open = True
            else:
                self.folder_open = True

    phone = FakePhone()

    assert open_app_from_springboard(phone, ("设置", "Settings"), settle_s=0.0)
    assert [op for op, _ in phone.actions] == ["tap", "invalidate", "tap", "invalidate"]


@pytest.mark.smoke
def test_open_app_from_springboard_tries_same_folder_page_once(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("文件", 42, 176, w=42),
        _el("其他", 92, 890, w=42),
        _el("DemoApp", 252, 176, w=82),
    )
    settings_page = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []
            self.opened = False

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return settings_page if self.opened else home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))

        def swipe_right(self):
            self.actions.append(("swipe_right", None))

        def swipe_left(self):
            self.actions.append(("swipe_left", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))
            if (modifier, keycode) == (0, 0x28):
                self.opened = True

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert open_app_from_springboard(phone, ("设置", "Settings"), max_pages=0, settle_s=0.0)
    folder_taps = [
        action for action in phone.actions
        if action[0] == "tap" and action[1] != (0, 0)
    ]
    assert len(folder_taps) == 1


@pytest.mark.smoke
def test_open_app_from_springboard_does_not_treat_app_library_category_as_home_folder(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    app_library = _scene(
        _el("App Library", 100, 86, w=96),
        _el("Suggestions", 92, 260, w=98),
        _el("Recently Added", 300, 260, w=130),
        _el("Utilities", 92, 560, w=80),
        _el("Creativity", 300, 560, w=84),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []

        def _viewport_size(self):
            return 640, 980

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return app_library

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))

        def swipe_right(self):
            self.actions.append(("swipe_right", None))

        def swipe_left(self):
            self.actions.append(("swipe_left", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert not open_app_from_springboard(phone, ("Settings",), max_pages=0, settle_s=0.0)
    assert not any(action[0] == "tap" for action in phone.actions)


@pytest.mark.smoke
def test_open_app_from_springboard_verifies_folder_overlay_before_inner_tap(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("文件", 42, 176, w=42),
        _el("其他", 92, 890, w=42),
        _el("DemoApp", 252, 176, w=82),
    )
    wrong_app = _scene(
        _el("Settings", 220, 320, w=72),
        _el("Continue", 220, 520, w=80),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []
            self.mode = "home"

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))
            self.mode = "home"

        def perceive(self):
            return wrong_app if self.mode == "wrong_app" else home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))
            if self.mode == "home":
                self.mode = "wrong_app"

        def swipe_right(self):
            self.actions.append(("swipe_right", None))

        def swipe_left(self):
            self.actions.append(("swipe_left", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert not open_app_from_springboard(phone, ("Settings",), max_pages=0, settle_s=0.0)
    taps = [action for action in phone.actions if action[0] == "tap"]
    assert len(taps) == 1


@pytest.mark.smoke
def test_open_app_from_springboard_falls_back_when_icon_tap_does_not_leave_home(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("文件", 42, 176),
        _el("设置", 154, 176),
        _el("DemoApp", 252, 176, w=82),
        _el("搜索", 196, 892, w=48),
    )
    settings_page = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []
            self.opened = False
            self.returned_after_spotlight = False

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return settings_page if self.opened else home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def swipe_right(self):
            self.actions.append(("swipe_right", None))

        def swipe_left(self):
            self.actions.append(("swipe_left", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))
            if (modifier, keycode) == (0, 0x28):
                self.opened = True

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert open_app_from_springboard(phone, ("设置", "Settings"), max_pages=0, settle_s=0.0)
    assert [op for op, _ in phone.actions] == [
        "tap",
        "invalidate",
        "swipe_left",
        "invalidate",
        "tap",
        "invalidate",
        "tap",
        "invalidate",
        "key",
        "key",
        "invalidate",
        "type",
        "invalidate",
        "key",
        "invalidate",
    ]


@pytest.mark.smoke
def test_open_app_from_springboard_falls_back_to_spotlight_when_home_ocr_fails(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)
    monkeypatch.setattr("glassbox.ios.springboard.wait_for_ios_home_screen", lambda phone, timeout=5.0: None)

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return _scene(
                _el("设置", 196, 72, w=48),
                _el("无线局域网", 54, 218, w=88),
                _el("蓝牙", 54, 272, w=42),
            )

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert open_app_from_springboard(phone, ("设置", "Settings"), settle_s=0.0)
    # Cold-start scan retries home() while it makes progress (up to 3) before the
    # Spotlight fallback; perceive never reports Home here, so it presses twice
    # (2nd shows no progress -> stop), then Spotlight does its own home() press.
    assert phone.actions == [
        ("home", None),
        ("invalidate", None),
        ("home", None),
        ("invalidate", None),
        ("home", None),
        ("invalidate", None),
        ("key", (0x08, 0x2C)),
        ("invalidate", None),
        ("key", (0x08, 0x04)),
        ("key", (0, 0x2A)),
        ("invalidate", None),
        ("type", ("settings",)),
        ("invalidate", None),
        ("key", (0, 0x28)),
        ("invalidate", None),
    ]


@pytest.mark.smoke
def test_open_app_via_spotlight_uses_keyboard_search(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []

        def home(self):
            self.actions.append(("home", None))

        def _viewport_size(self):
            return 440, 956

        def perceive(self):
            return _scene(
                _el("设置", 196, 72, w=48),
                _el("无线局域网", 54, 218, w=88),
                _el("蓝牙", 54, 272, w=42),
            )

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert open_app_via_spotlight(phone, ("设置", "Settings"), settle_s=0.0)
    assert phone.actions == [
        ("home", None),
        ("invalidate", None),
        ("key", (0x08, 0x2C)),
        ("invalidate", None),
        ("key", (0x08, 0x04)),
        ("key", (0, 0x2A)),
        ("invalidate", None),
        ("type", ("settings",)),
        ("invalidate", None),
        ("key", (0, 0x28)),
        ("invalidate", None),
    ]


@pytest.mark.smoke
def test_open_app_via_spotlight_prefers_home_search_pill(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("文件", 42, 176),
        _el("设置", 154, 176),
        _el("DemoApp", 252, 176, w=82),
        _el("搜索", 196, 892, w=48),
    )
    settings_page = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []
            self.opened = False

        def home(self):
            self.actions.append(("home", None))

        def _viewport_size(self):
            return 440, 956

        def perceive(self):
            return settings_page if self.opened else home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))
            if (modifier, keycode) == (0, 0x28):
                self.opened = True

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    phone = FakePhone()

    assert open_app_via_spotlight(phone, ("设置", "Settings"), settle_s=0.0)
    assert phone.actions == [
        ("tap", (220, 902)),
        ("invalidate", None),
        ("key", (0x08, 0x04)),
        ("key", (0, 0x2A)),
        ("invalidate", None),
        ("type", ("settings",)),
        ("invalidate", None),
        ("key", (0, 0x28)),
        ("invalidate", None),
    ]


@pytest.mark.smoke
def test_open_app_via_spotlight_taps_visible_best_result(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("文件", 42, 176),
        _el("DemoApp", 252, 176, w=82),
        _el("搜索", 196, 892, w=48),
    )
    spotlight_results = _scene(
        _el("最佳搜索结果", 18, 76, w=94),
        _el("设置", 62, 194, w=28),
        _el("DemoApp", 142, 196, w=64),
        _el("Q settings", 48, 901, w=94),
    )
    settings_page = _scene(
        _el("设置", 196, 72, w=48),
        _el("无线局域网", 54, 218, w=88),
        _el("蓝牙", 54, 272, w=42),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []
            self.typed = False
            self.opened = False

        def home(self):
            self.actions.append(("home", None))

        def _viewport_size(self):
            return 440, 956

        def perceive(self):
            if self.opened:
                return settings_page
            if self.typed:
                return spotlight_results
            return home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def tap_xy(self, x: int, y: int):
            self.actions.append(("tap", (x, y)))
            if self.typed and y < 260:
                self.opened = True

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))
            self.typed = True

    phone = FakePhone()

    assert open_app_via_spotlight(phone, ("设置", "Settings"), settle_s=0.0)
    assert ("tap", (38, 204)) in phone.actions
    assert ("key", (0, 0x28)) in phone.actions


@pytest.mark.smoke
def test_open_app_via_spotlight_reports_failure_when_still_on_home(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []

        def _viewport_size(self):
            return 440, 956

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return _scene(
                _el("文件", 42, 176),
                _el("设置", 154, 176),
                _el("DemoApp", 252, 176, w=82),
                _el("搜索", 196, 892, w=48),
            )

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    assert not open_app_via_spotlight(FakePhone(), ("设置", "Settings"), settle_s=0.0)


@pytest.mark.smoke
def test_open_app_via_spotlight_reports_failure_when_still_in_known_other_app(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []

        def _viewport_size(self):
            return 448, 973

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return _scene(
                _el("服务有问题", 170, 290, w=110, h=26),
                _el("Mac 大脑", 68, 577, w=74),
                _el("最近活动", 14, 715, w=62),
            )

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    assert not open_app_via_spotlight(FakePhone(), ("设置", "Settings"), settle_s=0.0)


@pytest.mark.smoke
def test_open_app_via_spotlight_requires_target_label_after_return(monkeypatch):
    monkeypatch.setattr("glassbox.ios.springboard.time.sleep", lambda _: None)

    home_page = _scene(
        _el("Q App资源库", 88, 112, w=140),
        _el("最近添加", 290, 360, w=72),
        _el("TestFlight", 290, 805, w=82),
    )
    game_center_settings_page = _scene(
        _el("Game Center", 190, 78, w=100),
        _el("邀请朋友", 54, 152, w=72),
        _el("允许 App访问你的Game Center朋友列表，改进游戏体验。", 52, 286, w=334),
        _el("使用 Apple账户关联的电子邮件地址和电话号码，让Game", 52, 412, w=336),
    )

    class FakePhone:
        def __init__(self):
            self.actions: list[tuple[str, tuple | None]] = []
            self.opened_previous_app = False

        def _viewport_size(self):
            return 448, 973

        def home(self):
            self.actions.append(("home", None))

        def perceive(self):
            return game_center_settings_page if self.opened_previous_app else home_page

        def invalidate_perceive_cache(self):
            self.actions.append(("invalidate", None))

        def key(self, modifier: int, keycode: int):
            self.actions.append(("key", (modifier, keycode)))
            if (modifier, keycode) == (0, 0x28):
                self.opened_previous_app = True

        def type(self, text: str):
            self.actions.append(("type", (text,)))

    assert not open_app_via_spotlight(FakePhone(), ("设置", "Settings"), settle_s=0.0)


@pytest.mark.smoke
def test_opened_settings_climbs_out_of_unknown_subpage_instead_of_recovering_home():
    """Settings reopened onto the Action-Button carousel classifies as unknown.
    Recovering Home would not clear Settings' nav stack, so the next reopen would
    loop here forever; instead back_gesture climbs out and the Settings root is
    accepted as the opened target."""
    carousel = _scene(
        UIElement(type="button", box=Box(x=166, y=606, w=112, h=24), text="静音模式", confidence=0.9),
        _el("为通话和提醒切换静音和响铃。", 120, 646, 210, 22),
    )
    root = _scene(
        _el("设置", 198, 72, 48),
        _el("无线局域网", 80, 370, 86),
        _el("蓝牙", 80, 424, 40),
        _el("蜂窝网络", 80, 478, 68),
        _el("通用", 80, 725, 40),
    )

    class FakePhone:
        def __init__(self):
            self.scene = carousel
            self.home_calls = 0
            self.back_calls = 0

        def perceive(self):
            return self.scene

        def back_gesture(self):
            self.back_calls += 1
            self.scene = root  # blind chevron tap pops the carousel → Settings root
            return SimpleNamespace(ok=True)

        def home(self):
            self.home_calls += 1

        def invalidate_perceive_cache(self):
            pass

        def _viewport_size(self):
            return 448, 990

    phone = FakePhone()
    assert _opened_expected_app_or_recover(phone, carousel, ("设置", "Settings"), settle_s=0) is True
    assert phone.back_calls == 1
    assert phone.home_calls == 0


@pytest.mark.smoke
def test_opened_wrong_app_recovers_home_when_climb_does_not_surface_target():
    """A genuinely wrong-app launch whose pages never resolve to the target:
    climbing Back a bounded number of times surfaces neither the target nor
    Home, so the open is rejected and Home is recovered (no infinite loop)."""
    other = _scene(_el("某第三方页面", 120, 300, 160, 24))

    class FakePhone:
        def __init__(self):
            self.home_calls = 0
            self.back_calls = 0

        def perceive(self):
            return other  # never resolves to Settings

        def back_gesture(self):
            self.back_calls += 1
            return SimpleNamespace(ok=True)

        def home(self):
            self.home_calls += 1

        def invalidate_perceive_cache(self):
            pass

        def _viewport_size(self):
            return 448, 990

    phone = FakePhone()
    assert _opened_expected_app_or_recover(phone, other, ("设置", "Settings"), settle_s=0) is False
    assert phone.home_calls == 1
    assert phone.back_calls == 4  # bounded by max_steps
