"""PicoKVM readiness preflight for the iOS Settings onboarding run.

Quick check that the PicoKVM rig is reachable before driving Settings:

    GLASSBOX_PICOKVM=1 uv run python -m skills.regression.ios_settings.diagnose --json

Two independent checks run:

1. The frame source decodes one frame from the PicoKVM HDMI stream.
2. The PicoKVM effector RPC is reachable (preflight also reports HDMI video
   state).

With ``--require-ready`` the process exits non-zero when the rig is not ready,
which is how :mod:`skills.regression.ios_settings.run_full` gates the
walkthrough.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from typing import Any

from glassbox.backend_registry import select_effector_backend
from glassbox.config import AgentConfig, get_config
from glassbox.runtime import RuntimeUnavailable, make_effector, make_source


def _frame_check(cfg: AgentConfig) -> dict[str, Any]:
    source = None
    try:
        source = make_source(cfg=cfg)
        fresh_snapshot = getattr(source, "fresh_snapshot", None)
        frame = fresh_snapshot() if callable(fresh_snapshot) else source.snapshot()
        width, height = frame.shape
        return {"ok": True, "resolution": [int(width), int(height)]}
    except RuntimeUnavailable as exc:
        return {"ok": False, "error": f"frame source unavailable: {exc}"}
    except Exception as exc:  # pragma: no cover - hardware/runtime dependent
        return {"ok": False, "error": f"frame decode failed: {exc}"}
    finally:
        if source is not None and hasattr(source, "close"):
            with contextlib.suppress(Exception):
                source.close()


def _effector_check(cfg: AgentConfig) -> dict[str, Any]:
    backend = select_effector_backend(cfg)
    if backend != "picokvm":
        return {
            "ok": False,
            "backend": backend,
            "error": "PicoKVM effector not selected; set GLASSBOX_PICOKVM=1",
        }
    eff = None
    try:
        eff = make_effector(None, cfg=cfg, connect=False)
        result = eff.preflight()
        return {
            "ok": bool(result.ok),
            "backend": backend,
            "fatal": bool(result.fatal),
            "code": result.code,
            "message": result.message,
            "config_ref": result.config_ref,
        }
    except Exception as exc:  # pragma: no cover - hardware/runtime dependent
        return {"ok": False, "backend": backend, "error": f"effector preflight failed: {exc}"}
    finally:
        if eff is not None and hasattr(eff, "close"):
            with contextlib.suppress(Exception):
                eff.close()


def diagnose(cfg: AgentConfig | None = None) -> dict[str, Any]:
    """Return a readiness report for the PicoKVM rig."""
    cfg = cfg or get_config()
    effector = _effector_check(cfg)
    frame = _frame_check(cfg)
    reasons: list[str] = []
    if not effector.get("ok"):
        reasons.append(effector.get("error") or effector.get("message") or "effector not ready")
    if not frame.get("ok"):
        reasons.append(frame.get("error") or "frame source not ready")
    return {
        "ready": {"ok": bool(effector.get("ok")) and bool(frame.get("ok")), "reasons": reasons},
        "effector": effector,
        "frame": frame,
    }


def _print_human(report: dict[str, Any]) -> None:
    ready = report["ready"]
    print(f"PicoKVM rig: {'READY' if ready['ok'] else 'NOT READY'}")
    effector = report["effector"]
    if effector.get("ok"):
        print(f"  effector: ok — {effector.get('message') or effector.get('backend')}")
    else:
        print(f"  effector: FAIL — {effector.get('error') or effector.get('message')}")
    frame = report["frame"]
    if frame.get("ok"):
        width, height = frame["resolution"]
        print(f"  frame:    ok — {width}x{height}")
    else:
        print(f"  frame:    FAIL — {frame.get('error')}")
    for reason in ready["reasons"]:
        print(f"  - {reason}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PicoKVM readiness preflight for the iOS Settings walkthrough",
    )
    parser.add_argument("--json", action="store_true", help="Print the readiness report as JSON.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero when the rig is not ready.",
    )
    args = parser.parse_args(argv)

    report = diagnose()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)

    if args.require_ready and not report["ready"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
