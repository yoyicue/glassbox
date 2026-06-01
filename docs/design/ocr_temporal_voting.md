# OCR Temporal Voting

## Status

This is not a greenfield feature. The repository already has multi-frame OCR
voting:

- `glassbox.cognition.ocr_vote.vote_scenes(scenes, ...)`
- `Phone.perceive_voted(n=2, ...)`
- `Perceptor.perceive_voted(...)`

The existing path already samples multiple frames, OCRs each frame, clusters
elements by position, votes text per cluster with `vote_ocr_texts`, adds
`ocr_vote_frames:*` / `ocr_vote_samples:*` evidence, and returns a voted
`Scene`.

This document is a spike-and-decision design, not a commitment to make temporal
voting the primary fix. For Home and Settings, closed-set lexicon/spatial
recognition is likely the main repair. Temporal voting only covers the subset
where real, distinct frames show correctable frame-to-frame OCR disagreement.

The work here is therefore not "add an OCR fusion subsystem". The work is:

1. Measure whether temporal OCR voting helps the current PicoKVM/iPad noise.
2. If it helps, extend the existing `vote_scenes` path with the missing
   semantics: stable/transient split, degradation metadata, and safer geometry.
3. If it does not help, route the first target pages to lexicon/spatial
   constraints, because Home and Settings are mostly closed-set screens.

Default runtime behavior must not change until the measurement and A/B gates
below pass.

## Scope

The honest v1 benefit surface is narrow:

- in scope: iPad static screens at rest, especially Home and Settings;
- maybe in scope after measurement: App Store static chrome and lock-screen text;
- not in v1 scope: iPhone fling/overscroll paths after scroll or drag.

iPhone scroll paths often have overshoot and trailing motion. If a design
requires a globally stable frame before fusing, those paths will frequently
degrade to single-frame OCR while still paying extra checks. v1 should say that
plainly instead of implying broad iPhone benefit.

## Problem

`Scene` is consumed as stable screen evidence, but OCR on the PicoKVM/iPad path
can be noisy:

```text
口 Notes
No.Lvents |ouay
H:36°L917
330
```

The ownership boundary is correct: OCR noise handling should be centralized in
perception/cognition, not reimplemented independently in SpringBoard, Settings,
App Store, or other app logic.

However, multi-frame voting only fixes one class of error:

```text
same screen region + different OCR text across frames -> consensus can help
same screen region + same wrong OCR text across frames -> voting cannot help
```

If `口 Notes` is reproduced deterministically on every frame, voting returns
`口 Notes` repeatedly and adds cost without improving recognition. That class of
failure needs lexicon, spatial, preprocessing, backend, or VLM help.

## Blocking Measurement Spike

Before changing default perception behavior, run a measurement spike on real
PicoKVM/iPad frames.

### Capture

For each static screen, capture `N=10` frames without user interaction:

- iPad Home widget page.
- Settings root/sidebar.
- App Store Today page.
- Lock screen with notifications.

For each frame:

- save frame timestamp and frame id;
- save a lightweight image hash for de-duplication;
- run the current OCR backend;
- save raw OCR elements;
- record `frame_diff_ratio` between adjacent frames;
- record whether frame ids or image hashes repeat.

The spike must compute OCR disagreement on de-duplicated effective frames, not
on raw back-to-back samples. Repeated buffer frames are still useful evidence,
but only for capture-path viability, not for per-region voting rates.

### Region Analysis

Cluster OCR elements by the current `vote_scenes` matching first. For each
cluster report:

- number of frames in which the region appears;
- raw text variants and counts;
- normalized text variants and counts;
- OCR confidence distribution;
- box center/size drift;
- whether `vote_ocr_texts` changes the winner;
- whether the final winner is correct by human label;
- likely fix class: `temporal_vote`, `lexicon_spatial`, `volatile_latest`,
  `preprocess`, `backend`, or `vlm`.

### Output

The spike should produce a JSON/Markdown report:

```text
screen: ipad_home_widgets
frames: 10
distinct_frames: 8
global_frame_diff: p50/p95/max
clusters:
  - location: ...
    samples: 10
    variants:
      "口 Notes": 10
    vote_changed_text: false
    human_label: "Notes"
    temporal_voting_helped: false
    likely_fix: "lexicon_spatial"
  - location: ...
    variants:
      "待机見示": 3
      "待机显示": 5
      "侍机昰示": 2
    vote_changed_text: true
    temporal_voting_helped: true
    likely_fix: "temporal_vote"
```

### Decision Gate

Only extend default/high-value perception paths if the spike shows a non-trivial
per-region disagreement rate that voting corrects. The rate is computed over
distinct image-hash frames.

Suggested gate:

```text
effective distinct frames >= K for the target path
>= 10% of important text regions have frame-to-frame variants
and >= 50% of those variants are corrected by vote_scenes
```

Use `K=5` for the initial `N=10` spike unless the report justifies another
number. If a path cannot produce enough distinct frames, that is itself a
finding: the capture path cannot feed temporal voting reliably, so the next
step should be lexicon/spatial recognition, preprocessing/backend work, or a
real sampling policy.

If disagreement is near zero for the named failures, the next step is not
temporal voting. The next step is closed-set recognition.

## Alternatives And ROI

Temporal voting has roughly `N x OCR` cost. The first target screens have
cheaper and often stronger alternatives.

### 1. Closed-Set Lexicon + Spatial Constraints

Home and Settings are not open-ended text recognition problems:

- Home has a known app-label lexicon and icon-grid geometry.
- Settings root/sidebar has a known row lexicon and row geometry.
- App Store has stable chrome markers such as Today, Games, Apps, Arcade, and
  Search.

The repository already uses this style:

- SpringBoard uses fuzzy `_matches` in `is_ios_home_screen` and
  `find_springboard_icon`.
- Settings uses confusion-folded closed-set matching through
  `confusion_compact`/policy helpers.

This path can fix a deterministic single-frame read like `口 Notes -> Notes`
at 1x OCR cost, while temporal voting cannot fix it unless the correct text
appears often enough across frames.

Preferred v1 order:

1. Closed-set lexicon/spatial match for Home and Settings.
2. Temporal voting only where the spike shows real frame-to-frame OCR
   disagreement.
3. VLM reground only for unresolved ambiguous targets and only behind existing
   opt-in/billed VLM flags.

### 2. Locale-Bound Confusion Folding

Do not globally `casefold` or apply English assumptions. The default UI locale
can be zh-Hans, and the known failures include CJK visual confusions such as
`口/日` and `見/显`.

Policy:

- open-set generic text: use `norm_text`;
- closed-set CJK/UI labels: use a locale-bound `Normalizer` or
  `confusion_compact`;
- app-specific label matching: use the app/page lexicon with score and margin;
- no global casefolding in OCR voting.

### 3. VLM Reground

The repo already has VLM/reground hooks. VLM can answer icon semantics that OCR
does not expose, but it is slower and billed. It should remain opt-in and used
for ambiguity or cold-start map building, not as the default fix for every OCR
read.

### 4. Single-Frame Preprocessing

Before paying 3x OCR, measure whether one better frame helps:

- upsample/crop only the text region;
- sharpen or contrast-normalize small labels;
- retry OCR on a cropped row;
- compare backend parameters.

This is especially relevant when errors are deterministic across frames.

### 5. OCR Backend Choice

If a backend consistently emits the same wrong CJK/Latin prefix, temporal voting
will not repair it. Backend comparison belongs in the spike report before
promoting multi-frame voting.

## Stability Gate Caveat

The current stability primitive is `frame_diff_ratio < 0.005` in
`glassbox/perception/stable.py`. That is useful for avoiding animation/scrolling,
but it is not proof that OCR will vary.

There is a tension:

- strict global stability may imply identical pixels, and deterministic OCR over
  identical pixels gives identical wrong text;
- the existing `vote_scenes` docstring calls out a win case where the same row
  OCRs differently across repeated reads, often on screens with small motion or
  capture jitter.

The spike must measure this instead of assuming it. If useful variation appears
only in small local regions while the whole frame is mostly stable, the design
should move from a single global stability gate to local/region-level drift
metadata.

## Existing Implementation To Extend

Current implementation:

```text
Phone.perceive_voted(n)
  -> Perceptor.perceive_voted(n)
  -> snapshot n frames
  -> recognize_elements(frame) for each frame
  -> vote_scenes(scenes)
  -> return Scene(observation_mode="voted")
```

`vote_scenes` currently:

- clusters by nearest position with `pos_tol`;
- allows at most one element from each scene in each cluster;
- requires matching `UIElement.type`;
- votes text per cluster with `vote_ocr_texts`;
- includes elements missing from the first frame;
- encodes provenance in `UIElement.type_evidence`;
- scales confidence by member count / frame count.

This should remain the primary path. Do not add a third parallel voting stack
unless there is a measured reason that `vote_scenes` cannot evolve.

## Architecture Boundary

`perceive()` / `perceive_voted()` are acceptable orchestration points for this
work because they already own snapshot, OCR, typing, scene classification, and
recording. The implementation should still keep the algorithm as a perception
helper that consumes the existing OCR boundary:

```text
Frame -> run_ocr()/recognize_elements() -> UIElement samples -> vote_scenes()
```

If an implementation keeps the historical `OCRFusion` name or introduces a new
helper class, that helper is still only a perception-layer coordinator over OCR
samples. It is not a new OCR backend, not a new scene model, and not a parallel
voter.

Do not introduce a separate OCR backend wrapper or a second timeout mechanism.
Per-sample OCR timeout behavior should reuse `Perceptor.run_ocr`, including the
existing `GLASSBOX_OCR_TIMEOUT` watchdog. The voting helper may add an outer
sampling budget, but that budget only decides when to stop collecting samples
and degrade; it must not duplicate OCR cancellation logic.

Runtime wiring should be flag-gated and narrow:

```text
perceive_voted() continues to be the explicit multi-frame API
perceive() may call the helper only for validated paths and only when enabled
```

The fallback path remains the current single-frame `perceive()`.

## Sampling And Cost Budget

Current `Perceptor.perceive_voted` takes back-to-back `snapshot()` calls with no
explicit interval. On AVF/PicoKVM, frame spacing is determined by the source.
For PicoKVM this may be very short, and static screens may return duplicate
frames from buffers. A documented `window_ms=350` would be false unless the
implementation actually polls across that window and de-duplicates frames.

v1 should choose one of two honest policies:

1. Accept back-to-back sampling and rely on the measurement spike to prove it
   has diversity.
2. Add an explicit sampling policy: `sample_spacing_ms`, `max_attempts`,
   duplicate frame rejection, and timeout behavior.

Do not silently combine a "stable frame" requirement with a claimed time window.

### Fresh Snapshot Interaction

Post-action fresh verification may call `fresh_snapshot()`, which can reopen
the source. Taking `N` truly fresh frames by reopening the source `N` times is
expensive and can exceed one second. Taking one fresh frame and then two normal
snapshots may instead read buffered frames unless de-duplication proves they are
new.

The implementation must state which it does.

Recommended default:

- use at most one `fresh_snapshot()` per post-action verification;
- after that, poll `snapshot()` with frame-id/hash de-duplication if voting is
  enabled for that path;
- if fewer than two usable distinct frames are available, degrade to the latest
  single-frame scene and record why.

### Timeout Semantics

`GLASSBOX_OCR_TIMEOUT` applies per `recognize()` call. For `N=3`, the worst-case
OCR wall time is up to three timeouts unless the voting operation has its own
outer budget.

Required behavior:

- one OCR timeout produces an empty/failed sample, not an automatic whole-action
  failure;
- if fewer than two usable samples remain, return a single-frame result and
  mark the vote as degraded;
- if an outer vote budget is exceeded, stop sampling and degrade;
- report `samples_requested`, `samples_used`, `timeouts`, and `degrade_reason`.

### Required Latency Report

Before enabling the path outside diagnostics, collect p50/p90 for:

- `perceive()`;
- `perceive_voted(n=3)`;
- `fresh_snapshot()`;
- one OCR `recognize()`;
- post-action verification with and without voting.

Any default-on proposal must show the task-level win is worth the added latency.

## Artifacts

Do not add unconditional `artifacts/<run>/ocr_fusion/` writes. The current
runtime artifact store has established run-level directories such as `frames/`,
`scenes/`, `diffs/`, and `verifications/`; adding a new per-algorithm hot-path
directory would create IO cost and another schema surface.

Diagnostic OCR-vote artifacts should be gated by both:

```text
ocr_temporal_voting_keep_raw_samples = true
and an existing debug/recording/artifact mode is active
```

Preferred storage:

- reuse the recorder / scene artifact path where possible;
- include compact vote metadata in `Scene.ocr_vote_metadata` only when the field
  exists;
- write raw frame crops and raw OCR samples only for measurement runs or full
  trace/debug mode;
- never write raw samples on the normal hot path by default.

## Proposed Incremental Extensions

### 1. Measurement Mode

Add a tool or helper around `perceive_voted` that records all raw samples,
cluster decisions, frame deltas, and OCR timing without changing runtime
behavior.

Possible location:

```text
glassbox/cognition/ocr_vote.py
skills/regression/ios_settings diagnostics
skills/regression/ios_gestures diagnostics
```

### 2. Stable vs Transient Classification

Separate region presence from text decision.

Region presence:

```text
stable region: appears in >= min_presence frames
transient region: appears in fewer frames
```

Text decision:

```text
1. Prefer exact whole-string majority.
2. If no whole-string majority, try vote_ocr_texts per-position consensus.
3. If per-position consensus has ambiguous ties, keep the latest/highest
   confidence sample and mark the text as degraded.
```

This avoids dropping a real row when three frames produce three different
strings. Do not drop transient text either: popups, permission sheets, search
suggestions, and toasts may be transient but important.

Because `Scene.elements` has no separate stable/transient field today, first
store status in `UIElement.type_evidence`:

```text
ocr_vote_status:stable
ocr_vote_status:transient
ocr_vote_text_status:whole_string_majority
ocr_vote_text_status:char_consensus
ocr_vote_text_status:degraded_latest
ocr_vote_frames:3
ocr_vote_samples:1
```

Only add explicit model fields after the data proves useful.

### 3. Degradation Metadata

`Scene` is a strict Pydantic model. Do not attach arbitrary attributes such as:

```python
scene.ocr_fusion = {...}
```

That will fail unless the field is added to `Scene`.

If metadata is needed, add an explicit optional field to
`glassbox.cognition.base.Scene`, following the existing explicit metadata fields
such as `vlm_*`:

```python
ocr_vote_metadata: dict[str, Any] = Field(default_factory=dict)
```

Do not enable `extra="allow"`.

### 4. Geometry Improvements

Avoid unordered "IoU OR center distance" clustering. It is order-dependent and
can merge neighboring rows on dense screens.

Extend `vote_scenes` with ordered greedy assignment:

- process one scene at a time;
- each cluster accepts at most one element from that scene;
- require same `UIElement.type`;
- use nearest eligible cluster, not arbitrary OR matching;
- set center tolerance as a proportion of median region height/width, not a
  fixed 24 px;
- optionally require compatible IoU or row-band overlap;
- report cluster drift;
- never merge rows when frame/region drift indicates scrolling.

The current `vote_scenes` already has the most important guards: nearest match,
per-frame uniqueness, and type equality. Evolve those guards instead of
replacing them with a looser rule.

### 5. Current Voting Limits

`vote_ocr_texts` normalizes readings, selects the modal string length, and then
does per-position majority voting inside that length bucket. It cannot delete a
CJK leading glyph by itself.

Do not use this as a promised temporal-vote example:

```text
口 Notes / 日 Notes / Notes -> Notes
```

With the current voter, the modal length is the longer string, so the output
will keep a leading glyph. Fixing that case requires closed-set label fitting
or an explicit alignment/leading-noise rule. A generic CJK-leading-noise stripper
is unsafe because the prefix could be real label text.

Valid temporal-vote example:

```text
待机見示 / 待机显示 / 侍机昰示 -> 待机显示
```

That works only when using the appropriate locale-bound CJK confusion normalizer.

### 6. Volatile Regions

Weather, clocks, counters, badges, and live numeric widgets are volatile. They
must not be treated like stable labels.

Rules:

- classify numeric/time/weather-like clusters as `volatile`;
- if numeric values disagree within the cluster, do not vote them into a
  synthetic string;
- prefer the latest single-frame reading;
- mark evidence as `ocr_vote_status:volatile_latest`;
- do not use fuzzy text similarity to merge separate nearby numeric readings.

This prevents strings such as `330`, `33°`, and `34°` from becoming a fused
artifact.

### 7. Raw vs Normalized Text

`TextRegion` is currently a frozen contract with:

```python
text: str
box: Box
confidence: float
```

Adding `raw_text` / `normalized_text` changes the cognition boundary contract
and requires a contract-version decision. Do not do that as part of this design
unless there is a clear consumer and migration plan.

For the first implementation, keep raw/normalized variants internal to
`vote_scenes` diagnostics and artifacts. `Scene.elements[*].text` remains the
chosen visible text.

### 8. Config

Any new runtime flag must be default-off. Avoid adding another cluster of
loosely related top-level booleans to config; prefer a structured observation
sub-config that is passed into `PhoneObservationConfig`.

Example shape:

```python
@dataclass(frozen=True)
class OcrTemporalVotingConfig:
    enabled: bool = False
    frames: int = 3
    min_presence: int = 2
    sample_spacing_ms: int = 0
    outer_timeout: float = 0.0
    keep_raw_samples: bool = False
```

`AgentConfig` may still expose the environment-backed values, but it should map
them into this structured object instead of spreading voting behavior across the
runtime. Any env-backed flag still needs a `GLASSBOX_` prefix and a CUQ/issue
docstring.

Example shape:

```python
ocr_temporal_voting_enabled: bool = False
"""CUQ-x.y: enable OCR temporal voting on validated perception paths only.
Default off because it adds N x OCR cost and changes element text. Promote only
after on-rig A/B shows task-level improvement. env GLASSBOX_OCR_TEMPORAL_VOTING_ENABLED."""
```

Related knobs should also default to conservative values:

```text
ocr_temporal_voting_frames = 3
ocr_temporal_voting_min_presence = 2
ocr_temporal_voting_sample_spacing_ms = 0
ocr_temporal_voting_outer_timeout = 0.0
ocr_temporal_voting_keep_raw_samples = false
```

Do not introduce `enabled=True`.

## Device And Path Expectations

Track fuse/degrade rate by path and device. v1 expected outcomes:

```text
iPad Home at rest:
  expected fuse rate: high if OCR actually varies
  fallback: lexicon/spatial if OCR is deterministic

iPad Settings root/sidebar at rest:
  expected fuse rate: medium/high for known CJK row jitter
  fallback: locale-bound closed-set matching

iPad App Store static chrome:
  expected fuse rate: unknown
  fallback: chrome verifier and Spotlight profile

iPhone after fling/scroll:
  expected fuse rate: low
  v1 benefit: none claimed
  fallback: latest frame + existing recovery/progress logic

Lock screen notifications:
  expected fuse rate: mixed
  fallback: transient-preserving latest frame for notification text
```

The rollout report must include `fuse_rate`, `degrade_rate`, and
`degrade_reason` per path.

## Verification Gate

Offline unit tests are necessary but not sufficient. Cleaner OCR artifacts do
not prove task improvement.

Before enabling this outside diagnostics, pre-register an on-rig A/B:

```text
device: iPad mini 7 through PicoKVM
locales: en and HK/zh where available
task: Settings drill-down and Home app opening
runs: n >= 5 per condition
conditions:
  A: temporal voting off
  B: temporal voting on for the selected path
```

Primary result metrics:

- `task_completion`;
- `entered_graph`;
- `required_rows_entered`;
- `wrong_app_opened`;
- `wrong_row_tapped`;
- recovery count;
- p50/p90 latency.

Secondary diagnostic metrics:

- OCR per-region disagreement rate;
- vote helped/hurt/unchanged counts;
- fuse/degrade rate;
- OCR timeout count;
- number of VLM escalations avoided or added.

Promotion rule:

```text
Promote only if B improves task-level metrics without an unacceptable latency
increase. If task metrics do not move, keep the feature default-off even if
the OCR artifact report looks cleaner.
```

This is the guard against building reliability machinery that is green in logs
but dead on the default path.

## Test Plan

Unit tests:

- deterministic wrong OCR repeated across frames is not reported as fixed;
- `口 Notes / 日 Notes / Notes` is not claimed to become `Notes` without a
  lexicon/alignment rule;
- CJK row jitter with `confusion_compact` still votes to the expected row;
- three different strings can fall back to char consensus instead of being
  dropped only because no whole-string count reached `min_votes`;
- volatile numeric/weather clusters prefer latest frame and do not synthesize a
  voted number;
- geometry clustering does not merge adjacent Settings rows or Home labels;
- transient elements are preserved and marked;
- metadata is stored only in explicit `Scene` fields or `UIElement.type_evidence`;
- config defaults remain off;
- any SpringBoard test that calls `is_ios_home_screen` uses the real parameter
  name `strict_springboard`, not `strict`.

Integration tests:

- `Phone.perceive_voted` still records multi-frame provenance;
- `vote_scenes` remains the only perception-level voting implementation;
- `GLASSBOX_OCR_TIMEOUT` on one sample degrades that sample rather than hanging;
- duplicate-frame sampling degrades instead of pretending to fuse.

On-rig tests:

- run the measurement spike first;
- run the pre-registered A/B gate;
- archive raw frames, raw OCR, voted scenes, timings, and task outcomes.

## Rollout

1. Add the measurement helper and artifact format.
2. Run the PicoKVM/iPad spike on the screens above.
3. Use the report to decide whether the next work item is:
   - closed-set lexicon/spatial fitting;
   - `vote_scenes` extension;
   - preprocessing/backend comparison;
   - VLM reground usage.
4. If extending `vote_scenes`, add stable/transient evidence, volatile handling,
   safer geometry, and degradation metadata behind a default-off flag.
5. Run the A/B gate.
6. Keep default-off unless task-level metrics improve.
