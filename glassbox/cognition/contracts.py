"""Boundary contracts for cognition seams and Scene classification.

These types are intentionally thin: seam implementations return facts, while
pipeline stages decide how those facts are projected onto `Scene`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.perception.source import Frame

COGNITION_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class TextRegion:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    text: str
    box: Box
    confidence: float


@dataclass(frozen=True)
class IconBox:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    box: Box
    label: str | None
    confidence: float


ClassificationSource = Literal["platform", "app", "vlm"]


@dataclass(frozen=True)
class SceneClassification:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    page_id: str | None = None
    platform_scene_kind: str | None = None
    semantic_scene_type: str | None = None
    classification_fields: dict[str, object] = field(default_factory=dict)
    confidence: float = 0.0
    source: ClassificationSource = "app"
    safe_actions: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class VLMRequest:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    image: Frame
    elements: list[UIElement]
    scene_hint: str | None
    system_prompt: str
    set_of_mark: bool = False


@dataclass(frozen=True)
class VLMCacheKeyPayload:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    image_bytes_hash: str
    elements: tuple[dict, ...]
    scene_hint: str | None
    prompt_key: str
    set_of_mark: bool
    effective_model: str


@dataclass(frozen=True)
class VLMResult:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    parsed: dict | None
    raw_content: str
    model: str
    usage: dict
    elapsed_ms: float


@dataclass(frozen=True)
class VLMStageOutcome:
    CONTRACT_VERSION: ClassVar[int] = COGNITION_CONTRACT_VERSION

    status: str
    error: str | None = None
    element_intents: dict[int, str] = field(default_factory=dict)
    classification: SceneClassification | None = None


class SceneClassificationProjector:
    """The only stage that writes classification fields onto `Scene`."""

    def __init__(
        self,
        *,
        scene_type_priority: tuple[ClassificationSource, ...] = ("vlm", "app", "platform"),
    ):
        self.scene_type_priority = scene_type_priority

    def project(
        self,
        scene: Scene,
        classifications: list[SceneClassification],
        *,
        overwrite_scene_type: bool = False,
    ) -> Scene:
        if not classifications:
            return scene

        by_source = {item.source: item for item in classifications}
        for item in classifications:
            if item.platform_scene_kind:
                scene.platform_scene_kind = item.platform_scene_kind
            if item.page_id:
                scene.page_id = item.page_id
            if item.safe_actions:
                scene.safe_actions = list(item.safe_actions)
            if item.evidence:
                scene.classification_evidence = list(item.evidence)
            if item.classification_fields:
                for key, value in item.classification_fields.items():
                    if not key.startswith("classification_"):
                        continue
                    if key not in Scene.model_fields:
                        continue
                    setattr(scene, key, value)

        semantic = self._choose_semantic_scene_type(by_source)
        if semantic:
            scene.semantic_scene_type = semantic

        preferred = self._choose_scene_type(by_source)
        if preferred and (overwrite_scene_type or not scene.scene_type):
            scene.scene_type = preferred

        winner = self._winner(by_source)
        if winner is not None:
            scene.classification_source = winner.source
            scene.classification_confidence = winner.confidence
        return scene

    def _choose_scene_type(self, by_source: dict[ClassificationSource, SceneClassification]) -> str | None:
        for source in self.scene_type_priority:
            item = by_source.get(source)
            if item is None:
                continue
            if item.semantic_scene_type:
                return item.semantic_scene_type
            if item.platform_scene_kind:
                return item.platform_scene_kind
        return None

    @staticmethod
    def _choose_semantic_scene_type(
        by_source: dict[ClassificationSource, SceneClassification],
    ) -> str | None:
        vlm = by_source.get("vlm")
        if vlm is not None and vlm.semantic_scene_type:
            return vlm.semantic_scene_type
        return None

    def _winner(
        self,
        by_source: dict[ClassificationSource, SceneClassification],
    ) -> SceneClassification | None:
        for source in self.scene_type_priority:
            item = by_source.get(source)
            if item is not None:
                return item
        return None


DEFAULT_SCENE_CLASSIFICATION_PROJECTOR = SceneClassificationProjector()
