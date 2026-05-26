# ruff: noqa: F403,F405,I001

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

from glassbox.effector import ActionResult

from skills.smoke.ios_settings_walkthrough_support import *

@pytest.mark.smoke
def test_visible_root_rows_count_as_root_coverage_evidence():
    visits = [PageVisit(path=("Settings",), title="设置", texts=("设置",))]
    seen_sigs: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("蜂窝网络", 78, 476, w=72),
        _el("无SIM卡", 316, 476, w=68),
        _el("声效与触感反馈", 78, 530, w=120),
        _el("屏幕时间", 78, 584, w=78),
        _el("SOS紧急联络", 78, 638, w=110),
        _el("面容ID与密码", 78, 690, w=110),
        _el("待机見示", 80, 883, w=70),
        _el("Q 搜索", 48, 912, w=62),
    )

    _record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen_sigs)
    coverage = _root_coverage(visits)

    assert "蜂窝网络" in coverage["visited"]
    assert "声音与触感" in coverage["visited"]
    assert "屏幕使用时间" in coverage["visited"]
    assert "紧急 SOS" in coverage["visited"]
    assert "Face ID与密码" in coverage["visited"]
    assert "待机显示" in coverage["visited"]

@pytest.mark.smoke
def test_root_coverage_mode_skips_root_row_navigation(monkeypatch):
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", True)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)

    assert not _should_traverse_candidates(0)
    assert _should_traverse_candidates(1)

@pytest.mark.smoke
def test_search_result_picker_uses_top_visible_root_result():
    scene = _scene(
        _el("08:40", 48, 26, w=72, ty="status_bar"),
        _el("通知", 76, 122, w=36, ty="button"),
        _el("显示通知", 78, 176, w=68, ty="button"),
        _el("待机显示", 76, 196, w=54),
        _el("Q通知", 46, 906, w=68),
        _el("×", 382, 910, w=24, ty="button"),
    )

    hit = _find_search_result(scene, "通知")

    assert hit is not None
    assert hit.text == "通知"
    assert hit.box.center == (94, 132)

@pytest.mark.smoke
def test_search_query_suggestion_matches_keyboard_candidate_for_pinyin_input():
    scene = _scene(
        _el("未找到“fengwowangluo”的相关结果", 60, 460, w=320),
        _el("1蜂窝网络", 142, 872, w=110),
        _el("2蜂窝", 262, 872, w=70),
        _el("Q feng wowanqluo", 46, 910, w=170),
        _el("×", 382, 910, w=24, ty="button"),
    )

    hit = _find_search_query_suggestion(scene, "蜂窝网络")

    assert hit is not None
    assert hit.text == "1蜂窝网络"


@pytest.mark.smoke
def test_open_root_label_via_search_accepts_ipad_split_view_root_detail():
    search_scene = _scene(_el("通知", 72, 160, w=40, ty="button"))
    opened_detail = _scene(
        _el("Q Search", 34, 90, w=72),
        _el("通知", 66, 494, w=40),
        _el("通知", 404, 44, w=90),
    )

    class SearchPhone:
        def __init__(self) -> None:
            self.scene = search_scene
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self) -> None:
            pass

        def type(self, _query: str):
            return ActionResult(ok=True, backend="mock", connected=True)

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = opened_detail
            return ActionResult(ok=True, backend="mock", connected=True)

    actions = SimpleNamespace(
        root_search_query=lambda label: "tongzhi" if label == "通知" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=lambda _phone: True,
        tap_search_field=lambda _phone, _scene: True,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        record_action_verdict=lambda _phone, _result: True,
        find_search_result=lambda scene, label: scene.elements[0] if label == "通知" else None,
        find_search_query_suggestion=lambda _scene, _label: None,
        is_settings_search_scene=lambda scene: scene is search_scene,
        scene_is_settings_root=lambda scene: scene is opened_detail,
        page_title=lambda scene: "通知" if scene is opened_detail else "Search",
        canonical_expected_root_label=lambda text: "通知" if text in {"通知", "Notifications"} else None,
    )

    assert settings_navigation.open_root_label_via_search(SearchPhone(), "通知", actions)


@pytest.mark.smoke
def test_open_root_label_via_search_clears_ipad_top_search_after_root_open(monkeypatch):
    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _seconds: None)
    search_scene = _scene(_el("Notifications", 72, 160, w=88, ty="button"))
    dirty_detail = _scene(
        _el("Q Notifications", 34, 90, w=124),
        _el("Notifications", 404, 44, w=90),
        _el("Apps → Notes", 72, 180, w=104),
    )
    clean_detail = _scene(
        _el("Q Search", 34, 90, w=72),
        _el("Notifications", 404, 44, w=90),
        _el("Scheduled Summary", 280, 320, w=138),
    )

    class SearchPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.scene = search_scene
            self.clear_calls = 0

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self) -> None:
            pass

        def type(self, _query: str):
            return ActionResult(ok=True, backend="mock", connected=True)

        def tap_xy(self, _x: int, _y: int):
            self.scene = dirty_detail
            return ActionResult(ok=True, backend="mock", connected=True)

    phone = SearchPhone()

    def clear_search(clear_phone):
        clear_phone.clear_calls += 1
        if clear_phone.scene is dirty_detail:
            clear_phone.scene = clean_detail
        return True

    actions = SimpleNamespace(
        root_search_query=lambda label: "Notifications" if label == "通知" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=clear_search,
        tap_search_field=lambda _phone, _scene: True,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        record_action_verdict=lambda _phone, _result: True,
        find_search_result=lambda scene, label: scene.elements[0] if scene is search_scene and label == "通知" else None,
        find_search_query_suggestion=lambda _scene, _label: None,
        is_settings_search_scene=lambda scene: scene is search_scene or scene is dirty_detail,
        scene_is_settings_root=lambda _scene: False,
        page_title=lambda scene: "Notifications" if scene is dirty_detail or scene is clean_detail else "Search",
        canonical_expected_root_label=lambda text: "通知" if text in {"通知", "Notifications"} else None,
    )

    assert settings_navigation.open_root_label_via_search(phone, "通知", actions)
    assert phone.clear_calls == 2
    assert phone.scene is clean_detail


@pytest.mark.smoke
def test_open_root_label_via_search_uses_existing_ipad_search_hit_before_typing(monkeypatch):
    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _seconds: None)
    search_scene = _scene(
        _el("Q Search", 34, 90, w=72),
        _el("Weather", 72, 142, w=58, ty="button"),
    )
    dirty_detail = _scene(
        _el("Q Weather", 34, 90, w=92),
        _el("Weather", 404, 44, w=70),
    )
    clean_detail = _scene(
        _el("Q Search", 34, 90, w=72),
        _el("Weather", 404, 44, w=70),
    )

    class SearchPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.scene = search_scene
            self.clear_calls = 0
            self.typed: list[str] = []
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self) -> None:
            pass

        def type(self, query: str):
            self.typed.append(query)
            return ActionResult(ok=True, backend="mock", connected=True)

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = dirty_detail
            return ActionResult(ok=True, backend="mock", connected=True)

    phone = SearchPhone()

    def clear_search(clear_phone):
        clear_phone.clear_calls += 1
        if clear_phone.scene is dirty_detail:
            clear_phone.scene = clean_detail
        return True

    actions = SimpleNamespace(
        root_search_query=lambda label: "Weather" if label == "Weather" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=clear_search,
        tap_search_field=lambda _phone, _scene: True,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        record_action_verdict=lambda _phone, _result: True,
        find_search_result=lambda scene, label: scene.elements[1] if scene is search_scene and label == "Weather" else None,
        find_search_query_suggestion=lambda _scene, _label: None,
        is_settings_search_scene=lambda scene: scene is search_scene or scene is dirty_detail,
        scene_is_settings_root=lambda _scene: False,
        page_title=lambda scene: "Weather" if scene is dirty_detail or scene is clean_detail else "Search",
        canonical_expected_root_label=lambda _text: None,
    )

    assert settings_navigation.open_root_label_via_search(phone, "Weather", actions)
    assert phone.typed == []
    assert phone.taps == [search_scene.elements[1].box.center]
    assert phone.clear_calls == 2
    assert phone.scene is clean_detail


@pytest.mark.smoke
def test_open_root_label_via_search_waits_for_delayed_results(monkeypatch):
    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _seconds: None)
    search_scene = _scene(_el("Q Battery", 54, 90, w=72))
    result_scene = _scene(_el("Battery", 72, 150, w=50, ty="button"))
    opened_detail = _scene(_el("Q Search", 34, 90, w=72), _el("Battery", 404, 44, w=90))

    class SearchPhone:
        def __init__(self) -> None:
            self.scene = search_scene
            self.polls_after_type = 0
            self.taps: list[tuple[int, int]] = []
            self.typed = False

        def perceive(self):
            if self.typed and self.scene is search_scene:
                self.polls_after_type += 1
                if self.polls_after_type >= 3:
                    self.scene = result_scene
            return self.scene

        def invalidate_perceive_cache(self) -> None:
            pass

        def type(self, _query: str):
            self.typed = True
            return ActionResult(ok=True, backend="mock", connected=True)

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            if self.scene is result_scene:
                self.scene = opened_detail
            return ActionResult(ok=True, backend="mock", connected=True)

    phone = SearchPhone()
    actions = SimpleNamespace(
        root_search_query=lambda label: "Battery" if label == "电池" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=lambda _phone: True,
        tap_search_field=lambda _phone, _scene: True,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        record_action_verdict=lambda _phone, _result: True,
        find_search_result=lambda scene, label: scene.elements[0] if scene is result_scene and label == "电池" else None,
        find_search_query_suggestion=lambda _scene, _label: None,
        is_settings_search_scene=lambda scene: scene is search_scene or scene is result_scene,
        scene_is_settings_root=lambda scene: scene is opened_detail,
        page_title=lambda scene: "电池" if scene is opened_detail else "Search",
        canonical_expected_root_label=lambda text: "电池" if text in {"电池", "Battery"} else None,
    )

    assert settings_navigation.open_root_label_via_search(phone, "电池", actions)
    assert phone.polls_after_type >= 3
    assert phone.taps == [(97, 160)]


@pytest.mark.smoke
def test_open_root_label_via_search_marks_ipad_search_unavailable_when_clear_fails():
    class SearchPhone:
        def __init__(self) -> None:
            self.device_geometry = SimpleNamespace(model="ipad_mini_7")

    actions = SimpleNamespace(
        root_search_query=lambda label: "battery" if label == "电池" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=lambda _phone: False,
    )
    phone = SearchPhone()

    assert not settings_navigation.open_root_label_via_search(phone, "电池", actions)
    assert phone._ios_settings_search_unavailable is True


@pytest.mark.smoke
def test_open_root_label_via_search_rejects_ipad_duplicate_query_no_results(monkeypatch):
    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _seconds: None)
    search_scene = _scene(_el("WLAN", 72, 160, w=52, ty="button"))
    no_results = _scene(
        _el("Q WLANWLAN", 34, 90, w=112),
        _el('No Results for "WLANWLAN"', 64, 176, w=220),
        _el("Sounds", 404, 44, w=70),
    )

    class SearchPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.scene = search_scene
            self.typed: list[str] = []
            self.taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self) -> None:
            pass

        def type(self, query: str):
            self.typed.append(query)
            return ActionResult(ok=True, backend="mock", connected=True)

        def tap_xy(self, x: int, y: int):
            self.taps.append((x, y))
            self.scene = no_results
            return ActionResult(ok=True, backend="mock", connected=True)

    actions = SimpleNamespace(
        root_search_query=lambda label: "WLAN" if label == "无线局域网" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=lambda _phone: True,
        tap_search_field=lambda _phone, _scene: True,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        record_action_verdict=lambda _phone, _result: True,
        find_search_result=lambda scene, label: scene.elements[0] if scene is search_scene and label == "无线局域网" else None,
        find_search_query_suggestion=lambda _scene, _label: None,
        is_settings_search_scene=lambda _scene: False,
        scene_is_settings_root=lambda _scene: False,
        page_title=lambda scene: "Q WLANWLAN" if scene is no_results else "Search",
        canonical_expected_root_label=lambda text: "无线局域网" if text in {"WLAN", "Wi-Fi"} else None,
    )
    phone = SearchPhone()

    assert not settings_navigation.open_root_label_via_search(phone, "无线局域网", actions)
    assert phone.typed == ["WLAN"]
    assert phone.taps == [(98, 170)]


@pytest.mark.smoke
def test_open_root_label_via_search_refocuses_ipad_top_search_when_results_lag(monkeypatch):
    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _seconds: None)
    pre_result_scene = _scene(_el("Q Search", 34, 90, w=72))
    result_scene = _scene(
        _el("Q WLAN", 34, 90, w=72),
        _el("WLAN", 72, 150, w=44, ty="button"),
        _el("WLAN Power", 72, 194, w=88),
    )
    opened_detail = _scene(_el("WLAN", 404, 44, w=70), _el("Choose a Network", 404, 180, w=150))

    class SearchPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def __init__(self) -> None:
            self.scene = pre_result_scene
            self.typed: list[str] = []
            self.focuses = 0
            self.result_taps: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def invalidate_perceive_cache(self) -> None:
            pass

        def type(self, query: str):
            self.typed.append(query)
            return ActionResult(ok=True, backend="mock", connected=True)

        def tap_xy(self, x: int, y: int):
            self.result_taps.append((x, y))
            self.scene = opened_detail
            return ActionResult(ok=True, backend="mock", connected=True)

    phone = SearchPhone()

    def tap_search_field(_phone, _scene):
        phone.focuses += 1
        if phone.typed:
            phone.scene = result_scene
        return True

    actions = SimpleNamespace(
        root_search_query=lambda label: "WLAN" if label == "无线局域网" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=lambda _phone: True,
        tap_search_field=tap_search_field,
        action_intent=lambda *_args, **_kwargs: nullcontext(),
        record_action_verdict=lambda _phone, _result: True,
        find_search_result=lambda scene, label: (
            scene.elements[1] if scene is result_scene and label == "无线局域网" else None
        ),
        find_search_query_suggestion=lambda _scene, _label: None,
        is_settings_search_scene=lambda scene: scene is pre_result_scene or scene is result_scene,
        scene_is_settings_root=lambda scene: scene is opened_detail,
        page_title=lambda scene: "WLAN" if scene is opened_detail else "Search",
        canonical_expected_root_label=lambda text: "无线局域网" if text in {"WLAN", "Wi-Fi"} else None,
    )

    assert settings_navigation.open_root_label_via_search(phone, "无线局域网", actions)
    assert phone.typed == ["WLAN"]
    assert phone.focuses == 2
    assert phone.result_taps == [(94, 160)]


@pytest.mark.smoke
def test_open_root_label_via_search_does_not_globally_disable_iphone_search_on_clear_miss():
    class SearchPhone:
        def __init__(self) -> None:
            self.device_geometry = SimpleNamespace(model="iphone_17_pro_max")

    actions = SimpleNamespace(
        root_search_query=lambda label: "battery" if label == "电池" else None,
        enter_settings_search=lambda _phone: True,
        clear_settings_search=lambda _phone: False,
    )
    phone = SearchPhone()

    assert not settings_navigation.open_root_label_via_search(phone, "电池", actions)
    assert not hasattr(phone, "_ios_settings_search_unavailable")


@pytest.mark.smoke
def test_search_query_suggestion_handles_ocr_joined_candidates():
    scene = _scene(
        _el("未找到“daijixianshi”的相关结果", 60, 460, w=320),
        _el("1待机显示2待机现实", 96, 872, w=230),
        _el("Q daiixian shi", 46, 908, w=124),
        _el("×", 382, 908, w=26, ty="button"),
    )

    hit = _find_search_query_suggestion(scene, "待机显示")

    assert hit is not None
    assert hit.text == "1待机显示2待机现实"

@pytest.mark.smoke
def test_wifi_network_list_is_not_crawled_as_navigation_rows():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("无线局域网", 170, 78, w=96),
        _el("编辑", 355, 78, w=38),
        _el("无线局域网", 70, 270, w=96),
        _el("我的网络", 70, 420, w=72),
        _el("kacier", 80, 480, w=52),
        _el("其他网络", 70, 560, w=72),
        _el("kacier_aiot", 80, 620, w=92),
    )

    assert _safe_navigation_candidates(scene) == []

@pytest.mark.smoke
def test_wifi_network_list_from_real_ocr_report_is_not_crawled():
    scene = _scene_from_texts([
        "编辑",
        "无线局域网",
        "接入无线局域网、查看可用网络，并管理加入网",
        "络及附近热点设置。进一步了解…",
        "无线局域网",
        "Kacler_Iptv",
        "我的网络",
        "kacier",
        "其他网络",
        "kacier_aiot",
        "minij_washer_r_91f0",
        "其他⋯",
        "使用无线局域网与蜂窝网络的App",
        "启用WAPI",
    ])

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "dynamic Wi-Fi rows"

@pytest.mark.smoke
def test_wifi_network_list_without_section_headers_is_not_crawled():
    scene = _scene_from_texts([
        "编辑",
        "无线局域网",
        "接入无线局域网、查看可用网络，并管理加入网",
        "络及附近热点设置。进一步了解…",
        "无线局域网",
        "V kacier_iptv",
        "网络",
        "ChinaNet-xbPV",
        "kacier_aiot",
        "minii_washer_r_91f0",
        "小猫",
        "其他⋯.",
        "使用无线局域网与蜂窝网络的App",
        "启用 WAPI",
    ])

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "dynamic Wi-Fi rows"

@pytest.mark.smoke
def test_wifi_detail_page_from_real_ocr_report_is_not_crawled():
    scene = _scene_from_texts([
        "kacier_iptv",
        "忽略此网络",
        "自动加入",
        "密码",
        "低数据模式",
        "私有无线局域网地址",
        "固定",
        "无线局域网地址",
        "配置IP",
        "IP地址",
        "自动＞",
        "203.0.113.10",
    ])

    assert _safe_navigation_candidates(scene) == []

@pytest.mark.smoke
def test_settings_root_only_uses_known_safe_navigation_labels():
    scene = _scene(
        _el("设置", 196, 78, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("kacier_iptv", 265, 370, w=92),
        _el("通知", 80, 590, w=40),
        _el("通用", 80, 725, w=40),
        _el("伴机息示", 80, 765, w=72),
        _el("minij_washer_r_91f0", 80, 780, w=150),
    )

    labels = [e.text for e in _safe_navigation_candidates(scene)]

    assert labels == ["无线局域网", "蓝牙", "通知", "通用", "伴机息示"]

@pytest.mark.smoke
def test_sensitive_password_root_rows_are_allowed_only_on_root_scan():
    scene = _scene(
        _el("设置", 196, 78, w=48),
        _el("Face ID与密码", 80, 590, w=108),
        _el("密码", 80, 650, w=40),
        _el("通用", 80, 725, w=40),
    )

    root_labels = [
        e.text
        for e in _safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]
    child_labels = [e.text for e in _safe_navigation_candidates(scene)]

    assert root_labels == ["Face ID与密码", "通用"]
    assert child_labels == ["通用"]

@pytest.mark.smoke
def test_short_ascii_ocr_noise_is_not_a_navigation_candidate():
    scene = _scene(
        _el("设置", 196, 78, w=48),
        _el("Oi", 48, 300, w=22),
        _el("-）", 80, 330, w=24),
        _el("通知", 80, 360, w=40),
        _el("通用", 80, 420, w=40),
        _el("App", 80, 480, w=34),
    )

    labels = [
        e.text
        for e in _safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]
    rejected = [
        row.text
        for row in DEFAULT_SETTINGS_POLICY.rejected_candidate_rows(
            scene,
            allow_sensitive_root_labels=True,
            allow_known_without_affordance=True,
        )
    ]

    assert labels == ["通知", "通用"]
    assert rejected == ["App"]

@pytest.mark.smoke
def test_exact_safe_navigation_labels_are_not_blocked_by_short_unsafe_tokens():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 72, w=48),
        _el("关于本机", 80, 280, w=72),
        _el("VPN与设备管理", 80, 340, w=112),
        _el("传输或还原iPhone", 80, 400, w=142),
        _el("关闭", 80, 460, w=40),
    )

    labels = [e.text for e in _safe_navigation_candidates(scene)]

    assert labels == ["关于本机", "VPN与设备管理", "传输或还原iPhone"]

@pytest.mark.smoke
def test_vlm_recover_root_label_resolves_when_ocr_unmatchable():
    """F:某根行 OCR 经 B/C 仍认不出 → VLM 读出后再匹配。"""
    import numpy as np

    from glassbox.cognition import Box, UIElement

    class _FakeKimi:
        def read_text_region(self, *, region_image: bytes) -> str:
            return "待机显示"

    class _Frame:
        img = np.full((400, 500, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    _reset_vlm_row_state()
    el = UIElement(type="button", box=Box(x=60, y=300, w=110, h=22),
                   text="乱码行", confidence=0.4)
    assert _canonical_expected_root_label("乱码行") is None
    assert _vlm_recover_root_label(_Phone(), el) == "待机显示"


@pytest.mark.smoke
def test_unknown_root_candidate_uses_local_vlm_crop_before_rejection():
    import cv2
    import numpy as np

    calls: list[tuple[int, int]] = []

    class _FakeKimi:
        def read_text_region(self, *, region_image: bytes) -> str:
            arr = np.frombuffer(region_image, dtype=np.uint8)
            crop = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            assert crop is not None
            calls.append(crop.shape[:2])
            return "待机显示"

        def describe_scene(self, *args, **kwargs):
            raise AssertionError("root candidate recovery must use a local row crop, not full-screen VLM")

    class _Frame:
        img = np.full((900, 500, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("P月l结机显示", 80, 420, w=120),
    )
    rejected: list[RejectedCandidate] = []

    _reset_vlm_row_state()
    _record_rejected_candidates(
        rejected,
        path=("Settings",),
        scene=scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
        phone=_Phone(),
    )

    assert rejected == []
    assert calls
    assert all(height < _Frame.img.shape[0] for height, _width in calls)
    assert all(height * width < _Frame.img.shape[0] * _Frame.img.shape[1] for height, width in calls)


@pytest.mark.smoke
def test_unknown_root_candidate_uses_local_vlm_choice_prompt():
    import cv2
    import numpy as np

    calls: list[tuple[int, int, str]] = []

    class _Response:
        raw_content = "待机显示"

    class _FakeKimi:
        def chat(self, **kwargs):
            arr = np.frombuffer(kwargs["image"], dtype=np.uint8)
            crop = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            assert crop is not None
            calls.append((*crop.shape[:2], kwargs["user_text"]))
            return _Response()

        def read_text_region(self, *, region_image: bytes) -> str:
            raise AssertionError("choice prompt should run before raw OCR fallback")

        def describe_scene(self, *args, **kwargs):
            raise AssertionError("root candidate recovery must not use full-screen describe_scene")

    class _Frame:
        img = np.full((900, 500, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("浩机見示", 80, 420, w=120),
    )
    rejected: list[RejectedCandidate] = []

    _reset_vlm_row_state()
    _record_rejected_candidates(
        rejected,
        path=("Settings",),
        scene=scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
        phone=_Phone(),
    )

    assert rejected == []
    assert calls
    assert all(height < _Frame.img.shape[0] for height, _width, _prompt in calls)
    assert any("候选标签" in prompt and "待机显示" in prompt for _height, _width, prompt in calls)


@pytest.mark.smoke
def test_unknown_root_candidate_finds_confused_scene_element_for_vlm():
    import numpy as np

    class _Response:
        raw_content = "待机显示"

    class _FakeKimi:
        def chat(self, **_kwargs):
            return _Response()

    class _Frame:
        img = np.full((980, 450, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("操作按钮", 82, 834, w=70),
        _el("供机見示", 76, 886, w=76),
    )
    rejected: list[RejectedCandidate] = []

    _reset_vlm_row_state()
    _record_rejected_candidates(
        rejected,
        path=("Settings",),
        scene=scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
        phone=_Phone(),
    )

    assert rejected == []


@pytest.mark.smoke
def test_unknown_root_candidate_on_same_row_as_known_label_is_suppressed():
    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("SDS", 38, 408, w=28),
        _el("SOS紧急联络", 80, 406, w=106),
    )
    rejected: list[RejectedCandidate] = []

    _record_rejected_candidates(
        rejected,
        path=("Settings",),
        scene=scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
        phone=None,
    )

    assert rejected == []


@pytest.mark.smoke
def test_visible_root_row_vlm_recovery_only_spends_budget_on_navigation_like_rows(monkeypatch):
    import numpy as np

    calls: list[bytes] = []

    class _FakeKimi:
        def read_text_region(self, *, region_image: bytes) -> str:
            calls.append(region_image)
            return ""

    class _Frame:
        img = np.full((900, 500, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    monkeypatch.setattr(settings_page_records.settings_scene_state, "scene_is_settings_root", lambda scene: True)
    visits = [PageVisit(path=("Settings",), title="设置", texts=("设置",))]
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("Da Li", 76, 190, w=80),
        _el("Apple 账户、iCloud等", 82, 220, w=180),
        _el("无线局域网", 80, 320, w=90),
        _el("P月l结机显示", 80, 420, w=120),
    )

    _reset_vlm_row_state()
    _record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen, phone=_Phone())

    assert len(calls) == 1


@pytest.mark.smoke
def test_visible_root_row_vlm_recovery_uses_catalog_order_prior(monkeypatch):
    import numpy as np

    prompts: list[str] = []

    class _Response:
        raw_content = "待机显示"

    class _FakeKimi:
        def chat(self, **kwargs):
            prompts.append(kwargs["user_text"])
            return _Response()

    class _Frame:
        img = np.full((980, 450, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    monkeypatch.setattr(settings_page_records.settings_scene_state, "scene_is_settings_root", lambda scene: True)
    visited_labels = (
        "无线局域网",
        "蓝牙",
        "蜂窝网络",
        "通知",
        "声音与触感",
        "专注模式",
        "屏幕使用时间",
        "通用",
        "辅助功能",
        "Siri",
        "操作按钮",
    )
    visits = [PageVisit(path=("Settings",), title="设置", texts=("设置",))]
    visits.extend(PageVisit(path=("Settings", label), title=label, texts=(label,)) for label in visited_labels)
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    scene = _scene(
        _el("设置", 20, 126, w=68, h=36, ty="button"),
        _el("操作按钮", 80, 835, w=70),
        _el("P月 传机見示", 36, 885, w=114),
        _el("Q", 48, 915, w=20),
        _el("搜索", 74, 915, w=40),
    )

    _reset_vlm_row_state()
    _record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen, phone=_Phone())

    assert any(visit.path == ("Settings", "待机显示") for visit in visits)
    assert prompts
    assert "待机显示" in prompts[-1]
    assert "无线局域网" not in prompts[-1]


@pytest.mark.smoke
def test_visible_root_row_vlm_recovery_skips_unsafe_root_values(monkeypatch):
    import numpy as np

    calls = 0

    class _FakeKimi:
        def chat(self, **_kwargs):
            nonlocal calls
            calls += 1
            return type("_Response", (), {"raw_content": "钱包与 Apple Pay"})()

    class _Frame:
        img = np.full((980, 450, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    monkeypatch.setattr(settings_page_records.settings_scene_state, "scene_is_settings_root", lambda scene: True)
    visits = [PageVisit(path=("Settings",), title="设置", texts=("设置",))]
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    scene = _scene(
        _el("设置", 20, 126, w=68, h=36, ty="button"),
        _el("VPN", 80, 641, w=36),
    )

    _reset_vlm_row_state()
    _record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen, phone=_Phone())

    assert calls == 0
    assert all(visit.path != ("Settings", "钱包与 Apple Pay") for visit in visits)


@pytest.mark.smoke
def test_visible_root_row_records_vlm_normalized_label_as_evidence(monkeypatch):
    import numpy as np

    class _Response:
        raw_content = "待机显示"

    class _FakeKimi:
        def chat(self, **_kwargs):
            return _Response()

    class _Frame:
        img = np.full((900, 500, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    monkeypatch.setattr(settings_page_records.settings_scene_state, "scene_is_settings_root", lambda scene: True)
    visits = [PageVisit(path=("Settings",), title="设置", texts=("设置",))]
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("浩机見示", 80, 420, w=120),
    )

    _reset_vlm_row_state()
    _record_visible_root_row_visits(scene=scene, visits=visits, seen_sigs=seen, phone=_Phone())

    assert visits[-1].path == ("Settings", "待机显示")
    assert visits[-1].title == "待机显示"
    assert "待机显示" in visits[-1].texts


@pytest.mark.smoke
def test_vlm_recover_root_label_noop_when_kimi_disabled():
    """VLM 关闭(默认)→ F 兜底直接 None,零行为变化。"""
    from glassbox.cognition import Box, UIElement

    class _Phone:
        kimi = None
        _last_frame = None

    _reset_vlm_row_state()
    el = UIElement(type="button", box=Box(x=60, y=300, w=110, h=22),
                   text="乱码行", confidence=0.4)
    assert _vlm_recover_root_label(_Phone(), el) is None


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("parsed", "raw_content"),
    [
        ({"action": "left_click", "coordinate": [0.5, 0.5]}, ""),
        ({"action": "left_click", "coordinate": [500, 500]}, ""),
        (None, '{"action":"left_click","coordinate":[224,405]}'),
        ({}, '{"action":"left_click","coordinate":[224,405]}'),
    ],
)
def test_vlm_point_for_label_normalizes_coordinate_forms(parsed, raw_content):
    import numpy as np

    class _Response:
        def __init__(self):
            self.parsed = parsed
            self.raw_content = raw_content

    class _FakeKimi:
        calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            assert kwargs["json_object"] is True
            assert kwargs["image"]
            return _Response()

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        def __init__(self):
            self.kimi = _FakeKimi()
            self._last_frame = _Frame()

    _reset_vlm_row_state()
    phone = _Phone()

    hit = _vlm_point_for_label(phone, "通用", scene_kind="settings_root")

    assert hit is not None
    assert hit.text == "通用"
    assert hit.box.center[1] == 535
    assert phone.kimi.calls == 1
    assert phone._ios_settings_last_vlm_point_grounding["status"] == "hit"


@pytest.mark.smoke
@pytest.mark.parametrize("scene_kind", ["springboard", "app_library", "springboard_or_app_library", "unknown"])
def test_vlm_point_for_label_allowlist_rejects_non_settings_scenes(scene_kind):
    import numpy as np

    class _FakeKimi:
        def chat(self, **_kwargs):
            raise AssertionError("non-settings scenes must not call Kimi")

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    _reset_vlm_row_state()

    assert _vlm_point_for_label(_Phone(), "通用", scene_kind=scene_kind) is None


@pytest.mark.smoke
def test_open_visible_or_scroll_to_row_does_not_call_vlm_when_match_hits(monkeypatch):
    from dataclasses import replace

    scene = _scene(_el("通用", 80, 300, w=40))

    class _Phone:
        def perceive(self):
            return scene

    def boom(*_args, **_kwargs):
        raise AssertionError("VLM fallback must only run after deterministic miss")

    actions = replace(walkthrough._navigation_actions(), vlm_point_for_label=boom)

    assert settings_navigation.open_visible_or_scroll_to_row(_Phone(), ("通用",), actions).text == "通用"


@pytest.mark.smoke
def test_open_visible_or_scroll_to_row_matches_ipad_sidebar_by_canonical_label():
    from dataclasses import replace

    scene = _scene(
        _el("Screen Time", 70, 360, w=82),
        _el("Lock Screen Time Settings", 318, 845, w=178),
    )

    class _Geometry:
        model = "ipad_mini_7"

    class _Phone:
        device_geometry = _Geometry()

        def _viewport_size(self):
            return 640, 989

        def perceive(self):
            return scene

    def canonical(text):
        return "屏幕使用时间" if text in {"屏幕使用时间", "Screen Time"} else None

    def boom(*_args, **_kwargs):
        raise AssertionError("VLM fallback must only run after deterministic miss")

    actions = replace(
        walkthrough._navigation_actions(),
        canonical_expected_root_label=canonical,
        vlm_point_for_label=boom,
    )

    hit = settings_navigation.open_visible_or_scroll_to_row(_Phone(), ("屏幕使用时间",), actions)

    assert hit is not None
    assert hit.text == "Screen Time"


@pytest.mark.smoke
def test_open_visible_or_scroll_to_row_matches_ipad_split_ampersand_sidebar_label():
    from dataclasses import replace

    scene = _scene(
        _el("Home Screen &", 70, 360, w=118),
        _el("App Library", 70, 382, w=90),
        _el("Search in App", 318, 845, w=92),
    )

    class _Geometry:
        model = "ipad_mini_7"

    class _Phone:
        device_geometry = _Geometry()

        def _viewport_size(self):
            return 640, 989

        def perceive(self):
            return scene

    def boom(*_args, **_kwargs):
        raise AssertionError("VLM fallback must only run after deterministic miss")

    actions = replace(walkthrough._navigation_actions(), vlm_point_for_label=boom)

    hit = settings_navigation.open_visible_or_scroll_to_row(
        _Phone(),
        ("Home Screen & App Library",),
        actions,
    )

    assert hit is not None
    assert hit.text == "Home Screen &"


@pytest.mark.smoke
def test_vlm_point_for_label_rejects_out_of_band_point():
    import numpy as np

    class _Response:
        def __init__(self):
            self.parsed = {"action": "left_click", "coordinate": [224, 1200]}
            self.raw_content = ""

    class _FakeKimi:
        def chat(self, **_kwargs):
            return _Response()

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    _reset_vlm_row_state()
    phone = _Phone()

    assert _vlm_point_for_label(phone, "通用", scene_kind="settings_root") is None
    assert phone._ios_settings_vlm_point_failure_reason == "out_of_band"


@pytest.mark.smoke
def test_vlm_point_for_label_rejects_unsafe_label_without_kimi_call():
    import numpy as np

    class _FakeKimi:
        def chat(self, **_kwargs):
            raise AssertionError("unsafe labels must not call Kimi")

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()

    _reset_vlm_row_state()
    phone = _Phone()

    assert _vlm_point_for_label(phone, "密码", scene_kind="settings_root") is None
    assert phone._ios_settings_vlm_point_failure_reason == "unsafe_label"


@pytest.mark.smoke
def test_vlm_point_for_label_cache_avoids_rebilling_stuck_frame():
    import numpy as np

    class _Response:
        def __init__(self):
            self.parsed = {"action": "left_click", "coordinate": [0.5, 0.5]}
            self.raw_content = ""

    class _FakeKimi:
        def __init__(self):
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            return _Response()

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        def __init__(self):
            self.kimi = _FakeKimi()
            self._last_frame = _Frame()

    _reset_vlm_row_state()
    phone = _Phone()

    first = _vlm_point_for_label(phone, "通用", scene_kind="settings_root")
    second = _vlm_point_for_label(phone, "通用", scene_kind="settings_root")

    assert first is not None
    assert second is not None
    assert phone.kimi.calls == 1
    assert phone._ios_settings_last_vlm_point_grounding["cached"] is True


@pytest.mark.smoke
def test_vlm_point_budget_is_separate_from_text_budget_but_total_capped():
    import numpy as np

    class _Response:
        def __init__(self):
            self.parsed = {"action": "left_click", "coordinate": [0.5, 0.5]}
            self.raw_content = ""

    class _FakeKimi:
        def __init__(self):
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            return _Response()

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        def __init__(self):
            self.kimi = _FakeKimi()
            self._last_frame = _Frame()

    _reset_vlm_row_state()
    settings_vlm_rows._row_calls = settings_vlm_rows._ROW_CALL_BUDGET
    phone = _Phone()

    assert _vlm_point_for_label(phone, "通用", scene_kind="settings_root") is not None

    settings_vlm_rows._point_calls = (
        settings_vlm_rows._ROW_TOTAL_CALL_BUDGET - settings_vlm_rows._row_calls
    )
    phone._last_frame = type("_Frame2", (), {
        "img": np.full((1001, 448, 3), 220, dtype=np.uint8),
    })()

    assert _vlm_point_for_label(phone, "通知", scene_kind="settings_root") is None
    assert phone._ios_settings_vlm_point_failure_reason == "budget_exhausted"


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("no_kimi", "no_kimi_or_frame"),
        ("parse_failed", "parse_failed"),
        ("scene_rejected", "scene_kind_rejected"),
    ],
)
def test_vlm_point_for_label_records_failure_reasons(setup, reason):
    import numpy as np

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _ParseFailKimi:
        def chat(self, **_kwargs):
            return type("_Response", (), {"parsed": {}, "raw_content": "not json"})()

    class _Phone:
        def __init__(self):
            self.kimi = None if setup == "no_kimi" else _ParseFailKimi()
            self._last_frame = _Frame()

    _reset_vlm_row_state()
    phone = _Phone()
    scene_kind = "springboard" if setup == "scene_rejected" else "settings_root"

    assert _vlm_point_for_label(phone, "通用", scene_kind=scene_kind) is None
    assert phone._ios_settings_vlm_point_failure_reason == reason
    assert phone._ios_settings_last_vlm_point_grounding["reason"] == reason


@pytest.mark.smoke
def test_vlm_point_that_does_not_navigate_records_tap_no_navigation(monkeypatch):
    import numpy as np
    from dataclasses import replace

    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _: None)
    candidate_scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("关于本机", 80, 300, w=72),
        _el("›", 386, 300, w=12),
    )
    miss_scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("乱码行", 80, 300, w=72),
        _el("›", 386, 300, w=12),
    )

    class _Response:
        def __init__(self):
            self.parsed = {"action": "left_click", "coordinate": [0.5, 0.5]}
            self.raw_content = ""

    class _FakeKimi:
        def chat(self, **_kwargs):
            return _Response()

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        def __init__(self):
            self.kimi = _FakeKimi()
            self._last_frame = _Frame()
            self.perceive_calls = 0
            self.tapped_vlm_row = False

        def perceive(self):
            self.perceive_calls += 1
            return candidate_scene if self.perceive_calls <= 2 else miss_scene

        def invalidate_perceive_cache(self):
            pass

    failures: list[NavigationFailure] = []

    def record_failure(store, *, path, scene, text, reason):
        store.append(NavigationFailure(path=path, title="设置", text=text, reason=reason))

    def tap_row(phone, row):
        assert row.type_source == "vlm_point_for_label"
        phone.tapped_vlm_row = True
        return True

    actions = replace(
        walkthrough._navigation_actions(),
        scene_kind=lambda _scene, phone=None: "settings_root",
        scene_is_settings_root=lambda _scene: True,
        root_coverage_perceive=lambda phone, _depth: phone.perceive(),
        record_visible_page=lambda **_kwargs: True,
        record_visible_root_row_visits=lambda **_kwargs: None,
        blocked_child_navigation_reason=lambda _scene: None,
        should_audit_candidates=lambda _depth: False,
        record_rejected_candidates=lambda *_args, **_kwargs: None,
        should_traverse_candidates=lambda _depth: True,
        safe_navigation_candidates=lambda _scene, **_kwargs: [
            _el("关于本机", 80, 300, w=72),
        ],
        tap_settings_row=tap_row,
        same_page_after_tap=lambda *_args, **_kwargs: True,
        is_settings_section_header=lambda *_args, **_kwargs: False,
        canonical_expected_root_label=lambda _text: None,
        record_navigation_failure=record_failure,
        scroll_budget_for_depth=lambda _depth: 1,
        scroll_down_confirmed=lambda *_args, **_kwargs: ("stuck", miss_scene),
        scroll_to_top=None,
        max_root_scroll_resets=0,
        crawl_missing_root_pages_via_search=lambda *_args, **_kwargs: None,
    )
    phone = _Phone()

    _reset_vlm_row_state()
    settings_navigation.crawl_current_page(
        phone,
        path=("Settings",),
        visits=[],
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=failures,
        actions=actions,
    )

    assert phone.tapped_vlm_row
    assert [(item.path, item.text, item.reason) for item in failures] == [
        (("Settings",), "关于本机", "tap_no_navigation"),
    ]


@pytest.mark.smoke
def test_vlm_point_synthetic_element_flows_through_picokvm_settings_row_projection():
    import numpy as np

    from glassbox.phone import Phone

    class _Response:
        def __init__(self):
            self.parsed = {"action": "left_click", "coordinate": [2000, 405]}
            self.raw_content = ""

    class _FakeKimi:
        def chat(self, **_kwargs):
            return _Response()

    class _Frame:
        img = np.full((1000, 448, 3), 220, dtype=np.uint8)

    class _Phone:
        kimi = _FakeKimi()
        _last_frame = _Frame()
        _last_scene = _scene(_el("设置", 18, 126, w=68, h=36))
        _last_scene.platform_scene_kind = "settings_root"

        def _effector_backend(self):
            return "picokvm"

        def _viewport_size(self):
            return 448, 1000

    _reset_vlm_row_state()
    phone = _Phone()

    hit = _vlm_point_for_label(phone, "通用", scene_kind="settings_root")

    assert hit is not None
    assert hit.box.center[0] != 2000
    assert Phone._picokvm_settings_row_tap_point_for_element(phone, hit) == (224, 535)


@pytest.mark.smoke
def test_picokvm_ipad_settings_row_projection_stays_in_sidebar():
    from glassbox.phone import Phone

    class _Geometry:
        model = "ipad_mini_7"

    class _Phone:
        device_geometry = _Geometry()
        _last_scene = _scene(
            _el("设置", 48, 72, w=72, h=28),
            _el("通用", 72, 332, w=44, h=24),
        )
        _last_scene.viewport_size = (744, 1133)
        _last_scene.platform_scene_kind = "settings_detail"
        _last_scene.safe_actions = ("tap_root_row",)

        def _effector_backend(self):
            return "picokvm"

        def _viewport_size(self):
            return 744, 1133

    hit = _el("通用", 72, 332, w=44, h=24)

    assert Phone._picokvm_settings_row_tap_point_for_element(_Phone(), hit) == (94, 344)


@pytest.mark.smoke
def test_picokvm_ipad_detail_row_projection_moves_inside_detail_pane():
    from glassbox.phone import Phone

    class _Geometry:
        model = "ipad_mini_7"

    class _Phone:
        device_geometry = _Geometry()
        _last_scene = _scene(
            _el("Screen Time", 70, 328, w=82, h=14),
            _el("Downtime", 320, 341, w=66, h=13),
        )
        _last_scene.viewport_size = (640, 989)
        _last_scene.platform_scene_kind = "settings_detail"
        _last_scene.page_id = "settings/Screen Time"
        _last_scene.safe_actions = ("tap_root_row",)

        def _effector_backend(self):
            return "picokvm"

        def _viewport_size(self):
            return 640, 989

    hit = _el("Downtime", 320, 341, w=66, h=13)

    assert Phone._picokvm_settings_row_tap_point_for_element(_Phone(), hit) == (403, 347)


@pytest.mark.smoke
def test_game_center_is_root_only_safe_but_account_rows_stay_unsafe():
    """Game Center is safe as a root-only inventory page; account rows stay blocked."""
    assert not _is_unsafe_navigation_text("Game Center")
    assert not _is_unsafe_navigation_text("GameCenter")
    assert _is_unsafe_navigation_text("iClOud")


@pytest.mark.smoke
@pytest.mark.parametrize("toggle", ["On", "Off", "打开", "关闭", "开", "关"])
def test_toggle_state_value_is_unsafe_only_as_whole_label(toggle):
    """开关「状态值」整行才算非导航;不能作为子串误伤真实导航行。"""
    assert _is_unsafe_navigation_text(toggle)


@pytest.mark.smoke
@pytest.mark.parametrize("label", [
    "NotificatiOns", "ActiOnButtOn", "Notifications", "Action Button", "关于本机", "Connections",
])
def test_nav_rows_containing_state_substrings_stay_safe(label):
    """「On/关」曾在子串档,误伤含这些字的导航行(Notifications/操作按钮/关于本机)。"""
    assert not _is_unsafe_navigation_text(label)

@pytest.mark.smoke
def test_long_english_safe_navigation_labels_are_not_filtered_by_length():
    scene = _scene(
        _el("Settings", 190, 78, w=70),
        _el("Home Screen & App Library", 72, 300, w=210),
        _el("VPN & Device Management", 72, 360, w=200),
        _el("Transfer or Reset iPhone", 72, 420, w=190),
        _el("This paragraph should not be treated as navigation", 72, 480, w=360),
    )

    labels = [e.text for e in _safe_navigation_candidates(scene)]

    assert labels == [
        "Home Screen & App Library",
        "VPN & Device Management",
        "Transfer or Reset iPhone",
    ]

@pytest.mark.smoke
def test_bluetooth_device_list_is_not_crawled_as_navigation_rows():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("蓝牙", 196, 78, w=48),
        _el("蓝牙", 70, 270, w=48),
        _el("我的设备", 70, 420, w=72),
        _el("Keyboard", 80, 480, w=92),
        _el("其他设备", 70, 560, w=72),
        _el("Headphones", 80, 620, w=110),
    )

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "dynamic Bluetooth device rows"

@pytest.mark.smoke
def test_bluetooth_ios26_generic_device_section_is_blocked():
    scene = _scene_from_texts([
        "<",
        "蓝牙",
        "连接可用于流播放音乐、打电话和玩游戏等活动",
        "蓝牙",
        "“蓝牙”设置打开时，此iPhone可被发现为 \"iPhone”。",
        "设备",
        "若要将 Apple Watch 与iPhone配对，请前往 Apple Watch",
        "App。",
    ])

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "dynamic Bluetooth device rows"

@pytest.mark.smoke
def test_battery_control_rows_are_blocked_to_avoid_setting_changes():
    scene = _scene_from_texts([
        "<",
        "电池",
        "充电上限",
        "80%",
        "85%",
        "优化电池充电",
        "电池百分比",
    ])

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "Battery selector/toggle rows"

@pytest.mark.smoke
def test_notification_control_rows_are_blocked_to_avoid_setting_changes():
    scene = _scene_from_texts([
        "<",
        "通知",
        "显示为",
        "定时推送摘要",
        "显示预览",
        "通知样式",
        "查找",
    ])

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "Notification selector/toggle rows"

@pytest.mark.smoke
def test_notification_app_rows_are_blocked_to_avoid_setting_changes():
    scene = _scene_from_texts([
        "<",
        "查找",
        "允许通知",
        "即时通知",
        "提醒",
        "声音",
        "标记",
    ])

    assert _safe_navigation_candidates(scene) == []
    assert _blocked_child_navigation_reason(scene) == "Notification app selector/toggle rows"

@pytest.mark.smoke
def test_blocked_page_report_records_reason_once():
    scene = _scene_from_texts([
        "无线局域网",
        "我的网络",
        "kacier",
        "其他网络",
    ])
    blocked_pages: list[BlockedPage] = []
    reason = _blocked_child_navigation_reason(scene)

    assert reason == "dynamic Wi-Fi rows"
    _record_blocked_page(
        blocked_pages,
        path=("Settings", "无线局域网"),
        scene=scene,
        reason=reason,
    )
    _record_blocked_page(
        blocked_pages,
        path=("Settings", "无线局域网"),
        scene=scene,
        reason=reason,
    )

    assert len(blocked_pages) == 1
    assert blocked_pages[0].path == ("Settings", "无线局域网")
    assert blocked_pages[0].reason == "dynamic Wi-Fi rows"

@pytest.mark.smoke
def test_passcode_prompt_is_reported_as_authentication_blocked_page():
    scene = _scene_from_texts([
        "输入密码",
        "请输入iPhone密码以继续",
        "1",
        "2",
        "3",
    ])
    blocked_pages: list[BlockedPage] = []
    reason = _blocked_child_navigation_reason(scene)

    assert reason == "authentication required"
    assert _safe_navigation_candidates(scene) == []
    _record_blocked_page(
        blocked_pages,
        path=("Settings", "Face ID与密码"),
        scene=scene,
        reason=reason,
    )

    assert blocked_pages[0].reason == "authentication required"
    assert blocked_pages[0].path == ("Settings", "Face ID与密码")

@pytest.mark.smoke
def test_unknown_navigation_rows_are_reported_for_review():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("关于本机", 80, 280, w=72),
        _el("›", 386, 280, w=12),
        _el("新设置页面", 80, 340, w=90),
        _el("关闭", 80, 400, w=40),
    )
    rejected: list[RejectedCandidate] = []

    _record_rejected_candidates(
        rejected,
        path=("Settings", "通用"),
        scene=scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )

    assert [(item.text, item.reason) for item in rejected] == [
        ("新设置页面", "unknown_navigation_label"),
        ("关闭", "unsafe_text"),
    ]

@pytest.mark.smoke
def test_unknown_rows_with_navigation_affordance_are_crawled():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("新设置页面", 80, 340, w=90),
        _el("›", 386, 340, w=12),
        _el("说明文字", 80, 400, w=72),
    )
    rejected: list[RejectedCandidate] = []

    labels = [e.text for e in _safe_navigation_candidates(scene)]
    _record_rejected_candidates(
        rejected,
        path=("Settings", "通用"),
        scene=scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )

    assert labels == ["新设置页面"]
    assert [(item.text, item.reason) for item in rejected] == [
        ("说明文字", "unknown_navigation_label"),
    ]

@pytest.mark.smoke
def test_unknown_list_item_rows_are_crawled_without_chevron_ocr():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("新设置页面", 80, 340, w=90, ty="list_item"),
    )

    labels = [e.text for e in _safe_navigation_candidates(scene)]

    assert labels == ["新设置页面"]

@pytest.mark.smoke
def test_settings_button_rows_are_navigation_affordances_without_chevron_ocr():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("关于本机", 80, 340, w=90, ty="button"),
    )

    labels = [
        e.text
        for e in _safe_navigation_candidates(scene, allow_known_without_affordance=False)
    ]

    assert labels == ["关于本机"]

@pytest.mark.smoke
def test_settings_section_headers_are_not_navigation_button_rows():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("辅助功能", 178, 78, w=76),
        _el("视觉", 40, 372, w=36, ty="button"),
        _el("旁白", 80, 416, w=42, ty="button"),
        _el("缩放", 80, 470, w=42, ty="button"),
    )

    labels = [
        e.text
        for e in _safe_navigation_candidates(scene, allow_known_without_affordance=False)
    ]

    assert labels == ["旁白", "缩放"]

@pytest.mark.smoke
def test_section_header_detected_at_viewport_bottom_without_row_below():
    """视觉 处在视口底部、下方没有行可见 —— 靠「同行右侧无内容」仍判成 header。

    回归 child audit 失败:辅助功能>视觉 被当导航候选 tap → tap_no_navigation。
    旧规则只认「下方有缩进行」,header 在视口底部时失效。
    """
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("辅助功能", 178, 78, w=76),
        _el("旁白", 80, 740, w=42, ty="button"),
        _el("关闭＞", 352, 740, w=56),
        _el("视觉", 40, 880, w=36, ty="button"),
    )
    header = scene.elements[-1]
    assert _is_settings_section_header(scene, header)

@pytest.mark.smoke
def test_real_row_with_trailing_chevron_not_flagged_as_header():
    """带 chevron 的真实行(即便在视口底部、下方无行)不被误判成 header。"""
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("辅助功能", 178, 78, w=76),
        _el("旁白", 40, 880, w=42, ty="button"),
        _el("关闭＞", 352, 880, w=56),
    )
    row = scene.elements[2]
    assert not _is_settings_section_header(scene, row)

@pytest.mark.smoke
def test_known_nested_rows_need_navigation_affordance_to_avoid_toggling_app_rows():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("蜂窝网络", 178, 78, w=76),
        _el("Safari浏览器", 80, 340, w=104),
    )
    rejected: list[RejectedCandidate] = []

    labels = [
        e.text
        for e in _safe_navigation_candidates(scene, allow_known_without_affordance=False)
    ]
    _record_rejected_candidates(
        rejected,
        path=("Settings", "蜂窝网络"),
        scene=scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )

    assert labels == []
    assert [(item.text, item.reason) for item in rejected] == [
        ("Safari浏览器", "missing_navigation_affordance"),
    ]

@pytest.mark.smoke
def test_tap_navigation_detection_prefers_title_change_over_text_overlap():
    before = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("关于本机", 80, 280, w=72),
        _el("软件更新", 80, 340, w=72),
        _el("iPhone 储存空间", 80, 400, w=130),
        _el("语言与地区", 80, 460, w=90),
        _el("词典", 80, 520, w=40),
    )
    after = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("关于本机", 180, 78, w=72),
        _el("关于本机", 80, 280, w=72),
        _el("软件更新", 80, 340, w=72),
        _el("iPhone 储存空间", 80, 400, w=130),
        _el("语言与地区", 80, 460, w=90),
        _el("词典", 80, 520, w=40),
    )

    assert _same_visible_page(
        [element.text for element in before.elements if element.text],
        [element.text for element in after.elements if element.text],
    )
    assert not _same_page_after_tap(before, after, expected_title="关于本机")
    assert _same_page_after_tap(before, after, expected_title="软件更新")

@pytest.mark.smoke
def test_tap_navigation_detection_accepts_known_shortened_page_titles():
    before = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("蜂窝网络", 178, 78, w=76),
        _el("Safari浏览器", 80, 340, w=104),
        _el("关闭", 80, 400, w=40),
        _el("无线局域网助理", 80, 460, w=120),
        _el("蜂窝数据选项", 80, 520, w=110),
    )
    after = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("Safari", 190, 78, w=70),
        _el("Safari浏览器", 80, 340, w=104),
        _el("关闭", 80, 400, w=40),
        _el("无线局域网助理", 80, 460, w=120),
        _el("蜂窝数据选项", 80, 520, w=110),
    )

    assert _same_visible_page(
        [element.text for element in before.elements if element.text],
        [element.text for element in after.elements if element.text],
    )
    assert not _same_page_after_tap(before, after, expected_title="Safari浏览器")

@pytest.mark.smoke
def test_crawler_records_rejected_candidates_seen_after_scroll(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "STRICT_CHILD_CANDIDATE_AUDIT", True)
    monkeypatch.setattr(walkthrough, "MAX_CHILD_SCROLLS_PER_PAGE", 8)
    phone = _ScrollingPhone([
        _scene(
            _el("<", 18, 72, w=14, ty="nav_back"),
            _el("通用", 198, 78, w=48),
        ),
        _scene(
            _el("<", 18, 72, w=14, ty="nav_back"),
            _el("通用", 198, 78, w=48),
            _el("滚动新页面", 80, 340, w=90),
        ),
    ])
    visits: list[PageVisit] = []
    rejected: list[RejectedCandidate] = []

    _crawl_current_page(
        phone,
        path=("Settings", "通用"),
        visits=visits,
        seen_sigs=set(),
        depth=1,
        max_depth=2,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=rejected,
        navigation_failures=[],
    )

    assert [visit.texts for visit in visits] == [
        ("<", "通用"),
        ("<", "通用", "滚动新页面"),
    ]
    assert [(item.path, item.text, item.reason) for item in rejected] == [
        (("Settings", "通用"), "滚动新页面", "unknown_navigation_label"),
    ]

@pytest.mark.smoke
def test_crawler_reports_max_pages_limit(monkeypatch):
    monkeypatch.setattr(walkthrough, "MAX_PAGES_VISITED", 1)
    phone = _Phone(_scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
    ))
    limits: set[str] = set()

    _crawl_current_page(
        phone,
        path=("Settings", "通用"),
        visits=[],
        seen_sigs=set(),
        depth=1,
        max_depth=2,
        limits_hit=limits,
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )

    assert limits == {"max_pages"}

@pytest.mark.smoke
def test_crawler_reports_max_depth_when_child_navigation_remains():
    phone = _Phone(_scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("关于本机", 80, 280, w=72),
        _el("›", 386, 280, w=12),
    ))
    limits: set[str] = set()

    old_child_navigation = walkthrough.CHILD_NAVIGATION_ENABLED
    walkthrough.CHILD_NAVIGATION_ENABLED = True
    try:
        _crawl_current_page(
            phone,
            path=("Settings", "通用"),
            visits=[],
            seen_sigs=set(),
            depth=1,
            max_depth=1,
            limits_hit=limits,
            blocked_pages=[],
            rejected_candidates=[],
            navigation_failures=[],
        )
    finally:
        walkthrough.CHILD_NAVIGATION_ENABLED = old_child_navigation

    assert limits == {"max_depth"}

@pytest.mark.smoke
def test_crawler_reports_max_scrolls_when_more_viewports_remain(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "MAX_CHILD_SCROLLS_PER_PAGE", 1)
    phone = _ScrollingPhone([
        _scene(
            _el("<", 18, 72, w=14, ty="nav_back"),
            _el("通用", 198, 78, w=48),
        ),
        _scene(
            _el("<", 18, 72, w=14, ty="nav_back"),
            _el("通用", 198, 78, w=48),
            _el("页面底部文字", 80, 820, w=120),
        ),
    ])
    limits: set[str] = set()

    _crawl_current_page(
        phone,
        path=("Settings", "通用"),
        visits=[],
        seen_sigs=set(),
        depth=1,
        max_depth=2,
        limits_hit=limits,
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )

    assert limits == {"max_scrolls_per_page"}


@pytest.mark.smoke
def test_ipad_root_stuck_scroll_falls_through_to_search_without_reset(monkeypatch):
    monkeypatch.setattr(settings_navigation.time, "sleep", lambda _: None)
    root = _scene(
        _el("Settings", 48, 72, w=70),
        _el("Notifications", 72, 300, w=110),
    )

    class IPadPhone:
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def perceive(self):
            return root

    reset_calls: list[str] = []
    search_calls: list[dict] = []

    actions = replace(
        walkthrough._navigation_actions(),
        scene_is_settings_root=lambda _scene: True,
        root_coverage_perceive=lambda _phone, _depth: root,
        record_visible_page=lambda **_kwargs: True,
        record_visible_root_row_visits=lambda **_kwargs: None,
        blocked_child_navigation_reason=lambda _scene: None,
        should_audit_candidates=lambda _depth: False,
        record_rejected_candidates=lambda *_args, **_kwargs: None,
        should_traverse_candidates=lambda _depth: False,
        scroll_budget_for_depth=lambda _depth: 1,
        scroll_down_confirmed=lambda *_args, **_kwargs: ("stuck", root),
        scroll_to_top=lambda _phone: reset_calls.append("reset"),
        max_root_scroll_resets=2,
        root_coverage=lambda _visits, phone=None: {
            "expected": ["电池"],
            "visited": [],
            "missing": ["电池"],
        },
        entry_exempt_sections=lambda _visits, phone=None: set(),
        crawl_missing_root_pages_via_search=lambda _phone, **kwargs: search_calls.append(kwargs),
    )

    settings_navigation.crawl_current_page(
        IPadPhone(),
        path=("Settings",),
        visits=[],
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
        actions=actions,
    )

    assert reset_calls == []
    assert len(search_calls) == 1


@pytest.mark.smoke
def test_crawler_records_navigation_failure_when_tap_does_not_open(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("通用", 198, 78, w=48),
        _el("关于本机", 80, 280, w=72),
        _el("›", 386, 280, w=12),
    )
    phone = _NoNavigationPhone(scene)
    failures: list[NavigationFailure] = []

    _crawl_current_page(
        phone,
        path=("Settings", "通用"),
        visits=[],
        seen_sigs=set(),
        depth=1,
        max_depth=2,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=failures,
    )

    assert phone.taps == [(125, 290)]
    assert [(item.path, item.text, item.reason) for item in failures] == [
        (("Settings", "通用"), "关于本机", "tap_no_navigation"),
    ]

@pytest.mark.smoke
def test_root_crawl_records_observed_root_title_after_shifted_tap(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(walkthrough, "_crawl_missing_root_pages_via_search", lambda *args, **kwargs: None)
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: True)
    root = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("通知", 80, 360, w=40),
        _el("›", 386, 360, w=12),
    )
    observed = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("声效与触感反馈", 160, 78, w=128),
        _el("静音模式", 80, 280, w=72),
    )

    class Phone:
        def __init__(self):
            self.scene = root

        def perceive(self):
            return self.scene

        def _viewport_size(self):
            return 448, 973

        def tap_xy(self, x, y):
            del x, y
            self.scene = observed

        def key(self, modifier, keycode):
            del modifier, keycode
            self.scene = root

        def invalidate_perceive_cache(self):
            pass

        def wheel_scroll_down(self, *, ticks=None):
            del ticks

    visits: list[PageVisit] = []

    _crawl_current_page(
        Phone(),
        path=("Settings",),
        visits=visits,
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )

    assert ("Settings", "声音与触感") in [visit.path for visit in visits]


@pytest.mark.smoke
def test_root_crawl_maps_live_ipad_short_sounds_title_to_root_coverage(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(walkthrough, "_crawl_missing_root_pages_via_search", lambda *args, **kwargs: None)
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: True)
    root = _scene(
        _el("Settings", 48, 72, w=70, ty="button"),
        _el("Camera", 80, 360, w=70),
        _el("›", 386, 360, w=12),
    )
    observed = _scene(
        _el("Sounds", 404, 44, w=70),
        _el("Ringtone", 404, 240, w=84),
    )

    class Phone:
        def __init__(self):
            self.scene = root

        def perceive(self):
            return self.scene

        def _viewport_size(self):
            return 744, 1133

        def tap_xy(self, x, y):
            del x, y
            self.scene = observed

        def key(self, modifier, keycode):
            del modifier, keycode
            self.scene = root

        def invalidate_perceive_cache(self):
            pass

        def wheel_scroll_down(self, *, ticks=None):
            del ticks

    visits: list[PageVisit] = []

    _crawl_current_page(
        Phone(),
        path=("Settings",),
        visits=visits,
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )

    paths = [visit.path for visit in visits]
    assert ("Settings", "声音与触感") in paths
    assert ("Settings", "Camera") not in paths


@pytest.mark.smoke
def test_root_crawl_keeps_observed_non_root_title_instead_of_requested_root(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(walkthrough, "_crawl_missing_root_pages_via_search", lambda *args, **kwargs: None)
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: True)
    root = _scene(
        _el("Settings", 48, 72, w=70, ty="button"),
        _el("General", 80, 360, w=70),
        _el("›", 386, 360, w=12),
    )
    observed = _scene(
        _el("Display & Brightness", 404, 44, w=160),
        _el("Appearance", 404, 240, w=90),
    )

    class Phone:
        def __init__(self):
            self.scene = root

        def perceive(self):
            return self.scene

        def _viewport_size(self):
            return 744, 1133

        def tap_xy(self, x, y):
            del x, y
            self.scene = observed

        def key(self, modifier, keycode):
            del modifier, keycode
            self.scene = root

        def invalidate_perceive_cache(self):
            pass

        def wheel_scroll_down(self, *, ticks=None):
            del ticks

    visits: list[PageVisit] = []

    _crawl_current_page(
        Phone(),
        path=("Settings",),
        visits=visits,
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )

    paths = [visit.path for visit in visits]
    assert ("Settings", "Display & Brightness") in paths
    assert ("Settings", "通用") not in paths


@pytest.mark.smoke
def test_root_crawl_canonicalizes_root_alias_when_child_title_is_missing(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(walkthrough, "_crawl_missing_root_pages_via_search", lambda *args, **kwargs: None)
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: True)
    root = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("SOS", 80, 360, w=40),
        _el("›", 386, 360, w=12),
    )
    observed = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("18:41", 190, 78, w=48),
        _el("隐私与安全性", 80, 280, w=110),
    )

    class Phone:
        def __init__(self):
            self.scene = root

        def perceive(self):
            return self.scene

        def _viewport_size(self):
            return 448, 973

        def tap_xy(self, x, y):
            del x, y
            self.scene = observed

        def key(self, modifier, keycode):
            del modifier, keycode
            self.scene = root

        def invalidate_perceive_cache(self):
            pass

        def wheel_scroll_down(self, *, ticks=None):
            del ticks

    visits: list[PageVisit] = []

    _crawl_current_page(
        Phone(),
        path=("Settings",),
        visits=visits,
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=[],
    )

    assert ("Settings", "紧急 SOS") in [visit.path for visit in visits]

@pytest.mark.smoke
def test_root_semantic_rejected_tap_is_deferred_to_root_coverage(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(walkthrough, "_crawl_missing_root_pages_via_search", lambda *args, **kwargs: None)
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: True)
    scene = _scene(
        _el("设置", 18, 126, w=68, h=36, ty="button"),
        _el("屏幕时间", 80, 360, w=76),
        _el("›", 386, 360, w=12),
    )

    class Phone(_NoNavigationPhone):
        def tap_xy(self, x: int, y: int) -> ActionResult:
            self.taps.append((x, y))
            return ActionResult.failed(
                backend="picokvm",
                connected=True,
                error="semantic rejected",
            )

    failures: list[NavigationFailure] = []

    _crawl_current_page(
        Phone(scene),
        path=("Settings",),
        visits=[],
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=failures,
    )

    assert failures == []

@pytest.mark.smoke
def test_root_tap_retries_after_same_page_settle_before_recording_failure(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(walkthrough, "_crawl_missing_root_pages_via_search", lambda *args, **kwargs: None)
    monkeypatch.setattr(walkthrough, "_scene_is_settings_root", lambda scene: True)
    root = _scene(
        _el("设置", 204, 84, w=36, ty="button"),
        _el("显示与亮度", 80, 280, w=88, ty="button"),
        _el("›", 386, 280, w=12),
    )
    settled_root = _scene(
        _el("设置", 204, 84, w=36, ty="button"),
        _el("显示与亮度", 80, 252, w=88, ty="button"),
        _el("›", 386, 252, w=12),
    )
    child = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("显示与亮度", 160, 78, w=100),
        _el("外观", 80, 280, w=40),
    )

    class Phone:
        def __init__(self):
            self.scene = root
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def _viewport_size(self):
            return 448, 973

        def tap_xy(self, x, y):
            self.taps.append((x, y))
            self.scene = settled_root if len(self.taps) == 1 else child

        def key(self, modifier, keycode):
            self.keys.append((modifier, keycode))
            self.scene = settled_root

        def invalidate_perceive_cache(self):
            pass

        def wheel_scroll_down(self, *, ticks=None):
            del ticks

    phone = Phone()
    visits: list[PageVisit] = []
    failures: list[NavigationFailure] = []

    _crawl_current_page(
        phone,
        path=("Settings",),
        visits=visits,
        seen_sigs=set(),
        depth=0,
        max_depth=1,
        limits_hit=set(),
        blocked_pages=[],
        rejected_candidates=[],
        navigation_failures=failures,
    )

    assert phone.taps == [(125, 290), (125, 262)]
    assert ("Settings", "显示与亮度") in [visit.path for visit in visits]
    assert failures == []

@pytest.mark.smoke
def test_root_child_crawl_returns_one_level_after_blocked_page(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    monkeypatch.setattr(walkthrough, "ROOT_COVERAGE_MODE", False)
    monkeypatch.setattr(walkthrough, "CHILD_NAVIGATION_ENABLED", True)
    root = _scene(
        _el("设置", 198, 78, w=48),
        _el("无线局域网", 80, 280, w=96),
        _el("›", 386, 280, w=12),
        _el("蓝牙", 80, 334, w=40),
        _el("蜂窝网络", 80, 388, w=72),
        _el("电池", 80, 442, w=40),
    )
    wifi = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("编辑", 340, 78, w=40),
        _el("无线局域网", 180, 78, w=96),
        _el("接入无线局域网、查看可用网络，并管理加入网", 60, 160, w=320),
        _el("kacier_iptv", 80, 360, w=90),
    )

    class Phone:
        def __init__(self):
            self.scene = root
            self.taps: list[tuple[int, int]] = []
            self.keys: list[tuple[int, int]] = []

        def perceive(self):
            return self.scene

        def _viewport_size(self):
            return 448, 973

        def tap_xy(self, x, y):
            self.taps.append((x, y))
            if self.scene is root:
                self.scene = wifi

        def key(self, modifier, keycode):
            self.keys.append((modifier, keycode))
            self.scene = root

        def invalidate_perceive_cache(self):
            pass

        def wheel_scroll_down(self, *, ticks=None):
            pass

        def swipe_up(self, **kwargs):
            pass

        def swipe_down(self, **kwargs):
            pass

    phone = Phone()
    blocked: list[BlockedPage] = []

    _crawl_current_page(
        phone,
        path=("Settings",),
        visits=[],
        seen_sigs=set(),
        depth=0,
        max_depth=2,
        limits_hit=set(),
        blocked_pages=blocked,
        rejected_candidates=[],
        navigation_failures=[],
    )

    assert phone.keys[0] == (0x08, 0x2F)
    assert phone.scene is root
    assert (("Settings", "无线局域网"), "dynamic Wi-Fi rows") in [
        (item.path, item.reason) for item in blocked
    ]

@pytest.mark.smoke
def test_return_one_level_falls_back_to_visible_back_button(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    ticks = iter([0.0, 1.0, 4.0, 4.0, 4.0])
    monkeypatch.setattr(walkthrough.time, "monotonic", lambda: next(ticks))
    child = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("充电", 198, 78, w=48),
    )
    parent = _scene(
        _el("设置", 198, 78, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
    )
    phone = _BackFallbackPhone(child, parent)

    assert _return_one_level(phone, parent_texts=["设置", "无线局域网", "蓝牙"], parent_title="设置")
    assert phone.keys == [(0x08, 0x2F)]
    assert phone.taps == [(25, 82)]

@pytest.mark.smoke
def test_return_one_level_falls_back_to_top_left_when_back_ocr_missing(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    ticks = iter([0.0, 1.0, 4.0, 4.0, 4.0])
    monkeypatch.setattr(walkthrough.time, "monotonic", lambda: next(ticks))
    child = _scene(
        _el("静音模式", 154, 300, w=80),
        _el("为通话和提醒切换静音和响铃。", 90, 360, w=280),
    )
    parent = _scene(
        _el("设置", 198, 78, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
    )
    phone = _TopLeftBackFallbackPhone(child, parent)

    assert _return_one_level(
        phone,
        parent_texts=["设置", "无线局域网", "蓝牙"],
        parent_title="设置",
        parent_is_root=True,
    )
    assert phone.keys == [(0x08, 0x2F)]
    assert phone.taps == [(24, 82)]


@pytest.mark.smoke
def test_return_one_level_falls_back_to_ipad_detail_pane_back_point(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    ticks = iter([0.0, 1.0, 4.0, 4.0, 4.0])
    monkeypatch.setattr(walkthrough.time, "monotonic", lambda: next(ticks))
    child = _scene(
        _el("Siri", 420, 78, w=42),
        _el("Allow Safari to Access", 316, 160, w=180),
    )
    parent = _scene(
        _el("Safari", 420, 78, w=56),
        _el("Default Browser App", 340, 360, w=150),
    )

    class IPadTopLeftBackFallbackPhone(_TopLeftBackFallbackPhone):
        device_geometry = SimpleNamespace(model="ipad_mini_7")

        def _viewport_size(self):
            return 640, 989

    phone = IPadTopLeftBackFallbackPhone(child, parent)

    assert _return_one_level(
        phone,
        parent_texts=["Safari", "Default Browser App"],
        parent_title="Safari",
        parent_is_root=False,
    )
    assert phone.keys == [(0x08, 0x2F)]
    assert phone.taps == [(305, 84)]


@pytest.mark.smoke
def test_return_one_level_treats_unknown_back_shortcut_as_fallbackable(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    ticks = iter([0.0, 1.0, 4.0, 4.0, 4.0])
    monkeypatch.setattr(walkthrough.time, "monotonic", lambda: next(ticks))
    child = _scene(
        _el("静音模式", 154, 300, w=80),
        _el("为通话和提醒切换静音和响铃。", 90, 360, w=280),
    )
    parent = _scene(
        _el("设置", 198, 78, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
    )

    class UnknownBackPhone(_TopLeftBackFallbackPhone):
        def key(self, modifier, keycode):
            self.keys.append((modifier, keycode))
            return ActionResult(
                ok=True,
                backend="fake",
                connected=True,
                semantic_status="unknown",
                semantic_reason="no scene or frame progress detected",
            )

    phone = UnknownBackPhone(child, parent)

    assert _return_one_level(
        phone,
        parent_texts=["设置", "无线局域网", "蓝牙"],
        parent_title="设置",
        parent_is_root=True,
    )
    assert phone.keys == [(0x08, 0x2F)]
    assert phone.taps == [(24, 82)]

@pytest.mark.smoke
def test_return_one_level_uses_picokvm_back_gesture(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(walkthrough.time, "monotonic", lambda: next(ticks))
    child = _scene(
        _el("无线局域网", 40, 236, w=108, h=26, ty="button"),
        _el("接入无线局域网、查看可用网络，并管理加入网", 40, 268, w=360),
        _el("kacier", 58, 398, w=52),
        _el("我的网络", 38, 462, w=72),
        _el("其他网络", 38, 576, w=70),
    )
    parent = _scene(
        _el("设置", 198, 78, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
    )

    class PicoKVMBackPhone:
        def __init__(self):
            self.scene = child
            self.keys: list[tuple[int, int]] = []
            self.back_gestures = 0

        def _effector_backend(self):
            return "picokvm"

        def perceive(self):
            return self.scene

        def key(self, modifier, keycode):
            self.keys.append((modifier, keycode))
            return ActionResult(ok=True, backend="picokvm", connected=True)

        def back_gesture(self):
            self.back_gestures += 1
            self.scene = parent
            return ActionResult(ok=True, backend="picokvm", connected=True)

        def invalidate_perceive_cache(self):
            pass

    phone = PicoKVMBackPhone()

    assert _return_one_level(phone, parent_texts=["设置", "无线局域网", "蓝牙"], parent_title="设置")
    assert phone.back_gestures == 1
    assert phone.keys == []

@pytest.mark.smoke
def test_return_one_level_falls_back_when_picokvm_back_gesture_is_unsupported(monkeypatch):
    monkeypatch.setattr(walkthrough.time, "sleep", lambda _: None)
    ticks = iter([0.0, 1.0, 4.0, 4.0, 4.0])
    monkeypatch.setattr(walkthrough.time, "monotonic", lambda: next(ticks))
    child = _scene(
        _el("电池", 198, 78, w=48),
        _el("低电量模式", 78, 360, w=86),
        _el("电池健康与充电", 78, 424, w=126),
    )
    parent = _scene(
        _el("设置", 198, 78, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
    )

    class UnsupportedPicoKVMBackPhone(_TopLeftBackFallbackPhone):
        def __init__(self):
            super().__init__(child, parent)
            self.back_gestures = 0

        def _effector_backend(self):
            return "picokvm"

        def back_gesture(self):
            self.back_gestures += 1
            raise RuntimeError("back_gesture failed: unsupported action")

    phone = UnsupportedPicoKVMBackPhone()

    assert _return_one_level(
        phone,
        parent_texts=["设置", "无线局域网", "蓝牙"],
        parent_title="设置",
        parent_is_root=True,
    )
    assert phone.back_gestures == 1
    assert phone.keys == []
    assert phone.taps == [(24, 82)]
