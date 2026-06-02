"""Offline A/B helper for the default-off UI layout segmentation seam.

This is a pre-rig screen: it compares a captured Scene against the same Scene
after icon injection + layout segmentation. It does not prove task success; it
only decides whether the candidate is clean enough to deserve on-rig A/B.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.icon_detect import detect_icons
from glassbox.cognition.layout_segment import segment_layout
from glassbox.cognition.text_match import compact_text

IconDetector = Callable[..., Sequence[Any]]
_ACTIONABLE_TYPES = {"button", "input", "list_item", "nav_back", "slider", "switch", "tab_bar_item"}


@dataclass(frozen=True)
class UiLayoutSpikeCase:
    name: str
    scene: Scene
    frame_img: Any
    scene_path: str | None = None
    frame_path: str | None = None


@dataclass(frozen=True)
class UiLayoutElementSummary:
    type: str
    text: str | None
    box: tuple[int, int, int, int]
    type_source: str | None
    type_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UiLayoutArmReport:
    name: str
    element_count: int
    type_counts: dict[str, int]
    actionable_count: int
    actionable_texts: dict[str, int]
    expected_texts_found: list[str] = field(default_factory=list)
    expected_texts_missing: list[str] = field(default_factory=list)
    expected_actionable_texts_found: list[str] = field(default_factory=list)
    no_text_actionable_count: int = 0
    elements: list[UiLayoutElementSummary] = field(default_factory=list)


@dataclass(frozen=True)
class UiLayoutCaseReport:
    name: str
    scene_path: str | None
    frame_path: str | None
    viewport_size: tuple[int, int]
    icons_detected: int
    baseline: UiLayoutArmReport
    candidate: UiLayoutArmReport
    element_delta: int
    actionable_delta: int
    expected_actionable_recovered: list[str]
    expected_actionable_lost: list[str]
    expected_text_lost: list[str]
    unexpected_actionable_texts: dict[str, int]
    offline_decision: str
    decision_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UiLayoutSegmentationSpikeReport:
    cases: list[UiLayoutCaseReport]
    expected_texts: list[str]
    min_expected_actionable_recovered: int
    max_no_text_actionables: int | None
    max_unexpected_actionable_texts: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_ui_layout_segmentation_spike(
    cases: Sequence[UiLayoutSpikeCase],
    *,
    expected_texts: Sequence[str] = (),
    icon_detector: IconDetector | None = None,
    min_expected_actionable_recovered: int = 1,
    max_no_text_actionables: int | None = None,
    max_unexpected_actionable_texts: int | None = None,
    keep_elements: bool = True,
) -> UiLayoutSegmentationSpikeReport:
    """Run baseline vs layout-segmented comparison for captured scenes."""
    if not cases:
        raise ValueError("collect_ui_layout_segmentation_spike requires at least one case")
    expected = _unique_texts(expected_texts)
    detector = icon_detector or detect_icons
    reports: list[UiLayoutCaseReport] = []
    for case in cases:
        reports.append(
            _run_case(
                case,
                expected_texts=expected,
                icon_detector=detector,
                min_expected_actionable_recovered=min_expected_actionable_recovered,
                max_no_text_actionables=max_no_text_actionables,
                max_unexpected_actionable_texts=max_unexpected_actionable_texts,
                keep_elements=keep_elements,
            )
        )
    return UiLayoutSegmentationSpikeReport(
        cases=reports,
        expected_texts=expected,
        min_expected_actionable_recovered=int(min_expected_actionable_recovered),
        max_no_text_actionables=max_no_text_actionables,
        max_unexpected_actionable_texts=max_unexpected_actionable_texts,
    )


def load_scene_frame_cases(
    scenes: Sequence[Path],
    frames: Sequence[Path],
    names: Sequence[str] | None = None,
) -> list[UiLayoutSpikeCase]:
    if len(scenes) != len(frames):
        raise ValueError("--scene and --frame counts must match")
    if names is not None and len(names) != len(scenes):
        raise ValueError("--case-name count must match --scene count")
    cases: list[UiLayoutSpikeCase] = []
    for index, (scene_path, frame_path) in enumerate(zip(scenes, frames, strict=True)):
        scene = Scene.model_validate(json.loads(Path(scene_path).read_text(encoding="utf-8")))
        frame_img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if frame_img is None:
            raise ValueError(f"Could not read frame image: {frame_path}")
        cases.append(
            UiLayoutSpikeCase(
                name=str(names[index] if names is not None else Path(scene_path).stem),
                scene=scene,
                frame_img=frame_img,
                scene_path=str(scene_path),
                frame_path=str(frame_path),
            )
        )
    return cases


def derive_frame_path(scene_path: Path) -> Path:
    """Derive artifacts/run_*/frames/frm_*.png from a scene JSON path."""
    path = Path(scene_path)
    name = path.name.replace("scn_", "frm_").replace(".json", ".png")
    if path.parent.name == "scenes":
        return path.parent.parent / "frames" / name
    return path.with_name(name)


def load_expected_texts(paths: Sequence[Path], inline: Sequence[str]) -> list[str]:
    expected = [item for item in (str(value).strip() for value in inline) if item]
    for path in paths:
        expected.extend(_read_expected_texts(path))
    return _unique_texts(expected)


def _run_case(
    case: UiLayoutSpikeCase,
    *,
    expected_texts: Sequence[str],
    icon_detector: IconDetector,
    min_expected_actionable_recovered: int,
    max_no_text_actionables: int | None,
    max_unexpected_actionable_texts: int | None,
    keep_elements: bool,
) -> UiLayoutCaseReport:
    baseline_scene = case.scene.model_copy(deep=True)
    candidate_scene, icons_detected = _inject_icons(case.scene, case.frame_img, icon_detector)
    viewport = _viewport_size(candidate_scene, case.frame_img)
    segment_layout(candidate_scene, viewport_size=viewport)
    baseline = _summarize_arm("baseline", baseline_scene, expected_texts=expected_texts, keep_elements=keep_elements)
    candidate = _summarize_arm("layout_segmented", candidate_scene, expected_texts=expected_texts, keep_elements=keep_elements)
    expected_actionable_recovered = sorted(
        set(candidate.expected_actionable_texts_found) - set(baseline.expected_actionable_texts_found),
        key=compact_text,
    )
    expected_actionable_lost = sorted(
        set(baseline.expected_actionable_texts_found) - set(candidate.expected_actionable_texts_found),
        key=compact_text,
    )
    expected_text_lost = sorted(
        set(baseline.expected_texts_found) - set(candidate.expected_texts_found),
        key=compact_text,
    )
    unexpected_actionable = _unexpected_actionable_texts(candidate.actionable_texts, expected_texts)
    decision, reasons = _offline_decision(
        expected_texts=expected_texts,
        expected_actionable_recovered=expected_actionable_recovered,
        expected_actionable_lost=expected_actionable_lost,
        expected_text_lost=expected_text_lost,
        no_text_actionable_count=candidate.no_text_actionable_count,
        unexpected_actionable_texts=unexpected_actionable,
        min_expected_actionable_recovered=min_expected_actionable_recovered,
        max_no_text_actionables=max_no_text_actionables,
        max_unexpected_actionable_texts=max_unexpected_actionable_texts,
    )
    return UiLayoutCaseReport(
        name=case.name,
        scene_path=case.scene_path,
        frame_path=case.frame_path,
        viewport_size=viewport,
        icons_detected=icons_detected,
        baseline=baseline,
        candidate=candidate,
        element_delta=candidate.element_count - baseline.element_count,
        actionable_delta=candidate.actionable_count - baseline.actionable_count,
        expected_actionable_recovered=expected_actionable_recovered,
        expected_actionable_lost=expected_actionable_lost,
        expected_text_lost=expected_text_lost,
        unexpected_actionable_texts=unexpected_actionable,
        offline_decision=decision,
        decision_reasons=reasons,
    )


def _inject_icons(
    scene: Scene,
    frame_img: Any,
    icon_detector: IconDetector,
) -> tuple[Scene, int]:
    text_boxes = tuple(_box_tuple(element.box) for element in scene.elements if element.text and element.box)
    icons = list(icon_detector(frame_img, text_boxes=text_boxes))
    elements = [element.model_copy(deep=True) for element in scene.elements]
    next_id = max((element.element_id for element in elements), default=-1) + 1
    for index, icon in enumerate(icons):
        x, y, w, h = _icon_box_tuple(icon)
        elements.append(
            UIElement(
                type="image",
                box=Box(x=x, y=y, w=w, h=h),
                text=None,
                confidence=0.5,
                element_id=next_id + index,
            )
        )
    return scene.model_copy(update={"elements": elements}, deep=True), len(icons)


def _summarize_arm(
    name: str,
    scene: Scene,
    *,
    expected_texts: Sequence[str],
    keep_elements: bool,
) -> UiLayoutArmReport:
    elements = list(scene.elements)
    actionables = [element for element in elements if element.type in _ACTIONABLE_TYPES]
    actionable_text_counts: Counter[str] = Counter(
        _clean_text(element.text)
        for element in actionables
        if _clean_text(element.text)
    )
    expected_found = _expected_matches(elements, expected_texts)
    expected_actionable_found = _expected_matches(actionables, expected_texts)
    summaries = [_element_summary(element) for element in elements] if keep_elements else []
    return UiLayoutArmReport(
        name=name,
        element_count=len(elements),
        type_counts=dict(sorted(Counter(element.type for element in elements).items())),
        actionable_count=len(actionables),
        actionable_texts=dict(sorted(actionable_text_counts.items())),
        expected_texts_found=expected_found,
        expected_texts_missing=[text for text in expected_texts if text not in expected_found],
        expected_actionable_texts_found=expected_actionable_found,
        no_text_actionable_count=sum(1 for element in actionables if not _clean_text(element.text)),
        elements=summaries,
    )


def _expected_matches(elements: Sequence[UIElement], expected_texts: Sequence[str]) -> list[str]:
    if not expected_texts:
        return []
    observed = [_clean_text(element.text) for element in elements if _clean_text(element.text)]
    found: list[str] = []
    for expected in expected_texts:
        if any(_text_matches(observed_text, expected) for observed_text in observed):
            found.append(expected)
    return found


def _unexpected_actionable_texts(
    actionable_texts: dict[str, int],
    expected_texts: Sequence[str],
) -> dict[str, int]:
    if not expected_texts:
        return dict(actionable_texts)
    return {
        text: count
        for text, count in actionable_texts.items()
        if not any(_text_matches(text, expected) for expected in expected_texts)
    }


def _offline_decision(
    *,
    expected_texts: Sequence[str],
    expected_actionable_recovered: Sequence[str],
    expected_actionable_lost: Sequence[str],
    expected_text_lost: Sequence[str],
    no_text_actionable_count: int,
    unexpected_actionable_texts: dict[str, int],
    min_expected_actionable_recovered: int,
    max_no_text_actionables: int | None,
    max_unexpected_actionable_texts: int | None,
) -> tuple[str, list[str]]:
    if not expected_texts:
        return "census_only", ["no_expected_texts"]
    reasons: list[str] = []
    if expected_text_lost:
        reasons.append("lost_expected_text")
    if expected_actionable_lost:
        reasons.append("lost_expected_actionable")
    if len(expected_actionable_recovered) < max(1, int(min_expected_actionable_recovered)):
        reasons.append("insufficient_expected_actionable_recovery")
    if max_no_text_actionables is not None and no_text_actionable_count > max_no_text_actionables:
        reasons.append("too_many_no_text_actionables")
    unexpected_count = sum(unexpected_actionable_texts.values())
    if max_unexpected_actionable_texts is not None and unexpected_count > max_unexpected_actionable_texts:
        reasons.append("too_many_unexpected_actionables")
    blocking = {
        "lost_expected_text",
        "lost_expected_actionable",
        "too_many_no_text_actionables",
        "too_many_unexpected_actionables",
    }
    if any(reason in blocking for reason in reasons):
        return "reject_offline", reasons
    if "insufficient_expected_actionable_recovery" in reasons:
        return "no_offline_signal", reasons
    return "promote_to_rig", ["expected_actionables_recovered"]


def _element_summary(element: UIElement) -> UiLayoutElementSummary:
    return UiLayoutElementSummary(
        type=element.type,
        text=element.text,
        box=_box_tuple(element.box),
        type_source=element.type_source,
        type_evidence=list(element.type_evidence),
    )


def _viewport_size(scene: Scene, frame_img: Any) -> tuple[int, int]:
    if scene.viewport_size is not None:
        return int(scene.viewport_size[0]), int(scene.viewport_size[1])
    height, width = frame_img.shape[:2]
    return int(width), int(height)


def _text_matches(observed: str, expected: str) -> bool:
    observed_key = compact_text(observed)
    expected_key = compact_text(expected)
    if not observed_key or not expected_key:
        return False
    return observed_key == expected_key or observed_key in expected_key or expected_key in observed_key


def _clean_text(text: str | None) -> str:
    return str(text or "").strip()


def _unique_texts(texts: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = _clean_text(text)
        key = compact_text(cleaned)
        if not key or key in seen:
            continue
        unique.append(cleaned)
        seen.add(key)
    return unique


def _read_expected_texts(path: Path) -> list[str]:
    raw = path.expanduser().read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(raw)
        if isinstance(payload, list):
            return [str(item).strip() for item in payload if str(item).strip()]
        if isinstance(payload, dict):
            values = payload.get("expected_texts") or payload.get("texts") or []
            if isinstance(values, list):
                return [str(item).strip() for item in values if str(item).strip()]
        raise ValueError(f"Expected-text JSON must be a list or object with expected_texts/texts: {path}")
    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _box_tuple(box: Box) -> tuple[int, int, int, int]:
    return int(box.x), int(box.y), int(box.w), int(box.h)


def _icon_box_tuple(icon: Any) -> tuple[int, int, int, int]:
    box = getattr(icon, "box", icon)
    if isinstance(box, Box):
        return _box_tuple(box)
    x, y, w, h = box
    return int(x), int(y), int(w), int(h)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", action="append", default=[], type=Path)
    parser.add_argument("--frame", action="append", default=[], type=Path)
    parser.add_argument("--case-name", action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--expect-text", action="append", default=[])
    parser.add_argument("--expect-file", action="append", default=[], type=Path)
    parser.add_argument("--min-expected-actionable-recovered", type=int, default=1)
    parser.add_argument("--max-no-text-actionables", type=int)
    parser.add_argument("--max-unexpected-actionables", type=int)
    parser.add_argument("--no-elements", action="store_true")
    args = parser.parse_args(argv)

    scenes = [Path(path) for path in args.scene]
    if not scenes:
        parser.error("pass at least one --scene")
    frames = [Path(path) for path in args.frame] if args.frame else [derive_frame_path(path) for path in scenes]
    expected_texts = load_expected_texts(args.expect_file, args.expect_text)
    report = collect_ui_layout_segmentation_spike(
        load_scene_frame_cases(scenes, frames, names=args.case_name or None),
        expected_texts=expected_texts,
        min_expected_actionable_recovered=args.min_expected_actionable_recovered,
        max_no_text_actionables=args.max_no_text_actionables,
        max_unexpected_actionable_texts=args.max_unexpected_actionables,
        keep_elements=not args.no_elements,
    )
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
