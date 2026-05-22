from __future__ import annotations

import pytest

from glassbox.action.semantics import action_verdict
from glassbox.effector import ActionResult


@pytest.mark.smoke
def test_no_after_scene_skipped_is_accepted_by_default():
    result = ActionResult(
        ok=True,
        backend="fake",
        connected=True,
        semantic_status="no_after_scene",
        semantic_reason="GUI verification skipped by no_after strategy",
        semantic_verification_skipped=True,
    )

    verdict = action_verdict(result)

    assert verdict.accepted is True
    assert verdict.status == "no_after_scene"


@pytest.mark.smoke
def test_no_after_scene_without_skip_is_rejected():
    result = ActionResult(
        ok=True,
        backend="fake",
        connected=True,
        semantic_status="no_after_scene",
        semantic_reason="after observation captured no frames",
        semantic_verification_skipped=False,
    )

    verdict = action_verdict(result)

    assert verdict.accepted is False
    assert verdict.status == "no_after_scene"


@pytest.mark.smoke
@pytest.mark.parametrize("status", ["transport_failed", "exception"])
def test_terminal_runtime_statuses_are_rejected(status: str):
    result = ActionResult(
        ok=True,
        backend="fake",
        connected=True,
        semantic_status=status,
        semantic_reason=f"{status} reason",
    )

    verdict = action_verdict(result)

    assert verdict.accepted is False
    assert verdict.status == status
