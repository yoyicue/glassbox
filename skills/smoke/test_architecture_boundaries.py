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
from glassbox.boundaries import ARCHITECTURE_BOUNDARY_CONTRACT_VERSION, AppLaunchTarget, StepContext
from glassbox.cognition import (
    COGNITION_CONTRACT_VERSION,
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    Box,
    IconBox,
    IconDetectFunctionAdapter,
    Scene,
    SceneClassification,
    SceneClassificationProjector,
    TextRegion,
    UIElement,
    VLMCacheKeyPayload,
    VLMRequest,
    VLMResult,
    VLMStageOutcome,
)
from glassbox.cognition.icon_detect import IconRegion
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
from glassbox.ios.springboard import IOSSpringboardProvider
from glassbox.perception.letterbox import LetterboxCrop
from glassbox.perception.source import FRAME_CONTRACT_VERSION, Frame, FrameContext
from glassbox.phone import Phone, PhoneGestureConfig
from glassbox.platforms import (
    IOSPlatform,
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


def test_boundary_contract_types_expose_stable_versions():
    assert ARCHITECTURE_BOUNDARY_CONTRACT_VERSION == 1
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


def test_icon_detector_adapter_uses_frame_text_regions_and_roi(monkeypatch):
    calls = []

    def fake_detect_icons(frame_img, *, text_boxes=(), backend=None, **_kwargs):
        calls.append((frame_img.shape, text_boxes, backend))
        return [IconRegion(box=(2, 3, 4, 5))]

    monkeypatch.setattr("glassbox.cognition.icon_contract.detect_icons", fake_detect_icons)
    adapter = IconDetectFunctionAdapter(backend="classical")
    frame = Frame(img=np.zeros((80, 100, 3), dtype=np.uint8), ts=1.0)

    icons = adapter.detect(
        frame,
        text_regions=[
            TextRegion(
                text="Label",
                box=Box(x=15, y=25, w=10, h=10),
                confidence=0.9,
            )
        ],
        roi=Box(x=10, y=20, w=30, h=40),
    )

    assert calls == [((40, 30, 3), ((5, 5, 10, 10),), "classical")]
    assert icons[0].box == Box(x=12, y=23, w=4, h=5)
    assert icons[0].label is None


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
