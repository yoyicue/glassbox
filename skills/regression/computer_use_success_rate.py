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
EXPECTED_STATE_VALUES = {
    "page_id",
    "visible_text",
    "element_appears",
    "element_gone",
    "root_coverage_complete",
    "unknown",
}
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
    "kind": "root_coverage_complete",
    "payload": {},
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


# CUQ-3.1: mechanical scroll/drag fillers (a single drilldown emits hundreds of
# them, ~99% of the action mix). Counting them in the headline action rate lets
# stable scroll success mask a real tap/navigation regression, so they are
# scored under a separate scroll_success_rate instead.
_SCROLL_FILLER_OPS = {"scroll", "scroll_wheel", "swipe", "swipe_up", "swipe_down", "drag", "wheel"}


def _is_scroll_filler(action: Mapping[str, Any]) -> bool:
    return str(action.get("op") or "") in _SCROLL_FILLER_OPS


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
    # CUQ-2.9: prefer the source stamped at selection time (ocr/vlm/...) over the
    # post-hoc "was the before-scene VLM-described" inference, which conflates
    # selection-time VLM with verification-time VLM.
    stamped = metadata.get("selection_source")
    if isinstance(stamped, str) and stamped in SOURCE_VALUES:
        return stamped
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


def _root_page_coverage(
    actions: list[Mapping[str, Any]],
    expected_root_pages: Iterable[str],
) -> tuple[int, int, list[str]]:
    """Coverage of the expected top-level pages by this run.

    A page is *covered* when a primary action that opened it succeeded — i.e. a
    `role == "primary"`, `verdict == "succeeded"` action whose target carries the
    page label. This ties coverage to success, not mere attempts.
    """
    expected = list(dict.fromkeys(str(page) for page in expected_root_pages if str(page)))
    if not expected:
        return 0, 0, 0, []
    visited = [
        str(action.get("target") or "")
        for action in actions
        if action.get("role") == "primary"
        and action.get("verdict") == "succeeded"
        and action.get("target")
    ]
    covered = [page for page in expected if _contains_text(visited, page)]
    missing = [page for page in expected if page not in covered]
    return len(covered), len(expected), 0, missing


def _coverage_from_report(root_coverage: Mapping[str, Any]) -> tuple[int, int, int, list[str]]:
    """Coverage from a walkthrough's own `root_coverage`.

    Counts a page as **covered** only when it was actually *entered* (its detail
    page was opened), not merely seen on the root list. Pages deliberately not
    entered for safety are counted as **blocked** and excluded from `missing`
    (they are surfaced separately, not treated as a coverage failure). Falls back
    to `visited` for older reports without the entered/blocked breakdown.
    """
    expected = [str(page) for page in (root_coverage.get("expected") or []) if str(page)]
    entered_list = root_coverage.get("entered")
    if isinstance(entered_list, list):
        entered = {str(page) for page in entered_list}
    else:
        entered = {str(page) for page in (root_coverage.get("visited") or [])}
    blocked: set[str] = set()
    for key in ("blocked", "entry_exempt", "device_unavailable"):
        blocked.update(str(page) for page in (root_coverage.get(key) or []))
    covered = [page for page in expected if page in entered]
    blocked_pages = [page for page in expected if page in blocked and page not in entered]
    required_missing = root_coverage.get("required_missing")
    if isinstance(required_missing, list):
        missing_set = {str(page) for page in required_missing}
        missing = [page for page in expected if page in missing_set and page not in entered and page not in blocked]
    else:
        missing = [page for page in expected if page not in entered and page not in blocked]
    return len(covered), len(expected), len(blocked_pages), missing


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
    root_coverage_complete: bool | None = None,
) -> str:
    if terminal_expected_state.get("kind") == "root_coverage_complete":
        if root_coverage_complete is None:
            return "unknown"
        return "succeeded" if root_coverage_complete else "failed"
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
    # CUQ-3.1: split task-meaningful primary actions from mechanical scroll/drag
    # fillers so the headline success/unknown rates reflect taps/navigation, not
    # scroll mechanics that dominate the count and hide tap regressions.
    task_actions = [action for action in primary_actions if not _is_scroll_filler(action)]
    scroll_actions = [action for action in primary_actions if _is_scroll_filler(action)]
    denominator = len(task_actions)
    succeeded = sum(1 for action in task_actions if action.get("verdict") == "succeeded")
    unknown = sum(1 for action in task_actions if action.get("verdict") == "unknown")
    scroll_succeeded = sum(1 for action in scroll_actions if action.get("verdict") == "succeeded")
    # CUQ-3.2: how much of the run actually exercised the P1/P2 stages. These are
    # ~0 when the strategy ladder / expected-state verification are dead on the
    # path under test, so a real success-rate delta cannot be attributed to them
    # — surface that instead of silently reporting zero (see coverage_warnings).
    expected_state_covered = sum(
        1
        for action in task_actions
        if isinstance(action.get("expected_state"), Mapping)
        and str(action["expected_state"].get("kind") or "unknown") != "unknown"
    )
    vlm_action_covered = sum(
        1 for action in task_actions if _metric_int(action, "vlm_calls") > 0
    )
    task_count = len(tasks)
    task_success = sum(1 for task in tasks if task.get("outcome") == "succeeded")
    task_completion_rate = task_success / task_count if task_count else 0.0
    task_completion_variance = (
        sum(
            ((1.0 if task.get("outcome") == "succeeded" else 0.0) - task_completion_rate) ** 2
            for task in tasks
        )
        / task_count
        if task_count
        else 0.0
    )
    recoveries = sum(_task_recovery_count(task) for task in tasks)
    # Coverage = entered ÷ reachable, where reachable = expected − blocked
    # (deliberately-blocked pages are unreachable and must not penalize coverage).
    coverage_ratios = []
    for task in tasks:
        reachable = _metric_int(task, "root_pages_expected") - _metric_int(task, "root_pages_blocked")
        if reachable > 0:
            coverage_ratios.append(_metric_int(task, "root_pages_covered") / reachable)
    root_pages_coverage = sum(coverage_ratios) / len(coverage_ratios) if coverage_ratios else 0.0
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
        "task_completion_rate": task_completion_rate,
        "task_completion_variance": task_completion_variance,
        "action_success_rate": succeeded / denominator if denominator else 0.0,
        "unknown_rate": unknown / denominator if denominator else 0.0,
        "task_action_count": len(task_actions),
        "scroll_action_count": len(scroll_actions),
        "scroll_success_rate": (
            scroll_succeeded / len(scroll_actions) if scroll_actions else 0.0
        ),
        "expected_state_coverage": expected_state_covered / denominator if denominator else 0.0,
        "vlm_action_coverage": vlm_action_covered / denominator if denominator else 0.0,
        "root_pages_coverage": root_pages_coverage,
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


def coverage_warnings(payload: Mapping[str, Any]) -> list[str]:
    """CUQ-3.2: flag stages a benchmark did not actually exercise, so a
    success-rate delta is not silently attributed to a dead P1/P2 path. Empty
    when there are no task-meaningful actions to judge."""
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        return []
    task_actions = _metric_int(metrics, "task_action_count")
    if task_actions <= 0:
        return []
    warnings: list[str] = []
    if float(metrics.get("expected_state_coverage", 0.0) or 0.0) == 0.0:
        warnings.append(
            f"expected_state_coverage=0 over {task_actions} task actions — P2 "
            "expected-state verification did not run on this task; success/unknown "
            "rates reflect the generic scene_progressed path only."
        )
    if float(metrics.get("vlm_action_coverage", 0.0) or 0.0) == 0.0:
        warnings.append(
            f"vlm_action_coverage=0 over {task_actions} task actions — the P1 VLM "
            "gate did not fire; a success-rate delta cannot be attributed to VLM "
            "grounding."
        )
    return warnings


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
    expected_root_pages: Iterable[str] = (),
    root_coverage: Mapping[str, Any] | None = None,
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
    if isinstance(root_coverage, Mapping):
        # Authoritative: the walkthrough already computed which top-level pages it
        # opened. Prefer it over matching the orchestrator action ledger (whose
        # row navigations are not recorded as matchable primary actions).
        covered, expected_count, blocked_count, missing = _coverage_from_report(root_coverage)
    else:
        covered, expected_count, blocked_count, missing = _root_page_coverage(
            action_records, expected_root_pages
        )
    reachable_count = max(0, expected_count - blocked_count)
    root_coverage_complete = reachable_count > 0 and covered == reachable_count and not missing
    return {
        "task": task,
        "round": round_index,
        "terminal_expected_state": terminal,
        "outcome": _task_outcome(
            action_records,
            final_state,
            terminal,
            root_coverage_complete=root_coverage_complete,
        ),
        "final_state": final_state,
        "root_pages_expected": expected_count,
        "root_pages_covered": covered,
        "root_pages_blocked": blocked_count,
        "root_pages_missing": missing,
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
    expected_root_pages: Iterable[str] = (),
    root_coverages: list[Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    run_dirs = [Path(path) for path in run_dirs]
    expected_root_pages = tuple(expected_root_pages)
    tasks = [
        aggregate_run_dir(
            run_dir,
            task=task,
            round_index=index,
            terminal_expected_state=terminal_expected_state,
            expected_root_pages=expected_root_pages,
            root_coverage=root_coverages[index] if root_coverages and index < len(root_coverages) else None,
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
        raw_expected_pages = entry.get("expected_root_pages", [])
        if not isinstance(raw_expected_pages, list) or not all(isinstance(p, str) for p in raw_expected_pages):
            raise ValueError(f"task manifest tasks[{index}].expected_root_pages must be a list of strings")
        run_dirs.append(run_dir)
        tasks.append(
            aggregate_run_dir(
                run_dir,
                task=str(entry.get("task") or "computer_use_run"),
                round_index=round_index,
                terminal_expected_state=terminal,
                expected_root_pages=raw_expected_pages,
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
        for key in ("root_pages_expected", "root_pages_covered", "root_pages_blocked"):
            if key in task and not _is_non_negative_int(task.get(key)):
                errors.append(f"tasks[{task_index}].{key} must be a non-negative integer")
        if "root_pages_missing" in task:
            missing = task.get("root_pages_missing")
            if not isinstance(missing, list):
                errors.append(f"tasks[{task_index}].root_pages_missing must be a list")
            elif any(not isinstance(text, str) for text in missing):
                errors.append(f"tasks[{task_index}].root_pages_missing must be a list of strings")
        # Coverage invariants. _metrics() computes root_pages_coverage as
        # covered ÷ (expected − blocked); without these a well-typed but
        # inconsistent artifact validates and reports coverage > 1.0.
        expected = task.get("root_pages_expected")
        covered = task.get("root_pages_covered")
        blocked = task.get("root_pages_blocked")
        if _is_non_negative_int(expected) and _is_non_negative_int(blocked) and blocked > expected:
            errors.append(
                f"tasks[{task_index}].root_pages_blocked ({blocked}) must not exceed "
                f"root_pages_expected ({expected})"
            )
        if (
            _is_non_negative_int(expected)
            and _is_non_negative_int(covered)
            and _is_non_negative_int(blocked)
            and covered > expected - blocked
        ):
            errors.append(
                f"tasks[{task_index}].root_pages_covered ({covered}) must not exceed reachable "
                f"root_pages (expected − blocked = {expected - blocked})"
            )
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
        "task_completion_variance",
        "action_success_rate",
        "unknown_rate",
        "task_action_count",
        "scroll_action_count",
        "scroll_success_rate",
        "expected_state_coverage",
        "vlm_action_coverage",
        "root_pages_coverage",
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
        if key in {"task_completion_rate", "action_success_rate", "root_pages_coverage"} and delta < -tolerance:
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
    root_coverages: list[Mapping[str, Any] | None] = []
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
        if args.drill_down:
            cmd.append("--drill-down")
        if args.skip_round_verify:
            cmd.append("--skip-verify")
        if args.language:
            cmd.extend(("--language", args.language))
        if args.region:
            cmd.extend(("--region", args.region))
        env = dict(os.environ)
        env["GLASSBOX_COMPUTER_USE_ARTIFACT_DIR"] = str(artifact_root)
        # The long PicoKVM stream can yield partial H.264 decodes during
        # multi-round runs. The gate needs fresh visual evidence, so default to
        # the bounded reconnect/garble-rejection path while preserving explicit
        # caller overrides.
        env.setdefault("GLASSBOX_PICOKVM_ROBUST_CAPTURE", "1")
        result = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[2], env=env)
        if result.returncode != 0 and not args.keep_going:
            return result.returncode
        new_dirs = _find_new_run_dirs(artifact_root, before)
        if not new_dirs:
            print(f"ERROR: round {index} wrote no computer-use artifact run under {artifact_root}")
            if not args.keep_going:
                return 1
            continue
        run_dirs.append(new_dirs[-1])
        report_payload = _read_json(report) if report.exists() else {}
        coverage = report_payload.get("root_coverage")
        root_coverages.append(coverage if isinstance(coverage, Mapping) else None)

    from skills.regression.ios_settings.policy import EXPECTED_ROOT_NAV_TEXT_ZH

    try:
        payload = aggregate_benchmark(
            run_dirs,
            task="settings_readonly_walkthrough",
            terminal_expected_state=terminal,
            config={
                "rounds": args.rounds,
                "task_set": "ios_settings",
                "language": args.language,
                "region": args.region,
            },
            expected_root_pages=EXPECTED_ROOT_NAV_TEXT_ZH,
            root_coverages=root_coverages,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    errors = validate_benchmark(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    for warning in coverage_warnings(payload):
        print(f"WARNING: {warning}")
    _write_json(args.out.expanduser().resolve(), payload)
    if args.min_task_completion is not None:
        task_completion = float(payload["metrics"].get("task_completion_rate", 0.0) or 0.0)
        if task_completion < args.min_task_completion:
            print(
                f"ERROR: task_completion_rate {task_completion:.6g} "
                f"< required {args.min_task_completion:.6g}"
            )
            return 1
    print(args.out.expanduser().resolve())
    return 0


def _run_canonical_primitives(args: argparse.Namespace) -> int:
    """CUQ-3.4: run each canonical primitive (go-home / launch-app / back /
    scroll-to-bottom) N rounds on the rig and aggregate into one benchmark, so a
    regression in the fragile HID primitives shows up in the success number."""
    from skills.regression.canonical_primitives import (
        CANONICAL_PRIMITIVE_TASKS,
        build_canonical_manifest,
    )

    artifact_root = args.artifact_root.expanduser().resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    run_dirs_by_task: dict[str, list[Path]] = {}
    repo_root = Path(__file__).resolve().parents[2]
    for task in CANONICAL_PRIMITIVE_TASKS:
        run_dirs_by_task[task.name] = []
        for index in range(args.rounds):
            before = {path for path in artifact_root.iterdir() if path.is_dir()}
            cmd = [sys.executable, "-m", "skills.regression.canonical_primitives", "--task", task.name]
            env = dict(os.environ)
            env["GLASSBOX_COMPUTER_USE_ARTIFACT_DIR"] = str(artifact_root)
            # A primitive may legitimately fail (that is what the benchmark
            # measures); only a missing artifact run is a harness error.
            subprocess.run(cmd, cwd=repo_root, env=env)
            new_dirs = _find_new_run_dirs(artifact_root, before)
            if not new_dirs:
                print(f"ERROR: {task.name} round {index} wrote no computer-use artifact run")
                return 1
            run_dirs_by_task[task.name].append(new_dirs[-1])

    manifest = build_canonical_manifest(run_dirs_by_task, rounds=args.rounds)
    manifest_path = artifact_root / "canonical_primitives_manifest.json"
    _write_json(manifest_path, manifest)
    try:
        payload = aggregate_benchmark_manifest(manifest_path)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    errors = validate_benchmark(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    for warning in coverage_warnings(payload):
        print(f"WARNING: {warning}")
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
    run_settings.add_argument("--language", default=None)
    run_settings.add_argument("--region", default=None)
    run_settings.add_argument("--quick", action="store_true")
    run_settings.add_argument("--skip-diagnose", action="store_true")
    run_settings.add_argument("--skip-round-verify", action="store_true")
    run_settings.add_argument("--keep-going", action="store_true")
    run_settings.add_argument("--min-task-completion", type=float, default=None)
    run_settings.add_argument(
        "--drill-down",
        action="store_true",
        help="Open each root section's detail page and screenshot it (real entry, "
        "not root-row visibility).",
    )

    run_canonical = sub.add_parser(
        "run-canonical-primitives",
        help="Run the canonical primitives (go-home/launch-app/back/scroll-to-bottom) N rounds and aggregate",
    )
    run_canonical.add_argument("--rounds", type=int, default=1)
    run_canonical.add_argument("--out", type=Path, required=True)
    run_canonical.add_argument("--artifact-root", type=Path, required=True)

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
        for warning in coverage_warnings(payload):
            print(f"WARNING: {warning}")
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
    if args.cmd == "run-canonical-primitives":
        if args.rounds <= 0:
            print("ERROR: --rounds must be positive")
            return 1
        return _run_canonical_primitives(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
