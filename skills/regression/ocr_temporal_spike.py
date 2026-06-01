"""Measurement helper for OCR temporal-voting viability.

This module intentionally samples raw single-frame OCR. It answers whether a
static screen actually produces frame-to-frame OCR variants before any runtime
path should opt in to temporal voting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.text_match import norm_text


@dataclass(frozen=True)
class OcrVariantCluster:
    sample_count: int
    variants: dict[str, int]
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class OcrTemporalSpikeReport:
    samples_requested: int
    samples_used: int
    distinct_frames: int
    duplicate_frames: int
    clusters: int
    variant_clusters: int
    variant_region_rate: float
    clusters_with_majority_change: int
    sample_spacing_ms: int
    clusters_detail: list[OcrVariantCluster] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_ocr_temporal_spike(
    phone: Any,
    *,
    samples: int = 10,
    spacing_ms: int = 100,
    pos_tol: int = 20,
    scope: str | None = None,
    keep_clusters: bool = True,
) -> OcrTemporalSpikeReport:
    """Collect raw OCR samples and report whether voting has real diversity."""
    requested = max(1, int(samples))
    spacing = max(0, int(spacing_ms))
    context = getattr(phone, "action_context", None)
    previous_suppress = getattr(context, "suppress_ocr_temporal_voting", None)
    previous_opt_in = getattr(context, "ocr_temporal_voting_opt_in", None)
    if context is not None:
        context.suppress_ocr_temporal_voting = True
        context.ocr_temporal_voting_opt_in = False
    try:
        scenes: list[Scene] = []
        frame_hashes: list[str] = []
        for index in range(requested):
            if index > 0 and spacing:
                time.sleep(spacing / 1000.0)
            phone.invalidate_perceive_cache()
            scene = phone.perceive(scope=scope)
            frame = getattr(phone, "last_frame", None)
            if frame is None:
                continue
            frame_hashes.append(_hash_frame(frame))
            scenes.append(scene)
    finally:
        if context is not None:
            if previous_suppress is not None:
                context.suppress_ocr_temporal_voting = previous_suppress
            if previous_opt_in is not None:
                context.ocr_temporal_voting_opt_in = previous_opt_in

    clusters = _cluster_text_regions(scenes, pos_tol=max(1, int(pos_tol)))
    details: list[OcrVariantCluster] = []
    variant_clusters = 0
    majority_changes = 0
    for members in clusters:
        variants: dict[str, int] = {}
        latest = ""
        for _scene_index, element in members:
            text = norm_text(element.text)
            if not text:
                continue
            latest = text
            variants[text] = variants.get(text, 0) + 1
        if len(variants) > 1:
            variant_clusters += 1
        if variants:
            winner = max(variants.items(), key=lambda item: item[1])[0]
            if latest and latest != winner and variants[winner] > sum(variants.values()) / 2:
                majority_changes += 1
        if keep_clusters:
            representative = members[-1][1]
            details.append(
                OcrVariantCluster(
                    sample_count=len({scene_index for scene_index, _ in members}),
                    variants=variants,
                    box=_box_tuple(representative.box),
                )
            )
    distinct = len({item for item in frame_hashes if item})
    return OcrTemporalSpikeReport(
        samples_requested=requested,
        samples_used=len(scenes),
        distinct_frames=distinct,
        duplicate_frames=max(0, len(frame_hashes) - distinct),
        clusters=len(clusters),
        variant_clusters=variant_clusters,
        variant_region_rate=(variant_clusters / len(clusters)) if clusters else 0.0,
        clusters_with_majority_change=majority_changes,
        sample_spacing_ms=spacing,
        clusters_detail=details,
    )


def _cluster_text_regions(scenes: list[Scene], *, pos_tol: int) -> list[list[tuple[int, UIElement]]]:
    clusters: list[dict[str, Any]] = []
    for scene_index, scene in enumerate(scenes):
        used: set[int] = set()
        for element in scene.elements:
            if not element.text:
                continue
            best_index: int | None = None
            best_distance = 1e18
            ex, ey = element.box.center
            for index, cluster in enumerate(clusters):
                if index in used:
                    continue
                distance = abs(float(cluster["cx"]) - ex) + abs(float(cluster["cy"]) - ey)
                if distance <= pos_tol and distance < best_distance:
                    best_index = index
                    best_distance = distance
            if best_index is None:
                clusters.append({"cx": float(ex), "cy": float(ey), "members": [(scene_index, element)]})
                used.add(len(clusters) - 1)
                continue
            cluster = clusters[best_index]
            cluster["members"].append((scene_index, element))
            count = len(cluster["members"])
            cluster["cx"] = (float(cluster["cx"]) * (count - 1) + ex) / count
            cluster["cy"] = (float(cluster["cy"]) * (count - 1) + ey) / count
            used.add(best_index)
    return [cluster["members"] for cluster in clusters]


def _hash_frame(frame: Any) -> str:
    image = getattr(frame, "img", None)
    if image is None:
        return ""
    return hashlib.blake2b(image.tobytes(), digest_size=16).hexdigest()


def _box_tuple(box: Box) -> tuple[int, int, int, int]:
    return int(box.x), int(box.y), int(box.w), int(box.h)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--spacing-ms", type=int, default=100)
    parser.add_argument("--pos-tol", type=int, default=20)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    from glassbox.config import get_config
    from glassbox.runtime import build_phone, make_source

    cfg = get_config().model_copy(update={"enable_memory": False})
    runtime = build_phone(source=make_source(cfg=cfg), cfg=cfg, profile=None)
    try:
        report = collect_ocr_temporal_spike(
            runtime.phone,
            samples=args.samples,
            spacing_ms=args.spacing_ms,
            pos_tol=args.pos_tol,
        )
    finally:
        runtime.close(save_memory=False)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
