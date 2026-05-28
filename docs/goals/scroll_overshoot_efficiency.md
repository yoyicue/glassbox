# Goal — Reduce iPhone scroll-overshoot inefficiency

Status: **open; iPhone wheel transport is reliable, but wheel has not yet won
end-to-end.** The 2026-05-28 iPhone wheel drill-down reached the same result as
the swipe baseline in about 6 minutes: 15/17 coverage, 0 navigation failures,
`success_rate=1.0`, and `exhaustive_ready=true`. `limits_hit` still included
`scroll_overshoot`, so the core inefficiency remains.

## Problem

On the PicoKVM iPhone rig, the default production scroll is still a
**momentum swipe-fling**:

- HID-mouse-as-touch supports only a coarse fling. Small/medium drags
  (~0.20–0.40 of viewport) do not register (`stuck`); only the large ~0.55 drag
  moves the list, and it **overshoots non-deterministically** (a single fling can
  jump from top to near-bottom). Reducing distance/velocity to cut overshoot
  drops below the registration threshold (`stuck`, worse) — so gesture precision
  is not tunable by config alone.
- The mouse **wheel** used to be classified as severely intermittent under
  AssistiveTouch. A 2026-05-28 PicoKVM RPC retest with UDC bounce + warmup
  overturned that transport-level story: after one throwaway first wheel
  attempt, R02-R10 were stable at a fixed 599 px per 30 ticks, with no observed
  decay. An isolated colleague rerun reproduced the effect at 10/10 rounds. The
  interim 0px local rerun was a stale long-lived video-stream artifact: direct
  ffmpeg frames moved while `Phone.snapshot()` returned an old frame until the
  source was reopened.
- The end-to-end Settings run did **not** prove a wheel win. A 30-tick batch is
  still about 600 px, or roughly 3-4 Settings rows, so it can skip whole row
  groups just like a swipe-fling. Rejected candidates such as
  `AirplaneMOde`/`PersOnalHOtspOt`/`Wallet&ApplePay`/`iClOud` show the same
  merged-token overrun mechanism.

Symptoms during a crawl: `[scroll] probe=overshoot` / `probe=stuck`, multi-pass
root re-scans, and the `scroll_overshoot` limit. The sections most at risk are
the upper-middle band a first fling jumps past.

## Why it matters

Efficiency, not correctness. The current run already lands 15/17 by paying for
it (multi-pass reset + search recovery). Cutting the overshoot tax would lower
HID-call count, latency, and the chance of a re-scan landing somewhere unexpected
(e.g. the StandBy clock mis-tap seen under the zh-locale mismatch).

## Directions (none free; pick by appetite)

1. **Tune iPhone wheel batch size before judging the hardware path.** The first
   Settings consumer should use small wheel batches (5-10 ticks, default 8) and
   adapt from probe feedback: `stuck` increases ticks, `overshoot` decreases
   ticks. Treat the 30-tick result as proof that wheel delivery is reliable, not
   proof that the crawl is more efficient.
2. **Add explicit overshoot boundary signals.** Status-bar boundary OCR is a
   useful special case: if the cursor region lands in the top chrome (`y < 100`)
   and OCR sees a time-like token, classify the scroll as `top-overshoot` and
   keep charging `scroll_overshoot`.
3. **Closed-loop overshoot recovery (software fallback).** Detect a fling's
   landing band (already classified `overshoot`/`progress`/`stuck`) and
   re-scroll a corrective short amount toward the missed band, instead of a fixed
   multi-pass re-scan from the top. Needs a control loop over the existing probe
   classifier in `skills/regression/ios_settings/scrolling.py`; bounded retries.
4. **Reliable search-based missed-page recovery (software fallback).**
   `crawl_missing_root_pages_via_search` is meant to recover skipped sections but
   has been unreliable; harden it so any band the fling skips is deterministically
   reached via in-app search rather than re-flinging. (Watch the StandBy/search
   mis-tap failure mode observed live.)
5. **iPad migration (hardware, IS a wheel win — updated 2026-05-27).** iPad's
   native pointer consumes the same Generic-Desktop mouse reports. The current
   connected iPad now scrolls Settings sidebar reliably via the existing
   `kvm_app.wheelReport` RPC — 3 fresh-reboot rounds, both directions,
   reproducible. Details, glassbox-side flip, and the one-time "activation"
   caveat in [docs/reference/picokvm_ipad_wheel.md](../reference/picokvm_ipad_wheel.md).
   With wheel authoritative on iPad, this makes the fallback directions obsolete
   on the iPad rig.

## Acceptance

- A healthy exhaustive en-HK / zh run no longer reports `scroll_overshoot` (or
  reports it strictly as benign), with coverage staying at the honest ceiling.
- Fewer HID calls / lower wall time on the same coverage (measure against the
  current en-HK baseline: 15/17, ~27–35 HID calls, 0 nav failures).
- No new mis-tap failures introduced by corrective re-scrolling.

## Constraints / reality (do not re-litigate)

- iOS still ignores the HID digitizer/touchpad; only a Generic-Desktop mouse
  works, and AssistiveTouch is mandatory on iPhone.
- Keep the swipe path available until small-batch wheel proves lower
  `scroll_overshoot` or lower HID cost on the same coverage. The hardware wheel
  path itself is no longer a known dead end, but the 30-tick Settings run only
  tied the baseline. **On iPadOS the wheel is already authoritative** — see
  `docs/reference/picokvm_ipad_wheel.md`.
- The 2026-05-28 `Settings > Sign Out` alert was a Game Center welcome-page
  misclassification: the page title contained a `Sign Out` button. It was not a
  real Apple Account sign-out path. See
  `artifacts/wheel_probe_2026-05-27/iphone_drill_down_2026-05-28/`.
- Background: `docs/design/ipad_mini_migration.md`; the on-device wheel/fling
  experiments are recorded in the project memory
  (`picokvm-scroll-overshoot-hardware-limit`, `ios-ignores-usb-hid-digitizer`).
