"""Minimal stdio JSON-RPC MCP server for the AI-native facade.

The implementation deliberately keeps transport thin and the tool bodies reuse
``glassbox.ai``. It supports the MCP JSON-RPC methods needed by clients
(``initialize``, ``tools/list``, ``tools/call``) without pulling an SDK
dependency into the base glassbox package.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glassbox.ai import AI_API_VERSION, open_phone

JSON = dict[str, Any]
REPO_GLASSBOX_ROOT = Path(__file__).resolve().parents[2]


class MCPError(RuntimeError):
    code = -32000

    def __init__(self, message: str, *, data: JSON | None = None):
        super().__init__(message)
        self.data = data or {}


class MCPAuthError(MCPError):
    code = -32001


class MCPToolError(MCPError):
    code = -32002


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_dir: Path
    session_id: str
    client_id: str
    created_at: float
    kind: str


class HarnessMCPService:
    """Tool dispatcher behind the stdio MCP transport."""

    def __init__(
        self,
        *,
        artifact_root: Path | str | None = None,
        auth_token: str | None = None,
        token_file: Path | str | None = None,
        allow_debug_tools: bool = False,
        allow_run_script: bool | None = None,
        open_phone_fn: Callable[..., Any] = open_phone,
    ):
        self.artifact_root = Path(
            artifact_root
            or os.environ.get("GLASSBOX_MCP_ARTIFACT_DIR")
            or os.environ.get("GLASSBOX_AI_ARTIFACT_DIR")
            or "artifacts/mcp"
        )
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.allow_debug_tools = bool(allow_debug_tools)
        self.allow_run_script = _env_flag("GLASSBOX_MCP_ALLOW_RUN_SCRIPT") if allow_run_script is None else bool(allow_run_script)
        self.open_phone_fn = open_phone_fn
        self.audit_path = self.artifact_root / "mcp_audit.jsonl"
        self.token_file = Path(token_file) if token_file else self.artifact_root / "mcp_token"
        self.auth_token = auth_token or os.environ.get("GLASSBOX_MCP_TOKEN") or self._load_or_create_token()
        self.runs: dict[str, RunRecord] = {}
        self.tasks = {
            "ios_settings_about": (
                "Open Settings > General and verify About using glassbox.ai.",
                "\n".join(
                    [
                        "from glassbox.ai import open_phone",
                        "",
                        "with open_phone(app='com.apple.Preferences', run_name='mcp-ios-settings-about') as phone:",
                        "    phone.goto('通用')",
                        "    phone.expect_visible('关于本机')",
                        "    phone.save_report()",
                        "",
                    ]
                ),
            ),
            "observe": (
                "Open a phone session and print one ObservationSummary.",
                "\n".join(
                    [
                        "from glassbox.ai import open_phone",
                        "",
                        "with open_phone(run_name='mcp-observe') as phone:",
                        "    print(phone.observe().summary)",
                        "    phone.save_report()",
                        "",
                    ]
                ),
            ),
        }

    def _load_or_create_token(self) -> str:
        if self.token_file.exists():
            return self.token_file.read_text(encoding="utf-8").strip()
        token = secrets.token_urlsafe(32)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token + "\n", encoding="utf-8")
        with contextlib.suppress(Exception):
            self.token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return token

    def handle_jsonrpc(self, request: JSON) -> JSON:
        seq = request.get("id")
        try:
            method = str(request.get("method") or "")
            params = request.get("params") or {}
            if method == "initialize":
                result = self.initialize(params)
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                result = self.call_tool(params)
            elif method == "shutdown":
                result = {}
            else:
                raise MCPError(f"unsupported MCP method: {method}")
            return {"jsonrpc": "2.0", "id": seq, "result": result}
        except MCPError as exc:
            return {
                "jsonrpc": "2.0",
                "id": seq,
                "error": {"code": exc.code, "message": str(exc), "data": exc.data},
            }
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": seq, "error": {"code": -32603, "message": str(exc)}}

    def initialize(self, _params: JSON | None = None) -> JSON:
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "glassbox-ai-native",
                "version": AI_API_VERSION,
                "transport": "stdio",
                "listen_scope": "stdio/local-process",
                "auth": "bearer-token-per-tool-call",
                "token_file": str(self.token_file),
                "run_script_enabled": self.allow_run_script,
            },
            "capabilities": {"tools": {"listChanged": False}},
        }

    def list_tools(self) -> list[JSON]:
        return [
            _tool("tool_search", "Find AI-native glassbox MCP tools by query.", ["query"]),
            _tool("describe_tool", "Return the full schema and safety notes for one tool.", ["tool_name"]),
            _tool("run_script", "Run AI-authored glassbox.ai code in a child process when explicitly enabled.", ["source"]),
            _tool("observe_summary", "Open a short glassbox.ai session and return one ObservationSummary.", []),
            _tool("get_artifact", "Read a run-owned artifact by ledger-relative path.", ["run_id", "path"]),
            _tool("execute_task", "Run a pre-registered repository task by id.", ["task_id"]),
            _tool("list_runs", "List runs owned by the session.", []),
            _tool("explore", "Run glassbox.ai exploration and return the compact trail.", ["goal"]),
        ]

    def call_tool(self, params: JSON) -> JSON:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise MCPToolError("tools/call arguments must be an object")
        self._authenticate(arguments)
        self._require_session(arguments)
        dispatch = {
            "tool_search": self.tool_search,
            "describe_tool": self.describe_tool,
            "run_script": self.run_script,
            "observe_summary": self.observe_summary,
            "get_artifact": self.get_artifact,
            "execute_task": self.execute_task,
            "list_runs": self.list_runs_tool,
            "explore": self.explore,
        }
        fn = dispatch.get(name)
        if fn is None:
            raise MCPToolError(f"unknown tool: {name}")
        self._audit("tool.called", arguments, {"tool": name})
        result = fn(arguments)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

    def _authenticate(self, args: JSON) -> None:
        supplied = str(args.get("auth_token") or "")
        expected = str(self.auth_token or "")
        if not secrets.compare_digest(supplied, expected):
            self._audit("auth.failed", args, {"reason": "bad_token"})
            raise MCPAuthError("invalid MCP auth token")

    def _require_session(self, args: JSON) -> tuple[str, str]:
        session_id = str(args.get("session_id") or "")
        client_id = str(args.get("client_id") or "")
        if not session_id or not client_id:
            raise MCPAuthError("session_id and client_id are required")
        return session_id, client_id

    def _audit(self, type_: str, args: JSON, payload: JSON) -> None:
        event = {
            "ts": time.time(),
            "type": type_,
            "session_id": args.get("session_id"),
            "client_id": args.get("client_id"),
            "payload": payload,
        }
        with self.audit_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(event, ensure_ascii=False) + "\n")

    def tool_search(self, args: JSON) -> JSON:
        query = str(args.get("query") or "").casefold()
        matches = []
        for tool in self.list_tools():
            haystack = f"{tool['name']} {tool.get('description', '')}".casefold()
            if not query or query in haystack:
                matches.append({"name": tool["name"], "description": tool["description"]})
        return {"tools": matches}

    def describe_tool(self, args: JSON) -> JSON:
        name = str(args.get("tool_name") or "")
        schemas = self._detailed_tool_schemas()
        if name not in schemas:
            raise MCPToolError(f"unknown tool for describe_tool: {name}")
        return schemas[name]

    def observe_summary(self, args: JSON) -> JSON:
        with self.open_phone_fn(
            app=args.get("app"),
            run_name=args.get("run_name") or "mcp-observe-summary",
            record=bool(args.get("record", True)),
            memory=bool(args.get("memory", True)),
        ) as phone:
            obs = phone.observe()
            artifacts = phone.save_report()
            self._remember_run(args, artifacts.run_id, artifacts.run_dir, kind="observe_summary")
            return {
                "run_id": artifacts.run_id,
                "summary": obs.summary,
                "page_id": obs.page_id,
                "viewport_size": list(obs.viewport_size) if obs.viewport_size else None,
                "coordinate_space": obs.coordinate_space,
                "crop_bbox": list(obs.crop_bbox) if obs.crop_bbox else None,
                "platform_scene_kind": obs.platform_scene_kind,
                "current_vc": obs.current_vc,
                "whitebox_evaluated": obs.whitebox_evaluated,
                "app_state": obs.app_state or {},
                "elements": [
                    {
                        "id": element.element_id,
                        "type": element.type,
                        "text": element.text,
                        "box": {
                            "x": element.box.x,
                            "y": element.box.y,
                            "w": element.box.w,
                            "h": element.box.h,
                            "center": list(element.box.center),
                        },
                        "confidence": element.confidence,
                    }
                    for element in obs.elements
                ],
                "scene_path": _rel_to(artifacts.run_dir, obs.scene_path),
                "screenshot_path": _rel_to(artifacts.run_dir, obs.screenshot_path),
                "report_path": _rel_to(artifacts.run_dir, artifacts.report_path),
            }

    def explore(self, args: JSON) -> JSON:
        goal = str(args.get("goal") or "")
        if not goal:
            raise MCPToolError("explore requires goal")
        with self.open_phone_fn(
            app=args.get("app"),
            run_name=args.get("run_name") or "mcp-explore",
            record=bool(args.get("record", True)),
            memory=bool(args.get("memory", True)),
        ) as phone:
            trail = phone.explore(goal, max_steps=int(args.get("max_steps", 12)))
            path_artifact = phone.save_path_as(str(args.get("path_name") or _safe_name(goal))) if trail.success else None
            artifacts = phone.save_report()
            self._remember_run(args, artifacts.run_id, artifacts.run_dir, kind="explore")
            return {
                "run_id": artifacts.run_id,
                "success": trail.success,
                "summary": trail.summary(),
                "matched_path": list(trail.matched_path),
                "trail_path": _rel_to(artifacts.run_dir, trail.artifact_path),
                "path_artifact": _rel_to(artifacts.run_dir, path_artifact.path) if path_artifact else None,
            }

    def run_script(self, args: JSON) -> JSON:
        if not self.allow_run_script:
            raise MCPToolError("run_script is disabled by default; restart server with --allow-run-script for trusted local users")
        source = str(args.get("source") or "")
        if not source.strip():
            raise MCPToolError("run_script requires source")
        return self._run_child_script(
            args,
            source=source,
            kind="run_script",
            timeout_s=float(args.get("timeout_s", 60.0)),
        )

    def execute_task(self, args: JSON) -> JSON:
        task_id = str(args.get("task_id") or "")
        task = self.tasks.get(task_id)
        if task is None:
            raise MCPToolError(f"unknown task_id: {task_id}")
        description, source = task
        result = self._run_child_script(
            args,
            source=source,
            kind=f"task:{task_id}",
            timeout_s=float(args.get("timeout_s", 120.0)),
        )
        result["task_id"] = task_id
        result["description"] = description
        return result

    def list_runs_tool(self, args: JSON) -> JSON:
        session_id, client_id = self._require_session(args)
        runs = [
            {
                "run_id": record.run_id,
                "run_dir": str(record.run_dir),
                "kind": record.kind,
                "created_at": record.created_at,
            }
            for record in self.runs.values()
            if record.session_id == session_id and record.client_id == client_id
        ]
        return {"runs": sorted(runs, key=lambda item: item["created_at"])}

    def get_artifact(self, args: JSON) -> JSON:
        run_id = str(args.get("run_id") or "")
        record = self._owned_run(args, run_id)
        rel_path = str(args.get("path") or "")
        if not rel_path:
            raise MCPToolError("get_artifact requires path")
        target = self._resolve_artifact(record.run_dir, rel_path)
        max_bytes = int(args.get("max_bytes", 65536))
        include_binary = bool(args.get("include_binary", False))
        data = target.read_bytes()
        truncated = len(data) > max_bytes
        sample = data[:max_bytes]
        payload: JSON = {
            "run_id": run_id,
            "path": str(target.relative_to(record.run_dir)),
            "bytes": len(data),
            "truncated": truncated,
        }
        if _looks_text(sample):
            payload["text"] = sample.decode("utf-8", errors="replace")
        elif include_binary:
            if not self.allow_debug_tools:
                raise MCPToolError("binary artifact reads require debug capability")
            payload["base64"] = base64.b64encode(sample).decode("ascii")
        else:
            payload["binary"] = True
        self._audit("artifact.read", args, {"run_id": run_id, "path": payload["path"], "bytes": len(data)})
        return payload

    def _run_child_script(self, args: JSON, *, source: str, kind: str, timeout_s: float) -> JSON:
        run_id = f"mcp_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
        run_dir = self.artifact_root / run_id
        workspace = run_dir / "workspace"
        scripts_dir = run_dir / "scripts"
        workspace.mkdir(parents=True)
        scripts_dir.mkdir()
        script_path = scripts_dir / "script.py"
        script_path.write_text(source, encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        self._remember_run(args, run_id, run_dir, kind=kind)
        self._audit(
            "script.started",
            args,
            {
                "run_id": run_id,
                "script_path": str(script_path.relative_to(run_dir)),
                "sha256": digest,
                "sandbox": "child-process-cwd-scrubbed-env-no-fs-isolation",
            },
        )
        env = self._sandbox_env(run_dir)
        try:
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=workspace,
                env=env,
                text=True,
                capture_output=True,
                timeout=max(1.0, timeout_s),
                check=False,
            )
            timed_out = False
            returncode = completed.returncode
            stdout = _truncate(completed.stdout, 32768)
            stderr = _truncate(completed.stderr, 32768)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = _truncate((exc.stdout or "") if isinstance(exc.stdout, str) else "", 32768)
            stderr = _truncate((exc.stderr or "") if isinstance(exc.stderr, str) else "", 32768)
        result = {
            "run_id": run_id,
            "ok": returncode == 0 and not timed_out,
            "returncode": returncode,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "script_path": str(script_path.relative_to(run_dir)),
            "sha256": digest,
            "sandbox": "child-process-cwd-scrubbed-env-no-fs-isolation",
        }
        (run_dir / "mcp_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._audit("script.finished", args, result)
        return result

    def _sandbox_env(self, run_dir: Path) -> dict[str, str]:
        allowed_prefixes = ("GLASSBOX_PICOKVM_",)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_GLASSBOX_ROOT),
            "GLASSBOX_AI_ARTIFACT_DIR": str(self.artifact_root),
            "GLASSBOX_ACTION_FAIL_FAST": "0",
        }
        for key, value in os.environ.items():
            if key.startswith(allowed_prefixes) and "PASSWORD" not in key and "TOKEN" not in key:
                env[key] = value
        return env

    def _remember_run(self, args: JSON, run_id: str, run_dir: Path, *, kind: str) -> None:
        session_id, client_id = self._require_session(args)
        self.runs[run_id] = RunRecord(
            run_id=run_id,
            run_dir=Path(run_dir),
            session_id=session_id,
            client_id=client_id,
            created_at=time.time(),
            kind=kind,
        )

    def _owned_run(self, args: JSON, run_id: str) -> RunRecord:
        session_id, client_id = self._require_session(args)
        record = self.runs.get(run_id)
        if record is None:
            raise MCPToolError(f"unknown run_id: {run_id}")
        if record.session_id != session_id or record.client_id != client_id:
            raise MCPAuthError("session does not own requested run")
        return record

    def _resolve_artifact(self, run_dir: Path, rel_path: str) -> Path:
        candidate = Path(rel_path)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            raise MCPToolError("artifact path must be ledger-relative and cannot contain '..'")
        if any(part.startswith(".") for part in candidate.parts):
            raise MCPToolError("hidden artifact paths are not readable through MCP")
        current = run_dir
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                raise MCPToolError("symlink artifacts are not readable through MCP")
        resolved = current.resolve()
        root = run_dir.resolve()
        if resolved != root and root not in resolved.parents:
            raise MCPToolError("artifact path escapes run directory")
        if not resolved.exists() or not resolved.is_file():
            raise MCPToolError(f"artifact not found: {rel_path}")
        return resolved

    def _detailed_tool_schemas(self) -> dict[str, JSON]:
        return {
            tool["name"]: {
                **tool,
                "safety": (
                    "Requires auth_token, session_id, and client_id. The token is the security boundary; "
                    "session_id/client_id organize run ownership within one trusted token domain. Responses are text-first."
                ),
                "inputSchema": tool["inputSchema"],
            }
            for tool in self.list_tools()
        }


def _tool(name: str, description: str, required: list[str]) -> JSON:
    properties: JSON = {
        "auth_token": {"type": "string"},
        "session_id": {"type": "string"},
        "client_id": {"type": "string"},
    }
    for item in required:
        properties[item] = {"type": "string"}
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": ["auth_token", "session_id", "client_id", *required],
            "additionalProperties": True,
        },
    }


def _looks_text(data: bytes) -> bool:
    if not data:
        return True
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _truncate(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[:max_chars] + "\n[truncated]"


def _env_flag(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.strip().casefold() in {"1", "true", "yes", "on"}


def _rel_to(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip()) or "path"


def serve_stdio(service: HarnessMCPService) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        else:
            response = service.handle_jsonrpc(request)
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the glassbox.ai MCP stdio server")
    parser.add_argument("--artifact-root", default=None)
    parser.add_argument("--auth-token", default=None)
    parser.add_argument("--token-file", default=None)
    parser.add_argument("--allow-debug-tools", action="store_true")
    parser.add_argument("--allow-run-script", action="store_true", default=None)
    args = parser.parse_args(argv)
    service = HarnessMCPService(
        artifact_root=args.artifact_root,
        auth_token=args.auth_token,
        token_file=args.token_file,
        allow_debug_tools=args.allow_debug_tools,
        allow_run_script=args.allow_run_script,
    )
    serve_stdio(service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
