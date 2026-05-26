# iPad mini Migration (target device: iPhone → iPad mini)

Status: baseline implemented on 2026-05-25. The tree can select an **iPad mini 7
(A17 Pro, USB-C, iPadOS)** profile over the same out-of-band PicoKVM USB-HID rig;
this note now tracks the remaining iPad-specific hardening.

Implemented baseline:
- `ipad_mini_7` device geometry (1488×2266 pixels, 744×1133 points).
- `ipados` platform variant with iPad safe-area geometry and split-view Settings
  scene classification.
- PicoKVM iPad behavior: no AssistiveTouch requirement, wheel transport exposed
  only as a bounded diagnostic path on the current rig, and crop-derived
  absolute-pointer calibration unless `GLASSBOX_PICOKVM_ABS_*` values are
  explicitly provided.
- iPad Settings navigation hooks: sidebar-only root candidates, right-detail-pane
  child candidates, iPad row tap points, and no back action after root-sidebar
  selection.
- iPad Settings search hooks: the policy can use the sidebar top search field,
  English/en-HK root search queries, OCR-number-prefixed search results, and
  split-view detail-title success checks.
- iPad top-search recovery: hidden/active top query states are cleared with a
  pointer-only edit-menu path (`Select All` → `Cut`) before retrying search.
- iPad Settings root drill-down safety: search fallback success now requires the
  opened split-view detail title to match the requested root, failed searches
  are reported as `search_no_result`, and stale/shifted taps keep the observed
  detail title instead of crediting the requested root.
- Hardware smoke on connected rig: PicoKVM RPC reachable, HDMI frame 1920×1080,
  iPad 3:2 crop auto-detected, keyboard Home HID consumed and classified as
  SpringBoard/Home from clean surfaces. Absolute pointer taps land on Settings
  sidebar rows, Settings right-pane details, and visible iPad Home icons.

Remaining hardening: iPad SpringBoard real Home-folder modeling beyond visible
and multi-page Home icons, broader split-view Settings inventory beyond the
current twelve actionable shared roots plus the first fourteen extra safe top-level
pages and six explicit blocked stop points, and a replacement for the disproven
Settings sidebar wheel-scroll assumption.

Hardware corrections from the connected iPad mini rig (2026-05-25):
- `wheelReport` ACKs but does **not** semantically scroll the iPad Settings
  sidebar on this PicoKVM/iPadOS path. Probes with hover, focus-click,
  different sidebar points, larger tick counts, raw pointer drag, arrow keys,
  PageUp/PageDown, and Cmd+F showed no sidebar movement.
  A later bounded drill-down still recorded all `scroll_wheel` actions as
  no-progress in the HID trace; any `probe=progress` line is treated as weak OCR
  or page-state signal, not proof that wheel scrolling works.
- iPad top search can show Settings search results, but the old iPhone search
  recovery was wrong because it assumed the bottom Search tab and bottom clear
  control. The code now avoids the bottom clear fallback on iPad top search and
  matches English/en-HK result text such as `Battery`.
- A live stuck iPad Settings top-search state (`BatteryBattery`, no results)
  was previously misclassified as `springboard`; it is now classified as
  `settings_search_results`. Direct clear-button/keyboard/Home attempts were
  not reliable, but the connected rig proved a pointer-only recovery:
  long-press the top query field, tap `Select All`, then tap `Cut`. The crawler
  now uses that path first on iPad, can focus hidden top-query fields before
  clearing, and stops instead of appending another query if clearing still
  fails.
- A later live stuck search state (`Q WLANWLAN`, no results) exposed a second
  classifier edge: right-pane `Calendar Alerts` text looked like an iPad Home
  Calendar widget and made the scene `springboard`. Strong top-search/no-results
  evidence now beats the Home-widget heuristic, so the same dirty state
  classifies as `settings_search_results` and recovery can clear it.
- A live Weather Settings search/detail overlay exposed the same class of
  iPadOS scene risk without no-results text: the right-pane `Weather` detail
  and top query could look like Home widget content. A top query plus Settings
  search result path hints and a visible detail pane now beats the Home-widget
  heuristic, and iPad search fallback first taps an already-visible exact result
  before relying on keyboard input.
- Live Settings top-search fallback is now proven on the connected iPad with
  `GLASSBOX_LANGUAGE=en`: from a clean root/sidebar state,
  `_open_root_label_via_search(..., "电池")` searched `Battery`, clicked the
  result, returned `True`, and landed on the `Battery` detail pane. English UI
  requires the English locale; the zh default query (`dianchi`) produced keyboard
  candidates/no Settings result on this device.
- PicoKVM keyboard `type()` now has a small configurable inter-key gap so iPadOS
  does not drop repeated letters (`Battery` previously became `Baery`, which
  then led to no-results and duplicate-query states).
- iPad Home widget pages were briefly misclassified as Settings top-search
  results because a widget number fell into the top-search band. The classifier
  now recognizes iPad Home widgets before Settings top-search and tightens the
  top-search geometry; `home()` semantic verification now succeeds on the live
  iPad Home page.
- Settings foregrounding from iPad Home is now proved on hardware. The OCR
  `Settings` icon label at `(381, 775)` needs a shallower iPad icon tap point
  around `(381, 740)`; that direct Home icon path opens Settings. When the
  current Home page is a widget/Today page without the Settings icon,
  SpringBoard scanning plus Spotlight fallback also opened Settings, and
  `_open_settings_from_home_if_visible` ended with `is_root=True`.
- A live quick drill-down now passes through the public runner:
  `run_full --quick --drill-down --language en --region HK` foregrounded
  Settings, opened six root detail panes in split view, and verified the report
  (`navigation_success_proxy_rate=1.0`, `8` visits, no navigation failures).
  The verifier now treats depth-limited sample visits as terminal instead of
  requiring blocked-page evidence for rows the crawler was not allowed to open.
- A bounded hardware drill-down with a higher page budget
  (`IOS_SETTINGS_MAX_PAGES=24`, depth 1, en-HK) now recovers from dirty iPad
  top-search states, opens eight expected root detail panes plus observed
  non-coverage pages such as `Camera`, records missed search fallbacks as
  `search_no_result`, and passes `verify_report --allow-partial`. It is still
  not exhaustive: several root sections remain missing because top-search
  fallback hit rate is insufficient and wheel scrolling is not authoritative.
- A later bounded hardware drill-down
  (`IOS_SETTINGS_MAX_PAGES=32`, `IOS_SETTINGS_MAX_SCROLLS_PER_PAGE=2`, depth 1,
  en-HK; report `/tmp/ipad-settings-search-drill-6.json`) added an iPad
  top-search refocus/re-poll after typing and raised expected root detail
  coverage from 8 to 11 of the shared 17-label iPhone/cross-device acceptance
  vocabulary, not an iPadOS Settings sidebar count.
  The recovered set includes `WLAN`, `Bluetooth`, `Notifications`, `General`,
  and `Accessibility`; the report passes
  `verify_report --allow-partial` after verifier root evidence is resolved using
  the report locale (`en-HK`, so `WLAN` maps back to `无线局域网`). Missing sections
  remain `Mobile Service`, `Action Button`, `StandBy`, `Emergency SOS`,
  `Battery`, and `Wallet & Apple Pay`.
- The next bounded drill-down after search-result filtering
  (`/tmp/ipad-settings-search-drill-7.json`) raised the best observed expected
  root detail coverage to 12 of those shared labels by recovering `Battery`; the
  report verifies with `verify_report --allow-partial`. The search-result picker
  now refuses to treat the active top-query text as a root result, so a
  `No Results for "MobileService"` state is recorded as `search_no_result`
  instead of tapping the query field. A follow-up dirty-state run
  (`/tmp/ipad-settings-search-drill-8.json`) verified the related split-OCR
  cleanup fix: `Q` + `ActionButton` is treated as an active query, so the next
  search no longer appends into `ActionButtonStandBy`.
- Settings reports now separate root misses by actionability: `entry_exempt`
  covers design/device-exempt roots such as `Wallet & Apple Pay`, `search_absent`
  records sections that Settings search explicitly returned as no-result on the
  run (for example `Mobile Service`, `Action Button`, `StandBy`, and
  `Emergency SOS` on `/tmp/ipad-settings-search-drill-7.json`), and
  `required_missing` is the remaining strict coverage gap. This keeps iPadOS
  device/profile differences visible without counting coverage-only roots as
  crawler-ready misses.
- New Settings reports also include `config.platform`/`config.phone_model`;
  when that context is iPadOS, repeated no-result search evidence for
  iPhone-oriented roots (`Mobile Service`, `Action Button`, `StandBy`,
  `Emergency SOS`) is promoted to `device_unavailable`/`entry_exempt`. This is
  deliberately gated on iPad context plus captured no-result evidence, so iPhone
  or capable iPad profiles still require those sections.
- A fresh bounded hardware drill-down after those report changes
  (`/tmp/ipad-settings-search-drill-10.json`, same page/scroll budget, en-HK)
  raised entered shared-label root coverage to 11 by recovering
  `Sounds & Haptics`, `Touch ID & Passcode`, and `Privacy & Security`. With
  iPad-only no-result roots plus `Wallet & Apple Pay` counted as entry-exempt,
  `Screen Time` was the only remaining required root miss on the connected iPad.
  The fixes were:
  prefer exact root display labels over alias search results (so `Sounds` does
  not steal `Sounds & Haptics`), use shorter iPad English search queries for
  `Passcode`/`Privacy`, and treat non-strict root candidate audit findings as
  warnings instead of strict verifier blockers. A follow-up run
  (`/tmp/ipad-settings-search-drill-11.json`) started from a lower sidebar
  position and confirmed the same recovered roots, but hit `return_to_root_failed`
  before proving the remaining iPhone-only no-result roots again.
- A later bounded hardware drill-down
  (`/tmp/ipad-settings-search-drill-12.json`, same budget, en-HK) fixed the
  final required Settings root miss. The Screen Time search result appears as a
  query-suggestion-like pair (`ScreenTime 6` + `Screen Time`) before the actual
  root result; tapping either suggestion line rewrites the query to `ScreenTime`
  and produces no-results. The picker now skips numbered compact suggestions and
  selects the later real `Screen Time` result. The report passes strict
  verification with `root_required_missing_count=0`,
  `root_entry_exempt_count=5`, and `exhaustive_ready=true`. The `17` root labels
  are not the iPadOS Settings sidebar count; they are only the shared
  iPhone/cross-device vocabulary currently used by the crawler. On this iPad
  profile the strict actionable required root set is `12` after the five
  entry-exempt roots are removed. Full iPadOS Settings inventory remains a
  separate coverage target from this shared-root acceptance gate.
- The same later run still recorded every `scroll_wheel` operation as
  no-progress (`3/3`), so the document should not treat iPadOS wheel as usable
  yet. Acceptance should continue to come from visible sidebar rows, title-checked
  top-search fallback, and graph/search recovery until a new HID path proves
  semantic scroll movement.
- Split-view Settings child traversal is now policy-modeled separately from root
  coverage: root scans emit only left-sidebar rows, while depth>0 child scans emit
  only right-detail-pane rows and require a right-pane navigation affordance for
  unknown labels. A live child audit on the connected iPad
  (`/tmp/ipad-settings-child-audit-7.json`) opened `General`, entered the
  right-pane child page `Settings > 通用 > Fonts`, returned without losing the
  parent/root state, and passed with no navigation failures. Follow-up hardening
  from that run: iPad back fallback now targets the detail pane instead of the
  full-screen iPhone top-left point, split-view visible-back detection accepts
  the right-pane boundary chevron, child audit metrics count only the requested
  target roots instead of the shared 17-label acceptance vocabulary, and detail
  candidates exclude the current page title/summary aliases.
- A stricter multi-root child audit
  (`/tmp/ipad-settings-child-audit-11.json`) now passes on hardware for both
  target roots: `Settings > 通用 > Software Update` and
  `Settings > 辅助功能 > VoiceOver`, with `target_roots_missing_child=[]`, no
  navigation failures, and `navigation_success_proxy_rate=1.0`. The fix is
  generic iPad detail-list structure, not an Accessibility whitelist: OCR value
  text such as `Off >` now counts as a trailing disclosure affordance for the row
  label on the same y-band, while the value text itself remains non-navigable.
  The run is still a bounded sample (`sample_limits_hit=["max_candidates_per_page"]`),
  so it proves the split-view transition/back primitive on two high-value roots,
  not exhaustive iPad Settings child inventory.
- A broader six-root child audit
  (`/tmp/ipad-settings-child-audit-18.json`) now passes on hardware for
  `General`, `Accessibility`, `Notifications`, `Privacy & Security`, `Battery`,
  and `Siri`: every target root opened, every target reached a deeper child
  (`About`, `VoiceOver`, `Scheduled Summary`, `Location Services`,
  `Battery Health`, `Talk to Siri`), `target_roots_missing_child=[]`,
  `limits_hit=[]`, no blocked/rejected candidates, no navigation failures, and
  `navigation_success_proxy_rate=1.0`. The generic fixes from the failing
  intermediate runs were: exact safe-known iPad detail labels can be tapped
  without a visible chevron, selector/toggle roots such as Battery/Notifications
  are no longer whole-page blocked when a right-pane disclosure row exists, the
  post-search iPad top query is cleared after opening a root detail, and minimal
  repeated-title detail pages such as `Scheduled Summary` classify as
  `settings_detail`.
- A supplemental tail-three child audit
  (`/tmp/ipad-settings-child-audit-tail-3-1.json`) now passes on hardware for
  the remaining high-value shared roots `Sounds & Haptics`, `Focus`, and
  `Screen Time`, reaching `Ringtone`, `Focus`, and `Downtime` respectively with
  `target_roots_missing_child=[]`, `target_failures=[]`, `limits_hit=[]`, and no
  known issues. The fixes behind the Screen Time recovery were generic iPad
  split-view handling: dashboard metric OCR such as `•avg` no longer steals the
  detail title, exact safe Screen Time child rows do not require flaky chevron
  OCR, sidebar row search is canonical-label aware (`屏幕使用时间` matches
  `Screen Time`), and right-pane taps are projected farther inside the detail
  pane instead of near the split boundary.
- A single all-nine consolidation child audit
  (`/tmp/ipad-settings-child-audit-22.json`) now passes on hardware for
  `General`, `Accessibility`, `Notifications`, `Privacy & Security`, `Battery`,
  `Siri`, `Sounds & Haptics`, `Focus`, and `Screen Time`: all nine target roots
  opened, all nine reached a deeper child (`About`, `VoiceOver`,
  `Scheduled Summary`, `Location Services`, `Battery Health`, `Talk to Siri`,
  `Ringtone`, `Focus`, `Downtime`), `target_roots_missing_child=[]`,
  `target_failures=[]`, `limits_hit=[]`, no known issues, and
  `navigation_success_proxy_rate=1.0`. This consolidates the prior six-root and
  tail-three evidence into one bounded hardware report; it is still not a claim
  of exhaustive iPad Settings child inventory.
- A broader General-only multi-child audit
  (`/private/tmp/ipad-settings-general-broad-child-6.json`) now passes on
  hardware with an English target label (`General`) even when the visible
  sidebar starts away from the General row. It opens `Settings > General`, then
  reaches five Settings-native child pages in one bounded run: `About`,
  `Software Update`, the iPad Storage app-list page OCR'd as `Q Applications`,
  `AirPlay & Continuity`, and `Screen Capture`. The iPad Storage/app-list page is
  stopped as `dynamic app list rows`, so the run does not open individual app
  storage rows. The report has `target_roots_missing_child=[]`,
  `target_failures=[]`, `limits_hit=[]`, no known issues,
  `return_root_failed=false`, and `navigation_success_proxy_rate=1.0`.
  Fixes behind this run are generic: shared-root English labels are canonicalized
  before top-search query selection, iPad split-view return confirmation no
  longer accepts left-sidebar text overlap as proof that the right detail pane
  returned to its parent, a final strict settle check catches late iPad back
  animations, and non-returnable/purchase-or-selector child labels such as
  `AppleCare & Warranty` and `AirDrop` are not entered as broad child samples.
- A Display & Brightness multi-child audit
  (`/private/tmp/ipad-settings-display-brightness-broad-child-1.json`) now
  passes on hardware as another settings-native broad sample. It opens
  `Settings > Display & Brightness`, reaches `Liquid Glass` and `Night Shift`,
  and returns without target failures, traversal limits, blocked pages,
  navigation failures, or known issues (`navigation_success_proxy_rate=1.0`).
  This is narrower than the General broad-child pass, but it independently
  proves right-pane child selection and return on a non-shared extra top-level
  Settings page.
- A Sounds & Haptics multi-child audit
  (`/private/tmp/ipad-settings-sounds-broad-child-1.json`) now passes on
  hardware for a shared root that previously had only one child in the
  consolidation report. It opens `Settings > Sounds & Haptics`, then reaches and
  returns from four ringtone/alert selector pages (`Ringtone`, `Text Tone`,
  `New Mail`, and `Sent Mail`) without target failures, hard traversal limits,
  blocked pages, navigation failures, or known issues
  (`navigation_success_proxy_rate=1.0`). The run is bounded by
  `max_candidates_per_page`/`max_depth`, so it is still sample coverage, not
  exhaustive Settings inventory.
- An Accessibility multi-child audit
  (`/private/tmp/ipad-settings-accessibility-broad-child-1.json`) now passes on
  hardware as a broader shared-root sample. It opens `Settings > Accessibility`,
  then reaches and returns from five Settings-native child pages (`Zoom`,
  `Hover Text`, `Audio Descriptions`, `Switch Control`, and `Voice Control`)
  without target failures, hard traversal limits, blocked pages, navigation
  failures, or known issues (`navigation_success_proxy_rate=1.0`). This extends
  the earlier all-nine child proof, which only sampled one Accessibility child,
  while still remaining bounded by `max_candidates_per_page`/`max_depth`.
- A Siri multi-child audit (`/private/tmp/ipad-settings-siri-broad-child-2.json`)
  now passes on hardware as another settings-native shared-root sample. It opens
  `Settings > Siri`, then reaches `Talk to Siri` and the Siri-owned `App Clips`
  suggestions page with `target_roots_missing_child=[]`, no target failures, no
  hard limits, no blocked pages, no navigation failures, and
  `navigation_success_proxy_rate=1.0`. The generic fix behind this was to make
  child-page blockers with row markers require the page marker as its own stable
  visible row; otherwise Siri's `Allow Notifications` row falsely matched the
  `Notifications` page blocker.
- A Notifications multi-child audit
  (`/private/tmp/ipad-settings-notifications-broad-child-3.json`) now passes on
  hardware with the iPad top-search panel still visible in the left sidebar. It
  opens `Settings > Notifications`, then reaches `Scheduled Summary` and
  `Show Previews` with `target_roots_missing_child=[]`, no target failures, no
  hard limits, no navigation failures, and `navigation_success_proxy_rate=1.0`.
  The `Show Previews` child page is correctly recorded as
  `Notification preview selector rows`, so the crawler observes the child page
  but does not change the preview setting. The generic fixes are that
  `Scheduled Summary`/`Show Previews` are exact safe child labels when chevron
  OCR is missing, and right-detail safe child evidence can relax a selector
  blocker even when the left sidebar search panel still shows
  `Suggestions`/`Recents`.
- A blocked-target child audit
  (`/tmp/ipad-settings-child-audit-blocked-3-1.json`) now proves the remaining
  actionable shared roots on this iPad profile are handled conservatively:
  `WLAN`, `Bluetooth`, and the internal `Face ID与密码` target displayed as
  `Touch ID & Passcode` all open, then stop at the root detail with explicit
  blocked reasons (`dynamic Wi-Fi rows`,
  `dynamic Bluetooth device rows`, and `passcode and biometric settings`).
  The report passes with `target_roots_blocked` covering all three targets,
  `target_failures=[]`, `target_roots_missing_child=[]`, `limits_hit=[]`, and no
  known issues. This is intentional read-only behavior: dynamic network/device
  rows and passcode/biometric controls are coverage evidence, not child
  traversal targets.
- An extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-camera-wallpaper-2.json`) now passes for
  shared-vocabulary-external safe Settings pages: `Camera` and `Wallpaper` both
  open with `root_required_missing_count=0`, no target failures, no limits, and
  no known issues. `Camera` reaches the deeper child page
  `Settings > Camera > Record Slo-mo`; `Wallpaper` is recorded as root-only
  coverage in `target_roots_without_child`, because the page did not expose a
  safe deeper child in the bounded sample. This begins broader iPad Settings
  inventory beyond the twelve actionable shared roots without pretending the
  child inventory is exhaustive.
- A second extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-3-1.json`) now passes for
  `Control Centre`, `Display & Brightness`, and `Multitasking & Gestures`.
  All three open with `root_required_missing_count=0`, no target failures, no
  limits, and no known issues. `Display & Brightness` reaches two deeper child
  pages (`Liquid Glass` and `Night Shift`); `Control Centre` and
  `Multitasking & Gestures` are recorded as root-only coverage in the bounded
  sample. A broader four-target attempt including `Search`
  (`/tmp/ipad-settings-extra-inventory-4-2.json`) still failed to open the
  `Search` settings page, so `Search` remains observed-but-not-accepted because
  it is ambiguous with the top sidebar search field.
- A third extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-pencil-home-1.json`) now passes for
  `Apple Pencil` and `Home Screen & App Library`. Both open with
  `root_required_missing_count=0`, no target failures, no limits, and no known
  issues. `Apple Pencil` reaches `Bottom Left Corner` and `Bottom Right Corner`;
  `Home Screen & App Library` is recorded as root-only coverage. The crawler now
  handles the split sidebar OCR form (`Home Screen &` / `App Library`) by matching
  the ampersand-ended first line to the full target label, then validating the
  opened detail title.
- A fourth extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-search-open-2-1.json`) now proves that
  safe non-shared Settings pages can be opened through iPad Settings top search,
  not only by currently visible sidebar rows. `Safari` and `FaceTime` both open
  as root-only coverage with `root_required_missing_count=0`, no target failures,
  no limits, and no known issues. The failed broader attempt
  (`/tmp/ipad-settings-extra-inventory-search-open-3-2.json`) left `Apps`
  observed-but-not-accepted at that point, matching the earlier `Search` result.
- A fifth extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-apps-6.json`) now accepts `Apps` as
  root-only coverage. The report opens `Settings > Apps` with title `Apps`,
  `opened_target_roots=["Apps"]`, `target_roots_without_child=["Apps"]`,
  `target_failures=[]`, `target_roots_missing_child=[]`, `limits_hit=[]`, no
  known issues, and `navigation_success_proxy_rate=1.0`. This also locks the
  related iPad top-search/detail-title fixes: `Q Search Apps` must not steal the
  page title, and an empty top-search `Suggestions`/`Recents` panel must not be
  treated as normal sidebar root rows. `Search` remains observed but not accepted
  because it is ambiguous with the sidebar search control.
  A later fresh-install read-only check
  (`/private/tmp/ipad-settings-apps-gamecenter-root-blocked-readonly-2.json`)
  upgrades `Apps` from root-only coverage to an explicit blocked stop point:
  it opens only the `Apps` root detail page, records `dynamic app list rows`,
  and exposes no safe child candidates, so the crawler does not drill into app
  permission panels such as `Books`.
- A sixth extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-game-center-2.json`) now accepts
  `Game Center` as root-only coverage. The report starts from the already opened
  split-view detail page, records `Settings > Game Center` with title
  `Game Center`, `opened_target_roots=["Game Center"]`,
  `target_roots_without_child=["Game Center"]`, `target_failures=[]`,
  `target_roots_missing_child=[]`, `limits_hit=[]`, no known issues,
  `return_root_failed=false`, and `navigation_success_proxy_rate=1.0`.
  This is intentionally root-only: `Game Center` onboarding/profile setup text is
  treated as a child-traversal block, so the crawler observes the page but does
  not chase profile, friend, sign-out, or setup controls.
  The same later read-only check now records `Game Center` as
  `game center onboarding requires action` with no safe child candidates, again
  without tapping through first-run setup.
- A seventh extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-weather-2.json`) now accepts `Weather` as
  root-only coverage. The report starts from a different selected Settings page
  with the iPad top-search panel open, opens `Settings > Weather`, and records
  `opened_target_roots=["Weather"]`, `target_roots_without_child=["Weather"]`,
  `target_failures=[]`, `target_roots_missing_child=[]`, `limits_hit=[]`, no
  known issues, `return_root_failed=false`, and
  `navigation_success_proxy_rate=1.0`. This locks the generic fixes for
  non-shared extra-root title validation, visible iPad search-result taps before
  keyboard input, and Weather search/detail overlays not being treated as
  SpringBoard.
- An eighth extra top-level inventory audit
  (`/tmp/ipad-settings-extra-inventory-books-translate-1.json`) now accepts
  `Books` and `Translate` as root-only coverage. The report opens
  `Settings > Books` and `Settings > Translate`, records
  `opened_target_roots=["Books", "Translate"]`,
  `target_roots_without_child=["Books", "Translate"]`, `target_failures=[]`,
  `target_roots_missing_child=[]`, `limits_hit=[]`, no known issues,
  `return_root_failed=false`, and `navigation_success_proxy_rate=1.0`.
- iPad SpringBoard foregrounding is now proved beyond Settings for a visible Home
  icon: `/tmp/ipad-springboard-files-open-2.json` opened `Files` from the current
  iPad Home page (`ok=true`, `is_home_after_open=false`). The first Files run also
  exposed a false positive where Files' two-column UI was classified as
  `settings_search_results`; the iPad top-search classifier now requires a real
  top search affordance or query+edit/no-results evidence, so Files settles to
  `unknown` instead of a Settings scene. OCR icon matching was tightened so iPad
  Home widget text such as `- Notes` is not treated as an app icon while real
  visible labels like `Settings`, `Files`, `App Store`, `Camera`, and `Maps` still
  resolve to icon tap points.
- iPad SpringBoard multi-page app foregrounding is now proved on hardware:
  `/tmp/ipad-springboard-page-scan-1.json` observed a second Home app page with
  `Clock`, `Phone`, `Tips`, `Weather`, and other labels, and
  `/tmp/ipad-springboard-clock-open-1.json` opened `Clock` from that non-current
  page via `open_app_from_springboard` (`ok=true`, `is_home_after_open=false`,
  post-open OCR includes `World Clock`, `Alarms`, `Stopwatch`, and `Timers`).
  The same scan reached App Library and detected categories such as `Utilities`,
  but that is not evidence for a real Home folder; true folder layout/entry
  remains unproved on this connected device.
- A dedicated Home folder scan
  (`/tmp/ipad-springboard-home-folder-scan-1.json`) now makes that limitation
  explicit: the connected iPad exposes two real Home pages, then App Library
  categories, but no visible real Home folder. The bottom-right floating glyph
  that looked folder-like is AssistiveTouch, not a folder:
  `/tmp/ipad-springboard-home-folder-open-2.json` records
  `assistive_touch_menu_not_home_folder` after the tap opened
  `App Switcher`, `Device`, `Gestures`, `Control Centre`, and `Home`. The only
  plausible labeled candidate, `Games`, is also not a folder:
  `/tmp/ipad-springboard-games-folder-check-1.json` tapped it and left Home
  (`after_is_home=false`). The SpringBoard icon filter now excludes visible
  AssistiveTouch menu controls so they are not treated as app/folder icons.

## Why consider it

On iPhone (iOS) we exhausted the precise-scroll / touch problem and hit hard
platform walls (all on-device verified):

- HID **digitizer / touchpad / Magic-Trackpad** input is ignored by iOS — only
  Generic-Desktop **mouse** works. No native touch, no two-finger scroll.
- Mouse **wheel** under AssistiveTouch (which iPhone *requires* for any pointer)
  is severely intermittent (~5–7%) and not revivable from the PicoKVM side
  (USB re-enumeration at 1 s / 12 s / full reboot all fail to reset it).
- So iPhone scrolling is stuck with the imprecise **swipe-drag fling**
  (shared Settings acceptance coverage varies 9–15 of the 17-label
  iPhone/cross-device vocabulary because of overshoot).

iPadOS removes the AssistiveTouch dependency and accepts native pointer clicks,
but the connected PicoKVM rig has **not** proved reliable Settings sidebar wheel
scrolling. The same USB-HID gadget plugs in directly and keyboard Home works;
precise scrolling and app foregrounding still need iPad-specific handling. See
the memory notes
`ios-ignores-usb-hid-digitizer`, `picokvm-scroll-overshoot-hardware-limit`,
`iphone-vs-ipad-mouse-keyboard-support`.

## What does NOT change (architecture is ready)

glassbox is built on pluggable seams (Platform / Effector / FrameSource / OCR /
VLM / CrawlPolicy / Verifier), so most of this is "add an iPad profile", not a
core rewrite.

- Core observe→decide→act→verify loop and all seams.
- The **HID gadget descriptors** (keyboard + absolute mouse + relative mouse +
  report-ID-2 wheel). iPad consumes absolute pointer clicks, but report-ID-2
  wheel ACK is not enough: Settings sidebar semantic movement is currently 0/n
  on hardware.
- PicoKVM hardware/firmware; the kvm_app RPCs (`absMouseReport`, `wheelReport`,
  `keyboardReport`, …).

## Current Implementation Status (highest → lowest impact)

Code locations below were validated against the tree on 2026-05-25; line numbers
are indicative, treat the symbol names as the stable anchors.

### 1. Device profile / coordinate calibration (implemented baseline)
Nothing else could be verified on hardware until tap coordinates landed; this is
now in place for the connected iPad mini.
- `glassbox/perception/device.py` includes the `ipad_mini_7` profile
  (1488×2266 pixels / 744×1133 points), selected through
  `GLASSBOX_PHONE_MODEL=ipad_mini_7`.
- PicoKVM absolute-pointer calibration can be derived from the detected crop for
  iPad, while explicit `GLASSBOX_PICOKVM_ABS_*` overrides still work for
  hardware-specific calibration.
- The iPad 3:2 mirror crop is detected from the 1920×1080 HDMI frame on the
  connected rig (`bbox=(640, 51, 640, 989)` in the latest runs), and absolute
  pointer taps have landed on Settings sidebar rows, right-pane rows, and visible
  Home icons.
- Remaining: keep this as a hardware acceptance gate for any new adapter/profile,
  because all higher-level iPad behavior depends on crop/calibration being true.

### 2. iPad Settings is a split view — the largest app-level rework
iPad "Settings" is a **two-pane split view** (left sidebar list + right detail),
not the iPhone single-column drill-down. The current
`skills/regression/ios_settings` model (enter a root row → record → return to
root) now has an iPad policy layer: root scans stay in the left sidebar, child
scans stay in the right detail pane, top-search fallback is title-checked, and
right-pane back handling targets the split boundary instead of the iPhone
top-left point.
- Strict shared-root acceptance is proved by `/tmp/ipad-settings-search-drill-12.json`
  (`root_required_missing_count=0` after five iPad/profile entry exemptions).
- Bounded child traversal is proved across nine high-value roots by the single
  all-nine `/tmp/ipad-settings-child-audit-22.json` report, including value-line
  disclosure OCR such as `Off >`, exact safe-known child labels without
  chevrons, minimal repeated title detail pages, and dashboard-style Screen Time
  title inference.
- The three remaining actionable shared roots on this profile are proved as
  safe blocked targets by `/tmp/ipad-settings-child-audit-blocked-3-1.json`:
  `WLAN`, `Bluetooth`, and the internal `Face ID与密码` target displayed as
  `Touch ID & Passcode` open but do not traverse dynamic network/device rows or
  passcode/biometric controls.
- Broader top-level Settings inventory beyond the shared-root gate now has
  hardware proof for fourteen extra safe pages:
  `/tmp/ipad-settings-extra-inventory-camera-wallpaper-2.json` covers `Camera`
  and `Wallpaper`, and `/tmp/ipad-settings-extra-inventory-3-1.json` covers
  `Control Centre`, `Display & Brightness`, and `Multitasking & Gestures`;
  `/tmp/ipad-settings-extra-inventory-pencil-home-1.json` covers `Apple Pencil`
  and `Home Screen & App Library`; and
  `/tmp/ipad-settings-extra-inventory-search-open-2-1.json` covers `Safari` and
  `FaceTime` through top-search fallback. `/tmp/ipad-settings-extra-inventory-apps-6.json`
  and `/tmp/ipad-settings-extra-inventory-game-center-2.json` first covered
  `Apps` and `Game Center` as root-only coverage; the later fresh-install
  read-only check
  `/private/tmp/ipad-settings-apps-gamecenter-root-blocked-readonly-2.json`
  turns both into explicit blocked stop points before any app-specific child
  page is tapped. `/tmp/ipad-settings-extra-inventory-weather-2.json`
  covers `Weather` as root-only coverage, and
  `/tmp/ipad-settings-extra-inventory-books-translate-1.json` covers `Books`
  and `Translate` as root-only coverage. `Search` remains observed but not
  accepted after broader attempts failed to open it reliably.
- A later negative app-specific pass tried `Calculator`, `Files`, `Freeform`,
  `Maps`, `Notes`, and `Clock` as possible additional top-level targets. The
  connected iPad did not open those through the current root/search path:
  `/private/tmp/ipad-settings-extra-inventory-calculator-1.json`,
  `/private/tmp/ipad-settings-extra-inventory-files-2.json`,
  `/private/tmp/ipad-settings-extra-inventory-freeform-2.json`,
  `/private/tmp/ipad-settings-extra-inventory-maps-2.json`,
  `/private/tmp/ipad-settings-extra-inventory-notes-2.json`, and
  `/private/tmp/ipad-settings-extra-inventory-clock-2.json` all record
  `target_root_not_opened`, so these labels are not accepted as extra safe
  top-level pages. The first `Freeform` attempt also exposed a probe robustness
  edge: if an unopened target leaves Settings in a dirty search state and return
  recovery fails, the child audit now records `return_root_failed` instead of
  crashing without a report.
- On a fresh iPadOS install, do not over-drill app-specific Settings pages into
  first-run permission/access panels. A bounded follow-up showed
  `/private/tmp/ipad-settings-extra-child-safari-1.json` can reach
  `Settings > Safari > Siri`, while Weather's first child path reaches a
  Location permission selector (`/private/tmp/ipad-weather-location-inspect-1.json`).
  A Camera broad-child attempt
  (`/private/tmp/ipad-settings-camera-broad-child-1.json`) similarly reached the
  fresh-install/privacy `Camera > App Clips` access page, not the Camera app
  recording settings page. Those are not good evidence for broad read-only
  Settings traversal on a not-yet-authorized device. The policy now blocks the
  observed Safari/Weather/Camera permission-access panels and `Allow Location
  Access` selector pages as app permission/access rows; a follow-up read-only
  check (`/private/tmp/ipad-settings-camera-permission-block-readonly-1.json`)
  opens only the Camera detail page, records
  `app permission/access selector rows`, and exposes `safe_candidate_texts=[]`.
  Future broader child samples should prefer settings-native, read-only pages.
- Screen Time has the same fresh-install boundary at `Always Allowed`: the page
  is an allowed-apps selector, not useful read-only Settings structure on a
  not-yet-authorized iPad. The policy now excludes that row from child
  candidates. A broader follow-up
  (`/private/tmp/ipad-settings-screen-time-broad-child-2.json`) reached the
  settings-native `Downtime` and `App Limits` child pages, then failed only when
  continuing into lower Screen Time rows that did not transition on this device;
  do not count that report as a passing broad-child sample.
- A settings-native blocked-target follow-up
  (`/private/tmp/ipad-settings-extra-blocked-native-1.json`) now turns four
  previously root-only pages into explicit read-only stop points:
  `Control Centre` (`control centre customization/reset rows`), `Wallpaper`
  (`wallpaper customization rows`), `Home Screen & App Library`
  (`home screen layout selector rows`), and `Multitasking & Gestures`
  (`multitasking layout selector rows`). The report passes with all four target
  roots opened, all four covered by `target_roots_blocked`, no target failures,
  no limits, no known issues, `return_root_failed=false`, and
  `navigation_success_proxy_rate=1.0`.
- A fresh-install app-list/onboarding read-only check
  (`/private/tmp/ipad-settings-apps-gamecenter-root-blocked-readonly-2.json`)
  now opens only the `Apps` and `Game Center` root detail pages and stops there.
  `Apps` is blocked as `dynamic app list rows`; `Game Center` is blocked as
  `game center onboarding requires action`; both expose `safe_candidate_texts=[]`.
  This also fixes the iPad split-view guard: pages with a live left sidebar can
  still be classified as blocked right-detail pages instead of being skipped as
  generic root surfaces.
- Remaining: keep broadening Settings sampling beyond the current twelve
  actionable shared roots plus these first fourteen extra top-level pages and six
  explicit blocked stop points, and keep stale-detail/return semantics under
  real multi-level pages without turning the policy into a page-specific rule
  list. The General, Accessibility, Siri, Notifications, Display & Brightness,
  and Sounds & Haptics broad-child passes reduce this risk but do not make the
  whole iPad Settings child inventory exhaustive.

### 3. Scene classifier / safe-area / springboard: pervasive single-column geometry
Under-stated previously — the iPhone single-column assumption was not confined to
Settings. The baseline now has iPad safe-area/platform hooks and an iPadOS scene
classifier for split-view Settings, SpringBoard/Home, top-search states, and
common false positives observed on the connected rig.
- Visible iPad Home icon foregrounding is proved for `Settings` and `Files`; a
  second-page OCR-label sweep is proved for `Clock`. OCR widget text such as
  `- Notes` is filtered out as non-icon text.
- Files' two-column UI no longer masquerades as Settings top-search.
- Current connected-device folder audit found no real Home folder to open:
  App Library category pages and the AssistiveTouch floating menu are explicitly
  rejected as folder evidence. Treat visible/multi-page OCR-label Home icons as
  accepted, but do not claim Home-folder foregrounding until a real folder exists
  on the device and an open-folder report passes.

### 4. Native pointer + keyboard instead of AssistiveTouch (implemented baseline)
iPad has a native pointer and does not need AssistiveTouch. The iPad profile uses
the direct PicoKVM mouse/keyboard path; keyboard Home is hardware-proved and the
Settings back fallback is detail-pane aware.
- Remaining: app switcher/control-center iPad ergonomics are lower priority than
  Settings and Home foregrounding, and should stay behind platform-specific
  capability checks.

### 5. Replace the wheel assumption for Settings sidebar coverage
The iPad profile exposes wheel transport, but the connected rig proved that
ACKed `wheelReport` does not move the Settings sidebar. Do not build acceptance
on wheel movement until a new HID path is proven. Current viable direction:
use visible sidebar rows + top-search recovery for missing root sections, and
keep wheel attempts bounded/diagnostic rather than authoritative. A future
firmware/native relative-wheel path or real trackpad gesture may still replace
this. If a later iPadOS hardware run proves semantic wheel movement, update this
section with the report path, probe point, tick count, and before/after sidebar
evidence before promoting wheel from diagnostic to accepted coverage machinery.

### 6. Platform seam: an iPadOS variant (implemented baseline)
`glassbox/platforms.py` can select the `ipados` backend, which swaps in iPad
safe-area/scene behavior while preserving the shared observe→decide→act→verify
core. Settings-specific policy is selected from platform/model context.
- Remaining: continue moving iPad-specific layout decisions behind this seam as
  more apps are proved, instead of letting iPhone constants leak back into shared
  code.

### 7. Wiring verification (proved on current rig)
The connected iPad mini rig delivers HDMI frames to PicoKVM and accepts USB-HID
keyboard/mouse input. This is now part of the hardware smoke evidence; re-check
only when adapter/cabling/profile changes.

## Summary

Core stayed; the iPad profile and iPadOS platform baseline now exist and are
hardware-proved for Settings root coverage, nine-root split-view child
traversal, broader General, Accessibility, Siri, Notifications, Display &
Brightness, and Sounds & Haptics child samples, three additional safe-blocked
Settings roots, fourteen extra safe top-level Settings pages beyond the
shared-root gate, six extra pages that now stop as explicit read-only blocked
targets, keyboard Home, native pointer taps, and visible/multi-page Home-icon
foregrounding.

The remaining work is narrower but still real: do not promote wheel scrolling
until semantic movement is observed, do not claim arbitrary iPad SpringBoard
foregrounding until a real Home folder exists and layout/entry is proved, and do
not call iPad Settings child inventory exhaustive until broader multi-level
samples pass on hardware.
