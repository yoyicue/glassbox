"""Default-off UI layout segmentation helpers.

This module builds a lightweight, geometric element graph from the existing
OCR text elements plus optional icon detections. It deliberately avoids model
captioning: semantic icon labels remain a separate VLM/opt-in tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from glassbox.cognition.base import Box, Scene, UIElement

_LAYOUT_SOURCE = "layout_segmenter"
_GROUP_EVIDENCE = "layout_segment:icon_label"
_ICON_ONLY_EVIDENCE = "layout_segment:icon_only"


@dataclass(frozen=True)
class _PairCandidate:
    image_index: int
    text_index: int
    score: float
    orientation: str
    ambiguous: bool = False


def segment_layout(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> Scene:
    """Group icon/text affordances and rewrite element ids into reading order.

    The function mutates and returns ``scene`` to match the rest of the
    perception pipeline. It is only called behind a default-off runtime flag.
    """
    elements = list(scene.elements)
    if not elements:
        return scene
    width, height = _resolve_viewport(scene, viewport_size)
    pairings = _select_icon_label_pairs(elements, width=width, height=height)
    consumed: set[int] = set()
    grouped: list[UIElement] = []

    for pair in pairings:
        if pair.ambiguous or pair.image_index in consumed or pair.text_index in consumed:
            continue
        image = elements[pair.image_index]
        text = elements[pair.text_index]
        grouped.append(
            _make_icon_label_element(
                image,
                text,
                orientation=pair.orientation,
                width=width,
                height=height,
            )
        )
        consumed.add(pair.image_index)
        consumed.add(pair.text_index)

    for index, element in enumerate(elements):
        if index in consumed:
            continue
        if element.type == "image":
            trailing_group = _find_trailing_group_for_icon(element, grouped, width=width, height=height)
            if trailing_group is not None:
                grouped[trailing_group] = _merge_trailing_icon(grouped[trailing_group], element, width=width)
                continue
            grouped.append(_promote_icon_only(element, width=width, height=height))
        else:
            grouped.append(element.model_copy(deep=True))

    scene.elements = _assign_reading_order(grouped)
    return scene


def _resolve_viewport(scene: Scene, viewport_size: tuple[int, int] | None) -> tuple[int, int]:
    size = viewport_size or scene.viewport_size
    if size is not None:
        return max(1, int(size[0])), max(1, int(size[1]))
    if not scene.elements:
        return 1, 1
    return (
        max(1, max(element.box.x2 for element in scene.elements)),
        max(1, max(element.box.y2 for element in scene.elements)),
    )


def _is_label_candidate(element: UIElement, *, width: int, height: int) -> bool:
    if element.type in {"image", "status_bar", "modal_sheet", "unknown"}:
        return False
    text = (element.text or "").strip()
    if not text:
        return False
    if element.box.y2 < height * 0.055:
        return False
    if element.box.w <= 0 or element.box.h <= 0:
        return False
    return element.box.x < width


def _score_icon_label_pair(
    image: UIElement,
    text: UIElement,
    *,
    width: int,
    height: int,
) -> tuple[float, str] | None:
    scores: list[tuple[float, str]] = []
    image_cx, image_cy = image.box.center
    text_cx, text_cy = text.box.center

    # Home / tab-bar style: icon above its label, horizontally centered.
    vertical_gap = text.box.y - image.box.y2
    vertical_max_gap = max(18.0, min(height * 0.09, max(image.box.h * 1.8, text.box.h * 2.2)))
    vertical_dx = abs(text_cx - image_cx)
    vertical_max_dx = max(12.0, min(width * 0.12, max(image.box.w, text.box.w) * 0.8))
    if -text.box.h * 0.35 <= vertical_gap <= vertical_max_gap and vertical_dx <= vertical_max_dx:
        scores.append((
            (vertical_dx / vertical_max_dx) + (max(0.0, vertical_gap) / vertical_max_gap),
            "vertical",
        ))

    # Row style: leading icon then label.
    leading_gap = text.box.x - image.box.x2
    row_tol = max(8.0, min(height * 0.045, max(image.box.h, text.box.h) * 0.75))
    row_gap = max(18.0, min(width * 0.18, max(image.box.w, text.box.w) * 3.5))
    row_dy = abs(text_cy - image_cy)
    if -8 <= leading_gap <= row_gap and row_dy <= row_tol:
        scores.append((
            (row_dy / row_tol) + (max(0.0, leading_gap) / row_gap),
            "leading",
        ))

    # Row style: label then trailing affordance (chevron, switch, info icon).
    trailing_gap = image.box.x - text.box.x2
    if -8 <= trailing_gap <= row_gap and row_dy <= row_tol and image_cx > text_cx:
        scores.append((
            (row_dy / row_tol) + (max(0.0, trailing_gap) / row_gap) + 0.1,
            "trailing",
        ))

    if not scores:
        return None
    score, orientation = min(scores, key=lambda item: item[0])
    if score > 1.55:
        return None
    return score, orientation


def _select_icon_label_pairs(
    elements: list[UIElement],
    *,
    width: int,
    height: int,
) -> list[_PairCandidate]:
    text_indices = [
        index for index, element in enumerate(elements)
        if _is_label_candidate(element, width=width, height=height)
    ]
    candidates: list[_PairCandidate] = []
    for image_index, image in enumerate(elements):
        if image.type != "image":
            continue
        scored: list[tuple[float, str, int]] = []
        for text_index in text_indices:
            score = _score_icon_label_pair(image, elements[text_index], width=width, height=height)
            if score is not None:
                scored.append((score[0], score[1], text_index))
        if not scored:
            continue
        scored.sort(key=lambda item: item[0])
        best_score, best_orientation, best_text = scored[0]
        ambiguous = len(scored) > 1 and scored[1][0] - best_score < 0.18
        candidates.append(_PairCandidate(
            image_index=image_index,
            text_index=best_text,
            score=best_score,
            orientation=best_orientation,
            ambiguous=ambiguous,
        ))
    return sorted(candidates, key=lambda item: item.score)


def _make_icon_label_element(
    image: UIElement,
    text: UIElement,
    *,
    orientation: str,
    width: int,
    height: int,
) -> UIElement:
    box = _union_boxes(image.box, text.box)
    element_type = _group_type(image, text, orientation=orientation, width=width, height=height)
    tap_point = _group_tap_point(image, text, box=box, orientation=orientation, element_type=element_type)
    confidence = max(0.0, min(1.0, (float(image.confidence) + float(text.confidence)) / 2.0))
    return UIElement(
        type=element_type,
        box=box,
        text=text.text,
        confidence=confidence,
        suggested_actions=_suggested_actions(element_type),
        type_confidence=max(text.type_confidence or 0.0, 0.82),
        type_source=_LAYOUT_SOURCE,
        type_evidence=_merged_evidence(
            text,
            _GROUP_EVIDENCE,
            f"layout_orientation:{orientation}",
            f"layout_children:{image.element_id},{text.element_id}",
        ),
        intent_label=text.intent_label,
        intent_confidence=text.intent_confidence,
        intent_source=text.intent_source,
        preferred_tap_point=tap_point,
        whitebox_hint=text.whitebox_hint,
    )


def _group_type(
    image: UIElement,
    text: UIElement,
    *,
    orientation: str,
    width: int,
    height: int,
) -> str:
    if text.type in {"nav_back", "tab_bar_item", "switch", "button", "list_item", "input"}:
        return text.type
    if orientation == "vertical":
        return "tab_bar_item" if text.box.y > height - 120 else "button"
    if _looks_like_switch(image, width=width):
        return "switch"
    return "list_item"


def _group_tap_point(
    image: UIElement,
    text: UIElement,
    *,
    box: Box,
    orientation: str,
    element_type: str,
) -> tuple[int, int]:
    if text.preferred_tap_point is not None:
        return text.preferred_tap_point
    if element_type == "switch" or orientation == "vertical":
        return image.box.center
    return box.center


def _promote_icon_only(element: UIElement, *, width: int, height: int) -> UIElement:
    element_type = _icon_only_type(element, width=width, height=height)
    return element.model_copy(
        update={
            "type": element_type,
            "suggested_actions": _suggested_actions(element_type),
            "type_confidence": max(element.type_confidence or 0.0, 0.68),
            "type_source": _LAYOUT_SOURCE,
            "type_evidence": _merged_evidence(element, _ICON_ONLY_EVIDENCE),
            "preferred_tap_point": element.preferred_tap_point or element.box.center,
        },
        deep=True,
    )


def _find_trailing_group_for_icon(
    icon: UIElement,
    grouped: list[UIElement],
    *,
    width: int,
    height: int,
) -> int | None:
    best_index = None
    best_score = float("inf")
    for index, group in enumerate(grouped):
        if "layout_orientation:leading" not in group.type_evidence:
            continue
        if not group.text:
            continue
        if icon.box.center[0] <= group.box.center[0]:
            continue
        if icon.box.x < group.box.x2 - max(8, icon.box.w // 2):
            continue
        tolerance = max(8.0, min(height * 0.045, max(icon.box.h, group.box.h) * 0.55))
        row_delta = abs(float(icon.box.center[1]) - float(group.box.center[1]))
        if row_delta > tolerance:
            continue
        # Accessories can sit at the far edge of a Settings row, but should not
        # cross columns into an unrelated pane.
        if icon.box.center[0] - group.box.center[0] > width * 0.85:
            continue
        score = row_delta + max(0, icon.box.x - group.box.x2) / max(1, width)
        if score < best_score:
            best_index = index
            best_score = score
    return best_index


def _merge_trailing_icon(group: UIElement, icon: UIElement, *, width: int) -> UIElement:
    box = _union_boxes(group.box, icon.box)
    element_type = "switch" if _looks_like_switch(icon, width=width) else group.type
    tap_point = icon.box.center if element_type == "switch" else box.center
    return group.model_copy(
        update={
            "type": element_type,
            "box": box,
            "suggested_actions": _suggested_actions(element_type),
            "preferred_tap_point": tap_point,
            "type_evidence": _merged_evidence(
                group,
                f"layout_accessory:{icon.element_id}",
                "layout_accessory_orientation:trailing",
            ),
        },
        deep=True,
    )


def _icon_only_type(element: UIElement, *, width: int, height: int) -> str:
    center_x, _ = element.box.center
    if element.box.y2 < min(110, height * 0.12) and (center_x < width * 0.18 or center_x > width * 0.82):
        return "nav_back"
    if _looks_like_switch(element, width=width):
        return "switch"
    return "button"


def _looks_like_switch(element: UIElement, *, width: int) -> bool:
    center_x, _ = element.box.center
    return element.box.w >= element.box.h * 1.45 and center_x > width * 0.55


def _suggested_actions(element_type: str) -> list[str]:
    if element_type == "input":
        return ["tap", "type"]
    if element_type == "status_bar":
        return []
    return ["tap"]


def _merged_evidence(element: UIElement, *items: str) -> list[str]:
    evidence = list(element.type_evidence or [])
    for item in items:
        if item and item not in evidence:
            evidence.append(item)
    return evidence


def _union_boxes(*boxes: Box) -> Box:
    x1 = min(box.x for box in boxes)
    y1 = min(box.y for box in boxes)
    x2 = max(box.x2 for box in boxes)
    y2 = max(box.y2 for box in boxes)
    return Box(x=x1, y=y1, w=max(1, x2 - x1), h=max(1, y2 - y1))


def _assign_reading_order(elements: list[UIElement]) -> list[UIElement]:
    rows = _cluster_rows(elements)
    ordered: list[UIElement] = []
    for row in sorted(rows, key=lambda item: item[0]):
        ordered.extend(sorted(row[1], key=lambda element: (element.box.x, element.box.center[1])))
    return [
        element.model_copy(update={"element_id": index}, deep=True)
        for index, element in enumerate(ordered)
    ]


def _cluster_rows(elements: list[UIElement]) -> list[tuple[float, list[UIElement]]]:
    rows: list[tuple[float, list[UIElement]]] = []
    for element in sorted(elements, key=lambda item: (item.box.center[1], item.box.x)):
        center_y = float(element.box.center[1])
        best_index = None
        best_distance = float("inf")
        for index, (row_y, row_elements) in enumerate(rows):
            tolerance = _row_tolerance([*row_elements, element])
            distance = abs(center_y - row_y)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            rows.append((center_y, [element]))
            continue
        _, row_elements = rows[best_index]
        row_elements.append(element)
        rows[best_index] = (_median_center_y(row_elements), row_elements)
    return rows


def _row_tolerance(elements: list[UIElement]) -> float:
    heights = [max(1, element.box.h) for element in elements]
    return max(8.0, min(48.0, float(median(heights)) * 0.65))


def _median_center_y(elements: list[UIElement]) -> float:
    return float(median(element.box.center[1] for element in elements))


__all__ = ["segment_layout"]
