# Goal — One authoritative section identity; remove capability illusions

Status: **complete**. Audit 2026-05-24, re-assessed with the owner, implemented
2026-05-24. The findings were not the same severity: one architectural problem
(#1), plus hygiene/clarity items that should not steal its priority.

## Context

The audit looked for logic that exists in the tree but does not participate in
the live execution path. The completed work sorted into:

- **Primary contradiction (#1):** Settings root-section identity had no single
  authoritative projection exit.
- **Secondary contradiction:** config/adapters suggested capabilities that were
  not on the live path.
- **Dead code / optimization:** one wrapper had no callers; one cache default
  left value on the table.

`file:line` references below were valid when audited on 2026-05-24; symbol names
are the stable anchor if lines drift.

---

## Primary contradiction — #1: no single source of section identity

The live crawl's authority remains the Chinese canonical label from
`DEFAULT_SETTINGS_POLICY.canonical_expected_root_label()` (`policy.py:666`),
which drives navigation, safety, coverage, and dedup. The typed `RootSection` /
`SectionVocab` is not yet the trunk:

- `SectionVocab.resolve()` (`sections.py:173`) serves report/test only, and its
  zh path reverse-calls the policy (`sections.py:191`).
- Before this goal, report/test code did its own label-to-id projection through
  the section module's canonical-label mapping.
- The verifier did not check the report's language-neutral `root_coverage.*_ids`
  fields against the same projection exit.

**Done:** added the shared compatibility exit
`root_section_for_canonical_label()` /
`root_section_ids_for_canonical_labels()` in `sections.py`. Report projection,
verifier `root_coverage.*_ids` validation, and smoke tests now call that shared
exit instead of assembling their own projection.

This removes the projection drift risk without doing the full repo-wide
zh-string migration. The live crawl can keep zh labels as its internal pivot
until the larger DI migration is deliberately scheduled.

**Deferred:** the full DI model
`SettingsPolicy(sections=locale.app("settings").sections)` remains out of this
cleanup round. It would replace the zh-string call sites with `RootSection` and
is tracked in [`docs/design/locale_seam_english_first.md`](../design/locale_seam_english_first.md).

---

## Secondary contradiction — suggests capability, not live path

These were not "the system is broken" bugs. The hazard was a maintainer assuming
a change here takes effect.

| Thing | Action taken |
| --- | --- |
| `wheel_interval_ms` | Deleted from `AgentConfig`; scroll timing still uses `wheel_ticks_per_scroll`. |
| `effector_crop_bbox` / `_cache` / `_retries` | Kept as plugin-effector reserved fields; docstrings now say reserved and no built-in consumer. |
| `ios_device` | Deleted from `AgentConfig`. |
| CrawlPolicy `ios_settings` adapter | Annotated as generic-runner-only; the live Settings regression remains the bespoke crawler. |

---

## Dead code

**Done:** deleted `core._vlm_recover_root_label`. The live VLM row recovery still
runs directly via `page_records.py:112` / `page_records.py:184`
(`vlm_rows.recover_root_label`), and the smoke-test helper aliases straight to
`vlm_rows.recover_root_label`.

---

## Optimization

**Done:** `build_full_run_env` now defaults `GLASSBOX_VLM_CACHE_DIR` to
`~/.cache/glassbox/vlm_describe/` and preserves explicit overrides, mirroring the
SpringBoard icon-map persistence.

---

## Verification

Targeted verification passed:

```bash
uv run pytest skills/smoke/test_section_vocab.py skills/smoke/test_report_locale_ids.py skills/smoke/test_settings_english_resolution.py skills/smoke/test_ios_settings_report_verifier.py skills/smoke/test_config.py skills/smoke/test_ios_settings_config.py skills/smoke/test_architecture_boundaries.py
```

Result: **170 passed**.

Search checks:

- `wheel_interval_ms`, `GLASSBOX_WHEEL_INTERVAL_MS`, and `ios_device` no longer
  exist in live config/code.
- `def _vlm_recover_root_label` no longer exists in `core.py`.
- Report/verifier/tests route canonical-label identity projection through
  `root_section_for_canonical_label()` /
  `root_section_ids_for_canonical_labels()`.

## Confirmed wired (no action)

Recorded so the next person does not re-investigate:

- **VLM** — cold-start SpringBoard icon map + row-OCR recovery
  (`page_records.py:112/184 -> vlm_rows.recover_root_label`) both run; the only
  gate was the default-off flag, flipped on for Settings runs by
  `build_full_run_env`.
- **Screen memory / UTG** — enabled via `build_full_run_env`, assembled at
  `runtime.py:456`, read by `_try_memory_return_to_settings_root` (`core.py:445`,
  wired at `recovery.py:246`). Narrow scope: return-to-root recovery only, not
  forward-navigation shortcutting. Widening it is a future goal, not a bug.
