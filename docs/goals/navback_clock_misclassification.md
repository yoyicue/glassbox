# Goal — Stop the status-bar clock being typed as a Back button

Status: **complete** (2026-05-24). Fixed in core `glassbox/cognition/heuristic.py`:
`rule_status_bar` now strips 1-digit-hour clocks via the shared
`_STATUS_BAR_TIME_RE` (kept in sync with `scene._TIME_RE`), and `rule_nav_back`
rejects time-pattern text as defense-in-depth. Regression tests added in
`skills/smoke/test_heuristic.py` (1-digit clocks → status_bar; real back glyphs →
nav_back). Full smoke 1103 passed, ruff clean. The optional recovery-selection
hardening (#3 below) was not needed — fixing the type at the source resolves the
live failure.

## Problem (live-reproduced)

On a device whose status-bar clock shows a **1-digit hour** (e.g. `8:55`), the
clock is mis-typed as a `nav_back` element. The return-to-root recovery then taps
the clock (cropped ≈ `(84, 37)`) instead of the real back chevron (cropped ≈
`(45, 92)`), so back never fires and the climb out of a Settings subpage fails
with `SettingsRootUnreachable`.

Hit live during an en-HK drill-down while Settings was deep on the **Focus**
subpage: bootstrap could not foreground the Settings root, and a manual tap on the
*real* chevron `(45, 92)` returned to root in one tap — confirming the tap
mechanism is fine and only the affordance was mislocated.

**Detector-agnostic.** This is an OCR/heuristic issue, not the icon detector — it
affects `classical` and `omniparser` equally. It only surfaced during the
omniparser run because the device happened to show a 1-digit hour and Settings was
parked on a subpage.

## Root cause (evidence)

`rule_status_bar` (`glassbox/cognition/heuristic.py:67-69`) detects the clock with
a hand-rolled check that assumes a **2-digit hour** — it requires `text[2] == ':'`
and `text[3:5].isdigit()`. A 1-digit hour like `8:55` has its colon at index 1,
so the check returns `None` and the clock is **not** stripped as `status_bar`.

Rules run in order (`heuristic.py:215`, "strip the status bar first, so nav_back
doesn't grab it"), so the unstripped clock falls through to `rule_nav_back`
(`heuristic.py:78-89`), where `in_top_bar` + `on_left` + `short_label`
(`0 < len("8:55") <= 5`) type it as `nav_back`.

Reproduced:

| text | `rule_status_bar` | `rule_nav_back` |
| --- | --- | --- |
| `8:55` | None ❌ | nav_back ❌ |
| `8:55C` | None ❌ | nav_back ❌ |
| `08:55` / `23:56` / `12:01` | status_bar ✅ | (not reached) |

The canonical time pattern already tolerates 1-digit hours and trailing OCR junk:
`_TIME_RE = ^\d{1,2}[:：.]?\d{2}[A-Za-z]?$` (`glassbox/ios/scene.py:95`). So
`rule_status_bar` and `_TIME_RE` are inconsistent; `_has_back_affordance`
(`scene.py:285`) already uses `_TIME_RE` + a nav-bar band to reject the clock for
*root detection*, but that guard is not applied when the recovery *selects which
element to tap as Back*.

## Fix

1. **Primary — fix `rule_status_bar` to match 1-digit hours.** Accept `H:MM` and
   `HH:MM` (with optional trailing letter / moon-emoji junk), matching `_TIME_RE`'s
   tolerance, so the clock is stripped before `rule_nav_back` can grab it.
   - Layering note: `glassbox/cognition` must not import from `glassbox/ios`.
     Put a shared time regex in `cognition` (e.g. next to the heuristic rules) and
     have `scene.py` reuse it, rather than importing `_TIME_RE` upward.
2. **Defense-in-depth — `rule_nav_back` rejects time-pattern text.** Even if the
   status-bar strip ever misses, a `H:MM`/`HH:MM` token must never be typed
   `nav_back`.
3. **Optional — recovery back-tap selection.** When the recovery picks the element
   to tap as Back, apply the same nav-bar-band + time filter `_has_back_affordance`
   already uses, so a status-bar-height or time-patterned element is never tapped.

## Verification

- Heuristic unit test: `8:55`, `8:55C`, `9:30` → `status_bar`, never `nav_back`;
  keep `08:55` / `23:56` passing.
- Recovery test: a scene with both a 1-digit clock and a real chevron taps the
  chevron, not the clock.
- Live: from a Settings subpage (e.g. Focus) on a device showing a 1-digit hour,
  return-to-root succeeds instead of raising `SettingsRootUnreachable`.

## Out of scope

The sticky device state that triggered the live hit — iOS Settings reopening to
its last-viewed subpage (Focus) — is expected iOS behavior, not a bug. This goal
is only about the clock→nav_back misclassification.
