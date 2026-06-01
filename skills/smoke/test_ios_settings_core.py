# ruff: noqa: F403,F405,I001

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from skills.smoke.ios_settings_walkthrough_support import *

@pytest.mark.smoke
def test_settings_root_requires_top_title_and_no_back_button():
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    child = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 72, w=48),
        _el("管理iPhone的整体设置和偏好设置，例如软件", 32, 138, w=360),
        _el("无线局域网", 240, 210, w=86),
    )

    assert _is_settings_root(_Phone(root))
    assert not _is_settings_root(_Phone(child))

@pytest.mark.smoke
def test_settings_root_accepts_scrolled_root_viewport():
    root = _scene(
        _el("设置", 198, 72, w=48),
        _el("通知", 80, 210, w=40),
        _el("专注模式", 80, 318, w=72),
        _el("屏幕时间", 80, 372, w=72),
        _el("面容ID与密码", 80, 480, w=110),
        _el("隐私与安全性", 80, 588, w=110),
        _el("钱包与 Apple Pay", 80, 642, w=138),
        _el("Game Center", 80, 696, w=104),
        _el("Q 搜索", 198, 900, w=54),
    )

    assert _is_settings_root(_Phone(root))

@pytest.mark.smoke
def test_settings_root_rejects_text_back_affordance_even_without_nav_back_type():
    child = _scene(
        _el("<", 18, 72, w=14, ty="text"),
        _el("辅助功能", 172, 78, w=76),
        _el("通用", 80, 340, w=40),
        _el("辅助功能", 80, 400, w=72),
        _el("无线局域网", 80, 460, w=86),
    )

    assert not _is_settings_root(_Phone(child))

@pytest.mark.smoke
def test_settings_detail_recognizer_handles_game_center_without_back_ocr():
    scene = _scene(
        _el("Game Center", 178, 78, w=110),
        _el("邀请朋友", 80, 160, w=72),
        _el("共享朋友列表", 80, 250, w=110, ty="button"),
        _el("允许 App访问你的Game Center朋友列表，改进游戏体验。", 32, 292, w=360),
        _el("是否对他人可见", 80, 328, w=126),
        _el("帮助朋友找到你", 80, 376, w=124, ty="button"),
        _el("使用 Apple账户关联的电子邮件地址和电话号码，让Game", 32, 420, w=360),
    )

    assert _scene_looks_like_settings_detail(scene)

@pytest.mark.smoke
def test_expected_root_labels_are_unique_safe_and_counted_by_coverage():
    assert len(EXPECTED_ROOT_NAV_TEXT) == len(set(EXPECTED_ROOT_NAV_TEXT))
    assert len(EXPECTED_ROOT_NAV_TEXT_ZH) == len(set(EXPECTED_ROOT_NAV_TEXT_ZH))
    assert len(SAFE_NAV_TEXT) == len(set(SAFE_NAV_TEXT))
    assert set(EXPECTED_ROOT_NAV_TEXT_ZH) <= set(EXPECTED_ROOT_NAV_TEXT)
    assert set(EXPECTED_ROOT_NAV_TEXT_ZH) <= set(SAFE_NAV_TEXT)

    visits = [
        PageVisit(path=("Settings",), title="设置", texts=("设置",)),
        *[
            PageVisit(path=("Settings", label), title=label, texts=(label,))
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
        ],
    ]
    coverage = _root_coverage(visits)

    assert coverage["visited"] == list(EXPECTED_ROOT_NAV_TEXT_ZH)
    assert coverage["missing"] == []

@pytest.mark.smoke
def test_root_label_aliases_map_to_expected_root_coverage_labels():
    for alias, canonical in ROOT_LABEL_ALIASES.items():
        assert canonical in EXPECTED_ROOT_NAV_TEXT_ZH
        assert _canonical_expected_root_label(alias) == canonical
    for label in EXPECTED_ROOT_NAV_TEXT_ZH:
        assert _canonical_expected_root_label(label) == label

    visits = [
        PageVisit(path=("Settings", alias), title=alias, texts=(alias,))
        for alias in ROOT_LABEL_ALIASES
    ]
    coverage = _root_coverage(visits)

    assert set(coverage["visited"]) == set(ROOT_LABEL_ALIASES.values())

@pytest.mark.smoke
def test_root_label_matching_handles_single_glyph_ocr_prefix_without_alias():
    assert "必通用" not in ROOT_LABEL_ALIASES
    assert _canonical_expected_root_label("必通用") == "通用"
    assert _canonical_expected_root_label("多多通用") is None

@pytest.mark.smoke
def test_root_label_matching_handles_zero_letter_sos_ocr_without_alias():
    assert "S0S" not in ROOT_LABEL_ALIASES
    assert _canonical_expected_root_label("S0S") == "紧急 SOS"

@pytest.mark.smoke
def test_expected_root_labels_have_search_queries():
    assert set(ROOT_SEARCH_QUERIES) == set(EXPECTED_ROOT_NAV_TEXT_ZH)
    assert all(query.strip() for query in ROOT_SEARCH_QUERIES.values())

@pytest.mark.smoke
def test_wait_screen_settled_waits_until_frames_stabilize():
    """滑入动画期间帧在动 → 等到连续两帧稳定才返回(防错位几何选候选)。"""
    import numpy as np

    from glassbox.perception.source import Frame

    moving1 = Frame(img=np.zeros((80, 80, 3), dtype=np.uint8), ts=0.0)
    moving2 = Frame(img=np.full((80, 80, 3), 110, dtype=np.uint8), ts=0.0)
    settled = Frame(img=np.full((80, 80, 3), 200, dtype=np.uint8), ts=0.0)
    frames = [moving1, moving2, settled, settled, settled]

    class _Phone:
        def __init__(self) -> None:
            self.i = 0

        def snapshot(self):
            f = frames[min(self.i, len(frames) - 1)]
            self.i += 1
            return f

    p = _Phone()
    _wait_screen_settled(p, settle_s=0.0)
    assert p.i >= 4   # 读过两帧运动帧,到连续稳定帧才停

@pytest.mark.smoke
def test_wait_screen_settled_noop_without_snapshot():
    class _NoSnapshot:
        pass

    _wait_screen_settled(_NoSnapshot())   # 不抛异常即可

@pytest.mark.smoke
def test_scroll_to_vertical_boundary_uses_wheel_until_stable(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    phone = _ScrollingPhone([
        _scene(_el("设置", 196, 72), _el("无线局域网", 54, 218)),
        _scene(_el("设置", 196, 72), _el("通知", 54, 218)),
        _scene(_el("设置", 196, 72), _el("通用", 54, 218)),
    ])
    phone.index = 2

    _scroll_to_vertical_boundary(phone, direction="up", max_steps=5)

    assert phone.index == 0

@pytest.mark.smoke
def test_settings_wheel_scroll_uses_conservative_default_ticks(monkeypatch):
    monkeypatch.delenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", raising=False)
    monkeypatch.delenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", raising=False)
    phone = _ScrollingPhone([
        _scene(_el("设置", 196, 72), _el("无线局域网", 54, 218)),
        _scene(_el("设置", 196, 72), _el("通知", 54, 218)),
    ])

    _wheel_scroll_down(phone)

    assert phone.down_ticks == [12]   # Static mid-batch after adaptive-8 regressed on-device.
    assert _settings_wheel_ticks_per_swipe() == 12


@pytest.mark.smoke
def test_scroll_down_confirmed_keeps_static_wheel_ticks_after_overshoot(monkeypatch):
    monkeypatch.delenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", raising=False)
    monkeypatch.delenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", raising=False)
    monkeypatch.setattr(settings_scrolling.time, "sleep", lambda _seconds: None)
    scenes = [
        _scene_from_texts(["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"]),
        _scene_from_texts(["Wallet", "Game Center", "Apps", "Passwords", "Privacy"]),
        _scene_from_texts(["Apps", "Passwords", "Privacy", "Safari", "Battery"]),
    ]
    phone = _ScrollingPhone(scenes)

    outcome, _after = settings_scrolling.scroll_down_confirmed(
        phone,
        ["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"],
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        texts=lambda observed: [element.text for element in observed.elements if element.text],
        depth=0,
        idx=0,
    )
    outcome2, _after2 = settings_scrolling.scroll_down_confirmed(
        phone,
        ["Wallet", "Game Center", "Apps", "Passwords", "Privacy"],
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        texts=lambda observed: [element.text for element in observed.elements if element.text],
        depth=0,
        idx=1,
    )

    assert outcome == "overshoot"
    assert outcome2 == "progress"
    assert phone.down_ticks == [12, 12]


@pytest.mark.smoke
def test_scroll_down_confirmed_treats_two_static_stucks_as_boundary(monkeypatch):
    monkeypatch.delenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", raising=False)
    monkeypatch.delenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", raising=False)
    monkeypatch.setattr(settings_scrolling.time, "sleep", lambda _seconds: None)
    scenes = [
        _scene_from_texts(["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"]),
        _scene_from_texts(["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"]),
        _scene_from_texts(["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"]),
    ]
    phone = _ScrollingPhone(scenes)

    outcome, _after = settings_scrolling.scroll_down_confirmed(
        phone,
        ["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"],
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        texts=lambda observed: [element.text for element in observed.elements if element.text],
        depth=0,
        idx=0,
    )

    assert outcome == "stuck"
    assert phone.down_ticks == [12, 12]


@pytest.mark.smoke
def test_scroll_down_confirmed_marks_top_status_bar_boundary_overshoot(monkeypatch):
    monkeypatch.setattr(settings_scrolling.time, "sleep", lambda _seconds: None)
    before = ["Settings", "Wi-Fi", "Bluetooth", "Cellular", "Notifications"]
    after = _scene(
        _el("13:04", 24, 40, w=48),
        _el("Wallet & Apple Pay", 70, 260, w=160),
        _el("Game Center", 70, 300, w=120),
        _el("Apps", 70, 340, w=80),
        _el("Safari", 70, 380, w=80),
    )
    phone = _ScrollingPhone([_scene_from_texts(before), after])

    outcome, _after = settings_scrolling.scroll_down_confirmed(
        phone,
        before,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        texts=lambda observed: [element.text for element in observed.elements if element.text],
        depth=0,
        idx=0,
    )

    assert outcome == "top-overshoot"

@pytest.mark.smoke
def test_ipad_settings_scroll_drags_sidebar_instead_of_hover_wheel():
    class IPadWheelPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.calls: list[tuple[int, dict]] = []
            self.drags: list[tuple[int, int, int, int, dict]] = []

        def supports(self, action: str) -> bool:
            return action == "scroll_wheel"

        def wheel_scroll_down(self, *, ticks: int | None = None) -> None:
            raise AssertionError("iPad Settings should use focused scroll_wheel directly")

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self) -> tuple[int, int]:
            return 640, 980

        def scroll_wheel(self, ticks: int, **kwargs) -> None:
            self.calls.append((ticks, kwargs))

        def _page_drag_xy(self, x1, y1, x2, y2, **kwargs) -> None:
            self.drags.append((x1, y1, x2, y2, kwargs))

    phone = IPadWheelPhone()

    _wheel_scroll_down(phone, ticks=6)

    assert phone.calls == []
    assert phone.drags == [
        (147, 842, 147, 313, {"via": "settings_sidebar_drag"}),
    ]


@pytest.mark.smoke
def test_ipad_root_scroll_down_confirmed_uses_row_tracked_ticks_for_missing_root(monkeypatch):
    monkeypatch.setattr(settings_scrolling.time, "sleep", lambda _seconds: None)
    monkeypatch.delenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", raising=False)
    monkeypatch.delenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", raising=False)
    monkeypatch.setenv("IOS_SETTINGS_IPAD_WHEEL_PIXELS_PER_TICK", "16")
    scene = _scene(
        _el("Settings", 48, 72, w=70),
        _el("Wi-Fi", 72, 280, w=70),
        _el("Bluetooth", 72, 344, w=120),
        _el("General", 72, 408, w=90),
    )

    class IPadWheelPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.calls: list[tuple[int, dict]] = []
            self.drags: list[tuple[int, int, int, int, dict]] = []

        def supports(self, action: str) -> bool:
            return action == "scroll_wheel"

        def wheel_scroll_down(self, *, ticks: int | None = None) -> None:
            raise AssertionError("iPad Settings should use focused scroll_wheel directly")

        def viewport_size(self) -> tuple[int, int]:
            return 640, 980

        def scroll_wheel(self, ticks: int, **kwargs) -> None:
            self.calls.append((ticks, kwargs))

        def _page_drag_xy(self, x1, y1, x2, y2, **kwargs) -> None:
            self.drags.append((x1, y1, x2, y2, kwargs))

        def invalidate_perceive_cache(self) -> None:
            pass

        def perceive(self):
            return scene

    phone = IPadWheelPhone()

    outcome, _after = settings_scrolling.scroll_down_confirmed(
        phone,
        ["Settings", "Wi-Fi", "Bluetooth", "General"],
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        texts=lambda observed: [element.text for element in observed.elements if element.text],
        depth=0,
        idx=0,
        scene=scene,
        target_labels=["电池"],
        canonical_expected_root_label=lambda text: {"Wi-Fi": "无线局域网", "Bluetooth": "蓝牙"}.get(text),
    )

    assert outcome == "stuck"
    assert phone.calls == []
    assert phone.drags == [
        (147, 842, 147, 313, {"via": "settings_sidebar_drag"}),
    ]


@pytest.mark.smoke
def test_ipad_settings_without_wheel_does_not_fallback_to_swipe():
    class IPadNoWheelPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.swipes: list[str] = []

        def supports(self, action: str) -> bool:
            return False

        def swipe_up(self) -> None:
            self.swipes.append("up")

        def swipe_down(self) -> None:
            self.swipes.append("down")

    phone = IPadNoWheelPhone()
    intents: list[str] = []

    def record_intent(_phone, label: str):
        intents.append(label)
        return nullcontext()

    settings_scrolling.wheel_scroll_down(phone, action_intent=record_intent)
    settings_scrolling.wheel_scroll_up(phone, action_intent=record_intent)

    assert phone.swipes == []
    assert intents == ["scroll.down.ipad_unavailable", "scroll.up.ipad_unavailable"]


@pytest.mark.smoke
def test_ipad_scroll_down_confirmed_does_not_retry_stuck_wheel(monkeypatch):
    monkeypatch.setattr(settings_scrolling.time, "sleep", lambda _seconds: None)
    scene = _scene(
        _el("Settings", 48, 70, w=70),
        _el("General", 72, 360, w=70),
        _el("Accessibility", 72, 420, w=120),
    )

    class IPadWheelPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.calls: list[tuple[int, dict]] = []

        def supports(self, action: str) -> bool:
            return action == "scroll_wheel"

        def wheel_scroll_down(self, *, ticks: int | None = None) -> None:
            raise AssertionError("iPad Settings should use focused scroll_wheel directly")

        def viewport_size(self):

            return self._viewport_size()

        def _viewport_size(self) -> tuple[int, int]:
            return 640, 980

        def scroll_wheel(self, ticks: int, **kwargs) -> None:
            self.calls.append((ticks, kwargs))

        def invalidate_perceive_cache(self) -> None:
            pass

        def perceive(self):
            return scene

    phone = IPadWheelPhone()

    outcome, after = settings_scrolling.scroll_down_confirmed(
        phone,
        ["Settings", "General", "Accessibility"],
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        texts=lambda observed: [element.text for element in observed.elements if element.text],
        depth=0,
        idx=0,
    )

    assert outcome == "stuck"
    assert after is scene
    assert len(phone.calls) == 1


@pytest.mark.smoke
def test_settings_wheel_scroll_honors_env_ticks(monkeypatch):
    monkeypatch.setenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", "7")
    monkeypatch.delenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", raising=False)
    assert _settings_wheel_ticks_per_swipe() == 7

    monkeypatch.setenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", "9")
    assert _settings_wheel_ticks_per_swipe() == 9

@pytest.mark.smoke
def test_settings_wheel_scroll_supports_legacy_no_ticks_method(monkeypatch):
    monkeypatch.delenv("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", raising=False)
    monkeypatch.delenv("GLASSBOX_WHEEL_TICKS_PER_SCROLL", raising=False)

    class LegacyWheelPhone:
        def __init__(self):
            self.calls = 0

        def wheel_scroll_down(self):
            self.calls += 1

    phone = LegacyWheelPhone()

    _wheel_scroll_down(phone)

    assert phone.calls == 1

@pytest.mark.smoke
def test_visible_page_signature_is_scoped_by_settings_path():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("同样的内容", 80, 340, w=100),
    )
    visits: list[PageVisit] = []
    seen = set()

    assert _record_visible_page(
        scene=scene,
        path=("Settings", "通用", "页面A"),
        visits=visits,
        seen_sigs=seen,
        depth=2,
    )
    assert _record_visible_page(
        scene=scene,
        path=("Settings", "通用", "页面B"),
        visits=visits,
        seen_sigs=seen,
        depth=2,
    )
    assert not _record_visible_page(
        scene=scene,
        path=("Settings", "通用", "页面B"),
        visits=visits,
        seen_sigs=seen,
        depth=2,
    )

    assert [visit.path for visit in visits] == [
        ("Settings", "通用", "页面A"),
        ("Settings", "通用", "页面B"),
    ]

@pytest.mark.smoke
def test_root_coverage_reports_expected_visited_and_missing_pages():
    visits = [
        PageVisit(path=("Settings",), title="设置", texts=()),
        PageVisit(path=("Settings", "无线局域网"), title="无线局域网", texts=()),
        PageVisit(path=("Settings", "伴机息示"), title="待机显示", texts=()),
    ]

    coverage = _root_coverage(visits)

    assert "无线局域网" in coverage["visited"]
    assert "待机显示" in coverage["visited"]
    assert "蓝牙" in coverage["missing"]


@pytest.mark.smoke
def test_drill_down_skips_root_row_prelisting(monkeypatch):
    calls = []
    monkeypatch.setattr(
        settings_page_records,
        "record_visible_root_row_visits",
        lambda **kwargs: calls.append(kwargs),
    )

    # Default (root-coverage) mode: visible root rows are recorded as visited.
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", False)
    walkthrough._record_visible_root_row_visits(scene=object(), visits=[], seen_sigs=set(), phone=None)
    assert len(calls) == 1

    # Drill-down: pre-marking is skipped so each section is actually entered.
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    walkthrough._record_visible_root_row_visits(scene=object(), visits=[], seen_sigs=set(), phone=None)
    assert len(calls) == 1
