"""Floor lineage — the value-timeline ledger's single source of format truth.

`docs/goals/flag_cell_ab_matrix.md` carries a per-cell value table of every
committed floor/snapshot change (the 地板谱系). This module owns the cell→
fixture mapping, the metric columns, and the exact number formatting, so the
table and the guard test (skills/smoke/test_floor_lineage.py) can never
disagree about presentation.

Append a new row after changing any floor fixture:

    uv run python -m skills.regression.floor_lineage

prints the CURRENT row for every cell in the doc's column format — copy the
changed cell's row into the table (with date/commit/event filled in). The
guard test fails the merge gate until the table's last row for that cell
matches the fixture again.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# cell label (as it appears in the doc table) -> fixture path
FLOOR_FIXTURES: dict[str, str] = {
    "设置": "skills/regression/fixtures/reliability_baseline.json",
    "Clock": "skills/regression/fixtures/clock_tabs_baseline.json",
    "canonical": "skills/regression/fixtures/canonical_primitives_baseline.json",
    "a11y": "skills/regression/fixtures/a11y_voice_control_cell_snapshot.json",
    "L2快照": "skills/regression/fixtures/l2_settings_expected_state_snapshot.json",
}

# the value columns, in table order
VALUE_KEYS: tuple[str, ...] = (
    "task_completion_rate",
    "action_success_rate",
    "expected_state_coverage",
    "recoveries",
    "strategy_switches",
    "vlm_action_coverage",
    "scroll_success_rate",
)


def format_value(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def current_values(cell: str) -> list[str]:
    """The cell's fixture metrics, formatted exactly as the doc table expects."""
    path = REPO_ROOT / FLOOR_FIXTURES[cell]
    metrics = json.loads(path.read_text(encoding="utf-8")).get("metrics", {})
    return [format_value(metrics.get(key)) for key in VALUE_KEYS]


def current_row(cell: str) -> str:
    """A ready-to-paste table row (date/commit/event left for the author)."""
    values = " | ".join(current_values(cell))
    return f"| {cell} | YYYY-MM-DD | `<sha>` | <事件> | {values} |"


def main() -> int:
    for cell in FLOOR_FIXTURES:
        try:
            print(current_row(cell))
        except FileNotFoundError:
            print(f"| {cell} | (fixture missing: {FLOOR_FIXTURES[cell]}) |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
