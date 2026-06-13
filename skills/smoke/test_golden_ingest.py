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

import json
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
    CI where artifacts/ is gitignored (the committed corpus is then authoritative).

    Uses include_facade=True to mirror `make golden-harvest`: this corpus is
    sourced from curated facade probes, so the idempotence check must scan the
    same run set the Makefile does (the default facade-skip is for direct CLI
    callers, not the curated refresh)."""
    if not has_source_ledgers([Path("artifacts")], include_facade=True):
        pytest.skip("no source ledgers (artifacts/ gitignored) — committed corpus is authoritative")
    harvest([Path("artifacts")], tmp_path, include_facade=True)
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


# —— privacy hardening (2026-06-13): cross-run union + harvest-inert facade ——
#
# All fixtures below use SYNTHETIC, obviously-fake personal values. The repo is
# public + MIT: never put a real display name / SSID / email in a test.
_FAKE_ACCOUNT_NAME = "Jamie Q Synthetic"  # multi-word, not a real person


def _write_scene(scenes_dir: Path, name: str, texts: list[str]) -> None:
    scenes_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "elements": [
            {"text": text, "box": {"x": 10, "y": 40 * i, "w": 200, "h": 16}, "type": "text"}
            for i, text in enumerate(texts)
        ]
    }
    (scenes_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _write_action(run_dir: Path, before_scene: str, after_scene: str, *, verifier="scene_progressed", status="succeeded") -> None:
    (run_dir / "actions.jsonl").write_text(
        json.dumps(
            {
                "op": "tap",
                "attempt_id": "att_000001",
                "attempt_group_id": "grp_000001",
                "before_command": {"scene": f"scenes/{before_scene}"},
                "after": {"scene": f"scenes/{after_scene}"},
                "semantic": {"verifier": verifier, "status": status},
            }
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.smoke
def test_harvest_union_scrubs_cross_run_unanchored_value(tmp_path):
    """THE 2026-06-13 INCIDENT, reproduced with synthetic values.

    Run A's Settings root anchors the account display name (the 'Apple Account,
    iCloud and more' subtitle right below it), so A's own scrubber learns it.
    Run B is an App-Library page that lists the SAME name as a flat text BETWEEN
    app labels — no account-card shape — so B's per-run scrubber cannot learn it.
    The union scrubber (primed across A+B) must scrub the name out of B's case."""
    from skills.regression.scrub import find_personal_texts

    run_a = tmp_path / "run_settings"
    run_b = tmp_path / "run_app_library"

    # Run A: account name anchored by the subtitle marker (per-run learns it).
    _write_scene(run_a / "scenes", "scn_000000.json",
                 ["Settings", _FAKE_ACCOUNT_NAME, "Apple Account, iCloud and more"])
    _write_scene(run_a / "scenes", "scn_000001.json",
                 ["General", "About", "Software Update"])
    _write_action(run_a, "scn_000000.json", "scn_000001.json")

    # Run B: App-Library — the same name sits between app labels, UNANCHORED.
    _write_scene(run_b / "scenes", "scn_000000.json",
                 ["App Library", "Maps", _FAKE_ACCOUNT_NAME, "Notes", "Reminders"])
    _write_scene(run_b / "scenes", "scn_000001.json",
                 ["App Library", "Search", "Recently Added", "Suggestions"])
    _write_action(run_b, "scn_000000.json", "scn_000001.json")

    # Sanity: B alone never anchors the name (structural detector finds nothing
    # in B's flat App-Library page), so a per-run-only harvest WOULD leak it.
    b_scene = json.loads((run_b / "scenes" / "scn_000000.json").read_text())
    assert not any(k == "account_name" for k, _i, _t in find_personal_texts(b_scene))

    out_dir = tmp_path / "corpus"
    report = harvest([run_a, run_b], out_dir)
    assert report.kept == 2, report.render()

    blobs = [p.read_text(encoding="utf-8") for p in out_dir.glob("*.json")]
    assert all(_FAKE_ACCOUNT_NAME not in b for b in blobs), (
        "cross-run union scrub failed: the App-Library page leaked the account name"
    )
    # The name was replaced by the account-name placeholder in B's case.
    assert any("SCRUBBED_ACCOUNT_NAME" in b for b in blobs)


@pytest.mark.smoke
def test_union_scrub_is_noop_on_already_clean_run(tmp_path):
    """No-churn proof: a run whose values are ALL anchored in its own scenes
    scrubs identically whether or not a union pass is layered on top — so the
    committed (per-run-anchored) corpus does not churn when union-scrubbing
    lands. Compares the union harvest against a per-run-only harvest byte-for-byte."""
    from skills.regression.golden_ingest import build_union_scrubber, candidate_cases

    run = tmp_path / "run_clean"
    _write_scene(run / "scenes", "scn_000000.json",
                 ["Settings", _FAKE_ACCOUNT_NAME, "Apple Account, iCloud and more"])
    _write_scene(run / "scenes", "scn_000001.json",
                 ["General", "About"])
    _write_action(run, "scn_000000.json", "scn_000001.json")

    per_run_only = candidate_cases(run, None)
    with_union = candidate_cases(run, build_union_scrubber([run]))
    assert per_run_only == with_union, "union pass churned an already-clean run"
    # And it is actually scrubbed (not vacuously equal because nothing matched).
    assert any("SCRUBBED_ACCOUNT_NAME" in t
               for c in with_union for t in c["before_texts"])


@pytest.mark.smoke
def test_union_placeholder_numbering_is_iteration_order_independent(tmp_path):
    """Determinism proof for placeholder STABILITY: the union numbers SSIDs in a
    fixed (kind, value) order, so scanning the runs in either order yields the
    same value->placeholder map (hence the same scrubbed bytes, hence stable
    fingerprints across hosts/harvests)."""
    from skills.regression.golden_ingest import build_union_scrubber

    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    _write_scene(run_a / "scenes", "scn_000000.json",
                 ["My Networks", "synthnet_alpha", "Other Networks"])
    _write_scene(run_b / "scenes", "scn_000000.json",
                 ["My Networks", "synthnet_bravo", "Other Networks"])

    forward = build_union_scrubber([run_a, run_b])._map
    backward = build_union_scrubber([run_b, run_a])._map
    assert forward == backward, "union placeholder numbering depends on scan order"
    # Deterministic: alpha < bravo, so alpha is always SSID_1.
    assert forward["synthnet_alpha"].endswith("SSID_1")
    assert forward["synthnet_bravo"].endswith("SSID_2")


@pytest.mark.smoke
def test_facade_session_is_harvest_inert_by_default(tmp_path):
    """Ad-hoc glassbox.ai probe sessions (manifests carrying ai_api_version) must
    be SKIPPED by default — the 2026-06-13 incident was a facade run that the
    harvester ingested. --include-facade is the explicit opt-in."""
    from skills.regression.golden_ingest import is_facade_session

    facade = tmp_path / "run_facade"
    _write_scene(facade / "scenes", "scn_000000.json", ["App Library", "Maps", "Notes"])
    _write_action(facade, "scn_000000.json", "scn_000000.json")
    (facade / "manifest.json").write_text(
        json.dumps({"run_id": "run_facade", "ai_api_version": "ai-api-v1"}), encoding="utf-8"
    )
    assert is_facade_session(facade) is True

    out_dir = tmp_path / "corpus"
    skipped = harvest([tmp_path], out_dir, allow_empty=True)
    assert skipped.scanned_runs == 0, "facade session was harvested despite default skip"

    included = harvest([tmp_path], out_dir, include_facade=True, allow_empty=True)
    assert included.scanned_runs == 1, "--include-facade did not re-admit the facade run"


@pytest.mark.smoke
def test_harness_run_without_facade_marker_is_harvested(tmp_path):
    """The flip side: a measurement-harness run (manifest WITHOUT ai_api_version,
    or no manifest at all) must still be harvested — the facade filter must not
    starve the legitimate corpus source."""
    from skills.regression.golden_ingest import is_facade_session

    harness = tmp_path / "run_harness"
    _write_scene(harness / "scenes", "scn_000000.json", ["Settings", "General"])
    _write_scene(harness / "scenes", "scn_000001.json", ["General", "About"])
    _write_action(harness, "scn_000000.json", "scn_000001.json")
    (harness / "manifest.json").write_text(
        json.dumps({"run_id": "run_harness", "harness_version": "git:dead", "platform": "ios"}),
        encoding="utf-8",
    )
    assert is_facade_session(harness) is False

    out_dir = tmp_path / "corpus"
    report = harvest([tmp_path], out_dir)
    assert report.scanned_runs == 1 and report.kept == 1, report.render()

    # A run with NO manifest at all fails safe toward the harness path.
    nomani = tmp_path / "run_nomani"
    _write_scene(nomani / "scenes", "scn_000000.json", ["Settings", "General"])
    _write_scene(nomani / "scenes", "scn_000001.json", ["General", "About"])
    _write_action(nomani, "scn_000000.json", "scn_000001.json")
    assert is_facade_session(nomani) is False
