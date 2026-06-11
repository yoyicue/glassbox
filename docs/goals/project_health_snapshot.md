# Project health snapshot

Status: **assessment + same-day remediation, snapshot as of `c892824`
(2026-06-11).** The structural items below were identified by the 2026-06-11
evaluation at `801032f` and their offline-fixable halves were remediated the
same day in PRs #68–#73 — each item carries a "Remediation" line saying what
landed and what honestly remains.

A whole-project health read intended as an input to the roadmap docs in this
directory, not a replacement for them. It summarises where the codebase is
strong, where the structural debt sits, and which changes have the highest
leverage. The action items it names are owned by existing docs — this file
points at them rather than duplicating their plans:

- [`computer_use_honest_gate_first.md`](computer_use_honest_gate_first.md) — the
  gate-coverage / expected-state work (item 4 below).
- [`computer_use_quality_roadmap.md`](computer_use_quality_roadmap.md) — what
  reliability machinery to build/wire.
- [`../design/architecture_boundaries.md`](../design/architecture_boundaries.md)
  — the seam contracts referenced in items 1 and 5.
- [`flag_cell_ab_matrix.md`](flag_cell_ab_matrix.md) — the per-flag A/B ledger.

Every count below is a snapshot, not a maintained figure. Regenerate with the
commands shown before citing any number as current.

## Supersedes the prior revision

The previous revision of this file was labelled "snapshot as of `5881a28`
(2026-06-10)". `5881a28` is in fact main's HEAD of **2026-06-03** (merge PR #56);
main sat idle that week, so the doc described a stale tree. Its headline item #1
("`compare_benchmarks` gates only 5 of 19 metrics; floor coverage = 0") had
**already been fixed** on main before the doc was written — gate expansion
`e430d92` (2026-06-05), expected-state tap routing `d9695ae` (2026-06-06),
coverage-bearing floor `571e568` (2026-06-10). This revision replaces it.

## Snapshot data

| Dimension | Value (as of `c892824`) | Regenerate with |
| --- | --- | --- |
| Core package size | `glassbox/` ≈ 38.9k LOC | `find glassbox -name '*.py' \| xargs wc -l \| tail -1` |
| Test/harness size | `skills/` ≈ 64.4k LOC | `find skills -name '*.py' \| xargs wc -l \| tail -1` |
| Docs | ≈ 10.8k LOC across `docs/` | `find docs -name '*.md' \| xargs wc -l \| tail -1` |
| Smoke suite | 1908 pass / 23 skip, offline (1931 collected) | `uv run pytest skills/smoke -q --collect-only \| tail -1` |
| Merge gate | green; now also runs a wheel-install packaging smoke | `make check` |
| CI | macOS `make check` (literally, since #68) on PR + self-hosted nightly rig | `.github/workflows/` |
| Gated metrics | 9–10 of 19 printed (7 drop + 2 rise + 1 conditional scroll), config-identity-checked, counts per-round | `grep -n 'GATE_DROP_METRICS\|GATE_RISE_METRICS' skills/regression/computer_use_success_rate.py` |
| History | 344 commits, 20 days old, single author (2 name strings, 1 email), 0 tags | `git rev-list --count HEAD; git log --reverse --format=%ci \| head -1; git log --format=%ae \| sort -u` |

The skipped smoke tests are app-specific fixtures gitignored by design
(`test_profile_match.py`, `test_whitebox.py`); both use skip-if-absent guards, so
deleting the fixtures merges green rather than failing. `make check` ran green
on the current tree during the 2026-06-11 evaluation (1879 passed / 23 skipped,
incl. the regression-gate and golden-audit lanes).

## Strengths

- **The seams are real, not decorative.** `boundaries.py` defines the protocol
  contracts; backends, platforms, and verifiers are discovered via eight
  declared entry-point groups in `pyproject.toml` (`glassbox.app_policies`,
  `.platforms`, `.frame_sources`, `.effectors`, `.ocr`, `.vlm`, `.crawl_policies`,
  `.verifiers`) rather than core edits — 6 of 8 graduated per
  [`../design/architecture_boundaries.md`](../design/architecture_boundaries.md).
  Third-party extensibility is proven end-to-end: a toy external package
  registering a `glassbox.effectors` entry point is discovered and selectable
  from a pure wheel install.
- **Verification of semantic effect, not transport ACK**, is a distinct layer
  (`glassbox/verification/`) rather than asserted in prose — the project's main
  differentiator from ACK-driven computer-use approaches.
- **Honesty discipline is institutionalised and has matured.** The committed
  floor is a real success run; the gate now gates 9–10 of 19 printed metrics
  (was 5), each with a dedicated offline rc=1 smoke test; a nightly
  fault-injection machinery probe exercises the default-on ladder/recovery; the
  A/B ledger ([`flag_cell_ab_matrix.md`](flag_cell_ab_matrix.md)) records
  **kept-OFF negative results** (two flags held off after zero/negative deltas,
  OmniParser kept opt-in despite a Clock 0.8→1.0 win). `AGENTS.md` prohibits
  citing a single headline accuracy number and enforces snapshot-with-sha doc
  discipline.
- **Clean linter-visible hygiene.** ruff fully clean; modern py311 typing; zero
  TODO/FIXME/HACK; zero bare `except`; tests outnumber product code.

## Structural items (priority order)

### 1. Packaging / consumer path is broken (HIGH, offline-fixable)

The core→skills inversion: `glassbox/crawl_policies.py:187,193` imports
`skills.regression.ios_settings.policy` behind a `pyproject`-declared entry
point, and the `glassbox-computer-use-success-rate` console script
(`pyproject.toml:49`) points at `skills.regression.…`. The wheel ships only
`glassbox/`, so both `ImportError` on any non-checkout install; dev/CI mask it
via the editable `.pth`. `.env` is resolved package-root-relative
(`glassbox/__init__.py:41` → `Path(__file__).resolve().parents[1]/".env"`), so a
wheel install looks for `site-packages/.env` and the documented config mechanism
silently no-ops for consumers. The merge gate has **zero packaging coverage**, so
this whole breakage class is structurally invisible. Extensibility itself is
proven true (see Strengths) — the gap is the published-install path, not the seam
design. Highest-leverage move: fix the inversion and add a wheel-install smoke to
the gate.

**Remediation: FIXED (PR #68).** Checkout-only crawl policies degrade with an
actionable error and are no longer advertised as wheel entry points; the broken
console script is gone; `.env` falls back to a `GLASSBOX_`-bearing CWD `.env`
on wheel installs; `py.typed` ships; sdist builds from an allow-list; and
`make packaging-smoke` (wheel build + isolated-venv probe) is part of
`make check`, with `test_packaging_guard.py` pinning the rule class offline.

```bash
grep -n "skills" glassbox/crawl_policies.py
sed -n '44,50p' pyproject.toml
make packaging-smoke
```

### 2. Demonstrated-capability envelope ≪ headline claims (HIGH)

Committed evidence is **2 apps (Settings, Clock) × 1 device (iPad mini 7 en/HK)
× read-only walkthroughs** — zero state-changing tasks. There are **zero
committed iPhone fixtures**; "drives a real iPhone" rests on dated doc prose with
gitignored/deleted artifacts. The nightly zh-iPhone lane compares against the
en-iPad floor and `compare_benchmarks` performs **no config-identity check** (the
identity guard exists only in `validate_floor_candidate`, which gates *promoting*
a floor, not the nightly comparison). Latency is unmeasured and ungated — the
benchmark schema has no duration field, so speed can regress through every gate.
UTG cross-run reuse is default-off with no committed evidence it improves any
outcome. Owner: [`computer_use_quality_roadmap.md`](computer_use_quality_roadmap.md).

**Remediation: PARTIAL (PR #69).** `compare_benchmarks` now refuses
cross-config gating (rc 2; `--allow-config-mismatch` = labelled advisory), the
nightly iPhone lane is explicitly advisory until a device-matched floor
exists, and `action_duration_ms_*` metrics print in every compare so speed is
visible (never gated — host-dependent). **Remaining (rig work, not offline):**
a device-matched iPhone floor, any state-changing task evidence, and a
warm-vs-cold UTG-reuse A/B.

```bash
grep -n "FLOOR_IDENTITY_CONFIG_KEYS\|def compare_benchmarks\|def validate_floor_candidate" skills/regression/computer_use_success_rate.py
```

### 3. Regenerability / single-rig bus factor (HIGH)

7 of 11 gate-load-bearing fixture groups can only be regenerated on the author's
private rig; raw evidence (ledgers, frames) is gitignored, so the repo carries
self-attested verdict JSON. `golden-audit` no-ops (rc 0) on any machine without
ledgers, **including CI** (`skills/regression/golden_ingest.py:203`), and the
documented `make golden-harvest` refresh on a contributor machine would *wipe* the
corpus. Bus factor is 1 for the entire ground-truth layer; merges are 0-approval
self-merges by a single author. Honesty as practiced is self-consistency +
candid labelling, not third-party auditability (tamper experiments confirm
metric-edit and status-flip attempts ARE caught offline — validators recompute
from tasks).

**Remediation: PARTIAL (PR #70).** `golden-harvest` refuses to wipe a
non-empty corpus from a ledger-free host (`--allow-empty` is the explicit
path); the audit's rc-0 no-op announces itself as skipped-by-design; and the
three gate-load-bearing fixtures flipped skip-if-absent → FAIL-if-absent.
**Remaining (structural):** 7/11 fixture groups stay regenerable only on the
author's rig, and bus factor 1 with 0-approval merges is a fact of a
single-maintainer project — recorded, not fixable offline.

```bash
git log --format='%an <%ae>' | sort | uniq -c
sed -n '200,215p' skills/regression/golden_ingest.py
```

### 4. Residual gate vacuity + nightly-lane calibration (MEDIUM)

This is residual, not regression — the prior #1 was fixed. `compare_benchmarks`
now gates `GATE_DROP_METRICS` (7) + `GATE_RISE_METRICS` (2) + a conditional
`scroll_success_rate` drop (`computer_use_success_rate.py:81-93`), each with
offline coverage (`skills/smoke/test_computer_use_regression_gate.py`, 23 tests).
But the committed floor (`fixtures/reliability_baseline.json`) reports
`strategy_switches=0` and `vlm_action_coverage=0.0`, so those two drop-gates are
**vacuous on the blocking lane** (disclosed in the fixture's own note; mitigated
by an L2 snapshot-`>0` smoke pin + the nightly machinery probe, which blocks
within the nightly but the nightly never gates merges). `unknown_rate=0.0` is
likewise a floor. Owner:
[`computer_use_honest_gate_first.md`](computer_use_honest_gate_first.md).

**Remediation: PARTIAL (PR #69).** Raw counts now gate per round (a 2-round
candidate is no longer a fake regression against the 5-round floor), and every
vacuous drop-gate announces itself on each compare run — "printed and gated"
can no longer read as "protected". **Remaining:** the vacuity itself ends only
when a floor with non-zero `strategy_switches`/`vlm_action_coverage` is
promoted (a rig run); until then the L2-snapshot pin + nightly machinery probe
stay the real teeth.

```bash
sed -n '81,97p' skills/regression/computer_use_success_rate.py
```

### 5. Architecture debt against defined boundaries (MEDIUM)

Platform seepage **grew to 8 sites** (was 3). The three classic ones still hold —
`runtime.py:30` top-level `glassbox.ios.settings_rows`, `perceptor.py:287-289`
platform-keyed dynamic annotator imports, `ai.py` localized `_APP_ALIASES` — plus
e.g. `phone.py:451`'s unconditional iOS `AssistiveTouchDriver` on the neutral
`Phone` facade and a top-level ios import in `target_planner.py`. `Phone` is now
**229 methods / 2211 lines** and out-bulks the **3784-line** orchestrator. Broad
`except Exception` count is **114** (~77 swallow silently; ruff's select list
omits BLE/TRY so this merges green). Logging is split **68 `print()` vs 54
loguru/logger** calls in library code, with real failure paths reporting via
`print`. Owner: the seam contracts in
[`../design/architecture_boundaries.md`](../design/architecture_boundaries.md).

**Remediation: PARTIAL (PR #73).** The platform-neutral modules (`runtime`,
`target_planner`, `app_policies`, `ai`) no longer import iOS modules eagerly —
the facade's zh alias table moved to `glassbox/ios/app_aliases.py` — and a
subprocess guard pins the rule; 49 library `print()` sites converted to loguru
(UTG save/load and profile-load failures are now visible to log collectors),
with an allow-list guard for CLI-only prints. **Remaining (needs its own
design pass):** the `Phone` (229 methods) / orchestrator (3.8k lines)
decomposition, perceptor's platform-keyed (already-lazy) annotator imports,
the unconditional AssistiveTouchDriver collaborator, and the broad
silent-`except` population beyond the critical paths.

```bash
grep -c "def " glassbox/phone.py; wc -l glassbox/phone.py glassbox/action/orchestrator.py
grep -rn "except Exception" glassbox --include="*.py" | wc -l
uv run pytest skills/smoke/test_platform_neutral_imports.py -q
```

### 6. Runtime robustness edges (MEDIUM, one cluster)

The per-action core is strong (budget-bounded retries, atomic UTG writes, VLM→OCR
degrade, P2/P3 ladder default-on). Weak edges, all default-on via the facade:
disk-full kills the run (Recorder/AuditSink writes unguarded, unbounded PNG
growth); a torn last line in `events.jsonl` breaks all replay consumers; the OCR
watchdog (`GLASSBOX_OCR_TIMEOUT`) is enabled on no committed path and the
default-on icon/layout YOLO stage has no hang protection; a mid-gesture HID
failure can latch the pointer button (`reset_hid_state` has no callers on failure
paths); VLM parse-failures are disk-cached permanently by frame hash (poisoning,
no TTL). Owner: [`computer_use_quality_roadmap.md`](computer_use_quality_roadmap.md).

**Remediation: FIXED (PR #72), all six.** Recorder/AuditSink degrade loudly
instead of dying; torn trailing `events.jsonl` lines are skipped (mid-file
corruption still raises); `GLASSBOX_OCR_TIMEOUT=20` armed on the committed rig
paths (global default untouched); press-bearing PicoKVM gestures best-effort
`reset_hid_state()` on mid-gesture failure; `CachedVLM` refuses to persist
parse-failed responses and heals poisoned entries on read; the facade
re-raises stability timeouts as `AIAssertionError` with an actionable message.
14 new smoke tests pin the behaviors.

## Corrected by adversarial review

- **"scene_progressed agrees with humans 0/29"** → all 29 are `verifier_status=
  'unknown'` **abstentions** on `op='drag'` (zero wrong assertions; 12/29 were
  achieved-but-unasserted). An abstention/recall gap, not 29 wrong calls.
- **"the scheduled nightly disables the default-on ladder"** → intentional
  baseline-lane semantics, documented in `rig-nightly.yml`; the machinery probe
  sets ops explicitly. Not a bug; a clarifying note at most.
- **"PicoKVM stream stall hangs forever"** → bounded by OpenCV/FFmpeg's default
  30 s AVIO interrupt watchdog (confirmed on installed opencv 4.13.0). Caveat:
  it's an upstream default the repo neither sets nor tests — a dependency bump
  could change it.

### 7. Docs drift (LOW — verify before citing)

Top-of-funnel docs (`README`/`AGENTS`/`ONBOARDING`) verify almost entirely, but
three claims are now wrong: two docs still state "main is NOT branch-protected"
(`computer_use_honest_gate_first.md:79` and `../design/code_health_roadmap.md`),
contradicting `AGENTS.md` and live `gh api`; `README.md:165` documents a
**nonexistent `glassbox.icon_detectors` entry-point group** (icon backends
actually load via a directory scan, `icon_detect.py:165`); and `ONBOARDING.md`
never mentions VLM or API keys though the `run_full` harness defaults VLM on
(`skills/regression/ios_settings/config.py` sets `GLASSBOX_ENABLE_VLM=1`) — a
new operator's first cold-start run hits a "Missing API key" failure.

**Remediation: FIXED (PR #71).** All three wrong claims corrected, the two
stale status lines updated (screen_memory.md now says the UTG shipped;
rig-validation Phase E credits the shipped `tap` laddering), and the dangling
references removed.

```bash
grep -rn "not branch-protected\|NOT branch-protected" docs/
grep -n "icon_detectors" README.md
grep -n "GLASSBOX_ENABLE_VLM" skills/regression/ios_settings/config.py
```

## Bottom line

**Honest-alpha; trajectory exemplary** — the prior eval's own prescriptions
landed within days, and this eval's offline-fixable items were remediated the
same day (PRs #68–#73; plus a settings-level hardening: the repo's Actions
fork-PR approval policy was raised from `first_time_contributors` to
`all_external_contributors`, closing the main fork-workflow path to the
self-hosted `picokvm` runner — note the runner registry read 0 runners at
audit time, so the exposure was latent, returning whenever the rig host
re-registers). The risk axis has **moved** from metric-scope (fixed) and
packaging (fixed) to **evidence scope and structure**. What remains, priority
order:

1. **Device-scope evidence (rig work):** a device-matched iPhone floor (or a
   deliberate decision to stay iPad-only and say so in README), at least one
   state-changing task, and a warm-vs-cold UTG-reuse A/B — item 2,
   [`computer_use_quality_roadmap.md`](computer_use_quality_roadmap.md).
2. **End the residual gate vacuity** by promoting a VLM-on floor with non-zero
   `strategy_switches`/`vlm_action_coverage` — item 4,
   [`computer_use_honest_gate_first.md`](computer_use_honest_gate_first.md).
3. **`Phone`/orchestrator decomposition** (229 methods / 3.8k lines), a config
   preset layer, and billed-VLM-client tests — item 5,
   [`../design/architecture_boundaries.md`](../design/architecture_boundaries.md).
4. **Latency from visible to gated** once duration baselines accumulate
   (the new `action_duration_ms_*` metrics make speed visible in every
   compare; gating needs per-host baselines first) — item 2.
5. Structural facts to keep stating, not fix: single-rig regenerability
   (7/11 fixture groups), bus factor 1 with 0-approval merges — item 3.
