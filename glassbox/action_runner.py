"""Action execution, recording, and fresh-frame verification for Phone."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from glassbox.action.actuation import ActuationPlan
from glassbox.cognition import Scene

if TYPE_CHECKING:
    from glassbox.effector import ActionResult


class ActionRunner:
    """Owns action behavior while Phone keeps the public facade."""

    def __init__(self, phone: Any) -> None:
        self._phone = phone
        self._context = phone.action_context

    def record_action(self, op: str, *, result=None, **kwargs) -> None:
        host = self._phone
        context = self._context
        action_kwargs = {**kwargs, **self.action_result_fields(result)}
        if host.recorder is not None:
            host.recorder.action(op, **action_kwargs)
        from glassbox.memory.schema import ActionRecord

        context.pending_actions_for_memory.append(ActionRecord.from_op(op, action_kwargs))
        context.needs_stable_frame = True
        context.fresh_source_reopened_after_action = False
        host.invalidate_perceive_cache()

    def failed_action_result(
        self,
        *,
        error: str,
        unsupported: bool = False,
    ) -> ActionResult:
        from glassbox.effector import ActionResult

        host = self._phone
        connected = False
        is_connected = getattr(host.effector, "is_connected", None)
        if callable(is_connected):
            try:
                connected = bool(is_connected())
            except Exception:
                connected = False
        return ActionResult.failed(
            backend=host.effector_backend(),
            connected=connected,
            error=error,
            unsupported=unsupported,
        )

    def execute_action(self, op: str, call, **kwargs) -> ActionResult:
        host = self._phone
        context = self._context
        if host.action_orchestrator is not None:
            orchestrator_kwargs = {key: value for key, value in kwargs.items() if not key.startswith("_semantic_")}
            return host.action_orchestrator.execute(host, op, call, **orchestrator_kwargs)
        if isinstance(call, ActuationPlan):
            plan = call
            command = plan.command_for_attempt(0)
            call = command.call
            kwargs = {**kwargs, **plan.metadata(), **command.kwargs}
        semantic_verify = bool(kwargs.pop("_semantic_verify", False))
        semantic_verify_action = str(kwargs.pop("_semantic_verify_action", op))
        semantic_verify_delay_ms = int(kwargs.pop("_semantic_verify_delay_ms", 0) or 0)
        semantic_verify_reopen_source = bool(kwargs.pop("_semantic_verify_reopen_source", False))
        before_frame = context.last_frame
        before_scene = context.last_scene
        context.needs_stable_frame = True
        context.fresh_source_reopened_after_action = False
        host.invalidate_perceive_cache()
        try:
            result = call()
        except Exception as exc:
            result = self.failed_action_result(
                error=f"{type(exc).__name__}: {exc}",
            )
            self.record_action(op, result=result, **kwargs)
            raise
        if semantic_verify and result is not None and getattr(result, "ok", True):
            result = self.verify_fresh_action_result(
                semantic_verify_action,
                result,
                metadata=kwargs,
                before_frame=before_frame,
                before_scene=before_scene,
                delay_ms=semantic_verify_delay_ms,
                reopen_source=semantic_verify_reopen_source,
            )
        self.record_action(op, result=result, **kwargs)
        if host.action_fail_fast and result is not None and getattr(result, "ok", True) is False:
            detail = getattr(result, "error", None) or "reported action failure"
            raise RuntimeError(f"{op} failed: {detail}")
        return result

    def run_semantic_plan(
        self,
        op: str,
        *,
        expected_state=None,
        actor: str = "agent",
        params: dict[str, Any] | None = None,
        **exec_kwargs: Any,
    ) -> ActionResult:
        from glassbox.action.semantic_plan import default_semantic_action_plan

        host = self._phone
        plan = default_semantic_action_plan(host, op, expected_state, **(params or {}))
        previous = host.in_semantic_plan
        host.set_semantic_plan_active(True)
        try:
            return host.action_orchestrator.execute(host, op, plan, actor=actor, **exec_kwargs)
        finally:
            host.set_semantic_plan_active(previous)

    def verify_fresh_action_result(
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
        from glassbox.verification import DEFAULT_REGISTRY

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
                semantic = self._verify_fresh_sample(
                    verifier,
                    action=action,
                    result=result,
                    metadata=metadata,
                    before_frame=before_frame,
                    before_scene=before_scene,
                    reopen_source=reopen_source,
                )
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

    def _verify_fresh_sample(
        self,
        verifier,
        *,
        action: str,
        result: ActionResult,
        metadata: dict,
        before_frame,
        before_scene: Scene | None,
        reopen_source: bool,
    ):
        from glassbox.verification import VerifierInput, compute_frame_diff, compute_scene_diff

        host = self._phone
        if reopen_source:
            host.reopen_source_for_fresh_capture()
        host.invalidate_perceive_cache()
        after_frame, after_scene = self.fresh_scene_for_verification(
            stable=True if host.stability_policy is not None else None,
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
        return verifier.verify(verifier_input)

    def fresh_scene_for_verification(self, *, stable: bool | None):
        host = self._phone
        context = self._context
        frame = host.snapshot(stable=stable)
        frame_id = int(frame.ts * 1000)
        scene = Scene(
            frame_id=frame_id,
            timestamp=frame.ts,
            elements=host.perceptor.recognize_elements(frame),
            source_frame_ids=[frame_id],
            source_timestamps=[frame.ts],
            observation_mode=context.last_observation_mode,
            stable_frame=context.last_stable_frame,
            viewport_size=(int(frame.img.shape[1]), int(frame.img.shape[0])),
        )
        if host.typer is not None:
            host.typer.upgrade(scene, frame_img=frame.img)
        host.apply_profile(scene, frame.img)
        host.apply_scene_classifiers(scene, frame.img)
        host.perceptor.set_last_scene(scene, frame)
        context.cache_frame = None
        context.cache_scene = None
        context.needs_stable_frame = False
        return frame, scene

    @staticmethod
    def action_result_fields(result) -> dict:
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


__all__ = ["ActionRunner"]
