# Goal — Stop mis-classifying real Settings detail pages

Status: **open / ready to pick up**. Found 2026-05-24 while auditing drill-down
screenshot evidence.

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

## Suggested approach

- **Fix #1 (ordering / false-springboard):** make `_looks_like_springboard`
  stricter, or require "not a Settings surface" first. A detail page has a single
  top-left back chevron + a section title + grouped rows — that should veto
  springboard. Mirror the Today-widget fix (positive springboard evidence:
  dock + page-dots + app-grid, not just an icon grid).
- **Fix #2 (detail recall):** broaden detail recognition beyond text markers —
  a top-left **back chevron** in the nav-bar band is strong positive evidence of
  a pushed (detail) page, even when the body is sparse/visual (Action Button
  carousel). Combine "has back affordance + not root + not springboard" ⇒ detail.

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
