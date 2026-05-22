"""Standard glassbox runtime assembly.

This module owns the production wiring for `Phone`: frame source, OCR, crop,
effector, recorder, VLM cache, memory, and scene classifiers. Pytest fixtures
and probes should delegate here so they do not drift.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from glassbox.backend_registry import (
    DEFAULT_EFFECTOR_REGISTRY,
    DEFAULT_FRAME_SOURCE_REGISTRY,
    DEFAULT_OCR_REGISTRY,
    DEFAULT_VLM_REGISTRY,
    select_effector_backend,
    select_frame_source_backend,
    select_ocr_backend,
    select_vlm_backend,
)
from glassbox.cognition import HeuristicTyper
from glassbox.config import AgentConfig, get_config
from glassbox.effector import Effector
from glassbox.geometry import content_size_for_crop, effector_frame_resolution, make_device_geometry
from glassbox.memory import save_utg, wrap_with_memory_if_enabled
from glassbox.obs import open_recorder, wrap_vlm_cache_if_enabled
from glassbox.perception.letterbox import LetterboxCrop
from glassbox.perception.stable import StabilityPolicy
from glassbox.phone import Phone, PhoneGestureConfig
from glassbox.platforms import DEFAULT_PLATFORM_REGISTRY, select_platform_backend

if TYPE_CHECKING:
    from glassbox.action.orchestrator import ActionOrchestrator
    from glassbox.boundaries import DeviceGeometry
    from glassbox.memory.graph import ScreenMemory
    from glassbox.obs.recorder import Recorder
    from glassbox.profile import Profile


class RuntimeUnavailable(RuntimeError):
    """Raised when the configured hardware/runtime path is unavailable."""


@dataclass
class PhoneRuntime:
    phone: Phone
    source: object
    effector: Effector
    recorder: Recorder | None = None
    memory: ScreenMemory | None = None
    action_orchestrator: ActionOrchestrator | None = None
    cfg: AgentConfig | None = None
    device_geometry: DeviceGeometry | None = None
    owns_source: bool = False
    owns_effector: bool = False
    owns_recorder: bool = False
    owns_memory: bool = False

    def close(self, *, close_source: bool | None = None, save_memory: bool = True) -> None:
        if self.owns_effector:
            with contextlib.suppress(Exception):
                self.effector.close()
        if self.recorder is not None and self.owns_recorder:
            with contextlib.suppress(Exception):
                self.recorder.close()
        if self.action_orchestrator is not None:
            with contextlib.suppress(Exception):
                self.action_orchestrator.close()
        if save_memory and self.memory is not None and self.owns_memory:
            save_memory_utg(self.memory, memory_dir=self.cfg.memory_dir if self.cfg else None)
        should_close_source = self.owns_source if close_source is None else close_source
        if should_close_source and hasattr(self.source, "close"):
            with contextlib.suppress(Exception):
                self.source.close()


def make_source(*, cfg: AgentConfig | None = None):
    cfg = cfg or get_config()
    backend = select_frame_source_backend(cfg)
    if backend == "avf" and cfg.no_hdmi:
        raise RuntimeUnavailable(
            "GLASSBOX_NO_HDMI=1 explicitly disables HDMI; set GLASSBOX_FRAME_DIR to use static images"
        )
    try:
        return DEFAULT_FRAME_SOURCE_REGISTRY.create(backend, cfg=cfg)
    except Exception as exc:
        if backend == "avf":
            raise RuntimeUnavailable(
                f"AVFFrameSource(index={cfg.hdmi_index}) failed to open: {exc}. "
                "Set GLASSBOX_FRAME_DIR=<dir> to use static images instead, or check the "
                "HDMI capture card and Terminal.app's Camera permission."
            ) from exc
        raise RuntimeUnavailable(str(exc)) from exc


def make_effector(
    source,
    *,
    cfg: AgentConfig | None = None,
    frame_resolution: tuple[int, int] | None = None,
    coordinate_space: str | None = None,
    device_geometry=None,
) -> Effector:
    cfg = cfg or get_config()
    coordinate_space = coordinate_space or "frame_px"
    backend = select_effector_backend(cfg)

    if backend == "picokvm":
        eff = DEFAULT_EFFECTOR_REGISTRY.create(
            backend,
            cfg=cfg,
            source=source,
            frame_resolution=frame_resolution,
            coordinate_space=coordinate_space,
            device_geometry=device_geometry,
        )
        preflight = eff.preflight()
        if not preflight.ok and preflight.fatal:
            raise RuntimeUnavailable(preflight.message)
        try:
            eff.connect()
        except Exception as exc:
            eff.close()
            if not getattr(cfg, "allow_noop_fallback", False):
                raise RuntimeUnavailable(
                    f"{backend} effector connect() failed: {exc}. "
                    "Confirm the configured hardware is connected, or set "
                    "GLASSBOX_ALLOW_NOOP_FALLBACK=1 for dry-run mode."
                ) from exc
            print(f"[runtime] {backend} effector connect() failed: {exc}")
            print("[runtime] falling back to NoOpEffector (GLASSBOX_ALLOW_NOOP_FALLBACK=1)")
            return DEFAULT_EFFECTOR_REGISTRY.create(
                "noop",
                cfg=cfg,
                source=source,
                frame_resolution=frame_resolution,
                coordinate_space=coordinate_space,
                device_geometry=device_geometry,
            )
        return eff

    return DEFAULT_EFFECTOR_REGISTRY.create(
        backend,
        cfg=cfg,
        source=source,
        frame_resolution=frame_resolution,
        coordinate_space=coordinate_space,
        device_geometry=device_geometry,
    )


def _crop_from_bbox(
    bbox: tuple[int, int, int, int],
    *,
    frame_size: tuple[int, int],
    phone_size: tuple[int, int],
) -> LetterboxCrop:
    x, y, w, h = (int(v) for v in bbox)
    if w <= 0 or h <= 0:
        raise RuntimeUnavailable(f"invalid crop bbox {bbox!r}")
    fw, fh = frame_size
    if x < 0 or y < 0 or x + w > fw or y + h > fh:
        raise RuntimeUnavailable(f"crop bbox {bbox!r} is outside frame {frame_size!r}")
    return LetterboxCrop(crop_bbox=(x, y, w, h), frame_size=frame_size, phone_size=phone_size)


def detect_crop(source, *, cfg: AgentConfig | None = None, device_geometry=None) -> LetterboxCrop | None:
    cfg = cfg or get_config()
    geometry = device_geometry or make_device_geometry(
        cfg,
        frame_size=getattr(source, "resolution", None),
    )
    phone_size = content_size_for_crop(cfg, geometry)
    crop_bbox = None
    if crop_bbox is not None:
        try:
            frame_size = source.resolution
        except Exception as exc:
            raise RuntimeUnavailable("configured crop bbox requires current frame resolution") from exc
        crop = _crop_from_bbox(crop_bbox, frame_size=frame_size, phone_size=phone_size)
        print(f"[runtime] using configured crop bbox={crop.crop_bbox}")
        return crop
    last_exc: Exception | None = None
    attempts = 1
    try:
        for _ in range(attempts):
            frame = source.snapshot()
            try:
                crop = LetterboxCrop.auto_detect(frame.img, phone_size=phone_size)
                break
            except Exception as exc:
                last_exc = exc
        else:
            raise last_exc or RuntimeUnavailable("no frame available for crop detection")
    except Exception as exc:
        print(f"[runtime] letterbox auto-detect failed, using full frame: {exc}")
        return None
    try:
        if crop.cropped_size == source.resolution and crop.cropped_size == phone_size:
            return None
    except Exception:
        pass
    print(
        f"[runtime] letterbox crop detected bbox={crop.crop_bbox} "
        f"cropped={crop.cropped_size} phone={crop.phone_size}"
    )
    return crop


def save_memory_utg(memory: ScreenMemory, *, memory_dir: str | None) -> None:
    save_utg(memory.utg, memory_dir=memory_dir)


def build_phone(
    *,
    source,
    profile: Profile | None = None,
    cfg: AgentConfig | None = None,
    ocr=None,
    effector: Effector | None = None,
    crop: LetterboxCrop | None = None,
    kimi=None,
    recorder: Recorder | None = None,
    memory: ScreenMemory | None = None,
) -> PhoneRuntime:
    cfg = cfg or get_config()
    try:
        source_frame_size = source.resolution
    except Exception:
        source_frame_size = None
    device_geometry = make_device_geometry(cfg, frame_size=source_frame_size)
    provided_effector = effector is not None
    provided_recorder = recorder is not None
    provided_memory = memory is not None
    if ocr is None:
        try:
            ocr = DEFAULT_OCR_REGISTRY.create(select_ocr_backend(cfg), cfg=cfg)
        except KeyError as exc:
            raise RuntimeUnavailable(
                f"GLASSBOX_OCR={cfg.ocr!r} is not supported; expected 'vision' or 'ocrmac'"
            ) from exc

    if crop is None:
        crop = detect_crop(source, cfg=cfg, device_geometry=device_geometry)

    if effector is None:
        coordinate_space = "frame_px"
        effector_resolution = effector_frame_resolution(
            cfg,
            device_geometry,
            crop_present=crop is not None,
        )
        effector = make_effector(
            source,
            cfg=cfg,
            frame_resolution=effector_resolution,
            coordinate_space=coordinate_space,
            device_geometry=device_geometry,
        )
    else:
        coordinate_space = getattr(effector, "coordinate_space", None)

    try:
        frame_size = crop.cropped_size if crop is not None else source.resolution
    except AttributeError:
        frame_size = None
    typer = HeuristicTyper(frame_size=frame_size)

    bundle_id = cfg.memory_bundle or (profile.app.bundle_id if profile else None)
    if bundle_id is None and memory is not None:
        bundle_id = getattr(getattr(memory, "utg", None), "bundle_id", None)
    app_version = profile.app.version if profile and not cfg.memory_bundle else None
    profile_name = profile.app.bundle_id if profile else (cfg.memory_bundle or "?")

    scene_classifiers = []
    from glassbox.app_policies import DEFAULT_APP_POLICY_REGISTRY

    app_scene_classifier = DEFAULT_APP_POLICY_REGISTRY.scene_classifier_for(bundle_id)
    if app_scene_classifier is not None:
        def _classify_app_scene(scene, viewport_size):
            return app_scene_classifier.classify(scene, viewport_size=viewport_size)

        scene_classifiers.append(_classify_app_scene)

    if recorder is None and cfg.recording_dir:
        recorder = open_recorder(cfg.recording_dir, meta={"profile": profile_name})

    if memory is None:
        memory = wrap_with_memory_if_enabled(
            bundle_id=bundle_id,
            app_version=app_version,
            enabled=cfg.enable_memory,
            memory_dir=cfg.memory_dir,
        )

    vlm_backend = select_vlm_backend(cfg)
    if kimi is None and vlm_backend is not None:
        kimi = wrap_vlm_cache_if_enabled(
            DEFAULT_VLM_REGISTRY.create(vlm_backend, cfg=cfg),
            cache_dir=cfg.vlm_cache_dir or cfg.kimi_cache_dir,
        )

    coldstart = None
    if cfg.enable_coldstart:
        if memory is None or not bundle_id:
            raise RuntimeUnavailable(
                "GLASSBOX_ENABLE_COLDSTART=1 requires screen memory and a bundle id; "
                "set GLASSBOX_ENABLE_MEMORY=1 plus GLASSBOX_MEMORY_BUNDLE or GLASSBOX_PROFILE_BUNDLE"
            )
        from glassbox.cognition.coldstart import ColdStartAnnotator

        # a raw client — the annotator calls .chat() directly, not describe_scene,
        # so it does not go through the describe-scene disk cache wrapper.
        if vlm_backend is None:
            vlm_backend = "moonshot"
        coldstart = ColdStartAnnotator(
            DEFAULT_VLM_REGISTRY.create(vlm_backend, cfg=cfg),
            max_calls=cfg.coldstart_max_calls,
        )

    action_orchestrator = None
    if cfg.computer_use_artifact_dir:
        from glassbox.action import ActionOrchestrator, RiskPolicy
        from glassbox.action.actuation_profile import load_actuation_profile
        from glassbox.action.seeds import DEFAULT_RECOVERY_SEED, load_json_seed
        from glassbox.obs.artifacts import ArtifactStore

        actuation_profile = load_actuation_profile(
            platform=cfg.platform,
            device_model=cfg.phone_model,
            profile_dir=cfg.actuation_profile_dir,
        )
        actuation_seed = load_json_seed(cfg.actuation_seed_path)
        if actuation_seed:
            actuation_profile.apply_seed(actuation_seed)
        recovery_seed = load_json_seed(cfg.recovery_seed_path, default=DEFAULT_RECOVERY_SEED)
        store = ArtifactStore(
            cfg.computer_use_artifact_dir,
            trace_level=cfg.computer_use_trace_level,
            manifest_extra={
                "backend": {
                    "name": effector.__class__.__name__,
                    "transport": "picokvm" if cfg.picokvm else "none",
                },
                "device": {
                    "name": device_geometry.model,
                    "model": device_geometry.model,
                    "os_version": None,
                    "locale": None,
                },
            },
        )
        action_orchestrator = ActionOrchestrator(
            store,
            risk_policy=RiskPolicy(guarded=cfg.computer_use_guarded),
            semantic_fail_fast=cfg.computer_use_semantic_fail_fast,
            observation_producer_mode=cfg.computer_use_observation_producer_mode,
            platform=cfg.platform,
            actuation_profile=actuation_profile,
            actuation_profile_dir=cfg.actuation_profile_dir,
            recovery_seed=recovery_seed,
        )

    platform = DEFAULT_PLATFORM_REGISTRY.create(
        select_platform_backend(cfg, bundle_id=bundle_id),
        cfg=cfg,
    )
    if platform.scene_classifier is not None:
        def _classify_platform_scene(scene, viewport_size):
            return platform.scene_classifier.classify(scene, viewport_size=viewport_size)

        scene_classifiers.insert(0, _classify_platform_scene)

    icon_map_factory = getattr(platform, "create_springboard_icon_map", None)
    icon_map = icon_map_factory() if callable(icon_map_factory) else None

    phone = Phone(
        source=source,
        ocr=ocr,
        effector=effector,
        profile=profile,
        typer=typer,
        kimi=kimi,
        recorder=recorder,
        memory=memory,
        coldstart=coldstart,
        crop=crop,
        coordinate_space=coordinate_space,
        stability_policy=StabilityPolicy(
            enabled=cfg.stable_after_action,
            timeout=cfg.stable_timeout,
            diff_threshold=cfg.stable_diff_threshold,
            consecutive=cfg.stable_consecutive,
            poll_interval=cfg.stable_poll_interval,
        ),
        scene_classifiers=scene_classifiers,
        platform_scene_classifier=platform.scene_classifier,
        action_fail_fast=getattr(cfg, "action_fail_fast", True),
        action_orchestrator=action_orchestrator,
        app_labels=(profile.app.name,) if profile else None,
        icon_map=icon_map,
        safe_area_provider=platform.safe_area,
        springboard_provider=platform.springboard,
        recovery_provider=platform.recovery,
        device_geometry=device_geometry,
        gesture_config=PhoneGestureConfig(
            wheel_ticks_per_scroll=cfg.wheel_ticks_per_scroll,
            wheel_invert=cfg.wheel_invert,
        ),
    )
    return PhoneRuntime(
        phone=phone,
        source=source,
        effector=effector,
        recorder=recorder,
        memory=memory,
        action_orchestrator=action_orchestrator,
        cfg=cfg,
        device_geometry=device_geometry,
        owns_effector=not provided_effector,
        owns_recorder=(not provided_recorder and recorder is not None),
        owns_memory=(not provided_memory and memory is not None),
    )
