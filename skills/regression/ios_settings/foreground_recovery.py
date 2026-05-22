"""Foreground recovery probes for iOS Settings evals.

The Settings walkthrough uses root coverage as its main long run. This module
keeps foreground-start cases separate so App Library / Home / global search
failures are measured as glassbox recovery gaps instead of hidden setup steps.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from glassbox.ios.progress import (
    screen_signature,
    stable_visible_texts,
    trace_payload_no_progress,
)
from glassbox.ios.scene import SETTINGS_TITLE_LABELS, classify_ios_scene
from glassbox.ios.springboard import open_app_from_springboard

SETTINGS_APP_LABELS = SETTINGS_TITLE_LABELS


def _texts(scene) -> list[str]:
    return [
        text
        for element in scene.elements
        if (text := (element.text or "").strip())
    ]


def _viewport_size(phone) -> tuple[int, int] | None:
    try:
        w, h = phone._viewport_size()
        return int(w), int(h)
    except Exception:
        return None


def _classify(scene, phone=None):
    viewport_size = _viewport_size(phone) if phone is not None else None
    if viewport_size is not None:
        return classify_ios_scene(scene, viewport_size=viewport_size)
    return classify_ios_scene(scene)


def _scene_payload(scene, phone=None) -> dict[str, Any]:
    texts = _texts(scene)
    classified = _classify(scene, phone=phone)
    return {
        "scene_type": classified.kind,
        "confidence": classified.confidence,
        "page_id": classified.page_id,
        "title": classified.title,
        "safe_actions": list(classified.safe_actions),
        "evidence": list(classified.evidence),
        "signature": list(screen_signature(texts)),
        "stable_texts": sorted(stable_visible_texts(texts))[:40],
        "texts": texts[:40],
        "elements": [
            {
                "text": (element.text or "").strip(),
                "type": element.type,
                "box": [element.box.x, element.box.y, element.box.w, element.box.h],
            }
            for element in scene.elements
            if (element.text or "").strip()
        ][:60],
    }


class ForegroundProbeTrace:
    def __init__(self, phone, *, settle_s: float):
        self.phone = phone
        self.settle_s = settle_s
        self.steps: list[dict[str, Any]] = []
        self.hid_call_count = 0
        self._last_payload: dict[str, Any] | None = None

    @property
    def last_payload(self) -> dict[str, Any] | None:
        return self._last_payload

    def observe(self, label: str, **metadata: Any) -> dict[str, Any]:
        with contextlib.suppress(Exception):
            self.phone.invalidate_perceive_cache()
        scene = self.phone.perceive()
        payload = _scene_payload(scene, phone=self.phone)
        self.steps.append({
            "kind": "observe",
            "label": label,
            **metadata,
            "scene": payload,
        })
        self._last_payload = payload
        return payload

    def action(self, op: str, fn: Callable[[], Any], **metadata: Any) -> Any:
        before = self._last_payload
        self.hid_call_count += 1
        result = fn()
        if self.settle_s > 0:
            time.sleep(self.settle_s)
        after = self.observe(f"after_{op}", **metadata)
        self.steps.append({
            "kind": "action_result",
            "op": op,
            **metadata,
            "before_signature": before.get("signature") if isinstance(before, dict) else None,
            "after_signature": after.get("signature"),
            "no_progress": trace_payload_no_progress(before, after) if isinstance(before, dict) else None,
        })
        return result


def probe_app_library_recovery(
    phone,
    *,
    labels: Iterable[str] = SETTINGS_APP_LABELS,
    max_swipes: int = 8,
    settle_s: float = 0.8,
    swipe_y_fractions: tuple[float, ...] = (0.55, 0.36, 0.74),
) -> dict[str, Any]:
    """Try to reach App Library from Home, then open Settings from that state.

    The probe is intentionally narrow: it records whether horizontal
    navigation can reach App Library and whether the foreground recovery path
    can still get Settings open afterwards.
    """
    trace = ForegroundProbeTrace(phone, settle_s=settle_s)
    trace.observe("initial")
    trace.action("home", lambda: phone.home())

    app_library_reached = _reach_app_library(
        phone,
        trace=trace,
        max_swipes=max_swipes,
        y_fractions=swipe_y_fractions,
    )
    if not app_library_reached:
        return _final_report(
            trace,
            status="failed",
            failure_reason="app_library_unreachable",
            app_library_reached=False,
            settings_opened=False,
        )

    opened = bool(trace.action(
        "open_settings_from_app_library_start",
        lambda: open_app_from_springboard(phone, tuple(labels), max_pages=max_swipes, settle_s=settle_s),
    ))
    final_scene = trace.last_payload or trace.observe("final")
    settings_opened = opened and final_scene.get("scene_type") in {"settings_root", "settings_detail"}
    return _final_report(
        trace,
        status="passed" if settings_opened else "failed",
        failure_reason=None if settings_opened else "settings_not_opened_from_app_library_start",
        app_library_reached=True,
        settings_opened=settings_opened,
    )


def _reach_app_library(
    phone,
    *,
    trace: ForegroundProbeTrace,
    max_swipes: int,
    y_fractions: tuple[float, ...],
) -> bool:
    current = trace.last_payload or trace.observe("before_app_library_scan")
    if current.get("scene_type") == "app_library":
        return True
    for lane_index, y_fraction in enumerate(y_fractions):
        if lane_index:
            trace.action("home_before_app_library_swipe_lane", lambda: phone.home(), y_fraction=y_fraction)
            current = trace.last_payload or {}
            if current.get("scene_type") == "app_library":
                return True
        seen: set[tuple[str, ...]] = {_visible_page_key(current)}
        repeated = 0
        for index in range(max(0, max_swipes)):
            trace.action(
                "swipe_left",
                lambda y_fraction=y_fraction: _swipe_left(phone, y_fraction=y_fraction),
                swipe_index=index + 1,
                y_fraction=y_fraction,
            )
            current = trace.last_payload or {}
            if current.get("scene_type") == "app_library":
                return True
            visible_key = _visible_page_key(current)
            if visible_key in seen:
                repeated += 1
                if repeated >= 2:
                    break
            else:
                repeated = 0
                seen.add(visible_key)
    return False


def _swipe_left(phone, *, y_fraction: float) -> None:
    try:
        phone.swipe_left(fraction=0.82, y_fraction=y_fraction)
    except TypeError:
        phone.swipe_left()


def _visible_page_key(payload: dict[str, Any]) -> tuple[str, ...]:
    stable_texts = payload.get("stable_texts")
    if isinstance(stable_texts, list) and stable_texts:
        return tuple(str(text) for text in stable_texts)
    return tuple(str(text) for text in payload.get("signature") or ())


def _final_report(
    trace: ForegroundProbeTrace,
    *,
    status: str,
    failure_reason: str | None,
    app_library_reached: bool,
    settings_opened: bool,
) -> dict[str, Any]:
    final_scene = trace.last_payload
    return {
        "probe": "ios_settings_app_library_foreground_recovery",
        "status": status,
        "failure_reason": failure_reason,
        "app_library_reached": app_library_reached,
        "settings_opened": settings_opened,
        "metrics": {
            "hid_call_count": trace.hid_call_count,
            "step_count": len(trace.steps),
            "final_scene_type": final_scene.get("scene_type") if isinstance(final_scene, dict) else None,
        },
        "failure_categories": _foreground_failure_categories(failure_reason),
        "steps": trace.steps,
    }


def _foreground_failure_categories(failure_reason: str | None) -> dict[str, list[str]]:
    categories = {key: [] for key in ("perception", "operation", "recovery", "efficiency", "safety")}
    if failure_reason == "app_library_unreachable":
        categories["recovery"].append("ios-foreground-app-library-unreachable")
    elif failure_reason == "settings_not_opened_from_app_library_start":
        categories["recovery"].append("ios-foreground-settings-not-opened")
    return categories


def write_report(report: dict[str, Any], path: str | Path | None) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
