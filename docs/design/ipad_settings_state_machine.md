# Design — iPad Settings navigation state machine (map + architecture levers)

Status: **implementation in progress; L1 dual projection/root signature and
memory-local L3b detail anchoring are implemented behind
`GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` (default-off), plus L2a static
device-profile availability, graph-entered root-row skip, and L4 row-tracked
sidebar wheel first move; L2b sidebar-absence oracle is implemented but remains
rig-acceptance-gated (2026-05-31).** Produced after a long series of
reactive *local* patches to the iPad Settings drill-down (breadcrumb-reject,
sidebar fallback, exemption-decouple, memory-return [reverted], an in-flight
sidebar-absence patch) kept hardening the SEARCH and RETURN-TO-ROOT paths. This
document maps the iPad Settings app as one state machine, names the structural
root causes those patches were band-aiding, and ranks the architecture-level
fixes that would *subsume* the patches. It extends the device-neutral FSM model in
`screen_state_fsm.md` (shipped P1–P3) with the iPad-split-view reality that model
under-specifies.

Every structural claim is verified against the 5 persisted per-run UTG graphs at
`artifacts/exempt_5round/r1–r5/.../memory/com.apple.Preferences.json`, the run
logs, and live source.

> **2026-05-30 adversarial review pass** (9-agent verify+assess against source +
> the 5 UTGs). The C1–C5 map below is confirmed near-verbatim; this revision
> corrects four over-stated figures, re-tiers **L1** from "read-only/low risk" to
> **MEDIUM-HIGH, flag-gated** (scene-kind is load-bearing, not metadata),
> re-sequences the levers (**L3b signature work must precede L1**), and replaces the
> §4 census-only acceptance metric — which the reverted Option-1 already passed
> while broken — with outcome gates. All review edits are marked ⟦review⟧.
>
> **2026-05-31 second review pass** (5 findings, source-verified). Corrects an
> internal contradiction in L1 (the empty-detail-pane discriminator cannot coexist
> with "every sidebar tap sources from root" — the missing piece is a *write-model*
> mechanism, not a classifier tweak), re-binds the L1 acceptance gate to the correct
> edge direction (`detail→root`, not `root→detail`, for return-to-root replay),
> de-conflates root-signature collapse (L1 #2) from L3b (detail-page signatures),
> reconciles the §4 test with the discriminator, and fixes a commit-provenance error
> (`678fbcc` is Option 3, not Option 1). These edits are marked ⟦review-2 2026-05-31⟧.
>
> **2026-05-31 third review pass** (3 findings, source-verified against `policy.py` +
> `recovery.py`). Separates three concepts L1 had conflated — *root context* (runtime
> recovery, already works via `scene_is_settings_root`), *graph root node + coverage*
> (the real gap), *physical detail→root transition* (only some states need it) — and
> scopes the return-to-root acceptance to return-requiring states only. Marked
> ⟦review-3 2026-05-31⟧.
>
> **2026-05-31 fourth review pass** (3 findings). Makes L1 executable by **committing to
> a single mechanism** (dual projection + action-typed source attribution) instead of
> three candidates, purges the last "structural scene-kind" language in favor of the
> projection/context write-model, and completes the review-marker registry. Marked
> ⟦review-4 2026-05-31⟧.
>
> **2026-05-31 fifth review pass** (2 findings, source-verified). Catches that "root is
> never a kind value" would leave memory-return inert — `nodes_for_page` filters on
> `scene_type ∈ (scene_type, semantic_scene_type, platform_scene_kind)`
> (`graph.py:212-220`), so the root projection node **must** carry
> `platform_scene_kind="settings_root"` as a stored field (the "not a kind" rule applies
> only to the classifier's per-frame return). Also updates §4's stale "resolve the
> mechanism" wording. Marked ⟦review-5 2026-05-31⟧.
>
> **2026-05-31 sixth review pass** (1 readability finding). Removes the leftover "Pick
> (a)/(b)/(c)" imperatives in L1 that contradicted the already-chosen mechanism;
> reframes the three options as "candidates considered → (a) chosen." Marked
> ⟦review-6 2026-05-31⟧.

## 1. The empirical state machine

### States — the split-view structural truth

The classifier (`glassbox/ipados/scene.py:classify_ipados_scene`) emits **6 scene
kinds directly** (`settings_detail`, `settings_root`, `settings_search_results`,
`system_search`, `springboard`, `unknown`) plus whatever the non-split `return ios`
fallback inherits from `classify_ios_scene` (⟦review⟧ the earlier "9" is only
reachable by counting that iOS fallback). On the real device the UTG only ever
persists **two**:

| run | nodes | settings_detail | settings_search_results | **settings_root** |
|-----|-------|-----------------|--------------------------|-------------------|
| r1 | 43 | 33 | 10 | **0** |
| r2 | 36 | 30 | 6 | **0** |
| r3 | 35 | 29 | 6 | **0** |
| r4 | 38 | 30 | 8 | **0** |
| r5 | 37 | 30 | 7 | **0** |

**There is no *persisted* root state — the minting branch is vestigial, not a data
gap.** `ipados/scene.py` *does* contain a branch that mints `settings_root` /
`page_id="settings/root"`, guarded by `if title and detail_evidence: →
settings_detail … else → settings_root`. On iPad split-view the sidebar and detail
pane are **always co-visible**, so the detail pane essentially always yields a
title + evidence, the `settings_detail` branch always wins, and the `settings_root`
branch is **never reached in steady state** — 0 of 189 persisted nodes across 5
runs are root. ⟦review⟧ It is *conditionally reachable*, not literally dead code: it
fires on any frame with `title=None` **or** `detail_evidence==()` (cold start,
OCR-empty detail pane, mid-scroll title dropout — the same C3 oscillation), it just
never sediments into a stable node. **The real gate is the `else` condition, which
fires on *detail-pane emptiness* — almost never true on split-view — so "decouple
root from the OCR title" (L1's original framing) mis-names the problem: the title
is not the gate, detail-pane emptiness is.**

The iPad "root" is not a screen — it is the *composite* state `(sidebar present)
+ (detail pane currently showing page X)`, a tuple the single-node-per-page model
cannot represent. The same `title`-presence test also sets `safe_actions`, so
scene identity *and* the action set are both coupled to a lossy OCR title.

### Transitions — a sparse chain plus a disconnected search island

Topology is **not** the hub-and-spoke the FSM assumes (r1, representative):

```
settings_detail        -> settings_detail            50   (forward chain + self-loops)
settings_search_results -> settings_search_results   14   (search island internal)
settings_detail        -> settings_search_results     4   (enter search)
settings_search_results -> settings_detail            4   (tap a result)
settings_root -> *  /  * -> settings_root             0
```

Reliability by op — ⟦review⟧ these are the **unweighted mean of per-edge
`success_rate`**, and the strict ordering only holds in r1 (it scrambles in r2–r5;
read it as "`type` clearly highest, `key`/`long_press` clearly lowest,
`scroll_wheel`≈`tap`≈`back` in the middle, run-dependent"): `type` 100% ›
`scroll_wheel` 80–83% › `tap` 72–82% › `back` 50–75% › `key` 17–67% › `long_press`
20–50%. **Traversal-weighted, `scroll_wheel` is only ~62–70%** — the mean-of-rates
over-states the load-bearing failure mode by ~15pt; use the weighted number when
arguing about fling backpressure. **100% of self-loops record success_rate=0.0**
(e.g. r1 17/17)
— the worst is `scroll_wheel settings_detail→settings_detail no_progress=10` (the
multi-pass sidebar scroll banging with zero forward progress). The graph cannot
distinguish "benign scroll reflow, still on Sounds" from "tap failed, stuck."

### Sub-machines

- **BOOTSTRAP** (`bootstrap.py`) — foreground Settings → lands in the composite root.
- **WALK** (primary, load-bearing) — `open_visible_or_scroll_to_row` + depth-0
  multi-pass scroll resets (max 2). Reaches ~11/12 reachable roots directly; the
  ceiling is momentum-fling overshoot.
- **SEARCH** (fallback, mostly futile) — `crawl_missing_root_pages_via_search`.
  In r1, of 5 search attempts only 蓝牙 resolves; the other 4 (蜂窝网络/操作按钮/
  待机显示/紧急SOS) each fail **once** (⟦review⟧ iPad search is single-attempt,
  `navigation.py:95 max_attempts=1`; the "5" is the count of distinct roots searched,
  of which 4 fail — *not* a per-root retry multiplier) and exist only to *confirm
  device-unavailability* for roots genuinely absent on a no-SIM iPad. Fix 3b and Part
  A both patch this
  futile path. (Cost note: `r1/run.log` has no wall-clock timestamps; the "~25% of
  the run is futile search" figure is a line-share / action-cost estimate, not a
  stopwatch reading. The mechanism is fully confirmed; treat 25% as order-of-
  magnitude.)
- **RETURN-TO-ROOT** (`recovery.py:return_to_settings_root`) — 12-retry scene-kind
  dispatch; the `via_memory` path is **structurally inert** because
  `path_to_page("settings/root")` has no root node to target.

## 2. Structural root causes

- **C1 — No `settings/root` node ⇒ RETURN-TO-ROOT memory path and graph-coverage
  are both dead.** `_settings_root_node_ids` (`graph_state.py:142-147`, which *does*
  already match on `_node_kind` incl. `platform_scene_kind` AND `page_id`) returns
  ∅ on every iPad run because no node ever carries that kind/page_id. So
  `root_entered_labels` / `inert_root_labels` are ∅ and `try_memory_return_to_
  settings_root` always returns False *on iPad*. The reverted root-minting experiment
  (**Option 1** — the mint-the-node half; its companion recognize/replay half never
  fired) lands here; the revert was correct, but the model defect remains — the memory
  call site is vestigial. ⟦review-2 2026-05-31⟧ **Provenance fix:** do **not** pin
  Option 1 to commit `678fbcc` — that commit is *Option 3*
  (`fix(settings): replay learned back-edges in the memory-path return`), an unrelated
  return-to-root replay change. The Option-1 mint was reverted and is not among the
  current head commits, so no hash is asserted here. ⟦review⟧ A minted root is
  *necessary but not sufficient*: even with root nodes, replay is still gated by
  `min_success_rate=0.5` + `allowed_actions={'home','back'}` (`core.py:459-460`), and
  `recovery.py:266` reaches this path **unconditionally** in the unknown-fallback, so
  a wrong/fragmented root can mis-target it even with the flag off.
- **C2 — SEARCH is load-bearing for futile device-unavailable confirmation.** WALK
  cannot *prove* a root is unreachable, so SEARCH is the de-facto availability
  oracle (4/5 search attempts in r1 exist only to fail). Fix 3b + Part A harden a
  path that should not be on the critical route.
- **C3 — Root/detail classification oscillates because identity is coupled to a
  lossy OCR title.** `if title and detail_evidence` decides the kind *and*
  `safe_actions` (`ipados/scene.py`). `_detail_pane_title` returns None mid-scroll
  / OCR variants ("Screem Time", "NOtificatiOns"), so a frame can flip
  detail→root→detail across perceives — the recovery churn.
- **C4 — Node-signature fragmentation: one logical page → 2–5 nodes.** r1:
  `settings/Camera` = 5 nodes, `settings/Bluetooth` = 4, `settings/Sounds` = 3. The
  signature is over-sensitive to scroll position / dynamic content / OCR variance,
  so the graph re-discovers pages and never accumulates reliable edges.
- **C5 — Coverage is judged per-frame, not from the graph.** The Phase-3 contract
  in `screen_state_fsm.md` ("coverage = root children reached, chase unexplored
  outbound root edges") targets root→child edges that don't exist on iPad (0
  root-sourced edges), so graph-authoritative coverage is a **silent no-op** and
  the crawl falls back to per-frame `missing=[…]` + multi-pass reset + search.

## 3. Prioritized levers (leverage × 1/risk)

### L1 — Synthesize a virtual `settings/root` node for split-view (model level)
**Removes C1; unblocks C5 + graph-level RETURN-TO-ROOT. Keystone — but ⟦review⟧
MEDIUM-HIGH risk, flag-gated (NOT "small, read-only, low risk").** ⟦review-3 2026-05-31⟧
**Disambiguate three things L1 touches — they are NOT the same, and conflating them is
why patches keep landing in recovery instead of the write-model:**
- **(i) root *context*** — the runtime recovery notion, which **already works**:
  `scene_is_settings_root()` returns true on any split-view detail frame (it carries
  `ipad_split_view` evidence + a `tap_root_row` safe action — `scene.py:94`,
  `policy.py:1352`), so recovery already *stops* correctly at the root context
  (`recovery.py:90`). L1 does **not** need to "fix" this.
- **(ii) graph root *node* + root-sourced edges + coverage** — the **real gap L1
  closes** (today 0 root nodes, 0 root-sourced edges). This is the keystone value.
- **(iii) physical `detail→root` return *transition*** — an actual navigation move only
  *some* states need (see acceptance in §4); most steady-state pages are already the
  root context and require no return. ⟦review-2 2026-05-31⟧ The prior
pass said L1 "must land after/with L3b"; that over-stated the dependency — L1's *root*
collapse is its own sub-item #2 (sidebar-scoped signature), so L1 does not hard-depend
on L3b. L3b (detail-page signatures) gates **L2**, not L1's minting (see §4). Scene-kind is load-bearing: via `_merge_scene_fields` (`graph.py:362-397`)
the emitted kind sets `platform_scene_kind` + `page_id` + `safe_actions` on the node;
that node then becomes `_last_node_id`, so it is the `from_id` of only the *single
immediately-following* edge (`graph.py:91-98`) — ⟦review-2 2026-05-31⟧ **not** "every
subsequent tap edge," and emitting a root *kind* does **not** by itself make sidebar
taps source from root (see detail 3). The change is side-effect-free on the *device*
but, done wrong, corrupts node metadata graph-wide on the *FSM*. Define the root as the composite state
`(sidebar present, not in search overlay)` and mint a stable synthetic root identity
(`page_id="settings/root"`) that every sidebar-row tap sources its edge from.
⟦review⟧ **Make-or-break details the original framing omitted** — ⟦review-2 2026-05-31⟧
*details 1 and 3 are in tension, and resolving that tension is the actual design work:*
1. **Root↔detail discriminator — and why detail-pane-emptiness cannot be it.**
   `(sidebar present, not in search)` is true on *every* detail frame too, so it
   cannot separate root from detail on its own; the title-gate is currently the only
   separator. ⟦review-2⟧ The obvious replacement — a positive **detail-pane-empty**
   signal (`detail_evidence==()`) — is **self-defeating on two counts.** (a) An empty
   detail pane is exactly the cold-start / OCR-dropout transient that *never sediments*
   (C3), so gating root on it just reproduces today's "0 persisted roots." (b) More
   fatally, it contradicts detail 3: in steady-state split-view the frame *immediately
   before* a sidebar-row tap still shows the previously-opened page, so under an
   empty-pane gate that frame classifies as `settings_detail` and the tap edge sources
   from detail — so **"every sidebar tap sources from root" can never hold.**
   Detail-pane emptiness is therefore *not* the discriminator. Root must be modeled as
   a **sidebar-scoped projection that co-exists with the detail page**, not a mutually
   exclusive empty-pane scene kind (see detail 3 for the mechanism).
2. **Sidebar-scoped signature.** Node identity is signature-based (`compute_signature`
   = stable texts + type histogram + phash, `signature.py:49-65`, resolved *before*
   `page_id` is merged at `graph.py:386`; `page_id` is only a negative scope filter,
   never a creation key). A composite-root frame's signature includes the variable
   detail-pane text, so it fragments exactly like `settings/Camera`=5 — **this is
   what the reverted Option-1 actually hit (15 fragmented root nodes, replay never
   fired).** Compute the *root* signature from **sidebar elements only**
   (`cx ≤ sidebar_right_x`, detail-pane text excluded) so the composite frame
   collapses to **one** root node regardless of which page is co-visible.
3. ⟦review-2 2026-05-31⟧ **Source-node attribution — the write-model gap, not a
   classifier tweak.** `graph.observe()` records every edge's `from_id` as the
   *previously resolved* node (`graph.py:91-98`: `_bump_edge(self._last_node_id, …)`
   then `self._last_node_id = node.screen_id`). So even a perfect root classifier does
   **not** make sidebar taps *source from* root unless the frame that *precedes* the
   tap resolved to root — which, per detail 1, it does not on steady-state split-view.
   Closing L1 therefore requires an explicit write-model mechanism, **not "just change
   `classify_ipados_scene`."** ⟦review-6 2026-05-31⟧ Three candidates were considered
   (the chosen one is fixed below — see "Chosen mechanism"): (a) **dual projection** — one
   split-view frame folds into *two* logical observations (a sidebar/root node and a
   detail node), so the root identity is always available as a `from_id`;
   (b) **synthetic composite edge** — at sidebar-tap time, synthesize the `root→detail`
   edge directly instead of relying on the previous-frame `from_id`; (c) **`from_id`
   override** — when the landed action is a sidebar-row tap, override the recorded
   source to the root identity. This source-attribution piece is what the reverted
   Option-1 never had. ⟦review-2 2026-05-31⟧ **Why this cannot live
   in the classifier:** `classify_ipados_scene` returns exactly *one* `(kind, page_id)`
   per frame (`scene.py:85`), so making it emit `settings_root` on a co-visible frame
   would *overwrite* the detail page's identity/metadata and break detail recognition
   (re-introducing C3 churn). All three options act at the **graph-write layer**
   (`graph.observe` / edge recording), not by flipping the classifier's single return —
   that is precisely why this is a *write-model* gap, not a classifier tweak. ⟦review-6
   2026-05-31⟧ The mechanism is **decided** (see "Chosen mechanism" immediately below) —
   it lives in the graph-write layer, not the classifier.

   ⟦review-4 2026-05-31⟧ **Chosen mechanism — commit to (a) dual projection +
   action-typed source attribution; build the test against it.** On every split-view
   `observe()`, fold the frame into **two** projections: a *sidebar-scoped root node*
   (signature from sidebar elements only, per detail 2 — one node across all co-visible
   pages) **and** the detail node. Then attribute the next edge's `from_id` **by action
   type**: a **sidebar-row tap** sources from the *root* projection (yielding the
   `root→detail` coverage edge); every *within-detail* action (scroll / in-page tap /
   back) sources from the *detail* projection. **Why not (b)/(c) standalone:** both
   presuppose a persisted root node to target/override, which only (a) mints — (c)'s
   `from_id` override then collapses into the action-typed selection *inside* (a), and
   (b)'s synthetic edge is just an alternative wiring of the same `root→detail`
   attribution. Keep (b)/(c) as fallbacks only if the dual-write proves too costly. This
   also realizes L3a's "root/sidebar is an orthogonal projection, not a `kind`" — the
   root lives as its own projected node, not a value the *classifier* emits per-frame.

   ⟦review-5 2026-05-31⟧ **Critical exception — the projected root node MUST still carry
   `platform_scene_kind="settings_root"` as a stored field.** "Not a classifier kind" was
   over-stated: the memory-return finder calls `path_to_page(node, "settings/root",
   scene_type="settings_root", …)` (`core.py:456-461`), and `nodes_for_page`
   (`graph.py:212-220`) keeps a node only if `scene_type` appears in
   `(n.scene_type, n.semantic_scene_type, n.platform_scene_kind)`. So a root projection
   with **only** `page_id="settings/root"` and no kind field is found by the coverage
   finder (page_id-only) but **invisible to memory-return** — i.e. memory-return stays
   inert exactly as today. **Resolution: the dual-write sets
   `platform_scene_kind="settings_root"` on the root projection node** (so both finders
   resolve it). The "orthogonal projection, not a kind" rule applies to the *classifier's
   single per-frame return*, **not** to the projected node's stored metadata — the node is
   semantically the root and is correctly tagged as such. (Alternative, if the dual-write
   cannot set that field: drop/loosen the `scene_type="settings_root"` filter in
   `core.py` to be projection-aware. Prefer setting the field — it is local to the write
   and keeps both finders uniform.)

Only with (1)+(2)+(3) does the (already-correct) `_settings_root_node_ids` query
populate usefully — ⟦review⟧ the earlier "finders populate immediately" overstated:
the finders additionally require the root to be the *recorded `from_id`* of sidebar
taps (today 0 of 38 tap edges source from root), and `_is_successful_root_outbound_edge`
*discards* any `root→root` edge, so a fragmented root actively starves L2. This makes
`root→detail` edges real, so **coverage (L2/C5) gains a source node.** ⟦review-2
2026-05-31⟧ **The two edge directions do different jobs and must not be conflated:**
`root→detail` edges feed *coverage*; the RETURN-TO-ROOT `via_memory` replay instead
needs `detail→root` edges via `{home,back}` with `success_rate ≥ 0.5`, because
`core.py:456-461` searches `path_to_page(node, "settings/root",
allowed_actions={"home","back"}, min_success_rate=0.5)` *toward* root. **Subsumes:**
the dormant `via_memory` path becomes live (un-reverts the *intent* of Option 1) —
⟦review-3 2026-05-31⟧ this is the *(iii) physical-return* path, relevant **only** for
states that genuinely must navigate back (see §4 acceptance), **not** for the
already-working *(i) root context* — **and only if** the relevant `detail→root`
back/home edges accumulate at ≥ 0.5 and clear that replay gate; keep
`settings_return_root_via_memory` **default-off** until an A/B proves the now-live
memory path improves recovery.

### L2 — Graph-authoritative coverage with explicit device-availability (model)
**Removes C5 + C2.** Once L1 gives root→child edges: coverage = "every sidebar root
row has a successful `root→detail` edge"; chase only unexplored outbound root
edges. Add a first-class `device_unavailable` label distinct from `missing`: a root
the sidebar walk never surfaces AND with no hardware affordance is unavailable
*from the graph/device profile*, not re-confirmed by SEARCH every run.
⟦review⟧ **Caveat — this oracle depends on L4.** "Sidebar never surfaces it" cannot
distinguish *device-unavailable* from *fling-overshoot skipped it* until L4 makes the
sidebar walk exhaustive; until then `device_unavailable` must come from a static
device-profile table, not from sidebar absence. So L4 partially gates L2's
correctness (see re-sequencing in §4). ⟦review-2 2026-05-31⟧ **Therefore split L2:**
**L2a** = graph-authoritative coverage + `device_unavailable` sourced from a *static
device-profile table* — **no L4 dependency**, can land right after L1; **L2b** = derive
`device_unavailable` from *sidebar absence* — must wait until L4 makes the sidebar walk
exhaustive (else it cannot tell "unavailable" from "fling-overshoot skipped"). The
ordering in §4 reflects this L2a/L2b split.
**Implementation:** L2a is model-keyed for the current `ipad_mini_7` rig profile.
L2b records sidebar-absent labels only when row-tracked root scrolling reaches an
exhaustive boundary; report/verifier logic refuses to treat `sidebar_absent` as
entry-exempt without that `sidebar_exhaustive` evidence.
**Subsumes / retires:** the futile SEARCH for the 4 device-unavailable roots; the
**in-flight sidebar-absence patch** (becomes a modeled root↔non-root transition);
most of **Part A** (search no longer load-bearing); **Fix 3b** (sidebar-direct
becomes the primary path; "search failed → try sidebar" inverts to "graph says
reachable → walk sidebar; never search").

### L3 — Decouple identity from the OCR title; stabilize signatures (model)
**Removes C3 + C4.** ⟦review⟧ **Split into two independently-shippable levers with
very different blast radius:**

- **L3a (iPad-local, lower risk).** Set `safe_actions` from structural evidence
  (sidebar / detail-pane / search-overlay presence) rather than from `title` presence —
  kills the recovery oscillation. ⟦review-3 2026-05-31⟧ **Keep this consistent with L1's
  projection model:** the single `kind` should keep describing the *mutually exclusive*
  surfaces (`settings_detail` / `settings_search_results` / `unknown`), while
  *root / sidebar-present* is an **orthogonal projection/context** (per L1 detail 3),
  **not** a fourth value crammed into the same one-per-frame `(kind, page_id)` return
  (`scene.py:85`). L3a decouples `safe_actions` from the title; it does **not** make
  `kind` itself carry root-ness — that is the write-model projection L1 owns. **Subsumes:** Fix
  3a (breadcrumb-reject) is a symptom of title-driven misclassification; once kind is
  structural it is largely unnecessary. (⟦review⟧ Caveat: `ipados/scene.py` imports
  and *calls* `classify_ios_scene` for its non-split fallback — `scene.py:74/83` — so
  even L3a touches shared iOS markers, not purely iPad-local.)
- **L3b (detail-page signature anchoring — the L2/detail-coverage precondition).**
  ⟦review-2 2026-05-31⟧ **Scope note:** L3b is **not** an L1 precondition — L1 collapses
  the *root* signature itself via its sub-item #2 (sidebar-scoped). L3b stabilizes the
  *detail-page* signatures so that `root→detail` / `detail→detail` edges accumulate
  reliably, which is what **L2** (graph-authoritative coverage) needs. Make detail-page
  signatures title-anchored + scroll-invariant (canonicalize OCR variants) so
  `settings/Camera` is one node, not five.

  ⟦as-built 2026-05-31⟧ **Shipped memory-local, NOT in shared `signature.py`.** The
  implementation anchors the detail signature inside the iPad root-projection write path
  (`graph.py:_ipados_settings_detail_signature` /
  `_should_use_ipados_settings_detail_signature`): for a `com.apple.Preferences`
  `settings_detail` frame whose `page_id` starts with `settings/`, the node signature is
  `stable_texts=[norm_text(page_id)]` + `type_histogram={"settings_detail": 1}` +
  `phash=""`, computed only when `GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` is on. This is
  **narrower and safer than the original plan**: same iPad flag, never touches the
  cross-platform signature path, so iPhone signatures are byte-identical with the flag
  off — the over-merge risk below does not apply to what shipped. Because the anchor keys
  off the already-resolved `page_id` (not raw OCR), OCR-variant canonicalization is
  deferred to whatever produced `page_id`; no second competing canonicalization was
  introduced.

  *Original (deferred) plan — only if detail anchoring is promoted into the shared path:*
  editing *cross-platform* `signature.py` (affects iPhone too — guard against over-merge:
  assert distinct known pages still resolve to distinct nodes), and its OCR-variant
  canonicalization **must route through the locale seam** (see
  `locale_seam_english_first.md`) rather than introduce a second, competing
  canonicalization. **This is the gating dependency for L2 (detail-page edge
accumulation), not for L1's root minting, and not a successor of L2.**

### L4 — Deterministic row-state-tracked sidebar scrolling (mostly local)
**Raises the WALK ceiling (the real source of "missing").** The 11/12 ceiling is
momentum-fling overshoot (`scroll_wheel no_progress=10`); iPad has precise wheel
scroll (see `picokvm_ipad_wheel.md`). Track sidebar row geometry per tick and
scroll to *land on* the next unentered row instead of fling-and-reset. Then SEARCH
is invoked only for genuinely-search-only roots (≈none on this device).
**Implementation first move:** root crawl now passes required missing root labels into
the scroll helper, and iPad root scrolling estimates one sidebar-row worth of wheel
ticks from current row geometry instead of using the full fixed fling. Rig A/B must
still prove this is exhaustive enough for L2b.
⟦review⟧ **Likely under-prioritized.** This is the *only* lever that attacks the
actual source of "missing." If WALK reliably reached 12/12, SEARCH → ~0 invocations
and C2's whole "SEARCH-as-availability-oracle" dissolves, shrinking L2's
`device_unavailable` apparatus to a tiny static device-profile lookup. Consider
promoting L4 ahead of, or concurrent with, L2.

### Stays a local patch (do NOT promote)
BOOTSTRAP's multi-fallback; AssistiveTouch back-gesture flakiness in RETURN-TO-ROOT
(hardware reality); per-device availability facts (蜂窝网络/钱包 = device-profile
data consumed by L2).

## 4. What to do next

**Current implemented slice: L1's chosen dual-projection write model is in tree,
flag-gated default-off.** ⟦review-5 2026-05-31⟧ Mechanism is fixed — (a) dual
projection + action-typed source attribution, with
`platform_scene_kind="settings_root"` on the root projection node. The implementation
also anchors iPad Settings detail signatures by `page_id` inside memory while the
flag is on; this is the local first move toward L3b, not the shared
`signature.py`/locale-seam canonicalization described above. L2a's static
device-profile availability is in tree too: known unavailable iPad roots are entry
exempt before search, and graph-entered root rows are skipped by the root crawl.
⟦review⟧ The original "first move: L1" understated that minting a root node is
worthless until the root signature collapses to a *single* stable node.
⟦review-2 2026-05-31⟧
**Correction to the prior pass:** that *root*-signature collapse is **L1's own sub-item
#2** (sidebar-scoped signature), **not L3b** — L3b stabilizes *detail-page* signatures
(`settings/Camera` = 1, not 5). So L1 is internally self-sufficient for root collapse
and does **not** hard-depend on L3b for minting; the prior pass's "L3b-before-L1"
dependency was mis-attributed. L3b is instead the precondition for **L2**: detail-page
nodes must stop fragmenting before graph-coverage can accumulate reliable `root→detail`
edges. Revised remaining order: **rig A/B for L1-on + L4 row-tracked scrolling +
L2b-on-evidence → complete shared L3b if the local memory signature is insufficient**.
L2b is implemented as an evidence-gated oracle: sidebar-absent labels become
device-unavailable only after a row-tracked root pass records `sidebar_exhaustive`.
Rig A/B still has to prove that this exhaustiveness signal is trustworthy.

**Acceptance for L1 is NOT "census 0 → non-zero."** ⟦review⟧ That is a wiring
metric, gameable by construction (the mint fires the branch regardless of navigation
quality) — the **reverted Option-1 already passed it** with 15 root nodes while
broken. It repeats the "structural metric ≠ task success" trap (cf. the committed
floor with `action_success_rate=0.955` but `task_completion_rate=0.0`). Gate instead
on the **outcome metrics the harness already computes** (`computer_use_success_rate.py`):
- **Necessary precheck:** census flips 0 → non-zero **AND** root collapses to **≤1–2
  stable signatures** per run (not 15).
- **`entered_graph` rises 0 → toward 12** — the direct C5 "silent no-op" signal
  (currently 0 on all 5 runs; note the harness's `root_pages_coverage` is fed by
  per-frame `entered`, *not* `entered_graph`, so name the field you gate on).
- **≥N `root→detail` edges** with `to_id ∉ root_ids` and `success_rate ≥ 0.5` — these
  gate **coverage** (`entered_graph` / L2), *not* the return-to-root replay.
- ⟦review-2 2026-05-31⟧ **Separately, ≥1 `detail→root` edge via `{home,back}` with
  `success_rate ≥ 0.5`** — *this* is what lets the replay gate fire, since
  `core.py:456-461` searches `path_to_page(node, "settings/root",
  allowed_actions={"home","back"}, min_success_rate=0.5)` *toward* root. Acceptance:
  `try_memory_return_to_settings_root` returns a real path **and actually replays it**
  on re-run. (The prior pass bound this gate to `root→detail` edges — the wrong
  direction; they never satisfy a toward-root path search.) ⟦review-3 2026-05-31⟧
  **Scope this correctly — do NOT require *every* detail page to emit a `detail→root`
  edge.** Most steady-state split-view pages *are* the root context (i) and need no
  physical return. The `detail→root` replay acceptance applies **only** to states that
  genuinely must navigate back: a *pushed* sub-page, a *search-results* surface, or an
  `unknown` recovery state (`recovery.py:90`). So gate **coverage** on `root→detail`
  (every reachable root row), and gate **replay** only on those return-requiring states
  — not on the whole detail census.
- **No regression** in `task_completion_rate` / `root_pages_coverage` /
  `navigation_success_proxy_rate` vs the committed floor; **futile-search action-share
  drops**. Reject any change where `action_success_rate` rises while
  `task_completion_rate` or `entered_graph` fall.

⟦as-built rig 2026-05-31⟧ **First on-rig pass (iPad mini 7, en/HK, n=1/arm — NOT yet
median-backed).** Back-to-back B-arm (L1 on) vs A-arm (flag off): `entered_graph` **0→7**,
`root_to_detail` success edges **0→14**, root mints + collapses to **2** signatures
(passes the ≤2 gate; ideal 1), acceptance green. **The A-arm (baseline) crashed with
`SettingsRootUnreachable` (`recovery.py:122`) while the B-arm completed** — direct
evidence that L1 removes the C1 return-to-root failure (B recognizes the composite root
in-place via `scene_is_settings_root`, `recovery.py:93-94`; A has no root node and
default-off `via_memory`, so its 12-retry heuristic fails after a fling overshoot). Two
caveats the rig exposed: (a) the root's 2-vs-1 signature split is **OCR case drift on the
sidebar text** (`BluetOOth`/`NOtificatiOns`) — this is an **L1-completion** item (the root
signature is L1's own sub-item #2; the fix is an OCR case-fold on that sidebar text **at the
locale seam**), *not* an L3b extension (L3b is detail-page signatures); (b) the coverage gap
is **L4 fling-overshoot**, orthogonal to L1; (c) **B's `sidebar_exhaustive=true` was a false
positive** — it exempted 5 reachable roots (the A-arm entered all 5) out of the required set,
so this run's acceptance-green was partly hollow. **Verdict must cross-check that B's
`entry_exempt` set excludes any root any arm actually entered, and weigh
`required_missing` / `task_completion` / crash-rate / median `entered_graph` — not
acceptance-green alone.** **n=1 is insufficient to flip the flag** — the
median rerun + zh locale are the remaining gate. Full plan +
hardened driver: `docs/goals/ipad_settings_l1_rig_ab_handoff.md`. (The first matrix
driver self-restarted and produced two concurrent runs on one rig; only the snapshotted
`B_1`/`A_1` pair is clean — the handoff adds a single-instance lock.)

⟦as-built rig rerun 2026-05-31⟧ **Median-backed A/B verdict on iPad mini 7:
ship-negative; keep `GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` default-off.** The
hardened matrix driver and extractor completed 3 B + 3 A rows for en/HK and, after
physically switching the iPad UI to Simplified Chinese, 3 B + 3 A rows for zh-Hans/CN.
Valid artifacts: `artifacts/ios_settings/ab/results_20260531_165130.jsonl` (en/HK rows
only) and `artifacts/ios_settings/ab/results_20260531_173903.jsonl` (zh-Hans/CN rows).
The `zh-CN` rows in `20260531_165130` are invalid (unsupported locale pack), and
`20260531_171315` is invalid for the locale verdict because the runner args were
zh-Hans/CN while the physical device UI was still English.

The primary L1 signal is still strong: median `entered_graph` is **B=7 vs A=0** in
both locales, and median `root_to_detail` is **B=14/13 vs A=0** (en/HK / zh-Hans-CN).
But the operational gate fails. en/HK B has rc/crash **2/3**, task completion **1/3**,
and median `root_sigs=3` (over the <=2 collapse gate); zh-Hans/CN B has rc/crash
**3/3**, task completion **0/3**, median `nav_proxy=0`, and median `visit_count=4`.
The mandatory exemption cross-check also still fails in en/HK: B's
`sidebar_absent`/`entry_exempt` set includes reachable roots
(`声音与触感`, `专注模式`, `屏幕使用时间`, `Face ID与密码`, `隐私与安全性`) that were entered
by another same-locale arm/round, so the sidebar-exhaustive oracle is still spurious
under fling/recovery variance. zh-Hans/CN has no same-locale overlap, but only because
both arms miss the same lower roots; that is not positive device-unavailable evidence.
Conclusion: L1's graph projection is useful, but default-on is blocked by L4/root
recovery and L2b sidebar-exhaustive reliability, plus the L1 sidebar-signature case-fold
via the locale seam.

**Rollout: flag-gated, default-off, rig-validated — exactly like Part A / Fix 3a/3b /
Option 3.** ⟦review⟧ L1 changes UTG topology, so a census-green change could merge
without the rig ever proving task improvement.
A/B for n=1 noise + 2-device envelope: flag-off baseline vs L1-on **back-to-back on
the same device in the same session** (controls fling variance), ≥3 rounds per arm
per device (iPad mini 7 en/HK **and** zh), require Δ > the observed run-to-run band
(`nav_proxy` already swings 0.808–0.840, so demand Δ>~0.05 **and** a strictly higher
`entered_graph` median), report medians not a single pair. `make check` (smoke +
regression gate) green, then nightly rig `make regression-compare` at non-zero
tolerance. After each rig run, validate the report plus persisted UTG with:

```
python -m skills.regression.ios_settings.state_machine_acceptance \
  "$IOS_SETTINGS_REPORT" \
  --memory-dir "$GLASSBOX_MEMORY_DIR" \
  --require-sidebar-exhaustive \
  --min-detail-to-root-edges 0
```

The wired entry point runs the **B-arm** (projection on + acceptance asserted):

```
make ipad-settings-state-machine IPAD_SETTINGS_REPORT=artifacts/ios_settings/candidate_enHK.json \
  IPAD_SETTINGS_EXTRA_ARGS='--language en --region HK'
```

Run the flag-off **A-arm** through the same target by overriding two make
variables — turn the projection off **and** empty the acceptance flags (with the
flag off no `settings/root` node is projected, so the structural assertions would
fail by construction). Use a distinct report path so the two arms get isolated UTG
stores and do not cross-pollute:

```
make ipad-settings-state-machine IPAD_SETTINGS_ROOT_PROJECTION=0 IPAD_SETTINGS_ACCEPTANCE= \
  IPAD_SETTINGS_REPORT=artifacts/ios_settings/baseline_enHK.json \
  IPAD_SETTINGS_EXTRA_ARGS='--language en --region HK'
```

Repeat both arms for `--language zh --region CN`, ≥3 rounds per arm per locale,
back-to-back on the same device. (Override via make **variables**, not a shell env
var: the recipe sets `GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` explicitly from
`IPAD_SETTINGS_ROOT_PROJECTION`. For an English greater-China sidebar that shows
`WLAN`, `--language en --region CN` works the same way.)

This gates the specific state-machine claims: root projection exists and collapses,
`entered_graph` is fed by successful `root→detail` edges, optional return replay has
`detail→root` evidence, and L2b only accepts sidebar absence when
`sidebar_exhaustive` is present.
Raise `--min-detail-to-root-edges` only for a rig scenario that exercises
return-required states; steady iPad split-view root taps do not require a physical
detail-to-root return edge.

**New test that does not overfit:** ⟦review-2 2026-05-31⟧ the test must assert the
*write-model* mechanism (detail 3), **not** a classifier kind that contradicts the
discriminator (detail 1). Concretely: feed a captured steady-state split-view frame
(sidebar present, detail pane *showing* a page) **followed by a sidebar-row tap**, and
assert that (i) the resulting **tap edge's `from_id` resolves to the single root node**
(root-*sourced* — the real gap; 0 of 38 today), and (ii) the root node collapses to
**one** signature across several different co-visible detail pages (detail 2). Add a
negative test (a search-overlay frame must NOT produce a root projection). ⟦review-4
2026-05-31⟧ **Bind directly to the chosen mechanism (a):** assert that a *single*
split-view `observe()` yields **both** a root projection node *and* a detail node, and
that the `from_id` selection is **action-typed** — the sidebar-row tap edge sources from
root, while a within-detail action (scroll / in-page tap) on the same page sources from
detail. Do **not** assert that `classify_ipados_scene` returns `kind=settings_root` for a
page-showing frame — that would bake in the empty-pane discriminator detail 1 rejects —
and do **not** assert an exact node count.

**The in-flight sidebar-absence patch: do NOT ship it standalone.** Sidebar-absence is
the very signal that distinguishes the root/non-root composite states; it belongs
*inside* L1/L3a's ⟦review-4 2026-05-31⟧ **projection/context write-model** (sidebar
present ⇒ root context, per L1 detail 3 — **not** a scene-kind value), where it also
fixes C3. Shipping it alone adds a sixth band-aid to the seam L1
reorganizes, and L2 makes it redundant.

## 5. Relationship to the shipped local patches

Already in tree: locale-fuzzy resolution (default-on),
`settings_search_recovery_decouple_exempt` (Part A, default-on, rig-validated 5/5),
Fix 3a/3b + memory-return Option 3 (default-off), L1 root projection
(`GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION`, default-off), L2a static/profile +
graph-entered root skip, and the L4 row-tracked sidebar wheel first move. These are
correct tactical or structural moves; the map now leaves rig A/B as the remaining
acceptance step before declaring the state-machine work complete.

⟦review⟧ **iPhone parity & the FSM invariant — reconcile before L2 relies on it.**
iPhone's `classify_ios_scene` already mints `page_id="settings/root"` for the genuine
*full-screen* root (`ios/scene.py:179`). L1 mints the **same** `page_id` for an iPad
*composite* (sidebar+detail) state. Runtime routing is iPad-only
(`platforms.py:188-193`), so no live cross-firing — but any device-agnostic
graph-finder / memory-return / coverage logic now treats a co-visible-composite root
and a full-screen root as the same semantic id, and the `screen_state_fsm.md`
invariant *"root = no forward parent"* is **violated** by an iPad root reachable by
forward taps from detail pages. Decide whether the FSM doc gets one shared,
device-aware root definition.

⟦review⟧ **"Un-reverts the intent of Option-1 without its breakage" is not yet
substantiated.** ⟦review-2 2026-05-31⟧ The reverted Option-1 experiment showed that
*creating* root nodes is not by itself sufficient — its nodes fragmented (15) and
recognize/replay never fired. (This is Option-1's lesson, **not** commit `678fbcc`,
which is the unrelated Option-3 back-edge replay fix.) L1 must show how it clears the
`min_success_rate=0.5` + `allowed_actions={'home','back'}` replay gate on a single
collapsed root node; until an A/B demonstrates that, treat it as an open claim, not a
settled subsumption. (All
evidence here remains single-device / n=1 / Settings × 2-device envelope — do not read
any of it as task success.)
