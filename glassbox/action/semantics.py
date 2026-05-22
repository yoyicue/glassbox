"""Helpers for consuming computer-use semantic action results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SemanticActionVerdict:
    accepted: bool
    status: str
    reason: str | None = None
    transport_ok: bool | None = None


def action_verdict(
    result: Any,
    *,
    unknown_policy: str = "fail",
    partial_policy: str = "fail",
    no_after_policy: str = "continue",
) -> SemanticActionVerdict:
    """Convert an optional ActionResult-like object to a caller decision.

    Legacy callers may return None. That means the action was fire-and-forget
    and has no computer-use semantic evidence, so preserve old behavior.
    """

    if result is None:
        return SemanticActionVerdict(accepted=True, status="legacy_no_result")
    transport_ok = getattr(result, "ok", None)
    if transport_ok is False:
        return SemanticActionVerdict(
            accepted=False,
            status="transport_failed",
            reason=getattr(result, "error", None),
            transport_ok=False,
        )
    status = getattr(result, "semantic_status", None)
    if status is None:
        return SemanticActionVerdict(
            accepted=transport_ok is not False,
            status="transport_only",
            reason=getattr(result, "error", None),
            transport_ok=transport_ok,
        )
    if status == "succeeded":
        return SemanticActionVerdict(True, status, getattr(result, "semantic_reason", None), transport_ok)
    if status == "unknown":
        return SemanticActionVerdict(
            unknown_policy == "continue",
            status,
            getattr(result, "semantic_reason", None),
            transport_ok,
        )
    if status == "partial":
        return SemanticActionVerdict(
            partial_policy == "continue",
            status,
            getattr(result, "semantic_reason", None),
            transport_ok,
        )
    if status == "no_after_scene":
        skipped = getattr(result, "semantic_verification_skipped", None)
        return SemanticActionVerdict(
            skipped is True and no_after_policy == "continue",
            status,
            getattr(result, "semantic_reason", None),
            transport_ok,
        )
    return SemanticActionVerdict(False, status, getattr(result, "semantic_reason", None), transport_ok)


def action_accepted(
    result: Any,
    *,
    unknown_policy: str = "fail",
    partial_policy: str = "fail",
    no_after_policy: str = "continue",
) -> bool:
    return action_verdict(
        result,
        unknown_policy=unknown_policy,
        partial_policy=partial_policy,
        no_after_policy=no_after_policy,
    ).accepted
