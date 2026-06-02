# Goal — UI element & layout segmentation (icon caption + typed, reading-ordered element graph)

Status: **proposed, not started — 2026-06-02.** The capability-raising follow-on
to [`ocr_max_out_vision_levers.md`](ocr_max_out_vision_levers.md). Line numbers
are a snapshot as of `18ce14a` (the cited cognition files are byte-identical on
this branch's `main` base — `git diff --name-only main 18ce14a` touches only
`skills/regression/ios_settings/`); reference by symbol. Re-verify with:

```bash
grep -n "def detect_icons\|text_boxes\|edges\[\|center sits inside" glassbox/cognition/icon_detect.py
grep -n "detect_icons_in_perceive\|detect_icons(" glassbox/config.py glassbox/perceptor.py
grep -n "render_set_of_mark\|set_of_mark" glassbox/cognition/som.py glassbox/cognition/contracts.py
grep -n "element_id=" glassbox/cognition/ocr_vision.py
```

## Framing — the real systemic gap

The 2026-06-02 gap analysis found that glassbox's *largest* structural distance
from best practice is **not** low-level text detection — it is **UI element /
layout segmentation**. The default path flattens a screen into raw-ordered text
elements plus (optionally) geometric icon boxes. Best-practice screen agents
(OmniParser, ScreenAI, Ferret-UI) instead build a **typed, reading-ordered
element graph** that groups an icon with its adjacent label into a single
tappable affordance and exposes parent/child + order. That graph is what makes
"tap the right row" robust. Verdict + provenance: `[[ocr-segmentation-gap-verdict]]`.

## What already exists — do NOT rebuild (verified @ `18ce14a`)

- **Anti-conflation geometry is DONE.** `detect_icons(text_boxes=...)`
  (`glassbox/cognition/icon_detect.py:177`) masks out OCR text boxes
  (`icon_detect.py:232-233`, `edges[y:y+h, x:x+w] = 0` — "icons are the non-text
  remainder") and **dedups by containment** ("drop a region whose center sits
  inside a larger kept region", `icon_detect.py:253`). This is OmniParser's
  "merge OCR ∪ icon, drop the overlap" exclusion half — already implemented,
  default-off behind `detect_icons_in_perceive` (`config.py:294`), injected in
  `perceptor.py` (`detect_icons(text_boxes=...)`, ~`:545`).
- **Element ids + a Set-of-Mark renderer exist** — `render_set_of_mark`
  (`glassbox/cognition/som.py:24`) draws a numbered box per element `id`, and
  `VLMRequest.set_of_mark` (`contracts.py:61`) carries it. **But it is
  VLM-prompt-only** (drawn for the model to reference), not a default-path graph.
- **An AGPL OmniParser interactable-region detector** is available as a
  git-ignored drop-in (`glassbox/cognition/icon_backends/omniparser.py`; memory
  `[[omniparser-icon-detector]]`). Detection only — no caption.

## What's missing — the actual work

1. **Reading order.** `element_id` is raw Vision/OCR order
   (`ocr_vision.py:174-181`, `element_id=i`). No row-band sort, no parent/child.
2. **Icon+label grouping.** Pair a detected icon with its adjacent label into ONE
   tappable row element (today they are two separate elements).
3. **Element typing.** Beyond `type='text'`/`'image'`: a typed record
   (row / button / toggle / nav / icon-only) the planner can reason over.
4. **Icon semantic caption.** Injected icons get only the geometric `type='image'`
   — no functional label (OmniParser's Florence-2/BLIP-2 caption step).

## Two tiers — split the cheap classical part from the expensive caption part

**Tier A — MIT, free, classical (the bulk of the grounding value).**
Reading-order (geometric row-band sort) + icon+label grouping + element typing.
**No model.** Builds directly on the existing anti-conflation geometry. Can
become default-on **after** an on-rig A/B. This alone lets the agent tap the
right row / the right icon-only control.

**Tier B — heavy / opt-in (semantic icon caption).** Give icons a functional
label. Two routes, neither on the free default path:
- **VLM caption** behind `GLASSBOX_ENABLE_VLM` (opt-in/billed; reuse the existing
  Set-of-Mark + Kimi path). Must NOT hit the free OCR-only default.
- **Classical icon classifier** (ScreenAI-style fixed-class) if an MIT-licensed
  model is found — keeps it free but adds a dependency.

**`RecognizeDocumentsRequest` (OS-26)** is the Apple-native reading-order/layout
source that can feed Tier A on capable devices — soft-import, fall back to the
geometric sort on older OS / non-document UI (lists are not paragraphs, so
validate it does not merge discrete rows).

## Acceptance

- A typed, reading-ordered `Scene` where icon-only controls and icon+label rows
  are **single** tappable elements in correct order.
- On-rig A/B (iPad mini 7 en/HK, n≥5) shows a grounding improvement —
  `entered_graph`, `required_rows_entered` up, `wrong_row_tapped` down — at
  acceptable latency. Promote Tier A default-on only on that win.
- Default path byte-identical until promoted.

## Constraints / reality (do not re-litigate)

- **Fix the core** — land in `glassbox/cognition/`, not
  `skills/regression/ios_settings/`.
- **MIT / no-AGPL** — Tier A is classical/MIT; the OmniParser YOLO + any
  Florence-2 captioner stay git-ignored drop-ins, **never** `pyproject` deps; VLM
  caption stays opt-in/billed.
- **Default-off / identity-default** until the A/B; new flags `GLASSBOX_`-prefixed
  with CUQ docstrings.
- **Locale-neutral** — reading-order and grouping are geometric/structural; do
  not bake in English/Chinese string assumptions (locale seam,
  `[[locale-seam-english-first]]`).

## Out of scope

The cheap Apple Vision levers ([`ocr_max_out_vision_levers.md`](ocr_max_out_vision_levers.md));
a new text DETECTOR ([`text_detector_dbnet_craft.md`](text_detector_dbnet_craft.md)).

## Entry points (verified @ `18ce14a`)

- `/Users/biu/glassbox/glassbox/cognition/icon_detect.py` — `detect_icons`
  (177-266): `text_boxes` masking (232-233), containment dedup (253),
  `detect_icons_voted` (268).
- `/Users/biu/glassbox/glassbox/config.py` — `detect_icons_in_perceive` (294).
- `/Users/biu/glassbox/glassbox/perceptor.py` — `detect_icons(text_boxes=...)`
  injection (~545).
- `/Users/biu/glassbox/glassbox/cognition/som.py` — `render_set_of_mark` (24).
- `/Users/biu/glassbox/glassbox/cognition/contracts.py` — `VLMRequest.set_of_mark`
  (61).
- `/Users/biu/glassbox/glassbox/cognition/ocr_vision.py` — `element_id=i` raw
  order (174-181).
- `/Users/biu/glassbox/glassbox/cognition/icon_backends/omniparser.py` — AGPL
  drop-in (git-ignored), detection only.
