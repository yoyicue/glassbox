"""Clock-tabs walkthrough benchmark — the second app eval cell (L2 multi-cell).

The eval-layers design (docs/design/glassbox_evaluation_layers.md §2 L2) wants
the capability layer to span more than one app cell: 设备 × App × 语言. This
module defines the first non-Settings cell: a read-only walkthrough of the
stock iPadOS **Clock** app — launch it, visit all four top tabs (Alarms →
Stopwatch → Timers → World Clock), and verify each tab's content anchor.

Why Clock: four fixed tabs, zero-risk read-only navigation (the walkthrough
never touches '+', Start, or any toggle), and OCR-friendly anchors. There is
no Clock scene classifier (page_id is None outside Settings/SpringBoard), so
expectations use the **visible_text** terminal kind — per-tab content anchors
that are tab-specific substrings:

  Alarms      -> "No Alarms"          (cell profile: this rig has no alarms)
  Stopwatch   -> "LAP NO." / "Start"  (never tapped, only asserted visible)
  Timers      -> "hours"              (the duration wheel labels)
  World Clock -> "Sunrise"            (cell profile: rig has cities configured)

The per-tab ``expect_visible`` threads an expected_state into the orchestrator
(CUQ-0.3), so the cell carries real ``expected_state_coverage``; the task's
``terminal_expected_state`` is the World Clock anchor (the walkthrough ends
back on the default tab), making ``task_completion_rate`` execution-based.

Like canonical_primitives: the task DEFINITIONS, sequencing, and manifest
assembly are here and unit-tested against a mock phone; the suite only
*executes* on a live rig (``main`` → ``open_phone``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

TASK_NAME = "clock_tabs_walkthrough"
TASK_SET = "ipados_clock_tabs"

# (tab label to tap, tab-specific content anchors — visible_text any_of)
CLOCK_TAB_VISITS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Alarms", ("No Alarms",)),
    ("Stopwatch", ("LAP NO.", "Start")),
    ("Timers", ("hours",)),
    ("World Clock", ("Sunrise",)),
)

# The walkthrough ends on World Clock, so the execution-based terminal is its
# anchor. Substring semantics: matches e.g. "Sunrise: 5:47 AM".
TERMINAL_EXPECTED_STATE: dict[str, Any] = {
    "kind": "visible_text",
    "payload": {"any_of": ["Sunrise"]},
}


def run_clock_tabs_walkthrough(phone: Any) -> list[tuple[str, Any]]:
    """Drive the walkthrough against an AIPhone; returns (tab, outcome) pairs.

    Read-only by construction: the only taps are the four tab labels. The
    dangerous controls on these pages ('+', Start, alarm toggles) are never
    targeted.
    """
    phone.launch_app("时钟", aliases=("Clock",))
    outcomes: list[tuple[str, Any]] = []
    for tab, anchors in CLOCK_TAB_VISITS:
        outcome = phone.tap(tab, expect_visible=list(anchors))
        outcomes.append((tab, outcome))
    return outcomes


def build_clock_tabs_manifest(
    run_dirs: Sequence[Any], *, rounds: int = 1
) -> dict[str, Any]:
    """Assemble the multi-round manifest consumed by aggregate_benchmark_manifest."""
    tasks: list[dict[str, Any]] = []
    for round_index, run_dir in enumerate(run_dirs):
        tasks.append(
            {
                "task": TASK_NAME,
                "run_dir": str(run_dir),
                "round": round_index,
                "terminal_expected_state": dict(TERMINAL_EXPECTED_STATE),
            }
        )
    return {
        "tasks": tasks,
        "config": {
            "task_set": TASK_SET,
            "rounds": int(rounds),
        },
    }


def cell_profile_notes() -> Mapping[str, str]:
    """Device-state assumptions this cell's anchors depend on (documented the
    same way the Settings cell documents device-inert roots)."""
    return {
        "alarms": "no alarms configured on the rig (anchor 'No Alarms')",
        "world_clock": "world-clock cities configured (anchor 'Sunrise: …' rows)",
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig only
    """Run one walkthrough round against a live rig and save its artifacts.

    Needs a device: ``open_phone`` raises ``RuntimeUnavailable`` without
    HDMI/HID. The benchmark driver invokes this N rounds with
    ``GLASSBOX_COMPUTER_USE_ARTIFACT_DIR`` set, then aggregates via
    ``build_clock_tabs_manifest`` + ``aggregate_benchmark_manifest``.
    """
    parser = argparse.ArgumentParser(description="Run the Clock-tabs walkthrough on the rig")
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args(argv)

    from glassbox.ai import open_phone

    with open_phone(run_name=args.run_name or "clock-tabs-walkthrough") as phone:
        outcomes = run_clock_tabs_walkthrough(phone)
        artifacts = phone.save_report()
    print(Path(getattr(artifacts, "run_dir", ".")))
    return 0 if all(getattr(outcome, "ok", False) for _, outcome in outcomes) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
