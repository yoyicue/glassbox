"""VLM-assisted row recovery for iOS Settings rows.

Owns the small amount of state needed for row-level OCR fallback: per-run
budgeting, crop cache, and the bounded Settings-list point grounding fallback.
The crawler resets this module at run start.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from glassbox.cognition import Box, UIElement
from glassbox.cognition.vlm_ocr import (
    choose_label_from_region,
    encode_crop_png,
    horizontal_band_box,
)
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY, EXPECTED_ROOT_NAV_TEXT_ZH

_ROW_TEXT_CACHE: dict[str, str] = {}
_ROW_CALL_BUDGET = 20
_POINT_CALL_BUDGET = 8
_ROW_TOTAL_CALL_BUDGET = _ROW_CALL_BUDGET + _POINT_CALL_BUDGET
_POINT_CACHE: dict[str, tuple[UIElement | None, str | None]] = {}
_row_calls = 0
_point_calls = 0
_POINT_SCENE_ALLOWLIST = frozenset({"settings_root", "settings_detail"})


def reset_row_state() -> None:
    global _point_calls, _row_calls
    _row_calls = 0
    _point_calls = 0
    _ROW_TEXT_CACHE.clear()
    _POINT_CACHE.clear()


def recover_root_label(
    phone,
    element,
    *,
    force: bool = False,
    candidate_labels: tuple[str, ...] | None = None,
) -> str | None:
    """Use VLM OCR for root-row labels only when Kimi is enabled."""
    global _row_calls
    kimi = getattr(phone, "kimi", None) if phone is not None else None
    frame = getattr(phone, "_last_frame", None) if phone is not None else None
    if kimi is None or frame is None or not (
        hasattr(kimi, "chat") or hasattr(kimi, "read_text_region")
    ):
        return None
    if not DEFAULT_SETTINGS_POLICY.should_recover_root_row_ocr(element):
        return None
    if not force and _row_calls >= _ROW_CALL_BUDGET:
        return None
    if _row_calls + _point_calls >= _ROW_TOTAL_CALL_BUDGET:
        return None
    _row_calls += 1
    from glassbox.cognition.vlm_ocr import read_row_text

    row_box = _row_band_box(frame.img, element.box)
    labels = candidate_labels or EXPECTED_ROOT_NAV_TEXT_ZH
    vlm_label = _choose_root_label_from_row(kimi, frame.img, row_box, labels)
    if vlm_label is not None:
        return vlm_label
    if not hasattr(kimi, "read_text_region"):
        return None
    vlm_text = read_row_text(kimi, frame.img, row_box, cache=_ROW_TEXT_CACHE)
    if not vlm_text:
        return None
    return DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(vlm_text)


def vlm_point_for_label(phone, label: str, *, scene_kind: str) -> UIElement | None:
    """Ground a Settings list row label to a synthetic row element.

    This is a narrow fallback for 1D Settings lists. The VLM-provided x is not
    trusted as a tap x; the returned element is shaped like a left-side row label
    so the existing Settings row tap projection keeps control of actuation.
    """
    global _point_calls
    label = (label or "").strip()
    if scene_kind not in _POINT_SCENE_ALLOWLIST:
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="scene_kind_rejected")
        return None
    if not label or DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text(label):
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="unsafe_label")
        return None
    kimi = getattr(phone, "kimi", None) if phone is not None else None
    frame = getattr(phone, "_last_frame", None) if phone is not None else None
    frame_img = getattr(frame, "img", None)
    if kimi is None or frame_img is None or not hasattr(kimi, "chat"):
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="no_kimi_or_frame")
        return None

    band = _visible_list_band_box(frame_img)
    crop_png = encode_crop_png(frame_img, band, pad=0)
    if crop_png is None:
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="parse_failed")
        return None
    cache_key = f"{hashlib.sha1(crop_png).hexdigest()}:{label}"
    if cache_key in _POINT_CACHE:
        cached, reason = _POINT_CACHE[cache_key]
        if cached is not None:
            _record_point_grounding(
                phone,
                label=label,
                scene_kind=scene_kind,
                hit=cached,
                cached=True,
            )
            return cached.model_copy(deep=True)
        _record_point_grounding(
            phone,
            label=label,
            scene_kind=scene_kind,
            reason=reason or "parse_failed",
            cached=True,
        )
        return None
    if _point_calls >= _POINT_CALL_BUDGET or _row_calls + _point_calls >= _ROW_TOTAL_CALL_BUDGET:
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="budget_exhausted")
        return None
    _point_calls += 1

    try:
        resp = kimi.chat(
            system=(
                "You are a UI row locator for iOS Settings. The image is a cropped "
                "vertical Settings list. Given one target row label, return only a "
                'computer_use JSON object: {"action":"left_click","coordinate":[x,y]}. '
                "The coordinate must be the center of the matching row in the provided image. "
                "If the row is not visible, return {}."
            ),
            user_text=f"Target row label: {label}",
            image=crop_png,
            json_object=True,
        )
    except Exception:
        _POINT_CACHE[cache_key] = (None, "parse_failed")
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="parse_failed")
        return None

    coordinate = _extract_coordinate(resp)
    if coordinate is None:
        _POINT_CACHE[cache_key] = (None, "parse_failed")
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="parse_failed")
        return None
    point = _normalize_crop_point(coordinate, band)
    if point is None:
        _POINT_CACHE[cache_key] = (None, "parse_failed")
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="parse_failed")
        return None
    x, y = point
    frame_h, frame_w = frame_img.shape[:2]
    if not (band.y <= y <= band.y2):
        _POINT_CACHE[cache_key] = (None, "out_of_band")
        _record_point_grounding(phone, label=label, scene_kind=scene_kind, reason="out_of_band")
        return None

    element = _synthetic_row_element(label, x=x, y=y, viewport_width=frame_w, viewport_height=frame_h)
    _POINT_CACHE[cache_key] = (element, None)
    _record_point_grounding(phone, label=label, scene_kind=scene_kind, hit=element)
    return element


def _choose_root_label_from_row(
    client,
    frame_img,
    row_box: Box,
    labels: tuple[str, ...],
) -> str | None:
    """Ask the VLM to choose an exact Settings root label from a local row crop."""
    return choose_label_from_region(
        client,
        frame_img,
        row_box,
        labels,
        pad=0,
        cache=_ROW_TEXT_CACHE,
        system=(
            "你是 iOS 设置列表行识别器。输入是一条局部裁剪的设置列表行，"
            "只能从给定候选中选择一个最匹配的根页面标签。"
            "只输出候选标签原文；如果不是这些候选，输出 NONE。"
        ),
        user_prefix="请识别这条局部截图对应哪一个候选标签。",
        normalizer=DEFAULT_SETTINGS_POLICY.canonical_expected_root_label,
    )


def _row_band_box(frame_img, box) -> Box:
    """Crop a horizontal row band, not a full screen and not just one noisy OCR glyph.

    Settings row labels can be split into multiple OCR elements. A single glyph
    crop often lacks enough context for VLM OCR; a shallow row band keeps the
    request local while preserving the visible label fragments.
    """
    return horizontal_band_box(frame_img, box, pad_y=8, min_height=34)


def _visible_list_band_box(frame_img) -> Box:
    frame_h, frame_w = frame_img.shape[:2]
    top = max(0, int(frame_h * 0.13))
    bottom = min(frame_h, int(frame_h * 0.94))
    if bottom - top < 80:
        top, bottom = 0, frame_h
    return Box(x=0, y=top, w=frame_w, h=max(1, bottom - top))


def _extract_coordinate(resp: Any) -> tuple[float, float] | None:
    parsed = getattr(resp, "parsed", None)
    payloads: list[dict[str, Any]] = []
    if isinstance(parsed, dict):
        payloads.append(parsed)
    raw_payload = _parse_json_object(getattr(resp, "raw_content", ""))
    if raw_payload is not None:
        payloads.append(raw_payload)
    if not payloads:
        return None
    for payload in payloads:
        coordinate = _coordinate_from_payload(payload)
        if coordinate is not None:
            return coordinate
    return None


def _coordinate_from_payload(payload: dict[str, Any]) -> tuple[float, float] | None:
    coordinate = payload.get("coordinate") or payload.get("coordinates")
    if coordinate is None and isinstance(payload.get("action"), dict):
        coordinate = payload["action"].get("coordinate") or payload["action"].get("coordinates")
    if (
        not isinstance(coordinate, (list, tuple))
        or len(coordinate) < 2
        or isinstance(coordinate[0], bool)
        or isinstance(coordinate[1], bool)
    ):
        return None
    try:
        return float(coordinate[0]), float(coordinate[1])
    except (TypeError, ValueError):
        return None


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match is None:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _normalize_crop_point(point: tuple[float, float], crop_box: Box) -> tuple[int, int] | None:
    x_raw, y_raw = point
    if not (x_raw >= 0 and y_raw >= 0):
        return None
    if x_raw <= 1.0 and y_raw <= 1.0:
        x = crop_box.x + round(x_raw * crop_box.w)
        y = crop_box.y + round(y_raw * crop_box.h)
        return x, y
    if x_raw <= 1000.0 and y_raw <= 1000.0 and (
        x_raw >= crop_box.w or y_raw >= crop_box.h
    ):
        x = crop_box.x + round((x_raw / 1000.0) * crop_box.w)
        y = crop_box.y + round((y_raw / 1000.0) * crop_box.h)
        return x, y
    x = crop_box.x + round(x_raw)
    y = crop_box.y + round(y_raw)
    return x, y


def _synthetic_row_element(
    label: str,
    *,
    x: int,
    y: int,
    viewport_width: int,
    viewport_height: int,
) -> UIElement:
    del x
    height = 22
    top = max(0, min(viewport_height - height, int(y) - height // 2))
    left = max(1, int(viewport_width * 0.18))
    width = max(44, min(int(viewport_width * 0.24), len(label) * 14 or 44))
    return UIElement(
        type="text",
        box=Box(x=left, y=top, w=width, h=height),
        text=label,
        confidence=0.5,
        type_source="vlm_point_for_label",
        type_evidence=["kimi_1d_row_y_grounding"],
    )


def _record_point_grounding(
    phone,
    *,
    label: str,
    scene_kind: str,
    reason: str | None = None,
    hit: UIElement | None = None,
    cached: bool = False,
) -> None:
    if phone is None:
        return
    payload: dict[str, Any] = {
        "label": label,
        "scene_kind": scene_kind,
        "cached": cached,
        "status": "hit" if hit is not None else "miss",
    }
    if reason is not None:
        payload["reason"] = reason
    if hit is not None:
        payload["point"] = list(hit.box.center)
    try:
        phone._ios_settings_last_vlm_point_grounding = payload
        phone._ios_settings_vlm_point_failure_reason = reason
        history = getattr(phone, "_ios_settings_vlm_point_grounding_history", None)
        if not isinstance(history, list):
            history = []
            phone._ios_settings_vlm_point_grounding_history = history
        history.append(payload)
    except Exception:
        pass
