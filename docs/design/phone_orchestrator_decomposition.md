# Phone / ActionOrchestrator decomposition — design

Status: **design, not implemented; snapshot as of `a578f1d` (2026-06-11).**
Produced by a 7-agent design pass (3 structure mappers → 2 independent
decomposition proposals → adversarial review against this repo's refactor
rules); the reviewer verified ~40 line-level citations against source. This doc
records the **synthesized plan** (risk-first spine + the two cheapest
seam-first wins) and the rejected alternative. Owner of the refactor rules:
[`code_health_roadmap.md`](code_health_roadmap.md); owner of the "god class"
finding: [`../goals/project_health_snapshot.md`](../goals/project_health_snapshot.md)
item 5.

Line numbers below are snapshots — regenerate before citing:

```bash
wc -l glassbox/phone.py glassbox/action/orchestrator.py
grep -c "def " glassbox/phone.py glassbox/action/orchestrator.py
```

## 1. What the maps found (measured, not assumed)

**Phone (`glassbox/phone.py`, ~2211 lines / 229 defs)** is already ~60-65%
one-line delegation to the 9 collaborators built in `_init_collaborators`
(`phone.py:447-456`). The bloat decomposes into four kinds:

1. **A back-compat twin layer**: ~32 same-name private/public method pairs +
   16 property getter/setter pairs mirroring `ActionContext`
   (`glassbox/action/context.py`). Kept alive almost exclusively by
   skills/smoke tests (~171 private-member references across 14 files;
   `test_computer_use_runtime.py` alone monkeypatches `phone._execute_action`
   41×); **zero** private access from `glassbox/` core outside
   `boundaries.py`'s transitional getattr shims.
2. **Constructor/config plumbing** (~390 lines), constructed only at
   `runtime.py`'s single build site.
3. **Three blocks of real logic stranded in the facade**: semantic tap
   orchestration (~190 lines, wires ElementSelector→TargetPlanner→ActionRunner
   plus the `_in_semantic_plan` ladder guard), the PicoKVM fresh-verify /
   back-guard block (~140 lines — `_picokvm_back_context` perceives on the
   recovery path; consumers are `glassbox/action/semantic_plan.py` (getattr)
   and `glassbox/system_navigator.py` (direct)), and effector-capability
   plumbing (~50 lines).
4. Thin delegation for the rest.

The real contract problem: `ActionHost` (`boundaries.py`) declares 8 members,
but collaborators actually consume ~45 distinct Phone members, collaborators
call **each other through phone**, and the orchestrator duck-types ~20 members
via `getattr` — so renames silently no-op instead of failing.

**ActionOrchestrator (`glassbox/action/orchestrator.py`, ~3784 lines)**
clusters into: attempt loop, semantic strategy ladder, recovery/stuck
dispatch, landing observation, verification dispatch, and ledger/audit
emission (41 `store.audit.append` sites). The dangerous couplings are
load-bearing and deliberate: VLM budget metadata dicts are mutated **in
place** and carried across retries (CUQ-0.7); the `_open_groups` lifecycle has
finalize-then-re-raise exception ordering; the `landing_missed` string is a
wire sentinel. Any extraction that copies a dict, reorders an emission, or
"cleans up" a sentinel changes behavior invisibly to the current test suite —
which is why **characterization comes first**.

## 2. The plan (B-spine: instruments first, verbatim moves, cold periphery only)

Each step is an independently mergeable, revertable PR; `make check` green +
committed floor non-regressed at every step. Timing-adjacent steps do not
count as done until the rig session (step 7) passes.

1. **Pin the implicit contracts (tests only, no production code).**
   Ledger-golden characterization: drive the orchestrator with scripted mock
   phones through a scenario matrix (legacy transport retry, idempotent-budget
   retry, ladder switch + recovery, stuck recover/rearm, landing-miss retry,
   VLM budget exhaustion across retries, **exception-interrupt finalization**)
   and snapshot the full ordered audit event stream. Plus (merged from the
   seam-first proposal): `picokvm_fresh_verify_kwargs` dict-equality oracle
   and explicit duck-typed-name pins. **Hard gate: these tests must pass
   against unmodified main before any production PR merges.**
2. **Formalize the duck-typed surface (typing + allow-list, no runtime
   change).** Split `ActionHost` into measured host facets
   (Perception/Actuation/State + an OrchestratorHost for the ~25
   orchestrator-consumed members); add a **generated** symbol-level
   getattr-existence allow-list test (embed the generator command per
   AGENTS.md doc discipline).
3. **Extract AuditEmitter / ledger payload assembly** (group lifecycle stays
   in the orchestrator). Validation: the step-1 ledger-golden byte-diff must
   be empty across the whole matrix.
4. **Move the ~10 pure landing/diff math statics verbatim** to
   `glassbox/action/landing.py` (the orchestration methods stay).
5. **Extract stuck-loop + preflight dispatch into a RecoveryCoordinator**
   (policy and guards stay put; same `recovery_policy` instance).
6. **Deduplicate `_reopen_source_for_fresh_capture`** — `phone.py` and
   `orchestrator.py` carry two hand-maintained copies of the same
   close/sleep(0.05)/open dance; extract one shared function, byte-identical
   body.
7. **One batched rig A/B closing steps 4-6 — on BOTH devices** (iPad mini 7 +
   iPhone, per `code_health_roadmap.md` §0.3 as written). This session also
   pays the roadmap's recorded outstanding P1/P2 live-refactor gate — one
   session, two debts.
8. *(then, offline)* **Delete the Phone twin layer** — migrate skills tests
   off private twins first, one cluster per PR, with a grep-guard against
   regrowth. Regenerate the reference counts in each PR description (the
   draft's "127 refs" did not reproduce; a fresh sweep found ~171 raw matches).
9. *(then, offline)* **Extract SemanticTapper** (the facade's semantic tap
   block) as a 10th collaborator.

Net effect: orchestrator sheds ~900-1000 lines with every rig-validated
decision path byte-identical; Phone sheds the twin layer and one real-logic
block, with the end-state facade cleanup deferred to a phase 2.

## 3. Invariants (verbatim from the review; violating any = behavior change)

- Audit-ledger wire contract byte-identical: event names, payload keys,
  **emission order**, across all 41 sites.
- VLM budget/audit metadata dicts keep **object identity** (mutated in place,
  carried across retries by `_carry_vlm_retry_metadata` — no extracted class
  may copy the dict).
- `landing_missed` stays a string sentinel with that exact value.
- `getattr(phone, "in_semantic_plan")` reads stay at their decision points;
  the set/restore in `ActionRunner.run_semantic_plan` and the `phone.py`
  recursion guard are untouched.
- `_open_groups` lifecycle and finalize-then-re-raise ordering stay in the
  orchestrator's execute paths.
- All sleeps and deadline math keep identical values and relative order.
- `actuation_profile` remains a single shared instance with preserved
  write-then-read order.
- No behavior fork (no `use_new_split` flag); extractions replace code paths,
  never duplicate them.
- Duck-typed getattr fallbacks preserved as-is (test stubs depend on them);
  renames guarded by the allow-list test.
- Platform neutrality holds (`test_platform_neutral_imports.py` stays green).

## 4. Rejected alternative (recorded, not abandoned)

The seam-first proposal's back half — extracting observation capture, the
semantic strategy ladder, and verification dispatch into their own classes —
was rejected **for this phase** by the adversarial review: those moves are
hot-core surgery on rig-validated paths whose only proposed oracle was a
2-scenario golden, violating the roadmap's characterize-first and scope
disciplines. They become eligible after the step-1 goldens have soaked and
step 7's two-device baseline exists. The PicoKVM back-guard move into
SystemNavigator is deferred until an iPhone rig slot exists (the moved code
perceives inside recovery and earns its keep on the iPhone).
