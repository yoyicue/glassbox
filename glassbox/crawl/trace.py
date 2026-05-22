"""Generic action tracing for app crawlers.

This module owns the trace lifecycle and artifact format that used to live in
the iOS Settings walkthrough. App-specific crawlers only need to provide scene
summaries, unique-view persistence, and domain-specific no-progress rules.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def action_result_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    to_event_fields = getattr(result, "to_event_fields", None)
    if callable(to_event_fields):
        fields = to_event_fields()
        return {key: json_safe(value) for key, value in fields.items()}
    if isinstance(result, dict):
        fields = {
            "action_ok": bool(result.get("ok", True)),
            "action_backend": result.get("backend", "unknown"),
            "action_connected": bool(result.get("connected", True)),
            "action_retry_count": int(result.get("retryCount", 0) or 0),
            "action_synthetic": bool(result.get("synthetic", False)),
        }
        ack_seq = result.get("ackSeq", result.get("seq"))
        if ack_seq is not None:
            fields["action_ack_seq"] = ack_seq
        if result.get("err"):
            fields["action_error"] = str(result.get("err"))
        return fields
    return {}


@dataclass
class ActionTraceEvent:
    op: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    status: str = "pending"
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    intent: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ActionTraceObserver:
    """In-memory action observer usable by crawlers and tests."""

    events: list[ActionTraceEvent] = field(default_factory=list)
    _pending: ActionTraceEvent | None = None

    def start(
        self,
        op: str,
        *,
        before: dict[str, Any] | None = None,
        args: Iterable[Any] = (),
        kwargs: dict[str, Any] | None = None,
        intent: dict[str, Any] | None = None,
    ) -> None:
        self.close_pending(status="no_after_scene")
        self._pending = ActionTraceEvent(
            op=op,
            before=before,
            args=list(args),
            kwargs=dict(kwargs or {}),
            intent=dict(intent) if intent is not None else None,
        )

    def set_result(self, result: dict[str, Any] | None) -> None:
        if self._pending is not None:
            self._pending.result = dict(result) if isinstance(result, dict) else None

    def finish(
        self,
        after: dict[str, Any] | None,
        *,
        status: str = "ok",
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if self._pending is None:
            return
        self._pending.after = after
        self._pending.status = status
        if result is not None:
            self._pending.result = dict(result)
        self._pending.error = error
        self.events.append(self._pending)
        self._pending = None

    def close_pending(
        self,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if self._pending is None:
            return
        self._pending.status = status
        if result is not None:
            self._pending.result = dict(result)
        self._pending.error = error
        self.events.append(self._pending)
        self._pending = None


class ActionRunTrace:
    """Serialize traced phone actions and keep generic action quality counters."""

    def __init__(
        self,
        artifact_dir: Path | str,
        *,
        trace_actions: bool,
        save_view_snapshots: bool = False,
        run_id: str | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.trace_actions = trace_actions
        self.save_view_snapshots = save_view_snapshots
        self.views_dir = self.artifact_dir / "views"
        self.actions_path = self.artifact_dir / "actions.jsonl"
        self.manifest_path = self.artifact_dir / "manifest.json"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.views_dir.mkdir(exist_ok=True)
        self._pending_action: dict[str, Any] | None = None
        self._action_seq = 0
        self._op_counts: Counter[str] = Counter()
        self._no_progress_counts: Counter[str] = Counter()
        self._progress_counts: Counter[str] = Counter()
        self._no_after_counts: Counter[str] = Counter()
        self._intent_stack: list[dict[str, Any]] = []
        self._intent_counts: Counter[str] = Counter()
        self._no_progress_intent_counts: Counter[str] = Counter()
        self._observer = ActionTraceObserver()
        self._action_failure_counts: Counter[str] = Counter()
        self._semantic_rejected_counts: Counter[str] = Counter()
        self._semantic_unknown_counts: Counter[str] = Counter()
        self._semantic_partial_counts: Counter[str] = Counter()
        self._semantic_status_counts: Counter[str] = Counter()
        self._exception_counts: Counter[str] = Counter()
        manifest_payload = {
            "run_id": run_id,
            "trace_actions": trace_actions,
            "save_view_snapshots": save_view_snapshots,
        }
        if manifest:
            manifest_payload.update(manifest)
        self.manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def unique_view_count(self) -> int:
        return 0

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "artifact_dir": str(self.artifact_dir),
            "actions_jsonl": str(self.actions_path) if self.trace_actions else None,
            "views_dir": str(self.views_dir) if self.save_view_snapshots else None,
            "unique_view_count": self.unique_view_count,
            "action_count": self._action_seq,
            "hid_call_count": self._action_seq,
            "hid_op_counts": dict(sorted(self._op_counts.items())),
            "hid_no_progress_count": sum(self._no_progress_counts.values()),
            "hid_no_progress_op_counts": dict(sorted(self._no_progress_counts.items())),
            "hid_progress_count": sum(self._progress_counts.values()),
            "hid_progress_op_counts": dict(sorted(self._progress_counts.items())),
            "hid_no_after_count": sum(self._no_after_counts.values()),
            "hid_no_after_op_counts": dict(sorted(self._no_after_counts.items())),
            "hid_action_failure_count": sum(self._action_failure_counts.values()),
            "hid_action_failure_op_counts": dict(sorted(self._action_failure_counts.items())),
            "hid_semantic_rejected_count": sum(self._semantic_rejected_counts.values()),
            "hid_semantic_rejected_op_counts": dict(sorted(self._semantic_rejected_counts.items())),
            "hid_semantic_unknown_count": sum(self._semantic_unknown_counts.values()),
            "hid_semantic_partial_count": sum(self._semantic_partial_counts.values()),
            "hid_semantic_status_counts": dict(sorted(self._semantic_status_counts.items())),
            "hid_exception_count": sum(self._exception_counts.values()),
            "hid_exception_op_counts": dict(sorted(self._exception_counts.items())),
            "hid_intent_counts": dict(sorted(self._intent_counts.items())),
            "hid_no_progress_intent_counts": dict(sorted(self._no_progress_intent_counts.items())),
        }

    @contextmanager
    def intent(self, name: str, **metadata: Any) -> Iterator[None]:
        self._intent_stack.append({"name": name, **metadata})
        try:
            yield
        finally:
            self._intent_stack.pop()

    def observe_scene(self, phone: Any, scene: Any) -> dict[str, Any]:
        payload = self.scene_payload(phone, scene)
        if self.save_view_snapshots:
            view_id = self.record_unique_view(phone, scene, payload)
            if view_id is not None:
                payload["view_id"] = view_id
        if self._pending_action is not None:
            self._pending_action["after"] = payload
            status = str(self._pending_action.get("status") or "ok")
            self._observer.finish(
                payload,
                status=status,
                result=self._pending_action.get("action_result"),
                error=self._pending_action.get("error"),
            )
            self._write_action(self._pending_action)
            self._pending_action = None
        return payload

    def start_action(
        self,
        op: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        before: dict[str, Any],
    ) -> None:
        self.close_pending(status="no_after_scene")
        self._action_seq += 1
        intent_payload = None
        intent_stack_payload = None
        if self._intent_stack:
            intent_payload = json_safe(dict(self._intent_stack[-1]))
            intent_stack_payload = json_safe([dict(intent) for intent in self._intent_stack])
        self._observer.start(
            op,
            before=before,
            args=args,
            kwargs=kwargs,
            intent=intent_payload if isinstance(intent_payload, dict) else None,
        )
        self._pending_action = {
            "seq": self._action_seq,
            "ts": time.time(),
            "op": op,
            "args": [json_safe(arg) for arg in args],
            "kwargs": {key: json_safe(value) for key, value in kwargs.items()},
            "before": before,
        }
        if intent_payload is not None:
            self._pending_action["intent"] = intent_payload
            self._pending_action["intent_stack"] = intent_stack_payload

    def record_action_result(self, result: Any) -> None:
        if self._pending_action is None:
            return
        payload = action_result_payload(result)
        if not payload:
            return
        self._pending_action["action_result"] = payload
        self._observer.set_result(payload)
        if payload.get("action_ok") is False:
            self._pending_action.setdefault("status", "action_failed")
        semantic_status = payload.get("semantic_status")
        if semantic_status in {"failed", "blocked", "approval_required", "transport_failed", "exception"}:
            self._pending_action.setdefault("status", f"semantic_{semantic_status}")
        elif semantic_status == "unknown":
            self._pending_action.setdefault("status", "semantic_unknown")
        elif semantic_status == "partial":
            self._pending_action.setdefault("status", "semantic_partial")
        elif semantic_status == "no_after_scene":
            status = (
                "semantic_no_after_skipped"
                if payload.get("semantic_verification_skipped") is True
                else "semantic_no_after_scene"
            )
            self._pending_action.setdefault("status", status)

    def record_action_exception(self, exc: BaseException) -> None:
        if self._pending_action is None:
            return
        error = f"{type(exc).__name__}: {exc}"
        self.close_pending(status="exception", error=error)

    def close(self) -> None:
        self.close_pending(status="no_after_scene")

    def close_pending(
        self,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if self._pending_action is None:
            return
        if result is not None:
            self._pending_action["action_result"] = result
        if error is not None:
            self._pending_action["error"] = error
        self._pending_action["after"] = None
        self._pending_action["status"] = status
        self._observer.close_pending(
            status=status,
            result=self._pending_action.get("action_result"),
            error=self._pending_action.get("error"),
        )
        self._write_action(self._pending_action)
        self._pending_action = None

    def scene_payload(self, phone: Any, scene: Any) -> dict[str, Any]:
        del phone
        texts: list[str] = []
        for element in getattr(scene, "elements", ()):
            text = str(getattr(element, "text", "") or "").strip()
            if text:
                texts.append(text)
        return {"texts": texts}

    def record_unique_view(
        self,
        phone: Any,
        scene: Any,
        payload: dict[str, Any],
    ) -> str | None:
        del phone, scene, payload
        return None

    def action_no_progress(
        self,
        *,
        payload: dict[str, Any],
        op: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> bool:
        del payload, op
        return before == after

    def _write_action(self, payload: dict[str, Any]) -> None:
        self._record_action_stats(payload)
        if not self.trace_actions:
            return
        with self.actions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _record_action_stats(self, payload: dict[str, Any]) -> None:
        op = str(payload.get("op") or "<unknown>")
        self._op_counts[op] += 1
        intent_name = self._intent_name(payload.get("intent"))
        self._intent_counts[intent_name] += 1
        status = str(payload.get("status") or "ok")
        if status == "exception":
            self._exception_counts[op] += 1
        result = payload.get("action_result")
        if isinstance(result, dict) and result.get("action_ok") is False:
            self._action_failure_counts[op] += 1
        if isinstance(result, dict):
            semantic_status = result.get("semantic_status")
            if semantic_status:
                semantic_key = str(semantic_status)
                self._semantic_status_counts[semantic_key] += 1
                if semantic_key in {"failed", "blocked", "approval_required", "transport_failed", "exception"}:
                    self._semantic_rejected_counts[op] += 1
                elif semantic_key == "unknown":
                    self._semantic_unknown_counts[op] += 1
                elif semantic_key == "partial":
                    self._semantic_partial_counts[op] += 1
                elif (
                    semantic_key == "no_after_scene"
                    and result.get("semantic_verification_skipped") is not True
                ):
                    self._semantic_rejected_counts[op] += 1
        after = payload.get("after")
        if not isinstance(after, dict):
            self._no_after_counts[op] += 1
            return
        before = payload.get("before")
        no_progress = (
            isinstance(before, dict)
            and self.action_no_progress(payload=payload, op=op, before=before, after=after)
        )
        if no_progress:
            self._no_progress_counts[op] += 1
            self._no_progress_intent_counts[intent_name] += 1
        else:
            self._progress_counts[op] += 1

    def _intent_name(self, intent: Any) -> str:
        if isinstance(intent, dict) and intent.get("name"):
            return str(intent["name"])
        return "<unspecified>"


class TracedPhone:
    """Proxy phone actions through an ActionRunTrace."""

    ACTION_METHODS = frozenset({
        "tap_xy", "tap_text", "tap_button", "tap_intent",
        "double_tap_xy", "long_press_xy", "swipe_xy", "drag_xy",
        "scroll_wheel", "wheel_scroll_down", "wheel_scroll_up",
        "swipe_up", "swipe_down", "swipe_left", "swipe_right",
        "back_gesture", "home", "recents", "control_center",
        "notification_center", "type", "key", "paste",
    })

    def __init__(
        self,
        phone: Any,
        trace: ActionRunTrace,
        *,
        action_methods: Iterable[str] | None = None,
    ) -> None:
        self._phone = phone
        self._trace = trace
        self._action_methods = frozenset(action_methods or self.ACTION_METHODS)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._phone, name)
        if name not in self._action_methods or not callable(attr):
            return attr

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            before_scene = self._phone.perceive()
            before_payload = self._trace.observe_scene(self._phone, before_scene)
            self._trace.start_action(name, args, kwargs, before_payload)
            try:
                result = attr(*args, **kwargs)
            except Exception as exc:
                self._trace.record_action_exception(exc)
                raise
            self._trace.record_action_result(result)
            return result

        return _wrapped

    def perceive(self) -> Any:
        scene = self._phone.perceive()
        self._trace.observe_scene(self._phone, scene)
        return scene
