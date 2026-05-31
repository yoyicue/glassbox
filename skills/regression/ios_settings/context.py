"""Per-phone runtime state for the iOS Settings crawler.

The crawler is an app-layer skill, so its bookkeeping must live here instead
of being stamped onto ``Phone`` as private attributes.
"""

from __future__ import annotations

import weakref
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SettingsRuntimeState:
    last_action_verdict: Any | None = None
    search_unavailable: bool = False
    search_input_toggled: bool = False
    last_row_tap: dict[str, Any] | None = None
    scene_classifications: list[dict[str, Any]] = field(default_factory=list)
    last_vlm_point_grounding: dict[str, Any] | None = None
    vlm_point_failure_reason: str | None = None
    vlm_point_grounding_history: list[dict[str, Any]] = field(default_factory=list)


_STATE_BY_ID: dict[int, SettingsRuntimeState] = {}


def state_for(phone: object) -> SettingsRuntimeState:
    key = id(phone)
    state = _STATE_BY_ID.get(key)
    if state is None:
        state = SettingsRuntimeState()
        _STATE_BY_ID[key] = state
        with suppress(TypeError):
            weakref.finalize(phone, _STATE_BY_ID.pop, key, None)
    return state


def reset_for(phone: object) -> None:
    _STATE_BY_ID.pop(id(phone), None)


def record_action_verdict(phone: object, verdict: Any) -> None:
    state_for(phone).last_action_verdict = verdict


def last_action_verdict(phone: object) -> Any | None:
    return state_for(phone).last_action_verdict


def set_search_unavailable(phone: object, value: bool = True) -> None:
    state_for(phone).search_unavailable = bool(value)


def search_unavailable(phone: object) -> bool:
    return state_for(phone).search_unavailable


def set_search_input_toggled(phone: object, value: bool = True) -> None:
    state_for(phone).search_input_toggled = bool(value)


def search_input_toggled(phone: object) -> bool:
    return state_for(phone).search_input_toggled


def record_row_tap(phone: object, payload: dict[str, Any]) -> None:
    state_for(phone).last_row_tap = payload


def last_row_tap(phone: object) -> dict[str, Any] | None:
    return state_for(phone).last_row_tap


def clear_row_tap(phone: object) -> None:
    state_for(phone).last_row_tap = None


def append_scene_classification(phone: object, record: dict[str, Any]) -> None:
    state_for(phone).scene_classifications.append(record)


def scene_classifications(phone: object) -> list[dict[str, Any]]:
    return state_for(phone).scene_classifications


def record_vlm_point_grounding(
    phone: object,
    payload: dict[str, Any],
    *,
    reason: str | None,
) -> None:
    state = state_for(phone)
    state.last_vlm_point_grounding = payload
    state.vlm_point_failure_reason = reason
    state.vlm_point_grounding_history.append(payload)
