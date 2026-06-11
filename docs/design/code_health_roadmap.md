# Design — Code-health roadmap (glassbox)

Status: **implementation in progress (2026-05-31).** Current checkpoint:
P4 is implemented; P5 flag-accessor/retirement-policy/constructor-bucket
down payment is in place;
P1 now has `ActionContext` plus owned collaborators for coordinates, perception,
selection, targeting, gestures, AssistiveTouch, system navigation, text input, and
action execution; `ActionHost` declares the public read surface plus the
`record_action` write hook; the production private-Phone reach inventory is
pinned by a smoke test; P2's touched orchestrator phase methods have been split
below the ~80-line target; P3 shared iOS/iPadOS scene helpers and recovery
ownership note are in place; `make check` passes locally. P6's concrete
`_run_attempt`/`_observe_after` side-effect contract is pinned by
`test_orchestrator_attempt_observe_after_side_effect_contract`, and memory-path
fallback/arrival edge cases are covered. `Phone.__init__` now keeps the legacy
signature but delegates configuration resolution, dependency wiring, feature
state, platform state, collaborator setup, and compatibility context setup to
focused helpers. **Not complete until the required P1/P2 rig A/B is run on both
iPad mini 7 and iPhone with distinct baseline/candidate SHAs and any drift is
resolved.** Remaining offline cleanup is complete for this roadmap snapshot;
VLM-selection coverage now includes non-finite/out-of-range confidence handling.

**Invalidated validation note (2026-05-31):** do not use
`artifacts/code_health_roadmap/ipad_ab_20260531_100240` as evidence for this
refactor. Both `baseline.json` and `candidate.json` record `git_sha=a48433b`,
and the Makefile target varies `GLASSBOX_SEMANTIC_PLAN_OPS` (empty vs.
`back,scroll,tap`), so that artifact validates the strategy-ladder flag on the
pre-refactor baseline, not behavior preservation of this roadmap refactor.
`artifacts/code_health_roadmap/ipad_settings_quick_20260531_100631` also lacks a
recorded git SHA. Follow-up iPad distinct-SHA smoke is recorded under
`artifacts/code_health_roadmap/ipad_refactor_smoke_20260531_104307`: the usable
comparison is `baseline2_a48433b.json` vs `candidate_b143faa.json` with matching
metrics (`task_completion_rate=0.5`, `action_success_rate=0.75`,
`scroll_success_rate=1.0`) across one canonical-primitives round. That is only a
smoke check, not the required P1/P2 live A/B: the sample is one round, both sides
still fail `go_home` final page-id classification and `launch_app` remains
`unknown`. iPhone distinct-SHA smoke is recorded under
`artifacts/code_health_roadmap/iphone_refactor_smoke_20260531_110740`: the
uncontrolled first pair is invalid because Settings reopened onto stale subpages
(`settings/WLAN` / `settings/Wallpaper`) instead of the root. After resetting the
Settings nav stack, `baseline_controlled_a48433b.json` vs
`candidate_controlled_b143faa.json` held the primary one-round metrics
(`task_completion_rate=0.5`, `action_success_rate=1.0`, `unknown_rate=0.0`), but
`scroll_success_rate` slipped `0.952381` -> `0.9`. Treat this as a smoke result
with residual scroll variance, not a completed gate: rounds=1, expected-state
coverage is 0, VLM-action coverage is 0, and no variance bounds were measured.
Both device halves therefore remain pending for the full P1/P2 live-refactor
gate.
Originally produced after a 5-dimension
evidence-based health assessment of the repo (architecture / god-files /
cross-platform duplication / tests / debt). Verdict going in: **this is a healthy
8-day-old, high-velocity research codebase (real Protocol seams in `boundaries.py`,
registries, a working `make check` gate = lint + tests + regression floor, ~1200
`@pytest.mark.smoke` tests / 1500+ collected with parametrization, 0 TODO/FIXME/HACK
— debt is explicit-via-flags), not 屎山.** Average dimension score
≈ 3.4/5. The strain is concentrated in a few god-files and procedural mega-methods
from fast empirical iteration. This roadmap pays that strain down **proactively and
behavior-preservingly** — it is not a rescue.

Every problem below is cited to live `file:line`. Where the assessment was wrong,
this doc says so (see **P5**, a false "10 dead flags" finding). **Revised 2026-05-31
after a reviewer caught stale baselines:** the `RecoveryProvider` seam already ships
(P3), substantial orchestrator/VLM/stuck tests already exist (P6), the private-coupling
surface is wider than orchestrator (P1/P5 inventory), and `make check` includes lint.
**A second pass corrected exact counts** (118 methods not 127; `class Phone` at `:143`
not `:121`; ~13 bool flags not "28"; 11 `ios_settings` files not 7). HEAD was unchanged
(`a48433b`) throughout — these were *measurement errors*, not drift. **Treat every count
here as a snapshot as of `a48433b`; regenerate with the inline commands, don't trust the
prose.**

## 0. Operating principles (apply to every phase)

1. **Characterization tests before refactor.** You cannot safely carve up a
   3255-line god-object without a behavior net. The single biggest risk-reducer is
   to *first* pin current behavior with tests, *then* refactor under them. This is
   the same "stabilize-before-you-move" lesson as `ipad_settings_state_machine.md`
   (L3b must precede L1).
2. **Behavior-preserving & PR-sized.** Each step is independently mergeable and
   revertable, changes no observable behavior, and lands green: `make check`
   (lint + tests + regression gate) must pass, and the committed reliability floor
   (`skills/regression/fixtures/reliability_baseline.json`) must not regress.
3. **`main` is branch-protected (since 2026-06-04: required `check` status,
   strict up-to-date, enforced for admins) — but with 0 review approvals.** CI
   is the only independent check, so each step must still be *self-verifying*
   before merge. Anything that touches action *timing/perception* (P1/P2)
   additionally needs one rig A/B (iPad mini 7 + iPhone) before it counts as
   done — a refactor that "passes offline" can still shift live nav reliability.
4. **Don't trust a single grep, metric, or stale assessment.** Two findings in the
   first draft were wrong: the "10 dead flags" was a word-splitting artifact (all 10
   are live), and "no platform recovery-provider seam" was already false (the seam
   ships — see P3). Verify a read-site/abstraction exists before recommending you add
   or delete one. Baselines drift fast on an 18-commit/day repo; re-check before citing.
5. **Scope discipline.** This is proactive debt paydown on healthy code. Do the
   low-risk quick wins (Phase 0) now; commit to the big god-object split (Phase 1)
   when growth actually makes Phone block you — not as a vanity refactor.

## 1. The six problems (with evidence)

| # | Problem | Where | Leverage | Risk | Effort |
|---|---------|-------|----------|------|--------|
| **P1** | `Phone` god-object (3255 LOC, **118 methods**) spanning perception+cognition+targeting+gestures+system-nav+text+orchestration; **6+ non-Phone module groups reach into Phone privates** (not just orchestrator — see P1-prep inventory) | `glassbox/phone.py:143`; consumers in `orchestrator.py`, `semantic_plan.py`, `action/recovery.py`, `ai.py`, `ios/springboard.py`, `skills/regression/ios_settings/*` | High | **High** (every action path) | High |
| **P2** | Procedural mega-methods: `_run_attempt` 260 L / 7-deep / ~48 cc; `execute` 206 L; `_observe_after` ~192 L | `glassbox/action/orchestrator.py:975-1233, 236-420, 2109+` | High (testability + refactor-safety) | Med | Med |
| **P3** | iOS/iPadOS copy-paste seam: duplicate/near-duplicate helpers under different names (one pair byte-identical, others differ in platform constants); **and** an under-used platform recovery seam (it exists + is wired, but only covers `system_search`; Settings recovery lives app-layer, orthogonal) | `ios/scene.py:653-661` ≡ `ipados/scene.py:553-561`; seam at `boundaries.py:124` + `platforms.py:148` + `runtime.py:678`; app-layer recovery in `skills/regression/ios_settings/recovery.py` | Low now, rises with a 3rd platform | Low | Med |
| **P4** | Layer violation: perception imports effector config (upward dep) | `glassbox/perception/picokvm_source.py:11` → `glassbox.effectors.picokvm.config` | Low (hygiene) | Low | **Low (quick win)** |
| **P5** | Flag *plumbing & retirement* (NOT dead code — see correction): most flags thread config→runtime→`Phone.__init__`→`self._x` (but some are runtime-/orchestrator-owned, see correction); some read cross-module via `getattr(phone, "_x", False)`; no retirement policy; legacy aliases linger | `phone.py:178-294` (~47 ctor params); `orchestrator.py:1716`, `ios/springboard.py:295` (cross-module private reach); `config.py` (legacy `enable_kimi→enable_vlm`). NB: only **~11** are private bool *feature flags*; `action_fail_fast`/`auto_refresh_letterbox_crop` are public/runtime-derived, the rest are tunables + ~20 deps — don't conflate | Med | Low | Low–Med |
| **P6** | Test gaps (narrower than first draft — real coverage EXISTS: `test_semantic_action_plan` 20, `test_computer_use_runtime` 72, `test_vlm_gate` 7, `test_stuck_loop_detector` 9, `test_memory_path`). Remaining: `_run_attempt`/`_observe_after` **side-effect boundaries** (only monkeypatched-to-explode today), `action/recovery.py` memory-path **edge cases**, and Phone-split **characterization** tests | `orchestrator.py:975-1233,2109+` (untested side-effects); `action/recovery.py` | High (it's what makes P1/P2 *safe*) | Low | Med |

### P5 correction + canonical flag-owner table (single source of truth)
The health assessment's "10 flags with zero detected usage" was false — all are wired to
live, default-off branches — and the first draft then lumped flags of **different owners**.
**This table is canonical; Phase 0 references it — do not re-list flags elsewhere.**
`PhoneFeatureFlags` = the **11 Phone-owned rows ONLY**.

| Flag | Owner | Wired at |
|------|-------|----------|
| `detect_icons_in_perceive` | **Phone** (`self._x`) | `phone.py:243` → read `:1248` |
| `strict_target_matching` | **Phone** | `phone.py:252` → `:1432` |
| `require_home_icon_grid` | **Phone** | `phone.py:255` → `:1638` (also `springboard.py:295`) |
| `reverify_fresh_frame` | **Phone** | `phone.py:259` (read `orchestrator.py:1716`) |
| `coldstart_promote_controls` | **Phone** | `phone.py:263` → `:840` |
| `vlm_set_of_mark` | **Phone** | `phone.py:267` |
| `memory_locate_priors` | **Phone** | `phone.py:271` → `:1483` |
| `strict_settings_detail` | **Phone** | `phone.py:275` |
| `ai_scroll_prefer_wheel` | **Phone** | `phone.py:279` (read `ai.py:529`) |
| `vlm_reground_selection` | **Phone** | `phone.py:283` → `:1447` |
| `whitebox_hint_selection` | **Phone** | `phone.py:287` → `:1554` |
| `enable_coldstart` | **AgentConfig runtime dep-gate** (builds ColdStartAnnotator; never reaches Phone) | `runtime.py:545` |
| `recover_then_retry` | **ActionOrchestrator** (ctor, not Phone) | `runtime.py:626` → `orchestrator.py:154/177/410` |

(The original false "10-flag" claim spanned all three owners — 8 Phone + `enable_coldstart`
+ `recover_then_retry`; the 3 Phone flags not in that claim — `vlm_set_of_mark`,
`strict_settings_detail`, `ai_scroll_prefer_wheel` — complete the 11.) So P5 is **not**
"delete dead flags"; the cleanup splits **by owner**. Real smells: (a) **threading
boilerplate**, (b) **cross-module reach into `phone._<flag>`** via `getattr` (`ai.py:529`,
`springboard.py:295`, `orchestrator.py:1716`), (c) **no retirement cadence** (rig-validated
flags never promoted; legacy aliases persist).

## 2. Sequencing (ROI × 1/risk)

```
Phase 0  (now, low risk, enabling)   P4 + P5(partial) + P6(characterization half)
   │                                  ── builds the safety net + quick hygiene wins
Phase 1  (when Phone blocks you)      P1  Phone → thin facade + collaborators
   │                                      & sever private coupling (ALL consumers)
Phase 2  (after P1)                   P2  extract mega-method state machines
Phase 3  (before a 3rd platform)      P3  dedup ios/ipados helpers + recovery ownership
Ongoing                               P5(retirement cadence) + P6(specific gaps)
```
Rationale: **P6's characterization half and P4/P5 quick wins gate P1/P2** (you refactor
under tests, not blind). P1 is highest-leverage but highest-risk, so it waits behind the
safety net and behind real need. P3 is genuinely deferrable until a third platform makes
the copy-paste rot.

## 3. Phase 0 — safety net + quick wins (do now)

**P4 — fix the layer violation (≈1 PR, hours).** Move the constant(s)
`perception/picokvm_source.py:11` needs out of `effectors/picokvm/config` into a
neutral module (e.g. `glassbox/geometry` or a small `perception/_picokvm_consts.py`),
or invert via a Protocol so perception depends on an abstraction, not the effector.
DoD: no `perception/*` module imports `glassbox.effectors.*`; `make check` green.

**P5(partial) — stop the bleeding, don't delete (≈1–2 PRs).**
- Add a **flag-retirement policy** doc-block in `config.py`: each flag carries its
  CUQ ticket + "promote-or-remove by" intent; a rig-validated default-on flag (e.g.
  the three current ones) gets a follow-up issue to make it unconditional and delete
  the branch.
- Replace **all** cross-module `getattr(phone, "_<flag>", …)` reads (e.g.
  `orchestrator.py:1716` `_reverify_fresh_frame`, `springboard.py:295`
  `_require_home_icon_grid`, `ai.py:529` `_ai_scroll_prefer_wheel`) with a **public
  accessor** on Phone (or pass the flag explicitly) — a small down-payment on P1's
  encapsulation (the bulk, ~82 reach-sites, is migrated in Phase 1).
- Optionally group the ctor params into **THREE separate** buckets — do NOT lump them:
  1. **`PhoneFeatureFlags`** — the **11 Phone-owned rows in the §P5 canonical table ONLY**
     (don't re-list them here — that table is the single source of truth).
  2. **Runtime-derived / public behavioral options** — NOT experiment flags, keep out of
     `PhoneFeatureFlags`: `action_fail_fast` (public attr, `phone.py:231`),
     `auto_refresh_letterbox_crop` (public + **runtime-derived** at `runtime.py:441`),
     `letterbox_refresh_consecutive`, `default_observation_scope`, `app_viewport_mode`.
  3. **Tunable limits** (`PhoneObservationConfig`): `max_ocr_elements`,
     `max_ocr_text_chars`, `ocr_timeout`, `perceive_cache_diff`.
  The ~20 injected deps (`ocr`, `kimi`, `memory`, providers, …) stay as constructor
  params. (Behavior-preserving.)
  **Implemented 2026-05-31:** `PhoneFeatureFlags`, `PhoneRuntimeOptions`, and
  `PhoneObservationConfig` now exist; production runtime assembly passes these
  buckets while legacy individual kwargs remain supported for tests and external
  callers.
DoD: no module outside `phone.py` reads `phone._<flag>`; flag inventory has a stated
retirement intent; `make check` green.

**P1-prep — inventory the Phone private-API surface (≈1 PR, hours).** **Don't
hand-curate this list — generate it and pin it with a test** (hand-written lists rot;
the snapshot below is as of `a48433b`). Generator — **symbol-level, not `-l` file-level**
(the allow-list test must key on `(module, private-symbol)` pairs, so adding a new
`phone._x` inside an already-listed file still fails; a file-level list would silently pass):
```
grep -rInoE 'phone\._[a-z_]+|getattr\(phone, ?"_[a-z_]+|setattr\(phone, ?"_[a-z_]+' glassbox/ skills/ \
  | grep -vE 'phone.py|/test_|/smoke/' | sort -u
# (AST extraction of phone._x / getattr(phone,"_x") / setattr(phone,"_x",…) is more robust
#  than regex if a call spans lines — prefer it for the committed test.)
```
Note: tests (`skills/smoke/**`, `test_*.py`) poke Phone privates **on purpose** (e.g.
`mock_phone._whitebox_hint_selection = True`); they are a separate *test-only escape
hatch* allow-list, NOT architecture violations — the production allow-list test must
exclude them or it will flag every fixture. Snapshot today — the surface is **wider than
the orchestrator**:
- `action/orchestrator.py`: `_last_frame`, `_last_stable_frame`, `_needs_stable_frame`,
  `_fresh_source_reopened_after_action`, `_record_action`, `_failed_action_result`,
  `_reopen_source_for_fresh_capture`, `_in_semantic_plan`, `_effector_backend`,
  `_last_stability_policy/score`, `_reverify_fresh_frame`.
- `action/semantic_plan.py`: `_to_phone`, `_home_via_assistive_touch_menu`,
  `_picokvm_back_context`, `_unsupported_action`.
- `action/recovery.py`: `_in_recovery`, `_last_scene`, `_last_frame`.
- `ai.py`: `_uses_semantic_plan`, `_ai_scroll_prefer_wheel`.
- `ios/springboard.py`: `_viewport_size`, `_require_home_icon_grid`.
- **`skills/regression/ios_settings/` — 11 files** (`core, crawler, foreground_recovery,
  graph_state, navigation, recovery, scene_state, scrolling, search_ui, trace, vlm_rows`):
  reads `_viewport_size`/`_last_frame` **and stamps its own state onto Phone** — the worst
  coupling, since the skill layer monkeypatches Phone. The stamped-attr set is
  **8 as of `a48433b`** (regenerate, don't hand-list — an earlier hand-list wrongly
  included `_ios_settings_crawl_policy_factory`, a function in `crawl_policies.py:183`).
  Use `-rhoE` and scope to the regression dir, or filenames like `test_ios_settings_*.py`
  inject fake attrs (`_ios_settings_navigation/recovery/scene_state`) and you get 11, not 8:
```
grep -rhoE 'setattr\(phone, ?"_ios_settings_[a-z_]+|getattr\(phone, ?"_ios_settings_[a-z_]+|phone\._ios_settings_[a-z_]+' \
  skills/regression/ios_settings glassbox/ | grep -oE '_ios_settings_[a-z_]+' | sort -u
```
DoD: a committed **allow-list test** that fails when a new private-reach appears (which
privates are "public-by-contract" via accessors vs. forbidden); the *test*, not this
prose, is the P1 acceptance scope.

**P6(characterization half) — pin behavior at the seams P1/P2 will move (≈2–4 PRs).**
Real coverage already EXISTS (`test_computer_use_runtime.py` 72, `test_semantic_action_plan.py`
20, `test_vlm_gate.py` 7, `test_stuck_loop_detector.py` 9, `test_memory_path.py`), so this
is *filling specific gaps*, not greenfield. Using the existing fakes (`FakeRpc`,
`SequenceOCR`, `FakeCap`) and golden OCR fixtures (`skills/golden/ios_scene/…`), lock
*current* behavior where it is NOT yet pinned:
- `Phone.tap_text/tap_element/tap_button/tap_intent` → assert actuation plan + recorded
  `ActionRecord` per representative scene (these become P1's contract).
- `ActionOrchestrator._run_attempt` / `_observe_after` **side-effect boundaries** — today
  `_run_attempt` is only monkeypatched-to-explode (`test_computer_use_runtime.py:1939`),
  not characterized. Pin the **concrete artifacts** each emits/mutates so the P2 extraction
  is provably behavior-preserving: **audit events** + **attempt-group JSONL fields**
  (`attempt_groups.jsonl` / `audit.jsonl`), the Phone flags `_needs_stable_frame` &
  `_fresh_source_reopened_after_action`, **perceive-cache invalidation**, and the
  **verifier-input shape**.
- `action/recovery.py` memory-path **edge cases** beyond the happy path already in
  `test_memory_path.py`.
DoD: each refactor target in P1/P2 has ≥1 behavior-locking test that would fail if the
extraction changed observable output.

**Implemented 2026-05-31:** `test_orchestrator_attempt_observe_after_side_effect_contract`
locks verifier-input shape, `actions.jsonl` / `attempt_groups.jsonl` /
`audit.jsonl` fields, fresh-source reopen metadata, Phone cache invalidation,
and action-memory side effects. Memory-path recovery is covered for learned
back-chain replay, no-path fallback, and failed-arrival fallback.

## 4. Phase 1 — P1: Phone → thin facade + collaborators

Decompose the 118 methods into cohesive collaborators that Phone *owns and delegates
to*; Phone stays as a lean facade + the single shared `ActionContext` (defined below —
there is no separate `PerceptionState`; frame/scene cache lives in `ActionContext`).
Extract **one
collaborator per PR**, each behind the Phase-0 characterization tests, behavior
identical. Proposed split (methods verified from `phone.py`):

| Collaborator | Responsibility | Representative methods |
|---|---|---|
| `CoordinateMapper` | frame↔crop↔effector space, letterbox, app-viewport | `_to_phone`, `_*_coordinate_space`, `_cropped_to_effector`, `_frame_to_effector`, `_viewport_size`, `_refresh_letterbox_crop_bbox`, `_apply_app_viewport`, `invalidate_app_viewport` |
| `Perceptor` | snapshot/perceive/OCR/icons/scene-classify + caches | `snapshot`, `perceive`, `perceive_voted`, `_run_ocr`, `_bound_ocr_elements`, `_maybe_detect_icons`, `_apply_scene_classifiers`, `_classify_platform_scene_now`, `_set_last_scene`, `invalidate_perceive_cache` |
| `ElementSelector` | text/element resolution, VLM reground, memory priors | `describe`, `find_text`, `expect_text`, `expect_no_text`, `_vlm_reground_selection`, `_memory_locate_selection` |
| `TargetPlanner` | element → actuation plan, reground, tap-point geometry | `_tap_point_for_element`, `_springboard_icon_tap_point_for_element`, `_picokvm_settings_row_tap_point_for_element`, `_target_tap_plan`, `_target_actuation_plan`, `_reground_tap_point`, `_preferred_actuation_method` |
| `GestureExecutor` | low-level taps/swipes/drags/wheel | `tap_xy`, `double_tap_xy`, `long_press_xy`, `swipe_xy`, `drag_xy`, `scroll_wheel`, `wheel_scroll_*`, `swipe_*`, `_page_drag_xy` |
| `AssistiveTouchDriver` | AssistiveTouch menu/primitives | `assistive_touch_*`, `_assistive_touch_tap_visible_item` |
| `SystemNavigator` | home/back/recents/control-center/open/close app | `back_gesture`, `home`, `_home_*`, `recents`, `control_center`, `notification_center`, `open_app`, `close_foreground_app` |
| `TextInput` | type/IME/clipboard/key/input-source | `type`, `_type_via_clipboard`, `key`, `paste`, `switch_input_source`, `_ime_composing`, `_clear_focused_field` |
| `ActionRunner` | execute/verify/record *behavior* — operates on `ActionContext` (holds no state itself) | `_execute_action`, `_run_semantic_plan`, `_failed_action_result`, `_action_result_fields`, `_record_action`, `_verify_fresh_action_result`, `_fresh_scene_for_verification`, `_observe_memory` |
| *(stays Phone facade)* | high-level intents that compose collaborators + backend caps | `tap_text/element/button/intent`, `supports`, `has_real_effector`, `_effector_backend` |

**Sever the private coupling (same phase) — for ALL consumers in the Phase-0
inventory, not just orchestrator.** Three roles, one owner each (don't overlap them):
- **`ActionContext`** is the **single state owner** — *all* the mutable fields move here
  off Phone, including the frame/scene cache: `_last_frame`, `_last_scene`,
  `_needs_stable_frame`, `_fresh_source_reopened_after_action`, `_last_stable_frame`,
  `_pending_actions_for_memory`. (No separate `PerceptionState` — these are one object.)
- **`ActionRunner`** owns the *behavior* — it operates on `ActionContext` (e.g.
  `_record_action` becomes `ActionRunner.record_action()` which appends to
  `ActionContext.pending_actions`; `_observe_memory`/`_failed_action_result` likewise read
  & write the context). It does NOT hold the state itself.
- **`ActionHost`** (Protocol in `boundaries.py`) is the narrow *host* interface external
  consumers depend on — read accessors (frame/scene/viewport/semantic-plan state) **plus**
  the `record_action` write hook. (For strict read/write separation, split it into
  `ActionReader` + `ActionRecorder`.) `orchestrator`, `semantic_plan`, `action/recovery`,
  `ai`, and `ios/springboard` depend on *that*, not on `phone._private`.

The biggest item is the `ios_settings` skill layer: replace its `phone._viewport_size`
reads with a public accessor and move its **8 stamped `_ios_settings_*` attrs** off Phone
into the skill's own context object. (Separately — `_trace` is **not** a stamped attr: it
is a field of the `TracedPhone` *wrapper* (`crawl/trace.py:411/431`) that
`ios_settings/trace.py:157` reads via `getattr(phone, "_trace")` to detect wrapping; treat
it as a tracing-wrapper accessor, not part of the monkeypatch cleanup.) **Only the
*inventory* is pre-paid in Phase 0** — the accessors / `ActionContext` / `ActionHost` are
BUILT here;
Phase 0 will swap only the **3** getattr flag-reads (`ai.py:529`, `springboard.py:295`,
`orchestrator.py:1716`), so the remaining ~82 reach-sites are migrated in this phase.

DoD per PR: one collaborator extracted; Phone delegates; characterization tests +
`make check` green; one rig A/B at the end of the phase confirms no live nav drift.

## 5. Phase 2 — P2: extract the mega-method state machines

With Phone decomposed and orchestrator coupling explicit, the `_run_attempt` (260 L,
7-deep) / `execute` (206 L) / `_observe_after` (192 L) phase machines can be carved into
named methods without local-variable-in-closure traps:
- `_run_attempt` → `_prepare_attempt → _run_command → _observe_after → _verify` with the
  exception/retry handling as a small explicit state enum, not nested `try/elif`.
- `_observe_after` → split frame-stabilization / scene-diff / verifier-input assembly
  into three single-responsibility helpers.
DoD: no method > ~80 L or > 4 nesting levels in the touched paths; characterization
tests unchanged & green; rig A/B clean.

## 6. Phase 3 — P3: tidy the iOS/iPadOS seam (defer until a 3rd platform looms)

- Factor the **duplicate / near-duplicate** scene helpers into a shared
  `glassbox/ios/_scene_common.py` (or `platforms/scene_common.py`) and unify naming.
  Only `_semantic_marker_hits` (`ios/scene.py:653`) ≡ `_marker_hits`
  (`ipados/scene.py:553`) are verified **byte-identical**. `_scene_size`/`_text`/`_matches`
  are *near-duplicates*, NOT identical — e.g. `_scene_size` has platform-specific default
  fallbacks (iOS 448×973 `ios/scene.py:308` vs iPadOS 744×1133 `ipados/scene.py:115`), so
  share only the common frame and **parameterize the platform defaults**; don't collapse
  them into one function.
- Make the iPadOS→iOS scene fallback (`ipados/scene.py:74,83`) an explicit, documented
  delegation seam rather than an inline call, so mutations to iOS scene logic don't
  silently alter the iPad fallback.
- **Do NOT introduce a `RecoveryProvider` seam — it already ships** (`boundaries.py:124`
  Protocol → `IOSPlatform.recovery` at `platforms.py:148`, injected at `runtime.py:678`,
  smoke-covered `test_architecture_boundaries.py:931`; `IPadOSPlatform` inherits it).
  The real work is **boundary/call-order hygiene**: the platform `IOSRecoveryProvider`
  (`ios/recovery.py:64`) only handles `system_search`, while all Settings-specific
  recovery (`return_to_settings_root`, …) lives app-layer in
  `skills/regression/ios_settings/recovery.py`. Decide and document which recovery is
  platform-owned vs app-owned, and whether iPadOS needs to *override* the inherited
  provider (today it does not). Avoid building a second, duplicate seam.

**Recovery ownership note (2026-05-31):** keep the current two-layer split. Platform
recovery owns OS-wide surfaces and launch mechanics that are meaningful outside one app:
`system_search`, Home/SpringBoard launch, and any future Control Center/App Switcher
recovery. App-layer recovery owns app-specific state machines and safety policy:
Settings root/detail/search return, root-row drill-down, blocked-row handling, and
iPad Settings split-view sidebar/detail semantics. iPadOS should inherit the iOS
platform recovery provider until it needs a different OS-wide launch mechanic; iPad
Settings quirks stay in the Settings skill context/policy, not in the platform provider.
DoD: zero byte-identical helper pairs (merged) and near-duplicates parameterized into one
shared helper; a one-page note in this doc (or `screen_state_fsm.md`) pinning
platform-recovery vs app-recovery ownership; iOS scene change covered by a test that
proves the iPad fallback path is intentionally affected.

## 7. Ongoing — P5 retirement & P6 gap-fill

- **Flag retirement cadence:** when a default-off flag is rig-validated default-on for N
  runs, file the promote-to-unconditional + delete-branch follow-up; remove a legacy
  alias once no caller uses it. Target: net flag count trends *down* between feature
  pushes, not monotonically up.
- **Remaining test gaps (specific — the broad ones are already covered):** `test_vlm_gate.py`
  exists but VLM *selection* edge cases (cache-miss / budget-exhausted / confidence
  threshold) in `cognition/vlm_kimi.py` may still be thin; `test_stuck_loop_detector.py`
  covers the detector but `action/recovery.py` memory-path edge cases and the
  `_run_attempt`/`_observe_after` side-effect boundaries (Phase-0 P6) are the real
  untested surfaces. Audit each against current coverage before writing — don't
  re-assert "no coverage."
  **2026-05-31 audit:** VLM gate/cache/budget trigger coverage is present in
  `test_vlm_gate.py` and `test_computer_use_runtime.py`; `test_vlm_kimi.py` also
  covers non-finite/out-of-range confidence so malformed VLM scores cannot leak
  into element state.

## 8. What this roadmap deliberately does NOT do

- It does **not** rewrite working subsystems for aesthetics. `core.py` (1560 L of thin
  delegation) is intentionally a compatibility wrapper — leave it.
- It does **not** add abstraction the codebase hasn't earned (no speculative 3rd-platform
  framework before P3 is actually needed).
- It does **not** touch the iPad Settings reliability work — that is a separate track
  (`ipad_settings_state_machine.md`, levers L3b→L1→L2→L4). Code-health refactors and
  Settings levers should not ride in the same PR.
