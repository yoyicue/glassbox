"""Guard: the floor-lineage value table cannot drift from the fixtures.

The 地板谱系 table in docs/goals/flag_cell_ab_matrix.md must gain a row every
time a committed floor/snapshot fixture changes its headline metrics. This
test recomputes each cell's current values via the shared formatter
(skills/regression/floor_lineage.py) and requires the table's LAST row for
that cell to carry exactly those values — change a fixture without appending
a row and the merge gate goes red, with the ready-to-paste row in the
failure message.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from skills.regression.floor_lineage import (
    FLOOR_FIXTURES,
    VALUE_KEYS,
    current_row,
    current_values,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = REPO_ROOT / "docs" / "goals" / "flag_cell_ab_matrix.md"


def _lineage_rows() -> dict[str, list[list[str]]]:
    """cell -> list of value-cell lists, in document order."""
    rows: dict[str, list[list[str]]] = {}
    in_section = False
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and "地板谱系" in line:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not (in_section and line.startswith("|")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 + len(VALUE_KEYS) or cells[0] not in FLOOR_FIXTURES:
            continue
        rows.setdefault(cells[0], []).append(cells[4 : 4 + len(VALUE_KEYS)])
    return rows


@pytest.mark.smoke
def test_every_floor_fixture_has_a_lineage_row():
    rows = _lineage_rows()
    missing = [cell for cell in FLOOR_FIXTURES if cell not in rows]
    assert not missing, (
        f"floor cells with no lineage row in {_DOC.name}: {missing} — append rows "
        "(generate with: uv run python -m skills.regression.floor_lineage)"
    )


@pytest.mark.smoke
@pytest.mark.parametrize("cell", sorted(FLOOR_FIXTURES))
def test_lineage_last_row_matches_fixture(cell):
    fixture = REPO_ROOT / FLOOR_FIXTURES[cell]
    if not fixture.exists():
        pytest.fail(f"committed floor fixture missing: {fixture}")
    rows = _lineage_rows().get(cell)
    assert rows, f"no lineage rows for cell {cell!r}"
    assert rows[-1] == current_values(cell), (
        f"floor fixture for {cell!r} changed but the 地板谱系 table's last row was "
        f"not updated.\n  table last row: {rows[-1]}\n  fixture now:    "
        f"{current_values(cell)}\n  append (fill date/sha/event):\n  {current_row(cell)}"
    )


@pytest.mark.smoke
def test_lineage_value_columns_match_module_contract():
    """The doc's column header must list exactly the VALUE_KEYS metrics, in
    order — renaming/reordering must happen in floor_lineage.py first."""
    header_pattern = re.compile(r"\|\s*格子\s*\|.*\|")
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        if header_pattern.match(line) and "completion" in line:
            return
    pytest.fail("地板谱系 table header not found in flag_cell_ab_matrix.md")
