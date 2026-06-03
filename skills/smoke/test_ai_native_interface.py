from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import glassbox.ai as ai_module
from glassbox.ai import (
    AI_API_VERSION,
    AIAssertionError,
    AIPhone,
    ObservationSummary,
    open_phone,
)
from glassbox.cognition import Box, Scene, UIElement
from glassbox.crawl.policy import CrawlState, NavigationCandidate, PageInfo
from glassbox.effector import ActionResult
from glassbox.obs.artifacts import ArtifactStore
from glassbox.perception.source import Frame, FrameContext
from skills.regression.ios_settings.ai_native_example import run_settings_about_example
from skills.regression.ios_settings.policy import SettingsPolicy


def _scene(*texts: str, page_id: str | None = "settings/root") -> Scene:
    return Scene(
        frame_id=1,
        timestamp=1.0,
        page_id=page_id,
        scene_type="settings",
        semantic_scene_type="settings",
        safe_actions=["scroll"],
        elements=[
            UIElement(
                type="button",
                box=Box(x=0, y=i * 20, w=120, h=16),
                text=text,
                confidence=0.95,
                element_id=i,
                suggested_actions=["tap"],
            )
            for i, text in enumerate(texts)
        ],
    )


def _plain_scene(*texts: str) -> Scene:
    return _scene(*texts, page_id=None)


class FakePhone:
    def __init__(self, scenes: list[Scene]):
        self.scenes = scenes
        self.observe_calls = 0
        self.actions: list[tuple[str, str | None]] = []
        self.action_kwargs: list[dict[str, object]] = []
        self.ai_scroll_prefer_wheel_enabled = False
        self._last_frame = Frame(
            img=np.zeros((40, 80, 3), dtype=np.uint8),
            ts=1.0,
            context=FrameContext(
                coordinate_space="cropped_px",
                source_shape=(1920, 1080),
                crop_bbox=(736, 0, 448, 956),
                projection="cropped_px",
            ),
        )

    def perceive(self):
        idx = min(self.observe_calls, len(self.scenes) - 1)
        self.observe_calls += 1
        return self.scenes[idx]

    def tap_text(self, target, **_kw):
        self.actions.append(("tap_text", target))
        self.action_kwargs.append(dict(_kw))  # CUQ-0.3: record expected_state etc.
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def tap_xy(self, x, y):
        self.actions.append(("tap_xy", f"{x},{y}"))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def swipe_xy(self, x1, y1, x2, y2, **_kw):
        self.actions.append(("swipe_xy", f"{x1},{y1}->{x2},{y2}"))
        self.action_kwargs.append(dict(_kw))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def close_foreground_app(self):
        self.actions.append(("close_foreground_app", None))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def open_app(self, label, *, aliases=()):
        self.actions.append(("open_app", label))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def back_gesture(self):
        self.actions.append(("back", None))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def home(self):
        self.actions.append(("home", None))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def swipe_up(self, **_kw):
        self.actions.append(("swipe_up", None))
        self.action_kwargs.append(dict(_kw))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def swipe_down(self, **_kw):
        self.actions.append(("swipe_down", None))
        self.action_kwargs.append(dict(_kw))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    # CUQ-3.15: wheel scroll (used only when supports('scroll_wheel') and the
    # AIPhone wheel-preference flag are both set).
    def supports(self, action):
        return action in getattr(self, "_supported", set())

    def wheel_scroll_down(self, *, ticks=None):
        self.actions.append(("wheel_scroll_down", None))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def wheel_scroll_up(self, *, ticks=None):
        self.actions.append(("wheel_scroll_up", None))
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    # CUQ-0.1: semantic-plan routing hooks (default off -> existing scroll tests
    # stay on the swipe/wheel path).
    def _uses_semantic_plan(self, op):
        return op in getattr(self, "_plan_ops", set())

    def uses_semantic_plan(self, op):
        return self._uses_semantic_plan(op)

    def _picokvm_fresh_verify_kwargs(self, op):
        del op
        return {}

    def picokvm_fresh_verify_kwargs(self, op):
        return self._picokvm_fresh_verify_kwargs(op)

    def _run_semantic_plan(self, op, *, params=None, **kw):
        self.actions.append(("semantic_plan", op))
        self.action_kwargs.append({"params": params, **kw})
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def run_semantic_plan(self, op, *, params=None, **kw):
        return self._run_semantic_plan(op, params=params, **kw)

    def expect_text(self, target, **_kw):
        scene = self.perceive()
        if target not in [e.text for e in scene.elements]:
            raise AssertionError(target)

    def _viewport_size(self):
        return self._last_frame.shape

    def viewport_size(self):
        return self._viewport_size()

    @property
    def last_frame(self):
        return self._last_frame

    def effector_coordinate_space(self):
        return "cropped_px"

    def _effector_backend(self):
        return "picokvm"

    def effector_backend(self):
        return self._effector_backend()


@dataclass
class FakeRuntime:
    phone: FakePhone
    action_orchestrator: object
    closed: bool = False

    def close(self, *, save_memory=True, close_source=None):
        self.closed = True


def _ai_phone(tmp_path: Path, scenes: list[Scene]) -> AIPhone:
    store = ArtifactStore(tmp_path, run_id="run-ai")
    orchestrator = type("Orchestrator", (), {"store": store})()
    runtime = FakeRuntime(FakePhone(scenes), orchestrator)
    return AIPhone(runtime, run_name="unit")


@pytest.mark.smoke
def test_ai_tap_threads_expected_state_into_orchestrator(tmp_path):
    """CUQ-0.3: AIPhone.tap(expect_visible/expect_page) threads an expected_state
    into tap_text -> orchestrator, engaging P1/P2 verification on the default
    agent tap path. Without an expectation, tap_text gets expected_state=None
    (byte-identical to before)."""
    phone = _ai_phone(tmp_path, [_scene("通用"), _scene("通用")])

    # No expectation -> expected_state must be None on the default path.
    phone.tap("通用")
    assert phone._phone.action_kwargs[-1].get("expected_state") is None

    # expect_visible -> a visible_text expected_state reaches tap_text.
    phone.tap("通用", expect_visible="通用")
    es = phone._phone.action_kwargs[-1].get("expected_state")
    assert es == {"kind": "visible_text", "payload": {"any_of": ["通用"]}}

    # expect_page -> a page_id expected_state reaches tap_text.
    phone.tap("通用", expect_page="settings/general")
    es = phone._phone.action_kwargs[-1].get("expected_state")
    assert es == {"kind": "page_id", "payload": {"page_id": "settings/general"}}


@pytest.mark.smoke
def test_ai_observe_returns_text_first_summary_and_artifacts(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("设置", "通用", "关于本机")])

    obs = phone.observe()

    assert isinstance(obs, ObservationSummary)
    assert obs.page_id == "settings/root"
    assert obs.visible_texts == ("设置", "通用", "关于本机")
    assert obs.scene_path.exists()
    assert obs.screenshot_path and obs.screenshot_path.exists()
    assert obs.viewport_size == (80, 40)
    assert obs.coordinate_space == "cropped_px"
    assert obs.crop_bbox == (736, 0, 448, 956)
    assert obs.elements[1].text == "通用"
    assert obs.elements[1].box.center == (60, 28)
    assert "Visible text" in obs.summary
    assert "elements=3" in obs.summary
    manifest = json.loads((phone.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ai_api_version"] == AI_API_VERSION


@pytest.mark.smoke
def test_ai_tap_requires_exactly_one_target(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("通用")])

    with pytest.raises(ValueError):
        phone.tap()
    with pytest.raises(ValueError):
        phone.tap("通用", intent="general")
    with pytest.raises(NotImplementedError):
        phone.tap(intent="open_general")

    outcome = phone.tap("通用")
    assert outcome.ok is True
    assert phone._phone.actions[-1] == ("tap_text", "通用")


@pytest.mark.smoke
def test_ai_facade_exposes_coordinate_primitives_and_cached_observation(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("设置", "通用")])

    obs = phone.observe()
    assert phone.perceive() is obs
    assert phone.viewport() == (80, 40)
    assert [element.text for element in phone.elements()] == ["设置", "通用"]

    assert phone.tap_xy(10, 20).semantic_status == "succeeded"
    assert phone.swipe_xy(1, 2, 3, 4).semantic_status == "succeeded"
    assert phone.launch_app("settings").semantic_status == "succeeded"
    assert phone.close_app().semantic_status == "succeeded"
    assert phone.home().semantic_status == "succeeded"
    assert phone._phone.actions[-5:] == [
        ("tap_xy", "10,20"),
        ("swipe_xy", "1,2->3,4"),
        ("open_app", "设置"),
        ("close_foreground_app", None),
        ("close_foreground_app", None),
    ]


@pytest.mark.smoke
def test_ai_swipe_expect_visible_uses_stream_until_match(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("Paywall"), _scene("Paywall"), _scene("Continue")])

    outcome = phone.swipe_xy(1, 2, 3, 4, expect_visible="Continue")

    assert outcome.semantic_status == "succeeded"
    kwargs = phone._phone.action_kwargs[-1]
    assert kwargs["settle_strategy"] == "stream_until_match"
    assert kwargs["expect_visible"] == ("Continue",)
    assert kwargs["expected_state"] == {"kind": "visible_text", "payload": {"any_of": ["Continue"]}}
    assert kwargs["stream_timeout_ms"] >= 1
    assert kwargs["max_stream_frames"] >= 1


@pytest.mark.smoke
def test_ai_scroll_until_polls_for_generic_target_text(tmp_path):
    phone = _ai_phone(
        tmp_path,
        [
            _scene("Paywall top"),
            _scene("Paywall middle"),
            _scene("Continue"),
        ],
    )

    obs = phone.scroll("down", until="Continue", timeout_s=2, max_steps=2, settle_timeout_s=1, sample_interval_s=0.01)

    assert "Continue" in obs.visible_texts
    assert ("swipe_up", None) in phone._phone.actions
    kwargs = phone._phone.action_kwargs[-1]
    assert kwargs["settle_strategy"] == "stream_until_match"
    assert kwargs["expect_visible"] == ("Continue",)
    assert kwargs["expected_state"] == {"kind": "visible_text", "payload": {"any_of": ["Continue"]}}


@pytest.mark.smoke
def test_ai_scroll_without_target_uses_transient_window(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("Top"), _scene("Bottom")])

    obs = phone.scroll(direction="down")

    assert obs.visible_texts == ("Bottom",)
    kwargs = phone._phone.action_kwargs[-1]
    assert kwargs["settle_strategy"] == "transient_window"
    assert kwargs["window_duration_ms"] >= 1


@pytest.mark.smoke
def test_ai_scroll_prefers_wheel_when_enabled_and_supported(tmp_path):
    """CUQ-3.15: with the wheel preference on AND the backend supporting it (the
    iPad rig), the generic scroll verb uses the precise wheel instead of swipe."""
    phone = _ai_phone(tmp_path, [_scene("Top"), _scene("Bottom")])
    phone._phone._supported = {"scroll_wheel"}
    phone._phone.ai_scroll_prefer_wheel_enabled = True

    phone.scroll(direction="down")
    phone.scroll(direction="up")

    ops = [op for op, _ in phone._phone.actions]
    assert "wheel_scroll_down" in ops
    assert "wheel_scroll_up" in ops
    assert "swipe_up" not in ops and "swipe_down" not in ops


@pytest.mark.smoke
def test_ai_scroll_falls_back_to_swipe_without_wheel_support(tmp_path):
    """CUQ-3.15 default-safe: with the flag off (or no wheel support) the scroll
    verb stays on swipe-fling — byte-identical to before."""
    phone = _ai_phone(tmp_path, [_scene("Top"), _scene("Bottom")])
    phone._phone.ai_scroll_prefer_wheel_enabled = True  # flag on, but...
    # ...backend does NOT support scroll_wheel -> must fall back to swipe.

    phone.scroll(direction="down")

    ops = [op for op, _ in phone._phone.actions]
    assert "swipe_up" in ops
    assert "wheel_scroll_down" not in ops


@pytest.mark.smoke
def test_ai_scroll_routes_through_semantic_plan_when_flagged(tmp_path):
    """CUQ-0.1: with `scroll` in the semantic-plan ops, the generic scroll verb
    runs the strategy ladder (wheel -> swipe, verified-failure switching) instead
    of the static swipe/wheel choice. The direction is threaded into the plan."""
    phone = _ai_phone(tmp_path, [_scene("Top"), _scene("Bottom")])
    phone._phone._plan_ops = {"scroll"}

    phone.scroll(direction="down")

    ops = [op for op, _ in phone._phone.actions]
    assert "semantic_plan" in ops
    assert "swipe_up" not in ops and "wheel_scroll_down" not in ops
    plan_kwargs = next(k for k in phone._phone.action_kwargs if k.get("params"))
    assert plan_kwargs["params"] == {"direction": "down"}
    assert plan_kwargs.get("policy_action") == "scroll"


@pytest.mark.smoke
def test_ai_navigate_to_page_uses_memory_path_entrypoint(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("设置", "通用", page_id="settings/general")])
    calls: list[dict[str, object]] = []

    def fake_navigate(page_id, *, scene_type=None, allowed_actions=None, min_success_rate=0.5):
        calls.append(
            {
                "page_id": page_id,
                "scene_type": scene_type,
                "allowed_actions": set(allowed_actions or ()),
                "min_success_rate": min_success_rate,
            }
        )
        return type(
            "Result",
            (),
            {
                "attempted": True,
                "reached": True,
                "reason": "reached",
            },
        )()

    phone._phone.navigate_to_page = fake_navigate

    outcome = phone.navigate_to_page(
        "settings/general",
        allowed_actions={"back"},
        min_success_rate=0.8,
    )

    assert outcome.semantic_status == "succeeded"
    assert outcome.semantic_verifier == "memory_path_navigation"
    assert calls == [
        {
            "page_id": "settings/general",
            "scene_type": None,
            "allowed_actions": {"back"},
            "min_success_rate": 0.8,
        }
    ]


@pytest.mark.smoke
def test_ai_goto_page_id_prefers_memory_path_navigation(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("设置", "通用", page_id="settings/general")])
    calls: list[dict[str, object]] = []

    def fake_navigate(page_id, *, scene_type=None, allowed_actions=None, min_success_rate=0.5):
        calls.append(
            {
                "page_id": page_id,
                "scene_type": scene_type,
                "allowed_actions": allowed_actions,
                "min_success_rate": min_success_rate,
            }
        )
        return SimpleNamespace(attempted=True, reached=True, reason="reached")

    phone._phone.navigate_to_page = fake_navigate

    obs = phone.goto("settings/general")

    assert obs.page_id == "settings/general"
    assert calls == [
        {
            "page_id": "settings/general",
            "scene_type": None,
            "allowed_actions": None,
            "min_success_rate": 0.5,
        }
    ]
    assert phone._phone.actions == []
    assert phone._last_action is not None
    assert phone._last_action.action == "navigate_to_page"


@pytest.mark.smoke
def test_ai_goto_page_id_falls_back_to_label_when_memory_path_cannot_reach(tmp_path):
    phone = _ai_phone(
        tmp_path,
        [
            _scene("设置", page_id="settings/root"),
            _scene("设置", page_id="settings/root"),
        ],
    )
    calls: list[str] = []

    def fake_navigate(page_id, *, scene_type=None, allowed_actions=None, min_success_rate=0.5):
        del scene_type, allowed_actions, min_success_rate
        calls.append(page_id)
        return SimpleNamespace(attempted=True, reached=False, reason="no_path")

    phone._phone.navigate_to_page = fake_navigate

    phone.goto("settings/missing")

    assert calls == ["settings/missing"]
    assert phone._phone.actions == [("tap_text", "settings/missing")]


@pytest.mark.smoke
def test_ai_scroll_flag_off_with_wheel_support_stays_on_swipe(tmp_path):
    """CUQ-3.15 default-safety (audit fix): the byte-identical default branch —
    flag OFF/absent while the backend DOES support the wheel must still swipe.
    (The other 'fallback' test had the flag ON with no wheel support, so it never
    exercised the flag-gate itself.)"""
    phone = _ai_phone(tmp_path, [_scene("Top"), _scene("Bottom")])
    phone._phone._supported = {"scroll_wheel"}  # iPad-like backend (wheel available)
    # ai_scroll_prefer_wheel_enabled deliberately left false (default off)

    phone.scroll(direction="down")

    ops = [op for op, _ in phone._phone.actions]
    assert "swipe_up" in ops
    assert "wheel_scroll_down" not in ops


@pytest.mark.smoke
def test_ai_action_outcome_downgrades_visual_only_success_to_unknown(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("设置")])
    result = ActionResult(
        ok=True,
        backend="fake",
        connected=True,
        semantic_status="succeeded",
        semantic_reason="scene or frame changed after action",
        semantic_verifier="scene_progressed",
        semantic_confidence=0.7,
    )

    outcome = phone._action_outcome("tap", "继续", result)

    assert outcome.ok is True
    assert outcome.transport_ok is True
    assert outcome.semantic_status == "unknown"
    assert outcome.semantic_verifier == "scene_progressed"
    assert "visual progress only" in (outcome.reason or "")


@pytest.mark.smoke
def test_ai_launch_app_fails_when_still_on_home(tmp_path):
    scene = _plain_scene("App Store", "照片", "天气", "设置")
    scene.platform_scene_kind = "springboard"
    phone = _ai_phone(tmp_path, [scene])

    outcome = phone.launch_app("DemoApp")

    assert outcome.semantic_status == "failed"
    assert outcome.semantic_verifier == "ai_launch_verification"
    assert "still on Home" in (outcome.reason or "")


@pytest.mark.smoke
def test_ai_launch_app_unknown_when_target_cannot_be_verified(tmp_path):
    phone = _ai_phone(tmp_path, [_plain_scene("Safari", "搜索或输入网站名称")])

    outcome = phone.launch_app("DemoApp")

    assert outcome.semantic_status == "unknown"
    assert outcome.semantic_verifier == "ai_launch_verification"
    assert "could not be verified" in (outcome.reason or "")


@pytest.mark.smoke
def test_ai_launch_app_uses_profile_whitebox_as_landing_proof(tmp_path):
    scene = _plain_scene("25℃", "开关")
    scene.current_vc = "DemoAppMainViewController"
    phone = _ai_phone(tmp_path, [scene])
    app = type("App", (), {"name": "DemoApp", "bundle_id": "com.example.demoapp"})()
    phone._phone.profile = type("Profile", (), {"app": app})()

    outcome = phone.launch_app("DemoApp")

    assert outcome.semantic_status == "succeeded"
    assert outcome.semantic_verifier == "ai_launch_verification"
    assert "current_vc" in (outcome.reason or "")


@pytest.mark.smoke
def test_ai_expect_visible_writes_failure_before_raising(tmp_path):
    phone = _ai_phone(tmp_path, [_scene("设置", "通用")])

    with pytest.raises(AIAssertionError) as exc:
        phone.expect_visible("关于本机", timeout_s=0)

    failure_path = exc.value.failure_path
    assert failure_path.exists()
    text = failure_path.read_text(encoding="utf-8")
    assert "Failure class: script_bug" in text
    assert "Actuation attribution:" in text
    assert "after scene:" in text


@pytest.mark.smoke
def test_ai_explore_and_save_path_as_are_text_first(tmp_path):
    phone = _ai_phone(
        tmp_path,
        [
            _scene("设置", "通用"),
            _scene("设置", "关于本机"),
        ],
    )

    trail = phone.explore("关于本机", max_steps=3)
    artifact = phone.save_path_as("settings_about")

    assert trail.success is True
    assert trail.artifact_path.exists()
    assert "visible:关于本机" in trail.matched_path
    assert artifact.path.exists()
    assert artifact.script_snippet_path and artifact.script_snippet_path.exists()


@pytest.mark.smoke
def test_ai_explore_uses_policy_candidates_and_safety(tmp_path):
    class UnitPolicy:
        def classify(self, observation):
            return PageInfo(page_id=observation.page_id, confidence=1.0)

        def candidates(self, observation):
            if "通用" in observation.visible_texts:
                return [NavigationCandidate(label="通用", action="tap", confidence=0.9)]
            return []

        def is_safe(self, candidate, observation):
            return candidate.label == "通用" and candidate.action == "tap"

        def should_stop(self, state: CrawlState):
            return state.steps >= 4 or state.found

    phone = _ai_phone(
        tmp_path,
        [
            _scene("设置", "通用"),
            _scene("设置", "关于本机", page_id="settings/general"),
        ],
    )
    phone.policy = UnitPolicy()

    trail = phone.explore("关于本机", max_steps=3)

    assert trail.success is True
    assert phone._phone.actions[0] == ("tap_text", "通用")
    assert "tap:通用" in trail.matched_path


@pytest.mark.smoke
def test_open_phone_rejects_timeout_without_wait():
    with pytest.raises(ValueError):
        open_phone(timeout_s=1)


@pytest.mark.smoke
def test_ai_config_enables_stable_post_action_wait_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("GLASSBOX_STABLE_AFTER_ACTION", raising=False)
    monkeypatch.delenv("GLASSBOX_STABLE_TIMEOUT", raising=False)
    monkeypatch.delenv("GLASSBOX_STABLE_CONSECUTIVE", raising=False)
    monkeypatch.setattr(
        ai_module,
        "get_config",
        lambda: ai_module.AgentConfig(
            computer_use_artifact_dir=str(tmp_path),
            stable_after_action=False,
            stable_timeout=3.0,
            stable_consecutive=2,
        ),
    )

    cfg = ai_module._ai_config(record=False, memory=False)

    assert cfg.stable_after_action is True
    assert cfg.stable_timeout >= 5.0
    assert cfg.stable_consecutive >= 3


@pytest.mark.smoke
def test_open_phone_passes_profile_bundle_to_runtime(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    profile = object()

    monkeypatch.setenv("GLASSBOX_AI_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(ai_module, "make_source", lambda *, cfg: object())
    monkeypatch.setattr(ai_module, "_load_profile", lambda bundle_id, *, profiles_dir=None: profile)

    def fake_build_phone(*, source, cfg, profile):
        captured["profile"] = profile
        return FakeRuntime(FakePhone([_scene("设置")]), type("Orchestrator", (), {"store": None})())

    monkeypatch.setattr(ai_module, "build_phone", fake_build_phone)

    phone = open_phone(profile_bundle="com.example.app", record=False, memory=False)

    assert captured["profile"] is profile
    assert phone.run_dir.exists()


@pytest.mark.smoke
def test_open_phone_ignores_config_profile_bundle_without_explicit_opt_in(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    monkeypatch.setenv("GLASSBOX_AI_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(
        ai_module,
        "_ai_config",
        lambda *, record, memory: SimpleNamespace(
            profile_bundle="com.example.from-env",
            computer_use_artifact_dir=str(tmp_path),
            recording_dir=None,
        ),
    )
    monkeypatch.setattr(ai_module, "make_source", lambda *, cfg: object())

    def fake_load_profile(bundle_id, *, profiles_dir=None):
        captured["bundle_id"] = bundle_id
        return None

    def fake_build_phone(*, source, cfg, profile):
        captured["profile"] = profile
        return FakeRuntime(FakePhone([_scene("设置")]), type("Orchestrator", (), {"store": None})())

    monkeypatch.setattr(ai_module, "_load_profile", fake_load_profile)
    monkeypatch.setattr(ai_module, "build_phone", fake_build_phone)

    open_phone(record=False, memory=False)

    assert captured["bundle_id"] is None
    assert captured["profile"] is None


@pytest.mark.smoke
def test_settings_policy_is_separate_from_ai_facade():
    policy = SettingsPolicy()
    obs = ObservationSummary(
        summary="settings",
        page_id=None,
        scene_type="settings",
        visible_texts=("设置", "通用", "飞行模式"),
        actions=(),
        can_scroll=True,
        screenshot_path=None,
        scene_path=Path("scene.json"),
        event_seq=1,
    )

    assert policy.classify(obs).page_id == "settings/root"
    labels = [candidate.label for candidate in policy.candidates(obs)]
    assert "通用" in labels
    assert "飞行模式" not in labels


@pytest.mark.smoke
def test_settings_ai_native_example_uses_public_facade_only():
    source = inspect.getsource(run_settings_about_example)

    assert "open_phone" in source
    assert "glassbox.phone" not in source
    assert "glassbox.runtime" not in source
