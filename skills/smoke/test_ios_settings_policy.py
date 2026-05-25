from __future__ import annotations

from pathlib import Path

import pytest

from glassbox.cognition import Box, Scene, UIElement
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

REPO_ROOT = Path(__file__).resolve().parents[2]
IOS_SETTINGS_CODE = [
    REPO_ROOT / "glassbox" / "ios" / "springboard.py",
    *sorted((REPO_ROOT / "skills" / "regression" / "ios_settings").glob("*.py")),
    *sorted((REPO_ROOT / "device transport" / "ios_agent" / "GlassboxHelper" / "GlassboxHelper").glob("*.swift")),
]
POLICY_CODE = REPO_ROOT / "skills" / "regression" / "ios_settings" / "policy.py"
POLICY_CONSUMERS = [
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "diagnose.py",
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "run_full.py",
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "verify_report.py",
]


def _el(text: str, x: int, y: int, w: int = 90, h: int = 24, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


FOREGROUNDING_CODE = [
    REPO_ROOT / "glassbox" / "ios" / "springboard.py",
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "core.py",
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "bootstrap.py",
]


@pytest.mark.smoke
def test_ios_settings_crawler_does_not_use_settings_urls_or_host_activation():
    forbidden = [
        "App-" + "Prefs",
        "prefs" + ":",
        "Prefs" + ":",
        "settings" + "://",
        "com.apple." + "Preferences",
        "UIApplication.shared.open",
        "canOpenURL",
        "LSApplicationWorkspace",
        "prefs" + ":root",
        "open" + "URL",
        "open" + "url",
        "sim" + "ctl",
        "process " + "launch",
    ]

    offenders: list[str] = []
    for path in IOS_SETTINGS_CODE:
        text = path.read_text(encoding="utf-8").lower()
        for needle in forbidden:
            if needle.lower() in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {needle!r}")

    assert offenders == []


@pytest.mark.smoke
def test_ios_settings_foregrounding_code_does_not_call_host_device_launchers():
    forbidden = [
        "xcrun",
        "devicectl",
        "simctl",
        "pymobiledevice3",
        "tidevice",
        "ios-deploy",
        "mobiledevice",
        "mobile_installation_proxy",
        "subprocess",
        "os.system",
        "popen",
        "process " + "launch",
    ]

    offenders: list[str] = []
    for path in FOREGROUNDING_CODE:
        text = path.read_text(encoding="utf-8").lower()
        for needle in forbidden:
            if needle.lower() in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {needle!r}")

    assert offenders == []


@pytest.mark.smoke
def test_ios_settings_foregrounding_entrypoint_uses_springboard_helper():
    core = (
        REPO_ROOT / "skills" / "regression" / "ios_settings" / "core.py"
    ).read_text(encoding="utf-8")
    bootstrap = (
        REPO_ROOT / "skills" / "regression" / "ios_settings" / "bootstrap.py"
    ).read_text(encoding="utf-8")
    springboard = (REPO_ROOT / "glassbox" / "ios" / "springboard.py").read_text(encoding="utf-8")

    assert "from glassbox.ios.springboard import open_app_from_springboard" in core
    assert "actions.open_app_from_springboard(phone, actions.root_title" in bootstrap
    assert "phone.home()" in springboard
    assert "phone.swipe_right()" in springboard
    assert "phone.swipe_left()" in springboard
    assert "phone.tap_xy(*icon.tap_point)" in springboard


@pytest.mark.smoke
def test_ios_settings_policy_is_decision_only():
    text = POLICY_CODE.read_text(encoding="utf-8")
    forbidden = [
        "test_readonly_walkthrough",
        "pytest",
        "time.sleep",
        "phone.",
        ".tap_xy(",
        ".key(",
        ".home(",
        "subprocess",
    ]

    offenders = [needle for needle in forbidden if needle in text]

    assert offenders == []


@pytest.mark.smoke
def test_ios_settings_rule_consumers_do_not_import_walkthrough():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in POLICY_CONSUMERS
        if "test_readonly_walkthrough import" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


@pytest.mark.smoke
def test_ios_settings_child_audit_does_not_import_walkthrough_private_api():
    text = (
        REPO_ROOT / "skills" / "regression" / "ios_settings" / "child_audit.py"
    ).read_text(encoding="utf-8")

    assert "test_readonly_walkthrough" not in text
    assert "walkthrough._" not in text


@pytest.mark.smoke
def test_ios_settings_crawler_does_not_import_pytest_walkthrough_private_api():
    text = (
        REPO_ROOT / "skills" / "regression" / "ios_settings" / "crawler.py"
    ).read_text(encoding="utf-8")

    assert "test_readonly_walkthrough" not in text
    assert "walkthrough._" not in text


@pytest.mark.smoke
def test_ios_settings_policy_owns_labels_candidates_and_blocked_pages():
    scene = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("无线局域网", 170, 78, w=96),
        _el("我的网络", 70, 420, w=72),
        _el("kacier", 80, 480, w=52),
        _el("其他网络", 70, 560, w=72),
    )

    assert DEFAULT_SETTINGS_POLICY.canonical_expected_root_label("待机見示") == "待机显示"
    assert DEFAULT_SETTINGS_POLICY.blocked_child_navigation_reason(scene) == "dynamic Wi-Fi rows"
    assert DEFAULT_SETTINGS_POLICY.safe_navigation_candidates(scene) == []
    assert DEFAULT_SETTINGS_POLICY.find_visible_back(scene).text == "<"
    assert DEFAULT_SETTINGS_POLICY.visible_root_row_label(_el("蓝牙", 70, 420, w=40)) == "蓝牙"
    assert DEFAULT_SETTINGS_POLICY.should_recover_root_row_ocr(_el("甩沲", 70, 420, w=40))


@pytest.mark.smoke
def test_ios_settings_policy_filters_short_ocr_noise_from_navigation_rows():
    assert DEFAULT_SETTINGS_POLICY.potential_navigation_row_text(_el("（②", 70, 420, w=40)) is None
    assert DEFAULT_SETTINGS_POLICY.potential_navigation_row_text(_el("O）", 70, 420, w=40)) is None


@pytest.mark.smoke
def test_camera_and_wallpaper_are_safe_known_not_unknown_candidates():
    # Top-level read-only pages (Camera / Wallpaper) lack a reliably-detected
    # disclosure chevron, so without an explicit safe-known decision they were
    # rejected as unknown_navigation_label at root and blocked the verifier. They
    # are safe to enter and observe; a genuinely unknown row must still reject.
    for label in ("Camera", "Wallpaper", "相机", "墙纸"):
        assert DEFAULT_SETTINGS_POLICY.is_safe_known_navigation_label(label), label
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("Camera", 80, 500, w=70),
        _el("Wallpaper", 80, 560, w=90),
        _el("Frobnicate", 80, 620, w=90),
    )
    rejected = DEFAULT_SETTINGS_POLICY.rejected_candidate_rows(
        scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
    )
    # Camera/Wallpaper are no longer rejected; only the unknown sentinel remains.
    assert [(item.text, item.reason) for item in rejected] == [
        ("Frobnicate", "unknown_navigation_label"),
    ]


@pytest.mark.smoke
def test_ios_settings_policy_counts_wallet_root_but_does_not_navigate_it():
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("钱包与ApplePay", 80, 420, w=130),
        _el("›", 386, 420, w=12),
    )

    assert DEFAULT_SETTINGS_POLICY.visible_root_row_label(scene.elements[1]) == "钱包与 Apple Pay"
    assert DEFAULT_SETTINGS_POLICY.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
    ) == []
    rejected = DEFAULT_SETTINGS_POLICY.rejected_candidate_rows(
        scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
    )
    assert [(item.text, item.reason) for item in rejected] == [("钱包与ApplePay", "unsafe_text")]


@pytest.mark.smoke
def test_ios_settings_policy_owns_scene_detail_and_back_fallback_decisions():
    detail = _scene(
        _el("Game Center", 178, 78, w=110),
        _el("邀请朋友", 80, 160, w=72),
        _el("共享朋友列表", 80, 250, w=110, ty="button"),
        _el("允许 App访问你的Game Center朋友列表，改进游戏体验。", 32, 292, w=360),
        _el("是否对他人可见", 80, 328, w=126),
        _el("帮助朋友找到你", 80, 376, w=124, ty="button"),
        _el("使用 Apple账户关联的电子邮件地址和电话号码，让Game", 32, 420, w=360),
    )
    blocked = _scene(
        _el("<", 18, 72, w=14, ty="nav_back"),
        _el("无线局域网", 170, 78, w=96),
        _el("我的网络", 70, 420, w=72),
        _el("其他网络", 70, 560, w=72),
    )

    assert DEFAULT_SETTINGS_POLICY.scene_looks_like_settings_detail(detail)
    assert DEFAULT_SETTINGS_POLICY.is_safe_top_left_back_fallback_scene(detail)
    assert not DEFAULT_SETTINGS_POLICY.is_safe_top_left_back_fallback_scene(blocked)


@pytest.mark.smoke
def test_ios_settings_policy_owns_settings_search_scene_decisions():
    search_results = _scene(
        _el("通知", 76, 126, w=40, ty="button"),
        _el("显示通知", 78, 180, w=68, ty="button"),
        _el("待机显示", 76, 198, w=54),
        _el("通知样式", 78, 244, w=72, ty="button"),
        _el("通知", 76, 262, w=40),
        _el("耳机通知", 78, 496, w=72, ty="button"),
        _el("辅助功能～音频与视觉", 78, 514, w=160),
    )
    app_search = _scene(
        _el("默认 App", 80, 118, w=70),
        _el("App Store", 80, 301, w=80),
        _el("Q", 48, 911, w=18, ty="tab_bar_item"),
        _el("搜索 App", 74, 910, w=72, ty="tab_bar_item"),
        _el("X", 384, 911, w=20, ty="tab_bar_item"),
    )
    query = _scene(_el("通知", 78, 126, w=36), _el("Q Tongzhi", 46, 908, w=94))

    assert DEFAULT_SETTINGS_POLICY.is_settings_search_scene(search_results)
    assert DEFAULT_SETTINGS_POLICY.looks_like_settings_search_results(search_results)
    assert not DEFAULT_SETTINGS_POLICY.is_settings_search_scene(app_search)
    assert DEFAULT_SETTINGS_POLICY.settings_search_has_query_text(query)


@pytest.mark.smoke
def test_settings_privacy_list_is_not_settings_search_results():
    scene = _scene(
        _el("18:51C", 32, 28, w=46, h=18, ty="status_bar"),
        _el("隐私与安全性", 118, 124, w=120, h=28),
        _el("控制哪些App和服务可以访问你的信息。", 146, 154, w=250, h=22),
        _el("定位服务", 80, 224, w=72, ty="button"),
        _el("4个使用期间可访问", 318, 224, w=132),
        _el("跟踪", 80, 280, w=36, ty="button"),
        _el("◎>", 382, 280, w=28),
        _el("日历", 80, 337, w=36, ty="button"),
        _el("无", 346, 337, w=18),
        _el("通讯录", 80, 392, w=54, ty="button"),
        _el("文件与文件夹", 80, 448, w=108, ty="button"),
        _el("专注模式", 80, 503, w=72, ty="button"),
        _el("健康数据", 80, 559, w=72, ty="button"),
        _el("家庭", 80, 615, w=36, ty="button"),
        _el("1个App", 346, 615, w=54),
        _el("媒体与 Apple Music", 116, 672, w=152, ty="button"),
    )

    assert DEFAULT_SETTINGS_POLICY.scene_kind(scene, viewport_size=(448, 973)) == "settings_detail"
    assert not DEFAULT_SETTINGS_POLICY.is_settings_search_scene(scene, viewport_size=(448, 973))


@pytest.mark.smoke
def test_ios_settings_policy_ignores_symbol_prefixed_short_ocr_fragments():
    fragment = _el("$OS", 72, 420, w=46)

    assert DEFAULT_SETTINGS_POLICY.potential_navigation_row_text(fragment) is None


@pytest.mark.smoke
def test_ios_settings_policy_owns_settings_search_element_selection():
    root = _scene(_el("设置", 198, 72, w=48), _el("Q 搜索", 198, 900, w=54))
    search = _scene(
        _el("Q通知", 46, 906, w=68),
        _el("×", 382, 910, w=24, ty="button"),
        _el("设置", 300, 929, w=22, h=10, ty="tab_bar_item"),
        _el("搜索", 126, 929, w=22, h=10, ty="tab_bar_item"),
    )
    system_search = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("通用", 56, 212, w=36, ty="button"),
        _el("面容ID与密码", 58, 710, w=106, ty="button"),
        _el("Q 搜索", 48, 912, w=62),
    )

    assert DEFAULT_SETTINGS_POLICY.find_root_search_tab(root).text == "Q 搜索"
    assert DEFAULT_SETTINGS_POLICY.find_search_field(search).text == "Q通知"
    assert DEFAULT_SETTINGS_POLICY.find_search_clear_button(search).text == "×"
    assert DEFAULT_SETTINGS_POLICY.find_settings_tab_in_search(search).text == "设置"
    assert DEFAULT_SETTINGS_POLICY.find_system_search_root_result(system_search)[1] == "通用"
