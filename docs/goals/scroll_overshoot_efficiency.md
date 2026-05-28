# Goal — Reduce iPhone scroll-overshoot inefficiency

Status: **open, wheel-revalidation proved; consumer rollout pending.** This is the only remaining signal on a
healthy en-HK exhaustive run — `limits_hit: scroll_overshoot` (a `warning`-level
known issue, `ios-settings-scroll-overshoot`), not an outage. Coverage is
honest 15/17 and `verify_report` passes; the cost is wasted re-scans, not missed
sections. The previous hard-ceiling story for the iPhone scroll primitive is
superseded by 2026-05-28 PicoKVM RPC wheel validation after UDC bounce +
warmup + throwaway prime.

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
  overturned that: after one throwaway first wheel attempt, R02-R10 were stable
  at a fixed 599 px per 30 ticks, with no observed decay. An isolated colleague
  rerun reproduced the effect at 10/10 rounds. The interim 0px local rerun was
  a stale long-lived video-stream artifact: direct ffmpeg frames moved while
  `Phone.snapshot()` returned an old frame until the source was reopened.

Symptoms during a crawl: `[scroll] probe=overshoot` / `probe=stuck`, multi-pass
root re-scans, and the `scroll_overshoot` limit. The sections most at risk are
the upper-middle band a first fling jumps past.

## Why it matters

Efficiency, not correctness. The current run already lands 15/17 by paying for
it (multi-pass reset + search recovery). Cutting the overshoot tax would lower
HID-call count, latency, and the chance of a re-scan landing somewhere unexpected
(e.g. the StandBy clock mis-tap seen under the zh-locale mismatch).

## Directions (none free; pick by appetite)

1. **Promote opt-in iPhone wheel into Settings consumers.** The production
   shape is UDC bounce + long iPhone warmup + one throwaway wheel prime, then
   RPC `wheelReport` batches. `Phone.scroll_wheel()` must reopen the PicoKVM
   source for fresh verification so stale stream buffers do not hide movement.
2. **Closed-loop overshoot recovery (software fallback).** Detect a fling's
   landing band (already classified `overshoot`/`progress`/`stuck`) and
   re-scroll a corrective short amount toward the missed band, instead of a fixed
   multi-pass re-scan from the top. Needs a control loop over the existing probe
   classifier in `skills/regression/ios_settings/scrolling.py`; bounded retries.
3. **Reliable search-based missed-page recovery (software fallback).**
   `crawl_missing_root_pages_via_search` is meant to recover skipped sections but
   has been unreliable; harden it so any band the fling skips is deterministically
   reached via in-app search rather than re-flinging. (Watch the StandBy/search
   mis-tap failure mode observed live.)
4. **iPad migration (hardware, IS a wheel win — updated 2026-05-27).** iPad's
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
- Keep the swipe path as the iPhone default until a bounce+warmup+prime wheel
  Settings run proves coverage. The hardware wheel path itself is no longer a
  known dead end. **On iPadOS the wheel is already authoritative** — see
  `docs/reference/picokvm_ipad_wheel.md`.
- Background: `docs/design/ipad_mini_migration.md`; the on-device wheel/fling
  experiments are recorded in the project memory
  (`picokvm-scroll-overshoot-hardware-limit`, `ios-ignores-usb-hid-digitizer`).
