"""Per-session auto-calibration probe (CUQ-3.7).

The actuation profile learns its tap offset opportunistically — from the
candidate-point correction pairs produced when a real task tap misses. That
leaves the FIRST task taps of a fresh session uncalibrated. This module adds an
eager session-start probe: when no offset has been learned yet, tap a known-safe
anchor once so the orchestrated tap's landing-retry/correction machinery seeds
the offset before the first task tap.

The decision (`session_calibration_needed`) and the probe driver
(`run_session_calibration_probe`) are pure and unit-tested with a mock phone; the
probe only *taps* on a live rig (it drives real HID). The anchor target is
operator-supplied (config) since there is no device-agnostic safe-to-tap element.
"""

from __future__ import annotations

import contextlib
from typing import Any


def session_calibration_needed(profile: Any) -> bool:
    """True at cold start — no control-class entry has a learned tap offset yet,
    so the first real taps would run uncalibrated. False once any offset exists
    (the opportunistic mid-run learning has already produced one)."""
    entries = getattr(profile, "entries", None)
    if not entries:
        return True
    for entry in entries.values():
        for stats in getattr(entry, "methods", {}).values():
            if getattr(stats, "offset", None) is not None:
                return False
    return True


def run_session_calibration_probe(phone: Any, target: str | None) -> bool:
    """Eagerly tap ``target`` once at session start to seed the actuation offset
    (via the orchestrated tap's correction machinery) before the first task tap.

    Returns True iff a probe tap ran. No-op (returns False) when ``target`` is
    empty, the phone cannot tap, or calibration already exists — so an
    unconfigured session is byte-identical. Tap failures are swallowed: the probe
    is best-effort warm-up, never a hard precondition.
    """
    target = (target or "").strip()
    if not target:
        return False
    profile = getattr(getattr(phone, "action_orchestrator", None), "actuation_profile", None)
    if profile is not None and not session_calibration_needed(profile):
        return False
    tap_text = getattr(phone, "tap_text", None)
    if not callable(tap_text):
        return False
    with contextlib.suppress(Exception):
        tap_text(target, landing_retry_allowed=True)
    return True
