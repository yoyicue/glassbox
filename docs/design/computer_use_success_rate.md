# Computer-Use Success Rate

Status: design note; Step 0 through P3 have an initial implementation.
This document sets the direction for raising end-to-end computer-use
reliability. It is deliberately **reliability-first**: we optimize success rate
before efficiency (latency/cost). Speed work comes after the numbers are good
and measured.

## Principle

> Maximize task success rate first. Accept extra latency, extra observations,
> extra VLM calls, and full retries as the price of reliability. Optimize
> efficiency only once success rate is high and measured.

## Design rules (invariants)

These are the rules every stage should follow under reliability-first:

1. **Never act on an unstable or low-confidence observation.** Wait for a stable
   fresh frame before acting; if OCR is low-confidence or the target is not
   found, escalate to the VLM rather than guessing.
2. **Verify every action against an expected state.** Treat `unknown` as failure
   (re-observe / switch strategy / recover), never as silent success.
3. **Exhaust strategies before giving up.** Each semantic action has an ordered
   list of strategies; on verified failure, switch to the next one.
4. **Always have a universal recovery: return to a known anchor (Home) and
   re-navigate** using screen memory. **Exception:** a safety / high-risk
   disqualifying state (SOS, power-off, approval-required) — there we stop and
   surface, never auto-recover or continue input (see the P2 state machine).
5. **Make steps idempotent and re-entrant** so retries and recovery are safe.
6. **Rank input primitives by reliability** and always verify the low-fidelity
   ones: `tap` > AssistiveTouch menu > keyboard combo > HID gesture / wheel.
7. **Accept the cost.** VLM **escalation when triggered** (per the P1 gating
   contract — not on every step), generous waits, and full retry budgets are
   acceptable until the success-rate baseline is healthy.

## Where success rate leaks today (grounded)

Observed during device-backed testing plus a read of the current tree.

1. **Perception is OCR-first by default; VLM grounding is opt-in (off).**
   `glassbox/cognition/candidates.py` ships an OCR+heuristic baseline and a VLM
   annotation strategy as an A/B; the default decision path is OCR. OCR cannot
   read Home/App-Library icon labels, and scene classifiers are heuristic and
   false-positive prone (`is_ios_home_screen` in `glassbox/ios/springboard.py`
   returned `True` on a Settings detail page and on App Library). Wrong target
   selection and wrong verification both follow. **Biggest leak.**
2. **Input fidelity gap: the HID pointer is not a touch digitizer.** The remote
   device-control path drives an absolute AssistiveTouch pointer, so system
   gestures and multi-touch are approximations iOS may ignore (home-indicator
   swipe missed, `wheelReport` not consumed, `Cmd-H` accepted by the device but
   ignored by iOS). Reliable primitives are taps and the AssistiveTouch menu;
   the rest can silently no-op.
3. **Retry repeats the same action; there is no systematic strategy switch.**
   `glassbox/action/orchestrator.py` has `retry_budget`, `landing_retry_budget`,
   `recovery_policy`, and `recovery_seed`, but retrying a flaky `Cmd-H` N times
   still fails. The fix shipped for `Phone.home()` (keyboard → AssistiveTouch →
   indicator drag) is the right pattern but is hand-coded per method.
4. **Verification reuses fragile perception and is mostly generic.** Fresh-frame
   semantic verification (not trusting transport ACK) is the right idea, but it
   diffs OCR scenes; if OCR is wrong the verdict is wrong, and generic
   `scene_progressed` is downgraded to `unknown`. Without a per-action expected
   state, the loop cannot reliably confirm success.
5. **Fixed calibration and fixed waits.** The current linear fit and gesture
   anchors are tuned on one calibrated test device; fixed `settle_ms` sleeps
   either act on stale frames or waste time. No per-session auto-calibration.
6. **Capture/transport robustness.** Single-consumer H.264 stream, service
   variability, pre-keyframe garbling, and per-call letterbox-crop drift can
   produce stale/garbled frames and coordinate jitter.
7. **Screen memory underused for control.** The UTG graph
   (`glassbox/memory/graph.py`) is not strongly driving shortest-path
   navigation, loop/stuck detection, or "transition mismatch = failure".

## Root cause

The strongest capabilities — VLM grounding, strategy switching, expected-state
verification, screen-memory navigation — are **not on the default path**. The
default path is built on the most fragile links: OCR, fixed coordinates, generic
verification, and same-action retry.

## Plan (reliability-first ordering)

### Step 0 — Measure: a success-rate harness

You cannot protect success rate without a number. Extend `run_full` /
`skills/regression/ios_settings/verify_report.py` into a repeatable success-rate
benchmark. Start with the **minimal** harness: a fixed task set, N repeats, and a
machine-comparable artifact.

- **Tasks:** the read-only Settings walkthrough (exists) plus a few canonical
  primitives — go Home, launch an app, back, scroll-to-bottom.
- **Method:** run each task N times; aggregate the success-rate distribution.

**Artifact schema (must be defined first — without it later runs cannot be
auto-compared).** One JSON document per benchmark run:

```jsonc
{
  "schema_version": 1,
  "run_id": "…", "started_at": "…", "git_sha": "…",
  "config": { "vlm_enabled": false, "phone_model": "test_phone_model" },
  "tasks": [
    {
      "task": "settings_readonly_walkthrough",
      "round": 0,
      "terminal_expected_state": { "kind": "page_id|visible_text|root_coverage_complete|…", "payload": {} },
      "outcome": "succeeded|failed|unknown",
      "final_state": { "page_id": "…", "is_anchor": true },
      "root_pages_expected": 17,        // size of the task's expected top-level page set
      "root_pages_covered": 12,         // sections actually ENTERED (detail page opened)
      "root_pages_blocked": 2,          // deliberately not entered (unsafe/protected); excluded from the denominator
      "root_pages_missing": ["…"],      // reachable sections seen but not entered this round
      "actions": [
        {
          "seq": 0,
          "role": "primary|recovery",
          "op": "home|back|launch_app|tap|scroll|…",
          "target": "…",
          "expected_state": { "kind": "page_id|visible_text|element_appears|element_gone", "payload": {} },
          "chosen_strategy": "assistive_touch_home",   // winning/final strategy
          "verdict": "succeeded|failed|unknown|blocked|transport_failed",   // normalized bucket (stable for compare)
          "raw_semantic_status": "succeeded|failed|partial|unknown|no_after_scene|transport_failed|exception|blocked|approval_required",
          "semantic_verifier": "ios_home_screen_visible",
          "confidence": 0.0,
          "selection_source": "none|system|memory|ocr|vlm",   // how the target was chosen (final)
          "verification_source": "none|system|memory|ocr|vlm", // how the outcome was verified (final)
          "vlm_calls": 0,                              // total over the action
          "vlm_cache_hits": 0,                         // cached VLM describe_scene responses
          "vlm_cache_misses": 0,                       // backend VLM describe_scene responses
          "vlm_triggers": ["target_missing", "verify_unknown"],
          "last_vlm_trigger": "verify_unknown",
          "vlm_budget_exhausted": false,
          "attempt_count": 2,
          "attempts": [
            { "idx": 0, "strategy": "keyboard_combo", "verdict": "failed",
              "selection_source": "ocr", "verification_source": "ocr",
              "vlm_calls": 0, "duration_ms": 0 },
            { "idx": 1, "strategy": "assistive_touch_home", "verdict": "succeeded",
              "selection_source": "ocr", "verification_source": "vlm", "vlm_calls": 1,
              "vlm_cache_hits": 0, "vlm_cache_misses": 1,
              "duration_ms": 0, "switched_reason": "expected_state_unmet" }
          ],
          "strategy_switches": 1,                      // count; per-switch reason in attempts[]
          "recovered": false,
          "duration_ms": 0
        }
      ]
    }
  ],
  "metrics": {
    "task_completion_rate": 0.0,
    "action_success_rate": 0.0,
    "unknown_rate": 0.0,
    "root_pages_coverage": 0.0,
    "recoveries": 0,
    "strategy_switches": 0,
    "retries": 0,
    "vlm_calls": 0,
    "vlm_calls_per_task": 0.0,
    "vlm_cache_hits": 0,
    "vlm_cache_misses": 0,
    "vlm_cache_hit_rate": 0.0
  }
}
```

The per-action and per-strategy-switch records are the point: they let us diff
two runs and attribute a success-rate change to a specific stage. Reuse the
existing `actions.jsonl` / `attempt_groups.jsonl` / `audit.jsonl` the
orchestrator already writes; this schema is the aggregated, comparable view.

**Counting rules (define the denominator, or `compare` will produce false
diffs):**

- An **action is the unit**, counted **once** regardless of attempts; the scalar
  is `attempt_count` and per-attempt detail lives under `attempts[]`. Success is
  judged at action resolution, not per attempt.
- **`verdict` is the normalized bucket; `raw_semantic_status` keeps full
  fidelity.** Metrics use `verdict`; the runner's state machine uses
  `raw_semantic_status`. Normalization (stable across runner changes):
  `partial → failed`; `no_after_scene → unknown`; `exception → transport_failed`;
  `approval_required → blocked`; the rest map to themselves.
- `action_success_rate` = `succeeded` primary actions ÷ **primary** actions.
- `unknown_rate` = `unknown` primary actions ÷ **primary** actions (same
  denominator), reported separately so a `failed → unknown` shift is visible.
  `unknown` counts as **not success**.
- **Recovery actions are excluded** from both denominators (`role: "recovery"`);
  they are counted only under `recoveries`. `recovered` is a **primary-action**
  field meaning "this primary action triggered a recovery and then continued to
  completion" — it is not the recovery action itself.
- A strategy switch within one action is **not** a new action; it increments
  `strategy_switches`. A retry of the same strategy increments `retries`.
- `task_completion_rate` = rounds whose task evidence satisfies
  `terminal_expected_state` ÷ total rounds. For ordinary terminal kinds
  (`page_id`, `visible_text`, element states), that evidence is `final_state`.
  For the Settings drill-down, `root_coverage_complete` means every required
  reachable root section was actually entered; blocked, device-unavailable, and
  entry-exempt sections are excluded.
- `root_pages_coverage` = mean over rounds of `root_pages_covered ÷ (expected −
  blocked)`. The walkthrough's `root_coverage` classifies each expected section
  (`reporting.classify_root_coverage`):
  - **entered** — its detail page was actually opened (a page record richer than
    the bare root-row label). This is what `root_pages_covered` counts.
  - **visible_only** — the row was seen on the scrolled root list but not entered
    (`record_visible_root_row_visits`). Counts as `missing` for coverage.
  - **blocked** — deliberately not entered for safety (e.g. Face ID, Wallet,
    flagged `unsafe_text` in `rejected_candidates`). `entry_exempt` and
    `device_unavailable` report entries are treated the same way. **Excluded
    from the denominator** so unreachable pages do not penalize coverage.
  - **missing** — not seen at all.

  So coverage measures **fraction of reachable sections actually entered**, not
  root-row visibility. Mode matters: the default walkthrough mostly produces
  `visible_only` (it scrolls the root and records visible rows — no per-section
  screenshot, per-visit text is just the label), while `run_full --drill-down`
  opens each section's detail page and saves a verifiable per-page screenshot
  (`IOS_SETTINGS_SAVE_VIEW_SNAPSHOTS`), turning rows into `entered`.
  `terminal_expected_state` can stay a separate, coarser end-state signal (for
  example, "ended at Settings root") or be set to `root_coverage_complete` when
  the task definition is exhaustive root coverage. `root_pages_coverage` is higher-is-better in
  `compare` (regression on a drop), like the success rates.

**Acceptance criteria:**

- `make`/CLI entrypoint runs the task set N times unattended and writes one
  schema-valid JSON per run.
- A `compare` step prints a per-metric delta between two run artifacts and exits
  non-zero on success-rate regression beyond a tolerance.
- Every later phase (P1/P2/P3) reports its before/after numbers from this
  harness; no reliability change merges without it.

### P1 — VLM grounding as a gated escalation (not blanket)

"VLM default" must **not** become blindly calling the VLM on every frame — that
adds cost and non-determinism without necessarily adding success. Define it as a
**gating contract**: OCR stays the cheap fast path, and the VLM is force-invoked
only on explicit triggers.

**Escalation triggers (any one forces a VLM grounding pass):**

1. OCR confidence for the target/scene is below threshold **or is missing** — an
   absent confidence must escalate, never be treated as high confidence.
2. The target is not found by OCR (find-by-description needed).
3. Scene classifiers conflict (disagree, low confidence, or hit a known
   false-positive pattern such as `is_ios_home_screen` on a detail page).
4. Verification returned `unknown`.

When no trigger fires, stay on OCR — the VLM is for disambiguation and grounding
(find-by-description, icon reading, set-of-marks), not routine reads. Cache via
`glassbox/obs/vlm_cache.py` so repeat screens are cheap.

**VLM budget (prevents escalation loops).** Triggers must be bounded, or
`unknown → VLM → still unknown → retry/strategy-switch → VLM …` will loop. Set a
**max VLM calls per action** (and per attempt); on exhaustion, stop escalating
and fall to the P2 strategy switch / recovery instead of calling the VLM again.
Record per action in the Step 0 schema: `vlm_calls`, `vlm_triggers` with
`last_vlm_trigger` (values: `low_confidence` | `confidence_missing` |
`target_missing` | `classifier_conflict` | `verify_unknown`), and
`vlm_budget_exhausted`.

**Acceptance criteria:**

- The four triggers are implemented and individually unit-tested (each forces a
  VLM call; absence of triggers does not).
- The per-action VLM budget is enforced and `vlm_budget_exhausted` is observable;
  a unit test proves `unknown → VLM → unknown` cannot loop past the budget.
- On the Step 0 harness, P1 raises `action_success_rate` and lowers
  `unknown_rate` versus the OCR-only baseline, with the **VLM-call count per task
  reported** (so cost is visible, not hidden).
- A VLM-disabled run still works (graceful degradation to OCR-only).

### P2 — Strategy ladder + expected-state verification

Generalize the hand-written `Phone.home()` fallback into a first-class
mechanism. **Define the data structure first**, then have the orchestrator
consume it — do not hard-code more per-method ladders inside the orchestrator.

Two layers: a **serializable spec** (goes in schema / audit / fixtures) and a
**runtime binding** that holds the callable. This mirrors `ActuationPlan` in
`glassbox/action/actuation.py`, whose `.metadata()` serializes the non-callable
parts for audit while the callable stays runtime-only.

```python
# --- Serializable specs (schema / audit / fixtures) ---

@dataclass(frozen=True)
class ExpectedState:
    kind: Literal["page_id", "visible_text", "element_appears", "element_gone"]
    payload: dict[str, Any]   # typed variants are fine instead of a raw dict
    # payload shape per kind:
    #   page_id         -> {"page_id": "settings/root"} or {"any_of": ["settings/root", ...]}
    #   visible_text    -> {"any_of": [...], "all_of": [...]}
    #   element_appears -> {"role": "...", "text": "...", "box": [x,y,w,h]?}
    #   element_gone    -> {"target_identity": {...}}   # needs the original target id
    # verified with a fresh frame; ties into screen-memory transitions

@dataclass(frozen=True)
class StrategySpec:
    name: str                # "keyboard_combo" | "assistive_touch_home" | ...
    capability: str | None   # gate against BackendCapabilities
    reliability_rank: int    # default-plan ordering + audit only; NOT runtime order
    params: dict[str, Any]   # serializable knobs (timings, coords, labels, ...)

@dataclass(frozen=True)
class SemanticActionSpec:
    op: str                          # "home" | "back" | "launch_app" | "tap" | "scroll"
    strategies: list[StrategySpec]   # runtime executes strictly in THIS order
    expected_state: ExpectedState
    recovery: str | None             # e.g. "recover_to_home_then_renavigate"
    idempotent: bool                 # safe to retry / re-enter

# --- Runtime binding (NOT serialized) ---

@dataclass(frozen=True)
class BoundStrategy:
    spec: StrategySpec
    call: Callable[..., ActionResult]    # bound from spec.name + spec.params at runtime

class SemanticActionPlan:                # runtime object
    spec: SemanticActionSpec
    bound: list[BoundStrategy]
    def metadata(self) -> dict: ...       # emits spec for audit, like ActuationPlan.metadata
```

The orchestrator (which already has audit, attempt groups, retry budgets,
landing observation, and memory path) runs the next eligible bound strategy
**strictly in `strategies` list order** (`reliability_rank` only seeds default
plans and audit, it is not the runtime sort), verifies against `expected_state`
with a fresh frame, and then transitions per the verifier outcome.

**Execution state machine (which verifier outcome takes which edge):**

Enumerate **every** outcome the runner can see; any unlisted outcome would
become an implicit, untracked fallback in v1.

| Verifier outcome | Edge |
| --- | --- |
| `succeeded` | done — return success |
| `failed` | **switch to next strategy**; if exhausted → `recovery` |
| `partial` | treat as `failed` by default (switch / recovery), or per action policy |
| `unknown` | escalate verification via VLM within the P1 budget; if still `unknown` → treat as `failed` |
| `no_after_scene` (no verifiable frame captured) | treat as `unknown` (re-observe / VLM within budget) |
| `transport_failed` | retry the **same** strategy within the transport retry budget; if exhausted → switch |
| `exception` | **terminate**; re-raise per the command-exception policy |
| `blocked` (safety / disqualifying state: SOS, power-off) | **terminate**, no retry / switch / recovery |
| `approval_required` | **terminate**, await human approval; no auto-switch / auto-recovery |

`recovery` (return to a known anchor + re-navigate) runs only after strategies
are exhausted, then the action is re-attempted once.

> **Recovery exception (reconciles invariant #4):** `blocked` and
> `approval_required` are the deliberate exceptions to "always have a universal
> recovery" — on a safety / high-risk disqualifying state we must **stop and
> surface**, never auto-recover or send more input.

- `Phone.home()` is the **reference implementation** of this ladder.
- Expected-state verification replaces generic `scene_progressed` where an
  expectation exists, which cuts `unknown` and catches silent no-ops.

**Acceptance criteria (phase 1 — incremental, not a big-bang rewrite):**

- `SemanticActionSpec` / `StrategySpec` / `ExpectedState` round-trip to/from JSON;
  the runtime `SemanticActionPlan` binds them to callables; ladder logic is
  unit-tested (switch-on-unmet, recovery-as-last, idempotency guard).
- Each of `home`, `back`, `launch_app`, `tap`, `scroll` has a **plan
  entrypoint**, and **no new bespoke fallback code is added** — any further
  recovery path must be a `StrategySpec`. `Phone.home()` may stay as the
  reference implementation; migrate it onto the plan runner only once the runner
  is stable, so we do not change too much at once.
- On the Step 0 harness, `unknown_rate` drops and `action_success_rate` rises
  for `back`/`launch_app`/`scroll` versus today, with `strategy_switches` and
  `recoveries` recorded per the schema.

### P3 — Stuck/loop detection → recover-to-anchor

This does **not** need a full planner. Reuse what exists today: the screen
signature (`glassbox/memory/signature.py`) and the orchestrator's attempt/action
groups.

- **Minimal trigger:** N consecutive steps with the **same screen signature** and
  the **same failure reason** → invoke `recover_to_home_then_renavigate`.
- Later: oscillation detection and treating a screen-memory transition mismatch
  as a strong failure signal.

**Acceptance criteria:**

- A unit test drives N identical (signature, failure-reason) steps and asserts
  recover-to-anchor fires exactly once at the threshold.
- On the Step 0 harness, injected dead-ends are recovered instead of looping;
  `recoveries` is recorded and task completion improves on those tasks.

### Later — efficiency

Only after the baseline is healthy: adaptive waits (replace fixed sleeps with
wait-for-stable / wait-for-expected — the reliability half of this is in the
rules above), VLM-call reduction (the P1 gating already bounds cost), and
parallelism.

> Note: **per-session auto-calibration is a reliability lever, not efficiency** —
> the fixed single-device linear fit causes mis-taps on other layouts/models. It
> is sequenced after P1–P3 only because the current rig is calibrated; treat it
> as reliability work, not a speed optimization.

## Regression / validation

- Gate every change on the Step 0 harness; require non-regression on success
  rate before merging.
- Keep the existing smoke/regression suites green (`uv run pytest skills/smoke`).
- Prefer live-rig validation for input-fidelity changes (the read-only Settings
  walkthrough is the canonical end-to-end check).

## Sequencing & status

The P-numbers are identity labels; the **execution order is Step 0 → P2 → P1 →
P3**:

1. **Step 0 — minimal success-rate harness** — _implemented._ The
   `skills.regression.computer_use_success_rate` CLI aggregates existing
   `actions.jsonl` / `attempt_groups.jsonl` / `audit.jsonl`, validates the
   schema, compares two benchmark artifacts, supports a task-manifest input for
   fixed multi-task benchmark sets, and can wrap the iOS Settings walkthrough
   for N rounds. It is exposed as
   `glassbox-computer-use-success-rate` and as
   `python -m skills.regression.computer_use_success_rate`; the repository
   `Makefile` exposes `computer-use-success-rate-ios-settings` as the
   unattended Settings benchmark wrapper.
   `task_completion_rate` is computed from task evidence satisfying
   `terminal_expected_state`; action success remains a separate primary-action
   metric. Metrics and compare output also include `vlm_calls`,
   `vlm_calls_per_task`, and VLM cache hit/miss metrics so P1 cost is visible.
   Validation checks top-level/task schema fields plus schema-critical
   action/attempt fields, including VLM trigger enums, VLM budget/cache
   counters, expected-state objects, source enums, final-state objects, and
   recomputed metrics.
2. **P2 — strategy ladder + expected-state verification** — _implemented
   foundation + orchestrator integration._ `SemanticActionSpec` /
   `StrategySpec` / `ExpectedState` round-trip as JSON; `SemanticActionPlan`
   binds runtime callables; the orchestrator can execute a semantic plan through
   the normal attempt/action artifact path; expected-state verification covers
   `page_id` (single `page_id` or `any_of` candidates), `visible_text`,
   `element_appears`, and `element_gone`. `tap_element` now routes through the
   semantic `tap` ladder when enabled while preserving element-specific actuation
   metadata in the target strategy. Settings row and search-root-result taps pass
   action-level `page_id` expected-state, so the success-rate harness can measure
   expected-state coverage on the real row-opening path. The Settings crawler
   disables semantic-plan global recovery for those row/search taps so a failed
   page open returns to crawler policy instead of launching a Home recovery inside
   the measured task. A 2026-06-06 iPad mini 7 snapshot (code `d9695ae`, artifact
   `/tmp/glassbox-l2-rank2-full-20260606-164702/benchmark.json`, command:
   `GLASSBOX_PHONE_MODEL=ipad_mini_7 ... run-ios-settings --rounds 5 --drill-down --language en --region HK`)
   produced 5 samples: 4 succeeded, 1 failed, `task_completion_rate=0.8`,
   `task_completion_variance=0.16`, `expected_state_coverage=0.976`,
   `root_pages_coverage=0.983`, and `recoveries=0`. The remaining failed sample
   missed `隐私与安全性`. A scrubbed copy is committed at
   `skills/regression/fixtures/l2_settings_expected_state_snapshot.json`; the
   offline regression smoke suite validates it and proves `compare_benchmarks`
   fails if its expected-state coverage drops to zero. It is a real L2 outcome
   snapshot, not yet a human-baselined acceptance result or the committed
   completion floor.
3. **P1 — VLM gated escalation** — _implemented foundation + expected-state
   runtime integration._ The
   `VLMEscalationGate` implements the four triggers, confidence-missing
   behavior, disabled graceful fallback, per-action/per-attempt budgets, and
   audit fields. Expected-state verification now routes ambiguous/failed states
   through the gate before switching semantic strategies.
4. **P3 — stuck/loop detection + recover-to-anchor** — _implemented minimal
   runtime hook._ `StuckLoopDetector` fires once after N identical
   `(screen_signature, failure_reason)` samples, and the orchestrator invokes
   the configured recovery policy when the threshold is reached.
5. Per-session auto-calibration (reliability) and efficiency work — _deferred._
