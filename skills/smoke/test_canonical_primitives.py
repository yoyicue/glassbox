"""Offline tests for the canonical-primitive benchmark (CUQ-3.4).

The suite only *executes* on a rig (main → open_phone), but the task
definitions, sequencing, and manifest assembly are pure and unit-tested here."""
from __future__ import annotations

import json

import pytest

from skills.regression.canonical_primitives import (
    CANONICAL_PRIMITIVE_TASKS,
    NAVIGATION_ORIGIN_POLICY,
    build_canonical_manifest,
    prepare_canonical_task_origin,
    run_canonical_suite,
    run_primitive,
)
from skills.regression.computer_use_success_rate import _validate_expected_state


class _MockAIPhone:
    """Records the AIPhone primitive calls a canonical task makes."""

    def __init__(self):
        self.calls: list[tuple] = []

    def home(self):
        self.calls.append(("home",))
        return type("O", (), {"ok": True})()

    def back(self):
        self.calls.append(("back",))
        return type("O", (), {"ok": True})()

    def launch_app(self, app, *, aliases=()):
        self.calls.append(("launch_app", app, tuple(aliases)))
        return type("O", (), {"ok": True})()

    def scroll(self, direction="down", *, max_steps=None, **_kw):
        self.calls.append(("scroll", direction, max_steps))
        return type("O", (), {"ok": True})()


class _OriginAIPhone(_MockAIPhone):
    def __init__(self, run_dir):
        super().__init__()
        self.run_dir = run_dir
        self.manifest_updates: list[dict] = []

    def home(self):
        self.calls.append(("home",))
        return type(
            "O",
            (),
            {
                "ok": True,
                "semantic_status": "succeeded",
                "semantic_verifier": "ios_home_screen_visible",
            },
        )()

    def update_manifest(self, payload):
        self.manifest_updates.append(dict(payload))


@pytest.mark.smoke
def test_canonical_suite_drives_each_primitive_in_order():
    phone = _MockAIPhone()
    results = run_canonical_suite(phone)

    assert [name for name, _ in results] == [
        "go_home",
        "launch_app",
        "back",
        "scroll_to_bottom",
    ]
    assert phone.calls == [
        ("home",),
        ("launch_app", "设置", ("Settings",)),
        ("back",),
        ("scroll", "down", 10),
    ]


@pytest.mark.smoke
def test_canonical_task_origin_resets_and_records_verified_home_precondition(tmp_path):
    phone = _OriginAIPhone(tmp_path / "run")

    origin = prepare_canonical_task_origin(phone)

    assert origin.can_start_clock is True
    assert phone.calls == [("home",)]
    assert phone.manifest_updates == [
        {
            "navigation_origin": {
                "policy": NAVIGATION_ORIGIN_POLICY,
                "attempted": True,
                "home_reached": True,
                "can_start_clock": True,
                "reason": "verified_home_reached",
                "action_ok": True,
                "semantic_status": "succeeded",
                "semantic_verifier": "ios_home_screen_visible",
                "error": None,
            }
        }
    ]
    recorded = json.loads((phone.run_dir / "navigation_origin.json").read_text(encoding="utf-8"))
    assert recorded["policy"] == NAVIGATION_ORIGIN_POLICY
    assert recorded["can_start_clock"] is True


@pytest.mark.smoke
def test_each_primitive_runs_its_own_action_not_a_neighbor():
    """Pins each task to its own primitive (a mis-wired go_home→back would fail)."""
    by_name = {t.name: t for t in CANONICAL_PRIMITIVE_TASKS}

    p = _MockAIPhone()
    run_primitive(p, by_name["go_home"])
    assert p.calls == [("home",)]

    p = _MockAIPhone()
    run_primitive(p, by_name["launch_app"])
    assert p.calls == [("launch_app", "设置", ("Settings",))]

    p = _MockAIPhone()
    run_primitive(p, by_name["back"])
    assert p.calls == [("back",)]

    p = _MockAIPhone()
    run_primitive(p, by_name["scroll_to_bottom"])
    assert p.calls == [("scroll", "down", 10)]


@pytest.mark.smoke
def test_canonical_task_terminal_expected_states_are_valid():
    """Every task's terminal_expected_state must pass the harness validator the
    aggregator runs, so a malformed terminal can't slip into the benchmark."""
    for task in CANONICAL_PRIMITIVE_TASKS:
        errors: list[str] = []
        _validate_expected_state(task.terminal_expected_state, task.name, errors)
        assert errors == [], f"{task.name}: {errors}"


@pytest.mark.smoke
def test_build_canonical_manifest_shapes_tasks_for_aggregator(tmp_path):
    run_dirs = {
        "go_home": [tmp_path / "go_home-0", tmp_path / "go_home-1"],
        "launch_app": [tmp_path / "launch_app-0"],
    }
    manifest = build_canonical_manifest(run_dirs, rounds=2)

    assert manifest["config"] == {
        "task_set": "canonical_primitives",
        "rounds": 2,
        "navigation_origin_policy": NAVIGATION_ORIGIN_POLICY,
    }
    tasks = manifest["tasks"]
    # 2 go_home rounds + 1 launch_app round; back/scroll absent (no run dirs).
    assert [t["task"] for t in tasks] == ["go_home", "go_home", "launch_app"]
    assert [t["round"] for t in tasks] == [0, 1, 0]
    # go_home carries its concrete terminal; every entry has the required fields.
    assert tasks[0]["terminal_expected_state"] == {
        "kind": "page_id",
        "payload": {"page_id": "springboard"},
    }
    for entry in tasks:
        assert set(entry) >= {"task", "run_dir", "round", "terminal_expected_state"}
