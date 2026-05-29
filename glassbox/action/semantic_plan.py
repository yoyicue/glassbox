"""Semantic action strategy plans.

This module is the runtime-neutral P2 foundation from
docs/design/computer_use_success_rate.md. Specs are JSON-serializable and can be
written into audit fixtures; bound plans attach callables at runtime and execute
the explicit verifier-outcome state machine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from glassbox.effector import ActionResult
from glassbox.verification.verifiers import SemanticOutcome

ExpectedStateKind = Literal["page_id", "visible_text", "element_appears", "element_gone"]
TerminalReason = Literal[
    "succeeded",
    "strategies_exhausted",
    "blocked",
    "approval_required",
    "exception",
    "not_idempotent",
]


@dataclass(frozen=True)
class ExpectedState:
    kind: ExpectedStateKind
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExpectedState:
        kind = str(payload.get("kind") or "")
        if kind not in {"page_id", "visible_text", "element_appears", "element_gone"}:
            raise ValueError(f"unsupported expected state kind: {kind!r}")
        raw_payload = payload.get("payload")
        return cls(kind=kind, payload=dict(raw_payload) if isinstance(raw_payload, Mapping) else {})


@dataclass(frozen=True)
class StrategySpec:
    name: str
    capability: str | None = None
    reliability_rank: int = 100
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "reliability_rank": self.reliability_rank,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StrategySpec:
        name = str(payload.get("name") or "")
        if not name:
            raise ValueError("strategy name is required")
        params = payload.get("params")
        return cls(
            name=name,
            capability=(
                str(payload["capability"])
                if payload.get("capability") is not None
                else None
            ),
            reliability_rank=int(payload.get("reliability_rank", 100) or 100),
            params=dict(params) if isinstance(params, Mapping) else {},
        )


@dataclass(frozen=True)
class SemanticActionSpec:
    op: str
    strategies: tuple[StrategySpec, ...]
    # Optional: when None, the strategy ladder is verified by the op's generic
    # verifier alone (e.g. home-screen-visible for `home`, scene-progress for
    # `tap`). This lets ops without a caller-supplied expectation still run the
    # ladder and switch strategy on verified failure (CUQ-0.1/0.8). A non-None
    # expected_state additionally refines/overrides the generic verdict.
    expected_state: ExpectedState | None = None
    recovery: str | None = None
    idempotent: bool = True

    def __post_init__(self) -> None:
        if not self.op:
            raise ValueError("semantic action op is required")
        if not self.strategies:
            raise ValueError("semantic action requires at least one strategy")

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "strategies": [strategy.to_dict() for strategy in self.strategies],
            "expected_state": self.expected_state.to_dict() if self.expected_state else None,
            "recovery": self.recovery,
            "idempotent": self.idempotent,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SemanticActionSpec:
        strategies = payload.get("strategies")
        if not isinstance(strategies, list):
            raise ValueError("semantic action strategies must be a list")
        expected_payload = payload.get("expected_state")
        return cls(
            op=str(payload.get("op") or ""),
            strategies=tuple(StrategySpec.from_dict(item) for item in strategies),
            expected_state=(
                ExpectedState.from_dict(expected_payload)
                if isinstance(expected_payload, Mapping)
                else None
            ),
            recovery=(
                str(payload["recovery"])
                if payload.get("recovery") is not None
                else None
            ),
            idempotent=bool(payload.get("idempotent", True)),
        )


@dataclass(frozen=True)
class BoundStrategy:
    spec: StrategySpec
    call: Callable[[], ActionResult]


@dataclass(frozen=True)
class SemanticAttempt:
    index: int
    strategy: str
    result: ActionResult
    semantic: SemanticOutcome
    edge: str
    switched_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "strategy": self.strategy,
            "result_ok": self.result.ok,
            "semantic": self.semantic.to_dict(),
            "edge": self.edge,
            "switched_reason": self.switched_reason,
        }


@dataclass(frozen=True)
class SemanticActionRun:
    spec: SemanticActionSpec
    attempts: tuple[SemanticAttempt, ...]
    status: str
    terminal_reason: TerminalReason
    recovered: bool = False
    vlm_calls: int = 0
    vlm_budget_exhausted: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def strategy_switches(self) -> int:
        switches = 0
        previous: str | None = None
        for attempt in self.attempts:
            if previous is not None and attempt.strategy != previous:
                switches += 1
            previous = attempt.strategy
        return switches

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "status": self.status,
            "terminal_reason": self.terminal_reason,
            "recovered": self.recovered,
            "strategy_switches": self.strategy_switches,
            "vlm_calls": self.vlm_calls,
            "vlm_budget_exhausted": self.vlm_budget_exhausted,
        }


VerifyCallable = Callable[[ExpectedState, ActionResult, StrategySpec, int], SemanticOutcome]
EscalateCallable = Callable[[ExpectedState, ActionResult, StrategySpec, int], SemanticOutcome]
RecoveryCallable = Callable[[str, ExpectedState], bool]
CapabilityCallable = Callable[[str], bool]
StrategyResolver = Callable[[StrategySpec], Callable[[], ActionResult]]


class SemanticActionPlan:
    def __init__(self, spec: SemanticActionSpec, bound: list[BoundStrategy] | tuple[BoundStrategy, ...]):
        if len(bound) != len(spec.strategies):
            raise ValueError("bound strategy count must match spec strategy count")
        self.spec = spec
        self.bound = tuple(bound)

    @classmethod
    def bind(
        cls,
        spec: SemanticActionSpec,
        resolver: StrategyResolver,
    ) -> SemanticActionPlan:
        return cls(spec, [BoundStrategy(strategy, resolver(strategy)) for strategy in spec.strategies])

    def metadata(self) -> dict[str, Any]:
        return {"semantic_action_spec": self.spec.to_dict()}

    def run(
        self,
        verify: VerifyCallable,
        *,
        supports: CapabilityCallable | None = None,
        escalate_vlm: EscalateCallable | None = None,
        recover: RecoveryCallable | None = None,
        transport_retry_budget: int = 0,
        vlm_budget_per_action: int = 0,
    ) -> SemanticActionRun:
        attempts: list[SemanticAttempt] = []
        recovered = False
        vlm_calls = 0
        vlm_budget_exhausted = False
        strategy_index = 0
        retry_counts: dict[int, int] = {}
        reattempted_after_recovery = False
        attempt_index = 0

        while strategy_index < len(self.bound):
            strategy = self.bound[strategy_index]
            if strategy.spec.capability and supports is not None and not supports(strategy.spec.capability):
                strategy_index += 1
                continue

            try:
                result = strategy.call()
                semantic = verify(self.spec.expected_state, result, strategy.spec, attempt_index)
            except Exception as exc:
                semantic = SemanticOutcome(
                    status="exception",
                    verifier="semantic_action_plan",
                    reason=f"{type(exc).__name__}: {exc}",
                    confidence=0.0,
                    retry_allowed=False,
                )
                result = ActionResult.failed(
                    backend="semantic_action_plan",
                    connected=False,
                    error=str(exc),
                    synthetic=True,
                )

            status = semantic.status
            if status == "no_after_scene":
                status = "unknown"
            if status == "unknown":
                if escalate_vlm is not None and vlm_calls < vlm_budget_per_action:
                    vlm_calls += 1
                    semantic = escalate_vlm(
                        self.spec.expected_state,
                        result,
                        strategy.spec,
                        attempt_index,
                    )
                    status = "unknown" if semantic.status == "no_after_scene" else semantic.status
                elif escalate_vlm is not None:
                    vlm_budget_exhausted = True

            edge = semantic_transition_edge(status, disqualifying_state=bool(semantic.disqualifying_state))
            attempts.append(
                SemanticAttempt(
                    index=attempt_index,
                    strategy=strategy.spec.name,
                    result=result,
                    semantic=semantic,
                    edge=edge,
                    switched_reason=(
                        "expected_state_unmet"
                        if edge in {"switch", "recover"}
                        else None
                    ),
                )
            )
            attempt_index += 1

            if edge == "done":
                return SemanticActionRun(
                    spec=self.spec,
                    attempts=tuple(attempts),
                    status="succeeded",
                    terminal_reason="succeeded",
                    recovered=recovered,
                    vlm_calls=vlm_calls,
                    vlm_budget_exhausted=vlm_budget_exhausted,
                )
            if edge == "terminate":
                terminal = "approval_required" if status == "approval_required" else (
                    "blocked" if status == "blocked" or semantic.disqualifying_state else "exception"
                )
                return SemanticActionRun(
                    spec=self.spec,
                    attempts=tuple(attempts),
                    status=status,
                    terminal_reason=terminal,
                    recovered=recovered,
                    vlm_calls=vlm_calls,
                    vlm_budget_exhausted=vlm_budget_exhausted,
                )
            if edge == "retry_same":
                used = retry_counts.get(strategy_index, 0)
                if self.spec.idempotent and used < transport_retry_budget:
                    retry_counts[strategy_index] = used + 1
                    continue
                strategy_index += 1
                continue

            if edge in {"switch", "recover"}:
                strategy_index += 1
                if strategy_index < len(self.bound):
                    continue
                if (
                    self.spec.recovery is not None
                    and recover is not None
                    and not reattempted_after_recovery
                ):
                    if not self.spec.idempotent:
                        return SemanticActionRun(
                            spec=self.spec,
                            attempts=tuple(attempts),
                            status="failed",
                            terminal_reason="not_idempotent",
                            recovered=recovered,
                            vlm_calls=vlm_calls,
                            vlm_budget_exhausted=vlm_budget_exhausted,
                        )
                    recovered = recover(self.spec.recovery, self.spec.expected_state)
                    reattempted_after_recovery = True
                    if recovered:
                        strategy_index = 0
                        retry_counts.clear()
                        continue
                return SemanticActionRun(
                    spec=self.spec,
                    attempts=tuple(attempts),
                    status="failed",
                    terminal_reason="strategies_exhausted",
                    recovered=recovered,
                    vlm_calls=vlm_calls,
                    vlm_budget_exhausted=vlm_budget_exhausted,
                )

        return SemanticActionRun(
            spec=self.spec,
            attempts=tuple(attempts),
            status="failed",
            terminal_reason="strategies_exhausted",
            recovered=recovered,
            vlm_calls=vlm_calls,
            vlm_budget_exhausted=vlm_budget_exhausted,
        )

    @staticmethod
    def _edge(status: str) -> str:
        return semantic_transition_edge(status)


def semantic_transition_edge(status: str, *, disqualifying_state: bool = False) -> str:
    """Map verifier status to the P2 state-machine edge used by all runners."""
    if disqualifying_state:
        return "terminate"
    if status == "succeeded":
        return "done"
    if status in {"failed", "partial", "unknown"}:
        return "switch"
    if status == "transport_failed":
        return "retry_same"
    if status in {"exception", "blocked", "approval_required"}:
        return "terminate"
    return "switch"


def verify_expected_state(expected: ExpectedState, scene: Any) -> SemanticOutcome:
    """Verify an expected post-state against one fresh scene-like object."""

    if scene is None:
        return SemanticOutcome(
            status="no_after_scene",
            verifier="expected_state",
            reason="missing scene for expected-state verification",
            confidence=0.0,
        )
    if expected.kind == "page_id":
        wanted = str(expected.payload.get("page_id") or "")
        actual = str(getattr(scene, "page_id", "") or "")
        status = "succeeded" if wanted and actual == wanted else "failed"
        return SemanticOutcome(
            status=status,
            verifier="expected_state",
            reason=(
                f"page_id matched: {wanted}"
                if status == "succeeded"
                else f"page_id mismatch: expected {wanted!r}, got {actual!r}"
            ),
            confidence=0.95 if status == "succeeded" else 0.75,
            matched_evidence=[actual] if status == "succeeded" else [],
            missing_evidence=[wanted] if status != "succeeded" and wanted else [],
            deterministic=True,
        )
    texts = _scene_texts(scene)
    if expected.kind == "visible_text":
        any_of = [str(item) for item in expected.payload.get("any_of", [])]
        all_of = [str(item) for item in expected.payload.get("all_of", [])]
        any_ok = not any_of or any(any(_contains_text(text, wanted) for text in texts) for wanted in any_of)
        missing_all = [
            wanted for wanted in all_of if not any(_contains_text(text, wanted) for text in texts)
        ]
        status = "succeeded" if any_ok and not missing_all else "failed"
        return SemanticOutcome(
            status=status,
            verifier="expected_state",
            reason="visible text expectation met" if status == "succeeded" else "visible text expectation unmet",
            confidence=0.9 if status == "succeeded" else 0.7,
            matched_evidence=[wanted for wanted in any_of + all_of if any(_contains_text(text, wanted) for text in texts)],
            missing_evidence=missing_all if any_ok else any_of,
            deterministic=True,
        )
    elements = list(getattr(scene, "elements", []) or [])
    if expected.kind == "element_appears":
        matched = _matching_elements(elements, expected.payload)
        return SemanticOutcome(
            status="succeeded" if matched else "failed",
            verifier="expected_state",
            reason="element appeared" if matched else "element did not appear",
            confidence=0.9 if matched else 0.7,
            matched_evidence=[_element_label(element) for element in matched],
            missing_evidence=[] if matched else [_element_query_label(expected.payload)],
            deterministic=True,
        )
    if expected.kind == "element_gone":
        matched = _matching_elements(elements, expected.payload.get("target_identity") or expected.payload)
        return SemanticOutcome(
            status="failed" if matched else "succeeded",
            verifier="expected_state",
            reason="element still visible" if matched else "element gone",
            confidence=0.7 if matched else 0.9,
            matched_evidence=[_element_label(element) for element in matched],
            deterministic=True,
        )
    return SemanticOutcome(
        status="unknown",
        verifier="expected_state",
        reason=f"unsupported expected-state kind: {expected.kind}",
        confidence=0.0,
    )


def _scene_texts(scene: Any) -> list[str]:
    return [
        str(getattr(element, "text", "") or "")
        for element in getattr(scene, "elements", []) or []
        if str(getattr(element, "text", "") or "")
    ]


def _contains_text(text: str, wanted: str) -> bool:
    return wanted in text if wanted else False


def _matching_elements(elements: list[Any], query: Mapping[str, Any]) -> list[Any]:
    role = query.get("role") or query.get("type")
    text = query.get("text") or query.get("label") or query.get("intent")
    out = []
    for element in elements:
        if role and str(getattr(element, "type", "") or "") != str(role):
            continue
        if text and not _contains_text(str(getattr(element, "text", "") or ""), str(text)):
            continue
        out.append(element)
    return out


def _element_label(element: Any) -> str:
    return str(getattr(element, "text", "") or getattr(element, "type", "") or "element")


def _element_query_label(query: Mapping[str, Any]) -> str:
    return str(query.get("text") or query.get("label") or query.get("intent") or query.get("role") or "element")


def default_semantic_action_spec(
    op: Literal["home", "back", "launch_app", "tap", "scroll"],
    expected_state: ExpectedState | None = None,
    *,
    recovery: str | None = "recover_to_home_then_renavigate",
    idempotent: bool = True,
) -> SemanticActionSpec:
    """Return a conservative default plan entrypoint for core semantic actions."""

    strategy_names: dict[str, tuple[tuple[str, str | None, int], ...]] = {
        "home": (
            ("keyboard_combo", "home", 30),
            ("assistive_touch_home", "assistive_touch", 20),
            ("home_indicator_drag", "close_foreground_app", 40),
        ),
        "back": (
            ("nav_back_tap", "tap", 10),
            ("keyboard_back", "key", 30),
            ("edge_back_gesture", "back", 40),
        ),
        "launch_app": (
            ("springboard_icon_tap", "tap", 10),
            ("springboard_search", "tap", 20),
            ("vlm_icon_map", "vlm", 25),
        ),
        "tap": (
            ("target_tap", "tap", 10),
            ("keyboard_focus_activate", "key", 20),
        ),
        "scroll": (
            ("wheel", "scroll_wheel", 20),
            ("drag", "drag", 40),
        ),
    }
    return SemanticActionSpec(
        op=op,
        strategies=tuple(
            StrategySpec(name=name, capability=capability, reliability_rank=rank)
            for name, capability, rank in strategy_names[op]
        ),
        expected_state=expected_state,
        recovery=recovery,
        idempotent=idempotent,
    )


def default_semantic_action_plan(
    phone: Any,
    op: Literal["home", "back", "launch_app", "tap", "scroll"],
    expected_state: ExpectedState | None = None,
    **params: Any,
) -> SemanticActionPlan:
    """Bind the default core action spec to a phone-like runtime object."""

    spec = default_semantic_action_spec(
        op,
        expected_state,
        recovery=params.pop("recovery", "recover_to_home_then_renavigate"),
        idempotent=bool(params.pop("idempotent", True)),
    )
    spec = SemanticActionSpec(
        op=spec.op,
        strategies=tuple(
            StrategySpec(
                name=strategy.name,
                capability=strategy.capability,
                reliability_rank=strategy.reliability_rank,
                params=_default_strategy_params(op, strategy.name, params),
            )
            for strategy in spec.strategies
        ),
        expected_state=spec.expected_state,
        recovery=spec.recovery,
        idempotent=spec.idempotent,
    )
    return SemanticActionPlan.bind(
        spec,
        lambda strategy: _bind_phone_strategy(phone, op, strategy, {**params, **strategy.params}),
    )


def _default_strategy_params(op: str, strategy_name: str, params: Mapping[str, Any]) -> dict[str, Any]:
    if op == "launch_app":
        out = {
            key: params[key]
            for key in ("app", "label", "max_pages", "settle_s")
            if key in params
        }
        if "aliases" in params:
            out["aliases"] = [str(item) for item in params.get("aliases", ()) or ()]
        return out
    if op == "tap" and strategy_name == "target_tap":
        return {
            key: params[key]
            for key in ("x", "y", "target", "text", "label")
            if key in params
        }
    if op == "scroll":
        return {
            key: params[key]
            for key in ("ticks", "horizontal", "x1", "y1", "x2", "y2", "direction")
            if key in params
        }
    return {}


def _bind_phone_strategy(
    phone: Any,
    op: str,
    strategy: StrategySpec,
    params: Mapping[str, Any],
) -> Callable[[], ActionResult]:
    name = strategy.name
    if op == "home":
        if name == "keyboard_combo":
            return lambda: phone.effector.home()
        if name == "assistive_touch_home":
            return lambda: phone._home_via_assistive_touch_menu()
        if name == "home_indicator_drag":
            return lambda: _call_phone_method(phone, "close_foreground_app", op, name)
    if op == "back":
        if name == "nav_back_tap":
            return lambda: _phone_nav_back_tap(phone)
        if name == "keyboard_back":
            return lambda: phone.effector.key(0x08, 0x2F)
        if name == "edge_back_gesture":
            return lambda: _call_phone_method(phone.effector, "back", op, name)
    if op == "launch_app":
        label = str(params.get("app") or params.get("label") or "")
        aliases = tuple(str(item) for item in params.get("aliases", ()) or ())
        max_pages = int(params.get("max_pages", 8) or 8)
        settle_s = float(params.get("settle_s", 0.8) or 0.8)
        return lambda: phone.open_app(label, aliases=aliases, max_pages=max_pages, settle_s=settle_s)
    if op == "tap":
        if name == "target_tap":
            return lambda: _phone_target_tap(phone, params)
        if name == "keyboard_focus_activate":
            return lambda: phone.effector.key(0, 0x28)
    if op == "scroll":
        # CUQ-0.1: a directional scroll (down = reveal content below). The ladder
        # is wheel -> swipe: the wheel sign follows the direction, and the swipe
        # fallback uses the backend's preset gesture (raw-coord drag only when
        # explicit x1..y2 are supplied) so it matches the existing swipe path.
        direction = str(params.get("direction") or "down")
        if name == "wheel":
            ticks = int(params.get("ticks", 3) or 3)
            signed = ticks if direction == "down" else -ticks
            horizontal = int(params.get("horizontal", 0) or 0)
            return lambda: phone.effector.scroll_wheel(signed, horizontal=horizontal)
        if name == "drag":
            if all(params.get(k) is not None for k in ("x1", "y1", "x2", "y2")):
                return lambda: _phone_drag(phone, params)
            return lambda: (phone.swipe_up() if direction == "down" else phone.swipe_down())
    return lambda: _unsupported(phone, op, name)


def _phone_nav_back_tap(phone: Any) -> ActionResult:
    context = getattr(phone, "_picokvm_back_context", None)
    if not callable(context):
        return _unsupported(phone, "back", "nav_back_tap")
    allowed, guard_reason, nav_back_point = context()
    if not allowed or nav_back_point is None:
        result = _unsupported(phone, "back", "nav_back_tap")
        # ActionResult is frozen — return a copy with the guard reason rather
        # than mutating in place (this binding had no production caller before
        # CUQ-0.1, so the in-place assignment had never run).
        if not result.error:
            result = replace(result, error=str(guard_reason or "nav back point unavailable"))
        return result
    x, y = nav_back_point
    px, py = phone._to_phone(x, y)
    return phone.effector.tap(px, py)


def _phone_target_tap(phone: Any, params: Mapping[str, Any]) -> ActionResult:
    if params.get("x") is not None and params.get("y") is not None:
        px, py = phone._to_phone(int(params["x"]), int(params["y"]))
        return phone.effector.tap(px, py)
    target = params.get("target") or params.get("text") or params.get("label")
    if target:
        return phone.tap_text(str(target))
    return _unsupported(phone, "tap", "target_tap")


def _phone_drag(phone: Any, params: Mapping[str, Any]) -> ActionResult:
    coords = [params.get(key) for key in ("x1", "y1", "x2", "y2")]
    if any(value is None for value in coords):
        return _unsupported(phone, "scroll", "drag")
    x1, y1, x2, y2 = (int(value) for value in coords)
    px1, py1 = phone._to_phone(x1, y1)
    px2, py2 = phone._to_phone(x2, y2)
    return phone.effector.drag(px1, py1, px2, py2)


def _call_phone_method(target: Any, method_name: str, op: str, strategy: str) -> ActionResult:
    method = getattr(target, method_name, None)
    if callable(method):
        return method()
    return _unsupported(target, op, strategy)


def _unsupported(phone: Any, op: str, strategy: str) -> ActionResult:
    method = getattr(phone, "_unsupported_action", None)
    if callable(method):
        return method(op, strategy=strategy)
    return ActionResult.failed(
        backend="semantic_action_plan",
        connected=False,
        error=f"unsupported semantic strategy: {op}.{strategy}",
        synthetic=True,
    )


__all__ = [
    "BoundStrategy",
    "ExpectedState",
    "SemanticActionPlan",
    "SemanticActionRun",
    "SemanticActionSpec",
    "SemanticAttempt",
    "StrategySpec",
    "default_semantic_action_plan",
    "default_semantic_action_spec",
    "verify_expected_state",
]
