"""Offline measurement for closed-set OCR postprocessing value.

This helper replays serialized OCR scenes twice: first as raw OCR-only
elements, then with the iOS/iPadOS closed-set annotators used by the default
perceive path. It measures how much Home/Settings canonicalization changes
element identity before spending more rig time on task-level A/B.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.text_match import norm_text
from glassbox.config import AgentConfig
from glassbox.ios.settings_rows import (
    SETTINGS_ROOT_INTENT_SOURCE,
    annotate_settings_root_row_intents,
    settings_root_fuzzy_aliases_for_config,
    settings_root_label_aliases_for_config,
)
from glassbox.ios.springboard import annotate_springboard_icon_intents
from glassbox.memory.element_key import element_key

SPRINGBOARD_INTENT_SOURCE = "springboard_lexicon"
_CLOSED_SET_INTENT_SOURCES = frozenset({SPRINGBOARD_INTENT_SOURCE, SETTINGS_ROOT_INTENT_SOURCE})


@dataclass(frozen=True)
class OcrPostprocessChange:
    file: str
    raw_text: str | None
    intent_label: str | None
    intent_source: str | None
    raw_key: str
    canonical_key: str
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class OcrPostprocessSpikeReport:
    files: int
    elements: int
    annotated_elements: int
    settings_annotations: int
    springboard_annotations: int
    canonical_key_changes: int
    raw_unique_keys: int
    canonical_unique_keys: int
    raw_to_canonical_key_delta: int
    canonical_labels_with_multiple_raw_variants: int
    raw_variant_excess: int
    annotations_by_source: dict[str, int]
    raw_variants_by_canonical_label: dict[str, dict[str, int]]
    examples: list[OcrPostprocessChange] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_ocr_postprocess_spike(
    paths: Sequence[Path],
    *,
    config: AgentConfig | None = None,
    platform: str = "ipados",
    max_examples: int = 30,
) -> OcrPostprocessSpikeReport:
    """Compare raw OCR element identity with closed-set canonicalized identity."""
    cfg = config or AgentConfig()
    settings_aliases = settings_root_label_aliases_for_config(cfg)
    settings_fuzzy_aliases = settings_root_fuzzy_aliases_for_config(cfg)
    raw_keys: set[str] = set()
    canonical_keys: set[str] = set()
    annotations_by_source: Counter[str] = Counter()
    raw_variants: dict[str, Counter[str]] = defaultdict(Counter)
    examples: list[OcrPostprocessChange] = []
    files = 0
    elements = 0
    settings_annotations = 0
    springboard_annotations = 0
    canonical_key_changes = 0

    for path in sorted(Path(item) for item in paths):
        scene = load_ocr_scene(path)
        _strip_closed_set_intents(scene)
        viewport_size = scene.viewport_size or _fallback_viewport(scene)
        before = [
            (element_key(element, viewport_size), element.text, _box_tuple(element.box))
            for element in scene.elements
        ]

        springboard_annotations += annotate_springboard_icon_intents(
            scene,
            viewport_size=viewport_size,
            platform=platform,
        )
        settings_annotations += annotate_settings_root_row_intents(
            scene,
            viewport_size=viewport_size,
            aliases=settings_aliases,
            fuzzy_aliases=settings_fuzzy_aliases,
        )

        files += 1
        elements += len(scene.elements)
        for element, (raw_key, raw_text, box) in zip(scene.elements, before, strict=True):
            canonical_key = element_key(element, viewport_size)
            raw_keys.add(raw_key)
            canonical_keys.add(canonical_key)
            if element.intent_source in _CLOSED_SET_INTENT_SOURCES:
                annotations_by_source[str(element.intent_source)] += 1
                if element.intent_label:
                    raw_variants[str(element.intent_label)][norm_text(raw_text)] += 1
            if canonical_key == raw_key:
                continue
            canonical_key_changes += 1
            if len(examples) < max(0, int(max_examples)):
                examples.append(
                    OcrPostprocessChange(
                        file=str(path),
                        raw_text=raw_text,
                        intent_label=element.intent_label,
                        intent_source=element.intent_source,
                        raw_key=raw_key,
                        canonical_key=canonical_key,
                        box=box,
                    )
                )

    variant_dict = {
        label: dict(counter.most_common())
        for label, counter in sorted(raw_variants.items(), key=lambda item: item[0])
    }
    return OcrPostprocessSpikeReport(
        files=files,
        elements=elements,
        annotated_elements=sum(annotations_by_source.values()),
        settings_annotations=settings_annotations,
        springboard_annotations=springboard_annotations,
        canonical_key_changes=canonical_key_changes,
        raw_unique_keys=len(raw_keys),
        canonical_unique_keys=len(canonical_keys),
        raw_to_canonical_key_delta=len(raw_keys) - len(canonical_keys),
        canonical_labels_with_multiple_raw_variants=sum(
            1 for variants in variant_dict.values() if len(variants) > 1
        ),
        raw_variant_excess=sum(max(0, len(variants) - 1) for variants in variant_dict.values()),
        annotations_by_source=dict(sorted(annotations_by_source.items())),
        raw_variants_by_canonical_label=variant_dict,
        examples=examples,
    )


def expand_ocr_paths(paths: Sequence[Path], directories: Sequence[Path]) -> list[Path]:
    expanded = [Path(path) for path in paths]
    for directory in directories:
        expanded.extend(sorted(Path(directory).glob("*.ocr.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in expanded:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        unique.append(resolved)
        seen.add(resolved)
    return unique


def load_ocr_scene(path: Path) -> Scene:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    elements = [
        _element_from_payload(raw, index=index)
        for index, raw in enumerate(payload.get("elements") or [])
        if isinstance(raw, dict)
    ]
    viewport_size = _viewport_size_from_png(path) or _viewport_size_from_payload(payload)
    return Scene(
        frame_id=int(payload.get("frame_id") or 0),
        timestamp=float(payload.get("timestamp") or 0.0),
        elements=elements,
        viewport_size=viewport_size,
        scene_type=payload.get("scene_type"),
        platform_scene_kind=payload.get("platform_scene_kind") or payload.get("scene_type"),
        page_id=payload.get("page_id"),
        safe_actions=list(payload.get("safe_actions") or []),
        classification_evidence=list(payload.get("classification_evidence") or payload.get("evidence") or []),
        classification_confidence=payload.get("classification_confidence") or payload.get("confidence"),
    )


def _element_from_payload(raw: dict[str, Any], *, index: int) -> UIElement:
    return UIElement(
        type=raw.get("type") or "text",
        box=_box_from_payload(raw.get("box")),
        text=raw.get("text"),
        confidence=float(raw.get("confidence", 1.0)),
        suggested_actions=list(raw.get("suggested_actions") or []),
        type_evidence=list(raw.get("type_evidence") or []),
        intent_label=raw.get("intent_label"),
        intent_confidence=raw.get("intent_confidence"),
        intent_source=raw.get("intent_source"),
        element_id=int(raw.get("element_id", index) or index),
    )


def _box_from_payload(raw: Any) -> Box:
    if isinstance(raw, dict):
        return Box(
            x=int(raw.get("x", 0)),
            y=int(raw.get("y", 0)),
            w=int(raw.get("w", 0)),
            h=int(raw.get("h", 0)),
        )
    if isinstance(raw, list | tuple) and len(raw) >= 4:
        return Box(x=int(raw[0]), y=int(raw[1]), w=int(raw[2]), h=int(raw[3]))
    return Box(x=0, y=0, w=0, h=0)


def _strip_closed_set_intents(scene: Scene) -> None:
    for element in scene.elements:
        if element.intent_source not in _CLOSED_SET_INTENT_SOURCES:
            continue
        element.intent_label = None
        element.intent_confidence = None
        element.intent_source = None
        element.type_evidence = [
            evidence
            for evidence in element.type_evidence
            if not (
                evidence in _CLOSED_SET_INTENT_SOURCES
                or evidence.startswith("springboard_app:")
                or evidence.startswith("springboard_label:")
                or evidence.startswith("settings_root_label:")
            )
        ]


def _viewport_size_from_png(path: Path) -> tuple[int, int] | None:
    png = path.with_suffix(".png")
    if not png.exists():
        return None
    image = cv2.imread(str(png))
    if image is None:
        return None
    height, width = image.shape[:2]
    return int(width), int(height)


def _viewport_size_from_payload(payload: dict[str, Any]) -> tuple[int, int] | None:
    raw = payload.get("viewport_size")
    if isinstance(raw, list | tuple) and len(raw) >= 2:
        return int(raw[0]), int(raw[1])
    return None


def _fallback_viewport(scene: Scene) -> tuple[int, int]:
    width = max((element.box.x2 for element in scene.elements), default=440)
    height = max((element.box.y2 for element in scene.elements), default=956)
    return max(width, 440), max(height, 956)


def _box_tuple(box: Box) -> tuple[int, int, int, int]:
    return int(box.x), int(box.y), int(box.w), int(box.h)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-json", action="append", default=[], type=Path)
    parser.add_argument("--ocr-dir", action="append", default=[], type=Path)
    parser.add_argument("--language", default="en")
    parser.add_argument("--region", default="HK")
    parser.add_argument("--phone-model", default="ipad_mini_7")
    parser.add_argument("--platform", default="ipados")
    parser.add_argument("--max-examples", type=int, default=30)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    paths = expand_ocr_paths(args.ocr_json, args.ocr_dir)
    if not paths:
        parser.error("pass at least one --ocr-json or --ocr-dir")
    report = collect_ocr_postprocess_spike(
        paths,
        config=AgentConfig(language=args.language, region=args.region, phone_model=args.phone_model),
        platform=args.platform,
        max_examples=args.max_examples,
    )
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.out.expanduser().write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
