"""glassbox/memory/schema.py — UI Transition Graph data model.

Pure pydantic schema, no I/O. A UTG is the agent's *learned* memory of an app:
nodes are screen states (each carrying the element layout last observed there),
edges are transitions (which action on which element led where).

See docs/design/screen_memory.md §2/§3. Complements the *static* knowledge in
glassbox/profile.py — profile is the factory prior, the UTG is experience.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from glassbox.cognition.base import Box, ElementType, WhiteboxHint

UTG_SCHEMA_VERSION = 2
UTG_RUNTIME_COMPAT = {
    "action_identity": "gesture-v2",
    "coordinate_space": "normalized-v1",
    "scene_fields": "split-v1",
}


def default_runtime_compat() -> dict[str, str]:
    return dict(UTG_RUNTIME_COMPAT)


class ActionRecord(BaseModel):
    """A normalized action observation stored on UTG edges.

    `params` carries operation-specific fields such as wheel ticks, keycode,
    swipe endpoints, or timing knobs. Legacy `(op, kwargs)` inputs are
    converted through `from_op()` so old callers and recordings continue to
    work.
    """

    op: str
    via: str | None = None
    target: str | None = None
    element_key: str | None = None
    x: int | None = None
    y: int | None = None
    coordinate_space: str = "frame_px"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("coordinate_space", mode="before")
    @classmethod
    def _normalize_coordinate_space(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text or text == "phone":
            return "frame_px"
        return text

    @classmethod
    def from_op(cls, op: str, kwargs: dict[str, Any] | None = None) -> ActionRecord:
        data = dict(kwargs or {})
        known = {"via", "target", "element_key", "x", "y", "coordinate_space"}
        params = {k: v for k, v in data.items() if k not in known}
        return cls(
            op=str(op or ""),
            via=_str_or_none(data.get("via")),
            target=_str_or_none(data.get("target")),
            element_key=_str_or_none(data.get("element_key")),
            x=_int_or_none(data.get("x")),
            y=_int_or_none(data.get("y")),
            coordinate_space=data.get("coordinate_space"),
            params=params,
        )

    def to_kwargs(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(self.params)
        if self.via is not None:
            out["via"] = self.via
        if self.target is not None:
            out["target"] = self.target
        if self.element_key is not None:
            out["element_key"] = self.element_key
        if self.x is not None:
            out["x"] = self.x
        if self.y is not None:
            out["y"] = self.y
        if self.coordinate_space != "frame_px":
            out["coordinate_space"] = self.coordinate_space
        return out


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ScreenSignature(BaseModel):
    """Structural fingerprint of a screen — tolerant to pixel noise.

    Built from the *stable* (non-volatile) content so a list whose rows churn
    still hashes to the same screen. See glassbox/memory/signature.py.
    """

    stable_texts: list[str] = Field(default_factory=list)   # sorted, normalized
    type_histogram: dict[str, int] = Field(default_factory=dict)
    phash: str = ""                                         # 64-char dhash, "" if unknown


class RememberedElement(BaseModel):
    """An element of a screen, accumulated across visits — the position memory."""

    key: str                                 # node-stable id (see element_key.py)
    box: Box                                 # smoothed / latest position
    type: ElementType
    text: str | None = None
    suggested_actions: list[str] = Field(default_factory=list)
    intent_label: str | None = None
    whitebox_hint: WhiteboxHint | None = None
    volatile: bool = False                   # content/position unreliable (list rows)
    visit_count: int = 0
    present: bool = True                     # false when an authoritative refresh no longer sees it
    missing_count: int = 0                   # consecutive authoritative misses
    last_seen_visit: int = 0                 # node visit number where this element was last observed


class ScreenNode(BaseModel):
    """One screen state in the UTG."""

    screen_id: str                           # stable UTG node id ("scr_N" for learned signature nodes)
    vc_name: str | None = None               # set when identified via a profile
    signature: ScreenSignature = Field(default_factory=ScreenSignature)
    elements: list[RememberedElement] = Field(default_factory=list)
    scene_type: str | None = None
    semantic_scene_type: str | None = None
    platform_scene_kind: str | None = None
    context: str | None = None
    available_intents: list[str] = Field(default_factory=list)
    page_id: str | None = None
    safe_actions: list[str] = Field(default_factory=list)
    classification_source: str | None = None
    classification_confidence: float | None = None
    classification_evidence: list[str] = Field(default_factory=list)
    app_state: dict[str, str] = Field(default_factory=dict)
    visit_count: int = 0
    first_seen: float = 0.0                  # epoch seconds
    last_seen: float = 0.0

    def element(self, key: str) -> RememberedElement | None:
        return next((e for e in self.elements if e.key == key), None)


class ScreenEdge(BaseModel):
    """A transition: doing `action_op` on `element_key` of `from_id` led to `to_id`."""

    from_id: str
    to_id: str
    action_op: str                           # tap / swipe_up / ...
    element_key: str | None = None           # the element acted on (None for tap_xy)
    action_kwargs: dict[str, Any] = Field(default_factory=dict)
    action_identity: str | None = None        # canonical edge identity within action_op
    action: ActionRecord | None = None
    policy_action: str | None = None          # planner-facing semantic action taxonomy
    count: int = 0                           # times observed — confidence
    success_count: int = 0                   # observations with a positive action outcome
    no_progress_count: int = 0               # observations with stuck/no-progress outcome
    overshoot_count: int = 0                 # scroll jumped too far; progress but low quality
    success_rate: float = 0.0                # success_count / count, maintained by ScreenMemory
    last_outcome: str | None = None          # progress/no_progress/stuck/overshoot


class UTG(BaseModel):
    """The full UI Transition Graph for one app."""

    schema_version: int = UTG_SCHEMA_VERSION
    runtime_compat: dict[str, str] = Field(default_factory=default_runtime_compat)
    bundle_id: str
    app_version: str | None = None
    nodes: dict[str, ScreenNode] = Field(default_factory=dict)
    edges: list[ScreenEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_runtime_compat(self) -> UTG:
        if not self.runtime_compat:
            self.runtime_compat = default_runtime_compat()
        return self

    def node(self, screen_id: str) -> ScreenNode | None:
        return self.nodes.get(screen_id)

    def outgoing(self, screen_id: str) -> list[ScreenEdge]:
        return [e for e in self.edges if e.from_id == screen_id]
