"""glassbox.cognition — visual understanding layer

base    — pydantic schema (Box / UIElement / Scene / WhiteboxHint)
Upcoming (M2+):
    ocr            Apple Vision OCR
    template       OpenCV template matching
    heuristic      Layer 2 heuristic typing
    vlm_kimi       Kimi K2.6 (primary VLM)
    vlm_claude     Claude Opus 4.7 Computer Use (fallback)
    hybrid         three-layer dispatcher
"""

from glassbox.cognition.asset_match import match_asset
from glassbox.cognition.base import (
    ActionType,
    Box,
    ElementType,
    Scene,
    UIElement,
    WhiteboxHint,
)
from glassbox.cognition.contracts import (
    COGNITION_CONTRACT_VERSION,
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    IconBox,
    SceneClassification,
    SceneClassificationProjector,
    TextRegion,
    VLMCacheKeyPayload,
    VLMRequest,
    VLMResult,
    VLMStageOutcome,
)
from glassbox.cognition.heuristic import (
    DEFAULT_RULES,
    HeuristicTyper,
    TypeGuess,
    find_button,
    find_by_intent,
    find_by_type,
    find_by_whitebox_hint,
)
from glassbox.cognition.ocr import AppleVisionOCR, find_text
from glassbox.cognition.ocr_contract import (
    LegacyUIElementOCRAdapter,
    ocr_results_to_elements,
    text_region_to_element,
    text_regions_to_elements,
)
from glassbox.cognition.ocr_vision import VisionOCR
from glassbox.cognition.som import render_set_of_mark
from glassbox.cognition.text_match import (
    MINUS_ALIASES,
    canonical_label,
    compact_text,
    norm_text,
    ocr_compact_text,
    text_contains,
    texts_match,
)
from glassbox.cognition.vlm_gate import (
    VLMEscalationGate,
    VLMGateInput,
    VLMGateState,
    escalation_triggers,
)
from glassbox.cognition.vlm_kimi import (
    KimiAnthropic,
    KimiResponse,
    KimiVL,
    MoonshotAnthropicVLM,
    SiliconFlowVLM,
    VLMResponse,
    enrich_scene,
    make_kimi_client,
    make_vlm_client,
    vlm_stage_outcome_from_result,
)
from glassbox.cognition.whitebox import apply_whitebox

__all__ = [
    "COGNITION_CONTRACT_VERSION",
    "DEFAULT_RULES",
    "DEFAULT_SCENE_CLASSIFICATION_PROJECTOR",
    "MINUS_ALIASES",
    "ActionType",
    "AppleVisionOCR",
    "Box",
    "ElementType",
    "HeuristicTyper",
    "IconBox",
    "KimiAnthropic",
    "KimiResponse",
    "KimiVL",
    "LegacyUIElementOCRAdapter",
    "MoonshotAnthropicVLM",
    "Scene",
    "SceneClassification",
    "SceneClassificationProjector",
    "SiliconFlowVLM",
    "TextRegion",
    "TypeGuess",
    "UIElement",
    "VLMCacheKeyPayload",
    "VLMEscalationGate",
    "VLMGateInput",
    "VLMGateState",
    "VLMRequest",
    "VLMResponse",
    "VLMResult",
    "VLMStageOutcome",
    "VisionOCR",
    "WhiteboxHint",
    "apply_whitebox",
    "canonical_label",
    "compact_text",
    "enrich_scene",
    "escalation_triggers",
    "find_button",
    "find_by_intent",
    "find_by_type",
    "find_by_whitebox_hint",
    "find_text",
    "make_kimi_client",
    "make_vlm_client",
    "match_asset",
    "norm_text",
    "ocr_compact_text",
    "ocr_results_to_elements",
    "render_set_of_mark",
    "text_contains",
    "text_region_to_element",
    "text_regions_to_elements",
    "texts_match",
    "vlm_stage_outcome_from_result",
]
