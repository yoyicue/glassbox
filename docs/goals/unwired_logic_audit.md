# Goal — One authoritative section identity; remove capability illusions

Status: **open / ready to pick up**. Audit 2026-05-24, re-assessed with the owner.
The findings are **not** the same severity. There is one architectural problem
(#1) and a set of hygiene/clarity items that must not be allowed to steal its
priority.

## Context

The audit looked for logic that *exists in the tree but does not participate in
the live execution path*. The results sort into:

- **Primary contradiction (#1):** Settings root-section *identity* has no single
  authoritative source. This is the mainline architectural problem.
- **Secondary contradiction:** config/adapters that *suggest a capability* but are
  not on the live path — a maintainer will assume "editing this takes effect" and
  be wrong. Delete, or annotate `reserved` / `generic-runner-only`.
- **Dead code / optimization:** a wrapper with no callers; a cache default left
  on the table.

`file:line` valid 2026-05-24; symbol names are the stable anchor if lines drift.

---

## Primary contradiction — #1: no single source of section identity ⭐

The live crawl's authority is the **Chinese canonical label** from
`DEFAULT_SETTINGS_POLICY.canonical_expected_root_label()` (`policy.py:666`) — it
drives navigation, safety, coverage, and dedup. The typed `RootSection` /
`SectionVocab` is **not** the trunk it looks like:

- `SectionVocab.resolve()` (`sections.py:173`) serves report/test only, and its zh
  path **reverse-calls the policy** (`sections.py:191`) — it depends on the very
  thing it appears to replace.
- The report does its *own* label→id projection via `ZH_CANON_TO_SECTION`
  (`reporting.py:23`).
- The verifier projects independently via `canonical_expected_root_label`
  (`verify_report.py:265`).

So the same text→identity question is answered by **three different routes**.

**Core risk:** the runtime decides it entered section *A* (policy label), but the
report/verifier, projecting through a different table, render it as *B* or drop it.
Not an immediate crash — a **silent drift** hazard that grows as the tables age.

**Strategy (one sentence):** do **not** do the full DI now — make
`canonical label → RootSection` a **single shared exit** that the report, the
verifier, and the tests all call, so no layer assembles its own projection.

- This removes the drift risk now, without detonating the repo-wide zh-string
  migration.
- **Full DI stays deferred** (the designed
  `SettingsPolicy(sections=locale.app("settings").sections)`, ~159 call sites,
  ~348 zh assertions — see
  [`docs/design/locale_seam_english_first.md`](../design/locale_seam_english_first.md)).
  Do not fold it into this round.

> #1 is the architectural judgment of this audit. The items below are cheaper and
> can be done first, but they must not displace it.

---

## Secondary contradiction — suggests capability, not live path

These are not "the system is broken." The hazard is a maintainer assuming a change
here takes effect. **Delete, or annotate `reserved` / `generic-runner-only`.**

| Thing | Evidence | Verdict |
| --- | --- | --- |
| `wheel_interval_ms` | `config.py:87` parsed; scroll consumes `wheel_ticks_per_scroll` (`config.py:85`) via `scroll_wheel` (`phone.py:1794`+); the interval has no reader | wire into the effector, or delete |
| `effector_crop_bbox` / `_cache` / `_retries` | `config.py:93` — for plugin effectors; PicoKVM uses its own `GLASSBOX_PICOKVM_*`; no built-in consumer | annotate "reserved — no built-in consumer" |
| `ios_device` | `config.py:239` — no consumer anywhere (not even a test) | delete |
| CrawlPolicy `ios_settings` adapter | `crawl_policies.py:1` provisional; generic runner resolves it (`skills/crawl/run.py:26`), but the Settings full run is bespoke `crawl_readonly_settings` (`run_full.py:98`) and never imports it | annotate "generic-runner-only"; do **not** rush to converge the bespoke crawl onto the seam |

---

## Dead code — delete

**`core._vlm_recover_root_label`** (`core.py:962`) has **zero references**. The
live VLM row recovery runs directly via `page_records.py:112` / `page_records.py:184`
(`vlm_rows.recover_root_label`), and the test helper aliases **straight to
`vlm_rows.recover_root_label`** (`ios_settings_walkthrough_support.py:55`), not the
wrapper. Delete it. Low risk.

---

## Optimization (not a bug)

**VLM describe cache unset by default.** The runtime honors the cache dir
(`runtime.py:464`), but `build_full_run_env` defaults only the icon-map path, not
`GLASSBOX_VLM_CACHE_DIR` (`config.py:186`), so describe results recompute every
run. Default it to e.g. `~/.cache/glassbox/vlm_describe/` (overridable), mirroring
the icon-map persistence. Clear cost win, low risk.

---

## Recommended order

Cheap-first, but with #1 as the architectural anchor that the rest serve:

1. **Dead code + secondary cleanup** — delete the wrapper; delete/annotate the
   capability-illusion config + the CrawlPolicy adapter. Lowest risk.
2. **VLM cache default.**
3. **#1 small fix** — the single shared `canonical label → RootSection` exit.
4. **#1 full DI** — deferred; schedule separately, never inside a cleanup round.

## Confirmed wired (no action)

So the next person does not re-investigate:

- **VLM** — cold-start SpringBoard icon map + row-OCR recovery
  (`page_records.py:112/184 → vlm_rows.recover_root_label`) both run; the only gate
  was the default-off flag, flipped on for Settings runs by `build_full_run_env`.
- **Screen memory / UTG** — enabled via `build_full_run_env`, assembled at
  `runtime.py:456`, read by `_try_memory_return_to_settings_root` (`core.py:445`,
  wired at `recovery.py:246`). **Narrow scope:** return-to-root recovery only, not
  forward-navigation shortcutting. Widening it is a future goal, not a bug.
