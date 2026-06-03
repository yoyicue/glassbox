from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from glassbox.app_policies import (
    DEFAULT_APP_POLICY_REGISTRY,
    AppPolicyRegistration,
    AppPolicyRegistry,
)
from glassbox.backend_registry import (
    DEFAULT_VLM_REGISTRY,
    BackendRegistration,
    BackendRegistry,
    avf_frame_source_registration,
    canonicalize_vlm_backend,
    moonshot_vlm_registration,
    noop_effector_registration,
    ocrmac_registration,
    picokvm_effector_registration,
    picokvm_frame_source_registration,
    siliconflow_vlm_registration,
    static_frame_source_registration,
    vision_ocr_registration,
)
from glassbox.boundaries import (
    ARCHITECTURE_BOUNDARY_CONTRACT_VERSION,
    ActionHost,
    AppLaunchTarget,
    StepContext,
)
from glassbox.cognition import (
    COGNITION_CONTRACT_VERSION,
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    Box,
    IconBox,
    Scene,
    SceneClassification,
    SceneClassificationProjector,
    TextRegion,
    UIElement,
    VLMCacheKeyPayload,
    VLMRequest,
    VLMResult,
    VLMStageOutcome,
    select_text_detector_backend,
)
from glassbox.cognition.ocr_contract import LegacyUIElementOCRAdapter
from glassbox.crawl_policies import (
    DEFAULT_CRAWL_POLICY_REGISTRY,
    CrawlPolicyRegistration,
    CrawlPolicyRegistry,
    GenericCrawlPolicyAdapter,
    SettingsCrawlPolicyAdapter,
)
from glassbox.effector import MockEffector, NoOpEffector
from glassbox.ios.safe_area import IOSSafeAreaProvider
from glassbox.ios.springboard import (
    IOSSpringboardProvider,
    find_springboard_icon,
    is_ios_home_screen,
)
from glassbox.perception.letterbox import LetterboxCrop
from glassbox.perception.source import FRAME_CONTRACT_VERSION, Frame, FrameContext
from glassbox.phone import (
    Phone,
    PhoneFeatureFlags,
    PhoneGestureConfig,
    PhoneObservationConfig,
    PhoneRuntimeOptions,
)
from glassbox.platforms import (
    IOSPlatform,
    IPadOSPlatform,
    PlatformRegistration,
    PlatformRegistry,
    select_platform_backend,
)
from glassbox.verification import (
    VerifierRegistration,
    VerifierRegistry,
    builtin_verifier_registrations,
)
from glassbox.verification.verifiers import SemanticOutcome, VerifierInput


class _Source:
    resolution = (100, 80)
    coordinate_space = "frame_px"

    def snapshot(self):
        return Frame(img=np.zeros((80, 100, 3), dtype=np.uint8), ts=1.0)


class _OCR:
    def recognize(self, _img):
        return [
            UIElement(
                type="text",
                box=Box(x=2, y=3, w=10, h=5),
                text="Settings",
                confidence=0.9,
            )
        ]


def test_architecture_boundaries_doc_records_closed_business_decisions():
    doc = Path(__file__).resolve().parents[2] / "docs/design/architecture_boundaries.md"
    text = doc.read_text()

    assert "8 个命名边界中 6 个达 §4 护栏" in text
    assert "Platform 为 provisional / iOS-only structural provider" in text
    assert "CrawlPolicy 为 provisional" in text
    assert "6/8 graduated + 2 provisional" in text
    assert "B-Q1 已决" in text
    assert "B-Q3 已决" in text
    assert "§10 待业务确认已清空" in text
    assert "不算第二 app" in text
    assert "待同事 review" not in text
    assert "转正路径见" not in text
    assert "才可转正" not in text
    assert "HarmonyOS 待确认" not in text
    assert "归并优先级待业务定" not in text


def test_action_host_protocol_declares_record_action_hook():
    assert "record_action" in ActionHost.__dict__


def test_phone_accepts_grouped_runtime_feature_and_observation_config():
    phone = Phone(
        source=_Source(),
        ocr=_OCR(),
        effector=NoOpEffector(),
        runtime_options=PhoneRuntimeOptions(
            action_fail_fast=False,
            auto_refresh_letterbox_crop=True,
            letterbox_refresh_consecutive=4,
            default_observation_scope="app",
            app_viewport_mode="iphone_compat",
        ),
        observation_config=PhoneObservationConfig(
            max_ocr_elements=7,
            max_ocr_text_chars=11,
            ocr_timeout=0.25,
            perceive_cache_diff=0.123,
        ),
        feature_flags=PhoneFeatureFlags(
            detect_icons_in_perceive=True,
            ui_layout_segmentation=True,
            strict_target_matching=True,
            require_home_icon_grid=True,
            reverify_fresh_frame=True,
            coldstart_promote_controls=True,
            vlm_set_of_mark=True,
            memory_locate_priors=True,
            strict_settings_detail=True,
            ai_scroll_prefer_wheel=True,
            vlm_reground_selection=True,
            whitebox_hint_selection=True,
        ),
    )

    assert phone.action_fail_fast is False
    assert phone.auto_refresh_letterbox_crop is True
    assert phone.letterbox_refresh_consecutive == 4
    assert phone.default_observation_scope == "app"
    assert phone.app_viewport_mode == "iphone_compat"
    assert phone.perceive_cache_diff == 0.123
    assert phone.max_ocr_elements == 7
    assert phone.max_ocr_text_chars == 11
    assert phone.ocr_timeout == 0.25
    assert phone.detect_icons_in_perceive_enabled is True
    assert phone.ui_layout_segmentation_enabled is True
    assert phone.strict_target_matching_enabled is True
    assert phone.require_home_icon_grid_enabled is True
    assert phone.reverify_fresh_frame_enabled is True
    assert phone.coldstart_promote_controls_enabled is True
    assert phone.vlm_set_of_mark_enabled is True
    assert phone.memory_locate_priors_enabled is True
    assert phone.strict_settings_detail_enabled is True
    assert phone.ai_scroll_prefer_wheel_enabled is True
    assert phone.vlm_reground_selection_enabled is True
    assert phone.whitebox_hint_selection_enabled is True


def test_phone_legacy_constructor_flags_still_work_with_bucket_api():
    phone = Phone(
        source=_Source(),
        ocr=_OCR(),
        effector=NoOpEffector(),
        action_fail_fast=False,
        auto_refresh_letterbox_crop=True,
        letterbox_refresh_consecutive=2,
        perceive_cache_diff=0.2,
        max_ocr_elements=3,
        strict_target_matching=True,
    )

    assert phone.action_fail_fast is False
    assert phone.auto_refresh_letterbox_crop is True
    assert phone.letterbox_refresh_consecutive == 2
    assert phone.perceive_cache_diff == 0.2
    assert phone.max_ocr_elements == 3
    assert phone.strict_target_matching_enabled is True


def test_text_detector_selector_is_vision_only_until_conditional_goal_triggers():
    from glassbox.config import AgentConfig

    assert select_text_detector_backend(AgentConfig(_env_file=None)) == "vision"


def test_boundary_contract_types_expose_stable_versions():
    assert ARCHITECTURE_BOUNDARY_CONTRACT_VERSION == 2
    assert FRAME_CONTRACT_VERSION == 1
    assert COGNITION_CONTRACT_VERSION == 1
    assert Frame.CONTRACT_VERSION == FRAME_CONTRACT_VERSION
    assert FrameContext.CONTRACT_VERSION == FRAME_CONTRACT_VERSION
    for ty in (
        TextRegion,
        IconBox,
        SceneClassification,
        VLMRequest,
        VLMCacheKeyPayload,
        VLMResult,
        VLMStageOutcome,
    ):
        assert ty.CONTRACT_VERSION == COGNITION_CONTRACT_VERSION


def test_default_scene_classification_projector_uses_vlm_first_priority():
    assert DEFAULT_SCENE_CLASSIFICATION_PROJECTOR.scene_type_priority == ("vlm", "app", "platform")


def test_scene_classification_projector_is_scene_classification_writer():
    scene = Scene(frame_id=1, timestamp=0.0)
    projector = SceneClassificationProjector()

    projector.project(
        scene,
        [
            SceneClassification(
                platform_scene_kind="settings_root",
                page_id="settings/root",
                source="platform",
                confidence=0.9,
                safe_actions=("scroll",),
                evidence=("settings_title",),
            ),
            SceneClassification(
                semantic_scene_type="login_form",
                source="vlm",
                confidence=1.0,
            ),
        ],
    )

    assert scene.platform_scene_kind == "settings_root"
    assert scene.semantic_scene_type == "login_form"
    assert scene.scene_type == "login_form"
    assert scene.page_id == "settings/root"
    assert scene.safe_actions == ["scroll"]
    assert scene.classification_source == "vlm"


def test_scene_classification_projector_flags_classifier_conflict():
    """CUQ-2.4: disagreeing platform scene kinds set classifier_conflict (the
    projector otherwise silently lets the last one win), feeding the VLM gate's
    trigger #3."""
    projector = SceneClassificationProjector()

    conflicted = Scene(frame_id=1, timestamp=0.0)
    projector.project(
        conflicted,
        [
            SceneClassification(platform_scene_kind="springboard", source="platform", confidence=0.6),
            SceneClassification(platform_scene_kind="settings_detail", source="app", confidence=0.8),
        ],
    )
    assert conflicted.classifier_conflict is True

    agreed = Scene(frame_id=1, timestamp=0.0)
    projector.project(
        agreed,
        [
            SceneClassification(platform_scene_kind="settings_detail", source="platform", confidence=0.6),
            SceneClassification(platform_scene_kind="settings_detail", source="app", confidence=0.8),
        ],
    )
    assert agreed.classifier_conflict is False


def test_scene_classification_projector_preserves_existing_scene_type_without_overwrite():
    scene = Scene(frame_id=1, timestamp=0.0, scene_type="vlm_settings")
    projector = SceneClassificationProjector()

    projector.project(
        scene,
        [
            SceneClassification(
                platform_scene_kind="settings_root",
                source="platform",
                confidence=0.9,
            )
        ],
    )

    assert scene.scene_type == "vlm_settings"
    assert scene.platform_scene_kind == "settings_root"


def test_phone_scene_classifier_hook_returns_classification_instead_of_mutating_scene():
    def classify(scene, viewport_size):
        assert scene.scene_type is None
        assert viewport_size == (100, 80)
        return SceneClassification(
            platform_scene_kind="unit_surface",
            source="platform",
            confidence=0.8,
        )

    phone = Phone(
        source=_Source(),
        ocr=_OCR(),
        effector=NoOpEffector(),
        scene_classifiers=[classify],
    )

    scene = phone.perceive()

    assert scene.scene_type == "unit_surface"
    assert scene.platform_scene_kind == "unit_surface"


def test_ios_platform_exposes_lazy_scene_classifier():
    platform = IOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="text", box=Box(x=198, y=72, w=48, h=20), text="设置", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=370, w=86, h=20), text="无线局域网", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=424, w=40, h=20), text="蓝牙", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=725, w=40, h=20), text="通用", confidence=0.9),
        ],
    )

    assert platform.scene_classifier is not None
    classified = platform.scene_classifier.classify(scene, viewport_size=(448, 973))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_root"
    assert classified.source == "platform"


def test_ipados_platform_classifies_settings_split_view_detail():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            UIElement(type="text", box=Box(x=48, y=72, w=72, h=28), text="设置", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=220, w=96, h=24), text="无线局域网", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=276, w=44, h=24), text="蓝牙", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=332, w=44, h=24), text="通用", confidence=0.9),
            UIElement(type="text", box=Box(x=418, y=76, w=70, h=28), text="通用", confidence=0.9),
            UIElement(type="text", box=Box(x=384, y=180, w=86, h=24), text="关于本机", confidence=0.9),
            UIElement(type="text", box=Box(x=384, y=236, w=86, h=24), text="软件更新", confidence=0.9),
            UIElement(type="text", box=Box(x=384, y=292, w=150, h=24), text="iPad 储存空间", confidence=0.9),
        ],
    )

    assert platform.safe_area is not None
    classified = platform.scene_classifier.classify(scene, viewport_size=(744, 1133))

    assert classified is not None
    assert platform.name == "ipados"
    assert classified.platform_scene_kind == "settings_detail"
    assert classified.page_id == "settings/通用"
    assert "tap_root_row" in classified.safe_actions
    assert "ipad_split_view" in classified.evidence


def test_ipados_platform_classifies_landscape_settings_without_sidebar_title():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(1920, 1080),
        elements=[
            UIElement(type="text", box=Box(x=273, y=186, w=104, h=22), text="• Search", confidence=0.9),
            UIElement(type="text", box=Box(x=363, y=296, w=179, h=20), text="Apple Account, iCloud", confidence=0.9),
            UIElement(type="text", box=Box(x=315, y=458, w=67, h=22), text="WLAN", confidence=0.9),
            UIElement(type="text", box=Box(x=321, y=593, w=73, h=25), text="Battery", confidence=0.9),
            UIElement(type="text", box=Box(x=321, y=675, w=81, h=18), text="General", confidence=0.9),
            UIElement(type="text", box=Box(x=318, y=740, w=126, h=28), text="Accessibility", confidence=0.9),
            UIElement(type="text", box=Box(x=321, y=878, w=79, h=22), text="Camera", confidence=0.9),
            UIElement(type="text", box=Box(x=899, y=78, w=123, h=17), text="Do Not Disturb", confidence=0.9),
            UIElement(type="text", box=Box(x=692, y=114, w=22, h=25), text="<", confidence=0.9),
            UIElement(type="button", box=Box(x=1080, y=114, w=201, h=26), text="Language & Region", confidence=0.9),
            UIElement(type="text", box=Box(x=698, y=209, w=220, h=23), text="Preferred Languages", confidence=0.9),
            UIElement(type="button", box=Box(x=698, y=265, w=75, h=20), text="English", confidence=0.9),
            UIElement(type="text", box=Box(x=698, y=469, w=583, h=20), text="Apps and websites will use the first language in this list that they support.", confidence=0.9),
            UIElement(type="text", box=Box(x=695, y=541, w=73, h=28), text="Region", confidence=0.9),
            UIElement(type="button", box=Box(x=698, y=614, w=92, h=20), text="Calendar", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(1920, 1080))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_detail"
    assert classified.page_id == "settings/Language & Region"
    assert "settings_sidebar_search" in classified.evidence
    assert "ipad_home_widgets" not in classified.evidence


def test_ipados_platform_classifies_minimal_repeated_title_detail():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=34, y=90, w=72, h=18), text="Q Search", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=220, w=52, h=16), text="WLAN", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=276, w=76, h=16), text="Battery", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=332, w=76, h=16), text="General", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=388, w=112, h=16), text="Accessibility", confidence=0.9),
            UIElement(type="text", box=Box(x=378, y=44, w=142, h=14), text="Scheduled Summary", confidence=0.9),
            UIElement(type="text", box=Box(x=280, y=108, w=138, h=16), text="Scheduled Summary", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 989))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_detail"
    assert classified.page_id == "settings/Scheduled Summary"
    assert "detail_repeated_title" in classified.evidence


def test_ipados_platform_classifies_screen_time_dashboard_title():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=34, y=90, w=72, h=18), text="Q Search", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=167, w=76, h=16), text="Battery", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=232, w=76, h=16), text="General", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=335, w=92, h=16), text="Screen Time", confidence=0.9),
            UIElement(type="text", box=Box(x=72, y=368, w=112, h=16), text="Accessibility", confidence=0.9),
            UIElement(type="text", box=Box(x=300, y=34, w=88, h=16), text="Daily Average", confidence=0.9),
            UIElement(type="button", box=Box(x=302, y=60, w=78, h=22), text="47h 19m", confidence=0.9),
            UIElement(type="text", box=Box(x=482, y=65, w=146, h=16), text="© 19% from last week", confidence=0.9),
            UIElement(type="text", box=Box(x=582, y=100, w=28, h=10), text="•avg", confidence=0.9),
            UIElement(type="text", box=Box(x=326, y=225, w=210, h=18), text="See All App & Website Activity", confidence=0.9),
            UIElement(type="text", box=Box(x=292, y=286, w=170, h=16), text="Updated today at 1:17PM", confidence=0.9),
            UIElement(type="text", box=Box(x=300, y=318, w=88, h=18), text="Limit Usage", confidence=0.9),
            UIElement(type="text", box=Box(x=318, y=348, w=76, h=18), text="Downtime", confidence=0.9),
            UIElement(type="text", box=Box(x=320, y=403, w=78, h=18), text="App Limits", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=456, w=112, h=18), text="Always Allowed", confidence=0.9),
            UIElement(type="text", box=Box(x=332, y=508, w=116, h=18), text="Screen Distance", confidence=0.9),
            UIElement(type="text", box=Box(x=336, y=608, w=158, h=18), text="Communication Limits", confidence=0.9),
            UIElement(type="text", box=Box(x=336, y=662, w=164, h=18), text="Communication Safety", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 989))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_detail"
    assert classified.page_id == "settings/Screen Time"


def test_ipados_platform_canonicalizes_screen_time_title_ocr_typo():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=36, y=90, w=70, h=14), text="Q Search", confidence=0.9),
            UIElement(type="text", box=Box(x=66, y=117, w=52, h=14), text="Camera", confidence=0.9),
            UIElement(type="text", box=Box(x=68, y=162, w=96, h=14), text="Control Centre", confidence=0.9),
            UIElement(type="text", box=Box(x=68, y=494, w=82, h=14), text="Notifications", confidence=0.9),
            UIElement(type="text", box=Box(x=66, y=539, w=52, h=12), text="Sounds", confidence=0.9),
            UIElement(type="text", box=Box(x=66, y=627, w=84, h=14), text="Screem Time", confidence=0.9),
            UIElement(type="text", box=Box(x=66, y=681, w=140, h=12), text="Touch ID & Passcode", confidence=0.9),
            UIElement(type="text", box=Box(x=64, y=725, w=124, h=18), text="Privacy & Security", confidence=0.9),
            UIElement(type="text", box=Box(x=406, y=44, w=88, h=14), text="Screen Time", confidence=0.9),
            UIElement(type="text", box=Box(x=282, y=106, w=76, h=12), text="All Devices", confidence=0.9),
            UIElement(type="text", box=Box(x=282, y=142, w=90, h=14), text="Daily Average", confidence=0.9),
            UIElement(type="button", box=Box(x=280, y=161, w=118, h=28), text="48h 25m", confidence=0.9),
            UIElement(type="text", box=Box(x=280, y=332, w=202, h=14), text="See All App & WebsiteActivity", confidence=0.9),
            UIElement(type="text", box=Box(x=278, y=428, w=86, h=16), text="Limit Usage", confidence=0.9),
            UIElement(type="text", box=Box(x=320, y=457, w=66, h=12), text="Downtime", confidence=0.9),
            UIElement(type="text", box=Box(x=316, y=509, w=74, h=16), text="App Limits", confidence=0.9),
            UIElement(type="text", box=Box(x=318, y=563, w=102, h=14), text="Always Allowed", confidence=0.9),
            UIElement(type="text", box=Box(x=318, y=615, w=110, h=14), text="Screen Distance", confidence=0.9),
            UIElement(type="text", box=Box(x=282, y=738, w=158, h=12), text="Communication Safety", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 989))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_detail"
    assert classified.page_id == "settings/Screen Time"


def test_ipados_platform_does_not_reuse_ios_settings_detail_fallback_on_home_widgets():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            UIElement(type="text", box=Box(x=40, y=70, w=180, h=24), text="下午8:54 5月25日周一", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=150, w=54, h=24), text="备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=205, w=92, h=24), text="无备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=350, y=150, w=32, h=24), text="25", confidence=0.9),
            UIElement(type="text", box=Box(x=350, y=205, w=130, h=24), text="The day following", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=420, w=64, h=24), text="上海市", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=476, w=36, h=24), text="26°", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(744, 1133))

    assert classified is not None
    assert classified.platform_scene_kind == "springboard"
    assert "ipad_home_widgets" in classified.evidence


def test_ipados_platform_app_store_chrome_beats_home_widget_false_positive():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 982),
        elements=[
            UIElement(type="text", box=Box(x=14, y=10, w=114, h=12), text="2:11PM Wed 3Jun", confidence=0.9),
            UIElement(type="text", box=Box(x=172, y=42, w=44, h=15), text="Today", confidence=0.9),
            UIElement(type="text", box=Box(x=242, y=41, w=48, h=13), text="Games", confidence=0.9),
            UIElement(type="text", box=Box(x=316, y=42, w=36, h=14), text="Apps", confidence=0.9),
            UIElement(type="text", box=Box(x=376, y=42, w=50, h=12), text="Arcade", confidence=0.9),
            UIElement(type="text", box=Box(x=210, y=92, w=220, h=34), text="Tuesday, June 2", confidence=0.9),
            UIElement(type="text", box=Box(x=346, y=164, w=106, h=12), text="NOW AVAILABLE", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=310, w=102, h=12), text="WORLD PREMIERE", confidence=0.9),
            UIElement(type="text", box=Box(x=46, y=330, w=188, h=20), text="Hit the Streets in", confidence=0.9),
            UIElement(type="button", box=Box(x=352, y=340, w=238, h=24), text="Meet Mortenax Blade", confidence=0.9),
            UIElement(type="text", box=Box(x=224, y=491, w=64, h=10), text="In-App Purchases", confidence=0.9),
            UIElement(type="text", box=Box(x=528, y=491, w=66, h=10), text="In-App Purchases", confidence=0.9),
            UIElement(type="text", box=Box(x=98, y=659, w=56, h=12), text="ChatGPT", confidence=0.9),
            UIElement(type="text", box=Box(x=98, y=713, w=62, h=12), text="Calendar", confidence=0.9),
            UIElement(type="text", box=Box(x=232, y=727, w=48, h=15), text="$12.99", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 982))

    assert classified is not None
    assert classified.platform_scene_kind == "unknown"
    assert "appstore_chrome" in classified.evidence
    assert "ipad_home_widgets" not in classified.evidence


def test_ipados_ios_compat_fallback_is_explicit_and_guards_settings_detail(monkeypatch):
    import glassbox.ipados.scene as ipados_scene
    from glassbox.ios.scene import IOSSceneClassification

    def fake_ios_fallback(_scene, *, viewport_size=None):
        assert viewport_size == (744, 1133)
        return IOSSceneClassification(
            kind="settings_detail",
            confidence=0.93,
            title="General",
            safe_actions=("back",),
            evidence=("fake_ios_detail",),
        )

    monkeypatch.setattr(ipados_scene, "classify_ios_scene", fake_ios_fallback)
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            UIElement(type="text", box=Box(x=360, y=82, w=78, h=24), text="General", confidence=0.9),
        ],
    )

    classified = ipados_scene.classify_ipados_scene(scene, viewport_size=(744, 1133))

    assert classified.kind == "unknown"
    assert classified.title == "General"
    assert classified.safe_actions == ("trace", "vlm_on_uncertain")
    assert classified.evidence == ("ipados_no_settings_sidebar", "fake_ios_detail")


def test_ipados_platform_classifies_live_widget_home_before_top_search():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=14, y=10, w=128, h=14), text="11:01PM Mon 25 May", confidence=0.9),
            UIElement(type="text", box=Box(x=136, y=104, w=12, h=10), text="12", confidence=0.9),
            UIElement(type="text", box=Box(x=108, y=116, w=12, h=10), text="10", confidence=0.9),
            UIElement(type="text", box=Box(x=98, y=216, w=40, h=10), text="MONDAY", confidence=0.9),
            UIElement(type="text", box=Box(x=98, y=228, w=32, h=22), text="25", confidence=0.9),
            UIElement(type="text", box=Box(x=98, y=334, w=50, h=14), text="Daxing 7", confidence=0.9),
            UIElement(type="text", box=Box(x=98, y=348, w=50, h=30), text="18°", confidence=0.9),
            UIElement(type="text", box=Box(x=220, y=94, w=56, h=10), text="Notes", confidence=0.9),
            UIElement(type="text", box=Box(x=218, y=130, w=46, h=10), text="No Notes", confidence=0.9),
            UIElement(type="text", box=Box(x=240, y=651, w=42, h=10), text="Camera", confidence=0.9),
            UIElement(type="text", box=Box(x=354, y=649, w=52, h=12), text="App Store", confidence=0.9),
            UIElement(type="text", box=Box(x=358, y=769, w=46, h=12), text="Settings", confidence=0.9),
            UIElement(type="text", box=Box(x=486, y=531, w=30, h=10), text="Maps", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 989))

    assert classified is not None
    assert classified.platform_scene_kind == "springboard"
    assert "ipad_home_widgets" in classified.evidence


def test_springboard_icon_tap_point_uses_shallower_ipad_offset():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=358, y=769, w=46, h=12), text="Settings", confidence=0.9),
        ],
    )

    icon = find_springboard_icon(scene, ("Settings",), viewport_size=(640, 989))

    assert icon is not None
    assert icon.tap_point == (381, 740)


def test_ipad_home_widget_text_is_not_treated_as_icon_label():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=220, y=94, w=56, h=10), text="- Notes", confidence=0.9),
            UIElement(type="text", box=Box(x=218, y=130, w=46, h=10), text="No Notes", confidence=0.9),
            UIElement(type="text", box=Box(x=240, y=649, w=42, h=13), text="Camera", confidence=0.9),
            UIElement(type="text", box=Box(x=354, y=649, w=52, h=12), text="App Store", confidence=0.9),
            UIElement(type="text", box=Box(x=358, y=769, w=46, h=13), text="Settings", confidence=0.9),
            UIElement(type="text", box=Box(x=486, y=412, w=28, h=12), text="Files", confidence=0.9),
            UIElement(type="text", box=Box(x=484, y=531, w=32, h=10), text="Maps", confidence=0.9),
        ],
    )

    assert find_springboard_icon(scene, ("Notes",), viewport_size=(640, 989)) is None
    assert find_springboard_icon(scene, ("Settings",), viewport_size=(640, 989)) is not None


def test_ipados_platform_classifies_spotlight_settings_overlay_as_system_search():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(644, 982),
        elements=[
            UIElement(type="text", box=Box(x=116, y=94, w=84, h=24), text="Settings", confidence=0.9),
            UIElement(type="button", box=Box(x=212, y=90, w=48, h=24), text="Open", confidence=0.9),
            UIElement(type="text", box=Box(x=84, y=140, w=52, h=16), text="Top Hit", confidence=0.9),
            UIElement(type="text", box=Box(x=112, y=226, w=58, h=16), text="Settings", confidence=0.9),
            UIElement(type="text", box=Box(x=84, y=276, w=86, h=16), text="Suggestions", confidence=0.9),
            UIElement(type="text", box=Box(x=460, y=360, w=92, h=16), text="Search in App", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(644, 982))

    assert classified is not None
    assert classified.platform_scene_kind == "system_search"
    assert "ipad_system_search_overlay" in classified.evidence


def test_ipados_platform_classifies_settings_top_search_no_results_as_search_results():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 988),
        elements=[
            UIElement(type="text", box=Box(x=34, y=86, w=118, h=20), text="Q BateryBattery/", confidence=0.9),
            UIElement(type="button", box=Box(x=66, y=526, w=128, h=18), text="No Results for", confidence=0.9),
            UIElement(type="text", box=Box(x=56, y=548, w=146, h=22), text='"BateryBattery"', confidence=0.9),
            UIElement(type="text", box=Box(x=52, y=574, w=158, h=14), text="Check the spelling or try a", confidence=0.9),
            UIElement(type="text", box=Box(x=422, y=44, w=54, h=16), text="Battery", confidence=0.9),
            UIElement(type="text", box=Box(x=278, y=108, w=72, h=28), text="100%", confidence=0.9),
            UIElement(type="text", box=Box(x=282, y=215, w=80, h=17), text="Daily Usage", confidence=0.9),
            UIElement(type="text", box=Box(x=278, y=500, w=150, h=14), text="App and System Activity", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 988))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_search_results"
    assert "ipad_settings_top_search" in classified.evidence


def test_ipados_platform_settings_top_search_beats_calendar_detail_widget_false_positive():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(640, 989),
        elements=[
            UIElement(type="text", box=Box(x=14, y=12, w=186, h=12), text="• Search 6:50 AM Tue 26 May", confidence=0.9),
            UIElement(type="text", box=Box(x=34, y=87, w=110, h=21), text="Q WLANWLAN", confidence=0.9),
            UIElement(type="button", box=Box(x=66, y=527, w=128, h=18), text="No Results for", confidence=0.9),
            UIElement(type="button", box=Box(x=62, y=549, w=134, h=20), text="“WLANWLAN”", confidence=0.9),
            UIElement(type="text", box=Box(x=54, y=575, w=156, h=14), text="Check the spelling or try a", confidence=0.9),
            UIElement(type="text", box=Box(x=424, y=43, w=52, h=13), text="Sounds", confidence=0.9),
            UIElement(type="text", box=Box(x=280, y=653, w=104, h=12), text="Calendar Alerts", confidence=0.9),
            UIElement(type="text", box=Box(x=552, y=653, w=58, h=13), text="Chord〉", confidence=0.9),
            UIElement(type="text", box=Box(x=280, y=697, w=106, h=14), text="Reminder Alerts", confidence=0.9),
            UIElement(type="text", box=Box(x=280, y=743, w=92, h=14), text="Default Alerts", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(640, 989))

    assert classified is not None
    assert classified.platform_scene_kind == "settings_search_results"
    assert "ipad_settings_top_search" in classified.evidence
    assert "ipad_home_widgets" not in classified.evidence


def test_ipados_platform_does_not_classify_files_sidebar_as_settings_top_search():
    platform = IPadOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(644, 984),
        elements=[
            UIElement(type="status_bar", box=Box(x=12, y=8, w=142, h=14), text="11:40AM Tue 26 May", confidence=0.9),
            UIElement(type="text", box=Box(x=32, y=44, w=14, h=20), text="<", confidence=0.9),
            UIElement(type="text", box=Box(x=66, y=90, w=58, h=16), text="Recents", confidence=0.9),
            UIElement(type="text", box=Box(x=64, y=420, w=54, h=16), text="Shared", confidence=0.9),
            UIElement(type="text", box=Box(x=64, y=470, w=54, h=16), text="Browse", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=90, w=58, h=16), text="Recents", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=160, w=78, h=16), text="Cylink.conf", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=192, w=124, h=16), text="29/8/2025", confidence=0.9),
            UIElement(type="text", box=Box(x=330, y=224, w=34, h=16), text="76 KB", confidence=0.9),
            UIElement(type="text", box=Box(x=610, y=940, w=14, h=14), text="Q", confidence=0.9),
        ],
    )

    classified = platform.scene_classifier.classify(scene, viewport_size=(644, 984))

    assert classified is not None
    assert classified.platform_scene_kind != "settings_search_results"
    assert "ipad_settings_top_search" not in classified.evidence


def test_legacy_ocr_adapter_returns_text_regions_and_offsets_roi():
    class LegacyOCR:
        def __init__(self):
            self.shapes = []

        def recognize(self, image):
            self.shapes.append(image.shape)
            return [
                UIElement(
                    type="text",
                    box=Box(x=1, y=2, w=10, h=5),
                    text="Hello",
                    confidence=0.8,
                )
            ]

    legacy = LegacyOCR()
    adapter = LegacyUIElementOCRAdapter(legacy)
    frame = Frame(img=np.zeros((80, 100, 3), dtype=np.uint8), ts=1.0)

    regions = adapter.recognize(frame, roi=Box(x=10, y=20, w=30, h=40))

    assert legacy.shapes == [(40, 30, 3)]
    assert regions == [
        TextRegion(
            text="Hello",
            box=Box(x=11, y=22, w=10, h=5),
            confidence=0.8,
        )
    ]


def test_legacy_ocr_adapter_routes_supported_roi_to_native_vision_coordinates():
    class NativeRoiOCR:
        supports_region_of_interest = True

        def __init__(self):
            self.calls = []

        def recognize(self, image, *, region_of_interest=None):
            self.calls.append((image.shape, region_of_interest))
            return [
                UIElement(
                    type="text",
                    box=Box(x=10, y=20, w=30, h=10),
                    text="Native",
                    confidence=0.8,
                )
            ]

    native = NativeRoiOCR()
    adapter = LegacyUIElementOCRAdapter(native)
    frame = Frame(img=np.zeros((80, 100, 3), dtype=np.uint8), ts=1.0)

    regions = adapter.recognize(frame, roi=Box(x=10, y=20, w=30, h=40))

    assert native.calls == [((80, 100, 3), (0.1, 0.25, 0.3, 0.5))]
    assert regions == [
        TextRegion(
            text="Native",
            box=Box(x=10, y=20, w=30, h=10),
            confidence=0.8,
        )
    ]


def test_phone_ocr_stage_converts_text_regions_to_ui_elements():
    class TextRegionOCR:
        contract = "TextRegionOCR"

        def recognize(self, image):
            assert isinstance(image, Frame)
            return [
                TextRegion(
                    text="Settings",
                    box=Box(x=2, y=3, w=10, h=5),
                    confidence=0.9,
                )
            ]

    phone = Phone(source=_Source(), ocr=TextRegionOCR(), effector=NoOpEffector())

    scene = phone.perceive()

    assert len(scene.elements) == 1
    assert scene.elements[0].type == "text"
    assert scene.elements[0].text == "Settings"
    assert scene.elements[0].element_id == 0


def test_phone_uses_injected_safe_area_provider_for_tab_bar_hit_point():
    class OCR:
        def recognize(self, _img):
            return [
                UIElement(
                    type="tab_bar_item",
                    box=Box(x=296, y=929, w=30, h=20),
                    text="设置",
                    confidence=0.9,
                )
            ]

    phone = Phone(
        source=_Source(),
        ocr=OCR(),
        effector=MockEffector(),
        safe_area_provider=IOSSafeAreaProvider(),
        action_fail_fast=False,
    )

    phone.tap_text("设置")
    last = phone.effector.last()
    assert last is not None
    assert last.kwargs == {"x": 311, "y": 72}


def test_phone_open_app_uses_injected_springboard_provider():
    class Provider:
        def __init__(self):
            self.calls = []

        def open_app(self, phone, target, *, max_pages=8, settle_s=0.8, icon_map=None):
            self.calls.append((phone, target, max_pages, settle_s, icon_map))
            return True

    provider = Provider()
    phone = Phone(
        source=_Source(),
        ocr=_OCR(),
        effector=MockEffector(),
        springboard_provider=provider,
        action_fail_fast=False,
    )

    result = phone.open_app("Settings", aliases=("设置",), max_pages=2, settle_s=0.1)

    assert result.ok is True
    assert provider.calls
    _, target, max_pages, settle_s, _ = provider.calls[0]
    assert target.labels == ("Settings",)
    assert target.aliases == ("设置",)
    assert max_pages == 2
    assert settle_s == 0.1


def test_phone_open_app_without_springboard_provider_is_unsupported():
    phone = Phone(
        source=_Source(),
        ocr=_OCR(),
        effector=MockEffector(),
        action_fail_fast=False,
    )

    result = phone.open_app("Settings")

    assert result.ok is False
    assert result.unsupported is True


def test_ios_springboard_provider_wraps_module_helper(monkeypatch):
    calls = []

    def fake_open(phone, labels, **kwargs):
        calls.append((phone, labels, kwargs))
        return True

    monkeypatch.setattr("glassbox.ios.springboard.open_app_from_springboard", fake_open)
    phone = Phone(source=_Source(), ocr=_OCR(), effector=MockEffector())
    provider = IOSSpringboardProvider()

    ok = provider.open_app(
        phone,
        target=AppLaunchTarget(
            bundle_id="",
            labels=("Settings",),
            aliases=("设置",),
        ),
        max_pages=3,
        settle_s=0.2,
        icon_map="map",
    )

    assert ok is True
    assert calls == [(phone, ("Settings", "设置"), {"max_pages": 3, "settle_s": 0.2, "icon_map": "map"})]


def test_springboard_home_recognizer_honors_platform_scene_kind():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="text", box=Box(x=20, y=80, w=120, h=20), text="备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=20, y=130, w=120, h=20), text="无备忘录", confidence=0.9),
        ],
    )
    scene.platform_scene_kind = "springboard"

    assert is_ios_home_screen(scene, viewport_size=(744, 1133)) is True

    scene.platform_scene_kind = "settings_detail"
    assert is_ios_home_screen(scene, viewport_size=(744, 1133)) is False


def test_app_policy_registry_resolves_builtin_settings_classifier():
    classifier = DEFAULT_APP_POLICY_REGISTRY.scene_classifier_for("com.apple.Preferences")

    assert classifier is not None
    assert DEFAULT_APP_POLICY_REGISTRY.crawl_policy_for("com.apple.Preferences") == "ios_settings"
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="text", box=Box(x=198, y=72, w=48, h=20), text="设置", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=370, w=86, h=20), text="无线局域网", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=424, w=40, h=20), text="蓝牙", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=725, w=40, h=20), text="通用", confidence=0.9),
        ],
    )
    classified = classifier.classify(scene, viewport_size=(448, 973))
    assert classified is not None
    assert classified.platform_scene_kind == "settings_root"
    assert classified.source == "app"


def test_app_policy_registry_resolves_ipados_settings_classifier():
    classifier = DEFAULT_APP_POLICY_REGISTRY.scene_classifier_for("com.apple.Preferences", platform="ipados")

    assert classifier is not None
    assert (
        DEFAULT_APP_POLICY_REGISTRY.crawl_policy_for("com.apple.Preferences", platform="ipados")
        == "ipados_settings"
    )
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        viewport_size=(744, 1133),
        elements=[
            UIElement(type="text", box=Box(x=40, y=70, w=180, h=24), text="下午8:54 5月25日周一", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=150, w=54, h=24), text="备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=205, w=92, h=24), text="无备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=350, y=205, w=130, h=24), text="The day following", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=420, w=64, h=24), text="上海市", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=476, w=36, h=24), text="26°", confidence=0.9),
        ],
    )
    classified = classifier.classify(scene, viewport_size=(744, 1133))
    assert classified is not None
    assert classified.platform_scene_kind == "springboard"
    assert classified.source == "app"


def test_app_policy_registry_loads_entry_point_registration(monkeypatch):
    class EntryPoint:
        def load(self):
            return AppPolicyRegistration(
                bundle_id="com.example.app",
                scene_classifier=_PolicyClassifier(),
                crawl_policy="unit_policy",
            )

    monkeypatch.setattr(
        "glassbox.app_policies.entry_points",
        lambda group: [EntryPoint()] if group == "glassbox.app_policies" else [],
    )
    registry = AppPolicyRegistry(load_entry_points=True)

    classifier = registry.scene_classifier_for("com.example.app")

    assert classifier is not None
    assert registry.crawl_policy_for("com.example.app") == "unit_policy"
    scene = Scene(frame_id=1, timestamp=0.0)
    classified = classifier.classify(scene)
    assert classified is not None
    assert classified.platform_scene_kind == "entry_point_surface"


def test_backend_registry_loads_entry_point_registration(monkeypatch):
    class EntryPoint:
        def load(self):
            return BackendRegistration(name="unit", factory=lambda **kwargs: kwargs["value"])

    monkeypatch.setattr(
        "glassbox.backend_registry.entry_points",
        lambda group: [EntryPoint()] if group == "glassbox.unit_backends" else [],
    )
    registry = BackendRegistry(entry_point_group="glassbox.unit_backends")

    assert registry.names() == ("unit",)
    assert registry.create("unit", value="created") == "created"


def test_backend_registry_priority_overrides_registration():
    registry = BackendRegistry(
        entry_point_group="glassbox.unit_backends",
        load_entry_points=False,
        registrations=(
            BackendRegistration(name="unit", factory=lambda **_: "low", priority=0),
            BackendRegistration(name="unit", factory=lambda **_: "high", priority=10),
        ),
    )

    assert registry.create("unit") == "high"


def test_builtin_pick_one_seam_registrations_have_public_names():
    assert static_frame_source_registration().name == "static"
    assert avf_frame_source_registration().name == "avf"
    assert picokvm_frame_source_registration().name == "picokvm_stream"
    assert noop_effector_registration().name == "noop"
    assert picokvm_effector_registration().name == "picokvm"
    assert ocrmac_registration().name == "ocrmac"
    assert vision_ocr_registration().name == "vision"


def test_builtin_vlm_registrations_expose_independent_providers():
    assert moonshot_vlm_registration().name == "moonshot"
    assert siliconflow_vlm_registration().name == "siliconflow"


def test_default_vlm_registry_exposes_only_canonical_provider_names():
    assert DEFAULT_VLM_REGISTRY.names() == ("moonshot", "siliconflow")
    assert canonicalize_vlm_backend("kimi") == "moonshot"
    assert canonicalize_vlm_backend("kimi_anthropic") == "moonshot"
    assert canonicalize_vlm_backend("kimi_siliconflow") == "siliconflow"


def test_crawl_policy_registry_loads_entry_point_registration(monkeypatch):
    class EntryPoint:
        def load(self):
            return CrawlPolicyRegistration(name="unit", factory=lambda **_: "policy")

    monkeypatch.setattr(
        "glassbox.crawl_policies.entry_points",
        lambda group: [EntryPoint()] if group == "glassbox.crawl_policies" else [],
    )
    registry = CrawlPolicyRegistry(load_entry_points=True)

    assert registry.names() == ("unit",)
    assert registry.create("unit") == "policy"


def test_platform_registry_loads_entry_point_registration(monkeypatch):
    class EntryPoint:
        def load(self):
            return PlatformRegistration(name="unit", factory=lambda **_: IOSPlatform())

    monkeypatch.setattr(
        "glassbox.platforms.entry_points",
        lambda group: [EntryPoint()] if group == "glassbox.platforms" else [],
    )
    registry = PlatformRegistry(load_entry_points=True)

    assert registry.names() == ("unit",)
    platform = registry.create("unit")
    assert platform.name == "ios"
    assert platform.supports("safe_area") is True
    assert platform.supports("springboard") is True
    assert platform.supports("recovery") is True


def test_ios_platform_exposes_recovery_provider():
    platform = IOSPlatform()

    assert platform.recovery is not None
    assert platform.supports("recovery") is True


def test_ios_platform_exposes_springboard_icon_map_factory():
    platform = IOSPlatform()

    assert platform.create_springboard_icon_map() is not None


def test_ios_springboard_provider_go_home_uses_step_context_metadata():
    class PhoneLike:
        def __init__(self):
            self.actions = []

        def home(self):
            self.actions.append("home")

    provider = IOSSpringboardProvider()
    phone = PhoneLike()

    assert provider.go_home(StepContext(metadata={"phone": phone})) is True
    assert phone.actions == ["home"]


def test_ios_recovery_provider_recovers_system_search():
    class PhoneLike:
        def __init__(self):
            self.actions = []

        def home(self):
            self.actions.append("home")

    platform = IOSPlatform()
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="text", box=Box(x=18, y=98, w=36, h=20), text="建议", confidence=0.9),
            UIElement(type="text", box=Box(x=56, y=152, w=34, h=20), text="App", confidence=0.9),
            UIElement(type="text", box=Box(x=56, y=212, w=36, h=20), text="通用", confidence=0.9),
            UIElement(type="text", box=Box(x=18, y=410, w=46, h=20), text="最近1", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=912, w=16, h=20), text="Q", confidence=0.9),
            UIElement(type="text", box=Box(x=68, y=910, w=42, h=20), text="搜索", confidence=0.9),
        ],
    )
    phone = PhoneLike()

    signal = platform.recovery.detect(scene)
    recovered = platform.recovery.recover(StepContext(metadata={"phone": phone, "scene": scene}))

    assert signal is not None
    assert signal.kind == "system_search"
    assert recovered is True
    assert phone.actions == ["home"]


def test_platform_selector_defaults_to_ios():
    class Cfg:
        platform = "ios"

    assert select_platform_backend(Cfg()) == "ios"


def test_platform_selector_auto_uses_ipados_for_ipad_model():
    class Cfg:
        platform = "ios"
        phone_model = "ipad_mini_7"
        model_fields_set = frozenset()

    assert select_platform_backend(Cfg()) == "ipados"


def test_platform_selector_respects_explicit_ios_for_ipad_model():
    class Cfg:
        platform = "ios"
        phone_model = "ipad_mini_7"
        model_fields_set = frozenset({"platform"})

    assert select_platform_backend(Cfg()) == "ios"


def test_settings_crawl_policy_adapter_exposes_provisional_crawl_policy():
    from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="text", box=Box(x=198, y=72, w=48, h=20), text="设置", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=370, w=86, h=20), text="无线局域网", confidence=0.9),
            UIElement(type="text", box=Box(x=390, y=370, w=16, h=20), text=">", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=424, w=40, h=20), text="蓝牙", confidence=0.9),
            UIElement(type="text", box=Box(x=390, y=424, w=16, h=20), text=">", confidence=0.9),
            UIElement(type="text", box=Box(x=80, y=725, w=40, h=20), text="通用", confidence=0.9),
            UIElement(type="text", box=Box(x=390, y=725, w=16, h=20), text=">", confidence=0.9),
        ],
    )
    adapter = SettingsCrawlPolicyAdapter(DEFAULT_SETTINGS_POLICY)

    candidates = adapter.candidates(scene)

    assert adapter.classify(scene) == "settings_root"
    assert [item["text"] for item in candidates] == ["无线局域网", "蓝牙", "通用"]
    assert [item["page_id"] for item in candidates] == [
        "settings/无线局域网",
        "settings/蓝牙",
        "settings/通用",
    ]
    assert adapter.is_safe(candidates[0], scene) is True
    assert adapter.is_safe({"text": "Apple ID"}, scene) is False
    assert adapter.should_stop(scene, []) is False


def test_generic_crawl_policy_adapter_exposes_app_agnostic_policy():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        scene_type="main",
        elements=[
            UIElement(type="text", box=Box(x=10, y=20, w=80, h=30), text="继续", confidence=0.9),
            UIElement(type="image", box=Box(x=10, y=80, w=80, h=30), text="", confidence=0.9),
        ],
    )
    adapter = GenericCrawlPolicyAdapter()

    candidates = adapter.candidates(scene)

    assert adapter.classify(scene) == "main"
    assert candidates == [
        {
            "action": "tap",
            "text": "继续",
            "label": "继续",
            "center": [50, 35],
            "role": "",
            "safe": True,
            "source": "generic_ocr",
        }
    ]
    assert adapter.is_safe(candidates[0], scene) is True
    assert adapter.is_safe({"action": "tap", "label": "继续", "source": "external"}, scene) is False
    assert adapter.should_stop(Scene(frame_id=2, timestamp=0.0, elements=[]), []) is True


def test_default_crawl_policy_registry_exposes_settings_adapter():
    policy = DEFAULT_CRAWL_POLICY_REGISTRY.create("ios_settings")

    assert isinstance(policy, SettingsCrawlPolicyAdapter)


def test_ios_settings_crawl_policy_selects_ipad_policy_from_runtime_config():
    from glassbox.config import AgentConfig
    from skills.regression.ios_settings.policy import IPadSettingsPolicy

    policy = DEFAULT_CRAWL_POLICY_REGISTRY.create(
        "ios_settings",
        cfg=AgentConfig(_env_file=None, phone_model="ipad_mini_7"),
    )

    assert isinstance(policy, SettingsCrawlPolicyAdapter)
    assert isinstance(policy.settings_policy, IPadSettingsPolicy)


def test_default_crawl_policy_registry_exposes_generic_policy():
    policy = DEFAULT_CRAWL_POLICY_REGISTRY.create("generic")

    assert isinstance(policy, GenericCrawlPolicyAdapter)


def test_crawl_run_cli_resolves_policy_from_registry():
    from skills.crawl.run import _make_crawl_policy

    assert isinstance(_make_crawl_policy("generic"), GenericCrawlPolicyAdapter)
    assert isinstance(_make_crawl_policy("ios_settings"), SettingsCrawlPolicyAdapter)


def test_crawl_run_cli_resolves_policy_name_by_bundle_and_overrides(monkeypatch):
    from glassbox.config import AgentConfig
    from skills.crawl.run import _resolve_crawl_policy_name

    cfg = AgentConfig(_env_file=None)

    monkeypatch.delenv("GLASSBOX_CRAWL_POLICY", raising=False)
    assert (
        _resolve_crawl_policy_name("com.apple.Preferences", explicit_policy=None, cfg=cfg)
        == "ios_settings"
    )
    assert (
        _resolve_crawl_policy_name(
            "com.apple.Preferences",
            explicit_policy=None,
            cfg=AgentConfig(_env_file=None, phone_model="ipad_mini_7"),
        )
        == "ipados_settings"
    )
    assert _resolve_crawl_policy_name("com.example.app", explicit_policy=None, cfg=cfg) == "generic"
    assert (
        _resolve_crawl_policy_name("com.apple.Preferences", explicit_policy="generic", cfg=cfg)
        == "generic"
    )

    monkeypatch.setenv("GLASSBOX_CRAWL_POLICY", "generic")
    assert (
        _resolve_crawl_policy_name("com.apple.Preferences", explicit_policy=None, cfg=cfg)
        == "generic"
    )


class _PolicyClassifier:
    def classify(self, scene, *, viewport_size=None):
        return SceneClassification(
            platform_scene_kind="entry_point_surface",
            source="app",
            confidence=0.7,
        )


def test_cropped_frame_carries_source_coordinate_context():
    crop = LetterboxCrop(crop_bbox=(10, 5, 50, 40), frame_size=(100, 80), phone_size=(500, 400))
    phone = Phone(source=_Source(), ocr=_OCR(), effector=NoOpEffector(), crop=crop)

    frame = phone.snapshot()

    assert frame.shape == (50, 40)
    assert frame.context.coordinate_space == "cropped_px"
    assert frame.context.source_coordinate_space == "frame_px"
    assert frame.context.source_shape == (100, 80)
    assert frame.context.crop_bbox == (10, 5, 50, 40)


def test_effector_preflight_contract_for_builtin_offline_effectors():
    assert NoOpEffector().preflight().ok is True
    assert MockEffector().preflight().ok is True


def test_phone_wheel_wrappers_use_injected_gesture_config():
    effector = MockEffector()
    phone = Phone(
        source=_Source(),
        ocr=_OCR(),
        effector=effector,
        gesture_config=PhoneGestureConfig(wheel_ticks_per_scroll=7, wheel_invert=True),
    )

    phone.wheel_scroll_down()
    phone.wheel_scroll_up()

    assert [action.kwargs["ticks"] for action in effector.actions] == [-7, 7]


class _Verifier:
    name = "unit_verifier"
    version = "1"

    def verify(self, input: VerifierInput) -> SemanticOutcome:
        return SemanticOutcome(status="passed", verifier=self.name, reason=input.action["type"])


def test_verifier_registration_declares_action_ownership():
    registry = VerifierRegistry(load_entry_points=False)
    registry.register_registration(
        VerifierRegistration(
            verifier=_Verifier(),
            handles_actions=("unit_action",),
            priority=10,
        )
    )

    assert registry.resolve("unit_action").name == "unit_verifier"


def test_builtin_verifiers_are_registration_contracts():
    registrations = builtin_verifier_registrations()

    assert {registration.verifier.name for registration in registrations} >= {
        "ios_control_center_opened",
        "scene_progressed",
        "tap_target_effect",
    }
    action_map = {
        action: registration.verifier.name
        for registration in registrations
        for action in registration.handles_actions
    }
    assert action_map["control_center"] == "ios_control_center_opened"
    assert action_map["scroll"] == "scene_progressed"
    assert action_map["tap"] == "tap_target_effect"


def test_verifier_registry_loads_entry_point_registration(monkeypatch):
    class EntryPoint:
        def load(self):
            return VerifierRegistration(
                verifier=_Verifier(),
                handles_actions=("entry_action",),
            )

    monkeypatch.setattr(
        "glassbox.verification.registry.entry_points",
        lambda group: [EntryPoint()] if group == "glassbox.verifiers" else [],
    )

    registry = VerifierRegistry(load_entry_points=True)

    assert registry.resolve("entry_action").name == "unit_verifier"


@pytest.mark.parametrize("source", ["platform", "app", "vlm"])
def test_scene_classification_source_is_closed_set(source):
    classification = SceneClassification(source=source)
    assert classification.source == source
