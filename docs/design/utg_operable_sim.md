# Operating the UTG as a sim (replay mode 3)

Status: design + prior-art study (not implemented). Date: 2026-06-01.
Companion to `docs/design/log_sim_replay_regression.md` — this is the deep dive on
its **mode 3** (the only replay mode that is a genuine *simulator*).

A recording can be consumed three ways: (1) read-only inspection
(`python -m glassbox.obs.replay`), (2) on-rails frame replay through the live
pipeline (Tiers B/C of the companion doc), and (3) the **UTG** — a learned
`step(state, action) → state'` state machine. Only (3) is a simulator: modes 1–2
cannot answer "what happens if the agent does *X*", because the next frame is
fixed by the recording regardless of the action chosen. This doc specifies how to
make the glassbox UTG **operable** as such an environment, grounds it in 20 years
of GUI-graph prior art, and is honest about the one wall every such system hits
(off-trajectory).

Every reused symbol below was read at the cited `file:line` (tagged **REAL**);
new code is tagged **NEW**.

---

## 1. The simulator criterion

A simulator exposes, at minimum:
- `reset(state) -> observation`
- `available_actions(state) -> [action]`
- `step(state, action) -> (state', observation', done)`

Mode 3 supplies all three from a UTG built by `build_from_recording()`: a *state*
is a learned screen node, an *action* is a learned edge, `step` is an edge walk.
Modes 1–2 supply none — they are a fixed frame tape.

---

## 2. What glassbox already has (≈70% of a simulator)

The UTG / `ScreenMemory` is already a navigable state machine, and is **already
used in production** for stuck-recovery (when an action gets stuck, the runtime
recognizes the current node and path-walks the learned graph back to a target
instead of resetting Home).

| Simulator part | Status | Location (REAL) |
|---|---|---|
| state identity `scene → node` | ✅ `recognize(scene, frame_img) -> ScreenNode \| None`; signature fuzzy match (text Jaccard 0.65 + type-histogram L1 0.35 + dhash Hamming 0.15), threshold **0.82** | `memory/graph.py:192`; `SIGNATURE_MATCH_THRESHOLD` `memory/signature.py:23` |
| learn edges (offline) | ✅ `build_from_recording(run_dir, bundle_id, *, memory=None)` folds one or many recordings into one UTG | `memory/recording.py:170` |
| learn edges (live) | ✅ `observe(scene, last_action, frame_img) -> ScreenNode` | `memory/graph.py:85` |
| outgoing edges of a node | ✅ `UTG.outgoing(screen_id) -> list[ScreenEdge]` | `memory/schema.py:198` |
| node lookup | ✅ `UTG.node(screen_id) -> ScreenNode \| None` | `memory/schema.py:195` |
| shortest path `state→goal` | ✅ `path(from_id, to_id)` / `path_to_page(...)` — reliability-weighted BFS | `memory/graph.py:226` / `:255` |
| element position prior | ✅ `locate(screen_id, element_key) -> Box \| None` | `memory/graph.py:205` |
| action↔edge canonicalization | ✅ (private) `_action_identity(action) -> str`; mismatch logic `_detect_transition_mismatch(...)` | `memory/graph.py:737` / `:134` |
| production consumption | ✅ recovery path-hook (`make_try_memory_path_hook`) + element grounding via `recognize()` | `runtime.py:398`; `element_selector.py:108` |

**Schemas (REAL, `memory/schema.py`):**
- `ScreenNode` (`:134`): `screen_id`, `signature`, `elements[]`, `page_id`, `scene_type`, `safe_actions`, `app_state`, `visit_count`, `first_seen/last_seen`.
- `ScreenEdge` (`:160`): `from_id`, `to_id`, `action_op`, `element_key`, `action_identity`, `action`, `count`, `success_count`, `no_progress_count`, `success_rate`, `last_outcome`.
- `ScreenSignature` (`:106`): `stable_texts[]`, `type_histogram{}`, `phash`.
- `ActionRecord` (`:31`): `op`, `via`, `target`, `element_key`, `x`, `y`, `coordinate_space`, `params`.
- `UTG` (`:179`): `bundle_id`, `app_version`, `nodes{screen_id: ScreenNode}`, `edges[]`.

---

## 3. What is missing (the operable-sim shell, ≈500 LOC)

Four pieces, none requiring a core refactor — the sim is a *consumer* of the UTG:

1. **Public `lookup_edge(node_id, action) -> ScreenEdge | None`** (NEW, add to `ScreenMemory`). The matching logic already exists inside `_detect_transition_mismatch`; expose it:
   ```python
   def lookup_edge(self, node_id: str, action: ActionRecord) -> ScreenEdge | None:
       want = self._action_identity(action)                    # REAL :737
       for e in self.utg.outgoing(node_id):                    # REAL :198
           if e.action_op != action.op:
               continue
           if (e.action_identity or self._legacy_edge_identity(e)) == want:
               return e
       return None
   ```

2. **`UTGFrameAccessor(run_dir, utg)`** (NEW, `glassbox/sim/frame_accessor.py`) with `frame_for_node(node_id) -> Frame | None`. Nodes store no pixels; the recording does. Map `node_id → snapshot_seq → PNG` using REAL `_snapshot_frames` / `_load_frame_img` (`memory/recording.py:144/160`) and the `snapshot_seq` carried on `scene` events. **Distinct from** the companion doc's Tier-B `RecordingFrameSource` (a *sequential* `FrameSource` with `snapshot()`/`advance()`): this is a *node-indexed random-access* accessor. Same recording, shared `_snapshot_frames`/`_load_frame_img` helpers, different surface — don't conflate.

3. **`step(node_id, action) -> (next_node_id, Scene | None)`** (NEW, on `ScreenMemory` or a `UTGSimulator` wrapper):
   ```python
   def step(self, node_id: str, action: ActionRecord) -> tuple[str, Scene | None]:
       edge = self.lookup_edge(node_id, action)
       if edge is None:
           return node_id, None                                # off-edge → policy decides
       return edge.to_id, _scene_from_node(self.utg.node(edge.to_id))
   ```

4. **`SimPhone` facade** (NEW, `glassbox/sim/sim_phone.py`) — satisfies the same surface as `AIPhone` so **unmodified agent code runs against the graph**:
   ```python
   class SimPhone:                                             # NEW — mirrors AIPhone surface
       def __init__(self, utg, frame_source, *, off_edge="stop"):
           self.memory = ScreenMemory(utg)                     # REAL
           self.frames = frame_source
           self._node = next(iter(utg.nodes), None)
           self._off_edge = off_edge                           # "stop" | "stay" | "nearest"
       def perceive(self) -> Scene:                            # ← agent's observe()
           return _scene_from_node(self.memory.utg.node(self._node))
       def snapshot(self) -> Frame | None:
           return self.frames.frame_for_node(self._node)
       def tap_text(self, target: str) -> ActionResult:        # ← agent's tap("...")
           action = ActionRecord.from_op("tap", {"target": target})   # REAL from_op
           nxt, scene = self.memory.step(self._node, action)
           if nxt == self._node and scene is None:
               return self._handle_off_edge(action)            # off-trajectory
           self._node = nxt
           return ActionResult(ok=True)
       def available_actions(self) -> list[str]:
           n = self.memory.utg.node(self._node)
           return n.safe_actions if n else []
       def reset(self, node_id=None): self._node = node_id or next(iter(self.memory.utg.nodes), None)
   ```
   Plus an **off-edge policy** (NEW): `stop` (fail-loud, default), `stay` (no-op, report drift via `last_recognize_score`), or `nearest` (snap to closest signature node — risky, see §6).

---

## 4. Buildability verdict

| Component | Effort | Risk | Why low |
|---|---|---|---|
| `lookup_edge()` public API | ~1h | low | copy `_detect_transition_mismatch` logic, expose |
| `UTGFrameAccessor` | ~2h | low | reuse `_snapshot_frames`/`_load_frame_img` (helpers shared with Tier B; distinct surface) |
| `step()` | ~1h | low | one-line edge walk |
| `SimPhone` facade | ~3h | med | must mirror `tap_text/swipe/perceive`; element + coord mapping |
| off-edge policy + tests | ~2h | med | divergence handling; agent-path integration test |

**~500 LOC, no changes to `Phone`/`AIPhone`/graph internals.** Critical path =
expose `lookup_edge` + build `UTGFrameAccessor`; `SimPhone` then composes them.

---

## 5. Where this sits in the prior art

Mode 3 is squarely in the validated mainstream of "model the GUI as a graph,
path-find to a target, replay edges." It is **not** novel research; the novelty
(if any) is only that the graph is learned from the *same recordings* used for
the Tier-A/B regression corpus.

### Classic GUI-graph models (20+ yr)
| System | Model | How it "operates" the graph |
|---|---|---|
| **GUITAR / EFG / EIG** (Memon, WCRE'03; ASE-J'13) | Event-Flow Graph — **node = GUI *event***, edge = "follows" | GUI Ripping (DFS) builds it; traverse paths → event sequences → replay |
| **WTG** (Yang/Rountev, ASE'15) | Window Transition Graph — node = window, edge = event/callback, models the **back-stack** | static construction + path traversal → GUI tests |
| **GoalExplorer / STG** (Lai & Rubin, ICSE'19) | Screen Transition Graph — node = screen, edge = navigation | path-find to a target screen/API → drive exploration along it (the clearest "path-to-target then replay") |
| **DroidBot / UTG** (Li et al., ICSE-C'17) | runtime UI-state graph (NetworkX DiGraph) | `get_navigation_steps()` = `nx.shortest_path` (BFS, unweighted) to any discovered state; ships `POLICY_REPLAY` + `POLICY_MEMORY_GUIDED` |
| **APE** (ICSE'19), **ORBIT/Crawljax** (FASE'13) | state **abstraction** (CEGAR refine/coarsen; state-equivalence) | solves the node-identity / state-explosion problem — glassbox's `0.82` signature threshold is the same lever |

**glassbox's `recognize()` + `path()` is a direct structural analog of DroidBot's
`get_navigation_steps()`.** The repo is re-deriving DroidBot's UTG navigation,
specialized to perception-built (vs a11y-tree-built) nodes.

### LLM-era analogs
- **AutoDroid** (MobiCom'24, arXiv 2308.15272): explores an app, builds a UTG, uses it as **"app memory"** to give an LLM navigation hints — **almost exactly glassbox's `enable_memory` + recovery design.**
- **MobiBench** (arXiv 2512.12634): multi-branch *offline* benchmark over recorded screens; blueprint for scoring an agent on a recorded UTG (see §6).
- **AndroidControl** (arXiv 2406.03679, 15,283 demos / 833 apps): the canonical single-path static replay dataset — and the single-golden-path limitation multi-branch UTGs exist to fix.

### Graph-replay vs generative world models (the key axis)
- **Graph-replay (finite recorded states, no synthesis):** DroidBot, GoalExplorer, AutoDroid, MobiBench, AndroidControl — **this is what glassbox's UTG is.**
- **Generative world models (synthesize a *novel* next screen from an action):** UISim (arXiv 2509.21733, layout→image diffusion), ViMo (2504.13936), Code2World (2602.09856, predicts next state as renderable HTML), MobileDreamer (2601.04035, structured-text sketch), CUWM (2602.17365, *Office-desktop* test-time action search). These can fill unrecorded transitions but at unproven app-detail fidelity + heavy compute.
- **Value-only (no successor at all):** VEM (2502.18906) scores state-action value from offline data — can grade an off-trajectory action but cannot continue past it.

---

## 6. The wall: off-trajectory — and the only known escapes

A recording is a finite set of states. The moment the agent chooses an action
that was **never recorded**, there is no successor frame. This is the central,
well-documented failure of all record-replay (2025 survey: ~17% of routine /
38–44% of buggy scenarios fail from state divergence, arXiv 2504.20237). There
are exactly **four** answers, and they are the same three roads from the
companion analysis plus a pragmatic patch:

| Escape | Representative | Cost | Fit for glassbox |
|---|---|---|---|
| **Re-anchor / penalize** — accept a valid alternative action but advance along the *default* recorded trajectory | MobiBench multi-branch (annotate valid actions/node; on a valid alt, mark correct and proceed to the next default screen) | off-default it stops being faithful; good for **scoring**, not navigation | ✅ best for graph-internal *regression scoring* |
| **Go online** — judge by path-agnostic "essential states" on a real device | A3 (arXiv 2501.01149, essential-state milestones) | loses determinism; needs hardware | = back to the rig (not log-sim) |
| **Synthesize the successor** — generative world model renders the unseen screen | UISim / Code2World / CUWM | hallucinated states; app-granularity fidelity unproven | ⚠️ research-grade; defer |
| **Self-heal / re-ground** — on locator miss, swap locator or re-ground via a11y+screenshot | Katalon/Testim/autoheal | only rescues same-state-different-position; can't cross a real divergence | usable as `SimPhone` `nearest` fallback (bounded) |

**Recommended default off-edge policy: `stop` (fail-loud) + drift report** via the
already-present `last_recognize_score`. Do **not** ship `nearest` as default —
signature collisions (two screens with identical layout → same node) would
silently teleport the agent (the node-aliasing failure mode that APE/ORBIT/
Screen2Vec all exist to mitigate).

---

## 7. Phased rollout

1. **Graph-internal navigation/regression (zero synthesis).** Expose `lookup_edge`
   + `step`; drive "goal → `path()` → walk edges → `recognize()` confirms arrival."
   This is immediately operable and doubles as a navigation/planning regression
   (the analog of DroidBot `POLICY_REPLAY`). Gate: a target node must be reached
   in the expected edge count.
2. **`SimPhone` facade.** Let unmodified agent scripts run on the graph; off-edge
   policy = `stop` + drift report. No generation.
3. **Territory growth.** Fold multiple recordings of the same `bundle_id` into one
   UTG via `build_from_recording(..., memory=utg.memory)`; bigger graph = larger
   operable surface. `app_version` mismatch cold-starts (guards against UI drift).
4. **(Optional, far future) generative successor.** Only if you accept possibly-
   hallucinated states; treat as a separate research track, not part of this sim.

---

## 8. Hard limits (state them in any usage doc)

1. **Only learned edges work** — an unvisited transition cannot be executed.
2. **Out-of-vocabulary actions** — tapping text not in the recording → no edge → off-edge policy fires.
3. **Node aliasing / signature collisions** — distinct screens with identical layout hash to one node; `recognize()` cannot tell them apart (drift score helps).
4. **Element-position quantization** — `_action_identity` buckets coordinates (`//80`); too coarse merges distinct taps, too fine fragments edges.
5. **Missing frames** — if a recording wasn't saved with frames, `frame_for_node()` returns None (Scene-only sim, no pixels).

---

## 9. Open decisions

- **`step()` returns recorded Scene vs re-perceived Scene.** Returning the stored
  node Scene is deterministic but frozen; re-perceiving the node's PNG via
  `Perceptor.perceive()` couples the sim to OCR drift (and overlaps Tier B). Pick
  per use: navigation regression → stored Scene; perception-in-the-loop → re-perceive.
- **Coordinate-tap support in `SimPhone`.** §3 sketches `tap_text`; coordinate
  taps need `_action_identity`-compatible bucketing to resolve to an edge.
- **Whether `nearest` off-edge is ever allowed** (bounded by a min recognize score).

---

## Appendix A — verified internal API ground-truth (`file:line`)

`recognize` `graph.py:192` · `observe` `:85` · `path` `:226` · `path_to_page`
`:255` · `locate` `:205` · `_detect_transition_mismatch` `:134` · `_action_identity`
`:737` · `_bump_edge` `:641` · `_nearest_signature_node` `:506` · `UTG.node`
`schema.py:195` · `UTG.outgoing` `:198` · `ScreenNode` `:134` · `ScreenEdge` `:160`
· `ScreenSignature` `:106` · `ActionRecord` `:31` · `SIGNATURE_MATCH_THRESHOLD=0.82`
`signature.py:23` · `build_from_recording` `recording.py:170` · `_snapshot_frames`
`:144` · `_load_frame_img` `:160` · recovery hook `runtime.py:398` · `recognize()`
grounding `element_selector.py:108`. `lookup_edge` / `step` / `SimPhone` /
`UTGFrameAccessor` do **not** exist yet (the NEW work).

## Appendix B — prior-art sources & verification caveats

Strongly verified (read against primary source/code): DroidBot
[github.com/honeynet/droidbot] — note `nx.shortest_path` is **BFS** (unweighted),
not Dijkstra. GUITAR/EFG [cs.umd.edu/~atif, Memon WCRE'03] — note node = **event**,
not state. WTG [ASE'15]. GoalExplorer STG [ICSE'19]. APE [ICSE'19]. AutoDroid
[arXiv 2308.15272]. AndroidControl [2406.03679]. A3 [2501.01149]. MobiBench
[2512.12634]. UISim [2509.21733] (venue "NeurIPS'25" **unverified**, reads as
preprint). ViMo [2504.13936]. Screen2Vec [2101.11103]. VEM [2502.18906]. RERAN/
R&R survey [2504.20237] — the "SARA reproduced 20/125" figure is **wrong** (paper:
18 recorded / 3 replayed). Mosaic = Halpern et al. **ISPASS'15** (coordinate→
device-independent IR); do not conflate with the FSE'22 "Cross-Device R&R"
(DirectorX/Rx, widget-tree). Recent but real (arXiv IDs post knowledge-cutoff,
reachable): Code2World [2602.09856], CUWM [2602.17365] (**Office desktop**,
test-time action search — not general offline eval), MobileDreamer [2601.04035],
MobileWorldBench [2512.14014], Agent+P [2510.06042].
