# Public API

`glassbox.ai` is the stable AI-facing import surface for author-mode scripts.
The current version is `ai-api-v1`.

```python
from glassbox.ai import open_phone

with open_phone(app="com.apple.Preferences", run_name="settings-about") as phone:
    phone.goto("通用")
    phone.expect_visible("关于本机")
    artifacts = phone.save_report()
```

A checked-in Settings reference lives at
`skills/regression/ios_settings/ai_native_example.py`.

Stable symbols:

- `open_phone(...) -> AIPhone`
- `AIPhone.observe() -> ObservationSummary`
- `AIPhone.perceive(refresh=False) -> ObservationSummary`
- `AIPhone.elements(refresh=False) -> tuple[ObservationElement, ...]`
- `AIPhone.viewport(refresh=False) -> tuple[int, int] | None`
- `AIPhone.tap(text=None, *, intent=None) -> ActionOutcome`
- `AIPhone.tap_xy(x, y, *, expect_visible=None, expect_page=None) -> ActionOutcome`
- `AIPhone.swipe_xy(x1, y1, x2, y2, *, steps=20, end_hold_ms=100, expect_visible=None, expect_page=None) -> ActionOutcome`
- `AIPhone.launch_app(app, *, aliases=(), expect_visible=None, expect_page=None) -> ActionOutcome`
- `AIPhone.close_app() -> ActionOutcome`
- `AIPhone.goto(label, *, timeout_s=10.0) -> ObservationSummary` (page-id-shaped
  labels try learned memory-path navigation first)
- `AIPhone.back() -> ActionOutcome`
- `AIPhone.home() -> ActionOutcome`
- `AIPhone.scroll(direction="down", *, until=None) -> ObservationSummary`
- `AIPhone.expect_visible(text, *, timeout_s=5.0) -> None`
- `AIPhone.expect_page(page_id) -> None`
- `AIPhone.explore(goal, *, max_steps=12) -> ExplorationTrail`
- `AIPhone.save_path_as(name) -> PathArtifact`
- `AIPhone.save_report() -> RunArtifacts`

Stable data classes:

- `ObservationSummary`
- `ObservationElement`
- `ElementBox`
- `ActionOutcome`
- `RunArtifacts`
- `ExplorationTrail`
- `PathArtifact`
- `AIAssertionError`
- `AttachBusyError`

Raw coordinates and full scene reads are debug escape hatches under
`phone.raw` and `phone.artifacts`; examples should prefer text methods first,
then facade-level geometry methods (`tap_xy` / `swipe_xy`) when the observation
element table proves OCR cannot express the target.
`tap(intent=...)` is reserved for future semantic intent routing and currently
raises `NotImplementedError` instead of treating the intent as OCR text.

`open_phone(profile_bundle=...)` is the explicit opt-in path for app-specific
whitebox/profile enrichment. The AI facade does not automatically consume
`GLASSBOX_PROFILE_BUNDLE`, so a local `.env` cannot silently turn generic runs into
DemoApp- or app-specific runs.

`observe()` always writes an AI observation screenshot when a frame is available,
even when recording is off. `ObservationSummary` includes text, element geometry,
viewport size, coordinate space, crop bbox, and artifact paths. `perceive()` is a
cached facade read: it returns the latest observation unless `refresh=True`.

`ActionOutcome.ok` is transport success. `ActionOutcome.semantic_status` is the
trusted semantic result; visual-only `scene_progressed` success is downgraded to
`unknown` by the facade unless the caller supplied an explicit expectation and it
matched.

`launch_app()` performs a facade-level landing check when no explicit expectation
is provided. It verifies Settings via page metadata, profile-backed apps via
whitebox/current-VC evidence, rejects a launch that remains on Home/SpringBoard,
and returns `unknown` when the app may have opened but target identity is not
provable from the observation.

Author-mode usage guidance is in
[`../reference/ai_native_author_mode.md`](../reference/ai_native_author_mode.md).

## Remote MCP

Remote agents use the stdio MCP server:

```bash
glassbox-mcp-server --artifact-root artifacts/mcp
```

The server requires `auth_token`, `session_id`, and `client_id` on every tool
call. If `GLASSBOX_MCP_TOKEN` is not set, it writes a generated token to
`<artifact-root>/mcp_token` with user-only permissions.

Default tools are text-first:

- `tool_search`
- `describe_tool`
- `run_script`
- `observe_summary`
- `get_artifact`
- `execute_task`
- `list_runs`
- `explore`

`run_script` is arbitrary code execution for a single trusted local user. It is
disabled by default and requires `--allow-run-script` or
`GLASSBOX_MCP_ALLOW_RUN_SCRIPT=1`; otherwise use `execute_task` for pre-registered
repository tasks. When enabled, it runs in a child process with a scrubbed
environment and per-run workspace, but it is not a filesystem or network
sandbox. `get_artifact` accepts only ledger-relative paths owned by the caller's
session. The shared token is the real security boundary; `session_id` /
`client_id` organize runs inside that trusted token domain and are not protection
against another holder of the same token.

## Long-Lived Session

Interactive authoring can keep one runtime open with the JSONL session process:

```bash
glassbox-ai-session --run-name demoapp-live --profile-bundle com.example.app
```

Each input line is a JSON command such as `{"command":"observe"}` or
`{"command":"tap_xy","x":120,"y":420}`; each output line is a JSON response.
This avoids reloading OCR/VLM/runtime state for every observe-decide-act step.

## Semantic Status

Generic `scene_progressed` no longer treats a full-frame pixel delta as semantic
success. A changed Scene identity/text can still succeed; a frame-only change is
`unknown` unless target landing observation or an explicit AI expectation proves
the intended effect.
