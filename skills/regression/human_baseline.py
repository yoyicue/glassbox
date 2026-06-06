"""Human-baseline protocol and validation for computer-use evals.

The benchmark harness can measure the agent without human help, but L2 eval
claims need a separate human control. This module keeps that control auditable:
the committed/template payload is pseudonymous, machine-validated, and uses the
same Settings root-page completion vocabulary as the agent benchmark.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY, EXPECTED_ROOT_NAV_TEXT

SCHEMA_VERSION = 1
PROTOCOL_ID = "ios_settings_readonly_walkthrough_en_hk_human_v1"
DEFAULT_BENCHMARK_REF = "skills/regression/fixtures/l2_settings_expected_state_snapshot.json"
EXPECTED_DEVICE = {
    "phone_model": "ipad_mini_7",
    "language": "en",
    "region": "HK",
}
OUTCOME_VALUES = {"succeeded", "failed", "aborted"}
PII_FIELD_NAMES = {"name", "full_name", "email", "phone", "apple_id"}
PII_TEXT_MARKERS = ("@", "Apple Account", "password")


def expected_root_pages() -> list[str]:
    """Return the canonical root labels from the Settings policy without aliases."""
    pages: list[str] = []
    seen: set[str] = set()
    for label in EXPECTED_ROOT_NAV_TEXT:
        canonical = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(label) or label
        if canonical not in seen:
            seen.add(canonical)
            pages.append(canonical)
    return pages


def template_payload(*, benchmark_ref: str = DEFAULT_BENCHMARK_REF) -> dict[str, Any]:
    pages = expected_root_pages()
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": {
            "id": PROTOCOL_ID,
            "task": "settings_readonly_walkthrough",
            "benchmark_ref": benchmark_ref,
            "device": dict(EXPECTED_DEVICE),
            "expected_root_pages": pages,
            "instructions": [
                "Start each trial at the verified Settings root page.",
                "Open each expected read-only root page once without changing settings.",
                "Record blocked or unavailable pages separately from missing required pages.",
                "Use only pseudonymous participant ids; do not record names, emails, or Apple IDs.",
            ],
        },
        "participants": [],
        "trials": [],
        "metrics": _metrics([]),
    }


def validate_human_baseline(
    payload: Mapping[str, Any],
    *,
    min_trials: int = 5,
    allow_template: bool = False,
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    protocol = payload.get("protocol")
    if not isinstance(protocol, Mapping):
        errors.append("protocol must be an object")
        protocol = {}
    _validate_protocol(protocol, errors)

    participants = payload.get("participants")
    participant_ids: set[str] = set()
    if not isinstance(participants, list):
        errors.append("participants must be a list")
        participants = []
    for idx, participant in enumerate(participants):
        _validate_participant(participant, idx, participant_ids, errors)

    trials = payload.get("trials")
    if not isinstance(trials, list):
        errors.append("trials must be a list")
        trials = []
    if not allow_template and len(trials) < min_trials:
        errors.append(f"trials must contain at least {min_trials} entries")
    expected_pages = [
        str(page) for page in protocol.get("expected_root_pages") or [] if isinstance(page, str)
    ]
    for idx, trial in enumerate(trials):
        _validate_trial(trial, idx, participant_ids, expected_pages, errors)

    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        errors.append("metrics must be an object")
    else:
        expected = _metrics([trial for trial in trials if isinstance(trial, Mapping)])
        for key, expected_value in expected.items():
            actual = metrics.get(key)
            if isinstance(expected_value, float):
                if not _is_number(actual):
                    errors.append(f"metrics.{key} must be a number")
                elif abs(float(actual) - expected_value) > 1e-9:
                    errors.append(f"metrics.{key} mismatch: {actual!r} != {expected_value!r}")
            elif actual != expected_value:
                errors.append(f"metrics.{key} mismatch: {actual!r} != {expected_value!r}")
    return errors


def _validate_protocol(protocol: Mapping[str, Any], errors: list[str]) -> None:
    if protocol.get("id") != PROTOCOL_ID:
        errors.append(f"protocol.id must be {PROTOCOL_ID!r}")
    for key in ("task", "benchmark_ref"):
        if not _is_non_empty_str(protocol.get(key)):
            errors.append(f"protocol.{key} must be a non-empty string")
    device = protocol.get("device")
    if not isinstance(device, Mapping):
        errors.append("protocol.device must be an object")
    else:
        for key, expected in EXPECTED_DEVICE.items():
            if device.get(key) != expected:
                errors.append(f"protocol.device.{key} must be {expected!r}")
    pages = protocol.get("expected_root_pages")
    if not isinstance(pages, list) or not pages:
        errors.append("protocol.expected_root_pages must be a non-empty list")
    elif any(not _is_non_empty_str(page) for page in pages):
        errors.append("protocol.expected_root_pages must contain only non-empty strings")
    elif pages != expected_root_pages():
        errors.append("protocol.expected_root_pages must equal Settings policy expected root pages")
    instructions = protocol.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        errors.append("protocol.instructions must be a non-empty list")
    elif any(not _is_non_empty_str(item) for item in instructions):
        errors.append("protocol.instructions must contain only non-empty strings")


def _validate_participant(
    participant: Any,
    idx: int,
    participant_ids: set[str],
    errors: list[str],
) -> None:
    prefix = f"participants[{idx}]"
    if not isinstance(participant, Mapping):
        errors.append(f"{prefix} must be an object")
        return
    for key in participant:
        if str(key).casefold() in PII_FIELD_NAMES:
            errors.append(f"{prefix}.{key} must not be recorded")
    participant_id = participant.get("participant_id")
    if not _is_non_empty_str(participant_id):
        errors.append(f"{prefix}.participant_id must be a non-empty string")
    elif _has_pii_marker(participant_id):
        errors.append(f"{prefix}.participant_id must be pseudonymous")
    else:
        if participant_id in participant_ids:
            errors.append(f"{prefix}.participant_id is duplicated")
        participant_ids.add(str(participant_id))
    for key in ("role", "experience"):
        if key in participant and not isinstance(participant.get(key), str):
            errors.append(f"{prefix}.{key} must be a string")


def _validate_trial(
    trial: Any,
    idx: int,
    participant_ids: set[str],
    expected_pages: Sequence[str],
    errors: list[str],
) -> None:
    prefix = f"trials[{idx}]"
    if not isinstance(trial, Mapping):
        errors.append(f"{prefix} must be an object")
        return
    for key in ("trial_id", "participant_id", "started_at", "ended_at"):
        if not _is_non_empty_str(trial.get(key)):
            errors.append(f"{prefix}.{key} must be a non-empty string")
        elif _has_pii_marker(str(trial.get(key))):
            errors.append(f"{prefix}.{key} must not contain direct identifiers")
    participant_id = trial.get("participant_id")
    if _is_non_empty_str(participant_id) and str(participant_id) not in participant_ids:
        errors.append(f"{prefix}.participant_id must reference participants")
    if trial.get("outcome") not in OUTCOME_VALUES:
        errors.append(f"{prefix}.outcome is invalid")
    for key in ("round", "duration_ms", "root_pages_expected", "root_pages_covered", "root_pages_blocked"):
        if not _is_non_negative_int(trial.get(key)):
            errors.append(f"{prefix}.{key} must be a non-negative integer")
    expected_count = len(expected_pages)
    if _is_non_negative_int(trial.get("root_pages_expected")) and expected_count and int(
        trial["root_pages_expected"]
    ) != expected_count:
        errors.append(f"{prefix}.root_pages_expected must equal protocol expected page count")
    expected = trial.get("root_pages_expected")
    covered = trial.get("root_pages_covered")
    blocked = trial.get("root_pages_blocked")
    blocked_labels = _validate_page_label_list(
        trial.get("root_pages_blocked_labels"),
        field=f"{prefix}.root_pages_blocked_labels",
        expected_pages=expected_pages,
        errors=errors,
    )
    if (
        _is_non_negative_int(blocked)
        and blocked_labels is not None
        and int(blocked) != len(blocked_labels)
    ):
        errors.append(f"{prefix}.root_pages_blocked must match root_pages_blocked_labels length")
    if _is_non_negative_int(expected) and _is_non_negative_int(blocked) and blocked > expected:
        errors.append(f"{prefix}.root_pages_blocked must not exceed root_pages_expected")
    if (
        _is_non_negative_int(expected)
        and _is_non_negative_int(covered)
        and _is_non_negative_int(blocked)
        and covered > expected - blocked
    ):
        errors.append(f"{prefix}.root_pages_covered must not exceed reachable root pages")
    missing = _validate_page_label_list(
        trial.get("root_pages_missing"),
        field=f"{prefix}.root_pages_missing",
        expected_pages=expected_pages,
        errors=errors,
    )
    if missing is not None and blocked_labels is not None and set(missing) & set(blocked_labels):
        errors.append(f"{prefix}.root_pages_missing must not overlap blocked labels")
    if trial.get("outcome") == "succeeded":
        if missing:
            errors.append(f"{prefix}.root_pages_missing must be empty for succeeded trials")
        if (
            _is_non_negative_int(expected)
            and _is_non_negative_int(covered)
            and _is_non_negative_int(blocked)
            and int(covered) != int(expected) - int(blocked)
        ):
            errors.append(f"{prefix}.root_pages_covered must equal reachable pages for succeeded trials")
    if "notes" in trial and not isinstance(trial.get("notes"), str):
        errors.append(f"{prefix}.notes must be a string")
    elif _has_pii_marker(str(trial.get("notes", ""))):
        errors.append(f"{prefix}.notes must not contain direct identifiers")


def _validate_page_label_list(
    value: Any,
    *,
    field: str,
    expected_pages: Sequence[str],
    errors: list[str],
) -> list[str] | None:
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return None
    if any(not isinstance(item, str) for item in value):
        errors.append(f"{field} must contain only strings")
        return None
    expected = set(expected_pages)
    unknown = [item for item in value if item not in expected]
    if unknown:
        errors.append(f"{field} contains labels outside protocol expected_root_pages: {unknown!r}")
    if len(set(value)) != len(value):
        errors.append(f"{field} must not contain duplicates")
    return list(value)


def _metrics(trials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(trials)
    succeeded = sum(1 for trial in trials if trial.get("outcome") == "succeeded")
    failed = sum(1 for trial in trials if trial.get("outcome") == "failed")
    aborted = sum(1 for trial in trials if trial.get("outcome") == "aborted")
    rate = succeeded / total if total else 0.0
    reachable = 0
    covered = 0
    durations: list[int] = []
    for trial in trials:
        expected = _int_or_zero(trial.get("root_pages_expected"))
        blocked = _int_or_zero(trial.get("root_pages_blocked"))
        reachable += max(0, expected - blocked)
        covered += _int_or_zero(trial.get("root_pages_covered"))
        duration = trial.get("duration_ms")
        if _is_non_negative_int(duration):
            durations.append(int(duration))
    return {
        "trial_count": total,
        "succeeded": succeeded,
        "failed": failed,
        "aborted": aborted,
        "task_completion_rate": rate,
        "task_completion_variance": rate * (1.0 - rate),
        "root_pages_coverage": covered / reachable if reachable else 0.0,
        "median_duration_ms": int(statistics.median(durations)) if durations else 0,
    }


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _int_or_zero(value: Any) -> int:
    return int(value) if _is_non_negative_int(value) else 0


def _has_pii_marker(value: str) -> bool:
    return any(marker.casefold() in value.casefold() for marker in PII_TEXT_MARKERS)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    template = sub.add_parser("template", help="Write a blank human-baseline template")
    template.add_argument("--out", type=Path, required=True)
    template.add_argument("--benchmark-ref", default=DEFAULT_BENCHMARK_REF)
    validate = sub.add_parser("validate", help="Validate a human-baseline JSON")
    validate.add_argument("path", type=Path)
    validate.add_argument("--min-trials", type=int, default=5)
    validate.add_argument("--allow-template", action="store_true")
    summarize = sub.add_parser("summarize", help="Print recomputed metrics")
    summarize.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "template":
        _write_json(args.out, template_payload(benchmark_ref=args.benchmark_ref))
        print(args.out)
        return 0
    if args.cmd == "validate":
        payload = _read_json(args.path)
        errors = validate_human_baseline(
            payload,
            min_trials=args.min_trials,
            allow_template=args.allow_template,
        )
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 2
        print("OK")
        return 0
    if args.cmd == "summarize":
        payload = _read_json(args.path)
        print(json.dumps(_metrics(payload.get("trials") or []), ensure_ascii=False, indent=2))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
