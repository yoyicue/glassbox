# Goal — Detect non-interactive (disabled) Settings rows, generically

Status: **open / investigating**. Decide CV vs VLM with a real benchmark before
replacing the interim no-SIM hack.

## Problem

Some Settings root rows can't be opened on a given device — e.g. **Mobile
Service / 蜂窝网络 on a no-SIM iPhone**: the row renders **greyed/disabled** and a
tap does not navigate. Today the crawl wastes ~2 min of a ~5.6 min run re-scanning
+ search-recovering for such rows, and verification needs a manual flag to pass.

We want to recognise "this row is inert" **the way a human does — by looking** —
not by tap-probing (a mis-landed tap on this AssistiveTouch rig can flip a toggle,
breaking the read-only guarantee). The signal must be **generic** (any disabled
row, any locale, any cause), not a per-section text match.

## What we already know (investigated 2026-05-24)

Ground truth from one live no-SIM root frame (`/tmp/cvbench_*`):
disabled = {Mobile Service, Personal Hotspot}; active = 9 real section rows.

| Approach | Result | Notes |
| --- | --- | --- |
| **tap-probe** (`tap_no_navigation`) | works but **rejected** | side-effect / coordinate risk on a read-only crawl; can't tell "inert by design" from "our tap bug" |
| **CV: icon saturation** | F1 0.67 | fails on naturally-grey active icons (General, Camera) |
| **CV: label text-contrast** (filtered to real section rows) | **F1 1.00, P/R 1.00** | clean gap: disabled 74–84 vs active 155–182; threshold window 85–155 |
| **VLM** (one call on the frame) | **correct, 0 false positives** | also caught Personal Hotspot; holistic/relative, no reference needed |
| no-SIM text hack (`"No SIM"`) | narrow | only Cellular; locale/version fragile |

Key correction: an earlier "CV is unreliable" call was wrong — it was caused by
not filtering candidates (value/subtitle/Wi-Fi-name text contaminated the
distribution) and by using icon saturation instead of **label text-contrast**
(active rows keep black label text even when their icon is grey; disabled rows
have grey label text).

**Caveat:** 1 frame, 2 positives — indicative, not conclusive. No dark-mode /
different-wallpaper / other-disabled-row coverage. Absolute thresholds may drift
across themes; a **relative-to-sibling** threshold likely generalises better (not
yet validated correctly).

## The decision to make

Pick the primary inert-row signal — **CV (free, deterministic, instant)** vs
**VLM (paid, ~1 call/root-page, robust/holistic)** — backed by P/R numbers across
realistic conditions, not one frame.

## Acceptance criteria

- A small **labeled benchmark set**: multiple frames across light/dark mode,
  different wallpapers, and as many real disabled-row examples as can be staged.
- P/R/F1 for: CV text-contrast (absolute **and** relative-to-sibling) and VLM.
- The chosen approach must be **provably ≥ the no-SIM hack**: catches Cellular,
  generalises to other disabled rows, and has **no false positives that drop a
  real (enterable) section** (false-disabled = silent coverage loss).
- Only then replace the hack.

## Constraints

- **Read-only**: decide by perception, never by speculative taps.
- **VLM cost bounded**: if VLM, fire once per root page (layout is stable in a
  run), not per row.
- **Honesty**: inert rows stay reported (`navigation_failures` /
  `root_coverage.missing`); they are just not chased or required — never hidden.
- On a SIM'd device no row is disabled, so Cellular must stay required (a real
  navigation regression must not be masked).

## Code touchpoints

- Interim hack to replace: `policy.detect_device_unavailable_root_labels` +
  `_NO_SIM_MARKERS` (commit `0cafb6c`, currently unpushed).
- Crawl stop-condition + verify exemption already wired via
  `core._entry_exempt_sections`, `navigation` reset-gate / search-recovery,
  `verify_report` auto-exempt — the new detector slots in behind the same seam.
- Perception enrichment target: set `element.interactive=False` on detected
  disabled rows so the crawl simply skips them.

## Interim

The no-SIM hack (`0cafb6c`) stays as the working stopgap until the benchmark
picks the general detector. Decide whether to push it as interim or hold.
