# Computer-Use Quality — On-Rig Validation Runbook

Companion to `computer_use_quality_roadmap.md`. The roadmap's offline-implementable
items are shipped (PRs #2–#24): each is **default-safe or flag-gated**, so the
default code path is byte-identical until a flag is flipped. This runbook is the
executable next step — it turns the shipped gated flags and the remaining
rig-dependent items into one ordered checklist with a validation gate and a
rollback for each.

Everything here needs a live PicoKVM rig (iPhone and/or iPad mini 7) because the
open questions are all "does this actually raise the success rate / hit the right
control / read the right pixels on real hardware" — none can be answered offline.

## How to run a validation pass

Each flag is validated by a **before/after A–B comparison** on a fixed task set,
not by eyeballing one run. The harness already exists:

```bash
# 1. Baseline (all flags default-off) — capture once per rig session.
uv run python -m skills.regression.computer_use_success_rate --label baseline ...

# 2. Flip ONE flag, re-run the SAME task set.
GLASSBOX_<FLAG>=1 uv run python -m skills.regression.computer_use_success_rate --label <flag> ...

# 3. Compare. The compare gate reports task_action_success_rate / unknown_rate
#    deltas (scroll fillers excluded — CUQ-3.1) and the P1/P2 coverage columns
#    (CUQ-3.2). A flag PASSES only if task_action_success_rate does not regress
#    AND its intended metric moves the right way.
```

**Golden rule: flip exactly one flag per pass.** The flags interact (e.g.
`strict_target_matching` changes which element a tap resolves; `reverify_fresh_frame`
changes the verification verdict), so a multi-flag flip makes a regression
un-attributable. Validate singly, then validate the winning combination once more
together before committing a new default.

**Rollback for every flag is the same:** unset the env var (or revert the default
in `config.py`). Because the default path is byte-identical, rollback is free and
total — there is no migration to undo.

---

## Phase A — Measurement & observability (flip first; lowest risk)

These do not change actuation; they make the later phases *judgeable*. Turn them
on at the start of the rig session and leave them on.

| Flag / setting | Roadmap | What to confirm |
| --- | --- | --- |
| `GLASSBOX_MEMORY_AUTOSAVE_EVERY=12` (already the default; tune) | CUQ-3.22 | UTG graph autosaves every N observations; confirm the snapshot file grows and survives a crash mid-run. Lower N if a long run loses graph state. |
| Harness P1/P2 coverage columns | CUQ-3.2 | Confirm `expected_state_coverage` / `vlm_action_coverage` are **non-zero** on a real run (they were structurally zero before). If still zero, the expected-state plumbing (Phase C / CUQ-0.3) is not reaching production calls — fix that before trusting any later A–B. |
| `derive_fit_from_crop` (PicoKVM config) + `fit_calibration_warning` | CUQ-3.5 / 3.9 | Confirm the inconsistent-fit and unvalidated-wheel warnings fire on a mis-calibrated rig and stay silent on a good one. These are your tripwires for the calibration phase. |

**Gate:** the coverage columns must be non-zero before Phase B/C numbers mean anything.

---

## Phase B — Precision & recognition flags (medium risk; A–B each)

Flip one, run the task set, compare. Each targets a specific "wrong target / wrong
scene" failure class — watch that class, and watch `task_action_success_rate` for
collateral regressions.

### `GLASSBOX_REVERIFY_FRESH_FRAME=1` — CUQ-1.3
- **Enables:** before a VLM verification escalation, re-perceive a fresh frame and
  re-verify; a settled-late text resolves without spending the VLM call.
- **Validate:** on a task set with slow-settling screens (post-tap spinners,
  network rows), confirm (a) `vlm_calls` per action **drops** (fresh OCR catches
  the text first) and (b) `task_action_success_rate` holds or rises. The
  `expected_state_refresh` verifier should appear in the audit.
- **Watch for:** extra capture+OCR latency with no VLM savings → the screens
  settle before the post-action capture, so the fresh read is redundant; leave off.

### `GLASSBOX_STRICT_TARGET_MATCHING=1` — CUQ-1.5 (also covers CUQ-1.4)
- **Enables:** `find_text`/`find_button`/`find_by_intent` prefer the closest-length
  containing row and return no-match when the fuzzy best doesn't beat the
  runner-up → an ambiguous read escalates instead of guessing. This is also the
  mitigation for the explore-path label ambiguity (CUQ-1.4).
- **Validate:** on pages with repeated/substring labels (a row label that is also
  a nav title), confirm taps land on the **row**, not the title, and that
  genuinely-unique labels still resolve (no recall loss → `unknown_rate` must not
  spike).
- **Watch for:** previously-working unique-label taps now returning unknown → the
  margin is too strict; needs a threshold tune before default-on.

### `GLASSBOX_REQUIRE_HOME_ICON_GRID=1` — CUQ-2.2
- **Enables:** `is_ios_home_screen` requires icon-grid corroboration before trusting
  a bare `springboard` classification as Home (closes the "Settings detail page
  mislabeled springboard → tap a row as an app icon" false-positive).
- **Validate:** confirm the real Home screen is still recognized as Home (no
  bootstrap regression) AND a scrolled Settings page is no longer mistaken for Home.
- **Watch for:** Home no longer recognized on a sparse/edited Home layout → the
  grid threshold is too strict.

### `GLASSBOX_DETECT_ICONS_IN_PERCEIVE=1` — CUQ-2.1
- **Enables:** the no-text icon detector runs in `perceive()` and injects icon-only
  controls (+, share, gear, back-chevron, trash) as tappable image elements.
- **Validate:** on screens whose only control is an icon, confirm the icon becomes
  a tap candidate and the task can proceed (previously impossible). Confirm scene
  **classification is unchanged** (icons injected after classifiers) and per-perceive
  latency stays acceptable.
- **Watch for:** spurious icon boxes adding noise to the candidate set / raising
  `unknown_rate`.

---

## Phase C — Strategy ladder (the big one: needs code + rig together)

### Finish CUQ-0.1 / 0.8, then flip `GLASSBOX_SEMANTIC_PLAN_OPS`
The foundation + `back` are shipped and flag-gated. Remaining **code** work
(mechanical, same pattern as `back`): wire `scroll` / `tap` / `launch_app` onto
`default_semantic_action_plan`, with the nested-orchestration suppression noted in
CUQ-0.8 for `tap`/`launch_app`/`home` (the AssistiveTouch-home strategy callable
re-enters the orchestrator — suppress that nesting so outer attempt artifacts stay
clean).

- **Validate incrementally:** flip `GLASSBOX_SEMANTIC_PLAN_OPS=back` first, confirm
  a verified-failed `nav_back_tap` actually switches to `keyboard_back` →
  `edge_back_gesture` on the rig (the whole point — strategy laddering). Then add
  `home`, then `scroll`, etc., one op per pass.
- **Gate:** for each op, the ladder must recover a case the legacy single-shot path
  gave up on, with no regression on the cases it already handled.
- **Then:** once all ops validate, set `GLASSBOX_SEMANTIC_PLAN_OPS=home,back,scroll,tap,launch_app`
  and consider flipping the default.

This is the highest-leverage remaining item: it is the difference between "one
strategy, give up on failure" and "try the next reliable primitive."

---

## Phase D — Calibration & persistence (rig-tuned)

### `actuation_profile_dir` default-flip — CUQ-3.6
- The safety enabler is shipped (loading a profile no longer carries a stale
  `unactuatable` verdict, only the offset). **Remaining:** default
  `GLASSBOX_ACTUATION_PROFILE_DIR` to the per-device memory path and populate
  `os_version`.
- **Validate:** run a session, let it learn an offset, restart, confirm the loaded
  offset **helps** (taps land closer) rather than mis-corrects. If offsets drift
  per session, keep persistence off.

### Per-session auto-calibration probe — CUQ-3.7 (code + rig)
- Currently relies on mid-run correction. **Implement** a one-time probe at session
  start (tap a known anchor, measure the landing error, seed the offset) so the
  first taps are already calibrated. Validate the seeded offset beats cold-start.

---

## Phase E — Remaining rig-dependent code items

These need a rig to even exercise, so they were not built offline. Priority order:

1. **CUQ-0.3 — expected_state on the production walkthrough/crawler.** Without it
   the P1/P2 coverage (Phase A) stays low and the ladder (Phase C) has nothing to
   verify against. High leverage; pairs with Phase A/C.
2. **CUQ-3.4 — canonical-primitive task benchmarks** (go-home / launch-app / back /
   scroll-to-bottom). These give the A–B passes above a stable, meaningful
   denominator. Build alongside the first rig session.
3. **CUQ-0.5 — generic `try_memory_path` recovery consumer.** The UTG graph + the
   `recover_to_home_then_renavigate` hook are wired; this adds the generic caller
   that replays a known path to re-navigate after a stuck-loop. Validate it
   actually recovers a deliberately-stuck run.
4. **CUQ-3.15 — generic AI scroll uses the wheel on iPad.** iPad wheel-scroll is
   confirmed working via RPC; route the generic scroll primitive to it on iPad
   (precise) instead of swipe-fling (overshoot). iPad-scoped; validate coverage.
5. **CUQ-2.6 — `settings_detail` false-positive tightening.** Safety-critical
   classifier; needs real third-party-app frames to confirm it cuts false-positives
   **without** losing real-Settings recall. Flag-gate, then A–B on a mixed frame set.

---

## What is intentionally NOT pursued (and why)

Recorded so these aren't re-attempted as quick wins:

- **CUQ-1.4** — subsumed by CUQ-1.5 on the live path; residual is non-live +
  behavior-changing (see the roadmap entry).
- **CUQ-3.11** — `Frame.ts` is decode-time (always ≈now), so an absolute decode-age
  check can't catch buffer-stale *content*; that staleness is already handled by
  `fresh_snapshot` reopen + the dhash/diff freshness checks.
- **CUQ-3.18** — `close_foreground_app` coords are fractions of a fixed
  `abs_logical_max`, so they already scale proportionally across aspect ratios;
  no iPhone→iPad re-derivation needed.
- **CUQ-2.8** — subsumed by CUQ-1.5's substring/fuzzy guard.
- **CUQ-3.17** — lives in `ipad_mini_migration.md`, which has uncommitted local
  edits; resolve there directly, not via this campaign.
