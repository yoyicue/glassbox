"""Repo-wide privacy guard.

Two layers, by design:

1. **Shape-based scan (runs everywhere, CI included):** every scene-shaped
   JSON committed under ``skills/golden/**`` and ``skills/regression/
   fixtures/**`` must produce ZERO findings from the shared structural
   personal-data detector (skills/regression/scrub.py). Placeholders
   (``SCRUBBED_*``) are never reported, so properly scrubbed corpora pass by
   construction.

2. **Direct value sweep (host-local, skips loudly in CI):** the personal
   values themselves are NEVER committed — they are re-derived at test time
   from the raw run ledgers under ``artifacts/`` (gitignored; present only on
   the rig/owner host) and then asserted absent from everything committed
   under ``skills/`` and ``glassbox/``. On hosts without the raw runs this
   check SKIPS by design; the shape-based scan above still guards there.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skills.regression.scrub import Scrubber, find_personal_texts

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (
    REPO_ROOT / "skills" / "golden",
    REPO_ROOT / "skills" / "regression" / "fixtures",
)
SWEEP_ROOTS = (REPO_ROOT / "skills", REPO_ROOT / "glassbox")

# Raw on-rig artifact ledgers (gitignored; present only on the rig/owner host):
# the only place the personal values exist, so the sweep can derive them
# without ever committing them. FIX 2 (2026-06-13) widens the derivation from a
# single floor-runs dir to ALL artifact scene layouts — so a value that leaks
# into the committed tree from ANY run (springboard, App-Library, Settings-
# detail, Screen-Time, the AI-facade `ai_*` probes, the `_reports` view dumps)
# is caught, not just the iPhone floor runs.
#
# This widening is only safe because the structural detector is now precise
# enough to NOT anchor generic iOS UI strings on those heterogeneous scenes
# (see skills/smoke/test_scrub.py precision suite); a loose detector here would
# false-positive committed generic content ("Settings" in skills/crawl/
# crawl_app.py, "Camera"/"Week" in the golden corpus).
#
# Each glob is BOUNDED (no unbounded `**` over artifacts/), so the scan can only
# reach the known scene-bearing layouts. `scenes/*.json` are full scene dumps;
# `views/*.ocr.json` are the report-view OCR dumps (also scene-shaped).
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
_DERIVATION_GLOBS = (
    # Top-level measurement-harness runs and AI-facade probe sessions.
    "run_*/scenes/*.json",
    "ai_*/scenes/*.json",
    # computer_use_success_rate floor / honest-gate / candidate run dirs.
    "computer_use_success_rate/*_runs/run_*/scenes/*.json",
    # ... and the nested rounds/ layout (iphone_floor_n5*, etc.).
    "computer_use_success_rate/*/rounds/run_*/scenes/*.json",
    # Per-app A/B run dirs (clock, app-store remote-AC).
    "clock_ab/*_runs/run_*/scenes/*.json",
    "appstore_remoteac_ab/*/run_*/scenes/*.json",
    # ios_settings report views and computer_use report views (OCR dumps).
    "ios_settings/*/*.artifacts/views/*.ocr.json",
    "computer_use_success_rate/*_reports/*.artifacts/views/*.ocr.json",
)

# Keys whose list-of-strings payloads are scene text dumps in committed
# fixtures (harvested golden cases, OCR fixtures, scene signatures).
_TEXT_LIST_KEYS = ("texts", "signature", "before_texts", "after_texts")
_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic",
    ".mp4", ".mov", ".zip", ".gz", ".bin", ".pyc",
}


def _iter_scene_shaped(payload: Any, where: str = "$") -> Iterator[tuple[str, dict]]:
    """Yield every scene-shaped dict in a JSON payload: dicts with an
    ``elements`` list, plus pseudo-scenes built from committed text dumps
    (``texts`` / ``signature`` / ``before_texts`` / ``after_texts``)."""
    if isinstance(payload, dict):
        if isinstance(payload.get("elements"), list):
            yield where, payload
        for key in _TEXT_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list) and value and all(isinstance(t, str) for t in value):
                yield f"{where}.{key}", {"elements": [{"text": text} for text in value]}
        for key, value in payload.items():
            if key != "elements":
                yield from _iter_scene_shaped(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _iter_scene_shaped(value, f"{where}[{index}]")


@pytest.mark.smoke
def test_committed_fixture_scenes_have_no_personal_data_shapes():
    """Structural detector over every committed scene-shaped JSON: zero
    findings. This is the layer that runs everywhere (no artifacts needed)."""
    scanned = 0
    findings: list[tuple[str, str, str, int, str]] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            rel = str(path.relative_to(REPO_ROOT))
            for where, scene in _iter_scene_shaped(payload):
                scanned += 1
                for kind, idx, text in find_personal_texts(scene):
                    findings.append((rel, where, kind, idx, text))
    assert scanned > 0, "privacy scan found no scene-shaped JSON — the guard went vacuous"
    assert findings == [], f"personal-data shapes in committed fixtures: {findings}"


def _iter_derivation_scene_paths() -> Iterator[Path]:
    """Every scene-bearing artifact path across the bounded derivation globs."""
    for pattern in _DERIVATION_GLOBS:
        yield from sorted(ARTIFACTS_DIR.glob(pattern))


def _derived_personal_values() -> set[str]:
    """Re-derive the personal value set from ALL artifact scene layouts (FIX 2),
    so a value that leaks from ANY run is swept for — not just the floor runs."""
    scrubber = Scrubber()
    for scene_path in _iter_derivation_scene_paths():
        try:
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(scene, dict):
            scrubber.collect(scene)
    return scrubber.values()


def _has_any_derivation_scenes() -> bool:
    return any(True for _ in _iter_derivation_scene_paths())


@pytest.mark.smoke
def test_raw_run_personal_values_absent_from_committed_tree():
    """Direct sweep: none of the personal values derivable from the raw artifact
    ledgers (ALL layouts, FIX 2) may appear anywhere under skills/ or glassbox/.
    The values are derived at test time and never committed; failures report a
    digest, not the value.

    ORCHESTRATOR NOTE — this assertion only RUNS on a host that holds the
    gitignored artifacts/ (the rig/owner host); CI and worktrees skip by design
    (the worktree has no artifacts/, so the widened derivation cannot be proven
    GREEN here). To confirm on the artifact-bearing host:

        uv run pytest skills/smoke/test_privacy_guard.py \\
            ::test_raw_run_personal_values_absent_from_committed_tree -q

    and, to inspect the re-derived value set / assert no generic words leaked in
    (host-local; never commit the output):

        uv run python -c "from skills.smoke.test_privacy_guard import \\
            _derived_personal_values as d; v=d(); print(len(v)); \\
            import json; print(json.dumps(sorted(len(x) for x in v)))"
    """
    if not ARTIFACTS_DIR.is_dir() or not _has_any_derivation_scenes():
        pytest.skip(
            "SKIPPED BY DESIGN: no raw artifact scenes under "
            f"{ARTIFACTS_DIR.relative_to(REPO_ROOT)} across the derivation globs "
            "(artifacts/ is gitignored, so CI, fresh checkouts and git worktrees cannot "
            "derive the personal value list). This sweep runs on hosts that hold the "
            "original artifacts (the rig/owner host); the shape-based scan in this file "
            "still guards committed fixtures everywhere."
        )
    values = _derived_personal_values()
    if not values:
        pytest.skip(
            "SKIPPED BY DESIGN: the raw run ledgers exist but the structural detector "
            "derived no personal values from them — nothing to sweep for."
        )
    hits: list[tuple[str, str]] = []
    for root in SWEEP_ROOTS:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() in _BINARY_SUFFIXES:
                continue
            if "__pycache__" in path.parts:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            for value in values:
                if value in content:
                    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
                    hits.append((str(path.relative_to(REPO_ROOT)), f"value sha256:{digest}"))
    assert hits == [], (
        f"personal values derived from raw artifact ledgers (all layouts) leaked "
        f"into the committed tree: {hits}"
    )
