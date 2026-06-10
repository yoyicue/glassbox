from __future__ import annotations

import pytest

from glassbox.action import (
    BoundStrategy,
    ExpectedState,
    SemanticActionPlan,
    SemanticActionSpec,
    StrategySpec,
    default_semantic_action_plan,
    default_semantic_action_spec,
    verify_expected_state,
)
from glassbox.cognition import Box, Scene, UIElement
from glassbox.effector import ActionResult
from glassbox.verification.verifiers import SemanticOutcome


def _ok() -> ActionResult:
    return ActionResult(ok=True, backend="test", connected=True)


def _outcome(status: str) -> SemanticOutcome:
    return SemanticOutcome(
        status=status,
        verifier="test",
        reason=status,
        confidence=1.0 if status == "succeeded" else 0.5,
    )


def _spec(*, idempotent: bool = True, recovery: str | None = "recover_to_home_then_renavigate"):
    return SemanticActionSpec(
        op="home",
        strategies=(
            StrategySpec("keyboard_combo", capability="home", reliability_rank=30),
            StrategySpec("assistive_touch_home", capability="assistive_touch", reliability_rank=20),
        ),
        expected_state=ExpectedState("page_id", {"page_id": "home"}),
        recovery=recovery,
        idempotent=idempotent,
    )


def _plan(spec: SemanticActionSpec, calls: list[str] | None = None) -> SemanticActionPlan:
    calls = [] if calls is None else calls

    def bind(strategy: StrategySpec):
        return lambda strategy=strategy: calls.append(strategy.name) or _ok()

    return SemanticActionPlan.bind(spec, bind)


def test_semantic_action_spec_round_trips_json_dict():
    spec = _spec()

    loaded = SemanticActionSpec.from_dict(spec.to_dict())

    assert loaded == spec
    assert loaded.to_dict()["strategies"][0]["name"] == "keyboard_combo"


def test_default_specs_exist_for_core_action_entrypoints():
    expected = ExpectedState("visible_text", {"any_of": ["设置"]})

    for op in ("home", "back", "launch_app", "tap", "scroll"):
        spec = default_semantic_action_spec(op, expected)
        assert spec.op == op
        assert spec.strategies
        assert spec.to_dict()["expected_state"] == expected.to_dict()


def test_default_semantic_action_plan_binds_core_phone_entrypoints():
    calls: list[tuple] = []

    class Effector:
        def home(self):
            calls.append(("home",))
            return _ok()

        def key(self, modifier, keycode):
            calls.append(("key", modifier, keycode))
            return _ok()

        def tap(self, x, y):
            calls.append(("tap", x, y))
            return _ok()

        def scroll_wheel(self, ticks, *, horizontal=0):
            calls.append(("scroll_wheel", ticks, horizontal))
            return _ok()

    class PhoneLike:
        effector = Effector()

        def _to_phone(self, x, y):
            return x + 10, y + 20

        def to_phone_coordinates(self, x, y):
            return self._to_phone(x, y)

        def _picokvm_back_context(self):
            return True, None, (1, 2)

        def picokvm_back_context(self):
            return self._picokvm_back_context()

        def open_app(self, label, *, aliases=(), max_pages=8, settle_s=0.8):
            calls.append(("open_app", label, aliases, max_pages, settle_s))
            return _ok()

        def tap_text(self, target):
            calls.append(("tap_text", target))
            return _ok()

        def _home_via_assistive_touch_menu(self):
            calls.append(("assistive_touch_home",))
            return _ok()

        def home_via_assistive_touch_menu(self):
            return self._home_via_assistive_touch_menu()

        def close_foreground_app(self):
            calls.append(("close_foreground_app",))
            return _ok()

    phone = PhoneLike()
    expected = ExpectedState("visible_text", {"any_of": ["Done"]})
    cases = [
        ("home", {}, ("home",)),
        ("back", {}, ("tap", 11, 22)),
        ("launch_app", {"app": "Settings"}, ("open_app", "Settings", (), 8, 0.8)),
        ("tap", {"x": 4, "y": 5}, ("tap", 14, 25)),
        ("scroll", {"ticks": 7}, ("scroll_wheel", 7, 0)),
    ]

    for op, params, expected_call in cases:
        calls.clear()
        plan = default_semantic_action_plan(phone, op, expected, **params)
        assert plan.spec.op == op
        assert len(plan.bound) == len(plan.spec.strategies)

        result = plan.bound[0].call()

        assert result.ok is True
        assert calls == [expected_call]


@pytest.mark.smoke
def test_tap_plan_target_strategy_preserves_runtime_element_tap_options():
    element = UIElement(type="text", box=Box(x=30, y=40, w=20, h=10), text="Bluetooth", confidence=0.95)
    expected_payload = {
        "kind": "page_id",
        "payload": {"any_of": ["settings/Bluetooth", "settings/蓝牙"]},
    }
    calls: list[dict] = []

    class PhoneLike:
        def tap_element(self, tapped_element, **kwargs):
            calls.append({"element": tapped_element, **kwargs})
            return _ok()

    plan = default_semantic_action_plan(
        PhoneLike(),
        "tap",
        ExpectedState.from_dict(expected_payload),
        element=element,
        intent="settings.row:Bluetooth",
        target="Bluetooth",
        via="settings.tap_row",
        tap_element_options={"retry_budget": 2, "idempotent": True},
        tap_element_expected_state=expected_payload,
    )

    assert plan.metadata()["semantic_action_spec"]["strategies"][0]["params"] == {
        "target": "Bluetooth"
    }
    assert plan.bound[0].call().ok is True
    assert calls == [
        {
            "element": element,
            "intent": "settings.row:Bluetooth",
            "target": "Bluetooth",
            "via": "settings.tap_row",
            "retry_budget": 2,
            "idempotent": True,
            "expected_state": expected_payload,
        }
    ]


@pytest.mark.smoke
def test_scroll_plan_ladder_is_direction_aware_wheel_then_swipe():
    """CUQ-0.1: the scroll plan ladders wheel -> swipe. The wheel sign follows the
    direction, and the swipe fallback uses the backend's preset gesture (down =
    reveal-content-below = swipe_up / +ticks)."""
    calls: list[tuple] = []

    class Effector:
        def scroll_wheel(self, ticks, *, horizontal=0):
            calls.append(("scroll_wheel", ticks, horizontal))
            return _ok()

    class PhoneLike:
        effector = Effector()

        def swipe_up(self):
            calls.append(("swipe_up",))
            return _ok()

        def swipe_down(self):
            calls.append(("swipe_down",))
            return _ok()

    phone = PhoneLike()
    expected = ExpectedState("visible_text", {"any_of": ["Done"]})

    # direction=down -> wheel positive ticks; swipe fallback = swipe_up
    calls.clear()
    down = default_semantic_action_plan(phone, "scroll", expected, direction="down", ticks=5)
    assert down.bound[0].call().ok  # wheel strategy
    assert down.bound[1].call().ok  # drag/swipe fallback strategy
    assert calls == [("scroll_wheel", 5, 0), ("swipe_up",)]

    # direction=up -> wheel negative ticks; swipe fallback = swipe_down
    calls.clear()
    up = default_semantic_action_plan(phone, "scroll", expected, direction="up", ticks=5)
    up.bound[0].call()
    up.bound[1].call()
    assert calls == [("scroll_wheel", -5, 0), ("swipe_down",)]


def test_default_semantic_action_plan_serializes_runtime_strategy_params():
    class Effector:
        def tap(self, _x, _y):
            return _ok()

        def scroll_wheel(self, _ticks, *, horizontal=0):
            del horizontal
            return _ok()

    class PhoneLike:
        effector = Effector()

        def _to_phone(self, x, y):
            return x, y

        def to_phone_coordinates(self, x, y):
            return self._to_phone(x, y)

        def open_app(self, *_args, **_kwargs):
            return _ok()

    expected = ExpectedState("visible_text", {"any_of": ["Done"]})

    launch = default_semantic_action_plan(
        PhoneLike(),
        "launch_app",
        expected,
        app="Settings",
        aliases=("设置", "Prefs"),
        max_pages=4,
        settle_s=0.25,
    )
    tap = default_semantic_action_plan(PhoneLike(), "tap", expected, x=4, y=5, label="Done")
    scroll = default_semantic_action_plan(
        PhoneLike(),
        "scroll",
        expected,
        ticks=7,
        horizontal=1,
        x1=1,
        y1=2,
        x2=3,
        y2=4,
    )

    launch_params = launch.metadata()["semantic_action_spec"]["strategies"][0]["params"]
    tap_params = tap.metadata()["semantic_action_spec"]["strategies"][0]["params"]
    scroll_params = scroll.metadata()["semantic_action_spec"]["strategies"][0]["params"]

    assert launch_params == {
        "app": "Settings",
        "aliases": ["设置", "Prefs"],
        "max_pages": 4,
        "settle_s": 0.25,
    }
    assert tap_params == {"x": 4, "y": 5, "label": "Done"}
    assert scroll_params == {"ticks": 7, "horizontal": 1, "x1": 1, "y1": 2, "x2": 3, "y2": 4}


def test_default_semantic_action_plan_accepts_expected_state_dict():
    class Effector:
        def tap(self, _x, _y):
            return _ok()

    class PhoneLike:
        effector = Effector()

        def to_phone_coordinates(self, x, y):
            return x, y

    expected = {"kind": "page_id", "payload": {"page_id": "settings/Bluetooth"}}

    plan = default_semantic_action_plan(PhoneLike(), "tap", expected, x=4, y=5)

    assert plan.metadata()["semantic_action_spec"]["expected_state"] == expected


def test_runner_switches_to_next_strategy_on_failed_expected_state():
    calls: list[str] = []
    plan = _plan(_spec(), calls)
    outcomes = iter([_outcome("failed"), _outcome("succeeded")])

    run = plan.run(lambda *_args: next(outcomes))

    assert run.succeeded is True
    assert calls == ["keyboard_combo", "assistive_touch_home"]
    assert run.strategy_switches == 1
    assert run.attempts[1].strategy == "assistive_touch_home"


def test_runner_treats_partial_as_failed_and_switches_strategy():
    calls: list[str] = []
    plan = _plan(_spec(), calls)
    outcomes = iter([_outcome("partial"), _outcome("succeeded")])

    run = plan.run(lambda *_args: next(outcomes))

    assert run.succeeded is True
    assert calls == ["keyboard_combo", "assistive_touch_home"]
    assert run.attempts[0].semantic.status == "partial"
    assert run.attempts[0].edge == "switch"
    assert run.attempts[0].switched_reason == "expected_state_unmet"
    assert run.strategy_switches == 1


def test_runner_runs_recovery_after_strategy_exhaustion_once():
    calls: list[str] = []
    recoveries: list[str] = []
    plan = _plan(
        SemanticActionSpec(
            op="back",
            strategies=(StrategySpec("keyboard_back"),),
            expected_state=ExpectedState("visible_text", {"any_of": ["Settings"]}),
            recovery="recover_to_home_then_renavigate",
            idempotent=True,
        ),
        calls,
    )
    outcomes = iter([_outcome("failed"), _outcome("succeeded")])

    run = plan.run(
        lambda *_args: next(outcomes),
        recover=lambda name, _expected: recoveries.append(name) or True,
    )

    assert run.succeeded is True
    assert run.recovered is True
    assert recoveries == ["recover_to_home_then_renavigate"]
    assert calls == ["keyboard_back", "keyboard_back"]


def test_runner_does_not_recover_non_idempotent_action():
    plan = _plan(
        SemanticActionSpec(
            op="tap",
            strategies=(StrategySpec("target_tap"),),
            expected_state=ExpectedState("element_appears", {"text": "Done"}),
            recovery="recover_to_home_then_renavigate",
            idempotent=False,
        )
    )

    run = plan.run(lambda *_args: _outcome("failed"), recover=lambda *_args: True)

    assert run.succeeded is False
    assert run.terminal_reason == "not_idempotent"
    assert run.recovered is False


def test_runner_retries_same_strategy_for_transport_failure_before_switching():
    calls: list[str] = []
    plan = _plan(_spec(), calls)
    outcomes = iter([_outcome("transport_failed"), _outcome("succeeded")])

    run = plan.run(lambda *_args: next(outcomes), transport_retry_budget=1)

    assert run.succeeded is True
    assert calls == ["keyboard_combo", "keyboard_combo"]
    assert run.strategy_switches == 0


def test_runner_does_not_retry_transport_failure_for_non_idempotent_action():
    calls: list[str] = []
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("element_appears", {"text": "Done"}),
        recovery=None,
        idempotent=False,
    )
    plan = _plan(spec, calls)

    run = plan.run(lambda *_args: _outcome("transport_failed"), transport_retry_budget=1)

    assert run.succeeded is False
    assert calls == ["target_tap"]
    assert run.attempts[0].edge == "retry_same"


def test_runner_terminates_on_blocked_without_switch_or_recovery():
    calls: list[str] = []
    recoveries: list[str] = []
    plan = _plan(_spec(), calls)

    run = plan.run(
        lambda *_args: _outcome("blocked"),
        recover=lambda name, _expected: recoveries.append(name) or True,
    )

    assert run.status == "blocked"
    assert run.terminal_reason == "blocked"
    assert calls == ["keyboard_combo"]
    assert recoveries == []


def test_runner_terminates_on_approval_required_without_switch_or_recovery():
    calls: list[str] = []
    recoveries: list[str] = []
    plan = _plan(_spec(), calls)

    run = plan.run(
        lambda *_args: _outcome("approval_required"),
        recover=lambda name, _expected: recoveries.append(name) or True,
    )

    assert run.status == "approval_required"
    assert run.terminal_reason == "approval_required"
    assert calls == ["keyboard_combo"]
    assert recoveries == []


def test_runner_converts_command_exception_to_terminal_exception_outcome():
    calls: list[str] = []
    spec = SemanticActionSpec(
        op="tap",
        strategies=(StrategySpec("target_tap"),),
        expected_state=ExpectedState("visible_text", {"any_of": ["Done"]}),
        recovery="recover_to_home_then_renavigate",
        idempotent=True,
    )

    def broken_call():
        calls.append("target_tap")
        raise RuntimeError("boom")

    plan = SemanticActionPlan(spec, [BoundStrategy(spec.strategies[0], broken_call)])

    run = plan.run(lambda *_args: _outcome("succeeded"), recover=lambda *_args: True)

    assert run.status == "exception"
    assert run.terminal_reason == "exception"
    assert calls == ["target_tap"]
    assert run.attempts[0].semantic.verifier == "semantic_action_plan"


def test_runner_terminates_on_disqualifying_state_without_switch_or_recovery():
    calls: list[str] = []
    recoveries: list[str] = []
    plan = _plan(_spec(), calls)

    def verify(*_args):
        return SemanticOutcome(
            status="failed",
            verifier="test",
            reason="power off screen",
            confidence=1.0,
            retry_allowed=False,
            disqualifying_state="ios_power_off_screen",
        )

    run = plan.run(
        verify,
        recover=lambda name, _expected: recoveries.append(name) or True,
    )

    assert run.status == "failed"
    assert run.terminal_reason == "blocked"
    assert run.attempts[0].edge == "terminate"
    assert calls == ["keyboard_combo"]
    assert recoveries == []


def test_runner_escalates_unknown_to_vlm_with_budget_then_switches():
    calls: list[str] = []
    plan = _plan(_spec(), calls)
    verify_outcomes = iter([_outcome("unknown"), _outcome("unknown")])
    vlm_outcomes = iter([_outcome("unknown")])

    run = plan.run(
        lambda *_args: next(verify_outcomes),
        escalate_vlm=lambda *_args: next(vlm_outcomes),
        vlm_budget_per_action=1,
    )

    assert run.succeeded is False
    assert calls == ["keyboard_combo", "assistive_touch_home"]
    assert run.vlm_calls == 1
    assert run.vlm_budget_exhausted is True


def test_runner_treats_no_after_scene_as_unknown_before_vlm_and_switch():
    calls: list[str] = []
    plan = _plan(_spec(), calls)
    verify_outcomes = iter([_outcome("no_after_scene"), _outcome("succeeded")])
    vlm_calls: list[tuple[str, int]] = []

    def escalate(_expected, _result, strategy, attempt_index):
        vlm_calls.append((strategy.name, attempt_index))
        return _outcome("no_after_scene")

    run = plan.run(
        lambda *_args: next(verify_outcomes),
        escalate_vlm=escalate,
        vlm_budget_per_action=1,
    )

    assert run.succeeded is True
    assert calls == ["keyboard_combo", "assistive_touch_home"]
    assert vlm_calls == [("keyboard_combo", 0)]
    assert run.vlm_calls == 1
    assert run.attempts[0].semantic.status == "no_after_scene"
    assert run.attempts[0].edge == "switch"
    assert run.attempts[0].switched_reason == "expected_state_unmet"


def test_bind_requires_one_callable_per_strategy():
    spec = _spec()

    with pytest.raises(ValueError):
        SemanticActionPlan(spec, [BoundStrategy(spec.strategies[0], _ok)])


def test_verify_expected_state_page_id_and_visible_text():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        page_id="settings/root",
        elements=[
            UIElement(type="text", box=Box(x=0, y=0, w=10, h=10), text="设置", confidence=0.95),
            UIElement(type="button", box=Box(x=0, y=10, w=10, h=10), text="通用", confidence=0.95),
        ],
    )

    assert (
        verify_expected_state(ExpectedState("page_id", {"page_id": "settings/root"}), scene).status
        == "succeeded"
    )
    assert (
        verify_expected_state(
            ExpectedState("page_id", {"any_of": ["settings/about", "settings/root"]}), scene
        ).status
        == "succeeded"
    )
    assert (
        verify_expected_state(ExpectedState("visible_text", {"any_of": ["通用"]}), scene).status
        == "succeeded"
    )
    assert (
        verify_expected_state(
            ExpectedState("visible_text", {"all_of": ["通用", "不存在"]}), scene
        ).status
        == "failed"
    )


def test_verify_expected_state_element_appears_and_gone():
    scene = Scene(
        frame_id=1,
        timestamp=0.0,
        elements=[
            UIElement(type="button", box=Box(x=0, y=0, w=10, h=10), text="完成", confidence=0.95),
        ],
    )

    assert verify_expected_state(ExpectedState("element_appears", {"role": "button", "text": "完成"}), scene).status == "succeeded"
    assert verify_expected_state(ExpectedState("element_gone", {"target_identity": {"role": "button", "text": "删除"}}), scene).status == "succeeded"
    assert verify_expected_state(ExpectedState("element_gone", {"target_identity": {"role": "button", "text": "完成"}}), scene).status == "failed"
