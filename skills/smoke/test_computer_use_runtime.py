from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from glassbox.action import (
    ActionOrchestrator,
    BoundStrategy,
    ExpectedState,
    RiskPolicy,
    RuntimeRecoveryPolicy,
    SemanticActionPlan,
    SemanticActionSpec,
    StrategySpec,
    StuckLoopDetector,
    default_semantic_action_plan,
    default_semantic_action_spec,
    make_try_memory_path_hook,
    recover_to_home_then_renavigate,
)
from glassbox.action import recovery as action_recovery
from glassbox.cognition import Box, UIElement
from glassbox.effector import ActionResult, MockEffector
from glassbox.ios.springboard import IOSSpringboardProvider
from glassbox.obs.artifacts import ArtifactStore
from glassbox.perception.source import Frame
from glassbox.perception.stable import StabilityPolicy
from glassbox.phone import Phone
from glassbox.verification.registry import VerifierRegistry
from glassbox.verification.verifiers import SemanticOutcome


class _Source:
    resolution = (32, 32)

    def __init__(self):
        self.count = 0

    def snapshot(self):
        value = min(self.count, 255)
        self.count += 1
        return Frame(img=np.full((32, 32, 3), value, dtype=np.uint8), ts=float(self.count))


class _ReopenSource(_Source):
    def __init__(self):
        super().__init__()
        self.opens = 0
        self.closes = 0

    def open(self):
        self.opens += 1

    def close(self):
        self.closes += 1


class _OCR:
    def __init__(self, text_frames: list[list[str]], *, confidence: float = 0.95):
        self.text_frames = text_frames
        self.confidence = confidence
        self.index = 0

    def recognize(self, image):
        del image
        texts = self.text_frames[min(self.index, len(self.text_frames) - 1)]
        self.index += 1
        return [
            UIElement(
                type="text",
                box=Box(x=1, y=1 + i * 4, w=20, h=3),
                text=text,
                confidence=self.confidence,
                element_id=i,
            )
            for i, text in enumerate(texts)
        ]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _make_phone(
    tmp_path: Path,
    text_frames: list[list[str]],
    *,
    connected: bool = True,
    guarded: bool = False,
    trace_level: str = "standard",
    semantic_fail_fast: bool = False,
    ocr_confidence: float = 0.95,
):
    store = ArtifactStore(tmp_path, run_id="run", trace_level=trace_level)
    orchestrator = ActionOrchestrator(
        store,
        risk_policy=RiskPolicy(guarded=guarded),
        semantic_fail_fast=semantic_fail_fast,
    )
    phone = Phone(
        source=_Source(),
        ocr=_OCR(text_frames, confidence=ocr_confidence),
        effector=MockEffector(_connected=connected),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        springboard_provider=IOSSpringboardProvider(),
    )
    return phone, orchestrator, store


class _RecoveryFakePhone:
    """Minimal duck-typed phone for the recover-to-home hook."""

    def __init__(self, *, home_ok: bool = True, home_status: str | None = "succeeded"):
        self._home_ok = home_ok
        self._home_status = home_status
        self.home_calls = 0
        self.memory = None

    def home(self):
        self.home_calls += 1
        return ActionResult(
            ok=self._home_ok,
            backend="fake",
            connected=True,
            semantic_status=self._home_status,
        )


@pytest.mark.smoke
def test_recover_to_home_hook_drives_home_and_reports_outcome():
    """CUQ-0.2: the universal recovery hook returns to the Home anchor and
    reports recovered only when Home is actually reached."""
    reached = _RecoveryFakePhone(home_ok=True, home_status="succeeded")
    assert recover_to_home_then_renavigate(
        reached, "stuck", {"recovery": "recover_to_home_then_renavigate"}
    ) is True
    assert reached.home_calls == 1

    failed = _RecoveryFakePhone(home_ok=False, home_status="failed")
    assert recover_to_home_then_renavigate(
        failed, "stuck", {"recovery": "recover_to_home_then_renavigate"}
    ) is False


@pytest.mark.smoke
def test_recover_to_home_hook_ignores_unknown_kind_and_guards_reentrancy():
    other = _RecoveryFakePhone()
    assert recover_to_home_then_renavigate(other, "stuck", {"recovery": "other"}) is False
    assert other.home_calls == 0

    nested = _RecoveryFakePhone()
    with action_recovery._recovery_guard(nested):
        assert recover_to_home_then_renavigate(
            nested, "stuck", {"recovery": "recover_to_home_then_renavigate"}
        ) is False
    assert nested.home_calls == 0


class _FakeEdge:
    def __init__(self, action_op: str):
        self.action_op = action_op


class _FakeNode:
    def __init__(self, screen_id: str, page_id: str):
        self.screen_id = screen_id
        self.page_id = page_id


class _MemoryPathFakePhone:
    """Duck-typed phone + screen-memory for the generic memory-path hook (CUQ-0.5).

    `recognize` returns the start node until every edge in `path` has been
    replayed, then the arrival node — so the hook's pre-path recognize and its
    post-replay arrival check see the right screens.
    """

    def __init__(self, *, path, arrive_page: str, home_ok: bool = True):
        self._path = path
        self._n = 0 if path is None else len(path)
        self._replayed = 0
        self._arrive_node = _FakeNode("n_root", arrive_page)
        self._start_node = _FakeNode("n_detail", "app/detail")
        self._home_ok = home_ok
        self.back_calls = 0
        self.home_calls = 0
        self.memory = self
        self._last_frame = None

    # --- screen-memory API ---
    def recognize(self, scene, frame_img=None):
        del scene, frame_img
        if self._path is None:
            return None
        return self._arrive_node if self._replayed >= self._n else self._start_node

    def path_to_page(self, from_id, page_id, *, scene_type=None, allowed_actions=None, min_success_rate=0.0):
        del from_id, page_id, scene_type, allowed_actions, min_success_rate
        return self._path

    # --- phone API ---
    def perceive(self, *, fresh=None):
        del fresh
        return object()

    def back_gesture(self):
        self.back_calls += 1
        self._replayed += 1
        return ActionResult(ok=True, backend="fake", connected=True, semantic_status="succeeded")

    def home(self):
        self.home_calls += 1
        return ActionResult(
            ok=self._home_ok,
            backend="fake",
            connected=True,
            semantic_status="succeeded" if self._home_ok else "failed",
        )


@pytest.mark.smoke
def test_memory_path_recovery_replays_learned_back_chain():
    """CUQ-0.5: the generic hook recognizes the current screen, fetches a learned
    path to the target page, and replays the edge chain to re-navigate in place
    (no Home reset) when the arrival check confirms the target."""
    phone = _MemoryPathFakePhone(path=[_FakeEdge("back"), _FakeEdge("back")], arrive_page="app/root")
    hook = make_try_memory_path_hook(target_page="app/root")
    assert hook(phone, "stuck", {"recovery": "recover_to_home_then_renavigate"}) is True
    assert phone.back_calls == 2
    assert phone.home_calls == 0  # recovered without falling back to Home


@pytest.mark.smoke
def test_memory_path_recovery_falls_back_to_home_when_no_path():
    """CUQ-0.5: no learned path -> delegate to the home-anchor fallback (so the
    hook is never worse than the home-only recovery)."""
    phone = _MemoryPathFakePhone(path=None, arrive_page="app/root")
    hook = make_try_memory_path_hook(target_page="app/root")
    assert hook(phone, "stuck", {"recovery": "recover_to_home_then_renavigate"}) is True
    assert phone.back_calls == 0
    assert phone.home_calls == 1  # fell back to Home


@pytest.mark.smoke
def test_memory_path_recovery_falls_back_when_arrival_unconfirmed():
    """CUQ-0.5: a replayed path that does not land on the target page is not a
    recovery -> fall back to Home rather than reporting a false success."""
    phone = _MemoryPathFakePhone(path=[_FakeEdge("back")], arrive_page="app/elsewhere")
    hook = make_try_memory_path_hook(target_page="app/root")
    assert hook(phone, "stuck", {"recovery": "recover_to_home_then_renavigate"}) is True
    assert phone.back_calls == 1
    assert phone.home_calls == 1


@pytest.mark.smoke
def test_build_recovery_hook_is_home_only_without_target():
    """CUQ-0.5: with no recovery_target_page configured, the runtime installs the
    plain home-anchor hook (default recovery is byte-identical)."""
    from glassbox.runtime import _build_recovery_hook

    class _Cfg:
        recovery_target_page = None
        recovery_allowed_actions = "home,back"
        recovery_min_success_rate = 0.5

    hook = _build_recovery_hook(
        _Cfg(),
        make_try_memory_path_hook=make_try_memory_path_hook,
        home_hook=recover_to_home_then_renavigate,
    )
    assert hook is recover_to_home_then_renavigate


@pytest.mark.smoke
def test_build_recovery_hook_parses_target_set_config():
    """CUQ-0.5 (audit fix): the flag-ON branch — target page + comma-split
    allowed-actions + float min-success-rate — must reach make_try_memory_path_hook.
    The only prior test covered the OFF branch, leaving the parse wiring unverified."""
    from glassbox.runtime import _build_recovery_hook

    captured = {}

    def fake_factory(*, target_page, allowed_actions, min_success_rate, fallback):
        captured.update(target_page=target_page, allowed_actions=allowed_actions,
                        min_success_rate=min_success_rate, fallback=fallback)
        return "sentinel-hook"

    class _Cfg:
        recovery_target_page = "  app/root  "          # exercises .strip()
        recovery_allowed_actions = " home , back ,, "    # comma-split + strip + empty-filter
        recovery_min_success_rate = "0.75"              # float() from a string

    hook = _build_recovery_hook(
        _Cfg(), make_try_memory_path_hook=fake_factory, home_hook=recover_to_home_then_renavigate
    )
    assert hook == "sentinel-hook"
    assert captured["target_page"] == "app/root"
    assert captured["allowed_actions"] == {"home", "back"}
    assert captured["min_success_rate"] == 0.75
    assert isinstance(captured["min_success_rate"], float)
    assert captured["fallback"] is recover_to_home_then_renavigate


@pytest.mark.smoke
def test_orchestrator_stuck_recovery_invokes_installed_hook(tmp_path):
    """CUQ-0.2 end-to-end: with the real hook installed, a repeated identical
    failure trips the stuck detector and actually drives recovery (recovered)."""
    store = ArtifactStore(tmp_path, run_id="run")
    recovered_calls = {"n": 0}

    def hook(phone, reason, payload):
        del phone, reason
        assert payload["recovery"] == "recover_to_home_then_renavigate"
        recovered_calls["n"] += 1
        return True

    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(hook=hook, max_attempts=2),
        stuck_detector=StuckLoopDetector(threshold=2),
    )
    phone, _, _ = _make_phone(tmp_path, [["停滞"]])
    phone.action_orchestrator = orchestrator

    sample_signature = "sig-stuck"

    def stuck_attempt():
        from glassbox.action.stuck import StuckSample

        decision = orchestrator.stuck_detector.observe(
            StuckSample(sample_signature, "no progress")
        )
        return decision

    # First identical sample: below threshold, no recovery yet.
    assert stuck_attempt().should_recover is False
    # Second identical sample: trips the threshold.
    decision = stuck_attempt()
    assert decision.should_recover is True
    result = orchestrator.recovery_policy.recover(
        phone, "no progress", {"recovery": decision.recovery}
    )
    orchestrator.close()
    assert result.attempted is True
    assert result.recovered is True
    assert recovered_calls["n"] == 1


@pytest.mark.smoke
def test_computer_use_runtime_control_center_success(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["勿扰模式", "未在播放"]],
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "ios_control_center_opened"
    assert result.attempt_id == "act_000000"
    assert (store.run_dir / "manifest.json").exists()
    assert (store.run_dir / "audit.jsonl").exists()
    assert (store.run_dir / "actions.jsonl").exists()
    assert (store.run_dir / "attempt_groups.jsonl").exists()
    assert (store.run_dir / "review_timeline.json").exists()
    assert (store.run_dir / "report.md").exists()
    report_md = (store.run_dir / "report.md").read_text(encoding="utf-8")
    report_html = (store.run_dir / "report.html").read_text(encoding="utf-8")
    assert "![before](frames/" in report_md
    assert "Diff summary:" in report_md
    assert "<img src='frames/" in report_html
    assert "<summary>Diff summary</summary>" in report_html
    manifest = json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["harness_version"]
    assert manifest["device"] == {
        "name": None,
        "model": None,
        "os_version": None,
        "locale": None,
    }
    assert manifest["privacy_mode"] == "sandbox_phone"
    assert manifest["preflight"]["status"] == "passed"
    assert manifest["observation_producer"] == {
        "mode": "scoped_source_owner",
        "continuous_recorder_feeds_buffer": False,
        "audit_writer": "action_orchestrator",
        "frame_capture_event": "promoted_ledger_frame_only",
        "source_owner": "action_orchestrator",
        "raw_frame_source": "phone.perceive_snapshot",
    }
    assert manifest["observation_buffer"]["min_retention_ms"] == 10000
    assert manifest["observation_buffer"]["min_retention_frames"] == 120
    assert manifest["artifact_metrics"]["frames_promoted"] == 3
    assert manifest["artifact_metrics"]["frame_files_saved"] == 3
    assert manifest["artifact_metrics"]["scene_files_saved"] == 3
    assert manifest["artifact_metrics"]["actions_projected"] == 1

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    action = actions[0]
    assert action["actor"] == "agent"
    assert action["command_result"]["transport_ok"] is True
    assert action["semantic"]["status"] == "succeeded"
    assert action["semantic"]["matched_frame_id"] == action["after"]["frame_id"]
    assert action["semantic"]["matched_scene_id"] == action["after"]["scene_id"]
    assert action["before_requested"]["screenshot"].startswith("frames/")
    assert action["before_command"]["frame_id"] != action["before_requested"]["frame_id"]
    assert action["before_command"]["screenshot"].startswith("frames/")
    assert action["after"]["screenshot"].startswith("frames/")
    assert action["diff"]["frame"].startswith("diffs/")
    assert action["verification"].startswith("verifications/")
    assert action["observation"]["started_ms_after_command"] >= 0
    assert action["observation"]["duration_ms"] >= 0
    assert action["observation"]["frame_ids"] == [action["after"]["frame_id"]]
    assert action["observation"]["scene_ids"] == [action["after"]["scene_id"]]

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert all(e["run_id"] == "run" for e in audit)
    assert next(e for e in audit if e["type"] == "observation.producer_configured")["payload"][
        "mode"
    ] == "scoped_source_owner"
    assert next(e for e in audit if e["type"] == "attempt_group.started")["actor"] == "agent"
    assert next(e for e in audit if e["type"] == "action.started")["actor"] == "agent"
    assert any(e["type"] == "run.preflight" for e in audit)
    assert next(e for e in audit if e["type"] == "run.finished")["payload"]["artifact_metrics"][
        "actions_projected"
    ] == 1
    assert [item.source for item in orchestrator.observation_buffer.snapshot()] == [
        "preflight",
        "before_requested",
        "before_command",
        "after",
    ]
    frame_events = [e for e in audit if e["type"] == "frame.captured"]
    assert len(frame_events) == 3
    assert {e["payload"]["observation_role"] for e in frame_events} == {
        "before_requested",
        "before_command",
        "after",
    }


@pytest.mark.smoke
def test_orchestrator_attempt_observe_after_side_effect_contract(tmp_path):
    """P6: lock the concrete _run_attempt/_observe_after boundary outputs.

    The later P2 extraction may move locals into helpers, but it must preserve
    verifier input shape, action artifacts, audit events, and Phone cache/fresh
    flags observable at the boundary.
    """

    captured_inputs = []

    class CapturingVerifier:
        name = "capturing_verifier"
        version = "test"
        success_markers = ()

        def verify(self, input):
            captured_inputs.append(input)
            return SemanticOutcome(
                status="succeeded",
                verifier=self.name,
                reason="captured verifier input",
                confidence=1.0,
                verifier_version=self.version,
                matched_frame_id=input.after_frame_ids[-1],
                matched_scene_id=input.after_scene_ids[-1],
                deterministic=True,
                retry_allowed=False,
            )

    registry = VerifierRegistry(load_entry_points=False)
    registry.register(CapturingVerifier())
    source = _ReopenSource()
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, registry=registry)
    phone = Phone(
        source=source,
        ocr=_OCR([["before requested"], ["before command"], ["after result"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    result = phone._execute_action(
        "tap",
        lambda: phone.effector.tap(3, 4),
        verifier="capturing_verifier",
        settle_strategy="fixed_delay_after",
        delay_ms=0,
        fresh_source_reopen=True,
        x=3,
        y=4,
        via="test_probe",
        target="Probe",
    )
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "capturing_verifier"
    assert source.closes == 1
    assert source.opens == 1

    assert len(captured_inputs) == 1
    verifier_input = captured_inputs[0]
    assert verifier_input.attempt_id == result.attempt_id == "act_000000"
    assert verifier_input.attempt_group_id == result.attempt_group_id
    assert verifier_input.action["op"] == "tap"
    assert verifier_input.action["kwargs"]["via"] == "test_probe"
    assert verifier_input.before_requested is not None
    assert verifier_input.before_command is not None
    assert [e.text for e in verifier_input.after_scenes[0].elements] == ["after result"]
    assert verifier_input.after_mode == "single_frame"
    assert len(verifier_input.after_frame_ids) == 1
    assert len(verifier_input.after_scene_ids) == 1
    assert verifier_input.command_result["transport_ok"] is True
    assert verifier_input.risk["allowed"] is True

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    action = actions[0]
    assert groups == [
        {
            "attempt_group_id": result.attempt_group_id,
            "op": "tap",
            "actor": "agent",
            "attempt_ids": ["act_000000"],
            "group_status": "succeeded",
            "terminal_reason": "captured verifier input",
            "retry_count": 0,
        }
    ]
    assert action["attempt_id"] == "act_000000"
    assert action["command"]["x"] == 3
    assert action["command"]["y"] == 4
    assert action["command_result"]["transport_ok"] is True
    assert action["semantic"]["status"] == "succeeded"
    assert action["semantic"]["matched_frame_id"] == verifier_input.after_frame_ids[0]
    assert action["semantic"]["matched_scene_id"] == verifier_input.after_scene_ids[0]
    assert action["observation"]["settle_strategy"] == "fixed_delay_after"
    assert action["observation"]["after_mode"] == "single_frame"
    assert action["observation"]["fresh_source_reopen"] is True
    assert action["observation"]["fresh_source_reopened"] is True
    assert action["observation"]["frame_ids"] == verifier_input.after_frame_ids
    assert action["observation"]["scene_ids"] == verifier_input.after_scene_ids

    event_types = [event["type"] for event in audit]
    assert event_types.index("policy.evaluated") < event_types.index("command.sent")
    assert event_types.index("command.sent") < event_types.index("command.acked")
    assert event_types.index("command.acked") < event_types.index("verifier.started")
    assert event_types.index("verifier.started") < event_types.index("verifier.finished")
    assert event_types.index("verifier.finished") < event_types.index("action.finished")

    recorded = phone._pending_actions_for_memory[-1]
    assert recorded.op == "tap"
    assert recorded.via == "test_probe"
    assert recorded.target == "Probe"
    assert recorded.x == 3
    assert recorded.y == 4
    assert phone._needs_stable_frame is True
    assert phone._fresh_source_reopened_after_action is False
    assert phone._cache_scene is None
    assert phone._last_scene is None


@pytest.mark.smoke
def test_orchestrator_can_reopen_source_before_fresh_after_observation(tmp_path):
    source = _ReopenSource()
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=source,
        ocr=_OCR([["设置"], ["设置"], ["天气", "日历", "照片", "App Store"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    result = phone._execute_action(
        "home",
        lambda: phone.effector.home(),
        fresh_source_reopen=True,
        fresh_delay_ms=0,
        settle_strategy="stream_until_match",
        stream_timeout_ms=1,
        sample_interval_ms=1,
    )
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert source.closes == 1
    assert source.opens == 1


@pytest.mark.smoke
def test_computer_use_runtime_executes_semantic_action_plan_strategy_ladder(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["Still here"],
            ["Done"],
        ],
    )
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.home()),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.home()),
        ],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert result.semantic_verifier == "expected_state"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["command"]["strategy"] for action in actions] == ["first_tap", "second_tap"]
    assert [action["semantic"]["status"] for action in actions] == ["failed", "succeeded"]
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert groups[-1]["group_status"] == "succeeded"
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(event["type"] == "semantic_plan.strategy_failed" for event in audit)
    assert any(event["type"] == "semantic_plan.finished" for event in audit)


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_preserves_strategy_list_order(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["Done"],
            ["Done"],
            ["Done"],
            ["Done"],
        ],
    )
    calls: list[str] = []
    spec = SemanticActionSpec(
        op="tap",
        strategies=(
            StrategySpec("listed_first_low_rank", reliability_rank=100),
            StrategySpec("listed_second_high_rank", reliability_rank=1),
        ),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(
                spec.strategies[0],
                lambda: calls.append("listed_first_low_rank") or phone.effector.home(),
            ),
            BoundStrategy(
                spec.strategies[1],
                lambda: calls.append("listed_second_high_rank") or phone.effector.home(),
            ),
        ],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert calls == ["listed_first_low_rank"]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["command"]["strategy"] for action in actions] == ["listed_first_low_rank"]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    finished = next(event for event in audit if event["type"] == "semantic_plan.finished")
    assert finished["payload"]["strategy_switches"] == 0


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_skips_unsupported_capability(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["Done"],
            ["Done"],
            ["Done"],
            ["Done"],
        ],
    )
    phone.supports = lambda capability: capability != "missing_capability"
    calls: list[str] = []
    spec = SemanticActionSpec(
        op="tap",
        strategies=(
            StrategySpec("unsupported_first", capability="missing_capability"),
            StrategySpec("supported_second", capability="tap"),
        ),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(
                spec.strategies[0],
                lambda: pytest.fail("unsupported strategy should be skipped"),
            ),
            BoundStrategy(
                spec.strategies[1],
                lambda: calls.append("supported_second") or phone.effector.home(),
            ),
        ],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert calls == ["supported_second"]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    assert actions[0]["command"]["strategy"] == "supported_second"
    assert actions[0]["command"]["attempt_index"] == 0
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    skipped = next(event for event in audit if event["type"] == "semantic_plan.strategy_skipped")
    assert skipped["payload"]["strategy"]["name"] == "unsupported_first"
    assert skipped["payload"]["reason"] == "capability unsupported"


@pytest.mark.smoke
def test_default_semantic_action_spec_expected_state_optional_roundtrip():
    """CUQ-0.1/0.8 enabler: a core-op plan can omit expected_state (the generic
    op verifier drives the ladder), and the spec round-trips with it None."""
    spec = default_semantic_action_spec("back")
    assert spec.expected_state is None
    assert [s.name for s in spec.strategies] == [
        "nav_back_tap",
        "keyboard_back",
        "edge_back_gesture",
    ]
    payload = spec.to_dict()
    assert payload["expected_state"] is None
    restored = SemanticActionSpec.from_dict(payload)
    assert restored.expected_state is None
    assert restored.op == "back"
    assert [s.name for s in restored.strategies] == [s.name for s in spec.strategies]

    plan = default_semantic_action_plan(object(), "back")
    assert len(plan.bound) == 3


@pytest.mark.smoke
def test_back_gesture_flag_routes_through_strategy_ladder(tmp_path):
    """CUQ-0.1: with the op flagged, back_gesture() runs the first-class ladder
    (nav_back_tap -> keyboard_back -> edge_back_gesture) with verified-failure
    switching, instead of the legacy single-shot path."""
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["停滞"]] * 16),  # no scene progress -> strategies fail & switch
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
        semantic_plan_ops=frozenset({"back"}),
    )

    phone.back_gesture()
    orchestrator.close()

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    plan_starts = [
        e
        for e in audit
        if e["type"] == "attempt_group.started"
        and isinstance(e.get("payload", {}).get("semantic_action_spec"), dict)
    ]
    assert plan_starts, "back was not routed through the SemanticActionPlan ladder"
    assert plan_starts[0]["payload"]["semantic_action_spec"]["op"] == "back"
    # the ladder engaged more than one strategy (switch and/or capability skip)
    laddered = sum(
        1
        for e in audit
        if e["type"] in {"semantic_plan.strategy_failed", "semantic_plan.strategy_skipped"}
    )
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert laddered >= 1 or len(actions) >= 2


@pytest.mark.smoke
def test_back_gesture_without_flag_uses_legacy_single_shot_path(tmp_path):
    """Default (flag off) preserves the legacy back path -- no SemanticActionPlan."""
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["停滞"]] * 6),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    phone.back_gesture()
    orchestrator.close()

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert not any(
        isinstance(e.get("payload", {}).get("semantic_action_spec"), dict) for e in audit
    )


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_recovers_and_reattempts(tmp_path):
    recoveries = []

    def recover(_phone, reason, payload):
        recoveries.append((reason, payload["semantic_action_spec"]["op"]))
        return True

    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(recover, max_attempts=1),
    )
    phone = Phone(
        source=_Source(),
        ocr=_OCR(
            [
                ["主屏幕"],
                ["主屏幕"],
                ["主屏幕"],
                ["Still here"],
                ["Still here"],
                ["Done"],
            ]
        ),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Still here"]}),
        recovery="recover_to_home_then_renavigate",
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], lambda: phone.effector.home())],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert recoveries == [("visible text expectation unmet", "tap")]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["semantic"]["status"] for action in actions] == ["failed", "succeeded"]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(event["type"] == "semantic_plan.recovery.started" for event in audit)
    finished = next(event for event in audit if event["type"] == "semantic_plan.finished")
    assert finished["payload"]["recovered"] is True


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_retries_same_strategy_on_transport_failure(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["Done"],
        ],
    )
    calls = []

    def flaky_call():
        calls.append("target_tap")
        if len(calls) == 1:
            return ActionResult.failed(
                backend="test",
                connected=False,
                error="transport down",
            )
        return ActionResult(ok=True, backend="test", connected=True)

    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"), StrategySpec("fallback_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["主屏幕"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], flaky_call),
            BoundStrategy(spec.strategies[1], lambda: ActionResult(ok=True, backend="test", connected=True)),
        ],
    )

    result = phone._execute_action("tap", plan, transport_retry_budget=1)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert calls == ["target_tap", "target_tap"]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["command"]["strategy"] for action in actions] == ["target_tap", "target_tap"]
    assert [action["semantic"]["status"] for action in actions] == ["transport_failed", "succeeded"]
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert groups[-1]["retry_count"] == 1
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    retry = next(event for event in audit if event["type"] == "action.retry_scheduled")
    assert retry["payload"]["kind"] == "transport"
    assert retry["payload"]["strategy"] == "target_tap"
    finished = next(event for event in audit if event["type"] == "semantic_plan.finished")
    assert finished["payload"]["strategy_switches"] == 0


@pytest.mark.smoke
def test_legacy_path_retries_transport_failure_independent_of_idempotency(tmp_path):
    """CUQ-0.10: a transport failure (the effector call returned not-ok before any
    GUI verification → the action did not land) is now retried on the LEGACY
    (non-plan) path up to transport_retry_budget, even for a non-idempotent op —
    previously only the (dead) semantic-plan path retried transport."""
    phone, orchestrator, store = _make_phone(tmp_path, [["主屏幕"]] * 6)
    calls = []

    def flaky_call():
        calls.append("x")
        if len(calls) == 1:
            return ActionResult.failed(backend="test", connected=False, error="transport down")
        return ActionResult(ok=True, backend="test", connected=True)

    result = phone._execute_action(
        "tap",
        flaky_call,
        idempotent=False,  # non-idempotent: retry_budget is forced to 0...
        transport_retry_budget=1,  # ...but a transport failure still retries.
        expected_state=ExpectedState("visible_text", {"any_of": ["主屏幕"]}).to_dict(),
    )
    orchestrator.close()

    assert calls == ["x", "x"]  # retried once despite non-idempotent
    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [a["semantic"]["status"] for a in actions] == ["transport_failed", "succeeded"]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    retry = next(e for e in audit if e["type"] == "action.retry_scheduled")
    assert retry["payload"]["kind"] == "transport"


@pytest.mark.smoke
def test_legacy_path_does_not_retry_transport_failure_without_budget(tmp_path):
    """CUQ-0.10 default-safety: with no transport_retry_budget (the default), a
    transport failure is NOT retried — byte-identical to before."""
    phone, orchestrator, _store = _make_phone(tmp_path / "no_budget", [["主屏幕"]] * 3)
    calls = []

    def always_fail():
        calls.append("x")
        return ActionResult.failed(backend="test", connected=False, error="transport down")

    phone._execute_action("tap", always_fail, idempotent=False)
    orchestrator.close()

    assert calls == ["x"]  # no retry on the default path


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_does_not_retry_non_idempotent_transport_failure(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
        ],
    )
    calls = []

    def flaky_call():
        calls.append("target_tap")
        return ActionResult.failed(
            backend="test",
            connected=False,
            error="transport down",
        )

    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=False,
    )
    plan = SemanticActionPlan(spec, [BoundStrategy(spec.strategies[0], flaky_call)])

    result = phone._execute_action("tap", plan, transport_retry_budget=1)
    orchestrator.close()

    assert result.semantic_status == "transport_failed"
    assert calls == ["target_tap"]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["command"]["strategy"] for action in actions] == ["target_tap"]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert not any(event["type"] == "action.retry_scheduled" for event in audit)


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_resets_transport_retry_budget_after_recovery(tmp_path):
    recoveries = []

    def recover(_phone, reason, payload):
        recoveries.append((reason, payload["semantic_action_spec"]["op"]))
        return True

    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(recover, max_attempts=1),
    )
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["Done"]] * 12),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )
    calls = []

    def flaky_call():
        calls.append("target_tap")
        if len(calls) in {1, 2, 3}:
            return ActionResult.failed(
                backend="test",
                connected=False,
                error="transport down",
            )
        return ActionResult(ok=True, backend="test", connected=True)

    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery="recover_to_home_then_renavigate",
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], flaky_call)],
    )

    result = phone._execute_action("tap", plan, transport_retry_budget=1)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert calls == ["target_tap", "target_tap", "target_tap", "target_tap"]
    assert recoveries == [("transport down", "tap")]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["semantic"]["status"] for action in actions] == [
        "transport_failed",
        "transport_failed",
        "transport_failed",
        "succeeded",
    ]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    retry_events = [event for event in audit if event["type"] == "action.retry_scheduled"]
    assert [event["payload"]["next_attempt_index"] for event in retry_events] == [1, 3]
    assert any(event["type"] == "semantic_plan.recovery.started" for event in audit)


@pytest.mark.smoke
def test_computer_use_runtime_expected_state_uses_vlm_gate_before_strategy_switch(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["unclear"],
        ],
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        assert scene_hint == "expected_state:visible_text"
        assert phone._last_scene is not None
        phone._last_scene.elements[0].text = "Done"
        phone._last_scene.vlm_status = "ok"
        return phone._last_scene

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.home()),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.home()),
        ],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    assert actions[0]["semantic"]["verifier"] == "expected_state_vlm"
    assert actions[0]["command"]["vlm_calls"] == 1
    assert actions[0]["command"]["vlm_triggers"] == ["target_missing", "verify_unknown"]


@pytest.mark.smoke
def test_reverify_fresh_frame_resolves_without_spending_vlm(tmp_path):
    """CUQ-1.3 (flag on): when an expected_state misses on the post-action OCR
    but the text has since finished rendering, re-perceiving a fresh frame
    resolves it via 'expected_state_refresh' WITHOUT spending a VLM call (a
    describe() call would only re-read the same stale frame)."""
    phone, orchestrator, _store = _make_phone(
        tmp_path,
        [
            ["loading"],  # after_scene: "Done" has not rendered yet
            ["Done"],     # fresh re-perceive: "Done" is now on screen
        ],
    )
    phone.perceive_cache_diff = 0  # isolate the re-OCR from the frame-diff cache
    phone._reverify_fresh_frame = True
    phone.kimi = object()
    calls = {"n": 0}

    def describe(scene_hint=None):
        calls["n"] += 1
        return phone._last_scene

    phone.describe = describe
    expected = ExpectedState("visible_text", {"any_of": ["Done"]})
    metadata = {"expected_state": expected.to_dict(), "max_vlm_calls_per_action": 1}
    base = SemanticOutcome(status="unknown", verifier="scene_progressed", reason="no progress")
    after_scene = phone.perceive()  # consumes ["loading"]

    result = orchestrator._semantic_after_expected_state(phone, base, metadata, after_scene)
    orchestrator.close()

    assert result.status == "succeeded"
    assert result.verifier == "expected_state_refresh"
    assert calls["n"] == 0  # the VLM budget was never touched
    assert metadata.get("vlm_calls", 0) == 0


@pytest.mark.smoke
def test_reverify_fresh_frame_off_keeps_vlm_escalation(tmp_path):
    """CUQ-1.3 (flag off, default): the fresh re-perceive is skipped, so an
    OCR-missed expectation still escalates to the VLM as before."""
    phone, orchestrator, _store = _make_phone(
        tmp_path,
        [
            ["loading"],
            ["Done"],  # present, but the flag-off path must NOT consume it
        ],
    )
    phone.perceive_cache_diff = 0
    phone.kimi = object()
    calls = {"n": 0}

    def describe(scene_hint=None):
        calls["n"] += 1
        phone._last_scene.elements[0].text = "Done"  # the VLM resolves it
        phone._last_scene.vlm_status = "ok"
        return phone._last_scene

    phone.describe = describe
    expected = ExpectedState("visible_text", {"any_of": ["Done"]})
    metadata = {"expected_state": expected.to_dict(), "max_vlm_calls_per_action": 1}
    base = SemanticOutcome(status="unknown", verifier="scene_progressed", reason="no progress")
    after_scene = phone.perceive()  # consumes ["loading"]

    result = orchestrator._semantic_after_expected_state(phone, base, metadata, after_scene)
    orchestrator.close()

    assert result.status == "succeeded"
    assert result.verifier == "expected_state_vlm"
    assert calls["n"] == 1  # escalated to the VLM, not the fresh-frame fast path


@pytest.mark.smoke
def test_legacy_path_enforces_per_action_vlm_budget_across_attempts(tmp_path):
    """CUQ-0.7: the per-action VLM budget must hold across retries. The legacy
    execute() loop now carries vlm_* counters forward in the shared metadata
    dict, so a second attempt cannot re-spend the per-action cap and an
    unknown->VLM->unknown sequence cannot loop the VLM past the budget."""
    phone, orchestrator, _store = _make_phone(tmp_path, [["unclear"]])
    phone.kimi = object()
    calls = {"n": 0}
    after_scene = phone.perceive()  # a real scene that does NOT contain "Done"

    def describe(scene_hint=None):
        calls["n"] += 1
        return after_scene  # the VLM does not resolve the expectation either

    phone.describe = describe
    expected = ExpectedState("visible_text", {"any_of": ["Done"]})
    metadata = {
        "expected_state": expected.to_dict(),
        "max_vlm_calls_per_action": 1,
        "max_vlm_calls_per_attempt": 1,
    }
    base = SemanticOutcome(status="unknown", verifier="scene_progressed", reason="no progress")

    # Attempt 0 escalates once and the merge bumps metadata["vlm_calls"] -> 1.
    orchestrator._semantic_after_expected_state(phone, base, metadata, after_scene)
    # Attempt 1 reuses the SAME carried-forward metadata: remaining budget is 0.
    orchestrator._semantic_after_expected_state(phone, base, metadata, after_scene)
    orchestrator.close()

    assert calls["n"] == 1
    assert metadata["vlm_calls"] == 1
    assert metadata.get("vlm_budget_exhausted") is True


@pytest.mark.smoke
def test_computer_use_runtime_expected_state_fast_path_does_not_call_vlm(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["Done"],
            ["Done"],
            ["Done"],
            ["Done"],
        ],
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        raise AssertionError(f"VLM should not run on OCR-verified success, got {scene_hint!r}")

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], lambda: phone.effector.home())],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["semantic"]["verifier"] == "expected_state"
    assert "vlm_calls" not in actions[0]["command"]


@pytest.mark.smoke
def test_computer_use_runtime_expected_state_vlm_gate_records_low_confidence(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["unclear"],
        ],
        ocr_confidence=0.4,
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        assert scene_hint == "expected_state:visible_text"
        assert phone._last_scene is not None
        phone._last_scene.elements[0].text = "Done"
        phone._last_scene.vlm_status = "ok"
        return phone._last_scene

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], lambda: phone.effector.home())],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["semantic"]["verifier"] == "expected_state_vlm"
    assert actions[0]["command"]["vlm_calls"] == 1
    assert actions[0]["command"]["vlm_triggers"] == [
        "low_confidence",
        "target_missing",
        "verify_unknown",
    ]


@pytest.mark.smoke
def test_computer_use_runtime_expected_state_vlm_gate_records_confidence_missing(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            [],
            [],
            [],
            [],
        ],
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        assert scene_hint == "expected_state:visible_text"
        assert phone._last_scene is not None
        phone._last_scene.elements.append(
            UIElement(
                type="text",
                box=Box(x=1, y=1, w=20, h=3),
                text="Done",
                confidence=0.9,
                element_id=0,
            )
        )
        phone._last_scene.vlm_status = "ok"
        return phone._last_scene

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], lambda: phone.effector.home())],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["semantic"]["verifier"] == "expected_state_vlm"
    assert actions[0]["command"]["vlm_calls"] == 1
    assert actions[0]["command"]["vlm_triggers"] == [
        "confidence_missing",
        "target_missing",
        "verify_unknown",
    ]


@pytest.mark.smoke
def test_computer_use_runtime_expected_state_records_vlm_cache_hit(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["unclear"],
        ],
    )

    class _Kimi:
        last_hit = False

    phone.kimi = _Kimi()

    def describe(scene_hint=None):
        assert scene_hint == "expected_state:visible_text"
        assert phone._last_scene is not None
        phone.kimi.last_hit = True
        phone._last_scene.elements[0].text = "Done"
        phone._last_scene.vlm_status = "ok"
        return phone._last_scene

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], lambda: phone.effector.home())],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["command"]["vlm_calls"] == 1
    assert actions[0]["command"]["vlm_cache_hits"] == 1
    assert "vlm_cache_misses" not in actions[0]["command"]


@pytest.mark.smoke
def test_computer_use_runtime_expected_state_vlm_gate_records_classifier_conflict(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["unclear"],
        ],
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        assert scene_hint == "expected_state:visible_text"
        assert phone._last_scene is not None
        phone._last_scene.elements[0].text = "Done"
        phone._last_scene.vlm_status = "ok"
        return phone._last_scene

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [BoundStrategy(spec.strategies[0], lambda: phone.effector.home())],
    )

    result = phone._execute_action("tap", plan, classifier_conflict=True)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["semantic"]["verifier"] == "expected_state_vlm"
    assert actions[0]["command"]["vlm_calls"] == 1
    assert actions[0]["command"]["vlm_triggers"] == [
        "target_missing",
        "classifier_conflict",
        "verify_unknown",
    ]
    assert actions[0]["command"]["last_vlm_trigger"] == "verify_unknown"


@pytest.mark.smoke
def test_computer_use_runtime_vlm_disabled_falls_back_to_strategy_switch(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["Still here"],
            ["Done"],
        ],
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        raise AssertionError(f"VLM should be disabled, got scene_hint={scene_hint!r}")

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.home()),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.home()),
        ],
    )

    result = phone._execute_action("tap", plan, vlm_disabled=True)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["command"]["strategy"] for action in actions] == ["first_tap", "second_tap"]
    assert actions[0]["command"]["vlm_calls"] == 0
    assert actions[0]["command"]["vlm_triggers"] == ["target_missing", "verify_unknown"]
    assert actions[1]["semantic"]["verifier"] == "expected_state"


@pytest.mark.smoke
def test_computer_use_runtime_vlm_attempt_budget_zero_falls_back_to_strategy_switch(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [
            ["主屏幕"],
            ["主屏幕"],
            ["主屏幕"],
            ["Still here"],
            ["Done"],
        ],
    )
    phone.kimi = object()

    def describe(scene_hint=None):
        raise AssertionError(f"VLM attempt budget should block calls, got {scene_hint!r}")

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.home()),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.home()),
        ],
    )

    result = phone._execute_action("tap", plan, max_vlm_calls_per_attempt=0)
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [action["command"]["strategy"] for action in actions] == ["first_tap", "second_tap"]
    assert actions[0]["command"]["vlm_calls"] == 0
    assert actions[0]["command"]["vlm_triggers"] == ["target_missing", "verify_unknown"]
    assert actions[0]["command"]["vlm_budget_exhausted"] is True
    assert actions[1]["semantic"]["verifier"] == "expected_state"


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_stops_on_approval_required(tmp_path):
    recoveries = []
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["想要访问您的照片", "不允许", "允许访问"]],
    )
    orchestrator.recovery_policy = RuntimeRecoveryPolicy(
        lambda _phone, reason, _payload: recoveries.append(reason) or True,
        max_attempts=1,
    )
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery="recover_to_home_then_renavigate",
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.tap(10, 10)),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.tap(20, 20)),
        ],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "approval_required"
    assert recoveries == []
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    assert actions[0]["semantic"]["disqualifying_state"] == "ios_system_permission_dialog"
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert groups[-1]["group_status"] == "approval_required"
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert not any(event["type"] == "semantic_plan.strategy_failed" for event in audit)
    assert not any(event["type"] == "semantic_plan.recovery.started" for event in audit)


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_stops_on_blocked_state(tmp_path):
    recoveries = []
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["滑动来关机", "SOS"]],
    )
    orchestrator.recovery_policy = RuntimeRecoveryPolicy(
        lambda _phone, reason, _payload: recoveries.append(reason) or True,
        max_attempts=1,
    )
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery="recover_to_home_then_renavigate",
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.tap(10, 10)),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.tap(20, 20)),
        ],
    )

    result = phone._execute_action("tap", plan)
    orchestrator.close()

    assert result.semantic_status == "blocked"  # CUQ-3.19: safety stop terminates
    assert recoveries == []
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    assert actions[0]["semantic"]["disqualifying_state"] == "ios_power_off_screen"
    assert actions[0]["semantic"]["retry_allowed"] is False
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert groups[-1]["group_status"] == "blocked"
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert not any(event["type"] == "semantic_plan.strategy_failed" for event in audit)
    assert not any(event["type"] == "semantic_plan.recovery.started" for event in audit)


@pytest.mark.smoke
def test_computer_use_runtime_semantic_plan_exception_terminates_without_switch(tmp_path):
    recoveries = []
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"]],
    )
    orchestrator.recovery_policy = RuntimeRecoveryPolicy(
        lambda _phone, reason, _payload: recoveries.append(reason) or True,
        max_attempts=1,
    )
    calls: list[str] = []

    def boom():
        calls.append("first_tap")
        raise RuntimeError("semantic strategy boom")

    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery="recover_to_home_then_renavigate",
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], boom),
            BoundStrategy(
                spec.strategies[1],
                lambda: pytest.fail("exception should terminate before second strategy"),
            ),
        ],
    )

    with pytest.raises(RuntimeError, match="semantic strategy boom"):
        phone._execute_action("tap", plan)
    orchestrator.close()

    assert calls == ["first_tap"]
    assert recoveries == []
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    assert actions[0]["status"] == "exception"
    assert actions[0]["semantic"]["status"] == "exception"
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert groups[-1]["group_status"] == "exception"
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(event["type"] == "action.exception" for event in audit)
    assert not any(event["type"] == "semantic_plan.strategy_failed" for event in audit)
    assert not any(event["type"] == "semantic_plan.recovery.started" for event in audit)


@pytest.mark.smoke
def test_computer_use_runtime_shares_vlm_action_budget_across_strategy_switches(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"]] * 8,
    )
    phone.kimi = object()
    describe_calls = []

    def describe(scene_hint=None):
        describe_calls.append(scene_hint)
        return phone._last_scene

    phone.describe = describe
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("first_tap"), StrategySpec("second_tap")),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(
        spec,
        [
            BoundStrategy(spec.strategies[0], lambda: phone.effector.home()),
            BoundStrategy(spec.strategies[1], lambda: phone.effector.home()),
        ],
    )

    result = phone._execute_action("tap", plan, max_vlm_calls_per_action=1)
    orchestrator.close()

    assert result.semantic_status == "failed"
    assert describe_calls == ["expected_state:visible_text"]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 2
    assert actions[0]["command"]["vlm_calls"] == 1
    assert actions[1]["command"]["vlm_calls"] == 1
    assert actions[1]["command"]["vlm_budget_exhausted"] is True


@pytest.mark.smoke
def test_computer_use_runtime_stuck_detector_recovers_after_repeated_failure(tmp_path):
    recoveries = []

    def recover(_phone, reason, payload):
        recoveries.append((reason, payload["recovery"]))
        return True

    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(recover, max_attempts=1),
        stuck_detector=StuckLoopDetector(threshold=2),
    )
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["主屏幕"]] * 12),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    first = phone.control_center()
    second = phone.control_center()
    third = phone.control_center()
    orchestrator.close()

    assert first.semantic_status == "failed"
    assert second.semantic_status == "failed"
    assert third.semantic_status == "failed"
    assert recoveries == [("required semantic markers were absent", "recover_to_home_then_renavigate")]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    observed = [event for event in audit if event["type"] == "stuck_detector.observed"]
    assert [event["payload"]["count"] for event in observed] == [1, 2, 3]
    assert sum(1 for event in audit if event["type"] == "stuck_detector.recovery.started") == 1
    assert sum(1 for event in audit if event["type"] == "stuck_detector.recovery.finished") == 1


@pytest.mark.smoke
def test_computer_use_runtime_failed_recovery_rearms_then_bounds_attempts(tmp_path):
    """CUQ-0.9: a recovery that does not recover re-arms the detector so the
    dead-end fires again, but only up to a bounded budget -- after which a
    terminal 'unrecoverable' marker is emitted instead of looping forever."""
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(lambda *_a: False, max_attempts=1),
        stuck_detector=StuckLoopDetector(threshold=2),
        max_stuck_recoveries=2,
    )
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["主屏幕"]] * 20),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    for _ in range(8):
        phone.control_center()
    orchestrator.close()

    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    started = sum(1 for e in audit if e["type"] == "stuck_detector.recovery.started")
    unrecoverable = [e for e in audit if e["type"] == "stuck_detector.unrecoverable"]
    # Fires at count 2; failed recovery re-arms; fires again at the 2nd budget
    # slot; budget (2) exhausted -> unrecoverable, no further recovery attempts.
    assert started == 2
    assert len(unrecoverable) == 1
    assert unrecoverable[0]["payload"]["recovery_failures"] == 2


@pytest.mark.smoke
def test_computer_use_runtime_success_clears_stuck_detector_progress(tmp_path):
    recoveries = []
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(
            lambda _phone, reason, payload: recoveries.append((reason, payload["recovery"])) or True,
            max_attempts=1,
        ),
        stuck_detector=StuckLoopDetector(threshold=2),
    )
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["主屏幕"]] * 12),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("noop"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["主屏幕"]}),
        recovery=None,
        idempotent=True,
    )
    plan = SemanticActionPlan(spec, [BoundStrategy(spec.strategies[0], lambda: ActionResult(ok=True, backend="test", connected=True))])

    first = phone.control_center()
    progress = phone._execute_action("tap", plan)
    second = phone.control_center()
    orchestrator.close()

    assert first.semantic_status == "failed"
    assert progress.semantic_status == "succeeded"
    assert second.semantic_status == "failed"
    assert recoveries == []
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    observed = [event for event in audit if event["type"] == "stuck_detector.observed"]
    assert [event["payload"]["count"] for event in observed] == [1, 1]


@pytest.mark.smoke
def test_computer_use_runtime_represents_transport_ok_semantic_failure(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"]],
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "failed"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["command_result"]["transport_ok"] is True
    assert actions[0]["semantic"]["status"] == "failed"
    assert "required semantic markers" in actions[0]["semantic"]["reason"]


@pytest.mark.smoke
def test_computer_use_runtime_can_fail_fast_on_semantic_failure(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"]],
        semantic_fail_fast=True,
    )

    with pytest.raises(RuntimeError, match="semantic failed"):
        phone.control_center()
    orchestrator.close()

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["command_result"]["transport_ok"] is True
    assert actions[0]["semantic"]["status"] == "failed"


@pytest.mark.smoke
def test_computer_use_runtime_disqualifying_state_suppresses_retry(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["滑动来关机", "SOS"]],
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "blocked"  # CUQ-3.19: power-off is a safety stop
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["semantic"]["disqualifying_state"] == "ios_power_off_screen"
    assert actions[0]["semantic"]["retry_allowed"] is False
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "disqualifying_state.detected" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_recents_home_unexpected_suppresses_retry(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["主屏幕"], ["天气", "日历", "照片", "App Store"]],
    )
    phone.perceive_cache_diff = 0.0

    result = phone._execute_action(
        "recents",
        lambda: phone.effector.recents(),
        retry_budget=1,
    )
    orchestrator.close()

    assert result.semantic_status == "failed"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert len(actions) == 1
    assert actions[0]["semantic"]["disqualifying_state"] == "ios_home_unexpected"
    assert actions[0]["semantic"]["retry_allowed"] is False
    assert groups[0]["retry_count"] == 0
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "disqualifying_state.detected" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_permission_dialog_semantic_requires_approval(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["想要访问您的照片", "不允许", "允许访问"]],
    )

    result = phone._execute_action(
        "tap",
        lambda: phone.effector.tap(10, 10),
        x=10,
        y=10,
        idempotent=True,
        retry_budget=1,
    )
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "approval_required"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert len(actions) == 1
    assert actions[0]["semantic"]["disqualifying_state"] == "ios_system_permission_dialog"
    assert actions[0]["semantic"]["retry_allowed"] is False
    assert groups[0]["retry_count"] == 0
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "disqualifying_state.detected" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_transport_failure_is_transport_failed(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"]],
        connected=False,
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.ok is False
    assert result.semantic_status == "transport_failed"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["after"] is None
    assert actions[0]["semantic"]["verification_skipped"] is False
    assert actions[0]["command_result"]["transport_ok"] is False
    assert result.semantic_verification_skipped is False


@pytest.mark.smoke
def test_computer_use_runtime_command_exception_closes_attempt_and_group(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["主屏幕"]],
    )

    with pytest.raises(RuntimeError, match="boom"):
        phone._execute_action("key", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    orchestrator.close()

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert actions[0]["status"] == "exception"
    assert actions[0]["semantic"]["status"] == "exception"
    assert actions[0]["semantic"]["reason"] == "command raised RuntimeError: boom"
    assert groups[0]["group_status"] == "exception"
    assert groups[0]["attempt_ids"] == ["act_000000"]
    assert any(e["type"] == "action.exception" for e in audit)
    assert any(e["type"] == "attempt_group.finished" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_verifier_exception_closes_attempt_and_group(tmp_path):
    class RaisingVerifier:
        name = "raising_verifier"
        version = "test"
        success_markers = ()

        def verify(self, input):
            del input
            raise RuntimeError("verifier boom")

    from glassbox.verification.registry import VerifierRegistry

    registry = VerifierRegistry()
    registry.register(RaisingVerifier())
    registry.map_action("control_center", "raising_verifier")
    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store, registry=registry)
    phone = Phone(
        source=_Source(),
        ocr=_OCR([["主屏幕"], ["主屏幕"], ["主屏幕"], ["勿扰模式"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    with pytest.raises(RuntimeError, match="verifier boom"):
        phone.control_center()
    orchestrator.close()

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert actions[0]["status"] == "exception"
    assert actions[0]["semantic"]["reason"] == "verifier raised RuntimeError: verifier boom"
    assert actions[0]["after"] is not None
    assert groups[0]["group_status"] == "exception"
    assert any(e["type"] == "verifier.started" for e in audit)
    assert any(e["type"] == "verifier.finished" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_unexpected_escape_finalizes_group_interrupted(tmp_path, monkeypatch):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"]],
    )

    def explode(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("orchestrator escaped")

    monkeypatch.setattr(orchestrator, "_run_attempt", explode)

    with pytest.raises(RuntimeError, match="orchestrator escaped"):
        phone.control_center()
    orchestrator.close()

    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert groups[0]["group_status"] == "interrupted"
    assert groups[0]["attempt_ids"] == ["act_000000"]
    assert any(e["type"] == "attempt_group.interrupted" for e in audit)
    assert any(e["type"] == "attempt_group.finished" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_preflight_records_missing_video(tmp_path):
    class FirstSnapshotMissing(_Source):
        def snapshot(self):
            if self.count == 0:
                self.count += 1
                return None
            return super().snapshot()

    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=FirstSnapshotMissing(),
        ocr=_OCR([["主屏幕"], ["勿扰模式"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    manifest = json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["preflight"]["status"] == "failed"
    assert manifest["preflight"]["error"] == "no video frame captured"
    assert manifest["preflight"]["recovery"]["attempted"] is False


@pytest.mark.smoke
def test_computer_use_runtime_preflight_recovery_hook_can_recover_missing_video(tmp_path):
    class RecoverableSource(_Source):
        def __init__(self):
            super().__init__()
            self.recovered = False

        def snapshot(self):
            if not self.recovered:
                return None
            return super().snapshot()

    source = RecoverableSource()
    recovery_calls: list[str] = []

    def recover(phone, reason, payload):
        del phone, payload
        recovery_calls.append(reason)
        source.recovered = True
        return True

    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(
        store,
        recovery_policy=RuntimeRecoveryPolicy(recover, max_attempts=1),
    )
    phone = Phone(
        source=source,
        ocr=_OCR([["主屏幕"], ["主屏幕"], ["勿扰模式"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert recovery_calls == ["no video frame captured"]
    manifest = json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["preflight"]["status"] == "passed"
    assert manifest["preflight"]["recovery"]["recovered"] is True
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "run.recovery.started" for e in audit)
    assert any(e["type"] == "run.recovery.finished" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_preflight_detects_lock_screen(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["输入密码", "Face ID"], ["主屏幕"], ["勿扰模式"]],
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    manifest = json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["preflight"]["status"] == "failed"
    assert manifest["preflight"]["disqualifying_state"] == "ios_lock_screen"
    assert manifest["preflight"]["recovery"]["attempted"] is False


@pytest.mark.smoke
def test_computer_use_runtime_guarded_policy_blocks_high_risk_action(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["密码"]],
        guarded=True,
    )

    result = phone.type("password", verify=False)
    orchestrator.close()

    assert result.ok is False
    assert result.semantic_status == "blocked"
    assert phone.effector.actions == []
    approvals = _read_jsonl(store.run_dir / "approvals.jsonl")
    assert approvals[0]["decision"] == "denied"
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "approval.requested" for e in audit)
    assert any(e["type"] == "approval.denied" for e in audit)
    assert next(e for e in audit if e["type"] == "approval.denied")["actor"] == "runtime"


@pytest.mark.smoke
def test_computer_use_runtime_records_approved_high_risk_action(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["密码"], ["密码"], ["password"]],
        guarded=True,
    )

    result = phone._execute_action(
        "type",
        lambda: phone.effector.type("password"),
        text="password",
        approved=True,
        approved_by="human",
    )
    orchestrator.close()

    assert result.ok is True
    approvals = _read_jsonl(store.run_dir / "approvals.jsonl")
    assert approvals[0]["decision"] == "approved"
    assert approvals[0]["decided_by"] == "human"
    assert approvals[0]["run_id"] == "run"
    assert approvals[0]["requested_at"]
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["before_requested"]["frame_id"] != actions[0]["before_command"]["frame_id"]
    frame_roles = [
        e["payload"]["observation_role"]
        for e in _read_jsonl(store.run_dir / "audit.jsonl")
        if e["type"] == "frame.captured"
    ]
    assert "before_command" in frame_roles
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "approval.approved" for e in audit)
    assert next(e for e in audit if e["type"] == "approval.approved")["actor"] == "human"


@pytest.mark.smoke
def test_computer_use_runtime_retries_unknown_idempotent_attempts(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["输入框"], ["输入框"], ["输入框"], ["abc"]],
    )

    result = phone._execute_action(
        "type",
        lambda: phone.effector.type("abc"),
        text="abc",
        idempotent=True,
        retry_budget=1,
    )
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert [a["attempt_id"] for a in actions] == ["act_000000", "act_000001"]
    assert actions[0]["semantic"]["status"] == "unknown"
    assert actions[1]["semantic"]["status"] == "succeeded"
    groups = _read_jsonl(store.run_dir / "attempt_groups.jsonl")
    assert groups[0]["attempt_ids"] == ["act_000000", "act_000001"]
    assert groups[0]["retry_count"] == 1
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "action.retry_scheduled" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_unknown_policy_fail_raises_after_recording(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["输入框"], ["输入框"]],
    )

    with pytest.raises(RuntimeError, match="semantic unknown"):
        phone._execute_action(
            "type",
            lambda: phone.effector.type("abc"),
            text="abc",
            unknown_policy="fail",
        )
    orchestrator.close()

    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["semantic"]["status"] == "unknown"
    assert actions[0]["observation"]["settle_strategy"] == "stable_after"


@pytest.mark.smoke
def test_computer_use_runtime_records_crawler_actor(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["勿扰模式"]],
    )

    phone._execute_action(
        "control_center",
        lambda: phone.effector.control_center(),
        actor="crawler",
    )
    orchestrator.close()

    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert action["actor"] == "crawler"
    assert next(e for e in audit if e["type"] == "action.started")["actor"] == "crawler"


@pytest.mark.smoke
def test_computer_use_runtime_no_after_is_verification_skipped(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"]],
    )

    result = phone._execute_action(
        "key",
        lambda: phone.effector.key(0, 0),
        modifier=0,
        keycode=0,
        settle_strategy="no_after",
    )
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "no_after_scene"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["after"] is None
    assert actions[0]["semantic"]["verification_skipped"] is True
    assert actions[0]["semantic"]["reason"] == "GUI verification skipped by no_after strategy"
    assert result.semantic_verification_skipped is True


@pytest.mark.smoke
def test_computer_use_runtime_stream_until_match_records_observation_hit(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["主屏幕"], ["动画中"], ["勿扰模式"]],
    )
    phone.perceive_cache_diff = 0.0

    result = phone._execute_action(
        "control_center",
        lambda: phone.effector.control_center(),
        settle_strategy="stream_until_match",
        stream_timeout_ms=500,
        sample_interval_ms=1,
        max_stream_frames=4,
    )
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    assert action["observation"]["after_mode"] == "window"
    assert action["observation"]["matched_by_observation"]["kind"] == "success_marker"
    assert action["observation"]["matched_by_observation"]["matched_evidence"] == ["勿扰模式"]
    assert action["observation"]["sample_interval_ms"] == 1
    assert action["observation"]["timeout_ms"] == 500
    assert action["observation"]["max_frames"] == 4
    assert action["observation"]["frame_count"] == 2
    assert action["observation"]["frame_ids"] == [item["frame_id"] for item in action["after_window"]]
    assert action["observation"]["scene_ids"] == [item["scene_id"] for item in action["after_window"]]
    assert action["semantic"]["observation_match"]["kind"] == "success_marker"
    assert len(action["after_window"]) == 2
    assert action["after_window"][-1]["screenshot"].startswith("frames/")
    assert (store.run_dir / action["after_window"][-1]["screenshot"]).exists()
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "observation.match_found" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_stream_until_match_can_use_expected_visible_metadata(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["主屏幕"], ["Loading"], ["Done"]],
    )
    phone.perceive_cache_diff = 0.0

    result = phone._execute_action(
        "swipe",
        lambda: phone.effector.home(),
        settle_strategy="stream_until_match",
        expect_visible="Done",
        stream_timeout_ms=500,
        sample_interval_ms=1,
        max_stream_frames=4,
    )
    orchestrator.close()

    assert result.ok is True
    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    assert action["observation"]["matched_by_observation"]["kind"] == "expected_visible"
    assert action["observation"]["matched_by_observation"]["matched_evidence"] == ["Done"]
    assert action["observation"]["frame_count"] == 2
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "observation.match_found" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_stream_until_match_stops_on_disqualifying_state(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["主屏幕"], ["滑动来关机", "SOS"], ["勿扰模式"]],
    )
    phone.perceive_cache_diff = 0.0

    result = phone._execute_action(
        "control_center",
        lambda: phone.effector.control_center(),
        settle_strategy="stream_until_match",
        stream_timeout_ms=500,
        sample_interval_ms=1,
        max_stream_frames=4,
    )
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "blocked"  # CUQ-3.19: power-off is a safety stop
    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    assert action["semantic"]["disqualifying_state"] == "ios_power_off_screen"
    assert action["semantic"]["retry_allowed"] is False
    assert action["observation"]["matched_by_observation"]["kind"] == "disqualifying_state"
    assert action["observation"]["matched_by_observation"]["state"] == "ios_power_off_screen"
    assert action["observation"]["frame_count"] == 1
    assert action["semantic"]["observation_match"]["kind"] == "disqualifying_state"
    assert len(action["after_window"]) == 1
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "observation.disqualifying_state_found" for e in audit)
    assert any(e["type"] == "disqualifying_state.detected" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_fixed_delay_after_records_timing_contract(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["勿扰模式"]],
    )

    result = phone._execute_action(
        "control_center",
        lambda: phone.effector.control_center(),
        settle_strategy="fixed_delay_after",
        fixed_delay_ms=1,
    )
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    assert action["observation"]["after_mode"] == "single_frame"
    assert action["observation"]["fixed_delay_ms"] == 1
    assert action["observation"]["frame_count"] == 1
    assert action["observation"]["duration_ms"] >= 0


@pytest.mark.smoke
def test_computer_use_runtime_records_stability_metadata(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["勿扰模式"], ["勿扰模式"]],
    )
    phone.stability_policy = StabilityPolicy(
        enabled=True,
        timeout=0.2,
        diff_threshold=1.0,
        consecutive=1,
        poll_interval=0.001,
    )

    phone.control_center()
    orchestrator.close()

    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    assert action["observation"]["settle_strategy"] == "stable_after"
    assert action["observation"]["stability_score"] == 1.0
    assert action["observation"]["stable_policy"]["consecutive"] == 1


@pytest.mark.smoke
def test_computer_use_runtime_after_observation_failure_is_unknown(tmp_path):
    class RaisingAfterOCR(_OCR):
        def recognize(self, image):
            if self.index >= 2:
                raise RuntimeError("ocr unavailable")
            return super().recognize(image)

    store = ArtifactStore(tmp_path, run_id="run")
    orchestrator = ActionOrchestrator(store)
    phone = Phone(
        source=_Source(),
        ocr=RaisingAfterOCR([["主屏幕"], ["主屏幕"]]),
        effector=MockEffector(),
        action_orchestrator=orchestrator,
        action_fail_fast=False,
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "no_after_scene"
    action = _read_jsonl(store.run_dir / "actions.jsonl")[0]
    assert action["after"] is None
    assert action["semantic"]["reason"] == "after observation captured no frames"
    assert result.semantic_verification_skipped is False
    audit = _read_jsonl(store.run_dir / "audit.jsonl")
    assert any(e["type"] == "after_observation.failed" for e in audit)


@pytest.mark.smoke
def test_computer_use_runtime_open_app_is_single_outer_semantic_action(tmp_path, monkeypatch):
    import glassbox.ios.springboard as springboard

    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["设置"]],
    )

    def fake_open_app(inner_phone, labels, **kwargs):
        del kwargs
        assert inner_phone is phone
        assert labels == ("Settings", "设置")
        assert inner_phone.action_orchestrator is None
        return True

    monkeypatch.setattr(springboard, "open_app_from_springboard", fake_open_app)

    result = phone.open_app("Settings", aliases=("设置",))
    orchestrator.close()

    assert result.ok is True
    assert result.semantic_status == "succeeded"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert len(actions) == 1
    assert actions[0]["op"] == "open_app"
    assert actions[0]["semantic"]["verifier"] == "foreground_app_matches"


@pytest.mark.smoke
def test_computer_use_runtime_summary_trace_keeps_ledger_without_png_frames(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["勿扰模式"]],
        trace_level="summary",
    )

    result = phone.control_center()
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    assert list((store.run_dir / "frames").glob("*.png")) == []
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    assert actions[0]["before_requested"]["frame_id"] == "frm_000000"
    assert actions[0]["before_requested"]["screenshot"] is None
    scene_payload = json.loads((store.run_dir / actions[0]["after"]["scene"]).read_text())
    assert scene_payload["texts"] == ["勿扰模式"]


@pytest.mark.smoke
def test_computer_use_runtime_action_can_raise_trace_level(tmp_path):
    phone, orchestrator, store = _make_phone(
        tmp_path,
        [["主屏幕"], ["主屏幕"], ["勿扰模式"]],
        trace_level="summary",
    )

    result = phone._execute_action(
        "control_center",
        lambda: phone.effector.control_center(),
        trace_level="full",
    )
    orchestrator.close()

    assert result.semantic_status == "succeeded"
    manifest = json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trace_level"] == "summary"
    actions = _read_jsonl(store.run_dir / "actions.jsonl")
    action = actions[0]
    assert action["observation"]["trace_level"] == "full"
    assert action["before_requested"]["screenshot"].startswith("frames/")
    assert action["before_command"]["screenshot"].startswith("frames/")
    assert action["after"]["screenshot"].startswith("frames/")
    scene_payload = json.loads((store.run_dir / action["after"]["scene"]).read_text())
    assert "elements" in scene_payload


@pytest.mark.smoke
def test_idempotent_retry_budget_enables_unknown_retry_only_for_safe_ops(tmp_path):
    """CUQ-0.11: with an opt-in idempotent_retry_budget, an op declared idempotent
    (home / scroll_wheel / ...) gets a semantic retry budget so an `unknown`
    verdict actually retries; non-idempotent ops (tap) stay at 0. Default budget 0
    keeps the unknown->retry policy a no-op (byte-identical)."""
    store = ArtifactStore(tmp_path, run_id="run")

    # Budget enabled.
    orch = ActionOrchestrator(store, idempotent_retry_budget=2)
    home_md = orch._action_metadata("home", {})
    assert home_md["idempotent"] is True
    assert home_md["retry_budget"] == 2
    assert home_md["unknown_policy"] == "retry"

    tap_md = orch._action_metadata("tap", {})
    assert tap_md["idempotent"] is False
    assert tap_md["retry_budget"] == 0
    assert tap_md["unknown_policy"] == "continue"
    orch.close()

    # Default (budget 0): even an idempotent op gets no retry -> policy no-op.
    orch0 = ActionOrchestrator(ArtifactStore(tmp_path / "d0", run_id="run"))
    home0 = orch0._action_metadata("home", {})
    assert home0["idempotent"] is True
    assert home0["retry_budget"] == 0
    assert home0["unknown_policy"] == "continue"
    orch0.close()


@pytest.mark.smoke
def test_tap_text_routes_through_plan_without_recursion_when_flagged(tmp_path):
    """CUQ-0.1: with `tap` flagged, the top-level tap_text routes through the
    strategy ladder exactly ONCE; the ladder's target_tap strategy (which calls
    back into tap_text) actuates in place under the _in_semantic_plan guard
    instead of re-routing — proving the recursion is broken."""
    phone, orchestrator, _store = _make_phone(tmp_path, [["Done"]] * 8)
    phone._semantic_plan_ops = frozenset({"tap"})

    runs = {"n": 0}
    original = phone._run_semantic_plan

    def spy(op, **kw):
        runs["n"] += 1
        return original(op, **kw)

    phone._run_semantic_plan = spy
    result = phone.tap_text("Done")
    orchestrator.close()

    assert result is not None
    assert runs["n"] == 1  # top-level routed once; nested target_tap did NOT re-route
    assert phone._in_semantic_plan is False  # guard restored after the plan


@pytest.mark.smoke
def test_in_semantic_plan_guard_skips_legacy_stuck_recovery(tmp_path):
    """CUQ-0.1: a NESTED legacy actuation (a strategy ladder calling tap_text /
    swipe_up) runs with _in_semantic_plan set, and the legacy execute path must
    then SKIP stuck recovery — so a nested actuation can't fire a Home reset in
    the middle of the ladder. Off (default) the legacy path recovers as before."""
    phone, orchestrator, _store = _make_phone(tmp_path, [["Done"]] * 4)
    calls = {"n": 0}
    original = orchestrator._maybe_recover_stuck

    def spy(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    orchestrator._maybe_recover_stuck = spy

    def ok_call():
        return ActionResult(ok=True, backend="test", connected=True)

    # Default (not in a plan): the legacy path reaches the recovery check.
    phone._in_semantic_plan = False
    phone._execute_action("tap", ok_call)
    assert calls["n"] == 1

    # In a plan (nested actuation): the legacy path skips recovery.
    calls["n"] = 0
    phone._in_semantic_plan = True
    phone._execute_action("tap", ok_call)
    orchestrator.close()
    assert calls["n"] == 0


@pytest.mark.smoke
def test_recover_then_retry_reattempts_after_successful_recovery(tmp_path):
    """CUQ-0.12: with recover_then_retry on, a failed action whose stuck recovery
    SUCCEEDS is re-attempted once from the recovered state — so recovery alters
    the current action's outcome, not just the next one. Re-entrancy-guarded."""
    phone, orchestrator, _store = _make_phone(tmp_path, [["停滞"]] * 8)
    orchestrator._recover_then_retry = True
    # Force recovery to report success so the retry branch is exercised.
    orchestrator._maybe_recover_stuck = lambda _p, _final, *, group_id: True

    calls = {"n": 0}

    def static_call():
        calls["n"] += 1  # lands, but the scene never progresses -> semantic "unknown"
        return ActionResult(ok=True, backend="test", connected=True)

    phone._execute_action("tap", static_call)
    orchestrator.close()

    assert calls["n"] == 2  # initial attempt + one post-recovery retry (then guarded)


@pytest.mark.smoke
def test_recover_then_retry_off_does_not_reattempt(tmp_path):
    """CUQ-0.12 default-safety: with the flag off (default), a successful recovery
    does NOT re-attempt — byte-identical to before (recovery primes the next)."""
    phone, orchestrator, _store = _make_phone(tmp_path, [["停滞"]] * 8)
    assert orchestrator._recover_then_retry is False
    orchestrator._maybe_recover_stuck = lambda _p, _final, *, group_id: True

    calls = {"n": 0}

    def static_call():
        calls["n"] += 1
        return ActionResult(ok=True, backend="test", connected=True)

    phone._execute_action("tap", static_call)
    orchestrator.close()

    assert calls["n"] == 1  # no retry on the default path
