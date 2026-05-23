"""Computer-use success-rate benchmark aggregation and comparison.

This is the Step 0 harness from docs/design/computer_use_success_rate.md: it
does not change runtime behavior. It projects existing computer-use ledgers
(`actions.jsonl`, `attempt_groups.jsonl`, `audit.jsonl`) into a stable,
machine-comparable benchmark JSON and compares two benchmark runs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ARTIFACT_LEDGER_FILES = ("manifest.json", "actions.jsonl", "attempt_groups.jsonl", "audit.jsonl")
SOURCE_VALUES = {"none", "system", "memory", "ocr", "vlm"}
VERDICT_VALUES = {"succeeded", "failed", "unknown", "blocked", "transport_failed"}
EXPECTED_STATE_VALUES = {"page_id", "visible_text", "element_appears", "element_gone", "unknown"}
RAW_STATUS_VALUES = {
    "succeeded",
    "failed",
    "partial",
    "unknown",
    "no_after_scene",
    "transport_failed",
    "exception",
    "blocked",
    "approval_required",
    "skipped",
}
VLM_TRIGGER_VALUES = {
    "low_confidence",
    "confidence_missing",
    "target_missing",
    "classifier_conflict",
    "verify_unknown",
}

DEFAULT_TERMINAL_EXPECTED_STATE = {"kind": "unknown", "payload": {}}
IOS_SETTINGS_TERMINAL_EXPECTED_STATE = {
    "kind": "page_id",
    "payload": {"page_id": "settings/root"},
}


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"object is not JSON serializable: {type(value).__name__}")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_required_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _read_required_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSONL file: {path}") from exc
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL in {path}:{line_no}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL row must be an object in {path}:{line_no}")
        rows.append(payload)
    return rows


def _git_sha() -> str:
    repo = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def normalize_status(status: Any) -> str:
    raw = str(status or "unknown")
    if raw == "partial":
        return "failed"
    if raw == "no_after_scene":
        return "unknown"
    if raw == "exception":
        return "transport_failed"
    if raw in {"approval_required", "skipped"}:
        return "blocked"
    if raw in VERDICT_VALUES:
        return raw
    return "unknown"


def semantic_verdict(raw_status: Any, semantic: Mapping[str, Any] | None = None) -> str:
    """Normalize an action verdict into the stable compare bucket."""
    del semantic
    return normalize_status(_raw_status(raw_status))


def _raw_status(status: Any) -> str:
    raw = str(status or "unknown")
    return raw if raw in RAW_STATUS_VALUES else "unknown"


def _action_metadata(action: Mapping[str, Any]) -> dict[str, Any]:
    command = action.get("command")
    if isinstance(command, dict):
        return command
    return {}


def _action_intent(action: Mapping[str, Any]) -> str:
    intent = action.get("intent")
    if isinstance(intent, dict) and intent.get("name"):
        return str(intent["name"])
    metadata = _action_metadata(action)
    return str(metadata.get("via") or metadata.get("policy_action") or action.get("op") or "unknown")


def _action_role(action: Mapping[str, Any], group: Mapping[str, Any] | None = None) -> str:
    explicit = str(action.get("role") or (group or {}).get("role") or "")
    if explicit in {"primary", "recovery"}:
        return explicit
    actor = str(action.get("actor") or (group or {}).get("actor") or "")
    intent = _action_intent(action)
    if actor == "runtime" or intent.startswith(("return.", "recovery.")) or ".recovery" in intent:
        return "recovery"
    return "primary"


def _chosen_strategy(action: Mapping[str, Any]) -> str:
    metadata = _action_metadata(action)
    for key in ("strategy", "actuation_method", "via", "policy_action"):
        if metadata.get(key):
            return str(metadata[key])
    command = action.get("command")
    if isinstance(command, dict) and command.get("type"):
        return str(command["type"])
    return "unknown"


def _target(action: Mapping[str, Any]) -> str:
    metadata = _action_metadata(action)
    for key in ("target", "label", "text", "app"):
        if metadata.get(key):
            return str(metadata[key])
    identity = metadata.get("target_identity")
    if isinstance(identity, dict):
        for key in ("intent", "text", "role", "type"):
            if identity.get(key):
                return str(identity[key])
    return ""


def _expected_state(action: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _action_metadata(action)
    expected = metadata.get("expected_state")
    if isinstance(expected, dict):
        kind = str(expected.get("kind") or "unknown")
        payload = expected.get("payload") if isinstance(expected.get("payload"), dict) else {}
        return {"kind": kind, "payload": payload}
    return {"kind": "unknown", "payload": {}}


def _scene_payload(run_dir: Path, scene_ref: Any) -> dict[str, Any]:
    if not isinstance(scene_ref, dict):
        return {}
    scene_path = scene_ref.get("scene")
    if not isinstance(scene_path, str):
        return {}
    return _read_json(run_dir / scene_path)


def _source_from_scene(run_dir: Path, scene_ref: Any) -> str:
    if not isinstance(scene_ref, dict):
        return "none"
    scene_path = scene_ref.get("scene")
    if not isinstance(scene_path, str):
        return "ocr"
    scene = _scene_payload(run_dir, scene_ref)
    if scene.get("vlm_status") == "ok" or scene.get("vlm_described") is True:
        return "vlm"
    return "ocr"


def _verification_source(run_dir: Path, action: Mapping[str, Any]) -> str:
    semantic = action.get("semantic")
    if isinstance(semantic, dict) and semantic.get("verification_skipped"):
        return "none"
    return _source_from_scene(run_dir, action.get("after"))


def _selection_source(run_dir: Path, action: Mapping[str, Any]) -> str:
    metadata = _action_metadata(action)
    if metadata.get("target_identity") or metadata.get("target") or metadata.get("label"):
        return _source_from_scene(run_dir, action.get("before_command") or action.get("before_requested"))
    if str(action.get("op") or "") in {"home", "back", "recents", "control_center", "notification_center"}:
        return "system"
    return "none"


def _vlm_fields(action: Mapping[str, Any]) -> tuple[int, list[str], str | None, bool]:
    metadata = _action_metadata(action)
    calls = int(metadata.get("vlm_calls", 0) or 0)
    triggers = metadata.get("vlm_triggers")
    if not isinstance(triggers, list):
        trigger = metadata.get("vlm_trigger")
        triggers = [trigger] if isinstance(trigger, str) and trigger else []
    clean = [str(item) for item in triggers if str(item) in VLM_TRIGGER_VALUES]
    last = metadata.get("last_vlm_trigger")
    last_value = str(last) if isinstance(last, str) and last in VLM_TRIGGER_VALUES else None
    if last_value is None and clean:
        last_value = clean[-1]
    return calls, clean, last_value, bool(metadata.get("vlm_budget_exhausted", False))


def _vlm_cache_fields(action: Mapping[str, Any]) -> tuple[int, int]:
    metadata = _action_metadata(action)
    return (
        int(metadata.get("vlm_cache_hits", 0) or 0),
        int(metadata.get("vlm_cache_misses", 0) or 0),
    )


def _duration_ms(action: Mapping[str, Any]) -> int:
    observation = action.get("observation")
    if isinstance(observation, dict) and isinstance(observation.get("duration_ms"), int):
        return int(observation["duration_ms"])
    return 0


def _attempt_payload(run_dir: Path, action: Mapping[str, Any], index: int) -> dict[str, Any]:
    semantic = action.get("semantic") if isinstance(action.get("semantic"), dict) else {}
    raw = _raw_status(semantic.get("status") if isinstance(semantic, dict) else None)
    vlm_calls, _triggers, _last_trigger, _budget = _vlm_fields(action)
    vlm_cache_hits, vlm_cache_misses = _vlm_cache_fields(action)
    payload = {
        "idx": index,
        "strategy": _chosen_strategy(action),
        "verdict": semantic_verdict(raw, semantic),
        "raw_semantic_status": raw,
        "selection_source": _selection_source(run_dir, action),
        "verification_source": _verification_source(run_dir, action),
        "vlm_calls": vlm_calls,
        "vlm_cache_hits": vlm_cache_hits,
        "vlm_cache_misses": vlm_cache_misses,
        "duration_ms": _duration_ms(action),
    }
    metadata = _action_metadata(action)
    if metadata.get("actuation_attempt_index") not in (None, index):
        payload["actuation_attempt_index"] = metadata.get("actuation_attempt_index")
    return payload


def _final_state(run_dir: Path, actions: list[dict[str, Any]]) -> dict[str, Any]:
    for action in reversed(actions):
        after = action.get("after")
        if isinstance(after, dict):
            scene = _scene_payload(run_dir, after)
            page_id = scene.get("page_id") or after.get("page_id")
            return {
                "page_id": page_id,
                "scene_id": after.get("scene_id"),
                "is_anchor": bool(page_id in {"home", "settings/root"}),
                "visible_texts": _scene_texts(scene),
                "elements": scene.get("elements") if isinstance(scene.get("elements"), list) else [],
            }
    return {"page_id": None, "is_anchor": False}


def _scene_texts(scene: Mapping[str, Any]) -> list[str]:
    texts = scene.get("texts")
    if isinstance(texts, list):
        return [str(text) for text in texts if str(text)]
    elements = scene.get("elements")
    if not isinstance(elements, list):
        return []
    out: list[str] = []
    for element in elements:
        if isinstance(element, Mapping) and element.get("text"):
            out.append(str(element["text"]))
    return out


def _contains_text(texts: Iterable[str], wanted: str) -> bool:
    return bool(wanted) and any(wanted in text for text in texts)


def _terminal_expected_state_met(
    final_state: Mapping[str, Any],
    terminal_expected_state: Mapping[str, Any],
) -> bool | None:
    kind = str(terminal_expected_state.get("kind") or "unknown")
    payload = terminal_expected_state.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    if kind == "page_id":
        wanted = str(payload.get("page_id") or "")
        return bool(wanted) and final_state.get("page_id") == wanted
    if kind == "visible_text":
        texts = [str(text) for text in final_state.get("visible_texts", []) or []]
        any_of = [str(item) for item in payload.get("any_of", []) or []]
        all_of = [str(item) for item in payload.get("all_of", []) or []]
        any_ok = not any_of or any(_contains_text(texts, wanted) for wanted in any_of)
        all_ok = all(_contains_text(texts, wanted) for wanted in all_of)
        return any_ok and all_ok
    if kind in {"element_appears", "element_gone"}:
        query = payload.get("target_identity") if isinstance(payload.get("target_identity"), Mapping) else payload
        matched = _final_state_element_matches(final_state, query)
        return matched if kind == "element_appears" else not matched
    return None


def _final_state_element_matches(final_state: Mapping[str, Any], query: Mapping[str, Any]) -> bool:
    text = str(query.get("text") or query.get("label") or query.get("intent") or "")
    role = str(query.get("role") or query.get("type") or "")
    elements = final_state.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, Mapping):
                continue
            element_text = str(element.get("text") or "")
            element_role = str(element.get("role") or element.get("type") or "")
            if role and element_role != role:
                continue
            if text and not _contains_text([element_text], text):
                continue
            if role or text:
                return True
    if text:
        texts = [str(item) for item in final_state.get("visible_texts", []) or []]
        return _contains_text(texts, text)
    return False


def _group_actions(
    actions: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> list[tuple[dict[str, Any] | None, list[dict[str, Any]]]]:
    actions_by_attempt = {
        str(action.get("attempt_id")): action
        for action in actions
        if action.get("attempt_id") is not None
    }
    used: set[int] = set()
    out: list[tuple[dict[str, Any] | None, list[dict[str, Any]]]] = []
    for group in groups:
        attempt_ids = group.get("attempt_ids")
        if not isinstance(attempt_ids, list):
            attempt_ids = []
        group_actions = [
            actions_by_attempt[str(attempt_id)]
            for attempt_id in attempt_ids
            if str(attempt_id) in actions_by_attempt
        ]
        for action in group_actions:
            used.add(id(action))
        out.append((group, group_actions))
    for action in actions:
        if id(action) not in used:
            out.append((None, [action]))
    return out


def _action_record(
    run_dir: Path,
    seq: int,
    group: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    retry_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not attempts and group is None:
        return None
    final = attempts[-1] if attempts else {}
    semantic = final.get("semantic") if isinstance(final.get("semantic"), dict) else {}
    raw = _raw_status(
        semantic.get("status")
        if semantic
        else (group or {}).get("group_status", "unknown")
    )
    attempt_payloads = [_attempt_payload(run_dir, action, index) for index, action in enumerate(attempts)]
    retry_by_next_index = {
        int((event.get("payload") or {}).get("next_attempt_index")): event
        for event in retry_events
        if isinstance(event.get("payload"), dict)
        and isinstance((event.get("payload") or {}).get("next_attempt_index"), int)
    }
    for payload in attempt_payloads:
        event = retry_by_next_index.get(int(payload["idx"]))
        if event is not None:
            event_payload = event.get("payload") or {}
            payload["switched_reason"] = str(event_payload.get("reason") or "retry_scheduled")
    strategy_failed_by_attempt_id = {
        str(event.get("attempt_id")): event
        for event in retry_events
        if event.get("type") == "semantic_plan.strategy_failed"
        and event.get("attempt_id") is not None
    }
    for index, payload in enumerate(attempt_payloads[1:], start=1):
        if payload.get("switched_reason"):
            continue
        previous_payload = attempt_payloads[index - 1]
        if payload.get("strategy") == previous_payload.get("strategy"):
            continue
        previous_attempt_id = str(attempts[index - 1].get("attempt_id"))
        event = strategy_failed_by_attempt_id.get(previous_attempt_id)
        if event is None:
            continue
        event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        payload["switched_reason"] = str(event_payload.get("reason") or "expected_state_unmet")

    vlm_calls = sum(int(payload.get("vlm_calls", 0) or 0) for payload in attempt_payloads)
    vlm_cache_hits = sum(int(payload.get("vlm_cache_hits", 0) or 0) for payload in attempt_payloads)
    vlm_cache_misses = sum(int(payload.get("vlm_cache_misses", 0) or 0) for payload in attempt_payloads)
    triggers: list[str] = []
    budget_exhausted = False
    for action in attempts:
        _calls, action_triggers, _last_trigger, action_budget_exhausted = _vlm_fields(action)
        for trigger in action_triggers:
            if trigger not in triggers:
                triggers.append(trigger)
        budget_exhausted = budget_exhausted or action_budget_exhausted
    last_trigger = triggers[-1] if triggers else None
    strategy_switches = 0
    retry_count_same_strategy = 0
    previous_strategy: str | None = None
    for payload in attempt_payloads:
        strategy = str(payload.get("strategy") or "unknown")
        if previous_strategy is not None:
            if strategy != previous_strategy:
                strategy_switches += 1
            else:
                retry_count_same_strategy += 1
        previous_strategy = strategy
    role = _action_role(final, group)
    recovered = role == "primary" and _recovery_finished_successfully(retry_events)
    return {
        "seq": seq,
        "role": role,
        "op": str((group or {}).get("op") or final.get("op") or "unknown"),
        "target": _target(final),
        "expected_state": _expected_state(final),
        "chosen_strategy": _chosen_strategy(final),
        "verdict": semantic_verdict(raw, semantic),
        "raw_semantic_status": raw,
        "semantic_verifier": str(semantic.get("verifier") or "unknown"),
        "confidence": float(semantic.get("confidence", 0.0) or 0.0),
        "selection_source": _selection_source(run_dir, final),
        "verification_source": _verification_source(run_dir, final),
        "vlm_calls": vlm_calls,
        "vlm_cache_hits": vlm_cache_hits,
        "vlm_cache_misses": vlm_cache_misses,
        "vlm_triggers": triggers,
        "last_vlm_trigger": last_trigger,
        "vlm_budget_exhausted": budget_exhausted,
        "attempt_count": len(attempts),
        "attempts": attempt_payloads,
        "strategy_switches": strategy_switches,
        "retries": retry_count_same_strategy,
        "recovered": recovered,
        "duration_ms": sum(int(payload.get("duration_ms", 0) or 0) for payload in attempt_payloads),
    }


def _recovery_finished_successfully(events: Iterable[Mapping[str, Any]]) -> bool:
    finished_events = {
        "run.recovery.finished",
        "semantic_plan.recovery.finished",
        "stuck_detector.recovery.finished",
    }
    for event in events:
        if event.get("type") not in finished_events:
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping) and payload.get("recovered") is True:
            return True
    return False


def _task_outcome(
    actions: list[dict[str, Any]],
    final_state: Mapping[str, Any],
    terminal_expected_state: Mapping[str, Any],
) -> str:
    terminal_met = _terminal_expected_state_met(final_state, terminal_expected_state)
    if terminal_met is not None:
        return "succeeded" if terminal_met else "failed"
    primary = [action for action in actions if action.get("role") == "primary"]
    if not primary:
        return "unknown"
    verdicts = {str(action.get("verdict") or "unknown") for action in primary}
    if verdicts == {"succeeded"}:
        return "succeeded"
    if "blocked" in verdicts or "transport_failed" in verdicts or "failed" in verdicts:
        return "failed"
    return "unknown"


def _metrics(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    all_actions = [
        action
        for task in tasks
        for action in _task_actions(task)
    ]
    primary_actions = [
        action
        for action in all_actions
        if action.get("role") == "primary"
    ]
    denominator = len(primary_actions)
    succeeded = sum(1 for action in primary_actions if action.get("verdict") == "succeeded")
    unknown = sum(1 for action in primary_actions if action.get("verdict") == "unknown")
    task_count = len(tasks)
    task_success = sum(1 for task in tasks if task.get("outcome") == "succeeded")
    recoveries = sum(_task_recovery_count(task) for task in tasks)
    vlm_calls = sum(
        _metric_int(action, "vlm_calls")
        for action in all_actions
    )
    vlm_cache_hits = sum(
        _metric_int(action, "vlm_cache_hits")
        for action in all_actions
    )
    vlm_cache_misses = sum(
        _metric_int(action, "vlm_cache_misses")
        for action in all_actions
    )
    return {
        "task_completion_rate": task_success / task_count if task_count else 0.0,
        "action_success_rate": succeeded / denominator if denominator else 0.0,
        "unknown_rate": unknown / denominator if denominator else 0.0,
        "recoveries": recoveries,
        "strategy_switches": sum(
            _metric_int(action, "strategy_switches")
            for action in all_actions
        ),
        "retries": sum(
            _metric_int(action, "retries")
            for action in all_actions
        ),
        "vlm_calls": vlm_calls,
        "vlm_calls_per_task": vlm_calls / task_count if task_count else 0.0,
        "vlm_cache_hits": vlm_cache_hits,
        "vlm_cache_misses": vlm_cache_misses,
        "vlm_cache_hit_rate": (
            vlm_cache_hits / (vlm_cache_hits + vlm_cache_misses)
            if (vlm_cache_hits + vlm_cache_misses)
            else 0.0
        ),
    }


def _task_recovery_count(task: Mapping[str, Any]) -> int:
    actions = _task_actions(task)
    primary_recovered = sum(
        1
        for action in actions
        if action.get("role") == "primary" and action.get("recovered") is True
    )
    recovery_actions = sum(
        1
        for action in actions
        if action.get("role") == "recovery"
    )
    return max(primary_recovered, recovery_actions)


def _task_actions(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    actions = task.get("actions", [])
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, Mapping)]


def _metric_int(action: Mapping[str, Any], key: str) -> int:
    value = action.get(key, 0)
    return int(value) if _is_non_negative_int(value) else 0


def aggregate_run_dir(
    run_dir: Path,
    *,
    task: str,
    round_index: int,
    terminal_expected_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _require_artifact_run_dir(run_dir)
    manifest = _read_required_json(run_dir / "manifest.json")
    actions = _read_required_jsonl(run_dir / "actions.jsonl")
    groups = _read_required_jsonl(run_dir / "attempt_groups.jsonl")
    audit = _read_required_jsonl(run_dir / "audit.jsonl")
    retry_events_by_group: dict[str, list[dict[str, Any]]] = {}
    for event in audit:
        group_id = event.get("attempt_group_id")
        if group_id is None:
            continue
        retry_events_by_group.setdefault(str(group_id), []).append(event)

    action_records: list[dict[str, Any]] = []
    for group, group_actions in _group_actions(actions, groups):
        group_id = str((group or {}).get("attempt_group_id") or (group_actions[0].get("attempt_group_id") if group_actions else ""))
        record = _action_record(
            run_dir,
            len(action_records),
            group,
            group_actions,
            retry_events_by_group.get(group_id, []),
        )
        if record is not None:
            action_records.append(record)

    terminal = dict(terminal_expected_state or DEFAULT_TERMINAL_EXPECTED_STATE)
    final_state = _final_state(run_dir, actions)
    return {
        "task": task,
        "round": round_index,
        "terminal_expected_state": terminal,
        "outcome": _task_outcome(action_records, final_state, terminal),
        "final_state": final_state,
        "actions": action_records,
        "artifact_run_dir": str(run_dir),
        "artifact_run_id": manifest.get("run_id") or run_dir.name,
    }


def _require_artifact_run_dir(run_dir: Path) -> None:
    if not run_dir.is_dir():
        raise ValueError(f"artifact run dir does not exist: {run_dir}")
    for filename in ARTIFACT_LEDGER_FILES:
        if not (run_dir / filename).is_file():
            raise ValueError(f"artifact run dir missing {filename}: {run_dir}")


def aggregate_benchmark(
    run_dirs: Iterable[Path],
    *,
    task: str = "computer_use_run",
    terminal_expected_state: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run_dirs = [Path(path) for path in run_dirs]
    tasks = [
        aggregate_run_dir(
            run_dir,
            task=task,
            round_index=index,
            terminal_expected_state=terminal_expected_state,
        )
        for index, run_dir in enumerate(run_dirs)
    ]
    return _aggregate_payload(tasks, run_dirs, config=config)


def _aggregate_payload(
    tasks: list[dict[str, Any]],
    run_dirs: list[Path],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    first_manifest = _read_json(run_dirs[0] / "manifest.json") if run_dirs else {}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "started_at": datetime.now().astimezone().isoformat(),
        "git_sha": _git_sha(),
        "config": {
            "vlm_enabled": False,
            "phone_model": ((first_manifest.get("device") or {}).get("model") if first_manifest else None),
            **dict(config or {}),
        },
        "tasks": tasks,
    }
    payload["metrics"] = _metrics(tasks)
    return payload


def aggregate_benchmark_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest = _read_required_json(manifest_path)
    entries = manifest.get("tasks")
    if not isinstance(entries, list):
        raise ValueError("task manifest must contain a tasks list")
    run_dirs: list[Path] = []
    tasks: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"task manifest tasks[{index}] must be an object")
        raw_run_dir = entry.get("run_dir")
        if not isinstance(raw_run_dir, str) or not raw_run_dir:
            raise ValueError(f"task manifest tasks[{index}].run_dir must be a non-empty string")
        run_dir = Path(raw_run_dir).expanduser()
        if not run_dir.is_absolute():
            run_dir = manifest_path.parent / run_dir
        run_dir = run_dir.resolve()
        round_index = entry.get("round", index)
        if not _is_non_negative_int(round_index):
            raise ValueError(f"task manifest tasks[{index}].round must be a non-negative integer")
        terminal = entry.get("terminal_expected_state", DEFAULT_TERMINAL_EXPECTED_STATE)
        if not isinstance(terminal, Mapping):
            raise ValueError(f"task manifest tasks[{index}].terminal_expected_state must be an object")
        terminal_errors: list[str] = []
        _validate_expected_state(terminal, f"task manifest tasks[{index}].terminal_expected_state", terminal_errors)
        if terminal_errors:
            raise ValueError(terminal_errors[0])
        run_dirs.append(run_dir)
        tasks.append(
            aggregate_run_dir(
                run_dir,
                task=str(entry.get("task") or "computer_use_run"),
                round_index=round_index,
                terminal_expected_state=terminal,
            )
        )
    config = manifest.get("config") if isinstance(manifest.get("config"), Mapping) else {}
    return _aggregate_payload(tasks, run_dirs, config=config)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _validate_expected_state(value: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return
    kind = value.get("kind")
    if not isinstance(kind, str) or not kind:
        errors.append(f"{prefix}.kind must be a non-empty string")
    elif kind not in EXPECTED_STATE_VALUES:
        errors.append(f"{prefix}.kind is invalid")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        errors.append(f"{prefix}.payload must be an object")


def _validate_vlm_fields(value: Mapping[str, Any], prefix: str, errors: list[str]) -> None:
    for key in ("vlm_calls", "vlm_cache_hits", "vlm_cache_misses"):
        if not _is_non_negative_int(value.get(key)):
            errors.append(f"{prefix}.{key} must be a non-negative integer")
    triggers = value.get("vlm_triggers")
    if not isinstance(triggers, list):
        errors.append(f"{prefix}.vlm_triggers must be a list")
        triggers = []
    invalid_triggers = [trigger for trigger in triggers if trigger not in VLM_TRIGGER_VALUES]
    if invalid_triggers:
        errors.append(f"{prefix}.vlm_triggers has invalid values: {invalid_triggers!r}")
    last_trigger = value.get("last_vlm_trigger")
    if last_trigger is not None and last_trigger not in VLM_TRIGGER_VALUES:
        errors.append(f"{prefix}.last_vlm_trigger is invalid")
    if last_trigger is not None and last_trigger not in triggers:
        errors.append(f"{prefix}.last_vlm_trigger must be present in vlm_triggers")
    if not isinstance(value.get("vlm_budget_exhausted"), bool):
        errors.append(f"{prefix}.vlm_budget_exhausted must be a boolean")


def _validate_attempt(
    attempt: Any,
    *,
    expected_index: int,
    prefix: str,
    errors: list[str],
) -> None:
    if not isinstance(attempt, dict):
        errors.append(f"{prefix} must be an object")
        return
    if attempt.get("idx") != expected_index:
        errors.append(f"{prefix}.idx must equal {expected_index}")
    if not isinstance(attempt.get("strategy"), str) or not attempt.get("strategy"):
        errors.append(f"{prefix}.strategy must be a non-empty string")
    if attempt.get("verdict") not in VERDICT_VALUES:
        errors.append(f"{prefix}.verdict is invalid")
    if attempt.get("raw_semantic_status") not in RAW_STATUS_VALUES:
        errors.append(f"{prefix}.raw_semantic_status is invalid")
    if attempt.get("selection_source") not in SOURCE_VALUES:
        errors.append(f"{prefix}.selection_source is invalid")
    if attempt.get("verification_source") not in SOURCE_VALUES:
        errors.append(f"{prefix}.verification_source is invalid")
    for key in ("vlm_calls", "vlm_cache_hits", "vlm_cache_misses", "duration_ms"):
        if not _is_non_negative_int(attempt.get(key)):
            errors.append(f"{prefix}.{key} must be a non-negative integer")
    if "switched_reason" in attempt and not isinstance(attempt.get("switched_reason"), str):
        errors.append(f"{prefix}.switched_reason must be a string")


def _validate_final_state(value: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return
    if value.get("page_id") is not None and not isinstance(value.get("page_id"), str):
        errors.append(f"{prefix}.page_id must be a string or null")
    if not isinstance(value.get("is_anchor"), bool):
        errors.append(f"{prefix}.is_anchor must be a boolean")
    visible_texts = value.get("visible_texts", [])
    if visible_texts is not None and (
        not isinstance(visible_texts, list)
        or any(not isinstance(text, str) for text in visible_texts)
    ):
        errors.append(f"{prefix}.visible_texts must be a list of strings")


def validate_benchmark(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("run_id", "started_at", "git_sha"):
        if not _is_non_empty_str(payload.get(key)):
            errors.append(f"{key} must be a non-empty string")
    if not isinstance(payload.get("config"), dict):
        errors.append("config must be an object")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        errors.append("tasks must be a list")
        tasks = []
    for task_index, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"tasks[{task_index}] must be an object")
            continue
        if not _is_non_empty_str(task.get("task")):
            errors.append(f"tasks[{task_index}].task must be a non-empty string")
        if not _is_non_negative_int(task.get("round")):
            errors.append(f"tasks[{task_index}].round must be a non-negative integer")
        if task.get("outcome") not in {"succeeded", "failed", "unknown"}:
            errors.append(f"tasks[{task_index}].outcome is invalid")
        _validate_final_state(task.get("final_state"), f"tasks[{task_index}].final_state", errors)
        if not isinstance(task.get("terminal_expected_state"), dict):
            errors.append(f"tasks[{task_index}].terminal_expected_state must be an object")
        else:
            _validate_expected_state(
                task.get("terminal_expected_state"),
                f"tasks[{task_index}].terminal_expected_state",
                errors,
            )
        actions = task.get("actions")
        if not isinstance(actions, list):
            errors.append(f"tasks[{task_index}].actions must be a list")
            continue
        for action_index, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"tasks[{task_index}].actions[{action_index}] must be an object")
                continue
            prefix = f"tasks[{task_index}].actions[{action_index}]"
            if not _is_non_negative_int(action.get("seq")):
                errors.append(f"{prefix}.seq must be a non-negative integer")
            for key in ("op", "chosen_strategy", "semantic_verifier"):
                if not _is_non_empty_str(action.get(key)):
                    errors.append(f"{prefix}.{key} must be a non-empty string")
            if not isinstance(action.get("target"), str):
                errors.append(f"{prefix}.target must be a string")
            if action.get("role") not in {"primary", "recovery"}:
                errors.append(f"{prefix}.role is invalid")
            if action.get("verdict") not in VERDICT_VALUES:
                errors.append(f"{prefix}.verdict is invalid")
            if action.get("raw_semantic_status") not in RAW_STATUS_VALUES:
                errors.append(f"{prefix}.raw_semantic_status is invalid")
            if action.get("selection_source") not in SOURCE_VALUES:
                errors.append(f"{prefix}.selection_source is invalid")
            if action.get("verification_source") not in SOURCE_VALUES:
                errors.append(f"{prefix}.verification_source is invalid")
            _validate_expected_state(action.get("expected_state"), f"{prefix}.expected_state", errors)
            if not _is_number(action.get("confidence")):
                errors.append(f"{prefix}.confidence must be a number")
            for key in ("strategy_switches", "retries", "duration_ms"):
                if not _is_non_negative_int(action.get(key)):
                    errors.append(f"{prefix}.{key} must be a non-negative integer")
            if not isinstance(action.get("recovered"), bool):
                errors.append(f"{prefix}.recovered must be a boolean")
            _validate_vlm_fields(action, prefix, errors)
            attempts = action.get("attempts")
            if not isinstance(attempts, list):
                errors.append(f"{prefix}.attempts must be a list")
            else:
                if not _is_non_negative_int(action.get("attempt_count")):
                    errors.append(f"{prefix}.attempt_count must be a non-negative integer")
                elif action.get("attempt_count") != len(attempts):
                    errors.append(f"{prefix}.attempt_count does not match attempts length")
                for attempt_index, attempt in enumerate(attempts):
                    _validate_attempt(
                        attempt,
                        expected_index=attempt_index,
                        prefix=f"{prefix}.attempts[{attempt_index}]",
                        errors=errors,
                    )
    valid_tasks = [task for task in tasks if isinstance(task, dict)]
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object")
    else:
        expected = _metrics(valid_tasks)
        for key, value in expected.items():
            actual = metrics.get(key)
            if isinstance(value, float):
                if not _is_number(actual):
                    errors.append(f"metrics.{key} must be a number")
                    continue
                if abs(float(actual or 0.0) - value) > 1e-9:
                    errors.append(f"metrics.{key} mismatch: {actual!r} != {value!r}")
            elif not _is_non_negative_int(actual):
                errors.append(f"metrics.{key} must be a non-negative integer")
            elif actual != value:
                errors.append(f"metrics.{key} mismatch: {actual!r} != {value!r}")
    return errors


def compare_benchmarks(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float = 0.0,
) -> tuple[int, list[str]]:
    errors = [f"baseline: {error}" for error in validate_benchmark(baseline)]
    errors.extend(f"candidate: {error}" for error in validate_benchmark(candidate))
    if not _is_number(tolerance) or float(tolerance) < 0.0:
        errors.append("tolerance must be a non-negative finite number")
    if errors:
        return 2, errors
    base_metrics = baseline.get("metrics") or {}
    cand_metrics = candidate.get("metrics") or {}
    lines: list[str] = []
    rc = 0
    for key in (
        "task_completion_rate",
        "action_success_rate",
        "unknown_rate",
        "recoveries",
        "strategy_switches",
        "retries",
        "vlm_calls",
        "vlm_calls_per_task",
        "vlm_cache_hits",
        "vlm_cache_misses",
        "vlm_cache_hit_rate",
    ):
        base = float(base_metrics.get(key, 0.0) or 0.0)
        cand = float(cand_metrics.get(key, 0.0) or 0.0)
        delta = cand - base
        lines.append(f"{key}: baseline={base:.6g} candidate={cand:.6g} delta={delta:+.6g}")
        if key in {"task_completion_rate", "action_success_rate"} and delta < -tolerance:
            rc = 1
        if key == "unknown_rate" and delta > tolerance:
            rc = 1
    return rc, lines


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _parse_json_arg(raw: str | None, default: Mapping[str, Any]) -> dict[str, Any]:
    if not raw:
        return dict(default)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _find_new_run_dirs(root: Path, before: set[Path]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and path not in before
        and all((path / filename).is_file() for filename in ARTIFACT_LEDGER_FILES)
    )


def _run_ios_settings(args: argparse.Namespace) -> int:
    try:
        terminal = _parse_json_arg(args.terminal_expected_state, IOS_SETTINGS_TERMINAL_EXPECTED_STATE)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: --terminal-expected-state: {exc}")
        return 1
    terminal_errors: list[str] = []
    _validate_expected_state(terminal, "--terminal-expected-state", terminal_errors)
    if terminal_errors:
        for error in terminal_errors:
            print(f"ERROR: {error}")
        return 1
    artifact_root = args.artifact_root.expanduser().resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    run_dirs: list[Path] = []
    for index in range(args.rounds):
        before = {path for path in artifact_root.iterdir() if path.is_dir()}
        report = args.report_dir.expanduser().resolve() / f"ios-settings-{index:03d}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "skills.regression.ios_settings.run_full",
            "--report",
            str(report),
        ]
        if args.quick:
            cmd.append("--quick")
        if args.skip_diagnose:
            cmd.append("--skip-diagnose")
        env = dict(os.environ)
        env["GLASSBOX_COMPUTER_USE_ARTIFACT_DIR"] = str(artifact_root)
        result = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[2], env=env)
        if result.returncode != 0:
            return result.returncode
        new_dirs = _find_new_run_dirs(artifact_root, before)
        if not new_dirs:
            print(f"ERROR: round {index} wrote no computer-use artifact run under {artifact_root}")
            return 1
        run_dirs.append(new_dirs[-1])

    try:
        payload = aggregate_benchmark(
            run_dirs,
            task="settings_readonly_walkthrough",
            terminal_expected_state=terminal,
            config={"rounds": args.rounds, "task_set": "ios_settings"},
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    errors = validate_benchmark(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    _write_json(args.out.expanduser().resolve(), payload)
    print(args.out.expanduser().resolve())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Computer-use success-rate benchmark tools")
    sub = parser.add_subparsers(dest="cmd", required=True)

    aggregate = sub.add_parser("aggregate", help="Aggregate one or more artifact run dirs")
    aggregate.add_argument("--run-dir", type=Path, action="append")
    aggregate.add_argument("--task-manifest", type=Path, default=None)
    aggregate.add_argument("--out", type=Path, required=True)
    aggregate.add_argument("--task", default="computer_use_run")
    aggregate.add_argument("--terminal-expected-state", default=None)

    validate = sub.add_parser("validate", help="Validate a benchmark JSON artifact")
    validate.add_argument("benchmark", type=Path)

    compare = sub.add_parser("compare", help="Compare two benchmark JSON artifacts")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--tolerance", type=float, default=0.0)

    run_settings = sub.add_parser("run-ios-settings", help="Run iOS Settings N times and aggregate")
    run_settings.add_argument("--rounds", type=int, default=1)
    run_settings.add_argument("--out", type=Path, required=True)
    run_settings.add_argument("--artifact-root", type=Path, required=True)
    run_settings.add_argument("--report-dir", type=Path, default=Path("/tmp/glassbox-ios-settings-benchmark"))
    run_settings.add_argument("--terminal-expected-state", default=None)
    run_settings.add_argument("--quick", action="store_true")
    run_settings.add_argument("--skip-diagnose", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "aggregate":
        if args.task_manifest is not None:
            if args.run_dir:
                print("ERROR: use either --task-manifest or --run-dir, not both")
                return 1
            try:
                payload = aggregate_benchmark_manifest(args.task_manifest)
            except ValueError as exc:
                print(f"ERROR: {exc}")
                return 1
        else:
            if not args.run_dir:
                print("ERROR: --run-dir is required unless --task-manifest is provided")
                return 1
            try:
                terminal = _parse_json_arg(args.terminal_expected_state, DEFAULT_TERMINAL_EXPECTED_STATE)
            except (json.JSONDecodeError, ValueError) as exc:
                print(f"ERROR: --terminal-expected-state: {exc}")
                return 1
            try:
                payload = aggregate_benchmark(args.run_dir, task=args.task, terminal_expected_state=terminal)
            except ValueError as exc:
                print(f"ERROR: {exc}")
                return 1
        errors = validate_benchmark(payload)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        _write_json(args.out.expanduser().resolve(), payload)
        print(args.out.expanduser().resolve())
        return 0
    if args.cmd == "validate":
        payload = _read_json(args.benchmark.expanduser().resolve())
        errors = validate_benchmark(payload)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("OK")
        return 0
    if args.cmd == "compare":
        baseline = _read_json(args.baseline.expanduser().resolve())
        candidate = _read_json(args.candidate.expanduser().resolve())
        rc, lines = compare_benchmarks(baseline, candidate, tolerance=args.tolerance)
        for line in lines:
            prefix = "ERROR: " if rc == 2 else ""
            print(prefix + line)
        return rc
    if args.cmd == "run-ios-settings":
        if args.rounds <= 0:
            print("ERROR: --rounds must be positive")
            return 1
        return _run_ios_settings(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
