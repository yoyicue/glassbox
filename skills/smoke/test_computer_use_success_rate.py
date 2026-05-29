from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import skills.regression.computer_use_success_rate as success_rate
from skills.regression.computer_use_success_rate import (
    aggregate_benchmark,
    aggregate_benchmark_manifest,
    compare_benchmarks,
    main,
    normalize_status,
    semantic_verdict,
    validate_benchmark,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, *rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _action(
    attempt_id: str,
    group_id: str,
    *,
    status: str,
    strategy: str,
    scene_file: str,
    target: str = "Settings",
    actor: str = "agent",
    op: str = "launch_app",
    intent_name: str = "launch_app",
    vlm_calls: int = 0,
    vlm_cache_hits: int = 0,
    vlm_cache_misses: int = 0,
) -> dict:
    return {
        "attempt_id": attempt_id,
        "attempt_group_id": group_id,
        "actor": actor,
        "op": op,
        "intent": {"name": intent_name},
        "before_command": {"scene": "scenes/before.json"},
        "after": {"scene": scene_file, "scene_id": attempt_id.replace("act", "scn")},
        "command": {
            "type": op,
            "target": target,
            "strategy": strategy,
            "expected_state": {"kind": "visible_text", "payload": {"any_of": ["设置"]}},
            "vlm_calls": vlm_calls,
            "vlm_cache_hits": vlm_cache_hits,
            "vlm_cache_misses": vlm_cache_misses,
        },
        "semantic": {
            "status": status,
            "verifier": "foreground_app_matches",
            "confidence": 0.8,
        },
        "observation": {"duration_ms": 10},
    }


def _run_dir(tmp_path: Path, *, status: str = "succeeded") -> Path:
    run_dir = tmp_path / f"run-{status}"
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": f"run-{status}",
            "device": {"model": "iphone_test"},
        },
    )
    _write_json(run_dir / "scenes" / "before.json", {"page_id": "home", "vlm_status": "error"})
    _write_json(run_dir / "scenes" / "after0.json", {"page_id": "home", "vlm_status": "error"})
    _write_json(
        run_dir / "scenes" / "after1.json",
        {
            "page_id": "settings/root",
            "vlm_status": "ok",
            "elements": [{"type": "text", "text": "设置"}],
        },
    )
    if status == "succeeded":
        actions = [
            _action("act_000000", "grp_000000", status="failed", strategy="keyboard_combo", scene_file="scenes/after0.json"),
            _action(
                "act_000001",
                "grp_000000",
                status="succeeded",
                strategy="assistive_touch_home",
                scene_file="scenes/after1.json",
                vlm_calls=1,
                vlm_cache_misses=1,
            ),
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000", "act_000001"],
                "group_status": "succeeded",
                "retry_count": 1,
            }
        ]
        audit = [
            {
                "type": "action.retry_scheduled",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {
                    "kind": "semantic",
                    "reason": "expected_state_unmet",
                    "next_attempt_index": 1,
                },
            }
        ]
    else:
        actions = [
            _action("act_000000", "grp_000000", status=status, strategy="keyboard_combo", scene_file="scenes/after0.json")
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000"],
                "group_status": status,
                "retry_count": 0,
            }
        ]
        audit = []
    if status == "failed_recovered":
        actions = [
            _action("act_000000", "grp_000000", status="failed", strategy="keyboard_combo", scene_file="scenes/after0.json")
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000"],
                "group_status": "failed",
                "retry_count": 0,
            }
        ]
        audit = [
            {
                "type": "stuck_detector.recovery.finished",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {"attempted": True, "recovered": True},
            }
        ]
    if status == "failed_recovery_attempt":
        actions = [
            _action("act_000000", "grp_000000", status="failed", strategy="keyboard_combo", scene_file="scenes/after0.json")
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000"],
                "group_status": "failed",
                "retry_count": 0,
            }
        ]
        audit = [
            {
                "type": "stuck_detector.recovery.started",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {"recovery": "recover_to_home_then_renavigate"},
            },
            {
                "type": "stuck_detector.recovery.finished",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {"attempted": True, "recovered": False},
            },
        ]
    if status == "succeeded_recovered":
        actions = [
            _action(
                "act_000000",
                "grp_000000",
                status="succeeded",
                strategy="recover_to_anchor",
                scene_file="scenes/after1.json",
            )
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000"],
                "group_status": "succeeded",
                "retry_count": 0,
            }
        ]
        audit = [
            {
                "type": "stuck_detector.recovery.finished",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {"attempted": True, "recovered": True},
            }
        ]
    if status == "transport_retried":
        actions = [
            _action("act_000000", "grp_000000", status="transport_failed", strategy="target_tap", scene_file="scenes/after0.json"),
            _action("act_000001", "grp_000000", status="succeeded", strategy="target_tap", scene_file="scenes/after1.json"),
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "tap",
                "actor": "agent",
                "attempt_ids": ["act_000000", "act_000001"],
                "group_status": "succeeded",
                "retry_count": 1,
            }
        ]
        audit = [
            {
                "type": "action.retry_scheduled",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {
                    "kind": "transport",
                    "reason": "transport down",
                    "strategy": "target_tap",
                    "next_attempt_index": 1,
                },
            }
        ]
    if status == "runtime_strategy_switched":
        actions = [
            _action("act_000000", "grp_000000", status="failed", strategy="keyboard_combo", scene_file="scenes/after0.json"),
            _action("act_000001", "grp_000000", status="succeeded", strategy="assistive_touch_home", scene_file="scenes/after1.json"),
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000", "act_000001"],
                "group_status": "succeeded",
                "retry_count": 1,
            }
        ]
        audit = [
            {
                "type": "semantic_plan.strategy_failed",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {
                    "strategy": "keyboard_combo",
                    "status": "failed",
                    "reason": "expected state unmet",
                    "next_strategy_index": 1,
                },
            }
        ]
    if status == "with_recovery_action":
        actions = [
            _action(
                "act_000000",
                "grp_000000",
                status="succeeded",
                strategy="springboard_icon_tap",
                scene_file="scenes/after1.json",
            ),
            _action(
                "act_000001",
                "grp_000001",
                status="failed",
                strategy="recover_to_anchor",
                scene_file="scenes/after0.json",
                actor="runtime",
                op="home",
                intent_name="recovery.home",
            ),
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000"],
                "group_status": "succeeded",
                "retry_count": 0,
            },
            {
                "attempt_group_id": "grp_000001",
                "op": "home",
                "actor": "runtime",
                "attempt_ids": ["act_000001"],
                "group_status": "failed",
                "retry_count": 0,
            },
        ]
        audit = []
    if status == "recovered_with_recovery_action":
        actions = [
            _action(
                "act_000000",
                "grp_000000",
                status="succeeded",
                strategy="springboard_icon_tap",
                scene_file="scenes/after1.json",
            ),
            _action(
                "act_000001",
                "grp_000001",
                status="succeeded",
                strategy="recover_to_anchor",
                scene_file="scenes/after1.json",
                actor="runtime",
                op="home",
                intent_name="recovery.home",
            ),
        ]
        groups = [
            {
                "attempt_group_id": "grp_000000",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": ["act_000000"],
                "group_status": "succeeded",
                "retry_count": 0,
            },
            {
                "attempt_group_id": "grp_000001",
                "op": "home",
                "actor": "runtime",
                "attempt_ids": ["act_000001"],
                "group_status": "succeeded",
                "retry_count": 0,
            },
        ]
        audit = [
            {
                "type": "stuck_detector.recovery.finished",
                "attempt_group_id": "grp_000000",
                "attempt_id": "act_000000",
                "payload": {"attempted": True, "recovered": True},
            }
        ]
    _append_jsonl(run_dir / "actions.jsonl", *actions)
    _append_jsonl(run_dir / "attempt_groups.jsonl", *groups)
    _append_jsonl(run_dir / "audit.jsonl", *audit)
    return run_dir


def test_status_normalization_keeps_stable_metric_buckets():
    assert normalize_status("partial") == "failed"
    assert normalize_status("no_after_scene") == "unknown"
    assert normalize_status("exception") == "transport_failed"
    assert normalize_status("approval_required") == "blocked"
    assert normalize_status("skipped") == "blocked"


def test_semantic_verdict_keeps_scene_progress_in_stable_unknown_bucket():
    assert semantic_verdict("unknown", {"verifier": "scene_progressed", "confidence": 0.7}) == "unknown"
    assert semantic_verdict("unknown", {"verifier": "scene_progressed", "confidence": 0.2}) == "unknown"
    assert semantic_verdict("failed", {"verifier": "scene_progressed", "confidence": 0.7}) == "failed"


def test_scroll_fillers_excluded_from_action_success_rate(tmp_path):
    """CUQ-3.1: a failed tap must not be masked by a succeeded scroll filler in
    the headline action_success_rate; scroll mechanics are scored separately."""
    run_dir = tmp_path / "run"
    _write_json(run_dir / "manifest.json", {"run_id": "run", "device": {"model": "iphone_test"}})
    _write_json(run_dir / "scenes" / "before.json", {"page_id": "settings/root", "vlm_status": "error"})
    _write_json(run_dir / "scenes" / "after_tap.json", {"page_id": "settings/root", "vlm_status": "error", "elements": []})
    _write_json(run_dir / "scenes" / "after_scroll.json", {"page_id": "settings/root", "vlm_status": "error", "elements": []})
    tap = _action(
        "act_000000", "grp_000000", status="failed", strategy="target_tap",
        scene_file="scenes/after_tap.json", op="tap", intent_name="tap", target="蓝牙",
    )
    scroll = _action(
        "act_000001", "grp_000001", status="succeeded", strategy="raw_hid_logical_drag",
        scene_file="scenes/after_scroll.json", op="drag", intent_name="scroll", target="",
    )
    groups = [
        {"attempt_group_id": "grp_000000", "op": "tap", "actor": "agent",
         "attempt_ids": ["act_000000"], "group_status": "failed", "retry_count": 0},
        {"attempt_group_id": "grp_000001", "op": "drag", "actor": "agent",
         "attempt_ids": ["act_000001"], "group_status": "succeeded", "retry_count": 0},
    ]
    _append_jsonl(run_dir / "actions.jsonl", tap, scroll)
    _append_jsonl(run_dir / "attempt_groups.jsonl", *groups)
    _append_jsonl(run_dir / "audit.jsonl")

    payload = aggregate_benchmark([run_dir])
    metrics = payload["metrics"]

    assert metrics["task_action_count"] == 1
    assert metrics["scroll_action_count"] == 1
    # The one task-meaningful action (the tap) failed -> 0.0, NOT 0.5 diluted by
    # the succeeded scroll.
    assert metrics["action_success_rate"] == 0.0
    assert metrics["unknown_rate"] == 0.0
    assert metrics["scroll_success_rate"] == 1.0
    assert validate_benchmark(payload) == []


def test_aggregate_benchmark_projects_attempt_groups_and_metrics(tmp_path):
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        task="settings_readonly_walkthrough",
        terminal_expected_state={"kind": "page_id", "payload": {"page_id": "settings/root"}},
    )

    assert validate_benchmark(payload) == []
    assert payload["config"]["phone_model"] == "iphone_test"
    assert payload["metrics"]["task_completion_rate"] == 1.0
    assert payload["metrics"]["action_success_rate"] == 1.0
    assert payload["metrics"]["unknown_rate"] == 0.0
    assert payload["metrics"]["vlm_calls"] == 1
    assert payload["metrics"]["vlm_calls_per_task"] == 1.0
    assert payload["metrics"]["vlm_cache_hits"] == 0
    assert payload["metrics"]["vlm_cache_misses"] == 1
    assert payload["metrics"]["vlm_cache_hit_rate"] == 0.0
    task = payload["tasks"][0]
    assert task["final_state"]["page_id"] == "settings/root"
    action = task["actions"][0]
    assert action["verdict"] == "succeeded"
    assert action["raw_semantic_status"] == "succeeded"
    assert action["attempt_count"] == 2
    assert action["vlm_cache_misses"] == 1
    assert action["strategy_switches"] == 1
    assert action["retries"] == 0
    assert payload["metrics"]["strategy_switches"] == 1
    assert payload["metrics"]["retries"] == 0
    assert len(action["attempts"]) == 2
    assert action["attempts"][1]["vlm_cache_misses"] == 1
    assert action["attempts"][1]["switched_reason"] == "expected_state_unmet"
    assert action["verification_source"] == "vlm"


def test_aggregate_benchmark_manifest_supports_fixed_task_set(tmp_path):
    home_run = _run_dir(tmp_path / "home", status="succeeded")
    launch_run = _run_dir(tmp_path / "launch", status="succeeded")
    manifest = tmp_path / "tasks.json"
    _write_json(
        manifest,
        {
            "config": {"task_set": "canonical_primitives"},
            "tasks": [
                {
                    "run_dir": "home/run-succeeded",
                    "task": "go_home",
                    "round": 0,
                    "terminal_expected_state": {
                        "kind": "visible_text",
                        "payload": {"any_of": ["设置"]},
                    },
                },
                {
                    "run_dir": str(launch_run),
                    "task": "launch_app",
                    "round": 1,
                    "terminal_expected_state": {
                        "kind": "page_id",
                        "payload": {"page_id": "settings/root"},
                    },
                },
            ],
        },
    )

    payload = aggregate_benchmark_manifest(manifest)

    assert validate_benchmark(payload) == []
    assert payload["config"]["task_set"] == "canonical_primitives"
    assert [task["task"] for task in payload["tasks"]] == ["go_home", "launch_app"]
    assert [task["round"] for task in payload["tasks"]] == [0, 1]
    assert payload["tasks"][0]["artifact_run_dir"] == str(home_run.resolve())
    assert payload["metrics"]["task_completion_rate"] == 1.0


def test_task_completion_rate_uses_terminal_expected_state(tmp_path):
    payload = aggregate_benchmark(
        [_run_dir(tmp_path, status="succeeded")],
        terminal_expected_state={"kind": "page_id", "payload": {"page_id": "settings/about"}},
    )

    assert validate_benchmark(payload) == []
    assert payload["tasks"][0]["outcome"] == "failed"
    assert payload["metrics"]["task_completion_rate"] == 0.0
    assert payload["metrics"]["action_success_rate"] == 1.0


def test_task_completion_rate_supports_visible_text_terminal_state(tmp_path):
    payload = aggregate_benchmark(
        [_run_dir(tmp_path, status="succeeded")],
        terminal_expected_state={"kind": "visible_text", "payload": {"any_of": ["设置"]}},
    )

    assert validate_benchmark(payload) == []
    assert payload["tasks"][0]["outcome"] == "succeeded"
    assert payload["tasks"][0]["final_state"]["visible_texts"] == ["设置"]
    assert payload["metrics"]["task_completion_rate"] == 1.0


def test_task_completion_rate_supports_element_terminal_states(tmp_path):
    appeared = aggregate_benchmark(
        [_run_dir(tmp_path / "appeared", status="succeeded")],
        terminal_expected_state={"kind": "element_appears", "payload": {"role": "text", "text": "设置"}},
    )
    gone = aggregate_benchmark(
        [_run_dir(tmp_path / "gone", status="succeeded")],
        terminal_expected_state={"kind": "element_gone", "payload": {"text": "不存在"}},
    )

    assert validate_benchmark(appeared) == []
    assert validate_benchmark(gone) == []
    assert appeared["tasks"][0]["outcome"] == "succeeded"
    assert gone["tasks"][0]["outcome"] == "succeeded"
    assert appeared["metrics"]["task_completion_rate"] == 1.0
    assert gone["metrics"]["task_completion_rate"] == 1.0


def test_root_page_coverage_counts_successfully_visited_pages(tmp_path):
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        expected_root_pages=["Settings", "无线局域网"],
    )
    task = payload["tasks"][0]
    assert task["root_pages_expected"] == 2
    assert task["root_pages_covered"] == 1          # the succeeded primary opened "Settings"
    assert task["root_pages_missing"] == ["无线局域网"]
    assert payload["metrics"]["root_pages_coverage"] == 0.5
    assert validate_benchmark(payload) == []


def test_root_page_coverage_prefers_walkthrough_report(tmp_path):
    # The walkthrough's own root_coverage is authoritative; the orchestrator
    # action ledger does not record row navigations as matchable primary actions.
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        expected_root_pages=["ignored-when-report-present"],
        root_coverages=[{"expected": ["无线局域网", "蓝牙", "通用"], "visited": ["无线局域网", "通用"]}],
    )
    task = payload["tasks"][0]
    assert task["root_pages_expected"] == 3
    assert task["root_pages_covered"] == 2
    assert task["root_pages_missing"] == ["蓝牙"]
    assert payload["metrics"]["root_pages_coverage"] == 2 / 3
    assert validate_benchmark(payload) == []


def test_root_page_coverage_uses_entered_and_excludes_blocked(tmp_path):
    # entered = actually opened; visible_only = seen on root but not entered;
    # blocked = deliberately not entered (unsafe) and excluded from the denominator.
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        root_coverages=[{
            "expected": ["A", "B", "C", "D"],
            "entered": ["A", "B"],
            "visible_only": ["C"],
            "blocked": ["D"],
        }],
    )
    task = payload["tasks"][0]
    assert task["root_pages_expected"] == 4
    assert task["root_pages_covered"] == 2
    assert task["root_pages_blocked"] == 1
    assert task["root_pages_missing"] == ["C"]
    assert payload["metrics"]["root_pages_coverage"] == 2 / 3  # entered / (expected - blocked)
    assert validate_benchmark(payload) == []


def test_validate_benchmark_rejects_covered_exceeding_reachable(tmp_path):
    """covered > expected − blocked would report root_pages_coverage > 1.0
    (covered ÷ reachable in _metrics), so validation must reject it."""
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        root_coverages=[{"expected": ["A", "B"], "entered": ["A"], "blocked": ["B"]}],
    )
    assert validate_benchmark(payload) == []  # consistent baseline
    payload["tasks"][0]["root_pages_covered"] = 2  # reachable = 2 − 1 = 1
    errors = validate_benchmark(payload)
    assert any("root_pages_covered" in e and "must not exceed reachable" in e for e in errors)


def test_validate_benchmark_rejects_blocked_exceeding_expected(tmp_path):
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        root_coverages=[{"expected": ["A", "B"], "entered": ["A"]}],
    )
    payload["tasks"][0]["root_pages_blocked"] = 3  # > expected (2)
    errors = validate_benchmark(payload)
    assert any("root_pages_blocked" in e and "must not exceed" in e for e in errors)


def test_validate_benchmark_rejects_non_string_missing(tmp_path):
    payload = aggregate_benchmark(
        [_run_dir(tmp_path)],
        root_coverages=[{"expected": ["A", "B"], "entered": ["A"]}],
    )
    payload["tasks"][0]["root_pages_missing"] = ["B", 123]
    errors = validate_benchmark(payload)
    assert any("root_pages_missing must be a list of strings" in e for e in errors)


def test_root_page_coverage_absent_without_expected_pages(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    assert payload["tasks"][0]["root_pages_expected"] == 0
    assert payload["metrics"]["root_pages_coverage"] == 0.0


def test_root_page_coverage_drop_fails_compare(tmp_path):
    baseline = aggregate_benchmark([_run_dir(tmp_path / "b")], expected_root_pages=["Settings"])
    candidate = aggregate_benchmark(
        [_run_dir(tmp_path / "c")],
        expected_root_pages=["Settings", "无线局域网"],
    )
    rc, lines = compare_benchmarks(baseline, candidate)
    assert rc == 1
    assert any("root_pages_coverage" in line for line in lines)


def test_validate_benchmark_recomputes_metrics(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    payload["metrics"]["action_success_rate"] = 0.0

    errors = validate_benchmark(payload)

    assert any("metrics.action_success_rate mismatch" in error for error in errors)


def test_validate_benchmark_rejects_invalid_metric_types(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    payload["metrics"]["action_success_rate"] = "high"
    payload["metrics"]["recoveries"] = True

    errors = validate_benchmark(payload)
    rc, lines = compare_benchmarks(aggregate_benchmark([_run_dir(tmp_path / "baseline")]), payload)

    assert "metrics.action_success_rate must be a number" in errors
    assert "metrics.recoveries must be a non-negative integer" in errors
    assert rc == 2
    assert any("candidate: metrics.action_success_rate must be a number" in line for line in lines)


def test_validate_benchmark_rejects_non_finite_numbers(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    payload["metrics"]["action_success_rate"] = float("nan")
    payload["tasks"][0]["actions"][0]["confidence"] = float("inf")

    errors = validate_benchmark(payload)
    rc, lines = compare_benchmarks(aggregate_benchmark([_run_dir(tmp_path / "baseline")]), payload)

    assert "metrics.action_success_rate must be a number" in errors
    assert "tasks[0].actions[0].confidence must be a number" in errors
    assert rc == 2
    assert any("candidate: metrics.action_success_rate must be a number" in line for line in lines)


def test_validate_benchmark_rejects_invalid_top_level_and_task_schema(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    payload["run_id"] = ""
    payload["started_at"] = None
    payload["git_sha"] = ""
    payload["config"] = []
    payload["tasks"][0]["task"] = ""
    payload["tasks"][0]["round"] = True
    payload["tasks"][0]["final_state"] = {
        "page_id": 123,
        "is_anchor": "yes",
        "visible_texts": ["设置", 9],
    }

    errors = validate_benchmark(payload)

    assert "run_id must be a non-empty string" in errors
    assert "started_at must be a non-empty string" in errors
    assert "git_sha must be a non-empty string" in errors
    assert "config must be an object" in errors
    assert "tasks[0].task must be a non-empty string" in errors
    assert "tasks[0].round must be a non-negative integer" in errors
    assert "tasks[0].final_state.page_id must be a string or null" in errors
    assert "tasks[0].final_state.is_anchor must be a boolean" in errors
    assert "tasks[0].final_state.visible_texts must be a list of strings" in errors


def test_validate_benchmark_reports_malformed_actions_without_crashing(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    payload["tasks"][0]["actions"] = "not-a-list"

    errors = validate_benchmark(payload)

    assert "tasks[0].actions must be a list" in errors
    assert any("metrics.action_success_rate mismatch" in error for error in errors)


def test_validate_benchmark_reports_non_object_action_without_crashing(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    payload["tasks"][0]["actions"] = ["not-an-object"]

    errors = validate_benchmark(payload)

    assert "tasks[0].actions[0] must be an object" in errors
    assert any("metrics.action_success_rate mismatch" in error for error in errors)


def test_validate_benchmark_rejects_invalid_vlm_and_attempt_schema(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path)])
    action = payload["tasks"][0]["actions"][0]
    payload["tasks"][0]["terminal_expected_state"]["kind"] = "not_a_state"
    action["seq"] = True
    action["op"] = ""
    action["target"] = 123
    action["chosen_strategy"] = ""
    action["semantic_verifier"] = ""
    action["expected_state"]["kind"] = "also_not_a_state"
    action["vlm_triggers"] = ["not_a_trigger"]
    action["last_vlm_trigger"] = "verify_unknown"
    action["vlm_cache_hits"] = True
    action["vlm_budget_exhausted"] = "no"
    action["strategy_switches"] = True
    action["attempt_count"] = True
    action["attempts"][0]["idx"] = 9
    action["attempts"][0]["vlm_calls"] = True
    action["attempts"][0]["verification_source"] = "guess"

    errors = validate_benchmark(payload)

    assert "tasks[0].terminal_expected_state.kind is invalid" in errors
    assert "tasks[0].actions[0].seq must be a non-negative integer" in errors
    assert "tasks[0].actions[0].op must be a non-empty string" in errors
    assert "tasks[0].actions[0].target must be a string" in errors
    assert "tasks[0].actions[0].chosen_strategy must be a non-empty string" in errors
    assert "tasks[0].actions[0].semantic_verifier must be a non-empty string" in errors
    assert "tasks[0].actions[0].expected_state.kind is invalid" in errors
    assert any("vlm_triggers has invalid values" in error for error in errors)
    assert any("last_vlm_trigger must be present" in error for error in errors)
    assert any("vlm_cache_hits must be a non-negative integer" in error for error in errors)
    assert any("vlm_budget_exhausted must be a boolean" in error for error in errors)
    assert any("strategy_switches must be a non-negative integer" in error for error in errors)
    assert any("attempt_count must be a non-negative integer" in error for error in errors)
    assert any("attempts[0].idx must equal 0" in error for error in errors)
    assert any("attempts[0].vlm_calls must be a non-negative integer" in error for error in errors)
    assert any("attempts[0].verification_source is invalid" in error for error in errors)


def test_aggregate_benchmark_counts_p3_recovery_events(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path, status="failed_recovered")])

    assert validate_benchmark(payload) == []
    assert payload["tasks"][0]["actions"][0]["recovered"] is True
    assert payload["metrics"]["recoveries"] == 1


def test_aggregate_benchmark_does_not_mark_failed_recovery_as_recovered(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path, status="failed_recovery_attempt")])

    assert validate_benchmark(payload) == []
    assert payload["tasks"][0]["actions"][0]["recovered"] is False
    assert payload["metrics"]["recoveries"] == 0


def test_aggregate_benchmark_excludes_recovery_actions_from_success_denominators(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path, status="with_recovery_action")])

    assert validate_benchmark(payload) == []
    actions = payload["tasks"][0]["actions"]
    assert [action["role"] for action in actions] == ["primary", "recovery"]
    assert payload["metrics"]["action_success_rate"] == 1.0
    assert payload["metrics"]["unknown_rate"] == 0.0
    assert payload["metrics"]["recoveries"] == 1


def test_aggregate_benchmark_honors_explicit_recovery_role(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    actions = [json.loads(line) for line in (run_dir / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    actions[-1]["role"] = "recovery"
    _append_jsonl(run_dir / "actions.jsonl", *actions)

    payload = aggregate_benchmark([run_dir])

    assert validate_benchmark(payload) == []
    assert payload["tasks"][0]["actions"][0]["role"] == "recovery"
    assert payload["metrics"]["action_success_rate"] == 0.0


def test_aggregate_benchmark_deduplicates_recovered_primary_and_recovery_action(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path, status="recovered_with_recovery_action")])

    assert validate_benchmark(payload) == []
    actions = payload["tasks"][0]["actions"]
    assert [action["role"] for action in actions] == ["primary", "recovery"]
    assert actions[0]["recovered"] is True
    assert actions[1]["recovered"] is False
    assert payload["metrics"]["recoveries"] == 1


def test_aggregate_benchmark_counts_transport_retry_without_strategy_switch(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path, status="transport_retried")])

    assert validate_benchmark(payload) == []
    action = payload["tasks"][0]["actions"][0]
    assert action["attempt_count"] == 2
    assert action["strategy_switches"] == 0
    assert action["retries"] == 1
    assert payload["metrics"]["strategy_switches"] == 0
    assert payload["metrics"]["retries"] == 1


def test_aggregate_benchmark_records_runtime_strategy_switch_reason_without_retry(tmp_path):
    payload = aggregate_benchmark([_run_dir(tmp_path, status="runtime_strategy_switched")])

    assert validate_benchmark(payload) == []
    action = payload["tasks"][0]["actions"][0]
    assert action["strategy_switches"] == 1
    assert action["retries"] == 0
    assert action["attempts"][1]["switched_reason"] == "expected state unmet"
    assert payload["metrics"]["strategy_switches"] == 1
    assert payload["metrics"]["retries"] == 0


def test_compare_benchmarks_shows_recovery_improving_task_completion(tmp_path):
    terminal = {"kind": "page_id", "payload": {"page_id": "settings/root"}}
    baseline = aggregate_benchmark(
        [_run_dir(tmp_path, status="failed_recovered")],
        terminal_expected_state=terminal,
    )
    candidate = aggregate_benchmark(
        [_run_dir(tmp_path, status="succeeded_recovered")],
        terminal_expected_state=terminal,
    )

    rc, lines = compare_benchmarks(baseline, candidate)

    assert rc == 0
    assert baseline["metrics"]["task_completion_rate"] == 0.0
    assert candidate["metrics"]["task_completion_rate"] == 1.0
    assert candidate["metrics"]["recoveries"] == 1
    assert any(line.startswith("task_completion_rate:") and "delta=+1" in line for line in lines)
    assert any(line.startswith("recoveries:") and "delta=+0" in line for line in lines)


def test_compare_benchmarks_fails_on_success_rate_regression(tmp_path):
    baseline = aggregate_benchmark([_run_dir(tmp_path, status="succeeded")])
    candidate = aggregate_benchmark([_run_dir(tmp_path, status="unknown")])

    rc, lines = compare_benchmarks(baseline, candidate)

    assert rc == 1
    assert any(line.startswith("action_success_rate:") for line in lines)
    assert any(line.startswith("unknown_rate:") for line in lines)
    assert any(line.startswith("vlm_calls:") for line in lines)
    assert any(line.startswith("vlm_calls_per_task:") for line in lines)
    assert any(line.startswith("vlm_cache_hits:") for line in lines)
    assert any(line.startswith("vlm_cache_misses:") for line in lines)
    assert any(line.startswith("vlm_cache_hit_rate:") for line in lines)


def test_compare_benchmarks_respects_success_rate_regression_tolerance(tmp_path):
    baseline = aggregate_benchmark(
        [
            _run_dir(tmp_path / "baseline-a", status="succeeded"),
            _run_dir(tmp_path / "baseline-b", status="succeeded_recovered"),
        ]
    )
    candidate = aggregate_benchmark(
        [
            _run_dir(tmp_path / "candidate-a", status="succeeded"),
            _run_dir(tmp_path / "candidate-b", status="unknown"),
        ]
    )

    tolerated_rc, tolerated_lines = compare_benchmarks(baseline, candidate, tolerance=0.5)
    strict_rc, strict_lines = compare_benchmarks(baseline, candidate, tolerance=0.49)

    assert baseline["metrics"]["action_success_rate"] == 1.0
    assert candidate["metrics"]["action_success_rate"] == 0.5
    assert candidate["metrics"]["unknown_rate"] == 0.5
    assert tolerated_rc == 0
    assert strict_rc == 1
    assert any(
        line.startswith("action_success_rate:") and "delta=-0.5" in line
        for line in tolerated_lines
    )
    assert any(
        line.startswith("unknown_rate:") and "delta=+0.5" in line
        for line in strict_lines
    )


def test_compare_benchmarks_rejects_invalid_tolerance(tmp_path):
    baseline = aggregate_benchmark([_run_dir(tmp_path / "baseline", status="succeeded")])
    candidate = aggregate_benchmark([_run_dir(tmp_path / "candidate", status="unknown")])

    negative_rc, negative_lines = compare_benchmarks(baseline, candidate, tolerance=-0.1)
    nan_rc, nan_lines = compare_benchmarks(baseline, candidate, tolerance=float("nan"))

    assert negative_rc == 2
    assert nan_rc == 2
    assert "tolerance must be a non-negative finite number" in negative_lines
    assert "tolerance must be a non-negative finite number" in nan_lines


def test_cli_aggregate_validate_and_compare(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    manifest = tmp_path / "tasks.json"
    manifest_out = tmp_path / "manifest-benchmark.json"
    _write_json(
        manifest,
        {
            "tasks": [
                {
                    "run_dir": str(run_dir),
                    "task": "go_home",
                    "round": 0,
                    "terminal_expected_state": {"kind": "visible_text", "payload": {"any_of": ["设置"]}},
                }
            ]
        },
    )

    assert main(["aggregate", "--run-dir", str(run_dir), "--out", str(baseline)]) == 0
    assert main(["validate", str(baseline)]) == 0
    assert main(["aggregate", "--run-dir", str(run_dir), "--out", str(candidate)]) == 0
    assert main(["compare", str(baseline), str(candidate)]) == 0
    assert main(["aggregate", "--task-manifest", str(manifest), "--out", str(manifest_out)]) == 0
    assert validate_benchmark(json.loads(manifest_out.read_text(encoding="utf-8"))) == []


def test_cli_aggregate_rejects_invalid_terminal_expected_state_json(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    out = tmp_path / "bad.json"

    rc = main(
        [
            "aggregate",
            "--run-dir",
            str(run_dir),
            "--out",
            str(out),
            "--terminal-expected-state",
            "{not-json",
        ]
    )

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_missing_run_dir_without_writing(tmp_path):
    out = tmp_path / "bad.json"

    rc = main(["aggregate", "--run-dir", str(tmp_path / "missing-run"), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_malformed_run_ledger_without_writing(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    out = tmp_path / "bad.json"
    (run_dir / "actions.jsonl").write_text("{not-json\n", encoding="utf-8")

    rc = main(["aggregate", "--run-dir", str(run_dir), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_invalid_task_manifest_without_writing(tmp_path):
    manifest = tmp_path / "tasks.json"
    out = tmp_path / "bad.json"
    _write_json(manifest, {"tasks": [{}]})

    rc = main(["aggregate", "--task-manifest", str(manifest), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_invalid_task_manifest_round_without_writing(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    manifest = tmp_path / "tasks.json"
    out = tmp_path / "bad.json"
    _write_json(manifest, {"tasks": [{"run_dir": str(run_dir), "round": True}]})

    rc = main(["aggregate", "--task-manifest", str(manifest), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_invalid_task_manifest_terminal_state_without_writing(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    manifest = tmp_path / "tasks.json"
    out = tmp_path / "bad.json"
    _write_json(
        manifest,
        {
            "tasks": [
                {
                    "run_dir": str(run_dir),
                    "terminal_expected_state": {"kind": "not_a_state", "payload": {}},
                }
            ]
        },
    )

    rc = main(["aggregate", "--task-manifest", str(manifest), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_malformed_task_manifest_json_without_writing(tmp_path):
    manifest = tmp_path / "tasks.json"
    out = tmp_path / "bad.json"
    manifest.write_text("{not-json\n", encoding="utf-8")

    rc = main(["aggregate", "--task-manifest", str(manifest), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_task_manifest_missing_run_dir_without_writing(tmp_path):
    manifest = tmp_path / "tasks.json"
    out = tmp_path / "bad.json"
    _write_json(manifest, {"tasks": [{"run_dir": "missing-run"}]})

    rc = main(["aggregate", "--task-manifest", str(manifest), "--out", str(out)])

    assert rc == 1
    assert not out.exists()


def test_cli_aggregate_rejects_non_object_terminal_expected_state(tmp_path):
    run_dir = _run_dir(tmp_path, status="succeeded")
    out = tmp_path / "bad.json"

    rc = main(
        [
            "aggregate",
            "--run-dir",
            str(run_dir),
            "--out",
            str(out),
            "--terminal-expected-state",
            "[]",
        ]
    )

    assert rc == 1
    assert not out.exists()


def test_cli_run_ios_settings_runs_rounds_and_aggregates(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    report_dir = tmp_path / "reports"
    out = tmp_path / "benchmark.json"
    calls = []

    def fake_run(cmd, *, cwd, env):
        index = len(calls)
        calls.append((cmd, cwd, env))
        run_dir = artifact_root / f"run-{index:03d}"
        _write_json(
            run_dir / "manifest.json",
            {
                "run_id": f"run-{index:03d}",
                "device": {"model": "iphone_test"},
            },
        )
        _write_json(run_dir / "scenes" / "before.json", {"page_id": "home"})
        _write_json(run_dir / "scenes" / "after.json", {"page_id": "settings/root"})
        _append_jsonl(
            run_dir / "actions.jsonl",
            _action(
                f"act_{index:06d}",
                f"grp_{index:06d}",
                status="succeeded",
                strategy="springboard_icon_tap",
                scene_file="scenes/after.json",
            ),
        )
        _append_jsonl(
            run_dir / "attempt_groups.jsonl",
            {
                "attempt_group_id": f"grp_{index:06d}",
                "op": "launch_app",
                "actor": "agent",
                "attempt_ids": [f"act_{index:06d}"],
                "group_status": "succeeded",
                "retry_count": 0,
            },
        )
        _append_jsonl(run_dir / "audit.jsonl")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(success_rate.subprocess, "run", fake_run)

    rc = main(
        [
            "run-ios-settings",
            "--rounds",
            "2",
            "--out",
            str(out),
            "--artifact-root",
            str(artifact_root),
            "--report-dir",
            str(report_dir),
            "--terminal-expected-state",
            '{"kind":"page_id","payload":{"page_id":"settings/root"}}',
            "--quick",
            "--skip-diagnose",
        ]
    )

    assert rc == 0
    assert len(calls) == 2
    assert all(call[0][-2:] == ["--quick", "--skip-diagnose"] for call in calls)
    assert all(call[2]["GLASSBOX_COMPUTER_USE_ARTIFACT_DIR"] == str(artifact_root.resolve()) for call in calls)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert validate_benchmark(payload) == []
    assert payload["config"]["rounds"] == 2
    assert payload["config"]["task_set"] == "ios_settings"
    assert [task["round"] for task in payload["tasks"]] == [0, 1]
    assert payload["metrics"]["task_completion_rate"] == 1.0


def test_cli_run_ios_settings_rejects_incomplete_artifact_run(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    out = tmp_path / "benchmark.json"

    def fake_run(cmd, *, cwd, env):
        del cmd, cwd, env
        run_dir = artifact_root / "run-incomplete"
        _write_json(run_dir / "manifest.json", {"run_id": "run-incomplete"})
        _append_jsonl(run_dir / "actions.jsonl")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(success_rate.subprocess, "run", fake_run)

    rc = main(
        [
            "run-ios-settings",
            "--rounds",
            "1",
            "--out",
            str(out),
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert rc == 1
    assert not out.exists()


def test_cli_run_ios_settings_rejects_malformed_artifact_run(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    out = tmp_path / "benchmark.json"

    def fake_run(cmd, *, cwd, env):
        del cmd, cwd, env
        run_dir = artifact_root / "run-malformed"
        _write_json(run_dir / "manifest.json", {"run_id": "run-malformed"})
        (run_dir / "actions.jsonl").parent.mkdir(parents=True, exist_ok=True)
        (run_dir / "actions.jsonl").write_text("{not-json\n", encoding="utf-8")
        _append_jsonl(run_dir / "attempt_groups.jsonl")
        _append_jsonl(run_dir / "audit.jsonl")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(success_rate.subprocess, "run", fake_run)

    rc = main(
        [
            "run-ios-settings",
            "--rounds",
            "1",
            "--out",
            str(out),
            "--artifact-root",
            str(artifact_root),
        ]
    )

    assert rc == 1
    assert not out.exists()


def test_cli_run_ios_settings_rejects_invalid_terminal_expected_state_before_running(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    out = tmp_path / "benchmark.json"
    calls = []

    def fake_run(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(success_rate.subprocess, "run", fake_run)

    rc = main(
        [
            "run-ios-settings",
            "--rounds",
            "1",
            "--out",
            str(out),
            "--artifact-root",
            str(artifact_root),
            "--terminal-expected-state",
            '{"kind":"not_a_state","payload":{}}',
        ]
    )

    assert rc == 1
    assert calls == []
    assert not out.exists()


def test_cli_run_ios_settings_rejects_invalid_terminal_expected_state_json(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    out = tmp_path / "benchmark.json"
    calls = []

    def fake_run(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(success_rate.subprocess, "run", fake_run)

    rc = main(
        [
            "run-ios-settings",
            "--rounds",
            "1",
            "--out",
            str(out),
            "--artifact-root",
            str(artifact_root),
            "--terminal-expected-state",
            "{not-json",
        ]
    )

    assert rc == 1
    assert calls == []
    assert not out.exists()


def test_cli_entrypoint_is_registered():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["glassbox-computer-use-success-rate"]
        == "skills.regression.computer_use_success_rate:main"
    )


def test_make_entrypoint_wraps_ios_settings_success_rate_harness():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "computer-use-success-rate-ios-settings:" in makefile
    assert "skills.regression.computer_use_success_rate" in makefile
    assert "run-ios-settings" in makefile
    assert "--rounds $(ROUNDS)" in makefile
    assert 'TERMINAL_EXPECTED_STATE ?= {"kind":"page_id","payload":{"page_id":"settings/root"}}' in makefile
