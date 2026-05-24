# Goal — Wire up (or remove) dead/parallel logic

Status: **open / ready to pick up**. Audit 2026-05-24, re-assessed with the
owner; no code changed by the audit itself. Findings are grouped by **severity
class**, not just listed — they are not all the same kind of problem.

## Context

An audit looked for logic that *exists in the tree but does not participate in
the live execution path* — the same class of gap as the locale `*_ids` that were
computed but never reached the live report. Two things people assumed were
"unwired" turned out to be wired (see [Confirmed wired](#confirmed-wired-no-action)).
The rest splits into:

- **Class A — real unwired risk / dead code:** drift hazard, dead code, or
  config that silently does nothing. Worth acting on.
- **Class B — naming / documentation misleading:** the code *works*; the risk is
  a maintainer assuming it does something it doesn't. Annotate, don't rush an
  implementation change.
- **Optimization (not a bug):** a default that leaves value on the table.

Evidence is cited as `file:line` (valid 2026-05-24; symbol names are the stable
anchor if lines drift).

## Recommended order

1. **#2 + #4** — pure cleanup (delete dead wrapper; resolve/annotate vestigial config). Lowest risk.
2. **#5** — default a VLM describe-cache dir. Clear, low-risk cost win.
3. **#1 (small fix only)** — a single shared `canonical label → RootSection` exit so report + verifier stop each assembling their own logic. The **full DI migration stays deferred** — do not fold it into this cleanup round.
4. **#3** — documentation/naming annotation only.

---

## Class A — real unwired risk / dead code

### 1. Typed locale resolver is a parallel resolver, not the live decision source ⭐

The live crawl resolves OCR text → section through
`DEFAULT_SETTINGS_POLICY.canonical_expected_root_label()` (`policy.py:666`) — the
Chinese-string alias map. The typed `SectionVocab.resolve()` (`sections.py:173`)
is **not an independent production decision source**: it serves report/test, and
its zh path actually **reverse-calls the policy** —
`sections.py:191-193` imports `DEFAULT_SETTINGS_POLICY` and delegates to
`canonical_expected_root_label`. So there are two label→id tables that must agree.

- **Severity:** not an immediate crash — the hazard is the two tables/aliases
  **drifting** over time, so the report/verifier id view silently disagrees with
  the crawl's actual decisions.
- **Small fix (this round):** factor a single shared `canonical label →
  RootSection` conversion exit and route report + verifier through it, so neither
  re-assembles the mapping. Keep zh as the internal pivot.
- **Full fix (deferred — do NOT do here):** the designed
  `SettingsPolicy(sections=locale.app("settings").sections)` DI, replacing the
  ~159 zh-string call sites with `RootSection` (churns ~348 zh test assertions).
  Tracked in [`docs/design/locale_seam_english_first.md`](../design/locale_seam_english_first.md).

### 2. `core._vlm_recover_root_label` is dead — delete it

The wrapper `core.py:962` has **zero references**. The live VLM row recovery runs
directly via `page_records.py:112` and `page_records.py:184`
(`vlm_rows.recover_root_label`). The test helper also aliases **straight to
`vlm_rows.recover_root_label`** (`ios_settings_walkthrough_support.py:55`), not to
the wrapper — so nothing points at the wrapper at all.

- **Severity:** dead indirection only (the feature itself is wired).
- **Action:** delete the wrapper. Low risk.

### 4. Dead / vestigial config fields

| Field | Evidence | Verdict |
| --- | --- | --- |
| `wheel_interval_ms` | `config.py:87` parsed, but scroll consumes `wheel_ticks_per_scroll` (`config.py:85`) via `scroll_wheel` (`phone.py:1794`+); no reader of the interval | wire into the effector/phone, or delete |
| `effector_crop_bbox` / `effector_crop_cache` / `effector_crop_retries` | `config.py:93` — "for plugin effectors"; PicoKVM uses its own `GLASSBOX_PICOKVM_*`; no built-in consumer | if kept, label "reserved — no built-in consumer" in the docstring |
| `ios_device` | `config.py:239` — no consumer anywhere (not even a test) | delete |

- **Severity:** documented knobs that silently do nothing mislead users (cf. the
  `run_full` VLM-default contract gap already fixed).

---

## Class B — naming / documentation misleading (works, but invites a wrong edit)

### 3. CrawlPolicy `ios_settings` adapter does not drive the real Settings regression

`glassbox/crawl_policies.py:1` is explicitly provisional. The generic runner
resolves it (`skills/crawl/run.py:26`), but the Settings full run uses the
bespoke `crawl_readonly_settings` (`run_full.py:98`), which never imports
`glassbox.crawl_policies`.

- **Severity:** **not a runtime bug.** The risk is a maintainer assuming an edit
  to the adapter affects the Settings regression.
- **Action (this round):** documentation / naming only — mark the adapter clearly
  as a generic-runner path, not the live Settings policy. Defer any decision to
  converge the bespoke crawl onto the seam.

---

## Optimization (not a bug)

### 5. VLM describe cache is wired but unset by default

The runtime honors the cache dir (`runtime.py:464`,
`cache_dir=cfg.vlm_cache_dir or cfg.kimi_cache_dir`), but `build_full_run_env`
defaults only the icon-map path, not `GLASSBOX_VLM_CACHE_DIR`
(`config.py:186`) — so VLM describe results are recomputed every run.

- **Action:** default `GLASSBOX_VLM_CACHE_DIR` to e.g. `~/.cache/glassbox/vlm_describe/`
  (overridable), mirroring the icon-map persistence. Clear cost win, low risk.

---

## Confirmed wired (no action)

Recorded so the next person does not re-investigate:

- **VLM** — cold-start SpringBoard icon map + row-OCR recovery
  (`page_records.py:112/184 → vlm_rows.recover_root_label`) both run; the only
  gate was the default-off flag, which `build_full_run_env` flips on for Settings
  runs.
- **Screen memory / UTG** — enabled via `build_full_run_env`
  (`GLASSBOX_ENABLE_MEMORY=1` + bundle), assembled at `runtime.py:456`, and read
  by `_try_memory_return_to_settings_root` (`core.py:445`, wired at
  `recovery.py:246`). **Narrow scope:** memory is used only for return-to-root
  recovery, *not* to shortcut forward navigation. Widening it is a possible future
  goal, not a bug.
