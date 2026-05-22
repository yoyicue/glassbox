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
class Insets:
    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0


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
    ) -> SceneClassification | None: ...


class AppSceneClassifier(Protocol):
    def classify(
        self,
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> SceneClassification | None: ...


class SafeAreaProvider(Protocol):
    def insets(self, scene: Scene) -> Insets: ...
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
    "AppLaunchTarget",
    "AppSceneClassifier",
    "CrawlPolicy",
    "DeviceGeometry",
    "Effector",
    "FrameSource",
    "IconDetector",
    "Insets",
    "Platform",
    "RecoveryProvider",
    "RecoverySignal",
    "SafeAreaProvider",
    "SceneClassifier",
    "SpringboardProvider",
    "StepContext",
    "Verifier",
]
