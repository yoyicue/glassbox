"""Extract one iPad Settings A/B run into a single JSONL row.

The matrix driver calls this after every rig run, including runs that exited
non-zero. It must be row-complete: missing or corrupt inputs are encoded as an
``extraction_error`` field instead of raising, so the results file still has one
line per attempted run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from glassbox.memory.schema import UTG, ScreenEdge, ScreenNode

SETTINGS_BUNDLE_ID = ".".join(("com", "apple", "Preferences"))
SETTINGS_ROOT_PAGE_ID = "settings/root"
SETTINGS_ROOT_KIND = "settings_root"
RETURN_ACTIONS = {"back", "home"}


def extract_row(arm: str, round_value: str, locale: str, rc_value: str, report_path: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "arm": arm,
        "round": _int_or_text(round_value),
        "locale": locale,
        "rc": _int_or_none(rc_value),
        "report": report_path,
    }
    rc = row["rc"] if isinstance(row["rc"], int) else 0

    path = Path(report_path)
    if not path.exists():
        row.update({
            "crash": rc != 0,
            "extraction_error": "report_missing",
        })
        return row

    try:
        report_payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        row.update({
            "crash": rc != 0,
            "extraction_error": "json_decode_error",
            "extraction_detail": str(exc),
        })
        return row
    except OSError as exc:
        row.update({
            "crash": rc != 0,
            "extraction_error": "report_read_error",
            "extraction_detail": str(exc),
        })
        return row

    if not isinstance(report_payload, dict):
        row.update({
            "crash": rc != 0,
            "extraction_error": "report_not_object",
        })
        return row

    report: dict[str, Any] = report_payload
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    root_coverage = report.get("root_coverage") if isinstance(report.get("root_coverage"), dict) else {}
    row.update(_report_fields(report, metrics, root_coverage, rc=rc))

    utg, utg_error, utg_path = _load_report_utg(report, path)
    if utg_path is not None:
        row["utg_path"] = str(utg_path)
    if utg_error is not None:
        row.update(_empty_utg_fields())
        row["extraction_error"] = utg_error
        return row

    assert utg is not None
    row.update(_utg_fields(utg))
    return row


def _report_fields(
    report: dict[str, Any],
    metrics: dict[str, Any],
    root_coverage: dict[str, Any],
    *,
    rc: int,
) -> dict[str, Any]:
    required_missing = _string_list(root_coverage.get("required_missing"))
    crash = (
        rc != 0
        or metrics.get("exception_hit") is True
        or "exception" in _string_list(report.get("limits_hit"))
    )
    task_completion = not crash and len(required_missing) == 0
    entered_graph_labels = _string_list(root_coverage.get("entered_graph"))
    entered_labels = _string_list(root_coverage.get("entered"))
    missing = _string_list(root_coverage.get("missing"))
    sidebar_absent = _string_list(root_coverage.get("sidebar_absent"))
    entry_exempt = _string_list(root_coverage.get("entry_exempt"))
    return {
        "run_id": _str_or_none(report.get("run_id")),
        "report_locale": _str_or_none(report.get("locale")),
        "crash": crash,
        "task_completion": task_completion,
        "visit_count": _int_or_none(report.get("visit_count")) or _int_or_none(metrics.get("visit_count")),
        "nav_proxy": _float_or_none(metrics.get("navigation_success_proxy_rate")),
        "hid_no_progress": _int_or_none(metrics.get("hid_no_progress_count")),
        "entered_graph": len(entered_graph_labels),
        "entered_graph_labels": entered_graph_labels,
        "entered": len(entered_labels),
        "entered_labels": entered_labels,
        "required_missing": required_missing,
        "required_missing_count": len(required_missing),
        "missing": missing,
        "missing_count": len(missing),
        "sidebar_absent": sidebar_absent,
        "sidebar_absent_count": len(sidebar_absent),
        "entry_exempt": entry_exempt,
        "entry_exempt_count": len(entry_exempt),
        "root_required_expected": _int_or_none(metrics.get("root_required_expected_count")),
        "root_expected": _int_or_none(metrics.get("root_expected_count")),
        "root_sidebar_exhaustive": bool(metrics.get("root_sidebar_exhaustive")),
    }


def _utg_fields(utg: UTG) -> dict[str, Any]:
    root_nodes = _settings_root_nodes(utg)
    root_ids = {node.screen_id for node in root_nodes}
    root_sigs = {_signature_key(node) for node in root_nodes}
    root_to_detail = [
        edge for edge in utg.edges
        if _successful_edge(edge)
        and edge.from_id in root_ids
        and edge.to_id not in root_ids
    ]
    detail_to_root = [
        edge for edge in utg.edges
        if _successful_edge(edge)
        and edge.from_id not in root_ids
        and edge.to_id in root_ids
        and _edge_policy_action(edge) in RETURN_ACTIONS
    ]
    return {
        "root_nodes": len(root_nodes),
        "root_sigs": len(root_sigs),
        "root_to_detail": len(root_to_detail),
        "detail_to_root": len(detail_to_root),
    }


def _empty_utg_fields() -> dict[str, None]:
    return {
        "root_nodes": None,
        "root_sigs": None,
        "root_to_detail": None,
        "detail_to_root": None,
    }


def _load_report_utg(report: dict[str, Any], report_path: Path) -> tuple[UTG | None, str | None, Path | None]:
    config = report.get("config") if isinstance(report.get("config"), dict) else {}
    memory_dir_value = config.get("memory_dir")
    candidates: list[Path] = []
    if isinstance(memory_dir_value, str) and memory_dir_value:
        candidates.append(Path(memory_dir_value) / f"{SETTINGS_BUNDLE_ID}.json")
    artifact_dir = report_path.with_suffix(".artifacts")
    if artifact_dir.exists():
        candidates.extend(sorted(artifact_dir.glob(f"*/memory/{SETTINGS_BUNDLE_ID}.json")))

    if not candidates:
        return None, "utg_missing", None

    first_path = candidates[0]
    for candidate in candidates:
        if candidate.exists():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    return None, "utg_not_object", candidate
                return UTG.model_validate(payload), None, candidate
            except json.JSONDecodeError:
                return None, "utg_json_decode_error", candidate
            except Exception as exc:
                return None, f"utg_load_error:{exc.__class__.__name__}", candidate
    return None, "utg_missing", first_path


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


def _int_or_text(value: str) -> int | str:
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 5:
        row = {
            "arm": args[0] if len(args) > 0 else None,
            "round": args[1] if len(args) > 1 else None,
            "locale": args[2] if len(args) > 2 else None,
            "rc": _int_or_none(args[3]) if len(args) > 3 else None,
            "report": args[4] if len(args) > 4 else None,
            "crash": False,
            "extraction_error": "usage",
        }
    else:
        row = extract_row(*args)
    print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
