from __future__ import annotations

import json
from pathlib import Path

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.ios.scene import apply_ios_classification, classify_ios_scene
from glassbox.ipados.scene import classify_ipados_scene

_GOLDEN_IOS_SCENE_DIR = Path(__file__).parents[1] / "golden" / "ios_scene" / "drill_aftersim"


def _el(text: str, x: int, y: int, w: int = 80, h: int = 20, *, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


def _scene_from_ocr_fixture(name: str) -> Scene:
    payload = json.loads((_GOLDEN_IOS_SCENE_DIR / name).read_text(encoding="utf-8"))
    elements = []
    for raw in payload["elements"]:
        x, y, w, h = raw["box"]
        elements.append(
            UIElement(
                type=raw.get("type") or "text",
                box=Box(x=x, y=y, w=w, h=h),
                text=raw.get("text"),
                confidence=float(raw.get("confidence", 1.0)),
            )
        )
    return Scene(frame_id=0, timestamp=0.0, elements=elements)


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("fixture_name", "expected_title"),
    [
        ("view_0002.ocr.json", "WLAN"),
        ("view_0007.ocr.json", "Bluetooth"),
        ("view_0012.ocr.json", "Silent Mode"),
        ("view_0025.ocr.json", "Face ID & Passcode"),
        ("view_0029.ocr.json", "Privacy & Security"),
    ],
)
def test_ios_scene_classifier_real_drill_detail_fixtures(fixture_name: str, expected_title: str):
    scene = _scene_from_ocr_fixture(fixture_name)

    classified = classify_ios_scene(scene)

    assert classified.kind == "settings_detail"
    assert classified.title == expected_title
    assert "back" in classified.safe_actions
    assert "semantic_settings_detail" in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_settings_root():
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_root"
    assert "tap_root_row" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_english_root_with_statusbar_clock_typed_nav_back():
    # Regression: the status-bar clock is sometimes OCR-typed as `nav_back` at
    # the top-left (its text is noisy, e.g. "3:50C" / "3:516"). It must not be
    # treated as a Back affordance and disqualify the (English) Settings root —
    # a real Back button lives in the nav bar below the status bar.
    scene = _scene(
        _el("3:516", 85, 36, w=44, ty="nav_back"),  # status-bar clock, mis-typed
        _el("Settings", 120, 147, w=110, ty="button"),
        _el("Bluetooth", 80, 434, w=80),
        _el("Battery", 80, 593, w=70, ty="button"),
        _el("General", 80, 734, w=70, ty="button"),
        _el("Accessibility", 80, 788, w=110),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 982))

    assert classified.kind == "settings_root"


@pytest.mark.smoke
def test_apply_ios_classification_projects_metadata_to_scene():
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )

    classified = apply_ios_classification(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_root"
    assert scene.scene_type == "settings_root"
    assert scene.platform_scene_kind == "settings_root"
    assert scene.page_id == "settings/root"
    assert "scroll" in scene.safe_actions
    assert scene.classification_source == "ios"
    assert scene.classification_confidence == pytest.approx(0.92)
    assert "root_markers" in scene.classification_evidence


@pytest.mark.smoke
def test_apply_ios_classification_preserves_existing_scene_type_by_default():
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("蓝牙", 80, 424, w=40),
        _el("通用", 80, 725, w=40),
    )
    scene.scene_type = "vlm_settings"

    apply_ios_classification(scene, viewport_size=(448, 973))

    assert scene.scene_type == "vlm_settings"
    assert scene.platform_scene_kind == "settings_root"
    assert scene.page_id == "settings/root"


@pytest.mark.smoke
def test_ios_scene_classifier_settings_root_accepts_siri_marker():
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("Siri", 80, 370, w=42),
        _el("通用", 80, 725, w=40),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_root"


@pytest.mark.smoke
def test_ios_scene_classifier_harness_console_is_not_settings():
    """GlassboxHelper(glassbox 自己的控制台)不能被误判成 settings_detail。"""
    scene = _scene(
        _el("服务", 80, 96, w=48),
        _el("服务有问题", 150, 200, w=160),
        _el("停止服务", 96, 290, w=120, ty="button"),
        _el("Mac 大脑", 120, 380, w=110),
        _el("最近活动", 90, 470, w=90),
        _el("暂无命令", 130, 520, w=110),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "harness_console"
    # 只允许 home 退出,绝不能 tap —— 否则可能点停自己的服务
    assert classified.safe_actions == ("home",)
    assert "tap_root_row" not in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_single_console_token_does_not_trip():
    """单个偶发 console 词不足以判定 —— 需 ≥2 个 GlassboxHelper 专有 marker。"""
    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("无线局域网", 80, 370, w=86),
        _el("最近活动", 80, 500, w=90),
        _el("通用", 80, 725, w=40),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_root"


@pytest.mark.smoke
def test_ios_scene_classifier_settings_search_results():
    scene = _scene(
        _el("通知", 76, 126, w=40, ty="button"),
        _el("通知～显示预览", 78, 244, w=130),
        _el("通用", 76, 320, w=40, ty="button"),
        _el("通用～关于本机", 78, 344, w=130),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_search_results"
    assert "tap_root_result" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_system_search_is_not_settings_search():
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("通用", 56, 212, w=36, ty="button"),
        _el("最近1", 18, 410, w=46),
        _el("隐私与安全性", 56, 708, w=104),
        _el("Q", 48, 912, w=16),
        _el("搜索", 68, 910, w=42),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "system_search"
    assert "home" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_today_widget_home_with_spotlight_is_springboard():
    # Regression (live HK-English device): the Today/widget home (weather widget
    # + app-label grid + bottom "Q Search" Spotlight pill) was mis-classified as
    # `settings_detail` (grouped-control false-positive), which broke SpringBoard
    # detection and the crawl's home() grounding. The bottom Spotlight pill marks
    # it as Home, not a Settings detail page.
    def _c(text, cx, cy, w=70, h=20, ty="text"):  # center-based placement
        return _el(text, cx - w // 2, cy - h // 2, w=w, h=h, ty=ty)

    scene = _scene(
        _c("Shanghai", 92, 130), _c("23°", 88, 161), _c("SUNDAY", 286, 130),
        _c("No Events Today", 323, 222, w=150), _c("H:27°L:23°", 95, 258, w=90),
        _c("Weather", 124, 294), _c("Calendar", 329, 294),
        _c("FaceTime", 73, 405), _c("Photos", 276, 405), _c("Camera", 380, 404),
        _c("Notes", 73, 516), _c("Clock", 175, 516), _c("App Store", 379, 516),
        _c("Wallet", 74, 626), _c("Settings", 176, 627), _c("RustDesk", 277, 626),
        _c("Q Search", 227, 798, w=90),
    )

    assert classify_ios_scene(scene, viewport_size=(452, 988)).kind == "springboard"


@pytest.mark.smoke
def test_ios_scene_classifier_weather_widget_home_is_springboard():
    scene = _scene(
        _el("上海市", 52, 118, w=52),
        _el("21°", 52, 144, w=64, h=36),
        _el("多云", 52, 212, w=32),
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

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "springboard"


@pytest.mark.smoke
def test_ios_scene_classifier_app_paywall_is_unknown_not_springboard():
    # A foreign app's in-app-purchase paywall (real OCR from a drifted-into
    # RemoteAC "Premium" screen). Feature bullets + plan cards + a device mockup
    # trip the SpringBoard icon-grid heuristic; misreading it as Home is a safety
    # bug — bootstrap would "tap the Settings icon" and could hit Continue /
    # Subscribe, triggering a purchase. The commerce tokens must route it to
    # unknown so recovery backs out instead of tapping content.
    scene = _scene(
        _el("AC Remote Control", 165, 145, w=120),
        _el("22.5°", 212, 245, w=40),
        _el("Tap Continue to Access your", 118, 378, w=210),
        _el("Premium AC Remote", 130, 408, w=190),
        _el("All control modes", 62, 510, w=110),
        _el("Timers & Schedules", 74, 545, w=120),
        _el("Smart Mode", 65, 615, w=90),
        _el("No ads", 49, 650, w=60),
        _el("3-day free trial", 172, 700, w=100),
        _el("$6.99/week", 184, 722, w=80),
        _el("$29.99/year", 178, 780, w=90),
        _el("Continue", 183, 862, w=80),
        _el("Terms of Use", 46, 916, w=80),
        _el("Privacy Policy", 179, 918, w=90),
        _el("Restore", 337, 916, w=50),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 992))

    assert classified.kind == "unknown"
    assert "purchase_paywall" in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_single_commerce_word_is_not_paywall():
    # Guard the >=2-signal rule so a real Settings-ish surface that merely
    # mentions one commerce-adjacent word is never vetoed as a paywall.
    from glassbox.ios.scene import _looks_like_purchase_paywall

    scene = _scene(
        _el("设置", 198, 72, w=48),
        _el("通用", 80, 300, w=42),
        _el("隐私与安全性", 80, 360, w=120),
        _el("Restore", 80, 420, w=50),
    )

    assert _looks_like_purchase_paywall(scene, viewport_size=(448, 973)) is False


@pytest.mark.smoke
def test_ios_scene_classifier_today_search_with_siri_suggestions_is_system_search():
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

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "system_search"


@pytest.mark.smoke
def test_ios_scene_classifier_typed_spotlight_results_are_system_search():
    scene = _scene(
        _el("最佳搜索结果", 18, 76, w=94, ty="button"),
        _el("设置", 60, 194, w=28),
        _el("建议", 18, 252, w=34),
        _el("settings", 58, 300, w=70, ty="button"),
        _el("在App中搜索", 18, 836, w=96),
        _el("Q settings", 48, 902, w=96, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "system_search"
    assert "open_app" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_settings_detail_without_back_ocr():
    scene = _scene(
        _el("音频与视觉", 180, 78, w=110),
        _el("使左右扬声器播放同一内容。", 42, 132, w=220),
        _el("始终显示音量控制", 70, 190, w=140, ty="button"),
        _el("在锁定屏幕上显示耳机和内建扬声器的音量控制。", 42, 234, w=330),
        _el("添加语音突显", 70, 294, w=110, ty="button"),
        _el("将分离人声添加为突显对话的额外选项。", 42, 338, w=330),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions
    assert classified.title != "编辑"


def _generic_body_marker_scene(*, learn_more: bool = False):
    """A screen that trips _looks_like_settings_detail_body via locale-generic
    body words only (允许/访问/账户/App) — i.e. the third-party-app FP shape."""
    els = [
        _el("允许此 App 在使用期间访问你的账户以同步内容与设置项目数据", 42, 200, w=330),
        _el("允许", 60, 260, w=80, ty="button"),
        _el("访问", 60, 320, w=80, ty="button"),
        _el("账户", 60, 380, w=80, ty="button"),
        _el("管理", 60, 440, w=80, ty="button"),
    ]
    if learn_more:
        els.append(_el("进一步了解", 60, 500, w=120))
    return _scene(*els)


@pytest.mark.smoke
def test_strict_settings_detail_rejects_third_party_generic_body():
    """CUQ-2.6: a screen carrying only locale-generic body words classifies as
    settings_detail by default, but NOT under strict_settings_detail (no
    Settings-distinguishing signal present)."""
    scene = _generic_body_marker_scene()
    vp = (448, 973)

    # Default: the generic body matcher accepts it (the documented FP).
    assert classify_ios_scene(scene, viewport_size=vp).kind == "settings_detail"
    # Strict: rejected -> not a settings_detail false-positive.
    assert classify_ios_scene(
        scene, viewport_size=vp, strict_settings_detail=True
    ).kind != "settings_detail"


@pytest.mark.smoke
def test_strict_settings_detail_keeps_real_settings_with_learn_more():
    """CUQ-2.6: a real Settings detail page (same body words + a Learn-More
    footnote) still classifies as settings_detail under strict — no recall loss
    for pages carrying a Settings-distinguishing signal."""
    scene = _generic_body_marker_scene(learn_more=True)
    assert classify_ios_scene(
        scene, viewport_size=(448, 973), strict_settings_detail=True
    ).kind == "settings_detail"


@pytest.mark.smoke
def test_ios_scene_classifier_wifi_detail_without_nav_ocr_is_not_springboard():
    scene = _scene(
        _el("编辑", 374, 84, w=36, h=18, ty="button"),
        _el("无线局域网", 40, 236, w=108, h=26, ty="button"),
        _el("接入无线局域网、查看可用网络，并管理加入网", 40, 268, w=360, h=22),
        _el("络及附近热点设置。进一步了解…", 38, 290, w=258, h=22),
        _el("无线局域网", 60, 344, w=86, h=18, ty="button"),
        _el("kacier", 58, 398, w=52, h=18),
        _el("我的网络", 38, 462, w=72, h=20),
        _el("kacier_iptv", 58, 509, w=90, h=24),
        _el("其他网络", 40, 576, w=68, h=18),
        _el("kacier_aiot", 58, 624, w=90, h=22),
        _el("minii_washer_r_91f0", 58, 732, w=162, h=22),
        _el("STB_DyJ8", 60, 788, w=84, h=21),
        _el("yunduo", 58, 841, w=62, h=19),
        _el("其他⋯..", 60, 894, w=54, h=20),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions
    assert classified.title != "编辑"


@pytest.mark.smoke
def test_ios_scene_classifier_software_update_detail_without_nav_ocr():
    scene = _scene(
        _el("软件更新", 186, 84, w=86, h=18, ty="button"),
        _el("自动更新", 42, 162, w=74, h=20, ty="button"),
        _el("打开＞", 352, 162, w=54, h=20),
        _el("iOS已是最新版本", 156, 570, w=138, h=20, ty="button"),
        _el("IOS 26.5", 190, 598, w=74, h=18),
        _el("更多详细信息", 178, 636, w=92, h=18),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_iphone_storage_detail_without_nav_ocr():
    scene = _scene(
        _el("iPhone储存空间", 172, 84, w=110, h=18, ty="button"),
        _el("iPhone", 44, 178, w=52, h=18),
        _el("已使用27.43 GB/512 GB", 258, 178, w=156, h=18),
        _el("484.57 GB", 196, 210, w=74, h=18),
        _el("应用程序 iOS •系统数据", 100, 236, w=176, h=18),
        _el("推荐", 42, 292, w=36, h=18),
        _el("卸载未使用的App", 80, 346, w=138, h=20, ty="button"),
        _el("大小", 352, 490, w=36, h=18),
        _el("库乐队", 80, 546, w=54, h=20, ty="button"),
        _el("1.76 GB", 342, 546, w=58, h=18),
        _el("iMovie 剪辑", 80, 600, w=92, h=20, ty="button"),
        _el("673.4 MB", 336, 600, w=68, h=18),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_grouped_settings_control_page_is_not_springboard():
    scene = _scene(
        _el("18:29", 78, 41, w=72, ty="status_bar"),
        _el("甩池", 198, 84, w=48, h=18, ty="button"),
        _el("100%", 58, 172, w=58, h=20, ty="button"),
        _el("已充满电", 58, 206, w=74, h=18),
        _el("每日用量", 42, 288, w=72, h=18),
        _el("随着iPhone的使用，用量和对比分析将在此处显示。", 42, 332, w=340, h=20),
        _el("完整分析可能需要几天时间才能显示。", 42, 354, w=280, h=20, ty="button"),
        _el("平均", 38, 396, w=36, h=18),
        _el("今天", 98, 396, w=36, h=18),
        _el("查看所有电池用量", 42, 612, w=126, h=20, ty="button"),
        _el("电池健康", 42, 702, w=72, h=20, ty="button"),
        _el("充电", 42, 756, w=36, h=20, ty="button"),
        _el("电量模式", 42, 810, w=72, h=20, ty="button"),
        _el("电池百分比", 42, 864, w=88, h=20, ty="button"),
        _el("正常＞", 352, 702, w=58, h=18),
        _el("自适应＞", 338, 810, w=72, h=18),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_screen_time_detail_without_nav_ocr():
    scene = _scene(
        _el("iPhone", 198, 84, w=52, h=18),
        _el("每周", 112, 150, w=38, h=18),
        _el("屏幕时间", 44, 210, w=76, h=20),
        _el("5月21日今天", 64, 258, w=104, h=18),
        _el("18小时8分钟", 92, 286, w=112, h=22, ty="button"),
        _el("信息与阅读", 50, 596, w=88, h=18),
        _el("38分钟", 46, 618, w=58, h=18),
        _el("更新于：今天 18:11", 58, 648, w=152, h=18),
        _el("最常使用", 42, 690, w=78, h=18),
        _el("设置", 80, 726, w=44, h=20, ty="button"),
        _el("每天", 300, 150, w=38, h=18),
        _el("12小时", 354, 364, w=62, h=18),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_screen_time_parent_without_nav_ocr():
    scene = _scene(
        _el("屏幕时间", 188, 84, w=74, h=18, ty="button"),
        _el("iPhone", 42, 156, w=52, h=18),
        _el("日均", 42, 200, w=36, h=18),
        _el("22小时35分钟", 96, 232, w=116, h=22, ty="button"),
        _el("查看所有App与网站活动", 62, 426, w=154, h=22, ty="button"),
        _el("更新于：今天18:11", 58, 468, w=144, h=18),
        _el("使用限制", 42, 506, w=72, h=18),
        _el("停用时间", 80, 542, w=76, h=20, ty="button"),
        _el("App限额", 80, 606, w=62, h=20, ty="button"),
        _el("始终允许", 80, 668, w=76, h=20, ty="button"),
        _el("屏幕距离", 80, 732, w=76, h=20, ty="button"),
        _el("通信安全", 80, 914, w=76, h=20, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_health_data_detail_without_nav_ocr():
    scene = _scene(
        _el("健康数据", 190, 84, w=74, h=18, ty="button"),
        _el("医疗详细信息", 42, 158, w=96, h=20),
        _el("健康详细信息", 42, 204, w=96, h=20, ty="button"),
        _el("医疗急救卡", 42, 258, w=82, h=20, ty="button"),
        _el("数据", 42, 324, w=36, h=18),
        _el("数据访问与设备", 42, 370, w=114, h=20, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_back_button_alone_is_not_settings_detail():
    scene = _scene(
        _el("返回", 28, 72, w=38, ty="nav_back"),
        _el("登录", 196, 78, w=54),
        _el("邮箱", 42, 180, w=40, ty="input"),
        _el("密码", 42, 240, w=40, ty="input"),
        _el("继续", 198, 320, w=50, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind != "settings_detail"


@pytest.mark.smoke
def test_ios_scene_classifier_settings_app_list_is_not_springboard():
    scene = _scene(
        _el("默认App", 80, 116, w=70),
        _el("管理 iPhone上的默认 App", 82, 140, w=170),
        _el("A", 40, 200, w=14),
        _el("Al办公", 80, 246, w=54),
        _el("App Store", 80, 300, w=80),
        _el("启用听写？", 90, 360, w=82, ty="button"),
        _el("使用你的声音在可键入的位置听写文", 90, 388, w=244),
        _el("电话", 80, 688, w=36, ty="button"),
        _el("Q", 48, 910, w=18, ty="tab_bar_item"),
        _el("搜索App", 68, 910, w=76, ty="tab_bar_item"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ipados_scene_classifier_weather_settings_search_detail_is_not_springboard():
    scene = _scene(
        _el("4 Search 5:32PM Tue 26 May", 16, 10, w=170, h=18, ty="status_bar"),
        _el("Weather", 34, 88, w=72),
        _el("Weather", 72, 142, w=58),
        _el("Apps", 72, 176, w=34),
        _el("Weather Conditions", 72, 210, w=144),
        _el("Apps → Weather", 72, 278, w=118),
        _el("<", 276, 46, w=14, h=18),
        _el("Weather", 420, 44, w=70),
        _el("Allow Weather to Access", 300, 108, w=172),
        _el("Location", 320, 154, w=64),
        _el("While Using >", 500, 154, w=98),
        _el("Siri", 320, 206, w=30),
        _el("Search", 320, 250, w=54),
        _el("Preferred Language", 344, 306, w=138),
        _el("Temperature Unit", 344, 416, w=130),
        _el("Choose how temperature should be displayed in the Weather", 344, 540, w=260),
    )
    scene.viewport_size = (640, 989)

    classified = classify_ipados_scene(scene)

    assert classified.kind == "settings_search_results"
    assert classified.title == "Weather"
    assert "ipad_settings_top_search" in classified.evidence
    assert any(item.startswith("settings_search_path_hints:") for item in classified.evidence)


@pytest.mark.smoke
def test_ios_scene_classifier_scrolled_app_settings_detail_without_nav_ocr():
    scene = _scene(
        _el("通讯录", 40, 230, w=66, h=24, ty="button"),
        _el("添加或移除账户、管理“Siri与搜索”", 38, 256, w=277, h=31),
        _el("联系人的显示方式。进一步了解⋯", 40, 284, w=262, h=24),
        _el("通讯录账户", 38, 336, w=86, ty="button"),
        _el("允许“通讯录”访问", 40, 402, w=144),
        _el("Siri", 80, 448, w=26),
        _el("搜索", 80, 502, w=36, ty="button"),
        _el("共享姓名和照片", 40, 590, w=120, ty="button"),
        _el("关闭＞", 352, 590, w=56),
        _el("选择姓名和照片以及谁可以看到你共享的内容，来个性化信息。", 38, 634, w=366),
        _el("提供商", 38, 692, w=56, ty="button"),
        _el("显示联系人照片", 40, 784, w=120, ty="button"),
        _el("排列顺序", 38, 838, w=72, ty="button"),
        _el("显示顺序", 38, 891, w=72, ty="button"),
        _el("短名称", 38, 946, w=54, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_privacy_list_is_not_settings_search_results():
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

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_detail"
    assert "back" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_game_center_onboarding_is_blocked():
    scene = _scene(
        _el("退出登录", 38, 106, w=72, ty="button"),
        _el("欢迎来到 Game Center", 80, 310, w=170, ty="button"),
        _el("继续", 200, 912, w=50, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_blocked_safety"
    assert classified.safe_actions == ("record_blocked",)


@pytest.mark.smoke
def test_ios_scene_classifier_app_library():
    scene = _scene(
        _el("Q App资源库", 88, 112, w=140),
        _el("AI办公", 92, 198, w=60),
        _el("App Store", 94, 272, w=82),
        _el("GlassboxHelper", 94, 790, w=78),
        _el("取消", 370, 112, w=42),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "app_library"
    assert "open_app" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_app_library_category_grid_without_title():
    scene = _scene(
        _el("pp资", 196, 86, w=54),
        _el("社交", 72, 168, w=46),
        _el("其他", 292, 168, w=46),
        _el("效率与財务", 92, 486, w=104),
        _el("TestFlight", 112, 548, w=92),
        _el("创意", 292, 486, w=46),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "app_library"
