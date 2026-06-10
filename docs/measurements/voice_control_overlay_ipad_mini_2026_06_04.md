# Voice Control overlay iPad mini 7 probe — 2026-06-04

> **Purpose**: small on-rig A/B for the rank-1 Voice Control overlay path:
> can HDMI + VisionOCR see continuous overlay markers, and do coordinate HID
> taps still work while Voice Control is enabled?
>
> **Snapshot**: working tree based on branch `docs/eval-and-a11y-design`, HEAD
> `a858e2e`; `GLASSBOX_PHONE_MODEL=ipad_mini_7`; iPad mini 7 rig; screen was
> already on `Settings > Accessibility > Voice Control > Overlay`.
>
> **Item Numbers generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-scroll-probe-v3 \
>   --scroll-probe
> ```
>
> **Item Names generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_names \
>   --output-dir /tmp/glassbox-vc-itemnames-harness
> ```
>
> **Item Names labeled replay generator**:
>
> ```bash
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_labeled_replay \
>   --labels skills/regression/fixtures/voice_control_overlay_itemnames_labels_v1.json \
>   --scene /tmp/glassbox-vc-itemnames-harness/ai-runs/run_2026_06_04_15_30_57_222512/scenes/scn_000023.json \
>   --frame /tmp/glassbox-vc-itemnames-harness/03_item_names_restored.png \
>   --output /tmp/glassbox-vc-itemnames-harness/itemnames_labeled_replay_v1.json
> ```
>
> **Numbered Grid generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode numbered_grid \
>   --output-dir /tmp/glassbox-vc-numbered-grid-harness-v1 \
>   --scroll-probe
> ```
>
> **Wheel hover probe generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-wheel-probe-v2 \
>   --wheel-probe \
>   --wheel-ticks 90 \
>   --wheel-repeat 1 \
>   --wheel-focus-point 135,930
> ```
>
> **Wheel focus-click probe generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-wheel-focus-click-v1 \
>   --wheel-probe \
>   --wheel-ticks 90 \
>   --wheel-repeat 1 \
>   --wheel-focus-point 135,930 \
>   --wheel-focus-click
> ```
>
> **Wheel bidirectional probe generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-wheel-bidir-probe-v1 \
>   --wheel-probe \
>   --wheel-ticks 90 \
>   --wheel-second-ticks -90 \
>   --wheel-repeat 1 \
>   --wheel-focus-point 135,930
> ```
>
> **After-reboot wheel bidirectional 360 probe generator**:
>
> ```bash
> set -a
> source /Users/biu/glassbox/.env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-wheel-bidir-360-after-reboot-v1 \
>   --wheel-probe \
>   --wheel-ticks 360 \
>   --wheel-second-ticks -360 \
>   --wheel-repeat 1 \
>   --wheel-focus-point 135,930
> ```
>
> **Keyboard insertion probe generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-keyboard-probe-v2 \
>   --keyboard-probe \
>   --keyboard-point 44,97 \
>   --keyboard-text gbvckbd
> ```
>
> **After-reboot keyboard retry generator**:
>
> ```bash
> set -a
> source /Users/biu/glassbox/.env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-keyboard-retry-after-reboot-v1 \
>   --keyboard-probe \
>   --keyboard-point 44,97 \
>   --keyboard-clear-before-type \
>   --keyboard-text gbvcretry
> ```
>
> **Patched facade keyboard retake generator**:
>
> ```bash
> set -a
> source /Users/biu/glassbox/.env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-keyboard-casefold-v1 \
>   --keyboard-probe \
>   --keyboard-point 44,97 \
>   --keyboard-clear-before-type \
>   --keyboard-text gbvccase
> ```
>
> **Keyboard Cmd-F focus probe generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-keyboard-cmdf-probe-v2 \
>   --keyboard-probe \
>   --keyboard-focus-method cmd_f \
>   --keyboard-clear-before-type \
>   --keyboard-text gbvccmdf
> ```
>
> **Keyboard overlay-off double-tap control generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-keyboard-overlay-off-doubletap-v1 \
>   --keyboard-probe \
>   --keyboard-disable-overlay-before-focus \
>   --keyboard-focus-method double_tap \
>   --keyboard-clear-before-type \
>   --keyboard-text gbvcoffdt
> ```
>
> **Discarded keyboard input-source switch probe generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-keyboard-overlay-off-switch-v1 \
>   --keyboard-probe \
>   --keyboard-disable-overlay-before-focus \
>   --keyboard-focus-method double_tap \
>   --keyboard-clear-before-type \
>   --keyboard-switch-input-before-type \
>   --allow-unsafe-keyboard-input-switch \
>   --keyboard-text gbvcswitch
> ```
>
> **FKA help preflight guard generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-fka-preflight-v2 \
>   --preflight-only
> ```
>
> **FKA help hard-stop bypass check generator**:
>
> ```bash
> set -a
> source .env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-fka-hardstop-v1 \
>   --no-require-overlay-page
> ```
>
> **After-reboot HDMI recovery/readiness generator**:
>
> ```bash
> set -a
> source /Users/biu/glassbox/.env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.ios_settings.diagnose --json \
>   | tee /tmp/glassbox-vc-diagnose-after-reboot-v1.json
> ```
>
> **Resume preflight generator**:
>
> ```bash
> set -a
> source /Users/biu/glassbox/.env
> set +a
> GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
>   --phone-model ipad_mini_7 \
>   --overlay-mode item_numbers \
>   --output-dir /tmp/glassbox-vc-overlay-ready-preflight-vN \
>   --preflight-only
> ```
>
> In this local run the rig env came from the sibling main worktree's `.env`.
> The harness sets `GLASSBOX_AI_ARTIFACT_DIR` under the output directory, so
> future runs do not need to leave source ledgers under repo `artifacts/`.

## Result

### Item Numbers

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `01_item_numbers_on_initial` | `settings/Overlay` | 45 | `item_numbers=11`, `item_names=1` | Continuous overlay was `Item Numbers`; one item-name false positive. |
| `tap_none` | same page | — | — | `tap_xy(299,116,cropped_px)` transport OK; semantic status `unknown` because same-page text changed. |
| `02_overlay_none_off` | `settings/Overlay` | 32 | `item_numbers=0`, `numbered_grid=0` | Numeric overlay markers disappeared. |
| `tap_item_numbers` | same page | — | — | `tap_xy(327,162,cropped_px)` transport OK; semantic status `unknown` for the same reason. |
| `03_item_numbers_on_restored` | `settings/Overlay` | 45 | `item_numbers=11`, `item_names=0` | Numeric overlay markers returned. |
| `3x swipe_scroll_probe` | same page | — | — | `tap_xy` and drag/swipe transport OK while overlay is active. |
| `04_item_numbers_after_scroll` | `settings/Overlay` | 42 | `item_numbers=11`, `item_names=0` | Sidebar scrolled to a different visible band. |

### Item Names

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `tap_item_names_initial` | same page | — | — | `tap_xy(320,208,cropped_px)` transport OK. |
| `01_item_names_initial` | `settings/Overlay` | 56 | `item_names=27` | Name badges visible and OCR-readable. Experimental mapping attached 23 scene elements. |
| `tap_none` | same page | — | — | `tap_xy(299,116,cropped_px)` transport OK. |
| `02_overlay_none_off` | `settings/Overlay` | 28 | all modes `0` | Overlay markers disappeared. |
| `tap_item_names` | same page | — | — | `tap_xy(320,208,cropped_px)` transport OK. |
| `03_item_names_restored` | `settings/Overlay` | 56 | `item_names=27` | Name badges returned. Experimental mapping attached 22 scene elements. |
| `restore_item_numbers` | same page | — | — | `tap_xy(327,162,cropped_px)` transport OK; rig left in Item Numbers mode. |

The probe JSON's `overlay_hint_mapping` was generated by the first prototype
matcher and shows the observed failure mode: several left-sidebar badges were
shifted to the next row (`Wallpaper` badge mapped to `Notifications`, etc.).
After adding below-badge geometry, text-match gating, and OCR typo tolerance, a
labeled replay over the saved `03_item_names_restored` scene produced this
offline result:

| Replay | Labels | Passed | Failed | Notes |
|---|---:|---:|---:|---|
| `voice_control_overlay_itemnames_labels_v1.json` | 12 | 12 | 0 | Includes expected-unmapped labels for `Dictate` and fused `Came Camera`; passes sidebar rows such as `Sii -> Siri`, `Wallpaper) -> Wallpaper`, `Notfications) -> Notifications`, and `AppS -> Apps`. |

This replay is a useful gate for the observed row-shift bug, not a broad enough
sample to enable default `WhiteboxHint.accessibility_id` writes.

### Numbered Grid

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `tap_numbered_grid_initial` | same page | — | — | `tap_xy(331,253,cropped_px)` transport OK. |
| `01_numbered_grid_initial` | `settings/Overlay` | 45 | `numbered_grid=5` | Grid markers visible and OCR-readable. |
| `tap_none` | same page | — | — | `tap_xy(299,116,cropped_px)` transport OK. |
| `02_overlay_none_off` | `settings/Overlay` | 28 | all modes `0` | Overlay markers disappeared. |
| `tap_numbered_grid` | same page | — | — | `tap_xy(331,253,cropped_px)` transport OK. |
| `03_numbered_grid_restored` | `settings/Overlay` | 43 | `numbered_grid=5` | Grid markers returned. |
| `3x swipe_scroll_probe` | same page | — | — | Long cropped-pixel swipes transport OK while grid overlay is active. |
| `04_numbered_grid_after_scroll` | `settings/Overlay` | 42 | `numbered_grid=4` | Sidebar scrolled to a different visible band. |
| `restore_item_numbers` | same page | — | — | `tap_xy(327,162,cropped_px)` transport OK; rig left in Item Numbers mode. |

### Text-targeted Tap Negative Probe

A follow-up one-off probe used the same explicit rig env
(`GLASSBOX_PHONE_MODEL=ipad_mini_7`, artifacts under
`/tmp/glassbox-vc-text-tap-ai-runs`) and called `phone.tap("Item Names")` while
the device was on `settings/Overlay` with `Item Numbers` active. The tap did
change the overlay from numbers to names, but the semantic-plan path did not
settle cleanly:

| Artifact | Result |
|---|---|
| `/tmp/glassbox-vc-text-tap-ai-runs/run_2026_06_04_15_53_07_945455/report.md` | Initial tap transport was `True` but semantic status stayed `unknown`. |
| same run, `review_timeline.json` | The plan then attempted additional actions, including `home`; one frame was classified as SpringBoard. |
| final exception | `expect_text('Item Names')` timed out after the last seen texts came from the Home/widget surface (`More`, `Hide`, `No Notes`, `Daxing`, ...). |

The rig was recovered by coordinate HID only: tap the visible Settings icon on
Home, tap the `Overlay` back affordance, then tap `Item Numbers` at
`(327,162,cropped_px)`. The recovered frame was again `settings/Overlay` with
`item_numbers=10` parsed markers.

### Wheel Hover Probe

The follow-up wheel probe used the reusable harness with the wheel focus point
explicitly interpreted as `cropped_px`. The device was on `settings/Overlay`
with `Item Numbers` active.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `03_item_numbers_restored` | `settings/Overlay` | 47 | `item_numbers=12` | Wheel baseline capture. |
| `wheel_scroll_probe` | same page | — | — | `scroll_wheel(90, focus=(135,930,cropped_px))` transport OK; PicoKVM backend, `executed_count=93`. |
| `04_item_numbers_after_wheel` | `settings/Overlay` | 46 | `item_numbers=12` | No clear semantic scroll movement. Updated analyzer reports `wheel_frame_diff.diff_ratio=0.008027` and `wheel_scroll_evidence="small_frame_change_with_semantic_or_ocr_delta"`. |
| `wheel_restore_scroll` | same page | — | — | `scroll_wheel(-90, focus=(135,930,cropped_px))` transport OK. |

This is a **negative/weak** wheel result, not a wheel validation: the only text
deltas were status/OCR changes such as time and `Airplane Moce -> Airplane Mode`,
while the frame diff stayed far below a full sidebar scroll.

The follow-up focus-click variant is also **not** a wheel validation. It did
produce a large frame diff (`0.292175`), but the analyzer now classifies it as
`page_changed_after_focus_or_wheel`: the focus click selected the sidebar
`Notifications` row, changing the page from `settings/Overlay` to
`settings/Notifications`.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `03_item_numbers_restored` | `settings/Overlay` | 48 | `item_numbers=13` | Wheel baseline capture. |
| `wheel_scroll_probe` | same page | — | — | `scroll_wheel(90, focus=(135,930,cropped_px), focus_click=True)` transport OK. |
| `04_item_numbers_after_wheel` | `settings/Notifications` | 70 | `item_numbers=8` | Page changed due focus click; not accepted as scroll evidence. |

The rig was recovered manually by tapping `Accessibility` in the sidebar,
`Voice Control`, then the `Overlay` row. The final recovered frame was again
`settings/Overlay` with Item Numbers visible.

The bidirectional wheel variant did not change the conclusion. It ran
`scroll_wheel(90)` and then `scroll_wheel(-90)` at the same cropped-pixel focus
point, with both transports OK and the page remaining `settings/Overlay`.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `03_item_numbers_restored` | `settings/Overlay` | 47 | `item_numbers=12` | Bidirectional baseline capture. |
| `wheel_scroll_probe` | same page | — | — | `scroll_wheel(90, focus=(135,930,cropped_px))` transport OK. |
| `04_item_numbers_after_wheel` | `settings/Overlay` | 47 | `item_numbers=13` | `diff_ratio=0.007753`; semantic deltas were OCR/status-like (`Kacler -> Kacier`, `• Search -> Q Search`). |
| `wheel_second_scroll_probe` | same page | — | — | `scroll_wheel(-90, focus=(135,930,cropped_px))` transport OK. |
| `05_item_numbers_after_wheel_second` | `settings/Overlay` | 48 | `item_numbers=12` | `diff_ratio=0.007524`; deltas reversed the same OCR noise. |

This rules out a simple wheel-sign error for this focus point. It is still
negative/weak evidence, not wheel-scroll validation.

After the FKA help trap was cleared by reboot, the same page accepted a larger
bidirectional wheel sample at the same cropped-pixel focus point. The rig first
reported PicoKVM video `no_signal`; `skills.regression.ios_settings.diagnose`
recovered HDMI video and decoded a `1920x1080` frame. A fresh preflight then
passed on `settings/Overlay`, and `/tmp/glassbox-vc-wheel-bidir-360-after-reboot-v1`
produced positive wheel-scroll evidence:

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `00_preflight` | `settings/Overlay` | 31 | all modes `0` | Guard passed; overlay was initially None. |
| `03_item_numbers_restored` | `settings/Overlay` | 49 | `item_numbers=11` | Item Numbers restored before wheel. |
| `wheel_scroll_probe` | same page | — | — | `scroll_wheel(360, focus=(135,930,cropped_px))` transport OK. |
| `04_item_numbers_after_wheel` | `settings/Overlay` | 42 | `item_numbers=11` | `wheel_scroll_evidence="frame_changed"`, `diff_ratio=0.087163`, semantic texts changed. |
| `wheel_second_scroll_probe` | same page | — | — | `scroll_wheel(-360, focus=(135,930,cropped_px))` transport OK. |
| `05_item_numbers_after_wheel_second` | `settings/Overlay` | 48 | `item_numbers=11` | `wheel_second_scroll_evidence="frame_changed"`, `diff_ratio=0.086383`, semantic texts changed in the opposite direction. |

This is a positive wheel result for this page/focus/tick size: hover-only
wheel works under an active Item Numbers overlay when the delta is large enough.

### Keyboard Insertion Probe

The keyboard probe now has a preflight guard: it first captures `00_preflight`
and requires `page_id == "settings/Overlay"` before it will execute taps or HID
typing. A previous ungarded run started on Notes and was discarded as invalid.
The valid v2 run started on `settings/Overlay` with `Item Numbers` active.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `00_preflight` | `settings/Overlay` | 45 | `item_numbers=12` | Guard passed; probe stayed on the intended page. |
| `tap_keyboard_field` | same page | — | — | `tap_xy(44,97,cropped_px)` transport OK. |
| `04_item_numbers_keyboard_focus` | `settings/Overlay` | 39 | `item_numbers=4` | Search field had focus and suggestions appeared. |
| `type_keyboard_text` | same page | — | — | `type_text("gbvckbd", verify=False)` transport OK; semantic reason said typed text was not visible. |
| `05_item_numbers_after_keyboard_type` | `settings/Overlay` | 46 | `item_numbers=11` | `keyboard_text_visible=false`; screenshot still showed Search placeholder, not `gbvckbd`. |
| restore keys | same page | — | — | Cmd-A, Delete, Esc transport OK/unknown semantic. |
| `06_item_numbers_after_keyboard_restore` | `settings/Overlay` | 45 | `item_numbers=10` | Page recovered; final restore tap kept Item Numbers active. |

This is a **negative** keyboard-visible-insertion result for this narrow path:
the search field focused, HID typing ACKed, but HDMI/OCR did not show the typed
string.

A second keyboard probe replaced the coordinate focus tap with `Cmd-F`, then
sent `Cmd-A`, `Delete`, and `type_text("gbvccmdf", verify=False)`. The preflight
passed and `Cmd-F` stayed on `settings/Overlay`, but typing still did not produce
visible text; after type, the page had changed to `settings/Voice Control`, and
the restore sequence ended on `settings/Accessibility` before manual coordinate
recovery.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `00_preflight` | `settings/Overlay` | 46 | `item_numbers=11` | Guard passed. |
| `keyboard_focus_cmd_f` | same page | — | — | `Cmd-F` transport OK. |
| `04_item_numbers_keyboard_focus` | `settings/Overlay` | 46 | `item_numbers=12` | Focus changed visible OCR (`Q Search -> • Search`) without page change. |
| clear keys | same page | — | — | Cmd-A and Delete transport OK. |
| `type_keyboard_text` | same page | — | — | `type_text("gbvccmdf", verify=False)` transport OK, but text was not visible. |
| `05_item_numbers_after_keyboard_type` | `settings/Voice Control` | 60 | `item_numbers=12` | `keyboard_text_visible=false`; page changed away from Overlay. |
| restore keys | `settings/Voice Control` | — | — | Cmd-A, Delete, Esc transport OK/unknown semantic. |
| `06_item_numbers_after_keyboard_restore` | `settings/Accessibility` | 60 | `item_numbers=5` | Manual coordinate recovery was needed to return to Overlay. |

This is also a **negative** keyboard-visible-insertion result. It suggests the
next attempt needs a safer text-field-specific activation strategy, not only a
different keyboard shortcut.

A third keyboard probe disabled the continuous overlay before focusing the
Search field, then double-tapped the field, cleared it, and typed
`gbvcoffdt`. This is a control sample: it does **not** validate overlay-active
typing; it checks whether the same HID keyboard path can visibly insert text
when overlay markers are gone.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `00_preflight` | `settings/Overlay` | 49 | `item_numbers=12` | Guard passed. |
| `keyboard_disable_overlay_before_focus` | same page | — | — | `tap_xy(299,116,cropped_px)` transport OK. |
| `04_item_numbers_keyboard_overlay_off` | `settings/Overlay` | 31 | all modes `0` | Overlay markers were off. |
| double tap Search | same page | — | — | Two `tap_xy(44,97,cropped_px)` actions transport OK. |
| `04_item_numbers_keyboard_focus` | `settings/Overlay` | 32 | all modes `0` | Search suggestions appeared (`Recents`, `Suggestions`, app names), but no typed text yet. |
| clear keys | same page | — | — | Cmd-A and Delete transport OK. |
| `type_keyboard_text` | same page | — | — | `type_text("gbvcoffdt", verify=False)` transport OK, but text was not visible. |
| `05_item_numbers_after_keyboard_type` | `settings/Overlay` | 32 | all modes `0` | `keyboard_text_visible=false`; page stayed on Overlay. |
| restore keys / overlay | same page | — | — | Restore keys left `settings/None`; final `tap_xy(327,162,cropped_px)` restored Item Numbers. |

This is a **negative control** for the current HID keyboard path: turning the
overlay off and using a text-field-specific double tap still did not produce
visible/OCR-readable inserted text. The failure is therefore not explained by
overlay text simply covering the input.

After the device was rebooted to clear the FKA help trap, a conservative retry
of the original Settings Search-field path succeeded. The probe stayed away from
`Ctrl-Space`: it focused Search by cropped-pixel tap, sent Cmd-A/Delete, and
typed `gbvcretry`.

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `00_preflight` | `settings/Overlay` | 47 | `item_numbers=12` | Guard passed; FKA help overlay absent. |
| `tap_keyboard_field` | `settings/Overlay` | — | — | `tap_xy(44,97,cropped_px)` transport OK; focus suggestions appeared. |
| `keyboard_pretype_select_all` / `keyboard_pretype_delete` | same page | — | — | Clear sequence transport OK. |
| `type_keyboard_text` | same page | — | — | `type_text("gbvcretry", verify=False)` transport OK; the immediate semantic check was too early/weak and reported typed text not visible. |
| `05_item_numbers_after_keyboard_type` | `page_id=null` | 19 | `item_numbers=1` | Analyzer found `keyboard_text_visible=true`; the token was visible in the post-type HDMI/OCR capture. |
| restore keys | same page | — | — | Cmd-A, Delete, Esc transport OK. |
| `06_item_numbers_after_keyboard_restore` | `settings/Overlay` | 35 | `item_numbers=1` | Restore returned to Overlay; a follow-up preflight restored stronger evidence with `item_numbers=12`. |

This is a positive keyboard-visible-insertion result for the coordinate Search
field path after reboot. It also exposes a verifier timing issue: the
`type_text` action's immediate semantic reason can be negative even when the
probe's later capture sees the inserted token. Follow-up code now makes
`AIPhone.type_text()` use the typed text as a post-action visible-text
expectation by default.

A 2026-06-05 patched-facade retake first reproduced one remaining verifier
bug: `gbvcpatch` was visible in the later HDMI/OCR capture as `Q Gbvcpatch` /
`"Gbvcpatch"`, but `AIPhone` still returned `unknown` because visible-text
matching was case-sensitive. After changing the facade matcher to compare
case-folded labels, the same guarded coordinate Search-field path passed with
`gbvccase`:

| Step | Page | OCR elements | Parsed markers | Notes |
|---|---|---:|---:|---|
| `00_preflight` | `settings/Overlay` | 45 | `item_numbers=10` | Guard passed; FKA help overlay absent. |
| `tap_keyboard_field` | `settings/Overlay` | — | — | `tap_xy(44,97,cropped_px)` transport OK; focus suggestions appeared. |
| `keyboard_pretype_select_all` / `keyboard_pretype_delete` | same page | — | — | Clear sequence transport OK. |
| `type_keyboard_text` | same page | — | — | `type_text("gbvccase", verify=False)` returned `semantic_status=succeeded`, `reason="AI facade expectation matched"`. |
| `05_item_numbers_after_keyboard_type` | `page_id=null` | 16 | all modes `0` | Analyzer found `keyboard_text_visible=true`; the token was visible in filtered Search results. |
| restore keys | same page | — | — | Cmd-A, Delete, Esc transport OK. |
| `06_item_numbers_after_keyboard_restore` | `settings/Overlay` | 35 | `item_numbers=1` | Restore returned to Overlay. |

This closes the patched `type_text` verifier retake for this one coordinate
Search-field path. It does not rehabilitate the earlier `Cmd-F`, overlay-off
double-tap, or `Ctrl-Space` variants.

The attempted input-source switch variant is **discarded as invalid**. It added
`--keyboard-switch-input-before-type`, which sends `Ctrl-Space` after focusing
Search with overlay markers off. The probe was stopped before final JSON
because it left the intended page and opened the iPadOS Full Keyboard Access
help overlay on Home. The only retained evidence is partial screenshots under
`/tmp/glassbox-vc-keyboard-overlay-off-switch-v1/`: after the input switch,
`05_item_numbers_after_keyboard_input_switch.png` shows Home, and
`05_item_numbers_after_keyboard_type.png` shows the FKA command help popover
(`Basic`, `Movement`, `Interaction`, `Device`). This run is not evidence for
or against text insertion; it only shows `Ctrl-Space` is unsafe as an
input-source recovery strategy on this rig. The current harness requires
`--allow-unsafe-keyboard-input-switch` before this action can run, and its
offline analyzer now reports `fka_help_overlay_detected` /
`keyboard_input_switch_opened_fka_help` if a future run captures this trap in
the JSON. If the device is already stuck there before a run starts, the
preflight guard now also reports `preflight_fka_help_overlay=true` and returns a
specific `preflight_error` asking the operator to clear the FKA help overlay
before on-rig probes. This FKA condition is a hard stop: it is not bypassed by
`--no-require-overlay-page`.

A real preflight-only replay on the stuck device produced
`/tmp/glassbox-vc-fka-preflight-v2/voice_control_overlay_ab.json` with exactly
one capture and no actions:

| Field | Value |
|---|---|
| exit code | `2` |
| `preflight_only` | `true` |
| `preflight_ok` | `false` |
| `preflight_page_id` | `null` |
| `preflight_fka_help_overlay` | `true` |
| `analysis.preflight_only` | `true` |
| `analysis.preflight_ready_for_probe` | `false` |
| `analysis.preflight_blocker` | `fka_help_overlay` |
| `analysis.fka_help_overlay_detected` | `true` |
| `analysis.fka_help_overlay_capture_labels` | `["00_preflight"]` |
| `analysis.action_count` | `0` |
| `analysis.preflight_stopped_before_actions` | `true` |
| actions after preflight | none |

A follow-up hard-stop check used `--no-require-overlay-page` while the device
was still stuck on the same FKA help overlay. It produced
`/tmp/glassbox-vc-fka-hardstop-v1/voice_control_overlay_ab.json`, also with
only the preflight capture and no actions:

| Field | Value |
|---|---|
| exit code | `2` |
| `preflight_only` | `false` |
| `preflight_ok` | `false` |
| `preflight_page_id` | `null` |
| `preflight_fka_help_overlay` | `true` |
| `analysis.preflight_only` | `false` |
| `analysis.preflight_ready_for_probe` | `false` |
| `analysis.preflight_blocker` | `fka_help_overlay` |
| `analysis.fka_help_overlay_detected` | `true` |
| `analysis.fka_help_overlay_capture_labels` | `["00_preflight"]` |
| `analysis.action_count` | `0` |
| `analysis.preflight_stopped_before_actions` | `true` |
| actions after preflight | none |

Later resume preflight checks showed the device remained on Home with the same
FKA help overlay. These runs were preflight-only and did not send HID actions:

| Run | Local rig time | exit | `preflight_ok` | `preflight_fka_help_overlay` | `analysis.preflight_blocker` | `analysis.action_count` | JSON |
|---|---|---:|---|---|---|---:|---|
| v2 | 2026-06-04 19:10 | `2` | `false` | `true` | `fka_help_overlay` | 0 | `/tmp/glassbox-vc-overlay-ready-preflight-v2/voice_control_overlay_ab.json` |
| v3 | 2026-06-04 19:14 | `2` | `false` | `true` | `fka_help_overlay` | 0 | `/tmp/glassbox-vc-overlay-ready-preflight-v3/voice_control_overlay_ab.json` |
| v4 | 2026-06-04 19:18 | `2` | `false` | `true` | `fka_help_overlay` | 0 | `/tmp/glassbox-vc-overlay-ready-preflight-v4/voice_control_overlay_ab.json` |

The latest `v4` run also had `analysis.preflight_stopped_before_actions=true`;
the transient H.264 decoder warnings during capture did not prevent the preflight
JSON from being written.

The parser also reports the same numeric badges if called with
`mode="numbered_grid"` while the device is actually in `Item Numbers` mode
(non-zero `numbered_grid` counts appear in the saved JSON for `Item Numbers`
captures). This is expected for the current prototype: `parse_voice_control_overlay`
is **mode-scoped**, not an overlay-mode detector. The caller must know the
configured Voice Control overlay mode.

## Conclusions

- HDMI frames are sufficient to verify `Item Numbers` overlay presence and
  absence on this rig: marker counts move from non-zero to zero and back.
- Coordinate HID tapping coexists with Voice Control overlay for this narrow
  Settings-page path. The tap transport succeeded both while overlay markers
  were visible and after they were disabled.
- Drag/swipe scrolling also coexists with Voice Control overlay in this narrow
  path for `Item Numbers` and `Numbered Grid`. The harness uses three long
  cropped-pixel swipes.
- A same-frame scene replay over `03_item_numbers_on_restored` parsed `6`
  item-number markers from the scene OCR and attached `5` of them to non-overlay
  elements when the probe explicitly enabled frame-local number hints.
- `Item Numbers` are **not stable element identities across scroll** in this
  sample. Two labels visible before and after scroll changed ids:
  `Siri: vc:item_number:22 -> vc:item_number:13` and
  `Wallpaper: vc:item_number:23 -> vc:item_number:15`.
- Follow-up `Item Names` probing showed HDMI/OCR can read many visible name
  badges (`27` markers before and after off/on restore). The first prototype
  badge-to-target matcher was not reliable enough for default memory identity:
  badges can be placed above or below the target, and VisionOCR can fuse badge
  text with underlying row text. The current matcher fixes the observed row-shift
  bug on a 12-label replay of the saved scene, but broader labeled replay is
  still required before default identity writes.
- `Numbered Grid` is also HDMI-verifiable on this page: counts moved
  `5 -> 0 -> 5`, then `4` after scroll. It is still a frame-local spatial
  anchor, not a stable element identity.
- Text-targeted taps are **not** safe to treat as validated under an active
  overlay. A one-off `phone.tap("Item Names")` sample changed the overlay but
  then drifted into the Home/widget surface and ended in an assertion timeout.
- Hover-only wheel under an active overlay is **validated for a larger delta**
  on this page/focus point. The early `90` and `90 -> -90` probes were
  transport-positive but too weak (`diff_ratio=0.008027`, then `0.007753` /
  `0.007524`). After reboot and HDMI recovery, `360 -> -360` at the same
  cropped-pixel focus point kept the page on `settings/Overlay` and produced
  bidirectional `wheel_scroll_evidence="frame_changed"` with frame diffs
  `0.087163` and `0.086383`.
- Focus-click wheel is **not** validated either. It produced a large frame diff,
  but by selecting a different Settings row (`Notifications`) rather than by
  scrolling the Overlay page.
- Keyboard visible insertion under an active overlay is **validated for the
  coordinate Search-field path after reboot**. Earlier samples were negative:
  `gbvckbd`, `gbvccmdf`, and overlay-off `gbvcoffdt` were not visible, and the
  `Cmd-F` sample could navigate away from Overlay. After reboot, the guarded
  coordinate Search-field retry inserted `gbvcretry`; the immediate `type_text`
  semantic reason was still negative, but the later HDMI/OCR capture reported
  `keyboard_text_visible=true`. A 2026-06-05 patched-facade retake inserted
  `gbvccase`; `AIPhone.type_text()` returned `semantic_status=succeeded` after
  matching the case-folded visible text, and the later capture again reported
  `keyboard_text_visible=true`. A discarded `Ctrl-Space`
  input-source switch attempt remains invalid and unsafe: it left Settings and
  opened the Full Keyboard Access help overlay on Home.
- This is **not** a task-success rate and not proof of voice recognition. It is
  a small structural probe over one page, one device, and three overlay
  coordinates.

## Still Open

- Safe resume path after the FKA help trap:
  1. Clear the Full Keyboard Access help overlay manually or physically on the
     device.
  2. Return the device to `Settings > Accessibility > Voice Control > Overlay`.
  3. Run the preflight-only guard before any destructive or state-changing
     probe:

     ```bash
     set -a
     source .env
     set +a
     GLASSBOX_PHONE_MODEL=ipad_mini_7 uv run python -m skills.regression.voice_control_overlay_probe \
       --phone-model ipad_mini_7 \
       --overlay-mode item_numbers \
       --output-dir /tmp/glassbox-vc-overlay-ready-preflight-v1 \
       --preflight-only
     ```

  4. Continue keyboard/wheel probes only if that run exits `0` and reports
     `analysis.preflight_ready_for_probe=true` with
     `analysis.preflight_blocker=null`.
- Text-targeted taps under an active overlay need a redesigned plan or guardrail;
  the 2026-06-04 `phone.tap("Item Names")` sample is a negative result, not a
  validation.
- Keyboard visible insertion is now accepted for one coordinate Search-field
  retry after reboot. The run exposed a timing bug where the immediate
  `type_text` verifier reported "typed text is not visible" before the later
  probe capture saw `gbvcretry`. The patched AI facade now waits for the typed
  text as a post-action expectation by default and matches visible text
  case-insensitively; the 2026-06-05 retake with `gbvccase` returned
  `semantic_status=succeeded`. Do not use `Ctrl-Space` as an input-source
  strategy on this rig: the discarded switch-input run opened Full Keyboard
  Access help on Home.
- Wheel scrolling is now accepted for `360 -> -360` at `(135,930,cropped_px)`,
  but smaller `90` deltas remain weak and focus-click changes page selection.
  Future callers should treat wheel validation as page/focus/tick-size specific.
- Number stability after scroll is contradicted for `Item Numbers` in this
  sample. Treat numeric/grid overlay ids as frame-local action anchors, not
  persistent memory keys. The implementation therefore does not write them to
  `WhiteboxHint.accessibility_id` by default.
- Overlay-to-element mapping still needs a broader labeled replay set. A first
  12-label Item Names replay over the saved Overlay scene now passes, but the
  default remains conservative: `apply_voice_control_overlay_hints` does not
  write names or numbers by default; callers must explicitly opt in to
  experimental name mapping or frame-local number anchors.
- Real Voice Control speech recognition is out of scope for HDMI-only probing;
  that needs audio injection or human speech.

## 2026-06-10 follow-up: v2 captures (General pane + scrolled sidebar)

Two further Item Names captures on the same iPad mini 7 rig (overlay enabled
via coordinate taps, then restored: overlay None + Voice Control toggle OFF,
pixel-verified). Frames/scenes stay in local artifacts (`/tmp/vc-captures`,
sidebar-at-top frames show the account row, so frames are NOT committed);
label manifests are committed as
`voice_control_overlay_itemnames_labels_general_v2.json` (17 labels — General
detail pane with the right-of-target badge geometry + 4 sidebar pairs +
2 negatives) and `..._scrolled_v2.json` (15 labels — sidebar scrolled to a
mid position, including two heavily garbled markers `M Touch n9` /
`Ne wallet ns` that the matcher correctly bridges to Touch ID / Wallet).
Both replay 17/17 and 15/15 against the real captured scenes and are now part
of the committed mapping-contract smoke gate (44 labels over 3 captures).

**Known matcher gaps surfaced by the v2 captures (worklist, deliberately NOT
committed as labels so the gate asserts only current behavior):**

1. `ADOUt` badge → `About` row (pane, marker (446,299) → target (337,327)):
   compact-similarity 0.80 sits just under the 0.82 SequenceMatcher floor in
   `_name_text_matches` — a 1-substitution OCR typo on a 5-char label fails.
2. `AutOFiI` badge → `AutoFill & Passwords` (pane, (444,708) → (384,735)):
   badge text is a truncated garble of a long row label; neither substring,
   token-intersection, nor ratio bridges it.
3. `Wallpaper` badge → `Wallpaper` row at the SCROLLED sidebar position
   ((129,478) → (99,450)): text identical yet `target_missing` — the same
   pair maps fine at the top position (v2 general, (131,848) → (101,820)).
4. `Notifications）` badge → `Notifications` row (scrolled, (130,531) →
   (109,502)): same pattern as 3 (text compacts to equality, geometry within
   bounds, still `target_missing`).

3/4 suggest the scrolled-position failures are not text matching but target
candidate filtering (possibly the row text region failing/passing the
dark-badge pixel gate differently mid-scroll); reproduce offline with the
saved scenes via `voice_control_overlay_labeled_replay --labels <draft>` —
the failing draft labels are preserved in the local capture directory.
