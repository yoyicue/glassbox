# en_ocr_correction A/B — 2026-06-01

On-rig A/B for the flag-gated English OCR correction (`GLASSBOX_EN_OCR_CORRECTION`,
config `en_ocr_correction`, default OFF). The feature commit (`5d64246`) shipped
the seam default-off and stated it "must clear an on-rig task_completion A/B
before defaulting on". This is that A/B. **Outcome: does not clear the bar —
keep default OFF.**

## Setup

- Device: iPad mini 7 through PicoKVM HDMI capture, **English** Settings.
- Backend: `vision` (`VisionOCR`; this is the only backend the flag affects —
  `ocrmac`/`AppleVisionOCR` has no correction knobs, so the flag is a no-op
  there). Confirmed `select_ocr_backend == "vision"` on this host.
- Locale: `en-HK`. Model override `GLASSBOX_PHONE_MODEL=ipad_mini_7`.
- Task: read-only Settings walkthrough, depth-1 drill-down.
- **n = 1 per condition** (one round — directional only, not conclusive).
- Commands:

```bash
# A (correction OFF)
GLASSBOX_PHONE_MODEL=ipad_mini_7 GLASSBOX_EN_OCR_CORRECTION=0 \
  uv run python -m skills.regression.ios_settings.run_full \
  --drill-down --language en --region HK --report a_off.json
# B (correction ON)
GLASSBOX_PHONE_MODEL=ipad_mini_7 GLASSBOX_EN_OCR_CORRECTION=1 \
  uv run python -m skills.regression.ios_settings.run_full \
  --drill-down --language en --region HK --report b_on.json
```

## Result (snapshot; report schema 0.1)

| metric | A (off) `run_id 53d89623…` | B (on) `run_id e1be44f0…` |
| --- | --- | --- |
| `root_required_missing_count` | **0** (12/12 required entered) | **0** (12/12 required entered) |
| `root_visited_count` | 12 | 12 |
| `navigation_failure_count` | 0 | 0 |
| `navigation_success_proxy_rate` | 1.0 | 1.0 |
| `visited_display` | WLAN, Bluetooth, Notifications, Sounds & Haptics, Focus, Screen Time, General, Accessibility, Siri, Face ID & Passcode, Privacy & Security, Battery | *(identical 12 rows)* |

**Task-level metrics are identical — a tie at the coverage ceiling (12/12
required rows entered, zero navigation failures, both conditions).** The flag
produced **no task-level improvement.**

The metrics that *did* differ (A took a Settings-search detour, `sidebar_exhaustive`
A=True / B=False, B picked up one `safety: ios-settings-navigation-candidate-policy-gap`,
`visit_count` 28 vs 23, B faster) are run-to-run **path/timing variance at n=1**,
not flag-attributable — and where they differ, B is not the better run.

### What correction actually did to the OCR text (a wash, slightly net-negative)

- The task-relevant sidebar row labels were **already read cleanly with
  correction OFF** (WLAN / Bluetooth / Siri / iCloud / Face ID & Passcode), so
  the proper-noun whitelist had little to add.
- With correction ON it re-introduced some word spacing (`&Passcode → & Passcode`,
  `fromthe → from the`) but **corrupted some proper nouns** (`Apple Pencil →
  "Apple Bencil"`); `Accessibility` was misread under both. Same re-spacing
  mechanism that fragments status-bar/timestamp text.
- This matches the pre-existing offline OCR-replay finding (net-negative on raw
  coverage).

## Decision

**Keep `en_ocr_correction` default OFF.** The on-rig A/B shows no task-level
benefit (tie at ceiling) and a wash-to-slightly-negative effect on OCR text. The
promotion rule ("promote only if B improves task-level metrics") is not met.

Incidental positive (independent of the flag): this run is also a live, on-rig
validation that the **closed-set SpringBoard/Settings canonicalization** carries
the task — with correction OFF the sidebar still resolved to clean canonical row
labels and entered 12/12 required rows. The English OCR correction is a redundant
(slightly harmful) layer on top of it on this surface.

## Caveats / what a future re-eval needs

1. **n = 1** per condition — directional, not conclusive.
2. **Ceiling effect**: both conditions hit 12/12 required, so this task cannot
   discriminate the flag. A meaningful re-eval needs a **non-saturated** task and
   **n ≥ 5** per condition.
3. **Harness gap**: the run report's `config` block does **not** record
   `en_ocr_correction` (it reads `None` in both reports), so the A/B is not
   self-auditable from the artifacts. The condition was verified separately
   (`GLASSBOX_EN_OCR_CORRECTION=1` flips `en_ocr_correction`/`uses_language_correction`
   to True, and B's text showed the expected re-spacing). **Recommend the run
   report echo the flag(s) under test** so a future A/B is reproducible from the
   committed record alone.
