# Design — Screen-state FSM as the authoritative navigation model

Status: **design / proposal**. Ties together three open goals
(`inert_row_detection`, `scene_detail_misclassification`, and the coverage/
efficiency work) under one model.

## Motivation

Every hard bug this cycle came from **reasoning over a single frame**:
- a detail page mislabeled `springboard`/`unknown` (WLAN, Bluetooth, Action Button);
- "is this row inert?" answered by a risky tap-probe or a `"No SIM"` text hack;
- wasted multi-pass re-scans because "missing" was judged per-frame.

The fix the research points to (Android/iOS nav principles; state-aware GUI
agents, Agent-SAMA arXiv 2505.23596): model the app as a **finite state machine**
— screens are states, actions are transitions — and let the graph **corroborate
or override** fragile single-frame heuristics.

## What already exists (don't reinvent)

glassbox's UTG / screen-memory (`glassbox/memory/`) is a partial FSM:
- **States** — `ScreenNode` (signature-keyed `screen_id`, `elements`,
  `scene_type` + `semantic_scene_type` + `classification_source`, `visit_count`).
- **Transitions** — `ScreenEdge(from_id, to_id, action_op, element_key, count,
  success_count, no_progress_count, overshoot_count, success_rate)`.
- **Ops** — `observe(node, action)` accrues edges; `recognize(scene)` maps a frame
  to a known node; `path_to_page(...)` routes via edges (used today for
  return-to-root); `locate(screen_id, element_key)` recalls geometry.
- Persisted per app/layout, drift-invalidated.

So we have nodes, edges, success/no-progress counts, and routing. What's missing
is **using the graph as the authority**, not just a return-recovery aid.

## Core idea

Promote the UTG to the primary source of truth for three questions the crawl asks
every step — **classification, interactability, coverage** — with the single-frame
heuristic as the cold-start prior, refined by graph evidence as confidence grows.

| Question | Single-frame (today) | FSM signal |
| --- | --- | --- |
| Is this root or a pushed detail? | body-text heuristics (fragile) | **inbound edge**: reached by a forward tap from root ⇒ detail; root is the node with no forward parent + the back-affordance rule |
| Is this row interactive? | tap-probe / "No SIM" text | **edge shape**: `tap X` whose `to_id == from_id` (self-loop) with rising `no_progress_count` ⇒ inert — no text, no extra tap |
| Which sections are covered / left? | per-frame "missing" + multi-pass | **graph reachability**: root's child nodes already reached = covered; only *unexplored* root edges remain |

Key point: the **transition that produced a screen** disambiguates it. WLAN read
as "springboard" is corrected because the edge says `settings_root --tap(WLAN)-->
this`, so it must be a detail child — regardless of the frame heuristic.

## Design decisions

1. **Node identity (the hard part).** Screens must map to stable `screen_id`s
   despite OCR noise and dynamic content (Bluetooth device list, Battery %,
   clock). The signature must be **structural** (layout/affordances/title), not
   content. Over-split (same screen → many nodes) and over-merge (distinct screens
   → one node) are the classic UTG failure modes; guard both with a
   distinct-screens test set. (Reuse/strengthen `memory/signature.py`.)

2. **Kind inference = prior + graph, with source tracking.** Compute
   `semantic_scene_type` by combining: (a) single-frame classifier (cold-start
   prior), (b) **back-affordance present ⇒ detail** (the canonical nav signal,
   per research), (c) **graph position** (reached by forward tap from root ⇒
   detail; reached by `home`/`back` ⇒ ancestor). Record `classification_source`
   (`frame` / `utg` / `affordance`) + `classification_evidence` so it stays
   auditable (the schema already has these fields).

3. **Interactability as an edge property.** A node-row is `interactive=False` once
   its tap edge is a self-loop with `no_progress_count ≥ k` (k≥2 to ride out a
   flaky tap; the existing multi-pass supplies the retries). Generalises the
   no-SIM hack and the tap-probe to *any* inert row, locale-agnostic, no extra
   taps. Feeds the existing `entry_exempt_sections` seam.

4. **Coverage & exploration from the graph.** Coverage = root children reached;
   the crawl chases only *unexplored* outbound root edges and stops when none
   remain (subsumes the multi-pass reset + the device-unavailable exemption).

5. **Confidence / cold-start.** Empty graph (first run) ⇒ fall back to single-frame
   heuristics and learn. Within a run and across runs (persisted), graph evidence
   takes over as `count`/`visit_count` grow. Never let a 1-observation edge
   override a confident frame signal.

## Phasing (each independently shippable, ordered by leverage/risk)

1. **Inert rows from edges** — use existing `no_progress_count` + self-loop to set
   interactability; retire the `"No SIM"` text hack. Smallest, leverages existing
   edge data, resolves `inert_row_detection`.
2. **Kind from graph + affordance** — set `semantic_scene_type` from back-affordance
   + inbound edge; resolves `scene_detail_misclassification` robustly. Keep frame
   classifier as cold-start prior.
3. **Graph-driven coverage/exploration** — replace per-frame "missing" + multi-pass
   with reachability over unexplored root edges.

## Risks / constraints

- **Identity instability** is the make-or-break; needs a real distinct-screens
  fixture set before trusting graph-derived decisions.
- **Read-only**: the FSM is learned only from the crawl's legitimate actions —
  never speculative taps to "explore" (a mis-tap can change state).
- **Honesty**: graph-derived classification/coverage must record source +
  evidence and stay reportable; never hide a real failure as "inert/known".
- **Cold-start**: first-ever run on a layout has no graph → must degrade exactly
  to today's single-frame behavior.

## Relationship to existing goals

- `inert_row_detection` → Phase 1.
- `scene_detail_misclassification` → Phase 2.
- coverage/efficiency (no-SIM exemption already shipped) → Phase 3 generalizes it.
