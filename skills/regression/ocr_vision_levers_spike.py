"""Measurement helper for Apple Vision OCR lever viability.

This module runs captured frames through the default Vision OCR path and one or
more opt-in lever arms. It is intentionally a measurement tool, not a runtime
default change: dense-frame recall and latency evidence must exist before any
OCR knob or tiling promotion.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2

from glassbox.cognition.base import Box, UIElement
from glassbox.cognition.contracts import TextRegion
from glassbox.cognition.ocr_contract import LegacyUIElementOCRAdapter
from glassbox.cognition.ocr_tiling import merge_text_regions, tile_boxes
from glassbox.cognition.text_match import compact_text, norm_text
from glassbox.perception.source import Frame

OcrFactory = Callable[..., Any]


@dataclass(frozen=True)
class OcrRegionSummary:
    frame: str
    text: str
    box: tuple[int, int, int, int]
    confidence: float
    small: bool


@dataclass(frozen=True)
class OcrVisionArmReport:
    name: str
    frame_count: int
    region_count: int
    nonempty_region_count: int
    small_region_count: int
    elapsed_ms_p50: float
    elapsed_ms_p90: float
    elapsed_ms_total: float
    texts: dict[str, int]
    expected_texts_found: list[str] = field(default_factory=list)
    expected_texts_missing: list[str] = field(default_factory=list)
    regions: list[OcrRegionSummary] = field(default_factory=list)


@dataclass(frozen=True)
class OcrVisionArmComparison:
    baseline: str
    candidate: str
    recovered_texts: dict[str, int]
    lost_texts: dict[str, int]
    expected_recovered_texts: list[str]
    expected_lost_texts: list[str]
    unexpected_recovered_texts: dict[str, int]
    region_delta: int
    small_region_delta: int
    elapsed_ms_total_delta: float
    offline_decision: str
    decision_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OcrVisionLeversSpikeReport:
    frames: list[str]
    small_height_ratio: float
    arms: list[OcrVisionArmReport]
    comparisons: list[OcrVisionArmComparison]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_ocr_vision_levers_spike(
    frames: Sequence[Frame],
    *,
    frame_names: Sequence[str] | None = None,
    ocr_factory: OcrFactory | None = None,
    minimum_text_height: float = 0.0,
    include_minimum_text_height_arm: bool = True,
    include_tiling_arm: bool = False,
    tiling_rows: int = 2,
    tiling_cols: int = 2,
    tiling_overlap: float = 0.15,
    tiling_include_full_frame: bool = True,
    tiling_nms_iou: float = 0.55,
    small_height_ratio: float = 0.035,
    expected_texts: Sequence[str] = (),
    min_expected_recovered_texts: int = 1,
    max_unexpected_recovered_texts: int | None = None,
    max_latency_delta_ms: float | None = None,
    keep_regions: bool = True,
) -> OcrVisionLeversSpikeReport:
    """Run captured frames through baseline and opt-in OCR lever arms."""
    if not frames:
        raise ValueError("collect_ocr_vision_levers_spike requires at least one frame")
    names = _frame_names(frames, frame_names)
    factory = ocr_factory or _default_vision_factory()

    arms: list[OcrVisionArmReport] = []
    baseline = _run_arm(
        "baseline",
        frames,
        names,
        lambda frame: _recognize_full(factory(), frame),
        small_height_ratio=small_height_ratio,
        expected_texts=expected_texts,
        keep_regions=keep_regions,
    )
    arms.append(baseline)

    if include_minimum_text_height_arm:
        arms.append(
            _run_arm(
                f"minimum_text_height={minimum_text_height:g}",
                frames,
                names,
                lambda frame: _recognize_full(
                    factory(minimum_text_height=minimum_text_height),
                    frame,
                ),
                small_height_ratio=small_height_ratio,
                expected_texts=expected_texts,
                keep_regions=keep_regions,
            )
        )

    if include_tiling_arm:
        arms.append(
            _run_arm(
                (
                    f"tiling_{tiling_rows}x{tiling_cols}_"
                    f"overlap={tiling_overlap:g}_minimum_text_height={minimum_text_height:g}"
                ),
                frames,
                names,
                lambda frame: _recognize_tiled(
                    factory(minimum_text_height=minimum_text_height),
                    frame,
                    rows=tiling_rows,
                    cols=tiling_cols,
                    overlap=tiling_overlap,
                    include_full_frame=tiling_include_full_frame,
                    nms_iou=tiling_nms_iou,
                ),
                small_height_ratio=small_height_ratio,
                expected_texts=expected_texts,
                keep_regions=keep_regions,
            )
        )

    comparisons = [
        _compare_arms(
            baseline,
            arm,
            expected_texts=expected_texts,
            min_expected_recovered_texts=min_expected_recovered_texts,
            max_unexpected_recovered_texts=max_unexpected_recovered_texts,
            max_latency_delta_ms=max_latency_delta_ms,
        )
        for arm in arms[1:]
    ]
    return OcrVisionLeversSpikeReport(
        frames=names,
        small_height_ratio=float(small_height_ratio),
        arms=arms,
        comparisons=comparisons,
    )


def load_frames(paths: Sequence[Path]) -> list[Frame]:
    frames: list[Frame] = []
    for path in paths:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read frame image: {path}")
        frames.append(Frame(img=image, ts=time.monotonic()))
    return frames


def expand_frame_paths(frames: Sequence[Path], frame_dirs: Sequence[Path]) -> list[Path]:
    paths = [Path(path) for path in frames]
    for directory in frame_dirs:
        paths.extend(
            sorted(
                path
                for path in Path(directory).iterdir()
                if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
            )
        )
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        unique.append(resolved)
        seen.add(resolved)
    return unique


def load_expected_texts(paths: Sequence[Path], inline: Sequence[str]) -> list[str]:
    expected = [item for item in (str(value).strip() for value in inline) if item]
    for path in paths:
        expected.extend(_read_expected_texts(path))
    unique: list[str] = []
    seen: set[str] = set()
    for item in expected:
        key = compact_text(item)
        if not key or key in seen:
            continue
        unique.append(item)
        seen.add(key)
    return unique


def _default_vision_factory() -> OcrFactory:
    from glassbox.cognition.ocr_vision import VisionOCR

    return VisionOCR


def _run_arm(
    name: str,
    frames: Sequence[Frame],
    frame_names: Sequence[str],
    recognizer: Callable[[Frame], list[TextRegion]],
    *,
    small_height_ratio: float,
    expected_texts: Sequence[str],
    keep_regions: bool,
) -> OcrVisionArmReport:
    regions: list[OcrRegionSummary] = []
    text_counts: Counter[str] = Counter()
    elapsed: list[float] = []
    region_count = 0
    nonempty_count = 0
    small_count = 0
    for frame, frame_name in zip(frames, frame_names, strict=True):
        started = time.perf_counter()
        frame_regions = recognizer(frame)
        elapsed.append((time.perf_counter() - started) * 1000.0)
        _, frame_h = frame.shape
        small_cutoff = max(1.0, float(frame_h) * float(small_height_ratio))
        for region in frame_regions:
            region_count += 1
            text = norm_text(region.text)
            if text:
                nonempty_count += 1
                text_counts[text] += 1
            small = region.box.h <= small_cutoff
            if small:
                small_count += 1
            if keep_regions:
                regions.append(
                    OcrRegionSummary(
                        frame=frame_name,
                        text=text,
                        box=_box_tuple(region.box),
                        confidence=float(region.confidence),
                        small=small,
                    )
                )
    found, missing = _expected_text_result(text_counts, expected_texts)
    return OcrVisionArmReport(
        name=name,
        frame_count=len(frames),
        region_count=region_count,
        nonempty_region_count=nonempty_count,
        small_region_count=small_count,
        elapsed_ms_p50=_percentile(elapsed, 50),
        elapsed_ms_p90=_percentile(elapsed, 90),
        elapsed_ms_total=sum(elapsed),
        texts=dict(sorted(text_counts.items())),
        expected_texts_found=found,
        expected_texts_missing=missing,
        regions=regions,
    )


def _recognize_full(ocr: Any, frame: Frame) -> list[TextRegion]:
    return _as_text_regions(ocr.recognize(frame.img))


def _recognize_tiled(
    ocr: Any,
    frame: Frame,
    *,
    rows: int,
    cols: int,
    overlap: float,
    include_full_frame: bool,
    nms_iou: float,
) -> list[TextRegion]:
    adapter = LegacyUIElementOCRAdapter(ocr)
    regions: list[TextRegion] = []
    if include_full_frame:
        regions.extend(adapter.recognize(frame))
    width, height = frame.shape
    for roi in tile_boxes(width, height, rows=rows, cols=cols, overlap=overlap):
        regions.extend(adapter.recognize(frame, roi=roi, native_roi=False))
    return merge_text_regions(regions, iou_threshold=nms_iou)


def _as_text_regions(results: Sequence[TextRegion | UIElement]) -> list[TextRegion]:
    regions: list[TextRegion] = []
    for item in results:
        if isinstance(item, TextRegion):
            regions.append(item)
            continue
        regions.append(
            TextRegion(
                text=item.text or "",
                box=item.box,
                confidence=float(item.confidence),
            )
        )
    return regions


def _compare_arms(
    baseline: OcrVisionArmReport,
    candidate: OcrVisionArmReport,
    *,
    expected_texts: Sequence[str],
    min_expected_recovered_texts: int,
    max_unexpected_recovered_texts: int | None,
    max_latency_delta_ms: float | None,
) -> OcrVisionArmComparison:
    baseline_counts = Counter(baseline.texts)
    candidate_counts = Counter(candidate.texts)
    recovered = {
        text: candidate_counts[text] - baseline_counts.get(text, 0)
        for text in sorted(candidate_counts)
        if candidate_counts[text] > baseline_counts.get(text, 0)
    }
    lost = {
        text: baseline_counts[text] - candidate_counts.get(text, 0)
        for text in sorted(baseline_counts)
        if baseline_counts[text] > candidate_counts.get(text, 0)
    }
    expected_recovered = sorted(
        set(candidate.expected_texts_found) - set(baseline.expected_texts_found),
        key=compact_text,
    )
    expected_lost = sorted(
        set(baseline.expected_texts_found) - set(candidate.expected_texts_found),
        key=compact_text,
    )
    unexpected_recovered = _unexpected_recovered_texts(recovered, expected_texts)
    latency_delta = candidate.elapsed_ms_total - baseline.elapsed_ms_total
    decision, reasons = _offline_decision(
        expected_texts=expected_texts,
        expected_recovered=expected_recovered,
        expected_lost=expected_lost,
        unexpected_recovered=unexpected_recovered,
        latency_delta_ms=latency_delta,
        min_expected_recovered_texts=min_expected_recovered_texts,
        max_unexpected_recovered_texts=max_unexpected_recovered_texts,
        max_latency_delta_ms=max_latency_delta_ms,
    )
    return OcrVisionArmComparison(
        baseline=baseline.name,
        candidate=candidate.name,
        recovered_texts=recovered,
        lost_texts=lost,
        expected_recovered_texts=expected_recovered,
        expected_lost_texts=expected_lost,
        unexpected_recovered_texts=unexpected_recovered,
        region_delta=candidate.region_count - baseline.region_count,
        small_region_delta=candidate.small_region_count - baseline.small_region_count,
        elapsed_ms_total_delta=latency_delta,
        offline_decision=decision,
        decision_reasons=reasons,
    )


def _expected_text_result(text_counts: Counter[str], expected_texts: Sequence[str]) -> tuple[list[str], list[str]]:
    if not expected_texts:
        return [], []
    observed = {compact_text(text) for text in text_counts}
    found: list[str] = []
    missing: list[str] = []
    for expected in expected_texts:
        if compact_text(expected) in observed:
            found.append(expected)
        else:
            missing.append(expected)
    return found, missing


def _unexpected_recovered_texts(
    recovered: dict[str, int],
    expected_texts: Sequence[str],
) -> dict[str, int]:
    expected_keys = {compact_text(text) for text in expected_texts}
    if not expected_keys:
        return dict(recovered)
    return {
        text: count
        for text, count in recovered.items()
        if compact_text(text) not in expected_keys
    }


def _offline_decision(
    *,
    expected_texts: Sequence[str],
    expected_recovered: Sequence[str],
    expected_lost: Sequence[str],
    unexpected_recovered: dict[str, int],
    latency_delta_ms: float,
    min_expected_recovered_texts: int,
    max_unexpected_recovered_texts: int | None,
    max_latency_delta_ms: float | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not expected_texts:
        return "census_only", ["no_expected_texts"]
    if expected_lost:
        reasons.append("lost_expected_texts")
    if len(expected_recovered) < max(1, int(min_expected_recovered_texts)):
        reasons.append("insufficient_expected_recovery")
    unexpected_count = sum(unexpected_recovered.values())
    if max_unexpected_recovered_texts is not None and unexpected_count > max_unexpected_recovered_texts:
        reasons.append("too_many_unexpected_recoveries")
    if max_latency_delta_ms is not None and latency_delta_ms > max_latency_delta_ms:
        reasons.append("latency_delta_too_high")
    blocking = {
        "lost_expected_texts",
        "too_many_unexpected_recoveries",
        "latency_delta_too_high",
    }
    if any(reason in blocking for reason in reasons):
        return "reject_offline", reasons
    if "insufficient_expected_recovery" in reasons:
        return "no_offline_signal", reasons
    return "promote_to_rig", ["expected_texts_recovered"]


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


def _frame_names(frames: Sequence[Frame], names: Sequence[str] | None) -> list[str]:
    if names is None:
        return [f"frame_{index:04d}" for index in range(len(frames))]
    if len(names) != len(frames):
        raise ValueError("frame_names length must match frames length")
    return [str(name) for name in names]


def _box_tuple(box: Box) -> tuple[int, int, int, int]:
    return int(box.x), int(box.y), int(box.w), int(box.h)


def _percentile(values: Sequence[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
    return ordered[index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", action="append", default=[], type=Path)
    parser.add_argument("--frame-dir", action="append", default=[], type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--minimum-text-height", type=float, default=0.0)
    parser.add_argument("--tiling", action="store_true")
    parser.add_argument("--tiling-rows", type=int, default=2)
    parser.add_argument("--tiling-cols", type=int, default=2)
    parser.add_argument("--tiling-overlap", type=float, default=0.15)
    parser.add_argument("--no-tiling-full-frame", action="store_true")
    parser.add_argument("--tiling-nms-iou", type=float, default=0.55)
    parser.add_argument("--small-height-ratio", type=float, default=0.035)
    parser.add_argument("--expect-text", action="append", default=[])
    parser.add_argument("--expect-file", action="append", default=[], type=Path)
    parser.add_argument("--min-expected-recovered", type=int, default=1)
    parser.add_argument("--max-unexpected-recovered", type=int)
    parser.add_argument("--max-latency-delta-ms", type=float)
    parser.add_argument("--no-regions", action="store_true")
    args = parser.parse_args(argv)

    paths = expand_frame_paths(args.frame, args.frame_dir)
    if not paths:
        parser.error("pass at least one --frame or --frame-dir")
    frames = load_frames(paths)
    expected_texts = load_expected_texts(args.expect_file, args.expect_text)
    report = collect_ocr_vision_levers_spike(
        frames,
        frame_names=[str(path) for path in paths],
        minimum_text_height=args.minimum_text_height,
        include_tiling_arm=args.tiling,
        tiling_rows=args.tiling_rows,
        tiling_cols=args.tiling_cols,
        tiling_overlap=args.tiling_overlap,
        tiling_include_full_frame=not args.no_tiling_full_frame,
        tiling_nms_iou=args.tiling_nms_iou,
        small_height_ratio=args.small_height_ratio,
        expected_texts=expected_texts,
        min_expected_recovered_texts=args.min_expected_recovered,
        max_unexpected_recovered_texts=args.max_unexpected_recovered,
        max_latency_delta_ms=args.max_latency_delta_ms,
        keep_regions=not args.no_regions,
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
