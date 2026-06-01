# Log-sim replay & regression harness (Tiers A + B + C)

Status: **Tier A implemented** (2026-06-01, branch `feat/tier-a-verifier-golden-replay`;
negative-control verified). Tiers B / C / UTG-sim remain design-only and are
deferred per the necessity review (see §9 + `MEMORY: log-sim-replay-design`). Date: 2026-06-01.

Turn the `artifacts/` corpus (run ledgers + recordings) into deterministic,
offline regression tests by **replaying recorded observations back through the
real pipeline** at three increasing depths. Each tier replays a different slice
of the perceive → decide → act → verify loop, has its own determinism budget,
and its own CI gate semantics.

This doc is grounded in the actual code: every reused symbol below was read at
the cited `file:line` and is tagged **REAL**; everything to be written is tagged
**NEW**. The spine — pairing a recorded frame with its recorded `Scene` — was
verified against a live recording (`scene` events carry `snapshot_seq`).

---

## 1. Goal & non-goals

**Goal.** A `make`-driven, device-free regression suite that re-runs real
captured data and fails when behavior regresses, without flaking on the parts of
the system that are legitimately non-deterministic.

**Non-goals.**
- Reproducing the *planner/agent trajectory*. LLM/agent prompts and responses
  are never persisted (confirmed: `recorder.py` / `artifacts.py` store only VLM
  *metadata*, never prompt/response). Tier C therefore validates the
  *mechanical* decision layer, not the planner's choices.
- Bit-exact wall-clock timing. Deadline loops branch on `time.monotonic()` at
  many core sites; we deliberately do **not** thread a clock seam through
  production code in v1 (see Tier C / open risks).
- **Interactive / off-trajectory simulation.** All three tiers here are *on-rails*
  replay-for-regression: the next frame is fixed by the recording, so the agent
  cannot act into an un-recorded state. A genuine `step(state, action) → state'`
  simulator is a separate concern — the learned **UTG**, documented in
  `docs/design/utg_operable_sim.md` (which calls itself replay "mode 3": modes 1
  = read-only inspection, 2 = these on-rails tiers, 3 = the operable UTG sim).

---

## 2. What we are replaying (verified seams)

| Seam | Reality | Implication |
|---|---|---|
| `FrameSource` Protocol | `boundaries.py:58` — `snapshot()->Frame`, `close()`, props `resolution/fps/coordinate_space`. Impls: `AVFFrameSource`, `StaticFrameSource`, `PicoKVMFrameSource`. **No** replay source exists. | A `RecordingFrameSource` (NEW) is the single clean injection point; pure DI on `phone.source`. |
| Frame↔Scene pairing | **REAL & verified in a live recording**: `scene` event carries `snapshot_seq`; `snapshot` event carries `seq` + `frame_file`. e.g. scene `seq=2` → `snapshot_seq=1`. | A recorded frame can be deterministically paired with its recorded `Scene`. |
| Perception | `Perceptor.perceive()` is a pure function of the frame (OCR + heuristic typing); VLM (Layer 3) is a *separate* `phone.describe()` call. | Frame-level replay re-derives the `Scene` deterministically (modulo OCR engine drift). |
| Action/verify | Orchestrator decides from `Scene` observations only; verifiers compare before/after `Scene`s; no live device read except fresh-frame verify. | Verifier replay is fully pure; closed-loop replay needs only frames + cached VLM + the two un-pure decision sources logged. |
| Golden loader | `iter_golden_cases(root)` = `sorted(Path(root).glob("*.json"))` — **non-recursive** (`golden.py:60`). | A `_harvested/` subdir is its own corpus, invisible to the hand-curated root's glob. |

The existing offline gate (`make check` → `regression-gate`) operates only at
the **metrics/ledger** level (validates `reliability_baseline.json`, runs
`compare_benchmarks`). It does **not** replay the pipeline. These tiers add the
missing replay layer beneath it.

---

## 3. Three-tier model & gate semantics

| Tier | Replays | Re-runs | CI gate | Anti-trap floor |
|---|---|---|---|---|
| **A** — verifier golden | ledger scene **texts** | `verifier.verify()` | **hard** (rides `make test`) + `golden-audit` drift check in `make check` | non-empty + verifier-coverage **floor test** |
| **B** — perception | recorded **PNGs** | `Perceptor.perceive()` | **tolerant**; `skip` if OmniParser/`.env` backend absent | recording-fixture non-empty floor |
| **C** — closed loop | frames + cached VLM | `ActionOrchestrator` | **advisory**; hard only on a curated `deterministic=True` set | fail-loud on VLM cache miss / missing decision log |

**The honest-gate trap (must avoid).** `make check`'s gate can be green while
never comparing, and a failed floor with `task_completion=0.0` cannot regress
(see `MEMORY: honest-gate-first`). A parametrized replay over an **empty**
corpus emits **zero** pytest items and stays green — vacuously. So every tier
ships with a **non-emptiness + coverage floor test** that fails when the corpus
is empty/zeroed. The floor is the load-bearing CI-honesty mechanism, not the
parametrized replay itself.

---

## 4. Tier A — verifier golden replay (ships first)

> **Status: IMPLEMENTED.** `skills/regression/golden_ingest.py` +
> `skills/smoke/test_golden_ingest.py` + `skills/golden/computer_use/_harvested/`
> (30 self-consistent cases) + `make golden-harvest` / `golden-audit`. A
> harvest-time **self-consistency filter** drops text-irreproducible candidates
> (38 → 30); `metadata.verifier` is pinned so replay resolves the exact verifier
> that ran. Negative control confirmed teeth: perturbing a verifier threshold
> reddens the replay. `golden-audit` no-ops in CI (artifacts/ gitignored), so the
> committed corpus + replay/floor tests are the real guard there.

Re-run real captured `(before_texts, action, after_texts) → expected_status`
through the verifier registry. 100% deterministic: no device, no VLM, no OCR
(scene texts are already serialized). Reuses the existing golden harness verbatim.

### Reused (REAL)
- `glassbox/verification/probe_ingest.py` — `load_actions(run_dir)` (`:10`),
  `golden_case_from_action(run_dir, action)` (`:19`), `write_golden_case(path, payload)` (`:43`).
- `glassbox/verification/golden.py` — `VerifierGoldenCase` (`:16`) with fields
  `{case_id, action, expected_status, before_texts, after_texts, metadata,
  expected_disqualifying_state}`; `.verifier_input()` (`:38`) already builds a
  full `VerifierInput` from texts; `iter_golden_cases(root)` (`:60`).
- `glassbox/verification/registry.py` — `VerifierRegistry().resolve(op)` → verifier
  with `.verify(VerifierInput) -> SemanticOutcome` (pattern confirmed at
  `test_computer_use_verifiers.py:100-103`). **Note:** `resolve()` takes the op
  string only; metadata rides inside `VerifierInput.action`.

### New
- `skills/regression/golden_ingest.py` **(NEW)** — batch CLI.
- `skills/smoke/test_golden_ingest.py` **(NEW)** — replay + floor + idempotence.
- `skills/golden/computer_use/_harvested/*.json` **(NEW corpus)** — machine-harvested,
  in its **own** dir so it never co-mingles with the 23 hand-curated cases.

```python
# skills/regression/golden_ingest.py  (NEW)
from glassbox.verification.probe_ingest import (        # all REAL
    load_actions, golden_case_from_action, write_golden_case,
)

def case_fingerprint(case: dict) -> str:
    # dedup on load-bearing fields ONLY (exactly what VerifierGoldenCase reads)
    key = {k: case.get(k) for k in (
        "verifier", "action", "expected_status",
        "before_texts", "after_texts", "expected_disqualifying_state")}
    blob = json.dumps(key, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:16]        # content-addressed → idempotent re-ingest

def harvest_run_dir(run_dir: Path) -> list[dict]:
    return [
        golden_case_from_action(run_dir, a)
        for a in load_actions(run_dir)
        if (a.get("semantic") or {}).get("verifier")
        and not (a.get("semantic") or {}).get("verification_skipped")
    ]

def harvest(roots, out_dir, *, only_deterministic=True) -> "HarvestReport":
    # walk run_*/ dirs with actions.jsonl; dedup by fingerprint;
    # split by semantic.deterministic → out_dir vs out_dir.parent/_harvested_nondet
    # filename = f"{verifier}__{fp}.json"; write via write_golden_case (idempotent)
    ...

def audit(roots, against) -> int:
    # re-harvest into a temp dir; rc!=0 if the committed corpus differs (uncommitted drift)
    ...
```

```python
# skills/smoke/test_golden_ingest.py  (NEW)
from glassbox.verification.golden import iter_golden_cases
from glassbox.verification.registry import VerifierRegistry

HARVESTED_ROOT = "skills/golden/computer_use/_harvested"

@pytest.mark.smoke
@pytest.mark.parametrize("case", iter_golden_cases(HARVESTED_ROOT),
                         ids=lambda c: c.case_id)
def test_harvested_verifier_golden_cases(case):
    outcome = VerifierRegistry().resolve(case.action).verify(case.verifier_input())  # REAL
    assert outcome.status == case.expected_status
    if case.expected_disqualifying_state:
        assert outcome.disqualifying_state == case.expected_disqualifying_state

@pytest.mark.smoke
def test_harvested_corpus_nonempty_and_covers_core_verifiers():   # *** ANTI-TRAP FLOOR ***
    cases = iter_golden_cases(HARVESTED_ROOT)
    assert len(cases) >= 1                          # empty parametrize = vacuously green
    assert {"scene_progressed"} <= {c.action for c in cases}   # extend allow-list as corpus grows

@pytest.mark.smoke
def test_harvest_idempotent(tmp_path):              # snapshot-with-commit, no hand-counted numbers
    from skills.regression.golden_ingest import harvest
    harvest([Path("artifacts")], tmp_path, only_deterministic=True)
    assert {p.name for p in tmp_path.glob("*.json")} \
        <= {p.name for p in Path(HARVESTED_ROOT).glob("*.json")}
```

```makefile
GOLDEN := uv run python -m skills.regression.golden_ingest
golden-harvest: ; $(GOLDEN) harvest --roots artifacts \
                    --out skills/golden/computer_use/_harvested --only-deterministic
golden-audit:   ; $(GOLDEN) audit --roots artifacts \
                    --against skills/golden/computer_use/_harvested   # rc!=0 on uncommitted drift
check: lint test regression-gate golden-audit        # replay itself already rides `make test`
```

**A catches:** verifier-logic + registry-routing regressions on real captured
scenes. **A cannot catch:** OCR/perception, coordinate/letterbox, control-loop —
it consumes scene *texts*, not pixels. Non-deterministic verifiers
(`semantic.deterministic=False`: lock/permission/crash/VLM-gated) route to
`_harvested_nondet/` and stay **off** the strict floor, so a legitimate VLM-path
change can't redden CI.

---

## 5. Tier B — frame-level perception replay (tolerant)

Feed recorded PNGs through the real `Perceptor.perceive()` and assert the
reconstructed `Scene` matches the recorded one within tolerance. Catches
perception/classifier/letterbox regressions.

### New files
- `glassbox/perception/recording_source.py` **(NEW)** — `RecordingFrameSource`.
- `glassbox/perception/replay_assert.py` **(NEW)** — `SceneTolerance` + `compare_scenes`.
- `skills/golden/recordings/<run_id>/` **(NEW corpus)** — 2-3 small trimmed recordings.
- `skills/smoke/test_perception_replay.py` **(NEW)**.

```python
# glassbox/perception/recording_source.py  (NEW) — satisfies FrameSource Protocol (boundaries.py:58)
from glassbox.perception.source import Frame, FrameContext               # REAL (source.py:77/38)
from glassbox.obs.recorder import iter_events                            # REAL (recorder.py:333)
from glassbox.memory.recording import (                                  # all REAL
    _snapshot_frames, _load_frame_img, _scene_from_event,                #   :144 / :160 / :28
)

class RecordingFrameSource:
    coordinate_space = "frame_px"                       # matches PicoKVM/AVF
    def __init__(self, run_dir, *, fps: float = 60.0):
        events = list(iter_events(run_dir))             # REAL
        self._frames = _snapshot_frames(Path(run_dir), events)   # {snapshot seq -> png Path}  REAL
        self._order  = [e["seq"] for e in events if e.get("type") == "snapshot"]
        # pair each recorded observe-Scene with its frame via the REAL snapshot_seq link:
        self._scene_by_seq = {
            e["snapshot_seq"]: _scene_from_event(e)
            for e in events
            if e.get("type") == "scene" and e.get("scene_event") == "observe"
        }
        self._i, self._fps = 0, fps

    def snapshot(self) -> Frame:                        # Protocol method
        seq = self._order[min(self._i, len(self._order) - 1)]
        img = _load_frame_img(self._frames[seq])        # REAL
        if img is None:
            raise RuntimeError(f"no png for snapshot seq {seq}")
        return Frame(img=img, ts=self._i / self._fps, context=FrameContext())  # deterministic ts

    def fresh_snapshot(self) -> Frame:                  # replay alias (no live device)
        return self.snapshot()
    def advance(self) -> bool: ...                      # mirror StaticFrameSource.advance (static.py:75)
    @property
    def resolution(self): ...                           # (w,h) from first Frame.shape
    @property
    def fps(self) -> float: return self._fps
    def close(self) -> None: self._frames.clear()
```

> **Naming — not the same class as the UTG sim's frame accessor.** This Tier-B
> `RecordingFrameSource` is a *sequential* `FrameSource` (`snapshot()`/`advance()`,
> Protocol-conforming, for on-rails replay). The operable UTG sim
> (`docs/design/utg_operable_sim.md`) needs a *node-indexed random-access* accessor
> (`frame_for_node(node_id)`), named `UTGFrameAccessor` there to avoid collision.
> Both wrap the same recording and share the REAL `_snapshot_frames` /
> `_load_frame_img` helpers, but expose different surfaces — keep them distinct.

### Wiring (mirror `static`, verified extension points)
```python
# glassbox/config.py: add next to frame_dir (:64). Auto-binds GLASSBOX_REPLAY_DIR (env_prefix="GLASSBOX_" @ :45)
replay_dir: str | None = None

# glassbox/backend_registry.py
def select_frame_source_backend(cfg) -> str:            # extend :123
    if cfg.picokvm:    return "picokvm_stream"
    if cfg.replay_dir: return "replay"                  # NEW — before frame_dir, mutually exclusive
    return "static" if cfg.frame_dir else "avf"

def _replay_frame_source_factory(*, cfg):               # mirror _static_frame_source_factory (:94)
    if not cfg.replay_dir:
        raise ValueError("replay FrameSource requires GLASSBOX_REPLAY_DIR")
    from glassbox.perception.recording_source import RecordingFrameSource
    return RecordingFrameSource(cfg.replay_dir)

def replay_frame_source_registration() -> BackendRegistration:   # add to DEFAULT_FRAME_SOURCE_REGISTRY (:240)
    return BackendRegistration(name="replay", factory=_replay_frame_source_factory)
```
No `Phone`/`Perceptor`/`Orchestrator` edits — pure DI on `phone.source`.

```python
# glassbox/perception/replay_assert.py  (NEW)
@dataclass
class SceneTolerance:                    # defaults are SEEDS — tune vs the real corpus before hard-gating
    page_id_must_match: bool = True      # verifier-relevant → hard
    scene_type_must_match: bool = True   # hard
    text_jaccard_min: float = 0.85       # set similarity over element texts; NOT order/exact
    element_count_delta_max: int = 2
    box_iou_min: float = 0.6             # per matched-text element

def compare_scenes(recorded: Scene, replayed: Scene, tol) -> "SceneMatchReport":
    # reuse compute_scene_diff (verification/diff.py:96, REAL) for texts_added/removed;
    # hard-fail on page_id/scene_type; tolerant on text jaccard / count / box IoU
    ...
```

**Cache hazard (the subtle one).** `phone.perceive_cache_diff = 0.005`
(`phone.py`) skips OCR when consecutive frames are near-identical and returns the
*cached* `Scene` — which would desync the per-scene assertion cursor. Tier-B
replay **must disable** this cache by **reusing the existing field**: set
`perceive_cache_diff = -1.0` in the replay cfg so `mean_absdiff < threshold` is
never true → one OCR per `advance()`. No new production flag (decision ③).

```python
# skills/smoke/test_perception_replay.py  (NEW)
@pytest.mark.smoke
@pytest.mark.parametrize("rec_dir", sorted(Path("skills/golden/recordings").iterdir()),
                         ids=lambda p: p.name)
def test_recorded_scene_reconstructs_within_tolerance(rec_dir):
    if not _omniparser_available():
        pytest.skip("perception backend (.env-gated) absent")     # skip, don't flake
    src = RecordingFrameSource(rec_dir)
    phone = build_phone(source=src, cfg=_replay_cfg(disable_perceive_cache=True))
    for seq, recorded in src._scene_by_seq.items():
        report = compare_scenes(recorded, phone.perceive(), SceneTolerance())
        assert report.ok, report.explain()
        src.advance()

@pytest.mark.smoke
def test_recording_fixture_corpus_nonempty():       # floor
    assert any(Path("skills/golden/recordings").iterdir())
```

Start with `xfail(strict=False)` on `box_iou` (geometry) and hard-assert only
text-set / `page_id` / `scene_type` until OCR stability is characterized on CI
hardware. **B catches:** OCR/OmniParser/classifier drift, letterbox/app-viewport
transform bugs, frame-cache drop/dup. **B cannot catch:** verifier semantics,
decisions, timing; a small genuine OCR regression *inside* tolerance is invisible.

---

## 6. Tier C — closed-loop drift simulator (advisory, incremental)

**Stated plainly.** Agent prompts+responses are never logged; VLM is
live-unless-cached; fresh-frame verify reads the live device
(`action_runner.py`); deadline loops branch on `time.monotonic()` at many sites
(`orchestrator.py`, `action_runner.py`, `element_selector.py`, `ai.py`). So
Tier C is a **drift detector, not a regression oracle**, and ships **advisory**
until a curated deterministic-replay set exists.

**The leverage point.** The mechanical decision tree (`_retry_kind`,
`_advance_after_semantic_attempt`, stuck-detection dhash, seq IDs) is a *pure
function of `semantic.status` (+ `disqualifying_state`)*. So **if Tier C pins the
verifier outcomes, most of the decision layer re-derives for free.** Only two
sources are genuinely un-logged and must be added.

### Three additions, each gated and incremental

1. **VLM determinism — reuse the REAL cache + a strict subclass.** Wrap with
   `wrap_vlm_cache_if_enabled(inner, enabled=True, cache_dir=...)`
   (`obs/vlm_cache.py`). Add `StrictCachedVLM(CachedVLM)` **(NEW)** raising on
   miss (`GLASSBOX_REPLAY_VLM_STRICT=1`) so no live call leaks.
   *Sharp edge (decision ①):* the live cache key is `sha256(frame_bytes +
   request_shape)`; replayed frame bytes pass through letterbox/viewport and may
   not equal the live-hashed bytes → key miss. **Resolution:** in replay mode look
   up by **call identity** (`snapshot_seq` + `request_shape`, i.e. the Nth VLM
   call of this run), not by content hash — deliberately immune to perception
   drift (Tier B's job). A miss is **reported as divergence**, not a hard fail.
   Needs a small "replay lookup mode" on `CachedVLM`.

2. **Checkpoint engine** **(NEW, `glassbox/replay/checkpoint.py`).** At each
   replayed step, hard-assert the stable fields, tolerate the noisy ones:
   - re-run `registry.resolve(op).verify(...)` → `status == recorded semantic.status` (HARD; reuses Tier A)
   - `page_id == recorded after.scene.page_id` (HARD)
   - `observation.screen_signature` match — **REAL field** (`actions.jsonl` →
     `observation/screen_signature`, dhash) (HARD)
   - `scene_diff` texts ⊆ recorded `diff_summary.scene` (TOLERANT)

3. **Decision log — the one genuinely missing artifact (default OFF).**
   ```python
   # glassbox/obs/decision_log.py  (NEW) — mirrors Recorder jsonl-append; GLASSBOX_DECISION_LOG=1
   # logs BRANCH OUTCOMES only, never prompts/responses (large + privacy; keys live in a private monorepo):
   {"attempt_id", "kind", "value", "inputs"}
   #   kind ∈ {retry, strategy_advance, selector_resolution, stream_match_index}
   def iter_decisions(run_dir): ...        # like iter_events
   ```
   Wire `record(...)` at `ElementSelector.expect_text` (which fallback won) and
   `_observe_after_stream_until_match` (which frame index matched) — the only two
   true divergence sources beyond the already-pure decisions.

4. **Clock — DEFER the invasive seam.**
   - **Phase 1 (ships now):** pytest-fixture `monkeypatch` of `time.monotonic`
     (a `ReplayClock` advancing a fixed `step_ms` per poll). Zero production
     edits.
   - **Phase 2 (only if Phase 1 proves value):** a real `_now()` seam behind
     `GLASSBOX_REPLAY_CLOCK=1`. Big-bang; risks altering live behavior. Do not
     build speculatively (`MEMORY: honest-gate-first`).

```python
# skills/regression/closed_loop_replay.py  (NEW)
def replay_run(run_dir, *, fail_on_vlm_miss=True, frame_interval_ms=250) -> "ReplayDivergenceReport":
    cfg = get_config().model_copy(update={"replay_dir": str(run_dir)})
    phone = build_phone(source=make_source(cfg=cfg), cfg=cfg,
                        kimi=wrap_vlm_cache_if_enabled(inner, enabled=True, cache_dir=run_dir/"vlm_cache"))
    # observation_producer_mode='scoped_source_owner' (orchestrator owns source) — simpler, REAL default
    # drive recorded actions.jsonl through ActionOrchestrator; classify each divergence:
    #   (a) perception-drift (Tier B would also flag)
    #   (b) timing-drift (frame-count variance — EXPECTED, reported not failed)
    #   (c) genuine decision regression  ← the ONLY kind we hard-gate, only on the deterministic set
    ...
```

```python
# skills/smoke/test_closed_loop_replay.py  (NEW)
@pytest.mark.parametrize("run_dir", _frozen_recordings())
def test_closed_loop_drift(run_dir, monkeypatch):
    if not _has_decisions_and_cache(run_dir):
        pytest.skip("no decisions.jsonl / vlm_cache → not replayable")
    monkeypatch.setattr("time.monotonic", ReplayClock(step_ms=250).monotonic)   # Phase-1 test-only
    rep = replay_run(run_dir, fail_on_vlm_miss=True)
    assert rep.pure_decision_divergences == [], rep.render()    # HARD: pure fns must match
    # rep.timing_divergences → reported, NOT failed (advisory)
```

```makefile
closed-loop-replay: ; GLASSBOX_REPLAY_VLM_STRICT=1 \
   uv run python -m skills.regression.closed_loop_replay replay --run-dir $(RUN_DIR)   # advisory; rc=0 unless --strict
# Fold the HARD pure-decision assertion into `make check` ONLY over the curated
# deterministic set, and ONLY once decision-logging has landed.
```

**C catches (with cache + decision log):** strategy-ladder / retry / skip /
stuck-recovery regressions (same recorded inputs → different branch). **C cannot
guarantee:** un-logged agent op-choices (planner trajectory), exact loop-exit
timing without Phase-2 clock, uncached VLM paths (fail-loud). Mirrors
`MEMORY: reliability-machinery — don't read 0.955 as task success`.

---

## 7. Config flags (all auto-bound via `env_prefix="GLASSBOX_"`, config.py:45)

| Flag | Tier | Effect |
|---|---|---|
| `GLASSBOX_REPLAY_DIR` (`cfg.replay_dir`) | B, C | select `RecordingFrameSource` |
| `GLASSBOX_VLM_CACHE_DIR` *(existing)* | C | deterministic VLM via disk cache |
| `GLASSBOX_REPLAY_VLM_STRICT` | C | raise on cache miss (no live leak) |
| `GLASSBOX_DECISION_LOG` | C | opt-in decision sidecar (default off) |
| `GLASSBOX_REPLAY_CLOCK` | C | Phase-2 production clock seam (not v1) |

---

## 8. Phased rollout

1. **A.1** `golden_ingest.py` + harvest the existing `artifacts/run_*` →
   `_harvested/` (default `--only-deterministic`, decision ⑤); wire
   `test_golden_ingest.py` + floor into `make test`; add `golden-audit` to
   `make check`. *No runtime code touched.*
2. **B.0** OCR/perception determinism characterization (decision ②): throwaway
   script, `perceive()` N× on the same recorded PNG across the real backends;
   derive `SceneTolerance` from measured p99 jitter. *Throwaway, not committed.*
3. **B.1** `RecordingFrameSource` + registry/config wiring + `replay_assert.py`;
   commit 1–2 trimmed recordings (≤8 decision-point frames each, cap ~10MB,
   decision ④); land with `box_iou` as `xfail`, text/`page_id` hard; flip geometry
   to hard once B.0's measured tolerances hold.
4. **C.1** `StrictCachedVLM` + checkpoint engine + `closed_loop_replay.py`,
   advisory, Phase-1 monkeypatch clock, over recordings that already have a VLM
   cache. Use the replay call-identity cache lookup (decision ①).
5. **C.2** `decision_log.py` + the two `record(...)` call sites; backfill is not
   possible for legacy runs (auto-skip). Only now consider a hard gate over the
   curated deterministic set.
6. **C.3 (optional)** Phase-2 `_now()` clock seam — only if C.1/C.2 proved value.

---

## 9. Decisions & recommended resolutions

Recorded 2026-06-01. Only **⑤** must be settled before Tier A ships; it is
decided here and reflected in the `golden-harvest` make target
(`--only-deterministic`). The rest are deferred to the tier that needs them, but
the recommended resolution is fixed now so implementation doesn't re-litigate.

| # | Decision | Recommended resolution | When |
|---|---|---|---|
| ① | VLM cache-key brittleness | **Replay looks up by call identity, not content hash** — key on `snapshot_seq` + `request_shape` (or "Nth VLM call of this run"), not `sha256(frame_bytes)`. Sidesteps byte-equality after letterbox/viewport churn. Deliberately immune to perception drift (that's Tier B's job). Cache miss → **report as divergence**, don't hard-fail, at first. Needs a small "replay lookup mode" on `CachedVLM`. | Tier C |
| ② | OCR/OmniParser determinism assumed, not measured | **Add a throwaway B.0 characterization step**: run `perceive()` N× on the same recorded PNG across the real backends, measure text-jaccard / box-IoU / element-count spread; set `SceneTolerance` to p99 + margin (replace the 0.85/0.6/2 seeds). **Layer by engine**: Apple Vision OCR is on-device + OS-pinned → hard-gate text/`page_id`; OmniParser (YOLO, `.env`-gated/AGPL) → tolerant/`xfail`, `skip` when backend absent. | before Tier B (B.0) |
| ③ | `perceive_cache_diff` disable | **No new production flag.** Reuse the existing `perceive_cache_diff` field, set it to `-1.0` in the replay cfg so `mean_absdiff < threshold` is never true → one OCR per `advance()`. Confirm the comparison operator at impl time (`-1.0` is safe for both `<` and `<=`). | Tier B |
| ④ | Fixture corpus weight | Tier A `_harvested/*.json` (text only, tiny) → **commit freely**. Tier B recordings: 1080p PNG ≈ 600KB/frame → **1–2 recordings, decision-point frames only (≤8 each), hard cap ~10MB**, go git-LFS above that; **never downscale** (changes OCR). VLM caches are small JSON → commit only for the curated deterministic Tier-C set. `decisions.jsonl` tiny → commit. | Tier B/C |
| ⑤ | Non-deterministic verifiers | **DECIDED.** Strict floor = `semantic.deterministic=True` only. `deterministic=False` (lock/permission/crash/VLM-gated) auto-routes to `_harvested_nondet/`, collected but **non-gating** (reported / `xfail-strict=False`). `--only-deterministic` is the harvest **default**. Mirrors `MEMORY: don't read 0.955 as task success`. | now |
| ⑥ | Branch protection | **Enable branch protection on `main` + make `make check` a required status check.** Until then every gate is advisory-in-practice no matter how "hard" the assertion (`main` is unprotected per `MEMORY`). Low effort, high leverage, but a repo/org-settings call — owner decides. | org, ASAP |

---

## 10. Net new surface (deliberately small)

`golden_ingest.py` (A) · `recording_source.py` + `replay_assert.py` + registry/
config wiring (B) · `decision_log.py` + `checkpoint.py` + `closed_loop_replay.py`
+ `StrictCachedVLM` (C) · 3 smoke tests + 2 committed fixture corpora. Tier A adds
**zero** runtime surface; everything below `phone.source` stays untouched except
the one-line registry extension.

---

## Appendix — verified API ground-truth (read at `file:line`)

- `boundaries.py:58` — `FrameSource` Protocol (`snapshot`, `close`, `resolution`, `fps`, `coordinate_space`).
- `perception/source.py:77` — `Frame(img, ts, context)`; `:38` `FrameContext`; `:157` `AVFFrameSource`.
- `perception/static.py:32` — `StaticFrameSource(source)`; `:56` `snapshot`; `:75` `advance`.
- `obs/recorder.py:333` — `iter_events(run_dir)`; recording event schema (`snapshot`/`scene`/`action`/`verdict`/`kimi_call`).
- recording `scene` event carries `snapshot_seq` + `scene_event` (verified in `artifacts/recordings/*/events.jsonl`).
- `memory/recording.py:28` `_scene_from_event`; `:144` `_snapshot_frames`; `:160` `_load_frame_img`; `:170` `build_from_recording`.
- `verification/probe_ingest.py:10/19/43` — `load_actions` / `golden_case_from_action` / `write_golden_case`.
- `verification/golden.py:16` `VerifierGoldenCase`; `:38` `.verifier_input()`; `:60` `iter_golden_cases` (non-recursive `glob("*.json")`).
- `verification/registry.py` — `VerifierRegistry().resolve(op).verify(VerifierInput)` (pattern at `test_computer_use_verifiers.py:100`).
- `verification/diff.py:96` — `compute_scene_diff(before, after) -> SceneDiff | None`.
- `backend_registry.py:94` `_static_frame_source_factory`; `:123` `select_frame_source_backend`; `:240` `DEFAULT_FRAME_SOURCE_REGISTRY`.
- `config.py:45` `env_prefix="GLASSBOX_"`; `:64` `frame_dir`.
- `obs/vlm_cache.py` — `CachedVLM` (key `sha256(frame_bytes+request_shape)`), `wrap_vlm_cache_if_enabled`.
- `actions.jsonl` real fields: `observation.screen_signature` (dhash), `semantic.{verifier,status,confidence,reason,deterministic,disqualifying_state}`, `diff_summary.scene`.
