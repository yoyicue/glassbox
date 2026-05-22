from __future__ import annotations

import numpy as np
import pytest

from glassbox.backend_registry import (
    DEFAULT_EFFECTOR_REGISTRY,
    DEFAULT_FRAME_SOURCE_REGISTRY,
    DEFAULT_VLM_REGISTRY,
    BackendRegistration,
    select_effector_backend,
    select_frame_source_backend,
    select_icon_detector_backend,
    select_ocr_backend,
    select_vlm_backend,
)
from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.config import AgentConfig
from glassbox.effector import ActionResult, BackendCapabilities, PreflightResult
from glassbox.geometry import make_device_geometry
from glassbox.memory import UTG, ScreenMemory
from glassbox.obs import Recorder
from glassbox.perception.letterbox import LetterboxCrop
from glassbox.perception.source import Frame
from glassbox.platforms import select_platform_backend
from glassbox.runtime import RuntimeUnavailable, build_phone


class FakeSource:
    resolution = (440, 956)

    def __init__(self):
        self.closed = False

    def snapshot(self):
        return Frame(img=np.zeros((956, 440, 3), dtype=np.uint8), ts=0.0)

    def close(self):
        self.closed = True


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
    assert select_icon_detector_backend(AgentConfig(_env_file=None)) == "classical"
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
