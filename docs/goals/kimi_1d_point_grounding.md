# Goal — VLM point-grounding fallback for 1D Settings lists

Status: **open / ready to implement (P1 designed)**. Empirically validated on
real frames; bounded, fallback-only, 1D-only.

## Motivation

When OCR garbles a whole row ("Bluetooth"→"BluetOOth") or misses it, the
deterministic locate (`match_any`) can't find which element to tap, even though
the row is on screen. We can't always canonicalize our way out. A VLM, given the
target label, can return the pixel point to tap directly.

## Evidence (measured 2026-05-24, our iOS frames, Kimi/Moonshot raw-coord)

| Surface | Dimensionality | Hit-rate | Mean error |
| --- | --- | --- | --- |
| Settings root list | 1D vertical | **7/7** | ~5 px (row ~18 px) |
| Settings detail page (General) | 1D vertical | **7/7** | ~14 px |
| Home icon grid | 2D | **2/6** | 90–240 px |

Conclusion: **Kimi raw-coordinate grounding is reliable on 1D vertical lists,
unreliable on the 2D icon grid.** This matches glassbox's own lesson
(`springboard_map.py`: "VLMs are unreliable at coordinates… all geometry comes
from detect_icons") — which holds for the 2D grid, not 1D lists. So: use Kimi
points for list rows; keep detector + set-of-marks for the icon grid.

## Design (P1)

Mirror the existing VLM-row seam (`vlm_rows.py`: budgeted, kimi-gated, row-band
crop). Add a sibling that maps **label → point**, used only as a fallback.

1. **New primitive** `vlm_rows.vlm_point_for_label(phone, label, *, scene_kind)`:
   - Gate: only `settings_root` / `settings_detail` scenes (NOT `springboard` —
     the measured 2D failure); only when `phone.kimi` + `phone._last_frame` exist;
     reuse the per-run call budget (`_ROW_CALL_BUDGET`).
   - Ask Kimi for the tap point as **computer_use JSON**
     (`{"action":"left_click","coordinate":[x,y]}`); parse + normalize (handle
     0–1, 0–1000, absolute).
   - Sanity-bound: reject points outside the list band (status bar / nav bar /
     off-screen).
   - Return a synthetic tap-able `UIElement` centred on the point, so the existing
     `tap_settings_row` + same-page verification path is unchanged.

2. **Hook** in `navigation.open_visible_or_scroll_to_row` (the row locator,
   navigation.py:158): when `match_any` returns `None`, call
   `vlm_point_for_label(phone, labels[0], scene_kind=...)` as the fallback.

3. **Wiring**: add `vlm_point_for_label` to `SettingsNavigationActions`; inject in
   `core._navigation_actions()`.

## Guardrails (encode the measured findings)

- **1D-only** — scene_kind gate; springboard returns None (no Kimi call).
- **Fallback-only** — fires solely when deterministic `match_any` fails (bounds
  cost; not per-row).
- **Safety unchanged** — only ground labels already cleared by the safety floor
  (`is_unsafe_navigation_text` etc.); the point doesn't bypass any safety check.
- **Verify after tap** — reuse `same_page_after_tap`; if the Kimi point didn't
  navigate, record `tap_no_navigation` (don't trust blindly, don't loop).
- **Budgeted** — per-run call cap (reuse `vlm_rows` budget).

## Tests (offline, fake kimi — no rig)

- Coordinate normalization: 0–1, 0–1000, absolute.
- 1D-gate: `scene_kind="springboard"` ⇒ returns None, no Kimi call.
- Fallback-only: `match_any` hit ⇒ `vlm_point_for_label` not called.
- Out-of-band point ⇒ rejected.
- Kimi point that doesn't navigate ⇒ `tap_no_navigation` recorded.

## Phasing

- **P1**: primitive + `open_visible_or_scroll_to_row` fallback + the 5 tests above.
- **P2 (optional)**: one call returns all visible rows' points (batch, cached by
  frame signature); extend the fallback to search/relocate recovery.

## Constraints

- Read-only: grounding only *locates*; the safety floor still decides what may be
  tapped.
- Do **not** use VLM point-grounding on the 2D icon grid — keep
  detector + set-of-marks there (measured 2/6).
- Cost bounded to fallback + budget; VLM stays opt-in (`GLASSBOX_ENABLE_VLM`).

## Code touchpoints

- `skills/regression/ios_settings/vlm_rows.py` — new primitive (beside
  `recover_root_label`, reuse budget/gate).
- `skills/regression/ios_settings/navigation.py` — `open_visible_or_scroll_to_row`
  fallback; `SettingsNavigationActions` field.
- `skills/regression/ios_settings/core.py` — `_navigation_actions()` wiring.
- Contract aligns with the broader "point + computer_use JSON" grounding seam
  (see `docs/design/screen_state_fsm.md` for the larger model direction).
