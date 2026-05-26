"""Action output protocol and test/noop implementations.

Real iPhone control is provided by pluggable effectors such as the PicoKVM
backend. This module keeps the common Effector protocol plus NoOp/Mock
implementations used by offline runs and tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

EFFECTOR_ACTIONS = frozenset({
    "tap",
    "long_press",
    "double_tap",
    "swipe",
    "drag",
    "close_foreground_app",
    "list_scroll_up",
    "list_scroll_down",
    "page_slide_left",
    "page_slide_right",
    "scroll_wheel",
    "wheel_scroll_down",
    "wheel_scroll_up",
    "type",
    "key",
    "set_clipboard",
    "home",
    "recents",
    "control_center",
    "notification_center",
    "paste",
})


@dataclass(frozen=True)
class ActionResult:
    """Execution status returned by an effector action."""

    ok: bool
    backend: str
    connected: bool
    ack_seq: int | None = None
    retry_count: int = 0
    error: str | None = None
    synthetic: bool = False
    unsupported: bool = False
    ack_seqs: tuple[int, ...] = ()
    partial: bool = False
    executed_count: int | None = None
    semantic_status: str | None = None
    semantic_reason: str | None = None
    semantic_confidence: float | None = None
    semantic_verifier: str | None = None
    semantic_verification_skipped: bool | None = None
    attempt_id: str | None = None
    attempt_group_id: str | None = None
    artifact_run_dir: str | None = None

    def to_event_fields(self) -> dict:
        fields = {
            "action_ok": self.ok,
            "action_backend": self.backend,
            "action_connected": self.connected,
            "action_retry_count": self.retry_count,
            "action_synthetic": self.synthetic,
            "action_unsupported": self.unsupported,
        }
        if self.ack_seq is not None:
            fields["action_ack_seq"] = self.ack_seq
        if self.ack_seqs:
            fields["action_ack_seqs"] = list(self.ack_seqs)
        if self.partial:
            fields["action_partial"] = True
        if self.executed_count is not None:
            fields["action_executed_count"] = self.executed_count
        if self.error:
            fields["action_error"] = self.error
        if self.semantic_status is not None:
            fields["semantic_status"] = self.semantic_status
        if self.semantic_reason is not None:
            fields["semantic_reason"] = self.semantic_reason
        if self.semantic_confidence is not None:
            fields["semantic_confidence"] = self.semantic_confidence
        if self.semantic_verifier is not None:
            fields["semantic_verifier"] = self.semantic_verifier
        if self.semantic_verification_skipped is not None:
            fields["semantic_verification_skipped"] = self.semantic_verification_skipped
        if self.attempt_id is not None:
            fields["attempt_id"] = self.attempt_id
        if self.attempt_group_id is not None:
            fields["attempt_group_id"] = self.attempt_group_id
        if self.artifact_run_dir is not None:
            fields["artifact_run_dir"] = self.artifact_run_dir
        return fields

    @classmethod
    def failed(
        cls,
        *,
        backend: str,
        connected: bool,
        error: str,
        synthetic: bool = False,
        unsupported: bool = False,
        ack_seq: int | None = None,
        retry_count: int = 0,
        ack_seqs: tuple[int, ...] = (),
        partial: bool = False,
        executed_count: int | None = None,
        semantic_status: str | None = None,
        semantic_reason: str | None = None,
        semantic_confidence: float | None = None,
        semantic_verifier: str | None = None,
        semantic_verification_skipped: bool | None = None,
        attempt_id: str | None = None,
        attempt_group_id: str | None = None,
        artifact_run_dir: str | None = None,
    ) -> ActionResult:
        return cls(
            ok=False,
            backend=backend,
            connected=connected,
            ack_seq=ack_seq,
            retry_count=retry_count,
            error=error,
            synthetic=synthetic,
            unsupported=unsupported,
            ack_seqs=ack_seqs,
            partial=partial,
            executed_count=executed_count,
            semantic_status=semantic_status,
            semantic_reason=semantic_reason,
            semantic_confidence=semantic_confidence,
            semantic_verifier=semantic_verifier,
            semantic_verification_skipped=semantic_verification_skipped,
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            artifact_run_dir=artifact_run_dir,
        )


# ─── Effector Protocol (walkthrough scripts depend only on this interface) ──
@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    fatal: bool = False
    code: str = "ok"
    message: str = ""
    config_ref: str | None = None


SystemActionStrategy = Literal[
    "direct",
    "keyboard_combo",
    "assistive_touch",
    "unsupported",
]
PointerKind = Literal["touch_digitizer", "external_mouse", "none", "unknown"]
ScrollStrategy = Literal["wheel", "drag", "unsupported"]


@dataclass(frozen=True)
class BackendCapabilities:
    """Backend capability contract consumed by semantic Phone actions.

    Effector.supports(action) describes direct transport operations. This
    structure describes both direct operations and semantic strategies the Phone
    layer can assemble using perception, such as AssistiveTouch Home on KVM.
    """

    backend: str
    coordinate_space: str = "frame_px"
    pointer_kind: PointerKind = "unknown"
    direct_actions: frozenset[str] = frozenset()
    keyboard: bool = False
    text: bool = False
    clipboard: bool = False
    scroll_strategy: ScrollStrategy = "unsupported"
    back_strategy: SystemActionStrategy = "keyboard_combo"
    home_strategy: SystemActionStrategy = "unsupported"
    recents_strategy: SystemActionStrategy = "unsupported"
    control_center_strategy: SystemActionStrategy = "unsupported"
    notification_center_strategy: SystemActionStrategy = "unsupported"
    switch_input_source_strategy: SystemActionStrategy = "unsupported"
    paste_strategy: SystemActionStrategy = "unsupported"
    requires_assistive_touch: bool = False
    requires_calibrated_crop: bool = False
    requires_connection: bool = False
    transport_label: str = "none"
    wheel_ticks_per_scroll: int | None = None
    wheel_invert: bool | None = None

    def supports_direct(self, action: str) -> bool:
        return action in self.direct_actions

    def supports_semantic(self, action: str) -> bool:
        if action in {
            "tap",
            "long_press",
            "double_tap",
            "swipe",
            "drag",
            "close_foreground_app",
            "list_scroll_up",
            "list_scroll_down",
            "page_slide_left",
            "page_slide_right",
            "key",
        }:
            return action in self.direct_actions
        if action == "type":
            return self.text
        if action == "set_clipboard":
            return self.clipboard
        if action in {"scroll_wheel", "wheel_scroll_down", "wheel_scroll_up"}:
            return self.scroll_strategy == "wheel"
        if action in {"back", "back_gesture"}:
            return self.back_strategy != "unsupported"
        if action == "home":
            return self.home_strategy != "unsupported"
        if action == "recents":
            return self.recents_strategy != "unsupported"
        if action == "control_center":
            return self.control_center_strategy != "unsupported"
        if action == "notification_center":
            return self.notification_center_strategy != "unsupported"
        if action == "switch_input_source":
            return self.switch_input_source_strategy != "unsupported"
        if action == "paste":
            return self.paste_strategy != "unsupported"
        return False


NOOP_CAPABILITIES = BackendCapabilities(
    backend="noop",
    pointer_kind="none",
)


MOCK_CAPABILITIES = BackendCapabilities(
    backend="mock",
    pointer_kind="touch_digitizer",
    direct_actions=EFFECTOR_ACTIONS,
    keyboard=True,
    text=True,
    clipboard=True,
    scroll_strategy="wheel",
    home_strategy="direct",
    recents_strategy="direct",
    control_center_strategy="direct",
    notification_center_strategy="direct",
    switch_input_source_strategy="keyboard_combo",
    paste_strategy="direct",
)


class Effector(Protocol):
    """Unified effector interface. PicoKVM / NoOp / Mock all implement it."""

    coordinate_space: str

    def is_connected(self) -> bool: ...
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def supports(self, action: str) -> bool: ...
    def capabilities(self) -> BackendCapabilities: ...
    def preflight(self) -> PreflightResult: ...

    # touch
    def tap(self, x: int, y: int) -> ActionResult: ...
    def long_press(self, x: int, y: int, hold_ms: int = 500) -> ActionResult: ...
    def double_tap(self, x: int, y: int) -> ActionResult: ...
    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              *, steps: int = 20, end_hold_ms: int = 100) -> ActionResult: ...
    def drag(self, x1: int, y1: int, x2: int, y2: int,
             *, down_hold_ms: int = 200, up_hold_ms: int = 100) -> ActionResult: ...
    def close_foreground_app(self) -> ActionResult: ...
    def list_scroll_up(self) -> ActionResult: ...
    def list_scroll_down(self) -> ActionResult: ...
    def page_slide_left(self) -> ActionResult: ...
    def page_slide_right(self) -> ActionResult: ...
    def scroll_wheel(self, ticks: int, *,
                     horizontal: int = 0, interval_ms: int = 40,
                     focus: bool = True, focus_click: bool = False,
                     focus_x: int | None = None,
                     focus_y: int | None = None) -> ActionResult: ...

    # keyboard
    def type(self, text: str) -> ActionResult: ...
    def key(self, modifier: int, keycode: int) -> ActionResult: ...
    def set_clipboard(self, text: str) -> ActionResult: ...

    # iOS system gestures
    def home(self) -> ActionResult: ...
    def recents(self) -> ActionResult: ...
    def control_center(self) -> ActionResult: ...
    def notification_center(self) -> ActionResult: ...
    def paste(self) -> ActionResult: ...


# ─── NoOp Effector — placeholder when there is no bridge ────────────
class NoOpEffector:
    """Placeholder effector when there is no bridge hardware. All actions only log."""

    def __init__(self, *, coordinate_space: str = "frame_px"):
        self.coordinate_space = coordinate_space

    def is_connected(self) -> bool:
        return False

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def supports(self, action: str) -> bool:
        return False

    def capabilities(self) -> BackendCapabilities:
        return replace(NOOP_CAPABILITIES, coordinate_space=self.coordinate_space)

    def preflight(self) -> PreflightResult:
        return PreflightResult(ok=True)

    def _log(self, op: str, **kw) -> ActionResult:
        kvs = ", ".join(f"{k}={v!r}" for k, v in kw.items())
        print(f"[NoOpEffector] {op}({kvs}) — bridge not connected")
        return ActionResult(
            ok=False,
            backend="noop",
            connected=False,
            error="bridge not connected",
            synthetic=True,
        )

    def tap(self, x, y):                  return self._log("tap", x=x, y=y)
    def long_press(self, x, y, hold_ms=500):    return self._log("long_press", x=x, y=y, hold_ms=hold_ms)
    def double_tap(self, x, y):           return self._log("double_tap", x=x, y=y)
    def swipe(self, x1, y1, x2, y2, *, steps=20, end_hold_ms=100):
        return self._log("swipe", x1=x1, y1=y1, x2=x2, y2=y2, steps=steps)
    def drag(self, x1, y1, x2, y2, *, down_hold_ms=200, up_hold_ms=100):
        return self._log("drag", x1=x1, y1=y1, x2=x2, y2=y2)
    def close_foreground_app(self):       return self._log("close_foreground_app")
    def list_scroll_up(self):             return self._log("list_scroll_up")
    def list_scroll_down(self):           return self._log("list_scroll_down")
    def page_slide_left(self):            return self._log("page_slide_left")
    def page_slide_right(self):           return self._log("page_slide_right")
    def scroll_wheel(self, ticks, *, horizontal=0, interval_ms=40,
                     focus=True, focus_click=False, focus_x=None, focus_y=None):
        kwargs = dict(
            ticks=ticks,
            horizontal=horizontal,
            interval_ms=interval_ms,
            focus=focus,
            focus_x=focus_x,
            focus_y=focus_y,
        )
        if focus_click:
            kwargs["focus_click"] = True
        return self._log("scroll_wheel", **kwargs)
    def type(self, text):                 return self._log("type", text=text)
    def key(self, modifier, keycode):     return self._log("key", mod=modifier, kc=keycode)
    def set_clipboard(self, text):        return self._log("set_clipboard", text=text)
    def home(self):                       return self._log("home")
    def recents(self):                    return self._log("recents")
    def control_center(self):             return self._log("control_center")
    def notification_center(self):        return self._log("notification_center")
    def paste(self):                      return self._log("paste")


# ─── Mock Effector — for unit tests, records every action ──────────
@dataclass
class MockAction:
    """One recorded effector call."""
    op: str
    kwargs: dict
    result: ActionResult | None = None


@dataclass
class MockEffector:
    """Effector for unit tests. Every action goes into the actions list.

    Usage:
        eff = MockEffector()
        phone = Phone(source, ocr, eff, profile)
        phone.tap_text("登录")
        assert eff.actions[0].op == "tap"
    """
    actions: list[MockAction] = field(default_factory=list)
    _connected: bool = True
    coordinate_space: str = "frame_px"

    def is_connected(self) -> bool: return self._connected
    def connect(self) -> None: self._connected = True
    def close(self) -> None: self._connected = False

    def supports(self, action: str) -> bool:
        return action in EFFECTOR_ACTIONS

    def capabilities(self) -> BackendCapabilities:
        return replace(MOCK_CAPABILITIES, coordinate_space=self.coordinate_space)

    def preflight(self) -> PreflightResult:
        return PreflightResult(ok=True)

    def _record(self, op: str, **kw) -> ActionResult:
        result = ActionResult(
            ok=self._connected,
            backend="mock",
            connected=self._connected,
            error=None if self._connected else "mock effector disconnected",
            synthetic=False,
        )
        self.actions.append(MockAction(op=op, kwargs=kw, result=result))
        return result

    def tap(self, x, y):                  return self._record("tap", x=x, y=y)
    def long_press(self, x, y, hold_ms=500):    return self._record("long_press", x=x, y=y, hold_ms=hold_ms)
    def double_tap(self, x, y):           return self._record("double_tap", x=x, y=y)
    def swipe(self, x1, y1, x2, y2, *, steps=20, end_hold_ms=100):
        return self._record("swipe", x1=x1, y1=y1, x2=x2, y2=y2, steps=steps, end_hold_ms=end_hold_ms)
    def drag(self, x1, y1, x2, y2, *, down_hold_ms=200, up_hold_ms=100):
        return self._record("drag", x1=x1, y1=y1, x2=x2, y2=y2,
                            down_hold_ms=down_hold_ms, up_hold_ms=up_hold_ms)
    def close_foreground_app(self):       return self._record("close_foreground_app")
    def list_scroll_up(self):             return self._record("list_scroll_up")
    def list_scroll_down(self):           return self._record("list_scroll_down")
    def page_slide_left(self):            return self._record("page_slide_left")
    def page_slide_right(self):           return self._record("page_slide_right")
    def scroll_wheel(self, ticks, *, horizontal=0, interval_ms=40,
                     focus=True, focus_click=False, focus_x=None, focus_y=None):
        kwargs = dict(
            ticks=ticks,
            horizontal=horizontal,
            interval_ms=interval_ms,
            focus=focus,
            focus_x=focus_x,
            focus_y=focus_y,
        )
        if focus_click:
            kwargs["focus_click"] = True
        return self._record("scroll_wheel", **kwargs)
    def type(self, text):                 return self._record("type", text=text)
    def key(self, modifier, keycode):     return self._record("key", modifier=modifier, keycode=keycode)
    def set_clipboard(self, text):        return self._record("set_clipboard", text=text)
    def home(self):                       return self._record("home")
    def recents(self):                    return self._record("recents")
    def control_center(self):             return self._record("control_center")
    def notification_center(self):        return self._record("notification_center")
    def paste(self):                      return self._record("paste")

    def last(self) -> MockAction | None:
        return self.actions[-1] if self.actions else None

    def reset(self) -> None:
        self.actions.clear()
