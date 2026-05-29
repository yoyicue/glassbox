"""glassbox/cognition/base.py — perception layer data schema

Output contract of the three-layer perception pipeline:
  Layer 1 (geometric)        → populates box / text / confidence
  Layer 2 (heuristic typing) → populates type / suggested_actions
  Layer 3 (VLM semantic)     → populates intent_label / semantic_scene_type / available_intents
  (whitebox)                 → populates whitebox_hint (when a Tier 1+ profile hits)

See docs/design/gui_understanding.md §7 for details.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ─── basic geometry ──────────────────────────────────────────────────
class Box(BaseModel):
    """Screen pixel coordinates. Convention: top-left origin, x to the right, y downward (cv2 style)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h


# ─── enums ───────────────────────────────────────────────────────────
ElementType = Literal[
    "text",            # raw text from OCR, not yet classified
    "button",
    "input",
    "tab_bar_item",
    "nav_back",
    "list_item",
    "switch",
    "slider",
    "image",
    "modal_sheet",
    "status_bar",      # iOS system status bar (time / Wi-Fi / battery / signal) — skipped during walkthrough
    "unknown",
]

ActionType = Literal[
    "tap",
    "long_press",
    "double_tap",
    "type",
    "swipe_left",
    "swipe_right",
    "swipe_up",
    "swipe_down",
    "drag",
]


# ─── whitebox hint (populated when a Tier 1+ profile hits) ───────────
class WhiteboxHint(BaseModel):
    """Whitebox hint from an app profile.

    Tier 0 (pure vision) leaves this None. Tier 1+ (an app profile is
    available) populates it based on what hits.
    See docs/roadmap.md for the discussion of Tier 0/1/2/3.
    """

    vc_name: str | None = None          # current / target ViewController name ("ListViewController")
    accessibility_id: str | None = None  # element accessibility identifier ("nextBtn")
    asset_match: str | None = None       # matched asset catalog resource name ("send_icon@2x")
    deep_link: str | None = None          # the deep link equivalent to this element
    swift_class: str | None = None        # Swift class name of the element / container


# ─── UI element ──────────────────────────────────────────────────────
class UIElement(BaseModel):
    """A UI element after perception.

    Layer 1 required: type='text', box, text, confidence.
    Layer 2 upgrade: type → button/input/..., suggested_actions.
    Layer 3 populates: intent_label.
    whitebox (optional): whitebox_hint.
    """

    type: ElementType
    box: Box
    text: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_actions: list[ActionType] = Field(default_factory=list)
    type_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    type_source: str | None = None
    type_evidence: list[str] = Field(default_factory=list)

    # populated by Layer 3
    intent_label: str | None = None
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    intent_source: str | None = None
    # Set-of-Mark number (shown to the VLM)
    element_id: int = 0

    # Optional policy-provided hit point for target-bearing actuation.
    preferred_tap_point: tuple[int, int] | None = None

    # populated by Tier 1+ profile
    whitebox_hint: WhiteboxHint | None = None


# ─── Scene (full perception result of one frame) ─────────────────────
class Scene(BaseModel):
    """Overall description of one frame after Layer 1+2 (+3, if invoked).

    Cached with the frame perceptual hash as key (see docs/design/gui_understanding.md §6.2).
    """

    frame_id: int
    timestamp: float                       # monotonic seconds
    elements: list[UIElement] = Field(default_factory=list)
    source_frame_ids: list[int] = Field(default_factory=list)
    source_timestamps: list[float] = Field(default_factory=list)
    observation_mode: str = "raw"
    stable_frame: bool | None = None
    viewport_size: tuple[int, int] | None = None

    # populated by Layer 3 (optional)
    scene_type: str | None = None          # legacy compatibility alias
    semantic_scene_type: str | None = None  # "login_form" / "chat_list" / ...
    context: str | None = None              # free text, status note from the VLM
    available_intents: list[str] = Field(default_factory=list)
    vlm_described: bool = False
    vlm_status: str | None = None
    vlm_model: str | None = None
    vlm_scene_hint: str | None = None
    vlm_elapsed_ms: int | None = None
    vlm_usage: dict[str, Any] = Field(default_factory=dict)
    vlm_error: str | None = None
    vlm_requested_element_ids: list[int] = Field(default_factory=list)
    vlm_returned_element_ids: list[int] = Field(default_factory=list)
    vlm_missing_element_ids: list[int] = Field(default_factory=list)
    vlm_intent_coverage: float | None = None

    # populated by platform/app classifiers. These fields are facts already
    # attached to the Scene; generic memory stores them but does not infer them.
    platform_scene_kind: str | None = None
    page_id: str | None = None
    safe_actions: list[str] = Field(default_factory=list)
    classification_source: str | None = None
    classification_confidence: float | None = None
    classification_evidence: list[str] = Field(default_factory=list)
    # CUQ-2.4: True when scene classifiers disagreed on the platform scene kind
    # (the projector otherwise silently lets the last one win). Feeds the VLM
    # escalation gate's classifier_conflict trigger.
    classifier_conflict: bool = False

    # populated by Layer 3: business state key→value (open convention, see vlm_kimi prompt comments for keys)
    #   subscription:  "subscribed" / "free" / "trial" / "expired" / "unknown"
    #   auth:          "logged_in" / "logged_out" / "unknown"
    #   current_view:  ≤8-char description, e.g. "设置" / "登录" / "控制" / "购买墙"
    #   unread_count:  integer string, omitted when there are no unread items
    # walkthrough scripts read: scene.app_state.get("subscription") == "subscribed"
    app_state: dict[str, str] = Field(default_factory=dict)

    # whitebox boost (when the profile hits the current VC)
    current_vc: str | None = None          # "ListViewController"
    whitebox_evaluated: bool = False       # profile/icon pass ran for this frame
