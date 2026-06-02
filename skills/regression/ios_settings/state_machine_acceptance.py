"""Acceptance checks for the iPad Settings state-machine work.

This verifier is intended for post-rig reports: it combines the Settings report
with the persisted UTG and checks the architecture-level signals from
docs/design/ipad_settings_state_machine.md. It is deliberately separate from
verify_report.py so normal report shape validation stays device-neutral.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glassbox.memory.schema import UTG, ScreenEdge, ScreenNode
from glassbox.memory.store import load_utg

SETTINGS_BUNDLE_ID = ".".join(("com", "apple", "Preferences"))
SETTINGS_ROOT_PAGE_ID = "settings/root"
SETTINGS_ROOT_KIND = "settings_root"
RETURN_ACTIONS = {"back", "home"}


@dataclass(frozen=True)
class StateMachineAcceptanceResult:
    errors: list[str]
    metrics: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_state_machine_acceptance(
    report: dict[str, Any],
    utg: UTG,
    *,
    max_root_signatures: int = 2,
    min_entered_graph: int = 1,
    min_root_to_detail_edges: int | None = None,
    min_detail_to_root_edges: int = 0,
    require_sidebar_exhaustive: bool = False,
    allow_required_missing: bool = False,
) -> StateMachineAcceptanceResult:
    root_nodes = _settings_root_nodes(utg)
    root_ids = {node.screen_id for node in root_nodes}
    root_signature_count = len({_signature_key(node) for node in root_nodes})
    root_to_detail_edges = [
        edge for edge in utg.edges
        if _successful_edge(edge)
        and edge.from_id in root_ids
        and edge.to_id not in root_ids
    ]
    detail_to_root_edges = [
        edge for edge in utg.edges
        if _successful_edge(edge)
        and edge.from_id not in root_ids
        and edge.to_id in root_ids
        and _edge_policy_action(edge) in RETURN_ACTIONS
    ]
    root_coverage = report.get("root_coverage") if isinstance(report.get("root_coverage"), dict) else {}
    entered_graph = _string_list(root_coverage.get("entered_graph"))
    required_missing = _string_list(root_coverage.get("required_missing"))
    sidebar_absent = _string_list(root_coverage.get("sidebar_absent"))
    sidebar_exhaustive = _sidebar_exhaustive(root_coverage)
    if min_root_to_detail_edges is None:
        min_root_to_detail_edges = max(1, len(entered_graph))

    metrics = {
        "root_node_count": len(root_nodes),
        "root_signature_count": root_signature_count,
        "root_to_detail_success_edge_count": len(root_to_detail_edges),
        "detail_to_root_return_success_edge_count": len(detail_to_root_edges),
        "entered_graph_count": len(entered_graph),
        "required_missing_count": len(required_missing),
        "sidebar_absent_count": len(sidebar_absent),
        "sidebar_exhaustive": sidebar_exhaustive,
    }
    errors: list[str] = []
    if utg.bundle_id != SETTINGS_BUNDLE_ID:
        errors.append(f"UTG bundle_id must be {SETTINGS_BUNDLE_ID!r}, got {utg.bundle_id!r}")
    if not root_nodes:
        errors.append("missing projected settings/root node")
    if root_signature_count > max_root_signatures:
        errors.append(
            f"projected settings/root fragmented into {root_signature_count} signatures "
            f"(max {max_root_signatures})"
        )
    for node in root_nodes:
        if _node_kind(node) != SETTINGS_ROOT_KIND:
            errors.append(f"root node {node.screen_id} is not tagged settings_root")
    if len(root_to_detail_edges) < min_root_to_detail_edges:
        errors.append(
            f"root→detail success edges below threshold: "
            f"{len(root_to_detail_edges)} < {min_root_to_detail_edges}"
        )
    if len(entered_graph) < min_entered_graph:
        errors.append(f"entered_graph below threshold: {len(entered_graph)} < {min_entered_graph}")
    if len(detail_to_root_edges) < min_detail_to_root_edges:
        errors.append(
            f"detail→root return success edges below threshold: "
            f"{len(detail_to_root_edges)} < {min_detail_to_root_edges}"
        )
    if required_missing and not allow_required_missing:
        errors.append(f"required_missing is not empty: {required_missing}")
    if sidebar_absent and not sidebar_exhaustive:
        errors.append("sidebar_absent requires sidebar_exhaustive evidence")
    if (
        require_sidebar_exhaustive
        and not sidebar_exhaustive
        and (required_missing or sidebar_absent)
    ):
        errors.append("sidebar_exhaustive evidence is required")
    return StateMachineAcceptanceResult(errors=errors, metrics=metrics)


def _settings_root_nodes(utg: UTG) -> list[ScreenNode]:
    return [
        node for node in utg.nodes.values()
        if node.page_id == SETTINGS_ROOT_PAGE_ID and _node_kind(node) == SETTINGS_ROOT_KIND
    ]


def _node_kind(node: ScreenNode) -> str | None:
    for value in (node.platform_scene_kind, node.scene_type, node.semantic_scene_type):
        if value:
            return value
    return None


def _signature_key(node: ScreenNode) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...], str]:
    sig = node.signature
    return (
        tuple(sig.stable_texts),
        tuple(sorted(sig.type_histogram.items())),
        sig.phash,
    )


def _successful_edge(edge: ScreenEdge) -> bool:
    return edge.success_rate >= 0.5 and edge.success_count > 0


def _edge_policy_action(edge: ScreenEdge) -> str:
    if edge.policy_action:
        return edge.policy_action
    if edge.action is not None:
        value = edge.action.params.get("policy_action")
        if value:
            return str(value)
    value = edge.action_kwargs.get("policy_action")
    return str(value or "")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _sidebar_exhaustive(root_coverage: dict[str, Any]) -> bool:
    # The written rig report spells sidebar_exhaustive as a list (["true"] / [],
    # via reporting.classify_root_coverage + page_records) — handled by the list
    # branch. The in-memory context.RootCoverage spells the same fact as a bare
    # bool; accept that (and the string form fixtures use) so this verifier is
    # robust whether it is handed a written report or one built from the dataclass.
    value = root_coverage.get("sidebar_exhaustive")
    if isinstance(value, bool):
        return value
    if isinstance(value, list):
        return any(str(item).lower() == "true" for item in value)
    return str(value).lower() == "true"


def _read_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"report must contain a JSON object: {path}")
    return payload


def _load_utg(report: dict[str, Any], *, utg_path: Path | None, memory_dir: Path | None) -> UTG:
    if utg_path is not None:
        payload = json.loads(utg_path.read_text(encoding="utf-8"))
        return UTG.model_validate(payload)
    if memory_dir is None:
        config = report.get("config")
        if isinstance(config, dict) and isinstance(config.get("memory_dir"), str):
            memory_dir = Path(config["memory_dir"])
    if memory_dir is None:
        raise ValueError("provide --utg or --memory-dir, or include config.memory_dir in the report")
    return load_utg(SETTINGS_BUNDLE_ID, memory_dir=memory_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--utg", type=Path, help="Path to the Settings UTG JSON")
    parser.add_argument("--memory-dir", type=Path, help="Directory containing the Settings UTG JSON")
    parser.add_argument("--max-root-signatures", type=int, default=2)
    parser.add_argument("--min-entered-graph", type=int, default=1)
    parser.add_argument("--min-root-to-detail-edges", type=int)
    parser.add_argument("--min-detail-to-root-edges", type=int, default=0)
    parser.add_argument("--require-sidebar-exhaustive", action="store_true")
    parser.add_argument("--allow-required-missing", action="store_true")
    args = parser.parse_args(argv)

    report = _read_report(args.report)
    utg = _load_utg(report, utg_path=args.utg, memory_dir=args.memory_dir)
    result = validate_state_machine_acceptance(
        report,
        utg,
        max_root_signatures=args.max_root_signatures,
        min_entered_graph=args.min_entered_graph,
        min_root_to_detail_edges=args.min_root_to_detail_edges,
        min_detail_to_root_edges=args.min_detail_to_root_edges,
        require_sidebar_exhaustive=args.require_sidebar_exhaustive,
        allow_required_missing=args.allow_required_missing,
    )
    print(json.dumps(result.metrics, ensure_ascii=False, sort_keys=True))
    if result.ok:
        print("OK")
        return 0
    for error in result.errors:
        print(f"ERROR: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
