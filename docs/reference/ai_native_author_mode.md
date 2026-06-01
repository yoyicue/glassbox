# AI-Native Author Mode

Use this guidance when an AI agent writes or debugs glassbox walkthroughs.

## Entry Point

Prefer the public facade:

```python
from glassbox.ai import open_phone

with open_phone(app="com.apple.Preferences", run_name="settings-about") as phone:
    phone.goto("通用")
    phone.expect_visible("关于本机")
    phone.save_report()
```

Do not import `glassbox.phone.Phone`, runtime assembly, or effector modules in
ordinary AI-authored scripts. Those remain advanced/internal surfaces.

## Configuration

`open_phone()` is the only configuration surface for ordinary scripts. Its
optional kwargs:

- `record=True` / `memory=True` — toggle artifact recording and UTG memory.
- `profile_bundle=<bundle-id>` — opt in to app-specific whitebox/profile
  enrichment (not auto-read from env).
- `run_name=...`, `wait=False`, `timeout_s=None`.

Everything else is process-level config read from `.env` / `GLASSBOX_*` by
`glassbox.config` at `open_phone()` time — set it before you open the phone, not
per call. The switches most likely to change what your script observes:

- `GLASSBOX_LANGUAGE` / `GLASSBOX_REGION` — device locale; affects every label
  your script matches (default `zh-Hans`).
- `GLASSBOX_STABLE_AFTER_ACTION` / `GLASSBOX_STABLE_TIMEOUT` /
  `GLASSBOX_STABLE_CONSECUTIVE` — post-action settle. The facade enables
  stable-after-action by default so you do not reason from a too-early frame.
- VLM is opt-in, env-configured, experimental, and billed: set
  `GLASSBOX_ENABLE_VLM=1` before `open_phone()`. It is not exposed as a facade
  param or method; observations carry its results transparently when enabled.

`glassbox/config.py` is the canonical, complete switch list (each field
documents its `GLASSBOX_*` env var and default); `.env.example` carries the
common ones.

## Author Loop

1. Write a small deterministic Python script using `glassbox.ai`.
2. Run the focused smoke or regression command.
3. On failure, read `failure.md` first.
4. Follow the referenced scene, screenshot, action, audit, and verification
   artifacts only as needed.
5. If `Failure class` is `script_bug`, patch the script or policy labels.
6. If `Failure class` is `harness_bug`, report or patch glassbox.
7. If `Failure class` is `environment_drift`, use `phone.explore(...)`, then
   `phone.save_path_as(...)`, and convert that path back into deterministic
   `goto` / `expect_visible` steps.

## Defaults

Prefer:

- `phone.observe()` / `phone.perceive()` for screenshot-backed summaries
- `phone.elements()` / `phone.viewport()` when choosing a geometric target
- `phone.goto(...)`
- `phone.expect_visible(...)`
- `phone.expect_page(...)`
- `phone.scroll(until=...)`
- `phone.tap_xy(...)` / `phone.swipe_xy(...)` when OCR text cannot express the target
- `phone.close_app()` for PicoKVM foreground-app dismissal
- `phone.launch_app(..., expect_visible=...)` with an explicit landing check
- `phone.explore(...)` only when the deterministic path is missing or stale

Avoid:

- raw coordinates without first citing the observation element or screenshot
- per-frame screenshot requests
- dumping full Scene JSON into model context by default
- adding Settings-specific labels to `glassbox.ai`
- `tap(intent=...)` until semantic intent routing is implemented

Raw access is a debug escape hatch under `phone.raw` and `phone.artifacts`; use it
only when failure artifacts prove the facade-level text and geometry methods
cannot express the task.

Treat `ActionOutcome.ok` as transport status. Trust `semantic_status` only when it
is `succeeded` from a target-specific verifier or `ai_expectation`; `unknown`
means the device accepted input but the visible result is not proven.

## Remote Agents

Remote agents do not import `glassbox.ai` directly. They call the MCP server
(`glassbox-mcp-server`), which exposes the same contract as text-first tools:
`run_script`, `observe_summary`, `get_artifact`, `execute_task`, `list_runs`, and
`explore`. Use `tool_search` / `describe_tool` to load details progressively.

Every tool call needs `auth_token`, `session_id`, and `client_id`; artifact reads
are restricted to runs owned by that session. The token is the actual security
boundary; session fields are run-organization metadata within one trusted token
domain, not isolation from another holder of the same token.

`run_script` is disabled by default because it is arbitrary local code execution
with a scrubbed child-process environment, not a filesystem/network sandbox. Use
`execute_task` for pre-registered automation. Only start the server with
`--allow-run-script` or `GLASSBOX_MCP_ALLOW_RUN_SCRIPT=1` for a single trusted local
user.

## Interactive Sessions

For human/AI-in-the-loop exploration, prefer a long-lived session instead of
spawning many short scripts:

```bash
glassbox-ai-session --run-name live-walkthrough
```

It speaks JSONL on stdin/stdout and keeps one `open_phone()` runtime alive.
Use it for repeated `observe` / `tap_xy` / `swipe_xy` / `close_app` /
`save_report` cycles when you are still discovering the deterministic path.
Pass `--profile-bundle <bundle-id>` only when the run should use app-specific
whitebox/profile enrichment; the generic session does not opt in via
`GLASSBOX_PROFILE_BUNDLE` automatically.

## Progressive Disclosure

This file teaches the entry points only. Policy details live in modules such as
`skills/regression/ios_settings/policy.py` and should be opened only when a
failure or task needs those rules.
