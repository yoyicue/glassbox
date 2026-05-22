"""Static seeds for actuation and recovery facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_RECOVERY_SEED = {
    "schema_version": 1,
    "blocking_overlays": {
        "ios_system_permission_dialog": {
            "kind": "permission",
            "profile_actuability": "not_applicable",
            "hint": "system permission dialog blocks the target; route through recovery/approval, not ActuationProfile",
        },
        "ios_lock_screen": {
            "kind": "lock_screen",
            "profile_actuability": "not_applicable",
            "hint": "device lock screen blocks app control; recover foreground/readiness before action retry",
        },
        "ios_power_off_screen": {
            "kind": "system_modal",
            "profile_actuability": "not_applicable",
            "hint": "power-off screen blocks app control; recovery must dismiss or abort",
        },
        "app_crashed_or_terminated": {
            "kind": "app_state",
            "profile_actuability": "not_applicable",
            "hint": "app crashed or terminated; relaunch/recover before attributing control reliability",
        },
    },
}


def load_json_seed(path: str | Path | None, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if path is None:
        return dict(default or {})
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(default or {})
    if not isinstance(payload, dict):
        return dict(default or {})
    return payload


def recovery_hint(seed: dict[str, Any], state: str | None) -> dict[str, Any] | None:
    if not state:
        return None
    overlays = seed.get("blocking_overlays") if isinstance(seed, dict) else None
    if not isinstance(overlays, dict):
        return None
    hint = overlays.get(state)
    return dict(hint) if isinstance(hint, dict) else None
