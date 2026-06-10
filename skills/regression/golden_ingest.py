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


def candidate_cases(run_dir: Path) -> list[dict[str, Any]]:
    """Verifier-bearing actions in one run, lifted to pinned golden payloads."""
    out: list[dict[str, Any]] = []
    for action in load_actions(run_dir):
        semantic = action.get("semantic") or {}
        verifier = semantic.get("verifier")
        if not verifier or semantic.get("verification_skipped"):
            continue
        payload = golden_case_from_action(run_dir, action)
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

    def render(self) -> str:
        cov = ", ".join(f"{k}={v}" for k, v in sorted(self.by_verifier.items()))
        return (
            f"scanned_runs={self.scanned_runs} with_verifier={self.runs_with_verifier} "
            f"candidates={self.candidates} kept={self.kept} "
            f"dropped(inconsistent={self.dropped_inconsistent}, dup={self.dropped_duplicate}) "
            f"removed_stale={self.removed_stale}\n  coverage: {cov or '(none)'}"
        )


def _iter_run_dirs(roots: list[Path]):
    for root in roots:
        root = Path(root)
        if (root / "actions.jsonl").exists():
            yield root
            continue
        for child in sorted(root.glob("run_*")):
            if (child / "actions.jsonl").exists():
                yield child


def has_source_ledgers(roots: list[Path]) -> bool:
    """Whether any harvestable run ledger exists. False in CI: artifacts/ is
    gitignored, so harvest/audit are local/rig-only — the committed corpus is the
    source of truth the replay test guards."""
    return any(True for _ in _iter_run_dirs([Path(r) for r in roots]))


def harvest(
    roots: list[Path],
    out_dir: Path,
    *,
    prune_stale: bool = True,
) -> HarvestReport:
    out_dir = Path(out_dir)
    registry = VerifierRegistry()
    report = HarvestReport()
    seen: dict[str, dict[str, Any]] = {}  # fingerprint -> payload

    for run_dir in _iter_run_dirs([Path(r) for r in roots]):
        report.scanned_runs += 1
        cases = candidate_cases(run_dir)
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


def audit(roots: list[Path], against: Path) -> int:
    """rc!=0 if the committed corpus differs from a fresh harvest (drift).

    No-ops (rc 0) when no source ledgers are present — in CI artifacts/ is
    gitignored, so there is nothing to re-harvest against; the replay+floor tests
    (which need only the committed corpus) are the real guard there."""
    against = Path(against)
    if not has_source_ledgers(roots):
        print("golden-audit skipped: no source ledgers (artifacts/ gitignored)")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        harvest(roots, Path(tmp), prune_stale=True)
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

    h = sub.add_parser("harvest", help="harvest ledgers into the committed corpus")
    h.add_argument("--roots", nargs="+", default=["artifacts"])
    h.add_argument("--out", default=str(HARVESTED_ROOT))

    a = sub.add_parser("audit", help="fail (rc 1) if the committed corpus drifts from a fresh harvest")
    a.add_argument("--roots", nargs="+", default=["artifacts"])
    a.add_argument("--against", default=str(HARVESTED_ROOT))

    args = ap.parse_args(argv)
    if args.cmd == "harvest":
        report = harvest([Path(r) for r in args.roots], Path(args.out))
        print(report.render())
        # Sanity: everything just written must load and replay.
        cases = iter_golden_cases(args.out)
        print(f"corpus: {len(cases)} loadable golden cases at {args.out}")
        return 0
    if args.cmd == "audit":
        return audit([Path(r) for r in args.roots], Path(args.against))
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
