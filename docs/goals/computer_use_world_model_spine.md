# Computer-Use Endgame: World-Model as Spine

Status: **THESIS + ACTION ROADMAP, with implementation slices — updated
2026-06-03.** Distilled from an architecture review (autonomous-driving analogy
→ glassbox). This branch implements offline-verifiable primitives for **0b**,
**B1**, **B2**, **A1**, and **B3**, then wires **0b/A1/B1/B2** into default-
compatible runtime or harness entrypoints. These are contracts / entrypoints /
guards, not a claim that the task-level roadmap is complete. Every `file:line`
anchor is a **snapshot as of `1d75ee9`** —
regenerate with the command in [Anchors](#anchors-regenerate-before-trusting-line-numbers)
before trusting a number.

## Thesis

The endgame of an out-of-band computer-use runtime is **not** "collapse the
classic pipeline (`observe → decide → act → verify`) into two stages." Stage
*count* is a red herring. The two variables that actually matter — borrowed from
the modular→end-to-end arc in autonomous driving — are:

1. **Are the inter-stage interfaces lossy?** Today a downstream stage sees only
   what the upstream stage chose to emit (a list of OCR text strings). Geometry,
   history, and device feedback that the upstream dropped are gone for good.
2. **Is there a first-class, persistent belief-state in the middle?** The
   BEV/world-model that perception *writes into* and planning *reads from*. In
   glassbox that role belongs to the UTG screen-memory graph.

So the endgame is a **world-model-as-spine closed loop**: perception writes the
belief-state, decision reads it, control selects an actuation by current HID
capability, verification writes the result back. "Perception that knows how it
got here and how to get home" and "control that picks the best HID method" are
both just *views onto that one shared belief-state* — not two megastages.

## Root cause (upstream of almost everything)

**Perception has historically been stateless.** Scene classifiers were pure
functions of the current frame; memory was observed *after* the scene was
already classified, so classification structurally could not use belief.

- `perceptor.perceive()` runs `apply_scene_classifiers` then `observe_memory`
  (`perceptor.py:447` → `:449`; same order at `:471`→`:475` and `:756`→`:763`).
- Classifiers historically received only `(scene, viewport_size)`
  (`perceptor.py:106-114`) — no memory handle. The initial implementation slice
  keeps old classifiers compatible while allowing prior-aware classifiers to
  accept `prior=SceneClassificationPrior`. The follow-up wiring slice passes
  this prior through runtime platform/app classifier wrappers and lets the iOS
  Settings-detail classifier abstain when a non-Settings prior conflicts with a
  weak Settings read.
- The UTG is opt-in and default-off (`enable_memory = False`, `config.py:657`),
  so most runs build no belief-state at all.

Consequence before the slice: the system re-derived "where am I" from raw OCR
every frame, with no "I just came from Home into Settings" prior. The slice adds
the contract and wiring; the remaining work is making platform/app classifiers
consume the prior for real arbitration.

## Problem map (symptoms of the missing spine)

Grouped by what it takes to fix, not by severity. Snapshot `1d75ee9`.

**C — Measurement (the meta-problem; fix FIRST).**
A failed run can pass the green gate, and there is no single accuracy number by
design — honest, but it means the architecture defects below stay invisible on
CI. You cannot tell whether any spine/wiring change helped without an honest
task-level compass on the *default* path. See `computer_use_honest_gate_first.md`,
`computer_use_success_rate.md`.

**B — Architecture (real design changes; fix SECOND).**
- **B1 Belief-conditioned perception.** Invert the observe-memory ordering so the
  UTG/last-state prior feeds classification *before* it commits to a scene
  identity (`perceptor.py:447`↔`:449`, classifiers at `:106-114`). Initial
  slice: `Perceptor` now builds a read-only `SceneClassificationPrior` via
  `memory.recognize()` and passes it to classifiers that opt in with `prior=`.
- **B2 Authoritative scene arbitration by VLM.** The projector copies
  `platform_scene_kind` from the platform source and lets the VLM write only
  `semantic_scene_type` (`contracts.py:126-127` vs `:142-162`). The VLM can
  *think* but not *steer* scene identity. Initial slice: VLM output may now
  include `platform_scene_kind`; `unknown` explicitly clears stale `page_id` and
  `safe_actions` so System-2 can safely veto a bad platform read. The follow-up
  wiring slice preserves VLM scene arbitration when classifiers rerun after
  `describe()`, and `perceive()` escalates to the configured VLM only when the
  current classifier result already marks the scene `vlm_on_uncertain`.
- **B3 Live capability model.** `BackendCapabilities` is a static declaration
  (`effector.py:166-202`), not validated/updated from action outcomes at runtime.
  Initial slice: current-run `ActuationProfile.record_attempt()` feedback is
  locked by smoke as a live de-advertise signal for failed methods.

**A — Wiring (capabilities exist, not load-bearing; fix THIRD, once the compass
can prove them).**
- **A1 Proactive navigation.** `graph.path()` / `path_to_page()`
  (`graph.py:228` / `:257`) are BFS-ready but only called reactively by
  `recover_to_home_then_renavigate` after stuck-recovery (`recovery.py:71-77`;
  installed default-on at `runtime.py:631-637`). Initial slice:
  `navigate_via_memory_path()` promotes the same safe replay machinery into a
  normal decision entrypoint without Home fallback. The follow-up wiring slice
  exposes this through `Phone.navigate_to_page()` and the AI facade's
  `AIPhone.navigate_to_page()`. Remaining work: make higher-level planners
  choose it automatically and extend the UTG beyond Settings to generic apps.
- **A2 Decision brain.** No owned/learned `observe→decide→act→verify` loop;
  decisions are hand-scripted in skills, and `tap_xy` (`phone.py:1714`) bypasses
  the orchestrator entirely. The realistic "policy" is VLM-as-System-2, **not** a
  trained net — glassbox has no large `(state, action)` corpus.
- **A3 Signature stability under richer perception.** `compute_signature` drops
  `is_volatile` (`list_item`) text from `stable_texts` (`signature.py:55`,
  `element_key.py:33`), so any perception change that re-types rows shifts the
  belief-state's identity basis. Only the iPadOS Settings root is currently
  special-cased (`graph._ipados_settings_root_signature`, `graph.py:418`); a spine
  made of UTG nodes needs a non-root regression guard.

## Actions, in dependency order

The ordering *is* the point: each tier needs the previous one to be measurable.

0. **Compass first.** Two parts; the second is the cheapest concrete step in the
   whole roadmap.

   **0a. Honest task-level signal.** A default-path metric a failed run cannot
   pass. Until it exists, treat every improvement below as unproven. (Builds on
   the existing honest-gate work; the gap is that it isn't on the load-bearing
   path.)

   **0b. Canonical home-reset + verify as the navigation-measurement origin.**
   On a new navigation task, reset to Home **and verify Home is reached before
   starting the clock**, so every measured trajectory is `Home→X` from a fixed
   origin. This is what makes navigation *measurable at all*:
   - a fixed origin makes route length / recoveries / edges comparable across
     runs (you can't A/B "did navigation improve" from a drifting start);
   - it gives the UTG a guaranteed-reachable **root**, so `path_to_page` is
     always defined and the graph stays connected instead of fragmenting into
     islands (observed screens with no route from a known anchor);
   - it bounds the off-trajectory state space so trajectories become replayable
     (off-trajectory is the wall for log-sim/UTG-sim; a shared origin is the
     lever against it).

   Mostly already-built — this is *promoting an existing recovery primitive to a
   task-entry discipline*, not new machinery. `recover_to_home_then_renavigate`
   (`recovery.py:34`) already treats Home as the universal anchor (`phone.home()`
   then optional `path_to_page`), and `system_navigator.home()`
   (`system_navigator.py:97`) already verifies arrival via the
   `ios_home_screen_visible` semantic verifier with a fallback ladder
   (`:107-158`, `home_reached` at `:164`). **The verify is load-bearing:**
   `phone.home()` is rig-dependent and can fail, so a failed reset must be
   measured as a **separate precondition**, never silently folded into the
   navigation metric.

   Two caveats, both mandatory:
   - **Dual-axis, not single-axis.** `Home→X` is the clean *lower-bound* axis
     (stateless navigation). "Navigate / recover from an *arbitrary* state"
     (off-trajectory) is a separate, harder axis graded later — do not let
     home-reset become the *only* measured path, or you measure the easy case and
     declare the spine sound (the census-flip trap; see
     `computer_use_honest_gate_first.md`).
   - **Harness / navigation-class default, not a production default.** Resetting
     discards in-app context (half-filled forms, modals, deep views off the clean
     route) and taxes every task with a `home + re-nav`. Default it for the eval
     harness and navigation-class tasks; let stateful tasks opt out.
1. **Spine — belief-conditioned perception (B1).** First concrete step: pass the
   recognized prior node + last action into `apply_scene_classifiers` as an
   optional `prior`, and let a classifier use it to break ties (e.g. "entered
   from App Store → resist the Settings reading"). Gate: task-level A/B on
   App-Store / settings-detail disambiguation, **not** a census flip.
2. **System-2 can steer (B2).** Let VLM escalation arbitrate `platform_scene_kind`
   under the existing triggers, not just annotate `semantic_scene_type`. Gate:
   `unknown_rate` ↓ and misclassification ↓ on a multi-app surface, task-level.
3. **Navigation in the loop (A1).** Call `path_to_page` proactively, UTG extended
   past Settings. Gate: fewer recoveries / shorter routes on a multi-app task.
4. **Live control + signature guard (B3, A3).** Feed `actuation_profile` success
   rates into live strategy selection and de-advertise a failed capability within
   a run; add the non-root signature-stability regression.

## Implementation Slices

- `prepare_navigation_measurement_origin(phone)` returns a
  `NavigationMeasurementOrigin` and only sets `can_start_clock=True` when
  `phone.home()` reports `semantic_status == "succeeded"`. Unverified or failed
  Home resets are precondition failures, not navigation trajectory samples.
- `skills.regression.canonical_primitives` now uses that Home precondition by
  default for navigation-class primitive runs, records `navigation_origin` in the
  run manifest and `navigation_origin.json`, and keeps
  `--skip-navigation-origin` as an explicit opt-out.
- `SceneClassificationPrior` is a cognition contract with recognized UTG node
  identity (`screen_id`, `page_id`, scene-kind fields) plus the pending
  successful last action (`last_action_op`, `last_action_target`,
  `last_action_via`).
- `Perceptor.apply_scene_classifiers()` computes that prior before projection and
  passes it to classifiers that declare `prior=`, while old
  `(scene, viewport_size)` classifiers stay compatible.
- Runtime platform/app classifier wrappers now accept `prior=`, iOS/iPadOS
  classifiers propagate it, and the iOS Settings-detail classifier can abstain to
  `unknown + vlm_on_uncertain` when a weak detail read conflicts with a known
  non-Settings prior.
- VLM describe output may now carry `platform_scene_kind` and optional `page_id`.
  When System-2 returns `platform_scene_kind="unknown"`, stale page IDs and safe
  actions are cleared instead of leaving a dangerous platform-classifier residue.
- `perceive()` now consumes `vlm_on_uncertain` when a VLM client is already
  configured, runs one scene-arbitration describe on that frame, and preserves the
  VLM's authoritative platform kind when platform/app classifiers rerun.
- `navigate_via_memory_path(phone, target_page, ...)` is the proactive A1
  primitive: recognize current node, ask `path_to_page`, replay only allowed
  generic edges, and verify arrival without falling back to Home.
- `Phone.navigate_to_page()` and `AIPhone.navigate_to_page()` expose that
  proactive memory-path navigation on normal runtime/facade surfaces.
- Current-run actuation feedback is covered as a live B3 de-advertise signal:
  once a method crosses the unactuatable gate, `should_skip_bucket()` flips
  immediately for the next decision in the same run.
- Smoke coverage: `skills/smoke/test_world_model_spine.py`,
  `skills/smoke/test_ios_scene.py`, `skills/smoke/test_canonical_primitives.py`,
  and `skills/smoke/test_ai_native_interface.py`.

## Non-goals / honest posture

- **No literal end-to-end *trained* policy.** No large labeled
  `(observation, expert-action)` corpus exists; System-2 is a VLM, not a net.
- **No single headline accuracy number.** Kept deliberately multi-layer (see
  `computer_use_success_rate.md`); do not cite one rate as task success.
- **Stage-count reduction is explicitly NOT a goal.** The spine + lossless
  interfaces are.
- **No forced Home reset for every production workflow.** The verified Home
  origin is defaulted for canonical navigation measurement, not for arbitrary
  stateful tasks that need to preserve in-app context.

## Anchors (regenerate before trusting line numbers)

Snapshot `1d75ee9`. Numbers drift — regenerate, do not transcribe:

```sh
git rev-parse --short HEAD
grep -n "observe_memory\|apply_scene_classifiers\|def perceive" glassbox/perceptor.py
grep -n "enable_memory" glassbox/config.py
grep -n "def path\b\|def path_to_page" glassbox/memory/graph.py
grep -n "path_to_page\|recover_to_home_then_renavigate" glassbox/action/recovery.py
grep -n "platform_scene_kind\|semantic_scene_type\|_choose_semantic" glassbox/cognition/contracts.py
grep -n "not is_volatile\|return el.type == " glassbox/memory/signature.py glassbox/memory/element_key.py
grep -n "class BackendCapabilities\|def supports_semantic" glassbox/effector.py
grep -n "def tap_xy" glassbox/phone.py
grep -n "RuntimeRecoveryPolicy\|recover_to_home_then_renavigate\|max_attempts" glassbox/runtime.py
grep -n "def recover_to_home_then_renavigate\|phone.home\|path_to_page" glassbox/action/recovery.py
grep -n "def home\|home_reached\|ios_home_screen_visible\|needs_fallback" glassbox/system_navigator.py
```

Related: `computer_use_quality_roadmap.md`, `computer_use_honest_gate_first.md`,
`computer_use_success_rate.md`, `ipad_settings_state_machine.md`.
