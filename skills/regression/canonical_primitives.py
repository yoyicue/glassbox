"""Canonical-primitive computer-use benchmark (CUQ-3.4).

The success-rate harness only ever runs the Settings walkthrough, so the
navigation/recovery primitives most central to reliability — **go-home**,
**launch-app**, **back**, **scroll-to-bottom** — are never benchmarked and a
regression in the fragile HID primitives is invisible to the success number.

This module defines those primitives as tiny one-action tasks and assembles a
multi-task manifest the existing `aggregate_benchmark_manifest` already scores
(per-task `terminal_expected_state` included). The task DEFINITIONS, sequencing,
and manifest assembly are here and are unit-tested against a mock phone; the
suite only *executes* on a live rig (``main`` → ``open_phone``), since the
primitives drive real HID/HDMI hardware.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# A permissive terminal: success is then judged by the action's own semantic
# verdict (captured in the run artifacts), not an absolute end-state. Used for
# primitives whose success is relative (back / scroll), where a fixed end page
# would need on-rig context.
PERMISSIVE_TERMINAL_EXPECTED_STATE: dict[str, Any] = {"kind": "unknown", "payload": {}}


@dataclass(frozen=True)
class PrimitiveTask:
    """One canonical primitive: a name, a callable that drives an AIPhone, and
    the terminal_expected_state the benchmark checks for that task."""

    name: str
    run: Callable[[Any], Any]
    terminal_expected_state: dict[str, Any] = field(
        default_factory=lambda: dict(PERMISSIVE_TERMINAL_EXPECTED_STATE)
    )
    description: str = ""


def _go_home(phone: Any) -> Any:
    return phone.home()


def _launch_settings(phone: Any) -> Any:
    # Settings is the universal anchor app present on every iOS/iPadOS device.
    return phone.launch_app("设置", aliases=("Settings",))


def _back(phone: Any) -> Any:
    return phone.back()


def _scroll_to_bottom(phone: Any, *, max_steps: int = 10) -> Any:
    # A long list (e.g. Settings root) scrolled to the bottom; closed-loop
    # overshoot/no-progress handling lives in AIPhone.scroll.
    return phone.scroll("down", max_steps=max_steps)


CANONICAL_PRIMITIVE_TASKS: tuple[PrimitiveTask, ...] = (
    PrimitiveTask(
        "go_home",
        _go_home,
        {"kind": "page_id", "payload": {"page_id": "springboard"}},
        "press Home and expect the Home screen",
    ),
    PrimitiveTask(
        "launch_app",
        _launch_settings,
        {"kind": "page_id", "payload": {"page_id": "settings/root"}},
        "launch the Settings app and expect its root",
    ),
    PrimitiveTask(
        "back",
        _back,
        dict(PERMISSIVE_TERMINAL_EXPECTED_STATE),
        "navigate back one level (success = the back action's verdict)",
    ),
    PrimitiveTask(
        "scroll_to_bottom",
        _scroll_to_bottom,
        dict(PERMISSIVE_TERMINAL_EXPECTED_STATE),
        "scroll a long list to the bottom (success = the scroll verdict)",
    ),
)

_TASKS_BY_NAME = {task.name: task for task in CANONICAL_PRIMITIVE_TASKS}


def run_primitive(phone: Any, task: PrimitiveTask) -> Any:
    """Drive a single canonical primitive against an AIPhone. Returns the
    primitive's outcome (ActionOutcome / ObservationSummary)."""
    return task.run(phone)


def run_canonical_suite(
    phone: Any, tasks: Sequence[PrimitiveTask] = CANONICAL_PRIMITIVE_TASKS
) -> list[tuple[str, Any]]:
    """Run every canonical primitive in order; returns (name, outcome) pairs."""
    return [(task.name, run_primitive(phone, task)) for task in tasks]


def build_canonical_manifest(
    run_dirs_by_task: Mapping[str, Sequence[Any]], *, rounds: int = 1
) -> dict[str, Any]:
    """Assemble a multi-task manifest (consumed by aggregate_benchmark_manifest)
    from per-task run directories. Each task entry carries its
    terminal_expected_state so the aggregator scores it correctly."""
    tasks: list[dict[str, Any]] = []
    for task in CANONICAL_PRIMITIVE_TASKS:
        for round_index, run_dir in enumerate(run_dirs_by_task.get(task.name, ())):
            tasks.append(
                {
                    "task": task.name,
                    "run_dir": str(run_dir),
                    "round": round_index,
                    "terminal_expected_state": task.terminal_expected_state,
                }
            )
    return {
        "tasks": tasks,
        "config": {"task_set": "canonical_primitives", "rounds": int(rounds)},
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig only
    """Run one canonical primitive against a live rig and save its artifacts.

    Needs a device: ``open_phone`` raises ``RuntimeUnavailable`` without HDMI/HID,
    so this entrypoint is not exercised offline (the task definitions and manifest
    assembly above are). The benchmark driver invokes this N rounds per task with
    ``GLASSBOX_COMPUTER_USE_ARTIFACT_DIR`` set, then aggregates the run dirs via
    ``build_canonical_manifest`` + ``aggregate_benchmark_manifest``.
    """
    parser = argparse.ArgumentParser(description="Run one canonical-primitive task on the rig")
    parser.add_argument("--task", required=True, choices=sorted(_TASKS_BY_NAME))
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args(argv)

    from glassbox.ai import open_phone

    task = _TASKS_BY_NAME[args.task]
    with open_phone(run_name=args.run_name or f"canonical-{task.name}") as phone:
        outcome = run_primitive(phone, task)
        artifacts = phone.save_report()
    print(Path(getattr(artifacts, "run_dir", ".")))
    return 0 if getattr(outcome, "ok", True) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
