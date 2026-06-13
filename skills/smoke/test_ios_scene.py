from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from glassbox.action.context import ActionContext
from glassbox.action.semantic_plan import ExpectedState, verify_expected_state
from glassbox.cognition import Box, Scene, SceneClassificationPrior, UIElement
from glassbox.element_selector import ElementSelector
from glassbox.ios.app_store import annotate_app_store_search_intents
from glassbox.ios.recovery import should_foreground_target_app_instead_of_back
from glassbox.ios.scene import apply_ios_classification, classify_ios_scene
from glassbox.ipados.scene import classify_ipados_scene
from glassbox.perceptor import Perceptor

_GOLDEN_IOS_SCENE_ROOT = Path(__file__).parents[1] / "golden" / "ios_scene"
_GOLDEN_IOS_SCENE_DIR = _GOLDEN_IOS_SCENE_ROOT / "drill_aftersim"


def _el(text: str, x: int, y: int, w: int = 80, h: int = 20, *, ty: str = "text") -> UIElement:
    return UIElement(type=ty, box=Box(x=x, y=y, w=w, h=h), text=text, confidence=0.9)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(elements))


def _scene_from_ocr_fixture(name: str, *, root: Path = _GOLDEN_IOS_SCENE_DIR) -> Scene:
    payload = json.loads((root / name).read_text(encoding="utf-8"))
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
def test_ios_recovery_foregrounds_target_from_weather_surface():
    scene = _scene(
        _el("Q Search for a city or ai...0", 36, 94, w=188),
        _el("MY LOCATION", 408, 130, w=80),
        _el("Daxing", 401, 148, w=92),
        _el("34°", 402, 184, w=112),
        _el("Sunny conditions will continue for the rest of the day.", 292, 402, w=280),
        _el("10-DAY FORECAST", 294, 576, w=120),
        _el("Today", 290, 614, w=50),
        _el("Tue", 292, 662, w=32),
    )

    assert should_foreground_target_app_instead_of_back(scene, viewport_size=(640, 989))


@pytest.mark.smoke
def test_ios_scene_classifier_keeps_ipad_home_widget_as_springboard():
    scene = _scene(
        _el("12:32PM Mon 1 Jun", 14, 10, w=120),
        _el("No Events Today", 96, 268, w=118),
        _el("Daxing 7", 98, 370, w=66),
        _el("34°", 98, 394, w=80),
        _el("Sunny", 188, 420, w=48),
        _el("H:36° L:17°", 190, 450, w=88),
        _el("No Notes", 222, 132, w=70),
        _el("Home", 128, 650, w=44),
        _el("Camera", 246, 650, w=58),
        _el("App Store", 354, 650, w=78),
        _el("Settings", 354, 760, w=72),
        _el("Files", 500, 420, w=42),
        _el("Maps", 500, 540, w=42),
    )
    scene.platform_scene_kind = "springboard"

    classified = classify_ios_scene(scene, viewport_size=(640, 989))

    assert classified.kind == "springboard"
    assert "home_widget_surface" in classified.evidence


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("fixture_name", "expected_title"),
    [
        ("view_0002.ocr.json", "WLAN"),
        ("view_0007.ocr.json", "Bluetooth"),
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
def test_ios_scene_classifier_action_button_carousel_verifier_golden():
    """Post-floor residual fix #1 (docs/design/iphone_settings_transition.md §5).

    `view_0012.ocr.json` is the iOS 26 操作按钮 / Action Button carousel slide:
    its only body text is the centered slide caption "Silent Mode" plus the
    description copy. The body-band semantic guess used to mint
    `settings/Silent Mode`, which the row's expected-state any_of
    (`settings/操作按钮` / `settings/Action Button` / …) rejected, so the crawler
    treated the entered page as not-entered (iPhone floor residual, all 5 rounds
    of the post-#99 floor). The carousel detector now mints `settings/Action
    Button`, and the row verifies `succeeded`.
    """
    scene = _scene_from_ocr_fixture("view_0012.ocr.json")

    classified = classify_ios_scene(scene)

    assert classified.kind == "settings_detail"
    assert classified.title == "Action Button"
    assert classified.page_id == "settings/Action Button"
    assert "back" in classified.safe_actions
    assert "action_button_carousel" in classified.evidence

    # Verifier-golden: the recorded row any_of accepts the minted identity.
    expected = ExpectedState.from_dict(
        {
            "kind": "page_id",
            "payload": {
                "any_of": [
                    "settings/操作按钮",
                    "settings/Action Button",
                    "com.apple.settings.action-button",
                ]
            },
        }
    )
    outcome = verify_expected_state(expected, SimpleNamespace(page_id=classified.page_id))
    assert outcome.status == "succeeded", outcome.reason


@pytest.mark.smoke
def test_ios_scene_classifier_sounds_haptics_not_action_button():
    """Guard (a): a real Sounds & Haptics detail page (which lists a "Silent
    Mode" row under its visible nav title) must NOT be reclassified as the
    Action Button carousel — it has many rows and a nav-band title, so the
    sparse/no-rows/no-nav-title veto excludes it.
    """
    scene = _scene(
        _el("Sounds & Haptics", 224, 94, w=156),
        _el("Silent Mode", 160, 209, w=120),
        _el("iPhone will play ringtones, alerts and system sounds.", 224, 252, w=320),
        _el("Show in Status Bar", 120, 311, w=140),
        _el("Input", 100, 401, w=48),
        _el("Ringtone and Alerts", 130, 476, w=160),
        _el("Change with Buttons", 130, 572, w=160),
        _el("Always Play", 320, 625, w=80),
        _el("Ringtone", 120, 744, w=80),
        _el("Text Tone", 120, 797, w=80),
        _el("New Voicemail", 130, 851, w=120),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 982))

    assert classified.page_id == "settings/Sounds & Haptics"
    assert "action_button_carousel" not in classified.evidence


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


def _ambiguous_settings_like_detail_scene() -> Scene:
    return _scene(
        _el("<", 18, 76, w=18, ty="nav_back"),
        _el("Apps", 196, 96, w=62),
        _el("Manage apps and access settings", 58, 190, w=310),
        _el("Default Apps", 58, 270, w=132),
        _el("Privacy", 58, 326, w=82),
    )


@pytest.mark.smoke
def test_ios_scene_classifier_uses_non_settings_prior_to_abstain_weak_settings_detail():
    scene = _ambiguous_settings_like_detail_scene()
    prior = SceneClassificationPrior(
        page_id="appstore/search",
        recognition_score=1.0,
        platform_scene_kind="app_store",
        last_action_op="tap",
        last_action_target="Apps",
    )

    baseline = classify_ios_scene(scene, viewport_size=(448, 973))
    classified = classify_ios_scene(scene, viewport_size=(448, 973), prior=prior)

    assert baseline.kind == "settings_detail"
    assert classified.kind == "unknown"
    assert classified.safe_actions == ("trace", "vlm_on_uncertain")
    assert "settings_detail_prior_abstain" in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_uses_generic_prior_fallback_to_abstain_weak_settings_detail():
    scene = _ambiguous_settings_like_detail_scene()
    prior = SceneClassificationPrior(
        page_id="notes/app-list",
        recognition_score=0.95,
        platform_scene_kind="notes_app",
        last_action_op="tap",
        last_action_target="Apps",
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973), prior=prior)

    assert classified.kind == "unknown"
    assert classified.safe_actions == ("trace", "vlm_on_uncertain")
    assert "settings_detail_prior_abstain" in classified.evidence
    assert "prior:notes_app" in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_does_not_resist_settings_detail_below_prior_margin():
    scene = _ambiguous_settings_like_detail_scene()
    prior = SceneClassificationPrior(
        page_id="appstore/search",
        # The ambiguous semantic detail read is 0.80; the prior must clear it by
        # SETTINGS_PRIOR_RESIST_MARGIN (0.08). Scores below 0.88 intentionally
        # defer to the current frame instead of forcing a memory-prior veto.
        recognition_score=0.87,
        platform_scene_kind="app_store",
        last_action_op="tap",
        last_action_target="Apps",
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973), prior=prior)

    assert classified.kind == "settings_detail"
    assert classified.page_id is not None
    assert classified.page_id.startswith("settings/")
    assert "settings_detail_prior_abstain" not in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_system_search_is_not_settings_search():
    # Weak branch (bare "建议" title, no hard Spotlight marker): genuine
    # Spotlight suggests APPS. At most ONE Settings-root-label row may appear
    # (e.g. a Siri shortcut to a recently-opened pane); two or more flip the
    # read to the Settings app's own search pane — see
    # test_ios_scene_classifier_settings_own_search_pane_*.
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("App", 56, 152, w=34),
        _el("App Store", 56, 212, w=80, ty="button"),
        _el("最近1", 18, 410, w=46),
        _el("隐私与安全性", 56, 708, w=104),
        _el("Q", 48, 912, w=16),
        _el("搜索", 68, 910, w=42),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "system_search"
    assert "home" in classified.safe_actions


@pytest.mark.smoke
def test_ios_scene_classifier_settings_own_search_pane_is_not_system_search():
    # Regression (live iphone_transition_n1 view_0065, iPhone 17 Pro Max
    # en/CN): tapping the Settings root's own Search field opens the Settings
    # app's UNTYPED search pane — "Suggestions" + "Recents" + bottom search
    # chrome. The weak Suggestions branch claimed system_search, so the
    # harness marked Settings search unavailable and pressed Home before the
    # query was ever typed (actions.jsonl seq 51-52). The pane's rows are
    # Settings root labels (Spotlight suggests apps), so >=2 such rows abstain
    # from system_search and the scene falls through to settings_search_home.
    scene = _scene_from_ocr_fixture(
        "view_0065.ocr.json", root=_GOLDEN_IOS_SCENE_ROOT / "settings_search_pane"
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 989))

    assert classified.kind == "settings_search_home"
    assert "type_query" in classified.safe_actions
    assert "home" not in classified.safe_actions


@pytest.mark.smoke
def test_settings_search_pane_fixture_stays_free_of_personal_data():
    # The committed view_0065 fixture is raw rig OCR; keep it provably free of
    # personal data (same shape guards as the transition-corpus scrub tests).
    import re

    payload = json.loads(
        (_GOLDEN_IOS_SCENE_ROOT / "settings_search_pane" / "view_0065.ocr.json")
        .read_text(encoding="utf-8")
    )
    email_shape = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    digit_separators = re.compile(r"[\s().+\-:/]")
    long_digit_run = re.compile(r"\d{7,}")
    ssid_shape = re.compile(r"^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+$")
    for element in payload["elements"]:
        text = element.get("text") or ""
        assert not email_shape.search(text)
        assert not long_digit_run.search(digit_separators.sub("", text))
        assert not ssid_shape.match(text.strip())
        assert not text.strip().startswith("DIRECT-")


@pytest.mark.smoke
def test_ios_scene_classifier_settings_own_search_pane_zh_is_not_system_search():
    # zh lane of the view_0065 abstain: same weak Suggestions shape with >=2
    # zh Settings root labels in the list band must abstain identically.
    scene = _scene(
        _el("建议", 18, 98, w=36),
        _el("面容ID与密码", 56, 152, w=110),
        _el("紧急 SOS", 56, 212, w=80),
        _el("通用", 56, 340, w=36),
        _el("最近", 18, 410, w=36),
        _el("屏幕使用时间", 56, 470, w=104),
        _el("隐私与安全性", 56, 708, w=104),
        _el("Q", 48, 912, w=16),
        _el("搜索", 68, 910, w=42),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_search_home"


@pytest.mark.smoke
def test_ios_scene_classifier_hard_spotlight_marker_wins_over_root_label_rows():
    # The abstain veto is WEAK-branch only: with a hard Spotlight marker
    # ("Siri Suggestions" — e.g. typed-Spotlight results listing Settings
    # deep-links), root-label rows must NOT flip the read away from
    # system_search.
    scene = _scene(
        _el("Siri Suggestions", 42, 128, w=130),
        _el("General", 56, 212, w=60, ty="button"),
        _el("Privacy & Security", 56, 280, w=140, ty="button"),
        _el("Screen Time", 56, 348, w=100, ty="button"),
        _el("Q Search", 68, 910, w=80),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "system_search"


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
def test_ios_scene_classifier_app_store_home_is_not_settings_detail():
    # Regression: App Store Home on the iPad/PicoKVM rig has top App Store tabs
    # plus card/list copy. The generic Settings-detail fallback used to take the
    # "Games/Apps" tab as a title and attach the dangerous back license.
    scene = _scene(
        _el("Games", 797, 80, w=204, h=37, ty="list_item"),
        _el("Today", 812, 95, w=45, h=14),
        _el("Apps", 952, 80, w=127, h=38, ty="list_item"),
        _el("Arcade", 1016, 81, w=100, h=38, ty="list_item"),
        _el("Tuesday, June 2", 848, 145, w=220, h=31),
        _el("NOW AVAILABLE", 982, 215, w=109, h=14),
        _el("Hit the Streets in", 684, 382, w=193, h=23),
        _el("Neverness to", 684, 407, w=151, h=26),
        _el("This urban adventure's full of hidden wonders.", 684, 466, w=246, h=14),
        _el("Meet Mortenax Blade", 988, 393, w=243, h=23, ty="button"),
        _el("Apple Arcade has more to discover", 988, 449, w=300, h=17),
        _el("Get", 882, 519, w=28, h=17),
        _el("I-Aop Purchaies", 862, 541, w=67, h=14),
    )

    classified = classify_ios_scene(scene, viewport_size=(1920, 1080))

    assert classified.kind == "unknown"
    assert classified.page_id is None
    assert "back" not in classified.safe_actions
    assert "edge_back" not in classified.safe_actions
    assert "appstore_chrome" in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_generic_detail_shape_without_settings_anchor_abstains():
    scene = _scene(
        _el("Articles", 190, 78, w=78),
        _el("Explore the latest stories selected for you today.", 42, 150, w=330),
        _el("Recommended collections and saved items appear here.", 42, 220, w=330),
        _el("Featured", 70, 300, w=74, ty="button"),
        _el("Saved", 70, 360, w=50, ty="button"),
        _el("History", 70, 420, w=58, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "unknown"
    assert classified.page_id is None
    assert "back" not in classified.safe_actions
    assert "edge_back" not in classified.safe_actions
    assert "settings_detail_abstain" in classified.evidence
    assert "missing_settings_anchor" in classified.evidence


def _app_store_home_scene(*, ui_layout_icon: bool) -> Scene:
    elements = [
        _el("2:54PM Tue 2Jun", 650, 59, w=117, h=17),
        _el("Today", 812, 95, w=45, h=14),
        _el("Games", 879, 95, w=53, h=14),
        _el("Apps", 952, 95, w=42, h=14),
        _el("Arcade", 1016, 95, w=53, h=14),
        _el("Tuesday, June 2", 848, 145, w=220, h=31),
        _el("NOW AVAILABLE", 982, 215, w=109, h=14),
        _el("WORLD PREMIERE", 684, 360, w=106, h=14),
        _el("Hit the Streets in", 684, 382, w=193, h=23),
        _el("Neverness to", 684, 407, w=151, h=26),
        _el("This urban adventure's full of hidden wonders.", 684, 466, w=246, h=14),
        _el("Get", 882, 519, w=28, h=17),
        _el("I-Aop Purchaies", 862, 541, w=67, h=14),
    ]
    if ui_layout_icon:
        elements.insert(2, _el("", 868, 82, w=72, h=35, ty="image"))
    return _scene(*elements)


@pytest.mark.smoke
def test_app_store_search_intent_requires_ui_layout_icon_candidate():
    baseline = _app_store_home_scene(ui_layout_icon=False)
    apply_ios_classification(baseline, viewport_size=(1920, 1080))

    assert annotate_app_store_search_intents(baseline, viewport_size=(1920, 1080)) == 0
    assert [element.intent_label for element in baseline.elements if element.intent_label] == []

    ui_layout = _app_store_home_scene(ui_layout_icon=True)
    apply_ios_classification(ui_layout, viewport_size=(1920, 1080))

    assert annotate_app_store_search_intents(ui_layout, viewport_size=(1920, 1080)) == 1
    search = [element for element in ui_layout.elements if element.intent_label == "Search"]
    assert len(search) == 1
    assert search[0].intent_source == "appstore_chrome"
    assert search[0].type == "button"
    assert "tap" in search[0].suggested_actions
    assert "appstore_search_icon" in search[0].type_evidence


@pytest.mark.smoke
def test_app_store_search_intent_is_wired_through_scene_annotations():
    scene = _app_store_home_scene(ui_layout_icon=True)
    apply_ios_classification(scene, viewport_size=(1920, 1080))
    phone = SimpleNamespace(
        action_context=ActionContext(),
        device_geometry=SimpleNamespace(model="ipad_mini_7"),
        ios_closed_set_canonicalization_enabled=True,
        settings_root_label_aliases=None,
        settings_root_fuzzy_aliases=False,
    )

    Perceptor(phone).apply_scene_annotations(scene, viewport_size=(1920, 1080))

    assert [element.intent_label for element in scene.elements if element.intent_label] == ["Search"]


@pytest.mark.smoke
def test_app_store_search_intent_is_consumed_by_element_selector():
    scene = _app_store_home_scene(ui_layout_icon=True)
    apply_ios_classification(scene, viewport_size=(1920, 1080))
    annotate_app_store_search_intents(scene, viewport_size=(1920, 1080))

    class FakePhone:
        strict_target_matching_enabled = False

        def perceive(self):
            return scene

        def viewport_size(self):
            return (1920, 1080)

    hit = ElementSelector(FakePhone()).find_text("Search")

    assert hit is not None
    assert not (hit.text or "").strip()
    assert hit.intent_label == "Search"
    assert hit.intent_source == "appstore_chrome"
    assert hit.type == "button"


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
def test_ios_scene_classifier_semantic_detail_mints_nav_band_title_over_first_row():
    # C2/S3 (docs/design/iphone_settings_transition.md): the semantic detail
    # guess scans the body band (cy >= h*0.11) and structurally excludes the
    # real centered nav title (cy≈92px on iPhone frames). The mint must prefer
    # the visible nav-band title over the first content row.
    scene = _scene(
        _el("<", 18, 80, w=14, ty="nav_back"),
        _el("Sounds & Haptics", 156, 82, w=140),
        _el("Silent Mode", 60, 200, w=100),
        _el("Switch between Silent and Ring for calls and alerts.", 40, 240, w=330),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert classified.page_id == "settings/Sounds & Haptics"
    assert classified.title == "Sounds & Haptics"


@pytest.mark.smoke
def test_ios_scene_classifier_semantic_detail_ignores_junk_nav_band_text():
    # Guard on the S3 nav-band preference: the nav-band winner must carry >=3
    # semantic chars. A nav-bar '+' (the Focus page's add button, which wins
    # _page_title's |cy-90| tie-break over the centered title) or OCR junk
    # like 'I!I,' must not replace a correct body-derived mint — on the live
    # run that would have regressed the verified 'settings/Privacy & Security'.
    scene = _scene(
        _el("<", 18, 80, w=14, ty="nav_back"),
        _el("+", 400, 80, w=16),
        _el("Do Not Disturb", 60, 200, w=120),
        _el("Switch between Silent and Ring for calls and alerts.", 40, 240, w=330),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 990))

    assert classified.kind == "settings_detail"
    assert classified.page_id == "settings/Do Not Disturb"
    assert classified.title == "Do Not Disturb"


@pytest.mark.smoke
def test_ios_scene_classifier_semantic_detail_keeps_two_char_cjk_nav_title():
    # CJK arm of the S3 junk guard: two CJK characters ARE a complete zh page
    # name (通用, 蓝牙, 电池 …). Under the Latin-only >=3 rule the guard
    # discarded the real nav title and minted the first body row instead
    # (通用 → settings/关于本机), which would have broken zh visit titles the
    # moment the Settings skill started delegating to this classifier.
    scene = _scene(
        _el("<", 20, 80, w=16, h=20, ty="nav_back"),
        _el("设置", 52, 86, w=40, h=20),
        _el("通用", 202, 79, w=44, h=22),
        _el("关于本机", 40, 160, w=86, h=20, ty="button"),
        _el("软件更新", 40, 214, w=86, h=20, ty="button"),
        _el("iPhone储存空间", 40, 268, w=130, h=20, ty="button"),
        _el("后台App刷新", 40, 322, w=110, h=20, ty="button"),
        _el("日期与时间", 40, 376, w=100, h=20, ty="button"),
        _el("键盘", 40, 430, w=44, h=20, ty="button"),
    )

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "settings_detail"
    assert classified.page_id == "settings/通用"
    assert classified.title == "通用"


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
        _el("homenet", 58, 398, w=52, h=18),
        _el("我的网络", 38, 462, w=72, h=20),
        _el("homenet_iptv", 58, 509, w=90, h=24),
        _el("其他网络", 40, 576, w=68, h=18),
        _el("homenet_aiot", 58, 624, w=90, h=22),
        _el("acme_washer_r_0a1b", 58, 732, w=162, h=22),
        _el("STB_AB12", 60, 788, w=84, h=21),
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
def test_ipados_split_detail_title_ignores_cross_pane_layout_control():
    scene = _scene(
        _el("4 Search 11:09AM Tue 2 Jun", 16, 12, w=176, h=12, ty="status_bar"),
        _el("Q Search", 36, 90, w=70, h=14),
        _el("Jo Doe", 20, 76, w=215, h=82, ty="button"),
        _el("Apple Account, iCloud", 94, 91, w=531, h=159, ty="switch"),
        _el("WLAN", 64, 268, w=46, h=16),
        _el("Bluetooth", 22, 251, w=214, h=75, ty="button"),
        _el("General", 66, 313, w=58, h=14),
        _el("Accessibility", 66, 358, w=92, h=14),
        _el("Siri", 64, 823, w=24, h=16),
        _el("Search and Look Up", 280, 106, w=138, h=14),
        _el("Show Recent Searches", 280, 142, w=152, h=12),
        _el("About Search & Privacy...", 280, 252, w=134, h=12),
        _el("Search Engine", 280, 301, w=96, h=17),
        _el("Help Apple Improve Search", 280, 378, w=180, h=14),
        _el("Help improve Search by allowing Apple to store the searches", 280, 414, w=318, h=14),
    )
    scene.viewport_size = (640, 989)

    classified = classify_ipados_scene(scene)

    assert classified.kind == "settings_detail"
    assert classified.title == "Search and Look Up"
    assert classified.page_id == "settings/Search and Look Up"


@pytest.mark.smoke
def test_ipados_compat_fallback_demotion_survives_nav_band_mint_fix():
    # The S3 nav-band mint fix reaches iPadOS only through
    # _classify_ios_compat_fallback (glassbox/ipados/scene.py). The iPad en/HK
    # floor is gate-load-bearing: a non-split surface that the iOS classifier
    # reads as settings_detail must STILL demote to unknown with NO page_id
    # minted, nav-band title or not — the fix must never leak a page identity
    # into the sidebar-less iPad path. (The split-view detail path mints from
    # _detail_pane_title and is untouched; see
    # test_ipados_split_detail_title_ignores_cross_pane_layout_control.)
    scene = _scene(
        _el("<", 18, 80, w=14, ty="nav_back"),
        _el("Sounds & Haptics", 290, 82, w=160),
        _el("Silent Mode", 160, 610, w=120),
        _el("Switch between Silent and Ring for calls and alerts.", 120, 650, w=330),
    )
    scene.viewport_size = (744, 1133)

    classified = classify_ipados_scene(scene)

    assert classified.kind == "unknown"
    assert classified.page_id is None
    assert classified.safe_actions == ("trace", "vlm_on_uncertain")
    assert classified.evidence[0] == "ipados_no_settings_sidebar"


@pytest.mark.smoke
def test_ipados_scene_classifier_weather_app_search_is_not_settings_search_results():
    scene = _scene(
        _el("11:04AM Mon 1 Jun", 16, 14, w=120, h=12),
        _el("Q Search for a city or ai...", 34, 92, w=190),
        _el("Daxing", 38, 144, w=64),
        _el("My Location", 38, 168, w=68),
        _el("Sunny", 38, 202, w=36),
        _el("Shanghai", 38, 250, w=86),
        _el("Beijing", 38, 353, w=63),
        _el("MY LOCATION", 406, 128, w=82),
        _el("Daxing", 402, 143, w=91, h=34),
        _el("31", 402, 182, w=86, h=70),
        _el("Sunny conditions will continue all day. Wind gusts", 292, 400, w=294, h=16),
        _el("Now", 292, 456, w=30, h=14),
        _el("11AM", 344, 456, w=34, h=12),
        _el("12PM", 398, 456, w=34, h=12),
        _el("1PM", 452, 456, w=30, h=12),
        _el("10-DAY FORECAST", 294, 574, w=120, h=12),
    )
    scene.viewport_size = (640, 989)

    classified = classify_ipados_scene(scene)

    assert classified.kind == "unknown"
    assert "weather_app_surface" in classified.evidence
    assert classified.kind != "settings_search_results"
    assert "ipad_settings_top_search" not in classified.evidence


@pytest.mark.smoke
def test_ios_scene_classifier_weather_search_with_platform_springboard_is_not_home():
    scene = _scene(
        _el("12:48PM Mon 1 Jun", 16, 14, w=122, h=12),
        _el("Q search for a city or ai...0", 34, 90, w=190, h=22),
        _el("Paste", 36, 136, w=36, h=12),
        _el("AutoFill", 98, 135, w=46, h=13),
        _el("& Home", 30, 158, w=58, h=14),
        _el("Wangjing International Resear...", 28, 178, w=208, h=16),
        _el("Chongqing", 376, 131, w=140, h=32),
        _el("25°", 394, 162, w=134, h=78),
        _el("Cloudy", 418, 250, w=58, h=18),
        _el("H:28° L:23°", 398, 268, w=98, h=19),
        _el("30 - Excellent", 292, 402, w=114, h=18),
        _el("Current AQI (CN) is 30.", 294, 520, w=138, h=14),
        _el("• HOURLY FORECAST", 294, 572, w=126, h=12),
        _el("Now", 292, 604, w=30, h=12),
        _el("1PM", 346, 606, w=28, h=10),
        _el("• 10-DAY FORECAST", 294, 746, w=120, h=12),
        _el("Today", 290, 784, w=52, h=20),
        _el("Tue", 292, 832, w=32, h=18),
    )
    scene.platform_scene_kind = "springboard"

    classified = classify_ios_scene(scene, viewport_size=(640, 989))

    assert classified.kind == "unknown"
    assert "weather_app_surface" in classified.evidence


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
def test_ios_scene_classifier_settings_app_library_title_is_not_system_app_library():
    scene = _scene(
        _el("• Search 6:51PM Mon 1Jun", 650, 59, w=179, h=17),
        _el("Q Search", 675, 139, w=73, h=17),
        _el("Apple Account, iCloud", 734, 212, w=120, h=14),
        _el("Airplane Mode", 703, 273, w=100, h=17),
        _el("WLAN", 703, 318, w=47, h=14),
        _el("Bluetooth", 706, 363, w=67, h=14),
        _el("Battery", 706, 407, w=50, h=17),
        _el("General", 706, 460, w=53, h=14),
        _el("Home Screen & App Library", 991, 95, w=195, h=17),
        _el("Use Large App Icons", 921, 179, w=142, h=17),
        _el("Show App Library in Dock", 921, 410, w=173, h=17),
    )

    classified = classify_ios_scene(scene, viewport_size=(1920, 1080))

    assert classified.kind != "app_library"


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


# ── modal_sheet: auto-presented card sheets (Apple Account safety family) ─────
# Evidence: iphone_transition_n1 (2026-06-12). iOS auto-presented the Apple
# Account "Is this still your phone number?" sheet over settings/root; the
# OCR-only cascade classified it springboard(0.82, icon_grid) — its short value
# rows spread like app labels — and recovery climbed SpringBoard / blind-tapped
# corners instead of the top-right close-X. Scenes below are CONSTRUCTED from
# the recorded shape with synthetic values (no real phone digits / account
# name / SSID committed).


def _apple_account_safety_sheet_scene(*, with_close_x: bool = True) -> Scene:
    elements = [
        _el("2:14", 64, 26, w=42, ty="status_bar"),
        _el("Is this still your phone number?", 36, 155, w=328, h=147, ty="button"),
        _el("Current trusted number:", 38, 308, w=248, h=22),
        _el("+1 (555) 010-4477", 38, 336, w=192, h=24),
        _el("Date added:", 38, 382, w=126, h=23),
        # Synthetic date: the real sheet's "Date added" value is personal
        # (the privacy guard derives it from raw run ledgers and sweeps the
        # tree); any date-shaped text exercises the classifier identically.
        _el("5 March 2021", 37, 412, w=163, h=22),
        _el("It is important to make sure your", 36, 457, w=314, h=23),
        _el("trusted phone number is correct so", 36, 486, w=340, h=22),
        _el("that you always have access to your", 37, 514, w=349, h=24),
        _el("Apple Account.", 38, 544, w=150, h=24),
        _el("If you forget your password or sign in", 36, 588, w=356, h=24),
        _el("on a new device, your trusted phone", 38, 618, w=350, h=26),
        _el("number is used to verify your identity.", 38, 648, w=361, h=22),
        _el("Messaging and data rates may apply.", 38, 676, w=358, h=24),
        _el("Keep using +1 (555) 010-4477", 98, 838, w=252, ty="button"),
        _el("Change trusted number", 128, 902, w=194, h=18, ty="button"),
    ]
    if with_close_x:
        elements.insert(1, _el("X", 394, 102, w=20, h=18, ty="button"))
    return _scene(*elements)


@pytest.mark.smoke
def test_ios_scene_classifier_apple_account_safety_sheet_is_modal_sheet():
    from glassbox.ios.scene import modal_sheet_close_point

    scene = _apple_account_safety_sheet_scene()

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "modal_sheet"
    assert "modal_close_affordance" in classified.evidence
    assert any(item.startswith("safety_sheet_vocabulary") for item in classified.evidence)
    assert "dismiss_modal" in classified.safe_actions
    # The dismiss point is the OCR'd X center — top-right band, never the
    # bottom action rows.
    x, y = modal_sheet_close_point(scene, viewport_size=(448, 973))
    assert (x, y) == (404, 111)
    assert x >= 448 * 0.75 and y <= 973 * 0.20


@pytest.mark.smoke
def test_ios_scene_classifier_safety_sheet_without_ocr_close_x_still_modal():
    from glassbox.ios.scene import modal_sheet_close_point

    scene = _apple_account_safety_sheet_scene(with_close_x=False)

    classified = classify_ios_scene(scene, viewport_size=(448, 973))

    assert classified.kind == "modal_sheet"
    # Vocabulary anchor carries it; the dismiss point falls back to the
    # canonical top-right close region (~0.90w, 0.11h).
    x, y = modal_sheet_close_point(scene, viewport_size=(448, 973))
    assert (x, y) == (403, 107)


@pytest.mark.smoke
def test_ios_scene_modal_sheet_abstains_without_card_shape_or_vocabulary():
    from glassbox.ios.scene import modal_sheet_overlay_evidence

    # A lone top-right "X" OCR token without sheet copy / safety vocabulary
    # must NOT produce a modal verdict (abstain to the existing cascade).
    scene = _scene(
        _el("X", 394, 102, w=20, h=18, ty="button"),
        _el("General", 80, 300, w=64),
        _el("About", 80, 360, w=50),
    )

    assert modal_sheet_overlay_evidence(scene, viewport_size=(448, 973)) is None
    assert classify_ios_scene(scene, viewport_size=(448, 973)).kind != "modal_sheet"


@pytest.mark.smoke
def test_ios_scene_modal_sheet_abstains_on_home_screen_with_x_app_label():
    from glassbox.ios.scene import modal_sheet_overlay_evidence

    # SpringBoard with an app literally labelled "X" near the top-right grid
    # cell: the strong-Home veto (bottom Spotlight pill + app grid) wins, so
    # the icon grid is still classified springboard, not a sheet.
    scene = _scene(
        _el("FaceTime", 56, 140, w=64),
        _el("Calendar", 168, 140, w=64),
        _el("Photos", 280, 140, w=50),
        _el("X", 396, 140, w=14),
        _el("Maps", 56, 250, w=40),
        _el("Notes", 168, 250, w=44),
        _el("Reminders", 280, 250, w=72),
        _el("Settings", 392, 250, w=58),
        _el("Q Search", 198, 902, w=70),
    )

    assert modal_sheet_overlay_evidence(scene, viewport_size=(448, 973)) is None
    assert classify_ios_scene(scene, viewport_size=(448, 973)).kind == "springboard"
