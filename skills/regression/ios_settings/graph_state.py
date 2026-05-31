"""Graph-backed Settings state evidence.

This module is the Settings crawler's narrow adapter over glassbox ScreenMemory:
it does not create a second graph, it only interprets existing UTG nodes/edges
for Settings-specific questions such as "did this root row already enter a
detail page?" and "has this row proved inert by repeated self-loop taps?".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from glassbox.boundaries import action_host_last_frame
from glassbox.cognition.text_match import norm_text
from glassbox.ios.scene import has_strong_ios_home_evidence
from glassbox.memory.schema import ScreenEdge, ScreenNode
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY, EXPECTED_ROOT_NAV_TEXT_ZH

_HARD_COUNTER_KINDS = frozenset({
    "settings_root",
    "settings_search_home",
    "settings_search_results",
    "settings_blocked_safety",
    "system_search",
    "app_library",
    "harness_console",
})
_GRAPH_SCENE_BASE_KINDS = frozenset({"unknown", "springboard", "springboard_or_app_library"})
_INERT_NO_PROGRESS_THRESHOLD = 2


@dataclass(frozen=True)
class GraphSceneKind:
    kind: str
    confidence: float
    evidence: tuple[str, ...]
    label: str | None = None


def graph_scene_kind(
    scene,
    phone,
    *,
    base_kind: str,
    viewport_size: tuple[int, int] | None = None,
) -> GraphSceneKind | None:
    """Return a graph-derived scene kind override, if the UTG has enough evidence."""
    if base_kind in _HARD_COUNTER_KINDS:
        return None
    if base_kind not in _GRAPH_SCENE_BASE_KINDS:
        return None
    if has_strong_ios_home_evidence(scene, viewport_size=viewport_size):
        return None
    memory = _memory(phone)
    if memory is None:
        return None
    node = _recognize_node(memory, scene, phone)
    if node is None:
        return None
    root_ids = _settings_root_node_ids(memory)
    if not root_ids:
        return None
    best = _best_inbound_root_detail_edge(memory, node.screen_id, root_ids)
    if best is None:
        return None
    edge, label = best
    return GraphSceneKind(
        kind="settings_detail",
        confidence=min(0.92, 0.82 + 0.03 * max(0, edge.success_count - 1)),
        label=label,
        evidence=(
            "utg_root_detail_edge",
            f"root_label:{label}",
            f"edge_count:{edge.count}",
            f"edge_success:{edge.success_count}",
            f"from:{edge.from_id}",
            f"to:{edge.to_id}",
        ),
    )


def root_entered_labels(phone) -> set[str]:
    """Canonical root labels with successful root→detail edges in the UTG."""
    memory = _memory(phone)
    if memory is None:
        return set()
    root_ids = _settings_root_node_ids(memory)
    if not root_ids:
        return set()
    entered: set[str] = set()
    for edge in memory.utg.edges:
        if not _is_successful_root_outbound_edge(edge, root_ids):
            continue
        label = _edge_root_label(edge)
        if label is not None:
            entered.add(label)
    return entered


def inert_root_labels(phone, *, min_no_progress: int = _INERT_NO_PROGRESS_THRESHOLD) -> set[str]:
    """Canonical root labels whose root tap edge is repeatedly a no-progress self-loop."""
    memory = _memory(phone)
    if memory is None:
        return set()
    root_ids = _settings_root_node_ids(memory)
    if not root_ids:
        return set()
    inert: set[str] = set()
    for edge in memory.utg.edges:
        if edge.from_id not in root_ids or edge.to_id != edge.from_id or edge.action_op != "tap":
            continue
        if edge.no_progress_count < min_no_progress or edge.success_count > 0:
            continue
        label = _edge_root_label(edge)
        if label is not None:
            inert.add(label)
    return inert


def is_inert_root_label(phone, label: str) -> bool:
    canonical = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(label)
    return canonical is not None and canonical in inert_root_labels(phone)


def _memory(phone):
    memory = getattr(phone, "memory", None) if phone is not None else None
    return memory if getattr(memory, "utg", None) is not None else None


def _recognize_node(memory, scene, phone) -> ScreenNode | None:
    frame = action_host_last_frame(phone) if phone is not None else None
    frame_img = getattr(frame, "img", None)
    try:
        return memory.recognize(scene, frame_img=frame_img)
    except Exception:
        try:
            return memory.recognize(scene)
        except Exception:
            return None


def _settings_root_node_ids(memory) -> set[str]:
    out: set[str] = set()
    for node in memory.utg.nodes.values():
        if _node_kind(node) == "settings_root" or node.page_id == "settings/root":
            out.add(node.screen_id)
    return out


def _node_kind(node: ScreenNode) -> str | None:
    return node.platform_scene_kind or node.scene_type or node.semantic_scene_type


def _best_inbound_root_detail_edge(
    memory,
    node_id: str,
    root_ids: set[str],
) -> tuple[ScreenEdge, str] | None:
    candidates: list[tuple[int, ScreenEdge, str]] = []
    for edge in memory.utg.edges:
        if edge.to_id != node_id or not _is_successful_root_outbound_edge(edge, root_ids):
            continue
        label = _edge_root_label(edge)
        if label is None:
            continue
        candidates.append((edge.success_count, edge, label))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].count), reverse=True)
    _score, edge, label = candidates[0]
    return edge, label


def _is_successful_root_outbound_edge(edge: ScreenEdge, root_ids: set[str]) -> bool:
    # The destination must be a NON-root node, not merely a different node id.
    # A no-SIM inert row (e.g. Mobile Service) can tap + coincide with a scroll
    # re-render, producing a root→root edge to a *different* root-signature node;
    # that is not entering a detail page, so requiring to_id ∉ root_ids (stricter
    # than to_id != from_id) keeps coverage honest. Under-crediting a detail page
    # mis-classified as root is the safe direction.
    return (
        edge.from_id in root_ids
        and edge.to_id not in root_ids
        and edge.action_op == "tap"
        and edge.success_count > 0
        and _edge_root_label(edge) is not None
    )


def _edge_root_label(edge: ScreenEdge) -> str | None:
    for raw in _edge_label_candidates(edge):
        label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(raw)
        if label is not None:
            return label
    return None


def _edge_label_candidates(edge: ScreenEdge) -> tuple[str, ...]:
    out: list[str] = []
    action = edge.action
    if action is not None:
        out.extend(_string_values(action.target, action.params.get("target"), action.params.get("text")))
    out.extend(_string_values(edge.action_kwargs.get("target"), edge.action_kwargs.get("text")))
    if edge.element_key:
        out.extend(_element_key_label_candidates(edge.element_key))
    if edge.action_identity and edge.action_identity.startswith("element:"):
        out.extend(_element_key_label_candidates(edge.action_identity.removeprefix("element:")))
    return tuple(dict.fromkeys(out))


def _string_values(*values: Any) -> list[str]:
    return [str(value).strip() for value in values if str(value or "").strip()]


def _element_key_label_candidates(key: str) -> list[str]:
    if not key.startswith("text:"):
        return []
    raw = key.removeprefix("text:").strip()
    out = [raw]
    # element_key stores norm_text(label); add canonical labels whose normalized
    # forms match so persisted edges remain readable even when action.target is
    # absent on older UTGs.
    out.extend(label for label in EXPECTED_ROOT_NAV_TEXT_ZH if norm_text(label) == raw)
    return out
