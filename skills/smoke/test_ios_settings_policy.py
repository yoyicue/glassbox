from __future__ import annotations

from pathlib import Path

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.config import get_config
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY, IPadSettingsPolicy

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


def _ipad_split_scene() -> Scene:
    return Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            _el("设置", 48, 72, w=72, h=28),
            _el("无线局域网", 72, 220, w=96, h=24),
            _el("蓝牙", 72, 276, w=44, h=24),
            _el("通用", 72, 332, w=44, h=24),
            _el("通用", 418, 76, w=70, h=28),
            _el("关于本机", 384, 180, w=86, h=24),
            _el("›", 700, 180, w=12, h=24),
            _el("软件更新", 384, 236, w=86, h=24),
            _el("›", 700, 236, w=12, h=24),
            _el("iPad 储存空间", 384, 292, w=150, h=24),
            _el("›", 700, 292, w=12, h=24),
        ],
    )


FOREGROUNDING_CODE = [
    REPO_ROOT / "glassbox" / "ios" / "springboard.py",
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "core.py",
    REPO_ROOT / "skills" / "regression" / "ios_settings" / "bootstrap.py",
]


@pytest.mark.smoke
def test_ipad_settings_policy_treats_split_view_sidebar_as_root_navigation():
    policy = IPadSettingsPolicy()
    scene = _ipad_split_scene()

    assert policy.scene_is_settings_root(scene) is True
    assert policy.scene_kind(scene) == "settings_detail"
    assert policy.page_title(scene) == "通用"

    candidates = policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    labels = [(candidate.text or "").strip() for candidate in candidates]

    assert labels == ["无线局域网", "蓝牙", "通用"]


@pytest.mark.smoke
def test_ipad_settings_policy_uses_detail_pane_for_child_navigation():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            *_ipad_split_scene().elements,
            _el("通用", 384, 132, w=70, h=24, ty="button"),
            _el("General", 384, 160, w=70, h=24, ty="button"),
        ],
    )

    candidates = policy.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )
    labels = [(candidate.text or "").strip() for candidate in candidates]

    assert labels == ["关于本机", "软件更新", "iPad 储存空间"]


@pytest.mark.smoke
def test_ipad_detail_unknown_child_requires_right_pane_affordance():
    policy = IPadSettingsPolicy()
    scene_without_chevron = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            _el("设置", 48, 72, w=72, h=28),
            _el("通用", 72, 332, w=44, h=24),
            _el("通用", 418, 76, w=70, h=28),
            _el("Advanced Sync", 384, 180, w=128, h=24),
        ],
    )
    scene_with_chevron = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            *scene_without_chevron.elements,
            _el("›", 700, 180, w=12, h=24),
        ],
    )

    assert policy.safe_navigation_candidates(
        scene_without_chevron,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    ) == []
    assert [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene_with_chevron,
            allow_sensitive_root_labels=False,
            allow_known_without_affordance=False,
        )
    ] == ["Advanced Sync"]


@pytest.mark.smoke
def test_ipad_settings_policy_allows_screen_time_rows_without_chevron_ocr():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("Battery", 72, 167, w=76, h=16),
            _el("Screen Time", 72, 335, w=92, h=16),
            _el("Accessibility", 72, 368, w=112, h=16),
            _el("Daily Average", 300, 34, w=88, h=16),
            _el("47h 19m", 302, 60, w=78, h=22),
            _el("© 19% from last week", 482, 65, w=146, h=16),
            _el("Limit Usage", 300, 318, w=88, h=18),
            _el("Downtime", 318, 348, w=76, h=18),
            _el("Schedule time away from the screen", 320, 369, w=216, h=14),
            _el("App Limits", 320, 403, w=78, h=18),
            _el("Set time limits for apps", 320, 422, w=138, h=12),
            _el("Always Allowed", 330, 456, w=112, h=18),
            _el("Choose apps to allow at all times", 330, 475, w=196, h=14),
        ],
    )

    candidates = policy.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )

    assert [candidate.text for candidate in candidates] == ["Downtime", "App Limits", "Always Allowed"]


@pytest.mark.smoke
def test_ipad_settings_policy_blocks_dynamic_wlan_child_rows():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("WLAN", 70, 328, w=44, h=16),
            _el("WLAN", 280, 188, w=44, h=18),
            _el("Connect to WLAN, view available networks,", 280, 216, w=300, h=14),
            _el("Networks", 280, 360, w=80, h=14),
            _el("kacier_aiot", 318, 402, w=100, h=14),
            _el("Other...", 318, 520, w=72, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(scene) == "dynamic Wi-Fi rows"
    assert policy.safe_navigation_candidates(scene) == []


@pytest.mark.smoke
def test_ipad_settings_policy_blocks_passcode_biometric_rows():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("Touch ID & Passcode", 70, 328, w=136, h=16),
            _el("Touch ID & Passcode", 280, 188, w=164, h=22),
            _el("Use Touch ID For", 280, 260, w=120, h=14),
            _el("iPad Unlock", 318, 300, w=90, h=14),
            _el("Fingerprints", 280, 520, w=92, h=14),
            _el("Turn Passcode On", 318, 620, w=130, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(scene) == "passcode and biometric settings"
    assert policy.safe_navigation_candidates(scene) == []


@pytest.mark.smoke
def test_ipad_settings_policy_blocks_game_center_onboarding_children():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("Game Center", 70, 328, w=92, h=16),
            _el("Game Center", 410, 44, w=92, h=16),
            _el("Welcome to Game Center", 300, 180, w=190, h=20),
            _el("Continue", 440, 720, w=70, h=18),
        ],
    )

    assert policy.blocked_child_navigation_reason(scene) == "game center onboarding requires action"
    assert policy.safe_navigation_candidates(scene) == []


@pytest.mark.smoke
def test_ipad_settings_policy_blocks_app_permission_access_children():
    policy = IPadSettingsPolicy()
    weather = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("Weather", 420, 44, w=62, h=12),
            _el("Allow Weather to Access", 280, 106, w=170, h=12),
            _el("Location", 314, 142, w=58, h=12),
            _el("Siri", 314, 186, w=24, h=16),
            _el("Search", 314, 230, w=48, h=16),
        ],
    )
    location = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Location", 418, 42, w=64, h=17),
            _el("Allow Location Access", 280, 104, w=154, h=14),
            _el("Never", 280, 142, w=42, h=12),
            _el("While Using the App", 280, 230, w=130, h=12),
            _el("Always", 280, 318, w=50, h=12),
            _el("Precise Location", 280, 430, w=120, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(weather) == "app permission/access selector rows"
    assert policy.safe_navigation_candidates(weather) == []
    assert policy.blocked_child_navigation_reason(location) == "app permission/access selector rows"
    assert policy.safe_navigation_candidates(location) == []


@pytest.mark.smoke
def test_ipad_detail_child_accepts_trailing_value_disclosure_affordance():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Settings", 48, 72, w=72, h=28),
            _el("Accessibility", 72, 332, w=112, h=24),
            _el("VoiceOver", 316, 338, w=68, h=12),
            _el("Off >", 572, 336, w=38, h=14),
            _el("Zoom", 314, 382, w=40, h=14),
            _el("Off >", 572, 382, w=38, h=14),
            _el("Physical and Motor", 280, 665, w=134, h=16),
        ],
    )

    candidates = policy.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )

    assert [(candidate.text or "").strip() for candidate in candidates] == ["VoiceOver", "Zoom"]


@pytest.mark.smoke
def test_ipad_detail_child_accepts_exact_safe_known_label_without_chevron():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Settings", 48, 72, w=72, h=28),
            _el("General", 72, 332, w=72),
            _el("General", 422, 44, w=52, h=17, ty="button"),
            _el("Manage your overall setup and preferences for", 280, 206, w=306, h=16),
            _el("About", 280, 300, w=52, h=16),
            _el("Software Update", 280, 344, w=112, h=16),
            _el("Advanced Sync", 280, 388, w=128, h=16),
        ],
    )

    candidates = policy.safe_navigation_candidates(
        scene,
        allow_sensitive_root_labels=False,
        allow_known_without_affordance=False,
    )

    assert [(candidate.text or "").strip() for candidate in candidates] == ["About", "Software Update"]


@pytest.mark.smoke
def test_ipad_battery_selector_root_allows_disclosure_child_not_chart_value():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 48, 90, w=72),
            _el("Battery", 72, 332, w=72),
            _el("Battery", 422, 44, w=52, h=17, ty="button"),
            _el("100%", 278, 110, w=72, h=30, ty="button"),
            _el("Battery Percentage", 280, 426, w=128, h=16),
            _el("Battery Health", 280, 583, w=96, h=16),
            _el("Normal >", 544, 583, w=66, h=15),
            _el("Low Power Mode", 280, 673, w=114, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(scene) is None
    assert [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=False,
            allow_known_without_affordance=False,
        )
    ] == ["Battery Health"]


@pytest.mark.smoke
def test_ipad_notifications_selector_root_allows_disclosure_children():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 48, 90, w=72),
            _el("Notifications", 72, 332, w=112),
            _el("Notifications", 404, 44, w=90, h=14),
            _el("Display As", 280, 106, w=74, h=16),
            _el("Count", 308, 226, w=34, h=10),
            _el("Scheduled Summary", 280, 320, w=138, h=14),
            _el("Off >", 572, 320, w=38, h=12),
            _el("Show Previews", 280, 366, w=100, h=12),
            _el("Always >", 546, 365, w=64, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(scene) is None
    assert [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=False,
            allow_known_without_affordance=False,
        )
    ] == ["Scheduled Summary", "Show Previews"]


@pytest.mark.smoke
def test_ipad_split_view_only_uses_right_pane_visible_back():
    policy = IPadSettingsPolicy()
    root_detail = _ipad_split_scene()
    child_detail = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            *root_detail.elements,
            _el("<", 350, 76, w=14, h=24),
            _el("Fonts", 418, 76, w=56, h=28),
        ],
    )
    boundary_back_child = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Settings", 48, 62, w=72, h=28),
            _el("WLAN", 66, 214, w=54, h=13),
            _el("Bluetooth", 66, 252, w=74, h=13),
            _el("General", 66, 475, w=54, h=13),
            _el("Legal & Regulatory", 384, 44, w=130, h=14),
            _el("<", 276, 42, w=16, h=20),
            _el("iPad", 280, 88, w=36, h=16),
        ],
    )
    sidebar_back_noise = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            *root_detail.elements,
            _el("<", 26, 76, w=14, h=24),
        ],
    )

    assert policy.find_visible_back(root_detail) is None
    assert policy.find_visible_back(child_detail).box.x == 350
    assert policy.find_visible_back(boundary_back_child).box.x == 276
    assert policy.find_visible_back(sidebar_back_noise) is None


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
def test_extra_top_level_pages_are_safe_known_not_unknown_candidates():
    # Some top-level read-only pages lack a reliably-detected disclosure chevron,
    # so without an explicit safe-known decision they were rejected as
    # unknown_navigation_label at root and blocked inventory sampling. They are
    # safe to enter and observe; a genuinely unknown row must still reject.
    for label in (
        "Camera", "Wallpaper", "相机", "墙纸",
        "Control Centre", "Control Center", "控制中心",
        "Display & Brightness", "显示与亮度",
        "Multitasking & Gestures", "多任务与手势",
        "Apple Pencil",
        "Home Screen & App Library", "Home Screen &", "App Library",
        "主屏幕与 App 资源库", "App 资源库",
        "Safari", "Safari浏览器", "FaceTime", "FaceTime 通话",
        "Apps", "Game Center", "Weather", "Books", "Translate",
    ):
        assert DEFAULT_SETTINGS_POLICY.is_safe_known_navigation_label(label), label
    assert DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("App")
    assert not DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Apps")
    assert not DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Game Center")
    assert not DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Weather")
    assert not DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Books")
    assert not DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Translate")
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("Camera", 80, 500, w=70),
        _el("Wallpaper", 80, 560, w=90),
        _el("Control Centre", 80, 620, w=110),
        _el("Display & Brightness", 80, 680, w=150),
        _el("Multitasking & Gestures", 80, 740, w=170),
        _el("Apple Pencil", 80, 800, w=96),
        _el("Home Screen &", 80, 815, w=120),
        _el("App Library", 80, 835, w=92),
        _el("Apps", 80, 855, w=60),
        _el("Game Center", 80, 865, w=90),
        _el("Weather", 80, 875, w=70, h=8),
        _el("Books", 80, 882, w=50, h=8),
        _el("Translate", 80, 889, w=72, h=8),
        _el("Frobnicate", 80, 896, w=90, h=8),
    )
    rejected = DEFAULT_SETTINGS_POLICY.rejected_candidate_rows(
        scene,
        allow_sensitive_root_labels=True,
        allow_known_without_affordance=True,
    )
    # Known inventory pages are no longer rejected; only the unknown sentinel remains.
    assert [(item.text, item.reason) for item in rejected] == [
        ("Frobnicate", "unknown_navigation_label"),
    ]


@pytest.mark.smoke
def test_ipad_sidebar_search_page_does_not_match_top_search_field():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 112, w=72),
            _el("Camera", 66, 620, w=52),
            _el("Search", 66, 820, w=58),
        ],
    )

    labels = [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=True,
            allow_known_without_affordance=True,
        )
    ]

    assert labels == ["Camera"]


@pytest.mark.smoke
def test_ipad_empty_top_search_panel_is_not_root_sidebar():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 88, w=72, h=21),
            _el("Suggestions", 40, 134, w=64, h=12),
            _el("Siri", 66, 192, w=26, h=16),
            _el("Recents", 40, 302, w=42, h=10),
            _el("Weather", 68, 328, w=58, h=12),
            _el("Apps", 70, 362, w=34, h=14),
            _el("<", 276, 42, w=14, h=18),
            _el("Weather", 420, 44, w=62, h=12),
            _el("Allow Weather to Access", 280, 106, w=170, h=12),
        ],
    )

    assert policy.is_settings_search_scene(scene)
    assert not policy.scene_is_settings_root(scene)
    assert not policy.settings_search_has_query_text(scene)


@pytest.mark.smoke
def test_ipad_top_search_query_does_not_steal_detail_title():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search Apps", 434, 42, w=106, h=16),
            _el("Q Search", 36, 87, w=70, h=15),
            _el("Apple Account, iCloud", 64, 134, w=150, h=12),
            _el("WLAN", 66, 192, w=46, h=16),
            _el("Bluetooth", 66, 226, w=72, h=16),
            _el("General", 66, 260, w=58, h=16),
            _el("Apps", 268, 44, w=36, h=14),
            _el("Default Apps", 320, 122, w=84, h=14),
            _el("Manage default apps on iPad", 318, 142, w=144, h=10),
        ],
    )

    assert policy.page_title(scene) == "Apps"


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


@pytest.mark.smoke
def test_ipad_settings_policy_uses_sidebar_top_search_field():
    policy = IPadSettingsPolicy()
    root = _scene(
        _el("Q Search", 34, 90, w=72),
        _el("Camera", 66, 118, w=52),
        _el("Notifications", 66, 494, w=84),
        _el("Notifications", 404, 44, w=90),
    )
    search = _scene(
        _el("Siri", 54, 92, w=26, ty="nav_back"),
        _el("Select", 34, 134, w=42),
        _el("AutoFill", 182, 134, w=48),
        _el("1 Notifications", 72, 160, w=104, ty="button"),
        _el("Notifications", 72, 318, w=68),
        _el("Notifications", 404, 44, w=90),
    )

    assert policy.find_root_search_tab(root).text == "Q Search"
    assert policy.find_search_result(root, "通知") is None
    assert not policy.is_settings_search_scene(root)
    assert policy.is_settings_search_scene(search)
    assert not policy.scene_is_settings_root(search)
    assert policy.settings_search_has_query_text(search)
    assert policy.find_search_field(search).text == "Siri"
    assert policy.find_search_result(search, "通知").text == "1 Notifications"


@pytest.mark.smoke
def test_ipad_settings_policy_does_not_treat_top_query_as_search_result():
    policy = IPadSettingsPolicy()
    search = _scene(
        _el("Paste", 34, 134, w=42),
        _el("MobileService", 62, 92, w=112),
        _el("Select", 82, 134, w=44),
        _el("Select All", 134, 134, w=72),
        _el('No Results for "MobileService"', 56, 176, w=230),
        _el("Check the spelling or try a", 56, 218, w=230),
        _el("Bluetooth", 424, 44, w=84),
    )

    assert policy.is_settings_search_scene(search)
    assert policy.find_search_field(search).text == "MobileService"
    assert policy.find_search_result(search, "蜂窝网络") is None


@pytest.mark.smoke
def test_ipad_settings_policy_prefers_exact_root_search_result_over_alias(monkeypatch):
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    get_config.cache_clear()
    policy = IPadSettingsPolicy()
    try:
        search = _scene(
            _el("Sounds", 54, 92, w=64),
            _el("Sounds", 72, 184, w=64, ty="button"),
            _el("Sounds & Haptics", 72, 232, w=132, ty="button"),
            _el("Background Sounds", 72, 280, w=140, ty="button"),
        )

        assert policy.find_search_result(search, "声音与触感").text == "Sounds & Haptics"
    finally:
        get_config.cache_clear()


@pytest.mark.smoke
def test_ipad_settings_policy_taps_primary_line_for_compact_screen_time_result(monkeypatch):
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    get_config.cache_clear()
    policy = IPadSettingsPolicy()
    try:
        search = _scene(
            _el("Screen", 54, 92, w=64),
            _el("ScreenTime 6", 58, 112, w=88),
            _el("Screen Time", 72, 148, w=84),
            _el("Home Screen &", 72, 190, w=104),
            _el("Screen Distance", 72, 404, w=110),
            _el("Screen Time", 72, 420, w=68),
        )

        assert policy.find_search_result(search, "屏幕使用时间").box.y == 420
    finally:
        get_config.cache_clear()


@pytest.mark.smoke
def test_ipad_settings_policy_prefers_split_query_text_over_q_placeholder():
    policy = IPadSettingsPolicy()
    search = _scene(
        _el("Accessibility", 404, 44, w=86),
        _el("Q", 34, 90, w=14),
        _el("ActionButton", 72, 92, w=104),
        _el("Paste", 34, 134, w=42),
        _el("Select", 82, 134, w=44),
        _el("Select All", 134, 134, w=72),
    )

    assert policy.is_settings_search_scene(search)
    assert policy.settings_search_has_query_text(search)
    assert policy.find_search_field(search).text == "ActionButton"


@pytest.mark.smoke
def test_ipad_settings_policy_does_not_treat_home_widget_title_as_top_search_query():
    policy = IPadSettingsPolicy()
    home = _scene(
        _el("11:08PM Mon 25 May", 14, 10, w=130),
        _el("12", 136, 104, w=12, h=10),
        _el("10", 108, 116, w=12, h=10),
        _el("Notes", 220, 94, w=56, h=10),
        _el("No Notes", 218, 130, w=46, h=10),
        _el("Settings", 358, 769, w=46, h=12),
    )
    home.platform_scene_kind = "springboard"

    assert policy.find_search_field(home) is None
    assert not policy.is_settings_search_scene(home)
    assert not policy.settings_search_has_query_text(home)


@pytest.mark.smoke
def test_settings_policy_uses_english_root_search_queries_for_english_locale(monkeypatch):
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    get_config.cache_clear()
    try:
        policy = IPadSettingsPolicy()

        assert policy.root_search_query("无线局域网") == "WLAN"
        assert policy.root_search_query("电池") == "Battery"
        assert policy.root_search_query("屏幕使用时间") == "Screen"
        assert policy.root_search_query("Face ID与密码") == "Passcode"
        assert policy.root_search_query("隐私与安全性") == "Privacy"
        assert policy.root_search_query("Safari") == "Safari"
        assert policy.root_search_query("FaceTime") == "FaceTime"
        assert policy.root_search_query("Apps") == "Apps"
        assert policy.root_search_query("Game Center") == "Game Center"
        assert policy.root_search_query("Weather") == "Weather"
        assert policy.root_search_query("Books") == "Books"
        assert policy.root_search_query("Translate") == "Translate"
        assert policy.root_search_query("Home Screen & App Library") == "Home Screen"
        assert policy.canonical_expected_root_label("Sounds") == "声音与触感"
        assert policy.canonical_expected_root_label("All Devices") == "屏幕使用时间"
        assert policy.canonical_expected_root_label("Touch ID & Passcode") == "Face ID与密码"
    finally:
        get_config.cache_clear()


@pytest.mark.smoke
def test_ipad_settings_policy_can_pick_settings_app_from_spotlight_overlay():
    policy = IPadSettingsPolicy()
    scene = _scene(
        _el("Settings", 116, 94, w=84),
        _el("Open", 212, 90, w=48, ty="button"),
        _el("Top Hit", 84, 140, w=52),
        _el("Settings", 112, 226, w=58),
        _el("Suggestions", 84, 276, w=86),
        _el("Search in App", 460, 360, w=92),
    )

    result = policy.find_system_search_root_result(scene, viewport_size=(644, 982))

    assert result is not None
    target, label = result
    assert target.text == "Open"
    assert label == "Settings"
