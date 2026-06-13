"""Harvest verifier golden-cases from run-ledger artifacts (log-sim Tier A).

Turns recorded `artifacts/run_*/actions.jsonl` ledgers into committed verifier
golden-cases under `skills/golden/computer_use/_harvested/`, so a verifier-logic
change (threshold/heuristic edit) produces an offline signal that
`test_computer_use_verifiers.py` already lacks for machine-captured scenes.

Design (see docs/design/log_sim_replay_regression.md, Tier A):
  - Reuses the committed primitives in glassbox.verification.probe_ingest.
  - Pins `metadata.verifier` to the verifier that actually ran, so replay resolves
    the same verifier (routing is already covered by the hand-curated corpus; the
    harvested corpus targets verifier *logic* on real captured texts).
  - SELF-CONSISTENCY FILTER: each candidate is immediately replayed through the
    verifier registry under the same lossy (text-only) reconstruction the test
    uses, and only kept if its recorded status reproduces. This guarantees every
    committed case is green-on-commit and deterministic.
  - Content-addressed filenames make re-ingest idempotent (no hand-counted
    baselines; `golden-audit` fails on uncommitted drift).

Privacy (hardened 2026-06-13 after an unscrubbed account display name nearly
reached the corpus from an App-Library page):
  - CROSS-RUN SCRUB UNION: the per-run scrubber only learns a value from a scene
    that structurally anchors it (e.g. the Settings account card). A *different*
    run can echo that same value in an unanchored shape (an App-Library page
    lists the display name between app labels), so its per-run scrubber never
    learns it. `harvest` therefore primes ONE union scrubber over EVERY scanned
    run's scenes (`build_union_scrubber`) and applies it as a residual pass: a
    value anchored in ANY run is scrubbed out of ALL cases. The union numbers
    placeholders in a fixed (kind, value) order so a fresh harvest is byte-stable
    across hosts, and the residual pass skips values the per-run scrubber already
    handled — so the committed corpus does not churn (no-op on already-clean runs).
  - HARVEST-INERT FACADE SESSIONS (defence in depth, not the primary net):
    `glassbox.ai` `open_phone()` probe sessions write `artifacts/run_*` ledgers
    that look harvestable but browse live screens full of personal data. They are
    skipped BY DEFAULT (`is_facade_session`, keyed on the `ai_api_version`
    manifest stamp). HONEST CAVEAT: this corpus is itself sourced from *curated*
    facade probes (run_name='manual-*'), so `make golden-harvest` opts in with
    `--include-facade`; the marker therefore cannot, on its own, tell a curated
    probe from an ad-hoc one — both carry `ai_api_version`. The default-skip
    protects a *direct* CLI caller (`python -m ...golden_ingest harvest`) who did
    not pass the flag from silently seeding the corpus with a stray scratch run,
    and replaces the old "remember to rm the scratch dir" operator discipline for
    that path. The real incident-class net is the cross-run UNION scrub above plus
    the widened repo-wide guard (skills/smoke/test_privacy_guard.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from glassbox.verification.golden import VerifierGoldenCase, iter_golden_cases
from glassbox.verification.probe_ingest import (
    golden_case_from_action,
    load_actions,
    write_golden_case,
)
from glassbox.verification.registry import VerifierRegistry
from skills.regression.scrub import Scrubber, find_personal_texts

HARVESTED_ROOT = Path("skills/golden/computer_use/_harvested")

# Load-bearing fields a VerifierGoldenCase actually consumes — the dedup key.
_FINGERPRINT_FIELDS = (
    "verifier",
    "action",
    "expected_status",
    "before_texts",
    "after_texts",
    "expected_disqualifying_state",
)


def case_fingerprint(case: dict[str, Any]) -> str:
    key = {f: case.get(f) for f in _FINGERPRINT_FIELDS}
    blob = json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _case_from_payload(payload: dict[str, Any]) -> VerifierGoldenCase:
    """Build an in-memory VerifierGoldenCase without round-tripping to disk."""
    return VerifierGoldenCase(
        case_id=str(payload["case_id"]),
        action=str(payload["action"]),
        expected_status=str(payload["expected_status"]),
        before_texts=[str(t) for t in payload.get("before_texts", [])],
        after_texts=[str(t) for t in payload.get("after_texts", [])],
        metadata=dict(payload.get("metadata", {})),
        expected_disqualifying_state=payload.get("expected_disqualifying_state"),
    )


def replays_consistently(payload: dict[str, Any], registry: VerifierRegistry) -> bool:
    """True iff the recorded status reproduces under the test's reconstruction."""
    case = _case_from_payload(payload)
    try:
        verifier = registry.resolve(case.action, case.metadata)
    except KeyError:
        # Ledgers from the semantic tap path pin verifiers (e.g. expected_state /
        # expected_state_vlm) that live in the orchestrator's expected-state
        # machinery, not the offline verifier registry — they are L2's domain,
        # not Tier-A golden material. Skip instead of crashing the harvest.
        return False
    outcome = verifier.verify(case.verifier_input())
    if outcome.status != case.expected_status:
        return False
    if case.expected_disqualifying_state:
        return outcome.disqualifying_state == case.expected_disqualifying_state
    return True


def _iter_run_scenes(run_dir: Path):
    """Yield every recorded scene of a run as an elements-bearing dict.

    Collection runs over the FULL scene payloads (boxes included — the
    connected-SSID rule is geometric), across the whole run rather than just
    the verifier-bearing before/after pairs: the Settings root shows the
    joined network and account name, and the scene that *anchors* a value
    structurally (e.g. the network list) is not always one the verifier saw.
    """
    scenes_dir = run_dir / "scenes"
    for scene_path in sorted(scenes_dir.glob("*.json")) if scenes_dir.is_dir() else []:
        try:
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(scene, dict):
            continue
        if not scene.get("elements") and isinstance(scene.get("texts"), list):
            # Older texts-only scene payloads (same shape probe_ingest accepts).
            scene = {"elements": [{"text": str(text)} for text in scene["texts"] if text]}
        yield scene


def _run_scrubber(run_dir: Path) -> Scrubber:
    """Personal-data scrubber primed on every recorded scene of THIS run.

    Per-run priming gives every committed case the same placeholder ordinals it
    has always had (numbering follows this run's scene-encounter order), so
    union-scrubbing (below) can stay a pure no-op on already-clean runs — no
    corpus churn."""
    scrubber = Scrubber()
    for scene in _iter_run_scenes(run_dir):
        scrubber.collect(scene)
    return scrubber


def build_union_scrubber(run_dirs: list[Path]) -> Scrubber:
    """A SINGLE scrubber primed across EVERY scanned run's scenes.

    Closes the cross-run leak that bit on 2026-06-13: a value structurally
    anchored in *any* one run (e.g. the account display name on the Settings
    account card) must scrub that value out of *every* harvested case, even
    cases from a different run whose own scenes never showed the anchor (an
    App-Library page can surface the bare name between app labels with no
    account-card shape, so the per-run scrubber for that run never learns it).

    Determinism: values are collected without ordinals (``collect_deferred``)
    and numbered in a fixed (kind, value) order (``finalize_union``), so a fresh
    harvest yields the same union placeholders regardless of which run is
    scanned first — fingerprints (hence committed filenames) stay stable."""
    union = Scrubber()
    for run_dir in run_dirs:
        for scene in _iter_run_scenes(run_dir):
            union.collect_deferred(scene)
    union.finalize_union()
    return union


def _scrub_payload(
    payload: dict[str, Any],
    scrubber: Scrubber,
    union: Scrubber | None = None,
) -> None:
    """Replace personal values in the case's texts (and free-text fields) with
    stable placeholders. Runs BEFORE fingerprinting so the committed filename is
    content-addressed over the scrubbed payload.

    Two passes:
      1. the PER-RUN scrubber (this run's own anchors) — byte-identical to the
         historical behaviour, so already-clean cases keep their placeholders.
      2. a residual UNION pass that scrubs only values the per-run pass did NOT
         cover (``skip`` = the per-run scrubber's values), i.e. cross-run leaks
         anchored in some OTHER scanned run. On a leak-free case this is a pure
         no-op, so the committed corpus does not churn."""
    per_run = scrubber.values()

    def _scrub(text: str | None) -> str | None:
        out = scrubber.scrub_text(text)
        if union is not None:
            out = union.scrub_text(out, skip=per_run)
        return out

    for key in ("before_texts", "after_texts"):
        payload[key] = [_scrub(text) for text in payload.get(key, [])]
    for key in ("expected_disqualifying_state",):
        if isinstance(payload.get(key), str):
            payload[key] = _scrub(payload[key])


def candidate_cases(run_dir: Path, union: Scrubber | None = None) -> list[dict[str, Any]]:
    """Verifier-bearing actions in one run, lifted to scrubbed, pinned golden
    payloads. Scrubbing happens before fingerprinting: a fresh harvest on a
    host whose ledgers contain personal values commits placeholders, never the
    values, and the content-addressed case_id is computed over the scrubbed
    texts.

    ``union`` (built by :func:`build_union_scrubber` over ALL scanned runs)
    scrubs cross-run leaks the per-run scrubber cannot learn (the 2026-06-13
    App-Library incident); it is applied as a no-op-on-clean residual pass."""
    out: list[dict[str, Any]] = []
    scrubber: Scrubber | None = None
    for action in load_actions(run_dir):
        semantic = action.get("semantic") or {}
        verifier = semantic.get("verifier")
        if not verifier or semantic.get("verification_skipped"):
            continue
        if scrubber is None:
            scrubber = _run_scrubber(run_dir)
        payload = golden_case_from_action(run_dir, action)
        _scrub_payload(payload, scrubber, union)
        # Hard post-condition: the structural detector must find nothing in the
        # scrubbed texts (placeholders are never reported, so this is stable).
        for key in ("before_texts", "after_texts"):
            pseudo_scene = {"elements": [{"text": text} for text in payload.get(key, [])]}
            leftovers = find_personal_texts(pseudo_scene)
            if leftovers:
                raise ValueError(
                    f"harvest scrub left personal data in {run_dir} {key}: "
                    f"{[(kind, idx) for kind, idx, _ in leftovers]}"
                )
        # Pin the exact verifier that ran so replay resolves it deterministically
        # (routing is exercised by the hand-curated corpus, not here).
        payload.setdefault("metadata", {})
        payload["metadata"]["verifier"] = verifier
        fp = case_fingerprint(payload)
        payload["case_id"] = f"{verifier}_{fp}"
        out.append(payload)
    return out


@dataclass
class HarvestReport:
    scanned_runs: int = 0
    runs_with_verifier: int = 0
    candidates: int = 0
    dropped_inconsistent: int = 0
    dropped_duplicate: int = 0
    kept: int = 0
    by_verifier: dict[str, int] = field(default_factory=dict)
    removed_stale: int = 0
    # True when the harvest found nothing keepable but the target corpus is
    # non-empty: pruning would have wiped the committed corpus, so it was
    # refused (see harvest(allow_empty=...)).
    aborted_wipe: bool = False

    def render(self) -> str:
        cov = ", ".join(f"{k}={v}" for k, v in sorted(self.by_verifier.items()))
        return (
            f"scanned_runs={self.scanned_runs} with_verifier={self.runs_with_verifier} "
            f"candidates={self.candidates} kept={self.kept} "
            f"dropped(inconsistent={self.dropped_inconsistent}, dup={self.dropped_duplicate}) "
            f"removed_stale={self.removed_stale}\n  coverage: {cov or '(none)'}"
        )


def is_facade_session(run_dir: Path) -> bool:
    """True for a ``glassbox.ai`` facade run (``open_phone``), detected by the
    ``ai_api_version`` manifest stamp (glassbox/ai.py ``_ensure_manifest`` →
    AI_API_VERSION). The measurement harness (run_full / floor / honest_gate)
    that writes the ``computer_use_success_rate`` baselines never sets that key.

    Used to make facade sessions HARVEST-INERT BY DEFAULT (the 2026-06-13 fix):
    they browse live Settings/App-Library and routinely surface personal values
    in scenes, so a direct CLI ``harvest`` (no ``--include-facade``) skips them
    rather than relying on the operator to ``rm`` the scratch dir.

    HONEST LIMIT: this corpus is sourced from *curated* facade probes, so the
    documented ``make golden-harvest`` passes ``--include-facade`` — the stamp
    cannot by itself separate a curated probe from an ad-hoc one. See the module
    docstring; the cross-run union scrub is the primary incident-class net.

    A run with no manifest is treated as NON-facade (fail safe toward the harness
    path — a harness run with a corrupt manifest must still be harvestable)."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(manifest, dict) and "ai_api_version" in manifest


def _iter_run_dirs(roots: list[Path], *, include_facade: bool = False):
    for root in roots:
        root = Path(root)
        if (root / "actions.jsonl").exists():
            if include_facade or not is_facade_session(root):
                yield root
            continue
        for child in sorted(root.glob("run_*")):
            if (child / "actions.jsonl").exists() and (
                include_facade or not is_facade_session(child)
            ):
                yield child


def has_source_ledgers(roots: list[Path], *, include_facade: bool = False) -> bool:
    """Whether any harvestable run ledger exists. False in CI: artifacts/ is
    gitignored, so harvest/audit are local/rig-only — the committed corpus is the
    source of truth the replay test guards."""
    return any(True for _ in _iter_run_dirs([Path(r) for r in roots], include_facade=include_facade))


def harvest(
    roots: list[Path],
    out_dir: Path,
    *,
    prune_stale: bool = True,
    allow_empty: bool = False,
    include_facade: bool = False,
) -> HarvestReport:
    out_dir = Path(out_dir)
    registry = VerifierRegistry()
    report = HarvestReport()
    seen: dict[str, dict[str, Any]] = {}  # fingerprint -> payload

    # Materialise the scanned run set once so the union scrubber can prime on
    # EVERY run's scenes before any case is scrubbed (cross-run propagation):
    # a value anchored in one run scrubs it out of every other run's cases too.
    # Facade probe sessions are skipped by default (is_facade_session) so an
    # ad-hoc open_phone run can never seed the committed corpus.
    run_dirs = list(_iter_run_dirs([Path(r) for r in roots], include_facade=include_facade))
    union = build_union_scrubber(run_dirs)

    for run_dir in run_dirs:
        report.scanned_runs += 1
        cases = candidate_cases(run_dir, union)
        if cases:
            report.runs_with_verifier += 1
        for payload in cases:
            report.candidates += 1
            if not replays_consistently(payload, registry):
                report.dropped_inconsistent += 1
                continue
            fp = case_fingerprint(payload)
            if fp in seen:
                report.dropped_duplicate += 1
                continue
            seen[fp] = payload

    out_dir.mkdir(parents=True, exist_ok=True)
    # Wipe guard: on a machine without run ledgers (every machine but the rig
    # host — artifacts/ is gitignored), a fresh harvest keeps 0 cases, and
    # prune_stale would then delete the entire committed corpus. That must be
    # an explicit decision, never a side effect of running the documented
    # refresh command on the wrong host.
    if not seen and not allow_empty and any(out_dir.glob("*.json")):
        report.aborted_wipe = True
        return report
    kept_files: set[str] = set()
    for fp, payload in seen.items():
        fname = f"{payload['metadata']['verifier']}__{fp}.json"
        write_golden_case(out_dir / fname, payload)
        kept_files.add(fname)
        report.kept += 1
        v = payload["metadata"]["verifier"]
        report.by_verifier[v] = report.by_verifier.get(v, 0) + 1

    if prune_stale:
        for existing in out_dir.glob("*.json"):
            if existing.name not in kept_files:
                existing.unlink()
                report.removed_stale += 1

    return report


def audit(roots: list[Path], against: Path, *, include_facade: bool = False) -> int:
    """rc!=0 if the committed corpus differs from a fresh harvest (drift).

    No-ops (rc 0) when no source ledgers are present — in CI artifacts/ is
    gitignored, so there is nothing to re-harvest against; the replay+floor tests
    (which need only the committed corpus) are the real guard there.

    ``include_facade`` must match the harvest setting or the fresh harvest would
    spuriously diverge from the committed corpus."""
    against = Path(against)
    if not has_source_ledgers(roots, include_facade=include_facade):
        print(
            "golden-audit SKIPPED (rc 0 BY DESIGN): no source ledgers under "
            f"{', '.join(str(r) for r in roots)} — drift can only be audited on a host "
            "with run artifacts (the rig). On ledger-free hosts (CI included) the "
            "committed corpus is guarded by the replay+floor smoke tests instead "
            "(skills/smoke/test_golden_ingest.py). Do NOT read this as 'corpus audited'."
        )
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        harvest(roots, Path(tmp), prune_stale=True, include_facade=include_facade)
        fresh = {p.name: p.read_text(encoding="utf-8") for p in Path(tmp).glob("*.json")}
    committed = {p.name: p.read_text(encoding="utf-8") for p in against.glob("*.json")}

    missing = sorted(set(fresh) - set(committed))   # a fresh harvest would add
    extra = sorted(set(committed) - set(fresh))     # committed but no longer harvested
    changed = sorted(n for n in (set(fresh) & set(committed)) if fresh[n] != committed[n])
    if not (missing or extra or changed):
        print(f"golden-audit OK: {len(committed)} cases match a fresh harvest")
        return 0
    print("golden-audit DRIFT — run `make golden-harvest` and commit:", file=sys.stderr)
    for n in missing:
        print(f"  + would add    {n}", file=sys.stderr)
    for n in extra:
        print(f"  - would remove {n}", file=sys.stderr)
    for n in changed:
        print(f"  ~ would change {n}", file=sys.stderr)
    return 1


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Harvest/audit verifier golden-cases from run ledgers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    _FACADE_HELP = (
        "Also harvest ad-hoc glassbox.ai facade probe sessions (manifests carrying "
        "ai_api_version). They are SKIPPED by default because they browse live "
        "screens and routinely surface personal values; only pass this for a run "
        "you have deliberately scrubbed/reviewed."
    )

    h = sub.add_parser("harvest", help="harvest ledgers into the committed corpus")
    h.add_argument("--roots", nargs="+", default=["artifacts"])
    h.add_argument("--out", default=str(HARVESTED_ROOT))
    h.add_argument(
        "--allow-empty",
        action="store_true",
        help=(
            "Permit a harvest that keeps 0 cases to prune (i.e. wipe) a non-empty "
            "corpus. Without this flag that situation aborts with rc 1 — it is what "
            "running the refresh on a ledger-free host looks like."
        ),
    )
    h.add_argument("--include-facade", action="store_true", help=_FACADE_HELP)

    a = sub.add_parser("audit", help="fail (rc 1) if the committed corpus drifts from a fresh harvest")
    a.add_argument("--roots", nargs="+", default=["artifacts"])
    a.add_argument("--against", default=str(HARVESTED_ROOT))
    a.add_argument("--include-facade", action="store_true", help=_FACADE_HELP)

    args = ap.parse_args(argv)
    if args.cmd == "harvest":
        report = harvest(
            [Path(r) for r in args.roots], Path(args.out),
            allow_empty=args.allow_empty, include_facade=args.include_facade,
        )
        print(report.render())
        if report.aborted_wipe:
            print(
                "golden-harvest REFUSED: the fresh harvest kept 0 cases but the corpus "
                f"at {args.out} is non-empty — pruning would WIPE the committed corpus. "
                "This is what running the refresh on a host without run ledgers looks "
                "like (artifacts/ is gitignored; only the rig host has them). Pass "
                "--allow-empty to wipe deliberately.",
                file=sys.stderr,
            )
            return 1
        # Sanity: everything just written must load and replay.
        cases = iter_golden_cases(args.out)
        print(f"corpus: {len(cases)} loadable golden cases at {args.out}")
        return 0
    if args.cmd == "audit":
        return audit(
            [Path(r) for r in args.roots], Path(args.against),
            include_facade=args.include_facade,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
