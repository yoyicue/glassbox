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
def test_harvest_scrubs_personal_values_before_fingerprinting(tmp_path):
    """A fresh harvest on a host whose ledgers contain personal values must
    commit stable placeholders, never the values — and the content-addressed
    case_id must be computed over the SCRUBBED texts, so the committed corpus
    is host-independent. The SSID is collected from the network-list scene and
    substring-replaced in every scene of the run (the detail page repeats it)."""
    import json

    from skills.regression.golden_ingest import case_fingerprint

    run_dir = tmp_path / "run_0001"
    scenes = run_dir / "scenes"
    scenes.mkdir(parents=True)

    def write_scene(name: str, texts: list[str]) -> None:
        payload = {
            "elements": [
                {"text": text, "box": {"x": 10, "y": 40 * i, "w": 80, "h": 16}, "type": "text"}
                for i, text in enumerate(texts)
            ]
        }
        (scenes / name).write_text(json.dumps(payload), encoding="utf-8")

    # SSID-shaped row in a network-list scene (structural detection anchor)...
    write_scene(
        "scn_000000.json",
        ["Edit", "WLAN", "My Networks", "testnet_5g", "Other Networks"],
    )
    # ... repeated on the network detail page the tap landed on.
    write_scene(
        "scn_000001.json",
        ["testnet_5g", "Forget This Network", "Auto-Join", "Low Data Mode", "Configure IP"],
    )
    (run_dir / "actions.jsonl").write_text(
        json.dumps(
            {
                "op": "tap",
                "attempt_id": "att_000001",
                "attempt_group_id": "grp_000001",
                "before_command": {"scene": "scenes/scn_000000.json"},
                "after": {"scene": "scenes/scn_000001.json"},
                "semantic": {"verifier": "scene_progressed", "status": "succeeded"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "corpus"
    report = harvest([run_dir], out_dir)
    assert report.kept == 1, report.render()

    (case_path,) = sorted(out_dir.glob("*.json"))
    raw = case_path.read_text(encoding="utf-8")
    assert "testnet_5g" not in raw, "personal value survived the harvest scrub"
    payload = json.loads(raw)
    assert payload["before_texts"].count("SCRUBBED_SSID_1") == 1
    assert payload["after_texts"][0] == "SCRUBBED_SSID_1"
    # Fingerprint is content-addressed over the SCRUBBED payload.
    assert case_path.name == f"scene_progressed__{case_fingerprint(payload)}.json"
    assert payload["case_id"] == f"scene_progressed_{case_fingerprint(payload)}"
    # The scrubbed case replays consistently through the live registry.
    assert replays_consistently(payload, VerifierRegistry()) is True
    # Re-harvest is idempotent: same scrub, same fingerprint, same filename.
    report2 = harvest([run_dir], out_dir)
    assert report2.kept == 1
    assert [p.name for p in sorted(out_dir.glob("*.json"))] == [case_path.name]


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
