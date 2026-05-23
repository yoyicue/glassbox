"""Pick-one backend registries for architecture seams."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Generic, TypeVar

from glassbox.cognition import AppleVisionOCR, IconDetectFunctionAdapter, VisionOCR
from glassbox.cognition.ocr_contract import LegacyUIElementOCRAdapter
from glassbox.cognition.vlm_kimi import MoonshotAnthropicVLM, SiliconFlowVLM
from glassbox.config import AgentConfig
from glassbox.effector import Effector, NoOpEffector
from glassbox.perception import AVFFrameSource, StaticFrameSource

T = TypeVar("T")
Factory = Callable[..., T]


@dataclass(frozen=True)
class BackendRegistration(Generic[T]):
    name: str
    factory: Factory[T]
    priority: int = 0


class BackendRegistry(Generic[T]):
    def __init__(
        self,
        *,
        entry_point_group: str,
        registrations: Iterable[BackendRegistration[T]] | None = None,
        load_entry_points: bool = True,
    ):
        self.entry_point_group = entry_point_group
        self._by_name: dict[str, BackendRegistration[T]] = {}
        self._entry_points_loaded = not load_entry_points
        for registration in registrations or ():
            self.register(registration)

    def register(self, registration: BackendRegistration[T]) -> None:
        current = self._by_name.get(registration.name)
        if current is None or registration.priority >= current.priority:
            self._by_name[registration.name] = registration

    def names(self) -> tuple[str, ...]:
        self._load_entry_points_once()
        return tuple(sorted(self._by_name))

    def resolve(self, name: str) -> BackendRegistration[T]:
        self._load_entry_points_once()
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(
                f"unknown backend {name!r} for {self.entry_point_group}; "
                f"registered={sorted(self._by_name)}"
            ) from exc

    def create(self, name: str, **kwargs) -> T:
        return self.resolve(name).factory(**kwargs)

    def _load_entry_points_once(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        try:
            selected = entry_points(group=self.entry_point_group)
        except TypeError:
            selected = entry_points().get(self.entry_point_group, ())
        for entry_point in selected:
            loaded = entry_point.load()
            for registration in _coerce_registrations(loaded):
                self.register(registration)


def _coerce_registrations(value) -> Iterable[BackendRegistration]:
    if isinstance(value, BackendRegistration):
        return (value,)
    if callable(value):
        return _coerce_registrations(value())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        registrations: list[BackendRegistration] = []
        for item in value:
            if not isinstance(item, BackendRegistration):
                raise TypeError(f"backend entry point returned unsupported item: {item!r}")
            registrations.append(item)
        return tuple(registrations)
    raise TypeError(f"backend entry point returned unsupported value: {value!r}")


def _static_frame_source_factory(*, cfg: AgentConfig):
    if not cfg.frame_dir:
        raise ValueError("static FrameSource requires GLASSBOX_FRAME_DIR")
    pngs = sorted(Path(cfg.frame_dir).glob("*.png"))
    if not pngs:
        raise ValueError(f"GLASSBOX_FRAME_DIR={cfg.frame_dir} found no png")
    return StaticFrameSource([str(p) for p in pngs])


def _avf_frame_source_factory(*, cfg: AgentConfig):
    src = AVFFrameSource(
        device_index=cfg.hdmi_index,
        fps_target=cfg.hdmi_fps,
        auto_recover_capture=cfg.auto_recover_capture,
    )
    src.open()
    return src


def _picokvm_frame_source_factory(*, cfg: AgentConfig):
    _ = cfg
    from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
    from glassbox.perception.picokvm_source import PicoKVMFrameSource

    src = PicoKVMFrameSource(config=PicoKVMEffectorConfig())
    src.open()
    return src


def select_frame_source_backend(cfg: AgentConfig) -> str:
    if cfg.picokvm:
        return "picokvm_stream"
    return "static" if cfg.frame_dir else "avf"


def static_frame_source_registration() -> BackendRegistration:
    return BackendRegistration(name="static", factory=_static_frame_source_factory)


def avf_frame_source_registration() -> BackendRegistration:
    return BackendRegistration(name="avf", factory=_avf_frame_source_factory)


def picokvm_frame_source_registration() -> BackendRegistration:
    return BackendRegistration(name="picokvm_stream", factory=_picokvm_frame_source_factory)


def _noop_effector_factory(*, cfg: AgentConfig, coordinate_space: str, **_kwargs) -> Effector:
    _ = cfg
    return NoOpEffector(coordinate_space=coordinate_space)


def _picokvm_effector_factory(*, cfg: AgentConfig, coordinate_space: str, **kwargs) -> Effector:
    _ = cfg
    from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
    from glassbox.effectors.picokvm.effector import PicoKVMEffector

    return PicoKVMEffector(config=PicoKVMEffectorConfig(), coordinate_space=coordinate_space, **kwargs)


def select_effector_backend(cfg: AgentConfig) -> str:
    explicit = "effector_backend" in getattr(cfg, "model_fields_set", set())
    if not explicit and cfg.picokvm:
        return "picokvm"
    name = str(getattr(cfg, "effector_backend", "noop") or "noop").strip().lower()
    return name or "noop"


def noop_effector_registration() -> BackendRegistration:
    return BackendRegistration(name="noop", factory=_noop_effector_factory)


def picokvm_effector_registration() -> BackendRegistration:
    return BackendRegistration(name="picokvm", factory=_picokvm_effector_factory)


def _ocr_languages(cfg: AgentConfig) -> tuple[str, ...]:
    # Locale-driven OCR recognition languages. Default (zh-Hans) resolves to
    # ("zh-Hans", "en-US") — identical to the previous hardcoded default.
    from glassbox.locale import resolve_locale

    return resolve_locale(cfg).ocr_languages


def _ocrmac_factory(*, cfg: AgentConfig):
    return LegacyUIElementOCRAdapter(AppleVisionOCR(languages=list(_ocr_languages(cfg))))


def _vision_ocr_factory(*, cfg: AgentConfig):
    return LegacyUIElementOCRAdapter(VisionOCR(languages=_ocr_languages(cfg)))


def select_ocr_backend(cfg: AgentConfig) -> str:
    return str(cfg.ocr).lower()


def ocrmac_registration() -> BackendRegistration:
    return BackendRegistration(name="ocrmac", factory=_ocrmac_factory)


def vision_ocr_registration() -> BackendRegistration:
    return BackendRegistration(name="vision", factory=_vision_ocr_factory)


def _icon_detector_factory(*, cfg: AgentConfig):
    return IconDetectFunctionAdapter(backend=select_icon_detector_backend(cfg))


def classical_icon_detector_registration() -> BackendRegistration:
    return BackendRegistration(name="classical", factory=_icon_detector_factory)


def select_icon_detector_backend(cfg: AgentConfig) -> str:
    return str(getattr(cfg, "icon_detector", "classical")).lower()


def _moonshot_vlm_factory(*, cfg: AgentConfig):
    _ = cfg
    return MoonshotAnthropicVLM()


def _siliconflow_vlm_factory(*, cfg: AgentConfig):
    _ = cfg
    return SiliconFlowVLM()


def moonshot_vlm_registration() -> BackendRegistration:
    return BackendRegistration(name="moonshot", factory=_moonshot_vlm_factory)


def siliconflow_vlm_registration() -> BackendRegistration:
    return BackendRegistration(name="siliconflow", factory=_siliconflow_vlm_factory)


_VLM_BACKEND_ALIASES = {
    "anthropic": "moonshot",
    "ms": "moonshot",
    "kimi": "moonshot",
    "kimi_anthropic": "moonshot",
    "siliconflow": "siliconflow",
    "sf": "siliconflow",
    "openai": "siliconflow",
    "kimi_siliconflow": "siliconflow",
}


def canonicalize_vlm_backend(name: str) -> str:
    normalized = str(name).strip().lower()
    return _VLM_BACKEND_ALIASES.get(normalized, normalized)


def select_vlm_backend(cfg: AgentConfig) -> str | None:
    enabled = cfg.enable_vlm if cfg.enable_vlm is not None else cfg.enable_kimi
    if not enabled:
        return None
    return canonicalize_vlm_backend(getattr(cfg, "vlm", "moonshot"))


DEFAULT_FRAME_SOURCE_REGISTRY = BackendRegistry(
    entry_point_group="glassbox.frame_sources",
    registrations=(
        static_frame_source_registration(),
        avf_frame_source_registration(),
        picokvm_frame_source_registration(),
    ),
)


DEFAULT_EFFECTOR_REGISTRY = BackendRegistry(
    entry_point_group="glassbox.effectors",
    registrations=(
        noop_effector_registration(),
        picokvm_effector_registration(),
    ),
)


DEFAULT_OCR_REGISTRY = BackendRegistry(
    entry_point_group="glassbox.ocr",
    registrations=(
        ocrmac_registration(),
        vision_ocr_registration(),
    ),
)


DEFAULT_ICON_DETECTOR_REGISTRY = BackendRegistry(
    entry_point_group="glassbox.icon_detectors",
    registrations=(
        classical_icon_detector_registration(),
    ),
)


DEFAULT_VLM_REGISTRY = BackendRegistry(
    entry_point_group="glassbox.vlm",
    registrations=(
        moonshot_vlm_registration(),
        siliconflow_vlm_registration(),
    ),
)


__all__ = [
    "DEFAULT_EFFECTOR_REGISTRY",
    "DEFAULT_FRAME_SOURCE_REGISTRY",
    "DEFAULT_ICON_DETECTOR_REGISTRY",
    "DEFAULT_OCR_REGISTRY",
    "DEFAULT_VLM_REGISTRY",
    "BackendRegistration",
    "BackendRegistry",
    "avf_frame_source_registration",
    "canonicalize_vlm_backend",
    "classical_icon_detector_registration",
    "moonshot_vlm_registration",
    "noop_effector_registration",
    "ocrmac_registration",
    "picokvm_effector_registration",
    "picokvm_frame_source_registration",
    "select_effector_backend",
    "select_frame_source_backend",
    "select_icon_detector_backend",
    "select_ocr_backend",
    "select_vlm_backend",
    "siliconflow_vlm_registration",
    "static_frame_source_registration",
    "vision_ocr_registration",
]
