"""Verifier-alignment harness: score the outcome verifier against annotation.

SPA-Bench discipline (docs/reference/computer_use_evaluation_landscape.md §4):
a programmatic verifier must itself be validated against independent
annotation — report its precision/recall/F1, do not assume it correct. This
module provides that loop for glassbox's semantic action verifier (the
``verifications/*.verification.json`` verdicts):

  extract   pull (action, expected_state, verifier verdict, frame refs)
            samples out of recorded run dirs into a blank annotation manifest
  score     compute the verifier-vs-annotation confusion matrix and the
            success-assertion precision/recall/F1 from an annotated manifest
  validate  schema/consistency-check a manifest (committed fixtures must have
            metrics that EXACTLY match recomputation, like human_baseline)

Framing: the verifier is scored as a **success asserter**. ``succeeded`` is
the positive assertion; ``failed`` and ``unknown`` both decline to assert
success (they differ for the failed-class metrics). Annotation truth vocab:
``achieved`` / ``not_achieved`` / ``cant_tell``; ``cant_tell`` samples are
excluded from binary metrics but reported.

Honesty note: the committed fixture's annotations are produced by frame
inspection and recorded with explicit ``annotation_source`` provenance. The
underlying frames stay in local (gitignored) artifacts, so the repo carries
the verdicts + annotations + scoring, not re-verifiable pixels — the same
self-reported-alignment limitation the landscape doc flags for SPA-Bench's
own F1, stated here explicitly rather than implied away.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
VERIFIER_STATUSES = ("succeeded", "failed", "unknown")
ANNOTATIONS = ("achieved", "not_achieved", "cant_tell")
# Direct-identifier markers, mirroring human_baseline's PII discipline.
PII_MARKERS = ("@", "Apple Account", "password")


# —— extract ──────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def extract_samples(run_dir: Path) -> list[dict[str, Any]]:
    """Pair actions.jsonl records with their semantic verifier verdicts.

    Record shape (observed on current artifact runs): per-attempt records keyed
    by ``attempt_id`` (= the ``verifications/<id>.verification.json`` stem),
    with the verdict embedded as the ``semantic`` dict and the action context
    under ``op`` / ``intent`` / ``command`` / ``before_command``.
    """
    run_dir = Path(run_dir)
    samples: list[dict[str, Any]] = []
    for action in _read_jsonl(run_dir / "actions.jsonl"):
        attempt_id = action.get("attempt_id")
        semantic = action.get("semantic")
        if not isinstance(semantic, dict):
            continue
        command = action.get("command") or {}
        intent = action.get("intent") or {}
        before = action.get("before_command") or {}
        samples.append(
            {
                "sample_id": f"{run_dir.name}/{attempt_id or len(samples)}",
                "run_dir": run_dir.name,
                "action_id": attempt_id,
                "op": action.get("op"),
                "intent": intent.get("name"),
                "target": command.get("target"),
                "expected_state": command.get("expected_state"),
                "verifier": semantic.get("verifier"),
                "verifier_status": semantic.get("status"),
                "verifier_reason": semantic.get("reason"),
                "before_frame": before.get("frame_id"),
                "after_frame": semantic.get("matched_frame_id"),
                "annotation": None,
                "annotation_rationale": None,
            }
        )
    # Keep only samples that actually have a verdict to score.
    return [s for s in samples if s["verifier_status"] in VERIFIER_STATUSES]


def build_manifest(run_dirs: list[Path]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        samples.extend(extract_samples(run_dir))
    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_source": None,
        "samples": samples,
        "metrics": None,
    }


# —— score ────────────────────────────────────────────────────────


def _binary_prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def score_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    # Score only scorable rows; validate_manifest flags out-of-vocab statuses.
    annotated = [
        s
        for s in manifest.get("samples", [])
        if s.get("annotation") in ANNOTATIONS and s.get("verifier_status") in VERIFIER_STATUSES
    ]
    confusion: dict[str, dict[str, int]] = {
        vs: {ann: 0 for ann in ANNOTATIONS} for vs in VERIFIER_STATUSES
    }
    for sample in annotated:
        confusion[sample["verifier_status"]][sample["annotation"]] += 1

    decided = [s for s in annotated if s["annotation"] != "cant_tell"]
    # Success assertion: positive = verifier says succeeded.
    succ_tp = sum(1 for s in decided if s["verifier_status"] == "succeeded" and s["annotation"] == "achieved")
    succ_fp = sum(1 for s in decided if s["verifier_status"] == "succeeded" and s["annotation"] == "not_achieved")
    succ_fn = sum(1 for s in decided if s["verifier_status"] != "succeeded" and s["annotation"] == "achieved")
    # Failure assertion: positive = verifier says failed.
    fail_tp = sum(1 for s in decided if s["verifier_status"] == "failed" and s["annotation"] == "not_achieved")
    fail_fp = sum(1 for s in decided if s["verifier_status"] == "failed" and s["annotation"] == "achieved")
    fail_fn = sum(1 for s in decided if s["verifier_status"] != "failed" and s["annotation"] == "not_achieved")

    per_verifier: dict[str, dict[str, int]] = {}
    for sample in annotated:
        name = str(sample.get("verifier"))
        bucket = per_verifier.setdefault(name, {"n": 0, "agree": 0})
        bucket["n"] += 1
        agree = (sample["verifier_status"], sample["annotation"]) in (
            ("succeeded", "achieved"),
            ("failed", "not_achieved"),
            ("unknown", "cant_tell"),
        )
        bucket["agree"] += int(agree)

    return {
        "n_samples": len(manifest.get("samples", [])),
        "n_annotated": len(annotated),
        "n_decided": len(decided),
        "confusion": confusion,
        "success_assertion": _binary_prf(succ_tp, succ_fp, succ_fn),
        "failure_assertion": _binary_prf(fail_tp, fail_fp, fail_fn),
        "per_verifier_agreement": per_verifier,
    }


# —— validate ─────────────────────────────────────────────────────


def validate_manifest(
    manifest: dict[str, Any], *, require_annotations: bool = True, min_samples: int = 20
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        return [*errors, "samples must be a non-empty list"]
    if require_annotations and len(samples) < min_samples:
        errors.append(f"need >= {min_samples} samples for a citable alignment, got {len(samples)}")
    seen_ids: set[str] = set()
    for index, sample in enumerate(samples):
        where = f"samples[{index}]"
        sid = sample.get("sample_id")
        if not sid or not isinstance(sid, str):
            errors.append(f"{where}: missing sample_id")
        elif sid in seen_ids:
            errors.append(f"{where}: duplicate sample_id {sid!r}")
        else:
            seen_ids.add(sid)
        if sample.get("verifier_status") not in VERIFIER_STATUSES:
            errors.append(f"{where}: verifier_status must be one of {VERIFIER_STATUSES}")
        annotation = sample.get("annotation")
        if require_annotations:
            if annotation not in ANNOTATIONS:
                errors.append(f"{where}: annotation must be one of {ANNOTATIONS}")
            if not sample.get("annotation_rationale"):
                errors.append(f"{where}: annotated sample needs annotation_rationale")
        elif annotation is not None and annotation not in ANNOTATIONS:
            errors.append(f"{where}: annotation must be null or one of {ANNOTATIONS}")
        blob = json.dumps(sample, ensure_ascii=False)
        for marker in PII_MARKERS:
            if marker in blob:
                errors.append(f"{where}: contains direct-identifier marker {marker!r}")
    if require_annotations:
        if not manifest.get("annotation_source"):
            errors.append("annotation_source provenance is required for an annotated manifest")
        recorded = manifest.get("metrics")
        if recorded is None:
            errors.append("annotated manifest must record metrics (run `score` and paste)")
        else:
            recomputed = score_manifest(manifest)
            if recorded != recomputed:
                errors.append("metrics do not match recomputation (re-run `score`)")
    return errors


# —— CLI ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outcome-verifier alignment (extract/score/validate)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    extract = sub.add_parser("extract", help="Build a blank annotation manifest from run dirs")
    extract.add_argument("run_dirs", nargs="+", type=Path)
    extract.add_argument("--out", type=Path, required=True)

    score = sub.add_parser("score", help="Score an annotated manifest; prints metrics JSON")
    score.add_argument("manifest", type=Path)

    validate = sub.add_parser("validate", help="Validate a manifest (rc 0 ok / 2 errors)")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--allow-blank", action="store_true")
    validate.add_argument("--min-samples", type=int, default=20)

    args = parser.parse_args(argv)
    if args.cmd == "extract":
        manifest = build_manifest(args.run_dirs)
        args.out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{args.out} ({len(manifest['samples'])} samples)")
        return 0
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.cmd == "score":
        print(json.dumps(score_manifest(payload), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "validate":
        errors = validate_manifest(
            payload,
            require_annotations=not args.allow_blank,
            min_samples=args.min_samples,
        )
        for error in errors:
            print(f"ERROR: {error}")
        if errors:
            return 2
        print("OK")
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
