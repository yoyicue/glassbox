"""Long-lived JSONL session for the glassbox.ai facade."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from glassbox.ai import (
    ActionOutcome,
    AIPhone,
    RunArtifacts,
    observation_payload,
    open_phone,
)

JSON = dict[str, Any]


class AISessionService:
    """Reuse one ``open_phone()`` runtime across many AI facade commands."""

    def __init__(
        self,
        *,
        open_phone_fn: Callable[..., AIPhone] = open_phone,
        open_kwargs: JSON | None = None,
    ):
        self.open_phone_fn = open_phone_fn
        self.open_kwargs = open_kwargs or {}
        self._ctx: AIPhone | None = None
        self.phone: AIPhone | None = None

    def start(self) -> JSON:
        if self.phone is not None:
            return {"ok": True, "already_started": True, "run_id": self.phone.run_id}
        self._ctx = self.open_phone_fn(**self.open_kwargs)
        self.phone = self._ctx.__enter__()
        return {"ok": True, "run_id": self.phone.run_id, "run_dir": str(self.phone.run_dir)}

    def close(self) -> JSON:
        if self.phone is None or self._ctx is None:
            return {"ok": True, "already_closed": True}
        phone = self.phone
        self._ctx.__exit__(None, None, None)
        self.phone = None
        self._ctx = None
        return {"ok": True, "run_id": phone.run_id}

    def handle(self, request: JSON) -> JSON:
        command = str(request.get("command") or request.get("cmd") or "")
        if command == "start":
            return self.start()
        if command in {"close", "exit", "quit"}:
            return self.close()
        phone = self._require_phone()
        if command in {"observe", "perceive"}:
            return {"ok": True, "observation": _observation_payload(phone.observe())}
        if command == "tap":
            return {"ok": True, "outcome": _outcome_payload(phone.tap(str(request["text"])))}
        if command == "tap_xy":
            kwargs = {}
            if request.get("coordinate_space") is not None:
                kwargs["coordinate_space"] = request.get("coordinate_space")
            return {
                "ok": True,
                "outcome": _outcome_payload(
                    phone.tap_xy(
                        int(request["x"]),
                        int(request["y"]),
                        **kwargs,
                    )
                ),
            }
        if command == "swipe_xy":
            return {
                "ok": True,
                "outcome": _outcome_payload(
                    phone.swipe_xy(
                        int(request["x1"]),
                        int(request["y1"]),
                        int(request["x2"]),
                        int(request["y2"]),
                        steps=int(request.get("steps", 20)),
                        end_hold_ms=int(request.get("end_hold_ms", 100)),
                        expect_visible=request.get("expect_visible"),
                        expect_page=request.get("expect_page"),
                        expect_timeout_s=float(request.get("expect_timeout_s", 5.0)),
                        sample_interval_s=float(request.get("sample_interval_s", 0.25)),
                    )
                ),
            }
        if command == "goto":
            return {"ok": True, "observation": _observation_payload(phone.goto(str(request["label"])))}
        if command == "scroll":
            # AI session API: `until` is caller-provided generic text; do not
            # infer completion from a raw action frame or hard-code app labels.
            return {
                "ok": True,
                "observation": _observation_payload(
                    phone.scroll(
                        str(request.get("direction") or "down"),
                        until=request.get("until"),
                        timeout_s=float(request.get("timeout_s", 10.0)),
                        max_steps=request.get("max_steps"),
                        settle_timeout_s=float(request.get("settle_timeout_s", 5.0)),
                        sample_interval_s=float(request.get("sample_interval_s", 0.25)),
                    )
                ),
            }
        if command == "back":
            return {"ok": True, "outcome": _outcome_payload(phone.back())}
        if command == "home":
            return {"ok": True, "outcome": _outcome_payload(phone.home())}
        if command == "close_app":
            return {"ok": True, "outcome": _outcome_payload(phone.close_app())}
        if command == "launch_app":
            return {
                "ok": True,
                "outcome": _outcome_payload(
                    phone.launch_app(
                        str(request["app"]),
                        aliases=tuple(str(item) for item in request.get("aliases", ())),
                        expect_visible=request.get("expect_visible"),
                        expect_page=request.get("expect_page"),
                    )
                ),
            }
        if command == "save_report":
            return {"ok": True, "artifacts": _artifacts_payload(phone.save_report())}
        raise ValueError(f"unknown ai session command: {command}")

    def _require_phone(self) -> AIPhone:
        if self.phone is None:
            self.start()
        assert self.phone is not None
        return self.phone


def serve_jsonl(service: AISessionService, *, input_stream=None, output_stream=None) -> None:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            result = service.handle(request)
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
        output_stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a long-lived glassbox.ai JSONL session")
    parser.add_argument("--app", default=None)
    parser.add_argument("--run-name", default="ai-session")
    parser.add_argument("--profile-bundle", default=None)
    parser.add_argument("--profiles-dir", default=None)
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    args = parser.parse_args(argv)
    service = AISessionService(
        open_kwargs={
            "app": args.app,
            "run_name": args.run_name,
            "profile_bundle": args.profile_bundle,
            "profiles_dir": Path(args.profiles_dir) if args.profiles_dir else None,
            "record": not args.no_record,
            "memory": not args.no_memory,
        }
    )
    try:
        serve_jsonl(service)
    finally:
        service.close()
    return 0


# Observation serialization is shared with the MCP server — see
# glassbox.ai.observation_payload (the single wire-format source of truth).
_observation_payload = observation_payload


def _outcome_payload(outcome: ActionOutcome) -> JSON:
    return {
        "ok": outcome.ok,
        "transport_ok": outcome.transport_ok,
        "semantic_status": outcome.semantic_status,
        "action": outcome.action,
        "target": outcome.target,
        "reason": outcome.reason,
        "artifact_path": str(outcome.artifact_path) if outcome.artifact_path else None,
        "unsupported": outcome.unsupported,
        "semantic_verifier": outcome.semantic_verifier,
        "semantic_confidence": outcome.semantic_confidence,
    }


def _artifacts_payload(artifacts: RunArtifacts) -> JSON:
    return {
        "run_id": artifacts.run_id,
        "run_name": artifacts.run_name,
        "run_dir": str(artifacts.run_dir),
        "manifest_path": str(artifacts.manifest_path),
        "report_path": str(artifacts.report_path) if artifacts.report_path else None,
        "failure_path": str(artifacts.failure_path) if artifacts.failure_path else None,
        "latest_scene_path": str(artifacts.latest_scene_path) if artifacts.latest_scene_path else None,
        "latest_screenshot_path": str(artifacts.latest_screenshot_path) if artifacts.latest_screenshot_path else None,
        "artifact_schema_version": artifacts.artifact_schema_version,
        "ai_api_version": artifacts.ai_api_version,
    }


if __name__ == "__main__":
    raise SystemExit(main())
