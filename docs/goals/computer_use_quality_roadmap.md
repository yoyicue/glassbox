# Goal — Raise end-to-end computer-use quality (wire the reliability machinery)

Status: **~40 items shipped (PRs #2–#34), then post-hoc audit-hardened.** A
13-dimension, adversarially-verified code review (70 confirmed findings) found
that the biggest computer-use quality lever is **wiring the already-built
reliability machinery into the production path**, not building more. The
machinery is now wired (default-safe or flag-gated). This doc is the trackable
gap-list and sequencing plan.

> **Post-campaign audit (2026-05-29):** a 78-agent adversarial audit of the full
> campaign diff (`main...pass-33`, 6 risk dimensions, 31/36 findings confirmed)
> hardened the result. Fixes applied: CUQ-0.4 selection-time VLM reground is now
> flag-gated (`vlm_reground_selection`, default off) — it had been running on any
> VLM-wired run, the one true byte-identity leak; the status-bar clock filter
> (CUQ-2.7) is now position-anchored so body time rows ("5:00 AM", "3:45") stay
> tappable; the unactuatable gate (CUQ-1.2) gained a hard-cap escape hatch so a
> single-identity dead control is eventually disabled, and load (CUQ-3.6) now
> clears a stale `unactuatable` label; the reground path honors the ambiguity
> guard (CUQ-1.5); letterbox hysteresis (CUQ-3.14) is jitter-tolerant. Plus
> mutation-killing wiring tests for the previously-untested config→Phone→consumer
> legs, and a default-on changelog in the rig runbook to honestly scope the
> byte-identity claim. It is the operational companion to
[`docs/design/computer_use_success_rate.md`](../design/computer_use_success_rate.md):
that doc says *what to build* (Step 0 / P1 / P2 / P3); this doc records *what is
built but not wired*, plus the independent correctness leaks found alongside.

## Headline

> glassbox's reliability engine is built but not plugged in. The design doc's own
> 2026 root-cause — *"the strongest capabilities are not on the default path"* —
> **still holds.** P1 (VLM gated escalation), P2 (strategy ladder +
> expected-state verification), and P3 (stuck → recover-to-anchor) exist as
> unit-tested foundations with **no production caller**. Several design-doc
> "implemented + orchestrator integration" claims are therefore overstated; they
> mean *"foundation present, not wired on the live path"* (see
> [Doc-honesty corrections](#doc-honesty-corrections)).

The foundations are healthy — the audit explicitly rejected the over-pessimistic
reads (stable-frame IS on by default via the AI facade; the VLM gate IS
constructible; the letterbox crop is NOT a one-shot startup measurement; see
[Verified NOT-issues](#verified-not-issues--do-not-re-litigate)). The work is
wiring + a batch of independent quick-win correctness fixes.

## Method & provenance

- 13 parallel subsystem readers (capture, OCR, scene-classification, VLM gate,
  candidate selection, orchestrator, actuation, verification, recovery, input
  fidelity, screen-memory, calibration, measurement), each comparing design-doc
  intent vs actual code.
- Every significant finding was independently re-read by an adversarial verifier;
  9 of 95 raw findings were rejected as wrong/already-handled and are recorded
  below so they are not re-litigated.
- Grounding run data (latest iPhone v3 drill-down): nav-success-proxy 95.7%, but
  9 `unknown` semantic outcomes + 6 no-progress in one walkthrough, `limits_hit`
  = `max_depth` — consistent with "verification leaks unknown" and "scroll
  dominates the action mix".

## Subsystem grades

| Grade | Subsystems |
| --- | --- |
| 🔴 leaky | VLM gating, orchestrator/strategy-ladder (P2), recovery/stuck (P3), success-rate measurement |
| 🟠 fragile | frame capture/freshness, candidate selection, actuation primitives, verification, HID input fidelity, screen-memory graph, calibration |
| 🟡 adequate | OCR/text-matching, scene classification |

## How to read item IDs

`CUQ-<tier>.<n>`. Each item: status checkbox, severity, effort, the gap, file
evidence, fix, and acceptance. Severity is the **adversarially-corrected** value.
Tiers are leverage-ordered: **Tier 0 (wiring) is worth more than Tiers 1–3
combined** because the machinery already exists and is tested.

---

## Tier 0 — Wire the existing machinery into the production path (highest leverage)

All of these are facets of one root cause, confirmed independently ~10×. Gate
every change on the Step-0 harness; ship behind a flag, then default-on.

### CUQ-0.1 — Route core ops through `default_semantic_action_plan` (the strategy ladder is dead code)
- [~] **critical→high · effort large · design-gap** — FOUNDATION + `back` DONE (flag-gated, default-off): added `cfg.semantic_plan_ops` (env `GLASSBOX_SEMANTIC_PLAN_OPS`) wired to `Phone._semantic_plan_ops`; `Phone._run_semantic_plan` builds `default_semantic_action_plan` and runs it through the orchestrator's `_execute_semantic_plan`. `back_gesture()` now routes through the `nav_back_tap → keyboard_back → edge_back_gesture` ladder with verified-failure switching when `back` is flagged (vs the legacy single-shot if/elif). **Key enabler:** `SemanticActionSpec.expected_state` is now optional — when None the op's *generic verifier* drives the ladder, so ops without a caller-supplied expectation can still switch strategies (orchestrator no longer injects a permissive expected_state that would short-circuit). Also fixed a latent frozen-`ActionResult` mutation bug in `_phone_nav_back_tap` that the (previously uncalled) binding hid. Tests: optional-expected_state round-trip, flag-on ladder routing, flag-off legacy. **`scroll` ALSO DONE** (flag-gated): `AIPhone._phone_scroll` routes through `_run_semantic_plan("scroll", direction=...)` when `scroll` is flagged, laddering **wheel → swipe** with verified-failure switching (the scroll plan's `drag` strategy is bound to the backend's preset swipe by direction, and the `wheel` sign follows the direction — no raw-coord mismatch). Tests: direction-aware wheel-sign + drag→swipe binding, and AIPhone routing-through-plan when flagged. **Remaining:** `tap`/`launch_app` (need the nested-orchestration suppression noted in CUQ-0.8; `home` already ladders bespoke), then on-rig validate and flip default-on.
- Gap: `SemanticActionPlan` / `default_semantic_action_plan` have **zero
  non-test callers**. Every real action takes the legacy `_execute_action`
  branch, whose only multi-attempt behavior is re-tapping the *same* coordinate
  in the *same* ROI. There is no strategy **switch** on verified failure (a
  failed tap never escalates to `keyboard_focus_activate`; a failed back never
  tries `keyboard_back`→`edge_back_gesture`; a failed launch never tries
  search/`vlm_icon_map`). This is exactly leak #3 the doc says P2 fixes.
- Evidence: `glassbox/action/semantic_plan.py:488-566` (specs + builder exist),
  `glassbox/phone.py:371-375` (always passes plain callable/`ActuationPlan`),
  `glassbox/action/orchestrator.py:226,243` (semantic branch only on
  `SemanticActionPlan`), `glassbox/ai.py:362,395,423`.
- Fix: route at least `back`/`scroll`/`tap` through `default_semantic_action_plan`
  (start with `back` — current single-shot if/elif at `phone.py:2374-2440`),
  migrate `home()`/`open_app()` onto it to unify (see CUQ-0.8). Wire
  `StrategySpec.capability` to `phone.supports(...)` so PicoKVM vs non-PicoKVM
  splits in `home()`'s pointer fallback are preserved.
- Acceptance: real runs emit `semantic_plan.strategy_failed` audit events and
  non-zero `strategy_switches`; Step-0 harness shows `unknown_rate` ↓ /
  `action_success_rate` ↑ for `back`/`scroll`/`tap` vs today.

### CUQ-0.2 — Install a real recovery hook (every `recover()` is currently a no-op)
- [x] **critical→high · effort medium · design-gap** — DONE: added `recover_to_home_then_renavigate` (in `action/recovery.py`, duck-typed, re-entrancy-guarded, optional `memory.path_to_page` replay when payload names a `target_page`) and wired it into the runtime orchestrator as `RuntimeRecoveryPolicy(hook=..., max_attempts=2)` (`runtime.py`). All three `recover()` call sites (stuck, semantic-plan exhaustion, preflight) now drive a real recovery instead of a no-op. Tests: hook unit tests + end-to-end stuck recovery (`test_computer_use_runtime.py`) + wiring assertion (`test_build_phone_wires_recovery_hook_into_orchestrator`).
- Gap: `runtime.py:572` constructs the orchestrator with no `recovery_policy=`,
  so it defaults to `RuntimeRecoveryPolicy(hook=None)`; `recover()` returns
  `recovered=False` without doing anything. The stuck detector fires, audits
  `stuck_detector.recovery.finished{recovered:false}`, and returns. invariant #4
  ("always recover to a known anchor and re-navigate") is unmet on every path —
  even Settings runs its own out-of-band recovery, so **no skill** benefits from
  the orchestrator hook.
- Evidence: `glassbox/runtime.py:572-581`, `glassbox/action/recovery.py:42-48`,
  `glassbox/action/orchestrator.py:159,522,656,801`.
- Fix: pass `recovery_policy=RuntimeRecoveryPolicy(hook=_default_recover,
  max_attempts=2)` and `stuck_detector=...`. `_default_recover(phone, reason,
  payload)` does `phone.home()` to the springboard anchor, then (if payload
  carries an in-progress target page) replays `memory.path_to_page()` (see
  CUQ-0.5); return `True` only after a fresh-frame verifier confirms the anchor.
  Map the `decision.recovery` name string (`recover_to_home_then_renavigate`,
  `stuck.py:23`) to the concrete callable instead of leaving it descriptive-only.
- Acceptance: a runtime smoke test asserts the live-built orchestrator's
  `recovery_policy.hook is not None` and `max_attempts > 0`; an injected dead-end
  fixture fires recovery and reaches `recovered=True` (P3 acceptance criterion).

### CUQ-0.3 — Attach `expected_state` on the production walkthrough/crawler
- [~] **critical→high · effort large · design-gap** — GENERIC-PATH SLICE DONE: the
  primary agent tap (`AIPhone.tap`) now accepts `expect_visible` / `expect_page`
  and threads an `expected_state` through `Phone.tap_text(expected_state=...)`
  into the orchestrator metadata, so the expected-state verification (P2) and
  VLM-gated escalation (P1) engage on the **default agent tap path** — previously
  only the Settings walkthrough set it, leaving the P1/P2 coverage telemetry
  (CUQ-3.2) structurally zero on generic runs. `AIPhone.tap_xy`/`swipe_xy` already
  carried expectations; this closes the main `tap(text=...)` path. Default (no
  expectation) is byte-identical (`expected_state=None`, post-tap
  `_apply_expectation` is a no-op). Test in `test_ai_native_interface.py`
  (visible_text + page_id threaded; none → None). **Remaining:** have the
  Settings/whitebox walkthrough crawler annotate each navigation step with its
  target page_id so the end-to-end canonical run also drives verification (the
  large app-specific half).
- Gap: expected-state verification only runs when a caller puts a dict in
  `metadata['expected_state']`; the only non-test caller is the `ai.py` facade.
  The canonical end-to-end check (the Settings walkthrough/crawler) never sets
  it, so every tap/scroll/back there is scored by generic `scene_progressed` and
  its `unknown` downgrade. The headline P2 lever ("cuts unknown, catches silent
  no-ops") does not protect the very task used to measure success.
- Evidence: `glassbox/action/orchestrator.py:1551-1569,2280-2294`,
  `glassbox/ai.py:1295-1305`; grep: no `glassbox/ios/*`,`/crawl/*` sets it.
- Fix: have the walkthrough attach an `ExpectedState` (`page_id` or
  `visible_text` of the target detail page) per semantic step, or route its
  primitives through CUQ-0.1.
- Acceptance: a smoke test asserts the live Settings drill-down produces
  `semantic_verifier == 'expected_state'` (not `scene_progressed`) for entry taps.

### CUQ-0.4 — Add a selection-time VLM escalation (gate today only fires post-action)
- [~] **critical→high · effort medium · design-gap** — DONE (entry point; VLM-gated): `expect_text` (which feeds `tap_text`/`tap_button`) now escalates on an OCR miss via `Phone._vlm_reground_selection` — a gated, single-call `VLMEscalationGate(target_found=False)` pass that runs `describe()` and re-resolves the target, trying raw text then the VLM-enriched **intent label** (`find_by_intent`) before raising. This implements trigger #2 (find-by-description) on the default selection path, where it previously hard-failed. Gated on a VLM client being wired, so VLM-disabled runs are unchanged. Test in `test_tap_intent.py`. **Remaining:** route `_reground_tap_point` and `tap_intent`'s existing `describe()` escapes through the same gate so all selection-time VLM obeys one budget + is recorded; emit `classifier_conflict` (trigger #3); cold-start/SoM grounding for true OCR-can't-read-it cases (needs VLM+rig to validate efficacy).
- Gap: the `VLMEscalationGate` is consulted in exactly one place —
  `_maybe_vlm_verify_expected_state`, on the *after* scene. The pre-action
  SELECTION path (`find_text`→`tap_text`) does pure text matching and raises
  `AssertionError` on an OCR miss; trigger #2 ("target not found by OCR →
  find-by-description") and trigger #3 (classifier conflict) are never produced
  on the default path. This is the unmitigated form of the doc's **#1 leak**.
  Note: `_reground_tap_point` (`phone.py:1319-1343`) already does a partial
  version (VLM `describe()` when OCR misses entirely) but only on retry
  (`attempt_index>0`) and **ungated/unbudgeted**.
- Evidence: `glassbox/phone.py:1135-1146,1194-1197,1524-1538,1643-1657`,
  `glassbox/action/orchestrator.py:1607-1641`, `glassbox/cognition/vlm_gate.py:67`.
- Fix: in `expect_text`/`tap_text`/`tap_button`/`tap_intent`, on first-look OCR
  miss **or** low-confidence/fuzzy-only match, build
  `VLMGateInput(ocr_confidence=matched.confidence, target_found=...)` through a
  shared `VLMEscalationGate`; on escalate, run `describe()` / find-by-description
  (set-of-marks for dense scenes, CUQ-2.x) within the per-action budget, re-resolve,
  set `selection_source=vlm`, and only raise after exhaustion. Route
  `_reground_tap_point`'s and `tap_intent`'s `describe()` through the same gate so
  selection-time VLM calls obey the budget and are recorded.
- Acceptance: a unit test proves trigger #2 forces a gated VLM call on selection;
  selection-time VLM calls appear in `vlm_calls`/`vlm_triggers` and obey
  `max_vlm_calls_per_action`.

### CUQ-0.5 — Install a generic `try_memory_path` recovery hook (UTG graph has no generic consumer)
- [x] **high · effort medium · design-gap** (default-safe; active when configured)
  — DONE: `make_try_memory_path_hook(target_page, allowed_actions,
  min_success_rate, fallback)` in `action/recovery.py` builds a generic recovery
  hook that, on a stuck/exhausted recovery, `recognize()`s the current screen,
  asks `memory.path_to_page()` for the shortest safe-enough learned path to the
  target page (reliability-weighted BFS from CUQ-3.23, gated by `allowed_actions`
  + `min_success_rate`), and replays the edge chain via backend-agnostic Phone
  primitives (`home` / `back_gesture` / `swipe_up`/`down`) — re-navigating in
  place instead of resetting to Home. An unknown-op edge, missing path, or
  unconfirmed arrival cleanly falls back to `recover_to_home_then_renavigate`, so
  it is never worse than the home-only recovery. Re-entrancy-guarded; replay is
  best-effort with a final `recognize`-the-target arrival check as the gate.
  Wired in `runtime.py` via `_build_recovery_hook`: installed ahead of the home
  hook **only when `cfg.recovery_target_page` is set** (env
  `GLASSBOX_RECOVERY_TARGET_PAGE`, + `_ALLOWED_ACTIONS` / `_MIN_SUCCESS_RATE`);
  default config keeps the byte-identical home-only recovery. Closes leak #7 —
  the UTG graph now has a generic, non-Settings consumer. Tests in
  `test_computer_use_runtime.py` (replay-back-chain, no-path→home,
  unconfirmed-arrival→home, default-is-home-only). **Remaining:** on-rig validate
  that a populated graph actually recovers a deliberately-stuck non-Settings run.
- Gap: `path()`/`path_to_page()`/`recognize()`/`locate()`/`expected_elements()`
  are implemented + unit-tested but the only non-test callers live in the
  Settings skill. The orchestrator imports only `compute_signature` from memory —
  it never queries the graph for navigation or recovery. Leak #7 confirmed: the
  "explore once, reuse the path" benefit is dormant for every app but Settings.
- Evidence: `glassbox/action/orchestrator.py:29,608-671`,
  `glassbox/runtime.py:572-581`, `skills/regression/ios_settings/core.py:447-478`.
- Fix: the recovery `RecoveryHook(phone, reason, payload)` seam already exists —
  install a generic `try_memory_path` default hook (parameterized by target
  `page_id` + `allowed_actions` + `min_success_rate`, all supported by
  `path_to_page`) that queries `phone.memory.path_to_page(recognized, anchor)`
  and replays the edge chain. No orchestrator change needed. Folds into CUQ-0.2.
- Acceptance: a non-Settings fixture recovers via a replayed memory path; BFS is
  reliability-weighted (see CUQ-3 medium list) so low-success edges are avoided.

### CUQ-0.6 — Default-on candidate-point landing retry for the agent tap path
- [x] **high · effort quick-win** — DONE: `_action_metadata` now `setdefault`s `landing_retry_allowed=True` for mouse_tap with landing observation (re-tap after a no-op is safe by construction); `forbid_landing_retry` stays the destructive-control opt-out. A first-attempt `missed` on the default agent tap path now re-grounds instead of failing. Regression in `test_actuation_feedback.py`.
- Gap: `_action_metadata` sets `landing_retry_budget=2` for `mouse_tap`, but a
  landing retry only runs when `landing_retry_allowed` is explicitly set — true
  only in regression nav + a smoke test, never on the agent's `tap_text` path.
  So a tap whose ROI did not change (`landing_signal=='missed'`, i.e. "tapped but
  nothing happened" from drift/off-center) is converted straight to `failed`
  after one attempt; the documented reground-on-drift remedy is dead on the live
  path.
- Evidence: `glassbox/action/orchestrator.py:2285-2288,2329-2332,1435-1441`,
  `glassbox/phone.py:1524-1538`, `glassbox/ai.py:347,464,937`.
- Fix: default `landing_retry_allowed=True` for idempotent taps inside
  `_target_tap_plan`/`tap_text` (keep `forbid_landing_retry` as the
  destructive-control opt-out), or at minimum expose the flag on `tap_text` and
  have the agent layer pass it. This also directly mitigates CUQ-1.2.
- Acceptance: a regression asserts a first-attempt `missed` on the default path
  triggers a candidate-point retry / reground before `failed`.

### CUQ-0.7 — Enforce the per-action VLM budget across retries on the legacy path
- [x] **high→medium · effort quick-win** — DONE: the legacy `execute()` loop now copies `vlm_calls`/`vlm_triggers`/`vlm_budget_exhausted`/cache counters from the per-attempt metadata back into the shared outer `metadata` after every attempt (mirroring the semantic-plan path at orchestrator.py:451-460), so the per-action VLM budget is enforced across retries instead of resetting to 0 each attempt. Regression `test_legacy_path_enforces_per_action_vlm_budget_across_attempts`.
- Gap: `max_vlm_calls_per_action` is enforced only on the (dead) semantic-plan
  path, which merges `vlm_calls` back into outer metadata. The legacy loop does
  not, so a flaky verified action can spend `per_attempt × max_attempts` calls;
  `unknown → VLM → unknown` can loop and burn budget without bound.
- Evidence: `glassbox/action/orchestrator.py:451-460,1604-1606`.
- Fix: thread the per-action VLM counter through the legacy retry loop and stop
  escalating on exhaustion (fall to strategy switch / recovery instead).
- Acceptance: a unit test proves `unknown→VLM→unknown` cannot exceed the
  per-action budget on the default path.

### CUQ-0.8 — Migrate `home()` onto the plan runner as the 1:1 ladder template
- [~] **high · effort medium · design-gap** — ENABLER DONE; `home` migration pending. The flag-gated routing infra (CUQ-0.1) + the optional-`expected_state` change make `home` a one-line `_run_semantic_plan("home")` gate. Deferred in this pass because the `assistive_touch_home` strategy callable (`_home_via_assistive_touch_menu`) re-enters the orchestrator (nested sub-tap recording) and the roadmap requires suppressing that nesting inside the strategy callable so outer attempt/group artifacts stay clean — best done with on-rig validation. `back` was migrated first instead (all-direct effector bindings, no nesting; highest-leverage per the audit).
- Gap: P2 acceptance forbids new bespoke fallback code, yet `home()` /
  `_picokvm_home_pointer_fallback` / `_verified_pointer_home` are exactly that —
  a hand-coded fallback ladder plus a verify wrapper that deliberately bypasses
  the orchestrator (so AT sub-taps aren't double-recorded), and they emit none of
  the attempt/group artifacts the harness needs. A canonical `home` `StrategySpec`
  ladder already exists in `semantic_plan.py:498-502` but is unused.
- Evidence: `glassbox/phone.py:2442-2539`,
  `docs/design/computer_use_success_rate.md:354-363`.
- Fix: migrate `home()` onto `default_semantic_action_plan`, encapsulating the
  AssistiveTouch nested-tap suppression inside the `assistive_touch_home` strategy
  callable so outer attempt/group + `semantic_plan.*` artifacts emit uniformly.
  This is the cleanest 1:1 migration and validates strategy-switch + recovery +
  shared-budget in one op; then forbid new bespoke fallbacks in review.
- Acceptance: `home` strategy switches are visible in the harness; no behavior
  regression on PicoKVM vs non-PicoKVM rigs.

### CUQ-0.9 — Make stuck recovery outcome-aware (one no-op currently → infinite loop)
- [x] **high · effort medium** — DONE: `_maybe_recover_stuck` now inspects `recovery.recovered`: success clears the failure counter; a failed/no-op recovery calls the new `StuckLoopDetector.rearm()` (un-fires the anchor + resets the run counter) so a persistent dead-end can fire again after `threshold` more samples instead of disarming forever. A bounded `max_stuck_recoveries` budget (default 3) caps total attempts and emits a terminal `stuck_detector.unrecoverable` audit marker on exhaustion. `observe_and_recover` now also honors the recover-bool. Tests: detector re-arm + end-to-end budget/unrecoverable.
- Gap: `_maybe_recover_stuck` never inspects `recovery.recovered`; meanwhile
  `StuckLoopDetector` adds the key to `_fired_keys` the first time it crosses
  threshold and only clears on a `succeeded` reset. So if recovery fails/no-ops
  (guaranteed today, see CUQ-0.2), `should_recover` stays `False` forever and the
  agent loops the same failed action indefinitely with no escalation, no
  termination.
- Evidence: `glassbox/action/orchestrator.py:617,656-671`,
  `glassbox/action/stuck.py:50-52,72-75`.
- Fix: only add to `_fired_keys` when `recovered=True`; otherwise re-arm so the
  detector can fire again after K more identical samples; add a bounded global
  recovery budget that surfaces a terminal `stuck-unrecoverable` status (never a
  silent loop) on exhaustion. Pass the recovery verdict back to the detector.
- Acceptance: a test drives a dead-end where the first recovery fails and asserts
  a second fire then a surfaced terminal status, not an infinite loop.

### Tier-0 medium companions
- [x] **CUQ-0.10** `transport_failed` is never retried on the legacy path (the
  `transport_retry_budget` lives only in the dead semantic-plan path). *medium* —
  DONE: the legacy `execute()` loop now reads `transport_retry_budget` (default 0
  → byte-identical), adds it to `max_attempts`, and `_retry_kind` returns a new
  `"transport"` kind for a `transport_failed` attempt — checked **before** the
  not-ok guard and **independent of idempotency**, because a transport failure
  means the effector call did not land (so retrying is safe even for a
  non-idempotent op, unlike a semantic failure). Budget threaded into the
  attempt-group audit. Tests in `test_computer_use_runtime.py` (retries a
  non-idempotent transport failure with budget; no retry at the default budget 0).
- [ ] **CUQ-0.11** Default retry/unknown policies are effective no-ops: most ops
  are non-idempotent so `retry_budget` is forced to 0 and `unknown_policy=retry`
  never fires. Decide per-op idempotency explicitly. *medium*
- [ ] **CUQ-0.12** Stuck/loop recovery runs only after a group finalizes and
  cannot alter the current action's outcome (`stuck.py:62 observe_and_recover` is
  dead; orchestrator uses `observe()` directly). *medium*

---

## Tier 1 — Independent correctness leaks (hurt success rate regardless of wiring)

### CUQ-1.1 — Pixel-diff "landed" upgrades `unknown`→`succeeded` and locks retry
- [x] **high · effort quick-win→medium** — DONE: `_semantic_after_landing` no longer promotes a mouse-tap `unknown`→`succeeded` on a raw ROI pixel delta (the focus-change upgrade is now restricted to `keyboard_focus_activate`, the one method where focus change is the intended evidence); a mouse tap stays `unknown` + `retry_allowed=True` so a later strategy/re-observation can fire. Real navigations still succeed via scene progress. Leak regression `test_mouse_tap_pixel_change_without_scene_progress_is_not_false_success`.
- Gap: a tap with `unknown` semantic verdict is promoted to `succeeded` whenever
  the landing observation reports `landed` — which means only that the ROI/frame
  changed by >0.001 (a ripple, keyboard, spinner, ad refresh, or row highlight
  all qualify) — and the promotion sets `retry_allowed=False`. This **bypasses**
  `SceneProgressedVerifier`'s own carousel/same-page guard
  (`verifiers.py:717-729` returns `unknown` for exactly this "frame changed but
  page identity didn't" case). Strong false-success leak. The upgrade is also
  unconditional w.r.t. `landing_retry_allowed`.
- Evidence: `glassbox/action/orchestrator.py:1709-1717,1435-1441,1500-1526`.
- Fix: gate the upgrade on a semantic delta (page_id/scene_type changed or
  expected_state met), not raw ROI pixels; reuse
  `_looks_like_transient_carousel_change`; restrict pure-pixel/focus upgrade to
  `keyboard_focus_activate`; keep `retry_allowed=True` so a later strategy fires.

### CUQ-1.2 — Unactuatable-bucket poisoning silently disables a whole control class
- [x] **high · effort medium** — DONE: `MethodStats` now tracks distinct `negative_identities`; `_method_is_unactuatable` requires `>= 5` all-negative tries AND (when identity is known) negatives from `>= 2` distinct controls, so transient misses on one stubborn target can't poison the shared (role,size,zone) bucket. `target_identity` is threaded through `record_attempt`. Decay already works via `_refresh_actuability` (any `semantic_ok` → actuatable) and CUQ-0.6 cuts the false-miss feed. Tests: distinct-controls still flags unactuatable; one stubborn control does not. (Cross-session persistence of the verdict is moot until CUQ-3.6 enables profile persistence.)
- Gap: `_method_is_unactuatable` flags a bucket after only 3 missed/`landed_noop`
  tries; the bucket key is coarse (`control_role, size_bucket, region_zone`),
  shared across many targets; "missed" is a low-threshold (0.001) ROI diff on a
  possibly-animating fresh frame. Three transient perception misses on different
  switches can flip the shared bucket, and `_skip_decision` then returns a
  synthetic `skipped`/`failed` for every future tap in that class **without
  sending a command**.
- Evidence: `glassbox/action/actuation_profile.py:414-418`,
  `glassbox/action/orchestrator.py:595-606,719-732,1435-1441`,
  `glassbox/action/actuation.py:147-163`.
- Fix: raise min-tries (≥5) from **distinct** `target_identity` values; require a
  corroborating semantic `failed` (not just a pixel miss); clear the verdict on
  any later `landed_ok`; do not persist `unactuatable` across sessions; let the
  default path bypass the skip ≥once per distinct target. CUQ-0.6 reduces the
  false-miss feed.

### CUQ-1.3 — VLM verification "escalation" re-checks identical stale OCR
- [x] **medium · effort medium** (flag-gated, default-off) — DONE: confirmed the
  gap in code (`describe()` enriches `_last_scene` in place from the same
  `_last_frame` — no re-capture, no re-OCR), so for text expectations the VLM
  re-check was guaranteed identical. `cfg.reverify_fresh_frame` (env
  `GLASSBOX_REVERIFY_FRESH_FRAME`) now makes `_maybe_vlm_verify_expected_state`
  re-perceive a fresh frame (`perceive(fresh=True)`) and re-verify BEFORE the
  gate: if the now-settled text matches it returns `expected_state_refresh`
  succeeded **without** spending a VLM call; otherwise the fresher scene becomes
  the escalation basis (so even the VLM no longer reads the stale frame). The
  fresh OCR short-circuits via the perceive cache when pixels are unchanged, so
  an unchanged screen stays cheap and still escalates. Default off (adds a
  capture+OCR on escalation); both branches tested in `test_computer_use_runtime`.
  **Remaining:** on-rig validation of the fresh-read hit rate before default-on;
  optionally a direct "is X visible?" VLM question for true-unreadable cases.
- Gap: on `unknown`/`failed` verification the orchestrator calls `describe()` then
  re-runs `verify_expected_state` — but `describe()` enriches the *same*
  already-captured scene in place (fills `intent_label`/`page_id`); it does not
  re-capture, re-OCR, or add text. For `visible_text`/`element_appears`/
  `element_gone` (the common case), the second pass reads identical texts, so a
  missed OCR stays missed while burning budget+latency.
- Evidence: `glassbox/action/orchestrator.py:1623-1641`,
  `glassbox/phone.py:1079-1096`, `glassbox/action/semantic_plan.py:407-446`.
- Fix: on escalation, capture a fresh frame and re-run perception, or have the
  VLM answer the expectation directly ("is text X visible? / what page is this?").

### CUQ-1.4 — Candidate executor discards the resolved center and re-resolves the bare label
- [~] **medium · effort medium** — RE-SCOPED AFTER CODE AUDIT: the live path is
  better than the gap implies and the residual is non-live + rig-gated, so no
  new code ships here.
  - The **main tap path** (`tap_text` / `tap_element`) already actuates the
    resolved element's `box.center` (actuation.py `preferred_point or
    element.box.center`) — it does *not* re-resolve, so there is no bug there.
  - The **live MCP `explore` path** uses the Settings policy
    (`open_phone(app=...)` → `RuntimeSettingsPolicy`), whose `candidates()` is
    built from **deduplicated `visible_texts` strings**, not resolved elements —
    it has no single resolved center to carry, so the duplicate-label ambiguity
    is inherent. That ambiguity is exactly what **CUQ-1.5's `strict_target_matching`
    guard already mitigates** (the executor's `tap_text(label)` then prefers the
    closest-length row / escalates instead of taking find_text's first match).
    So CUQ-1.4 is effectively **subsumed by CUQ-1.5** for the live path.
  - The "candidate carries a precise resolved center" scenario is the **generic
    crawl `TapCandidate`** (`candidates.py` center-bearing), used only by the
    *generic runner* policy (`crawl_policies.py`, returns dicts). Those dict
    candidates are silently dropped by `_policy_candidates`' `isinstance(...,
    NavigationCandidate)` filter, so that path taps nothing today.
  - **Remaining (non-live, rig-gated):** thread the center through
    `NavigationCandidate` + stop dropping dict candidates + tap the center — but
    that flips the generic-runner explore from scroll-only to tapping (a real
    behavior change) and needs on-rig validation of coordinate-space correctness
    and the disambiguation choice. Deferred rather than shipping an inert field.
- Gap: `ai.py:937 _execute_candidate` calls `tap_text(candidate.label)` even
  though the candidate already carries a precise resolved center
  (`candidates.py:29`). The label is re-resolved through `find_text`'s first-match
  substring/fuzzy ladder, so the tap can land on a *different* element sharing the
  label (nav title vs row).
- Fix: tap the already-selected element/center via `tap_element` (or pass the
  candidate center as the actuation target). Highest-precision fix for the
  "wrong target even when OCR is correct" class.

### CUQ-1.5 — `find_text`/`find_button`/`find_by_intent` have no ambiguity guard
- [x] **medium · effort medium** (flag-gated, default-off) — DONE for all three:
  an `ambiguity_guard` mode makes the substring tier prefer the closest-length
  containing row (not the first) and the fuzzy tier return None when the best
  match doesn't beat the runner-up by a margin (so an ambiguous read escalates
  instead of guessing — the doc's #1 leak even when OCR is correct). Behind
  `cfg.strict_target_matching`; the default path is byte-identical, so it's safe
  to ship and rig-validate before flipping on. Also addresses **CUQ-2.8**
  (substring-before-fuzzy short-needle). The same guard is applied to
  `find_button` and `find_by_intent` (wired through `tap_button`/`tap_intent`/
  the CUQ-0.4 reground). Tests in `test_ocr_vision.py` + `test_heuristic.py`.
- Gap: all three return the **first** exact→substring→fuzzy match, with no
  closest-length / best-vs-second margin check. `match_known_label`
  (`text_match.py:237-278`) already implements the right margin rule but the
  selection functions don't use it.
- Evidence: `glassbox/cognition/ocr.py:155-172`,
  `glassbox/cognition/heuristic.py:393-408,430-445`.
- Fix: prefer closest-length/highest-ratio in substring tier; adopt the margin
  rule in fuzzy tier (ambiguous → None/escalate to VLM, CUQ-0.4); apply
  nav-title deprioritization (`_rows_before_nav_title`) uniformly.

### CUQ-1.6 — Stuck signature uses exact string equality → OCR jitter never reaches threshold
- [x] **high · effort medium · design-gap** — DONE: `StuckLoopDetector` now matches each sample against the run's *anchor* via structural `similarity() >= SIGNATURE_MATCH_THRESHOLD` (+ exact failure_reason), falling back to exact equality for opaque/plain strings; the anchor is held fixed so drift can't accumulate. `_screen_signature` now feeds `dhash(frame)` as the phash so the perceptual-hash term in `similarity()` contributes. Regressions: jitter-tolerance + genuine-reset tests in `test_stuck_loop_detector.py`. (Re-fire/outcome-awareness is CUQ-0.9.)
- Gap: the detector keys on a JSON-stringified `ScreenSignature` compared with
  `==`. A single OCR jitter (one extra/missing token, a spinner counted as an
  element, a per-type histogram change) makes `key != last_key`, resets the count
  to 1, and the threshold of 3 is never reached — so the detector **under-fires on
  exactly the noisy screens it exists to catch**. `signature.py` already defines
  `SIGNATURE_MATCH_THRESHOLD` (Jaccard + histogram tolerance) but it's unused here;
  `phash` is always `""` on this path, so the `dhash` term is dead.
- Evidence: `glassbox/action/stuck.py:44-49`,
  `glassbox/action/orchestrator.py:1796-1802`,
  `glassbox/memory/signature.py:23,49-65`, `glassbox/memory/element_key.py:23-29`.
- Fix: keep the last `ScreenSignature` object and accumulate when
  `similarity(prev,cur) >= SIGNATURE_MATCH_THRESHOLD` AND failure_reason matches;
  feed a `dhash` into `_screen_signature`. Test with N slightly-jittered
  signatures and assert recovery still fires.

### Tier-1 medium companions
- [x] **CUQ-1.7** Shape-mismatched (garbled/partial) frames are scored as max
  diff = "everything changed" instead of being rejected. *quick-win* — DONE:
  `compute_frame_diff` now returns `diff_ratio=None`/`changed=None` on a shape
  mismatch (indeterminate), so a garbled decode maps to an "indeterminate"
  landing signal and a falsey progress check instead of a confident
  landed/progress. `FrameDiff` fields are now nullable. Test in
  `test_computer_use_verifiers.py`.
- [x] **CUQ-1.8** Graph scene-kind override silently no-ops on `recognize`
  failure, masking node-identity drift. *medium* — DONE (signal): `recognize()`
  now records `last_recognize_score` + `last_recognize_node_id`, so a near-miss
  (`0 < score < match_threshold` against a known node) — i.e. node-identity
  drift — is distinguishable from a genuinely-new screen (both return `None`).
  Additive + queryable; test in `test_memory_observe.py`. (Consumer that acts on
  drift is a follow-up.)

---

## Tier 2 — Perception & grounding gaps (enlarge the actionable space)

### CUQ-2.1 — `detect_icons` never runs in the default `perceive()` path
- [x] **high · effort medium · design-gap** (flag-gated, default-off) — DONE: `Phone._maybe_detect_icons` runs the no-text icon detector inside `perceive()` (masking OCR text boxes) and injects surviving regions as tappable `type="image"` elements, so icon-only controls (`+`/share/gear/back-chevron/trash) become tap candidates instead of being invisible to the OCR-text-only set. Runs **after** the scene classifiers (classification unaffected) and best-effort (never breaks perceive). Behind `cfg.detect_icons_in_perceive` (env `GLASSBOX_DETECT_ICONS_IN_PERCEIVE`), default off — adds CV cost per perceive and changes the candidate set, so validate on-rig before enabling. Test in `test_icon_detect.py`.
- Gap: the well-built no-text icon detector is wired only into the Home
  springboard map and the (default-off) cold-start annotator. On an ordinary app
  page the default `perceive()` yields **zero** icon elements, so a `+`/share/
  gear/back-chevron/trash icon button with no text cannot be a tap candidate.
- Evidence: `glassbox/phone.py:970-995`, `glassbox/cognition/coldstart.py:299-325`,
  `glassbox/config.py:206`, `glassbox/cognition/heuristic.py:299-341`.
- Fix: run `detect_icons` (or `detect_icons_voted` on stable frames) inside
  `perceive()` after OCR, masking OCR text boxes, injecting survivors as
  `type='image'/'unknown'` elements with box-center tap points. Gate cheaply
  (only when a requested target wasn't OCR-matched, or on icon-heavy scenes).

### CUQ-2.2 — Graph-authoritative scene kind never reaches `perceive()` / `is_ios_home_screen`
- [~] **high · effort large (min-fix medium) · design-gap** — MIN-FIX DONE
  (flag-gated, default-off): `is_ios_home_screen` gains a `strict_springboard`
  mode that refuses to trust a bare `springboard` classification without
  icon-grid corroboration (or the structural spread checks), closing the
  false-positive where a Settings detail page mislabeled `springboard` is read
  as Home (and a settings row tapped as an app icon). Threaded through the
  SpringBoard nav/recovery call sites + the icon-tap path via `_strict_home(phone)`,
  behind `cfg.require_home_icon_grid`. Default path byte-identical. Test in
  `test_ios_springboard.py`. **Remaining (large):** make the graph-derived kind
  authoritative at the `perceive()` chokepoint (projector source slot), not just
  in `is_ios_home_screen` — needs the projector-priority rework.
- Gap: the graph/transition override runs only inside Settings'
  `scene_state.scene_kind()`; every `phone.perceive()` sets `platform_scene_kind`
  from the bare single-frame `classify_ios_scene`, and the universal
  `is_ios_home_screen` re-invokes the bare classifier with no graph/VLM
  consultation. A detail page misread as `springboard` makes `is_ios_home_screen`
  return `True` → SpringBoard nav can tap a Settings row as a Home icon.
- Evidence: `glassbox/phone.py:696-708`, `glassbox/ios/springboard.py:179-202`,
  `skills/regression/ios_settings/scene_state.py:56-86,graph_state.py:40-79`.
- Fix (min): gate `is_ios_home_screen`'s `springboard` trust on `not
  graph_says_detail` and/or require `_has_strong_icon_grid` corroboration.
  Fix (full): feed the graph-derived kind into a scene classifier with a source
  slot out-ranking bare platform/app (note projector priority is
  `("vlm","app","platform")`, `contracts.py:103`). Downgrade the FSM doc's
  "authority/implemented" claim to "crawl-scoped".

### CUQ-2.3 — `switch`/`slider` element types are never produced (toggles tap the label)
- [x] **medium · effort medium** (flag-gated, default-off) — DONE: found the
  switch/slider types are declared AND `actuation.py` already biases the tap
  toward the control for them — the only missing piece was a producer. The VLM
  cold-start already classifies a `toggle`/`slider` role but only wrote it as a
  `type_evidence` tag (never promoted to the element type). `apply_annotation_to_scene`
  now takes `promote_controls`: when set, a VLM `toggle`/`slider` role promotes
  the anchored element to the declared `switch`/`slider` type AND sets
  `preferred_tap_point` to the row's right-margin control location
  (`viewport_w * 0.92` at the label's y) — so the tap lands on the switch, not the
  label OCR box (where a tap only highlights the row). Wired
  `cfg.coldstart_promote_controls` (env `GLASSBOX_COLDSTART_PROMOTE_CONTROLS`) →
  `Phone._coldstart_promote_controls`; only reachable when cold-start is enabled,
  default off → byte-identical. Tests in `test_coldstart.py` (promote→switch+right
  tap; off→stays text). **Remaining:** on-rig validate the 0.92 tap fraction
  actually toggles the control (and an OCR-only structural detector for runs
  without the cold-start VLM).

### Tier-2 medium companions
- [x] **CUQ-2.4** VLM verifier is not "opt-in for conflicts only" as documented —
  classifier conflicts are never escalated. *medium* — DONE: the projector sets
  `scene.classifier_conflict` when scene classifiers disagree on the platform
  scene kind (it otherwise silently let the last one win), and
  `_maybe_vlm_verify_expected_state` feeds it into the gate so trigger #3
  (classifier_conflict) actually fires. New `Scene.classifier_conflict` field;
  tests in `test_architecture_boundaries.py`.
- [x] **CUQ-2.5** Set-of-Mark grounding is implemented but never enabled by the
  gate's `describe()` escalation. *medium* (pairs with CUQ-0.4) — DONE
  (flag-gated, default-off): the SoM renderer (`render_set_of_mark`) and the
  `describe_scene(set_of_mark=...)` consumption (per-`id` mapping in
  `enrich_scene`) already existed; the gap was that `enrich_scene` never
  forwarded the flag and `describe()` never requested it. `enrich_scene` now
  takes `set_of_mark` and forwards it (via `VLMRequest`, and only-when-True for
  the legacy kwargs paths so non-SoM stubs stay byte-identical); `Phone.describe`
  takes `set_of_mark` defaulting to the `vlm_set_of_mark` flag
  (`cfg.vlm_set_of_mark`, env `GLASSBOX_VLM_SET_OF_MARK`), so every grounding /
  verification `describe()` escalation (incl. CUQ-0.4's `_vlm_reground_selection`)
  gets numbered marks when enabled. Default off → byte-identical. Test in
  `test_vlm_kimi.py`. **Remaining:** on-rig A/B of SoM vs text-only grounding
  accuracy on dense/ambiguous scenes before default-on.
- [x] **CUQ-2.6** `settings_detail` false-positives on third-party app screens via
  locale-generic body markers. *medium* — DONE (flag-gated, default-off): found
  the FP has **two** routes — `_looks_like_settings_detail_body` (generic markers
  允许/访问/账户/App) and `settings_detail_semantic_guess` (generic *copy* markers,
  no noun required). `cfg.strict_settings_detail` (env
  `GLASSBOX_STRICT_SETTINGS_DETAIL`) gates both: the body matcher additionally
  requires a Settings-distinguishing signal (a system noun like Wi-Fi/Bluetooth/
  Face ID, or a Learn-More footnote), and the semantic guess requires ≥1 system
  noun (a guess resting only on generic copy markers is rejected). Threaded
  `classify_ios_scene(strict_settings_detail=)` → the two matchers, and through
  `IOSSceneClassifier.classify` ← `Phone._classify_platform_scene_now` (forwarded
  only when the flag is on, so the default call stays byte-identical and stubs
  are unaffected). The negative uses of the body matcher (search-results /
  is-home exclusion) are intentionally left non-strict. Tests in
  `test_ios_scene.py` (generic-body FP rejected under strict via both routes;
  real Settings with a Learn-More signal preserved). **Remaining:** on-rig
  confirm no scrolled-detail recall loss (a real page with neither a noun nor a
  Learn-More footnote visible) before default-on.
- [x] **CUQ-2.7** Status-bar clock filtering lives only in the Settings policy;
  core `find_text`/`text_match` still match clock noise. *medium* — DONE: added a
  core, locale-neutral `looks_like_status_bar_clock` to `text_match` (handles
  trailing OCR-noise glyphs like `"2:03 C"`, `"12:09 €"`), and `ocr_tap_candidates`
  now skips clock-noise labels (a clock OCR'd as plain `text` previously survived
  as a tap candidate on the generic, non-Settings path). Tests in
  `test_text_match.py` + `test_candidates.py`.
- [x] **CUQ-2.8** `find_text` substring tier runs before fuzzy and matches short
  needles inside long rows. *medium* — SUBSUMED by CUQ-1.5: the `ambiguity_guard`
  mode (flag `strict_target_matching`) makes the substring tier prefer the
  closest-length containing row instead of the first match, which is exactly this
  short-needle-in-a-long-row defect. No separate change ships — closing the
  default-path substring order unconditionally is the risky part CUQ-1.5
  deliberately flag-gated (validate on-rig before default-on).
- [x] **CUQ-2.9** `selection_source` is inferred post-hoc ("was the scene
  VLM-described") rather than recorded at selection time — the headline diagnostic
  is unreliable. *medium* — DONE: `_target_actuation_plan` stamps a
  `selection_source` into the recorded command; `tap_text` stamps `expect_text`'s
  real source (`"ocr"`, or `"vlm"` when CUQ-0.4 grounding resolved it),
  `tap_intent` stamps `"vlm"`; the harness `_selection_source` now prefers a
  stamped value over inference. Tests cover both. (`tap_button`/`tap_element`/
  `tap_xy` still infer — the harness handles the mix.)
- [x] **CUQ-2.10** `whitebox_hint` (asset_match / accessibility_id / deep_link) is
  audit-only metadata and never influences selection or tap point. *medium* — DONE
  (flag-gated, default-off): `find_by_whitebox_hint` resolves a target by an
  element's whitebox identity (accessibility_id / asset_match / deep_link /
  swift_class) — a Tier-1+ profile signal more reliable than fuzzy OCR — and
  `expect_text` uses it as a fallback when OCR misses (reusing the just-perceived
  scene), under `cfg.whitebox_hint_selection` (env
  `GLASSBOX_WHITEBOX_HINT_SELECTION`). `selection_source="whitebox"` is stamped.
  Default off → byte-identical; only effective with a whitebox profile populating
  hints. Tests: matcher (identity-not-text) + `expect_text` resolves-by-hint /
  flag-off-hard-fails. **Remaining:** influence the tap POINT (the hint carries no
  geometry today) and candidate-scoring priors — needs a whitebox asset workspace
  on-rig.

---

## Tier 3 — Measurement, calibration, capture robustness (make "did it improve?" answerable)

### Measurement — without these, Tier 0/1/2 changes can't be judged

### CUQ-3.1 — `action_success_rate` denominator is dominated by scroll/drag fillers
- [x] **high · effort medium** — DONE: `_metrics` now splits primary actions into task-meaningful vs scroll/drag fillers (`_is_scroll_filler`); `action_success_rate`/`unknown_rate` count only task actions, so a tap/navigation regression is no longer masked by stable scroll success. Added `task_action_count`, `scroll_action_count`, `scroll_success_rate` (validator-safe ints/floats) and wired them into the `compare` delta display. Regression `test_scroll_fillers_excluded_from_action_success_rate`. **Remaining refinement:** orchestrator-stamped top-level `role` (vs intent-prefix heuristic) and a full per-op breakdown (needs validator to accept a dict metric).
- Gap: in real data, 304/308 (98.7%) of counted action records are `drag` scroll
  fillers; only 4 are task-meaningful taps. So a tap/navigation regression is
  statistically invisible to the compare gate, and `unknown_rate` reflects scroll
  mechanics not genuine ambiguity.
- Evidence: `skills/regression/computer_use_success_rate.py:175,589,606`.
- Fix: have the orchestrator stamp a real top-level `role`
  (`orchestrator.py:1265-1284,749-757`) instead of the intent-prefix heuristic;
  exclude/down-weight `op==scroll/drag` from the primary denominator (or a
  separate `scroll_success`); report per-op success. Amend doc lines 116-117,
  183-190 accordingly.

### CUQ-3.2 — Harness's P1/P2 telemetry columns are structurally zero on every real run
- [~] **high · effort large (coupled to Tier 0)** — VISIBILITY DONE: the harness now
  reports `expected_state_coverage` + `vlm_action_coverage` and `coverage_warnings`
  prints a loud `WARNING:` when a benchmark with task actions has zero coverage —
  turning the silent dead-signal condition into a visible one (the small-first
  fix the audit recommended). Wired into both `run`/`run-ios-settings` CLI paths
  and the `compare` delta display. Tests in `test_computer_use_success_rate.py`.
  **Remaining:** the larger work of routing the walkthrough through
  `default_semantic_action_plan` / `expected_state` (CUQ-0.1/0.3) so coverage is
  non-zero on real runs — that's the Tier-0 rollout, needs the rig.
- Gap: `vlm_calls`, `vlm_cache_*`, `expected_state`, `vlm_triggers`, semantic
  `strategy` are emitted only by `_execute_semantic_plan` (no production caller),
  so they aggregate to ~0 — the benchmark cannot attribute a success-rate delta
  to the VLM-gate or strategy-ladder stage, which is the schema's whole point.
- Evidence: `glassbox/action/orchestrator.py:243,431,451`,
  `skills/regression/computer_use_success_rate.py:210,257`.
- Fix (small, first): emit a **coverage warning** when a Settings benchmark yields
  zero `expected_state`/`vlm` coverage, so the dead-signal condition is loud, not
  silently zero. Then resolved by Tier 0 wiring.

### CUQ-3.3 — No CI / merge gate runs the harness ("no reliability change merges without it" is unenforced)
- [x] **high · effort medium · design-gap** — DONE (core gate): added `make lint`/`make test`/`make check` (device-independent) and `.github/workflows/ci.yml` running ruff + the smoke suite on every PR/push to main (macOS runner, because `ocrmac` is a darwin-only core dep). `make check` verified green locally (ruff clean, 1325 passed). **Remaining sub-part:** commit a frozen golden benchmark JSON and run `compare`/`validate` against it in CI to exercise the comparator path (depends on CUQ-3.2 coverage warning).
- Gap: no `.github/workflows`, no pre-commit, no committed baseline JSON
  (`artifacts/` is gitignored); `skills/smoke` is never auto-run. The
  comprehensive schema/compare unit tests **exist** but nothing executes them.
- Evidence: `Makefile:10`, `skills/regression/computer_use_success_rate.py:1076`,
  `skills/smoke/test_computer_use_success_rate.py`.
- Fix: (a) add a device-independent CI/`make check` that runs `uv run pytest
  skills/smoke` on every PR; (b) commit a frozen golden benchmark JSON outside the
  gitignore and run `compare`/`validate` on it; (c) keep live-rig numbers as a
  manual non-blocking step but require PR authors to paste before/after deltas.

### CUQ-3.4 — Canonical-primitive tasks (go-home / launch-app / back / scroll-to-bottom) are not benchmarked
- [ ] **high · effort large · design-gap**
- Gap: only `settings_readonly_walkthrough` runs; the primitives most central to
  recovery/navigation reliability are never benchmarked, so regressions in the
  fragile HID primitives are invisible to the success number.
  `aggregate_benchmark_manifest` supports a multi-task manifest but none is wired.
- Evidence: `skills/regression/computer_use_success_rate.py:807,1199`.
- Fix: author + commit a `tasks.json` (with per-task `terminal_expected_state`),
  add a Make/CLI entry to run it N rounds, include in the gated baseline.

### Calibration — systematic mis-taps

### CUQ-3.5 — iPhone uses a hardcoded single-rig coordinate fit (iPad already auto-derives)
- [x] **high · effort quick-win→medium · design-gap** — DONE (opt-in): renamed `_apply_ipad_crop_calibration`→`_apply_crop_calibration`, gated on `_is_ipad_target() OR cfg.derive_fit_from_crop`. iPad still always derives from the crop; iPhone unifies onto the same path via `GLASSBOX_PICOKVM_DERIVE_FIT_FROM_CROP=1`. Kept opt-in (not a silent default flip) because it changes live tap coordinates and a drifting crop (CUQ-3.14) could regress them without an on-rig validation run — but the test proves the crop-derived fit reproduces the hand-measured static fit to ~4 sig-figs (the static fit was measured from this crop), so flipping it on after validation is low-risk. Test: `test_picokvm_iphone_opt_in_derives_calibration_from_crop`. **Default-flip pending: CUQ-3.14 (crop stability) + a live-rig validation run.**
- Gap: the iPhone HID fit (`abs_to_phone_scale_*`, `abs_origin_offset_*`) is a
  fixed constant from one 2026-05-21 rig; `_apply_ipad_crop_calibration`
  re-derives from the live crop **only** when `_is_ipad_target()`. Any capture-card
  / cabling / model / re-seated-adapter change shifts the true frame→logical map
  and every iPhone tap is offset, with no session-start compensation.
- Evidence: `glassbox/effectors/picokvm/config.py:42-48`,
  `glassbox/effectors/picokvm/effector.py:72-76,299-307,392-398`.
- Fix: drop the `not self._is_ipad_target()` clause at `effector.py:307` so the
  existing crop-derivation also runs for iPhone (keep static constants only as the
  crop-is-None fallback and the `GLASSBOX_PICOKVM_ABS_*` escape hatch).

### CUQ-3.6 — Actuation profile is never persisted across sessions (default config)
- [~] **high · effort medium** — SAFETY ENABLER DONE: `load_actuation_profile`
  now resets the unactuatable-driving evidence (command_tries / negatives /
  negative_identities) for any would-be-unactuatable bucket on load while
  **keeping the learned calibration offset**, so persisting a profile across
  sessions carries the useful calibration but never a stale "unactuatable"
  verdict that would silently disable a control class (the CUQ-1.2 coupling).
  Actuatable buckets are untouched (round-trip preserved). Test in
  `test_actuation_feedback.py`. **Remaining (risky default-flip):** default
  `actuation_profile_dir` to the per-device memory path + populate `os_version`
  — needs on-rig validation that loaded offsets help rather than mis-correct.
- Gap: `cfg.actuation_profile_dir` defaults to `None`, so learned per-bucket tap
  offsets, best-method selection, and unactuatable verdicts are discarded each
  run; `os_version` is hardwired to `'unknown'`. Every session cold-starts and
  re-pays the mis-tap cost.
- Evidence: `glassbox/config.py:249`, `glassbox/runtime.py:547-551,578-579`,
  `glassbox/action/orchestrator.py:212-219`.
- Fix: default `actuation_profile_dir` to the per-device memory path; populate
  `os_version` from device geometry/manifest. (Pair with CUQ-1.2 so a poisoned
  `unactuatable` verdict is never persisted.)

### Calibration medium companions
- [ ] **CUQ-3.7** No per-session auto-calibration probe; relies on mid-run
  opportunistic correction only. *large*
- [x] **CUQ-3.8** A single noisy correction pair immediately biases a whole control
  bucket; no magnitude clamp / variance gate. *medium* — DONE: `record_correction_pair`
  now rejects an implausibly large missed→landed delta (`_correction_is_outlier`:
  >150px frame / >0.5 roi-normalized) as a mis-pairing rather than a calibration
  offset, so one noisy pair can't bias the shared bucket. Call site already
  tolerated a `None` return. Test in `test_actuation_feedback.py`.
- [x] **CUQ-3.9** `phone_model` and the linear-fit constants are independent config
  with no consistency check. *quick-win* — DONE: `PicoKVMEffector._warn_on_inconsistent_fit`
  surfaces (via `fit_calibration_warning` + a loguru warning) the case where an
  iPad target is left on the static iPhone fit with no crop to derive from and
  no explicit `GLASSBOX_PICOKVM_ABS_*` override — taps would be systematically
  off. Test covers iPad-no-crop (warns) vs derived/override/iPhone (silent).

### Capture robustness

### CUQ-3.10 — PicoKVM source returns the first post-reopen frame with no keyframe warmup
- [x] **high · effort quick-win · design-gap** — DONE: `fresh_snapshot()` discards `fresh_warmup_frames` (default 2) post-reopen frames, returns the first frame passing `_frame_looks_decoded` (std > 1.0, rejects flat/partial decodes), falls back to `snapshot()` on settle-budget exhaustion. Tests in `test_picokvm_frame_source.py`.
- Gap: `fresh_snapshot()` does close→open→read-first-frame with no discard; the
  AVF source deliberately discards 3 warmup frames. On H.264 the first decode
  after reopen is often a P-frame/partial that decodes as a smear — and
  `fresh_snapshot` is the freshness boundary right after every PicoKVM action, so
  a garbled frame directly corrupts the verification verdict.
- Evidence: `glassbox/perception/picokvm_source.py:57-82`,
  `glassbox/perception/source.py:264-266`.
- Fix: after `open()` read-and-discard 2-3 frames; for `fresh_snapshot`
  specifically, read until two consecutive frames have identical shape and
  `frame_diff_ratio` settles below epsilon, rejecting near-zero-mean /
  degenerate-variance frames.

### Capture medium companions
- [x] **CUQ-3.11** No absolute staleness-by-age check: a buffered frame older than
  the action is never rejected by age. *medium* — NOT APPLICABLE (code-verified):
  `Frame.ts` is stamped `time.monotonic()` at **decode** time
  (`picokvm_source.snapshot`), so it is always ≈now — an absolute decode-age check
  would be a no-op. The real concern (OpenCV handing back a buffered frame whose
  *content* predates the action) cannot be detected from `ts`; it is instead
  addressed by `fresh_snapshot`'s reopen + keyframe warmup (CUQ-3.10), the H.264
  garble/reconnect path (CUQ-3.13), and the dhash/diff freshness checks. No
  meaningful age-based code to add.
- [x] **CUQ-3.12** AssistiveTouch menu taps and the `swipe_xy` fallback omit the
  PicoKVM fresh-verify reopen, verifying on possibly-stale frames. *quick-win* —
  DONE: `_assistive_touch_tap_visible_item` and `swipe_xy` now thread
  `_picokvm_fresh_verify_kwargs` (reopen + stream-until-match), so their post-action
  verdict reads off a fresh frame on PicoKVM; no-op on other backends and
  `swipe_xy` respects a caller-set settle strategy (`setdefault`). Test in
  `test_effector_integration.py`.
- [x] **CUQ-3.13** No H.264 liveness/garble detection or bounded reconnect loop
  (one read-failure path is two attempts then raise). *medium* — DONE
  (flag-gated, default-off): `cfg.robust_capture` (env
  `GLASSBOX_PICOKVM_ROBUST_CAPTURE`) routes `snapshot()` through `_robust_snapshot`
  — a bounded reconnect loop (`snapshot_reconnect_attempts`, default 4) that
  rejects partial/garbled decodes (`_frame_looks_decoded`, the CUQ-3.10 std
  floor) AND read failures, reopening the stream with linear backoff between
  tries, so a transiently stalled/smeared stream recovers instead of returning a
  corrupt frame or raising after two tries. Default off keeps the existing
  2-attempt path byte-identical (verified: a flat frame is still returned in
  default mode). Tests in `test_picokvm_frame_source.py` (recovers-after-garble,
  raises-on-budget-exhaustion, default-returns-flat). **Remaining:** on-rig tune
  the attempt budget/backoff; a frozen-stream (identical-frame) liveness signal
  is deferred (ambiguous against a legitimately static screen).
- [x] **CUQ-3.14** Per-frame letterbox auto-refresh can silently re-fit the crop to
  transient content and drift coordinates. *medium* — DONE (default-fixed, with a
  knob): `_refresh_letterbox_crop_bbox` now applies consecutive-confirmation
  hysteresis — a NEW bbox must be detected on `cfg.letterbox_refresh_consecutive`
  (default 2) consecutive frames before it commits, so a single transient-content
  frame (fullscreen image/video/splash) can no longer re-fit the crop and drift
  every subsequent coordinate. A reverting bbox clears the pending state. This is
  a defect fix so it ships **on by default** (the one-frame-delayed re-fit of a
  genuine sustained change is immaterial); set the knob to 1 to restore the old
  commit-on-first-detection behavior (env `GLASSBOX_LETTERBOX_REFRESH_CONSECUTIVE`).
  Only active when the crop is auto-detected (where auto-refresh runs). Tests in
  `test_runtime.py` (sustained change commits on the 2nd frame; a one-off
  transient is discarded). **Remaining:** on-rig confirm the threshold suits the
  observed bbox-detection noise.

### Input fidelity

### CUQ-3.15 — Generic AI scroll always uses swipe-fling, never the wheel (even on iPad)
- [x] **high (iPad-scoped) · effort medium · design-gap** (flag-gated, default-off)
  — DONE: a `_phone_scroll(direction)` helper now routes the generic scroll verb
  to the precise wheel (`wheel_scroll_down/up`) when the backend
  `supports('scroll_wheel')` AND `cfg.ai_scroll_prefer_wheel` is set, else the
  swipe-fling fallback. Wired at all three sites the roadmap named —
  `AIPhone.scroll`, `explore`'s scroll step, and `_execute_candidate`'s
  scroll/swipe actions. Flag (env `GLASSBOX_AI_SCROLL_PREFER_WHEEL`) →
  `Phone._ai_scroll_prefer_wheel`; default off → swipe everywhere
  (byte-identical). Intended for the iPad rig where the wheel is
  validated/authoritative ([[picokvm-ipad-wheel-rpc-works]]); iPhone wheel is
  intermittent so it stays off there. Tests in `test_ai_native_interface.py`
  (wheel when enabled+supported; swipe fallback otherwise). **Remaining:** lift
  the `scrolling.py` closed-loop overshoot corrective-rescroll into the generic
  verb; on-rig confirm coverage gains on the iPad.
- Gap: `AIPhone.scroll()/explore()/_execute_candidate()` call `swipe_up/down`
  unconditionally; only the Settings crawler prefers the wheel. So every generic
  task pays the swipe-fling overshoot tax even on the iPad rig where the wheel is
  validated/authoritative. The closed-loop overshoot probe already exists — but
  only inside `scrolling.py`.
- Evidence: `glassbox/ai.py:529-533,606,938-941`, `glassbox/phone.py:2215-2252`,
  `skills/regression/ios_settings/scrolling.py:67-75`.
- Fix: in `AIPhone.scroll()` (and `explore`/`_execute_candidate`), route to
  `wheel_scroll_down/up()` when `supports('scroll_wheel')`, fall back to swipe
  otherwise; lift the `scroll_outcome` corrective-rescroll logic from
  `scrolling.py` into the generic verb.

### Input-fidelity medium companions
- [x] **CUQ-3.16** iPhone wheel activation state (primed/bounced/ack_only,
  `scroll_strategy_validated`, `wheel_diagnostic`) is computed in detail but
  consumed nowhere. *quick-win* — DONE: `PicoKVMEffector._warn_on_unvalidated_wheel`
  (run from `connect()`) surfaces an opt-in iPhone wheel that did not reach
  `'primed'` via `wheel_validation_warning` + a loguru warning, so the operator
  knows wheel scrolling is unvalidated and the run leans on swipe fallback.
  Disabled-wheel / primed cases stay silent. Test covers all three.
- [ ] **CUQ-3.17** `ipad_mini_migration.md` self-contradicts: §5 says wheel
  "superseded/authoritative" while the same doc records every `scroll_wheel` as
  no-progress. Reconcile against `picokvm_ipad_wheel.md`. *medium*
- [~] **CUQ-3.18** `close_foreground_app` home-indicator drag and `keyboard_focus`
  point are iPhone-shaped logical constants applied to iPad too. *medium* —
  RE-SCOPED (code-verified): both `close_app_drag_*` and `keyboard_focus_x/y` are
  expressed in **logical** coordinates of the fixed `abs_logical_max` (32767), i.e.
  fractions of the screen (drag ≈ bottom-center→top-center; focus ≈ (0.44, 0.36)).
  They therefore **scale proportionally across aspect ratios** — they are not an
  iPhone-px constant that breaks on iPad. The open question is whether the
  proportional *location* is semantically correct on iPad (e.g. is (0.44,0.36) a
  neutral focus area there) — content-dependent and **rig-validated**, not an
  offline-fixable geometry bug. Any iPad-specific override would be a blind guess
  without the rig.

### Safety
- [x] **CUQ-3.19** Power-off / lock / app-crash disqualifying states map to
  `status=failed`, not a terminal `blocked` safety bucket (invariant #4
  exception). *medium* — DONE: the three device-safety states (`ios_power_off_screen`,
  `ios_lock_screen`, `app_crashed_or_terminated`) now return `status="blocked"`
  so they bucket as a deliberate safety stop rather than a task failure
  (`semantic_transition_edge` already terminated via the disqualifying-state
  flag; this aligns the status with the documented state machine).
  `ios_home_unexpected` (navigation anomaly) stays `failed`; permission stays
  `approval_required`. Updated verifier/runtime tests + golden fixtures.

### Screen-memory medium companions
- [~] **CUQ-3.20** "Transition mismatch = failure" is unimplemented; the graph
  never validates that an action landed where the edge predicted. *medium* —
  SIGNAL DONE: `ScreenMemory.observe` now sets `last_transition_mismatch` when an
  action lands on a different node than a learned high-success edge for the same
  `(from_node, action)` predicted (`_detect_transition_mismatch`). Additive +
  queryable; safe. **Remaining (integration):** have the orchestrator/verifier
  consume `last_transition_mismatch` as a strong failure signal (feeds recovery).
- [x] **CUQ-3.21** `locate()`/`expected_elements()` position priors have no runtime
  consumer; OCR-ROI narrowing and candidate-scoring priors are dead. *medium* —
  DONE (flag-gated, default-off): `expect_text` now consults the UTG position
  memory as a selection prior on an OCR miss, **before** the billed VLM reground
  (`_memory_locate_selection`): recognize the current screen →
  `expected_elements(screen_id)` → reuse `find_text` over the remembered
  (text, box) elements → return the last-known box as the tap target
  (`_last_selection_source="memory"`). Volatile (list-row) positions are skipped
  (unreliable), and a stale prior that mis-taps is caught by the orchestrator's
  post-action verification. `cfg.memory_locate_priors` (env
  `GLASSBOX_MEMORY_LOCATE_PRIORS`) → `Phone._memory_locate_priors`; default off →
  byte-identical (and a no-op without a populated graph). Gives the graph a
  generic selection consumer alongside CUQ-0.5's recovery consumer. Tests in
  `test_tap_intent.py` (resolves-from-memory / volatile-skipped / flag-off
  hard-fails). **Remaining:** OCR-ROI narrowing + candidate-scoring priors
  (rank live candidates by proximity to the remembered box) and on-rig
  hit-rate validation.
- [x] **CUQ-3.22** UTG is persisted only on `runtime.close()`; a mid-run crash
  loses the whole session's learned graph. *quick-win* — DONE: `ScreenMemory`
  takes an injectable `autosave` callback + `autosave_every` and persists the
  UTG every N observations (best-effort; IO stays out of the graph module).
  `wrap_with_memory_if_enabled` wires it to `save_utg` for runtime-owned memory;
  new `cfg.memory_autosave_every` (default 12). Externally-provided memory
  (tests) stays close-only. Tests in `test_memory_observe.py`.
- [x] **CUQ-3.23** BFS path is not reliability-weighted (low-success edges aren't
  avoided). *low* (fold into CUQ-0.5) — DONE: `_path_to_targets` now visits each
  node's outgoing edges most-reliable-first (`success_rate`, then
  `success_count`), so among equal-length paths it routes via the higher-success
  edge instead of an arbitrary low-success one (still shortest-hop BFS). Test in
  `test_memory_path.py`.

---

## Recommended sequencing

If only three things ship, ship these (lowest risk, highest leverage):

1. **Stop the bleeding (quick-win, local):** CUQ-0.2 (recovery hook) +
   CUQ-0.6 (default-on landing retry) + CUQ-0.7 (VLM budget) + CUQ-1.1
   (pixel-diff false-success) + CUQ-3.10 (keyframe warmup).
2. **Prove the ladder (template migration):** CUQ-0.8 (`home()` → semantic plan),
   then CUQ-0.1 expands to `back`/`scroll`/`tap`. Validate strategy-switch +
   recovery + shared budget end-to-end on the Step-0 harness.
3. **Make improvement measurable:** CUQ-3.1 (denominator) + CUQ-3.3 (CI gate) +
   CUQ-3.2 (coverage warning) — otherwise every later step is unmeasurable.

Full ordering: Tier 0 → Tier 1 → Tier 3-measurement → Tier 2 → Tier
3-calibration/capture/fidelity. Each item gates on the Step-0 harness with a
committed baseline; ship behind a flag, then default-on after a non-regression.

## Doc-honesty corrections

The audit found these `computer_use_success_rate.md` / `screen_state_fsm.md`
status claims overstated. Until the wiring lands, downgrade them so the docs stop
misleading planning:

- P1 "implemented foundation + expected-state runtime integration" → **gate runs
  on verification only; selection-time triggers (#2/#3) unimplemented on the
  default path** (CUQ-0.4).
- P2 "implemented foundation + orchestrator integration" → **`SemanticActionPlan`
  has no production caller; expected-state verification is off the default path**
  (CUQ-0.1, CUQ-0.3).
- P3 "implemented minimal runtime hook … invokes the configured recovery policy"
  → **no recovery hook is installed in production; every `recover()` is a no-op**
  (CUQ-0.2, CUQ-0.9).
- FSM "the UTG is the authority for ambiguous scene kind" → **crawl-scoped
  (Settings only); the universal `perceive()`/`is_ios_home_screen` path is not
  graph-corrected** (CUQ-2.2).

## Verified NOT-issues (do not re-litigate)

Adversarial verification rejected these as wrong or already-handled:

- **Stable-frame is NOT off by default.** `open_phone()`→`_ai_config()` sets
  `stable_after_action=True`; the tap target IS grounded on a stable frame via
  `_needs_stable_frame`. (Residual: the base-config default diverges from the AI
  facade — flipping `config.py:131`/`stable.py:21` to `True` would harden
  non-facade entrypoints; low priority.)
- **The VLM gate is NOT unconstructible / off.** It's built when a VLM is enabled;
  the real gap is *where* it's consulted (CUQ-0.4), not whether it exists.
- **`unknown` is NOT silently treated as success by default** — the
  consumer-chain claim was factually wrong (the false-success path is the
  specific pixel-diff upgrade in CUQ-1.1, not a blanket policy).
- **The letterbox crop is NOT a one-shot startup measurement** that a single dark
  frame can wreck; it can refresh per-frame (the real concern is drift, CUQ-3.14).
- **`page_id` verifier is not near-dead**, and `expect_page` is not dropped when
  `visible_text` is given (those micro-claims didn't hold).
- **Scroll/swipe/drag do have a movement check**; the "no-op silently reports
  success" claim didn't hold for those ops (the real false-success is CUQ-1.1).
- **The default terminal `page_id` does match** in normal runs (the
  "never-matches" claim was wrong).

## Acceptance for this roadmap

- Each `CUQ-*` item lands behind a flag, gated on the Step-0 harness with a
  committed baseline (CUQ-3.3), and flips default-on only after a non-regression.
- The four doc-honesty corrections are applied (or the wiring lands and the
  claims become true).
- Tier-0 completion is provable: real Settings runs emit non-zero
  `strategy_switches`/`recoveries`/`expected_state` coverage, and an injected
  dead-end fixture reaches `recovered=True`.
