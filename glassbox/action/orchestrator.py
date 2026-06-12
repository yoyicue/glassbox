"""Action lifecycle orchestration for computer-use runtime."""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import numpy as np

from glassbox.action.actuation import ActuationPlan
from glassbox.action.actuation_profile import ActuationProfile, save_actuation_profile
from glassbox.action.policy import RiskDecision, RiskPolicy
from glassbox.action.recovery import RuntimeRecoveryPolicy
from glassbox.action.seeds import DEFAULT_RECOVERY_SEED, recovery_hint
from glassbox.action.semantic_plan import (
    ExpectedState,
    SemanticActionPlan,
    page_identity_changed,
    semantic_transition_edge,
    verify_expected_state,
)
from glassbox.action.stuck import StuckLoopDetector, StuckSample
from glassbox.cognition.vlm_gate import VLMEscalationGate, VLMGateInput
from glassbox.effector import ActionResult
from glassbox.memory.signature import compute_signature, dhash
from glassbox.obs.artifacts import ArtifactStore, StoredFrame, StoredScene
from glassbox.obs.stream import ObservationBuffer
from glassbox.verification import (
    DEFAULT_REGISTRY,
    VerifierInput,
    VerifierRegistry,
    compute_frame_diff,
    compute_scene_diff,
)
from glassbox.verification.verifiers import SemanticOutcome, detect_disqualifying_state

ActionCallable = Callable[[], ActionResult]
ActionCallOrPlan = ActionCallable | ActuationPlan | SemanticActionPlan
Observation = tuple[StoredFrame | None, StoredScene | None, Any, Any]
OBSERVATION_PRODUCER_MODES = {"scoped_source_owner", "recorder_buffer"}
ACTUATION_ATTRIBUTION_LABELS = {
    "landed_ok",
    "landed_noop",
    "missed",
    "wrong_target",
    "blocked",
    "unknown",
}


@dataclass
class AttemptExecution:
    attempt_id: str
    result: ActionResult
    semantic: SemanticOutcome
    action_payload: dict[str, Any]
    command_exception: BaseException | None = None
    landing_observation: dict[str, Any] | None = None
    attempt_attribution: dict[str, Any] | None = None
    # S5b (docs/design/iphone_settings_transition.md): the minted page_ids of
    # the attempt's before_command / last after scene, in memory only (never
    # serialized) so the strategy-ladder advance can see whether the action
    # physically moved page identity even though verification said failed.
    before_page_id: str | None = None
    after_page_id: str | None = None


@dataclass
class AfterObservation:
    frames: list[Observation] = field(default_factory=list)
    matched_by_observation: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandExecution:
    result: ActionResult
    payload: dict[str, Any]
    completed_at: float
    exception: BaseException | None = None
    semantic: SemanticOutcome | None = None


@dataclass(frozen=True)
class RetryBudgets:
    semantic: int
    landing: int
    transport: int

    @property
    def max_attempts(self) -> int:
        return 1 + self.semantic + self.landing + self.transport


@dataclass
class AttemptPreparation:
    before_requested: Observation | None
    before_command: Observation | None
    risk: RiskDecision
    blocked_attempt: AttemptExecution | None = None
    command_result: ActionResult | None = None
    semantic: SemanticOutcome | None = None
    exception: BaseException | None = None


@dataclass
class AttemptOutcome:
    command_result: ActionResult
    semantic: SemanticOutcome
    command_exception: BaseException | None = None
    after: list[Observation] = field(default_factory=list)
    frame_diff: dict[str, Any] | None = None
    scene_diff: dict[str, Any] | None = None
    after_observation_metadata: dict[str, Any] = field(default_factory=dict)
    matched_by_observation: dict[str, Any] | None = None
    landing_observation: dict[str, Any] | None = None


@dataclass(frozen=True)
class SemanticRecoveryResult:
    used: bool = False
    recovered: bool = False


@dataclass(frozen=True)
class SemanticPlanAdvance:
    strategy_index: int
    attempt_index: int
    recovery_used: bool
    recovered: bool
    terminal_reason: str
    continue_loop: bool = False
    stop: bool = False


@dataclass(frozen=True)
class SemanticPlanLoopResult:
    attempts: list[AttemptExecution]
    recovered: bool
    terminal_reason: str


@dataclass
class PostCommandVerification:
    semantic: SemanticOutcome
    after: list[Observation] = field(default_factory=list)
    frame_diff: dict[str, Any] | None = None
    scene_diff: dict[str, Any] | None = None
    after_observation_metadata: dict[str, Any] = field(default_factory=dict)
    matched_by_observation: dict[str, Any] | None = None
    landing_observation: dict[str, Any] | None = None
    exception: BaseException | None = None


@dataclass(frozen=True)
class PostCommandContext:
    phone: Any
    op: str
    kwargs: dict[str, Any]
    settle_strategy: str
    verifier: Any
    metadata: dict[str, Any]
    group_id: str
    attempt_id: str
    before_requested: Observation | None
    before_command: Observation | None
    risk: RiskDecision
    command_payload: dict[str, Any]
    landing_retry_available: bool


def _result_to_command(result: ActionResult | None) -> dict[str, Any]:
    if result is None:
        return {"transport_ok": False, "backend": "unknown", "connected": False}
    return {
        "transport_ok": bool(result.ok),
        "backend": result.backend,
        "connected": result.connected,
        "ack_seq": result.ack_seq,
        "ack_seqs": list(result.ack_seqs),
        "retry_count": result.retry_count,
        "error": result.error,
        "synthetic": result.synthetic,
        "unsupported": result.unsupported,
        "partial": result.partial,
        "executed_count": result.executed_count,
    }


def _semantic_unknown(verifier: str, reason: str, *, skipped: bool = False) -> SemanticOutcome:
    return SemanticOutcome(
        status="unknown",
        verifier=verifier,
        reason=reason,
        confidence=0.0,
        verification_skipped=skipped,
    )


def _semantic_no_after(verifier: str, reason: str, *, skipped: bool = False) -> SemanticOutcome:
    return SemanticOutcome(
        status="no_after_scene",
        verifier=verifier,
        reason=reason,
        confidence=0.0,
        retry_allowed=False,
        verification_skipped=skipped,
    )


def _semantic_transport_failed(verifier: str, reason: str) -> SemanticOutcome:
    return SemanticOutcome(
        status="transport_failed",
        verifier=verifier,
        reason=reason,
        confidence=0.0,
        retry_allowed=False,
        verification_skipped=False,
    )


def _semantic_exception(verifier: str, exc: BaseException, *, phase: str) -> SemanticOutcome:
    return SemanticOutcome(
        status="exception",
        verifier=verifier,
        reason=f"{phase} raised {type(exc).__name__}: {exc}",
        confidence=0.0,
        retry_allowed=False,
        verification_skipped=False,
    )


class ActionOrchestrator:
    """Owns before/command/after/diff/verifier/audit sequencing."""

    def __init__(
        self,
        store: ArtifactStore,
        *,
        registry: VerifierRegistry | None = None,
        risk_policy: RiskPolicy | None = None,
        recovery_policy: RuntimeRecoveryPolicy | None = None,
        platform: str = "ios",
        semantic_fail_fast: bool = False,
        observation_producer_mode: str = "scoped_source_owner",
        observation_buffer: ObservationBuffer | None = None,
        actuation_profile: ActuationProfile | None = None,
        actuation_profile_dir: str | None = None,
        recovery_seed: dict[str, Any] | None = None,
        stuck_detector: StuckLoopDetector | None = None,
        max_stuck_recoveries: int = 3,
        idempotent_retry_budget: int = 0,
        recover_then_retry: bool = False,
        tap_retry_identity_guard: bool = False,
    ):
        if observation_producer_mode not in OBSERVATION_PRODUCER_MODES:
            expected = ", ".join(sorted(OBSERVATION_PRODUCER_MODES))
            raise ValueError(f"unsupported observation producer mode {observation_producer_mode!r}; expected {expected}")
        self.store = store
        self.registry = registry or DEFAULT_REGISTRY
        self.risk_policy = risk_policy or RiskPolicy()
        self.recovery_policy = recovery_policy or RuntimeRecoveryPolicy()
        self.platform = platform
        self.actuation_profile = actuation_profile or ActuationProfile(platform=platform)
        self.actuation_profile_dir = actuation_profile_dir
        self.recovery_seed = recovery_seed or DEFAULT_RECOVERY_SEED
        self.stuck_detector = stuck_detector or StuckLoopDetector()
        self.max_stuck_recoveries = max(0, int(max_stuck_recoveries))
        self._stuck_recovery_failures = 0
        # CUQ-0.11: opt-in semantic retry budget for ops declared idempotent
        # (_default_idempotent). 0 (default) keeps retry_budget at 0 so the
        # unknown->retry policy stays a no-op — byte-identical to before.
        self._idempotent_retry_budget = max(0, int(idempotent_retry_budget))
        # CUQ-0.12: opt-in — when stuck recovery succeeds, re-attempt the failed
        # action once from the recovered state so recovery alters the CURRENT
        # outcome (not only the next action). Default off (byte-identical).
        self._recover_then_retry = bool(recover_then_retry)
        # S5b (docs/design/iphone_settings_transition.md §1 C4): opt-in edge on
        # the tap strategy ladder — when verification fails/unknowns but the
        # before/after page identity CHANGED, the next same-target rung would
        # actuate stale coordinates on a different page (ledger acts
        # 63-65/74-76/96-98 of run_2026_06_12_06_04_38_737160), so the ladder
        # stops with semantic unknown instead. Default off (byte-identical);
        # flip-to-default-on is gated on rig A/B evidence.
        self._tap_retry_identity_guard = bool(tap_retry_identity_guard)
        self._in_recover_retry = False
        self.semantic_fail_fast = semantic_fail_fast
        self.observation_producer_mode = observation_producer_mode
        self._group_seq = 0
        self._attempt_seq = 0
        self._actions: list[dict[str, Any]] = []
        self._open_groups: dict[str, dict[str, Any]] = {}
        self._preflight_done = False
        self.observation_buffer = observation_buffer or ObservationBuffer()
        self._record_observation_producer_config()

    def _record_observation_producer_config(self) -> None:
        buffer_payload = {
            "min_retention_ms": self.observation_buffer.min_retention_ms,
            "min_retention_frames": self.observation_buffer.min_retention_frames,
            "clock": "monotonic",
            "drop_policy": "drop_unpromoted_oldest",
        }
        producer_payload = {
            "mode": self.observation_producer_mode,
            "continuous_recorder_feeds_buffer": self.observation_producer_mode == "recorder_buffer",
            "audit_writer": "action_orchestrator",
            "frame_capture_event": "promoted_ledger_frame_only",
        }
        if self.observation_producer_mode == "scoped_source_owner":
            producer_payload.update({
                "source_owner": "action_orchestrator",
                "raw_frame_source": "phone.perceive_snapshot",
            })
        else:
            producer_payload.update({
                "source_owner": "recorder",
                "raw_frame_source": "observation_buffer",
            })
        self.store.update_manifest({
            "observation_buffer": buffer_payload,
            "observation_producer": producer_payload,
            "recovery_seed": {
                "schema_version": self.recovery_seed.get("schema_version"),
                "blocking_overlay_states": sorted(
                    (self.recovery_seed.get("blocking_overlays") or {}).keys()
                    if isinstance(self.recovery_seed.get("blocking_overlays"), dict)
                    else []
                ),
            },
        })
        self.store.audit.append("observation.producer_configured", payload=producer_payload)

    def close(self) -> None:
        self._finalize_open_groups_as_interrupted("orchestrator closed with open attempt group")
        self.store.write_actuation_profile(self.actuation_profile.to_dict())
        self.store.write_actuation_report()
        if self.actuation_profile_dir is not None:
            with contextlib.suppress(Exception):
                save_actuation_profile(self.actuation_profile, profile_dir=self.actuation_profile_dir)
        self.store.write_review_outputs(self._actions)
        self.store.close()

    def execute(self, phone, op: str, call: ActionCallOrPlan, **kwargs: Any) -> ActionResult:
        self._preflight(phone)
        group_id = self._next_group_id()
        plan = call if isinstance(call, ActuationPlan) else None
        semantic_plan = call if isinstance(call, SemanticActionPlan) else None
        if plan is not None:
            kwargs = {**kwargs, **plan.metadata()}
        if semantic_plan is not None:
            kwargs = {**kwargs, **semantic_plan.metadata()}
        metadata = self._action_metadata(op, kwargs)
        actor = self._actor(metadata)
        skipped = self._skip_decision(phone, op=op, metadata=metadata)
        if skipped is not None:
            return self._skipped_result(
                phone,
                op=op,
                metadata=metadata,
                actor=actor,
                reason=skipped,
                group_id=group_id,
            )
        if semantic_plan is not None:
            return self._execute_semantic_plan(
                phone,
                op=op,
                plan=semantic_plan,
                kwargs=kwargs,
                metadata=metadata,
                actor=actor,
                group_id=group_id,
            )
        budgets = self._legacy_retry_budgets(metadata)
        self._start_attempt_group(op=op, actor=actor, group_id=group_id, budgets=budgets)
        attempts = self._run_legacy_attempts(
            phone,
            op=op,
            call=call,
            kwargs=kwargs,
            metadata=metadata,
            plan=plan,
            group_id=group_id,
            actor=actor,
            budgets=budgets,
        )

        return self._finish_legacy_execute(
            phone,
            op=op,
            call=call,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            actor=actor,
            attempts=attempts,
        )

    def _finish_legacy_execute(
        self,
        phone,
        *,
        op: str,
        call: ActionCallOrPlan,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        actor: str,
        attempts: list[AttemptExecution],
    ) -> ActionResult:
        final = attempts[-1]
        self._finalize_group(
            group_id,
            op=op,
            attempt_id=final.attempt_id,
            actor=actor,
            attempts=attempts,
            group_status=final.semantic.status,
            terminal_reason=final.semantic.disqualifying_state or final.semantic.reason,
        )
        # CUQ-0.1: do not fire stuck-recovery for a NESTED legacy actuation that a
        # strategy ladder invoked (tap_text / swipe_up inside a plan). The outer
        # plan owns recovery; a nested recovery here would Home-reset mid-ladder.
        # The flag is only set while _run_semantic_plan is active (default off).
        recovered = False
        if not getattr(phone, "in_semantic_plan", False):
            recovered = self._maybe_recover_stuck(phone, final, group_id=group_id)

        # CUQ-0.12: opt-in — recovery normally only primes the NEXT action. When
        # enabled, a *successful* recovery of a still-failed action re-attempts it
        # once from the recovered (clean) state, so the action's recorded outcome
        # can reflect the post-recovery result. Re-entrancy-guarded (a retry can't
        # itself retry) and skipped inside a plan. Default off → byte-identical.
        if (
            self._recover_then_retry
            and recovered
            and not self._in_recover_retry
            and not getattr(phone, "in_semantic_plan", False)
            and final.semantic.status in {"failed", "unknown", "partial"}
        ):
            self.store.audit.append(
                "stuck_detector.recover_then_retry",
                attempt_id=final.attempt_id,
                attempt_group_id=group_id,
                payload={"op": op, "prior_status": final.semantic.status},
            )
            self._in_recover_retry = True
            try:
                return self.execute(phone, op, call, **kwargs)
            finally:
                self._in_recover_retry = False

        enriched = self._enrich_result(final.result, final.semantic, final.attempt_id, group_id)
        if final.command_exception is not None:
            raise final.command_exception
        if phone.action_fail_fast and not enriched.ok:
            detail = enriched.error or "reported action failure"
            raise RuntimeError(f"{op} failed: {detail}")
        if self.semantic_fail_fast and final.semantic.status in {"failed", "blocked", "approval_required"}:
            raise RuntimeError(f"{op} semantic {final.semantic.status}: {final.semantic.reason}")
        if final.semantic.status == "unknown" and metadata.get("unknown_policy") == "fail":
            raise RuntimeError(f"{op} semantic unknown: {final.semantic.reason}")
        if final.semantic.status == "partial" and metadata.get("partial_policy") == "fail":
            raise RuntimeError(f"{op} semantic partial: {final.semantic.reason}")
        return enriched

    def _legacy_retry_budgets(self, metadata: dict[str, Any]) -> RetryBudgets:
        retry_budget = int(metadata.get("retry_budget", 0) or 0)
        if not metadata.get("idempotent"):
            retry_budget = 0
        landing_retry_budget = int(metadata.get("landing_retry_budget", 0) or 0)
        if not self._landing_retry_allowed(metadata):
            landing_retry_budget = 0
        # CUQ-0.10: transport failures are retryable independent of idempotency
        # because the action did not land. Default 0 preserves legacy behavior.
        transport_retry_budget = int(metadata.get("transport_retry_budget", 0) or 0)
        return RetryBudgets(
            semantic=retry_budget,
            landing=landing_retry_budget,
            transport=transport_retry_budget,
        )

    def _start_attempt_group(
        self,
        *,
        op: str,
        actor: str,
        group_id: str,
        budgets: RetryBudgets,
    ) -> None:
        self.store.audit.append(
            "attempt_group.started",
            actor=actor,
            attempt_group_id=group_id,
            payload={
                "op": op,
                "retry_budget": budgets.semantic,
                "landing_retry_budget": budgets.landing,
                "transport_retry_budget": budgets.transport,
                "actor": actor,
            },
        )
        self._open_groups[group_id] = {
            "op": op,
            "actor": actor,
            "retry_budget": budgets.semantic,
            "landing_retry_budget": budgets.landing,
            "transport_retry_budget": budgets.transport,
            "attempt_ids": [],
            "started_at": time.monotonic(),
        }

    def _run_legacy_attempts(
        self,
        phone,
        *,
        op: str,
        call: ActionCallOrPlan,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        plan: ActuationPlan | None,
        group_id: str,
        actor: str,
        budgets: RetryBudgets,
    ) -> list[AttemptExecution]:
        attempts: list[AttemptExecution] = []
        semantic_retries_used = 0
        landing_retries_used = 0
        transport_retries_used = 0
        try:
            for attempt_index in range(budgets.max_attempts):
                attempt_id = self._next_attempt_id()
                self._open_groups[group_id]["attempt_ids"].append(attempt_id)
                attempt_call: ActionCallable
                attempt_kwargs = dict(kwargs)
                if plan is not None:
                    command = plan.command_for_attempt(attempt_index)
                    attempt_call = command.call
                    attempt_kwargs.update(command.kwargs)
                else:
                    attempt_call = call  # type: ignore[assignment]
                attempt_metadata = {**metadata, **attempt_kwargs, "attempt_index": attempt_index}
                attempt = self._run_attempt(
                    phone,
                    op=op,
                    call=attempt_call,
                    kwargs=attempt_kwargs,
                    metadata=attempt_metadata,
                    group_id=group_id,
                    attempt_id=attempt_id,
                    attempt_index=attempt_index,
                    actor=actor,
                    landing_retry_available=landing_retries_used < budgets.landing,
                )
                self._carry_vlm_retry_metadata(attempt_metadata, metadata)
                attempts.append(attempt)
                retry_kind = self._retry_kind(
                    attempt,
                    metadata,
                    semantic_retries_used=semantic_retries_used,
                    retry_budget=budgets.semantic,
                    landing_retries_used=landing_retries_used,
                    landing_retry_budget=budgets.landing,
                    transport_retries_used=transport_retries_used,
                    transport_retry_budget=budgets.transport,
                )
                if retry_kind is None:
                    break
                if retry_kind == "landing":
                    landing_retries_used += 1
                elif retry_kind == "transport":
                    transport_retries_used += 1
                else:
                    semantic_retries_used += 1
                self._audit_retry_scheduled(
                    group_id=group_id,
                    attempt=attempt,
                    retry_kind=retry_kind,
                    next_attempt_index=attempt_index + 1,
                )
        except BaseException:
            self._finalize_group(
                group_id,
                op=op,
                actor=actor,
                attempts=attempts,
                group_status="interrupted",
                terminal_reason="orchestrator exception before group conclusion",
            )
            raise
        return attempts

    @staticmethod
    def _carry_vlm_retry_metadata(
        attempt_metadata: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        # CUQ-0.7: carry per-action VLM budget + audit counters forward
        # across retries so each retry cannot re-spend the per-action cap.
        for key in (
            "vlm_calls",
            "vlm_triggers",
            "last_vlm_trigger",
            "vlm_budget_exhausted",
            "vlm_cache_hits",
            "vlm_cache_misses",
        ):
            if key in attempt_metadata:
                metadata[key] = attempt_metadata[key]

    def _audit_retry_scheduled(
        self,
        *,
        group_id: str,
        attempt: AttemptExecution,
        retry_kind: str,
        next_attempt_index: int,
    ) -> None:
        self.store.audit.append(
            "action.retry_scheduled",
            attempt_id=attempt.attempt_id,
            attempt_group_id=group_id,
            payload={
                "kind": retry_kind,
                "reason": attempt.semantic.reason,
                "next_attempt_index": next_attempt_index,
            },
        )

    def _start_semantic_plan_group(
        self,
        *,
        op: str,
        actor: str,
        group_id: str,
        spec,
        strategy_count: int,
    ) -> None:
        self.store.audit.append(
            "attempt_group.started",
            actor=actor,
            attempt_group_id=group_id,
            payload={
                "op": op,
                "actor": actor,
                "semantic_action_spec": spec.to_dict(),
                "strategy_count": strategy_count,
            },
        )
        self._open_groups[group_id] = {
            "op": op,
            "actor": actor,
            "retry_budget": 0,
            "landing_retry_budget": 0,
            "attempt_ids": [],
            "started_at": time.monotonic(),
        }

    def _semantic_strategy_supported(self, phone, strategy) -> bool:
        capability = strategy.spec.capability
        return not capability or getattr(phone, "supports", lambda _op: True)(capability)

    def _audit_semantic_strategy_skipped(self, *, group_id: str, strategy, reason: str) -> None:
        self.store.audit.append(
            "semantic_plan.strategy_skipped",
            attempt_group_id=group_id,
            payload={
                "strategy": strategy.spec.to_dict(),
                "reason": reason,
            },
        )

    def _run_semantic_strategy_attempt(
        self,
        phone,
        *,
        op: str,
        spec,
        strategy,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_index: int,
        actor: str,
    ) -> tuple[AttemptExecution, dict[str, Any]]:
        attempt_id = self._next_attempt_id()
        self._open_groups[group_id]["attempt_ids"].append(attempt_id)
        attempt_kwargs = {
            **kwargs,
            "strategy": strategy.spec.name,
            "semantic_action_strategy": strategy.spec.to_dict(),
            "idempotent": spec.idempotent,
            "attempt_index": attempt_index,
        }
        if spec.expected_state is not None:
            attempt_kwargs["expected_state"] = spec.expected_state.to_dict()
        attempt_metadata = {**metadata, **attempt_kwargs}
        attempt = self._run_attempt(
            phone,
            op=op,
            call=strategy.call,
            kwargs=attempt_kwargs,
            metadata=attempt_metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            actor=actor,
        )
        return attempt, attempt_metadata

    def _audit_transport_retry(
        self,
        *,
        group_id: str,
        attempt: AttemptExecution,
        strategy,
        next_attempt_index: int,
    ) -> None:
        self.store.audit.append(
            "action.retry_scheduled",
            attempt_id=attempt.attempt_id,
            attempt_group_id=group_id,
            payload={
                "kind": "transport",
                "reason": attempt.semantic.reason,
                "strategy": strategy.spec.name,
                "next_attempt_index": next_attempt_index,
            },
        )

    def _audit_semantic_strategy_failed(
        self,
        *,
        group_id: str,
        attempt: AttemptExecution,
        strategy,
        status: str,
        next_strategy_index: int,
    ) -> None:
        self.store.audit.append(
            "semantic_plan.strategy_failed",
            attempt_id=attempt.attempt_id,
            attempt_group_id=group_id,
            payload={
                "strategy": strategy.spec.name,
                "status": status,
                "reason": attempt.semantic.reason,
                "next_strategy_index": next_strategy_index,
            },
        )

    def _recover_semantic_plan(
        self,
        phone,
        *,
        spec,
        attempt: AttemptExecution,
        group_id: str,
    ) -> SemanticRecoveryResult:
        if spec.recovery is None or not spec.idempotent or self.recovery_policy is None:
            return SemanticRecoveryResult()
        self.store.audit.append(
            "semantic_plan.recovery.started",
            attempt_id=attempt.attempt_id,
            attempt_group_id=group_id,
            payload={
                "recovery": spec.recovery,
                "reason": attempt.semantic.reason,
            },
        )
        recovery = self.recovery_policy.recover(
            phone,
            attempt.semantic.reason,
            {"semantic_action_spec": spec.to_dict()},
        )
        self.store.audit.append(
            "semantic_plan.recovery.finished",
            attempt_id=attempt.attempt_id,
            attempt_group_id=group_id,
            payload=recovery.to_dict(),
        )
        return SemanticRecoveryResult(used=True, recovered=recovery.recovered)

    def _append_empty_semantic_plan_attempt(self, phone, *, group_id: str) -> list[AttemptExecution]:
        result = phone.failed_action_result(error="semantic plan had no eligible strategies")
        semantic = _semantic_exception(
            "semantic_action_plan",
            RuntimeError("semantic plan had no eligible strategies"),
            phase="strategy selection",
        )
        attempt_id = self._next_attempt_id()
        self._open_groups[group_id]["attempt_ids"].append(attempt_id)
        return [AttemptExecution(attempt_id, result, semantic, {})]

    def _finish_semantic_plan_result(
        self,
        phone,
        *,
        op: str,
        actor: str,
        spec,
        attempts: list[AttemptExecution],
        recovered: bool,
        group_id: str,
        terminal_reason: str,
    ) -> ActionResult:
        final = attempts[-1]
        self._finalize_group(
            group_id,
            op=op,
            attempt_id=final.attempt_id,
            actor=actor,
            attempts=attempts,
            group_status=final.semantic.status,
            terminal_reason=terminal_reason,
        )
        self._maybe_recover_stuck(phone, final, group_id=group_id)
        self.store.audit.append(
            "semantic_plan.finished",
            attempt_id=final.attempt_id,
            attempt_group_id=group_id,
            payload={
                "status": final.semantic.status,
                "recovered": recovered,
                "strategy_switches": self._strategy_switch_count(attempts),
                "semantic_action_spec": spec.to_dict(),
            },
        )
        enriched = self._enrich_result(final.result, final.semantic, final.attempt_id, group_id)
        if final.command_exception is not None:
            raise final.command_exception
        if phone.action_fail_fast and not enriched.ok:
            detail = enriched.error or "reported action failure"
            raise RuntimeError(f"{op} failed: {detail}")
        if self.semantic_fail_fast and final.semantic.status in {"failed", "blocked", "approval_required"}:
            raise RuntimeError(f"{op} semantic {final.semantic.status}: {final.semantic.reason}")
        return enriched

    def _transport_retry_advance(
        self,
        *,
        attempt: AttemptExecution,
        strategy,
        strategy_index: int,
        attempt_index: int,
        transport_retry_budget: int,
        transport_retries_by_strategy: dict[int, int],
        recovery_used: bool,
        group_id: str,
    ) -> SemanticPlanAdvance | None:
        used_transport_retries = transport_retries_by_strategy.get(strategy_index, 0)
        if used_transport_retries >= transport_retry_budget:
            return None
        transport_retries_by_strategy[strategy_index] = used_transport_retries + 1
        self._audit_transport_retry(
            group_id=group_id,
            attempt=attempt,
            strategy=strategy,
            next_attempt_index=attempt_index + 1,
        )
        return SemanticPlanAdvance(
            strategy_index,
            attempt_index + 1,
            recovery_used,
            False,
            "strategies exhausted",
            continue_loop=True,
        )

    def _semantic_recovery_advance(
        self,
        phone,
        *,
        spec,
        attempt: AttemptExecution,
        next_strategy_index: int,
        next_attempt_index: int,
        recovery_used: bool,
        transport_retries_by_strategy: dict[int, int],
        group_id: str,
    ) -> SemanticPlanAdvance | None:
        if recovery_used:
            return None
        recovery = self._recover_semantic_plan(
            phone,
            spec=spec,
            attempt=attempt,
            group_id=group_id,
        )
        if recovery.recovered:
            transport_retries_by_strategy.clear()
            return SemanticPlanAdvance(0, next_attempt_index, recovery.used, True, "strategies exhausted", True)
        return SemanticPlanAdvance(
            next_strategy_index,
            next_attempt_index,
            recovery.used,
            False,
            attempt.semantic.reason,
            stop=True,
        )

    @staticmethod
    def _terminal_semantic_advance(
        *,
        edge: str,
        attempt: AttemptExecution,
        strategy_index: int,
        attempt_index: int,
        recovery_used: bool,
    ) -> SemanticPlanAdvance | None:
        if edge == "done":
            return SemanticPlanAdvance(
                strategy_index,
                attempt_index,
                recovery_used,
                False,
                "expected state reached",
                stop=True,
            )
        if edge != "terminate":
            return None
        terminal_reason = attempt.semantic.disqualifying_state or attempt.semantic.reason
        return SemanticPlanAdvance(strategy_index, attempt_index, recovery_used, False, terminal_reason, stop=True)

    def _identity_guard_stop(
        self,
        *,
        spec,
        attempt: AttemptExecution,
        strategy,
        status: str,
        strategy_index: int,
        attempt_index: int,
        recovery_used: bool,
        group_id: str,
    ) -> SemanticPlanAdvance | None:
        """S5b edge (docs/design/iphone_settings_transition.md §1 C4 / §2):
        forbid same-target re-actuation once the page identity changed.

        A tap whose verification came back failed/unknown but whose
        before→after minted page identity CHANGED has physically navigated
        somewhere: the remaining tap rungs (keyboard_focus_activate, a
        post-recovery rung-0 re-run) would re-actuate the same target on a
        DIFFERENT page — arbitrary detail-page content (live repro: ledger
        acts 63-65/74-76/96-98 of run_2026_06_12_06_04_38_737160). The tap
        ladder has no non-destructive rung to skip to, so the plan stops with
        semantic unknown ("we left the page; whether it was the wanted page is
        unverified" — the run's 4 such rejections were all false). This is an
        edge on the existing ladder, not a new rung; flag-gated
        (GLASSBOX_TAP_RETRY_IDENTITY_GUARD, default off → byte-identical)."""
        if not self._tap_retry_identity_guard or spec.op != "tap":
            return None
        if not page_identity_changed(attempt.before_page_id, attempt.after_page_id):
            return None
        reason = (
            "tap retry identity guard: page identity changed "
            f"({attempt.before_page_id!r} -> {attempt.after_page_id!r}); "
            "same-target re-tap forbidden"
        )
        self.store.audit.append(
            "semantic_plan.identity_guard.blocked",
            attempt_id=attempt.attempt_id,
            attempt_group_id=group_id,
            payload={
                "strategy": strategy.spec.name,
                "status": status,
                "before_page_id": attempt.before_page_id,
                "after_page_id": attempt.after_page_id,
                "verifier_reason": attempt.semantic.reason,
            },
        )
        attempt.semantic = SemanticOutcome(
            status="unknown",
            verifier="tap_retry_identity_guard",
            reason=f"{reason} (verifier said: {attempt.semantic.reason})",
            confidence=attempt.semantic.confidence,
            matched_evidence=list(attempt.semantic.matched_evidence),
            missing_evidence=list(attempt.semantic.missing_evidence),
            matched_frame_id=attempt.semantic.matched_frame_id,
            matched_scene_id=attempt.semantic.matched_scene_id,
            deterministic=True,
            retry_allowed=False,
        )
        return SemanticPlanAdvance(
            strategy_index,
            attempt_index + 1,
            recovery_used,
            False,
            reason,
            stop=True,
        )

    def _advance_after_semantic_attempt(
        self,
        phone,
        *,
        spec,
        plan: SemanticActionPlan,
        attempt: AttemptExecution,
        strategy,
        status: str,
        strategy_index: int,
        attempt_index: int,
        transport_retry_budget: int,
        transport_retries_by_strategy: dict[int, int],
        recovery_used: bool,
        group_id: str,
    ) -> SemanticPlanAdvance:
        edge = semantic_transition_edge(
            status,
            disqualifying_state=bool(attempt.semantic.disqualifying_state),
        )
        terminal = self._terminal_semantic_advance(
            edge=edge,
            attempt=attempt,
            strategy_index=strategy_index,
            attempt_index=attempt_index,
            recovery_used=recovery_used,
        )
        if terminal is not None:
            return terminal
        if edge == "retry_same" and spec.idempotent:
            retry = self._transport_retry_advance(
                attempt=attempt,
                strategy=strategy,
                strategy_index=strategy_index,
                attempt_index=attempt_index,
                transport_retry_budget=transport_retry_budget,
                transport_retries_by_strategy=transport_retries_by_strategy,
                recovery_used=recovery_used,
                group_id=group_id,
            )
            if retry is not None:
                return retry
        guard = self._identity_guard_stop(
            spec=spec,
            attempt=attempt,
            strategy=strategy,
            status=status,
            strategy_index=strategy_index,
            attempt_index=attempt_index,
            recovery_used=recovery_used,
            group_id=group_id,
        )
        if guard is not None:
            return guard
        next_strategy_index = strategy_index + 1
        self._audit_semantic_strategy_failed(
            group_id=group_id,
            attempt=attempt,
            strategy=strategy,
            status=status,
            next_strategy_index=next_strategy_index,
        )
        next_attempt_index = attempt_index + 1
        if next_strategy_index < len(plan.bound):
            return SemanticPlanAdvance(
                next_strategy_index,
                next_attempt_index,
                recovery_used,
                False,
                "strategies exhausted",
                continue_loop=True,
            )
        recovery = self._semantic_recovery_advance(
            phone,
            spec=spec,
            attempt=attempt,
            next_strategy_index=next_strategy_index,
            next_attempt_index=next_attempt_index,
            recovery_used=recovery_used,
            transport_retries_by_strategy=transport_retries_by_strategy,
            group_id=group_id,
        )
        if recovery is not None:
            return recovery
        return SemanticPlanAdvance(
            next_strategy_index,
            next_attempt_index,
            recovery_used,
            False,
            attempt.semantic.reason,
            stop=True,
        )

    def _run_semantic_plan_loop(
        self,
        phone,
        *,
        op: str,
        plan: SemanticActionPlan,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        attempts: list[AttemptExecution],
        actor: str,
        group_id: str,
        transport_retry_budget: int,
    ) -> SemanticPlanLoopResult:
        spec = plan.spec
        recovered = False
        recovery_used = False
        strategy_index = 0
        attempt_index = 0
        terminal_reason = "strategies exhausted"
        transport_retries_by_strategy: dict[int, int] = {}
        while strategy_index < len(plan.bound):
            strategy = plan.bound[strategy_index]
            if not self._semantic_strategy_supported(phone, strategy):
                self._audit_semantic_strategy_skipped(
                    group_id=group_id,
                    strategy=strategy,
                    reason="capability unsupported",
                )
                strategy_index += 1
                continue
            attempt, attempt_metadata = self._run_semantic_strategy_attempt(
                phone,
                op=op,
                spec=spec,
                strategy=strategy,
                kwargs=kwargs,
                metadata=metadata,
                group_id=group_id,
                attempt_index=attempt_index,
                actor=actor,
            )
            self._carry_vlm_retry_metadata(attempt_metadata, metadata)
            attempts.append(attempt)
            advance = self._advance_after_semantic_attempt(
                phone,
                spec=spec,
                plan=plan,
                attempt=attempt,
                strategy=strategy,
                status=attempt.semantic.status,
                strategy_index=strategy_index,
                attempt_index=attempt_index,
                transport_retry_budget=transport_retry_budget,
                transport_retries_by_strategy=transport_retries_by_strategy,
                recovery_used=recovery_used,
                group_id=group_id,
            )
            strategy_index = advance.strategy_index
            attempt_index = advance.attempt_index
            recovery_used = advance.recovery_used
            recovered = recovered or advance.recovered
            terminal_reason = advance.terminal_reason
            if advance.continue_loop:
                continue
            break
        return SemanticPlanLoopResult(attempts, recovered, terminal_reason)

    def _execute_semantic_plan(
        self,
        phone,
        *,
        op: str,
        plan: SemanticActionPlan,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        actor: str,
        group_id: str,
    ) -> ActionResult:
        spec = plan.spec
        self._start_semantic_plan_group(
            op=op,
            actor=actor,
            group_id=group_id,
            spec=spec,
            strategy_count=len(plan.bound),
        )
        transport_retry_budget = self._int_metadata(
            metadata,
            "transport_retry_budget",
            self._int_metadata(metadata, "retry_budget", 0),
        )
        attempts: list[AttemptExecution] = []
        try:
            result = self._run_semantic_plan_loop(
                phone,
                op=op,
                plan=plan,
                kwargs=kwargs,
                metadata=metadata,
                attempts=attempts,
                actor=actor,
                group_id=group_id,
                transport_retry_budget=transport_retry_budget,
            )
        except BaseException:
            self._finalize_group(
                group_id,
                op=op,
                actor=actor,
                attempts=attempts,
                group_status="interrupted",
                terminal_reason="semantic plan exception before group conclusion",
            )
            raise

        attempts = result.attempts
        if not attempts:
            attempts = self._append_empty_semantic_plan_attempt(phone, group_id=group_id)

        return self._finish_semantic_plan_result(
            phone,
            op=op,
            actor=actor,
            spec=spec,
            attempts=attempts,
            recovered=result.recovered,
            group_id=group_id,
            terminal_reason=result.terminal_reason,
        )

    def _skip_decision(self, phone, *, op: str, metadata: dict[str, Any]) -> str | None:
        if not self._landing_observation_enabled(metadata):
            return None
        if metadata.get("ignore_actuation_profile_skip"):
            return None
        if not getattr(phone, "supports", lambda _op: True)(op):
            return "unsupported"
        skip, reason = self.actuation_profile.should_skip_bucket(
            metadata.get("control_bucket"),
            method=str(metadata.get("actuation_method") or "mouse_tap"),
        )
        return reason if skip else None

    @staticmethod
    def _stuck_screen_signature(final: AttemptExecution) -> str | None:
        observation = final.action_payload.get("observation") if final.action_payload else None
        signature = (
            observation.get("screen_signature")
            if isinstance(observation, dict)
            else None
        )
        return signature if isinstance(signature, str) and signature else None

    def _audit_stuck_observed(
        self,
        *,
        final: AttemptExecution,
        group_id: str,
        signature: str,
        reason: str,
        decision,
    ) -> None:
        self.store.audit.append(
            "stuck_detector.observed",
            attempt_id=final.attempt_id,
            attempt_group_id=group_id,
            payload={
                "screen_signature": signature,
                "failure_reason": reason,
                "count": decision.count,
                "should_recover": decision.should_recover,
                "recovery": decision.recovery,
            },
        )

    def _audit_stuck_recovery_started(
        self,
        *,
        final: AttemptExecution,
        group_id: str,
        reason: str,
        recovery: str,
    ) -> None:
        self.store.audit.append(
            "stuck_detector.recovery.started",
            attempt_id=final.attempt_id,
            attempt_group_id=group_id,
            payload={
                "recovery": recovery,
                "failure_reason": reason,
            },
        )

    def _audit_stuck_unrecoverable(
        self,
        *,
        final: AttemptExecution,
        group_id: str,
        reason: str,
        signature: str,
    ) -> None:
        self.store.audit.append(
            "stuck_detector.unrecoverable",
            attempt_id=final.attempt_id,
            attempt_group_id=group_id,
            payload={
                "failure_reason": reason,
                "screen_signature": signature,
                "recovery_failures": self._stuck_recovery_failures,
            },
        )

    def _maybe_recover_stuck(
        self,
        phone,
        final: AttemptExecution,
        *,
        group_id: str,
    ) -> bool:
        """Run stuck/loop recovery if the detector trips. Returns True iff a
        recovery actually succeeded (so CUQ-0.12's opt-in retry can re-attempt the
        action from the recovered state)."""
        status = final.semantic.status
        if status == "succeeded":
            self.stuck_detector.reset()
            return False
        if status in {"blocked", "approval_required", "exception"}:
            return False
        if final.semantic.disqualifying_state:
            return False
        signature = self._stuck_screen_signature(final)
        if signature is None:
            return False
        reason = str(final.semantic.disqualifying_state or final.semantic.reason or status)
        decision = self.stuck_detector.observe(StuckSample(signature, str(reason)))
        self._audit_stuck_observed(
            final=final,
            group_id=group_id,
            signature=signature,
            reason=reason,
            decision=decision,
        )
        if not decision.should_recover:
            return False
        self._audit_stuck_recovery_started(
            final=final,
            group_id=group_id,
            reason=reason,
            recovery=decision.recovery,
        )
        recovery = self.recovery_policy.recover(
            phone,
            reason,
            {
                "recovery": decision.recovery,
                "screen_signature": signature,
                "attempt_group_id": group_id,
                "attempt_id": final.attempt_id,
            },
        )
        self.store.audit.append(
            "stuck_detector.recovery.finished",
            attempt_id=final.attempt_id,
            attempt_group_id=group_id,
            payload=recovery.to_dict(),
        )
        # CUQ-0.9: make re-firing outcome-aware. A recovery that actually
        # recovered clears the failure budget; one that did not must NOT leave
        # the anchor permanently disarmed (which would loop the failed action
        # forever after a single no-op recovery). Re-arm so the dead-end can
        # fire again after `threshold` more samples, up to a bounded budget;
        # on exhaustion surface a terminal marker instead of retrying forever.
        if recovery.recovered:
            self._stuck_recovery_failures = 0
            return True
        self._stuck_recovery_failures += 1
        if self._stuck_recovery_failures >= self.max_stuck_recoveries:
            self._audit_stuck_unrecoverable(
                final=final,
                group_id=group_id,
                reason=reason,
                signature=signature,
            )
            return False
        self.stuck_detector.rearm()
        return False

    def _skipped_result(
        self,
        phone,
        *,
        op: str,
        metadata: dict[str, Any],
        actor: str,
        reason: str,
        group_id: str,
    ) -> ActionResult:
        payload = {
            "attempt_group_id": group_id,
            "op": op,
            "reason": reason,
            "method": metadata.get("actuation_method", "mouse_tap"),
            "control_bucket": metadata.get("control_bucket"),
            "target_identity": metadata.get("target_identity"),
            "emitted_by": "runtime",
            "action_actor": actor,
        }
        self.store.audit.append(
            "attempt_group.started",
            actor=actor,
            attempt_group_id=group_id,
            payload={"op": op, "actor": actor, "skipped": True, "reason": reason},
        )
        self.store.audit.append(
            "actuation.skipped",
            attempt_group_id=group_id,
            payload=payload,
        )
        group_payload = {
            "attempt_group_id": group_id,
            "op": op,
            "actor": actor,
            "attempt_ids": [],
            "group_status": "skipped",
            "terminal_reason": reason,
            "retry_count": 0,
        }
        self.store.append_group(group_payload)
        self.store.audit.append(
            "attempt_group.finished",
            attempt_group_id=group_id,
            payload=group_payload,
        )
        return replace(
            phone.failed_action_result(
                error=f"actuation skipped: {reason}",
                unsupported=reason == "unsupported",
            ),
            synthetic=True,
            semantic_status="skipped",
            semantic_reason=reason,
            semantic_confidence=1.0,
            semantic_verifier="actuation_profile",
            semantic_verification_skipped=True,
            attempt_group_id=group_id,
            artifact_run_dir=str(self.store.run_dir),
        )

    def _finalize_group(
        self,
        group_id: str,
        *,
        op: str,
        actor: str,
        attempts: list[AttemptExecution],
        group_status: str,
        terminal_reason: str,
        attempt_id: str | None = None,
    ) -> None:
        open_group = self._open_groups.pop(group_id, {})
        attempt_ids = [attempt.attempt_id for attempt in attempts]
        if not attempt_ids:
            attempt_ids = list(open_group.get("attempt_ids") or [])
        group_payload = {
            "attempt_group_id": group_id,
            "op": op,
            "actor": actor,
            "attempt_ids": attempt_ids,
            "group_status": group_status,
            "terminal_reason": terminal_reason,
            "retry_count": max(0, len(attempts) - 1),
        }
        self.store.append_group(group_payload)
        self._emit_group_attribution(
            group_id,
            actor=actor,
            attempts=attempts,
            terminal_attempt_id=attempt_id,
        )
        if group_status == "interrupted":
            self.store.audit.append(
                "attempt_group.interrupted",
                attempt_id=attempt_id,
                attempt_group_id=group_id,
                payload=group_payload,
            )
        self.store.audit.append(
            "attempt_group.finished",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=group_payload,
        )

    def _finalize_open_groups_as_interrupted(self, reason: str) -> None:
        for group_id, group in list(self._open_groups.items()):
            self._finalize_group(
                group_id,
                op=str(group.get("op") or "unknown"),
                actor=str(group.get("actor") or "runtime"),
                attempts=[],
                group_status="interrupted",
                terminal_reason=reason,
            )

    def _preflight(self, phone) -> None:
        if self._preflight_done:
            return
        started = time.monotonic()
        payload = self._preflight_probe(phone, started=started)
        if payload.get("status") == "failed":
            reason = str(payload.get("disqualifying_state") or payload.get("error") or "preflight failed")
            self.store.audit.append(
                "run.recovery.started",
                payload={"reason": reason, "preflight": payload},
            )
            recovery = self.recovery_policy.recover(phone, reason, payload)
            self.store.audit.append(
                "run.recovery.finished",
                payload=recovery.to_dict(),
            )
            if recovery.recovered:
                retry_payload = self._preflight_probe(phone, started=started)
                retry_payload["recovery"] = recovery.to_dict()
                payload = retry_payload
            else:
                payload["recovery"] = recovery.to_dict()
        self.store.audit.append("run.preflight", payload=payload)
        self.store.update_manifest({"preflight": payload})
        self._preflight_done = True

    def _preflight_probe(self, phone, *, started: float) -> dict[str, Any]:
        try:
            frame = phone.snapshot(stable=False)
            if frame is not None:
                self.observation_buffer.append(frame, source="preflight")
            viewport = None
            if frame is not None and frame.img is not None:
                h, w = frame.img.shape[:2]
                viewport = {"width": int(w), "height": int(h)}
            if frame is None or frame.img is None:
                payload = {
                    "status": "failed",
                    "error": "no video frame captured",
                    "viewport": viewport,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            else:
                texts: list[str] = []
                with contextlib.suppress(Exception):
                    texts = [
                        str(element.text).strip()
                        for element in phone.ocr.recognize(frame.img)
                        if element.text and str(element.text).strip()
                    ]
                disqualified = detect_disqualifying_state(texts)
                if disqualified is not None:
                    spec, hits = disqualified
                    return {
                        "status": "failed",
                        "error": f"preflight disqualifying state: {spec.state}",
                        "viewport": viewport,
                        "disqualifying_state": spec.state,
                        "matched_evidence": hits,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                if not texts and float(frame.img.mean()) < 2.0:
                    return {
                        "status": "failed",
                        "error": "blank video frame captured",
                        "viewport": viewport,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                payload = {
                    "status": "passed",
                    "viewport": viewport,
                    "texts_sampled": len(texts),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
        except Exception as exc:
            payload = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        return payload

    def _run_attempt(
        self,
        phone,
        *,
        op: str,
        call: ActionCallable,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        attempt_index: int,
        actor: str,
        landing_retry_available: bool = False,
    ) -> AttemptExecution:
        verifier = self.registry.resolve(op, metadata)
        settle_strategy = str(metadata["settle_strategy"])
        preparation = self._prepare_attempt(
            phone,
            op=op,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            actor=actor,
            verifier_name=verifier.name,
        )
        if preparation.blocked_attempt is not None:
            return preparation.blocked_attempt
        before_requested = preparation.before_requested
        before_command = preparation.before_command
        risk = preparation.risk
        outcome = self._run_prepared_command_attempt(
            phone,
            op=op,
            call=call,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            actor=actor,
            verifier=verifier,
            settle_strategy=settle_strategy,
            before_requested=before_requested,
            before_command=before_command,
            risk=risk,
            preparation=preparation,
            landing_retry_available=landing_retry_available,
        )
        return self._finish_attempt_outcome(
            phone,
            op=op,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            actor=actor,
            before_requested=before_requested,
            before_command=before_command,
            risk=risk,
            outcome=outcome,
        )

    def _run_prepared_command_attempt(
        self,
        phone,
        *,
        op: str, call: ActionCallable, kwargs: dict[str, Any], metadata: dict[str, Any],
        group_id: str, attempt_id: str, attempt_index: int, actor: str, verifier,
        settle_strategy: str, before_requested: Observation | None, before_command: Observation | None,
        risk: RiskDecision, preparation: AttemptPreparation, landing_retry_available: bool,
    ) -> AttemptOutcome:
        command_result = preparation.command_result
        command_exception = preparation.exception
        semantic: SemanticOutcome | None = preparation.semantic
        after_observation_metadata: dict[str, Any] = {
            "settle_strategy": settle_strategy,
            "after_mode": "none",
            "trace_level": self.store.effective_trace_level(self._trace_level_override(metadata)),
        }
        try:
            command_payload = None
            command_completed_at = 0.0
            if semantic is None:
                command = self._run_command(
                    phone,
                    op=op,
                    call=call,
                    metadata=metadata,
                    attempt_id=attempt_id,
                    group_id=group_id,
                    verifier_name=verifier.name,
                )
                command_result = command.result
                command_payload = command.payload
                command_completed_at = command.completed_at
                command_exception = command.exception
                semantic = command.semantic
            if semantic is None and command_result is not None and command_result.ok:
                verification = self._verify_after_successful_command(
                    phone,
                    op=op,
                    kwargs=kwargs,
                    settle_strategy=settle_strategy,
                    verifier=verifier,
                    metadata=metadata,
                    group_id=group_id,
                    attempt_id=attempt_id,
                    attempt_index=attempt_index,
                    actor=actor,
                    before_requested=before_requested,
                    before_command=before_command,
                    risk=risk,
                    command_payload=command_payload or {},
                    command_completed_at=command_completed_at,
                    landing_retry_available=landing_retry_available,
                )
                if verification.exception is not None:
                    command_exception = verification.exception
                assert command_result is not None
                return self._outcome_from_verification(command_result, semantic, command_exception, verification)
            if semantic is None:
                assert command_result is not None
                reason = command_result.error or "command transport failed before GUI verification"
                semantic = _semantic_transport_failed(verifier.name, reason)
        except Exception as exc:
            command_exception = exc
            if command_result is None:
                command_result = phone.failed_action_result(error=f"{type(exc).__name__}: {exc}")
            semantic = _semantic_exception(verifier.name, exc, phase="command")
        assert command_result is not None
        assert semantic is not None
        return AttemptOutcome(
            command_result=command_result,
            semantic=semantic,
            command_exception=command_exception,
            after_observation_metadata=after_observation_metadata,
        )

    @staticmethod
    def _outcome_from_verification(
        command_result: ActionResult,
        current_semantic: SemanticOutcome | None,
        command_exception: BaseException | None,
        verification: PostCommandVerification,
    ) -> AttemptOutcome:
        del current_semantic
        return AttemptOutcome(
            command_result=command_result,
            semantic=verification.semantic,
            command_exception=command_exception,
            after=verification.after,
            frame_diff=verification.frame_diff,
            scene_diff=verification.scene_diff,
            after_observation_metadata=verification.after_observation_metadata,
            matched_by_observation=verification.matched_by_observation,
            landing_observation=verification.landing_observation,
        )

    def _finish_attempt_outcome(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        actor: str,
        before_requested: Observation | None,
        before_command: Observation | None,
        risk: RiskDecision,
        outcome: AttemptOutcome,
    ) -> AttemptExecution:
        return self._finish_attempt(
            phone,
            op=op,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            before_requested=before_requested,
            before_command=before_command,
            after=outcome.after,
            frame_diff=outcome.frame_diff,
            scene_diff=outcome.scene_diff,
            after_observation_metadata=outcome.after_observation_metadata,
            matched_by_observation=outcome.matched_by_observation,
            actor=actor,
            risk=risk,
            command_result=outcome.command_result,
            semantic=outcome.semantic,
            command_exception=outcome.command_exception,
            landing_observation=outcome.landing_observation,
        )

    def _prepare_attempt(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        attempt_index: int,
        actor: str,
        verifier_name: str,
    ) -> AttemptPreparation:
        before_requested: Observation | None = None
        before_command: Observation | None = None
        risk = self._default_attempt_risk(op)
        trace_level_override = self._trace_level_override(metadata)
        phase = "attempt setup"
        self._audit_action_started(op, metadata, group_id=group_id, attempt_id=attempt_id, attempt_index=attempt_index, actor=actor)
        try:
            phase = "before_requested"
            before_requested = self._observe_attempt_role(
                phone, role="before_requested", group_id=group_id, attempt_id=attempt_id, trace_level=trace_level_override
            )
            before_command = before_requested
            phase = "policy"
            risk = self._evaluate_attempt_risk(op, metadata, group_id=group_id, attempt_id=attempt_id)
            if risk.allowed and risk.approval_required:
                self._record_approval(
                    op=op,
                    kwargs=kwargs,
                    group_id=group_id,
                    attempt_id=attempt_id,
                    before_requested=before_requested,
                    risk=risk,
                    decision="approved",
                    decided_by=str(metadata.get("approved_by") or "policy_fixture"),
                )
                phase = "before_command"
                before_command = self._observe_attempt_role(
                    phone, role="before_command", group_id=group_id, attempt_id=attempt_id, trace_level=trace_level_override
                )
            if not risk.allowed:
                blocked = self._blocked_attempt(
                    phone,
                    op=op,
                    kwargs=kwargs,
                    metadata=metadata,
                    group_id=group_id,
                    attempt_id=attempt_id,
                    before_requested=before_requested,
                    before_command=before_command,
                    risk=risk,
                    verifier_name=verifier_name,
                    actor=actor,
                )
                return AttemptPreparation(before_requested, before_command, risk, blocked_attempt=blocked)
            if before_command is before_requested:
                phase = "before_command"
                before_command = self._observe_attempt_role(
                    phone, role="before_command", group_id=group_id, attempt_id=attempt_id, trace_level=trace_level_override
                )
            return AttemptPreparation(before_requested, before_command, risk)
        except Exception as exc:
            return AttemptPreparation(
                before_requested,
                before_command,
                risk,
                command_result=phone.failed_action_result(error=f"{type(exc).__name__}: {exc}"),
                semantic=_semantic_exception(verifier_name, exc, phase=phase),
                exception=exc,
            )

    @staticmethod
    def _default_attempt_risk(op: str) -> RiskDecision:
        return RiskDecision(
            level="medium",
            approval_required=False,
            allowed=True,
            reason="runtime exception before policy evaluation",
            source="runtime",
            metadata={"op": op},
        )

    def _audit_action_started(
        self,
        op: str,
        metadata: dict[str, Any],
        *,
        group_id: str,
        attempt_id: str,
        attempt_index: int,
        actor: str,
    ) -> None:
        self.store.audit.append(
            "action.started",
            actor=actor,
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload={"op": op, "attempt_index": attempt_index, "metadata": metadata, "actor": actor},
        )

    def _observe_attempt_role(
        self,
        phone,
        *,
        role: str,
        group_id: str,
        attempt_id: str,
        trace_level: str | None,
    ) -> Observation:
        return self._observe(
            phone,
            role=role,
            stable=False,
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            trace_level=trace_level,
        )

    def _evaluate_attempt_risk(
        self,
        op: str,
        metadata: dict[str, Any],
        *,
        group_id: str,
        attempt_id: str,
    ) -> RiskDecision:
        risk = self.risk_policy.evaluate(op, metadata)
        self.store.audit.append(
            "policy.evaluated",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=risk.to_dict(),
        )
        return risk

    def _run_command(
        self,
        phone,
        *,
        op: str,
        call: ActionCallable,
        metadata: dict[str, Any],
        attempt_id: str,
        group_id: str,
        verifier_name: str,
    ) -> CommandExecution:
        self.store.audit.append(
            "command.sent",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload={"op": op, "command": metadata},
        )
        command_exception: BaseException | None = None
        semantic: SemanticOutcome | None = None
        try:
            command_result = call()
        except Exception as exc:
            command_exception = exc
            command_result = phone.failed_action_result(error=f"{type(exc).__name__}: {exc}")
            semantic = _semantic_exception(verifier_name, exc, phase="command")

        command_payload = _result_to_command(command_result)
        self.store.audit.append(
            "command.acked" if command_result.ok else "command.failed",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=command_payload,
        )
        command_completed_at = time.monotonic()
        phone.mark_action_observation_dirty()
        return CommandExecution(
            result=command_result,
            payload=command_payload,
            completed_at=command_completed_at,
            exception=command_exception,
            semantic=semantic,
        )

    def _verify_after_successful_command(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        settle_strategy: str,
        verifier,
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        attempt_index: int,
        actor: str,
        before_requested: Observation | None,
        before_command: Observation | None,
        risk: RiskDecision,
        command_payload: dict[str, Any],
        command_completed_at: float,
        landing_retry_available: bool,
    ) -> PostCommandVerification:
        ctx = PostCommandContext(
            phone=phone,
            op=op,
            kwargs=kwargs,
            settle_strategy=settle_strategy,
            verifier=verifier,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            before_requested=before_requested,
            before_command=before_command,
            risk=risk,
            command_payload=command_payload,
            landing_retry_available=landing_retry_available,
        )
        try:
            landing_observation = self._observe_landing_after_command(
                ctx,
                attempt_index=attempt_index,
                actor=actor,
                command_completed_at=command_completed_at,
            )
        except Exception as exc:
            return self._post_command_exception(ctx, exc, phase="landing_observation")
        try:
            after_observation = self._observe_after(
                phone,
                strategy=settle_strategy,
                verifier=verifier,
                metadata=metadata,
                attempt_id=attempt_id,
                attempt_group_id=group_id,
                command_completed_at=command_completed_at,
            )
        except Exception as exc:
            return self._post_command_exception(
                ctx,
                exc,
                phase="after_observation",
                landing_observation=landing_observation,
            )
        return self._verify_after_observation(ctx, after_observation, landing_observation)

    def _observe_landing_after_command(
        self,
        ctx: PostCommandContext,
        *,
        attempt_index: int,
        actor: str,
        command_completed_at: float,
    ) -> dict[str, Any] | None:
        if not self._landing_observation_enabled(ctx.metadata):
            return None
        return self._observe_landing(
            ctx.phone,
            before_command=ctx.before_command,
            metadata=ctx.metadata,
            group_id=ctx.group_id,
            attempt_id=ctx.attempt_id,
            attempt_index=attempt_index,
            actor=actor,
            command_completed_at=command_completed_at,
        )

    def _verify_after_observation(
        self,
        ctx: PostCommandContext,
        after_observation: AfterObservation,
        landing_observation: dict[str, Any] | None,
    ) -> PostCommandVerification:
        after = after_observation.frames
        matched_by_observation = after_observation.matched_by_observation
        if ctx.settle_strategy == "no_after":
            return self._post_command_no_after(
                ctx,
                after_observation,
                landing_observation,
                "GUI verification skipped by no_after strategy",
                skipped=True,
            )
        if not after:
            return self._post_command_no_after(
                ctx,
                after_observation,
                landing_observation,
                "after observation captured no frames",
                skipped=False,
            )
        try:
            frame_diff_payload, scene_diff_payload = self._compute_diff(
                before_command=ctx.before_command, after=after, attempt_id=ctx.attempt_id, group_id=ctx.group_id,
            )
        except Exception as exc:
            return self._post_command_exception(
                ctx,
                exc,
                phase="diff",
                after=after,
                after_observation_metadata=after_observation.metadata,
                matched_by_observation=matched_by_observation,
                landing_observation=landing_observation,
            )
        try:
            semantic = self._verify_after_scenes(
                ctx.phone,
                op=ctx.op,
                kwargs=ctx.kwargs,
                metadata=ctx.metadata,
                group_id=ctx.group_id,
                attempt_id=ctx.attempt_id,
                verifier=ctx.verifier,
                before_requested=ctx.before_requested,
                before_command=ctx.before_command,
                after=after,
                settle_strategy=ctx.settle_strategy,
                frame_diff_payload=frame_diff_payload,
                scene_diff_payload=scene_diff_payload,
                command_payload=ctx.command_payload,
                risk=ctx.risk,
                matched_by_observation=matched_by_observation,
                landing_observation=landing_observation,
                landing_retry_available=ctx.landing_retry_available,
            )
        except Exception as exc:
            return self._post_command_exception(
                ctx,
                exc,
                phase="verifier",
                after=after,
                frame_diff=frame_diff_payload,
                scene_diff=scene_diff_payload,
                after_observation_metadata=after_observation.metadata,
                matched_by_observation=matched_by_observation,
                landing_observation=landing_observation,
            )
        return self._post_command_verified(
            semantic,
            after=after,
            frame_diff=frame_diff_payload,
            scene_diff=scene_diff_payload,
            after_observation=after_observation,
            matched_by_observation=matched_by_observation,
            landing_observation=landing_observation,
        )

    @staticmethod
    def _post_command_no_after(
        ctx: PostCommandContext,
        after_observation: AfterObservation,
        landing_observation: dict[str, Any] | None,
        reason: str,
        *,
        skipped: bool,
    ) -> PostCommandVerification:
        return PostCommandVerification(
            semantic=_semantic_no_after(ctx.verifier.name, reason, skipped=skipped),
            after_observation_metadata=after_observation.metadata,
            landing_observation=landing_observation,
        )

    @staticmethod
    def _post_command_verified(
        semantic: SemanticOutcome,
        *,
        after: list[Observation],
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
        after_observation: AfterObservation,
        matched_by_observation: dict[str, Any] | None,
        landing_observation: dict[str, Any] | None,
    ) -> PostCommandVerification:
        return PostCommandVerification(
            semantic=semantic,
            after=after,
            frame_diff=frame_diff,
            scene_diff=scene_diff,
            after_observation_metadata=after_observation.metadata,
            matched_by_observation=matched_by_observation,
            landing_observation=landing_observation,
        )

    def _post_command_exception(
        self,
        ctx: PostCommandContext,
        exc: Exception,
        *,
        phase: str,
        after: list[Observation] | None = None,
        frame_diff: dict[str, Any] | None = None,
        scene_diff: dict[str, Any] | None = None,
        after_observation_metadata: dict[str, Any] | None = None,
        matched_by_observation: dict[str, Any] | None = None,
        landing_observation: dict[str, Any] | None = None,
    ) -> PostCommandVerification:
        return PostCommandVerification(
            semantic=_semantic_exception(ctx.verifier.name, exc, phase=phase),
            after=after or [],
            frame_diff=frame_diff,
            scene_diff=scene_diff,
            after_observation_metadata=after_observation_metadata or {
                "settle_strategy": ctx.settle_strategy,
                "after_mode": "none",
                "trace_level": self.store.effective_trace_level(self._trace_level_override(ctx.metadata)),
            },
            matched_by_observation=matched_by_observation,
            landing_observation=landing_observation,
            exception=exc,
        )

    def _verify_after_scenes(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        verifier,
        before_requested: Observation | None,
        before_command: Observation | None,
        after: list[Observation],
        settle_strategy: str,
        frame_diff_payload: dict[str, Any] | None,
        scene_diff_payload: dict[str, Any] | None,
        command_payload: dict[str, Any],
        risk: RiskDecision,
        matched_by_observation: dict[str, Any] | None,
        landing_observation: dict[str, Any] | None,
        landing_retry_available: bool,
    ) -> SemanticOutcome:
        verifier_observations = [item for item in after if item[3] is not None]
        verifier_input = VerifierInput(
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            action={"op": op, "args": [], "kwargs": kwargs, "metadata": metadata},
            before_requested=before_requested[3] if before_requested else None,
            before_command=before_command[3] if before_command else None,
            after_scenes=[item[3] for item in verifier_observations],
            after_frame_ids=[item[0].frame_id for item in verifier_observations if item[0] is not None],
            after_scene_ids=[item[1].scene_id for item in verifier_observations if item[1] is not None],
            after_mode=self._after_mode(settle_strategy),
            frame_diff=frame_diff_payload,
            scene_diff=scene_diff_payload,
            command_result=command_payload,
            risk=risk.to_dict(),
            platform=self.platform,
            matched_by_observation=matched_by_observation,
        )
        self.store.audit.append(
            "verifier.started",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload={"verifier": verifier.name},
        )
        semantic = verifier.verify(verifier_input)
        semantic = self._semantic_after_expected_state(
            phone,
            semantic,
            metadata,
            after[-1][3] if after else None,
        )
        return self._semantic_after_landing(
            semantic,
            landing_observation,
            metadata,
            landing_retry_available=landing_retry_available,
        )

    def _blocked_attempt(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        before_requested: Observation,
        before_command: Observation,
        risk: RiskDecision,
        verifier_name: str,
        actor: str,
    ) -> AttemptExecution:
        self._record_approval(
            op=op,
            kwargs=kwargs,
            group_id=group_id,
            attempt_id=attempt_id,
            before_requested=before_requested,
            risk=risk,
            decision="denied",
            decided_by="policy",
        )
        result = ActionResult.failed(
            backend=getattr(phone, "effector_backend", lambda: "unknown")(),
            connected=False,
            error=risk.reason,
            synthetic=True,
        )
        semantic = SemanticOutcome(
            status="blocked",
            verifier=verifier_name,
            reason=risk.reason,
            verifier_version="policy",
            verification_skipped=True,
        )
        return self._finish_attempt(
            phone,
            op=op,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            before_requested=before_requested,
            before_command=before_command,
            after=[],
            frame_diff=None,
            scene_diff=None,
            after_observation_metadata={"settle_strategy": metadata.get("settle_strategy"), "after_mode": "none"},
            matched_by_observation=None,
            actor=actor,
            risk=risk,
            command_result=result,
            semantic=semantic,
            command_exception=None,
            landing_observation=None,
        )

    def _store_attempt_verification(
        self,
        *,
        attempt_id: str,
        group_id: str,
        semantic: SemanticOutcome,
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
        trace_level_override: str | None,
    ) -> tuple[str, dict[str, Any]]:
        verification_file = self.store.store_verification(attempt_id, semantic.to_dict())
        diff_files = self.store.store_diff(
            attempt_id,
            {"frame": frame_diff, "scene": scene_diff},
            trace_level=trace_level_override,
        )
        self.store.audit.append(
            "verifier.finished",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload={**semantic.to_dict(), "file": verification_file},
        )
        if semantic.disqualifying_state:
            self.store.audit.append(
                "disqualifying_state.detected",
                attempt_id=attempt_id,
                attempt_group_id=group_id,
                payload=semantic.to_dict(),
            )
        return verification_file, diff_files

    def _attempt_observation_payload(
        self,
        phone,
        *,
        metadata: dict[str, Any],
        after: list[Observation],
        matched_by_observation: dict[str, Any] | None,
        trace_level_override: str | None,
        after_observation_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        after_mode = self._after_mode(str(metadata.get("settle_strategy"))) if after else "none"
        screen_signature = self._screen_signature(after[-1][3], after[-1][2]) if after else None
        observation_payload = {
            "settle_strategy": metadata.get("settle_strategy"),
            "after_mode": after_mode,
            "matched_by_observation": matched_by_observation,
            "stable_policy": getattr(phone, "last_stability_policy", None),
            "stability_score": getattr(phone, "last_stability_score", None),
            "frame_ids": [item[0].frame_id for item in after if item[0] is not None],
            "scene_ids": [item[1].scene_id for item in after if item[1] is not None],
            "frame_count": len(after),
            "trace_level": self.store.effective_trace_level(trace_level_override),
            "screen_signature": screen_signature,
        }
        observation_payload.update(after_observation_metadata or {})
        observation_payload["after_mode"] = after_mode
        observation_payload["matched_by_observation"] = matched_by_observation
        return observation_payload

    def _attempt_action_payload(
        self,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        actor: str,
        risk: RiskDecision,
        command_result: ActionResult,
        semantic: SemanticOutcome,
        before_requested: Observation | None,
        before_command: Observation | None,
        after: list[Observation],
        after_mode: str,
        diff_files: dict[str, Any],
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
        observation_payload: dict[str, Any],
        verification_file: str,
    ) -> dict[str, Any]:
        action_payload = {
            "attempt_id": attempt_id,
            "attempt_group_id": group_id,
            "actor": actor,
            "op": op,
            "intent": {"name": kwargs.get("via") or kwargs.get("policy_action") or op},
            "risk": risk.to_dict(),
            "before_requested": self._refs(before_requested),
            "before_command": self._refs(before_command),
            "command": {"type": op, **kwargs},
            "command_result": _result_to_command(command_result),
            "after": self._refs(after[-1]) if after else None,
            "after_window": [self._refs(item) for item in after] if after and after_mode == "window" else None,
            "diff": diff_files,
            "diff_summary": {"frame": frame_diff, "scene": scene_diff},
            "observation": observation_payload,
            "semantic": semantic.to_dict(),
            "verification": verification_file,
            "status": semantic.status,
        }
        self._carry_vlm_retry_metadata(metadata, action_payload["command"])
        return action_payload

    def _append_finished_attempt(
        self,
        *,
        action_payload: dict[str, Any],
        semantic: SemanticOutcome,
        command_exception: BaseException | None,
        attempt_id: str,
        group_id: str,
    ) -> None:
        self.store.append_action(action_payload)
        self.store.audit.append(
            "action.finished" if command_exception is None else "action.exception",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload={"status": semantic.status, "exception": repr(command_exception) if command_exception else None},
        )
        self._actions.append(action_payload)

    def _build_finished_action_payload(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        actor: str,
        risk: RiskDecision,
        command_result: ActionResult,
        semantic: SemanticOutcome,
        before_requested: Observation | None,
        before_command: Observation | None,
        after: list[Observation],
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
        matched_by_observation: dict[str, Any] | None,
        landing_observation: dict[str, Any] | None,
        trace_level_override: str | None,
        after_observation_metadata: dict[str, Any] | None,
        verification_file: str,
        diff_files: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        attempt_attribution = self._attempt_attribution(
            attempt_id=attempt_id,
            group_id=group_id,
            attempt_index=int(metadata.get("attempt_index", 0) or 0),
            metadata=metadata,
            semantic=semantic,
            landing_observation=landing_observation,
            frame_diff=frame_diff,
            scene_diff=scene_diff,
            actor=actor,
        )
        after_mode = self._after_mode(str(metadata.get("settle_strategy"))) if after else "none"
        observation_payload = self._attempt_observation_payload(
            phone,
            metadata=metadata,
            after=after,
            matched_by_observation=matched_by_observation,
            trace_level_override=trace_level_override,
            after_observation_metadata=after_observation_metadata,
        )
        action_payload = self._attempt_action_payload(
            op=op,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            actor=actor,
            risk=risk,
            command_result=command_result,
            semantic=semantic,
            before_requested=before_requested,
            before_command=before_command,
            after=after,
            after_mode=after_mode,
            diff_files=diff_files,
            frame_diff=frame_diff,
            scene_diff=scene_diff,
            observation_payload=observation_payload,
            verification_file=verification_file,
        )
        if landing_observation is not None or attempt_attribution is not None:
            action_payload["actuation"] = {
                "landing_observation": landing_observation,
                "attempt_attribution": attempt_attribution,
            }
        return action_payload, attempt_attribution

    def _finish_attempt(
        self,
        phone,
        *,
        op: str,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        before_requested: Observation | None,
        before_command: Observation | None,
        after: list[Observation],
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
        after_observation_metadata: dict[str, Any] | None,
        matched_by_observation: dict[str, Any] | None,
        actor: str,
        risk: RiskDecision,
        command_result: ActionResult,
        semantic: SemanticOutcome,
        command_exception: BaseException | None,
        landing_observation: dict[str, Any] | None = None,
    ) -> AttemptExecution:
        with contextlib.suppress(Exception):
            phone.record_action(op, result=command_result, **kwargs)
        trace_level_override = self._trace_level_override(metadata)
        verification_file, diff_files = self._store_attempt_verification(
            attempt_id=attempt_id,
            group_id=group_id,
            semantic=semantic,
            frame_diff=frame_diff,
            scene_diff=scene_diff,
            trace_level_override=trace_level_override,
        )
        action_payload, attempt_attribution = self._build_finished_action_payload(
            phone,
            op=op,
            kwargs=kwargs,
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            actor=actor,
            risk=risk,
            command_result=command_result,
            semantic=semantic,
            before_requested=before_requested,
            before_command=before_command,
            after=after,
            frame_diff=frame_diff,
            scene_diff=scene_diff,
            matched_by_observation=matched_by_observation,
            landing_observation=landing_observation,
            trace_level_override=trace_level_override,
            after_observation_metadata=after_observation_metadata,
            verification_file=verification_file,
            diff_files=diff_files,
        )
        self._append_finished_attempt(
            action_payload=action_payload,
            semantic=semantic,
            command_exception=command_exception,
            attempt_id=attempt_id,
            group_id=group_id,
        )
        return AttemptExecution(
            attempt_id=attempt_id,
            result=command_result,
            semantic=semantic,
            action_payload=action_payload,
            command_exception=command_exception,
            landing_observation=landing_observation,
            attempt_attribution=attempt_attribution,
            before_page_id=self._observation_page_id(before_command),
            after_page_id=self._observation_page_id(after[-1]) if after else None,
        )

    def _record_approval(
        self,
        *,
        op: str,
        kwargs: dict[str, Any],
        group_id: str,
        attempt_id: str,
        before_requested: Observation,
        risk: RiskDecision,
        decision: str,
        decided_by: str,
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        approval_payload = {
            "approval_id": f"apv_{attempt_id}",
            "run_id": self.store.run_id,
            "attempt_group_id": group_id,
            "attempt_id": attempt_id,
            "requested_at": now,
            "risk_level": risk.level,
            "reason": risk.reason,
            "proposed_action": {"op": op, **kwargs},
            "before_frame_id": before_requested[0].frame_id if before_requested and before_requested[0] else None,
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": now,
        }
        self.store.audit.append(
            "approval.requested",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=approval_payload,
        )
        self.store.audit.append(
            f"approval.{decision}",
            actor="human" if decided_by == "human" else "runtime",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=approval_payload,
        )
        self.store.append_approval(approval_payload)

    def _compute_diff(
        self,
        *,
        before_command: Observation | None,
        after: list[Observation],
        attempt_id: str,
        group_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        before_frame = before_command[2] if before_command else None
        after_frame = after[-1][2] if after else None
        before_scene = before_command[3] if before_command else None
        after_scene = after[-1][3] if after else None
        frame_diff = compute_frame_diff(
            before_frame.img if before_frame is not None else None,
            after_frame.img if after_frame is not None else None,
        )
        scene_diff = compute_scene_diff(before_scene, after_scene)
        frame_diff_payload = frame_diff.to_dict() if frame_diff else None
        scene_diff_payload = scene_diff.to_dict() if scene_diff else None
        self.store.audit.append(
            "diff.computed",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload={"frame": frame_diff_payload, "scene": scene_diff_payload},
        )
        return frame_diff_payload, scene_diff_payload

    def _landing_window_frames(
        self,
        phone,
        *,
        group_id: str,
        attempt_id: str,
        trace_level_override: str | None,
        max_frames: int,
        interval_s: float,
    ) -> list[Observation]:
        frames: list[Observation] = []
        for index in range(max_frames):
            if index > 0 and interval_s > 0:
                time.sleep(interval_s)
            try:
                frames.append(
                    self._observe(
                        phone,
                        role="landing_window",
                        stable=False,
                        attempt_id=attempt_id,
                        attempt_group_id=group_id,
                        trace_level=trace_level_override,
                    )
                )
            except Exception as exc:
                self.store.audit.append(
                    "after_observation.failed",
                    attempt_id=attempt_id,
                    attempt_group_id=group_id,
                    payload={"role": "landing_window", "error": f"{type(exc).__name__}: {exc}"},
                )
                break
        return frames

    def _landing_diff_artifact(
        self,
        *,
        before_command: Observation | None,
        frames: list[Observation],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if metadata.get("actuation_method") == "keyboard_focus_activate":
            return self._focus_evidence_artifact(before_command, frames)
        return self._roi_diff_artifact(
            before_command[2] if before_command else None,
            [item[2] for item in frames],
            metadata.get("target_roi"),
        )

    @staticmethod
    def _landing_signal(diff_artifact: dict[str, Any], threshold: float) -> str:
        if diff_artifact.get("diff_ratio") is None:
            return "indeterminate"
        if bool(diff_artifact.get("focus_changed")) or float(diff_artifact["diff_ratio"]) > threshold:
            return "landed"
        return "missed"

    @staticmethod
    def _landing_payload(
        *,
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        attempt_index: int,
        actor: str,
        frames: list[Observation],
        diff_artifact: dict[str, Any],
        signal: str,
        threshold: float,
        started: float,
        command_completed_at: float,
    ) -> dict[str, Any]:
        return {
            "attempt_group_id": group_id,
            "attempt_id": attempt_id,
            "attempt_index": attempt_index,
            "target_identity": metadata.get("target_identity"),
            "method": metadata.get("actuation_method", "mouse_tap"),
            "control_bucket": metadata.get("control_bucket"),
            "target_roi": metadata.get("target_roi"),
            "roi_space": metadata.get("roi_space"),
            "target_point": metadata.get("target_point"),
            "target_point_frame": metadata.get("target_point_frame"),
            "landing_signal": signal,
            "landing_window_ids": {
                "frame_ids": [item[0].frame_id for item in frames if item[0] is not None],
                "scene_ids": [item[1].scene_id for item in frames if item[1] is not None],
            },
            "landing_diff_artifact": diff_artifact,
            "thresholds": {"roi_diff_ratio": threshold},
            "attributor_version": "2026-05-20.1",
            "emitted_by": "runtime",
            "action_actor": actor,
            "started_ms_after_command": int((started - command_completed_at) * 1000),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    def _observe_landing(
        self,
        phone,
        *,
        before_command: Observation | None,
        metadata: dict[str, Any],
        group_id: str,
        attempt_id: str,
        attempt_index: int,
        actor: str,
        command_completed_at: float,
    ) -> dict[str, Any]:
        trace_level_override = self._trace_level_override(metadata)
        max_frames = max(1, int(metadata.get("landing_window_frames", 1) or 1))
        interval_s = float(metadata.get("landing_sample_interval_ms", 0) or 0) / 1000.0
        started = time.monotonic()
        frames = self._landing_window_frames(
            phone,
            group_id=group_id,
            attempt_id=attempt_id,
            trace_level_override=trace_level_override,
            max_frames=max_frames,
            interval_s=interval_s,
        )
        diff_artifact = self._landing_diff_artifact(
            before_command=before_command,
            frames=frames,
            metadata=metadata,
        )
        threshold = float(metadata.get("landing_diff_threshold", 0.001) or 0.001)
        signal = self._landing_signal(diff_artifact, threshold)
        payload = self._landing_payload(
            metadata=metadata,
            group_id=group_id,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            actor=actor,
            frames=frames,
            diff_artifact=diff_artifact,
            signal=signal,
            threshold=threshold,
            started=started,
            command_completed_at=command_completed_at,
        )
        self.store.audit.append(
            "actuation.landing_observed",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=payload,
        )
        return payload

    @staticmethod
    def _focus_evidence_artifact(
        before_command: Observation | None,
        frames: list[Observation],
    ) -> dict[str, Any]:
        before_frame = before_command[2] if before_command else None
        before_scene = before_command[3] if before_command else None
        after_frames = [item[2] for item in frames if item[2] is not None]
        after_scenes = [item[3] for item in frames if item[3] is not None]
        frame_diff = compute_frame_diff(
            before_frame.img if before_frame is not None else None,
            after_frames[-1].img if after_frames else None,
        )
        scene_diff = compute_scene_diff(before_scene, after_scenes[-1] if after_scenes else None)
        diff_ratio = frame_diff.diff_ratio if frame_diff is not None else None
        scene_changed = bool(scene_diff.changed) if scene_diff is not None else False
        frame_changed = bool(frame_diff.changed) if frame_diff is not None else False
        return {
            "diff_ratio": diff_ratio,
            "changed": bool(scene_changed or frame_changed),
            "focus_changed": bool(scene_changed or frame_changed),
            "scene_diff": scene_diff.to_dict() if scene_diff is not None else None,
            "frame_diff": frame_diff.to_dict() if frame_diff is not None else None,
            "window": "post_command_focus",
        }

    @staticmethod
    def _roi_diff_artifact(before_frame: Any, after_frames: list[Any], roi: Any) -> dict[str, Any]:
        if before_frame is None or getattr(before_frame, "img", None) is None:
            return {"diff_ratio": None, "changed": None, "reason": "missing before frame"}
        if not after_frames:
            return {"diff_ratio": None, "changed": None, "reason": "missing landing frames"}
        if not isinstance(roi, dict):
            return {"diff_ratio": None, "changed": None, "reason": "missing target roi"}
        before = before_frame.img
        best_ratio: float | None = None
        best_bbox: list[int] | None = None
        for frame in after_frames:
            after = getattr(frame, "img", None)
            if after is None:
                continue
            ratio, bbox = ActionOrchestrator._roi_diff(before, after, roi)
            if best_ratio is None or ratio > best_ratio:
                best_ratio = ratio
                best_bbox = bbox
        if best_ratio is None:
            return {"diff_ratio": None, "changed": None, "reason": "landing frames had no image"}
        return {
            "diff_ratio": best_ratio,
            "changed": best_ratio > 0.001,
            "changed_bbox": best_bbox,
            "window": "post_command_short",
        }

    @staticmethod
    def _roi_diff(before: np.ndarray, after: np.ndarray, roi: dict[str, Any]) -> tuple[float, list[int] | None]:
        if before.shape != after.shape:
            height = min(before.shape[0], after.shape[0])
            width = min(before.shape[1], after.shape[1])
        else:
            height, width = before.shape[:2]
        x = max(0, min(int(roi.get("x", 0) or 0), width))
        y = max(0, min(int(roi.get("y", 0) or 0), height))
        x2 = max(x, min(x + max(0, int(roi.get("w", 0) or 0)), width))
        y2 = max(y, min(y + max(0, int(roi.get("h", 0) or 0)), height))
        if x2 <= x or y2 <= y:
            return 0.0, None
        before_roi = before[y:y2, x:x2]
        after_roi = after[y:y2, x:x2]
        delta = np.abs(before_roi.astype("int16") - after_roi.astype("int16"))
        ratio = float(delta.mean() / 255.0)
        mask = delta.mean(axis=2) > 12 if delta.ndim == 3 else delta > 12
        ys, xs = np.where(mask)
        if len(xs) == 0 or len(ys) == 0:
            return ratio, None
        return ratio, [x + int(xs.min()), y + int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]

    def _semantic_after_expected_state(
        self,
        phone,
        semantic: SemanticOutcome,
        metadata: dict[str, Any],
        after_scene: Any,
    ) -> SemanticOutcome:
        expected_payload = metadata.get("expected_state")
        if not isinstance(expected_payload, dict):
            return semantic
        if semantic.disqualifying_state:
            return semantic
        if semantic.status in {"blocked", "approval_required", "exception", "transport_failed"}:
            return semantic
        try:
            expected = ExpectedState.from_dict(expected_payload)
        except Exception:
            return semantic
        expected_semantic = verify_expected_state(expected, after_scene)
        if expected_semantic.status == "succeeded":
            return replace(
                expected_semantic,
                observation_match=semantic.observation_match,
                matched_frame_id=semantic.matched_frame_id,
                matched_scene_id=semantic.matched_scene_id,
            )
        vlm_semantic = self._maybe_vlm_verify_expected_state(
            phone,
            expected,
            semantic=semantic,
            expected_semantic=expected_semantic,
            metadata=metadata,
            after_scene=after_scene,
        )
        if vlm_semantic is not None:
            expected_semantic = vlm_semantic
        return replace(
            expected_semantic,
            observation_match=semantic.observation_match,
            matched_frame_id=semantic.matched_frame_id,
            matched_scene_id=semantic.matched_scene_id,
        )

    def _maybe_vlm_verify_expected_state(
        self,
        phone,
        expected: ExpectedState,
        *,
        semantic: SemanticOutcome,
        expected_semantic: SemanticOutcome,
        metadata: dict[str, Any],
        after_scene: Any,
    ) -> SemanticOutcome | None:
        # CUQ-1.3: the OCR verify above and a subsequent describe() both read the
        # same post-action frame (describe() enriches it in place — no re-capture,
        # no re-OCR), so for text-based expectations the VLM re-check is guaranteed
        # to read identical text. Re-perceive a fresh frame first so text that only
        # finished rendering after settle is re-read cheaply: if it now matches we
        # return succeeded WITHOUT spending the VLM call, and otherwise the fresher
        # scene becomes the basis for the VLM escalation. perceive(fresh=True)
        # short-circuits via the perceive cache when pixels are unchanged, so this
        # only re-OCRs a genuinely changed screen. Flag-gated (default off).
        if getattr(phone, "reverify_fresh_frame_enabled", False):
            fresh_scene = self._reperceive_fresh(phone)
            if fresh_scene is not None:
                fresh_semantic = verify_expected_state(expected, fresh_scene)
                if fresh_semantic.status == "succeeded":
                    return replace(
                        fresh_semantic,
                        verifier="expected_state_refresh",
                        reason=f"{fresh_semantic.reason} after fresh re-perceive",
                    )
                # Escalate to the VLM against the fresher read, not the stale one.
                after_scene = fresh_scene
                expected_semantic = fresh_semantic
        max_calls_per_action = self._int_metadata(metadata, "max_vlm_calls_per_action", 1)
        used_action_calls = self._int_metadata(metadata, "vlm_calls", 0)
        remaining_action_calls = max(0, max_calls_per_action - used_action_calls)
        gate = VLMEscalationGate(
            enabled=bool(getattr(phone, "kimi", None) is not None and not metadata.get("vlm_disabled")),
            max_calls_per_action=remaining_action_calls,
            max_calls_per_attempt=self._int_metadata(metadata, "max_vlm_calls_per_attempt", 1),
        )
        gate_input = VLMGateInput(
            ocr_confidence=self._scene_confidence(after_scene),
            target_found=expected_semantic.status == "succeeded",
            # CUQ-2.4: trigger #3 — honor a classifier conflict recorded on the
            # scene by the projector, not just an explicit metadata flag.
            classifier_conflict=bool(metadata.get("classifier_conflict", False))
            or bool(getattr(after_scene, "classifier_conflict", False)),
            verification_status=(
                "unknown"
                if semantic.status == "unknown" or expected_semantic.status in {"unknown", "no_after_scene"}
                else expected_semantic.status
            ),
        )

        def call_vlm():
            scene = phone.describe(scene_hint=f"expected_state:{expected.kind}")
            self._record_vlm_cache_fields(metadata, getattr(phone, "kimi", None))
            return scene

        scene = gate.escalate(
            gate_input,
            call_vlm,
            attempt_index=int(metadata.get("attempt_index", 0) or 0),
        )
        self._merge_vlm_audit_fields(metadata, gate.audit_fields())
        if scene is None:
            return None
        vlm_semantic = verify_expected_state(expected, scene)
        return replace(
            vlm_semantic,
            verifier="expected_state_vlm",
            reason=f"{vlm_semantic.reason} after VLM escalation",
        )

    @staticmethod
    def _reperceive_fresh(phone) -> Any | None:
        """CUQ-1.3: force a fresh capture+OCR for re-verification.

        Returns the freshly perceived scene, or None when the phone cannot
        re-perceive (no such method, or it raised) — callers then fall back to
        the existing post-action scene. perceive(fresh=True) bypasses the stale
        post-action frame; the perceive cache still short-circuits OCR when the
        new frame is pixel-identical, so an unchanged screen stays cheap.
        """
        perceive = getattr(phone, "perceive", None)
        if not callable(perceive):
            return None
        try:
            return perceive(fresh=True)
        except TypeError:
            # A phone/stub whose perceive() does not accept `fresh`.
            try:
                return perceive()
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def _int_metadata(metadata: dict[str, Any], key: str, default: int) -> int:
        try:
            return int(metadata.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _scene_confidence(scene: Any) -> float | None:
        if scene is None:
            return None
        values = [
            float(value)
            for element in getattr(scene, "elements", []) or []
            for value in [getattr(element, "confidence", None)]
            if isinstance(value, (int, float))
        ]
        if not values:
            return None
        return min(values)

    @staticmethod
    def _merge_vlm_audit_fields(metadata: dict[str, Any], fields: dict[str, Any]) -> None:
        metadata["vlm_calls"] = int(metadata.get("vlm_calls", 0) or 0) + int(fields.get("vlm_calls", 0) or 0)
        triggers = list(metadata.get("vlm_triggers") or [])
        for trigger in fields.get("vlm_triggers", []) or []:
            if trigger not in triggers:
                triggers.append(trigger)
        metadata["vlm_triggers"] = triggers
        metadata["last_vlm_trigger"] = fields.get("last_vlm_trigger") or (
            triggers[-1] if triggers else None
        )
        metadata["vlm_budget_exhausted"] = bool(
            metadata.get("vlm_budget_exhausted") or fields.get("vlm_budget_exhausted")
        )

    @staticmethod
    def _record_vlm_cache_fields(metadata: dict[str, Any], kimi: Any) -> None:
        if getattr(kimi, "last_hit", False):
            metadata["vlm_cache_hits"] = int(metadata.get("vlm_cache_hits", 0) or 0) + 1
            return
        metadata["vlm_cache_misses"] = int(metadata.get("vlm_cache_misses", 0) or 0) + 1

    @staticmethod
    def _strategy_switch_count(attempts: list[AttemptExecution]) -> int:
        switches = 0
        previous: str | None = None
        for attempt in attempts:
            command = attempt.action_payload.get("command") if attempt.action_payload else None
            strategy = command.get("strategy") if isinstance(command, dict) else None
            strategy_name = str(strategy or "")
            if previous is not None and strategy_name != previous:
                switches += 1
            previous = strategy_name
        return switches

    @staticmethod
    def _semantic_after_landing(
        semantic: SemanticOutcome,
        landing_observation: dict[str, Any] | None,
        metadata: dict[str, Any],
        *,
        landing_retry_available: bool,
    ) -> SemanticOutcome:
        if landing_observation is None:
            return semantic
        signal = landing_observation.get("landing_signal")
        method = metadata.get("actuation_method", "mouse_tap")
        if signal == "landed" and semantic.status == "unknown":
            if method == "keyboard_focus_activate":
                # A focus change IS the intended success evidence for a keyboard
                # focus activation, so the landing observation legitimately
                # resolves an unknown verification.
                return replace(
                    semantic,
                    status="succeeded",
                    reason="focus change observed after action",
                    confidence=max(semantic.confidence, 0.75),
                    retry_allowed=False,
                    observation_match=semantic.observation_match,
                )
            # CUQ-1.1: for a mouse tap, a raw ROI pixel delta (ripple, row
            # highlight, spinner, keyboard appearing, same-page reflow) is NOT
            # semantic proof of success. Verification already had the chance to
            # confirm a real navigation via scene progress and returned unknown,
            # so promoting on pixels alone double-counts evidence the verifier
            # already rejected and silently scores no-op taps as success. Keep
            # it unknown but retryable so a later strategy / re-observation can
            # still fire instead of locking the ladder with a false success.
            return replace(semantic, retry_allowed=True)
        if signal != "missed":
            return semantic
        if semantic.disqualifying_state or semantic.status in {
            "succeeded",
            "failed",
            "blocked",
            "approval_required",
            "transport_failed",
            "exception",
        }:
            return semantic
        retry_allowed = (
            ActionOrchestrator._landing_retry_allowed(metadata)
            and landing_retry_available
        )
        return replace(
            semantic,
            status="unknown" if retry_allowed else "failed",
            reason="landing_missed",
            confidence=max(semantic.confidence, 0.7),
            retry_allowed=retry_allowed,
            observation_match=semantic.observation_match,
        )

    def _attempt_attribution(
        self,
        *,
        attempt_id: str,
        group_id: str,
        attempt_index: int,
        metadata: dict[str, Any],
        semantic: SemanticOutcome,
        landing_observation: dict[str, Any] | None,
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
        actor: str,
    ) -> dict[str, Any] | None:
        if landing_observation is None:
            return None
        label = self._attribution_label(
            semantic=semantic,
            landing_observation=landing_observation,
            frame_diff=frame_diff,
            scene_diff=scene_diff,
        )
        payload = {
            "attempt_group_id": group_id,
            "attempt_id": attempt_id,
            "attempt_index": attempt_index,
            "method": metadata.get("actuation_method", "mouse_tap"),
            "label": label,
            "landing_signal": landing_observation.get("landing_signal"),
            "verifier_outcome_ref": {
                "status": semantic.status,
                "reason": semantic.reason,
                "verifier": semantic.verifier,
            },
            "emitted_by": "runtime",
            "action_actor": actor,
        }
        hint = recovery_hint(self.recovery_seed, semantic.disqualifying_state)
        if hint is not None:
            payload["recovery_hint"] = hint
        self.store.audit.append(
            "actuation.attempt_attributed",
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            payload=payload,
        )
        self.actuation_profile.record_attempt(
            control_bucket=metadata.get("control_bucket"),
            method=payload.get("method"),
            landing_signal=payload.get("landing_signal"),
            label=payload.get("label"),
            target_identity=metadata.get("target_identity"),
        )
        return payload

    @staticmethod
    def _screen_signature(scene: Any, frame: Any = None) -> str | None:
        if scene is None:
            return None
        with contextlib.suppress(Exception):
            # Feed a dhash so the perceptual-hash term in similarity() actually
            # contributes (CUQ-1.6); tolerate a missing/odd frame (phash="").
            phash = ""
            with contextlib.suppress(Exception):
                phash = dhash(getattr(frame, "img", None))
            sig = compute_signature(scene, phash=phash)
            return json.dumps(sig.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return None

    @staticmethod
    def _attribution_label(
        *,
        semantic: SemanticOutcome,
        landing_observation: dict[str, Any],
        frame_diff: dict[str, Any] | None,
        scene_diff: dict[str, Any] | None,
    ) -> str:
        landing_signal = landing_observation.get("landing_signal")
        if semantic.disqualifying_state or semantic.status in {"blocked", "approval_required"}:
            return "blocked"
        if semantic.status == "succeeded":
            return "landed_ok"
        if landing_signal == "missed":
            return "missed"
        changed = bool((scene_diff or {}).get("changed") or (frame_diff or {}).get("changed"))
        if semantic.status == "failed" and changed:
            return "wrong_target"
        if landing_signal == "landed":
            return "landed_noop"
        return "unknown"

    def _emit_group_attribution(
        self,
        group_id: str,
        *,
        actor: str,
        attempts: list[AttemptExecution],
        terminal_attempt_id: str | None,
    ) -> None:
        contributing = [
            {
                "attempt_id": attempt.attempt_id,
                "method": attempt.attempt_attribution.get("method"),
                "landing_signal": attempt.attempt_attribution.get("landing_signal"),
                "label": attempt.attempt_attribution.get("label"),
            }
            for attempt in attempts
            if attempt.attempt_attribution is not None
        ]
        if not contributing:
            return
        terminal = attempts[-1]
        terminal_attr = terminal.attempt_attribution or {}
        payload = {
            "attempt_group_id": group_id,
            "label": terminal_attr.get("label", "unknown"),
            "terminal_attempt_id": terminal_attempt_id or terminal.attempt_id,
            "terminal_method": terminal_attr.get("method"),
            "contributing_attempts": contributing,
            "verifier_outcome_ref": {
                "status": terminal.semantic.status,
                "reason": terminal.semantic.reason,
                "verifier": terminal.semantic.verifier,
            },
            "emitted_by": "runtime",
            "action_actor": actor,
        }
        self.store.audit.append(
            "actuation.attributed",
            attempt_id=terminal_attempt_id or terminal.attempt_id,
            attempt_group_id=group_id,
            payload=payload,
        )
        self._record_correction_pairs(group_id, attempts=attempts)

    def _record_correction_pairs(self, group_id: str, *, attempts: list[AttemptExecution]) -> None:
        missed: AttemptExecution | None = None
        for attempt in attempts:
            observation = attempt.landing_observation or {}
            signal = observation.get("landing_signal")
            if signal == "missed" and missed is None:
                missed = attempt
                continue
            if signal != "landed" or missed is None:
                continue
            missed_obs = missed.landing_observation or {}
            landed_obs = attempt.landing_observation or {}
            if (
                missed_obs.get("target_identity") != landed_obs.get("target_identity")
                or missed_obs.get("control_bucket") != landed_obs.get("control_bucket")
            ):
                continue
            pair = self.actuation_profile.record_correction_pair(
                control_bucket=landed_obs.get("control_bucket"),
                method=landed_obs.get("method"),
                missed_point=missed_obs.get("target_point_frame") or missed_obs.get("target_point"),
                landed_point=landed_obs.get("target_point_frame") or landed_obs.get("target_point"),
            )
            if pair is None:
                continue
            pair.update({
                "attempt_group_id": group_id,
                "target_identity": landed_obs.get("target_identity"),
                "missed_attempt_id": missed.attempt_id,
                "landed_attempt_id": attempt.attempt_id,
                "emitted_by": "runtime",
            })
            missed = None

    def _observe(
        self,
        phone,
        *,
        role: str,
        stable: bool,
        attempt_id: str,
        attempt_group_id: str,
        trace_level: str | None = None,
    ):
        scene = phone.perceive(stable=stable)
        frame = phone.last_frame
        if frame is not None:
            self.observation_buffer.append(frame, source=role)
        stored_frame = self.store.promote_frame(
            frame,
            role=role,
            stable=phone.last_stable_frame,
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            trace_level=trace_level,
        )
        stored_scene = self.store.store_scene(
            scene,
            frame_id=stored_frame.frame_id if stored_frame else None,
            role=role,
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            trace_level=trace_level,
        )
        return stored_frame, stored_scene, frame, scene

    def _observe_after(
        self,
        phone,
        *,
        strategy: str,
        verifier,
        metadata: dict[str, Any],
        attempt_id: str,
        attempt_group_id: str,
        command_completed_at: float,
    ) -> AfterObservation:
        started = time.monotonic()
        base_metadata: dict[str, Any] = {
            "settle_strategy": strategy,
            "after_mode": self._after_mode(strategy),
            "started_ms_after_command": int((started - command_completed_at) * 1000),
            "trace_level": self.store.effective_trace_level(self._trace_level_override(metadata)),
        }
        trace_level_override = self._trace_level_override(metadata)
        if strategy == "no_after":
            base_metadata.update({
                "duration_ms": 0,
                "frame_count": 0,
                "verification_skipped": True,
            })
            return AfterObservation(metadata=base_metadata)
        self._prepare_fresh_after_capture(phone, metadata=metadata, base_metadata=base_metadata)
        if strategy == "fixed_delay_after":
            return self._observe_after_fixed_delay(
                phone,
                metadata=metadata,
                started=started,
                base_metadata=base_metadata,
                attempt_id=attempt_id,
                attempt_group_id=attempt_group_id,
                trace_level=trace_level_override,
            )
        if strategy == "transient_window":
            return self._observe_after_transient_window(
                phone,
                metadata=metadata,
                started=started,
                base_metadata=base_metadata,
                attempt_id=attempt_id,
                attempt_group_id=attempt_group_id,
                trace_level=trace_level_override,
            )
        if strategy == "stream_until_match":
            return self._observe_after_stream_until_match(
                phone,
                verifier=verifier,
                metadata=metadata,
                started=started,
                base_metadata=base_metadata,
                attempt_id=attempt_id,
                attempt_group_id=attempt_group_id,
                trace_level=trace_level_override,
            )
        return self._observe_after_default(
            phone,
            strategy=strategy,
            started=started,
            base_metadata=base_metadata,
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            trace_level=trace_level_override,
        )

    def _prepare_fresh_after_capture(
        self,
        phone,
        *,
        metadata: dict[str, Any],
        base_metadata: dict[str, Any],
    ) -> None:
        fresh_delay_ms = int(metadata.get("fresh_delay_ms", 0) or 0)
        if fresh_delay_ms > 0:
            time.sleep(fresh_delay_ms / 1000.0)
        reopened = self._reopen_source_for_fresh_capture(phone) if metadata.get("fresh_source_reopen") else False
        if fresh_delay_ms > 0 or metadata.get("fresh_source_reopen"):
            phone.invalidate_perceive_cache()
            base_metadata.update({
                "fresh_delay_ms": fresh_delay_ms,
                "fresh_source_reopen": bool(metadata.get("fresh_source_reopen")),
                "fresh_source_reopened": reopened,
            })

    def _observe_after_fixed_delay(
        self,
        phone,
        *,
        metadata: dict[str, Any],
        started: float,
        base_metadata: dict[str, Any],
        attempt_id: str,
        attempt_group_id: str,
        trace_level: str | None,
    ) -> AfterObservation:
        delay_s = float(metadata.get("delay_ms", metadata.get("fixed_delay_ms", 250))) / 1000.0
        time.sleep(max(0.0, delay_s))
        frames: list[Observation] = []
        try:
            frames.append(
                self._observe(
                    phone,
                    role="after",
                    stable=False,
                    attempt_id=attempt_id,
                    attempt_group_id=attempt_group_id,
                    trace_level=trace_level,
                )
            )
        except Exception as exc:
            self._audit_after_observation_failed(exc, attempt_id=attempt_id, attempt_group_id=attempt_group_id)
        base_metadata.update({
            "fixed_delay_ms": int(delay_s * 1000),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "frame_count": len(frames),
        })
        return AfterObservation(frames=frames, metadata=base_metadata)

    def _observe_after_transient_window(
        self,
        phone,
        *,
        metadata: dict[str, Any],
        started: float,
        base_metadata: dict[str, Any],
        attempt_id: str,
        attempt_group_id: str,
        trace_level: str | None,
    ) -> AfterObservation:
        frames: list[Observation] = []
        timeout_s = float(metadata.get("window_duration_ms", metadata.get("transient_window_ms", 1800))) / 1000.0
        interval_s = float(metadata.get("sample_interval_ms", 250)) / 1000.0
        max_frames = max(1, int(metadata.get("max_stream_frames", metadata.get("max_window_frames", 8))))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and len(frames) < max_frames:
            try:
                frames.append(
                    self._observe(
                        phone,
                        role="after_window",
                        stable=False,
                        attempt_id=attempt_id,
                        attempt_group_id=attempt_group_id,
                        trace_level=trace_level,
                    )
                )
            except Exception as exc:
                self._audit_after_observation_failed(exc, attempt_id=attempt_id, attempt_group_id=attempt_group_id)
                break
            time.sleep(interval_s)
        base_metadata.update({
            "duration_ms": int((time.monotonic() - started) * 1000),
            "timeout_ms": int(timeout_s * 1000),
            "sample_interval_ms": int(interval_s * 1000),
            "max_frames": max_frames,
            "frame_count": len(frames),
        })
        return AfterObservation(frames=frames, metadata=base_metadata)

    def _observe_after_stream_until_match(
        self,
        phone,
        *,
        verifier,
        metadata: dict[str, Any],
        started: float,
        base_metadata: dict[str, Any],
        attempt_id: str,
        attempt_group_id: str,
        trace_level: str | None,
    ) -> AfterObservation:
        frames: list[Observation] = []
        matched: dict[str, Any] | None = None
        timeout_s = float(metadata.get("stream_timeout_ms", 1800)) / 1000.0
        interval_s = float(metadata.get("sample_interval_ms", 250)) / 1000.0
        max_frames = max(1, int(metadata.get("max_stream_frames", 12)))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and len(frames) < max_frames:
            try:
                observation = self._observe(
                    phone,
                    role="after_window",
                    stable=False,
                    attempt_id=attempt_id,
                    attempt_group_id=attempt_group_id,
                    trace_level=trace_level,
                )
            except Exception as exc:
                self._audit_after_observation_failed(exc, attempt_id=attempt_id, attempt_group_id=attempt_group_id)
                break
            frames.append(observation)
            matched = self._lightweight_match(verifier, observation, metadata=metadata)
            if matched is not None:
                event_type = (
                    "observation.disqualifying_state_found"
                    if matched.get("kind") == "disqualifying_state"
                    else "observation.match_found"
                )
                self.store.audit.append(
                    event_type,
                    attempt_id=attempt_id,
                    attempt_group_id=attempt_group_id,
                    payload=matched,
                )
                break
            time.sleep(interval_s)
        if matched is None:
            self.store.audit.append(
                "observation.match_timeout",
                attempt_id=attempt_id,
                attempt_group_id=attempt_group_id,
                payload={
                    "frames": len(frames),
                    "timeout_ms": int(timeout_s * 1000),
                    "sample_interval_ms": int(interval_s * 1000),
                },
            )
        base_metadata.update({
            "duration_ms": int((time.monotonic() - started) * 1000),
            "timeout_ms": int(timeout_s * 1000),
            "sample_interval_ms": int(interval_s * 1000),
            "max_frames": max_frames,
            "frame_count": len(frames),
        })
        return AfterObservation(frames=frames, matched_by_observation=matched, metadata=base_metadata)

    def _observe_after_default(
        self,
        phone,
        *,
        strategy: str,
        started: float,
        base_metadata: dict[str, Any],
        attempt_id: str,
        attempt_group_id: str,
        trace_level: str | None,
    ) -> AfterObservation:
        policy = getattr(phone, "stability_policy", None)
        stable = strategy == "stable_after" and policy is not None and policy.enabled
        try:
            frames = [
                self._observe(
                    phone,
                    role="after",
                    stable=stable,
                    attempt_id=attempt_id,
                    attempt_group_id=attempt_group_id,
                    trace_level=trace_level,
                )
            ]
        except Exception as exc:
            self._audit_after_observation_failed(exc, attempt_id=attempt_id, attempt_group_id=attempt_group_id)
            frames = []
        base_metadata.update({
            "duration_ms": int((time.monotonic() - started) * 1000),
            "frame_count": len(frames),
        })
        return AfterObservation(frames=frames, metadata=base_metadata)

    def _audit_after_observation_failed(
        self,
        exc: BaseException,
        *,
        attempt_id: str,
        attempt_group_id: str,
    ) -> None:
        self.store.audit.append(
            "after_observation.failed",
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            payload={"error": f"{type(exc).__name__}: {exc}"},
        )

    @staticmethod
    def _reopen_source_for_fresh_capture(phone) -> bool:
        source = getattr(phone, "source", None)
        close = getattr(source, "close", None)
        open_ = getattr(source, "open", None)
        if not callable(close) or not callable(open_):
            return False
        close()
        time.sleep(0.05)
        open_()
        mark_reopened = getattr(phone, "mark_fresh_source_reopened_after_action", None)
        if callable(mark_reopened):
            mark_reopened()
        return True

    @staticmethod
    def _lightweight_match(
        verifier,
        observation: Observation,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        frame, scene_ref, _raw_frame, scene = observation
        if scene is None:
            return None
        texts = [str(e.text).strip() for e in scene.elements if e.text and str(e.text).strip()]
        disqualified = detect_disqualifying_state(
            texts,
            include_home_unexpected=bool(getattr(verifier, "home_unexpected_disqualifies", False)),
        )
        if disqualified is not None:
            spec, hits = disqualified
            return {
                "kind": "disqualifying_state",
                "verifier": getattr(verifier, "name", "unknown"),
                "state": spec.state,
                "matched_evidence": hits,
                "frame_id": frame.frame_id if frame else None,
                "scene_id": scene_ref.scene_id if scene_ref else None,
            }
        if expected_match := ActionOrchestrator._lightweight_expected_match(metadata, scene, frame, scene_ref, texts):
            return expected_match
        markers = tuple(getattr(verifier, "success_markers", ()) or ())
        hits = [marker for marker in markers if any(marker in text for text in texts)]
        minimum_hits = int(getattr(verifier, "min_marker_count", getattr(verifier, "minimum_hits", 1)) or 1)
        if len(set(hits)) < minimum_hits:
            kind = scene.platform_scene_kind or scene.scene_type or scene.semantic_scene_type or ""
            if not (getattr(verifier, "name", "") == "ios_home_screen_visible" and kind == "springboard"):
                return None
        if not hits and not (
            getattr(verifier, "name", "") == "ios_home_screen_visible"
            and (scene.platform_scene_kind or scene.scene_type or scene.semantic_scene_type) == "springboard"
        ):
            return None
        return {
            "kind": "success_marker",
            "verifier": getattr(verifier, "name", "unknown"),
            "matched_evidence": hits or ["springboard"],
            "frame_id": frame.frame_id if frame else None,
            "scene_id": scene_ref.scene_id if scene_ref else None,
        }

    @staticmethod
    def _lightweight_expected_match(
        metadata: dict[str, Any] | None,
        scene,
        frame,
        scene_ref,
        texts: list[str],
    ) -> dict[str, Any] | None:
        if not isinstance(metadata, dict):
            return None
        expected_payload = metadata.get("expected_state")
        if isinstance(expected_payload, dict):
            try:
                expected = ExpectedState.from_dict(expected_payload)
                semantic = verify_expected_state(expected, scene)
            except Exception:
                semantic = None
            if semantic is not None and semantic.status == "succeeded":
                return {
                    "kind": "expected_state",
                    "verifier": "expected_state",
                    "matched_evidence": semantic.matched_evidence,
                    "frame_id": frame.frame_id if frame else None,
                    "scene_id": scene_ref.scene_id if scene_ref else None,
                }
        expected_page = metadata.get("expect_page") or metadata.get("expected_page")
        if expected_page and str(getattr(scene, "page_id", "") or "") == str(expected_page):
            return {
                "kind": "expected_page",
                "verifier": "expected_state",
                "matched_evidence": [str(expected_page)],
                "frame_id": frame.frame_id if frame else None,
                "scene_id": scene_ref.scene_id if scene_ref else None,
            }
        targets = ActionOrchestrator._metadata_text_targets(metadata)
        hits = [target for target in targets if any(target in text for text in texts)]
        if hits:
            return {
                "kind": "expected_visible",
                "verifier": "expected_state",
                "matched_evidence": hits,
                "frame_id": frame.frame_id if frame else None,
                "scene_id": scene_ref.scene_id if scene_ref else None,
            }
        return None

    @staticmethod
    def _metadata_text_targets(metadata: dict[str, Any]) -> tuple[str, ...]:
        values: list[str] = []
        for key in ("expect_visible", "expected_visible"):
            raw = metadata.get(key)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, (list, tuple)):
                values.extend(str(item) for item in raw)
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _refs(item: Observation | None) -> dict[str, Any] | None:
        if item is None:
            return None
        frame, scene, _raw_frame, _raw_scene = item
        return {
            "frame_id": frame.frame_id if frame else None,
            "scene_id": scene.scene_id if scene else None,
            "screenshot": frame.file if frame else None,
            "scene": scene.file if scene else None,
        }

    @staticmethod
    def _observation_page_id(item: Observation | None) -> str | None:
        """Minted page_id of an observation's raw scene (S5b identity signal)."""
        if item is None:
            return None
        return str(getattr(item[3], "page_id", "") or "") or None

    @staticmethod
    def _after_mode(strategy: str) -> str:
        if strategy == "no_after":
            return "none"
        if strategy in {"transient_window", "stream_until_match"}:
            return "window"
        return "single_frame"

    @staticmethod
    def _trace_level_override(metadata: dict[str, Any]) -> str | None:
        raw = metadata.get("trace_level") or metadata.get("artifact_trace_level")
        return str(raw) if raw else None

    def _next_group_id(self) -> str:
        value = f"grp_{self._group_seq:06d}"
        self._group_seq += 1
        return value

    def _next_attempt_id(self) -> str:
        value = f"act_{self._attempt_seq:06d}"
        self._attempt_seq += 1
        return value

    def _action_metadata(self, op: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(kwargs)
        metadata.setdefault("idempotent", self._default_idempotent(op))
        metadata.setdefault("settle_strategy", self._settle_strategy(op, metadata))
        # CUQ-0.11: an idempotent op (safe to re-do) gets the opt-in semantic
        # retry budget, so an `unknown` verdict actually retries instead of the
        # policy being a dead no-op. Non-idempotent ops stay at 0 (a retry could
        # double-apply). Default budget 0 → byte-identical.
        metadata.setdefault(
            "retry_budget",
            self._idempotent_retry_budget if metadata.get("idempotent") else 0,
        )
        if metadata.get("actuation_method") == "mouse_tap" and self._landing_observation_enabled(metadata):
            metadata.setdefault("landing_retry_budget", 2)
            # CUQ-0.6: a landing retry only fires on a "missed" tap (ROI
            # unchanged), so re-tapping after a no-op is safe by construction.
            # Default it on for the agent tap path so a drift/off-center first
            # tap re-grounds instead of failing after a single shot. Destructive
            # controls opt out via forbid_landing_retry.
            metadata.setdefault("landing_retry_allowed", True)
        else:
            metadata.setdefault("landing_retry_budget", 0)
        metadata.setdefault(
            "unknown_policy",
            "retry" if metadata.get("idempotent") and int(metadata.get("retry_budget", 0) or 0) > 0 else "continue",
        )
        metadata.setdefault("partial_policy", "continue")
        return metadata

    @staticmethod
    def _default_idempotent(op: str) -> bool:
        return op in {"control_center", "notification_center", "recents", "home", "scroll_wheel"}

    @staticmethod
    def _settle_strategy(op: str, metadata: dict[str, Any]) -> str:
        if "settle_strategy" in metadata:
            return str(metadata["settle_strategy"])
        if op == "recents":
            return "transient_window"
        if op in {"control_center", "notification_center", "tap", "type", "key", "paste"}:
            return "stable_after"
        return "stable_after"

    @staticmethod
    def _actor(metadata: dict[str, Any]) -> str:
        actor = str(metadata.get("actor") or metadata.get("initiator") or "agent")
        return actor if actor in {"agent", "crawler", "human", "runtime", "review", "replay"} else "agent"

    @staticmethod
    def _landing_observation_enabled(metadata: dict[str, Any]) -> bool:
        method = metadata.get("actuation_method")
        if method not in {"mouse_tap", "keyboard_focus_activate"}:
            return False
        if not isinstance(metadata.get("target_identity"), dict):
            return False
        if not isinstance(metadata.get("control_bucket"), dict):
            return False
        if method == "mouse_tap":
            return isinstance(metadata.get("target_roi"), dict) and metadata.get("roi_space") is not None
        return True

    @staticmethod
    def _landing_retry_allowed(metadata: dict[str, Any]) -> bool:
        if metadata.get("forbid_landing_retry"):
            return False
        return bool(metadata.get("landing_retry_allowed"))

    @staticmethod
    def _retry_kind(
        attempt: AttemptExecution,
        metadata: dict[str, Any],
        *,
        semantic_retries_used: int,
        retry_budget: int,
        landing_retries_used: int,
        landing_retry_budget: int,
        transport_retries_used: int = 0,
        transport_retry_budget: int = 0,
    ) -> str | None:
        if attempt.command_exception is not None:
            return None
        # CUQ-0.10: a transport failure (the effector call returned not-ok before
        # any GUI verification) means the action did NOT land, so retrying is safe
        # even for a non-idempotent op — unlike a semantic failure where the tap
        # may have partially taken effect. Retry up to the opt-in transport budget
        # (default 0 → byte-identical). Checked before the not-ok guard because a
        # transport failure carries result.ok == False.
        if attempt.semantic.status == "transport_failed":
            return "transport" if transport_retries_used < transport_retry_budget else None
        if not attempt.result.ok:
            return None
        if not attempt.semantic.retry_allowed:
            return None
        if attempt.semantic.status == "unknown" and attempt.semantic.reason == "landing_missed":
            if landing_retries_used >= landing_retry_budget:
                return None
            if not ActionOrchestrator._landing_retry_allowed(metadata):
                return None
            return "landing"
        if semantic_retries_used >= retry_budget:
            return None
        if not metadata.get("idempotent"):
            return None
        if attempt.semantic.status == "unknown":
            return "semantic" if metadata.get("unknown_policy") == "retry" else None
        if attempt.semantic.status == "partial":
            return "semantic" if metadata.get("partial_policy") == "retry" else None
        return None

    def _enrich_result(
        self,
        result: ActionResult,
        semantic: SemanticOutcome,
        attempt_id: str,
        group_id: str,
    ) -> ActionResult:
        return replace(
            result,
            semantic_status=semantic.status,
            semantic_reason=semantic.reason,
            semantic_confidence=semantic.confidence,
            semantic_verifier=semantic.verifier,
            semantic_verification_skipped=semantic.verification_skipped,
            attempt_id=attempt_id,
            attempt_group_id=group_id,
            artifact_run_dir=str(self.store.run_dir),
        )
