"""AI-facing facade for author-mode glassbox scripts.

This module is intentionally narrow: AI-authored scripts import this layer
instead of reaching into ``Phone`` and runtime assembly details. The default
path is in-process and uses ``glassbox.runtime`` directly; a future harnessd/MCP
transport can consume the same data classes and method contract.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Any

from glassbox.config import AgentConfig, get_config
from glassbox.crawl.policy import CrawlState, NavigationCandidate
from glassbox.effector import ActionResult
from glassbox.runtime import PhoneRuntime, build_phone, make_source

AI_API_VERSION = "ai-api-v1"
SUPPORTED_ARTIFACT_SCHEMA_VERSION = 1
_AI_DEFAULT_STABLE_TIMEOUT_S = 5.0
_AI_DEFAULT_STABLE_CONSECUTIVE = 3
_AI_DEFAULT_EXPECT_TIMEOUT_S = 5.0
_AI_DEFAULT_SCROLL_TIMEOUT_S = 10.0
_AI_DEFAULT_SAMPLE_INTERVAL_S = 0.25
_AI_DEFAULT_SCROLL_WINDOW_S = 1.2

_APP_ALIASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "com.apple.Preferences": ("设置", ("Settings",)),
    "settings": ("设置", ("Settings",)),
    "Settings": ("设置", ("Settings",)),
    "设置": ("设置", ("Settings",)),
}


@dataclass(frozen=True)
class ElementBox:
    x: int
    y: int
    w: int
    h: int
    center: tuple[int, int]


@dataclass(frozen=True)
class ObservationElement:
    element_id: int
    type: str
    box: ElementBox
    text: str | None = None
    confidence: float = 0.0
    suggested_actions: tuple[str, ...] = ()
    intent_label: str | None = None
    preferred_tap_point: tuple[int, int] | None = None
    whitebox_hint: dict[str, Any] | None = None


@dataclass(frozen=True)
class ObservationSummary:
    summary: str
    page_id: str | None
    scene_type: str | None
    visible_texts: tuple[str, ...]
    actions: tuple[str, ...]
    can_scroll: bool | None
    screenshot_path: Path | None
    scene_path: Path
    event_seq: int
    elements: tuple[ObservationElement, ...] = ()
    viewport_size: tuple[int, int] | None = None
    coordinate_space: str = "frame_px"
    crop_bbox: tuple[int, int, int, int] | None = None
    source_shape: tuple[int, int] | None = None
    projection: str | None = None
    platform_scene_kind: str | None = None
    current_vc: str | None = None
    whitebox_evaluated: bool = False
    app_state: dict[str, str] | None = None

    def __str__(self) -> str:
        return self.summary


@dataclass(frozen=True)
class ActionOutcome:
    ok: bool
    semantic_status: str
    action: str
    target: str | None
    reason: str | None
    artifact_path: Path | None
    transport_ok: bool | None = None
    unsupported: bool = False
    semantic_verifier: str | None = None
    semantic_confidence: float | None = None


@dataclass(frozen=True)
class RunArtifacts:
    run_id: str
    run_name: str | None
    run_dir: Path
    manifest_path: Path
    report_path: Path | None
    failure_path: Path | None
    latest_scene_path: Path | None
    latest_screenshot_path: Path | None
    artifact_schema_version: int
    ai_api_version: str


@dataclass(frozen=True)
class DecisionTraceStep:
    index: int
    observation_event_seq: int
    observed_page_id: str | None
    decision_action: str
    decision_target: str | None
    decision_reason: str
    action_semantic_status: str
    verified: bool
    verification: str
    after_event_seq: int
    after_page_id: str | None


@dataclass(frozen=True)
class ExplorationTrail:
    goal: str
    success: bool
    steps: tuple[str, ...]
    final_observation: ObservationSummary
    matched_path: tuple[str, ...]
    artifact_path: Path
    decision_trace: tuple[DecisionTraceStep, ...] = ()

    def summary(self) -> str:
        status = "success" if self.success else "failed"
        path = " -> ".join(self.matched_path) if self.matched_path else "(no path)"
        return f"{status}: {self.goal}; path={path}; steps={len(self.steps)}"


@dataclass(frozen=True)
class PathArtifact:
    name: str
    run_id: str
    path: Path
    steps: tuple[str, ...]
    source_trail_path: Path | None
    script_snippet_path: Path | None


class AttachBusyError(RuntimeError):
    """Raised when a future harnessd path cannot acquire a device lease."""


class AIAssertionError(AssertionError):
    """Assertion failure with stable artifact handles for AI debugging."""

    def __init__(
        self,
        message: str,
        *,
        run_id: str,
        failure_path: Path,
        observation: ObservationSummary | None = None,
        artifacts: RunArtifacts | None = None,
    ):
        super().__init__(message)
        self.run_id = run_id
        self.failure_path = failure_path
        self.observation = observation
        self.artifacts = artifacts


class AIRawAccess:
    """Explicit escape hatch for advanced/debug callers."""

    def __init__(self, owner: AIPhone):
        self._owner = owner

    def tap_xy(self, x: int, y: int, *, coordinate_space: str | None = None) -> ActionOutcome:
        return self._owner.tap_xy(x, y, coordinate_space=coordinate_space)

    def latest_scene(self) -> dict[str, Any] | None:
        path = self._owner._latest_scene_path
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


class AIArtifactAccess:
    """Read-only artifact helper that resolves paths under this run directory."""

    def __init__(self, owner: AIPhone):
        self._owner = owner

    def read_scene_json(self, path: Path | str | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._owner._latest_scene_path
        if target is None:
            raise FileNotFoundError("no scene artifact has been written yet")
        resolved = self._owner._resolve_artifact_path(target)
        return json.loads(resolved.read_text(encoding="utf-8"))


class AIPhone:
    """Stable, AI-facing phone handle returned by :func:`open_phone`."""

    def __init__(
        self,
        runtime: PhoneRuntime,
        *,
        run_name: str | None = None,
        app: str | None = None,
        policy: Any = None,
    ):
        self._runtime = runtime
        self._phone = runtime.phone
        self.run_name = run_name
        self.app = app
        self.policy = policy
        self._store = getattr(runtime.action_orchestrator, "store", None)
        self.run_id = str(getattr(self._store, "run_id", None) or f"ai_{int(time.time() * 1000)}")
        self.run_dir = Path(getattr(self._store, "run_dir", Path("artifacts") / self.run_id))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_frames_dir = self.run_dir / "frames"
        self._fallback_scenes_dir = self.run_dir / "scenes"
        self._fallback_frames_dir.mkdir(exist_ok=True)
        self._fallback_scenes_dir.mkdir(exist_ok=True)
        self._event_seq = 0
        self._latest_observation: ObservationSummary | None = None
        self._latest_scene_path: Path | None = None
        self._latest_screenshot_path: Path | None = None
        self._last_action: ActionOutcome | None = None
        self._last_trail: ExplorationTrail | None = None
        self._finalized = False
        self.raw = AIRawAccess(self)
        self.artifacts = AIArtifactAccess(self)
        self._ensure_manifest()

    def __enter__(self) -> AIPhone:
        if self.app:
            self._open_app(self.app)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc is not None and not isinstance(exc, AIAssertionError):
            self._write_failure(
                expected="script completed without exception",
                observed=str(exc),
                failure_class="harness_bug" if exc_type and exc_type.__module__.startswith("glassbox") else "script_bug",
                failure_source=f"exception.{exc_type.__name__ if exc_type else 'unknown'}",
            )
        self._finalize(status="failed" if exc is not None else "finished")
        return False

    def observe(self) -> ObservationSummary:
        try:
            scene = self._phone.perceive()
        except TimeoutError as exc:
            # wait_stable raises a bare TimeoutError on perpetually-animating
            # screens; the facade must not leak it into author scripts.
            # ObservationSummary cannot carry "unstable" honestly, so degrade
            # to the facade's own error type with an actionable message.
            policy = getattr(self._phone, "stability_policy", None)
            timeout_s = getattr(policy, "timeout", None)
            within = f"{float(timeout_s):g}s" if timeout_s else "the stability timeout"
            message = (
                f"screen never stabilized within {within} — animating UI? raise the "
                "stability timeout (GLASSBOX_STABLE_TIMEOUT) or set "
                "GLASSBOX_STABLE_AFTER_ACTION=0 to act on unstable frames"
            )
            failure_path = self._write_failure(
                expected="screen stabilized before observe()",
                observed=str(exc),
                failure_class="environment_drift",
                failure_source="observe.stability_timeout",
            )
            raise AIAssertionError(
                message,
                run_id=self.run_id,
                failure_path=failure_path,
                observation=self._latest_observation,
                artifacts=self.save_report(),
            ) from exc
        frame = getattr(self._phone, "last_frame", None)
        frame_id = None
        screenshot_path: Path | None = None
        scene_path: Path
        if self._store is not None:
            stored_frame = self._store.promote_frame(
                frame,
                role="ai_observe",
                stable=getattr(scene, "stable_frame", None),
                trace_level="full",
            )
            frame_id = stored_frame.frame_id if stored_frame is not None else None
            screenshot_path = self._artifact_path(stored_frame.file) if stored_frame and stored_frame.file else None
            if screenshot_path is None:
                screenshot_path = self._write_fallback_frame(frame)
            stored_scene = self._store.store_scene(scene, frame_id=frame_id, role="ai_observe")
            if stored_scene is None or stored_scene.file is None:
                scene_path = self._write_fallback_scene(scene)
            else:
                scene_path = self._artifact_path(stored_scene.file)
        else:
            screenshot_path = self._write_fallback_frame(frame)
            scene_path = self._write_fallback_scene(scene)

        visible_texts = tuple(e.text for e in scene.elements if e.text)
        actions = tuple(dict.fromkeys([*getattr(scene, "available_intents", ()), *getattr(scene, "safe_actions", ())]))
        scene_type = scene.semantic_scene_type or scene.scene_type
        page_id = scene.page_id
        can_scroll = self._can_scroll(scene)
        event_seq = self._next_event_seq()
        elements = tuple(_element_summary(element) for element in scene.elements)
        viewport_size = self._viewport_from_scene_frame(scene, frame)
        frame_context = getattr(frame, "context", None)
        coordinate_space = str(getattr(frame_context, "coordinate_space", None) or self._phone_coordinate_space())
        crop_bbox = _tuple_ints(getattr(frame_context, "crop_bbox", None), 4)
        source_shape = _tuple_ints(getattr(frame_context, "source_shape", None), 2)
        projection = getattr(frame_context, "projection", None)
        summary = self._summarize_observation(
            page_id,
            scene_type,
            visible_texts,
            can_scroll,
            scene_path,
            screenshot_path,
            n_elements=len(elements),
            viewport_size=viewport_size,
            coordinate_space=coordinate_space,
            crop_bbox=crop_bbox,
        )
        obs = ObservationSummary(
            summary=summary,
            page_id=page_id,
            scene_type=scene_type,
            visible_texts=visible_texts,
            actions=actions,
            can_scroll=can_scroll,
            screenshot_path=screenshot_path,
            scene_path=scene_path,
            event_seq=event_seq,
            elements=elements,
            viewport_size=viewport_size,
            coordinate_space=coordinate_space,
            crop_bbox=crop_bbox,
            source_shape=source_shape,
            projection=projection,
            platform_scene_kind=getattr(scene, "platform_scene_kind", None),
            current_vc=getattr(scene, "current_vc", None),
            whitebox_evaluated=bool(getattr(scene, "whitebox_evaluated", False)),
            app_state=dict(getattr(scene, "app_state", {}) or {}),
        )
        self._latest_observation = obs
        self._latest_scene_path = scene_path
        self._latest_screenshot_path = screenshot_path
        return obs

    def perceive(self, *, refresh: bool = False) -> ObservationSummary:
        if refresh or self._latest_observation is None:
            return self.observe()
        return self._latest_observation

    def elements(self, *, refresh: bool = False) -> tuple[ObservationElement, ...]:
        return self.perceive(refresh=refresh).elements

    def viewport(self, *, refresh: bool = False) -> tuple[int, int] | None:
        return self.perceive(refresh=refresh).viewport_size

    def tap(
        self,
        text: str | None = None,
        *,
        intent: str | None = None,
        expect_visible: str | Sequence[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionOutcome:
        if (text is None) == (intent is None):
            raise ValueError("tap() requires exactly one of text or intent")
        if intent is not None:
            raise NotImplementedError("tap(intent=...) is reserved for semantic intent routing and is not implemented yet")
        target = text if text is not None else intent
        assert target is not None
        # CUQ-0.3: declaring what the tap should achieve (expect_visible /
        # expect_page) threads an expected_state into the orchestrator so its
        # expected-state verification (P2) and VLM-gated escalation (P1) engage on
        # the default agent tap path — not only the Settings walkthrough. Without
        # an expectation this is byte-identical to before (expected_state=None,
        # and the post-tap _apply_expectation is a no-op).
        expected_state = _expected_state(expect_visible=expect_visible, expect_page=expect_page)
        result = self._phone.tap_text(target, expected_state=expected_state)
        outcome = self._action_outcome("tap", target, result)
        return self._apply_expectation(outcome, expect_visible=expect_visible, expect_page=expect_page)

    def tap_xy(
        self,
        x: int,
        y: int,
        *,
        coordinate_space: str | None = None,
        expect_visible: str | None = None,
        expect_page: str | None = None,
    ) -> ActionOutcome:
        kwargs = {}
        if coordinate_space is not None:
            kwargs["coordinate_space"] = coordinate_space
        result = self._phone.tap_xy(int(x), int(y), **kwargs)
        outcome = self._action_outcome("tap_xy", f"{int(x)},{int(y)}", result)
        return self._apply_expectation(outcome, expect_visible=expect_visible, expect_page=expect_page)

    def swipe_xy(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        coordinate_space: str | None = None,
        steps: int = 20,
        end_hold_ms: int = 100,
        expect_visible: str | None = None,
        expect_page: str | None = None,
        expect_timeout_s: float = _AI_DEFAULT_EXPECT_TIMEOUT_S,
        sample_interval_s: float = _AI_DEFAULT_SAMPLE_INTERVAL_S,
    ) -> ActionOutcome:
        target_texts = _text_targets(expect_visible)
        expected_state = _expected_state(expect_visible=target_texts, expect_page=expect_page)
        wait_kwargs: dict[str, Any] = {}
        if target_texts or expect_page:
            # AI: expected swipes can animate/scroll after command ack; stream frames
            # until the caller-provided target appears instead of trusting one early frame.
            wait_kwargs.update(
                settle_strategy="stream_until_match",
                expected_state=expected_state,
                expect_visible=target_texts,
                expect_page=expect_page,
                stream_timeout_ms=_seconds_to_ms(expect_timeout_s),
                sample_interval_ms=_seconds_to_ms(sample_interval_s),
                max_stream_frames=_max_frames(expect_timeout_s, sample_interval_s),
            )
        if coordinate_space is not None:
            wait_kwargs["coordinate_space"] = coordinate_space
        result = self._phone.swipe_xy(
            int(x1),
            int(y1),
            int(x2),
            int(y2),
            steps=int(steps),
            end_hold_ms=int(end_hold_ms),
            **wait_kwargs,
        )
        outcome = self._action_outcome("swipe_xy", f"{int(x1)},{int(y1)}->{int(x2)},{int(y2)}", result)
        return self._apply_expectation(
            outcome,
            expect_visible=target_texts,
            expect_page=expect_page,
            timeout_s=expect_timeout_s,
            sample_interval_s=sample_interval_s,
        )

    def scroll_wheel(
        self,
        ticks: int,
        *,
        focus_x: int | None = None,
        focus_y: int | None = None,
        coordinate_space: str | None = None,
        focus_click: bool = False,
        interval_ms: int | None = None,
        expect_visible: str | None = None,
        expect_page: str | None = None,
    ) -> ActionOutcome:
        kwargs: dict[str, Any] = {"focus_click": bool(focus_click)}
        if focus_x is not None:
            kwargs["focus_x"] = int(focus_x)
        if focus_y is not None:
            kwargs["focus_y"] = int(focus_y)
        if coordinate_space is not None:
            kwargs["coordinate_space"] = coordinate_space
        if interval_ms is not None:
            kwargs["interval_ms"] = int(interval_ms)
        result = self._phone.scroll_wheel(int(ticks), **kwargs)
        outcome = self._action_outcome("scroll_wheel", f"wheel:{int(ticks)}", result)
        return self._apply_expectation(outcome, expect_visible=expect_visible, expect_page=expect_page)

    def type_text(
        self,
        text: str,
        *,
        verify: bool | None = None,
        expect_visible: str | Sequence[str] | None = None,
        expect_page: str | None = None,
        expect_timeout_s: float = _AI_DEFAULT_EXPECT_TIMEOUT_S,
        sample_interval_s: float = _AI_DEFAULT_SAMPLE_INTERVAL_S,
    ) -> ActionOutcome:
        typed_text = str(text)
        result = self._phone.type(typed_text, verify=verify)
        outcome = self._action_outcome("type_text", typed_text, result)
        target_texts = _text_targets(expect_visible if expect_visible is not None else typed_text)
        return self._apply_expectation(
            outcome,
            expect_visible=target_texts,
            expect_page=expect_page,
            timeout_s=expect_timeout_s,
            sample_interval_s=sample_interval_s,
        )

    def key(self, modifier: int, keycode: int) -> ActionOutcome:
        result = self._phone.key(int(modifier), int(keycode))
        return self._action_outcome("key", f"{int(modifier)}:{int(keycode)}", result)

    def launch_app(
        self,
        app: str,
        *,
        aliases: tuple[str, ...] = (),
        expect_visible: str | None = None,
        expect_page: str | None = None,
    ) -> ActionOutcome:
        label, default_aliases = _APP_ALIASES.get(app, (app, ()))
        all_aliases = tuple(dict.fromkeys([*aliases, *default_aliases]))
        result = self._phone.open_app(label, aliases=all_aliases)
        outcome = self._action_outcome("launch_app", app, result)
        if expect_visible is not None or expect_page is not None:
            return self._apply_expectation(outcome, expect_visible=expect_visible, expect_page=expect_page)
        obs = self.observe()
        target_match = self._launch_target_match(app, label, all_aliases, obs)
        if target_match:
            verified = replace(
                outcome,
                semantic_status="succeeded",
                reason=target_match,
                artifact_path=obs.scene_path,
                semantic_verifier="ai_launch_verification",
                semantic_confidence=0.85,
            )
            self._last_action = verified
            return verified
        if self._looks_like_home(obs):
            failed = replace(
                outcome,
                semantic_status="failed",
                reason=f"launch target not opened; still on Home/SpringBoard for {app!r}",
                artifact_path=obs.scene_path,
                semantic_verifier="ai_launch_verification",
                semantic_confidence=0.8,
            )
            self._last_action = failed
            return failed
        unknown = replace(
            outcome,
            semantic_status="unknown",
            reason=f"launch left Home but target app could not be verified for {app!r}",
            artifact_path=obs.scene_path,
            semantic_verifier="ai_launch_verification",
            semantic_confidence=0.3,
        )
        self._last_action = unknown
        return unknown

    def goto(self, label: str, *, timeout_s: float = 10.0) -> ObservationSummary:
        if self._looks_like_page_id(label):
            outcome = self.navigate_to_page(label)
            if outcome.semantic_status == "succeeded":
                return self.perceive()
        target = self._policy_target(label, self.observe()) if self.policy is not None else label
        result = self._phone.tap_text(target, timeout=timeout_s)
        self._action_outcome("goto", target, result)
        return self.observe()

    def back(self) -> ActionOutcome:
        return self._action_outcome("back", None, self._phone.back_gesture())

    def home(self) -> ActionOutcome:
        if self._phone_backend() == "picokvm":
            close_app = getattr(self._phone, "close_foreground_app", None)
            if callable(close_app):
                return self._action_outcome("home", None, close_app())
        return self._action_outcome("home", None, self._phone.home())

    def navigate_to_page(
        self,
        page_id: str,
        *,
        scene_type: str | None = None,
        allowed_actions: set[str] | None = None,
        min_success_rate: float = 0.5,
    ) -> ActionOutcome:
        navigator = getattr(self._phone, "navigate_to_page", None)
        if callable(navigator):
            result = navigator(
                page_id,
                scene_type=scene_type,
                allowed_actions=allowed_actions,
                min_success_rate=min_success_rate,
            )
        else:
            from glassbox.action import navigate_via_memory_path

            result = navigate_via_memory_path(
                self._phone,
                page_id,
                scene_type=scene_type,
                allowed_actions=allowed_actions,
                min_success_rate=min_success_rate,
            )
        obs = self.observe()
        if getattr(result, "reached", False):
            semantic_status = "succeeded"
            confidence = 1.0
        elif not getattr(result, "attempted", False) and getattr(result, "reason", "") == "memory_unavailable":
            semantic_status = "unsupported"
            confidence = 0.0
        else:
            semantic_status = "unknown"
            confidence = 0.0
        outcome = ActionOutcome(
            ok=bool(getattr(result, "reached", False)),
            semantic_status=semantic_status,
            action="navigate_to_page",
            target=page_id,
            reason=getattr(result, "reason", None),
            artifact_path=obs.scene_path,
            transport_ok=None,
            unsupported=semantic_status == "unsupported",
            semantic_verifier="memory_path_navigation",
            semantic_confidence=confidence,
        )
        self._last_action = outcome
        return outcome

    def close_app(self) -> ActionOutcome:
        close_app = getattr(self._phone, "close_foreground_app", None)
        if not callable(close_app):
            return ActionOutcome(
                ok=False,
                semantic_status="unsupported",
                action="close_app",
                target=None,
                reason="Phone.close_foreground_app is not available",
                artifact_path=self._latest_scene_path,
                transport_ok=False,
                unsupported=True,
            )
        return self._action_outcome("close_app", None, close_app())

    def _phone_scroll(self, normalized: str, **swipe_kwargs):
        """Route a generic scroll. ``down`` means reveal-content-below
        (swipe_up / wheel_scroll_down).

        CUQ-0.1: when ``scroll`` is in the semantic-plan ops, run the first-class
        strategy ladder (wheel -> swipe) with verified-failure switching, so a
        wheel scroll that does not move the screen falls back to the swipe
        instead of silently failing. CUQ-3.15: otherwise prefer the precise wheel
        when the backend supports it and the operator opted in, else swipe-fling.
        """
        phone = self._phone
        uses_plan = getattr(phone, "uses_semantic_plan", None)
        if callable(uses_plan) and uses_plan("scroll"):
            fresh_kwargs = getattr(phone, "picokvm_fresh_verify_kwargs", None)
            fresh = fresh_kwargs("scroll") if callable(fresh_kwargs) else {}
            return phone.run_semantic_plan(
                "scroll",
                params={"direction": normalized},
                via="scroll",
                policy_action="scroll",
                **fresh,
            )
        if getattr(phone, "ai_scroll_prefer_wheel_enabled", False) and phone.supports("scroll_wheel"):
            return (
                phone.wheel_scroll_down()
                if normalized == "down"
                else phone.wheel_scroll_up()
            )
        return (
            phone.swipe_up(**swipe_kwargs)
            if normalized == "down"
            else phone.swipe_down(**swipe_kwargs)
        )

    def scroll(
        self,
        direction: str = "down",
        *,
        until: str | Sequence[str] | None = None,
        timeout_s: float = _AI_DEFAULT_SCROLL_TIMEOUT_S,
        max_steps: int | None = None,
        settle_timeout_s: float = _AI_DEFAULT_EXPECT_TIMEOUT_S,
        sample_interval_s: float = _AI_DEFAULT_SAMPLE_INTERVAL_S,
    ) -> ObservationSummary:
        """Scroll and return a post-wait observation.

        AI callers should use the returned ObservationSummary, and pass
        ``until=...`` for any app-specific target text. The API does not know
        names like "Skip Now"; it only waits for caller-provided targets.
        """
        normalized = direction.lower()
        if normalized not in {"down", "up"}:
            raise ValueError("scroll direction must be 'down' or 'up'")
        targets = _text_targets(until)
        step_limit = max(1, int(max_steps if max_steps is not None else (8 if targets else 1)))
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        obs = self.observe()
        for _idx in range(step_limit):
            if targets and self._any_target_visible(targets, obs):
                return obs
            remaining_s = max(0.0, deadline - time.monotonic()) if targets else settle_timeout_s
            if targets and remaining_s <= 0:
                return obs
            action_kwargs = self._scroll_wait_kwargs(
                targets,
                timeout_s=min(float(settle_timeout_s), remaining_s) if targets else _AI_DEFAULT_SCROLL_WINDOW_S,
                sample_interval_s=sample_interval_s,
            )
            # AI: scroll completion is judged by the observation below, not by
            # the action outcome or the first post-command screenshot.
            result = self._phone_scroll(normalized, **action_kwargs)
            self._action_outcome("scroll", ", ".join(targets) if targets else None, result)
            if targets:
                obs = self._wait_for_targets(
                    targets,
                    timeout_s=min(float(settle_timeout_s), max(0.0, deadline - time.monotonic())),
                    sample_interval_s=sample_interval_s,
                )
            else:
                obs = self.observe()
            if targets and self._any_target_visible(targets, obs):
                return obs
        return obs

    def expect_visible(self, text: str, *, timeout_s: float = 5.0) -> None:
        try:
            self._phone.expect_text(text, timeout=timeout_s)
            if self._latest_observation is None:
                self.observe()
        except AssertionError as exc:
            obs = self._safe_observe()
            failure_path = self._write_failure(
                expected=text,
                observed=", ".join(obs.visible_texts[:12]) if obs else str(exc),
                failure_class="script_bug",
                failure_source="assertion.expect_visible",
                observation=obs,
            )
            raise AIAssertionError(
                f"expected visible text {text!r}",
                run_id=self.run_id,
                failure_path=failure_path,
                observation=obs,
                artifacts=self.save_report(),
            ) from exc

    def expect_page(self, page_id: str) -> None:
        obs = self.observe()
        if obs.page_id == page_id:
            return
        failure_path = self._write_failure(
            expected=page_id,
            observed=obs.page_id or "(unknown)",
            failure_class="environment_drift",
            failure_source="assertion.expect_page",
            observation=obs,
        )
        raise AIAssertionError(
            f"expected page_id {page_id!r}, got {obs.page_id!r}",
            run_id=self.run_id,
            failure_path=failure_path,
            observation=obs,
            artifacts=self.save_report(),
        )

    def explore(self, goal: str, *, max_steps: int = 12) -> ExplorationTrail:
        steps: list[str] = []
        matched_path: list[str] = []
        decision_trace: list[DecisionTraceStep] = []
        needle = goal.strip()
        obs = self.observe()
        success = self._explore_goal_met(needle, obs)
        if success:
            matched_path.append(f"observe:{needle}")
        step_limit = max(0, int(max_steps))
        if self._looks_like_page_id(needle) and not success and step_limit > 0:
            before_obs = obs
            outcome = self.navigate_to_page(needle)
            obs = self.perceive()
            success = self._explore_goal_met(needle, obs)
            steps.append(f"1. navigate_to_page {needle}")
            matched_path.append(f"navigate_to_page:{needle}")
            decision_trace.append(
                DecisionTraceStep(
                    index=1,
                    observation_event_seq=before_obs.event_seq,
                    observed_page_id=before_obs.page_id,
                    decision_action="navigate_to_page",
                    decision_target=needle,
                    decision_reason="page_id_memory_path",
                    action_semantic_status=outcome.semantic_status,
                    verified=success,
                    verification="page_id" if success else "page_not_reached",
                    after_event_seq=obs.event_seq,
                    after_page_id=obs.page_id,
                )
            )
            if success:
                matched_path.append(f"page:{needle}")
        for idx in range(len(steps), step_limit):
            if success:
                break
            candidate = self._next_policy_candidate(obs, goal=needle)
            if candidate is not None:
                before_obs = obs
                memory_page_id = str(candidate.page_id or "").strip()
                if memory_page_id:
                    outcome = self.navigate_to_page(memory_page_id)
                    obs = self.perceive()
                    page_reached = obs.page_id == memory_page_id or outcome.semantic_status == "succeeded"
                    if page_reached:
                        success = self._explore_goal_met(needle, obs)
                        steps.append(f"{idx + 1}. navigate_to_page {memory_page_id}")
                        matched_path.append(f"navigate_to_page:{memory_page_id}")
                        decision_trace.append(
                            DecisionTraceStep(
                                index=idx + 1,
                                observation_event_seq=before_obs.event_seq,
                                observed_page_id=before_obs.page_id,
                                decision_action="navigate_to_page",
                                decision_target=memory_page_id,
                                decision_reason=candidate.reason or "policy_candidate_page_id",
                                action_semantic_status=outcome.semantic_status,
                                verified=success,
                                verification="visible_goal" if success else "page_id",
                                after_event_seq=obs.event_seq,
                                after_page_id=obs.page_id,
                            )
                        )
                        if success:
                            matched_path.append(f"visible:{needle}")
                            break
                        if self._policy_should_stop(obs, steps=len(steps), found=success):
                            break
                        continue
                    before_obs = obs
                result = self._execute_candidate(candidate)
                outcome = self._action_outcome(f"explore.{candidate.action}", candidate.label, result)
                decision_action = candidate.action
                decision_target = candidate.label
                decision_reason = candidate.reason or "policy_candidate"
                steps.append(f"{idx + 1}. {candidate.action} {candidate.label}")
                matched_path.append(f"{candidate.action}:{candidate.label}")
            else:
                result = self._phone_scroll("down")
                outcome = self._action_outcome("explore.scroll", needle, result)
                decision_action = "scroll"
                decision_target = "down"
                decision_reason = "no_safe_policy_candidate"
                steps.append(f"{idx + 1}. scroll down")
                before_obs = obs
            obs = self.observe()
            success = self._explore_goal_met(needle, obs)
            decision_trace.append(
                DecisionTraceStep(
                    index=idx + 1,
                    observation_event_seq=before_obs.event_seq,
                    observed_page_id=before_obs.page_id,
                    decision_action=decision_action,
                    decision_target=decision_target,
                    decision_reason=decision_reason,
                    action_semantic_status=outcome.semantic_status,
                    verified=success,
                    verification="visible_goal" if success else "goal_not_visible",
                    after_event_seq=obs.event_seq,
                    after_page_id=obs.page_id,
                )
            )
            if success:
                if candidate is None:
                    matched_path.append("scroll:down")
                matched_path.append(f"visible:{needle}")
                break
            if self._policy_should_stop(obs, steps=len(steps), found=success):
                break
        artifact_path = self._write_trail(needle, success, steps, matched_path, obs, decision_trace)
        trail = ExplorationTrail(
            goal=goal,
            success=success,
            steps=tuple(steps),
            final_observation=obs,
            matched_path=tuple(matched_path),
            artifact_path=artifact_path,
            decision_trace=tuple(decision_trace),
        )
        self._last_trail = trail
        return trail

    def save_path_as(self, name: str) -> PathArtifact:
        if self._last_trail is None:
            raise RuntimeError("save_path_as() requires a successful explore() trail first")
        paths_dir = self.run_dir / "paths"
        paths_dir.mkdir(exist_ok=True)
        safe_name = _safe_name(name)
        path = paths_dir / f"{safe_name}.json"
        snippet_path = paths_dir / f"{safe_name}.py"
        steps = self._last_trail.matched_path or self._last_trail.steps
        path.write_text(
            json.dumps(
                {
                    "name": name,
                    "run_id": self.run_id,
                    "goal": self._last_trail.goal,
                    "success": self._last_trail.success,
                    "steps": list(steps),
                    "source_trail_path": str(self._last_trail.artifact_path.relative_to(self.run_dir)),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        snippet_path.write_text(_script_snippet(name, steps), encoding="utf-8")
        return PathArtifact(
            name=name,
            run_id=self.run_id,
            path=path,
            steps=tuple(steps),
            source_trail_path=self._last_trail.artifact_path,
            script_snippet_path=snippet_path,
        )

    def save_report(self) -> RunArtifacts:
        self._write_report()
        return self._run_artifacts()

    def update_manifest(self, payload: Mapping[str, Any]) -> None:
        data = dict(payload)
        if self._store is not None:
            self._store.update_manifest(data)
            return
        path = self._manifest_path()
        current: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                current = loaded
        current.update(data)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _open_app(self, app: str) -> None:
        if hasattr(self._phone, "open_app"):
            self.launch_app(app)

    def _next_event_seq(self) -> int:
        self._event_seq += 1
        return self._event_seq

    def _action_outcome(self, action: str, target: str | None, result: ActionResult) -> ActionOutcome:
        semantic_status, reason = self._facade_semantic_status(result)
        outcome = ActionOutcome(
            ok=bool(result.ok),
            semantic_status=semantic_status,
            action=action,
            target=target,
            reason=reason,
            artifact_path=self._latest_scene_path,
            transport_ok=bool(result.ok),
            unsupported=bool(result.unsupported),
            semantic_verifier=result.semantic_verifier,
            semantic_confidence=result.semantic_confidence,
        )
        self._last_action = outcome
        return outcome

    def _facade_semantic_status(self, result: ActionResult) -> tuple[str, str | None]:
        status = result.semantic_status
        reason = result.semantic_reason or result.error
        if status == "succeeded" and result.semantic_verifier == "scene_progressed":
            return "unknown", f"visual progress only; semantic target not proven ({reason or 'scene_progressed'})"
        if status is not None:
            return str(status), reason
        if result.unsupported:
            return "unsupported", reason
        return ("unknown" if result.ok else "failed"), reason

    def _apply_expectation(
        self,
        outcome: ActionOutcome,
        *,
        expect_visible: str | Sequence[str] | None,
        expect_page: str | None,
        timeout_s: float = _AI_DEFAULT_EXPECT_TIMEOUT_S,
        sample_interval_s: float = _AI_DEFAULT_SAMPLE_INTERVAL_S,
    ) -> ActionOutcome:
        targets = _text_targets(expect_visible)
        if not targets and expect_page is None:
            return outcome
        obs = self._wait_for_expectation(
            targets,
            expect_page=expect_page,
            timeout_s=timeout_s,
            sample_interval_s=sample_interval_s,
        )
        if targets and not self._any_target_visible(targets, obs):
            updated = replace(
                outcome,
                semantic_status="unknown",
                reason=f"expected visible text not observed after action: {', '.join(targets)}",
                semantic_verifier="ai_expectation",
                semantic_confidence=0.0,
            )
            self._last_action = updated
            return updated
        if expect_page is not None and obs.page_id != expect_page:
            updated = replace(
                outcome,
                semantic_status="unknown",
                reason=f"expected page_id {expect_page!r}, got {obs.page_id!r}",
                semantic_verifier="ai_expectation",
                semantic_confidence=0.0,
            )
            self._last_action = updated
            return updated
        verified = replace(
            outcome,
            semantic_status="succeeded",
            reason="AI facade expectation matched",
            artifact_path=obs.scene_path,
            semantic_verifier="ai_expectation",
            semantic_confidence=1.0,
        )
        self._last_action = verified
        return verified

    def _scroll_wait_kwargs(
        self,
        targets: tuple[str, ...],
        *,
        timeout_s: float,
        sample_interval_s: float,
    ) -> dict[str, Any]:
        if targets:
            return {
                "settle_strategy": "stream_until_match",
                "expected_state": _expected_state(expect_visible=targets),
                "expect_visible": targets,
                "stream_timeout_ms": _seconds_to_ms(timeout_s),
                "sample_interval_ms": _seconds_to_ms(sample_interval_s),
                "max_stream_frames": _max_frames(timeout_s, sample_interval_s),
            }
        return {
            "settle_strategy": "transient_window",
            "window_duration_ms": _seconds_to_ms(timeout_s),
            "sample_interval_ms": _seconds_to_ms(sample_interval_s),
            "max_stream_frames": _max_frames(timeout_s, sample_interval_s),
        }

    def _wait_for_expectation(
        self,
        targets: tuple[str, ...],
        *,
        expect_page: str | None,
        timeout_s: float,
        sample_interval_s: float,
    ) -> ObservationSummary:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        obs = self.observe()
        while not self._expectation_met(targets, expect_page=expect_page, obs=obs) and time.monotonic() < deadline:
            time.sleep(max(0.01, float(sample_interval_s)))
            obs = self.observe()
        return obs

    def _wait_for_targets(
        self,
        targets: tuple[str, ...],
        *,
        timeout_s: float,
        sample_interval_s: float,
    ) -> ObservationSummary:
        return self._wait_for_expectation(
            targets,
            expect_page=None,
            timeout_s=timeout_s,
            sample_interval_s=sample_interval_s,
        )

    def _expectation_met(
        self,
        targets: tuple[str, ...],
        *,
        expect_page: str | None,
        obs: ObservationSummary,
    ) -> bool:
        if targets and not self._any_target_visible(targets, obs):
            return False
        return not (expect_page is not None and obs.page_id != expect_page)

    def _any_target_visible(self, targets: tuple[str, ...], obs: ObservationSummary) -> bool:
        return any(self._goal_visible(target, obs) for target in targets)

    def _artifact_path(self, rel_file: str | None) -> Path | None:
        return self.run_dir / rel_file if rel_file else None

    def _write_fallback_frame(self, frame: Any) -> Path | None:
        if frame is None or getattr(frame, "img", None) is None:
            return None
        path = self._fallback_frames_dir / f"ai_observe_{self._event_seq:06d}.png"
        try:
            import cv2

            if cv2.imwrite(str(path), frame.img):
                return path
        except Exception:
            return None
        return None

    def _write_fallback_scene(self, scene: Any) -> Path:
        path = self._fallback_scenes_dir / f"ai_observe_{self._event_seq:06d}.json"
        payload = scene.model_dump(mode="json") if hasattr(scene, "model_dump") else {"scene": str(scene)}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _resolve_artifact_path(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.run_dir / path
        resolved = candidate.resolve()
        root = self.run_dir.resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError(f"artifact path escapes run dir: {path}")
        return resolved

    def _ensure_manifest(self) -> None:
        payload = {
            "ai_api_version": AI_API_VERSION,
            "ai_api_artifact_schema_supported": [SUPPORTED_ARTIFACT_SCHEMA_VERSION],
            "run_name": self.run_name,
            "app": self.app,
        }
        if self._store is not None:
            self._store.update_manifest(payload)
            return
        manifest = {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "app": self.app,
            "artifact_schema_version": SUPPORTED_ARTIFACT_SCHEMA_VERSION,
            **payload,
        }
        self._manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    def _policy_target(self, label: str, obs: ObservationSummary) -> str:
        candidate = self._matching_policy_candidate(label, obs)
        if candidate is None:
            if self._text_visible(label, obs):
                synthetic = NavigationCandidate(label=label, action="tap", confidence=0.0, reason="visible_requested_label")
                if self._policy_is_safe(synthetic, obs):
                    return label
                raise ValueError(f"policy rejected navigation target: {label}")
            return label
        if not self._policy_is_safe(candidate, obs):
            raise ValueError(f"policy rejected navigation target: {candidate.label}")
        if candidate.action != "tap":
            raise ValueError(f"goto() only supports tap candidates, got {candidate.action!r}")
        return candidate.label

    @staticmethod
    def _looks_like_page_id(label: str) -> bool:
        value = label.strip()
        if "/" not in value or any(ch.isspace() for ch in value):
            return False
        parts = value.split("/")
        return len(parts) >= 2 and all(parts)

    def _matching_policy_candidate(self, label: str, obs: ObservationSummary) -> NavigationCandidate | None:
        for candidate in self._policy_candidates(obs):
            if self._labels_match(candidate.label, label):
                return candidate
        return None

    def _next_policy_candidate(self, obs: ObservationSummary, *, goal: str) -> NavigationCandidate | None:
        candidates = [
            candidate
            for candidate in self._policy_candidates(obs)
            if self._policy_is_safe(candidate, obs)
        ]
        if not candidates:
            return None
        exact = [candidate for candidate in candidates if self._labels_match(candidate.label, goal)]
        if exact:
            return max(exact, key=lambda item: item.confidence)
        tap_candidates = [candidate for candidate in candidates if candidate.action == "tap"]
        if tap_candidates:
            return max(tap_candidates, key=lambda item: item.confidence)
        return max(candidates, key=lambda item: item.confidence)

    def _policy_candidates(self, obs: ObservationSummary) -> list[NavigationCandidate]:
        if self.policy is None or not hasattr(self.policy, "candidates"):
            return []
        candidates = self.policy.candidates(obs)
        return [candidate for candidate in candidates if isinstance(candidate, NavigationCandidate)]

    def _policy_is_safe(self, candidate: NavigationCandidate, obs: ObservationSummary) -> bool:
        if self.policy is None or not hasattr(self.policy, "is_safe"):
            return True
        return bool(self.policy.is_safe(candidate, obs))

    def _policy_should_stop(self, obs: ObservationSummary, *, steps: int, found: bool) -> bool:
        if self.policy is None or not hasattr(self.policy, "should_stop"):
            return False
        page_id = obs.page_id
        if hasattr(self.policy, "classify"):
            page_info = self.policy.classify(obs)
            page_id = page_info.page_id or page_id
        state = CrawlState(
            steps=steps,
            visited_pages=tuple([page_id] if page_id else []),
            found=found,
        )
        return bool(self.policy.should_stop(state))

    def _execute_candidate(self, candidate: NavigationCandidate) -> ActionResult:
        action = candidate.action
        if action == "tap":
            return self._phone.tap_text(candidate.label)
        if action in {"scroll", "scroll_down", "swipe_up"}:
            return self._phone_scroll("down")
        if action in {"scroll_up", "swipe_down"}:
            return self._phone_scroll("up")
        raise ValueError(f"unsupported policy action: {action}")

    def _safe_observe(self) -> ObservationSummary | None:
        try:
            return self.observe()
        except Exception:
            return self._latest_observation

    def _write_failure(
        self,
        *,
        expected: str,
        observed: str,
        failure_class: str,
        failure_source: str,
        observation: ObservationSummary | None = None,
    ) -> Path:
        observation = observation or self._latest_observation
        path = self.run_dir / "failure.md"
        attribution = self._actuation_attribution()
        lines = [
            "# Failure",
            "",
            f"Task: {self.run_name or self.app or 'AI glassbox run'}",
            f"Expected: {expected}",
            f"Observed page: {observation.page_id if observation else '(unknown)'}",
            f"Observed: {observed}",
            f"Last action: {self._last_action.action if self._last_action else '(none)'}",
            f"Failure class: {failure_class}",
            "Failure confidence: 0.50",
            f"Failure source: {failure_source}",
            f"Actuation attribution: {attribution}",
            "Actuation evidence: see audit.jsonl and actuation_report.json when present",
            "",
            "Run ledger:",
            f"- review timeline: {self._maybe_rel('review_timeline.json')}",
            f"- action rows: {self._maybe_rel('actions.jsonl')}",
            f"- after scene: {self._rel(observation.scene_path) if observation else '(none)'}",
            f"- screenshot: {self._rel(observation.screenshot_path) if observation and observation.screenshot_path else '(none)'}",
            f"- audit stream: {self._maybe_rel('audit.jsonl')}",
            f"- actuation events: {self._maybe_rel('audit.jsonl')}",
            "",
            "Suggested next checks:",
            "- inspect OCR text in the after scene JSON",
            "- inspect action/verifier output in the run ledger",
            "- decide whether policy label mapping, OCR matching, or actuation is wrong",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_report(self) -> Path:
        path = self.run_dir / "report.md"
        obs = self._latest_observation
        lines = [
            "# AI Glassbox Run Report",
            "",
            f"Run: `{self.run_id}`",
            f"Name: {self.run_name or '(none)'}",
            f"AI API: `{AI_API_VERSION}`",
            "",
        ]
        if obs is not None:
            lines.extend([
                "## Latest Observation",
                "",
                obs.summary,
                "",
                f"- scene: `{self._rel(obs.scene_path)}`",
                f"- screenshot: `{self._rel(obs.screenshot_path) if obs.screenshot_path else '(none)'}`",
                "",
            ])
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_trail(
        self,
        goal: str,
        success: bool,
        steps: list[str],
        matched_path: list[str],
        observation: ObservationSummary,
        decision_trace: list[DecisionTraceStep],
    ) -> Path:
        trails_dir = self.run_dir / "exploration"
        trails_dir.mkdir(exist_ok=True)
        path = trails_dir / f"trail_{len(list(trails_dir.glob('trail_*.json'))):03d}.json"
        path.write_text(
            json.dumps(
                {
                    "goal": goal,
                    "success": success,
                    "steps": steps,
                    "matched_path": matched_path,
                    "decision_trace": [
                        {
                            "index": step.index,
                            "observation_event_seq": step.observation_event_seq,
                            "observed_page_id": step.observed_page_id,
                            "decision_action": step.decision_action,
                            "decision_target": step.decision_target,
                            "decision_reason": step.decision_reason,
                            "action_semantic_status": step.action_semantic_status,
                            "verified": step.verified,
                            "verification": step.verification,
                            "after_event_seq": step.after_event_seq,
                            "after_page_id": step.after_page_id,
                        }
                        for step in decision_trace
                    ],
                    "final_observation": {
                        "summary": observation.summary,
                        "page_id": observation.page_id,
                        "scene_path": str(self._rel(observation.scene_path)),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _finalize(self, *, status: str) -> None:
        if self._finalized:
            return
        with _suppress_all():
            self._write_report()
        with _suppress_all():
            self._runtime.close(save_memory=True)
        self._finalized = True

    def _run_artifacts(self) -> RunArtifacts:
        manifest = self._manifest_path()
        return RunArtifacts(
            run_id=self.run_id,
            run_name=self.run_name,
            run_dir=self.run_dir,
            manifest_path=manifest,
            report_path=self.run_dir / "report.md" if (self.run_dir / "report.md").exists() else None,
            failure_path=self.run_dir / "failure.md" if (self.run_dir / "failure.md").exists() else None,
            latest_scene_path=self._latest_scene_path,
            latest_screenshot_path=self._latest_screenshot_path,
            artifact_schema_version=SUPPORTED_ARTIFACT_SCHEMA_VERSION,
            ai_api_version=AI_API_VERSION,
        )

    def _summarize_observation(
        self,
        page_id: str | None,
        scene_type: str | None,
        visible_texts: tuple[str, ...],
        can_scroll: bool | None,
        scene_path: Path,
        screenshot_path: Path | None,
        *,
        n_elements: int,
        viewport_size: tuple[int, int] | None,
        coordinate_space: str,
        crop_bbox: tuple[int, int, int, int] | None,
    ) -> str:
        label = page_id or scene_type or "Observed screen"
        rows = ", ".join(visible_texts[:8]) if visible_texts else "(no visible text)"
        scroll = "unknown" if can_scroll is None else str(can_scroll)
        viewport = f"{viewport_size[0]}x{viewport_size[1]}" if viewport_size else "unknown"
        crop = crop_bbox if crop_bbox is not None else "none"
        parts = [
            f"{label}. Visible text: {rows}.",
            f"page_id={page_id}, scene_type={scene_type}, can_scroll={scroll}, elements={n_elements}.",
            f"coordinate_space={coordinate_space}, viewport={viewport}, crop_bbox={crop}.",
            f"Artifacts: {self._rel(scene_path)}",
        ]
        if screenshot_path is not None:
            parts[-1] += f", {self._rel(screenshot_path)}"
        parts[-1] += "."
        return " ".join(parts)

    def _viewport_from_scene_frame(self, scene: Any, frame: Any) -> tuple[int, int] | None:
        viewport = getattr(scene, "viewport_size", None)
        if viewport is not None:
            return tuple(int(v) for v in viewport)
        if frame is not None and getattr(frame, "img", None) is not None:
            h, w = frame.img.shape[:2]
            return int(w), int(h)
        viewport_size = getattr(self._phone, "viewport_size", None)
        if callable(viewport_size):
            try:
                w, h = viewport_size()
                return int(w), int(h)
            except Exception:
                return None
        return None

    def _phone_coordinate_space(self) -> str:
        coordinate_space = getattr(self._phone, "effector_coordinate_space", None)
        if callable(coordinate_space):
            try:
                return str(coordinate_space())
            except Exception:
                pass
        return "frame_px"

    def _phone_backend(self) -> str:
        backend = getattr(self._phone, "effector_backend", None)
        if callable(backend):
            try:
                return str(backend())
            except Exception:
                return ""
        return ""

    def _launch_target_match(
        self,
        app: str,
        label: str,
        aliases: tuple[str, ...],
        obs: ObservationSummary,
    ) -> str | None:
        labels = {value.strip().casefold() for value in (app, label, *aliases) if value.strip()}
        if labels & {"settings", "设置", "com.apple.preferences"}:
            if (obs.page_id or "").startswith("settings/"):
                return f"Settings page verified by page_id={obs.page_id}"
            if "settings" in str(obs.scene_type or "").casefold():
                return f"Settings page verified by scene_type={obs.scene_type}"
        profile = getattr(self._phone, "profile", None)
        profile_name = str(getattr(getattr(profile, "app", None), "name", "") or "").casefold()
        profile_bundle = str(getattr(getattr(profile, "app", None), "bundle_id", "") or "").casefold()
        if obs.current_vc and (not labels or profile_name in labels or profile_bundle in labels):
            return f"profile current_vc verified: {obs.current_vc}"
        if obs.whitebox_evaluated and (not labels or profile_name in labels or profile_bundle in labels):
            return "profile whitebox evaluated on launched screen"
        for text in obs.visible_texts:
            text_key = text.strip().casefold()
            if text_key in labels:
                return f"target label visible: {text}"
        return None

    def _looks_like_home(self, obs: ObservationSummary) -> bool:
        if obs.platform_scene_kind == "springboard":
            return True
        markers = {"app store", "照片", "相机", "日历", "天气", "钱包", "时钟", "facetime", "设置"}
        visible = {text.strip().casefold() for text in obs.visible_texts}
        return len(markers & visible) >= 3

    def _can_scroll(self, scene: Any) -> bool | None:
        safe_actions = set(getattr(scene, "safe_actions", ()) or ())
        if "scroll" in safe_actions or "swipe_up" in safe_actions or "swipe_down" in safe_actions:
            return True
        for element in getattr(scene, "elements", ()) or ():
            if any(action in {"swipe_up", "swipe_down"} for action in getattr(element, "suggested_actions", ())):
                return True
        return None

    def _goal_visible(self, goal: str, obs: ObservationSummary) -> bool:
        return any(self._labels_match(text, goal) for text in obs.visible_texts)

    def _explore_goal_met(self, goal: str, obs: ObservationSummary) -> bool:
        if self._looks_like_page_id(goal):
            return obs.page_id == goal
        return self._goal_visible(goal, obs)

    def _text_visible(self, text: str, obs: ObservationSummary) -> bool:
        return any(self._labels_match(visible, text) for visible in obs.visible_texts)

    def _labels_match(self, left: str, right: str) -> bool:
        lhs = left.strip().casefold()
        rhs = right.strip().casefold()
        return bool(lhs and rhs and (lhs == rhs or lhs in rhs or rhs in lhs))

    def _actuation_attribution(self) -> str:
        report_path = self.run_dir / "actuation_report.json"
        if not report_path.exists():
            return "unknown"
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "unknown"
        labels = payload.get("group_labels") or payload.get("attempt_labels") or {}
        if not labels:
            return "unknown"
        return max(labels.items(), key=lambda item: item[1])[0]

    def _maybe_rel(self, name: str) -> str:
        path = self.run_dir / name
        return name if path.exists() else f"{name} (missing)"

    def _rel(self, path: Path | None) -> str:
        if path is None:
            return "(none)"
        try:
            return str(path.relative_to(self.run_dir))
        except ValueError:
            return str(path)


def open_phone(
    *,
    app: str | None = None,
    policy: Any = None,
    profile_bundle: str | None = None,
    profiles_dir: str | Path | None = None,
    record: bool = True,
    memory: bool = True,
    run_name: str | None = None,
    wait: bool = False,
    timeout_s: float | None = None,
) -> AIPhone:
    """Open an AI-facing phone handle.

    The AI facade enables stable post-action observations by default so scripts
    do not accidentally reason from a too-early action frame. Set
    GLASSBOX_STABLE_AFTER_ACTION explicitly to override that behavior.
    """
    if timeout_s is not None and not wait:
        raise ValueError("timeout_s is only meaningful when wait=True")
    cfg = _ai_config(record=record, memory=memory)
    source = make_source(cfg=cfg)
    profile = _load_profile(profile_bundle, profiles_dir=profiles_dir)
    runtime = build_phone(source=source, cfg=cfg, profile=profile)
    return AIPhone(runtime, run_name=run_name, app=app, policy=policy)


def _ai_config(*, record: bool, memory: bool) -> AgentConfig:
    cfg = get_config()
    artifact_root = os.environ.get("GLASSBOX_AI_ARTIFACT_DIR") or cfg.computer_use_artifact_dir or "artifacts"
    updates: dict[str, Any] = {
        "computer_use_artifact_dir": str(artifact_root),
        "enable_memory": bool(memory),
        "action_fail_fast": False,
    }
    if "GLASSBOX_STABLE_AFTER_ACTION" not in os.environ:
        updates["stable_after_action"] = True
    if "GLASSBOX_STABLE_TIMEOUT" not in os.environ:
        updates["stable_timeout"] = max(float(cfg.stable_timeout), _AI_DEFAULT_STABLE_TIMEOUT_S)
    if "GLASSBOX_STABLE_CONSECUTIVE" not in os.environ:
        updates["stable_consecutive"] = max(int(cfg.stable_consecutive), _AI_DEFAULT_STABLE_CONSECUTIVE)
    if record and not cfg.recording_dir:
        updates["recording_dir"] = str(Path(artifact_root) / "recordings")
    return cfg.model_copy(update=updates)


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return safe or "path"


def _load_profile(bundle_id: str | None, *, profiles_dir: str | Path | None = None):
    if not bundle_id:
        return None
    from glassbox.profile import ProfileRegistry

    root = Path(profiles_dir or Path(__file__).resolve().parents[1] / "profiles")
    registry = ProfileRegistry()
    registry.load_dir(root, strict=False)
    return registry.get(bundle_id)


def _tuple_ints(value: Any, length: int) -> tuple[int, ...] | None:
    if value is None:
        return None
    try:
        items = tuple(int(v) for v in value)
    except TypeError:
        return None
    return items if len(items) == length else None


def _text_targets(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    items = (value,) if isinstance(value, str) else tuple(str(item) for item in value)
    return tuple(dict.fromkeys(item.strip() for item in items if item.strip()))


def _expected_state(
    *,
    expect_visible: str | Sequence[str] | None = None,
    expect_page: str | None = None,
) -> dict[str, Any] | None:
    targets = _text_targets(expect_visible)
    if targets:
        return {"kind": "visible_text", "payload": {"any_of": list(targets)}}
    if expect_page:
        return {"kind": "page_id", "payload": {"page_id": expect_page}}
    return None


def _seconds_to_ms(value: float) -> int:
    return max(1, int(float(value) * 1000))


def _max_frames(timeout_s: float, sample_interval_s: float) -> int:
    interval_ms = _seconds_to_ms(sample_interval_s)
    return max(1, int(_seconds_to_ms(timeout_s) / interval_ms) + 1)


def _element_summary(element: Any) -> ObservationElement:
    box = element.box
    hint = getattr(element, "whitebox_hint", None)
    if hint is not None and hasattr(hint, "model_dump"):
        hint_payload = hint.model_dump(mode="json")
    else:
        hint_payload = hint if isinstance(hint, dict) else None
    preferred = getattr(element, "preferred_tap_point", None)
    return ObservationElement(
        element_id=int(getattr(element, "element_id", 0) or 0),
        type=str(getattr(element, "type", "unknown")),
        text=getattr(element, "text", None),
        confidence=float(getattr(element, "confidence", 0.0) or 0.0),
        box=ElementBox(
            x=int(box.x),
            y=int(box.y),
            w=int(box.w),
            h=int(box.h),
            center=(int(box.center[0]), int(box.center[1])),
        ),
        suggested_actions=tuple(str(action) for action in (getattr(element, "suggested_actions", ()) or ())),
        intent_label=getattr(element, "intent_label", None),
        preferred_tap_point=tuple(int(v) for v in preferred) if preferred is not None else None,
        whitebox_hint=hint_payload,
    )


def _script_snippet(name: str, steps: tuple[str, ...] | list[str]) -> str:
    lines = [
        "from glassbox.ai import open_phone",
        "",
        "",
        f"def run_{_safe_name(name)}():",
        "    with open_phone() as phone:",
        "        # AI: trust returned observations, not raw action frames; scroll can settle late.",
    ]
    for step in steps:
        text = str(step)
        if text.startswith("visible:"):
            lines.append(f"        phone.expect_visible({text.removeprefix('visible:')!r})")
        elif text.startswith("observe:"):
            lines.append("        phone.observe()")
        elif text.startswith("scroll:down"):
            lines.append("        phone.scroll('down')")
        elif text.startswith("scroll:up"):
            lines.append("        phone.scroll('up')")
        else:
            lines.append(f"        # {text}")
    return "\n".join(lines) + "\n"


class _suppress_all:
    def __enter__(self):
        return None

    def __exit__(self, *_exc):
        return True
