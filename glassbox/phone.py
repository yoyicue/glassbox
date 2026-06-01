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

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from glassbox.action.actuation import (
    ActuationPlan,
)
from glassbox.action.context import ActionContext
from glassbox.action_runner import ActionRunner
from glassbox.assistive_touch_driver import AssistiveTouchDriver
from glassbox.boundaries import SceneClassifier as PlatformSceneClassifier
from glassbox.cognition import (
    AppleVisionOCR,
    HeuristicTyper,
    Scene,
    SceneClassification,
    UIElement,
    find_button,
    find_by_intent,
    find_text,
)
from glassbox.coordinate_mapper import CoordinateMapper
from glassbox.effector import NOOP_CAPABILITIES, BackendCapabilities
from glassbox.element_selector import ElementSelector
from glassbox.gesture_executor import GestureExecutor
from glassbox.perception.app_viewport import ViewportCrop
from glassbox.perceptor import Perceptor
from glassbox.system_navigator import SystemNavigator
from glassbox.target_planner import TargetPlanner
from glassbox.text_input import TextInput

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


@dataclass(frozen=True)
class PhoneFeatureFlags:
    detect_icons_in_perceive: bool = False
    strict_target_matching: bool = False
    require_home_icon_grid: bool = False
    reverify_fresh_frame: bool = False
    coldstart_promote_controls: bool = False
    vlm_set_of_mark: bool = False
    memory_locate_priors: bool = False
    strict_settings_detail: bool = False
    ai_scroll_prefer_wheel: bool = False
    vlm_reground_selection: bool = False
    whitebox_hint_selection: bool = False


@dataclass(frozen=True)
class PhoneRuntimeOptions:
    action_fail_fast: bool = True
    auto_refresh_letterbox_crop: bool = False
    letterbox_refresh_consecutive: int = 1
    default_observation_scope: str = "device"
    app_viewport_mode: str = "auto"


@dataclass(frozen=True)
class OcrTemporalVotingConfig:
    enabled: bool = False
    frames: int = 3
    min_presence: int = 2
    pos_tol: int = 20
    sample_spacing_ms: int = 0
    outer_timeout: float = 0.0
    keep_raw_samples: bool = False


@dataclass(frozen=True)
class PhoneObservationConfig:
    max_ocr_elements: int = 800
    max_ocr_text_chars: int = 1024
    ocr_timeout: float = 0.0
    perceive_cache_diff: float = 0.005
    ocr_temporal_voting: OcrTemporalVotingConfig = field(default_factory=OcrTemporalVotingConfig)
    settings_root_label_aliases: Mapping[str, str] | None = None
    settings_root_fuzzy_aliases: bool = False


# HID modifiers / keycodes used by the keyboard helpers.
_KEY_RETURN = 0x28

def _target_planner_for(phone: Any) -> TargetPlanner:
    planner = getattr(phone, "target_planner", None)
    return planner if planner is not None else TargetPlanner(phone)


def _assistive_touch_driver_for(phone: Any) -> AssistiveTouchDriver:
    driver = getattr(phone, "assistive_touch_driver", None)
    return driver if driver is not None else AssistiveTouchDriver(phone)


def _gesture_executor_for(phone: Any) -> GestureExecutor:
    executor = getattr(phone, "gesture_executor", None)
    return executor if executor is not None else GestureExecutor(phone)


def _system_navigator_for(phone: Any) -> SystemNavigator:
    navigator = getattr(phone, "system_navigator", None)
    return navigator if navigator is not None else SystemNavigator(phone)


def _text_input_for(phone: Any) -> TextInput:
    text_input = getattr(phone, "text_input", None)
    return text_input if text_input is not None else TextInput(phone)


def _element_selector_for(phone: Any) -> ElementSelector:
    selector = getattr(phone, "element_selector", None)
    return selector if selector is not None else ElementSelector(phone)


def _perceptor_for(phone: Any) -> Perceptor:
    perceptor = getattr(phone, "perceptor", None)
    return perceptor if perceptor is not None else Perceptor(phone)


def _action_runner_for(phone: Any) -> ActionRunner:
    runner = getattr(phone, "action_runner", None)
    return runner if runner is not None else ActionRunner(phone)


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
        feature_flags: PhoneFeatureFlags | None = None,
        runtime_options: PhoneRuntimeOptions | None = None,
        observation_config: PhoneObservationConfig | None = None,
        app_viewport: ViewportCrop | None = None,
        app_viewport_mode: str = "auto",
        default_observation_scope: str = "device",
        auto_refresh_letterbox_crop: bool = False,
        letterbox_refresh_consecutive: int = 1,
        semantic_plan_ops: frozenset[str] | None = None,
        detect_icons_in_perceive: bool = False,
        max_ocr_elements: int = 800,
        max_ocr_text_chars: int = 1024,
        ocr_timeout: float = 0.0,
        strict_target_matching: bool = False,
        require_home_icon_grid: bool = False,
        reverify_fresh_frame: bool = False,
        coldstart_promote_controls: bool = False,
        vlm_set_of_mark: bool = False,
        memory_locate_priors: bool = False,
        strict_settings_detail: bool = False,
        ai_scroll_prefer_wheel: bool = False,
        vlm_reground_selection: bool = False,
        whitebox_hint_selection: bool = False,
        calibration_probe_target: str = "",
    ):
        runtime_options, observation_config, feature_flags = self._resolve_constructor_configs(
            runtime_options=runtime_options,
            observation_config=observation_config,
            feature_flags=feature_flags,
            action_fail_fast=action_fail_fast,
            auto_refresh_letterbox_crop=auto_refresh_letterbox_crop,
            letterbox_refresh_consecutive=letterbox_refresh_consecutive,
            default_observation_scope=default_observation_scope,
            app_viewport_mode=app_viewport_mode,
            max_ocr_elements=max_ocr_elements,
            max_ocr_text_chars=max_ocr_text_chars,
            ocr_timeout=ocr_timeout,
            perceive_cache_diff=perceive_cache_diff,
            detect_icons_in_perceive=detect_icons_in_perceive,
            strict_target_matching=strict_target_matching,
            require_home_icon_grid=require_home_icon_grid,
            reverify_fresh_frame=reverify_fresh_frame,
            coldstart_promote_controls=coldstart_promote_controls,
            vlm_set_of_mark=vlm_set_of_mark,
            memory_locate_priors=memory_locate_priors,
            strict_settings_detail=strict_settings_detail,
            ai_scroll_prefer_wheel=ai_scroll_prefer_wheel,
            vlm_reground_selection=vlm_reground_selection,
            whitebox_hint_selection=whitebox_hint_selection,
        )
        self.action_context = ActionContext()
        self._init_core_dependencies(
            source=source,
            ocr=ocr,
            effector=effector,
            profile=profile,
            typer=typer,
            kimi=kimi,
            recorder=recorder,
            memory=memory,
            coldstart=coldstart,
        )
        self._init_runtime_state(
            crop=crop,
            coordinate_space=coordinate_space,
            stability_policy=stability_policy,
            runtime_options=runtime_options,
            observation_config=observation_config,
            scene_classifiers=scene_classifiers,
            platform_scene_classifier=platform_scene_classifier,
            action_orchestrator=action_orchestrator,
            semantic_plan_ops=semantic_plan_ops,
        )
        self._init_collaborators()
        self._init_feature_state(feature_flags, observation_config, calibration_probe_target)
        self._init_platform_state(
            app_labels=app_labels,
            icon_map=icon_map,
            safe_area_provider=safe_area_provider,
            springboard_provider=springboard_provider,
            recovery_provider=recovery_provider,
            device_geometry=device_geometry,
            gesture_config=gesture_config,
            app_viewport=app_viewport,
            runtime_options=runtime_options,
        )
        self._init_action_context_compat_state()
        self.perceive_cache_stats = {"hits": 0, "misses": 0}

    @staticmethod
    def _resolve_constructor_configs(
        *,
        runtime_options: PhoneRuntimeOptions | None,
        observation_config: PhoneObservationConfig | None,
        feature_flags: PhoneFeatureFlags | None,
        action_fail_fast: bool,
        auto_refresh_letterbox_crop: bool,
        letterbox_refresh_consecutive: int,
        default_observation_scope: str,
        app_viewport_mode: str,
        max_ocr_elements: int,
        max_ocr_text_chars: int,
        ocr_timeout: float,
        perceive_cache_diff: float,
        detect_icons_in_perceive: bool,
        strict_target_matching: bool,
        require_home_icon_grid: bool,
        reverify_fresh_frame: bool,
        coldstart_promote_controls: bool,
        vlm_set_of_mark: bool,
        memory_locate_priors: bool,
        strict_settings_detail: bool,
        ai_scroll_prefer_wheel: bool,
        vlm_reground_selection: bool,
        whitebox_hint_selection: bool,
    ) -> tuple[PhoneRuntimeOptions, PhoneObservationConfig, PhoneFeatureFlags]:
        runtime_options = runtime_options or PhoneRuntimeOptions(
            action_fail_fast=action_fail_fast,
            auto_refresh_letterbox_crop=auto_refresh_letterbox_crop,
            letterbox_refresh_consecutive=letterbox_refresh_consecutive,
            default_observation_scope=default_observation_scope,
            app_viewport_mode=app_viewport_mode,
        )
        observation_config = observation_config or PhoneObservationConfig(
            max_ocr_elements=max_ocr_elements,
            max_ocr_text_chars=max_ocr_text_chars,
            ocr_timeout=ocr_timeout,
            perceive_cache_diff=perceive_cache_diff,
        )
        feature_flags = feature_flags or PhoneFeatureFlags(
            detect_icons_in_perceive=detect_icons_in_perceive,
            strict_target_matching=strict_target_matching,
            require_home_icon_grid=require_home_icon_grid,
            reverify_fresh_frame=reverify_fresh_frame,
            coldstart_promote_controls=coldstart_promote_controls,
            vlm_set_of_mark=vlm_set_of_mark,
            memory_locate_priors=memory_locate_priors,
            strict_settings_detail=strict_settings_detail,
            ai_scroll_prefer_wheel=ai_scroll_prefer_wheel,
            vlm_reground_selection=vlm_reground_selection,
            whitebox_hint_selection=whitebox_hint_selection,
        )
        return runtime_options, observation_config, feature_flags

    def _init_core_dependencies(
        self,
        *,
        source,
        ocr: AppleVisionOCR,
        effector,
        profile: Profile | None,
        typer: HeuristicTyper | None,
        kimi,
        recorder: Recorder | None,
        memory,
        coldstart,
    ) -> None:
        self.source = source
        self.ocr = ocr
        self.effector = effector
        self.profile = profile
        self.typer = typer
        self.kimi = kimi
        self.recorder = recorder
        self.memory = memory               # ScreenMemory | None — UTG screen memory
        self.coldstart = coldstart         # ColdStartAnnotator | None — cold-start VLM annotation

    def _init_runtime_state(
        self,
        *,
        crop: LetterboxCrop | None,
        coordinate_space: str | None,
        stability_policy: StabilityPolicy | None,
        runtime_options: PhoneRuntimeOptions,
        observation_config: PhoneObservationConfig,
        scene_classifiers: list[SceneClassifier] | None,
        platform_scene_classifier: PlatformSceneClassifier | None,
        action_orchestrator: ActionOrchestrator | None,
        semantic_plan_ops: frozenset[str] | None,
    ) -> None:
        self.crop = crop
        self.auto_refresh_letterbox_crop = bool(runtime_options.auto_refresh_letterbox_crop)
        # CUQ-3.14: hysteresis for auto-refresh — require this many consecutive
        # identical detections of a new bbox before committing it (so transient
        # content can't drift the crop). 1 = commit on first detection (legacy).
        self._letterbox_refresh_consecutive = max(1, int(runtime_options.letterbox_refresh_consecutive))
        self._pending_crop_bbox: tuple[int, int, int, int] | None = None
        self._pending_crop_count = 0
        self.coordinate_space = coordinate_space or "auto"
        self.stability_policy = stability_policy
        self.perceive_cache_diff = observation_config.perceive_cache_diff
        self.scene_classifiers = list(scene_classifiers or [])
        self._platform_scene_classifier = platform_scene_classifier
        self.action_fail_fast = runtime_options.action_fail_fast
        self.action_orchestrator = action_orchestrator
        # CUQ-0.1/0.8: ops routed through the first-class SemanticActionPlan
        # strategy ladder (verified-failure -> switch to next primitive) instead
        # of the legacy single-strategy path. Empty by default; flag-gated.
        self._semantic_plan_ops = frozenset(semantic_plan_ops or ())
        # CUQ-0.1: set while a strategy ladder runs, so an orchestrated actuation
        # invoked by a strategy callable (tap_text / swipe_up) does not re-route
        # into the plan (recursion) or fire its own mid-plan stuck recovery.
        self._in_semantic_plan = False

    def _init_collaborators(self) -> None:
        self.action_runner = ActionRunner(self)
        self.coordinate_mapper = CoordinateMapper(self)
        self.target_planner = TargetPlanner(self)
        self.assistive_touch_driver = AssistiveTouchDriver(self)
        self.gesture_executor = GestureExecutor(self)
        self.system_navigator = SystemNavigator(self)
        self.text_input = TextInput(self)
        self.element_selector = ElementSelector(self)
        self.perceptor = Perceptor(self)

    def _init_feature_state(
        self,
        feature_flags: PhoneFeatureFlags,
        observation_config: PhoneObservationConfig,
        calibration_probe_target: str,
    ) -> None:
        # CUQ-2.1: inject no-text icon regions into perceive() so icon-only
        # controls become tap candidates. Flag-gated (default off).
        self._detect_icons_in_perceive = bool(feature_flags.detect_icons_in_perceive)
        # Live-camera OCR hardening: cap OCR output volume (default-on, generous
        # — only a chaotic camera-preview frame ever exceeds it) and an opt-in
        # recognize() watchdog (default off; enable on the live rig).
        self._max_ocr_elements = max(0, int(observation_config.max_ocr_elements))
        self._max_ocr_text_chars = max(0, int(observation_config.max_ocr_text_chars))
        self._ocr_timeout = max(0.0, float(observation_config.ocr_timeout))
        self.settings_root_label_aliases = (
            dict(observation_config.settings_root_label_aliases)
            if observation_config.settings_root_label_aliases is not None
            else None
        )
        self.settings_root_fuzzy_aliases = bool(observation_config.settings_root_fuzzy_aliases)
        vote_cfg = observation_config.ocr_temporal_voting
        self._ocr_temporal_voting = OcrTemporalVotingConfig(
            enabled=bool(vote_cfg.enabled),
            frames=max(1, int(vote_cfg.frames)),
            min_presence=max(1, int(vote_cfg.min_presence)),
            pos_tol=max(1, int(vote_cfg.pos_tol)),
            sample_spacing_ms=max(0, int(vote_cfg.sample_spacing_ms)),
            outer_timeout=max(0.0, float(vote_cfg.outer_timeout)),
            keep_raw_samples=bool(vote_cfg.keep_raw_samples),
        )
        # CUQ-1.5: ambiguity-aware find_text (closest-length substring + fuzzy
        # margin). Flag-gated (default off) — changes which element a tap hits.
        self._strict_target_matching = bool(feature_flags.strict_target_matching)
        # CUQ-2.2: require icon-grid corroboration before trusting a bare
        # 'springboard' classification as Home. Flag-gated (default off).
        self._require_home_icon_grid = bool(feature_flags.require_home_icon_grid)
        # CUQ-1.3: re-perceive a fresh frame before a VLM verification escalation
        # so settled-late text is re-read cheaply (and can avoid the VLM call).
        # Flag-gated (default off) — read by the orchestrator via getattr.
        self._reverify_fresh_frame = bool(feature_flags.reverify_fresh_frame)
        # CUQ-2.3: promote VLM toggle/slider roles to switch/slider element types
        # and aim the tap at the row's right-margin control. Flag-gated (default
        # off); only reachable when cold-start annotation is enabled.
        self._coldstart_promote_controls = bool(feature_flags.coldstart_promote_controls)
        # CUQ-2.5: enable Set-of-Mark grounding on describe() escalations — the
        # VLM correlates elements to numbered marks it can see. Flag-gated
        # (default off); only matters when a VLM client is wired.
        self._vlm_set_of_mark = bool(feature_flags.vlm_set_of_mark)
        # CUQ-3.21: use the UTG position memory as a selection prior when OCR
        # misses (before the billed VLM reground). Flag-gated (default off);
        # only matters when memory is wired + populated.
        self._memory_locate_priors = bool(feature_flags.memory_locate_priors)
        # CUQ-2.6: require a Settings-distinguishing signal before the generic
        # body-marker heuristic classifies a screen as settings_detail (closes a
        # third-party-app false-positive). Flag-gated (default off).
        self._strict_settings_detail = bool(feature_flags.strict_settings_detail)
        # CUQ-3.15: route generic AI scroll to the precise wheel when the backend
        # supports it (the iPad rig, where the wheel is validated). Flag-gated
        # (default off → swipe-fling), read by AIPhone via getattr.
        self._ai_scroll_prefer_wheel = bool(feature_flags.ai_scroll_prefer_wheel)
        # CUQ-0.4: selection-time VLM reground on an OCR miss. Flag-gated (default
        # off) so the default expect_text path is byte-identical — no billed
        # describe() on a miss — even when a VLM client is wired.
        self._vlm_reground_selection_enabled = bool(feature_flags.vlm_reground_selection)
        # CUQ-2.10: let an element's whitebox identity (accessibility_id /
        # asset_match / deep_link) resolve a target when OCR misses. Flag-gated
        # (default off); only matters with a Tier-1+ app profile populating hints.
        self._whitebox_hint_selection = bool(feature_flags.whitebox_hint_selection)
        # CUQ-3.7: known-safe anchor for the session-start calibration probe.
        # Empty (default) disables it (byte-identical).
        self._calibration_probe_target = str(calibration_probe_target or "")
        # CUQ-2.9: how the most recent target was resolved (ocr vs vlm), stamped
        # into the next tap's metadata so selection_source is recorded at
        # selection time rather than inferred post-hoc.
        self._last_selection_source: str = "ocr"

    def _init_platform_state(
        self,
        *,
        app_labels: tuple[str, ...] | None,
        icon_map,
        safe_area_provider,
        springboard_provider,
        recovery_provider,
        device_geometry,
        gesture_config: PhoneGestureConfig | None,
        app_viewport: ViewportCrop | None,
        runtime_options: PhoneRuntimeOptions,
    ) -> None:
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
        self.app_viewport_mode = str(runtime_options.app_viewport_mode or "auto").strip().lower()
        self.default_observation_scope = self._normalize_observation_scope(
            runtime_options.default_observation_scope
        )
        self._cjk_foreground_settle_s = 2.0

    def _init_action_context_compat_state(self) -> None:
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

    @property
    def _pending_actions_for_memory(self):
        return self.action_context.pending_actions_for_memory

    @_pending_actions_for_memory.setter
    def _pending_actions_for_memory(self, value) -> None:
        self.action_context.pending_actions_for_memory = value

    @property
    def _last_frame(self):
        return self.action_context.last_frame

    @_last_frame.setter
    def _last_frame(self, value) -> None:
        self.action_context.last_frame = value

    @property
    def _last_scene(self):
        return self.action_context.last_scene

    @_last_scene.setter
    def _last_scene(self, value) -> None:
        self.action_context.last_scene = value

    @property
    def _last_scene_coordinate_space(self):
        return self.action_context.last_scene_coordinate_space

    @_last_scene_coordinate_space.setter
    def _last_scene_coordinate_space(self, value) -> None:
        self.action_context.last_scene_coordinate_space = value

    @property
    def _implicit_coordinate_space_error(self):
        return self.action_context.implicit_coordinate_space_error

    @_implicit_coordinate_space_error.setter
    def _implicit_coordinate_space_error(self, value) -> None:
        self.action_context.implicit_coordinate_space_error = value

    @property
    def _cache_frame(self):
        return self.action_context.cache_frame

    @_cache_frame.setter
    def _cache_frame(self, value) -> None:
        self.action_context.cache_frame = value

    @property
    def _cache_scene(self):
        return self.action_context.cache_scene

    @_cache_scene.setter
    def _cache_scene(self, value) -> None:
        self.action_context.cache_scene = value

    @property
    def _cache_scope(self) -> str:
        return self.action_context.cache_scope

    @_cache_scope.setter
    def _cache_scope(self, value: str) -> None:
        self.action_context.cache_scope = value

    @property
    def _needs_stable_frame(self) -> bool:
        return self.action_context.needs_stable_frame

    @_needs_stable_frame.setter
    def _needs_stable_frame(self, value: bool) -> None:
        self.action_context.needs_stable_frame = bool(value)

    @property
    def _fresh_source_reopened_after_action(self) -> bool:
        return self.action_context.fresh_source_reopened_after_action

    @_fresh_source_reopened_after_action.setter
    def _fresh_source_reopened_after_action(self, value: bool) -> None:
        self.action_context.fresh_source_reopened_after_action = bool(value)

    @property
    def _last_stable_frame(self):
        return self.action_context.last_stable_frame

    @_last_stable_frame.setter
    def _last_stable_frame(self, value) -> None:
        self.action_context.last_stable_frame = value

    @property
    def _last_stability_score(self):
        return self.action_context.last_stability_score

    @_last_stability_score.setter
    def _last_stability_score(self, value) -> None:
        self.action_context.last_stability_score = value

    @property
    def _last_stability_policy(self):
        return self.action_context.last_stability_policy

    @_last_stability_policy.setter
    def _last_stability_policy(self, value) -> None:
        self.action_context.last_stability_policy = value

    @property
    def _last_observation_mode(self) -> str:
        return self.action_context.last_observation_mode

    @_last_observation_mode.setter
    def _last_observation_mode(self, value: str) -> None:
        self.action_context.last_observation_mode = str(value)

    @property
    def _pending_crop_bbox(self) -> tuple[int, int, int, int] | None:
        return self.action_context.pending_crop_bbox

    @_pending_crop_bbox.setter
    def _pending_crop_bbox(self, value: tuple[int, int, int, int] | None) -> None:
        self.action_context.pending_crop_bbox = value

    @property
    def _pending_crop_count(self) -> int:
        return self.action_context.pending_crop_count

    @_pending_crop_count.setter
    def _pending_crop_count(self, value: int) -> None:
        self.action_context.pending_crop_count = int(value)

    # —— Coordinate transform ——
    def _to_phone(self, x: float, y: float, *, coordinate_space: str | None = None) -> tuple[int, int]:
        """Observation coords -> coords the effector should see."""
        return self.coordinate_mapper.to_phone(x, y, coordinate_space=coordinate_space)

    def to_phone_coordinates(
        self,
        x: float,
        y: float,
        *,
        coordinate_space: str | None = None,
    ) -> tuple[int, int]:
        """Public observation-to-effector coordinate transform."""
        return self._to_phone(x, y, coordinate_space=coordinate_space)

    def _normalize_input_coordinate_space(self, coordinate_space: str | None) -> str:
        return self.coordinate_mapper.normalize_input_coordinate_space(coordinate_space)

    def normalize_input_coordinate_space(self, coordinate_space: str | None) -> str:
        """Public coordinate-space normalizer for gesture collaborators."""
        return self._normalize_input_coordinate_space(coordinate_space)

    def _infer_input_coordinate_space(self) -> str:
        return self.coordinate_mapper.infer_input_coordinate_space()

    def infer_input_coordinate_space(self) -> str:
        """Public input coordinate-space inference for planning collaborators."""
        return self._infer_input_coordinate_space()

    def _cropped_to_effector(self, x: float, y: float) -> tuple[int, int]:
        return self.coordinate_mapper.cropped_to_effector(x, y)

    def _frame_to_effector(self, x: float, y: float) -> tuple[int, int]:
        return self.coordinate_mapper.frame_to_effector(x, y)

    @staticmethod
    def _normalize_observation_scope(scope: str | None) -> str:
        normalized = str(scope or "device").strip().lower().replace("-", "_")
        if normalized in {"app", "foreground", "foreground_app"}:
            return "app"
        return "device"

    def normalize_observation_scope(self, scope: str | None) -> str:
        """Public observation-scope normalizer for perception collaborators."""
        return self._normalize_observation_scope(scope)

    def _coordinate_space(self) -> str:
        return self.coordinate_mapper.effector_coordinate_space()

    def effector_coordinate_space(self) -> str:
        """Public coordinate-space accessor for collaborators outside Phone."""
        return self._coordinate_space()

    # —— Action recording / screen memory ——
    def _record_action(self, op: str, *, result=None, **kwargs) -> None:
        """Log an effector action to the recorder (if any) and stash it so the
        screen-memory layer can label the next transition edge.

        Any effector action may change the visible screen. Clear cached Scene
        state so the next semantic operation cannot accidentally reuse the
        pre-action screen while the HDMI feed is still catching up. Keep the
        last frame around as a viewport-size hint for chained gesture helpers.
        """
        _action_runner_for(self).record_action(op, result=result, **kwargs)

    def supports(self, action: str) -> bool:
        capabilities = self._backend_capabilities()
        if capabilities is not None:
            return capabilities.supports_semantic(action)
        supports = getattr(self.effector, "supports", None)
        if callable(supports):
            return bool(supports(action))
        return hasattr(self.effector, action)

    @property
    def require_home_icon_grid_enabled(self) -> bool:
        return self._require_home_icon_grid

    @property
    def reverify_fresh_frame_enabled(self) -> bool:
        return self._reverify_fresh_frame

    @property
    def ai_scroll_prefer_wheel_enabled(self) -> bool:
        return self._ai_scroll_prefer_wheel

    @property
    def cjk_foreground_settle_s(self) -> float:
        return self._cjk_foreground_settle_s

    @property
    def strict_target_matching_enabled(self) -> bool:
        return self._strict_target_matching

    @property
    def vlm_set_of_mark_enabled(self) -> bool:
        return self._vlm_set_of_mark

    @property
    def vlm_reground_selection_enabled(self) -> bool:
        return self._vlm_reground_selection_enabled

    @property
    def memory_locate_priors_enabled(self) -> bool:
        return self._memory_locate_priors

    @property
    def whitebox_hint_selection_enabled(self) -> bool:
        return self._whitebox_hint_selection

    @property
    def coldstart_promote_controls_enabled(self) -> bool:
        return self._coldstart_promote_controls

    @property
    def strict_settings_detail_enabled(self) -> bool:
        return self._strict_settings_detail

    @property
    def detect_icons_in_perceive_enabled(self) -> bool:
        return self._detect_icons_in_perceive

    @property
    def max_ocr_elements(self) -> int:
        return self._max_ocr_elements

    @property
    def max_ocr_text_chars(self) -> int:
        return self._max_ocr_text_chars

    @property
    def ocr_timeout(self) -> float:
        return self._ocr_timeout

    @property
    def ocr_temporal_voting_config(self) -> OcrTemporalVotingConfig:
        return self._ocr_temporal_voting

    @property
    def ocr_temporal_voting_enabled(self) -> bool:
        return self._ocr_temporal_voting.enabled

    @property
    def letterbox_refresh_consecutive(self) -> int:
        return self._letterbox_refresh_consecutive

    @property
    def platform_scene_classifier(self) -> PlatformSceneClassifier | None:
        return self._platform_scene_classifier

    def set_last_selection_source(self, source: str) -> None:
        self._last_selection_source = str(source)

    def _backend_capabilities(self) -> BackendCapabilities | None:
        capabilities = getattr(self.effector, "capabilities", None)
        if callable(capabilities):
            try:
                return capabilities()
            except Exception as exc:
                logger.warning(f"effector capabilities() failed: {exc}")
                return NOOP_CAPABILITIES
        return None

    def backend_capabilities(self) -> BackendCapabilities | None:
        """Public backend-capability accessor for collaborators outside Phone."""
        return self._backend_capabilities()

    def _system_action_strategy(self, action: str) -> str:
        capabilities = self._backend_capabilities()
        if capabilities is None:
            return "direct" if self.supports(action) else "unsupported"
        return str(getattr(capabilities, f"{action}_strategy", "unsupported"))

    def system_action_strategy(self, action: str) -> str:
        """Public system-action strategy accessor for navigation collaborators."""
        return self._system_action_strategy(action)

    def _effector_backend(self) -> str:
        name = self.effector.__class__.__name__
        return name[:-8].lower() if name.endswith("Effector") else name.lower()

    def effector_backend(self) -> str:
        """Public effector-backend name accessor for collaborators outside Phone."""
        return self._effector_backend()

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
        return _action_runner_for(self).failed_action_result(error=error, unsupported=unsupported)

    def failed_action_result(
        self,
        *,
        error: str,
        unsupported: bool = False,
    ) -> ActionResult:
        """Public failed action-result factory for action collaborators."""
        return self._failed_action_result(error=error, unsupported=unsupported)

    def record_action(self, op: str, *, result=None, **kwargs) -> None:
        """Public action-record hook for action collaborators."""
        self._record_action(op, result=result, **kwargs)

    @property
    def in_semantic_plan(self) -> bool:
        return self._in_semantic_plan

    def set_semantic_plan_active(self, active: bool) -> None:
        self._in_semantic_plan = bool(active)

    def mark_action_observation_dirty(self) -> None:
        """Mark that an effector command may have changed the visible screen."""
        self._needs_stable_frame = True
        self._fresh_source_reopened_after_action = False
        self.invalidate_perceive_cache()

    def mark_fresh_source_reopened_after_action(self) -> None:
        self._fresh_source_reopened_after_action = True

    @property
    def last_stability_policy(self) -> dict | None:
        return self._last_stability_policy

    @property
    def last_stability_score(self) -> float | None:
        return self._last_stability_score

    def _execute_action(self, op: str, call, **kwargs) -> ActionResult:
        """Run one effector action and record a typed result even on failure."""
        return _action_runner_for(self).execute_action(op, call, **kwargs)

    def execute_action(self, op: str, call, **kwargs) -> ActionResult:
        """Public action execution hook for owned Phone collaborators."""
        return self._execute_action(op, call, **kwargs)

    def run_calibration_probe(self) -> bool:
        """CUQ-3.7: eagerly tap the configured anchor at session start to seed the
        actuation offset before the first task tap. No-op (returns False) when no
        target is configured or calibration already exists."""
        from glassbox.action.calibration import run_session_calibration_probe

        return run_session_calibration_probe(self, self._calibration_probe_target)

    def _uses_semantic_plan(self, op: str) -> bool:
        """CUQ-0.1/0.8: is this op routed through the first-class strategy ladder?"""
        return op in self._semantic_plan_ops and self.action_orchestrator is not None

    def uses_semantic_plan(self, op: str) -> bool:
        """Public semantic-plan routing predicate for collaborators."""
        return self._uses_semantic_plan(op)

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
        return _action_runner_for(self).run_semantic_plan(
            op,
            expected_state=expected_state,
            actor=actor,
            params=params,
            **exec_kwargs,
        )

    def run_semantic_plan(self, op: str, **kwargs: Any) -> ActionResult:
        """Public semantic-plan executor for collaborators."""
        return self._run_semantic_plan(op, **kwargs)

    def _set_last_scene(self, scene: Scene, frame: Frame | None) -> None:
        _perceptor_for(self).set_last_scene(scene, frame)

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
        return _action_runner_for(self).verify_fresh_action_result(
            action,
            result,
            metadata=metadata,
            before_frame=before_frame,
            before_scene=before_scene,
            delay_ms=delay_ms,
            reopen_source=reopen_source,
        )

    def _fresh_scene_for_verification(self, *, stable: bool | None):
        return _action_runner_for(self).fresh_scene_for_verification(stable=stable)

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

    def reopen_source_for_fresh_capture(self) -> bool:
        """Public fresh-capture reopen hook for perception collaborators."""
        return self._reopen_source_for_fresh_capture()

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

    def picokvm_fresh_verify_kwargs(self, action: str) -> dict:
        """Public PicoKVM fresh-frame verification metadata accessor."""
        return self._picokvm_fresh_verify_kwargs(action)

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

    def picokvm_back_context(self) -> tuple[bool, str, tuple[int, int] | None]:
        """Public PicoKVM back-navigation guard context."""
        return self._picokvm_back_context()

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

    def verify_fresh_action_result(
        self,
        action: str,
        result: ActionResult,
        *,
        metadata: dict,
        before_frame,
        before_scene,
        delay_ms: int,
        reopen_source: bool,
    ) -> ActionResult:
        """Public fresh-frame verification hook for owned Phone collaborators."""
        return self._verify_fresh_action_result(
            action,
            result,
            metadata=metadata,
            before_frame=before_frame,
            before_scene=before_scene,
            delay_ms=delay_ms,
            reopen_source=reopen_source,
        )

    def unsupported_action(self, op: str, **kwargs) -> ActionResult:
        """Public unsupported-action result helper for collaborators."""
        return self._unsupported_action(op, **kwargs)

    @staticmethod
    def _action_result_fields(result) -> dict:
        return ActionRunner.action_result_fields(result)

    def _viewport_size(self) -> tuple[int, int]:
        """Return the currently perceived viewport size in cropped-frame coords."""
        if self._last_frame is None:
            self.snapshot()
        assert self._last_frame is not None
        return self._last_frame.shape

    def viewport_size(self) -> tuple[int, int]:
        """Public viewport-size accessor for collaborators outside Phone."""
        return self._viewport_size()

    @property
    def last_frame(self) -> Frame | None:
        """Most recent perceived/snapshotted frame, exposed read-only."""
        return self._last_frame

    @property
    def last_stable_frame(self) -> bool:
        """Whether the latest frame came from the stable-frame path."""
        return self._last_stable_frame

    @property
    def last_scene(self) -> Scene | None:
        """Most recent perceived scene, exposed read-only."""
        return self._last_scene

    @property
    def last_scene_coordinate_space(self) -> str | None:
        """Coordinate space attached to the latest perceived scene."""
        return self._last_scene_coordinate_space

    def _observe_memory(self, scene: Scene, frame_img) -> None:
        """Fold the scene into the UTG and cold-start annotator."""
        _perceptor_for(self).observe_memory(scene, frame_img)

    @staticmethod
    def _memory_action_candidate(action: ActionRecord) -> bool:
        return Perceptor.memory_action_candidate(action)

    def _apply_scene_classifiers(self, scene: Scene, frame_img: np.ndarray | None) -> None:
        """Run optional platform/app classifier hooks before recording/memory."""
        _perceptor_for(self).apply_scene_classifiers(scene, frame_img)

    def apply_scene_classifiers(self, scene: Scene, frame_img: np.ndarray | None) -> None:
        """Public scene-classifier hook for owned Phone collaborators."""
        self._apply_scene_classifiers(scene, frame_img)

    def _classify_platform_scene_now(
        self,
        scene: Scene,
        viewport_size: tuple[int, int] | None,
    ) -> SceneClassification | None:
        return _perceptor_for(self).classify_platform_scene_now(scene, viewport_size)

    def classify_platform_scene_now(
        self,
        scene: Scene,
        *,
        viewport_size: tuple[int, int] | None,
    ) -> SceneClassification | None:
        """Public platform scene classifier hook for planning collaborators."""
        return self._classify_platform_scene_now(scene, viewport_size=viewport_size)

    # —— Profile (Tier 1+ white-box) ——
    def _apply_profile(self, scene: Scene, frame_img=None) -> None:
        """Tag the scene with the KnownVC it is showing and, when that VC has
        known_elements + an asset workspace, icon-match whitebox_hint onto its
        elements. Re-run after Layer 3 so the Kimi scene_type can sharpen the
        VC match. No-op at Tier 0 (no profile)."""
        _perceptor_for(self).apply_profile(scene, frame_img)

    def apply_profile(self, scene: Scene, frame_img=None) -> None:
        """Public profile hook for owned Phone collaborators."""
        self._apply_profile(scene, frame_img)

    def cache_scene(self, scene: Scene) -> None:
        self._cache_scene = scene.model_copy(deep=True)

    # —— Perception ——
    def _should_wait_stable(self, stable: bool | None) -> bool:
        return _perceptor_for(self).should_wait_stable(stable)

    def _should_fresh_snapshot(self, fresh: bool | None) -> bool:
        return _perceptor_for(self).should_fresh_snapshot(fresh)

    def _source_supports_fresh_snapshot(self) -> bool:
        return _perceptor_for(self).source_supports_fresh_snapshot()

    def _source_snapshot(self, *, fresh: bool) -> Frame | None:
        return _perceptor_for(self).source_snapshot(fresh=fresh)

    def snapshot(
        self,
        *,
        stable: bool | None = None,
        scope: str | None = None,
        fresh: bool | None = None,
    ) -> Frame | None:
        return _perceptor_for(self).snapshot(stable=stable, scope=scope, fresh=fresh)

    def _refresh_letterbox_crop_bbox(self, raw: Frame) -> None:
        _perceptor_for(self).refresh_letterbox_crop_bbox(raw)

    def _apply_app_viewport(self, frame: Frame) -> Frame:
        return _perceptor_for(self).apply_app_viewport(frame)

    def _should_detect_app_viewport(self, frame: Frame) -> bool:
        return _perceptor_for(self).should_detect_app_viewport(frame)

    def invalidate_app_viewport(self) -> None:
        """Drop an auto-detected app viewport so the next app-scope snapshot re-detects it."""
        _perceptor_for(self).invalidate_app_viewport()

    def invalidate_perceive_cache(self) -> None:
        """Explicitly clear the Scene cache. After tap_*/swipe, Phone cannot
        tell whether the screen changed; a high-level walkthrough script can
        manually invalidate after an operation that disrupts the screen."""
        _perceptor_for(self).invalidate_perceive_cache()

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
        return _perceptor_for(self).perceive(stable=stable, scope=scope, fresh=fresh)

    def _recognize_elements(self, frame: Frame) -> list[UIElement]:
        return _perceptor_for(self).recognize_elements(frame)

    def _run_ocr(self, frame: Frame) -> list[UIElement]:
        """OCR the frame, optionally under a wall-clock watchdog.

        The watchdog (``ocr_timeout`` > 0) runs recognize() in a daemon thread
        and, if it overruns, returns an empty element set so perceive yields an
        `unknown` scene (recovery backs out) instead of hanging. It works only
        because Apple Vision releases the GIL during recognition; a pure-Python
        regex stall downstream cannot be interrupted this way — the element/char
        caps in `_bound_ocr_elements` are the defense for that. Default off, so
        the bare path below is byte-identical to before."""
        return _perceptor_for(self).run_ocr(frame)

    def _bound_ocr_elements(self, elements: list[UIElement]) -> list[UIElement]:
        """Clip pathological OCR output (a live-camera preview emits chaotic,
        high-volume text) so downstream scene/text regexes never see it. No real
        iOS screen approaches these limits, so this is a no-op on normal frames;
        on a chaotic frame the clipped set classifies `unknown` (recovery backs
        out) anyway. Both caps default-on (generous); 0 disables either."""
        return _perceptor_for(self).bound_ocr_elements(elements)

    def _maybe_detect_icons(self, scene: Scene, frame_img) -> None:
        """CUQ-2.1 (flag-gated): inject no-text icon regions as tappable image
        elements so icon-only controls (+, share, gear, back-chevron, trash)
        become tap candidates instead of being invisible to the OCR-text-only
        set. Runs after the scene classifiers so classification is unaffected;
        best-effort (never breaks perceive)."""
        _perceptor_for(self).maybe_detect_icons(scene, frame_img)

    def perceive_voted(
        self,
        n: int = 3,
        *,
        text_normalizer=None,
        scope: str | None = None,
        pos_tol: int | None = None,
        min_presence: int | None = None,
        sample_spacing_ms: int | None = None,
    ) -> Scene:
        """Perceive a STABLE screen `n` times and vote per-row text (D).

        For accuracy-critical reads where the screen is not moving — OCR
        jitter on a row is decided by majority instead of one sampled frame.
        Costs ~n× OCR; bypasses the frame-diff cache by design. n<=1 falls
        back to a single perceive().
        """
        return _perceptor_for(self).perceive_voted(
            n=n,
            text_normalizer=text_normalizer,
            scope=scope,
            pos_tol=pos_tol,
            min_presence=min_presence,
            sample_spacing_ms=sample_spacing_ms,
        )

    def describe(self, *, scene_hint: str | None = None, set_of_mark: bool | None = None) -> Scene:
        return _element_selector_for(self).describe(scene_hint=scene_hint, set_of_mark=set_of_mark)

    # —— Verdict ——
    def find_text(self, target: str, *, fuzzy_ratio: float = 0.8) -> UIElement | None:
        return _element_selector_for(self).find_text(target, fuzzy_ratio=fuzzy_ratio)

    def _vlm_reground_selection(self, target: str, *, fuzzy_ratio: float) -> UIElement | None:
        return _element_selector_for(self).vlm_reground_selection(target, fuzzy_ratio=fuzzy_ratio)

    def _memory_locate_selection(self, target: str, *, fuzzy_ratio: float) -> UIElement | None:
        return _element_selector_for(self).memory_locate_selection(target, fuzzy_ratio=fuzzy_ratio)

    def _rows_before_nav_title(self, elements: list[UIElement]) -> list[UIElement]:
        return _element_selector_for(self).rows_before_nav_title(elements)

    def expect_text(
        self,
        target: str,
        *,
        timeout: float = 5.0,
        fuzzy_ratio: float = 0.8,
        poll_interval: float = 0.5,
    ) -> UIElement:
        return _element_selector_for(self).expect_text(
            target,
            timeout=timeout,
            fuzzy_ratio=fuzzy_ratio,
            poll_interval=poll_interval,
        )

    def expect_no_text(self, target: str, *, fuzzy_ratio: float = 0.9) -> None:
        _element_selector_for(self).expect_no_text(target, fuzzy_ratio=fuzzy_ratio)

    # —— Action ——
    def _target_planner(self) -> TargetPlanner:
        return _target_planner_for(self)

    def _tap_point_for_element(self, el: UIElement) -> tuple[int, int]:
        return _target_planner_for(self).tap_point_for_element(el)

    def _springboard_icon_tap_point_for_element(self, el: UIElement) -> tuple[int, int] | None:
        return _target_planner_for(self).springboard_icon_tap_point_for_element(el)

    def _picokvm_settings_row_tap_point_for_element(self, el: UIElement) -> tuple[int, int] | None:
        return _target_planner_for(self).picokvm_settings_row_tap_point_for_element(el)

    @staticmethod
    def _pop_actuation_options(kwargs: dict) -> dict:
        return TargetPlanner.pop_actuation_options(kwargs)

    def _scene_ref_for_target(self) -> dict | None:
        return _target_planner_for(self).scene_ref_for_target()

    def _reground_tap_point(self, *, target: str):
        return _target_planner_for(self).reground_tap_point(target=target)

    def _locate_in_last_scene(self, target: str) -> UIElement | None:
        scene = self._last_scene
        if scene is None:
            return None
        return find_text(self._rows_before_nav_title(scene.elements), target, fuzzy_ratio=0.8)

    def locate_in_last_scene(self, target: str) -> UIElement | None:
        """Public lookup in the current scene, used for retry re-grounding."""
        return self._locate_in_last_scene(target)

    def _target_tap_plan(
        self,
        *,
        element: UIElement,
        intent: str,
        via: str,
        target: str,
        actuation_options: dict | None = None,
    ) -> tuple[ActuationPlan, dict]:
        return _target_planner_for(self).target_tap_plan(
            element=element,
            intent=intent,
            via=via,
            target=target,
            actuation_options=actuation_options,
        )

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
        return _target_planner_for(self).target_actuation_plan(
            element=element,
            intent=intent,
            via=via,
            target=target,
            actuation_options=actuation_options,
            selection_source=selection_source,
        )

    def _actuation_offset(self, control_bucket: dict[str, str]):
        return _target_planner_for(self).actuation_offset(control_bucket)

    def _preferred_actuation_method(self, control_bucket: dict[str, str]) -> str:
        return _target_planner_for(self).preferred_actuation_method(control_bucket)

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
        return _target_planner_for(self).target_keyboard_focus_plan(
            element=element,
            intent=intent,
            via=via,
            target=target,
            modifier=modifier,
            keycode=keycode,
            actuation_options=actuation_options,
        )

    def tap_text(
        self, target: str, *, expected_state: dict[str, Any] | None = None, **kw
    ) -> ActionResult:
        # CUQ-0.1: when `tap` is flagged, route the top-level tap through the
        # strategy ladder (target_tap -> keyboard_focus_activate, verified-failure
        # switching). The `_in_semantic_plan` guard ensures the ladder's own
        # target_tap strategy (which calls back here) actuates in place rather
        # than recursing into the plan. Default (tap not flagged) is unchanged.
        if self._uses_semantic_plan("tap") and not self._in_semantic_plan:
            params: dict[str, Any] = {"target": target}
            x = kw.get("x")
            y = kw.get("y")
            if x is not None and y is not None:
                params["x"], params["y"] = x, y
            return self._run_semantic_plan(
                "tap",
                expected_state=expected_state,
                params=params,
                via="tap_text",
                policy_action="tap",
                **self._picokvm_fresh_verify_kwargs("tap"),
            )
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
        # CUQ-0.3: when the caller declares what the tap should achieve, thread it
        # into the orchestrator metadata so the expected-state verification (P2)
        # and VLM-gated escalation (P1) engage on the default agent tap path —
        # not just on the Settings walkthrough. None preserves today's generic
        # scene-progressed verification (byte-identical).
        if expected_state is not None:
            metadata = {**metadata, "expected_state": expected_state}
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
        btn = find_button(scene.elements, label, fuzzy_ratio=fuzzy_ratio,
                          ambiguity_guard=self._strict_target_matching)
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
        el = find_by_intent(
            scene.elements, intent, fuzzy_ratio=fuzzy_ratio,
            ambiguity_guard=self._strict_target_matching,
        ) if scene else None
        if el is None:
            if self.kimi is None:
                if all(e.intent_label is None for e in scene.elements):
                    return self.tap_button(intent, fuzzy_ratio=fuzzy_ratio)
            else:
                self.describe(scene_hint=scene_hint or intent)
                scene = self._last_scene   # type: ignore[assignment]
                el = find_by_intent(
            scene.elements, intent, fuzzy_ratio=fuzzy_ratio,
            ambiguity_guard=self._strict_target_matching,
        ) if scene else None
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
        return _gesture_executor_for(self).tap_xy(x, y, coordinate_space=coordinate_space)

    def assistive_touch_open_menu(self, *, settle_s: float = 0.9) -> ActionResult:
        return _assistive_touch_driver_for(self).open_menu(settle_s=settle_s)

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
        return _assistive_touch_driver_for(self).tap_menu_item(
            label,
            path=path,
            open_menu=open_menu,
            allow_unsafe=allow_unsafe,
            settle_s=settle_s,
            primitive_name=primitive_name,
        )

    def assistive_touch_run_primitive(
        self,
        name: str,
        *,
        open_menu: bool = True,
        settle_s: float = 0.9,
    ) -> ActionResult:
        return _assistive_touch_driver_for(self).run_primitive(
            name,
            open_menu=open_menu,
            settle_s=settle_s,
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
        return _assistive_touch_driver_for(self).tap_visible_item(
            label,
            via=via,
            path=path,
            settle_s=settle_s,
            allow_unsafe=allow_unsafe,
            primitive_name=primitive_name,
        )

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
        return _assistive_touch_driver_for(self).record_failure(
            error=error,
            via=via,
            target=target,
            path=path,
            safety_blocked=safety_blocked,
            unsupported=unsupported,
            primitive_name=primitive_name,
        )

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
        return _gesture_executor_for(self).double_tap_xy(
            x,
            y,
            coordinate_space=coordinate_space,
            target=target,
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
        return _gesture_executor_for(self).long_press_xy(
            x,
            y,
            coordinate_space=coordinate_space,
            hold_ms=hold_ms,
            target=target,
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
        return _gesture_executor_for(self).swipe_xy(
            x1,
            y1,
            x2,
            y2,
            coordinate_space=coordinate_space,
            steps=steps,
            end_hold_ms=end_hold_ms,
            via=via,
            policy_action=policy_action,
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
        return _gesture_executor_for(self).drag_xy(
            x1,
            y1,
            x2,
            y2,
            coordinate_space=coordinate_space,
            down_hold_ms=down_hold_ms,
            up_hold_ms=up_hold_ms,
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
        return _gesture_executor_for(self).scroll_wheel(
            ticks,
            horizontal=horizontal,
            focus_x=focus_x,
            focus_y=focus_y,
            focus_click=focus_click,
            interval_ms=interval_ms,
        )

    def _default_wheel_ticks(self) -> int:
        return _gesture_executor_for(self).default_wheel_ticks()

    def wheel_scroll_down(self, *, ticks: int | None = None) -> ActionResult:
        return _gesture_executor_for(self).wheel_scroll_down(ticks=ticks)

    def wheel_scroll_up(self, *, ticks: int | None = None) -> ActionResult:
        return _gesture_executor_for(self).wheel_scroll_up(ticks=ticks)

    def _picokvm_drag_preset(
        self,
        method_name: str,
        *,
        via: str,
        policy_action: str,
        **metadata: Any,
    ) -> ActionResult | None:
        return _gesture_executor_for(self).picokvm_drag_preset(
            method_name,
            via=via,
            policy_action=policy_action,
            **metadata,
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
        return _gesture_executor_for(self).swipe_up(
            fraction=fraction,
            settle_strategy=settle_strategy,
            window_duration_ms=window_duration_ms,
            stream_timeout_ms=stream_timeout_ms,
            sample_interval_ms=sample_interval_ms,
            max_stream_frames=max_stream_frames,
            expected_state=expected_state,
            expect_visible=expect_visible,
            expect_page=expect_page,
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
        return _gesture_executor_for(self).swipe_down(
            fraction=fraction,
            settle_strategy=settle_strategy,
            window_duration_ms=window_duration_ms,
            stream_timeout_ms=stream_timeout_ms,
            sample_interval_ms=sample_interval_ms,
            max_stream_frames=max_stream_frames,
            expected_state=expected_state,
            expect_visible=expect_visible,
            expect_page=expect_page,
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
        return _gesture_executor_for(self).page_drag_xy(
            x1,
            y1,
            x2,
            y2,
            via=via,
            down_hold_ms=down_hold_ms,
            up_hold_ms=up_hold_ms,
        )

    def swipe_left(self, *, fraction: float = 0.84, y_fraction: float = 0.45) -> ActionResult:
        return _gesture_executor_for(self).swipe_left(fraction=fraction, y_fraction=y_fraction)

    def swipe_right(self, *, fraction: float = 0.84, y_fraction: float = 0.45) -> ActionResult:
        return _gesture_executor_for(self).swipe_right(fraction=fraction, y_fraction=y_fraction)

    def close_foreground_app(self) -> ActionResult:
        return _system_navigator_for(self).close_foreground_app()

    def back_gesture(self) -> ActionResult:
        return _system_navigator_for(self).back_gesture()

    def home(self) -> ActionResult:
        return _system_navigator_for(self).home()

    def _picokvm_home_needs_fallback(self, result: ActionResult) -> bool:
        return _system_navigator_for(self).picokvm_home_needs_fallback(result)

    def _home_via_assistive_touch_menu(self) -> ActionResult:
        return _system_navigator_for(self).home_via_assistive_touch_menu()

    def home_via_assistive_touch_menu(self) -> ActionResult:
        """Public AssistiveTouch Home fallback for semantic action plans."""
        return self._home_via_assistive_touch_menu()

    def _expects_assistive_touch(self) -> bool:
        return _system_navigator_for(self).expects_assistive_touch()

    def _picokvm_home_pointer_fallback(
        self, *, fallback_from: str, last_result: ActionResult
    ) -> ActionResult:
        return _system_navigator_for(self).picokvm_home_pointer_fallback(
            fallback_from=fallback_from,
            last_result=last_result,
        )

    @staticmethod
    def _home_reached(result: ActionResult) -> bool:
        return SystemNavigator.home_reached(result)

    def _verified_pointer_home(self, call, **metadata) -> ActionResult:
        return _system_navigator_for(self).verified_pointer_home(call, **metadata)

    def recents(self) -> ActionResult:
        return _system_navigator_for(self).recents()

    def control_center(self) -> ActionResult:
        return _system_navigator_for(self).control_center()

    def notification_center(self) -> ActionResult:
        return _system_navigator_for(self).notification_center()

    def open_app(
        self,
        label: str,
        *,
        aliases: tuple[str, ...] = (),
        max_pages: int = 8,
        settle_s: float = 0.8,
    ) -> ActionResult:
        return _system_navigator_for(self).open_app(
            label,
            aliases=aliases,
            max_pages=max_pages,
            settle_s=settle_s,
        )

    def type(self, text: str, *, verify: bool | None = None,
             max_switches: int = 2) -> ActionResult:
        return _text_input_for(self).type(text, verify=verify, max_switches=max_switches)

    def _type_via_clipboard(self, text: str) -> ActionResult:
        return _text_input_for(self).type_via_clipboard(text)

    def _foreground_app(self, labels: tuple[str, ...]) -> None:
        _text_input_for(self).foreground_app(labels)

    def foreground_app(self, labels: tuple[str, ...]) -> None:
        _text_input_for(self).foreground_app(labels)

    def _ime_composing(self) -> bool:
        return _text_input_for(self).ime_composing()

    def ime_composing(self) -> bool:
        return self._ime_composing()

    def _clear_focused_field(self) -> None:
        _text_input_for(self).clear_focused_field()

    def clear_focused_field(self) -> None:
        _text_input_for(self).clear_focused_field()

    def key(self, modifier: int, keycode: int) -> ActionResult:
        return _text_input_for(self).key(modifier, keycode)

    def switch_input_source(self) -> ActionResult:
        return _text_input_for(self).switch_input_source()

    def paste(self) -> ActionResult:
        return _text_input_for(self).paste()

    # —— Metadata ——
    def has_real_effector(self) -> bool:
        return self.effector.is_connected()
