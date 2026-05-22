"""Golden-case loader for verifier regression tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glassbox.cognition import Box, Scene, UIElement
from glassbox.verification.diff import compute_scene_diff
from glassbox.verification.verifiers import VerifierInput


@dataclass(frozen=True)
class VerifierGoldenCase:
    case_id: str
    action: str
    expected_status: str
    before_texts: list[str]
    after_texts: list[str]
    metadata: dict[str, Any]
    expected_disqualifying_state: str | None = None

    @classmethod
    def from_path(cls, path: Path | str) -> VerifierGoldenCase:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            case_id=str(payload["case_id"]),
            action=str(payload["action"]),
            expected_status=str(payload["expected_status"]),
            before_texts=[str(text) for text in payload.get("before_texts", [])],
            after_texts=[str(text) for text in payload.get("after_texts", [])],
            metadata=dict(payload.get("metadata", {})),
            expected_disqualifying_state=payload.get("expected_disqualifying_state"),
        )

    def verifier_input(self) -> VerifierInput:
        before_requested = _scene(self.before_texts, frame_id=1)
        before_command = _scene(self.before_texts, frame_id=2)
        after_scene = _scene(self.after_texts, frame_id=3)
        scene_diff = compute_scene_diff(before_command, after_scene)
        return VerifierInput(
            attempt_id=f"{self.case_id}.attempt",
            attempt_group_id=f"{self.case_id}.group",
            action={"op": self.action, "args": [], "kwargs": {}, "metadata": self.metadata},
            before_requested=before_requested,
            before_command=before_command,
            after_scenes=[after_scene],
            after_mode="single_frame",
            frame_diff=None,
            scene_diff=scene_diff.to_dict() if scene_diff else None,
            command_result={"transport_ok": True},
            risk={"level": "medium"},
            after_frame_ids=[f"{self.case_id}.frm_after"],
            after_scene_ids=[f"{self.case_id}.scn_after"],
        )


def iter_golden_cases(root: Path | str) -> list[VerifierGoldenCase]:
    return [
        VerifierGoldenCase.from_path(path)
        for path in sorted(Path(root).glob("*.json"))
    ]


def _scene(texts: list[str], *, frame_id: int) -> Scene:
    return Scene(
        frame_id=frame_id,
        timestamp=float(frame_id),
        elements=[
            UIElement(
                type="text",
                box=Box(x=0, y=index * 10, w=100, h=8),
                text=text,
                confidence=0.95,
                element_id=index,
            )
            for index, text in enumerate(texts)
        ],
    )
