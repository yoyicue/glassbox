# Goal — Reduce iPhone scroll-overshoot inefficiency

Status: **open, hardware-bounded.** This is the only remaining signal on a
healthy en-HK exhaustive run — `limits_hit: scroll_overshoot` (a `warning`-level
known issue, `ios-settings-scroll-overshoot`), not an outage. Coverage is
honest 15/17 and `verify_report` passes; the cost is wasted re-scans, not missed
sections. The hard ceiling is the iPhone scroll primitive — accept that and
attack the *recovery cost*, or change the hardware.

## Problem

On the PicoKVM iPhone rig, the only usable scroll is a **momentum swipe-fling**:

- HID-mouse-as-touch supports only a coarse fling. Small/medium drags
  (~0.20–0.40 of viewport) do not register (`stuck`); only the large ~0.55 drag
  moves the list, and it **overshoots non-deterministically** (a single fling can
  jump from top to near-bottom). Reducing distance/velocity to cut overshoot
  drops below the registration threshold (`stuck`, worse) — so gesture precision
  is not tunable by config alone.
- The mouse **wheel** scrolls precisely (~1 row/tick, no fling) but is **severely
  intermittent (~5–7%) under AssistiveTouch**, which the iPhone *requires* for any
  pointer. It worked ~5× early in a session then stayed dead (rigorous 40-trial:
  0/20 raw, 0/20 RPC). Not revivable from the PicoKVM side (reboot / gadget
  unbind-rebind at 1s and 12s gaps all failed); format/interface-independent
  (abs report-ID-2 and M4-style relative both 0/n). It is the documented iOS
  AssistiveTouch wheel bug. So the wheel stays **opt-in** (`GLASSBOX_PICOKVM_
  WHEEL_ENABLED=1`), reliable on iPad only (corrected mechanism, commit `32d21e4`).

Symptoms during a crawl: `[scroll] probe=overshoot` / `probe=stuck`, multi-pass
root re-scans, and the `scroll_overshoot` limit. The sections most at risk are
the upper-middle band a first fling jumps past.

## Why it matters

Efficiency, not correctness. The current run already lands 15/17 by paying for
it (multi-pass reset + search recovery). Cutting the overshoot tax would lower
HID-call count, latency, and the chance of a re-scan landing somewhere unexpected
(e.g. the StandBy clock mis-tap seen under the zh-locale mismatch).

## Directions (none free; pick by appetite)

1. **Closed-loop overshoot recovery (software, iPhone-stays).** Detect a fling's
   landing band (already classified `overshoot`/`progress`/`stuck`) and
   re-scroll a corrective short amount toward the missed band, instead of a fixed
   multi-pass re-scan from the top. Needs a control loop over the existing probe
   classifier in `skills/regression/ios_settings/scrolling.py`; bounded retries.
2. **Reliable search-based missed-page recovery (software, iPhone-stays).**
   `crawl_missing_root_pages_via_search` is meant to recover skipped sections but
   has been unreliable; harden it so any band the fling skips is deterministically
   reached via in-app search rather than re-flinging. (Watch the StandBy/search
   mis-tap failure mode observed live.)
3. **iPad migration (hardware, IS a wheel win — updated 2026-05-27).** iPad's
   native pointer consumes the same Generic-Desktop mouse reports. The current
   connected iPad now scrolls Settings sidebar reliably via the existing
   `kvm_app.wheelReport` RPC — 3 fresh-reboot rounds, both directions,
   reproducible. Details, glassbox-side flip, and the one-time "activation"
   caveat in [docs/reference/picokvm_ipad_wheel.md](../reference/picokvm_ipad_wheel.md).
   With wheel authoritative on iPad, Direction 3 makes 1 and 2 obsolete on the
   iPad rig (they remain the value-now options on the iPhone rig).

## Acceptance

- A healthy exhaustive en-HK / zh run no longer reports `scroll_overshoot` (or
  reports it strictly as benign), with coverage staying at the honest ceiling.
- Fewer HID calls / lower wall time on the same coverage (measure against the
  current en-HK baseline: 15/17, ~27–35 HID calls, 0 nav failures).
- No new mis-tap failures introduced by corrective re-scrolling.

## Constraints / reality (do not re-litigate)

- No reliable precise-scroll path exists on **iPhone** from the PicoKVM side; the
  wheel is not restorable on demand. iOS ignores the HID digitizer/touchpad;
  only a Generic-Desktop mouse works, and AssistiveTouch is mandatory for it.
- Keep the swipe path as the iPhone default; the wheel stays explicit opt-in /
  diagnostic on iPhone. **On iPadOS the wheel is now authoritative** — see
  `docs/reference/picokvm_ipad_wheel.md`.
- Background: `docs/design/ipad_mini_migration.md`; the on-device wheel/fling
  experiments are recorded in the project memory
  (`picokvm-scroll-overshoot-hardware-limit`, `ios-ignores-usb-hid-digitizer`).
