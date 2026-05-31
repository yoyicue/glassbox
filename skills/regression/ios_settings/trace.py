"""Action trace adapter for iOS Settings crawlers."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glassbox.boundaries import action_host_last_frame
from glassbox.crawl.trace import ActionRunTrace, TracedPhone

SCROLL_OPS = frozenset({"wheel_scroll_down", "wheel_scroll_up", "scroll_wheel"})


@dataclass(frozen=True)
class SettingsTraceCallbacks:
    texts: Callable[[Any], list[str]]
    classify_scene: Callable[[Any], Any]
    scene_type: Callable[[Any], str]
    page_title: Callable[[Any], str]
    screen_signature: Callable[[list[str]], tuple[str, ...]]
    scroll_outcome: Callable[[list[str], list[str]], str]
    trace_payload_no_progress: Callable[[dict[str, Any], dict[str, Any]], bool]


class SettingsRunTrace(ActionRunTrace):
    """Settings-specific trace artifacts for reviewing failed real-device runs."""

    def __init__(
        self,
        artifact_dir: Path | str,
        *,
        trace_actions: bool,
        save_view_snapshots: bool,
        run_id: str | None = None,
        callbacks: SettingsTraceCallbacks,
    ) -> None:
        self._settings_callbacks = callbacks
        self._seen_views: dict[tuple[str, tuple[str, ...]], str] = {}
        self._view_seq = 0
        super().__init__(
            artifact_dir,
            trace_actions=trace_actions,
            save_view_snapshots=save_view_snapshots,
            run_id=run_id,
        )

    @property
    def unique_view_count(self) -> int:
        return len(self._seen_views)

    def scene_payload(self, phone, scene) -> dict[str, Any]:
        del phone
        callbacks = self._settings_callbacks
        texts = callbacks.texts(scene)
        classified = callbacks.classify_scene(scene)
        scene_type = classified.kind if classified is not None else callbacks.scene_type(scene)
        return {
            "scene_type": scene_type,
            "confidence": classified.confidence if classified is not None else None,
            "page_id": classified.page_id if classified is not None else None,
            "title": classified.title if classified is not None else callbacks.page_title(scene),
            "safe_actions": list(classified.safe_actions) if classified is not None else [],
            "evidence": list(classified.evidence) if classified is not None else [],
            "signature": list(callbacks.screen_signature(texts)),
            "texts": texts[:40],
            "elements": [
                {
                    "type": element.type,
                    "text": element.text,
                    "box": [element.box.x, element.box.y, element.box.w, element.box.h],
                    "confidence": round(element.confidence, 3),
                }
                for element in scene.elements
            ],
        }

    def record_unique_view(self, phone, scene, payload: dict[str, Any]) -> str | None:
        key = (str(payload["scene_type"]), tuple(payload["signature"]))
        existing = self._seen_views.get(key)
        if existing is not None:
            return existing
        self._view_seq += 1
        view_id = f"view_{self._view_seq:04d}"
        self._seen_views[key] = view_id
        ocr_path = self.views_dir / f"{view_id}.ocr.json"
        ocr_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        frame = action_host_last_frame(phone)
        img = getattr(frame, "img", None)
        if img is not None:
            try:
                import cv2

                cv2.imwrite(str(self.views_dir / f"{view_id}.png"), img)
            except Exception:
                pass
        return view_id

    def action_no_progress(
        self,
        *,
        payload: dict[str, Any],
        op: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        del payload
        callbacks = self._settings_callbacks
        if op in SCROLL_OPS:
            before_texts, after_texts = before.get("texts"), after.get("texts")
            return (
                isinstance(before_texts, list)
                and isinstance(after_texts, list)
                and callbacks.scroll_outcome(before_texts, after_texts) == "stuck"
            )
        return callbacks.trace_payload_no_progress(before, after)


class TracedSettingsPhone(TracedPhone):
    ACTION_METHODS = frozenset({
        "tap_xy", "tap_text", "tap_button", "tap_intent",
        "double_tap_xy", "long_press_xy", "swipe_xy", "drag_xy",
        "scroll_wheel", "wheel_scroll_down", "wheel_scroll_up",
        "swipe_up", "swipe_down", "swipe_left", "swipe_right",
        "back_gesture", "home", "recents", "control_center",
        "notification_center", "type", "key", "paste",
    })

    def __init__(self, phone, trace: SettingsRunTrace):
        super().__init__(phone, trace, action_methods=self.ACTION_METHODS)


def wrap_phone_with_trace(
    phone,
    *,
    artifact_dir: Path | str | None,
    trace_actions: bool,
    save_view_snapshots: bool,
    run_id: str | None,
    callbacks: SettingsTraceCallbacks,
):
    if not (trace_actions or save_view_snapshots) or artifact_dir is None:
        return phone, None
    trace = SettingsRunTrace(
        artifact_dir,
        trace_actions=trace_actions,
        save_view_snapshots=save_view_snapshots,
        run_id=run_id,
        callbacks=callbacks,
    )
    return TracedSettingsPhone(phone, trace), trace


def action_intent(phone, name: str, **metadata: Any):
    trace = getattr(phone, "_trace", None)
    if isinstance(trace, SettingsRunTrace):
        return trace.intent(name, **metadata)

    @contextmanager
    def _noop():
        yield

    return _noop()
