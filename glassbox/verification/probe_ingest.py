"""Convert runtime probe artifacts into verifier golden-case candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_actions(run_dir: Path | str) -> list[dict[str, Any]]:
    path = Path(run_dir) / "actions.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def golden_case_from_action(
    run_dir: Path | str,
    action: dict[str, Any],
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    semantic = action.get("semantic") or {}
    before_ref = action.get("before_command") or action.get("before_requested") or {}
    after_ref = action.get("after") or {}
    payload = {
        "case_id": case_id or f"{semantic.get('verifier', action.get('op'))}_{action.get('attempt_id')}",
        "action": action.get("op"),
        "verifier": semantic.get("verifier"),
        "expected_status": semantic.get("status"),
        "before_texts": _scene_texts(run_path, before_ref.get("scene")),
        "after_texts": _scene_texts(run_path, after_ref.get("scene")),
        "metadata": {},
    }
    if semantic.get("disqualifying_state"):
        payload["expected_disqualifying_state"] = semantic["disqualifying_state"]
    return payload


def write_golden_case(path: Path | str, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _scene_texts(run_dir: Path, rel_scene: str | None) -> list[str]:
    if not rel_scene:
        return []
    payload = json.loads((run_dir / rel_scene).read_text(encoding="utf-8"))
    if "texts" in payload:
        return [str(text) for text in payload.get("texts") or [] if text]
    return [
        str(element["text"])
        for element in payload.get("elements", [])
        if element.get("text")
    ]
