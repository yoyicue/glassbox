# Goal — Wire up (or remove) dead/parallel logic

Status: **open / ready to pick up**. Audit done 2026-05-24; no code changed by
the audit itself. Each item below is independently actionable.

## Context

An audit looked for logic that *exists in the tree but does not participate in
the live execution path* — the same class of gap as the locale `*_ids` that were
computed but never reached the live report. Two things people assumed were
"unwired" turned out to be wired (see [Confirmed wired](#confirmed-wired-no-action));
the genuinely unwired/parallel logic is in [Findings](#findings).

Evidence is cited as `file:line` (valid as of 2026-05-24; symbol names are the
stable anchor if lines drift).

## Findings

### 1. Typed locale resolver is not in the live decision path ⭐ (highest value)

The live crawl resolves OCR text → section **only** through
`SettingsPolicy.canonical_expected_root_label` (`policy.py:666`), a Chinese-string
alias map plus the `en-CN`/`en-HK` overlay bridge. The typed resolver
`SectionVocab.resolve()` / `RootSection` (`sections.py`) is used **only** by:

- report display, added recently — `reporting.py:36` `_active_section_vocab`,
  `reporting.py:233` (the `*_ids` / `*_display` enrichment), and
- the smoke tests.

Navigation, coverage, safety, and dedup never call it. So there are **two
parallel resolvers** that must be kept in sync by hand.

- **Why it matters:** drift risk — the report's displayed/identified section can
  disagree with the section the crawl actually navigated/scored, because they are
  resolved by different code with different alias tables.
- **Suggested action (incremental, low blast radius):** make the report display
  derive from the *same* resolution the crawl used (e.g. have the live path
  record the resolved `RootSection` id on each visit, and let reporting render
  from that), instead of re-resolving the zh label a second time through
  `SectionVocab`. This collapses the two paths at the report boundary without the
  full DI rewrite.
- **Full fix (deferred, large):** the designed
  `SettingsPolicy(sections=locale.app("settings").sections)` DI — replace the
  ~159 zh-string call sites with `RootSection`. Tracked in
  [`docs/design/locale_seam_english_first.md`](../design/locale_seam_english_first.md);
  out of scope for this goal unless explicitly taken on (churns ~348 zh test
  assertions).

### 2. `core._vlm_recover_root_label` is a dead wrapper

`core.py:962` `_vlm_recover_root_label(phone, element)` wraps
`vlm_rows.recover_root_label`, but has **zero callers**. The live VLM row
recovery runs directly via `page_records.py:112` and `page_records.py:184`. The
only other reference is a test alias in
`skills/smoke/ios_settings_walkthrough_support.py`.

- **Why it matters:** dead indirection; a reader assumes core owns VLM row
  recovery when it does not.
- **Suggested action:** delete `_vlm_recover_root_label` (and its test alias /
  any test that only exercises the wrapper), or route `page_records` through it
  if a single seam is wanted. Confirm the feature still works (it lives in
  `vlm_rows.recover_root_label`).

### 3. CrawlPolicy seam's `ios_settings` adapter does not drive the real crawl

`glassbox/crawl_policies.py` + `app_policies.py:50` (`crawl_policy="ios_settings"`)
are consumed only by the generic runner `skills/crawl/run.py:26-27`. The actual
Settings regression crawl (`skills/regression/ios_settings/`) is bespoke and
never imports `glassbox.crawl_policies`.

- **Why it matters:** the provisional adapter looks authoritative but is a
  separate, generic path; changes there do not affect the real Settings run.
  (Consistent with the "CrawlPolicy provisional" note in
  [`docs/design/architecture_boundaries.md`](../design/architecture_boundaries.md).)
- **Suggested action:** decide the intent — either converge the regression crawl
  onto the seam, or mark the `ios_settings` adapter explicitly as a generic-runner
  demo so it is not mistaken for the live policy.

### 4. Dead / vestigial config fields (parsed + sometimes tested, no runtime consumer)

| Field | env | Status |
| --- | --- | --- |
| `effector_crop_bbox` (`config.py:93`) | — | "for plugin effectors"; PicoKVM uses its own `GLASSBOX_PICOKVM_*`. No shipped consumer. |
| `effector_crop_cache` (`config.py:96`) | — | Same — forward-looking seam config, currently inert. |
| `effector_crop_retries` (`config.py:99`) | — | Same. Only `test_config.py` reads it. |
| `wheel_interval_ms` (`config.py:87`) | `GLASSBOX_WHEEL_INTERVAL_MS` | No runtime consumer; wheel timing is driven by `GLASSBOX_WHEEL_TICKS_PER_SCROLL`. Setting it does nothing. |
| `ios_device` (`config.py:239`) | — | Zero references anywhere (not even a test). Fully vestigial. |

- **Why it matters:** documented knobs that silently do nothing mislead users
  (cf. the `run_full` VLM-default contract gap already fixed).
- **Suggested action:** for each, either (a) wire it to its consumer, or (b)
  remove it; if it is a deliberate plugin-effector extension seam
  (`effector_crop_*`), keep it but say so in the docstring ("reserved for plugin
  effectors; no built-in consumer").

### 5. VLM describe cache is wired but unset by default (tuning, not a bug)

`vlm_cache_dir` / `kimi_cache_dir` are honored at `runtime.py:464`
(`cache_dir=cfg.vlm_cache_dir or cfg.kimi_cache_dir`) but default to unset, so
VLM describe results are not cached across runs. Unlike the SpringBoard icon map,
`build_full_run_env` does not default a path, so repeat VLM describe cost is paid
every run.

- **Suggested action (small win):** mirror the icon-map persistence — have
  `build_full_run_env` default `GLASSBOX_VLM_CACHE_DIR` (e.g. under
  `~/.cache/glassbox/`), overridable. Bounds VLM cost without changing behavior.

## Confirmed wired (no action)

Recorded so the next person does not re-investigate:

- **VLM** — cold-start SpringBoard icon map + row-OCR recovery
  (`page_records.py:112/184 → vlm_rows.recover_root_label`) both run; the only
  gate was the default-off flag, which `build_full_run_env` flips on for Settings
  runs.
- **Screen memory / UTG** — enabled via `build_full_run_env`
  (`GLASSBOX_ENABLE_MEMORY=1` + bundle), assembled at `runtime.py:456`, and read
  by `_try_memory_return_to_settings_root` (`core.py:445`, wired at
  `recovery.py:246`). **Note the narrow scope:** memory is used only for
  return-to-root recovery, *not* to shortcut forward navigation. Widening it
  (memory-guided forward nav) is a possible future goal, not a bug.

## Suggested order

1. **#2 + #4** — cleanup (delete dead wrapper + resolve/annotate vestigial
   config). Low risk, pure subtraction.
2. **#1 (incremental)** — collapse report display onto the live resolution to
   kill the drift risk.
3. **#5** — default a VLM describe cache dir.
4. **#3** — decide CrawlPolicy adapter intent.
5. **#1 (full DI)** — only if the neutral-id migration is explicitly scheduled.
