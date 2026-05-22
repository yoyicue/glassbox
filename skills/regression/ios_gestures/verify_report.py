"""Verifier for the iOS gesture/AssistiveTouch v2 regression report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CORE_REQUIRED_PROBES = (
    "home_screen_ready",
    "springboard_swipe_left",
    "springboard_swipe_right",
)
ASSISTIVE_TOUCH_REQUIRED_PROBES = (
    "assistive_touch_precise_tap",
    "assistive_touch_level1_menu_items",
    "assistive_touch_level2_device_menu",
    "assistive_touch_level3_more_menu",
    "assistive_touch_unsafe_guard",
    "assistive_touch_dismiss",
)
REQUIRED_PROBES = CORE_REQUIRED_PROBES + ASSISTIVE_TOUCH_REQUIRED_PROBES


def validate_report(payload: dict[str, Any], *, expected_run_id: str | None = None) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("runner") != "ios_gestures.run_full_v2":
        errors.append("runner must be ios_gestures.run_full_v2")
    run_id = payload.get("run_id")
    if not run_id:
        errors.append("run_id is required")
    if expected_run_id is not None and run_id != expected_run_id:
        errors.append(f"run_id mismatch: expected {expected_run_id}, got {run_id}")
    if payload.get("status") != "passed":
        errors.append(f"status must be passed, got {payload.get('status')!r}")

    probes = payload.get("probes")
    if not isinstance(probes, list) or not probes:
        errors.append("probes must be a non-empty list")
        return errors
    by_name = {probe.get("name"): probe for probe in probes if isinstance(probe, dict)}
    config = payload.get("config") or {}
    assistive_touch_available = config.get("assistive_touch_available", True) is not False
    required_probes = CORE_REQUIRED_PROBES + (
        ASSISTIVE_TOUCH_REQUIRED_PROBES if assistive_touch_available else ()
    )
    for name in required_probes:
        probe = by_name.get(name)
        if probe is None:
            errors.append(f"missing required probe: {name}")
            continue
        if probe.get("status") != "passed":
            errors.append(f"required probe {name} did not pass: {probe.get('reason') or probe.get('status')}")
        artifacts = probe.get("artifacts") or {}
        if not artifacts:
            errors.append(f"required probe {name} has no artifacts")
    if not assistive_touch_available:
        for name in ASSISTIVE_TOUCH_REQUIRED_PROBES:
            probe = by_name.get(name)
            if probe is None:
                errors.append(f"missing skipped AssistiveTouch probe: {name}")
                continue
            if probe.get("status") != "skipped":
                errors.append(f"AssistiveTouch probe {name} must be skipped when unavailable")
            artifacts = probe.get("artifacts") or {}
            if not artifacts:
                errors.append(f"skipped AssistiveTouch probe {name} has no artifacts")

    metrics = payload.get("metrics") or {}
    if metrics.get("failed", 0):
        errors.append(f"metrics.failed must be 0, got {metrics.get('failed')}")
    if metrics.get("passed", 0) < len(required_probes):
        errors.append("metrics.passed is lower than required probe count")
    safe_clicks = metrics.get("assistive_touch_safe_clicks")
    if not isinstance(safe_clicks, dict):
        errors.append("metrics.assistive_touch_safe_clicks is required")
    elif assistive_touch_available and safe_clicks.get("effect_observed") != safe_clicks.get("total"):
        errors.append("metrics.assistive_touch_safe_clicks must have all effects observed")
    path_navigation = metrics.get("assistive_touch_path_navigation")
    if not isinstance(path_navigation, dict):
        errors.append("metrics.assistive_touch_path_navigation is required")
    elif assistive_touch_available and path_navigation.get("succeeded") != path_navigation.get("total"):
        errors.append("metrics.assistive_touch_path_navigation must have all hops succeeded")
    unsafe = metrics.get("assistive_touch_unsafe")
    if not isinstance(unsafe, dict):
        errors.append("metrics.assistive_touch_unsafe is required")
    elif unsafe.get("physical_taps") != 0:
        errors.append(f"unsafe AssistiveTouch physical taps must be 0, got {unsafe.get('physical_taps')}")
    for key in ("recovery", "actions", "artifacts"):
        if not isinstance(metrics.get(key), dict):
            errors.append(f"metrics.{key} is required")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary is required")
    elif "safe_clicks" not in summary or "unsafe_physical_taps" not in summary:
        errors.append("summary must include safe_clicks and unsafe_physical_taps")
    if not config.get("unsafe_policy"):
        errors.append("config.unsafe_policy is required")
    artifacts = payload.get("artifacts") or {}
    if not artifacts.get("artifact_dir"):
        errors.append("artifacts.artifact_dir is required")
    if not artifacts.get("computer_use_artifact_dir"):
        errors.append("artifacts.computer_use_artifact_dir is required")
    if not artifacts.get("summary"):
        errors.append("artifacts.summary is required")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an iOS gesture v2 regression report")
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-run-id", default=None)
    args = parser.parse_args(argv)

    if not args.report.exists():
        print(f"ERROR: report does not exist: {args.report}")
        return 1
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    errors = validate_report(payload, expected_run_id=args.expected_run_id)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
