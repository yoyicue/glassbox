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
    replays_consistently,
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


@pytest.mark.smoke
def test_replays_consistently_skips_unreplayable_verifier_instead_of_crashing():
    """Semantic-tap ledgers pin orchestrator-side verifiers (expected_state /
    expected_state_vlm) that the offline registry cannot replay. Harvest must
    treat them as not-replayable (skip), not crash with KeyError — otherwise
    `make check` breaks on any machine whose artifacts/ holds such a run."""
    payload = {
        "case_id": "expected_state_deadbeef",
        "action": "tap",
        "expected_status": "succeeded",
        "before_texts": ["General"],
        "after_texts": ["About"],
        "metadata": {"verifier": "expected_state"},
    }
    assert replays_consistently(payload, VerifierRegistry()) is False


@pytest.mark.smoke
def test_harvest_refuses_to_wipe_a_nonempty_corpus(tmp_path, capsys):
    """Running the documented refresh (`make golden-harvest`) on a host without
    run ledgers used to keep 0 cases and then prune-WIPE the committed corpus.
    That must be an explicit decision (--allow-empty), never a side effect."""
    from skills.regression.golden_ingest import _main

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    committed_case = corpus / "scene_progressed__deadbeef.json"
    committed_case.write_text("{}", encoding="utf-8")
    empty_roots = tmp_path / "no-ledgers"
    empty_roots.mkdir()

    rc = _main(["harvest", "--roots", str(empty_roots), "--out", str(corpus)])
    captured = capsys.readouterr()
    assert rc == 1
    assert committed_case.exists(), "the committed corpus must survive a refused harvest"
    assert "WIPE" in captured.err

    rc = _main(
        ["harvest", "--roots", str(empty_roots), "--out", str(corpus), "--allow-empty"]
    )
    assert rc == 0
    assert not committed_case.exists(), "--allow-empty is the explicit wipe path"


@pytest.mark.smoke
def test_audit_skip_on_ledger_free_host_is_loud_and_honest(tmp_path, capsys):
    """The rc-0 no-op on ledger-free hosts (CI included) is by design, but it
    must say so explicitly — 'golden-audit OK' and 'golden-audit skipped' must
    be impossible to confuse."""
    from skills.regression.golden_ingest import audit

    empty_roots = tmp_path / "no-ledgers"
    empty_roots.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    rc = audit([empty_roots], corpus)
    captured = capsys.readouterr()
    assert rc == 0
    assert "SKIPPED" in captured.out
    assert "BY DESIGN" in captured.out
    assert "Do NOT read this as 'corpus audited'" in captured.out
