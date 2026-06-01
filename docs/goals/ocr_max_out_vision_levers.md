# Goal — Max out the existing Apple Vision OCR levers (before any new detector)

Status: **proposed, not started — 2026-06-02.** Handoff doc. Line numbers are a
snapshot as of `18ce14a`; reference by symbol (they drift). Re-verify every
pointer before editing — regenerate the inventory with:

```bash
git rev-parse --short HEAD
grep -n "minimum_text_height\|setRegionOfInterest_\|region_of_interest" glassbox/cognition/ocr_vision.py
grep -n "VisionOCR(" glassbox/backend_registry.py          # what the factory forwards
grep -rn "region_of_interest=" glassbox skills --include="*.py"   # expect: zero callers
grep -n "pos_tol\|vote_scenes" glassbox/cognition/ocr_vote.py glassbox/perceptor.py
```

## Framing — what "用满" means here

This goal is **exhaust the free, already-in-tree Apple Vision capabilities and
fix glassbox's own OCR geometry — before adopting any new model.** It is the
cheap, MIT-clean, zero-new-dependency half of the OCR work surfaced by the
2026-06-02 three-workflow gap analysis. The decisions that bound it:

- **SAM3 before OCR: rejected.** SAM is class-agnostic concept segmentation, not
  a text detector; CUDA-only on Apple Silicon; "SAM License" is incompatible
  with the MIT core. See project memory `[[sam3-not-a-text-detector]]`.
- **A new DBNet/CRAFT text detector: a *later, separate* goal**, and only if the
  levers below prove insufficient. The Apple-Silicon best-practice recipe is
  pre-researched in `[[dbnet-craft-apple-silicon]]` — don't start there.
- **icon caption + typed reading-ordered element graph** (the genuinely systemic
  *UI element/layout segmentation* gap) is **also out of scope here** — a bigger
  capability item for its own goal.

Full gap verdict + source-code corrections: `[[ocr-segmentation-gap-verdict]]`.

## Why it matters

glassbox owns **zero** text-detection/segmentation: `VisionOCR.recognize`
(`glassbox/cognition/ocr_vision.py:123`) delegates detect+recognize to Apple's
`VNRecognizeTextRequest` as a black box. The gap analysis found that several of
the *cheapest* recall levers Apple already gives us are **wired but unreachable
or actively no-op'd today**, and that the most-cited "dense Settings rows merge"
failure is **glassbox's own voting geometry bug, not a Vision miss**. So before
spending on a new detector, harvest what is already in the tree. The honest
caveat from the `en_ocr_correction` experiment applies throughout: *offline
cleaner OCR is necessary, not sufficient* — only an on-rig task A/B promotes
anything (`[[honest-gate-first-strategy]]`).

---

## Workstream 1 — Expose the frozen `VisionOCR` knobs **and fix the `minimumTextHeight` no-op** (the flagship cheap win)

**Effort: LOW–MEDIUM · Risk: LOW (if identity-default is preserved).**

Two distinct facts, both verified:

1. **The factory forwards only 3 of the engine's knobs.** `_vision_ocr_factory`
   (`glassbox/backend_registry.py:185-198`) constructs `VisionOCR(...)` passing
   only `languages`, `uses_language_correction`, `custom_words` (from the locale
   overlay). `minimum_text_height`, `confidence_threshold`, and `unsharp_*` are
   therefore frozen at the `VisionOCR.__init__` defaults and **unreachable from
   config** — even though the engine fully supports them
   (`ocr_vision.py:57-119`).

2. **`minimum_text_height=0.0` is a NO-OP.** `recognize()` guards with
   `if self.minimum_text_height > 0:` (`ocr_vision.py:151`) before calling
   `request.setMinimumTextHeight_(...)`. The default is `0.0`
   (`ocr_vision.py:62`), so `setMinimumTextHeight_` is **never called** and
   **Apple's library default `0.03125` (drop text < ~3.1% of frame height) stays
   in effect.** Small button labels are being filtered *today*. The docstring
   ("default 0.0 = no filtering") is misleading.

**The trap (must not break this):** the zh non-regression hinge
`test_zh_ocr_engine_params_byte_identical_to_vision_defaults`
(`skills/smoke/test_locale.py:34`) reads the defaults *off the `VisionOCR`
signature* and asserts the zh-resolved factory call equals them. A naive "flip
the default to set minimumTextHeight=0" would change behavior for **every**
caller incl. zh and break this lock.

**Do it this way:**
- Change `minimum_text_height`'s default to a `None` sentinel meaning *don't
  touch Apple's default*; guard becomes `if self.minimum_text_height is not
  None:`. `None` → byte-identical (no call). An **explicit `0.0`** now actually
  reaches `setMinimumTextHeight_(0.0)` → small-text recall.
- Thread `minimum_text_height` / `confidence_threshold` / `unsharp_*` through the
  factory from config (or, preferably, from a small structured OCR sub-config in
  the locale resolver — mirror the existing `host.ocr_temporal_voting_config`
  pattern, `perceptor.py:400,589`; avoid another cluster of loose top-level
  booleans).
- Keep the **resolved default = untouched** so zh *and* en-default stay
  byte-identical. Extend `test_locale.py` to assert the new knobs also resolve to
  the signature default for zh (so a future drift on either side fails).
- Add the small-text opt-in (e.g. an `en` dense-list profile or a default-off
  flag) that lowers `minimumTextHeight`. **This is a real behavior change → gate
  the default flip on the on-rig A/B below.**

**Acceptance:** config can set all three knobs; `minimumTextHeight=0` demonstrably
returns more small-label elements on a captured dense-Settings frame; zh +
en-default calls remain byte-identical (test_locale green); `make check` green.

---

## Workstream 2 — Revive native ROI + an opt-in tiling pass for dense/small text

**Effort: MEDIUM · Risk: LOW–MEDIUM.**

`VisionOCR.recognize` already accepts `region_of_interest=` (normalized,
bottom-left origin) and wires `setRegionOfInterest_`
(`ocr_vision.py:127,155-157`) — but **no one passes it.** Verified: zero
`region_of_interest=` callers across `glassbox/` and `skills/`. The boundary
adapter `LegacyUIElementOCRAdapter.recognize` instead does a **numpy crop**
(`ocr_contract.py:52-53` → `_frame_for_roi`) and calls
`inner.recognize(frame.img)` with no ROI.

Two improvements (the second is the real small-text lever):
- **(a) Route an ROI to the native `setRegionOfInterest_`** instead of a numpy
  crop where the full-image language context helps (mind the coordinate
  conversion: pixel top-left `Box` → Vision normalized bottom-left).
- **(b) Opt-in tiling pass for dense regions:** split the cropped content area
  into overlapping ROI windows, OCR each, and **merge/dedup at the seams**
  (NMS + row-band reading order). Small labels then occupy more of the working
  resolution (effective upsample) → higher recall, the same mechanism
  Ferret-UI's sub-image split uses. Default-off; tie to a latency report.

**Caveat (decides ROI):** per-tile OCR multiplies the `recognize()` cost and the
DB-style "detect → crop → re-recognize" tax — it can be **slower than one tuned
full-frame `.accurate`**. Measure p50/p90 before promoting (see
`docs/design/ocr_temporal_voting.md` "Required Latency Report").

**Acceptance:** native-ROI path exercised by a test; tiling pass recovers
measurably more small labels on a captured dense frame at an acceptable latency
delta; default path unchanged.

---

## Workstream 3 — Fix the voting geometry (dense-row merge is OUR bug)

**Effort: MEDIUM · Risk: MEDIUM (must not split true rows).**

`vote_scenes` clusters elements across frames with a **single absolute
Manhattan pixel tolerance** `pos_tol` (`ocr_vote.py:124-179`). It *is* a config
knob (`ocr_temporal_voting_pos_tol=20`, `config.py:224`, threaded via
`perceptor.py:413,590,650`) — so the fix is **not** "expose it" but **change the
model**: an absolute px tolerance merges adjacent rows on dense screens.

This is **live today**, not dormant: `perceive_voted` runs on the opt-in gate
(`perceptor.py:404`) and has real callers — `skills/crawl/crawl_app.py:55` and
`skills/regression/ios_settings/scrolling.py:58`. So the merge hazard already
affects the crawler and the Settings scrolling harness.

Implement the unimplemented `docs/design/ocr_temporal_voting.md` §4 geometry:
- tolerance **relative to median region height/width**, not a fixed 24/20 px;
- require compatible **IoU or row-band overlap**, not arbitrary nearest-match;
- **reject merges when cluster drift indicates scrolling**;
- keep the existing guards (nearest match, per-frame uniqueness, type equality).

**Acceptance:** a smoke test asserts adjacent Settings rows / Home labels are
**not** merged across jittered frames (distinct-label assertion), while genuine
CJK row jitter still votes to one row. No regression in the crawl/scrolling
harness coverage.

---

## Validation discipline (applies to every default flip)

- **Offline is necessary, not sufficient.** The `en_ocr_correction` flag was
  offline **net-negative** (coverage 0.997→0.949, "Apple Pencil"→"Apple Bencil")
  and is still default-off pending a rig A/B. Treat every "cleaner OCR" change
  the same.
- **On-rig A/B, n≥5 per arm, iPad mini 7 en/HK** (`run_full --language en
  --region HK`). Primary metrics: `required_rows_entered`, `wrong_row_tapped`,
  `entered_graph`, `task_completion`; secondary: small-label recall, p50/p90
  latency. Promote a default flip **only** on a task-level win at acceptable
  latency — not on a cleaner OCR dump.
- **zh stays byte-identical**, locked by `skills/smoke/test_locale.py` (extend it
  for any new forwarded knob).

## Out of scope (do not pull in)

SAM3 (rejected, `[[sam3-not-a-text-detector]]`); a new DBNet/CRAFT detector
(separate later goal, `[[dbnet-craft-apple-silicon]]`); icon caption + typed
reading-ordered element graph (separate UI-element-segmentation goal);
`RecognizeDocumentsRequest` reading-order (OS-26-gated); recognizer swap for the
Cyrillic homoglyph error (recognition, not segmentation — long tail, poor ROI);
VLM grounding (opt-in/billed, not the free default path).

## Constraints / reality (do not re-litigate)

- **Fix the core.** Land in `glassbox/cognition/` + `glassbox/locale.py` /
  `glassbox/backend_registry.py`, **not** in `skills/regression/ios_settings/`,
  so every caller benefits.
- **Zero new dependencies, MIT-clean.** Everything here is Apple-native Vision —
  no new models, no AGPL.
- **Default-off / identity-default.** zh and en-default runs must stay
  byte-identical; new knobs default to "untouched"; new flags default off with a
  `GLASSBOX_`-prefixed env + CUQ docstring (follow the `ocr_temporal_voting_*`
  precedent in `config.py`).
- **`make check` stays green offline** — all wiring + unit tests are
  rig-independent; only the *promotion* A/B needs the rig.

## Entry points (verified @ `18ce14a`)

- `/Users/biu/glassbox/glassbox/cognition/ocr_vision.py` — `VisionOCR.__init__`
  knobs (57-119); the `minimum_text_height > 0` guard (151); native
  `setRegionOfInterest_` (155-157); `_apply_unsharp` (185-209).
- `/Users/biu/glassbox/glassbox/backend_registry.py` — `_vision_ocr_factory`
  (185-198): the 3-knob passthrough to widen.
- `/Users/biu/glassbox/glassbox/cognition/ocr_contract.py` —
  `LegacyUIElementOCRAdapter.recognize` (51-67) + `_frame_for_roi` (70-83): the
  numpy-crop path that bypasses native ROI.
- `/Users/biu/glassbox/glassbox/cognition/ocr_vote.py` — `vote_scenes` (124-179):
  the absolute-`pos_tol` clustering to make row-relative.
- `/Users/biu/glassbox/glassbox/perceptor.py` — voting opt-in gate (400-414),
  `perceive_voted` (567-651).
- `/Users/biu/glassbox/glassbox/config.py` — OCR knobs (166-244).
- `/Users/biu/glassbox/skills/smoke/test_locale.py` — the zh byte-identity lock
  to extend (34-115).
