# Design — Recognition→action pipeline (map + minimal-wiring audit)

Status: **map, not a change — produced 2026-06-01 against `add96d0`.** Answers
three questions about the runtime's perception→click/drag pipeline: (1) what is
the default path, (2) what *should* be wired by default but isn't, (3) what is
genuinely redundant and prunable. It is a strategic companion to
[`computer_use_honest_gate_first.md`](../goals/computer_use_honest_gate_first.md)
(the broken-compass redirection), [`code_health_roadmap.md`](code_health_roadmap.md)
(where the prune list below should be folded), and
[`architecture_boundaries.md`](architecture_boundaries.md) (the seams).

Method: an 11-layer multi-agent read of the live source, each layer classifying
its components `default-on / opt-in / dead-on-default / vestigial / unwired /
test-only` with a caller as evidence, followed by 116 adversarial "find a
default-path caller or it's dead" verdicts. The **three headline claims below
were then re-verified by hand this session** (grep + read); they are marked
✓verified. Everything else is the audit's classification — trust the line
numbers only as of `add96d0`; reference by symbol when they drift. Raw
structured output (11 maps + 116 verdicts) is persisted at
`artifacts/pipeline_audit/audit_2026-06-01.json` (git-ignored).

## Headline

> The recognition end is already lean — VLM, icon detection, screen-memory, and
> ~60 CUQ recognizer flags are correctly **default-off**. The real "unnecessary
> entity" problem is on the **action** end: the reliability stack the project
> built and A/B-validated (P2 strategy ladder, landing-retry, P3 recover-to-home)
> only runs on the path gated by one flag — and the **headline iPad rig
> acceptance run takes the other path, which bypasses almost all of it.** That is
> the most valuable thing to wire by default. The genuinely-dead code is small
> and surgical.

## 1. The default pipeline (one action: observe → act → verify)

Nine stages. "Default" here = a normal run with no opt-in flags set; on the
committed rig `.env` sets `GLASSBOX_PICOKVM=1`, so stage 1/8 land on PicoKVM.

| # | Stage | What runs by default | Key files (`@add96d0`) |
|---|-------|----------------------|------------------------|
| 1 | **Frame capture** | rig: `PicoKVMFrameSource` decoding HTTP H.264; no-hardware: `AVFFrameSource` (cv2/AVFoundation) | `backend_registry.py:123`, `perception/picokvm_source.py`, `perceptor.py:235` |
| 2 | **Letterbox crop + coordinate lineage** | `detect_crop` auto-detects letterbox at build; each snapshot `frame_px→cropped_px`, `FrameContext(projection='cropped_px')`; `frame_scope='device'` (app-viewport crop skipped) | `runtime.py:300`, `perception/letterbox.py`, `perceptor.py:197`, `geometry.py:10` |
| 3 | **OCR recognition** | Apple Vision direct (`VisionOCR`: unsharp, `uses_language_correction=False`, `custom_words=['+','-']`, accurate) → `UIElement(type='text')`, capped 800 elems / 1024 chars; no OCR watchdog | `cognition/ocr_vision.py:54`, `config.py:167 (ocr='vision')`, `perceptor.py:421` |
| 4 | **Typer / control enrichment** | `HeuristicTyper.upgrade` over `DEFAULT_RULES` (status_bar, nav_back, tab_bar, list_item, button…) + OpenCV modal-close `×`; scene-classification projection. **No VLM, no general icon detection** | `cognition/heuristic.py`, `cognition/icon_detect.py:39`, `contracts.py:97` |
| 5 | **Target selection** | (a) coordinate: crawler computes cx,cy → `phone.tap_xy`; (b) target-bearing (Settings row + every `AIPhone` tap): `expect_text→find_text` (fuzzy 0.8) → `UIElement`. OCR miss hard-fails unless a fallback flag is on | `element_selector.py:140`, `cognition/ocr.py:135`, `phone.py:1422/1613` |
| 6 | **Target → gesture plan** | `target_actuation_plan` → control bucket → `mouse_tap` → `tap_point_for_element` (settings-row re-aim, icon centroid) + candidate points → `ActuationPlan`. Coordinate path builds a bare `tap` (point only, no identity) | `target_planner.py:275/204/70`, `action/actuation.py:99`, `ios/safe_area.py:50` |
| 7 | **Coordinate mapping** | `CoordinateMapper.to_phone`: `cropped_px → effector frame_px` (adds crop offset back) | `coordinate_mapper.py:14/62`, `phone.py:660` |
| 8 | **HID emission (click/drag)** | PicoKVM: tap = 2×absMouseReport settle → down 100ms → up. Scroll: **iPad `wheelReport` (default-on)** / **iPhone swipe-fling drag (wheel default-off)**. back = Meta+[. Unconfigured runs → `NoOpEffector` | `effectors/picokvm/effector.py:494/662/563`, `effector.py:308`, `backend_registry.py:154` |
| 9 | **Verification** | per-op verifier (tap→`TapTargetEffect`, scroll→`SceneProgressed`, back→`NavigationBack`): `detect_disqualifying_state` + `compute_frame_diff`/`compute_scene_diff`; signature → `StuckLoopDetector` | `verification/registry.py:31`, `verification/verifiers.py:465`, `verification/diff.py`, `memory/signature.py:27` |

Stages 1–4 = "recognition"; 5–8 = "click/drag"; 9 = feedback.

## 2. The crux: there are **two** default paths, forked on one flag ✓verified

The entire reliability stack lives or dies on whether `cfg.computer_use_artifact_dir`
is set — it gates whether `runtime.py:571` builds the `ActionOrchestrator`, and
`action_runner.py:62` reroutes **all** actions through it once present.

- **Path A — orchestrator / task path.** Reached by the `AIPhone` facade
  (`ai.py:1290` *always* forces `computer_use_artifact_dir='artifacts'`,
  `stable_after_action=True`) and by the success-rate benchmark
  (`computer_use_success_rate.py` injects `GLASSBOX_COMPUTER_USE_ARTIFACT_DIR`).
  The full spine runs: per-attempt observe→risk→command→observe→diff→verify, the
  **P2 strategy ladder** (`semantic_plan_ops='back,scroll,tap'`,
  `config.py:496`), **landing-observation + missed-tap reground** (because
  `tap_element` carries `target_identity`/`control_bucket`/`target_roi`), and
  **P3 recover-to-home** on stuck (`runtime.py:624` installs
  `RuntimeRecoveryPolicy(hook=recover_to_home_then_renavigate)`). **The
  A/B-validated 0→0.5 / 0.955 numbers are this path.**
- **Path B — crawl path.** The direct iPad Settings rig
  (`make ipad-settings-state-machine` → `run_full` → `crawl_readonly_settings`).
  `build_full_run_env` sets `GLASSBOX_PICOKVM`/`ENABLE_VLM`/`ENABLE_MEMORY` but
  **never `GLASSBOX_COMPUTER_USE_ARTIFACT_DIR`**, so `action_orchestrator` stays
  `None` and `action_runner.execute_action` takes the bare-effector branch.
  `tap_element`'s rich `ActuationPlan` collapses to `command_for_attempt(0)`'s
  first coordinate — **strategy ladder, landing-retry/reground, expected-state
  verification, and recover-to-home all no-op.** The crawler substitutes
  hand-rolled equivalents (per-candidate reground, same-page-after-tap retry,
  wheel→swipe fallback, multi-pass scroll reset, return-to-root). The one
  reliability primitive it keeps is the PicoKVM fresh-frame `_semantic_verify`
  (`action_runner.py:87`, gated on `GLASSBOX_PICOKVM`).

✓verified this session: `runtime.py:571` gates on `cfg.computer_use_artifact_dir`;
`ai.py:1290` always sets it; `grep COMPUTER_USE_ARTIFACT_DIR skills/regression/ios_settings/`
returns nothing.

**Consequence:** the 0.955 / A-B reliability numbers reflect Path A machinery,
but `make ipad-settings-state-machine` (the headline rig acceptance) is Path B
and exercises almost none of it. This is the mechanism behind "complex but low
utility" — the machinery is not dead, it is *bypassed by the headline workload.*

## 3. Should be wired by default (the missing entity)

| Wire this | Why | Current state |
|-----------|-----|---------------|
| **Route the direct Settings rig through the orchestrator** — set `computer_use_artifact_dir` in `build_full_run_env` | One env var makes the headline rig validate the product's actual reliability stack instead of hand-rolled substitutes. The verdict explicitly reclassifies the "dead machinery" premise as *false* → fix is **wire-default** | opt-in: `skills/regression/ios_settings/config.py:157` never sets it |
| **A real-pipeline offline gate for `make check`** (`StaticFrameSource` replay → perceive→classify→select→plan→NoOp effector) | The current regression-gate diffs a frozen JSON fixture against a degraded copy of itself; it never builds a FrameSource/perceive/effector, so an OCR / tap-routing / scroll regression produces **no signal**. It proves comparator math, not field reliability | missing; `Makefile:13` check→regression-gate runs only schema validate + comparator self-test |
| **Replace the failed-floor fixture with a completed multi-round baseline** (+ keep the new floor-honesty assertion) | `reliability_baseline.json` is a *failed* run (`task_completion_rate=0.0`, ends on Weather); `compare` only flags a DROP, so the headline metric can never regress below 0.0. The in-flight `test_committed_baseline_floor_completed_a_task` asserts >0 and currently makes `make check` **RED** | broken; tracked in [`computer_use_honest_gate_first.md`](../goals/computer_use_honest_gate_first.md) — **this is the active working-tree change** |
| **`IOSRecoveryProvider.detect/recover` consumed in the step loop — or delete the class** | A Spotlight/global-search trap is exactly the dead-end the stuck detector exists for, yet the provider is constructed, threaded onto `phone.recovery_provider`, and **never read** in `glassbox/`. Worst of both: built, wired, never run | dead wiring: `platforms.py:148`→`runtime.py:682`→`phone.py:503`, zero production reader ✓verified |
| **Wire the memory drift signals** `last_transition_mismatch` / `last_recognize_score` into recovery/verification | Computed on every observe/recognize on the default path, read by no non-test code; roadmap left the consumer as a follow-up | producer default-on, consumer unwritten: `memory/graph.py:75-82` |

## 4. Genuinely redundant / prunable (the unnecessary entity)

Adversarially confirmed to have no default-path caller. Low-risk, surgical;
these should feed [`code_health_roadmap.md`](code_health_roadmap.md).

| Item | Why dead | Note |
|------|----------|------|
| **Duplicate `find_text`** `ocr_vision.py:267` | strictly-weaker copy of `cognition.ocr.find_text` (no ambiguity guard); only 2 smoke tests import it | ✓verified test-only — delete, repoint tests at `glassbox.cognition.find_text` |
| **`IconDetectFunctionAdapter` + icon-detector registry / entry-point** | the one backend registry of five `runtime.py` never `.create()`s; real path calls raw `detect_icons()` directly | keep raw `detect_icons`/`detect_icons_voted`; remove `icon_contract.py` + `backend_registry.py:198-207,280-285` + entry-point |
| **`SemanticActionPlan.run()` in-class ladder** `semantic_plan.py:218-360` (incl. `escalate_vlm`) | a complete *second* ladder engine the orchestrator never calls (it reimplements in `_run_semantic_plan_loop`); `escalate_vlm` doubly dead | migrate its 12 ladder-semantics assertions onto the orchestrator loop first |
| **`IOSRecoveryProvider` class + `phone.recovery_provider` plumbing** | see §3 — built, wired, never read | **keep** module-level `dismiss_system_search` (live in `skills/regression/ios_settings/recovery.py`); remove only the class+plumbing. Or wire-default (§3) |
| **`StuckLoopDetector.observe_and_recover`** `stuck.py:125` | convenience wrapper the orchestrator deliberately open-codes (needs audit markers + budget the wrapper can't express); one unit test keeps it alive | delete method, keep class |
| **`PicoKVMVideoConfig`/`Settings`** `perception/picokvm_config.py` | live factory always injects `PicoKVMEffectorConfig` (a superset); the `config or PicoKVMVideoConfig()` fallback is unreachable | switch annotation to a Protocol, drop the re-exports |
| **`IOSSafeArea.insets()` stub + `Insets`** `ios/safe_area.py:53`, `boundaries.py:37` | always returns empty `Insets()`; zero callers (live method is `bottom_hit_point`) | keep provider + `bottom_hit_point` |
| **Misc dead leaves** | `_KEY_UP_ARROW`/`_KEY_V` keycodes (`effector.py:31`, zero refs); `assistive_touch_layout_model` + 3 helpers behind an unimported shim; `apply_ios_classification` (`ios/scene.py:287`, test-only); `make_vlm_client`/Kimi aliases (`DEFAULT_URL`/`MODEL` zero refs); `ios/crawl.py` `settle_then_read`/`ReadPolicy`/3 result types | each trivial-to-low risk; keep the singular `assistive_touch_primitive`, `classify_scroll_attempt`, `CrawlMetrics` (live) |

## 5. Correctly opt-in — do **not** over-wire (Occam cuts both ways)

- **P1 VLM escalation + the whole VLM layer** (`vlm_gate`, describe/enrich, SoM,
  coldstart): double-gated (needs `expected_state` **and** a non-`None` kimi);
  VLM is billed/latency-bearing, so default-off is the correct cost posture. Keep
  behind `GLASSBOX_ENABLE_VLM`.
- **Expected-state verification** (`verify_expected_state` via
  `metadata['expected_state']`): the real agent post-condition mechanism
  (`ai.tap(expect_*)`); a no-op unless a caller declares an expectation —
  correctly opt-in to the agent facade.
- **ScreenMemory / UTG stack + iPad settings-root projection**: behind
  `GLASSBOX_ENABLE_MEMORY` / `GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION`. The iPad
  root projection is still rig-acceptance-gated — do **not** flip default-on
  standalone (see [`ipad_settings_state_machine.md`](ipad_settings_state_machine.md)).
- **Crawler-only OCR sub-pipeline** (`vlm_ocr`, `label_prior`, closed-set
  `canonical_label`/`match_known_label`, `vote_scenes`): live for the regression
  rig, not the default `find_text` path — keep crawler-scoped.
- **Generic crawl subsystem**, `StaticFrameSource`, `MockEffector`, AVF ffmpeg
  fallback + `recover_capture_device` (error-only), `ocrmac` backend,
  `actuation_seed`/`calibration_probe`, `double_tap`/`long_press`: correctly-gated
  opt-in / defensive surfaces — side-effect-free when unreached.
  **Note** `keyboard_focus_activate` *is* reached default-on as the tap-ladder
  fallback when a tap verified-fails — not dead.

## 6. Open questions (product/maintenance calls the audit can't make)

1. Is the PicoKVM rig "the product", or is the no-flag NoOp/AVF path? The
   committed `.env` makes the rig the local default; a clean checkout drives no
   hardware. Should `picokvm`/`requires_calibrated_crop` be the literal config
   default vs an env flag?
2. **Which task path is canonical** — promote the direct iPad rig to the
   orchestrator path (§3 #1), or is the crawler's hand-rolled reliability
   intentionally separate? This decides whether the ladder/landing/recovery code
   is "dead weight on the headline workload" or just exercised by a different
   entrypoint.
3. Should the crawler's auxiliary search/recovery affordance taps (raw `tap_xy`)
   route through `tap_element` to gain reground/landing-retry, or is
   coordinate-tapping correct for icon-grid targets with no OCR text element?
4. For symbols kept alive solely by tests (`apply_ios_classification`,
   `SemanticActionPlan.run()`, `make_vlm_client`, several `ios/crawl` contracts):
   delete + migrate tests, or keep as executable specs?
5. Was the in-flight floor-honesty assertion meant to land with a regenerated
   completed-floor fixture? `make check` is RED until the floor is replaced.

---

*Provenance: 11-layer agent map + 116 adversarial verdicts, `add96d0`,
2026-06-01. Headline §2 + the three ✓verified rows hand-checked this session.
Line numbers drift — reference by symbol. Raw output:
`artifacts/pipeline_audit/audit_2026-06-01.json`.*
