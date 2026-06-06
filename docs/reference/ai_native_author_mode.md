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

## Where Tests Go: smoke vs regression

`skills/smoke/` is the offline unit/contract suite (`make test` → `pytest
skills/smoke -q`); it runs in CI on every PR with no rig. `skills/regression/`
is the on-rig measurement harness, its committed baselines, and the few
acceptance tests that drive a real device. Decide top-down — first match wins:

1. Needs a real rig (PicoKVM/HDMI, a physical iPad/iPhone)? → `regression`.
   This is the hard line: `crawler.crawl_readonly_settings(...,
   require_real_effector=True)` raises `SettingsCrawlerUnavailable` when
   `phone.has_real_effector()` is false.
2. Needs a live device or network to run at all? → `regression`.
3. A runnable harness, collection script, or CLI that validates rig artifacts
   (has `main()` / argparse)? → `regression` (e.g. `run_full.py`,
   `canonical_primitives.py`, `computer_use_success_rate.py`,
   `state_machine_acceptance.py`).
4. Produces or compares a reliability baseline? → the artifact goes in
   `skills/regression/fixtures/` (e.g. `reliability_baseline.json`); the
   measurement code stays in `regression`.
5. Otherwise — asserts offline with `mock_phone` + a static fixture, marks
   `@pytest.mark.smoke`, finishes inside `make test`? → `skills/smoke`.

Harness code and its unit test live apart: the harness goes in `regression`,
its fast offline test goes in `smoke`. Adding a Settings-crawler feature means
code in `skills/regression/ios_settings/` plus a mocked test in
`skills/smoke/test_ios_settings_crawler.py` (it monkeypatches `_run_core_crawl`
and passes `require_real_effector=False`). A smoke test importing regression
harness code to exercise it offline is the normal, one-way dependency.

Signals: the `phone` / `_frame_source` fixtures `pytest.skip` on
`RuntimeUnavailable`, so any test depending on them is rig-bound — think
`regression`. `@pytest.mark.smoke` marks the offline suite; `@pytest.mark.regression`
marks an on-rig acceptance test (e.g. `test_readonly_walkthrough.py`). Naming
trap: `make regression-gate` runs only the *offline* half (completion-floor
`validate`, human-control template `validate`, and the regression/human-baseline
smoke tests) and is part of `make check`. The real on-rig suite runs via direct
CLI (`run_full`) or the `rig-nightly.yml` workflow; `make regression-compare` is
**not** a device run — it's the JSON-to-JSON gate that fails on a success-rate
regression once a real run has produced a candidate benchmark.

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
