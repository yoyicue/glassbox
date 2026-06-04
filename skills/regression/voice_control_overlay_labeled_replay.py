"""Replay labeled Voice Control overlay mappings against saved scenes.

This harness is intentionally offline. A live probe should capture a screenshot,
scene JSON, and a small human label manifest; this module re-runs the overlay
parser + hint mapper and reports whether each labeled badge maps to the expected
target element.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import cv2
from pydantic import BaseModel, Field

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.voice_control_overlay import (
    VoiceControlOverlayMarker,
    VoiceControlOverlayMode,
    apply_voice_control_overlay_hints,
    parse_voice_control_overlay,
)


class VoiceControlOverlayReplayLabel(BaseModel):
    """One human-labeled badge-to-target expectation."""

    name: str | None = None
    marker_text: str
    marker_center: tuple[int, int] | None = None
    target_text: str | None = None
    target_center: tuple[int, int] | None = None
    expect_mapped: bool = True


class VoiceControlOverlayReplayLabelSet(BaseModel):
    mode: VoiceControlOverlayMode = "item_names"
    marker_center_tolerance: int = Field(default=28, ge=0)
    target_center_tolerance: int = Field(default=36, ge=0)
    labels: list[VoiceControlOverlayReplayLabel]


class VoiceControlOverlayReplayCaseResult(BaseModel):
    name: str
    passed: bool
    reason: str
    marker_text: str
    marker_center: tuple[int, int] | None = None
    expected_accessibility_id: str | None = None
    expected_target_text: str | None = None
    expected_target_center: tuple[int, int] | None = None
    actual_target_text: str | None = None
    actual_target_center: tuple[int, int] | None = None
    actual_element_id: int | None = None


class VoiceControlOverlayReplayReport(BaseModel):
    mode: VoiceControlOverlayMode
    total: int
    passed: int
    failed: int
    cases: list[VoiceControlOverlayReplayCaseResult]


def evaluate_voice_control_overlay_labels(
    scene: Scene,
    markers: Sequence[VoiceControlOverlayMarker],
    label_set: VoiceControlOverlayReplayLabelSet,
) -> VoiceControlOverlayReplayReport:
    """Evaluate labeled overlay marker mappings without mutating ``scene``."""

    replay_scene = scene.model_copy(deep=True)
    apply_voice_control_overlay_hints(
        replay_scene,
        markers,
        include_names=label_set.mode == "item_names",
        include_frame_local_numbers=label_set.mode in {"item_numbers", "numbered_grid"},
    )
    cases = [
        _evaluate_label(
            replay_scene,
            markers,
            label,
            marker_center_tolerance=label_set.marker_center_tolerance,
            target_center_tolerance=label_set.target_center_tolerance,
        )
        for label in label_set.labels
    ]
    passed = sum(1 for case in cases if case.passed)
    return VoiceControlOverlayReplayReport(
        mode=label_set.mode,
        total=len(cases),
        passed=passed,
        failed=len(cases) - passed,
        cases=cases,
    )


def _evaluate_label(
    scene: Scene,
    markers: Sequence[VoiceControlOverlayMarker],
    label: VoiceControlOverlayReplayLabel,
    *,
    marker_center_tolerance: int,
    target_center_tolerance: int,
) -> VoiceControlOverlayReplayCaseResult:
    case_name = label.name or label.marker_text
    marker = _find_marker(
        markers,
        label,
        center_tolerance=marker_center_tolerance,
    )
    if marker is None:
        return VoiceControlOverlayReplayCaseResult(
            name=case_name,
            passed=False,
            reason="marker_missing_or_ambiguous",
            marker_text=label.marker_text,
            expected_target_text=label.target_text,
            expected_target_center=label.target_center,
        )

    mapped_targets = _mapped_targets(scene, marker.accessibility_id)
    if not label.expect_mapped:
        return VoiceControlOverlayReplayCaseResult(
            name=case_name,
            passed=not mapped_targets,
            reason="unmapped_as_expected" if not mapped_targets else "unexpected_mapping",
            marker_text=marker.text,
            marker_center=marker.center,
            expected_accessibility_id=marker.accessibility_id,
            actual_target_text=mapped_targets[0].text if mapped_targets else None,
            actual_target_center=mapped_targets[0].box.center if mapped_targets else None,
            actual_element_id=mapped_targets[0].element_id if mapped_targets else None,
        )

    if len(mapped_targets) != 1:
        return VoiceControlOverlayReplayCaseResult(
            name=case_name,
            passed=False,
            reason="target_missing" if not mapped_targets else "multiple_targets",
            marker_text=marker.text,
            marker_center=marker.center,
            expected_accessibility_id=marker.accessibility_id,
            expected_target_text=label.target_text,
            expected_target_center=label.target_center,
        )

    target = mapped_targets[0]
    text_ok = (
        label.target_text is None
        or _text_matches(label.target_text, target.text)
    )
    center_ok = (
        label.target_center is None
        or _distance(label.target_center, target.box.center) <= target_center_tolerance
    )
    passed = text_ok and center_ok
    if passed:
        reason = "matched"
    elif not text_ok:
        reason = "target_text_mismatch"
    else:
        reason = "target_center_mismatch"
    return VoiceControlOverlayReplayCaseResult(
        name=case_name,
        passed=passed,
        reason=reason,
        marker_text=marker.text,
        marker_center=marker.center,
        expected_accessibility_id=marker.accessibility_id,
        expected_target_text=label.target_text,
        expected_target_center=label.target_center,
        actual_target_text=target.text,
        actual_target_center=target.box.center,
        actual_element_id=target.element_id,
    )


def _find_marker(
    markers: Sequence[VoiceControlOverlayMarker],
    label: VoiceControlOverlayReplayLabel,
    *,
    center_tolerance: int,
) -> VoiceControlOverlayMarker | None:
    candidates = [
        marker
        for marker in markers
        if _text_matches(label.marker_text, marker.text)
    ]
    if label.marker_center is not None:
        candidates = [
            marker
            for marker in candidates
            if _distance(label.marker_center, marker.center) <= center_tolerance
        ]
        return min(
            candidates,
            key=lambda marker: _distance(label.marker_center, marker.center),
            default=None,
        )
    if len(candidates) == 1:
        return candidates[0]
    return None


def _mapped_targets(scene: Scene, accessibility_id: str) -> list[UIElement]:
    return [
        element
        for element in scene.elements
        if (
            element.whitebox_hint is not None
            and element.whitebox_hint.accessibility_id == accessibility_id
        )
    ]


def _text_matches(expected: str | None, actual: str | None) -> bool:
    expected_norm = _compact_text(expected)
    actual_norm = _compact_text(actual)
    if not expected_norm or not actual_norm:
        return False
    if expected_norm in actual_norm or actual_norm in expected_norm:
        return True
    return SequenceMatcher(None, expected_norm, actual_norm).ratio() >= 0.82


def _compact_text(text: str | None) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").lower())


def _distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    dx = left[0] - right[0]
    dy = left[1] - right[1]
    return (dx * dx + dy * dy) ** 0.5


def _load_label_set(path: Path) -> VoiceControlOverlayReplayLabelSet:
    return VoiceControlOverlayReplayLabelSet.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _capture_from_probe(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for step in payload.get("steps", []):
        capture = step.get("capture")
        if isinstance(capture, dict) and capture.get("label") == label:
            return capture
    raise ValueError(f"capture {label!r} not found in {path}")


def _scene_and_frame_from_args(args: argparse.Namespace) -> tuple[Scene, Any]:
    scene_path = args.scene
    frame_path = args.frame
    if args.probe_json is not None:
        capture = _capture_from_probe(args.probe_json, args.capture_label)
        scene_value = capture.get("scene_path")
        if not scene_value:
            raise ValueError(
                "probe capture has no scene_path; rerun voice_control_overlay_probe "
                "from a version that records scene_path, or pass --scene"
            )
        scene_path = Path(scene_value)
        frame_path = Path(capture["screenshot"])
    if scene_path is None or frame_path is None:
        raise ValueError("provide --scene and --frame, or provide --probe-json")
    scene = Scene.model_validate_json(Path(scene_path).read_text(encoding="utf-8"))
    frame = cv2.imread(str(frame_path))
    if frame is None:
        raise ValueError(f"could not load frame {frame_path}")
    return scene, frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--scene", type=Path)
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--probe-json", type=Path)
    parser.add_argument("--capture-label", default="03_item_names_restored")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    label_set = _load_label_set(args.labels)
    scene, frame = _scene_and_frame_from_args(args)
    markers = parse_voice_control_overlay(
        scene.elements,
        mode=label_set.mode,
        frame_img=frame,
    )
    report = evaluate_voice_control_overlay_labels(scene, markers, label_set)
    payload = report.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
