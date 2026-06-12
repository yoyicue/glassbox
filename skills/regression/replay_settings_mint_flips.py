"""Replay classify_ios_scene over a raw run's scene ledgers; emit page_id flips.

S3 of docs/design/iphone_settings_transition.md (nav-band mint fix). For every
``scenes/scn_*.json`` in a raw on-rig run directory (gitignored; exists only on
the rig/owner host) this reconstructs the Scene from the recorded OCR elements,
re-classifies it with the **current** ``glassbox.ios.scene.classify_ios_scene``,
and emits every ``recorded page_id → re-minted page_id`` flip, grouped for hand
review. The reviewed output is committed as
``skills/regression/fixtures/ios_settings_mint_flip_allowlist.json`` and pinned
by ``skills/smoke/test_ios_settings_mint_flips.py``.

Generator command (also embedded in the committed allow-list):

    uv run python -m skills.regression.replay_settings_mint_flips \
        --run artifacts/computer_use_success_rate/iphone_floor_runs/run_2026_06_12_06_04_38_737160

Scenes whose recorded page_id was authored by the VLM describe pass
(``classification_source == "vlm"``) are skipped, not diffed: an OCR-only
classifier replay cannot reproduce VLM-authored identities by definition. At
the pre-S3 tree this replay showed **zero** recorded-vs-re-minted diffs outside
the VLM set, so the emitted flips are exactly the classifier delta.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from glassbox.cognition import Box, Scene, UIElement
from glassbox.ios.scene import classify_ios_scene

DEFAULT_RUN = Path(
    "artifacts/computer_use_success_rate/iphone_floor_runs/run_2026_06_12_06_04_38_737160"
)


def scene_from_payload(payload: dict[str, Any]) -> Scene:
    """Rebuild a classifiable Scene from a recorded scenes/scn_*.json payload."""
    elements = []
    for raw in payload.get("elements", []):
        box = raw["box"]
        elements.append(
            UIElement(
                type=raw.get("type") or "text",
                box=Box(x=box["x"], y=box["y"], w=box["w"], h=box["h"]),
                text=raw.get("text"),
                confidence=float(raw.get("confidence") or 1.0),
            )
        )
    scene = Scene(frame_id=0, timestamp=0.0, elements=elements)
    viewport = payload.get("viewport_size")
    if viewport:
        scene.viewport_size = (int(viewport[0]), int(viewport[1]))
    return scene


def replay_mint_flips(run_dir: Path) -> dict[str, Any]:
    """Return {scenes, skipped_vlm, flips:[{scene_id, old, new}…]} for a run."""
    scene_paths = sorted((run_dir / "scenes").glob("scn_*.json"))
    if not scene_paths:
        raise ValueError(f"no scenes/scn_*.json under {run_dir}")
    flips: list[dict[str, Any]] = []
    skipped_vlm = 0
    for path in scene_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("classification_source") == "vlm":
            skipped_vlm += 1
            continue
        old = payload.get("page_id")
        new = classify_ios_scene(scene_from_payload(payload)).page_id
        if old != new:
            flips.append({"scene_id": path.stem, "old": old, "new": new})
    return {"scenes": len(scene_paths), "skipped_vlm": skipped_vlm, "flips": flips}


def grouped_flips(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Group per-scene flips by (old, new) for hand review."""
    groups: dict[tuple[Any, Any], list[str]] = {}
    for flip in report["flips"]:
        groups.setdefault((flip["old"], flip["new"]), []).append(flip["scene_id"])
    return [
        {"old": old, "new": new, "scenes": sorted(scenes), "review": ""}
        for (old, new), scenes in sorted(groups.items(), key=lambda kv: kv[1][0])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN, help="raw run directory")
    args = parser.parse_args()
    report = replay_mint_flips(args.run)
    print(
        json.dumps(
            {
                "schema": "ios_settings_mint_flip_allowlist.v1",
                "run": args.run.name,
                "scenes": report["scenes"],
                "skipped_vlm": report["skipped_vlm"],
                "flips": grouped_flips(report),
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
