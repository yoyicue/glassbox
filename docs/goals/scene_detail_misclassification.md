# Goal — Stop mis-classifying real Settings detail pages

Status: **P1/P2/P3 implemented; P4+ roadmap**. Found 2026-05-24 while auditing
drill-down screenshot evidence. Phased plan P1-P6 recorded below.

## Problem

`classify_ios_scene` (`glassbox/ios/scene.py:120`) mislabels real Settings
**detail** pages. In a live en-HK drill-down (`/tmp/drill_aftersim`, 35 captured
views) the scene types were:

```
13 settings_root   10 settings_detail   6 unknown   5 springboard   1 search_results
```

Several of the `unknown`/`springboard` frames are genuine detail pages
(pixel-verified):

| Page | view | wrongly labeled |
| --- | --- | --- |
| WLAN detail (network list, "Connect to WLAN…") | view_0002 | **springboard** |
| Privacy & Security detail | view_0029 | **springboard** |
| Bluetooth detail ("Connect to accessories…", Devices) | view_0007 | **unknown** (title=None) |
| Face ID & Passcode detail | view_0025 | **unknown** |
| Action Button detail (Silent Mode carousel) | view_0012 | **unknown** |

(The crawl still entered all of them — coverage's `_label_entered` keys on the
visit's detail *texts*, not scene_type — so this did not break this run. It is a
latent correctness risk, not a current outage.)

## Two failure modes

1. **False springboard.** Real detail pages (WLAN, Privacy) satisfy
   `_looks_like_springboard`, which is checked **before** the detail check
   (`scene.py:177` vs `:214`), so they never reach the detail classifier. Likely
   the icon-grid-ish network/row layout trips the springboard heuristic. This is
   the **same family as the already-fixed Today-widget-home misclassification** —
   a non-home surface read as springboard.
2. **Detail → unknown.** Sparse / visually-driven detail pages don't satisfy
   `_looks_like_settings_detail_body` (`scene.py:779`): Action Button is a dark
   image carousel with almost no text; Bluetooth shows a loading "Devices"
   spinner; Face ID has few rows. The body heuristic needs text markers they
   lack.

## Why it matters

- **Recovery / bootstrap** key on scene kind: `scene_looks_like_settings_detail`,
  `scene_is_settings_root`, `return_from_unknown_settings_state`,
  `return_from_settings_detail_state`. A detail page seen as `springboard` is the
  dangerous case — bootstrap/recovery could act as if on Home (e.g. try to open
  Settings) while actually inside a section.
- **Evidence/audit**: the wrong `scene_type`/`title` made the screenshot-evidence
  audit produce false gaps; any tooling trusting `scene_type` is unreliable.

## Best practices (researched 2026-05-24)

Industry/UX guidance converges on one canonical signal for this exact problem:

- **The presence/absence of a visible Back/Up affordance is THE heuristic for
  root-vs-pushed-detail.** A pushed detail view shows a back button; the app's
  home/root does not. (Android: "if a screen is the topmost one… it should not
  present an Up button"; iOS UINavigationController shows the back button once a
  VC is pushed.) This directly supports Fix #2 below and explains why our
  body-text heuristic is fragile — it ignores the canonical nav-bar signal.
- **Higher-end direction:** state-aware agents model screens as a finite state
  machine (each screen a state, actions as transitions) instead of reasoning only
  over the current frame. glassbox's UTG/screen-memory is a partial version; a
  detail-vs-root decision could also be corroborated by the transition that
  produced the screen (tapped a root row → expect a detail).

Sources: Android navigation principles (developer.android.com), iOS navigation
patterns (frankrausch.com / CodePath), and state-aware GUI-agent research
(Agent-SAMA, arXiv 2505.23596).

## Suggested approach (P1)

Do not keep adding page-specific `_looks_like_X_detail` rules. P1 should install
a small semantic fallback layer for ambiguous iOS scene classification:

- Keep deterministic fast paths and hard safety gates first: harness console,
  Settings root/search, system search, blocked safety, App Library, and the
  status-bar-clock guard.
- Before returning `springboard`, allow a **Settings-detail semantic veto** when
  the frame has Settings-detail structure/copy and lacks strong Home evidence.
- Before returning `unknown`, allow the same semantic fallback to classify sparse
  detail pages as `settings_detail`.
- Treat OCR-visible Back/Up affordance as strong detail evidence, but do **not**
  depend on it exclusively: the current 5 failing real frames have no OCR back
  affordance.
- Add a recovery safety belt: if recovery is about to treat a frame as
  `springboard/app_library`, but the semantic fallback says Settings detail, use
  the detail return path instead of `open_app_from_springboard`.

P1 semantic cues should be structural and language-aware, not one-off page
special cases:

- Settings detail intro pattern: left/top title plus descriptive copy such as
  `Connect to...`, `Control which apps...`, `Manage apps...`, `Learn more`.
- Settings nouns/rows: `WLAN`, `Bluetooth`, `Face ID`, `Passcode`, `Privacy`,
  `Location Services`, `Devices`, grouped left-label/right-value rows.
- Strong Home evidence remains a veto: bottom Home search pill, multi-column app
  grid, dock/page-dot evidence, or real App Library categories.

## Phasing

### P1 — Semantic Fallback For Current Bug

Implemented in current working tree:

- Persist the 5 real `/tmp/drill_aftersim.artifacts/views` OCR JSON files as
  smoke fixtures.
- Add a local semantic scene fallback (OCR text + geometry summary, no VLM by
  default) that can override only `unknown` or would-be `springboard` in
  Settings-like ambiguity.
- Add recovery safety belt so a Settings-like detail frame is not reopened as
  SpringBoard.
- Acceptance is the current goal's acceptance: the 5 real detail fixtures become
  `settings_detail`; existing real root/search/springboard tests do not regress.

### P2 — Transition Prior + Gated VLM Verifier

Implemented in current working tree:

- Add transition-aware evidence: if the previous verified action was
  `settings.tap_row` from Settings, the next changed screen has a strong prior
  of `settings_detail` unless Home/search/blocked evidence is strong.
- Add an opt-in VLM verifier only for conflicts/low confidence:
  `unknown + transition says detail`, `springboard + Settings-like cues`, or
  recovery about to open Settings from a suspicious SpringBoard frame.
- Cache by frame/OCR signature + transition label and bound calls per run.
- Record `classification_source` / evidence as `frame`, `semantic`,
  `transition`, or `vlm`.

### P3 — Graph-Authoritative Settings Model

Implemented in current working tree:

- Promote screen-memory/UTG evidence to the authority for Settings scene kind
  and recovery: `settings/root --tap_row(Bluetooth)--> node` is a detail edge
  unless strong evidence contradicts it.
- Derive root coverage from successful root outbound edges, not only per-frame
  text visits.
- Derive inert rows from repeated self-loop/no-progress edges instead of text
  hacks.
- Split into P3a graph-backed classification/recovery, P3b graph-backed
  coverage, P3c graph-backed inert rows, P3d persisted reuse across runs.

### P4 — Self-Improving Settings Navigation

- Mine real crawl traces for classifier conflicts, recovery loops, VLM
  disagreement, graph over/under-splitting, and new unseen page types.
- Generate small human-review labeling packs and turn approved labels into
  fixtures/golden tests.
- Allow learned or VLM-distilled classifiers to replace the P1 scoring fallback,
  while deterministic safety gates remain authoritative.
- Produce policy suggestions (aliases, blocked patterns, inert-row evidence),
  but require tests/review before shipping them.

### P5 — General GUI World Model

- Generalize from Settings to app-agnostic GUI state, controls, action effects,
  preconditions, recovery paths, and side-effect risk.
- Learn action-effect records from every run: `state + action + expected effect
  + observed state + verifier result + risk`.
- Introduce a formal risk taxonomy (`observe-only`, `navigation`, `idempotent`,
  `reversible`, `setting-changing`, `destructive`, `auth/payment/privacy`,
  `unknown`) and constrain planners to task-allowed risk.
- Transfer common GUI patterns across apps: list rows, details, tab bars,
  modals, forms, search, permission dialogs, and destructive confirmations.

### P6 — Verifiable GUI Agent Runtime

- Express tasks as declarative contracts with allowed risk, forbidden effects,
  success criteria, time/VLM budgets, and required artifacts.
- Make each agent step auditable: observation hash, policy authorization,
  predicted effect, action, actual effect, verifier result, recovery, artifact.
- Split specialized agents for perception, navigation, safety, recovery, QA, and
  review over a shared audited state store.
- Run continuous evaluation across offline fixtures, replay traces, simulator
  runs, real-device canaries, cost/latency regression, and unsafe-near-miss
  checks.
- Keep self-improvement human-governed: automatic fixture mining and candidate
  repairs are allowed; silent deployment of learned policy is not.

## Acceptance

- Re-classify the captured view set: the 5 pixel-verified detail pages above →
  `settings_detail`; true `settings_root` / real springboard / search frames
  unchanged (no regression).
- Build a small **labeled fixture set** from representative frames (persist a few
  out of `/tmp/drill_aftersim.artifacts/views`, which is ephemeral) so this is a
  smoke regression, not a one-off.
- No regression in the existing scene-classification smoke tests.

## Constraints

- Back-chevron detection must keep the status-bar-clock guard (see the already
  fixed clock→nav_back issue) so the clock is never read as a back affordance.
