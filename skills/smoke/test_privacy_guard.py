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
# Raw on-rig run ledgers (gitignored): the only place the personal values
# exist, so the sweep can derive them without ever committing them.
RAW_RUNS_DIR = REPO_ROOT / "artifacts" / "computer_use_success_rate" / "iphone_floor_runs"

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


def _derived_personal_values() -> set[str]:
    scrubber = Scrubber()
    for scene_path in sorted(RAW_RUNS_DIR.glob("run_*/scenes/*.json")):
        try:
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(scene, dict):
            scrubber.collect(scene)
    return scrubber.values()


@pytest.mark.smoke
def test_raw_run_personal_values_absent_from_committed_tree():
    """Direct sweep: none of the personal values derivable from the raw run
    ledgers may appear anywhere under skills/ or glassbox/. The values are
    derived at test time and never committed; failures report a digest, not
    the value."""
    if not RAW_RUNS_DIR.is_dir() or not any(RAW_RUNS_DIR.glob("run_*/scenes/*.json")):
        pytest.skip(
            "SKIPPED BY DESIGN: no raw run ledgers under "
            f"{RAW_RUNS_DIR.relative_to(REPO_ROOT)} (artifacts/ is gitignored, so CI and "
            "fresh checkouts cannot derive the personal value list). This sweep runs on "
            "hosts that hold the original artifacts (the rig/owner host); the shape-based "
            "scan in this file still guards committed fixtures everywhere."
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
    assert hits == [], f"personal values from raw run ledgers leaked into the tree: {hits}"
