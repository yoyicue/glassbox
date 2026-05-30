# Design — iPad Settings navigation state machine (map + architecture levers)

Status: **map, not yet implemented (2026-05-30).** Produced after a long series of
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

## 1. The empirical state machine

### States — the split-view structural truth

The classifier (`glassbox/ipados/scene.py:classify_ipados_scene`) can emit 9 scene
kinds, but on the real device the UTG only ever persists **two**:

| run | nodes | settings_detail | settings_search_results | **settings_root** |
|-----|-------|-----------------|--------------------------|-------------------|
| r1 | 43 | 33 | 10 | **0** |
| r2 | 36 | 30 | 6 | **0** |
| r3 | 35 | 29 | 6 | **0** |
| r4 | 38 | 30 | 8 | **0** |
| r5 | 37 | 30 | 7 | **0** |

**There is no root state, and it is dead code, not a data gap.** `ipados/scene.py`
*does* contain a branch that mints `settings_root` / `page_id="settings/root"`, but
it is guarded by `if title and detail_evidence: → settings_detail … else →
settings_root`. On iPad split-view the sidebar and detail pane are **always
co-visible**, so the detail pane essentially always yields a title + evidence, the
`settings_detail` branch always wins, and the `settings_root` branch is
**structurally unreachable in steady state**. 0 of 189 persisted nodes across 5
runs are root.

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

Reliability by op (edge `success_rate`): `type` 100% › `scroll_wheel` 80–83% (with
heavy `no_progress` backpressure) › `tap` 72–82% › `back` 50–75% › `key` 17–67% ›
`long_press` 20–50%. **100% of self-loops record success_rate=0.0** (e.g. r1 17/17)
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
  待机显示/紧急SOS) each fail 5× and exist only to *confirm device-unavailability*
  for roots genuinely absent on a no-SIM iPad. Fix 3b and Part A both patch this
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
  settings_root` always returns False. Part B was reverted because it lands here;
  the revert was correct, but the model defect remains — the memory call site is
  vestigial.
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
**Removes C1; unblocks C5 + RETURN-TO-ROOT. Keystone; small, read-only, low risk.**
Define the root as the composite state `(sidebar present, not in search overlay)`,
independent of the detail pane's title: in `ipados/scene.py`, decouple
root-detection from `_detail_pane_title` and mint a stable synthetic root identity
(`page_id="settings/root"`) that every sidebar-row tap sources its edge from. The
`_settings_root_node_ids` query is already correct (it matches kind + page_id), so
once the classifier mints root nodes the finders populate immediately. This makes
`root→detail` edges real, so coverage (L2) has a source node and the memory path
can replay. **Subsumes:** the dormant `via_memory` path becomes live and correct
(un-reverts the *intent* of Part B without its breakage).

### L2 — Graph-authoritative coverage with explicit device-availability (model)
**Removes C5 + C2.** Once L1 gives root→child edges: coverage = "every sidebar root
row has a successful `root→detail` edge"; chase only unexplored outbound root
edges. Add a first-class `device_unavailable` label distinct from `missing`: a root
the sidebar walk never surfaces AND with no hardware affordance is unavailable
*from the graph/device profile*, not re-confirmed by SEARCH every run.
**Subsumes / retires:** the futile SEARCH for the 4 device-unavailable roots; the
**in-flight sidebar-absence patch** (becomes a modeled root↔non-root transition);
most of **Part A** (search no longer load-bearing); **Fix 3b** (sidebar-direct
becomes the primary path; "search failed → try sidebar" inverts to "graph says
reachable → walk sidebar; never search").

### L3 — Decouple root/detail identity from the OCR title; stabilize signatures (model)
**Removes C3 + C4.** Make scene-kind a function of structural evidence (sidebar /
detail-pane / search-overlay presence) and set `safe_actions` from the kind, not
from `title` presence — kills the recovery oscillation. Make detail-page signatures
title-anchored + scroll-invariant (canonicalize OCR variants) so `settings/Camera`
is one node, not five — the precondition for L1/L2 to accumulate trustworthy
evidence. **Subsumes:** Fix 3a (breadcrumb-reject) is a symptom of title-driven
misclassification; once kind is structural it is largely unnecessary.

### L4 — Deterministic row-state-tracked sidebar scrolling (mostly local)
**Raises the WALK ceiling (the real source of "missing").** The 11/12 ceiling is
momentum-fling overshoot (`scroll_wheel no_progress=10`); iPad has precise wheel
scroll (see `picokvm_ipad_wheel.md`). Track sidebar row geometry per tick and
scroll to *land on* the next unentered row instead of fling-and-reset. Then SEARCH
is invoked only for genuinely-search-only roots (≈none on this device).

### Stays a local patch (do NOT promote)
BOOTSTRAP's multi-fallback; AssistiveTouch back-gesture flakiness in RETURN-TO-ROOT
(hardware reality); per-device availability facts (蜂窝网络/钱包 = device-profile
data consumed by L2).

## 4. What to do next

**First move: L1** — give iPad a real `settings/root` node (composite-state
definition in the classifier; the graph-finder query is already correct). It is
the keystone: small, read-only, removes C1, and is the precondition for L2 + the
live memory path. Validate by re-running `exempt_5round` and confirming the node
census flips from `0 root nodes` to non-zero with real `root→detail` edges — that
single metric proves the model defect is closed.

**The in-flight sidebar-absence patch: do NOT ship it standalone.** Sidebar-absence
is the very signal that distinguishes the root/non-root composite states; it
belongs *inside* L1/L3's structural scene-kind definition (sidebar present ⇒ root
context), where it also fixes C3. Shipping it alone adds a sixth band-aid to the
seam L1 reorganizes, and L2 makes it redundant.

**Sequence: L1 → L2 → L3 → L4.** L1+L2 together retire the futile SEARCH, the
sidebar-absence patch, and Part A's relevance, and re-activate the memory path; L3
stabilizes the graph those depend on; L4 raises the WALK ceiling so SEARCH
approaches zero invocations.

## 5. Relationship to the shipped local patches

Already on `main` (flag states as of 2026-05-30): locale-fuzzy resolution
(default-on), `settings_search_recovery_decouple_exempt` (Part A, default-on,
rig-validated 5/5), Fix 3a/3b + memory-return Option 3 (default-off). These are
correct and safe as tactical guards, but the map shows most are band-aids on
C1/C2/C3; **L1+L2 are the structural fixes that make them non-critical.** Do the
model work before adding more guards to the same seams.
