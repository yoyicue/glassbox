# Design — `settings_detail` false positives: arbitration, veto & abstain

Status: **analysis + proposal (not yet implemented), 2026-06-02.** Captures the
diagnosis of the App-Store-HOME-→-`settings_detail` misclassification surfaced on
the en-HK iPad rig, plus the verdict on three candidate levers (deterministic
arbitration, screen-memory prior, async VLM). No code changed yet.

This is the **dual** of `docs/goals/scene_detail_misclassification.md`: that goal
fixed the *false negative* (a real Settings detail page read as
`springboard`/`unknown`) by adding a Settings-detail veto *before*
springboard/unknown. This doc is the *false positive* the same aggressiveness now
produces — a non-Settings app page read *as* `settings_detail`.

Related: `docs/design/screen_state_fsm.md` (UTG-as-authority),
`docs/design/recognition_to_action_pipeline.md`, `docs/design/screen_memory.md`.

> **Line-number snapshot.** All `file:line` references are as of `3ca3861`
> (branch `docs/goal-ocr-vision-levers`). They drift; re-derive with the
> generator commands in [§7](#7-how-to-re-verify-the-claims-in-this-doc) rather
> than trusting the numbers. Symbol names are the durable anchors.

---

## 1. Symptom

On a read-only A/B over the App Store HOME page, both arms classified it as
`platform_scene_kind=settings_detail`, `page_id="settings/Apps"`,
`confidence=0.78`, `evidence=["center_title_or_back","detail_rows"]`. The 17
`scn_*.json` dumps from the bug run
(`artifacts/run_2026_06_01_16_31_30_695846/scenes/`) are all misclassified the
same way and form a ready offline corpus.

## 2. Root cause

`classify_ios_scene()` (`glassbox/ios/scene.py`) is a **first-match heuristic
cascade**: the first branch whose predicate fires returns, and ordering *is* the
arbitration. App Store HOME falls through every earlier gate to the **generic
Settings-detail fallback** `_looks_like_settings_detail` (returned at
`scene.py:289-297`).

That fallback's `has_settings_copy` check (`scene.py:782-790`) accepts the **bare
token `"App"`** (and `"Apple"`) as Settings evidence:

```python
or any(marker in _text(el) for marker in ("iPhone", "Apple", "Siri", "隐私", "默认", "App"))  # scene.py:787
```

App Store is saturated with `App`/`Apps`/`Apple`. Combined with a top "title"
(the **Apps** tab), long copy rows (card descriptions), and left-aligned rows, all
of the fallback's structural conditions are trivially met → `settings_detail`.

There is already a guard for exactly this: `strict_settings_detail` (CUQ-2.6)
requires a Settings-*specific* anchor (a system noun like Wi-Fi/Bluetooth/Face ID,
or a "了解更多"/Learn-More footnote) via `_has_settings_distinguishing_signal`. But
it is **dormant on the live path** — the feature flag defaults False
(`config.py:484 strict_settings_detail: bool = False`) and `classify_ios_scene`
is called without it. So the over-broad non-strict fallback is what runs in
production.

## 3. Why this is harmful, not cosmetic

`settings_detail` emits `safe_actions=(back, edge_back)`. Downstream, that tuple
is a **license to act**, and nothing re-checks confidence or task context before
acting (the `IOSSceneClassification.confidence` docstring explicitly warns callers
*not* to threshold it; grep confirms no consumer does).

The harmful chain (all on the PicoKVM iPad path):

1. `phone.py:_picokvm_back_context` (`phone.py:1096`) sees
   `safe_actions ∋ back` **and** `platform_scene_kind == "settings_detail"` and
   returns `(True, "platform_settings_detail", _inferred_ios_nav_back_point(...))`
   (`phone.py:1109`).
2. `_inferred_ios_nav_back_point` returns a **blind** top-left coordinate
   `round(w*0.09), round(h*0.09)` (`phone.py:1159`) — no real element required.
3. `system_navigator.back_gesture` (`system_navigator.py:34`) reads that context
   (`:46`) and **actually taps it**: `host.effector.tap(px, py)`
   (`system_navigator.py:60-65`).

On the App Store Today/Apps tab, the top-left ~9%×9% is **content** (a story card
or the account avatar). So "back" navigates *into* content or opens the account
sheet, and the guard records success because a tap landed. Two more downstream
amplifiers:

- `target_planner.picokvm_settings_row_tap_point_for_element` remaps App Store row
  taps into a Settings **column geometry** (gated on `page_id.startswith("settings")`
  / `tap_root_row`).
- `memory/graph.py:_merge_scene_fields` persists `page_id=settings/Apps`,
  `platform_scene_kind=settings_detail`, `safe_actions` onto a **new** UTG node,
  poisoning future recognition (and, because the Settings regression run pins
  `GLASSBOX_MEMORY_BUNDLE=com.apple.Preferences`, the phantom node lands in the
  *real* Settings UTG file).

**The "good output" requirement, therefore:** never attach the `(back, edge_back)`
license unless a Settings-specific anchor is present; and never set a
`settings/*` `page_id` unless Settings is proven — because `target_planner` and
`memory` key on it.

`unknown` is the demonstrably-safe sink: its `safe_actions=(trace, vlm_on_uncertain)`
does **not** intersect `{back, edge_back}` (so the bad tap is suppressed), and
`unknown` is the kind the climb-out / recover-Home / re-foreground-the-app
machinery is tuned for (`ios/springboard.py:_opened_expected_app_or_recover`,
`ios/recovery.py:should_foreground_target_app_instead_of_back`).

## 4. Best practice (external consensus, mapped to glassbox)

The literature has moved away from a single first-match cascade. The transferable,
**OCR-only / free / deterministic** ideas:

- **Evidence arbitration over competing hypotheses** — accumulate weighted
  positive *and negative* evidence per candidate kind; pick the max only above a
  margin, instead of "first `if` wins."
- **Selective prediction / reject-option (ABSTAIN)** — emit `unknown` when no
  hypothesis has a class-specific anchor (Chow's reject rule; risk-coverage). The
  recurring warning: heuristic/softmax confidence is **mis-calibrated and
  overconfident out-of-distribution** — App-Store-under-a-Settings-classifier is
  exactly that. glassbox's `0.78` is a hand-tuned heuristic, not a probability, so
  gate on **anchor presence/absence**, not on the number.
- **Open-set rejection with negative (veto) evidence** — tokens incompatible with
  a class subtract from it. App Store chrome (Today/Games/Apps/Arcade/Get/In-App
  Purchases) should veto Settings. This generalizes the veto pattern already in
  `scene.py` (paywall→unknown, weather→unknown, GlassboxHelper console guard).
- **App "chrome" as a structural prior** — a bottom tab bar with specific labels
  is a higher-signal identity than body copy; detectable from OCR geometry alone.
- **Confidence-gated escalation (FrugalGPT / adaptive routing)** — cheap
  deterministic layer first; escalate to a billed VLM *only* on abstain. Maps onto
  glassbox's opt-in VLM design.

Heavier pure-vision parsers (OmniParser / Set-of-Marks / learned screen
embeddings) are **contrast/escalation references, not the hot path**: they require
a finetuned model or a VLM and mostly reconstruct an element list rather than emit
a cheap page-type label — the two things glassbox deliberately avoids by default.

> Source caveat (doc discipline): the survey was done with WebFetch blocked, so
> page bodies were not read. The *concepts* above are well-established and safe to
> rely on; **do not** transcribe specific paper IDs or benchmark percentages into
> this repo without re-verifying them against the primary source first.

## 5. Recommended fix — incremental arbitration, **not** a rewrite

Codex's instinct (arbitration + veto + abstain) is the right *direction*, but a
full rewrite of the cascade into a scorer is the wrong *scope* and the riskiest
way to ship it. The cascade encodes hard-won precedence a flat scorer would
silently lose: `harness_console` must win unconditionally (else the agent taps its
own runtime), the paywall/weather vetoes, and ~10 specialized `settings_detail`
sub-recognizers each tuned against the **same 5 committed recall fixtures**
(`view_0002/0007/0012/0025/0029`). A rewrite re-routes all 5 through new logic for
no added benefit — they enter via the *earlier* `semantic_guess` branch, not the
buggy fallback, so a **targeted** fix has near-zero recall risk.

Minimal, in-core, default-on sequence (all OCR-only / free / deterministic —
"fix the core, not the skill"):

- **Step 0 (proof first).** Add the offline smoke assertion in §6 *before*
  touching the classifier. Without it, `make check` proves nothing here (§6).
- **Step 1a — VETO.** Before the generic fallback (`scene.py:289`), check an App
  Store / commerce-chrome token set (Today/Games/Apps/Arcade/Get/In-App Purchases,
  `$`-prices, bottom tab-bar signature). On hit → `unknown`, evidence
  `("appstore_chrome",)`, `safe_actions=(trace, vlm_on_uncertain)` — **not**
  `(back, edge_back)`. This alone closes the bug and removes the license-to-act.
- **Step 1b — ANCHOR.** Drop the bare `"App"` from the `has_settings_copy` marker
  list (`scene.py:787`) so it no longer counts as Settings evidence. This is the
  precise root token.
- **Step 1c — ABSTAIN.** When the fallback would assert `settings_detail` at 0.78
  with no Settings-specific anchor, return `unknown` instead (the safe sink, §3).
- **Step 2 (optional, rig-gated).** Flip `strict_settings_detail` ON for the live
  path — it already exists and is tested. But it is a global default and may cost
  recall on real Settings pages whose only signal is generic body words; validate
  on-rig first. Step 1 closes *this* bug without that global risk, so treat Step 2
  as a separate decision, not a prerequisite.
- **Step 3 (only if needed).** `unknown`'s last-resort branch (`phone.py:1131`)
  still blind-taps a chevron — benign on real iOS sub-pages, a misfire on App
  Store. If on-rig runs show App Store should be *re-launched* rather than backed
  out of, add a positive `kind="app_store"` that
  `recovery.should_foreground_target_app_instead_of_back` treats like
  `springboard` (re-launch, don't Back).

## 6. How to verify (the verification ladder)

- **Tier 1 — offline golden/smoke (NEW test, EXISTING harness — load-bearing).**
  Add a test to `skills/smoke/test_ios_scene.py` asserting App Store HOME tokens
  (Today/Games/Apps/Arcade/$12.99) classify `kind != "settings_detail"` (post-fix
  `== "unknown"` with a veto-evidence token). Copy the paywall test pattern
  (`test_ios_scene.py:307-335`, which asserts `kind == "unknown"` + an evidence
  token). **Pair it with a recall guard:** confirm the 5 real `settings_detail`
  fixtures (parametrized test at `test_ios_scene.py:92-100`) still classify
  correctly. A strict-vs-non-strict paired pattern already exists to mirror
  (`test_ios_scene.py:423-435`).
- **Tier 2 — offline corpus replay (NEW test + NEW fixtures).** Harvest the 17
  `scn_*.json` from the bug run into `skills/golden/ios_scene/` (`artifacts/` is
  gitignored, so the raw dumps cannot be the gate). Note the box-shape adapter:
  scene dumps use `{x,y,w,h}`, the golden loader expects `[x,y,w,h]`.
- **Tier 3 — on-rig A/B (EXISTING harness, INDIRECT).**
  `skills/regression/ios_settings/ab_matrix.sh` raw_no_canonical arms; read
  `task_completion / entered_graph / root_sigs / required_missing` via
  `ab_extract.py`. Because the harness measures **Settings coverage**, an
  App-Store-as-Settings fix shows up only indirectly (fewer spurious settings/Apps
  nodes / cleaner UTG). Treat Tier 1/2 as the primary proof.

> **Do NOT claim `make check` proves the fix.** The offline regression-gate never
> calls `compare` on a fresh run and the committed floor has
> `task_completion=0.0`, so it stays green even when the live classifier path is
> broken (see `glassbox-honest-gate-first-strategy` / the
> `test_computer_use_regression_gate.py` docstring). The new deterministic
> assertion in `test_ios_scene.py` is the honest, load-bearing proof.

## 7. Why **not** memory, and why **not** async VLM (for this bug)

**Screen-memory (UTG): real-but-later, not for this bug.**
- Memory is a strictly downstream **consumer**: `apply_scene_classifiers` runs
  *before* `observe_memory` every frame, and there is **no** memory→classifier
  feedback edge anywhere.
- Bootstrap circularity: App Store HOME has never been seen under a correct label,
  so `recognize()` has nothing to retrieve on the first visit — and that first
  mislabeled frame **mints a poisoned node** (`graph.py:_merge_scene_fields`).
- Scoping circularity: `_node_scope_matches` filters candidates by `page_id`, so a
  frame mislabeled `settings/Apps` is steered *toward* Settings nodes and away
  from any true App Store node.
- The one genuinely useful fact: `compute_signature` (`memory/signature.py:49-65`)
  is purely **structural** (stable_texts + type_histogram + phash) and does **not**
  key on the poisoned `page_id`/`platform_scene_kind` on the iOS hot path — so App
  Store and real Settings have *different* signatures despite sharing the wrong
  label. A structural prior *could* separate them — but only if wired, un-gated,
  and after a trusted node exists. Undercut further by the open
  `list_item → volatile → dropped-from-stable_texts` drift hazard (both screens
  are list-dominated; discriminating rows get stripped — see
  `docs/goals/ui_element_layout_segmentation.md`).
- Cheap, generic hardening worth doing *anyway* (not for this ticket): gate the
  semantic-label write in `_merge_scene_fields` behind multi-visit corroboration so
  one bad visit cannot poison the graph; add discriminative app-chrome tokens to
  the signature.

**Async VLM: no — over-engineering for this class of error.**
- **Turning the VLM on today does not fix it.** `platform_scene_kind`/`page_id`
  (the misclassified fields) are written *only* by the OCR heuristic. The VLM
  produces `source="vlm"` carrying only `semantic_scene_type` (soft Layer-3); it
  is not a platform classifier, and last-write-wins among platform classifiers
  keeps `settings_detail` (`cognition/contracts.py` projector;
  `cognition/vlm_kimi.py`). So `GLASSBOX_ENABLE_VLM=1` leaves the bug *and* the
  harmful `safe_actions` intact.
- **Async is net-new infrastructure.** There is **zero** `asyncio`/
  `concurrent.futures` in `glassbox/`; all VLM calls are blocking ~8.5–20s HTTP.
  An async relabel would need a background runner, a brand-new path for a VLM
  verdict to write `platform_scene_kind`/`page_id` onto a UTG node (impossible
  today), and activation of the **inert** `vlm_on_uncertain` safe-action (it is
  referenced only as a literal in `ios/scene.py` / `ipados/scene.py` and in tests
  — never dispatched by runtime code).
- **The screen is not VLM-shaped.** It is text-saturated with the exact veto
  chrome and lacks any Settings anchor; a rule resolves it for free. Empirically,
  reasoning VLMs add large token/latency cost for marginal/negative GUI-agent
  gains and can themselves mislabel a dense store page.

**When an opt-in VLM *does* earn its cost** (out of scope for this bug, and only
*after* the net-new plumbing): genuinely under-determined screens (icon-only /
unlabeled custom chrome / look-alike pages no token can name); high-stakes
irreversible actions (risk-escalation); latency-critical VLM-ON profiles using
speculative "act-now / verify-async / rollback-on-disagreement." Even then the
role is **VLM-as-verifier/tie-breaker firing only on the deterministic
arbitrator's ABSTAIN** — never VLM-as-primary — plus a node-keyed cache (bill once
per new screen) and resolving the layout-seg signature-instability hazard first.

## 8. How to re-verify the claims in this doc

```bash
# Root token + fallback branch
rg -n 'marker in _text\(el\) for marker in' glassbox/ios/scene.py        # the bare-"App" line
rg -n 'center_title_or_back|_looks_like_settings_detail|strict_settings_detail' glassbox/ios/scene.py
rg -n 'strict_settings_detail' glassbox/config.py                        # default False

# Harm chain
rg -n '_picokvm_back_context|_inferred_ios_nav_back_point|platform_settings_detail' glassbox/phone.py
rg -n 'picokvm_back_context|effector.tap|def back_gesture' glassbox/system_navigator.py

# VLM facts
rg -rln 'import asyncio|concurrent.futures' glassbox/                     # expect: (empty)
rg -rn 'vlm_on_uncertain' glassbox/ skills/                              # producers + tests only, no dispatch

# Memory facts
rg -n 'def compute_signature|stable_texts|type_histogram|phash' glassbox/memory/signature.py
rg -n '_merge_scene_fields|_node_scope_matches' glassbox/memory/graph.py

# Offline proof + corpus
rg -n 'app_paywall_is_unknown|strict_settings_detail|_scene_from_ocr_fixture' skills/smoke/test_ios_scene.py
ls artifacts/run_2026_06_01_16_31_30_695846/scenes/ | wc -l            # the 17-scene corpus
```
