# Goal — Finish the locale seam (big-churn phases + default flip)

Status: **seam implemented + en-HK live-validated; remaining work is the
heavy/breaking phases below.** The English-first / Chinese-switchable seam is
real and proven on the live rig — what is left is the large mechanical rewire,
a breaking report-schema migration, the classifier rewire, and the gated global
default flip. Full design + rationale: `docs/design/locale_seam_english_first.md`
(this goal is the actionable handoff slice of that doc's "Remaining" section).

## What already works (do not redo)

- `glassbox/locale.py` — `Locale` packs (`zh-Hans` / `zh-Hans-CN` / `en-US` /
  `en-CN` / `en-HK`) + registry + `resolve_locale`; `AgentConfig.language` /
  `region` (env `GLASSBOX_LANGUAGE` / `GLASSBOX_REGION`, default `zh-Hans`).
- `skills/regression/ios_settings/sections.py` — neutral `RootSection` identity
  + `SectionVocab` (typed `resolve`, en-CN/HK `WLAN`/`Mobile Service` overlay).
- `policy.py` compatibility bridge — `_active_root_aliases` reads the active
  locale and applies the greater-China overlay; OCR is locale-threaded via
  `backend_registry._ocr_languages`.
- Per-run locale selection — `run_full --language en --region HK` (sets the env
  for that process only; the global default stays `zh-Hans`).
- **Live-validated (2026-05-25):** en-HK drill-down = honest 15/17, `verify_report`
  exit 0, OCR garbling gone, ~30% fewer HID calls vs the zh-on-English mismatch.

## Why finish it

The bridge reads the **global config** inside the resolver, so it cannot run two
locales concurrently in one process and `SectionVocab` is not yet on the live
crawl path. Identity is still pivoted on Chinese strings
(`EXPECTED_ROOT_NAV_TEXT_ZH` + `canonical_expected_root_label`), so reports are
zh-label-keyed and not byte-comparable across locales. The default cannot flip
to English until both locales are green in CI on the real wire format.

## Phasing (keep the Chinese 15/17 drill-down green as the gate throughout)

### P2a — Runtime identity DI (heavy/churny)
- Replace the module-global zh-string pivot with an injected
  `SettingsPolicy(sections=locale.app("settings").sections)`; thread it through
  the existing DI seams (`SettingsNavigationActions`, report writer, verifier).
- Port `canonical_*`, coverage/safety/VLM decisions, and the locale-bound
  normalizer call sites to `RootSection` ids (~50–159 sites — change *type*, not
  logic, by having `canonical_*` return `RootSection`).
- Keep `DEFAULT_SETTINGS_POLICY` / `EXPECTED_ROOT_NAV_TEXT_ZH` only as a
  `zh-Hans` shim until all call sites take the injected policy.
- **Report still writes v0.1 (zh-label) primary** — isolates identity from schema.
- **Gate:** Chinese 5-round drill-down stays 15/17. English is unit-testable
  only here (classifier still zh/mixed until P3), not a live pass condition.

### P2b — Report wire format v0.2 (breaking schema migration)
- Flip report **primary** fields to stable ids: `path_ids` / `path_labels` /
  `raw_texts` per visit (segment 0 = `"SETTINGS"`, segment 1 = `RootSection` id,
  segment 2+ = `null`); coverage keys on `path_ids[1]`. Keep `display_label` /
  `raw_text` for humans. Bump `schema_version` `0.1` → `0.2`; **v0.2 reports MUST
  carry the pack key.**
- `verify_report` + success-rate aggregation **dual-read** (v0.1 label-format and
  v0.2 id-format), preferring id when the version says so; old v0.1 reports
  resolve best-effort as `zh-Hans` with a `--report-locale` override. Optional
  one-shot v0.1→v0.2 converter.
- **Gate:** the same zh run validates under v0.2 AND re-validates an archived v0.1.

### P3 — Locale-aware Platform classifier
- Wire `glassbox/ios/scene.py` to `locale.chrome` (app-agnostic back/edit-done/
  Spotlight/app-library/blocked-safety), `locale.app("settings").surfaces`
  (page-title / search / detail markers), and
  `sections.root_classifier_terms(EXPECTED_ROOT_SECTIONS)` (root markers,
  **derived**, no second copy). English-primary ordering.
- Do NOT move Settings markers into `chrome`; do NOT add a separate
  `root_markers`. Keep `_TIME_RE`/geometry/`HARNESS_CONSOLE_MARKERS` neutral.
- **Gate:** re-validate zh; English becomes live-testable end-to-end.

### P4 — English parity + global default flip
- A clean **multi-round** English drill-down (the single-round en-HK 15/17 is
  done) + `verify_report` with `CELLULAR` device-unavailable on this no-SIM rig.
- Only when **both locales are green in CI on the v0.2 wire format**, flip the
  in-code global default `language` from `zh-Hans` to `en-US`.

## Acceptance

- zh 5-round drill-down stays 15/17 after each phase (the regression gate).
- v0.2 reports are byte-comparable across en/zh on coverage ids; verifier
  dual-reads both formats; an archived v0.1 report still validates.
- An English live drill-down reaches parity, then the default flip lands with
  both locales green in CI.

## Constraints

- Cross-locale resolve fallback stays **app-scoped** (union of that app's
  aliases), never a global union.
- The identity schema stays owned by the Settings domain (`sections.py`); Locale
  is the *vocabulary* source only (not Profile.localization, not `_APP_ALIASES`).
- Do not pin `GLASSBOX_LANGUAGE` in `.env` before the P4 flip — it flips the
  global `get_config` default for every caller incl. the smoke suite (breaks
  `test_greater_china_english_is_pack_bound`). Use the per-run flags until then.
