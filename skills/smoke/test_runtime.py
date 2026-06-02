from __future__ import annotations

import time

import numpy as np
import pytest

from glassbox.action import recover_to_home_then_renavigate
from glassbox.backend_registry import (
    DEFAULT_EFFECTOR_REGISTRY,
    DEFAULT_FRAME_SOURCE_REGISTRY,
    DEFAULT_VLM_REGISTRY,
    BackendRegistration,
    select_effector_backend,
    select_frame_source_backend,
    select_ocr_backend,
    select_vlm_backend,
)
from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.contracts import TextRegion
from glassbox.config import AgentConfig
from glassbox.effector import ActionResult, BackendCapabilities, PreflightResult
from glassbox.geometry import make_device_geometry
from glassbox.memory import UTG, ScreenMemory
from glassbox.obs import Recorder
from glassbox.perception.letterbox import LetterboxCrop
from glassbox.perception.source import Frame
from glassbox.platforms import DEFAULT_PLATFORM_REGISTRY, select_platform_backend
from glassbox.runtime import RuntimeUnavailable, build_phone, detect_crop


class FakeSource:
    resolution = (440, 956)

    def __init__(self):
        self.closed = False

    def snapshot(self):
        return Frame(img=np.zeros((956, 440, 3), dtype=np.uint8), ts=0.0)

    def close(self):
        self.closed = True


class AdvancingSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.index = 0

    def snapshot(self):
        image = np.zeros((956, 440, 3), dtype=np.uint8)
        image[0, 0, 0] = self.index
        ts = float(self.index + 1)
        self.index += 1
        return Frame(img=image, ts=ts)


class FreshSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.fresh_snapshots = 0

    def fresh_snapshot(self):
        self.fresh_snapshots += 1
        return self.snapshot()


class FakeOCR:
    def recognize(self, _image):
        return [
            UIElement(
                type="text",
                box=Box(x=20, y=100, w=120, h=40),
                text="设置",
                confidence=0.9,
            )
        ]


class HomeIconOCR:
    def recognize(self, _image):
        def el(text: str, x: int, y: int, w: int = 60):
            return UIElement(
                type="text",
                box=Box(x=x, y=y, w=w, h=20),
                text=text,
                confidence=0.9,
            )

        return [
            el("日 Notes", 42, 176),
            el("Facefime", 154, 176),
            el("App Store", 252, 176, 82),
            el("camera", 42, 316),
            el("Settings", 154, 316),
            el("Books", 252, 316),
            el("Search", 196, 892),
        ]


class CountingVotingOCR:
    def __init__(self):
        self.calls = 0
        self.readings = ["待机見示", "待机显示", "侍机昰示"]

    def recognize(self, _image):
        text = self.readings[min(self.calls, len(self.readings) - 1)]
        self.calls += 1
        return [
            UIElement(
                type="text",
                box=Box(x=20, y=100, w=120, h=40),
                text=text,
                confidence=0.9,
            )
        ]


class TimeoutOnceOCR:
    def __init__(self):
        self.calls = 0

    def recognize(self, _image):
        call_index = self.calls
        self.calls += 1
        if call_index == 0:
            time.sleep(0.05)
        return [
            UIElement(
                type="text",
                box=Box(x=20, y=100, w=120, h=40),
                text=f"frame-{call_index}",
                confidence=0.9,
            )
        ]


class ShapeOCR:
    def __init__(self):
        self.shapes: list[tuple[int, int]] = []

    def recognize(self, image):
        self.shapes.append((image.shape[1], image.shape[0]))
        return []


class LayoutRowOCR:
    def recognize(self, image):
        height, width = image.shape[:2]
        icon = max(22, int(width * 0.055))
        x = int(width * 0.08)
        y = int(height * 0.22)
        gap = max(10, int(width * 0.025))
        return [
            UIElement(
                type="text",
                box=Box(x=x + icon + gap, y=y + 2, w=max(52, int(width * 0.15)), h=20),
                text="WLAN",
                confidence=0.9,
            )
        ]


class TileOnlyTextRegionOCR:
    contract = "TextRegionOCR"

    def __init__(self):
        self.calls: list[tuple[str, tuple[int, int, int, int] | None, bool | None]] = []

    def recognize(self, frame, *, roi=None, native_roi=None):
        roi_tuple = None if roi is None else (roi.x, roi.y, roi.w, roi.h)
        self.calls.append(("frame", roi_tuple, native_roi))
        if roi is None:
            return [
                TextRegion(
                    text="Full",
                    box=Box(x=5, y=5, w=20, h=10),
                    confidence=0.9,
                )
            ]
        if roi.x == 0 and roi.y == 0:
            return [
                TextRegion(
                    text="Tiny",
                    box=Box(x=roi.x + 8, y=roi.y + 8, w=16, h=8),
                    confidence=0.8,
                )
            ]
        return []


class FakeSettingsOCR:
    def recognize(self, _image):
        return [
            UIElement(
                type="text",
                box=Box(x=198, y=72, w=48, h=20),
                text="设置",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=370, w=86, h=20),
                text="无线局域网",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=424, w=40, h=20),
                text="蓝牙",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=725, w=40, h=20),
                text="通用",
                confidence=0.9,
            ),
        ]


class NoisySettingsRootOCR:
    def recognize(self, _image):
        return [
            UIElement(
                type="text",
                box=Box(x=198, y=72, w=48, h=20),
                text="设置",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=300, w=40, h=20),
                text="蓝牙",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=360, w=86, h=20),
                text="待机見示",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=420, w=40, h=20),
                text="S0S",
                confidence=0.9,
            ),
        ]


class GreaterChinaEnglishSettingsRootOCR:
    def recognize(self, _image):
        return [
            UIElement(
                type="text",
                box=Box(x=198, y=72, w=72, h=20),
                text="Settings",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=300, w=64, h=20),
                text="WLAN",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=360, w=140, h=20),
                text="Mobile Service",
                confidence=0.9,
            ),
            UIElement(
                type="text",
                box=Box(x=80, y=420, w=96, h=20),
                text="Screem Time",
                confidence=0.9,
            ),
        ]


class FakeIPadSource(FakeSource):
    resolution = (744, 1133)

    def snapshot(self):
        return Frame(img=np.zeros((1133, 744, 3), dtype=np.uint8), ts=0.0)


class FakeIPadHomeWidgetOCR:
    def recognize(self, _image):
        return [
            UIElement(type="text", box=Box(x=40, y=70, w=180, h=24), text="下午8:54 5月25日周一", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=150, w=54, h=24), text="备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=205, w=92, h=24), text="无备忘录", confidence=0.9),
            UIElement(type="text", box=Box(x=350, y=205, w=130, h=24), text="The day following", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=420, w=64, h=24), text="上海市", confidence=0.9),
            UIElement(type="text", box=Box(x=48, y=476, w=36, h=24), text="26°", confidence=0.9),
        ]


class FakeEffector:
    coordinate_space = "frame_px"

    def __init__(self):
        self.closed = False

    def is_connected(self):
        return True

    def close(self):
        self.closed = True

    def supports(self, _action):
        return True

    def tap(self, *_args, **_kwargs):
        return ActionResult(ok=True, backend="fake", connected=True)


@pytest.mark.smoke
def test_build_phone_rejects_coldstart_without_memory_before_vlm_client(monkeypatch):
    source = FakeSource()
    effector = FakeEffector()
    cfg = AgentConfig(
        _env_file=None,
        enable_coldstart=True,
        enable_memory=False,
        memory_bundle="com.example",
    )
    monkeypatch.setattr(
        "glassbox.runtime.DEFAULT_VLM_REGISTRY.create",
        lambda *args, **kwargs: pytest.fail(
            "cold-start invalid config must not construct VLM client"
        ),
    )

    with pytest.raises(RuntimeUnavailable, match="ENABLE_COLDSTART"):
        build_phone(source=source, cfg=cfg, ocr=FakeOCR(), effector=effector)


@pytest.mark.smoke
def test_build_phone_uses_neutral_vlm_cache_config(monkeypatch, tmp_path):
    source = FakeSource()
    effector = FakeEffector()
    client = object()
    calls: dict[str, object] = {}
    cfg = AgentConfig(
        _env_file=None,
        enable_kimi=True,
        vlm_cache_dir=str(tmp_path / "vlm-cache"),
        kimi_cache_dir=str(tmp_path / "legacy-cache"),
    )

    monkeypatch.setattr(
        "glassbox.runtime.DEFAULT_VLM_REGISTRY.create",
        lambda *args, **kwargs: client,
    )

    def fake_wrap(created_client, *, cache_dir):
        calls["client"] = created_client
        calls["cache_dir"] = cache_dir
        return created_client

    monkeypatch.setattr("glassbox.runtime.wrap_vlm_cache_if_enabled", fake_wrap)

    runtime = build_phone(source=source, cfg=cfg, ocr=FakeOCR(), effector=effector)

    assert runtime.phone.kimi is client
    assert calls == {"client": client, "cache_dir": str(tmp_path / "vlm-cache")}


@pytest.mark.smoke
def test_build_phone_wires_recovery_hook_into_orchestrator(tmp_path):
    """CUQ-0.2: the production runtime must install a real recovery hook so the
    orchestrator's stuck/loop and strategy-exhaustion recovery are not no-ops."""
    source = FakeSource()
    effector = FakeEffector()
    cfg = AgentConfig(
        _env_file=None,
        computer_use_artifact_dir=str(tmp_path / "cu"),
    )

    runtime = build_phone(source=source, cfg=cfg, ocr=FakeOCR(), effector=effector)
    orchestrator = runtime.phone.action_orchestrator
    runtime.close()

    assert orchestrator is not None
    assert orchestrator.recovery_policy.hook is recover_to_home_then_renavigate
    assert orchestrator.recovery_policy.max_attempts >= 1


@pytest.mark.smoke
def test_phone_runtime_does_not_close_or_persist_borrowed_components(tmp_path):
    source = FakeSource()
    effector = FakeEffector()
    recorder = Recorder(tmp_path / "borrowed-recording", save_frames=False)
    memory = ScreenMemory(UTG(bundle_id="com.borrowed"))
    cfg = AgentConfig(_env_file=None, memory_dir=str(tmp_path / "memory"))

    runtime = build_phone(
        source=source,
        cfg=cfg,
        ocr=FakeOCR(),
        effector=effector,
        recorder=recorder,
        memory=memory,
    )
    runtime.close()

    assert source.closed is False
    assert effector.closed is False
    assert recorder._closed is False
    assert not (tmp_path / "memory" / "com.borrowed.json").exists()
    recorder.close()


@pytest.mark.smoke
def test_phone_runtime_closes_and_persists_owned_components(tmp_path):
    source = FakeSource()
    effector = FakeEffector()
    cfg = AgentConfig(
        _env_file=None,
        recording_dir=str(tmp_path / "runs"),
        enable_memory=True,
        memory_bundle="com.owned",
        memory_dir=str(tmp_path / "memory"),
    )

    runtime = build_phone(source=source, cfg=cfg, ocr=FakeOCR(), effector=effector)
    runtime.memory.observe(Scene(frame_id=1, timestamp=0.0, elements=[]))
    runtime.close()

    assert source.closed is False
    assert effector.closed is False
    assert runtime.recorder is not None and runtime.recorder._closed is True
    assert (tmp_path / "memory" / "com.owned.json").exists()


@pytest.mark.smoke
def test_runtime_selects_registered_frame_source_and_effector_backends(tmp_path):
    static_dir = tmp_path / "frames"
    static_dir.mkdir()

    assert select_frame_source_backend(AgentConfig(_env_file=None, frame_dir=str(static_dir))) == "static"
    assert select_frame_source_backend(AgentConfig(_env_file=None, frame_dir=None)) == "avf"
    assert select_frame_source_backend(AgentConfig(_env_file=None, picokvm=True)) == "picokvm_stream"
    assert select_effector_backend(AgentConfig(_env_file=None)) == "noop"
    assert select_effector_backend(AgentConfig(_env_file=None, picokvm=True)) == "picokvm"
    assert select_effector_backend(AgentConfig(_env_file=None, effector_backend="picokvm")) == "picokvm"
    assert (
        select_effector_backend(AgentConfig(_env_file=None, picokvm=True, effector_backend="noop"))
        == "noop"
    )
    assert select_ocr_backend(AgentConfig(_env_file=None, ocr="vision")) == "vision"
    assert select_ocr_backend(AgentConfig(_env_file=None, ocr="ocrmac")) == "ocrmac"
    assert select_vlm_backend(AgentConfig(_env_file=None, enable_kimi=False)) is None
    assert select_vlm_backend(AgentConfig(_env_file=None, enable_kimi=True)) == "moonshot"
    assert select_vlm_backend(
        AgentConfig(_env_file=None, enable_vlm=True, enable_kimi=False)
    ) == "moonshot"
    assert select_vlm_backend(
        AgentConfig(_env_file=None, enable_vlm=False, enable_kimi=True)
    ) is None
    assert select_vlm_backend(
        AgentConfig(_env_file=None, enable_kimi=True, vlm="siliconflow")
    ) == "siliconflow"
    assert select_vlm_backend(AgentConfig(_env_file=None, enable_kimi=True, vlm="kimi")) == "moonshot"
    assert (
        select_vlm_backend(AgentConfig(_env_file=None, enable_kimi=True, vlm="kimi_siliconflow"))
        == "siliconflow"
    )
    assert "picokvm_stream" in set(DEFAULT_FRAME_SOURCE_REGISTRY.names())
    assert "picokvm" in set(DEFAULT_EFFECTOR_REGISTRY.names())
    assert set(DEFAULT_VLM_REGISTRY.names()) == {"moonshot", "siliconflow"}
    assert select_platform_backend(AgentConfig(_env_file=None)) == "ios"
    assert "ipados" in set(DEFAULT_PLATFORM_REGISTRY.names())
    assert select_platform_backend(AgentConfig(_env_file=None, phone_model="ipad_mini_7")) == "ipados"


@pytest.mark.smoke
def test_picokvm_flags_select_matching_frame_source_and_effector(monkeypatch):
    for env_name in ("AGENT_PICOKVM", "GLASSBOX_PICOKVM"):
        monkeypatch.delenv("AGENT_PICOKVM", raising=False)
        monkeypatch.delenv("GLASSBOX_PICOKVM", raising=False)
        monkeypatch.delenv("GLASSBOX_EFFECTOR", raising=False)
        monkeypatch.setenv(env_name, "1")
        cfg = AgentConfig(_env_file=None)

        assert select_frame_source_backend(cfg) == "picokvm_stream"
        assert select_effector_backend(cfg) == "picokvm"


@pytest.mark.smoke
def test_device_geometry_is_built_once_from_config_and_source():
    cfg = AgentConfig(_env_file=None, phone_model="iphone_15")
    geometry = make_device_geometry(cfg, frame_size=(100, 200))

    assert geometry.model == "iphone_15"
    assert geometry.frame_size == (100, 200)
    assert geometry.phone_size == (1179, 2556)
    assert geometry.phone_points == (393, 852)


@pytest.mark.smoke
def test_detect_crop_accepts_ipad_landscape_orientation():
    class IPadLandscapeSource:
        resolution = (1920, 1080)

        def snapshot(self):
            img = np.zeros((1080, 1920, 3), dtype=np.uint8)
            img[57:1023, 225:1695] = 255
            return Frame(img=img, ts=0.0)

    cfg = AgentConfig(_env_file=None, phone_model="ipad_mini_7")
    crop = detect_crop(
        IPadLandscapeSource(),
        cfg=cfg,
        device_geometry=make_device_geometry(cfg, frame_size=(1920, 1080)),
    )

    assert crop is not None
    assert crop.crop_bbox == (225, 57, 1470, 966)
    assert crop.phone_size == (2266, 1488)


@pytest.mark.smoke
def test_build_phone_activates_app_scene_classifier_by_bundle():
    source = FakeSource()
    effector = FakeEffector()
    cfg = AgentConfig(_env_file=None, memory_bundle="com.apple.Preferences")

    runtime = build_phone(source=source, cfg=cfg, ocr=FakeSettingsOCR(), effector=effector)

    scene = runtime.phone.perceive()
    assert runtime.phone.safe_area_provider is not None
    assert runtime.phone.springboard_provider is not None
    assert runtime.phone.recovery_provider is not None
    assert scene.scene_type == "settings_root"
    assert scene.platform_scene_kind == "settings_root"


@pytest.mark.smoke
def test_runtime_populates_settings_root_row_intent_labels_from_core_annotator():
    source = FakeSource()
    effector = FakeEffector()
    cfg = AgentConfig(_env_file=None, memory_bundle="com.apple.Preferences")

    runtime = build_phone(source=source, cfg=cfg, ocr=NoisySettingsRootOCR(), effector=effector)

    scene = runtime.phone.perceive()

    by_text = {element.text: element for element in scene.elements}
    assert scene.platform_scene_kind == "settings_root"
    assert by_text["待机見示"].intent_label == "待机显示"
    assert by_text["待机見示"].intent_source == "settings_root_lexicon"
    assert by_text["S0S"].intent_label == "紧急 SOS"


@pytest.mark.smoke
def test_runtime_populates_greater_china_english_settings_root_intents_from_core_annotator():
    source = FakeIPadSource()
    effector = FakeEffector()
    cfg = AgentConfig(
        _env_file=None,
        phone_model="ipad_mini_7",
        memory_bundle="com.apple.Preferences",
        language="en",
        region="HK",
        settings_locale_fuzzy_resolution=True,
    )

    runtime = build_phone(
        source=source,
        cfg=cfg,
        ocr=GreaterChinaEnglishSettingsRootOCR(),
        effector=effector,
    )

    scene = runtime.phone.perceive()

    by_text = {element.text: element for element in scene.elements}
    assert scene.platform_scene_kind == "settings_root"
    assert by_text["WLAN"].intent_label == "无线局域网"
    assert by_text["Mobile Service"].intent_label == "蜂窝网络"
    assert by_text["Screem Time"].intent_label == "屏幕使用时间"


@pytest.mark.smoke
def test_build_phone_threads_configured_app_viewport_into_default_observation_scope():
    source = FakeSource()
    effector = FakeEffector()
    ocr = ShapeOCR()
    cfg = AgentConfig(
        _env_file=None,
        app_viewport_bbox=(10, 20, 50, 70),
        default_observation_scope="app",
    )

    runtime = build_phone(source=source, cfg=cfg, ocr=ocr, effector=effector)
    scene = runtime.phone.perceive()

    assert ocr.shapes == [(50, 70)]
    assert scene.viewport_size == (50, 70)
    assert runtime.phone.app_viewport is not None
    assert runtime.phone.app_viewport.bbox == (10, 20, 50, 70)


@pytest.mark.smoke
def test_ocr_tiling_is_default_off_for_text_region_ocr():
    ocr = TileOnlyTextRegionOCR()
    runtime = build_phone(
        source=FakeSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=ocr,
        effector=FakeEffector(),
    )

    scene = runtime.phone.perceive()

    assert [element.text for element in scene.elements] == ["Full"]
    assert ocr.calls == [("frame", None, None)]


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("source_cls", "phone_model"),
    [
        (FakeSource, "iphone_17_pro_max"),
        (FakeIPadSource, "ipad_mini_7"),
    ],
)
def test_ocr_tiling_opt_in_recovers_tile_only_text_regions_on_iphone_and_ipad(
    source_cls,
    phone_model,
):
    ocr = TileOnlyTextRegionOCR()
    runtime = build_phone(
        source=source_cls(),
        cfg=AgentConfig(
            _env_file=None,
            phone_model=phone_model,
            ocr_tiling_enabled=True,
            ocr_tiling_rows=2,
            ocr_tiling_cols=2,
            ocr_tiling_overlap=0.0,
        ),
        ocr=ocr,
        effector=FakeEffector(),
    )

    scene = runtime.phone.perceive()

    assert [element.text for element in scene.elements] == ["Full", "Tiny"]
    tile_calls = [call for call in ocr.calls if call[1] is not None]
    assert len(tile_calls) == 4
    assert all(native_roi is False for _, _, native_roi in tile_calls)


@pytest.mark.smoke
def test_ui_layout_segmentation_is_default_off_and_does_not_run_icon_detector(monkeypatch):
    calls = 0

    def fake_detect_icons(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr("glassbox.cognition.icon_detect.detect_icons", fake_detect_icons)
    runtime = build_phone(
        source=FakeSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=LayoutRowOCR(),
        effector=FakeEffector(),
    )

    scene = runtime.phone.perceive()

    assert calls == 0
    assert [(element.type, element.text) for element in scene.elements] == [("text", "WLAN")]


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("source_cls", "phone_model"),
    [
        (FakeSource, "iphone_17_pro_max"),
        (FakeIPadSource, "ipad_mini_7"),
    ],
)
def test_ui_layout_segmentation_opt_in_groups_icon_labels_on_iphone_and_ipad(
    monkeypatch,
    source_cls,
    phone_model,
):
    from glassbox.cognition.icon_detect import IconRegion

    calls = 0

    def fake_detect_icons(frame_img, *, text_boxes=(), **_kwargs):
        nonlocal calls
        calls += 1
        height, width = frame_img.shape[:2]
        icon = max(22, int(width * 0.055))
        return [IconRegion(box=(int(width * 0.08), int(height * 0.22), icon, icon))]

    monkeypatch.setattr("glassbox.cognition.icon_detect.detect_icons", fake_detect_icons)
    runtime = build_phone(
        source=source_cls(),
        cfg=AgentConfig(
            _env_file=None,
            phone_model=phone_model,
            ui_layout_segmentation_enabled=True,
        ),
        ocr=LayoutRowOCR(),
        effector=FakeEffector(),
    )

    scene = runtime.phone.perceive()

    assert calls == 1
    assert len(scene.elements) == 1
    row = scene.elements[0]
    assert row.type == "list_item"
    assert row.text == "WLAN"
    assert row.element_id == 0
    assert row.suggested_actions == ["tap"]
    assert row.type_source == "layout_segmenter"
    assert "layout_segment:icon_label" in row.type_evidence


@pytest.mark.smoke
def test_build_phone_uses_ipados_settings_app_classifier_for_home_widgets():
    cfg = AgentConfig(
        _env_file=None,
        phone_model="ipad_mini_7",
        memory_bundle="com.apple.Preferences",
    )

    runtime = build_phone(
        source=FakeIPadSource(),
        cfg=cfg,
        ocr=FakeIPadHomeWidgetOCR(),
        effector=FakeEffector(),
    )

    scene = runtime.phone.perceive()
    assert scene.scene_type == "springboard"
    assert scene.platform_scene_kind == "springboard"
    assert scene.classification_source == "app"


@pytest.mark.smoke
def test_phone_refreshes_letterbox_crop_when_source_resolution_changes():
    class FourKSource:
        resolution = (3840, 2160)

        def snapshot(self):
            img = np.zeros((2160, 3840, 3), dtype=np.uint8)
            img[:, 1422:2418] = 255
            return Frame(img=img, ts=0.0)

    crop = LetterboxCrop(
        crop_bbox=(711, 0, 498, 1080),
        frame_size=(1920, 1080),
        phone_size=(440, 956),
    )
    runtime = build_phone(
        source=FourKSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=FakeOCR(),
        effector=FakeEffector(),
        crop=crop,
    )

    frame = runtime.phone.snapshot()

    assert runtime.phone.crop is not None
    assert runtime.phone.crop.frame_size == (3840, 2160)
    assert runtime.phone.crop.crop_bbox == (1422, 0, 996, 2160)
    assert frame.shape == (996, 2160)
    assert int(frame.img.max()) == 255


@pytest.mark.smoke
def test_phone_refreshes_letterbox_crop_when_bbox_change_is_sustained():
    """CUQ-3.14: a SUSTAINED bbox change re-fits — but only after the hysteresis
    (default 2 consecutive frames), not on the first differing frame."""
    class MovingCropSource:
        resolution = (1920, 1080)

        def __init__(self):
            self.calls = 0

        def snapshot(self):
            self.calls += 1
            left = 711 if self.calls == 1 else 800  # call 1 (setup) = 711, then 800
            img = np.zeros((1080, 1920, 3), dtype=np.uint8)
            img[:, left:left + 498] = 255
            return Frame(img=img, ts=0.0)

    runtime = build_phone(
        source=MovingCropSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=FakeOCR(),
        effector=FakeEffector(),
    )

    # First 800 frame: pending under hysteresis, crop NOT yet re-fit.
    runtime.phone.snapshot()
    assert runtime.phone.crop.crop_bbox == (711, 0, 498, 1080)
    # Second consecutive 800 frame: hysteresis met, crop commits.
    frame = runtime.phone.snapshot()
    assert runtime.phone.crop.frame_size == (1920, 1080)
    assert runtime.phone.crop.crop_bbox == (800, 0, 498, 1080)
    assert frame.shape == (498, 1080)


@pytest.mark.smoke
def test_phone_does_not_refit_letterbox_crop_on_transient_frame():
    """CUQ-3.14: a single transient-content frame (one-off different bbox) must
    NOT drift the crop — the hysteresis discards it when the bbox reverts."""
    class TransientCropSource:
        resolution = (1920, 1080)

        def __init__(self):
            self.calls = 0

        def snapshot(self):
            self.calls += 1
            left = 800 if self.calls == 2 else 711  # call 2 is a one-off transient
            img = np.zeros((1080, 1920, 3), dtype=np.uint8)
            img[:, left:left + 498] = 255
            return Frame(img=img, ts=0.0)

    runtime = build_phone(
        source=TransientCropSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=FakeOCR(),
        effector=FakeEffector(),
    )

    runtime.phone.snapshot()   # call 2: transient 800 -> pending only
    runtime.phone.snapshot()   # call 3: back to 711 -> pending discarded

    assert runtime.phone.crop.crop_bbox == (711, 0, 498, 1080)


@pytest.mark.smoke
def test_phone_refits_letterbox_crop_despite_detector_jitter():
    """CUQ-3.14 audit fix: a sustained re-fit whose detected bbox jitters by a
    few px between frames must still commit (within-tolerance detections
    accumulate toward the hysteresis threshold instead of resetting it forever)."""
    class JitteryCropSource:
        resolution = (1920, 1080)

        def __init__(self):
            self.calls = 0

        def snapshot(self):
            self.calls += 1
            # call 1 (setup) = 711; then a sustained move to ~800 that jitters 800/801.
            left = 711 if self.calls == 1 else (800 if self.calls == 2 else 801)
            img = np.zeros((1080, 1920, 3), dtype=np.uint8)
            img[:, left:left + 498] = 255
            return Frame(img=img, ts=0.0)

    runtime = build_phone(
        source=JitteryCropSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=FakeOCR(),
        effector=FakeEffector(),
    )

    runtime.phone.snapshot()   # call 2: 800 -> pending (count 1)
    runtime.phone.snapshot()   # call 3: 801 (within tol of 800) -> count 2 -> commit latest
    assert runtime.phone.crop.crop_bbox == (801, 0, 498, 1080)


@pytest.mark.smoke
def test_build_phone_takes_platform_subcapabilities_from_registry(monkeypatch):
    class Platform:
        name = "unit"
        scene_classifier = "scene"
        safe_area = "safe"
        recovery = None
        springboard = "springboard"
        recovery = "recovery"

        def supports(self, capability):
            return getattr(self, capability, None) is not None

        def create_springboard_icon_map(self):
            return "icon-map"

    calls = []

    def fake_create(name, **kwargs):
        calls.append((name, kwargs))
        return Platform()

    monkeypatch.setattr("glassbox.runtime.DEFAULT_PLATFORM_REGISTRY.create", fake_create)
    cfg = AgentConfig(
        _env_file=None,
        platform="unit",
        wheel_ticks_per_scroll=12,
        wheel_invert=True,
    )

    runtime = build_phone(source=FakeSource(), cfg=cfg, ocr=FakeOCR(), effector=FakeEffector())

    assert calls == [("unit", {"cfg": cfg})]
    assert runtime.device_geometry is not None
    assert runtime.device_geometry.model == "iphone_17_pro_max"
    assert runtime.device_geometry.frame_size == FakeSource.resolution
    assert runtime.phone.device_geometry is runtime.device_geometry
    assert runtime.phone.safe_area_provider == "safe"
    assert runtime.phone.springboard_provider == "springboard"
    assert runtime.phone.recovery_provider == "recovery"
    assert runtime.phone._platform_scene_classifier == "scene"
    assert runtime.phone.icon_map == "icon-map"
    assert runtime.phone.gesture_config.wheel_ticks_per_scroll == 12
    assert runtime.phone.gesture_config.wheel_invert is True


@pytest.mark.smoke
def test_build_phone_loads_out_of_tree_effector_from_entry_point(monkeypatch):
    class BrightSource:
        resolution = (440, 956)

        @staticmethod
        def snapshot():
            return Frame(img=np.full((956, 440, 3), 255, dtype=np.uint8), ts=0.0)

    class ToyEffector:
        coordinate_space = "phone_pt"

        def __init__(self, **_kwargs):
            self.connected = False

        def capabilities(self):
            return BackendCapabilities(
                backend="toy",
                coordinate_space="phone_pt",
                pointer_kind="touch_digitizer",
                requires_calibrated_crop=True,
                requires_connection=True,
                transport_label="toy-wire",
                wheel_ticks_per_scroll=7,
                wheel_invert=True,
            )

        def preflight(self):
            return PreflightResult(ok=True)

        def connect(self):
            self.connected = True

        def close(self):
            self.connected = False

        def is_connected(self):
            return self.connected

        def supports(self, _action):
            return True

        def tap(self, *_args, **_kwargs):
            return ActionResult(ok=True, backend="toy", connected=self.connected)

    class ToyEntryPoint:
        def load(self):
            return BackendRegistration(name="toy", factory=lambda **kwargs: ToyEffector(**kwargs))

    def fake_entry_points(*, group=None):
        return [ToyEntryPoint()] if group == "glassbox.effectors" else []

    old_registrations = dict(DEFAULT_EFFECTOR_REGISTRY._by_name)
    old_loaded = DEFAULT_EFFECTOR_REGISTRY._entry_points_loaded
    monkeypatch.setattr("glassbox.backend_registry.entry_points", fake_entry_points)
    monkeypatch.setenv("GLASSBOX_EFFECTOR", "toy")
    DEFAULT_EFFECTOR_REGISTRY._entry_points_loaded = False
    try:
        cfg = AgentConfig(_env_file=None)
        runtime = build_phone(source=BrightSource(), cfg=cfg, ocr=FakeOCR())
    finally:
        DEFAULT_EFFECTOR_REGISTRY._by_name = old_registrations
        DEFAULT_EFFECTOR_REGISTRY._entry_points_loaded = old_loaded

    assert isinstance(runtime.effector, ToyEffector)
    assert runtime.effector.connected is True
    assert runtime.phone.coordinate_space == "phone_pt"
    assert runtime.phone.gesture_config.wheel_ticks_per_scroll == 7
    assert runtime.phone.gesture_config.wheel_invert is True


@pytest.mark.smoke
def test_build_phone_freshens_source_after_effector_connect(monkeypatch):
    class ConnectingEffector:
        coordinate_space = "frame_px"

        def __init__(self, **_kwargs):
            self.connected = False

        def capabilities(self):
            return BackendCapabilities(
                backend="unit",
                coordinate_space="frame_px",
                requires_connection=True,
            )

        def preflight(self):
            return PreflightResult(ok=True)

        def connect(self):
            self.connected = True

        def close(self):
            self.connected = False

        def is_connected(self):
            return self.connected

        def supports(self, _action):
            return True

    class ConnectingEntryPoint:
        def load(self):
            return BackendRegistration(
                name="unit_connect",
                factory=lambda **kwargs: ConnectingEffector(**kwargs),
            )

    def fake_entry_points(*, group=None):
        return [ConnectingEntryPoint()] if group == "glassbox.effectors" else []

    old_registrations = dict(DEFAULT_EFFECTOR_REGISTRY._by_name)
    old_loaded = DEFAULT_EFFECTOR_REGISTRY._entry_points_loaded
    monkeypatch.setattr("glassbox.backend_registry.entry_points", fake_entry_points)
    monkeypatch.setenv("GLASSBOX_EFFECTOR", "unit_connect")
    DEFAULT_EFFECTOR_REGISTRY._entry_points_loaded = False
    source = FreshSource()
    try:
        runtime = build_phone(source=source, cfg=AgentConfig(_env_file=None), ocr=FakeOCR())
    finally:
        DEFAULT_EFFECTOR_REGISTRY._by_name = old_registrations
        DEFAULT_EFFECTOR_REGISTRY._entry_points_loaded = old_loaded

    assert isinstance(runtime.effector, ConnectingEffector)
    assert runtime.effector.connected is True
    assert source.fresh_snapshots == 1


@pytest.mark.smoke
def test_runtime_wires_ocr_temporal_voting_config_without_global_perceive_side_effect():
    ocr = CountingVotingOCR()
    runtime = build_phone(
        source=FakeSource(),
        cfg=AgentConfig(
            _env_file=None,
            ocr_temporal_voting_enabled=True,
            ocr_temporal_voting_frames=3,
            ocr_temporal_voting_min_presence=2,
        ),
        ocr=ocr,
    )

    scene = runtime.phone.perceive()

    assert ocr.calls == 1
    assert scene.observation_mode == "raw"
    assert scene.ocr_vote_metadata == {}
    assert runtime.phone.ocr_temporal_voting_config.enabled is True

    runtime.phone.action_context.ocr_temporal_voting_opt_in = True
    scene = runtime.phone.perceive()

    assert ocr.calls == 4
    assert scene.observation_mode == "voted_degraded"
    assert scene.ocr_vote_metadata["samples_requested"] == 3
    assert scene.ocr_vote_metadata["samples_used"] == 3
    assert scene.ocr_vote_metadata["degrade_reason"] == "duplicate_frames"


@pytest.mark.smoke
def test_runtime_populates_springboard_icon_intent_labels_from_lexicon():
    runtime = build_phone(
        source=FakeSource(),
        cfg=AgentConfig(_env_file=None),
        ocr=HomeIconOCR(),
    )

    scene = runtime.phone.perceive()

    by_text = {element.text: element for element in scene.elements}
    assert scene.platform_scene_kind == "springboard"
    assert by_text["日 Notes"].intent_label == "Notes"
    assert by_text["Facefime"].intent_label == "FaceTime"
    assert by_text["App Store"].intent_label == "App Store"
    assert by_text["camera"].intent_label == "Camera"
    assert by_text["Settings"].intent_source == "springboard_lexicon"


@pytest.mark.smoke
def test_perceive_voted_n_one_bypasses_enabled_global_voting():
    ocr = CountingVotingOCR()
    runtime = build_phone(
        source=FakeSource(),
        cfg=AgentConfig(
            _env_file=None,
            ocr_temporal_voting_enabled=True,
            ocr_temporal_voting_frames=3,
        ),
        ocr=ocr,
    )

    scene = runtime.phone.perceive_voted(n=1)

    assert ocr.calls == 1
    assert scene.observation_mode == "raw"
    assert scene.ocr_vote_metadata == {}


@pytest.mark.smoke
def test_perceive_voted_degrades_when_timeouts_leave_too_few_usable_samples():
    runtime = build_phone(
        source=AdvancingSource(),
        cfg=AgentConfig(_env_file=None, ocr_timeout=0.001),
        ocr=TimeoutOnceOCR(),
    )

    scene = runtime.phone.perceive_voted(n=2)

    assert scene.observation_mode == "voted_degraded"
    assert scene.ocr_vote_metadata["samples_used"] == 2
    assert scene.ocr_vote_metadata["distinct_frames"] == 2
    assert scene.ocr_vote_metadata["timeouts"] == 1
    assert scene.ocr_vote_metadata["degrade_reason"] == "ocr_timeouts"
