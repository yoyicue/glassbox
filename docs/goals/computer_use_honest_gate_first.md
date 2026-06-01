# Goal — Honest-gate-first redirection (fix the compass before the engine)

Status: **in progress (2026-06-01).** Phase-0 implementation has started: the
offline smoke gate now rejects a committed floor with zero task completion, and
the fixture headline text no longer treats `action_success_rate` as the
reliability number. A real iPad quick n=5 smoke now emits an aggregate with
`task_completion_rate=1.0` / variance `0.0`, but the full drill-down n=5 still
fails before it can replace the committed floor. The remaining blocker is a
completed multi-round full drill-down floor. This doc is the trackable
redirection plan; it is a strategic companion to
[`computer_use_quality_roadmap.md`](computer_use_quality_roadmap.md) (which says
*what reliability machinery to build/wire*) and
[`../design/ipad_settings_state_machine.md`](../design/ipad_settings_state_machine.md)
(the iPad C1–C5 model fixes). This doc says **why effort has not converted to
utility, and the order to fix it in.**

## Headline

> glassbox feels "complex but low utility" because it is steered by a metric
> uncorrelated with the goal, behind a gate that can never fail. The complexity
> is real; the compass is broken. Fix the compass first, then narrow the domain,
> then let the real number decide which complexity to keep.

The single committed end-to-end floor
(`skills/regression/fixtures/reliability_baseline.json`) finished `outcome:
"failed"`, sitting in the **Weather app**, with `task_completion_rate = 0.0` — yet
its published headline is `action_success_rate = 0.955`, and that fixture passes
`make check` **green**.

## 1. The mechanism (re-verified 2026-06-01)

| Fact | Evidence (personally verified this session) |
|------|---------|
| The floor is a *failed* run | `reliability_baseline.json`: `task_completion_rate=0.0`, `tasks[0].outcome="failed"`, `final_state.page_id=null`, final `visible_texts` are Weather ("MY LOCATION", "10-DAY FORECAST") |
| The 0.955 headline is a back-dominated per-tap ACK | op breakdown in the fixture: **back 59, tap 48, scroll_wheel 9, home 2, type 1, open_app 1, long_press 1** (121 actions; the 112 denominator drops the 9 scroll "fillers"). `action_success_rate=0.9553571` |
| The load-bearing primitive is failing | `scroll_success_rate=0.2222` (2/9 succeed, 7 unknown) — the mechanical reason the run never reached lower sections / root |
| Key verification stages never fired | `expected_state_coverage=0.0`, `vlm_action_coverage=0.0`, `vlm_calls=0`; `strategy_switches=5`, so the ladder did switch, but not with expected-state or VLM coverage |
| The task-completion gate cannot fail on this floor | `compare` gate at `computer_use_success_rate.py:1184` trips only on `delta < -tolerance` for `{task_completion_rate, action_success_rate, root_pages_coverage}`. A floor pinned at `task_completion_rate=0.0` cannot reject another zero-completion candidate on task completion |
| …and `make check` doesn't even run that gate | `regression-gate` (`Makefile:36-38`) runs `validate` (schema-only) + `test_computer_use_regression_gate.py`, whose floor test (`test_committed_baseline_fixture_is_schema_valid`) checks **schema only**. `compare` runs only in `regression-compare`/`ab-semantic-plan` (`Makefile:45,64`), which need a live rig. **So the failed floor passes offline CI green.** |

**Net:** the number being optimized and ratcheted (`action_success_rate`) does not
measure task success and structurally masks failure; the gate guarding it cannot
go red offline. That is the precise, mechanical source of "complex but low utility."

## 2. The four convergent root causes

A 12-agent diagnosis (4 lenses × honest-performance / complexity-vs-payoff /
physical-ceiling / scope) plus 4 adversarial verdicts converged on:

1. **Broken compass (above).** Metric uncorrelated with goal + un-failable gate.
   This is lever #1: until it's fixed, no other work can be trusted.
2. **The strongest capabilities are off the default path — and the crawler bypasses
   the orchestrator entirely.** The Settings crawler navigates via
   `phone.tap_xy(cx,cy)` (`skills/regression/ios_settings/navigation.py:163,254,455`
   → `glassbox/phone.py:1613` → gesture executor), **bypassing**
   `default_semantic_action_plan` and expected-state verification for those row
   taps. That is why the floor shows `vlm_calls=0` / `expected_state_coverage=0`,
   even though `strategy_switches=5` on other primitives. Much of the
   recovery/strategy/VLM machinery is *not on the path that actually matters for
   row entry.* Of 29 bool config flags, **26 default False**
   (`glassbox/config.py`). This is the same root cause named in
   [`../design/computer_use_success_rate.md`](../design/computer_use_success_rate.md):
   "the strongest capabilities are not on the default path."
3. **iPhone is fighting physics.** Three hard, live-proven HID ceilings (iOS ignores
   USB HID digitizer; mouse wheel ~5–7% intermittent and unrevivable → no precise
   scroll primitive; no keyboard system-nav). The **iPad path dissolves all three**
   (native pointer + 9/9-validated wheel + keyboard nav) and is already default-on
   (`glassbox/effectors/picokvm/effector.py:208,223`). The out-of-band HDMI+HID
   substrate is right for the "no on-device code" goal — it was just pointed at the
   wrong device.
4. **No honest "done", velocity decoupled from outcome.** ~191 commits / 9 days with
   floor `task_completion` still 0.0; the L1 lever is on its 6th doc-review pass and
   rig-A/B'd ship-negative (en/HK B `task_completion` **1/3** with `entered_graph` 7
   but crash 2/3; A `task_completion` 2/3 but `entered_graph` 0; zh runs are
   broken/contaminated — `ipad_settings_l1_rig_ab_handoff.md:39-46,103-105`). `main`
   is not branch-protected (`../design/code_health_roadmap.md:83`).

## 3. The plan

All four independent strategy proposals converged on the **same first move**, and
the adversarial review corrected *where it must be wired*. Phases are strictly
ordered: do not start a phase before the prior one's gate is real.

### Phase 0 — Fix the compass (this week · no hardware · fully reversible)

- **0.1 Make the failed floor go red offline.** **Implemented in code.** Add a one-line assertion to
  `skills/smoke/test_computer_use_regression_gate.py` (or to `validate`) that the
  committed floor's own `metrics.task_completion_rate > 0` **and** every
  `tasks[*].outcome != "failed"`. *This — not a `compare` edit — is what makes
  `make check` red on the current Weather-app floor, with zero hardware.* (The
  `compare`/`--min-task-completion` change is still worth adding, but it only
  hardens the nightly rig path.)
- **0.2 Re-headline.** **Implemented in prose/fixture metadata.** In `skills/regression/fixtures/README.md` and the fixture's
  `config.note`, lead with `task_completion_rate` (currently 0.0) and stop calling
  `action_success_rate=0.955` "the reliability number"; label it a
  scroll-excluded, back-dominated per-tap ACK proxy.
- **0.3 Branch-protect `main`** (one `gh api -X PUT …/branches/main/protection`
  requiring `check`, with an admin bypass). Otherwise a red gate is theater on a
  191-commit/9-day history.
- **0.4 Set the absolute bar to `> 0`** **Implemented in the smoke assertion.** Set the bar to `> 0`, not an aspirational 0.34. The
  Phase-0 goal is only "a failed run can no longer pass." Ratchet later, from real
  data.

**Phase-0 done-bar:** `make check` is RED on the current committed floor; the
headline number everyone quotes is `task_completion_rate`.

### Phase 1 — Move the number off 0 (next 1–2 weeks · iPad rig)

- **1.1 Freeze the ODD.** The only gated task is the iPad mini 7 / **en-HK**
  Settings read-only drill-down. Drop the zh-iPhone `make
  computer-use-success-rate-ios-settings` target from the gate (iPhone fights
  physics — root cause #3).
- **1.2 Make `n` visible.** `computer_use_success_rate run-ios-settings` now
  exposes the outer `--rounds N` loop on the iPad `run_full` path, can pass
  `--language en --region HK` into each round, can keep going after a failed
  round, and emits `task_completion_variance`. Run **n ≥ 5** and emit the
  aggregate benchmark plus the per-round reports/artifacts. **First honest
  milestone: `task_completion > 0 at n=5` with per-round evidence — quick mode
  now shows this; the full drill-down has not yet.**
- **1.3 Move the number with the right lever, in the right order.** `entered_graph`
  is **L1's** signal (the virtual `settings/root` projection), *not L4's*:
  `ipad_settings_l1_rig_ab_handoff.md` shows `entered_graph` 0→7 only when L1 is ON.
  L4 (deterministic, row-tracked scroll — VLM-free, iPad wheel 9/9) is a
  **precondition** for L1, not an independent `entered_graph` lever. Correct
  sequence: **L4 first, then flip L1 on** behind the same en/HK n≥5 harness.
  - Caveat to clear first: the floor fixture has **no `entered_graph` field**
    (verified: 0 occurrences) — do *not* add it to the gated keys until the harness
    emits it. Gate Phase-1 on `task_completion_rate` (present) only.
  - Locale caveat: `policy.py` has a base `EXPECTED_ROOT_NAV_TEXT` (:63) plus a ZH
    variant `EXPECTED_ROOT_NAV_TEXT_ZH` (:130). Confirm the en/HK English labels
    resolve through `canonical_expected_root_label` before trusting any en
    `entered_graph` count.

**Phase-1 done-bar:** the en/HK drill-down reports a real `task_completion` mean +
variance at n≥5, and the chosen lever moves it measurably above 0 across rounds.

**Current rig evidence (2026-06-01):**

- Full drill-down n=5, default path:
  `artifacts/computer_use_success_rate/honest_gate_en_hk_n5_v2.json` was not
  produced. Round 0 verified `OK`; round 1 failed report verification with
  `required_missing=["隐私与安全性"]` and `navigation candidate did not open:
  Settings > 隐私与安全性`.
- Full drill-down n=5 with
  `GLASSBOX_SETTINGS_SEARCH_ROOT_FALLBACK_SIDEBAR=1` also did not complete; round
  0 crashed with `SettingsRootUnreachable` while returning to root during the
  scroll loop.
- Quick drill-down n=5 with keep-going and skipped per-round exhaustive verify
  did complete:
  `artifacts/computer_use_success_rate/honest_gate_quick_n5.json` validated with
  `task_completion_rate=1.0`, `task_completion_variance=0.0`,
  `root_pages_coverage=0.2353`, `expected_state_coverage=0.0`, and
  `vlm_action_coverage=0.0`. This is useful smoke evidence, but it is not the
  full floor required to replace `reliability_baseline.json`.

### Phase 2 — Prune complexity (only after the number moves)

- **2.1 Let the real per-task number decide.** Now — and only now — judge the
  recovery/strategy/VLM machinery by whether it moves *this task's* number. To make
  expected-state/VLM verification count for row entry, the crawler must route row taps through `phone.semantic` instead
  of `tap_xy` — **a real architecture change, not a flag flip** (root cause #2).
  Whatever doesn't earn its place gets deleted.
- **2.2 Delete for maintenance, not for determinism.** Removing dormant or
  low-yield branches may reduce drag, but will **not** by itself collapse
  run-to-run variance — that lives in the OCR/hardware substrate (22% scroll,
  false-positive scene classification), not only in the ladder. Do not sell
  deletion as determinism.

## 4. What to stop doing

- **Stop** quoting/optimizing `action_success_rate` as the reliability number.
- **Stop** shipping n=1 single-round floors as ratcheting baselines.
- **Stop** the L1 doc-review treadmill (now 6 passes) until the gate rewards the
  metric that judges it.
- **Stop** spending default-path budget on iPhone while the iPad ODD is unproven.
- **Stop** adding new default-off flags / parallel perception backends until the
  existing ones demonstrably move the one task's `task_completion`.

## 5. Why this order (the strategic turn)

Today's posture is L4-style autonomy — cascading fallbacks, recover-from-anything,
strategy ladders — while delivering L0–L1 utility. The redirection is the inverse:
**fix the compass → narrow to a physics-clean device + one task → push the real
number past 90% → then let that number tell you which complexity to keep or cut.**

## 6. Verification ledger (what is solid vs relayed)

**Personally re-verified against the tree this session** (2026-06-01): the floor's
`outcome="failed"` / `task_completion_rate=0.0` / `expected_state_coverage=0` /
`vlm_calls=0` / **`strategy_switches=5`** / `scroll_success_rate=0.2222` /
`action_success_rate=0.9553`; the op breakdown (back 59 / tap 48 / scroll 9 / …);
the gate logic at `computer_use_success_rate.py:1184`; that `regression-gate` runs
`validate` + a schema-only smoke test and **not** `compare` (`Makefile:36-38`); the
crawler's `tap_xy` path (`navigation.py:163,254,455` → `phone.py:1613`); the floor
fixture has **0** `entered_graph` fields; `config.py` has **26** `bool = False` vs
**3** `bool = True`; the L1 A/B median table (`ipad_settings_l1_rig_ab_handoff.md:39-46`).

**Relayed, re-confirm before acting:** `main` branch-protection status (a live `gh`
check timed out on network; `code_health_roadmap.md:83` records it as unprotected —
re-run `gh api repos/<owner>/glassbox/branches/main/protection`). The iPhone HID
ceilings are from prior on-rig experiments recorded in MEMORY, not re-run here.

> Per the repo's own rule (`no-hand-counted-baselines-in-docs`): every count above
> is a snapshot — regenerate with the inline `grep`/fixture reads before citing in
> a PR; do not trust the prose if HEAD has moved.
