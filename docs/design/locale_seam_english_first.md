# Locale Seam — English-first, Chinese-switchable

Status: **Phase 1 + Phase 2a-foundation implemented** (smoke green); later
phases sequenced below. Defines how glassbox treats device **language + region**
as a first-class seam. **English is the target default**, with Chinese (and
China-region variants) as switchable packs — the global default is **flipped
last**, only after parity (see Migration).

### Implementation status (2026-05-25) — P1 + P2 done; P3 functional; P4 live-validated on the rig (global flip still gated)
- **P2a compatibility bridge (NOT the full DI model yet):** the live resolver
  (`canonical_expected_root_label`, used by coverage/dedup) maps English UI text
  to the canonical section; the greater-China English `WLAN` / `Mobile Service`
  that broke the live English run resolve **only under the `en-CN` / `en-HK`
  packs** (`ROOT_LABEL_LOCALE_ALIASES` overlay keyed by pack key, NOT folded into
  the global map; a zh, en-US, *or zh-Hans-CN* run rejects them). Live-verified
  on the test device (Hong Kong region, English): its root shows `WLAN` and
  `Mobile Service` (same as mainland CN, NOT `Wi-Fi`/`Cellular`). The typed
  `SectionVocab` (`sections.py`) wraps the same data.
  **Caveat:** this reads the active locale from the **global config**
  (`resolve_locale(get_config())`) inside the resolver — a *compatibility
  bridge*, not the designed `SettingsPolicy(sections=locale.app("settings").
  sections)` injection. So `DEFAULT_SETTINGS_POLICY` is not a true per-instance
  locale-bound object: two locales can't run concurrently in one process, and
  `SectionVocab` is not yet threaded into the live crawl path. Full DI is the
  remaining 2a call-site rewire.
  Tests: `skills/smoke/test_settings_english_resolution.py`.
- **P2b (report — additive ids, still v0.1):** `root_coverage` now carries
  `expected_ids`/`visited_ids`/`missing_ids` (stable `RootSection` tokens) beside
  the zh labels, and the report gains a resolved `locale` pack-key tag. These are
  **forward-compatible additions on the v0.1 structure** — the report is tagged
  `schema_version: "0.1"`, NOT "0.2" (the breaking v0.2 contract below —
  `path_ids`/`path_labels`/`raw_texts` primary + verifier dual-read — is not
  emitted yet). zh label fields stay primary; existing reports/verifier
  unchanged. Tests: `skills/smoke/test_report_locale_ids.py`.
- **P3 (classifier):** English scene classification already works — the markers
  are bilingual and the global CJK confusion folds are no-ops on Latin text, and
  the real English blocker (clock-as-Back) shipped in `4594e74`. The remaining
  P3 item (sourcing root markers from `locale.app().surfaces`/`sections` for
  single-source cleanliness) is deferred as architectural, not functional.
- **P4 (English end-to-end + flip):** the English resolution path works
  end-to-end (proven by the resolution tests above); the production default stays
  `zh-Hans`. **Live English drill-down now validated (2026-05-25)** on the
  Hong-Kong-region English rig: a single `en-HK` drill-down credited 15/17 root
  sections (the two non-credited are by design — `CELLULAR` no-SIM device-inert,
  `WALLET` blocked), with `WLAN`/`Mobile Service` resolving via the overlay,
  en-US-only OCR (CJK garbling gone), and **zero** wasted multi-pass / search /
  mis-tap tail (vs the zh-locale run on the same English device: 14/17, 2
  multi-pass resets, 2 nav failures, 49→35 HID calls). `verify_report` passes on
  coverage (the only remaining errors — `Camera`/`Wallpaper` — are the
  pre-existing, locale-independent candidate-policy gap, identical under zh). The
  English locale is selected **per live run** via `run_full --language en --region
  HK` (sets `GLASSBOX_LANGUAGE`/`GLASSBOX_REGION` for that process only) — NOT
  pinned in `.env`, because a `.env` `GLASSBOX_LANGUAGE` flips the *global*
  `get_config` default for every caller including the smoke suite (which asserts
  the zh-Hans default in `test_greater_china_english_is_pack_bound`). The in-code
  **global default stays `zh-Hans`**. Remaining P4 items: a multi-round English
  run + the global default flip, still gated on both-locale CI green.

### Earlier status (Phase 1 / 2a-foundation)
- **Done — Phase 1 (seam scaffold, wired):** `glassbox/locale.py` (`Locale`
  packs `zh-Hans` / `zh-Hans-CN` / `en-US` / `en-CN` + `LocaleRegistry` +
  `resolve_locale`); `AgentConfig.language`/`region` (default `zh-Hans`); OCR
  factories thread `locale.ocr_languages` (zh resolves to the exact prior
  `("zh-Hans","en-US")`); parameterized `Normalizer(classes=…)` in `text_match`
  with the global `confusion_compact` kept as the zh shim. Tests:
  `skills/smoke/test_locale.py`.
- **Done — Phase 2a foundation (typed identity + vocab, additive):**
  `skills/regression/ios_settings/sections.py` — the `RootSection` identity
  schema (owned by the Settings domain), `SectionVocab` (typed `resolve()`,
  id_token == `id.value`, region overlays for `WLAN`/`Mobile Service`), zh vocab
  reusing the existing resolver for OCR-garble coverage. Contract tests:
  `skills/smoke/test_section_vocab.py` (label/search completeness, no alias
  collision, VLM round-trip, same section set across packs).
- **Remaining (sequenced):** Phase 2a call-site rewire (~50 sites off zh
  strings onto `RootSection` + the injected `SectionVocab`; the heavy/churny
  part) → Phase 2b report v0.2 (`path_ids` + dual-read) → Phase 3
  locale-aware classifier → Phase 4 English live validation + default flip.
  These need either large test churn, a breaking schema migration, or the live
  rig, so they are not in this increment.

## Why

English is a net positive on this rig (empirically, 2026-05-24):

- Apple Vision OCR reads Latin UI **markedly cleaner** — live English reads
  came back clean (`Settings, Bluetooth, Mobile Service, Personal Hotspot,
  Battery, General, Accessibility, Apple Account, iCloud and more`), vs the
  pervasive CJK garbling seen all session (`书 / 包 / S0S / 面容ID与密码 /
  往机貝示 / 声效与触感反馈`). The lookalike/segmentation errors that justify the
  whole confusion-fold + multi-frame-vote + alias machinery largely vanish.
- Lower **compute/latency** (fewer voting passes, fewer landing retries, fewer
  VLM rescues). OCR is local/free either way; the VLM (the only paid layer) is
  off by default and trends to ~0 calls in English.

But switching the device to English today makes the crawl run *worse*, because
language is hardcoded with **Chinese as the implicit canonical identity**. A
trial English run exposed this: a core classifier bug (since fixed —
`4594e74`, status-bar clock typed `nav_back`), unmapped China-region English
labels (`WLAN`, `Mobile Service`), and Chinese-only coverage/VLM. So
"English-first" is a small **architecture** project, not a config flip.

## Principle: separate IDENTITY from DISPLAY

A Settings section has a **language-neutral identity** (`RootSection.WIFI`).
Language/region only changes its **display vocabulary**. Orchestration
(coverage, safety, crawl policy, verifier, VLM) keys on the identity and never
on localized text. Language/region become selectable **packs**, not branching
logic.

## Language vs Region are TWO dimensions (review fix P1-b)

Do not conflate them. China-region English (`WLAN`, `Mobile Service`) is
**English language + CN region**, and must NOT live in a Chinese pack. Model a
locale as `language` + optional `region`, with a clear composite pack key:

| pack key | language | region | carries |
|---|---|---|---|
| `en-US` | en | US | base English vocab (Wi-Fi, Cellular, …) |
| `en-CN` | en | CN | overlay on `en-US`: `WLAN`→WIFI, `Mobile Service`→CELLULAR |
| `zh-Hans` | zh-Hans | — | base Chinese vocab (无线局域网, 蜂窝网络, …) |
| `zh-Hans-CN` | zh-Hans | CN | overlay on `zh-Hans`: CN-only Chinese label variants |

A pack = base-language vocab + optional region **overlay** (region aliases
resolved first, then base). English display words only ever live in `en-*`
packs.

## The `Locale` seam

Parallel to the existing `Platform` seam (`glassbox/platforms.py`), registered
like the others (`BackendRegistry` / `PlatformRegistry`) and selected by config.

- `glassbox/locale.py`: `Locale` protocol + `LocaleRegistry` +
  `select_locale_backend(cfg)`.
- `glassbox/config.py`: add `language: str` + `region: str | None` (env
  `GLASSBOX_LANGUAGE` / `GLASSBOX_REGION`); the seam composes the pack key.
  **Default stays `zh-Hans` during migration; flipped to `en-US` in the final
  phase** (review fix P1-a).
- `glassbox/runtime.py:build_phone()`: resolve the `Locale` once and thread it
  to the three consumers below (where `IOSPlatform` is assembled,
  `runtime.py:528`).

```python
class Locale(Protocol):
    language: str                          # "en", "zh-Hans"
    region: str | None                     # "US", "CN", or None
    code: str                              # composite pack key, e.g. "en-CN"
    ocr_languages: tuple[str, ...]         # Vision recognitionLanguages
    confusion_classes: tuple[str, ...]     # OCR visual-confusion folds (en: ())
    # chrome = APP-AGNOSTIC system-UI words ONLY: back glyphs, edit/done,
    # system-search (Spotlight), app-library, blocked-safety (passcode prompt).
    # NOT a title bar, NOT app launch names, NOT any built-in app's content.
    chrome: ChromeVocabulary
    # Per built-in app: surfaces (for the classifier) + sections (identity).
    def app(self, app: str) -> AppLocale: ...

class AppLocale(Protocol):                  # e.g. app("settings")
    surfaces: SurfaceVocabulary            # NON-section page markers (classifier)
    sections: LabelVocabulary              # section IDENTITY (below)

# Typed surface key — like RootSection, avoid ad-hoc "about"/"storage" strings
class SettingsSurface(str, Enum):
    ABOUT = "ABOUT"; SOFTWARE_UPDATE = "SOFTWARE_UPDATE"; STORAGE = "STORAGE"
    SCREEN_TIME = "SCREEN_TIME"; HEALTH_DATA = "HEALTH_DATA"

class SurfaceVocabulary(Protocol):         # consumed by the scene classifier
    # The on-screen TITLE-BAR text of the already-open app, used only to confirm
    # "we are on Settings root" during scene classification. NOT an app display
    # name and NOT a SpringBoard/app-launch alias (those live in the app catalog).
    page_title_markers: tuple[str, ...]    # ("Settings",) / ("设置",)
    search_labels: tuple[str, ...]         # in-app search affordance
    detail_markers: dict[SettingsSurface, tuple[str, ...]]  # typed keys
    # NOTE: NO root_markers here. The root-section terms are DERIVED from
    # `sections` (see `root_classifier_terms` below) so the two can never drift.

# Typed identity: identity is RootSection, never a display str (review fix P2-a)
class LabelVocabulary(Protocol):           # conceptually LabelVocabulary[RootSection]
    def label(self, section: RootSection) -> str          # ID -> localized text
    def resolve(self, ocr_text: str) -> RootSection | None  # text -> ID; NEVER text
    def search_query(self, section: RootSection) -> str | None
    # Narrow, single-purpose: labels+aliases for the given sections, used ONLY by
    # the root scene classifier to count "≥2 root markers". NOT a general fuzzy
    # pool and NOT a substitute for resolve()/canonical identity.
    def root_classifier_terms(self, sections: Iterable[RootSection]) -> tuple[str, ...]
    def vlm_prompt(self) -> str
    def vlm_candidates(self) -> tuple[VlmCandidate, ...]   # see VLM wire contract

@dataclass(frozen=True)
class VlmCandidate:                        # what the VLM actually sees
    id: RootSection                        # stable identity (returned to us)
    id_token: str                          # == id.value; the ASCII token the VLM emits
    label: str                             # localized display shown in the prompt
    aliases: tuple[str, ...]               # accepted spellings/region variants
```

Contract: **`id_token == id.value`** (the `RootSection` enum value, e.g.
`"WIFI"`) — a single stable ASCII token per section, identical across packs, so
the VLM never emits a localized string as identity.

`resolve()` returns a typed `RootSection` (or `None`) — returning a localized
string is a contract violation, so callers cannot keep passing display text as
identity. Packs ship as **data**, not code.

### VLM wire contract (review fix)

The VLM sees and emits **text**, never a Python enum, so identity must be
recovered deterministically:

- The prompt lists candidates as `{id_token, label, aliases}` and **instructs
  the model to output the `id_token`** (a stable ASCII token, e.g. `WIFI`).
- The response is mapped back: exact `id_token` → `RootSection`; if the model
  instead echoes a `label`/alias, run it through `vocab.resolve()`. Anything
  unresolvable → `None` (treated as "no pick"), never adopted as identity.

This forbids the failure mode of "VLM free-text becomes the canonical label."

## Neutral section identity — owned by the Settings domain

The identity **schema** lives in the Settings policy/domain
(`skills/regression/ios_settings/`), **not** in any locale pack: define the
root sections **once**, language-neutrally, with their safety semantics (today
tangled into Chinese-string tuples). Locale packs only map text↔these ids.

```python
class RootSection(str, Enum):
    # Explicit values REQUIRED: id_token / report id / VLM token all use
    # `.value`, so it must equal the name (no `auto()`, no implicit value).
    WIFI = "WIFI"
    BLUETOOTH = "BLUETOOTH"
    CELLULAR = "CELLULAR"
    # … NOTIFICATIONS, SOUNDS_HAPTICS, FOCUS, SCREEN_TIME, GENERAL,
    # ACCESSIBILITY, ACTION_BUTTON, STANDBY, FACE_ID_PASSCODE, SIRI,
    # EMERGENCY_SOS, PRIVACY_SECURITY, BATTERY each `NAME = "NAME"` …
    WALLET = "WALLET"

EXPECTED_ROOT_SECTIONS = (...)
COVERAGE_ONLY = {RootSection.WALLET}              # was ROOT_COVERAGE_ONLY_LABELS
ROOT_ONLY_UNSAFE_OVERRIDE = {RootSection.FACE_ID_PASSCODE}  # safe@root, unsafe@detail
# unsafe / safe-known become ID sets, not text tuples
```

Everywhere identity crosses a wire — `id_token`, report `path_ids`/coverage,
VLM token — it is `section.value` (the explicit string), never the localized
label and never an `auto()` integer.

Coverage = `EXPECTED_ROOT_SECTIONS` minus the device-unavailable set
(`CELLULAR` on a no-SIM iPhone — already an opt-in verifier concept,
`verify_report.py --device-unavailable-root`, now keyed by ID).

## Boundary with existing localization/alias sources (review fix P2-b)

The repo already has two localization/alias sources; the new seam must not
become a third overlapping one. Single-responsibility split:

- **`Locale` seam (NEW)** — provides the active **language/region context**,
  the **system-UI chrome** vocabulary, and the **display/resolve vocabulary**
  for apps glassbox has a built-in policy for (today: Settings) — i.e. the
  text↔id mapping (labels, aliases, search queries, VLM candidates) + OCR
  language/confusion. It does **not own the identity schema itself** (the
  `RootSection` enum / `EXPECTED_ROOT_SECTIONS` / safety ID-sets live in the
  Settings **domain**, below). Locale is the *vocabulary* source, not the
  *identity* source. It is **not** an all-app localization dispatcher.
- **`Profile.localization`** (`glassbox/profile.py:180`, `lang_code ->
  {string_key: text}`) — a **profiled app's own string catalog** (third-party
  apps' `known_elements` etc.). The keys/semantic ids belong to **Profile**.
  Locale only exposes the active `language` as **read-only context**; Profile's
  own consumers index `localization` by that language. **Locale never selects
  Profile sub-maps and never resolves app-private identity.** (No overlap:
  Settings is a built-in policy app, not a third-party profiled one.)
- **`glassbox/ai.py` `_APP_ALIASES`** (`ai.py:27`) — **app-launch** aliases for
  finding/opening an app icon (`open_app`). Launch-name compatibility only;
  **not** a section-identity source. App **launch/display names are NOT OS
  chrome** — they belong to a platform **app catalog / app-alias registry**
  (where `_APP_ALIASES` lives), localized there via the language context. They
  must not be put into `Locale.chrome` (which is strictly system-UI words).

Rule of thumb: *built-in app section identity* → `locale.app(x).sections`;
*root-section markers* → **derived** from `sections.root_classifier_terms(...)`,
never stored separately; *non-section surface markers* (page-title / search /
detail) → `locale.app(x).surfaces`; *a profiled app's private strings* →
Profile.localization (Locale supplies language only); *launch-by-name* → app
catalog / `_APP_ALIASES` (compat only); *app-agnostic system-UI words*
(back/edit-done/Spotlight/app-library/blocked-safety) → `Locale.chrome`.

## Consumers and what changes

### 1. Perception — OCR + text-match (`glassbox/cognition/`)
- `ocr_vision.py:59` / `ocr.py:57`: `languages` ← `locale.ocr_languages`
  (en: `("en-US",)` — dropping `zh-Hans` speeds up + de-noises English OCR).
  Per-instance, so Phase 1 can do this directly.
- `text_match.py:52` — **final target**: normalization is locale-bound via
  `Normalizer(classes=locale.confusion_classes)` (en: `()`; the CJK folds live
  in the zh pack). **Phasing**: Phase 1 only *adds* the parameterized
  `Normalizer` API; the module-level `_CONFUSION_CLASSES` / `confusion_compact()`
  stay as the **zh compatibility default** (do NOT swap the global in Phase 1).
  Call sites migrate to the locale-bound `Normalizer` in **Phase 2a**.
  `MINUS_ALIASES` stays neutral throughout.

### 2. Platform scene classifier (`glassbox/ios/scene.py`)
Split the markers by ownership (review fix):
- **`locale.chrome`** (app-agnostic): back-glyph / edit-done sets,
  `SYSTEM_SEARCH_MARKERS`, `APP_LIBRARY_*`, `BLOCKED_SAFETY_MARKERS`.
- **`locale.app("settings").surfaces`** (non-section page markers):
  `SETTINGS_TITLE_LABELS` → `page_title_markers`, `SETTINGS_SEARCH_LABELS`,
  the `*_detail` body markers (about/software-update/storage/screen-time/health).
- **`SETTINGS_ROOT_MARKERS` is NOT a surface field.** `_is_settings_root`'s
  "≥2 root markers" check derives its terms from
  `locale.app("settings").sections.root_classifier_terms(EXPECTED_ROOT_SECTIONS)`
  — the single source of root-section vocabulary (no second copy in surfaces).

The classifier takes the `Locale`; for Settings surfaces it consults
`locale.app("settings").surfaces` + `.sections` (for root terms), for generic
surfaces `locale.chrome`.
`_TIME_RE` + geometry stay neutral. `HARNESS_CONSOLE_MARKERS` stays (glassbox's
own console, not device-language). (Longer term, built-in app surface knowledge
could move out of the generic classifier into the app layer; for now it stays
in the classifier but reads from the locale.)

### 3. Settings app-policy (`skills/regression/ios_settings/`) — from module
globals to a locale-bound instance (review fix)

The bulk. Today identity is the module global `EXPECTED_ROOT_NAV_TEXT_ZH` and
`DEFAULT_SETTINGS_POLICY.canonical_expected_root_label()` returns Chinese
(`policy.py:89,648`), read directly by ~50 call sites — so a runtime `Locale`
alone wouldn't reach them.

Migration target: **`SettingsPolicy` becomes an instance constructed with a
locale-bound `LabelVocabulary`** — the policy only needs section identity, so
pass `sections`, not the whole `AppLocale`:
`SettingsPolicy(sections=locale.app("settings").sections)` (field type
`LabelVocabulary`). It is **threaded explicitly** through the seams that already
exist for DI: `SettingsNavigationActions` (already a dataclass of injected
callables — the natural carrier), the report writer, and the verifier. The
module-level `DEFAULT_SETTINGS_POLICY` / `EXPECTED_ROOT_NAV_TEXT_ZH` remain only
as a **`zh-Hans` compatibility shim**, then are retired once all call sites take
the injected policy. (If the policy later needs surface markers too, pass the
whole `AppLocale` as a distinct `app_locale` field — never overload one `vocab`.)

**Separation of concerns — `SettingsPolicy` owns identity ONLY, not artifact
locale metadata** (review fix). The policy gets `sections` (ID↔label/resolve)
and nothing more; it cannot and must not supply `locale.code` / display_label /
raw OCR for the report (that would bloat it into half a `Locale` and break the
boundary). The **report writer / verifier take the report locale context
separately**:

```python
policy = SettingsPolicy(sections=locale.app("settings").sections)   # identity
report_writer = ReportWriter(
    policy=policy,                       # ids + safety
    report_locale=ReportLocaleContext(   # narrow, artifact-only
        pack_key=locale.code,            # "en-CN" → report schema_version tag
        sections=locale.app("settings").sections,  # id -> display_label
    ),
)
```

`ReportLocaleContext` is a thin record (pack key + the section vocab for
display) — *not* the whole `Locale`. The verifier likewise receives the
pack key + (for dual-read) the vocab needed to resolve old labels.

- `policy.py`: Chinese tuples + `ROOT_LABEL_ALIASES` → neutral `RootSection`
  set + safety ID-sets; `canonical_expected_root_label(text)` →
  `self.sections.resolve(text) -> RootSection`.
- `reporting.py:104-112` + `EXPECTED_MIN_VISITS`: coverage over `RootSection`;
  `pack_key` + `display_label` come from the `ReportLocaleContext`, not policy.
- `verify_report.py`: expected / exemptions / device-unavailable keyed by ID;
  pack key + dual-read vocab passed in, not derived from policy.
- `vlm_rows.py:47,73-78`: candidates + prompt from `self.sections`.

## Observability + report wire format (open question → decision)

Record the active **language+region pack key** in the run report
(`reporting.py`) and the success-rate benchmark config, so a 15/17-zh vs
14/17-en diff is never misread as a regression.

Pin the wire format so en/zh reports are **directly comparable**: the artifact
**primary fields** for `expected` / `visited` / `missing` (and visit
`path` segments at root) are written as **stable section ids** (`"WIFI"`,
`"CELLULAR"`, …), never localized labels. A parallel **`display_label`** (and
the raw OCR text) is stored alongside for humans, but tooling/diffs key on the
id. So a zh run and an en run produce byte-comparable coverage sets.

### Schema migration (review fix — this is a breaking change)

Stable ids break `verify_report.py`, historical reports, success-rate
aggregation, and tests that assume Chinese path/label. Do it versioned, not
in-place:

- **Bump `schema_version`** on the report (e.g. `"0.1"` → `"0.2"`); the report
  declares whether root paths/coverage are `label`-format or `id`-format.
- **Concrete v0.2 `PageVisit`** — don't just "replace path segments". Today
  `path` is a single tuple `("Settings","General","About")`. v0.2 splits it
  into parallel arrays so each segment's identity status is explicit:
  ```
  path_ids:    ["SETTINGS", "GENERAL", null]   # app-root token, RootSection, …
  path_labels: ["Settings", "General", "About"]# localized display per segment
  raw_texts:   ["Settings", "General", "About"]# raw OCR per segment
  ```
  Rules: segment 0 = a fixed **app-root token** (`"SETTINGS"`); segment 1 = the
  **`RootSection` id** (the only segment whose identity is enforced); segment
  2+ (child/detail pages) have **`path_ids = null`** — child-page identity is
  explicitly **out of scope** now (only the 17 root sections have neutral ids).
  **Coverage keys on `path_ids[1]`.** Whether to identity-ize child pages later
  is future work, not blocking.
- **Writer (v0.2)**: `expected`/`visited`/`missing` are `RootSection` ids;
  visits use the structure above. `display_label` + `raw_text` retained for
  humans.
- **Reader dual-read window**: `verify_report.py` + aggregation accept **both**
  — v0.1 (label) and v0.2 (id), preferring id when the version says so.
  **v0.2 reports MUST carry the pack key**; v0.1 reports have no locale tag, so
  resolving their labels is **best-effort, defaulting to `zh-Hans`** (almost all
  history is zh) with a CLI **`--report-locale` override** for the rare old
  English label-format report. Never silently mis-validate an old en report as zh.
- **One-shot converter** (optional) to upgrade archived v0.1 reports to v0.2.
- **Sequencing**: the report change lands in **Phase 2b** (after runtime
  identity in 2a), behind the version bump; the dual-read window stays until
  both locales are validated, then v0.1 support can be dropped.

## Locale-pack contract tests (open question → decision)

Each pack must pass, in CI:
- **Total coverage**: every `EXPECTED_ROOT_SECTION` has a `label` and a
  `search_query`.
- **No alias collision** *within an app vocab*: no OCR text resolves to two
  different `RootSection`s.
- **Typed resolve**: `resolve()` returns `RootSection | None`, never a string.
- **VLM round-trip**: every `vlm_candidates()` entry has a unique stable
  `id_token`; feeding any candidate's `label` or each of its `aliases` back
  through `resolve()` returns that candidate's `id`.
- **Stable-id discipline**: section ids are pack-independent (the `en-*` and
  `zh-*` packs expose the *same* `RootSection` set) so reports are comparable.
- **Verifier compat**: a representative en and zh report both validate.

## What does NOT change

Core observe→decide→act→verify loop; the fixes shipped this session
(candidate re-grounding, multi-pass reset, search `unknown`-tolerance, the
clock/Back classifier fix); PicoKVM effector + RPCs; coordinate calibration;
the scroll/AssistiveTouch reality. Identity-vs-display is the only new concept.

## Phased migration (keep Chinese green throughout) — revised per review

The **default locale flip is the last step**, not Phase 1.

1. **Seam scaffold** — add `Locale` protocol/registry + `language`/`region`
   config, resolve in `build_phone`. Ship `en-US` / `en-CN` / `zh-Hans` /
   `zh-Hans-CN` packs with today's values. **Default + Settings harness/CI
   pinned to `zh-Hans`**, with the zh pack's initial values defined to **equal
   today's globals exactly** — `ocr_languages == ("zh-Hans", "en-US")`,
   `confusion_classes ==` the current `_CONFUSION_CLASSES`, normalizer default
   unchanged. Goal is **behaviorally / metrics unchanged for zh** (code paths
   move and the report may gain a `language`/`region` tag, so don't claim a
   literal identical artifact), gated by the Chinese 5-round drill-down staying
   15/17.
   - **OCR language**: thread `locale.ocr_languages` into the OCR backend (easy,
     per-instance). For zh the list is unchanged.
   - **Confusion folding is NOT swapped globally yet.** `_CONFUSION_CLASSES` /
     `confusion_compact()` are module-level globals used directly by many match
     sites; making them locale-dependent by mutating the global would let
     different callers in one process share the wrong normalizer. Instead Phase
     1 adds a **parameterized normalizer API** (`confusion_compact(text, *,
     classes=...)` / a `Normalizer` the locale builds) while the existing global
     stays as the zh default. Call sites migrate to the locale-bound normalizer
     in Phase 2a (with the Settings policy), not now.
   Split to keep the blast radius small — separate **runtime identity** from
   **artifact wire format** so a report-migration bug can't masquerade as an
   identity regression:

   **2a. Runtime identity only.** Introduce `RootSection`; port the *in-memory*
   policy — `canonical_*`, coverage/safety/VLM decisions, the locale-bound
   normalizer call sites — to IDs, fed by the locale vocab packs (incl. region
   overlays). **The report still writes the old (v0.1, zh-label) primary
   format** (dual-write the ids internally if convenient, but the on-disk
   primary stays v0.1). **Gate: Chinese 5-round drill-down stays 15/17** — this
   isolates "does identity still resolve correctly?" from any schema change.
   Hidden-cycle caveat: the Platform classifier still uses old zh/mixed markers
   until Phase 3, so **English is unit-testable only; an English *live* crawl is
   NOT a pass condition here.**

   **2b. Artifact wire format.** Flip the report **primary** fields to v0.2
   (`path_ids`/coverage as stable ids + `display_label`/`raw_text`), bump
   `schema_version`, and land the verifier/aggregation dual-read. **Gate: the
   same zh run validates under v0.2, and re-validates an archived v0.1 report.**
3. **Locale-aware Platform classifier** — wire the classifier to `locale.chrome`
   (generic surfaces), `locale.app("settings").surfaces` (page-title / search /
   detail markers) and `…sections.root_classifier_terms(...)` (root markers,
   derived); English-primary ordering. (Do NOT move Settings markers into
   `chrome`, and do NOT add a separate `root_markers` copy.) Re-validate zh.
4. **English validation + flip** — root-cause the English early-termination,
   run a clean **English** 5-round drill-down + `verify_report` (with
   `CELLULAR` device-unavailable on this no-SIM rig). Only when both locales
   are green in CI, **flip the global default to `en-US`**.

## Risks / open questions

- **Region ≠ language** — modeled above as overlay packs (`en-CN` vs
  `zh-Hans-CN`); the WLAN/Mobile Service overlay belongs to `en-CN`.
- **Identity churn** — ~50 call sites move off Chinese strings; do it behind
  `canonical_*` returning `RootSection` so call sites change *type*, not logic.
- **Cross-locale resolve fallback is app-scoped** — keep a union-of-aliases
  fallback (so a stray Chinese string still resolves under English), but
  **scoped to the same app vocab only**, never a global union (different apps
  can reuse a word).
- **Default-flip timing** — the global default flip waits for both-locale CI
  green (Phase 4), avoiding any window where a zh device runs en OCR while the
  policy is still zh-canonical.

## Summary

Make **locale a seam** with explicit **language + region**. Identify Settings
sections by **typed neutral IDs**; ship English & Chinese (+ region overlays)
as data vocab packs consumed by perception, the Platform classifier, and the
Settings policy. Orchestration keys on identity, never on language. The
**identity schema is owned by the Settings domain**; **Locale is the sole
*vocabulary* (display/resolve) source** for it (Profile.localization =
app-private strings; `_APP_ALIASES` = launch compat). Migrate in 4 phases with
the Chinese 15/17 drill-down as the regression gate; **flip the default to
English last**, after English reaches parity in CI.
