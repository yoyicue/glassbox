# Goal — VLM point-grounding fallback for 1D Settings lists

Status: **open / ready to implement**. P1 designed; **peer-reviewed 2026-05-24,
4 fixes + form notes incorporated below**. Empirically validated; bounded,
fallback-only, 1D-only.

## Motivation

When OCR garbles a whole row ("Bluetooth"→"BluetOOth") or misses it, the
deterministic locate (`match_any`) can't find which element to tap, even though
the row is on screen. We can't always canonicalize our way out. A VLM, given the
target label, can return the row's position to tap directly.

## Evidence (measured 2026-05-24, our iOS frames, Kimi/Moonshot raw-coord)

| Surface | Dimensionality | Hit-rate | Mean error |
| --- | --- | --- | --- |
| Settings root list | 1D vertical | **7/7** | ~5 px (row ~18 px) |
| Settings detail page (General) | 1D vertical | **7/7** | ~14 px |
| Home icon grid | 2D | **2/6** | 90–240 px |

Conclusion: **Kimi raw-coordinate grounding is reliable on 1D vertical lists,
unreliable on the 2D icon grid.** Note `x` was always ≈ screen mid-line — only the
**row's `y`** carried signal, which matches how PicoKVM taps Settings rows (below).
This is consistent with glassbox's own lesson (`springboard_map.py`,
`vlm_kimi.py`: "don't let Kimi return click coordinates directly, ~100px offset")
— which holds for the **2D grid**; the **1D list** is a bounded exception.

## Design (P1) — with review fixes

Mirror the existing VLM-row seam (`vlm_rows.py`: budgeted, kimi-gated). Add a
sibling that maps **label → the row's y**, used only as a fallback.

1. **New primitive** `vlm_rows.vlm_point_for_label(phone, label, *, scene_kind)`
   (beside `recover_root_label`):
   - **Scene gate = allowlist** `{settings_root, settings_detail}` — *not*
     "≠ springboard" (scene kinds also include `app_library`, `system_search`,
     `unknown`; only the two list scenes are safe to ground).
   - Only when `phone.kimi` + `phone._last_frame` exist; reuse `_ROW_CALL_BUDGET`,
     **plus a separate (frame-signature, label) cache** so a stuck frame doesn't
     re-burn budget.
   - **Safety precondition in code** (fix #4): reject the label if
     `is_unsafe_navigation_text(label)` — `open_visible_or_scroll_to_row` does not
     guarantee its `labels` are safety-filtered, so the primitive must not become
     an arbitrary coordinate-click channel.
   - **Crop = the visible list band, not a row band** (fix #2): `recover_root_label`
     crops around a *known* element box, but here `match_any` already failed (no
     element). Crop the full visible list region; convert the crop-relative point
     **back to frame coords**.
   - Ask Kimi for the point as **computer_use JSON**
     (`{"action":"left_click","coordinate":[x,y]}`); parse from **both
     `resp.parsed` and `resp.raw_content`**, then normalize the three forms
     (0–1, 0–1000, absolute).
   - Sanity-bound: reject points outside the list band (status bar / nav bar /
     off-screen).
   - **Return a row-label-like synthetic `UIElement`** (fix #3): `type="text"`,
     left-aligned x, carrying the label text — so it flows through
     `Phone._picokvm_settings_row_tap_point_for_element` (phone.py:1031), which
     projects the tap to the row mid-line and keeps only `y`. **Do not** hand back
     Kimi's raw x/y as the click point and bypass that projection. (This matches
     the measurement: the useful signal is the row `y`.)

2. **Hook** in `navigation.open_visible_or_scroll_to_row` (navigation.py:158):
   - First `labels = tuple(labels)` (fix: an iterable can be consumed across
     scroll rounds).
   - When `match_any` returns `None`, call
     `vlm_point_for_label(phone, labels[0], scene_kind=actions.scene_kind(scene))`.

3. **Wiring** (fix #1): `SettingsNavigationActions` has only `scene_is_settings_root`
   today — add a `scene_kind: Callable[..., str]` field and inject `_scene_kind`
   (core.py:159) in `core._navigation_actions()` (core.py:745). Add the
   `vlm_point_for_label` field too.

4. **Reconcile the comment** (form note): update `vlm_kimi.py:29`
   ("Do not let Kimi return click coordinates directly") to: "2D / general
   scenes: no; the Settings **1D-list fallback** is a bounded, measured
   exception" — so the codebase doesn't carry contradictory guidance.

## Guardrails (encode the measured findings)

- **1D-only** via scene allowlist (springboard / app_library / unknown ⇒ no call).
- **Fallback-only** — fires solely when deterministic `match_any` fails.
- **Safety enforced in code** — primitive rejects unsafe labels (not just "by
  convention").
- **No projection bypass** — synthetic element goes through the PicoKVM Settings
  row tap projection (y-only, mid-line x).
- **Verify after tap** — reuse `same_page_after_tap`; no navigation ⇒ record
  `tap_no_navigation`, don't loop.
- **Budgeted + cached** — per-run cap and per-(frame,label) cache.

## Tests (offline, fake kimi — no rig)

1. Coordinate normalization: 0–1, 0–1000, absolute; parse from `parsed` and
   `raw_content`.
2. Scene allowlist: `springboard` **and** `app_library` ⇒ returns None, no Kimi
   call (locks "1D-only").
3. Fallback-only: `match_any` hit ⇒ `vlm_point_for_label` not called.
4. Out-of-band point ⇒ rejected.
5. Unsafe label ⇒ rejected (no Kimi call), even if passed in directly.
6. Kimi point that doesn't navigate ⇒ `tap_no_navigation` recorded.
7. **PicoKVM**: the synthetic element is routed through
   `_picokvm_settings_row_tap_point_for_element` (mid-line x / row y), not tapped
   at Kimi's raw x/y — locks "safety/projection path unchanged".

## Phasing

- **P1**: primitive + `open_visible_or_scroll_to_row` fallback + tests 1–7 +
  the `vlm_kimi.py` comment fix.
- **P2 (optional)**: one call returns all visible rows' points (batch, cached by
  frame signature); extend to search/relocate recovery.

## Constraints

- Read-only: grounding only *locates*; the safety floor still decides what may be
  tapped.
- Do **not** use VLM point-grounding on the 2D icon grid — keep
  detector + set-of-marks there (measured 2/6).
- VLM stays opt-in (`GLASSBOX_ENABLE_VLM`); cost bounded to fallback + budget +
  cache.

## Code touchpoints

- `skills/regression/ios_settings/vlm_rows.py:24` — new primitive (share budget,
  add frame+label cache, list-band crop, safety reject).
- `skills/regression/ios_settings/navigation.py:158` —
  `open_visible_or_scroll_to_row` fallback + `tuple(labels)`;
  `SettingsNavigationActions` gains `scene_kind` + `vlm_point_for_label`.
- `skills/regression/ios_settings/core.py:745` — inject `_scene_kind`
  (core.py:159) + `vlm_point_for_label`.
- `glassbox/phone.py:1031` — `_picokvm_settings_row_tap_point_for_element` is the
  projection the synthetic element must flow through (do not bypass).
- `glassbox/cognition/vlm_kimi.py:29` — update the "no direct coordinates" comment
  to note the bounded 1D exception.
- Larger model direction: `docs/design/screen_state_fsm.md`.
