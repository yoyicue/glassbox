"""Extract + scrub the committed iPhone Settings transition corpus (S1).

Design: docs/design/iphone_settings_transition.md (S1 — offline transition
replay corpus). Source of truth is a raw on-rig run ledger (actions.jsonl +
scenes/*.json); this generator selects the candidate-tap groups (the tap
attempts whose command carries a `page_id` expected_state and a row target),
keeps only what replay needs, and scrubs personal data **structurally** — the
personal strings themselves never appear in this file or in the tests.

Generator command (also embedded in the corpus README):

    uv run python -m skills.regression.extract_transition_corpus \
        --run artifacts/computer_use_success_rate/iphone_floor_runs/run_2026_06_12_06_04_38_737160 \
        --out skills/golden/ios_settings_transitions

Scrubbed classes: see skills/regression/scrub.py (the shared structural
detector + scrubber this generator delegates to).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loguru import logger

from skills.regression.scrub import (  # noqa: F401  (re-exported public API)
    PLACEHOLDER_PREFIX,
    find_personal_texts,
)
from skills.regression.scrub import (
    Scrubber as _Scrubber,
)


def _slim_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": scene.get("scene_id"),
        "page_id": scene.get("page_id"),
        "platform_scene_kind": scene.get("platform_scene_kind"),
        "elements": [
            {"text": e.get("text"), "box": e.get("box"), "type": e.get("type")}
            for e in scene.get("elements", [])
        ],
    }


def _load_scene(run_dir: Path, rel: str) -> dict[str, Any]:
    return json.loads((run_dir / rel).read_text())


def _candidate_and_wrapper_actions(
    actions: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Pair each candidate tap (page_id expected_state + row target) with its
    agent-actor wrapper attempts (same any_of payload, no target)."""

    def any_of_key(action: dict[str, Any]) -> tuple[str, ...] | None:
        expected = (action.get("command") or {}).get("expected_state") or {}
        if expected.get("kind") != "page_id":
            return None
        payload = expected.get("payload") or {}
        any_of = payload.get("any_of") or ([payload["page_id"]] if payload.get("page_id") else [])
        return tuple(str(item) for item in any_of)

    inner: dict[str, dict[str, Any]] = {}
    wrappers: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for action in actions:
        key = any_of_key(action)
        if key is None:
            continue
        if (action.get("command") or {}).get("target"):
            group_id = action["attempt_group_id"]
            if group_id in inner:
                raise ValueError(f"candidate group {group_id} has multiple tap attempts")
            inner[group_id] = action
        else:
            wrappers.setdefault(key, []).append(action)
    paired: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for group_id in sorted(inner):
        action = inner[group_id]
        paired.append((action, wrappers.get(any_of_key(action), [])))
    return paired


def _verified_via(inner: dict[str, Any], wrapper_attempts: list[dict[str, Any]]) -> str | None:
    """How the candidate verified live, with the inner tap taking precedence.

    The wrapper retries observe later/fresh frames, so their verdicts can
    diverge from the recorded after-scene; classification keys on the attempt
    whose after-scene the corpus actually commits.
    """
    verdicts = [inner.get("semantic") or {}] + [
        w.get("semantic") or {} for w in sorted(wrapper_attempts, key=lambda a: a["attempt_id"])
    ]
    for verdict in verdicts:
        if verdict.get("status") != "succeeded":
            continue
        if "after VLM escalation" in str(verdict.get("reason") or ""):
            return "vlm_escalation"
        return "page_id"
    return None


def extract(run_dir: Path, out_dir: Path) -> dict[str, Any]:
    actions = [
        json.loads(line)
        for line in (run_dir / "actions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    paired = _candidate_and_wrapper_actions(actions)
    if not paired:
        raise ValueError(f"no candidate tap groups found in {run_dir}")
    logger.info("found {} candidate tap groups", len(paired))

    # Root scene: the before_command scene of the first candidate tap.
    first_inner = min((inner for inner, _ in paired), key=lambda a: a["attempt_id"])
    root_scene_raw = _load_scene(run_dir, first_inner["before_command"]["scene"])
    if root_scene_raw.get("platform_scene_kind") != "settings_root":
        raise ValueError("first candidate tap does not start from the Settings root")

    root_scene = _slim_scene(root_scene_raw)
    groups: list[dict[str, Any]] = []
    for inner, wrapper_attempts in paired:
        command = inner["command"]
        semantic = inner.get("semantic") or {}
        after_scene = _slim_scene(_load_scene(run_dir, inner["after"]["scene"]))
        wrapper_ids = sorted({w["attempt_group_id"] for w in wrapper_attempts})
        if len(wrapper_ids) > 1:
            raise ValueError(f"group {inner['attempt_group_id']} pairs >1 wrapper: {wrapper_ids}")
        groups.append(
            {
                "schema": "ios_settings_transition_group.v1",
                "group_id": inner["attempt_group_id"],
                "wrapper_group_id": wrapper_ids[0] if wrapper_ids else None,
                "attempt_id": inner["attempt_id"],
                "target": command["target"],
                "expected_state": command["expected_state"],
                "recorded_verdict": semantic.get("status"),
                "recorded_reason": semantic.get("reason"),
                "verified_live": _verified_via(inner, wrapper_attempts) is not None,
                "verified_via": _verified_via(inner, wrapper_attempts),
                "after_scene": after_scene,
                "notes": {
                    "wrapper_attempts": [
                        {
                            "attempt_id": w["attempt_id"],
                            "status": (w.get("semantic") or {}).get("status"),
                            "reason": (w.get("semantic") or {}).get("reason"),
                        }
                        for w in sorted(wrapper_attempts, key=lambda a: a["attempt_id"])
                    ],
                },
            }
        )

    # Scrub: collect personal values across every scene first, then replace
    # everywhere (scenes + free-text verdict reasons).
    scrubber = _Scrubber()
    scrubber.collect(root_scene)
    for group in groups:
        scrubber.collect(group["after_scene"])
    scrubber.scrub_scene(root_scene)
    for group in groups:
        scrubber.scrub_scene(group["after_scene"])
        group["recorded_reason"] = scrubber.scrub_text(group["recorded_reason"])
        for attempt in group["notes"]["wrapper_attempts"]:
            attempt["reason"] = scrubber.scrub_text(attempt["reason"])

    # Hard post-condition: the detector must find nothing after scrubbing.
    for label, scene in [("root_scene", root_scene)] + [
        (g["group_id"], g["after_scene"]) for g in groups
    ]:
        leftovers = find_personal_texts(scene)
        if leftovers:
            raise ValueError(f"scrub left personal data in {label}: {leftovers}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "root_scene.json").write_text(
        json.dumps({"schema": "ios_settings_transition_root_scene.v1", **root_scene},
                   ensure_ascii=False, indent=1) + "\n"
    )
    for group in groups:
        (out_dir / f"{group['group_id']}.json").write_text(
            json.dumps(group, ensure_ascii=False, indent=1) + "\n"
        )
    summary = {
        "groups": len(groups),
        "scrub_replacements": scrubber.replacement_count,
        "scrub_counts": scrubber.counts(),
        "verified_via": {
            via: sum(1 for g in groups if g["verified_via"] == via)
            for via in ("page_id", "vlm_escalation", None)
        },
    }
    logger.info("corpus written to {}: {}", out_dir, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="raw run directory")
    parser.add_argument("--out", required=True, type=Path, help="corpus output directory")
    args = parser.parse_args()
    extract(args.run, args.out)


if __name__ == "__main__":
    main()
