"""glassbox/phone.py — the main object for walkthrough scripts

Integrates perception (frame source + OCR + heuristic typer) + cognition
(Kimi VLM) + effector (HID bridge) + profile (white-box hints) +
observability (recorder), exposing a high-level API:

    phone.snapshot()                # grab a frame
    phone.perceive()                # OCR + Layer 2 → Scene
    phone.describe(scene_hint=...)  # Layer 3 Kimi populates intent_label

    phone.find_text("登录")
    phone.expect_text("登录")
    phone.expect_no_text("加载中")

    phone.tap_text("登录")           # Layer 1 string match
    phone.tap_button("登录")         # Layer 2 typed-filter
    phone.tap_intent("确认登录")     # Layer 3 semantic label
    phone.tap_xy(x, y)               # absolute coordinates
    phone.wheel_scroll_down() / wheel_scroll_up()  # wheel scroll
    phone.swipe_up() / swipe_down()  # touch swipe gestures
    phone.swipe_left() / swipe_right() # horizontal page gestures
    phone.home()                     # iOS system gesture
    phone.recents()                  # App Switcher
    phone.control_center()           # Control Center
    phone.notification_center()      # Notification Center

Phone is decoupled from pytest — the fixture assembles it, and a probe can
also instantiate it directly.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from glassbox.action.actuation import (
    ActuationCommand,
    ActuationPlan,
    CandidatePointGenerator,
    Point,
    Rect,
    control_bucket_for_element,
    target_identity_for_element,
)
from glassbox.boundaries import AppLaunchTarget
from glassbox.boundaries import SceneClassifier as PlatformSceneClassifier
from glassbox.cognition import (
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    AppleVisionOCR,
    Box,
    HeuristicTyper,
    Scene,
    SceneClassification,
    UIElement,
    find_button,
    find_by_intent,
    find_text,
)
from glassbox.cognition.coldstart import apply_annotation_to_scene
from glassbox.cognition.ocr_contract import ocr_results_to_elements
from glassbox.cognition.vlm_kimi import enrich_scene
from glassbox.effector import NOOP_CAPABILITIES, BackendCapabilities
from glassbox.perception.app_viewport import (
    ViewportCrop,
    detect_iphone_compat_viewport,
    detected_viewport_needs_update,
)

if TYPE_CHECKING:
    import numpy as np

    from glassbox.action.orchestrator import ActionOrchestrator
    from glassbox.effector import ActionResult
    from glassbox.memory.schema import ActionRecord
    from glassbox.obs.recorder import Recorder
    from glassbox.perception.letterbox import LetterboxCrop
    from glassbox.perception.source import Frame
    from glassbox.perception.stable import StabilityPolicy
    from glassbox.profile import Profile

SceneClassifier = Callable[["Scene", tuple[int, int] | None], SceneClassification | None]


@dataclass(frozen=True)
class PhoneGestureConfig:
    wheel_ticks_per_scroll: int = 90
    wheel_invert: bool = False


def _add_optional_action_metadata(target: dict[str, Any], **items: Any) -> None:
    for key, value in items.items():
        if value is not None:
            target[key] = value


# HID modifiers / keycodes used by the keyboard helpers.
_MOD_META_LEFT = 0x08
_MOD_CTRL = 0x01    # ⌃ (left Control)
_KEY_A = 0x04
_KEY_RETURN = 0x28
_KEY_SPACE = 0x2C
_KEY_DELETE = 0x2A  # backspace
_KEY_ESC = 0x29

# A retry re-grounds (re-locates) the target and taps its current position only
# when it has drifted more than this (Manhattan, frame px) from where it was
# first seen; smaller misses keep the candidate-point progression.
_REGROUND_MIN_SHIFT_PX = 24

# GlassboxHelper's Home-screen icon name — for the CJK clipboard A-dance.
_HIDGLASSBOX_LABELS = ("GlassboxHelper",)


def _is_ascii(text: str) -> bool:
    """True if every character can be expressed as a HID keycode (ASCII)."""
    return all(ord(ch) < 128 for ch in text)


class Phone:
    """Unified entry point called by walkthrough scripts. Integrates
    perception + cognition + effector + profile + obs.

    crop:
        LetterboxCrop. When set, snapshot() automatically crops the source
        frame to the content area, so subsequent OCR / Kimi only see the
        cropped frame. The tap_* family automatically applies a coordinate
        transform from cropped coords to iPhone logical coords before
        calling the effector. Unset (None) → pass-through (legacy behavior).
    perceive_cache_diff:
        Scene cache threshold. During perceive(), if the mean absdiff
        between the current frame and the last OCR'd frame is below this
        value, the previous Scene is reused directly (elements / typing /
        intent_label all preserved), saving ~80ms of OCR plus any Kimi
        describe already run. 0.0 = disable the cache.
    """

    def __init__(
        self,
        source,
        ocr: AppleVisionOCR,
        effector,
        profile: Profile | None = None,
        typer: HeuristicTyper | None = None,
        kimi=None,
        recorder: Recorder | None = None,
        memory=None,
        crop: LetterboxCrop | None = None,
        coordinate_space: str | None = None,
        stability_policy: StabilityPolicy | None = None,
        perceive_cache_diff: float = 0.005,
        scene_classifiers: list[SceneClassifier] | None = None,
        platform_scene_classifier: PlatformSceneClassifier | None = None,
        coldstart=None,
        action_fail_fast: bool = True,
        action_orchestrator: ActionOrchestrator | None = None,
        app_labels: tuple[str, ...] | None = None,
        icon_map=None,
        safe_area_provider=None,
        springboard_provider=None,
        recovery_provider=None,
        device_geometry=None,
        gesture_config: PhoneGestureConfig | None = None,
        app_viewport: ViewportCrop | None = None,
        app_viewport_mode: str = "auto",
        default_observation_scope: str = "device",
        auto_refresh_letterbox_crop: bool = False,
        semantic_plan_ops: frozenset[str] | None = None,
        detect_icons_in_perceive: bool = False,
    ):
        self.source = source
        self.ocr = ocr
        self.effector = effector
        self.profile = profile
        self.typer = typer
        self.kimi = kimi
        self.recorder = recorder
        self.memory = memory               # ScreenMemory | None — UTG screen memory
        self.coldstart = coldstart         # ColdStartAnnotator | None — cold-start VLM annotation
        self.crop = crop
        self.auto_refresh_letterbox_crop = bool(auto_refresh_letterbox_crop)
        self.coordinate_space = coordinate_space or "auto"
        self.stability_policy = stability_policy
        self.perceive_cache_diff = perceive_cache_diff
        self.scene_classifiers = list(scene_classifiers or [])
        self._platform_scene_classifier = platform_scene_classifier
        self.action_fail_fast = action_fail_fast
        self.action_orchestrator = action_orchestrator
        # CUQ-0.1/0.8: ops routed through the first-class SemanticActionPlan
        # strategy ladder (verified-failure -> switch to next primitive) instead
        # of the legacy single-strategy path. Empty by default; flag-gated.
        self._semantic_plan_ops = frozenset(semantic_plan_ops or ())
        # CUQ-2.1: inject no-text icon regions into perceive() so icon-only
        # controls become tap candidates. Flag-gated (default off).
        self._detect_icons_in_perceive = bool(detect_icons_in_perceive)
        # CUQ-2.9: how the most recent target was resolved (ocr vs vlm), stamped
        # into the next tap's metadata so selection_source is recorded at
        # selection time rather than inferred post-hoc.
        self._last_selection_source: str = "ocr"
        # CJK type() routes through the clipboard; the A-dance foregrounds apps
        # via HID (opening from the Home screen), needing the controlled app's
        # Home-screen name(s) and a springboard icon map.
        self.app_labels = app_labels
        self.icon_map = icon_map
        self.safe_area_provider = safe_area_provider
        self.springboard_provider = springboard_provider
        self.recovery_provider = recovery_provider
        self.device_geometry = device_geometry
        self.gesture_config = gesture_config or PhoneGestureConfig()
        self.app_viewport = app_viewport
        self.app_viewport_mode = str(app_viewport_mode or "auto").strip().lower()
        self.default_observation_scope = self._normalize_observation_scope(default_observation_scope)
        self._cjk_foreground_settle_s = 2.0
        # effector actions since the last observed scene, consumed by memory on next perceive()
        self._pending_actions_for_memory: list[ActionRecord] = []
        self._last_frame: Frame | None = None
        self._last_scene: Scene | None = None
        self._last_scene_coordinate_space: str | None = None
        self._implicit_coordinate_space_error: tuple[str, str] | None = None
        # frame cache: holds the (frame, scene) from the last completed OCR
        self._cache_frame: Frame | None = None
        self._cache_scene: Scene | None = None
        self._cache_scope = "device"
        self._needs_stable_frame = False
        self._fresh_source_reopened_after_action = False
        self._last_observation_mode = "raw"
        self._last_stable_frame: bool | None = None
        self._last_stability_score: float | None = None
        self._last_stability_policy: dict | None = None
        # hit/miss stats (directly visible to walkthrough scripts)
        self.perceive_cache_stats = {"hits": 0, "misses": 0}

    # —— Coordinate transform ——
    def _to_phone(self, x: float, y: float, *, coordinate_space: str | None = None) -> tuple[int, int]:
        """Observation coords -> coords the effector should see."""
        if coordinate_space is None and self._implicit_coordinate_space_error is not None:
            previous, current = self._implicit_coordinate_space_error
            raise ValueError(
                "implicit coordinate space is ambiguous after observation scope changed "
                f"from {previous!r} to {current!r}; pass coordinate_space explicitly"
            )
        input_space = self._normalize_input_coordinate_space(coordinate_space)
        if input_space == "app_px":
            if self.app_viewport is None:
                raise ValueError("coordinate_space='app_px' requires an app_viewport")
            x, y = self.app_viewport.child_to_parent(x, y)
            input_space = self.app_viewport.parent_coordinate_space
        if input_space == "frame_px":
            return self._frame_to_effector(x, y)
        if input_space == "cropped_px":
            return self._cropped_to_effector(x, y)
        raise ValueError(f"unsupported coordinate_space for phone input: {coordinate_space!r}")

    def _normalize_input_coordinate_space(self, coordinate_space: str | None) -> str:
        if coordinate_space is None:
            return self._infer_input_coordinate_space()
        normalized = str(coordinate_space).strip().lower().replace("-", "_")
        if normalized in {"app", "app_px"}:
            return "app_px"
        if normalized in {"device", "cropped", "cropped_px"}:
            return "cropped_px" if self.crop is not None else "frame_px"
        if normalized in {"frame", "frame_px", "raw", "raw_frame"}:
            return "frame_px"
        return normalized

    def _infer_input_coordinate_space(self) -> str:
        if self._last_scene_coordinate_space is not None:
            return self._last_scene_coordinate_space
        if self._last_frame is not None:
            return self._last_frame.context.coordinate_space
        return "cropped_px" if self.crop is not None else "frame_px"

    def _cropped_to_effector(self, x: float, y: float) -> tuple[int, int]:
        if self.crop is None:
            return round(x), round(y)
        effector_space = getattr(self.effector, "coordinate_space", None)
        if effector_space == "frame_px":
            return self.crop.cropped_to_frame(x, y)
        return self.crop.cropped_to_phone(x, y)

    def _frame_to_effector(self, x: float, y: float) -> tuple[int, int]:
        if self.crop is None:
            return round(x), round(y)
        effector_space = getattr(self.effector, "coordinate_space", None)
        if effector_space == "frame_px":
            return round(x), round(y)
        cx, cy, _w, _h = self.crop.crop_bbox
        return self.crop.cropped_to_phone(float(x) - cx, float(y) - cy)

    @staticmethod
    def _normalize_observation_scope(scope: str | None) -> str:
        normalized = str(scope or "device").strip().lower().replace("-", "_")
        if normalized in {"app", "foreground", "foreground_app"}:
            return "app"
        return "device"

    def _coordinate_space(self) -> str:
        if self.coordinate_space != "auto":
            return self.coordinate_space
        effector_space = getattr(self.effector, "coordinate_space", None)
        if self.crop is not None and effector_space != "frame_px":
            return "phone_pt" if effector_space == "phone_pt" else "phone_px"
        return str(effector_space or "frame_px")

    # —— Action recording / screen memory ——
    def _record_action(self, op: str, *, result=None, **kwargs) -> None:
        """Log an effector action to the recorder (if any) and stash it so the
        screen-memory layer can label the next transition edge.

        Any effector action may change the visible screen. Clear cached Scene
        state so the next semantic operation cannot accidentally reuse the
        pre-action screen while the HDMI feed is still catching up. Keep the
        last frame around as a viewport-size hint for chained gesture helpers.
        """
        action_kwargs = {**kwargs, **self._action_result_fields(result)}
        if self.recorder is not None:
            self.recorder.action(op, **action_kwargs)
        from glassbox.memory.schema import ActionRecord
        self._pending_actions_for_memory.append(ActionRecord.from_op(op, action_kwargs))
        self._needs_stable_frame = True
        self._fresh_source_reopened_after_action = False
        self.invalidate_perceive_cache()

    def supports(self, action: str) -> bool:
        capabilities = self._backend_capabilities()
        if capabilities is not None:
            return capabilities.supports_semantic(action)
        supports = getattr(self.effector, "supports", None)
        if callable(supports):
            return bool(supports(action))
        return hasattr(self.effector, action)

    def _backend_capabilities(self) -> BackendCapabilities | None:
        capabilities = getattr(self.effector, "capabilities", None)
        if callable(capabilities):
            try:
                return capabilities()
            except Exception as exc:
                logger.warning(f"effector capabilities() failed: {exc}")
                return NOOP_CAPABILITIES
        return None

    def _system_action_strategy(self, action: str) -> str:
        capabilities = self._backend_capabilities()
        if capabilities is None:
            return "direct" if self.supports(action) else "unsupported"
        return str(getattr(capabilities, f"{action}_strategy", "unsupported"))

    def _effector_backend(self) -> str:
        name = self.effector.__class__.__name__
        return name[:-8].lower() if name.endswith("Effector") else name.lower()

    def _is_picokvm_backend(self) -> bool:
        capabilities = self._backend_capabilities()
        if capabilities is not None:
            return capabilities.backend == "picokvm"
        return self._effector_backend() == "picokvm"

    def _failed_action_result(
        self,
        *,
        error: str,
        unsupported: bool = False,
    ) -> ActionResult:
        from glassbox.effector import ActionResult

        connected = False
        is_connected = getattr(self.effector, "is_connected", None)
        if callable(is_connected):
            try:
                connected = bool(is_connected())
            except Exception:
                connected = False
        return ActionResult.failed(
            backend=self._effector_backend(),
            connected=connected,
            error=error,
            unsupported=unsupported,
        )

    def _execute_action(self, op: str, call, **kwargs) -> ActionResult:
        """Run one effector action and record a typed result even on failure."""
        if self.action_orchestrator is not None:
            orchestrator_kwargs = {key: value for key, value in kwargs.items() if not key.startswith("_semantic_")}
            return self.action_orchestrator.execute(self, op, call, **orchestrator_kwargs)
        if isinstance(call, ActuationPlan):
            plan = call
            command = plan.command_for_attempt(0)
            call = command.call
            kwargs = {**kwargs, **plan.metadata(), **command.kwargs}
        semantic_verify = bool(kwargs.pop("_semantic_verify", False))
        semantic_verify_action = str(kwargs.pop("_semantic_verify_action", op))
        semantic_verify_delay_ms = int(kwargs.pop("_semantic_verify_delay_ms", 0) or 0)
        semantic_verify_reopen_source = bool(kwargs.pop("_semantic_verify_reopen_source", False))
        before_frame = self._last_frame
        before_scene = self._last_scene
        self._needs_stable_frame = True
        self._fresh_source_reopened_after_action = False
        self.invalidate_perceive_cache()
        try:
            result = call()
        except Exception as exc:
            result = self._failed_action_result(
                error=f"{type(exc).__name__}: {exc}",
            )
            self._record_action(op, result=result, **kwargs)
            raise
        if semantic_verify and result is not None and getattr(result, "ok", True):
            result = self._verify_fresh_action_result(
                semantic_verify_action,
                result,
                metadata=kwargs,
                before_frame=before_frame,
                before_scene=before_scene,
                delay_ms=semantic_verify_delay_ms,
                reopen_source=semantic_verify_reopen_source,
            )
        self._record_action(op, result=result, **kwargs)
        if self.action_fail_fast and result is not None and getattr(result, "ok", True) is False:
            detail = getattr(result, "error", None) or "reported action failure"
            raise RuntimeError(f"{op} failed: {detail}")
        return result

    def _uses_semantic_plan(self, op: str) -> bool:
        """CUQ-0.1/0.8: is this op routed through the first-class strategy ladder?"""
        return op in self._semantic_plan_ops and self.action_orchestrator is not None

    def _run_semantic_plan(
        self,
        op: str,
        *,
        expected_state=None,
        actor: str = "agent",
        params: dict[str, Any] | None = None,
        **exec_kwargs: Any,
    ) -> ActionResult:
        """Run a core op through default_semantic_action_plan: the orchestrator
        executes each strategy in order and switches to the next on verified
        failure (recovering after exhaustion), instead of the legacy
        single-strategy path. ``params`` feed the plan's strategy bindings;
        ``exec_kwargs`` become orchestrator metadata (via/policy_action/fresh
        verify)."""
        from glassbox.action.semantic_plan import default_semantic_action_plan

        plan = default_semantic_action_plan(self, op, expected_state, **(params or {}))
        return self.action_orchestrator.execute(self, op, plan, actor=actor, **exec_kwargs)

    def _set_last_scene(self, scene: Scene, frame: Frame | None) -> None:
        self._last_scene = scene
        self._last_scene_coordinate_space = frame.context.coordinate_space if frame is not None else None
        self._implicit_coordinate_space_error = None

    def _verify_fresh_action_result(
        self,
        action: str,
        result: ActionResult,
        *,
        metadata: dict,
        before_frame,
        before_scene: Scene | None,
        delay_ms: int,
        reopen_source: bool,
    ) -> ActionResult:
        from glassbox.verification import (
            DEFAULT_REGISTRY,
            VerifierInput,
            compute_frame_diff,
            compute_scene_diff,
        )

        verifier = DEFAULT_REGISTRY.resolve(action, metadata)
        try:
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            stream_until_match = metadata.get("settle_strategy") == "stream_until_match"
            timeout_ms = int(metadata.get("stream_timeout_ms", 0) or 0)
            interval_ms = max(1, int(metadata.get("sample_interval_ms", 250) or 250))
            max_stream_frames = max(1, int(metadata.get("max_stream_frames", 1) or 1))
            if not stream_until_match:
                max_stream_frames = 1
            deadline = time.monotonic() + max(0, timeout_ms) / 1000.0 if timeout_ms > 0 else None
            semantic = None
            for sample_index in range(max_stream_frames):
                if sample_index > 0:
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    time.sleep(interval_ms / 1000.0)
                if reopen_source:
                    self._reopen_source_for_fresh_capture()
                self.invalidate_perceive_cache()
                after_frame, after_scene = self._fresh_scene_for_verification(
                    stable=True if self.stability_policy is not None else None,
                )
                frame_diff = compute_frame_diff(
                    before_frame.img if before_frame is not None else None,
                    after_frame.img if after_frame is not None else None,
                )
                scene_diff = compute_scene_diff(before_scene, after_scene)
                verifier_input = VerifierInput(
                    attempt_id="phone_direct",
                    attempt_group_id="phone_direct",
                    action={"op": action, "args": [], "kwargs": {}, "metadata": metadata},
                    before_requested=before_scene,
                    before_command=before_scene,
                    after_scenes=[after_scene],
                    after_mode="fresh_frame",
                    frame_diff=frame_diff.to_dict() if frame_diff is not None else None,
                    scene_diff=scene_diff.to_dict() if scene_diff is not None else None,
                    command_result=result.to_event_fields(),
                    risk={"level": "medium"},
                    after_frame_ids=[str(after_scene.frame_id)],
                    after_scene_ids=[after_scene.page_id or after_scene.scene_type or str(after_scene.frame_id)],
                )
                semantic = verifier.verify(verifier_input)
                if semantic.status == "succeeded" or not stream_until_match:
                    break
            assert semantic is not None
            return replace(
                result,
                semantic_status=semantic.status,
                semantic_reason=semantic.reason,
                semantic_confidence=semantic.confidence,
                semantic_verifier=semantic.verifier,
                semantic_verification_skipped=semantic.verification_skipped,
                attempt_id="phone_direct",
                attempt_group_id="phone_direct",
            )
        except Exception as exc:
            return replace(
                result,
                semantic_status="unknown",
                semantic_reason=f"fresh-frame verification failed: {type(exc).__name__}: {exc}",
                semantic_confidence=0.0,
                semantic_verifier=getattr(verifier, "name", action),
                semantic_verification_skipped=False,
                attempt_id="phone_direct",
                attempt_group_id="phone_direct",
            )

    def _fresh_scene_for_verification(self, *, stable: bool | None):
        frame = self.snapshot(stable=stable)
        frame_id = int(frame.ts * 1000)
        scene = Scene(
            frame_id=frame_id,
            timestamp=frame.ts,
            elements=self._recognize_elements(frame),
            source_frame_ids=[frame_id],
            source_timestamps=[frame.ts],
            observation_mode=self._last_observation_mode,
            stable_frame=self._last_stable_frame,
            viewport_size=(int(frame.img.shape[1]), int(frame.img.shape[0])),
        )
        if self.typer is not None:
            self.typer.upgrade(scene, frame_img=frame.img)
        self._apply_profile(scene, frame.img)
        self._apply_scene_classifiers(scene, frame.img)
        self._set_last_scene(scene, frame)
        self._cache_frame = None
        self._cache_scene = None
        self._needs_stable_frame = False
        return frame, scene

    def _reopen_source_for_fresh_capture(self) -> bool:
        close = getattr(self.source, "close", None)
        open_ = getattr(self.source, "open", None)
        if not callable(close) or not callable(open_):
            return False
        close()
        time.sleep(0.05)
        open_()
        self._fresh_source_reopened_after_action = True
        return True

    def _picokvm_fresh_verify_kwargs(self, action: str) -> dict:
        if not self._is_picokvm_backend():
            return {}
        cfg = getattr(self.effector, "config", None)
        if cfg is None or not bool(getattr(cfg, "semantic_verify_enabled", True)):
            return {}
        delay_ms = int(getattr(cfg, "semantic_verify_delay_ms", 800) or 0)
        timeout_ms = int(getattr(cfg, "semantic_verify_timeout_ms", 1800) or 1800)
        interval_ms = int(getattr(cfg, "semantic_verify_sample_interval_ms", 250) or 250)
        return {
            "_semantic_verify": True,
            "_semantic_verify_action": action,
            "_semantic_verify_delay_ms": delay_ms,
            "_semantic_verify_reopen_source": bool(getattr(cfg, "semantic_verify_reopen_source", True)),
            "settle_strategy": "stream_until_match",
            "fresh_source_reopen": bool(getattr(cfg, "semantic_verify_reopen_source", True)),
            "fresh_delay_ms": delay_ms,
            "stream_timeout_ms": timeout_ms,
            "sample_interval_ms": interval_ms,
            "max_stream_frames": max(1, int(timeout_ms / max(1, interval_ms))),
            "semantic_verify": "fresh_frame",
        }

    def _picokvm_back_guard(self) -> tuple[bool, str]:
        allowed, reason, _back_point = self._picokvm_back_context()
        return allowed, reason

    def _picokvm_back_context(self) -> tuple[bool, str, tuple[int, int] | None]:
        capabilities = self._backend_capabilities()
        if capabilities is None or capabilities.backend != "picokvm":
            return True, "not_picokvm", None
        try:
            scene = self.perceive()
        except Exception as exc:
            return False, f"scene_unavailable:{exc}", None
        nav_back = self._visible_nav_back_in_scene(scene)
        nav_point = nav_back.box.center if nav_back is not None else None
        safe_actions = set(scene.safe_actions or [])
        if safe_actions.intersection({"back", "edge_back"}):
            if nav_point is None and scene.platform_scene_kind == "settings_detail":
                return True, "platform_settings_detail", self._inferred_ios_nav_back_point(scene)
            return True, "safe_action", nav_point
        if nav_point is not None:
            return True, "nav_back_element", nav_point
        classified = self._classify_platform_scene_now(scene, viewport_size=self._viewport_size())
        if (
            classified is not None
            and classified.platform_scene_kind == "settings_detail"
            and "back" in classified.safe_actions
        ):
            return True, "platform_settings_detail", nav_point or self._inferred_ios_nav_back_point(scene)
        # Last resort: a page the classifier positively tagged "unknown" (it ran
        # and could not identify the scene — distinct from no classifier at all)
        # is almost always a sub-page whose chrome defeats back/affordance
        # detection, e.g. the Action-Button carousel with a live camera preview.
        # iOS still draws the conventional top-left back chevron there, so a
        # blind inferred-chevron tap climbs out instead of stranding recovery.
        # Recognized roots/home keep returning no target (nothing to go back to).
        if "unknown" in {
            scene.platform_scene_kind,
            getattr(classified, "platform_scene_kind", None),
        }:
            return True, "blind_inferred_back", self._inferred_ios_nav_back_point(scene)
        return False, "no_parent_back_target", None

    def _visible_nav_back_in_scene(self, scene: Scene) -> UIElement | None:
        candidates = [
            element
            for element in scene.elements
            if element.type == "nav_back" and element.box.center[1] <= self._viewport_size()[1] * 0.22
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda element: (element.box.y, element.box.x))[0]

    def _inferred_ios_nav_back_point(self, scene: Scene | None = None) -> tuple[int, int]:
        w, h = self._viewport_size()
        model = str(getattr(getattr(self, "device_geometry", None), "model", "") or "").lower().replace("-", "_")
        if model.startswith("ipad") and scene is not None:
            evidence = set(getattr(scene, "evidence", None) or ())
            if scene.platform_scene_kind == "settings_detail" or "ipad_split_view" in evidence:
                from glassbox.ipados.scene import sidebar_right_x

                sidebar_right = sidebar_right_x(w)
                detail_width = max(1, w - sidebar_right)
                return min(w - 24, sidebar_right + max(8, round(detail_width * 0.02))), round(h * 0.055)
        return round(w * 0.09), round(h * 0.09)

    def _unsupported_action(self, op: str, **kwargs) -> ActionResult:
        result = self._failed_action_result(
            error=f"unsupported action: {op}",
            unsupported=True,
        )
        self._record_action(op, result=result, **kwargs)
        if self.action_fail_fast:
            raise RuntimeError(f"{op} failed: unsupported action")
        return result

    @staticmethod
    def _action_result_fields(result) -> dict:
        if result is None:
            return {}
        to_event_fields = getattr(result, "to_event_fields", None)
        if callable(to_event_fields):
            return to_event_fields()
        if isinstance(result, dict):
            fields = {
                "action_backend": "unknown",
                "action_connected": True,
                "action_ok": bool(result.get("ok", True)),
                "action_retry_count": int(result.get("retryCount", 0) or 0),
                "action_synthetic": False,
            }
            ack_seq = result.get("ackSeq", result.get("seq"))
            if ack_seq is not None:
                fields["action_ack_seq"] = ack_seq
            if result.get("err"):
                fields["action_error"] = str(result.get("err"))
            return fields
        return {}

    def _viewport_size(self) -> tuple[int, int]:
        """Return the currently perceived viewport size in cropped-frame coords."""
        if self._last_frame is None:
            self.snapshot()
        assert self._last_frame is not None
        return self._last_frame.shape

    def _observe_memory(self, scene: Scene, frame_img) -> None:
        """Fold the scene into the UTG (if the memory layer is on), then run the
        cold-start annotator off the resolved node."""
        if self.memory is None:
            self._pending_actions_for_memory.clear()
            return
        actions = [
            action for action in self._pending_actions_for_memory
            if self._memory_action_candidate(action)
        ]
        last_action = actions[0] if len(actions) == 1 else None
        node = self.memory.observe(scene, last_action, frame_img=frame_img)
        self._pending_actions_for_memory = []
        if self.coldstart is not None and frame_img is not None:
            try:
                annotation = self.coldstart.observe(node=node, scene=scene, frame_img=frame_img)
            except Exception as exc:  # a VLM/network failure must not break perceive
                logger.warning(f"cold-start annotation failed: {exc}")
            else:
                if annotation is not None:
                    apply_annotation_to_scene(scene, annotation)

    @staticmethod
    def _memory_action_candidate(action: ActionRecord) -> bool:
        if action.params.get("action_ok") is not True:
            return False
        return action.params.get("action_synthetic") is not True

    def _apply_scene_classifiers(self, scene: Scene, frame_img: np.ndarray | None) -> None:
        """Run optional platform/app classifier hooks before recording/memory."""
        if not self.scene_classifiers:
            return
        viewport_size = None
        if frame_img is not None and getattr(frame_img, "ndim", 0) >= 2:
            viewport_size = (int(frame_img.shape[1]), int(frame_img.shape[0]))
        classifications: list[SceneClassification] = []
        for classify in self.scene_classifiers:
            result = classify(scene, viewport_size)
            if result is not None:
                classifications.append(result)
        DEFAULT_SCENE_CLASSIFICATION_PROJECTOR.project(scene, classifications)

    def _classify_platform_scene_now(
        self,
        scene: Scene,
        viewport_size: tuple[int, int] | None,
    ) -> SceneClassification | None:
        classifier = self._platform_scene_classifier
        if classifier is None:
            return None
        return classifier.classify(scene, viewport_size=viewport_size)

    # —— Profile (Tier 1+ white-box) ——
    def _apply_profile(self, scene: Scene, frame_img=None) -> None:
        """Tag the scene with the KnownVC it is showing and, when that VC has
        known_elements + an asset workspace, icon-match whitebox_hint onto its
        elements. Re-run after Layer 3 so the Kimi scene_type can sharpen the
        VC match. No-op at Tier 0 (no profile)."""
        if self.profile is None:
            return
        match = self.profile.match_vc_detail(scene)
        scene.current_vc = None if match.ambiguous else match.vc_name
        if frame_img is not None:
            from glassbox.cognition.whitebox import apply_whitebox
            scene.whitebox_evaluated = True
            apply_whitebox(scene, frame_img, self.profile)

    # —— Perception ——
    def _should_wait_stable(self, stable: bool | None) -> bool:
        if stable is not None:
            return stable
        policy = self.stability_policy
        if policy is None or not policy.enabled:
            return False
        return not policy.after_action_only or self._needs_stable_frame

    def _should_fresh_snapshot(self, fresh: bool | None) -> bool:
        if fresh is not None:
            return bool(fresh)
        if self._fresh_source_reopened_after_action:
            return False
        return self._needs_stable_frame and self._source_supports_fresh_snapshot()

    def _source_supports_fresh_snapshot(self) -> bool:
        return callable(getattr(self.source, "fresh_snapshot", None))

    def _source_snapshot(self, *, fresh: bool) -> Frame | None:
        if fresh:
            fresh_snapshot = getattr(self.source, "fresh_snapshot", None)
            if callable(fresh_snapshot):
                frame = fresh_snapshot()
                self._fresh_source_reopened_after_action = True
                return frame
            self._reopen_source_for_fresh_capture()
        return self.source.snapshot()

    def snapshot(
        self,
        *,
        stable: bool | None = None,
        scope: str | None = None,
        fresh: bool | None = None,
    ) -> Frame | None:
        from glassbox.perception.source import Frame as _Frame
        frame_scope = self._normalize_observation_scope(scope or self.default_observation_scope)
        previous_scene_space = self._last_scene_coordinate_space if self._last_scene is not None else None
        fresh_source = self._should_fresh_snapshot(fresh)
        if self._should_wait_stable(stable):
            from glassbox.perception.stable import wait_stable_result
            policy = self.stability_policy
            assert policy is not None
            initial_frame = None
            if fresh_source:
                initial_frame = self._source_snapshot(fresh=True)
            result = wait_stable_result(
                self.source,
                timeout=policy.timeout,
                diff_threshold=policy.diff_threshold,
                consecutive=policy.consecutive,
                poll_interval=policy.poll_interval,
                initial_frame=initial_frame,
            )
            raw = result.frame
            self._last_observation_mode = "stable"
            self._last_stable_frame = True
            self._last_stability_score = result.stability_score
            self._last_stability_policy = {
                "timeout": policy.timeout,
                "diff_threshold": policy.diff_threshold,
                "consecutive": policy.consecutive,
                "poll_interval": policy.poll_interval,
            }
        else:
            raw = self._source_snapshot(fresh=fresh_source)
            self._last_observation_mode = "raw"
            self._last_stable_frame = None
            self._last_stability_score = None
            self._last_stability_policy = None
        if raw is None:
            self._last_frame = None
            self._last_scene = None
            self._last_scene_coordinate_space = None
            self._implicit_coordinate_space_error = None
            if self.recorder is not None:
                self.recorder.snapshot(None)
            return None
        if self.crop is not None:
            if raw.shape != self.crop.frame_size:
                from glassbox.perception.letterbox import LetterboxCrop
                self.crop = LetterboxCrop.auto_detect(raw.img, phone_size=self.crop.phone_size)
                logger.info(
                    "letterbox crop refreshed after source resolution changed: "
                    f"frame={self.crop.frame_size} bbox={self.crop.crop_bbox}"
                )
            elif self.auto_refresh_letterbox_crop:
                self._refresh_letterbox_crop_bbox(raw)
            raw = _Frame(
                img=self.crop.crop(raw.img),
                ts=raw.ts,
                context=raw.context.with_crop(
                    source_shape=raw.shape,
                    crop_bbox=self.crop.crop_bbox,
                    projection="cropped_px",
                    name="device",
                ),
            )
        if frame_scope == "app":
            raw = self._apply_app_viewport(raw)
        self._last_frame = raw
        current_space = raw.context.coordinate_space
        if previous_scene_space is not None and previous_scene_space != current_space:
            self._implicit_coordinate_space_error = (previous_scene_space, current_space)
        else:
            self._implicit_coordinate_space_error = None
        self._last_scene = None   # invalidate
        self._last_scene_coordinate_space = None
        if self.recorder is not None:
            self.recorder.snapshot(self._last_frame)
        return self._last_frame

    def _refresh_letterbox_crop_bbox(self, raw: Frame) -> None:
        if self.crop is None:
            return
        try:
            from glassbox.perception.letterbox import LetterboxCrop
            detected = LetterboxCrop.auto_detect(raw.img, phone_size=self.crop.phone_size)
        except Exception:
            return
        if detected.crop_bbox == self.crop.crop_bbox:
            return
        self.crop = detected
        logger.info(
            "letterbox crop refreshed after source bbox changed: "
            f"frame={self.crop.frame_size} bbox={self.crop.crop_bbox}"
        )

    def _apply_app_viewport(self, frame: Frame) -> Frame:
        from glassbox.perception.source import Frame as _Frame

        viewport = self.app_viewport
        if self._should_detect_app_viewport(frame):
            detected = detect_iphone_compat_viewport(frame.img)
            if detected is not None:
                detected = replace(detected, parent_coordinate_space=frame.context.coordinate_space)
                if viewport is None or (
                    viewport.source == "detected" and detected_viewport_needs_update(viewport, detected)
                ):
                    viewport = detected
                    self.app_viewport = detected
            elif viewport is not None and viewport.source == "detected":
                self.app_viewport = None
                viewport = None
        if viewport is None:
            return frame
        return _Frame(
            img=viewport.crop(frame.img),
            ts=frame.ts,
            context=frame.context.with_crop(
                source_shape=frame.shape,
                crop_bbox=viewport.bbox,
                projection=viewport.coordinate_space,
                name=viewport.name,
            ),
        )

    def _should_detect_app_viewport(self, frame: Frame) -> bool:
        if self.app_viewport_mode == "device":
            return False
        if frame.context.coordinate_space not in {"cropped_px", "frame_px"}:
            return False
        model = str(getattr(getattr(self, "device_geometry", None), "model", "") or "").lower().replace("-", "_")
        if model and not model.startswith("ipad"):
            return False
        return self.app_viewport_mode in {"auto", "iphone_compat"}

    def invalidate_app_viewport(self) -> None:
        """Drop an auto-detected app viewport so the next app-scope snapshot re-detects it."""
        if self.app_viewport is not None and self.app_viewport.source == "detected":
            self.app_viewport = None

    def invalidate_perceive_cache(self) -> None:
        """Explicitly clear the Scene cache. After tap_*/swipe, Phone cannot
        tell whether the screen changed; a high-level walkthrough script can
        manually invalidate after an operation that disrupts the screen."""
        self._cache_frame = None
        self._cache_scene = None
        self._last_scene = None
        self._last_scene_coordinate_space = None
        self._implicit_coordinate_space_error = None

    def perceive(
        self,
        *,
        stable: bool | None = None,
        scope: str | None = None,
        fresh: bool | None = None,
    ) -> Scene:
        """OCR → Layer 2 heuristic typing. Returns the full Scene.

        frame diff cache: when the mean absdiff against the last OCR'd frame
        is < perceive_cache_diff, the Scene is reused directly (only
        frame_id / timestamp updated), saving OCR + Kimi describe. A
        threshold of 0 disables it.
        """
        from glassbox.perception.stable import frame_diff_ratio

        frame_scope = self._normalize_observation_scope(scope or self.default_observation_scope)
        frame = self.snapshot(stable=stable, scope=frame_scope, fresh=fresh)
        observation_mode = self._last_observation_mode
        stable_frame = self._last_stable_frame

        # —— cache hit ——
        if (
            self.perceive_cache_diff > 0
            and self._cache_frame is not None
            and self._cache_scene is not None
            and self._cache_scope == frame_scope
            and self._cache_frame.img.shape == frame.img.shape
            and frame_diff_ratio(self._cache_frame.img, frame.img) < self.perceive_cache_diff
        ):
            scene = self._cache_scene.model_copy(
                update={
                    "frame_id": int(frame.ts * 1000),
                    "timestamp": frame.ts,
                    "source_frame_ids": [int(frame.ts * 1000)],
                    "source_timestamps": [frame.ts],
                    "observation_mode": observation_mode,
                    "stable_frame": stable_frame,
                    "viewport_size": (int(frame.img.shape[1]), int(frame.img.shape[0])),
                },
                deep=True,
            )
            self._apply_scene_classifiers(scene, frame.img)
            self.perceive_cache_stats["hits"] += 1
            self._observe_memory(scene, frame.img)
            self._set_last_scene(scene, frame)
            self._cache_scene = scene.model_copy(deep=True)
            if self.recorder is not None:
                self.recorder.scene(scene)
            self._needs_stable_frame = False
            return scene

        # —— cache miss: run OCR for real ——
        elements = self._recognize_elements(frame)
        scene = Scene(
            frame_id=int(frame.ts * 1000),
            timestamp=frame.ts,
            elements=elements,
            source_frame_ids=[int(frame.ts * 1000)],
            source_timestamps=[frame.ts],
            observation_mode=observation_mode,
            stable_frame=stable_frame,
            viewport_size=(int(frame.img.shape[1]), int(frame.img.shape[0])),
        )
        if self.typer is not None:
            self.typer.upgrade(scene, frame_img=frame.img)
        self._apply_profile(scene, frame.img)
        self._apply_scene_classifiers(scene, frame.img)
        self._maybe_detect_icons(scene, frame.img)
        self.perceive_cache_stats["misses"] += 1
        self._observe_memory(scene, frame.img)
        self._cache_frame = frame
        self._cache_scene = scene.model_copy(deep=True)
        self._cache_scope = frame_scope
        self._set_last_scene(scene, frame)
        if self.recorder is not None:
            self.recorder.scene(scene)
        self._needs_stable_frame = False
        return scene

    def _recognize_elements(self, frame: Frame) -> list[UIElement]:
        if getattr(self.ocr, "contract", None) == "TextRegionOCR":
            return ocr_results_to_elements(self.ocr.recognize(frame))
        return ocr_results_to_elements(self.ocr.recognize(frame.img))

    def _maybe_detect_icons(self, scene: Scene, frame_img) -> None:
        """CUQ-2.1 (flag-gated): inject no-text icon regions as tappable image
        elements so icon-only controls (+, share, gear, back-chevron, trash)
        become tap candidates instead of being invisible to the OCR-text-only
        set. Runs after the scene classifiers so classification is unaffected;
        best-effort (never breaks perceive)."""
        if not self._detect_icons_in_perceive or frame_img is None:
            return
        try:
            from glassbox.cognition.icon_detect import detect_icons

            text_boxes = tuple(
                (el.box.x, el.box.y, el.box.w, el.box.h)
                for el in scene.elements
                if getattr(el, "text", None)
            )
            regions = detect_icons(frame_img, text_boxes=text_boxes)
        except Exception:
            return
        if not regions:
            return
        next_id = max(
            (el.element_id for el in scene.elements if el.element_id is not None),
            default=-1,
        ) + 1
        for region in regions:
            x, y, w, h = region.box
            scene.elements.append(
                UIElement(
                    type="image",
                    box=Box(x=int(x), y=int(y), w=int(w), h=int(h)),
                    text=None,
                    confidence=0.3,
                    element_id=next_id,
                )
            )
            next_id += 1

    def perceive_voted(self, n: int = 2, *, text_normalizer=None, scope: str | None = None) -> Scene:
        """Perceive a STABLE screen `n` times and vote per-row text (D).

        For accuracy-critical reads where the screen is not moving — OCR
        jitter on a row is decided by majority instead of one sampled frame.
        Costs ~n× OCR; bypasses the frame-diff cache by design. n<=1 falls
        back to a single perceive().
        """
        if n <= 1:
            return self.perceive(scope=scope)
        frame_scope = self._normalize_observation_scope(scope or self.default_observation_scope)
        from glassbox.cognition.ocr_vote import vote_scenes

        scenes: list[Scene] = []
        last_frame = None
        source_frame_ids: list[int] = []
        source_timestamps: list[float] = []
        for _ in range(n):
            frame = self.snapshot(scope=frame_scope)
            last_frame = frame
            frame_id = int(frame.ts * 1000)
            source_frame_ids.append(frame_id)
            source_timestamps.append(frame.ts)
            elements = self._recognize_elements(frame)
            sc = Scene(
                frame_id=frame_id,
                timestamp=frame.ts,
                elements=elements,
                source_frame_ids=[frame_id],
                source_timestamps=[frame.ts],
                observation_mode=self._last_observation_mode,
                stable_frame=self._last_stable_frame,
                viewport_size=(int(frame.img.shape[1]), int(frame.img.shape[0])),
            )
            if self.typer is not None:
                self.typer.upgrade(sc, frame_img=frame.img)
            scenes.append(sc)
        scene = vote_scenes(scenes, text_normalizer=text_normalizer)
        if last_frame is not None:
            scene = scene.model_copy(
                update={
                    "frame_id": int(last_frame.ts * 1000),
                    "timestamp": last_frame.ts,
                    "source_frame_ids": source_frame_ids,
                    "source_timestamps": source_timestamps,
                    "observation_mode": "voted",
                    "stable_frame": any(s.stable_frame is True for s in scenes),
                    "viewport_size": (
                        int(last_frame.img.shape[1]),
                        int(last_frame.img.shape[0]),
                    ),
                },
                deep=True,
            )
        frame_img = last_frame.img if last_frame is not None else None
        self._apply_profile(scene, frame_img)
        self._apply_scene_classifiers(scene, frame_img)
        # voted reads bypass the diff cache; invalidate so a later perceive()
        # cannot reuse a stale single-frame scene against this voted one.
        self._cache_frame = None
        self._cache_scene = None
        self._cache_scope = frame_scope
        if frame_img is not None:
            self._observe_memory(scene, frame_img)
        self._set_last_scene(scene, last_frame)
        if self.recorder is not None:
            self.recorder.scene(scene)
        self._needs_stable_frame = False
        return scene

    def describe(self, *, scene_hint: str | None = None) -> Scene:
        """Run Kimi Layer 3 to populate _last_scene with intent_label / scene_type.

        Slow (~6-15s) and billed, so only call it explicitly at key
        decision points.
        Kimi not wired up → just return the last scene (non-blocking).
        """
        if self._last_scene is None:
            self.perceive()
        if self.kimi is None or self._last_scene is None:
            return self._last_scene   # type: ignore[return-value]

        if self._last_frame is None:
            return self._last_scene

        # reset the cache hit flag (if self.kimi is a CachedKimi)
        if hasattr(self.kimi, "last_hit"):
            self.kimi.last_hit = False
        t0 = time.monotonic()
        enrich_scene(
            self._last_scene,
            self._last_frame,
            self.kimi,
            scene_hint=scene_hint,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        vlm_ok = self._last_scene.vlm_status == "ok"
        if vlm_ok:
            # Layer 3 has now set scene_type — re-match so a scene_type anchor can
            # sharpen (or correct) the VC identified at the OCR-only stage.
            self._apply_profile(
                self._last_scene,
                self._last_frame.img if self._last_frame is not None else None,
            )
            self._apply_scene_classifiers(
                self._last_scene,
                self._last_frame.img if self._last_frame is not None else None,
            )
            # describe() mutates _last_scene in place. When _last_scene came from a
            # cache hit, it is a copy of _cache_scene, so persist top-level Layer 3
            # fields such as scene_type/context/app_state for future cache hits.
            self._cache_scene = self._last_scene.model_copy(deep=True)
            if self.memory is not None:
                self.memory.merge_scene_metadata(
                    self._last_scene,
                    self._last_frame.img if self._last_frame is not None else None,
                )

        if self.recorder is not None:
            self.recorder.kimi_call(
                model=self._last_scene.vlm_model or getattr(self.kimi, "model", "?"),
                hit=bool(getattr(self.kimi, "last_hit", False)),
                elapsed_ms=elapsed_ms,
                usage=dict(self._last_scene.vlm_usage),
                scene_hint=scene_hint,
                status=self._last_scene.vlm_status or "unknown",
                error=self._last_scene.vlm_error,
                parse_ok=vlm_ok,
            )
            self.recorder.scene(self._last_scene, purpose="metadata")
        return self._last_scene

    # —— Verdict ——
    def find_text(self, target: str, *, fuzzy_ratio: float = 0.8) -> UIElement | None:
        """OCR the current frame and find an element matching target.

        Nav-bar title elements are pushed to the end of the search order: the
        centered page title is non-interactive, so when the same text is also a
        tappable row (e.g. "键盘" as both the nav title and a list row),
        ``find_text`` would otherwise return the title and ``tap_text`` would
        no-op on it.
        """
        scene = self.perceive()
        return find_text(self._rows_before_nav_title(scene.elements),
                         target, fuzzy_ratio=fuzzy_ratio)

    def _vlm_reground_selection(self, target: str, *, fuzzy_ratio: float) -> UIElement | None:
        """CUQ-0.4: selection-time VLM escalation (P1 trigger #2 — target not
        found by OCR → find-by-description).

        When OCR cannot locate the target, escalate to the VLM through the
        gate and retry the lookup before failing, instead of hard-failing the
        step. Gated on a VLM client being wired (so VLM-disabled runs are
        unchanged) and budgeted to a single grounding call per selection.
        Returns the grounded element, or None when VLM is unavailable / the
        budget is spent / the target still cannot be resolved.
        """
        if self.kimi is None:
            return None
        from glassbox.cognition.vlm_gate import VLMEscalationGate, VLMGateInput

        gate = VLMEscalationGate(enabled=True, max_calls_per_action=1, max_calls_per_attempt=1)
        gate_input = VLMGateInput(ocr_confidence=None, target_found=False)
        described = gate.escalate(gate_input, lambda: self.describe(scene_hint=f"find:{target}"))
        if described is None:
            return None
        elements = self._rows_before_nav_title(described.elements)
        # Try raw text first, then the VLM-enriched intent labels: describe()
        # adds intent_label/scene semantics (it does not re-OCR raw text, see
        # CUQ-1.3), so find_by_intent is what rescues a target OCR mis-read or
        # could not surface as plain text.
        hit = find_text(elements, target, fuzzy_ratio=fuzzy_ratio)
        if hit is None:
            hit = find_by_intent(elements, target, fuzzy_ratio=fuzzy_ratio)
        return hit

    def _rows_before_nav_title(self, elements: list[UIElement]) -> list[UIElement]:
        """Reorder elements so likely nav-bar titles come last (deprioritized).

        A nav-bar title is in the top band of the screen AND horizontally
        centered; nav-bar buttons (back ``<``, Edit) sit at the edges and are
        not affected.
        """
        try:
            w, h = self._viewport_size()
        except Exception:
            return elements

        def is_nav_title(el: UIElement) -> bool:
            cx, cy = el.box.center
            return cy < h * 0.13 and abs(cx - w / 2) < w * 0.18

        rows = [e for e in elements if not is_nav_title(e)]
        titles = [e for e in elements if is_nav_title(e)]
        return rows + titles if titles else elements

    def expect_text(
        self,
        target: str,
        *,
        timeout: float = 5.0,
        fuzzy_ratio: float = 0.8,
        poll_interval: float = 0.5,
    ) -> UIElement:
        """Block until the target text appears. On timeout, raise AssertionError (so pytest marks it red)."""
        deadline = time.monotonic() + timeout
        last_seen_texts: list[str] = []
        while time.monotonic() < deadline:
            el = self.find_text(target, fuzzy_ratio=fuzzy_ratio)
            if el is not None:
                self._last_selection_source = "ocr"
                if self.recorder is not None:
                    self.recorder.verdict(f"expect_text({target!r})", passed=True)
                return el
            if self._last_scene:
                last_seen_texts = [e.text for e in self._last_scene.elements if e.text]
            time.sleep(poll_interval)
        # CUQ-0.4: OCR could not locate the target; before hard-failing, give the
        # VLM a single gated chance to ground it (find-by-description). No-op when
        # VLM is disabled, so default behavior is unchanged.
        grounded = self._vlm_reground_selection(target, fuzzy_ratio=fuzzy_ratio)
        if grounded is not None:
            self._last_selection_source = "vlm"
            if self.recorder is not None:
                self.recorder.verdict(f"expect_text({target!r})", passed=True, message="vlm_grounded")
            return grounded
        if self.recorder is not None:
            self.recorder.verdict(
                f"expect_text({target!r})",
                passed=False,
                message=f"timeout {timeout}s; last seen={last_seen_texts[:10]}",
            )
        raise AssertionError(
            f"expect_text({target!r}) timed out ({timeout}s). "
            f"Last seen text: {last_seen_texts[:10]}..."
        )

    def expect_no_text(self, target: str, *, fuzzy_ratio: float = 0.9) -> None:
        el = self.find_text(target, fuzzy_ratio=fuzzy_ratio)
        if self.recorder is not None:
            self.recorder.verdict(
                f"expect_no_text({target!r})",
                passed=el is None,
                message=f"found={el.text!r}" if el is not None else "",
            )
        if el is not None:
            raise AssertionError(f"expect_no_text({target!r}) but found: {el.text!r}")

    # —— Action ——
    def _tap_point_for_element(self, el: UIElement) -> tuple[int, int]:
        settings_row_point = self._picokvm_settings_row_tap_point_for_element(el)
        if settings_row_point is not None:
            return settings_row_point
        springboard_icon_point = self._springboard_icon_tap_point_for_element(el)
        if springboard_icon_point is not None:
            return springboard_icon_point
        if el.preferred_tap_point is not None:
            return el.preferred_tap_point
        cx, cy = el.box.center
        if el.type == "tab_bar_item" and self.safe_area_provider is not None:
            return self.safe_area_provider.bottom_hit_point(
                self._viewport_size(),
                x=cx,
                y=cy,
                element_type=el.type,
            )
        return cx, cy

    def _springboard_icon_tap_point_for_element(self, el: UIElement) -> tuple[int, int] | None:
        if not el.text or self._last_scene is None:
            return None
        try:
            viewport_size = self._viewport_size()
        except Exception:
            viewport_size = None
        try:
            from glassbox.ios.springboard import find_springboard_icon, is_ios_home_screen

            if not is_ios_home_screen(self._last_scene, viewport_size=viewport_size):
                return None
            icon = find_springboard_icon(self._last_scene, (el.text,), viewport_size=viewport_size)
        except Exception:
            return None
        if icon is None:
            return None
        if icon.element.box != el.box or icon.element.text != el.text:
            return None
        return icon.tap_point

    def _picokvm_settings_row_tap_point_for_element(self, el: UIElement) -> tuple[int, int] | None:
        if self._effector_backend() != "picokvm" or self._last_scene is None:
            return None
        if el.type not in {"list_item", "button", "text"} or not el.text:
            return None
        scene = self._last_scene
        scene_kind = str(scene.platform_scene_kind or scene.semantic_scene_type or scene.scene_type or "")
        page_id = str(scene.page_id or "")
        width, height = self._viewport_size()
        safe_actions = set(scene.safe_actions or [])
        if not (scene_kind or page_id or safe_actions):
            try:
                classified = self._classify_platform_scene_now(scene, viewport_size=(width, height))
            except Exception:
                classified = None
            if classified is not None:
                scene_kind = classified.platform_scene_kind or ""
                page_id = classified.page_id or ""
                safe_actions = set(classified.safe_actions or ())
        if not (
            scene_kind.startswith("settings")
            or page_id.startswith("settings")
            or "tap_root_row" in safe_actions
        ):
            return None
        cx, cy = el.box.center
        if cy < int(height * 0.18) or cy > int(height * 0.94):
            return None
        model = str(getattr(getattr(self, "device_geometry", None), "model", "") or "").lower().replace("-", "_")
        if model.startswith("ipad"):
            from glassbox.ipados.scene import sidebar_right_x

            sidebar_right = sidebar_right_x(width)
            if cx <= sidebar_right:
                return min(max(cx, int(width * 0.10)), max(int(width * 0.10), sidebar_right - 44)), cy
            detail_x = min(
                max(int(sidebar_right + (width - sidebar_right) * 0.34), sidebar_right + 64),
                width - 44,
            )
            return min(max(cx, detail_x), width - 44), cy
        if el.box.x > int(width * 0.45):
            return None
        if el.box.w > int(width * 0.65):
            return None
        return int(width * 0.5), cy

    @staticmethod
    def _pop_actuation_options(kwargs: dict) -> dict:
        option_keys = {
            "landing_retry_allowed",
            "forbid_landing_retry",
            "landing_retry_budget",
            "landing_diff_threshold",
            "landing_window_frames",
            "landing_sample_interval_ms",
            "ignore_actuation_profile_skip",
        }
        return {key: kwargs.pop(key) for key in list(kwargs) if key in option_keys}

    def _scene_ref_for_target(self) -> dict | None:
        if self._last_scene is None:
            return None
        return {
            "frame_id": self._last_scene.frame_id,
            "page_id": self._last_scene.page_id,
            "scene_type": self._last_scene.semantic_scene_type or self._last_scene.scene_type,
        }

    def _reground_tap_point(self, *, target: str):
        """Re-perceive and re-locate ``target``; return its current tap point.

        P2: a fresh OCR read (``find_text``) relocates the element after a
        drag-scroll / animation moved it. P1: if OCR cannot find it and a VLM is
        wired, escalate to ``describe`` (VLM grounding) and retry the lookup.
        Returns ``None`` when the target cannot be re-located.
        """
        if not target:
            return None
        try:
            # Re-locate against the scene the prior attempt's fresh-frame
            # verification already captured (no extra capture / no frame cost).
            # P1: escalate to the VLM only when OCR cannot find the target.
            element = self._locate_in_last_scene(target)
            if element is None and self.kimi is not None:
                self.describe()
                element = self._locate_in_last_scene(target)
        except Exception as exc:
            logger.warning(f"reground tap target {target!r} failed: {exc}")
            return None
        if element is None:
            return None
        px, py = self._tap_point_for_element(element)
        return Point(px, py)

    def _locate_in_last_scene(self, target: str) -> UIElement | None:
        scene = self._last_scene
        if scene is None:
            return None
        return find_text(self._rows_before_nav_title(scene.elements), target, fuzzy_ratio=0.8)

    def _target_tap_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        actuation_options: dict | None = None,
    ) -> tuple[ActuationPlan, dict]:
        preferred = self._tap_point_for_element(element)
        control_bucket = control_bucket_for_element(element, viewport_size=self._viewport_size())
        offset = self._actuation_offset(control_bucket)
        if offset is not None and offset.space == "frame_px":
            preferred = (
                round(preferred[0] + offset.mean[0]),
                round(preferred[1] + offset.mean[1]),
            )
        candidates = CandidatePointGenerator().generate(element, preferred_point=preferred)
        coordinate_space = self._coordinate_space()
        source_coordinate_space = self._last_scene_coordinate_space or self._infer_input_coordinate_space()

        def build_command(point: Point, attempt_index: int) -> ActuationCommand:
            # On a retry, re-perceive and re-locate the target. If it has DRIFTED
            # from where we first saw it (drag-scroll overshoot / animation), tap
            # its current position — the dominant fix for "tapped but nothing
            # happened". If it has not moved, keep the candidate-point progression
            # (small offsets) for ordinary targeting error.
            regrounded = False
            tap_point = point
            tap_point_space = source_coordinate_space
            if attempt_index > 0:
                fresh = self._reground_tap_point(target=target)
                if fresh is not None:
                    orig_cx, orig_cy = element.box.center
                    if abs(fresh.x - orig_cx) + abs(fresh.y - orig_cy) > _REGROUND_MIN_SHIFT_PX:
                        tap_point = fresh
                        tap_point_space = self._last_scene_coordinate_space or source_coordinate_space
                        regrounded = True
            px, py = self._to_phone(tap_point.x, tap_point.y, coordinate_space=tap_point_space)
            return ActuationCommand(
                call=lambda px=px, py=py: self.effector.tap(px, py),
                kwargs={
                    "x": px,
                    "y": py,
                    "coordinate_space": coordinate_space,
                    "target_point": {"x": px, "y": py, "space": coordinate_space},
                    "target_point_frame": tap_point.to_dict(space=tap_point_space),
                    "actuation_attempt_index": attempt_index,
                    "regrounded": regrounded,
                },
            )

        plan = ActuationPlan(
            target_identity=target_identity_for_element(
                intent=intent,
                element=element,
                via=via,
                scene_ref=self._scene_ref_for_target(),
            ),
            method="mouse_tap",
            control_bucket=control_bucket,
            target_roi=Rect.from_box(element.box),
            roi_space=source_coordinate_space,
            candidate_target_points=candidates,
            build_command=build_command,
        )
        metadata = {
            "via": via,
            "target": target,
            "coordinate_space": coordinate_space,
            **self._picokvm_fresh_verify_kwargs("tap"),
            **(actuation_options or {}),
        }
        return plan, metadata

    def _target_actuation_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        actuation_options: dict | None = None,
        selection_source: str | None = None,
    ) -> tuple[str, ActuationPlan, dict]:
        control_bucket = control_bucket_for_element(element, viewport_size=self._viewport_size())
        if self._preferred_actuation_method(control_bucket) == "keyboard_focus_activate":
            op, (plan, metadata) = "key", self._target_keyboard_focus_plan(
                element=element,
                intent=intent,
                via=f"{via}:keyboard_focus_activate",
                target=target,
                modifier=0,
                keycode=_KEY_RETURN,
                actuation_options=actuation_options,
            )
        else:
            op, (plan, metadata) = "tap", self._target_tap_plan(
                element=element,
                intent=intent,
                via=via,
                target=target,
                actuation_options=actuation_options,
            )
        # CUQ-2.9: record how the target was resolved at selection time, so the
        # success-rate harness reads the real source instead of inferring it
        # post-hoc from "was the scene VLM-described".
        if selection_source:
            metadata = {**metadata, "selection_source": selection_source}
        return op, plan, metadata

    def _actuation_offset(self, control_bucket: dict[str, str]):
        profile = getattr(self.action_orchestrator, "actuation_profile", None)
        if profile is None:
            return None
        offset_for_bucket = getattr(profile, "offset_for_bucket", None)
        if not callable(offset_for_bucket):
            return None
        return offset_for_bucket(control_bucket)

    def _preferred_actuation_method(self, control_bucket: dict[str, str]) -> str:
        profile = getattr(self.action_orchestrator, "actuation_profile", None)
        if profile is None:
            return "mouse_tap"
        best_method_for_bucket = getattr(profile, "best_method_for_bucket", None)
        if not callable(best_method_for_bucket):
            return "mouse_tap"
        method = str(best_method_for_bucket(control_bucket, default="mouse_tap"))
        if method == "keyboard_focus_activate" and self.supports("key"):
            return method
        return "mouse_tap"

    def _target_keyboard_focus_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        modifier: int,
        keycode: int,
        actuation_options: dict | None = None,
    ) -> tuple[ActuationPlan, dict]:
        control_bucket = control_bucket_for_element(element, viewport_size=self._viewport_size())

        def build_command(point: Point, attempt_index: int) -> ActuationCommand:
            del point
            return ActuationCommand(
                call=lambda modifier=modifier, keycode=keycode: self.effector.key(modifier, keycode),
                kwargs={
                    "modifier": modifier,
                    "keycode": keycode,
                    "actuation_attempt_index": attempt_index,
                },
            )

        plan = ActuationPlan(
            target_identity=target_identity_for_element(
                intent=intent,
                element=element,
                via=via,
                scene_ref=self._scene_ref_for_target(),
            ),
            method="keyboard_focus_activate",
            control_bucket=control_bucket,
            target_roi=Rect.from_box(element.box),
            roi_space="focus_evidence",
            candidate_target_points=(Point(*element.box.center),),
            build_command=build_command,
        )
        metadata = {
            "via": via,
            "target": target,
            "policy_action": "tap",
            "coordinate_space": "keyboard_focus",
            **(actuation_options or {}),
        }
        return plan, metadata

    def tap_text(self, target: str, **kw) -> ActionResult:
        actuation_options = self._pop_actuation_options(kw)
        el = self.expect_text(target, **kw)
        op, plan, metadata = self._target_actuation_plan(
            element=el,
            intent=target,
            via="tap_text",
            target=target,
            actuation_options=actuation_options,
            selection_source=self._last_selection_source,
        )
        return self._execute_action(
            op,
            plan,
            **metadata,
        )

    def tap_element(
        self,
        element: UIElement,
        *,
        intent: str | None = None,
        via: str = "tap_element",
        target: str | None = None,
        landing_retry_allowed: bool | None = None,
        forbid_landing_retry: bool = False,
        landing_retry_budget: int | None = None,
        ignore_actuation_profile_skip: bool = False,
        retry_budget: int | None = None,
        unknown_policy: str | None = None,
        idempotent: bool | None = None,
    ) -> ActionResult:
        """Tap a known perceived element through target-bearing actuation feedback."""
        label = target or element.text or element.type or "element"
        actuation_options = {
            "forbid_landing_retry": forbid_landing_retry,
        }
        if ignore_actuation_profile_skip:
            actuation_options["ignore_actuation_profile_skip"] = True
        if landing_retry_allowed is not None:
            actuation_options["landing_retry_allowed"] = landing_retry_allowed
        if landing_retry_budget is not None:
            actuation_options["landing_retry_budget"] = landing_retry_budget
        if retry_budget is not None:
            actuation_options["retry_budget"] = retry_budget
        if unknown_policy is not None:
            actuation_options["unknown_policy"] = unknown_policy
        if idempotent is not None:
            actuation_options["idempotent"] = idempotent
        op, plan, metadata = self._target_actuation_plan(
            element=element,
            intent=intent or label,
            via=via,
            target=label,
            actuation_options=actuation_options,
        )
        return self._execute_action(
            op,
            plan,
            **metadata,
        )

    def tap_button(
        self,
        label: str,
        *,
        fuzzy_ratio: float = 0.8,
        landing_retry_allowed: bool | None = None,
        forbid_landing_retry: bool = False,
        landing_retry_budget: int | None = None,
    ) -> ActionResult:
        """Look for label only among type='button' elements (upgraded by
        Layer 2), which is more precise.

        Falls back to tap_text when no button is found (in case OCR did not
        recognize the button as a filled block).
        """
        scene = self.perceive()
        btn = find_button(scene.elements, label, fuzzy_ratio=fuzzy_ratio)
        actuation_options = {
            "forbid_landing_retry": forbid_landing_retry,
        }
        if landing_retry_allowed is not None:
            actuation_options["landing_retry_allowed"] = landing_retry_allowed
        if landing_retry_budget is not None:
            actuation_options["landing_retry_budget"] = landing_retry_budget
        if btn is None:
            return self.tap_text(label, fuzzy_ratio=fuzzy_ratio, **actuation_options)
        op, plan, metadata = self._target_actuation_plan(
            element=btn,
            intent=label,
            via="tap_button",
            target=label,
            actuation_options=actuation_options,
        )
        return self._execute_action(
            op,
            plan,
            **metadata,
        )

    def tap_intent(
        self,
        intent: str,
        *,
        fuzzy_ratio: float = 0.7,
        scene_hint: str | None = None,
        landing_retry_allowed: bool | None = None,
        forbid_landing_retry: bool = False,
        landing_retry_budget: int | None = None,
    ) -> ActionResult:
        """Find an element by its Layer 3 (Kimi) intent_label and tap it.

        Semantic matching (intent="确认登录" hits the OCR'd "登录" button) is
        more robust than tap_text / tap_button.

        Current scene has no intent_label → automatically run self.describe()
        to let Kimi populate it.
        Kimi not wired up (self.kimi is None) → fall back to tap_button(intent).
        """
        scene = self._last_scene if self._last_scene is not None else self.perceive()
        el = find_by_intent(scene.elements, intent, fuzzy_ratio=fuzzy_ratio) if scene else None
        if el is None:
            if self.kimi is None:
                if all(e.intent_label is None for e in scene.elements):
                    return self.tap_button(intent, fuzzy_ratio=fuzzy_ratio)
            else:
                self.describe(scene_hint=scene_hint or intent)
                scene = self._last_scene   # type: ignore[assignment]
                el = find_by_intent(scene.elements, intent, fuzzy_ratio=fuzzy_ratio) if scene else None
        if el is None:
            raise AssertionError(
                f"tap_intent({intent!r}) — no matching intent_label found in the current scene, "
                f"recognized intents={[e.intent_label for e in scene.elements if e.intent_label] if scene else []}"
            )
        actuation_options = {
            "forbid_landing_retry": forbid_landing_retry,
        }
        if landing_retry_allowed is not None:
            actuation_options["landing_retry_allowed"] = landing_retry_allowed
        if landing_retry_budget is not None:
            actuation_options["landing_retry_budget"] = landing_retry_budget
        op, plan, metadata = self._target_actuation_plan(
            element=el,
            intent=intent,
            via="tap_intent",
            target=intent,
            actuation_options=actuation_options,
            selection_source="vlm",  # CUQ-2.9: matched a VLM-derived intent label
        )
        return self._execute_action(
            op,
            plan,
            **metadata,
        )

    def tap_xy(self, x: int, y: int, *, coordinate_space: str | None = None) -> ActionResult:
        """Tap observation coordinates, optionally tagged with their source coordinate space."""
        input_space = self._normalize_input_coordinate_space(coordinate_space)
        px, py = self._to_phone(x, y, coordinate_space=coordinate_space)
        return self._execute_action(
            "tap",
            lambda: self.effector.tap(px, py),
            x=px,
            y=py,
            coordinate_space=self._coordinate_space(),
            target_point={"x": px, "y": py, "space": self._coordinate_space()},
            target_point_frame={"x": x, "y": y, "space": input_space},
            via="tap_xy",
            **self._picokvm_fresh_verify_kwargs("tap"),
        )

    def assistive_touch_open_menu(self, *, settle_s: float = 0.9) -> ActionResult:
        """Open the visible AssistiveTouch floating menu by visual detection.

        The button can be parked on either edge, so this primitive detects the
        current button in the latest frame and converts that frame coordinate to
        the effector coordinate space at execution time.
        """
        from glassbox.ios.assistive_touch import detect_assistive_touch_button

        frame = self.snapshot(stable=True if self.stability_policy is not None else None)
        candidate = detect_assistive_touch_button(frame.img)
        if candidate is None:
            return self._record_assistive_touch_failure(
                "AssistiveTouch floating button was not detected",
                via="assistive_touch.open_menu",
                target="AssistiveTouch",
            )
        x, y = candidate.center
        px, py = self._to_phone(x, y)
        result = self._execute_action(
            "tap",
            lambda: self.effector.tap(px, py),
            x=px,
            y=py,
            coordinate_space=self._coordinate_space(),
            target_point={"x": px, "y": py, "space": self._coordinate_space()},
            target_point_frame={"x": x, "y": y, "space": "frame_px"},
            via="assistive_touch.open_menu",
            target="AssistiveTouch",
            policy_action="assistive_touch",
            assistive_touch_candidate=candidate.to_report(),
        )
        if settle_s > 0:
            time.sleep(settle_s)
        return result

    def assistive_touch_tap_menu_item(
        self,
        label: str,
        *,
        path: tuple[str, ...] = (),
        open_menu: bool = True,
        allow_unsafe: bool = False,
        settle_s: float = 0.9,
        primitive_name: str | None = None,
    ) -> ActionResult:
        """Tap an AssistiveTouch menu item by current visual menu geometry.

        ``path`` names submenu hops, for example ``("设备", "更多")`` before
        tapping a third-level item. Unsafe targets such as SOS/restart are
        blocked before any physical input is sent.
        """
        from glassbox.ios.assistive_touch import (
            canonical_assistive_touch_label,
            is_assistive_touch_unsafe,
        )

        labels = (*path, label)
        unsafe = [canonical_assistive_touch_label(item) for item in labels if is_assistive_touch_unsafe(item)]
        if unsafe and not allow_unsafe:
            return self._record_assistive_touch_failure(
                f"unsafe AssistiveTouch action blocked: {unsafe[-1]}",
                via="assistive_touch.blocked",
                target=canonical_assistive_touch_label(label),
                path=path,
                safety_blocked=True,
                primitive_name=primitive_name,
            )
        last_result = None
        if open_menu:
            last_result = self.assistive_touch_open_menu(settle_s=settle_s)
            if not getattr(last_result, "ok", False):
                return last_result
        for segment in path:
            last_result = self._assistive_touch_tap_visible_item(
                segment,
                via="assistive_touch.navigate",
                path=(),
                settle_s=settle_s,
                allow_unsafe=allow_unsafe,
                primitive_name=primitive_name,
            )
            if not getattr(last_result, "ok", False):
                return last_result
        return self._assistive_touch_tap_visible_item(
            label,
            via="assistive_touch.menu_item",
            path=path,
            settle_s=settle_s,
            allow_unsafe=allow_unsafe,
            primitive_name=primitive_name,
        )

    def assistive_touch_run_primitive(
        self,
        name: str,
        *,
        open_menu: bool = True,
        settle_s: float = 0.9,
    ) -> ActionResult:
        """Execute a named safe AssistiveTouch menu primitive.

        Names come from ``assistive_touch_safe_primitives()``. This only
        exposes catalogued safe targets; unsafe system actions remain blocked.
        """
        from glassbox.ios.assistive_touch import assistive_touch_primitive

        primitive = assistive_touch_primitive(name)
        if primitive is None:
            return self._record_assistive_touch_failure(
                f"unknown AssistiveTouch primitive: {name}",
                via="assistive_touch.primitive",
                target=name,
                unsupported=True,
                primitive_name=name,
            )
        return self.assistive_touch_tap_menu_item(
            primitive.label,
            path=primitive.path,
            open_menu=open_menu,
            allow_unsafe=False,
            settle_s=settle_s,
            primitive_name=primitive.name,
        )

    def _assistive_touch_tap_visible_item(
        self,
        label: str,
        *,
        via: str,
        path: tuple[str, ...],
        settle_s: float,
        allow_unsafe: bool,
        primitive_name: str | None = None,
    ) -> ActionResult:
        from glassbox.ios.assistive_touch import (
            canonical_assistive_touch_label,
            find_assistive_touch_menu_item,
            is_assistive_touch_unsafe,
        )

        canonical = canonical_assistive_touch_label(label)
        if is_assistive_touch_unsafe(canonical) and not allow_unsafe:
            return self._record_assistive_touch_failure(
                f"unsafe AssistiveTouch action blocked: {canonical}",
                via="assistive_touch.blocked",
                target=canonical,
                path=path,
                safety_blocked=True,
                primitive_name=primitive_name,
            )
        scene = self.perceive(stable=True if self.stability_policy is not None else None)
        item = find_assistive_touch_menu_item(scene, canonical)
        if item is None and self.kimi is not None:
            try:
                scene = self.describe(scene_hint=f"AssistiveTouch menu item: {canonical}")
            except Exception as exc:
                logger.warning(f"AssistiveTouch VLM fallback failed for {canonical!r}: {exc}")
            else:
                item = find_assistive_touch_menu_item(scene, canonical)
        if item is None:
            return self._record_assistive_touch_failure(
                f"AssistiveTouch menu item not found: {canonical}",
                via=via,
                target=canonical,
                path=path,
                primitive_name=primitive_name,
            )
        if item.unsafe and not allow_unsafe:
            return self._record_assistive_touch_failure(
                f"unsafe AssistiveTouch action blocked: {canonical}",
                via="assistive_touch.blocked",
                target=canonical,
                path=path,
                safety_blocked=True,
                primitive_name=primitive_name,
            )
        x, y = item.tap_point
        px, py = self._to_phone(x, y)
        metadata = {
            "x": px,
            "y": py,
            "coordinate_space": self._coordinate_space(),
            "target_point": {"x": px, "y": py, "space": self._coordinate_space()},
            "target_point_frame": {"x": x, "y": y, "space": "frame_px"},
            "via": via,
            "target": canonical,
            "policy_action": "assistive_touch",
            "assistive_touch_path": list(path),
            "assistive_touch_item": item.to_report(),
        }
        if primitive_name is not None:
            metadata["assistive_touch_primitive"] = primitive_name
        # CUQ-3.12: AssistiveTouch menu taps verified on a possibly-stale frame.
        # Reopen for a fresh frame on PicoKVM (no-op on other backends) so the
        # post-tap verdict is read off live pixels.
        metadata.update(self._picokvm_fresh_verify_kwargs("tap"))
        result = self._execute_action(
            "tap",
            lambda: self.effector.tap(px, py),
            **metadata,
        )
        if settle_s > 0:
            time.sleep(settle_s)
        return result

    def _record_assistive_touch_failure(
        self,
        error: str,
        *,
        via: str,
        target: str,
        path: tuple[str, ...] = (),
        safety_blocked: bool = False,
        unsupported: bool = False,
        primitive_name: str | None = None,
    ) -> ActionResult:
        result = self._failed_action_result(
            error=error,
            unsupported=safety_blocked or unsupported,
        )
        metadata = {
            "via": via,
            "target": target,
            "policy_action": "assistive_touch",
            "assistive_touch_path": list(path),
            "safety_blocked": safety_blocked,
        }
        if primitive_name is not None:
            metadata["assistive_touch_primitive"] = primitive_name
        self._record_action("assistive_touch", result=result, **metadata)
        return result

    def keyboard_focus_activate(
        self,
        target: str,
        *,
        fuzzy_ratio: float = 0.8,
        modifier: int = 0,
        keycode: int = _KEY_RETURN,
    ) -> ActionResult:
        """Activate a target via keyboard focus/activation instead of mouse coordinates."""
        el = self.expect_text(target, fuzzy_ratio=fuzzy_ratio)
        plan, metadata = self._target_keyboard_focus_plan(
            element=el,
            intent=target,
            via="keyboard_focus_activate",
            target=target,
            modifier=modifier,
            keycode=keycode,
        )
        return self._execute_action(
            "key",
            plan,
            **metadata,
        )

    def double_tap_xy(
        self,
        x: int,
        y: int,
        *,
        coordinate_space: str | None = None,
        target: str | None = None,
    ) -> ActionResult:
        input_space = self._normalize_input_coordinate_space(coordinate_space)
        px, py = self._to_phone(x, y, coordinate_space=coordinate_space)
        metadata = {"target": target} if target else {}
        return self._execute_action(
            "double_tap",
            lambda: self.effector.double_tap(px, py),
            x=px,
            y=py,
            coordinate_space=self._coordinate_space(),
            target_point={"x": px, "y": py, "space": self._coordinate_space()},
            target_point_frame={"x": x, "y": y, "space": input_space},
            via="double_tap_xy",
            **metadata,
            **self._picokvm_fresh_verify_kwargs("double_tap"),
        )

    def long_press_xy(
        self,
        x: int,
        y: int,
        *,
        coordinate_space: str | None = None,
        hold_ms: int = 500,
        target: str | None = None,
    ) -> ActionResult:
        input_space = self._normalize_input_coordinate_space(coordinate_space)
        px, py = self._to_phone(x, y, coordinate_space=coordinate_space)
        metadata = {"target": target} if target else {}
        return self._execute_action(
            "long_press",
            lambda: self.effector.long_press(px, py, hold_ms=hold_ms),
            x=px,
            y=py,
            coordinate_space=self._coordinate_space(),
            target_point={"x": px, "y": py, "space": self._coordinate_space()},
            target_point_frame={"x": x, "y": y, "space": input_space},
            hold_ms=hold_ms,
            via="long_press_xy",
            **metadata,
            **self._picokvm_fresh_verify_kwargs("long_press"),
        )

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
        via: str = "swipe_xy",
        policy_action: str | None = None,
        settle_strategy: str | None = None,
        fixed_delay_ms: int | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        fresh_delay_ms: int | None = None,
        fresh_source_reopen: bool | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        px1, py1 = self._to_phone(x1, y1, coordinate_space=coordinate_space)
        px2, py2 = self._to_phone(x2, y2, coordinate_space=coordinate_space)
        action_kwargs = {
            "x1": px1,
            "y1": py1,
            "x2": px2,
            "y2": py2,
            "coordinate_space": self._coordinate_space(),
            "steps": steps,
            "end_hold_ms": end_hold_ms,
            "via": via,
        }
        if policy_action:
            action_kwargs["policy_action"] = policy_action
        _add_optional_action_metadata(
            action_kwargs,
            settle_strategy=settle_strategy,
            fixed_delay_ms=fixed_delay_ms,
            window_duration_ms=window_duration_ms,
            stream_timeout_ms=stream_timeout_ms,
            sample_interval_ms=sample_interval_ms,
            max_stream_frames=max_stream_frames,
            fresh_delay_ms=fresh_delay_ms,
            fresh_source_reopen=fresh_source_reopen,
            expected_state=expected_state,
            expect_visible=expect_visible,
            expect_page=expect_page,
        )
        # CUQ-3.12: default the swipe verification to a fresh-frame reopen on
        # PicoKVM (no-op on other backends), without overriding any settle/fresh
        # option the caller set explicitly.
        for key, value in self._picokvm_fresh_verify_kwargs("swipe").items():
            action_kwargs.setdefault(key, value)
        return self._execute_action(
            "swipe",
            lambda: self.effector.swipe(
                px1, py1, px2, py2, steps=steps, end_hold_ms=end_hold_ms,
            ),
            **action_kwargs,
        )

    def drag_xy(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        coordinate_space: str | None = None,
        down_hold_ms: int = 200,
        up_hold_ms: int = 100,
        settle_strategy: str | None = None,
        fixed_delay_ms: int | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        fresh_delay_ms: int | None = None,
        fresh_source_reopen: bool | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        px1, py1 = self._to_phone(x1, y1, coordinate_space=coordinate_space)
        px2, py2 = self._to_phone(x2, y2, coordinate_space=coordinate_space)
        action_kwargs = {
            "x1": px1,
            "y1": py1,
            "x2": px2,
            "y2": py2,
            "coordinate_space": self._coordinate_space(),
            "down_hold_ms": down_hold_ms,
            "up_hold_ms": up_hold_ms,
            "via": "drag_xy",
        }
        _add_optional_action_metadata(
            action_kwargs,
            settle_strategy=settle_strategy,
            fixed_delay_ms=fixed_delay_ms,
            window_duration_ms=window_duration_ms,
            stream_timeout_ms=stream_timeout_ms,
            sample_interval_ms=sample_interval_ms,
            max_stream_frames=max_stream_frames,
            fresh_delay_ms=fresh_delay_ms,
            fresh_source_reopen=fresh_source_reopen,
            expected_state=expected_state,
            expect_visible=expect_visible,
            expect_page=expect_page,
        )
        return self._execute_action(
            "drag",
            lambda: self.effector.drag(
                px1, py1, px2, py2,
                down_hold_ms=down_hold_ms, up_hold_ms=up_hold_ms,
            ),
            **action_kwargs,
        )

    def scroll_wheel(
        self,
        ticks: int,
        *,
        horizontal: int = 0,
        focus_x: int | None = None,
        focus_y: int | None = None,
        focus_click: bool = False,
        interval_ms: int | None = None,
    ) -> ActionResult:
        """Mouse-wheel scroll. This is separate from swipe/drag semantics."""
        w, h = self._viewport_size()
        cx = w // 2 if focus_x is None else int(focus_x)
        cy = int(h * 0.55) if focus_y is None else int(focus_y)
        px, py = self._to_phone(cx, cy)
        kwargs = {
            "horizontal": int(horizontal),
            "focus_x": px,
            "focus_y": py,
        }
        if focus_click:
            kwargs["focus_click"] = True
        if interval_ms is not None:
            kwargs["interval_ms"] = int(interval_ms)
        if not self.supports("scroll_wheel"):
            unsupported_kwargs = {
                "ticks": int(ticks),
                "horizontal": int(horizontal),
                "focus_x": px,
                "focus_y": py,
                "coordinate_space": self._coordinate_space(),
                "via": "scroll_wheel",
            }
            if focus_click:
                unsupported_kwargs["focus_click"] = True
            return self._unsupported_action(
                "scroll_wheel",
                **unsupported_kwargs,
            )
        action_kwargs = {
            "ticks": int(ticks),
            "horizontal": int(horizontal),
            "focus_x": px,
            "focus_y": py,
            "coordinate_space": self._coordinate_space(),
            "via": "scroll_wheel",
        }
        if focus_click:
            action_kwargs["focus_click"] = True
        action_kwargs.update(self._picokvm_fresh_verify_kwargs("scroll_wheel"))
        return self._execute_action(
            "scroll_wheel",
            lambda: self.effector.scroll_wheel(int(ticks), **kwargs),
            **action_kwargs,
        )

    def _default_wheel_ticks(self) -> int:
        ticks = int(self.gesture_config.wheel_ticks_per_scroll)
        return max(1, ticks)

    def wheel_scroll_down(self, *, ticks: int | None = None) -> ActionResult:
        """Scroll content down using mouse-wheel semantics."""
        amount = self._default_wheel_ticks() if ticks is None else int(ticks)
        if self.gesture_config.wheel_invert:
            amount *= -1
        return self.scroll_wheel(amount)

    def wheel_scroll_up(self, *, ticks: int | None = None) -> ActionResult:
        """Scroll content up using mouse-wheel semantics."""
        amount = self._default_wheel_ticks() if ticks is None else int(ticks)
        if self.gesture_config.wheel_invert:
            amount *= -1
        return self.scroll_wheel(-amount)

    def _picokvm_drag_preset(
        self,
        method_name: str,
        *,
        via: str,
        policy_action: str,
        **metadata: Any,
    ) -> ActionResult | None:
        if self._effector_backend() != "picokvm":
            return None
        method = getattr(self.effector, method_name, None)
        if not callable(method):
            return None
        action_metadata = {
            **self._picokvm_fresh_verify_kwargs("drag"),
            **{key: value for key, value in metadata.items() if value is not None},
        }
        return self._execute_action(
            "drag",
            method,
            via=via,
            policy_action=policy_action,
            preset=f"picokvm.{method_name}",
            strategy="raw_hid_logical_drag",
            **action_metadata,
        )

    def swipe_up(
        self,
        *,
        fraction: float = 0.55,
        settle_strategy: str | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        """Vertical upward touch swipe."""
        metadata = {
            "settle_strategy": settle_strategy,
            "window_duration_ms": window_duration_ms,
            "stream_timeout_ms": stream_timeout_ms,
            "sample_interval_ms": sample_interval_ms,
            "max_stream_frames": max_stream_frames,
            "expected_state": expected_state,
            "expect_visible": expect_visible,
            "expect_page": expect_page,
        }
        preset = self._picokvm_drag_preset("list_scroll_up", via="swipe_up", policy_action="scroll", **metadata)
        if preset is not None:
            return preset
        w, h = self._viewport_size()
        x = w // 2
        return self.swipe_xy(
            x,
            int(h * 0.78),
            x,
            int(h * max(0.15, 0.78 - fraction)),
            via="swipe_up",
            policy_action="scroll",
            **metadata,
        )

    def swipe_down(
        self,
        *,
        fraction: float = 0.55,
        settle_strategy: str | None = None,
        window_duration_ms: int | None = None,
        stream_timeout_ms: int | None = None,
        sample_interval_ms: int | None = None,
        max_stream_frames: int | None = None,
        expected_state: dict[str, Any] | None = None,
        expect_visible: str | tuple[str, ...] | list[str] | None = None,
        expect_page: str | None = None,
    ) -> ActionResult:
        """Vertical downward touch swipe."""
        metadata = {
            "settle_strategy": settle_strategy,
            "window_duration_ms": window_duration_ms,
            "stream_timeout_ms": stream_timeout_ms,
            "sample_interval_ms": sample_interval_ms,
            "max_stream_frames": max_stream_frames,
            "expected_state": expected_state,
            "expect_visible": expect_visible,
            "expect_page": expect_page,
        }
        preset = self._picokvm_drag_preset("list_scroll_down", via="swipe_down", policy_action="scroll", **metadata)
        if preset is not None:
            return preset
        w, h = self._viewport_size()
        x = w // 2
        return self.swipe_xy(
            x,
            int(h * 0.30),
            x,
            int(h * min(0.90, 0.30 + fraction)),
            via="swipe_down",
            policy_action="scroll",
            **metadata,
        )

    def _page_drag_xy(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        via: str,
        down_hold_ms: int = 350,
        up_hold_ms: int = 150,
    ) -> ActionResult:
        px1, py1 = self._to_phone(x1, y1)
        px2, py2 = self._to_phone(x2, y2)
        return self._execute_action(
            "drag",
            lambda: self.effector.drag(
                px1, py1, px2, py2,
                down_hold_ms=down_hold_ms,
                up_hold_ms=up_hold_ms,
            ),
            x1=px1,
            y1=py1,
            x2=px2,
            y2=py2,
            coordinate_space=self._coordinate_space(),
            down_hold_ms=down_hold_ms,
            up_hold_ms=up_hold_ms,
            via=via,
            policy_action="page",
        )

    def swipe_left(self, *, fraction: float = 0.84, y_fraction: float = 0.45) -> ActionResult:
        """Horizontal page-left gesture, e.g. advance to the next iOS Home page.

        The hardware ``swipe`` command acknowledges successfully on SpringBoard
        but only moves the AssistiveTouch pointer. A mouse press-drag at the
        page midpoint is the validated page-turn primitive.
        """
        preset = self._picokvm_drag_preset("page_slide_left", via="swipe_left", policy_action="page")
        if preset is not None:
            return preset
        w, h = self._viewport_size()
        y = int(h * y_fraction)
        return self._page_drag_xy(
            int(w * 0.92),
            y,
            int(w * max(0.08, 0.92 - fraction)),
            y,
            via="swipe_left",
        )

    def swipe_right(self, *, fraction: float = 0.84, y_fraction: float = 0.45) -> ActionResult:
        """Horizontal page-right gesture, e.g. move to the previous iOS Home page."""
        preset = self._picokvm_drag_preset("page_slide_right", via="swipe_right", policy_action="page")
        if preset is not None:
            return preset
        w, h = self._viewport_size()
        y = int(h * y_fraction)
        return self._page_drag_xy(
            int(w * 0.08),
            y,
            int(w * min(0.92, 0.08 + fraction)),
            y,
            via="swipe_right",
        )

    def close_foreground_app(self) -> ActionResult:
        """Close the current foreground app using a backend-specific drag path."""
        if not self.supports("close_foreground_app"):
            return self._unsupported_action("close_foreground_app")
        close_app = getattr(self.effector, "close_foreground_app", None)
        if not callable(close_app):
            return self._unsupported_action("close_foreground_app", strategy="missing_effector_method")
        return self._execute_action(
            "close_foreground_app",
            close_app,
            policy_action="close_foreground_app",
            strategy="home_indicator_drag",
            **self._picokvm_fresh_verify_kwargs("drag"),
        )

    def back_gesture(self) -> ActionResult:
        """iOS back navigation — sent as the Meta+[ keyboard shortcut.

        The left-edge swipe gesture cannot work on this bridge: it injects a
        mouse pointer, not a touch digitizer, so an edge swipe just mis-taps
        whatever row sits at the vertical midpoint instead of triggering
        interactive-pop (verified on-device 2026-05-18). Meta+[ is the reliable
        back path. The method name and its back_gesture/back trace metadata are
        kept so existing callers and the memory graph keep working.
        """
        if self._uses_semantic_plan("back"):
            # CUQ-0.1: ladder nav_back_tap -> keyboard_back -> edge_back_gesture
            # with verified-failure switching, instead of the single-shot path
            # below that commits to ONE strategy with no escalation.
            return self._run_semantic_plan(
                "back",
                via="back_gesture",
                policy_action="back",
                **self._picokvm_fresh_verify_kwargs("back"),
            )
        strategy = self._system_action_strategy("back")
        if strategy == "unsupported":
            return self._unsupported_action("back_gesture", strategy=strategy)
        allowed, guard_reason, nav_back_point = self._picokvm_back_context()
        if not allowed:
            # Not finding a back target on the current scene is a recoverable
            # miss, not a backend capability gap, so this must never fail-fast:
            # recovery layers need to stay free to try another strategy (e.g. a
            # blind top-left chevron tap). Record the same unsupported result as
            # _unsupported_action would, just without raising.
            result = self._failed_action_result(
                error="unsupported action: back_gesture",
                unsupported=True,
            )
            self._record_action(
                "back_gesture",
                result=result,
                strategy=strategy,
                guard=guard_reason,
            )
            return result
        if nav_back_point is not None:
            x, y = nav_back_point
            px, py = self._to_phone(x, y)
            return self._execute_action(
                "back",
                lambda: self.effector.tap(px, py),
                x=px,
                y=py,
                coordinate_space=self._coordinate_space(),
                target_point={"x": px, "y": py, "space": self._coordinate_space()},
                target_point_frame={"x": x, "y": y, "space": "frame_px"},
                via="back_gesture",
                policy_action="back",
                strategy="nav_back_tap",
                guard=guard_reason,
                **self._picokvm_fresh_verify_kwargs("back"),
            )
        back = getattr(self.effector, "back", None)
        if callable(back):
            return self._execute_action(
                "back",
                back,
                via="back_gesture",
                policy_action="back",
                strategy=strategy,
                **self._picokvm_fresh_verify_kwargs("back"),
            )
        return self._execute_action(
            "key",
            lambda: self.effector.key(_MOD_META_LEFT, 0x2F),
            modifier=_MOD_META_LEFT,
            keycode=0x2F,
            via="back_gesture",
            policy_action="back",
            strategy=strategy,
        )

    def home(self) -> ActionResult:
        strategy = self._system_action_strategy("home")
        if strategy in {"direct", "keyboard_combo"}:
            result = self._execute_action(
                "home",
                lambda: self.effector.home(),
                strategy=strategy,
                **self._picokvm_fresh_verify_kwargs("home"),
            )
            if self._picokvm_home_needs_fallback(result):
                return self._picokvm_home_pointer_fallback(
                    fallback_from=strategy, last_result=result
                )
            return result
        if strategy == "assistive_touch":
            return self._home_via_assistive_touch_menu()
        return self._unsupported_action("home", strategy=strategy)

    def _picokvm_home_needs_fallback(self, result: ActionResult) -> bool:
        return (
            self._effector_backend() == "picokvm"
            and result.semantic_verifier == "ios_home_screen_visible"
            and result.semantic_status != "succeeded"
        )

    def _home_via_assistive_touch_menu(self) -> ActionResult:
        return self.assistive_touch_tap_menu_item(
            "主屏幕",
            open_menu=True,
            settle_s=0.9,
            primitive_name="assistive_touch.home",
        )

    def _expects_assistive_touch(self) -> bool:
        capabilities = self._backend_capabilities()
        return bool(capabilities is not None and getattr(capabilities, "requires_assistive_touch", False))

    def _picokvm_home_pointer_fallback(
        self, *, fallback_from: str, last_result: ActionResult
    ) -> ActionResult:
        """Recover Home with pointer-only paths when keyboard Cmd-H did not land.

        On PicoKVM rigs the hardware-keyboard Cmd-H can be accepted by the device
        yet ignored by iOS, and the home-indicator drag is unreliable, while the
        pure-pointer AssistiveTouch menu Home works. Prefer AssistiveTouch, then
        the indicator drag, and return the best (most home-like) result seen.
        """
        result = last_result
        if self._expects_assistive_touch():
            at_result = self._verified_pointer_home(
                self._home_via_assistive_touch_menu,
                strategy="assistive_touch_home_fallback",
                fallback_from=fallback_from,
            )
            if self._home_reached(at_result):
                return at_result
            result = at_result
        close_app = getattr(self.effector, "close_foreground_app", None)
        if callable(close_app):
            drag_result = self._execute_action(
                "home",
                close_app,
                strategy="home_indicator_drag_fallback",
                fallback_from=fallback_from,
                **self._picokvm_fresh_verify_kwargs("home"),
            )
            if self._home_reached(drag_result):
                return drag_result
            result = drag_result
        return result

    @staticmethod
    def _home_reached(result: ActionResult) -> bool:
        return result is not None and getattr(result, "semantic_status", None) == "succeeded"

    def _verified_pointer_home(self, call, **metadata) -> ActionResult:
        """Run a Home recovery that performs its own sub-taps, then verify the
        home screen with a fresh frame.

        Unlike :meth:`_execute_action`, this does not re-wrap the call in the
        record/orchestrator path, so the AssistiveTouch menu's own taps are not
        double-recorded or nested inside another action.
        """
        verify_kwargs = self._picokvm_fresh_verify_kwargs("home")
        before_frame = self._last_frame
        before_scene = self._last_scene
        result = call()
        if not verify_kwargs or result is None or not getattr(result, "ok", True):
            return result
        return self._verify_fresh_action_result(
            "home",
            result,
            metadata={**metadata, **verify_kwargs},
            before_frame=before_frame,
            before_scene=before_scene,
            delay_ms=int(verify_kwargs.get("_semantic_verify_delay_ms", 0) or 0),
            reopen_source=bool(verify_kwargs.get("_semantic_verify_reopen_source", False)),
        )

    def recents(self) -> ActionResult:
        strategy = self._system_action_strategy("recents")
        if strategy in {"direct", "keyboard_combo"}:
            return self._execute_action("recents", lambda: self.effector.recents(), strategy=strategy)
        return self._unsupported_action("recents", strategy=strategy)

    def control_center(self) -> ActionResult:
        strategy = self._system_action_strategy("control_center")
        if strategy == "unsupported":
            return self._unsupported_action("control_center", strategy=strategy)
        return self._execute_action(
            "control_center", lambda: self.effector.control_center(), strategy=strategy)

    def notification_center(self) -> ActionResult:
        strategy = self._system_action_strategy("notification_center")
        if strategy == "unsupported":
            return self._unsupported_action("notification_center", strategy=strategy)
        return self._execute_action(
            "notification_center", lambda: self.effector.notification_center(), strategy=strategy)

    def open_app(
        self,
        label: str,
        *,
        aliases: tuple[str, ...] = (),
        max_pages: int = 8,
        settle_s: float = 0.8,
    ) -> ActionResult:
        """Open an iOS app from SpringBoard as one semantic action.

        The implementation uses lower-level Home/search/tap helpers internally,
        but the computer-use runtime records the outer `open_app` intent as one
        action attempt. This keeps the AI-facing API semantic while preserving
        raw helper operations for legacy recorder/debug paths.
        """
        from glassbox.effector import ActionResult

        if self.springboard_provider is None:
            return self._unsupported_action(
                "open_app",
                app=label,
                aliases=list(aliases),
                max_pages=max_pages,
                settle_s=settle_s,
            )
        target = AppLaunchTarget(bundle_id="", labels=(label,), aliases=aliases)

        def _open() -> ActionResult:
            orchestrator = self.action_orchestrator
            self.action_orchestrator = None
            try:
                ok = self.springboard_provider.open_app(
                    self,
                    target,
                    max_pages=max_pages,
                    settle_s=settle_s,
                    icon_map=self.icon_map,
                )
            finally:
                self.action_orchestrator = orchestrator
            return ActionResult(
                ok=bool(ok),
                backend="phone",
                connected=self.has_real_effector(),
                synthetic=True,
                error=None if ok else f"app not opened: {label}",
            )

        return self._execute_action(
            "open_app",
            _open,
            app=label,
            aliases=list(aliases),
            max_pages=max_pages,
            settle_s=settle_s,
        )

    def type(self, text: str, *, verify: bool | None = None,
             max_switches: int = 2) -> ActionResult:
        """Type text via the HID keyboard.

        HID delivers raw keycodes, so the effect depends on the controlled
        device's active input source:

        - Convention: keep the device's hardware keyboard on the English (ABC)
          source. ASCII then types literally.
        - Closed loop: when ``verify`` is on (default for ASCII text), the
          typed text is read back; if a non-English IME swallowed it as
          composition, ``switch_input_source()`` cycles the IME, the field is
          cleared, and the text retyped — bounded by ``max_switches``.
        - CJK / non-ASCII text cannot be expressed as HID keycodes; it is
          routed through the clipboard: the device's GlassboxHelper sets
          UIPasteboard, then Meta+V pastes it (see ``_type_via_clipboard``).

        Pass ``verify=False`` for fields whose content is not OCR-visible
        (e.g. password fields), where read-back cannot confirm the text.
        """
        if not _is_ascii(text):
            # CJK / non-ASCII: HID keycodes cannot express it; use clipboard + Meta+V.
            return self._type_via_clipboard(text)
        if verify is None:
            verify = True
        result = self._execute_action("type", lambda: self.effector.type(text), text=text)
        if not verify:
            return result
        for attempt in range(1, max_switches + 1):
            if not self._ime_composing():
                return result
            # a CJK IME is composing the keystrokes — cycle source, clear, retype
            logger.info(
                f"type({text!r}): CJK IME composing detected — "
                f"switching input source (attempt {attempt}/{max_switches})"
            )
            self.switch_input_source()
            time.sleep(0.4)
            self._clear_focused_field()
            result = self._execute_action(
                "type", lambda: self.effector.type(text),
                text=text, type_switch_attempt=attempt,
            )
        if self._ime_composing():
            logger.warning(
                f"type({text!r}) still composing after {max_switches} input-source switches"
            )
        return result

    def _type_via_clipboard(self, text: str) -> ActionResult:
        """Input non-ASCII text by setting the clipboard, then pasting (Meta+V).

        HID keycodes cannot express CJK. The controlled device's GlassboxHelper sets
        ``UIPasteboard`` (the ``set_clipboard`` effector action), and Meta+V
        pastes it into the focused field. Note: this overwrites the device
        clipboard.

        iOS forbids a *background* app from writing the pasteboard, so the
        GlassboxHelper app is foregrounded around ``set_clipboard`` and the controlled
        app re-foregrounded before the paste (Option A). Foregrounding is pure
        HID — the app is opened from the Home screen (see ``_foreground_app``),
        so this needs no devicectl / Xcode / Developer Mode at runtime. The
        A-dance runs only when ``app_labels`` + ``icon_map`` + a VLM (``kimi``)
        are all available; otherwise this is a bare set_clipboard+paste, which
        only works if GlassboxHelper already happens to be foreground.
        """
        if not self.supports("set_clipboard"):
            logger.warning(
                f"type({text!r}): non-ASCII text needs effector.set_clipboard "
                "(GlassboxHelper setClipboard) — unavailable on this effector"
            )
            return self._unsupported_action("type", text=text)
        dance = (
            self.app_labels is not None
            and self.icon_map is not None
            and self.kimi is not None
            and self.springboard_provider is not None
        )
        if dance:
            self._foreground_app(_HIDGLASSBOX_LABELS)
        self._execute_action(
            "set_clipboard", lambda: self.effector.set_clipboard(text), text=text)
        if dance:
            self._foreground_app(self.app_labels)
        return self._execute_action(
            "paste", lambda: self.effector.paste(), via="type_clipboard", text=text)

    def _foreground_app(self, labels: tuple[str, ...]) -> None:
        """Foreground an app by opening it from the Home screen — pure HID.

        Uses the VLM springboard icon map (``open_app_via_icon_map``), so it
        needs no devicectl / Xcode / Developer Mode at runtime. The app must
        have a Home-screen icon on the current Home page.
        """
        if self.springboard_provider is None:
            return
        target = AppLaunchTarget(bundle_id="", labels=labels)
        self.springboard_provider.foreground_app(
            self,
            target,
            icon_map=self.icon_map,
            settle_s=self._cjk_foreground_settle_s,
        )

    # A CJK IME candidate-bar entry — a digit followed by a Han character.
    # OCR merges/splits bar cells unpredictably, so this is matched anywhere in
    # an element's text (findall), not anchored.
    _IME_CANDIDATE_RE = re.compile(r"[1-9]\s*[一-鿿]")

    def _ime_composing(self) -> bool:
        """Best-effort: True if a CJK IME candidate bar is on screen.

        The candidate bar (a horizontal row of numbered ``<digit><word>``
        cells just above the keyboard) is the direct signal that keystrokes
        are being composed rather than typed literally — more reliable than
        reading the field, since an ASCII composing buffer still shows the
        literal letters. Detected by counting ``<digit><Han>`` entries in the
        bottom screen band; OCR often merges several cells into one element.
        """
        time.sleep(0.4)  # let the field / candidate bar render
        try:
            scene = self.perceive()
        except Exception:
            return False  # perception unavailable — do not spuriously retry
        try:
            _, height = self._viewport_size()
        except Exception:
            height = 956
        y_floor = height * 0.7  # candidate bar sits low, near the keyboard
        hits = 0
        for e in scene.elements:
            if e.text and e.box.center[1] >= y_floor:
                hits += len(self._IME_CANDIDATE_RE.findall(e.text))
        return hits >= 2

    def _clear_focused_field(self) -> None:
        """Clear the focused text field: cancel IME composition, select all, delete."""
        self.key(0, _KEY_ESC)        # cancel any pending IME composition
        self.key(_MOD_META_LEFT, _KEY_A)   # select all
        self.key(0, _KEY_DELETE)     # delete the selection

    def key(self, modifier: int, keycode: int) -> ActionResult:
        return self._execute_action(
            "key",
            lambda: self.effector.key(modifier, keycode),
            modifier=modifier,
            keycode=keycode,
        )

    def switch_input_source(self) -> ActionResult:
        """Cycle the hardware-keyboard input source (Ctrl+Space).

        iOS offers only next-source cycling, no direct select. ``type`` uses
        this to recover when a non-English IME intercepts ASCII keystrokes as
        composition instead of literal text.
        """
        strategy = self._system_action_strategy("switch_input_source")
        if strategy == "unsupported":
            return self._unsupported_action("switch_input_source", strategy=strategy)
        return self._execute_action(
            "key",
            lambda: self.effector.key(_MOD_CTRL, _KEY_SPACE),
            modifier=_MOD_CTRL,
            keycode=_KEY_SPACE,
            via="switch_input_source",
            strategy=strategy,
        )

    def paste(self) -> ActionResult:
        strategy = self._system_action_strategy("paste")
        if strategy == "unsupported":
            return self._unsupported_action("paste", strategy=strategy)
        return self._execute_action("paste", lambda: self.effector.paste(), strategy=strategy)

    # —— Metadata ——
    def has_real_effector(self) -> bool:
        return self.effector.is_connected()
