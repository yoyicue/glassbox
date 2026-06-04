"""On-rig probe for iOS Voice Control continuous overlay.

The probe assumes the device is already on:

    Settings > Accessibility > Voice Control > Overlay

It toggles the requested overlay -> None -> requested overlay using cropped-pixel coordinates,
captures HDMI frames, runs VisionOCR, and summarizes overlay marker counts. This
is a measurement harness, not a smoke test; it needs the real rig.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import cv2

from glassbox.ai import open_phone
from glassbox.cognition.base import Scene
from glassbox.cognition.ocr_vision import VisionOCR
from glassbox.cognition.voice_control_overlay import (
    apply_voice_control_overlay_hints,
    parse_voice_control_overlay,
)

_MODES = ("item_numbers", "item_names", "numbered_grid")
_MODE_LABELS = {
    "item_numbers": "item_numbers",
    "item_names": "item_names",
    "numbered_grid": "numbered_grid",
}
_MOD_CTRL = 0x01
_MOD_META_LEFT = 0x08
_KEY_A = 0x04
_KEY_F = 0x09
_KEY_DELETE = 0x2A
_KEY_ESC = 0x29
_KEY_RETURN = 0x28
_KEY_SPACE = 0x2C


def _parse_point(value: str) -> tuple[int, int]:
    try:
        x_text, y_text = value.split(",", 1)
        return int(x_text), int(y_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("point must be X,Y") from exc


def _action_dict(outcome: Any) -> dict[str, Any]:
    return {
        "ok": outcome.ok,
        "transport_ok": outcome.transport_ok,
        "semantic_status": outcome.semantic_status,
        "reason": outcome.reason,
        "target": outcome.target,
    }


def _run_keyboard_focus(
    phone: Any,
    *,
    result: dict[str, Any],
    method: str,
    keyboard_point: tuple[int, int],
) -> None:
    if method == "tap":
        focus = phone.tap_xy(*keyboard_point, coordinate_space="cropped_px")
        result["steps"].append(
            {
                "action": "tap_keyboard_field",
                "point": list(keyboard_point),
                "outcome": _action_dict(focus),
            }
        )
        return
    if method == "double_tap":
        first = phone.tap_xy(*keyboard_point, coordinate_space="cropped_px")
        result["steps"].append(
            {
                "action": "double_tap_keyboard_field_first",
                "point": list(keyboard_point),
                "outcome": _action_dict(first),
            }
        )
        time.sleep(0.15)
        second = phone.tap_xy(*keyboard_point, coordinate_space="cropped_px")
        result["steps"].append(
            {
                "action": "double_tap_keyboard_field_second",
                "point": list(keyboard_point),
                "outcome": _action_dict(second),
            }
        )
        return
    if method == "cmd_f":
        key = phone.key(_MOD_META_LEFT, _KEY_F)
        result["steps"].append(
            {
                "action": "keyboard_focus_cmd_f",
                "modifier": _MOD_META_LEFT,
                "keycode": _KEY_F,
                "outcome": _action_dict(key),
            }
        )
        return
    if method == "tap_then_cmd_f":
        _run_keyboard_focus(
            phone,
            result=result,
            method="tap",
            keyboard_point=keyboard_point,
        )
        _run_keyboard_focus(
            phone,
            result=result,
            method="cmd_f",
            keyboard_point=keyboard_point,
        )
        return
    raise ValueError(f"unsupported keyboard focus method: {method}")


def _run_key_sequence(
    phone: Any,
    *,
    result: dict[str, Any],
    key_sequence: tuple[tuple[str, int, int], ...],
    settle_s: float,
) -> None:
    for action, modifier, keycode in key_sequence:
        key = phone.key(modifier, keycode)
        result["steps"].append(
            {
                "action": action,
                "modifier": modifier,
                "keycode": keycode,
                "outcome": _action_dict(key),
            }
        )
        time.sleep(settle_s)


def _overlay_hint_mapping(obs: Any, frame: Any, *, mode: str) -> dict[str, Any]:
    scene_path = Path(obs.scene_path) if obs.scene_path else None
    if scene_path is None or not scene_path.exists():
        return {"mode": mode, "scene_marker_count": None, "mapped": []}
    scene = Scene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    markers = parse_voice_control_overlay(scene.elements, mode=mode, frame_img=frame)
    apply_voice_control_overlay_hints(
        scene,
        markers,
        include_names=mode == "item_names",
        include_frame_local_numbers=mode in {"item_numbers", "numbered_grid"},
    )
    mapped = [
        {
            "element_id": element.element_id,
            "text": element.text,
            "type": element.type,
            "center": list(element.box.center),
            "accessibility_id": element.whitebox_hint.accessibility_id,
        }
        for element in scene.elements
        if (
            element.whitebox_hint is not None
            and element.whitebox_hint.accessibility_id
        )
    ]
    return {"mode": mode, "scene_marker_count": len(markers), "mapped": mapped}


def _capture(
    phone: Any,
    *,
    label: str,
    output_dir: Path,
    ocr: VisionOCR,
    mapping_mode: str,
) -> dict[str, Any]:
    obs = phone.observe()
    screenshot = Path(obs.screenshot_path) if obs.screenshot_path else None
    if screenshot is None:
        raise RuntimeError(f"{label}: observe did not produce a screenshot")
    scene_path = Path(obs.scene_path) if obs.scene_path else None
    frame = cv2.imread(str(screenshot))
    if frame is None:
        raise RuntimeError(f"{label}: could not load screenshot {screenshot}")

    elements = ocr.recognize(frame)
    mode_counts: dict[str, int] = {}
    samples: dict[str, list[dict[str, Any]]] = {}
    for mode in _MODES:
        markers = parse_voice_control_overlay(elements, mode=mode, frame_img=frame)
        mode_counts[mode] = len(markers)
        samples[mode] = [
            {
                "kind": marker.kind,
                "text": marker.text,
                "number": marker.number,
                "center": list(marker.center),
                "confidence": round(marker.confidence, 3),
            }
            for marker in markers[:16]
        ]

    copied = output_dir / f"{label}.png"
    shutil.copy2(screenshot, copied)
    return {
        "label": label,
        "page_id": obs.page_id,
        "scene_type": obs.scene_type,
        "coordinate_space": obs.coordinate_space,
        "viewport_size": list(obs.viewport_size or ()),
        "crop_bbox": list(obs.crop_bbox or ()),
        "screenshot": str(copied),
        "scene_path": str(scene_path) if scene_path is not None else None,
        "visible_texts": list(obs.visible_texts),
        "visible_texts_head": list(obs.visible_texts)[:35],
        "ocr_count": len(elements),
        "mode_counts": mode_counts,
        "samples": samples,
        "overlay_hint_mapping": _overlay_hint_mapping(obs, frame, mode=mapping_mode),
    }


def run_probe(
    *,
    output_dir: Path,
    overlay_mode: str,
    none_point: tuple[int, int],
    item_numbers_point: tuple[int, int],
    item_names_point: tuple[int, int],
    numbered_grid_point: tuple[int, int],
    final_overlay_mode: str | None,
    scroll_probe: bool,
    scroll_start: tuple[int, int],
    scroll_end: tuple[int, int],
    scroll_repeat: int,
    restore_scroll: bool,
    wheel_probe: bool,
    wheel_ticks: int,
    wheel_second_ticks: int | None,
    wheel_repeat: int,
    wheel_focus_point: tuple[int, int] | None,
    wheel_focus_click: bool,
    restore_wheel: bool,
    keyboard_probe: bool,
    keyboard_point: tuple[int, int],
    keyboard_focus_method: str,
    keyboard_disable_overlay_before_focus: bool,
    keyboard_switch_input_before_type: bool,
    allow_unsafe_keyboard_input_switch: bool,
    keyboard_clear_before_type: bool,
    keyboard_press_return: bool,
    keyboard_text: str,
    restore_keyboard: bool,
    require_overlay_page: bool,
    preflight_only: bool,
    settle_s: float,
    phone_model: str | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if phone_model:
        os.environ["GLASSBOX_PHONE_MODEL"] = phone_model
    os.environ.setdefault("GLASSBOX_AI_ARTIFACT_DIR", str(output_dir / "ai-runs"))
    if keyboard_switch_input_before_type and not allow_unsafe_keyboard_input_switch:
        raise ValueError(
            "keyboard input-source switching is disabled by default: the 2026-06-04 "
            "iPad mini 7 run showed Ctrl-Space can leave Settings and open Full "
            "Keyboard Access help. Pass --allow-unsafe-keyboard-input-switch only "
            "when intentionally reproducing that unsafe probe."
        )

    ocr = VisionOCR()
    overlay_points = {
        "item_numbers": item_numbers_point,
        "item_names": item_names_point,
        "numbered_grid": numbered_grid_point,
    }
    overlay_point = overlay_points[overlay_mode]
    mode_label = _MODE_LABELS[overlay_mode]
    result: dict[str, Any] = {
        "env": {
            "GLASSBOX_PHONE_MODEL": os.environ.get("GLASSBOX_PHONE_MODEL"),
            "GLASSBOX_AI_ARTIFACT_DIR": os.environ.get("GLASSBOX_AI_ARTIFACT_DIR"),
        },
        "overlay_mode": overlay_mode,
        "preflight_only": preflight_only,
        "keyboard_text": keyboard_text if keyboard_probe else None,
        "keyboard_focus_method": keyboard_focus_method if keyboard_probe else None,
        "keyboard_disable_overlay_before_focus": (
            keyboard_disable_overlay_before_focus if keyboard_probe else None
        ),
        "keyboard_switch_input_before_type": (
            keyboard_switch_input_before_type if keyboard_probe else None
        ),
        "keyboard_clear_before_type": keyboard_clear_before_type if keyboard_probe else None,
        "keyboard_press_return": keyboard_press_return if keyboard_probe else None,
        "wheel_second_ticks": wheel_second_ticks if wheel_probe else None,
        "points": {
            "none": list(none_point),
            "item_numbers": list(item_numbers_point),
            "item_names": list(item_names_point),
            "numbered_grid": list(numbered_grid_point),
            "scroll_start": list(scroll_start),
            "scroll_end": list(scroll_end),
            "wheel_focus": list(wheel_focus_point) if wheel_focus_point is not None else None,
            "wheel_focus_coordinate_space": "cropped_px" if wheel_focus_point is not None else None,
            "keyboard": list(keyboard_point),
        },
        "steps": [],
    }
    with open_phone(run_name="voice_control_overlay_ab") as phone:
        result["run_dir"] = str(phone.run_dir)
        preflight = _capture(
            phone,
            label="00_preflight",
            output_dir=output_dir,
            ocr=ocr,
            mapping_mode=overlay_mode,
        )
        result["steps"].append({"capture": preflight})
        result["preflight_page_id"] = preflight.get("page_id")
        result["preflight_ok"] = preflight.get("page_id") == "settings/Overlay"
        result["preflight_fka_help_overlay"] = _looks_like_fka_help_overlay(preflight)
        if not result["preflight_ok"] or result["preflight_fka_help_overlay"]:
            result["preflight_error"] = _preflight_error(preflight)
        if _should_stop_after_preflight(
            preflight_ok=bool(result["preflight_ok"]),
            preflight_fka_help_overlay=bool(result["preflight_fka_help_overlay"]),
            require_overlay_page=require_overlay_page,
            preflight_only=preflight_only,
        ):
            return result
        initial = phone.tap_xy(*overlay_point, coordinate_space="cropped_px")
        result["steps"].append(
            {
                "action": f"tap_{mode_label}_initial",
                "point": list(overlay_point),
                "outcome": _action_dict(initial),
            }
        )
        time.sleep(settle_s)
        result["steps"].append(
            {
                "capture": _capture(
                    phone,
                    label=f"01_{mode_label}_initial",
                    output_dir=output_dir,
                    ocr=ocr,
                    mapping_mode=overlay_mode,
                )
            }
        )

        none = phone.tap_xy(*none_point, coordinate_space="cropped_px")
        result["steps"].append(
            {"action": "tap_none", "point": list(none_point), "outcome": _action_dict(none)}
        )
        time.sleep(settle_s)
        result["steps"].append(
            {
                "capture": _capture(
                    phone,
                    label="02_overlay_none_off",
                    output_dir=output_dir,
                    ocr=ocr,
                    mapping_mode=overlay_mode,
                )
            }
        )

        selected = phone.tap_xy(*overlay_point, coordinate_space="cropped_px")
        result["steps"].append(
            {
                "action": f"tap_{mode_label}",
                "point": list(overlay_point),
                "outcome": _action_dict(selected),
            }
        )
        time.sleep(settle_s)
        result["steps"].append(
            {
                "capture": _capture(
                    phone,
                    label=f"03_{mode_label}_restored",
                    output_dir=output_dir,
                    ocr=ocr,
                    mapping_mode=overlay_mode,
                )
            }
        )
        if keyboard_probe:
            if keyboard_disable_overlay_before_focus:
                off = phone.tap_xy(*none_point, coordinate_space="cropped_px")
                result["steps"].append(
                    {
                        "action": "keyboard_disable_overlay_before_focus",
                        "point": list(none_point),
                        "outcome": _action_dict(off),
                    }
                )
                time.sleep(settle_s)
                result["steps"].append(
                    {
                        "capture": _capture(
                            phone,
                            label=f"04_{mode_label}_keyboard_overlay_off",
                            output_dir=output_dir,
                            ocr=ocr,
                            mapping_mode=overlay_mode,
                        )
                    }
                )
            _run_keyboard_focus(
                phone,
                result=result,
                method=keyboard_focus_method,
                keyboard_point=keyboard_point,
            )
            time.sleep(settle_s)
            result["steps"].append(
                {
                    "capture": _capture(
                        phone,
                        label=f"04_{mode_label}_keyboard_focus",
                        output_dir=output_dir,
                        ocr=ocr,
                        mapping_mode=overlay_mode,
                    )
                }
            )
            if keyboard_clear_before_type:
                _run_key_sequence(
                    phone,
                    result=result,
                    key_sequence=(
                        ("keyboard_pretype_select_all", _MOD_META_LEFT, _KEY_A),
                        ("keyboard_pretype_delete", 0, _KEY_DELETE),
                    ),
                    settle_s=settle_s,
                )
                result["steps"].append(
                    {
                        "capture": _capture(
                            phone,
                            label=f"05_{mode_label}_after_keyboard_clear",
                            output_dir=output_dir,
                            ocr=ocr,
                            mapping_mode=overlay_mode,
                        )
                    }
                )
            if keyboard_switch_input_before_type:
                key = phone.key(_MOD_CTRL, _KEY_SPACE)
                result["steps"].append(
                    {
                        "action": "keyboard_switch_input_before_type",
                        "modifier": _MOD_CTRL,
                        "keycode": _KEY_SPACE,
                        "outcome": _action_dict(key),
                    }
                )
                time.sleep(settle_s)
                result["steps"].append(
                    {
                        "capture": _capture(
                            phone,
                            label=f"05_{mode_label}_after_keyboard_input_switch",
                            output_dir=output_dir,
                            ocr=ocr,
                            mapping_mode=overlay_mode,
                        )
                    }
                )
            typed = phone.type_text(keyboard_text, verify=False)
            result["steps"].append(
                {
                    "action": "type_keyboard_text",
                    "text": keyboard_text,
                    "outcome": _action_dict(typed),
                }
            )
            time.sleep(settle_s)
            result["steps"].append(
                {
                    "capture": _capture(
                        phone,
                        label=f"05_{mode_label}_after_keyboard_type",
                        output_dir=output_dir,
                        ocr=ocr,
                        mapping_mode=overlay_mode,
                    )
                }
            )
            if keyboard_press_return:
                key = phone.key(0, _KEY_RETURN)
                result["steps"].append(
                    {
                        "action": "keyboard_return_after_type",
                        "modifier": 0,
                        "keycode": _KEY_RETURN,
                        "outcome": _action_dict(key),
                    }
                )
                time.sleep(settle_s)
                result["steps"].append(
                    {
                        "capture": _capture(
                            phone,
                            label=f"06_{mode_label}_after_keyboard_return",
                            output_dir=output_dir,
                            ocr=ocr,
                            mapping_mode=overlay_mode,
                        )
                    }
                )
            if restore_keyboard:
                _run_key_sequence(
                    phone,
                    result=result,
                    key_sequence=(
                        ("keyboard_select_all", _MOD_META_LEFT, _KEY_A),
                        ("keyboard_delete", 0, _KEY_DELETE),
                        ("keyboard_escape", 0, _KEY_ESC),
                    ),
                    settle_s=settle_s,
                )
                result["steps"].append(
                    {
                        "capture": _capture(
                            phone,
                            label=f"06_{mode_label}_after_keyboard_restore",
                            output_dir=output_dir,
                            ocr=ocr,
                            mapping_mode=overlay_mode,
                        )
                    }
                )
        if scroll_probe:
            for index in range(scroll_repeat):
                swipe = phone.swipe_xy(
                    *scroll_start,
                    *scroll_end,
                    coordinate_space="cropped_px",
                    steps=40,
                    end_hold_ms=300,
                )
                result["steps"].append(
                    {
                        "action": "swipe_scroll_probe",
                        "index": index,
                        "from": list(scroll_start),
                        "to": list(scroll_end),
                        "outcome": _action_dict(swipe),
                    }
                )
                time.sleep(settle_s)
            result["steps"].append(
                {
                    "capture": _capture(
                        phone,
                        label=f"04_{mode_label}_after_scroll",
                        output_dir=output_dir,
                        ocr=ocr,
                        mapping_mode=overlay_mode,
                    )
                }
            )
            if restore_scroll:
                for index in range(scroll_repeat):
                    restore = phone.swipe_xy(
                        *scroll_end,
                        *scroll_start,
                        coordinate_space="cropped_px",
                        steps=40,
                        end_hold_ms=300,
                    )
                    result["steps"].append(
                        {
                            "action": "swipe_restore_scroll",
                            "index": index,
                            "from": list(scroll_end),
                            "to": list(scroll_start),
                            "outcome": _action_dict(restore),
                        }
                    )
                    time.sleep(settle_s)
        if wheel_probe:
            wheel_kwargs: dict[str, Any] = {"focus_click": wheel_focus_click}
            if wheel_focus_point is not None:
                wheel_kwargs["focus_x"] = wheel_focus_point[0]
                wheel_kwargs["focus_y"] = wheel_focus_point[1]
                wheel_kwargs["coordinate_space"] = "cropped_px"
            for index in range(wheel_repeat):
                wheel = phone.scroll_wheel(wheel_ticks, **wheel_kwargs)
                result["steps"].append(
                    {
                        "action": "wheel_scroll_probe",
                        "index": index,
                        "ticks": wheel_ticks,
                        "focus": list(wheel_focus_point) if wheel_focus_point is not None else None,
                        "focus_click": wheel_focus_click,
                        "outcome": _action_dict(wheel),
                    }
                )
                time.sleep(settle_s)
            result["steps"].append(
                {
                    "capture": _capture(
                        phone,
                        label=f"04_{mode_label}_after_wheel",
                        output_dir=output_dir,
                        ocr=ocr,
                        mapping_mode=overlay_mode,
                    )
                }
            )
            if wheel_second_ticks is not None:
                for index in range(wheel_repeat):
                    wheel = phone.scroll_wheel(wheel_second_ticks, **wheel_kwargs)
                    result["steps"].append(
                        {
                            "action": "wheel_second_scroll_probe",
                            "index": index,
                            "ticks": wheel_second_ticks,
                            "focus": list(wheel_focus_point) if wheel_focus_point is not None else None,
                            "focus_click": wheel_focus_click,
                            "outcome": _action_dict(wheel),
                        }
                    )
                    time.sleep(settle_s)
                result["steps"].append(
                    {
                        "capture": _capture(
                            phone,
                            label=f"05_{mode_label}_after_wheel_second",
                            output_dir=output_dir,
                            ocr=ocr,
                            mapping_mode=overlay_mode,
                        )
                    }
                )
            if restore_wheel:
                net_ticks = wheel_ticks * wheel_repeat
                if wheel_second_ticks is not None:
                    net_ticks += wheel_second_ticks * wheel_repeat
                restore_ticks = -net_ticks
                if restore_ticks:
                    wheel = phone.scroll_wheel(restore_ticks, **wheel_kwargs)
                    result["steps"].append(
                        {
                            "action": "wheel_restore_scroll",
                            "index": 0,
                            "ticks": restore_ticks,
                            "focus": list(wheel_focus_point) if wheel_focus_point is not None else None,
                            "focus_click": wheel_focus_click,
                            "outcome": _action_dict(wheel),
                        }
                    )
                    time.sleep(settle_s)
        if final_overlay_mode is not None:
            final_point = overlay_points[final_overlay_mode]
            final = phone.tap_xy(*final_point, coordinate_space="cropped_px")
            result["steps"].append(
                {
                    "action": f"restore_{_MODE_LABELS[final_overlay_mode]}",
                    "point": list(final_point),
                    "outcome": _action_dict(final),
                }
            )
    return result


def analyze_probe_result(result: dict[str, Any]) -> dict[str, Any]:
    """Summarize a probe JSON without needing the rig.

    The raw run keeps every action/capture for inspection. This summary provides
    the stable facts docs and follow-up gates usually need: selected-mode marker
    counts, whether the off state is clean, action transport health, and whether
    common mapped labels changed overlay ids across a scroll sample.
    """

    overlay_mode = str(result.get("overlay_mode") or "item_numbers")
    captures = [step["capture"] for step in result.get("steps", []) if "capture" in step]
    actions = [step for step in result.get("steps", []) if "action" in step]
    capture_summaries = [_capture_summary(capture, overlay_mode=overlay_mode) for capture in captures]
    off_capture = _first_capture(captures, "02_overlay_none_off")
    restored_capture = _first_capture_with(captures, "_restored")
    after_scroll_capture = _first_capture_with(captures, "_after_scroll")
    after_wheel_capture = _first_capture_with(captures, "_after_wheel")
    after_wheel_second_capture = _first_capture_with(captures, "_after_wheel_second")
    keyboard_overlay_off_capture = _first_capture_with(captures, "_keyboard_overlay_off")
    after_keyboard_focus_capture = _first_capture_with(captures, "_keyboard_focus")
    after_keyboard_input_switch_capture = _first_capture_with(
        captures,
        "_after_keyboard_input_switch",
    )
    after_keyboard_capture = _first_capture_with(captures, "_after_keyboard_type")
    after_keyboard_return_capture = _first_capture_with(captures, "_after_keyboard_return")
    mapping_delta = _mapping_delta(restored_capture, after_scroll_capture)
    wheel_delta = _visible_text_delta(restored_capture, after_wheel_capture)
    wheel_semantic_delta = _visible_text_delta(
        restored_capture,
        after_wheel_capture,
        semantic_only=True,
    )
    wheel_frame_diff = _frame_diff_summary(restored_capture, after_wheel_capture)
    wheel_second_before = after_wheel_capture or restored_capture
    wheel_second_delta = _visible_text_delta(wheel_second_before, after_wheel_second_capture)
    wheel_second_semantic_delta = _visible_text_delta(
        wheel_second_before,
        after_wheel_second_capture,
        semantic_only=True,
    )
    wheel_second_frame_diff = _frame_diff_summary(
        wheel_second_before,
        after_wheel_second_capture,
    )
    keyboard_focus_delta = _visible_text_delta(
        restored_capture,
        after_keyboard_focus_capture,
        semantic_only=True,
    )
    keyboard_input_switch_delta = _visible_text_delta(
        after_keyboard_focus_capture,
        after_keyboard_input_switch_capture,
        semantic_only=True,
    )
    fka_help_capture_labels = [
        str(capture.get("label"))
        for capture in captures
        if _looks_like_fka_help_overlay(capture)
    ]
    preflight_capture = _first_capture(captures, "00_preflight")
    preflight_fka_help_overlay = _looks_like_fka_help_overlay(preflight_capture) or bool(
        result.get("preflight_fka_help_overlay")
    )
    preflight_blocker = _preflight_blocker(
        preflight_ok=result.get("preflight_ok"),
        preflight_fka_help_overlay=preflight_fka_help_overlay,
        preflight_page_id=result.get("preflight_page_id"),
    )
    keyboard_text = str(result.get("keyboard_text") or "")
    return {
        "overlay_mode": overlay_mode,
        "preflight_only": result.get("preflight_only"),
        "preflight_ok": result.get("preflight_ok"),
        "preflight_page_id": result.get("preflight_page_id"),
        "preflight_error": result.get("preflight_error"),
        "preflight_fka_help_overlay": preflight_fka_help_overlay,
        "preflight_ready_for_probe": (
            None if result.get("preflight_ok") is None else preflight_blocker is None
        ),
        "preflight_blocker": preflight_blocker,
        "keyboard_focus_method": result.get("keyboard_focus_method"),
        "keyboard_disable_overlay_before_focus": result.get(
            "keyboard_disable_overlay_before_focus"
        ),
        "keyboard_switch_input_before_type": result.get("keyboard_switch_input_before_type"),
        "keyboard_clear_before_type": result.get("keyboard_clear_before_type"),
        "keyboard_press_return": result.get("keyboard_press_return"),
        "wheel_second_ticks": result.get("wheel_second_ticks"),
        "captures": capture_summaries,
        "fka_help_overlay_detected": bool(fka_help_capture_labels),
        "fka_help_overlay_capture_labels": fka_help_capture_labels,
        "action_count": len(actions),
        "preflight_stopped_before_actions": (
            result.get("preflight_ok") is not None
            and len(actions) == 0
            and bool(captures)
        ),
        "actions_transport_ok": all(
            bool(step.get("outcome", {}).get("transport_ok", step.get("outcome", {}).get("ok")))
            for step in actions
        ),
        "overlay_off_selected_count": _mode_count(off_capture, overlay_mode),
        "overlay_off_all_zero": (
            off_capture is not None
            and all(int(value) == 0 for value in off_capture.get("mode_counts", {}).values())
        ),
        "restored_selected_count": _mode_count(restored_capture, overlay_mode),
        "mapping_common_count": len(mapping_delta["common"]),
        "mapping_stable_count": len(mapping_delta["stable"]),
        "mapping_changed": mapping_delta["changed"],
        "wheel_visible_text_changed": wheel_delta["changed"],
        "wheel_texts_added": wheel_delta["added"],
        "wheel_texts_removed": wheel_delta["removed"],
        "wheel_semantic_text_changed": wheel_semantic_delta["changed"],
        "wheel_semantic_texts_added": wheel_semantic_delta["added"],
        "wheel_semantic_texts_removed": wheel_semantic_delta["removed"],
        "wheel_frame_diff": wheel_frame_diff,
        "wheel_scroll_evidence": _wheel_scroll_evidence(
            before_wheel_capture=restored_capture,
            after_wheel_capture=after_wheel_capture,
            raw_delta=wheel_delta,
            semantic_delta=wheel_semantic_delta,
            frame_diff=wheel_frame_diff,
        ),
        "wheel_second_visible_text_changed": wheel_second_delta["changed"],
        "wheel_second_texts_added": wheel_second_delta["added"],
        "wheel_second_texts_removed": wheel_second_delta["removed"],
        "wheel_second_semantic_text_changed": wheel_second_semantic_delta["changed"],
        "wheel_second_semantic_texts_added": wheel_second_semantic_delta["added"],
        "wheel_second_semantic_texts_removed": wheel_second_semantic_delta["removed"],
        "wheel_second_frame_diff": wheel_second_frame_diff,
        "wheel_second_scroll_evidence": _wheel_scroll_evidence(
            before_wheel_capture=wheel_second_before,
            after_wheel_capture=after_wheel_second_capture,
            raw_delta=wheel_second_delta,
            semantic_delta=wheel_second_semantic_delta,
            frame_diff=wheel_second_frame_diff,
        ),
        "keyboard_focus_visible_text_changed": keyboard_focus_delta["changed"],
        "keyboard_focus_texts_added": keyboard_focus_delta["added"],
        "keyboard_focus_texts_removed": keyboard_focus_delta["removed"],
        "keyboard_overlay_off_selected_count": _mode_count(
            keyboard_overlay_off_capture,
            overlay_mode,
        ),
        "keyboard_overlay_off_all_zero": (
            keyboard_overlay_off_capture is not None
            and all(
                int(value) == 0
                for value in keyboard_overlay_off_capture.get("mode_counts", {}).values()
            )
        ),
        "keyboard_overlay_off_page_id": (
            keyboard_overlay_off_capture.get("page_id")
            if keyboard_overlay_off_capture is not None
            else None
        ),
        "keyboard_focus_capture_page_id": (
            after_keyboard_focus_capture.get("page_id")
            if after_keyboard_focus_capture is not None
            else None
        ),
        "keyboard_focus_page_changed": (
            restored_capture is not None
            and after_keyboard_focus_capture is not None
            and restored_capture.get("page_id") != after_keyboard_focus_capture.get("page_id")
        ),
        "keyboard_input_switch_visible_text_changed": keyboard_input_switch_delta["changed"],
        "keyboard_input_switch_texts_added": keyboard_input_switch_delta["added"],
        "keyboard_input_switch_texts_removed": keyboard_input_switch_delta["removed"],
        "keyboard_input_switch_capture_page_id": (
            after_keyboard_input_switch_capture.get("page_id")
            if after_keyboard_input_switch_capture is not None
            else None
        ),
        "keyboard_input_switch_opened_fka_help": _looks_like_fka_help_overlay(
            after_keyboard_input_switch_capture,
        ),
        "keyboard_text": keyboard_text,
        "keyboard_text_visible": _keyboard_text_visible(
            after_keyboard_capture,
            keyboard_text,
        ),
        "keyboard_text_visible_after_return": _keyboard_text_visible(
            after_keyboard_return_capture,
            keyboard_text,
        ),
        "keyboard_capture_page_id": (
            after_keyboard_capture.get("page_id") if after_keyboard_capture is not None else None
        ),
        "keyboard_return_capture_page_id": (
            after_keyboard_return_capture.get("page_id")
            if after_keyboard_return_capture is not None
            else None
        ),
    }


def _capture_summary(capture: dict[str, Any], *, overlay_mode: str) -> dict[str, Any]:
    mapping = capture.get("overlay_hint_mapping", {})
    mode_counts = capture.get("mode_counts", {})
    return {
        "label": capture.get("label"),
        "page_id": capture.get("page_id"),
        "ocr_count": capture.get("ocr_count"),
        "fka_help_overlay": _looks_like_fka_help_overlay(capture),
        "selected_mode_count": int(mode_counts.get(overlay_mode, 0) or 0),
        "other_mode_counts": {
            mode: int(count)
            for mode, count in mode_counts.items()
            if mode != overlay_mode and int(count or 0) > 0
        },
        "scene_marker_count": mapping.get("scene_marker_count"),
        "mapped_count": len(mapping.get("mapped", [])),
    }


def _first_capture(captures: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    return next((capture for capture in captures if capture.get("label") == label), None)


def _first_capture_with(captures: list[dict[str, Any]], suffix: str) -> dict[str, Any] | None:
    return next((capture for capture in captures if str(capture.get("label", "")).endswith(suffix)), None)


def _mode_count(capture: dict[str, Any] | None, mode: str) -> int | None:
    if capture is None:
        return None
    return int(capture.get("mode_counts", {}).get(mode, 0) or 0)


def _mapping_delta(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]] | list[str]]:
    before_ids = _unique_mapped_ids_by_text(before)
    after_ids = _unique_mapped_ids_by_text(after)
    common = sorted(set(before_ids) & set(after_ids))
    stable: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for text in common:
        row = {
            "text": text,
            "before": before_ids[text],
            "after": after_ids[text],
        }
        if before_ids[text] == after_ids[text]:
            stable.append(row)
        else:
            changed.append(row)
    return {"common": common, "stable": stable, "changed": changed}


def _unique_mapped_ids_by_text(capture: dict[str, Any] | None) -> dict[str, str]:
    if capture is None:
        return {}
    by_text: dict[str, list[str]] = {}
    for item in capture.get("overlay_hint_mapping", {}).get("mapped", []):
        text = str(item.get("text") or "").strip()
        accessibility_id = str(item.get("accessibility_id") or "").strip()
        if not text or not accessibility_id:
            continue
        by_text.setdefault(text, []).append(accessibility_id)
    return {text: ids[0] for text, ids in by_text.items() if len(ids) == 1}


def _visible_text_delta(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    semantic_only: bool = False,
) -> dict[str, Any]:
    if before is None or after is None:
        return {"changed": None, "added": [], "removed": []}
    before_texts = set(_visible_texts(before, semantic_only=semantic_only))
    after_texts = set(_visible_texts(after, semantic_only=semantic_only))
    added = sorted(after_texts - before_texts)
    removed = sorted(before_texts - after_texts)
    return {
        "changed": bool(added or removed),
        "added": added[:24],
        "removed": removed[:24],
    }


def _visible_texts(capture: dict[str, Any], *, semantic_only: bool = False) -> list[str]:
    values = capture.get("visible_texts", capture.get("visible_texts_head", []))
    texts = [str(value).strip() for value in values if str(value).strip()]
    if not semantic_only:
        return texts
    return [text for text in texts if _is_semantic_wheel_text(text)]


def _looks_like_fka_help_overlay(capture: dict[str, Any] | None) -> bool:
    if capture is None:
        return False
    texts = {text.lower() for text in _visible_texts(capture)}
    if "basic" not in texts or "help" not in texts:
        return False
    section_hits = sum(section in texts for section in ("movement", "interaction", "device"))
    command_hits = sum(
        command in texts
        for command in (
            "move forwards",
            "move backwards",
            "activate",
            "home",
            "find",
        )
    )
    return section_hits >= 2 and command_hits >= 2


def _preflight_error(preflight: dict[str, Any]) -> str:
    if _looks_like_fka_help_overlay(preflight):
        return (
            "voice_control_overlay_probe requires the device to start on "
            "settings/Overlay; got Full Keyboard Access help overlay. Clear the "
            "FKA help overlay before running on-rig probes."
        )
    return (
        "voice_control_overlay_probe requires the device to start on "
        f"settings/Overlay; got {preflight.get('page_id')!r}"
    )


def _preflight_blocker(
    *,
    preflight_ok: Any,
    preflight_fka_help_overlay: bool,
    preflight_page_id: Any,
) -> str | None:
    if preflight_ok is None:
        return None
    if preflight_ok:
        return None
    if preflight_fka_help_overlay:
        return "fka_help_overlay"
    return f"wrong_page:{preflight_page_id!r}"


def _should_stop_after_preflight(
    *,
    preflight_ok: bool,
    preflight_fka_help_overlay: bool,
    require_overlay_page: bool,
    preflight_only: bool,
) -> bool:
    if preflight_only:
        return True
    if preflight_fka_help_overlay:
        return True
    return require_overlay_page and not preflight_ok


def _is_semantic_wheel_text(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if any(token in normalized for token in ("PM", "AM", "Thu", "Jun", "100%")):
        return False
    digits = "".join(ch for ch in normalized if ch.isdigit())
    letters = "".join(ch for ch in normalized if ch.isalpha())
    if digits and not letters:
        return False
    return not (len(normalized) <= 2 and not letters)


def _frame_diff_summary(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if before is None or after is None:
        return None
    before_path = before.get("screenshot")
    after_path = after.get("screenshot")
    if not before_path or not after_path:
        return None
    before_img = cv2.imread(str(before_path))
    after_img = cv2.imread(str(after_path))
    if before_img is None or after_img is None:
        return None
    if before_img.shape != after_img.shape:
        height = min(before_img.shape[0], after_img.shape[0])
        width = min(before_img.shape[1], after_img.shape[1])
        before_img = before_img[:height, :width]
        after_img = after_img[:height, :width]
    diff = cv2.absdiff(before_img, after_img)
    mask = (diff > 10).any(axis=2)
    ys, xs = mask.nonzero()
    return {
        "diff_ratio": round(float(mask.mean()), 6),
        "mean_abs": round(float(diff.mean()), 6),
        "changed_bbox": (
            [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
            if xs.size
            else None
        ),
    }


def _wheel_scroll_evidence(
    *,
    before_wheel_capture: dict[str, Any] | None,
    after_wheel_capture: dict[str, Any] | None,
    raw_delta: dict[str, Any],
    semantic_delta: dict[str, Any],
    frame_diff: dict[str, Any] | None,
) -> str:
    if after_wheel_capture is None:
        return "not_run"
    if (
        before_wheel_capture is not None
        and before_wheel_capture.get("page_id") != after_wheel_capture.get("page_id")
    ):
        return "page_changed_after_focus_or_wheel"
    diff_ratio = float(frame_diff.get("diff_ratio", 0.0)) if frame_diff else None
    if diff_ratio is not None and diff_ratio >= 0.02:
        return "frame_changed"
    if semantic_delta["changed"]:
        return "small_frame_change_with_semantic_or_ocr_delta"
    if raw_delta["changed"]:
        return "ocr_or_status_noise_only"
    return "no_visible_change"


def _keyboard_text_visible(capture: dict[str, Any] | None, needle: str) -> bool | None:
    needle = needle.strip().lower()
    if capture is None or not needle:
        return None
    return any(needle in text.lower() for text in _visible_texts(capture))


def _print_summary(result: dict[str, Any], json_path: Path) -> None:
    for step in result["steps"]:
        if "capture" in step:
            capture = step["capture"]
            print(
                capture["label"],
                "page=",
                capture["page_id"],
                "ocr=",
                capture["ocr_count"],
                "counts=",
                capture["mode_counts"],
                "shot=",
                capture["screenshot"],
                "scene_markers=",
                capture["overlay_hint_mapping"]["scene_marker_count"],
                "mapped=",
                len(capture["overlay_hint_mapping"]["mapped"]),
            )
        else:
            point = step.get("point")
            if point is None and step.get("from") is not None:
                point = f"{step.get('from')}->{step.get('to')}"
            if point is None and step.get("ticks") is not None:
                point = f"wheel:{step.get('ticks')}"
            print(step["action"], point, step["outcome"])
    analysis = result.get("analysis", {})
    if analysis:
        print("analysis=", json.dumps(analysis, ensure_ascii=False, sort_keys=True))
    print("json=", json_path)
    print("run_dir=", result["run_dir"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/glassbox-vc-ab"))
    parser.add_argument("--phone-model", default=None)
    parser.add_argument("--overlay-mode", choices=_MODES, default="item_numbers")
    parser.add_argument("--none-point", type=_parse_point, default=(299, 116))
    parser.add_argument("--item-numbers-point", type=_parse_point, default=(327, 162))
    parser.add_argument("--item-names-point", type=_parse_point, default=(320, 208))
    parser.add_argument("--numbered-grid-point", type=_parse_point, default=(331, 253))
    parser.add_argument("--final-overlay-mode", choices=_MODES, default="item_numbers")
    parser.add_argument("--no-final-overlay-restore", action="store_true")
    parser.add_argument("--scroll-probe", action="store_true")
    parser.add_argument("--scroll-start", type=_parse_point, default=(135, 930))
    parser.add_argument("--scroll-end", type=_parse_point, default=(135, 180))
    parser.add_argument("--scroll-repeat", type=int, default=3)
    parser.add_argument("--no-restore-scroll", action="store_true")
    parser.add_argument("--wheel-probe", action="store_true")
    parser.add_argument("--wheel-ticks", type=int, default=90)
    parser.add_argument("--wheel-second-ticks", type=int, default=None)
    parser.add_argument("--wheel-repeat", type=int, default=1)
    parser.add_argument("--wheel-focus-point", type=_parse_point, default=(135, 930))
    parser.add_argument("--wheel-focus-click", action="store_true")
    parser.add_argument("--no-wheel-focus", action="store_true")
    parser.add_argument("--no-restore-wheel", action="store_true")
    parser.add_argument("--keyboard-probe", action="store_true")
    parser.add_argument("--keyboard-point", type=_parse_point, default=(44, 97))
    parser.add_argument(
        "--keyboard-focus-method",
        choices=("tap", "double_tap", "cmd_f", "tap_then_cmd_f"),
        default="tap",
    )
    parser.add_argument("--keyboard-disable-overlay-before-focus", action="store_true")
    parser.add_argument("--keyboard-switch-input-before-type", action="store_true")
    parser.add_argument(
        "--allow-unsafe-keyboard-input-switch",
        action="store_true",
        help=(
            "Allow --keyboard-switch-input-before-type. This is unsafe on the "
            "iPad mini 7 rig: Ctrl-Space can leave Settings and open Full Keyboard "
            "Access help."
        ),
    )
    parser.add_argument("--keyboard-clear-before-type", action="store_true")
    parser.add_argument("--keyboard-press-return", action="store_true")
    parser.add_argument("--keyboard-text", default="gbvckbd")
    parser.add_argument("--no-restore-keyboard", action="store_true")
    parser.add_argument("--no-require-overlay-page", action="store_true")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Capture and analyze only 00_preflight, then exit before any tap/keyboard/wheel action.",
    )
    parser.add_argument("--settle-s", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.keyboard_switch_input_before_type and not args.allow_unsafe_keyboard_input_switch:
        parser.error(
            "--keyboard-switch-input-before-type is unsafe on the iPad mini 7 rig; "
            "pass --allow-unsafe-keyboard-input-switch to intentionally reproduce it"
        )

    result = run_probe(
        output_dir=args.output_dir,
        overlay_mode=args.overlay_mode,
        none_point=args.none_point,
        item_numbers_point=args.item_numbers_point,
        item_names_point=args.item_names_point,
        numbered_grid_point=args.numbered_grid_point,
        final_overlay_mode=None if args.no_final_overlay_restore else args.final_overlay_mode,
        scroll_probe=args.scroll_probe,
        scroll_start=args.scroll_start,
        scroll_end=args.scroll_end,
        scroll_repeat=max(1, args.scroll_repeat),
        restore_scroll=not args.no_restore_scroll,
        wheel_probe=args.wheel_probe,
        wheel_ticks=args.wheel_ticks,
        wheel_second_ticks=args.wheel_second_ticks,
        wheel_repeat=max(1, args.wheel_repeat),
        wheel_focus_point=None if args.no_wheel_focus else args.wheel_focus_point,
        wheel_focus_click=args.wheel_focus_click,
        restore_wheel=not args.no_restore_wheel,
        keyboard_probe=args.keyboard_probe,
        keyboard_point=args.keyboard_point,
        keyboard_focus_method=args.keyboard_focus_method,
        keyboard_disable_overlay_before_focus=args.keyboard_disable_overlay_before_focus,
        keyboard_switch_input_before_type=args.keyboard_switch_input_before_type,
        allow_unsafe_keyboard_input_switch=args.allow_unsafe_keyboard_input_switch,
        keyboard_clear_before_type=args.keyboard_clear_before_type,
        keyboard_press_return=args.keyboard_press_return,
        keyboard_text=args.keyboard_text,
        restore_keyboard=not args.no_restore_keyboard,
        require_overlay_page=not args.no_require_overlay_page,
        preflight_only=args.preflight_only,
        settle_s=args.settle_s,
        phone_model=args.phone_model,
    )
    result["analysis"] = analyze_probe_result(result)
    json_path = args.output_dir / "voice_control_overlay_ab.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_summary(result, json_path)
    return 2 if result.get("preflight_ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
