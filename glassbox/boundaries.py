"""Public architecture boundary protocols.

This module names the extension seams described in
`docs/design/architecture_boundaries.md`. Concrete backends can adapt to these
protocols without importing the runtime assembler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from glassbox.cognition.base import Box, Scene
from glassbox.cognition.contracts import (
    IconBox,
    SceneClassification,
    SceneClassificationPrior,
    TextRegion,
    VLMRequest,
    VLMResult,
)
from glassbox.effector import Effector
from glassbox.perception.source import Frame
from glassbox.verification.verifiers import SemanticOutcome, VerifierInput

ARCHITECTURE_BOUNDARY_CONTRACT_VERSION = 2


@dataclass(frozen=True)
class DeviceGeometry:
    model: str
    frame_size: tuple[int, int] | None = None
    phone_size: tuple[int, int] | None = None
    phone_points: tuple[int, int] | None = None


@dataclass(frozen=True)
class RecoverySignal:
    kind: str
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepContext:
    run_id: str | None = None
    driver: str | None = None
    coordinate_space: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class AppLaunchTarget:
    bundle_id: str
    labels: tuple[str, ...]
    aliases: tuple[str, ...] = ()


class FrameSource(Protocol):
    resolution: tuple[int, int]
    fps: float
    coordinate_space: str

    def snapshot(self) -> Frame: ...
    def close(self) -> None: ...


class OCR(Protocol):
    def recognize(self, image: Frame, *, roi: Box | None = None) -> list[TextRegion]: ...


class VLM(Protocol):
    def describe_scene(self, request: VLMRequest) -> VLMResult: ...


class IconDetector(Protocol):
    def detect(
        self,
        image: Frame,
        *,
        text_regions: list[TextRegion] | None = None,
        roi: Box | None = None,
    ) -> tuple[IconBox, ...]: ...


class SceneClassifier(Protocol):
    def classify(
        self,
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None = None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None: ...


class AppSceneClassifier(Protocol):
    def classify(
        self,
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None = None,
        prior: SceneClassificationPrior | None = None,
    ) -> SceneClassification | None: ...


class SafeAreaProvider(Protocol):
    def bottom_hit_point(
        self,
        viewport_size: tuple[int, int],
        *,
        x: int | None = None,
        y: int | None = None,
        element_type: str | None = None,
        fallback_x_fraction: float = 0.5,
    ) -> tuple[int, int]: ...


class RecoveryProvider(Protocol):
    def detect(self, scene: Scene) -> RecoverySignal | None: ...
    def recover(self, ctx: StepContext) -> bool: ...


class ActionHost(Protocol):
    """Narrow host surface consumed by action/crawl collaborators."""

    @property
    def last_frame(self) -> Frame | None: ...
    @property
    def last_scene(self) -> Scene | None: ...
    @property
    def last_stable_frame(self) -> bool | None: ...
    def viewport_size(self) -> tuple[int, int]: ...
    def backend_capabilities(self) -> Any | None: ...
    def effector_backend(self) -> str: ...
    def effector_coordinate_space(self) -> str: ...
    def record_action(
        self,
        op: str,
        *,
        result: Any | None = None,
        **kwargs: Any,
    ) -> None: ...


def action_host_last_frame(host: object) -> Frame | None:
    frame = getattr(host, "last_frame", None)
    if frame is not None:
        return frame
    # Transitional duck-test compatibility while P1 moves callers to ActionHost.
    return getattr(host, "_last_frame", None)


def action_host_last_scene(host: object) -> Scene | None:
    scene = getattr(host, "last_scene", None)
    if scene is not None:
        return scene
    # Transitional duck-test compatibility while P1 moves callers to ActionHost.
    return getattr(host, "_last_scene", None)


def action_host_backend_capabilities(host: object) -> Any | None:
    capabilities = getattr(host, "backend_capabilities", None)
    if callable(capabilities):
        try:
            return capabilities()
        except Exception:
            return None
    # Transitional duck-test compatibility while P1 moves callers to ActionHost.
    legacy = getattr(host, "_backend_capabilities", None)
    if callable(legacy):
        try:
            return legacy()
        except Exception:
            return None
    return None


def action_host_effector_backend(host: object) -> str:
    backend = getattr(host, "effector_backend", None)
    if callable(backend):
        return str(backend())
    # Transitional duck-test compatibility while P1 moves callers to ActionHost.
    legacy = getattr(host, "_effector_backend", None)
    return str(legacy()) if callable(legacy) else "unknown"


class SpringboardProvider(Protocol):
    def open_app(
        self,
        phone,
        target: AppLaunchTarget,
        *,
        max_pages: int = 8,
        settle_s: float = 0.8,
        icon_map=None,
    ) -> bool: ...
    def foreground_app(
        self,
        phone,
        target: AppLaunchTarget,
        *,
        settle_s: float = 0.8,
        icon_map=None,
    ) -> bool: ...
    def go_home(self, ctx: StepContext) -> bool: ...


class Platform(Protocol):
    name: str
    scene_classifier: SceneClassifier | None
    safe_area: SafeAreaProvider | None
    recovery: RecoveryProvider | None
    springboard: SpringboardProvider | None

    def supports(self, capability: str) -> bool: ...
    def create_springboard_icon_map(self) -> Any | None: ...


class Verifier(Protocol):
    name: str
    version: str

    def verify(self, input: VerifierInput) -> SemanticOutcome: ...


class CrawlPolicy(Protocol):
    def classify(self, scene: Scene) -> str: ...
    def candidates(self, scene: Scene) -> list[dict[str, Any]]: ...
    def is_safe(self, action: dict[str, Any], scene: Scene) -> bool: ...
    def should_stop(self, scene: Scene, history: list[dict[str, Any]]) -> bool: ...


__all__ = [
    "ARCHITECTURE_BOUNDARY_CONTRACT_VERSION",
    "OCR",
    "VLM",
    "ActionHost",
    "AppLaunchTarget",
    "AppSceneClassifier",
    "CrawlPolicy",
    "DeviceGeometry",
    "Effector",
    "FrameSource",
    "IconDetector",
    "Platform",
    "RecoveryProvider",
    "RecoverySignal",
    "SafeAreaProvider",
    "SceneClassifier",
    "SpringboardProvider",
    "StepContext",
    "Verifier",
    "action_host_backend_capabilities",
    "action_host_effector_backend",
    "action_host_last_frame",
    "action_host_last_scene",
]
