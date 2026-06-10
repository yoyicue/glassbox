"""Machinery-probe computer-use benchmark (P2/P3 fault-injection).

The clean reliability floor escalates nothing — on a healthy Settings drill-down
every tap verifies first-try, so ``strategy_switches`` and ``recoveries`` are 0
*by design* (an honest "no escalation occurred"). That is good, but it leaves the
strategy ladder (P2) and the stuck→recover machinery (P3) with **no committed,
blocking regression signal**: a PR that silently breaks the ladder or recovery
merges green because the clean floor never exercises them, and gating "coverage
must not drop" on a clean run is perverse (a more reliable path escalates *less*).

This module closes that gap with a deliberate, clearly-labelled **fault
injection**: tap a present row but declare an *unreachable* expected page, so the
orchestrator's expected-state verification fails on every strategy. The machine's
correct response is to advance the strategy ladder and fire a recovery cycle — so
the honest invariant is "**the machine fired**" (``strategy_switches >= 1`` AND
``recoveries >= 1``). A drop to 0 means the ladder/recovery machinery broke. This
is a separate ``task_set="machinery_probe"`` cell; the injected task is *expected*
to not complete (``task_completion`` is not its success signal) and it must never
be conflated with the reliability completion floor.

The task DEFINITIONS + manifest assembly + the "machine fired" gate are here and
are unit-tested against a mock phone; the suite only *executes* on a live rig
(``main`` → ``open_phone``), since it drives real HID/HDMI hardware.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# An expected page_id no real Settings screen can satisfy. Tapping a present row
# while declaring this page guarantees the post-action expected-state check fails
# on every strategy, which is what drives the ladder + recovery we want to probe.
UNREACHABLE_PAGE_ID = "settings/__machinery_probe_unreachable__"

# The injected task is supposed to NOT reach its (impossible) target, so its
# terminal expectation is permissive — success is judged by "did the machine
# fire", not by the unreachable page.
PERMISSIVE_TERMINAL_EXPECTED_STATE: dict[str, Any] = {"kind": "unknown", "payload": {}}


@dataclass(frozen=True)
class MachineryProbeTask:
    """One fault-injection probe: a name, a callable that drives an AIPhone into a
    controlled verification failure, and a description."""

    name: str
    run: Callable[[Any], Any]
    description: str = ""
    terminal_expected_state: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.terminal_expected_state is None:
            object.__setattr__(
                self, "terminal_expected_state", dict(PERMISSIVE_TERMINAL_EXPECTED_STATE)
            )


def _readable_row_text(phone: Any) -> str:
    """Return the text of a present, readable row to tap (locale-independent —
    we tap whatever is on screen, not a fixed English/Chinese label)."""
    elements = list(phone.elements())
    rows = [
        element
        for element in elements
        if (getattr(element, "text", "") or "").strip()
        and getattr(element, "type", "") == "list_item"
    ]
    if not rows:
        rows = [element for element in elements if (getattr(element, "text", "") or "").strip()]
    if not rows:
        raise RuntimeError("machinery probe: no readable row on screen to tap")
    return str(rows[0].text)


def _wrong_expectation_tap(phone: Any) -> Any:
    """Inject a controlled verification failure.

    Open Settings (a universal anchor), then tap a present row while declaring an
    UNREACHABLE expected page. The tap lands, but expected-state verification can
    never succeed, so the orchestrator advances its strategy ladder (P2) and the
    stuck-detector fires a recovery cycle (P3). We tap a real on-screen row so the
    failure is in VERIFICATION (the path the machine is meant to handle), not in
    target-finding.
    """
    phone.launch_app("设置", aliases=("Settings",))
    target = _readable_row_text(phone)
    return phone.tap(target, expect_page=UNREACHABLE_PAGE_ID)


MACHINERY_PROBE_TASKS: tuple[MachineryProbeTask, ...] = (
    MachineryProbeTask(
        "wrong_expectation_tap",
        _wrong_expectation_tap,
        "tap a present row with an unreachable expected page; the strategy ladder "
        "and recovery must fire",
    ),
)

_TASKS_BY_NAME = {task.name: task for task in MACHINERY_PROBE_TASKS}


def run_probe(phone: Any, task: MachineryProbeTask) -> Any:
    """Drive a single machinery probe against an AIPhone."""
    return task.run(phone)


def build_machinery_probe_manifest(
    run_dirs_by_task: Mapping[str, Sequence[Any]], *, rounds: int = 1
) -> dict[str, Any]:
    """Assemble a multi-task manifest (consumed by aggregate_benchmark_manifest)
    from per-task run directories."""
    tasks: list[dict[str, Any]] = []
    for task in MACHINERY_PROBE_TASKS:
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
        "config": {
            "task_set": "machinery_probe",
            "rounds": int(rounds),
        },
    }


def machinery_fired_reasons(benchmark: Mapping[str, Any]) -> list[str]:
    """Return reasons the probe FAILED to fire the machine (empty list = the
    ladder + recovery both fired, which is the pass condition).

    This is the blocking invariant: a deliberate verification failure MUST drive
    ``strategy_switches >= 1`` (the ladder advanced) and ``recoveries >= 1`` (the
    stuck-detector recovered). A drop to 0 means the P2/P3 machinery regressed.
    """
    metrics = benchmark.get("metrics")
    if not isinstance(metrics, Mapping):
        return ["benchmark has no metrics block"]
    reasons: list[str] = []
    strategy_switches = metrics.get("strategy_switches", 0) or 0
    recoveries = metrics.get("recoveries", 0) or 0
    if strategy_switches < 1:
        reasons.append(
            f"strategy_switches={strategy_switches} < 1: the strategy ladder did not "
            "advance on an unsatisfiable expectation (P2 ladder regressed)"
        )
    if recoveries < 1:
        reasons.append(
            f"recoveries={recoveries} < 1: the stuck-detector recovery did not fire "
            "on an unsatisfiable expectation (P3 recovery regressed)"
        )
    return reasons


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig only
    """Run one machinery probe against a live rig and save its artifacts.

    Needs a device: ``open_phone`` raises ``RuntimeUnavailable`` without HDMI/HID,
    so this entrypoint is not exercised offline (the task definitions, manifest
    assembly, and the ``machinery_fired_reasons`` gate above are). The benchmark
    driver invokes this N rounds with ``GLASSBOX_COMPUTER_USE_ARTIFACT_DIR`` set,
    then aggregates the run dirs via ``build_machinery_probe_manifest`` +
    ``aggregate_benchmark_manifest``.
    """
    parser = argparse.ArgumentParser(description="Run one machinery-probe task on the rig")
    parser.add_argument("--task", default="wrong_expectation_tap", choices=sorted(_TASKS_BY_NAME))
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args(argv)

    from glassbox.ai import open_phone

    task = _TASKS_BY_NAME[args.task]
    with open_phone(run_name=args.run_name or f"machinery-probe-{task.name}") as phone:
        run_probe(phone, task)
        artifacts = phone.save_report()
    print(Path(getattr(artifacts, "run_dir", ".")))
    # The probe is EXPECTED to fail its (impossible) target; success of THIS
    # entrypoint just means it ran and saved artifacts. The "machine fired" gate
    # runs over the aggregated benchmark, not here.
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
