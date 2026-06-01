"""Tier A — verifier golden replay over the machine-harvested corpus.

The hand-curated corpus (skills/golden/computer_use/*.json) tests verifier
routing + chosen edge cases. THIS suite replays the broader machine-harvested
corpus (_harvested/, minted by skills/regression/golden_ingest.py from real run
ledgers) so a verifier-logic change (a threshold/heuristic edit) flips a recorded
status and fails offline — the gap the metrics-only regression-gate cannot see.

Anti-trap note: an empty parametrize emits ZERO pytest items and stays green, so
the per-case replay alone cannot guard a zeroed corpus — the floor test does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from glassbox.verification.golden import iter_golden_cases
from glassbox.verification.registry import VerifierRegistry
from skills.regression.golden_ingest import (
    HARVESTED_ROOT,
    harvest,
    has_source_ledgers,
)

_HARVESTED = str(HARVESTED_ROOT)
# Core action verifiers that the iPad-Settings ODD structurally exercises (taps +
# scroll/swipe/default). A minimal coverage invariant, NOT a transcribed count —
# corpus size drift is caught by `golden-audit`, not here.
_CORE_VERIFIERS = {"scene_progressed", "tap_target_effect"}


@pytest.mark.smoke
@pytest.mark.parametrize("case", iter_golden_cases(_HARVESTED), ids=lambda c: c.case_id)
def test_harvested_verifier_golden_case_replays(case):
    """Each harvested case must reproduce its recorded status through the live
    verifier. metadata.verifier pins the exact verifier that ran, so this isolates
    verifier *logic* (routing is covered by the hand-curated corpus)."""
    verifier = VerifierRegistry().resolve(case.action, case.metadata)
    outcome = verifier.verify(case.verifier_input())
    assert outcome.status == case.expected_status, (
        f"{case.case_id}: {verifier.name} -> {outcome.status} "
        f"!= recorded {case.expected_status} ({outcome.reason})"
    )
    if case.expected_disqualifying_state:
        assert outcome.disqualifying_state == case.expected_disqualifying_state


@pytest.mark.smoke
def test_harvested_corpus_nonempty_and_covers_core_verifiers():
    """ANTI-TRAP FLOOR. Empty parametrize = 0 items = vacuously green, so this is
    the load-bearing guard that the harvested corpus actually exists and is not
    degenerate to a single verifier."""
    cases = iter_golden_cases(_HARVESTED)
    assert len(cases) >= 1, "harvested corpus is empty — the replay test is vacuous"
    covered = {VerifierRegistry().resolve(c.action, c.metadata).name for c in cases}
    missing = _CORE_VERIFIERS - covered
    assert not missing, f"harvested corpus lost core verifier coverage: {missing}"


@pytest.mark.smoke
def test_harvest_is_idempotent(tmp_path):
    """Re-harvesting the source ledgers reproduces exactly the committed filename
    set (content-addressed) — enforces the no-hand-counted-baseline rule. Skips in
    CI where artifacts/ is gitignored (the committed corpus is then authoritative)."""
    if not has_source_ledgers([Path("artifacts")]):
        pytest.skip("no source ledgers (artifacts/ gitignored) — committed corpus is authoritative")
    harvest([Path("artifacts")], tmp_path)
    fresh = {p.name for p in tmp_path.glob("*.json")}
    committed = {p.name for p in Path(_HARVESTED).glob("*.json")}
    assert fresh == committed, (
        f"harvest drift — run `make golden-harvest` and commit. "
        f"added={sorted(fresh - committed)} removed={sorted(committed - fresh)}"
    )
