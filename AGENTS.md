# AGENTS.md

Guidance for AI agents (and humans) working in the glassbox repo. Start here,
then follow the pointers. For depth: `README.md` (architecture, install,
hardware), `ONBOARDING.md` (rig bring-up), `docs/` (design, goals, reference).

## What this is

glassbox is an **out-of-band** computer-use runtime that drives a real iPhone
(iOS) or iPad (iPadOS) from screen observations — frames over HDMI, actions over
USB HID, **no code on the device**. It runs an `observe → decide → act → verify`
loop and persists a screen-memory (UTG) graph across runs. **MIT-licensed,
public repo.**

## Setup & core commands

```bash
uv sync --extra dev                  # install (Python >=3.11, uv-managed)
uv run python -c "import glassbox"    # smoke-import

make check    # MERGE GATE: lint + test + regression-gate + golden-audit. Keep it GREEN.
make test     # uv run pytest skills/smoke -q  — fast, offline, no hardware
uv run ruff check glassbox skills     # lint (line-length 100, target py311)

uv run pytest skills/smoke/test_foo.py -q             # one test file
uv run pytest skills/smoke/test_foo.py::test_bar -q   # one test
```

- `make check` is **device-independent** (no PicoKVM/rig) and is what CI runs on
  every PR. Run it before you push. Its on-rig time-series companion is
  `.github/workflows/rig-nightly.yml` (self-hosted `picokvm` runner, iPhone 17
  Pro Max zh + iPad mini 7 en matrix) — informational, never a merge gate.
- pytest: `testpaths = skills`; markers are `smoke` (fast, offline),
  `regression` (slow, needs rig/artifacts), `feature(name)`.
  `--strict-markers` is on, so a typoed marker fails instead of silently
  selecting nothing.
- **Working in a `git worktree`? Create it with `make worktree DEST=../gb-foo
  BRANCH=feature/foo`** (or `scripts/new-worktree.sh`). A bare `git worktree add`
  does **not** copy gitignored local config, so the worktree silently misses `.env`
  (→ `cfg.picokvm` false → effector selected as **NoOp**: no HID, plus icon/VLM
  fall back) and the AGPL omniparser plugin; `.env` is read **relative to the
  package root**, not CWD, so it must exist at the worktree's own root. The helper
  symlinks both. Each worktree still needs its own `uv sync --extra dev` (separate
  `.venv`; for omniparser also `uv pip install ultralytics torch huggingface_hub`).
- `main` is branch-protected: merging needs a PR whose `check` status check (the
  CI job that runs `make check`) is green, with the branch up to date with `main`
  first (strict). The rule is enforced for admins too and requires no review
  approvals. So keep `make check` green locally, branch for non-trivial work, and
  still get the user's go-ahead before merging to `main`.

## Repository map

- **`glassbox/`** — the MIT core package, one sub-package per pipeline stage:
  `perception/` (frame + letterbox crop + stability), `cognition/` (OCR/VLM →
  elements), `action/` (intents → actuations), `effector.py` + `effectors/` (HID
  transport), `verification/` (semantic effect, **not** transport ACK),
  `memory/` (UTG graph), `obs/` (recorder/replay/caches), `ios/` + `ipados/`
  (platform providers). `runtime.py` assembles them into a `Phone`; `ai.py` is
  the `glassbox.ai` facade. Seams are named boundaries (`boundaries.py`)
  discovered via entry points — add a backend by registering one, **not** by
  editing core. The entry-point groups (see `pyproject.toml`):
  `glassbox.frame_sources`, `glassbox.ocr`, `glassbox.vlm`,
  `glassbox.effectors`, `glassbox.verifiers`, `glassbox.platforms`,
  `glassbox.crawl_policies`, `glassbox.app_policies`.
- **`skills/`** — tests and harnesses, **not** app code:
  - `smoke/` — offline unit/contract suite (the bulk of the tests).
  - `regression/` — on-rig measurement harness + committed baselines.
  - `golden/` — static expected-output fixtures consumed by smoke.
  - `crawl/` — generic app-explorer library.
  - Placement rule: see `docs/reference/ai_native_author_mode.md` →
    "Where Tests Go: smoke vs regression".
- **`docs/`** — `design/` (architecture & decisions), `goals/` (roadmaps),
  `reference/` (author mode, rig/hardware references), `measurements/`
  (experiment reports).
- **`README.md`** (architecture/install/hardware) · **`ONBOARDING.md`** (rig
  bring-up from parts to first run).

## Conventions

- **Fix the core, not the skill.** When a walkthrough or crawl fails because of a
  perception/action/verification bug, fix it in `glassbox/` so every caller
  benefits — do not band-aid it inside a walkthrough or
  `skills/regression/ios_settings/`. (The Settings drill-down reliability wins
  all landed this way; the skill only *opts in* to core capabilities.)
- **Author via the `glassbox.ai` facade.** AI-authored scripts use
  `from glassbox.ai import open_phone`; do **not** import `glassbox.phone.Phone`,
  `runtime`, or effector modules in ordinary scripts. Full guide:
  `docs/reference/ai_native_author_mode.md`.
- **smoke vs regression.** Offline, mock-Phone, `@pytest.mark.smoke`-able test →
  `skills/smoke/`. Needs a real rig / is runnable harness code / produces or
  compares a baseline → `skills/regression/`. Harness code lives in `regression`;
  its fast offline unit test lives in `smoke`.
- **Doc discipline — verify before you write.** Never transcribe a count, file
  list, or symbol name from grep/subagent output into a doc as fact. Re-check it
  against current source right before writing; mark numbers as "snapshot as of
  `<sha>`"; embed the generator command; prefer a committed allow-list/assertion
  test over a hand-typed inventory. (Stale baselines have been caught repeatedly.)
  zsh does **not** word-split an unquoted `$var` — use an explicit `for` loop or
  `${=var}`, or grep counts silently come back wrong.
- **Transport `ok` ≠ success.** Trust `ActionResult.semantic_status`
  (`succeeded` / `unknown` / `failed`, set by the post-action verifier), not the
  effector ACK — an action can be delivered over HID and still do nothing on
  screen.
- **Don't over-claim reliability.** The eval harness is deliberately multi-layer
  and honest; there is no single "accuracy rate". Do not cite one headline number
  (e.g. an action-level ACK rate) as task-completion success — cite the roadmap
  docs under `docs/goals/`.

## Security & licensing boundaries

- The repo is **public + MIT** — never commit secrets. `.env` is gitignored and
  holds local rig/VLM config; keep API keys there only, never in source or in a
  commit message.
- **VLM is opt-in, env-configured, experimental, and billed.** Set
  `GLASSBOX_ENABLE_VLM=1` before `open_phone()`; it is not a facade parameter.
  Default runs are OCR-only and free.
- **AGPL stays out of the MIT core.** Heavy AGPL icon-detector backends (e.g.
  OmniParser) are git-ignored drop-in plugins under
  `glassbox/cognition/icon_backends/`, **not** `pyproject.toml` extras — a clean
  checkout has zero AGPL by default. Don't promote them into the project deps.

## Hardware / rig notes (only when running on real devices)

Most work is offline (`make check`). For on-rig runs see `ONBOARDING.md` and
`docs/reference/`. Facts that bite:

- **iPhone** drives via the AssistiveTouch pointer only: clicks work, scroll is an
  imprecise swipe-fling (precise wheel is intermittent → off by default), keyboard
  is text + a few combos. **iPad** has a native pointer + reliable wheel — prefer
  iPad for scroll-heavy work.
- The `make computer-use-success-rate-ios-settings` target assumes a **zh iPhone**.
  For the **iPad mini 7** rig, drive `run_full` directly:
  `GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.ios_settings.run_full --drill-down --language en --region HK`.
- **Locale:** default is `zh-Hans`, English is switchable per run with
  `run_full --language en --region HK`. **Do not pin `GLASSBOX_LANGUAGE` in
  `.env`** — it flips the global default for every caller, including the smoke
  suite.
