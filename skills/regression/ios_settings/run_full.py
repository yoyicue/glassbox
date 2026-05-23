"""Run the read-only iOS Settings walkthrough and verify its report.

Single onboarding entry point once the PicoKVM rig is healthy:

    GLASSBOX_PICOKVM=1 uv run python -m skills.regression.ios_settings.run_full

Fast first-run smoke (a few pages, no exhaustive coverage):

    GLASSBOX_PICOKVM=1 uv run python -m skills.regression.ios_settings.run_full --quick

Check readiness only (no walkthrough):

    GLASSBOX_PICOKVM=1 uv run python -m skills.regression.ios_settings.diagnose --require-ready --json

The crawler is read-only: it foregrounds Settings through SpringBoard helpers,
opens navigation rows, observes page text, and returns via the visible back
affordance. It never changes a setting. The run writes a JSON report (and
artifacts) so a newcomer can confirm the whole perception → action →
verification pipeline works end to end.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

from glassbox.config import get_config
from glassbox.runtime import RuntimeUnavailable, build_phone, make_source
from skills.regression.ios_settings import diagnose as diagnose_mod
from skills.regression.ios_settings.config import SettingsRunConfig, build_full_run_env
from skills.regression.ios_settings.crawler import (
    SettingsCrawlerUnavailable,
    crawl_readonly_settings,
)
from skills.regression.ios_settings.verify_report import validate_report

# A quick run trades exhaustive coverage for a fast confidence check: visit a
# handful of root pages instead of every expected page.
_QUICK_ENV_OVERRIDES = {
    "IOS_SETTINGS_REQUIRE_EXHAUSTIVE": "0",
    "IOS_SETTINGS_MAX_PAGES": "8",
    "IOS_SETTINGS_MAX_DEPTH": "1",
    "IOS_SETTINGS_MIN_PAGES": "2",
}

# Drill-down: actually open each root section's detail page (depth 1) instead of
# only recording which root rows are visible, and save a per-page screenshot.
# This is what produces verifiable evidence that a section was entered, not just
# seen on the scrolled root list.
_DRILL_DOWN_ENV_OVERRIDES = {
    "IOS_SETTINGS_CHILD_NAVIGATION_ENABLED": "1",
    "IOS_SETTINGS_ROOT_COVERAGE_MODE": "0",
    "IOS_SETTINGS_SAVE_VIEW_SNAPSHOTS": "1",
    "IOS_SETTINGS_MAX_DEPTH": "1",
}


@contextlib.contextmanager
def _temporary_env(env: dict[str, str]) -> Iterator[None]:
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(env)
        get_config.cache_clear()
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)
        get_config.cache_clear()


def _run_diagnose(env: dict[str, str], diagnose_report: Path, *, require_ready: bool) -> int:
    with _temporary_env(env):
        report = diagnose_mod.diagnose(get_config())
        diagnose_mod._print_human(report)
    diagnose_report.parent.mkdir(parents=True, exist_ok=True)
    diagnose_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if require_ready and not report["ready"]["ok"]:
        print(f"ERROR: PicoKVM rig not ready; see {diagnose_report}")
        return 1
    return 0


def _run_crawler(env: dict[str, str]) -> int:
    print("+ crawl_readonly_settings", flush=True)
    runtime = None
    source = None
    try:
        with _temporary_env(env):
            cfg = get_config()
            source = make_source(cfg=cfg)
            runtime = build_phone(source=source, cfg=cfg)
            crawl_readonly_settings(
                runtime.phone,
                config=SettingsRunConfig.from_env(),
                require_real_effector=True,
            )
    except (RuntimeUnavailable, SettingsCrawlerUnavailable) as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        if runtime is not None:
            runtime.close(close_source=True)
        elif source is not None and hasattr(source, "close"):
            with contextlib.suppress(Exception):
                source.close()
    return 0


def _verify_report(report: Path, *, expected_run_id: str, require_exhaustive: bool) -> int:
    payload = json.loads(report.read_text(encoding="utf-8"))
    errors = validate_report(
        payload,
        require_exhaustive=require_exhaustive,
        expected_run_id=expected_run_id,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run and verify the read-only iOS Settings walkthrough")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("/tmp/ios-settings-full.json"),
        help="JSON report path written by the walkthrough and checked by the verifier.",
    )
    parser.add_argument(
        "--diagnose-report",
        type=Path,
        default=None,
        help="JSON preflight report path. Defaults to <report stem>.diagnose.json next to --report.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Fast first-run smoke: a few pages, non-exhaustive, lenient verification.",
    )
    parser.add_argument("--skip-diagnose", action="store_true", help="Skip the PicoKVM readiness preflight.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip report verification.")
    parser.add_argument(
        "--drill-down",
        action="store_true",
        help="Open each root section's detail page (depth 1) and save a per-page "
        "screenshot, instead of only recording which root rows are visible. "
        "Snapshots go under IOS_SETTINGS_ARTIFACT_DIR (or <report>.artifacts).",
    )
    parser.add_argument(
        "--memory-dir",
        type=Path,
        default=None,
        help="UTG memory directory for this run. Defaults to an isolated report artifact path.",
    )
    parser.add_argument(
        "--reuse-memory",
        action="store_true",
        help="Reuse GLASSBOX_MEMORY_DIR or --memory-dir instead of an isolated run store.",
    )
    args = parser.parse_args(argv)

    report = args.report.expanduser().resolve()
    diagnose_report = (
        args.diagnose_report.expanduser().resolve()
        if args.diagnose_report is not None
        else report.with_name(f"{report.stem}.diagnose.json")
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    env = build_full_run_env(
        report,
        run_id=run_id,
        memory_dir=args.memory_dir.expanduser().resolve() if args.memory_dir else None,
        reuse_memory=args.reuse_memory,
    )
    if args.quick:
        env.update(_QUICK_ENV_OVERRIDES)
    if args.drill_down:
        env.update(_DRILL_DOWN_ENV_OVERRIDES)
        env.setdefault("IOS_SETTINGS_ARTIFACT_DIR", str(report.with_suffix(".artifacts")))

    if report.exists():
        report.unlink()
    if not args.skip_diagnose and diagnose_report.exists():
        diagnose_report.unlink()

    if not args.skip_diagnose:
        rc = _run_diagnose(env, diagnose_report, require_ready=True)
        if rc != 0:
            return rc

    rc = _run_crawler(env)
    if rc != 0:
        return rc

    if not report.exists():
        print(f"ERROR: walkthrough did not write report: {report}")
        return 1
    if args.skip_verify:
        print(f"report: {report}")
        return 0
    return _verify_report(report, expected_run_id=run_id, require_exhaustive=not args.quick)


if __name__ == "__main__":
    raise SystemExit(main())
