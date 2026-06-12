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
def test_ipad_settings_policy_rejects_screen_time_duration_metrics_as_child_rows():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Search", 58, 89, w=48, h=15),
            _el("Screen Time", 406, 44, w=88, h=14),
            _el("All Devices", 282, 103, w=76, h=15),
            _el("Daily Average", 282, 142, w=90, h=14),
            _el("55h 56m", 280, 162, w=118, h=26, ty="button"),
            _el("29h", 586, 240, w=24, h=10),
            _el("See All App & WebsiteActivity", 280, 332, w=202, h=14),
            _el("Limit Usage", 278, 428, w=86, h=16),
            _el("Downtime", 320, 457, w=66, h=12),
            _el("Schedule time away from the screen", 318, 478, w=216, h=12),
            _el("App Limits", 316, 509, w=74, h=17),
            _el("Set time limits for apps", 318, 529, w=138, h=14),
            _el("Always Allowed", 318, 563, w=102, h=14),
            _el("Choose apps to allow at all times", 318, 583, w=196, h=12),
        ],
    )

    labels = [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=False,
            allow_known_without_affordance=False,
        )
    ]

    assert "55h 56m" not in labels
    assert "29h" not in labels
    assert labels[:2] == ["Downtime", "App Limits"]


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

    assert [candidate.text for candidate in candidates] == ["Downtime", "App Limits"]


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
            _el("homenet_aiot", 318, 402, w=100, h=14),
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
    camera = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("Camera", 420, 44, w=62, h=12),
            _el("Photos and videos taken with the camera may contain other", 280, 106, w=320, h=12),
            _el("Apps that have requested access to the camera will", 280, 160, w=320, h=12),
            _el("appear here.", 280, 180, w=86, h=12),
            _el("App Clips", 314, 230, w=72, h=16),
        ],
    )
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

    assert policy.blocked_child_navigation_reason(camera) == "app permission/access selector rows"
    assert policy.safe_navigation_candidates(camera) == []
    assert policy.blocked_child_navigation_reason(weather) == "app permission/access selector rows"
    assert policy.safe_navigation_candidates(weather) == []
    assert policy.blocked_child_navigation_reason(location) == "app permission/access selector rows"
    assert policy.safe_navigation_candidates(location) == []


@pytest.mark.smoke
def test_ipad_settings_policy_blocks_settings_native_layout_customization_pages():
    policy = IPadSettingsPolicy()
    control_centre = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Control Centre", 420, 44, w=112, h=16),
            _el("Customise Control Centre", 280, 130, w=176, h=14),
            _el("Access Within Apps", 280, 310, w=136, h=14),
            _el("Reset Control Centre", 280, 430, w=140, h=14),
        ],
    )
    wallpaper = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Wallpaper", 420, 44, w=84, h=16),
            _el("CURRENT", 310, 116, w=66, h=12),
            _el("Customise", 300, 260, w=74, h=14),
            _el("+Add New Wallpaper", 300, 540, w=150, h=14),
            _el("Lock Screen", 300, 650, w=90, h=14),
        ],
    )
    home_screen = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Home Screen & App Library", 360, 44, w=200, h=16),
            _el("Use Large App Icons", 300, 170, w=142, h=14),
            _el("Newly Downloaded Apps", 300, 260, w=172, h=14),
            _el("Add to Home Screen", 320, 310, w=140, h=14),
            _el("App Library Only", 320, 360, w=122, h=14),
        ],
    )
    multitasking = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Multitasking & Gestures", 360, 44, w=190, h=16),
            _el("Full-Screen Apps", 300, 120, w=130, h=14),
            _el("Windowed Apps", 300, 260, w=118, h=14),
            _el("Stage Manager", 300, 400, w=116, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(control_centre) == "control centre customization/reset rows"
    assert policy.safe_navigation_candidates(control_centre) == []
    assert policy.blocked_child_navigation_reason(wallpaper) == "wallpaper customization rows"
    assert policy.safe_navigation_candidates(wallpaper) == []
    assert policy.blocked_child_navigation_reason(home_screen) == "home screen layout selector rows"
    assert policy.safe_navigation_candidates(home_screen) == []
    assert policy.blocked_child_navigation_reason(multitasking) == "multitasking layout selector rows"
    assert policy.safe_navigation_candidates(multitasking) == []


@pytest.mark.smoke
def test_ipad_blocked_reason_ignores_sidebar_marker_collisions():
    policy = IPadSettingsPolicy()
    apps = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("WLAN", 70, 214, w=44, h=16),
            _el("homenet", 70, 242, w=50, h=12),
            _el("Notifications", 70, 330, w=92, h=16),
            _el("Sounds", 70, 360, w=52, h=16),
            _el("Apps", 268, 44, w=42, h=16),
            _el("Detault Apps", 314, 120, w=84, h=14),
            _el("Manage default apps on iPad", 314, 146, w=190, h=12),
            _el("App Store", 314, 250, w=76, h=14),
            _el("Books", 314, 290, w=46, h=14),
            _el("Calculator", 314, 330, w=76, h=14),
        ],
    )
    game_center = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("WLAN", 70, 214, w=44, h=16),
            _el("homenet", 70, 242, w=50, h=12),
            _el("Bluetooth", 70, 292, w=70, h=16),
            _el("Game Center", 268, 44, w=96, h=16),
            _el("Customize Profile", 314, 180, w=128, h=14),
            _el("Friends", 314, 260, w=58, h=14),
            _el("Friend Requests", 314, 300, w=118, h=14),
            _el("Invite Friends", 314, 340, w=100, h=14),
            _el("Share Friends List", 314, 390, w=132, h=14),
        ],
    )
    benign = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 34, 90, w=72, h=18),
            _el("WLAN", 70, 214, w=44, h=16),
            _el("homenet", 70, 242, w=50, h=12),
            _el("Notifications", 70, 330, w=92, h=16),
            _el("Sounds", 70, 360, w=52, h=16),
            _el("Example", 420, 44, w=72, h=16),
            _el("Read Only", 314, 180, w=80, h=14),
        ],
    )

    assert policy.blocked_child_navigation_reason(apps) == "dynamic app list rows"
    assert policy.blocked_child_navigation_reason(game_center) == "game center profile/social rows"
    assert policy.blocked_child_navigation_reason(benign) is None


@pytest.mark.smoke
def test_ipad_split_view_detail_root_can_still_be_blocked():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Settings", 48, 62, w=72, h=28),
            _el("WLAN", 70, 214, w=44, h=16),
            _el("Bluetooth", 70, 252, w=70, h=16),
            _el("General", 70, 292, w=58, h=16),
            _el("Accessibility", 70, 332, w=96, h=16),
            _el("Apps", 420, 44, w=42, h=16),
            _el("Detault Apps", 314, 120, w=84, h=14),
            _el("Manage default apps on iPad", 314, 146, w=190, h=12),
            _el("App Store", 314, 250, w=76, h=14),
            _el("Books", 314, 290, w=46, h=14),
            _el("Calculator", 314, 330, w=76, h=14),
        ],
    )

    assert policy.classify_scene(scene).kind == "settings_detail"
    assert policy.scene_is_settings_root(scene) is True
    assert policy.blocked_child_navigation_reason(scene) == "dynamic app list rows"
    assert policy.safe_navigation_candidates(scene) == []
    root_candidates = policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    assert [candidate.text for candidate in root_candidates] == [
        "WLAN",
        "Bluetooth",
        "General",
        "Accessibility",
    ]


@pytest.mark.smoke
def test_settings_policy_rejects_applecare_warranty_child_navigation():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Settings", 48, 62, w=72, h=28),
            _el("General", 70, 292, w=58, h=16),
            _el("General", 420, 44, w=70, h=16),
            _el("About", 314, 300, w=42, h=14),
            _el("Software Update", 314, 344, w=130, h=14),
            _el("iPad Storage", 314, 388, w=104, h=14),
            _el("AppleCare & Warranty", 314, 432, w=168, h=14),
            _el("AirDrop", 314, 476, w=64, h=14),
        ],
    )

    assert policy.is_unsafe_navigation_text("AppleCare & Warranty")
    assert policy.is_unsafe_navigation_text("AirDrop")
    labels = [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=False,
            allow_known_without_affordance=False,
        )
    ]
    assert "AppleCare & Warranty" not in labels
    assert "AirDrop" not in labels
    assert labels == ["About", "Software Update"]


@pytest.mark.smoke
def test_settings_policy_rejects_always_allowed_app_list_navigation():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Screen Time", 70, 292, w=96, h=16),
            _el("Screen Time", 420, 44, w=96, h=16),
            _el("Downtime", 314, 300, w=76, h=14),
            _el("Schedule time away from the screen", 314, 320, w=220, h=12),
            _el("App Limits", 314, 370, w=78, h=14),
            _el("Set time limits for apps", 314, 390, w=170, h=12),
            _el("Always Allowed", 314, 440, w=116, h=14),
            _el("Choose apps to allow at all times", 314, 460, w=220, h=12),
        ],
    )

    assert policy.is_unsafe_navigation_text("Always Allowed")
    assert [
        (candidate.text or "").strip()
        for candidate in policy.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=False,
            allow_known_without_affordance=False,
        )
    ] == ["Downtime", "App Limits"]


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
            _el("Suggestions", 88, 142, w=86, h=14),
            _el("Recents", 82, 184, w=68, h=14),
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
def test_ipad_notifications_selector_root_allows_exact_safe_children_without_chevron_ocr():
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
            _el("Off", 572, 320, w=26, h=12),
            _el("Show Previews", 280, 366, w=100, h=12),
            _el("Always", 546, 365, w=52, h=14),
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
def test_ipad_siri_allow_notifications_row_does_not_block_page_as_notifications():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Search", 48, 90, w=72),
            _el("Notifications", 72, 332, w=112),
            _el("Siri", 404, 44, w=40, h=14),
            _el("Siri Requests", 280, 220, w=96, h=14),
            _el("Talk to Siri", 280, 260, w=82, h=14),
            _el("Off >", 572, 260, w=38, h=12),
            _el("Suggestions", 280, 410, w=82, h=14),
            _el("Allow Notifications", 280, 520, w=128, h=14),
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
    ] == ["Talk to Siri"]


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
        _el("homenet", 80, 480, w=52),
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
def test_ipad_search_root_accepts_search_and_look_up_detail_title():
    policy = IPadSettingsPolicy()

    assert policy.title_matches_navigation_label("Search and Look Up", "Search")


@pytest.mark.smoke
def test_ipad_sidebar_search_page_does_not_match_top_search_field():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Search", 34, 88, w=52),
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
def test_ipad_sidebar_drops_wrapped_app_library_tail_candidate():
    # iPad wraps "Home Screen & App Library" onto two sidebar lines. The trailing
    # "App Library" line is the same row as the leading "Home Screen &" line, not a
    # standalone navigable root; offering it as its own candidate taps dead space
    # and records a spurious tap_no_navigation. The row is reached via "Home Screen &".
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Home Screen &", 66, 360, w=118),
            # OCR reads the wrapped tail without the space; both forms must drop.
            _el("AppLibrary", 66, 382, w=90),
            _el("Camera", 66, 620, w=52),
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

    assert "Home Screen &" in labels
    assert "Camera" in labels
    assert "AppLibrary" not in labels
    assert "App Library" not in labels


@pytest.mark.smoke
def test_expected_blocked_reasons_includes_ipad_selector_reasons():
    # The verifier whitelist is derived from the iPad superset of blocked-child
    # markers, so iPad-only block reasons must be accepted; otherwise a legitimate
    # read-only skip of an iPad selector/customization/dynamic page fails verify.
    from skills.regression.ios_settings.reporting import EXPECTED_BLOCKED_REASONS

    for reason in (
        "control centre customization/reset rows",
        "home screen layout selector rows",
        "multitasking layout selector rows",
        "wallpaper customization rows",
        "game center profile/social rows",
        "dynamic app list rows",
    ):
        assert reason in EXPECTED_BLOCKED_REASONS, reason


@pytest.mark.smoke
def test_texts_support_blocked_reason_is_reason_specific_under_ipad_sidebar():
    # The iPad split view always shows the full sidebar, so the Notifications row
    # markers ("Sounds", "Alerts", …) are satisfied on every page. The blocked-page
    # evidence check must confirm the page's OWN reason, not the first marker that
    # happens to match the contaminating sidebar.
    from skills.regression.ios_settings.reporting import texts_support_blocked_reason

    home_screen_texts = [
        # sidebar (always visible) — includes Notifications + Sounds + Wallpaper
        "General", "Notifications", "Sounds", "Wallpaper", "Home Screen & App Library",
        # detail pane: the Home Screen layout selector rows
        "Home Screen & App Library", "Newly Downloaded Apps", "Add to Home Screen",
        "App Library Only", "Use Large App Icons",
    ]
    assert texts_support_blocked_reason(home_screen_texts, "home screen layout selector rows")
    # Sidebar-only evidence (the page name but none of its detail rows) must NOT
    # pass — the reason needs its own row evidence, not just the sidebar label.
    sidebar_only = ["General", "Notifications", "Sounds", "Wallpaper", "Home Screen & App Library"]
    assert not texts_support_blocked_reason(sidebar_only, "home screen layout selector rows")


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
def test_ipad_top_search_ignores_layout_grouped_account_row():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Apps", 268, 44, w=36, h=14),
            _el("Q Search Apps", 434, 42, w=106, h=16),
            _el("Jo Doe", 19, 28, w=222, h=130, ty="button"),
            _el("Q Search", 36, 90, w=70, h=14),
            _el("Apple Account, iCloud", 94, 108, w=526, h=66, ty="switch"),
            _el("WLAN", 25, 205, w=203, h=79, ty="button"),
            _el("Bluetooth", 22, 252, w=217, h=74, ty="button"),
        ],
    )

    field = policy.find_search_field(scene)

    assert field is not None
    assert field.text == "Q Search"
    assert not policy.settings_search_has_query_text(scene)


@pytest.mark.smoke
def test_ipad_sidebar_candidates_ignore_profile_band_owner_row():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Apps", 268, 44, w=36, h=14),
            _el("Q Search", 36, 90, w=70, h=14),
            _el("Jo Doe", 94, 142, w=44, h=16, ty="list_item"),
            _el("Apple Account, iCloud", 94, 108, w=526, h=66, ty="switch"),
            _el("Airplane Mode", 30, 126, w=207, h=112, ty="button"),
            _el("WLAN", 25, 205, w=203, h=79, ty="button"),
            _el("Bluetooth", 22, 252, w=217, h=74, ty="button"),
        ],
    )

    labels = [
        element.text
        for element in policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]

    assert "Jo Doe" not in labels
    assert "Apple Account, iCloud" not in labels
    assert "Airplane Mode" not in labels
    assert labels[:2] == ["WLAN", "Bluetooth"]


@pytest.mark.smoke
def test_ipad_sidebar_candidates_skip_status_text_and_optional_roots():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 36, 90, w=70, h=14),
            _el("WLAN", 35, 205, w=203, h=79, ty="button"),
            _el("homenet", 182, 270, w=44, h=14),
            _el("Bluetooth", 35, 252, w=217, h=74, ty="button"),
            _el("General", 35, 346, w=217, h=74, ty="button"),
            _el("Wallpaper", 35, 435, w=99, h=26, ty="list_item"),
            _el("Apps", 35, 916, w=67, h=25, ty="list_item"),
        ],
    )

    labels = [
        (element.text or "").strip()
        for element in policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]

    assert labels == ["WLAN", "Bluetooth", "General"]


@pytest.mark.smoke
def test_ipad_sidebar_candidates_ignore_cross_pane_layout_rows():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 36, 90, w=70, h=14),
            _el("Notifications", 18, 423, w=226, h=83, ty="button"),
            # Layout segmentation can merge a right-pane detail row with left
            # sidebar structure, giving it a center inside the sidebar even
            # though its box crosses into the detail pane.
            _el("Talk to Siri", 22, 298, w=328, h=44, ty="list_item"),
            _el("Siri Requests", 280, 282, w=92, h=14),
            _el("Siri", 280, 178, w=32, h=18, ty="button"),
        ],
    )

    labels = [
        (element.text or "").strip()
        for element in policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]

    assert labels == ["Notifications"]


@pytest.mark.smoke
def test_ipad_sidebar_candidates_skip_game_center_optional_social_root():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            _el("Q Search", 36, 90, w=70, h=14),
            _el("Privacy & Security", 18, 666, w=230, h=80, ty="button"),
            # Layout segmentation can promote the optional Game Center sidebar
            # row to a high-confidence button. It is account/social state, not a
            # required root for strict Settings coverage.
            _el("Game Center", 15, 710, w=229, h=86, ty="button"),
            _el("iCloud", 66, 826, w=44, h=14),
            _el("Apps", 66, 924, w=36, h=14),
        ],
    )

    labels = [
        (element.text or "").strip()
        for element in policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]

    assert "Privacy & Security" in labels
    assert "Game Center" not in labels


@pytest.mark.smoke
def test_ipad_sidebar_accepts_known_root_row_with_minor_right_overflow():
    policy = IPadSettingsPolicy()
    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(640, 989),
        page_id="settings/Screen Time",
        scene_type="settings_detail",
        elements=[
            _el("Screen Time", 406, 44, w=86, h=14),
            _el("Privacy & Security", 35, 720, w=271, h=27, ty="list_item"),
            _el("Content & Privacy Restrictions", 281, 872, w=237, h=29, ty="list_item"),
        ],
    )

    labels = [
        (element.text or "").strip()
        for element in policy.safe_navigation_candidates(scene, allow_sensitive_root_labels=True)
    ]

    assert "Privacy & Security" in labels
    assert "Content & Privacy Restrictions" not in labels


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
def test_ipad_settings_policy_scales_top_search_geometry_for_pixel_viewport():
    policy = IPadSettingsPolicy()
    root = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(1488, 2266),
        elements=[
            _el("Q Search", 68, 184, w=144, h=40),
            _el("Camera", 132, 236, w=104, h=40),
            _el("Notifications", 132, 988, w=168, h=40),
            _el("Notifications", 808, 88, w=180, h=40),
        ],
    )
    search = Scene(
        frame_id=0,
        timestamp=0.0,
        viewport_size=(1488, 2266),
        elements=[
            _el("Siri", 108, 184, w=52, h=40, ty="nav_back"),
            _el("Select", 68, 284, w=84, h=40),
            _el("1 Notifications", 144, 360, w=208, h=40, ty="button"),
        ],
    )

    assert policy.find_root_search_tab(root).text == "Q Search"
    assert policy.is_settings_search_scene(search)
    assert policy.find_search_field(search).text == "Siri"
    assert policy.find_search_result(search, "通知").text == "1 Notifications"


@pytest.mark.smoke
def test_default_settings_policy_resolves_ipad_variant_at_call_time(monkeypatch):
    monkeypatch.setenv("GLASSBOX_PHONE_MODEL", "ipad_mini_7")
    get_config.cache_clear()
    try:
        root = Scene(
            frame_id=0,
            timestamp=0.0,
            viewport_size=(1488, 2266),
            elements=[
                _el("Q Search", 68, 184, w=144, h=40),
                _el("Camera", 132, 236, w=104, h=40),
            ],
        )

        assert DEFAULT_SETTINGS_POLICY.find_root_search_tab(root).text == "Q Search"
    finally:
        get_config.cache_clear()


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


def _accessibility_search_scene():
    """iPad deep-search for "Accessibility": a pure root row PLUS many
    `Accessibility → Child` breadcrumbs above it (mirrors the live rig OCR)."""
    return _scene(
        _el("Q Accessibilityl", 54, 92, w=130),                       # search field
        _el("Accessibility → VoiceOver", 72, 150, w=150, ty="button"),  # breadcrumb (topmost)
        _el("Accessibility → Switch", 72, 204, w=118, ty="button"),     # breadcrumb
        _el("Accessibility →> Keyboards", 72, 256, w=140, ty="button"), # breadcrumb (OCR `→>`)
        _el("Accessibility", 72, 320, w=68, ty="button"),               # the real root row
    )


@pytest.mark.smoke
def test_ipad_search_breadcrumb_child_wins_when_flag_off(monkeypatch):
    """Documents the bug: with the flag OFF the breadcrumb ties the root at rank 0
    and the higher-on-screen breadcrumb wins (selection path byte-identical)."""
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    monkeypatch.delenv("GLASSBOX_SETTINGS_SEARCH_REJECT_BREADCRUMB_RESULT", raising=False)
    get_config.cache_clear()
    try:
        result = IPadSettingsPolicy().find_search_result(_accessibility_search_scene(), "辅助功能")
        assert result is not None
        assert "→" in result.text and result.text != "Accessibility"  # a child breadcrumb won
    finally:
        get_config.cache_clear()


@pytest.mark.smoke
def test_ipad_search_rejects_breadcrumb_and_picks_root_when_flag_on(monkeypatch):
    """Fix 3: with the flag ON the breadcrumbs are rejected and the genuine root
    row is selected, even though it is lower on screen than the breadcrumbs."""
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    monkeypatch.setenv("GLASSBOX_SETTINGS_SEARCH_REJECT_BREADCRUMB_RESULT", "1")
    get_config.cache_clear()
    try:
        result = IPadSettingsPolicy().find_search_result(_accessibility_search_scene(), "辅助功能")
        assert result is not None and result.text == "Accessibility"
    finally:
        get_config.cache_clear()


@pytest.mark.smoke
def test_ipad_search_breadcrumb_flag_keeps_normal_root_result(monkeypatch):
    """No-regression: a normal root search (no breadcrumbs) still resolves to the
    root with the flag ON — the guard only drops arrow-bearing crumbs."""
    monkeypatch.setenv("GLASSBOX_LANGUAGE", "en")
    monkeypatch.setenv("GLASSBOX_REGION", "HK")
    monkeypatch.setenv("GLASSBOX_SETTINGS_SEARCH_REJECT_BREADCRUMB_RESULT", "1")
    get_config.cache_clear()
    try:
        search = _scene(
            _el("Sounds", 54, 92, w=64),
            _el("Sounds", 72, 184, w=64, ty="button"),
            _el("Sounds & Haptics", 72, 232, w=132, ty="button"),
            _el("Background Sounds", 72, 280, w=140, ty="button"),
        )
        assert IPadSettingsPolicy().find_search_result(search, "声音与触感").text == "Sounds & Haptics"
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
        assert policy.root_search_query("Wi-Fi") == "WLAN"
        assert policy.root_search_query("General") == "General"
        assert policy.root_search_query("Sounds") == "Sounds"
        assert policy.root_search_query("电池") == "Battery"
        assert policy.root_search_query("屏幕使用时间") == "Screen"
        assert policy.root_search_query("Screen Time") == "Screen"
        assert policy.root_search_query("Face ID与密码") == "Passcode"
        assert policy.root_search_query("Touch ID & Passcode") == "Passcode"
        assert policy.root_search_query("隐私与安全性") == "Privacy"
        assert policy.root_search_query("Privacy & Security") == "Privacy"
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
        assert "WLAN" in policy.page_id_route_label_candidates("无线局域网")
        assert "Notifications" in policy.page_id_route_label_candidates("通知")
        assert "Touch ID & Passcode" in policy.page_id_route_label_candidates("Face ID与密码")
        assert "Home Screen & App Library" in policy.page_id_route_label_candidates("Home Screen &")
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


@pytest.mark.smoke
def test_settings_policy_blocks_apple_account_review_row_as_unsafe():
    """Apple-Account-review row en blocked-safety vocab (iphone_transition_n1,
    2026-06-12): the en root row "Review Apple Account phone number" anchors
    the auto-presented trusted-number safety sheet ("Is this still your phone
    number?"). The drill-down must never deliberately tap it — same family as
    the zh Apple-Account rows (Apple账户 / iCloud) already in the unsafe
    vocabulary."""
    assert DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Review Apple Account phone number")
    assert DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text(
        "Review Apple Account phone number", allow_sensitive_root_labels=True
    )
    # The banner sibling row stays covered by the existing iCloud entry.
    assert DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text("Apple Account, iCloud and more")

    scene = Scene(
        frame_id=0,
        timestamp=0.0,
        elements=[
            _el("Settings", 188, 80, w=70, ty="button"),
            _el("Review Apple Account phone number", 80, 250, w=300),
            _el("General", 80, 800, w=64),
        ],
    )
    rejected = {
        (item.text, item.reason)
        for item in DEFAULT_SETTINGS_POLICY.rejected_candidate_rows(
            scene,
            allow_sensitive_root_labels=True,
            allow_known_without_affordance=True,
        )
    }
    assert ("Review Apple Account phone number", "unsafe_text") in rejected
    labels = [
        (candidate.text or "").strip()
        for candidate in DEFAULT_SETTINGS_POLICY.safe_navigation_candidates(
            scene,
            allow_sensitive_root_labels=True,
            allow_known_without_affordance=True,
        )
    ]
    assert "Review Apple Account phone number" not in labels
