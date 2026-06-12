# Handoff — iPad Settings L1 rig A/B: finish the validation

Status: **COMPLETED 2026-05-31. T1/T2/T3 were run on the iPad mini 7 rig.
Do not flip `GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` default-on.** L1 is real
(`entered_graph` and `root_to_detail` move only in B), but the median-backed gate is
ship-negative because B is not stable enough: B crash/rc-nonzero is 2/3 on en/HK and
3/3 on zh-Hans/CN, root signatures regress to median 3, zh-Hans/CN has median
`nav_proxy=0`, and en/HK still fails the mandatory exemption cross-check.

Owner before handoff: state-machine implementation + first rig pass (2026-05-31).
Branch: **`settings-ipad-rig-ab`** (not merged; this handoff added uncommitted
tooling/docs on top of the branch).
All paths below are relative to repo root `/Users/biu/glassbox`.

---

## 0. Final result from this handoff

**Valid evidence used for the decision**

> ⚠️ **2026-05-31 post-review note: the `artifacts/ios_settings/ab/` directory (all
> `results_*.jsonl`, per-run reports, and `*.artifacts/.../memory/*.json` UTGs) was
> deleted when the host ran out of disk.** The numbers in this section are preserved
> because they were read row-by-row into the review transcript before deletion; the raw
> files are gone, so the zh-stale-graph hypothesis below could not be re-confirmed at the
> UTG-file level. To reproduce, re-run the matrix (the tooling in §5 is intact).

- en/HK physical English UI: `artifacts/ios_settings/ab/results_20260531_165130.jsonl`,
  using only the six `locale=en-HK` rows. The `zh-CN` rows in the same file are invalid
  because `zh-CN` is not a supported locale pack for this runner (`zh-Hans-CN` is).
- zh-Hans/CN physical Simplified Chinese UI: the device was actually switched to Chinese
  in Settings > Language & Region, then verified by OCR/screenshot
  `artifacts/ios_settings/current_language_region_zh_applied.png` with text including
  `设置`, `通用`, `语言与地区`, `简体中文`, `地区`, `日期格式`. Valid matrix:
  `artifacts/ios_settings/ab/results_20260531_173903.jsonl`.
- Discard `artifacts/ios_settings/ab/results_20260531_171315.jsonl`: it used
  `zh-Hans/CN` runner args while the physical device UI was still English.

**Median table (n=3 per arm per locale)**

| locale | arm | rc/crash | task_completion | `entered_graph` med | `root_to_detail` med | `root_sigs` med | `nav_proxy` med | `required_missing_count` med | `visit_count` med |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| en-HK | B | 2/3 | 1/3 | **7** | **14** | **3** | 1.0 | 0 | 18 |
| en-HK | A | 1/3 | 2/3 | 0 | 0 | 0 | 1.0 | 0 | 30 |
| zh-Hans-CN | B ⚠️ | 3/3 | 0/3 | ~~7~~ | ~~13~~ | 3–14 | 0.0 | 0 | 4 |
| zh-Hans-CN | A | 3/3 | 0/3 | 0 | 0 | 0 | 0.0 | 12 | 4 |

⚠️ **The zh-Hans-CN B row is a BROKEN run, not valid positive evidence — see the review
correction below. Do not read its `entered_graph`/`root_to_detail` as real.**

**Verdict**

- ⟦review-correction 2026-05-31⟧ **L1's graph signal is demonstrated on en/HK only — NOT
  "both locales".** The original line claimed "real in both locales"; that overstates the
  zh data. The zh-Hans-CN B matrix is internally self-contradictory and must be treated as
  a broken run:
  - r2 and r3 report `visit_count=4` with `nav_proxy=0.0` (zero navigation progress) yet
    `entered_graph=7` / `root_to_detail=13`. A run that visited 4 pages with zero progress
    **cannot** have entered 7 distinct roots or built 13 root→detail edges — these are
    almost certainly read from a **stale/leaked UTG store** (a prior run's graph), not the
    zh run that actually died. (Could not be confirmed at the UTG-file level — those files
    were deleted with the rest of `ab/`; the internal contradiction alone is disqualifying.)
  - r1 reports `root_sigs=14` (root fragmented into 14 signatures — Chinese sidebar OCR is
    far worse than English's 3), `visit_count=18`.
  - All 3 zh-B rounds crashed; 2 of 3 stalled at `visit_count=4`. This is a cold-start /
    post-language-switch navigation failure, not L1 evidence either way. **zh is
    inconclusive/broken, not a positive or negative L1 result.**
  - **Net: the only trustworthy L1 signal is en/HK** — B `entered_graph` median 7,
    `root_to_detail` 14, vs A's 0/0. That alone is enough to keep the verdict
    ship-negative; zh adds no positive support.
- Blocking signal: default-on is not defensible. B still fails the operational gate:
  rc/crash is high, `task_completion` is poor, root collapse is median 3 rather than
  <=2, and zh-Hans/CN falls into low-visit/no-progress runs.
- Mandatory exemption cross-check: en/HK still fails. B's `sidebar_absent` set
  (`声音与触感`, `专注模式`, `屏幕使用时间`, `Face ID与密码`, `隐私与安全性`) overlaps roots
  reached by A/B in the same locale, so those exemptions are spurious. zh-Hans/CN has no
  same-locale overlap, but that is because both arms miss the same lower roots; it is not
  a positive proof of device-unavailability.
- Main contradiction to fix before another default-on attempt: **L4/root recovery and
  L2b sidebar-exhaustive reliability, plus L1 sidebar-signature case-fold via the locale
  seam.** L1 is useful, but the current rig behavior cannot distinguish "unavailable"
  from "not reached" robustly enough.
- ⟦review-correction 2026-05-31⟧ **New follow-on surfaced by the zh run: a crashed run can
  emit graph metrics from a stale/leaked UTG store.** The zh-B `visit=4 → entered_graph=7`
  contradiction means `ab_extract` (or the run's memory wiring) read a graph that did not
  belong to that run. Before trusting any future matrix: ensure each run gets a fresh
  isolated `memory_dir` AND that the extractor reads only that run's UTG (verify the report
  `run_id` matches the UTG path's `run_id` segment, and treat a `visit_count`-vs-`entered_graph`
  contradiction as an automatic `extraction_error`/quarantine, not a valid row).

**Tooling delivered by this handoff** (all intact; only the `artifacts/ios_settings/ab/`
output data was lost to the disk-full event — the code survives in the branch):

- `skills/regression/ios_settings/ab_extract.py`: rc-tolerant, always-one-line JSONL
  extractor, including `sidebar_absent`, `entry_exempt`, and the `entered`/`entered_graph`
  label lists (richer than the original spec, so the exemption cross-check is computable
  offline). ⟦review 2026-05-31⟧ smoke test re-run green (3 passed) after the disk event.
- `skills/regression/ios_settings/ab_matrix.sh`: single-instance locked, per-stamp,
  rc-tolerant A/B driver. Default locales are `en:HK zh-Hans:CN`.
- `skills/smoke/test_ios_settings_ab_extract.py`: good/missing/truncated report coverage.

**Review outcome (2026-05-31):** verdict (ship-negative, don't flip) is **confirmed
correct**; en/HK numbers and the exemption-cross-check failure are accurate; tooling meets
(exceeds) spec and tests pass. One correction applied above — the "real in both locales"
claim was overstated; zh is a broken/contaminated run, so the en/HK evidence stands alone.

---

## 1. What is already done (don't redo)

- **Implementation** (commit `1069406` on `main`): L1 dual-projection root +
  action-typed source attribution (`glassbox/memory/graph.py`), root node tagged
  `platform_scene_kind="settings_root"`, L3b detail-signature anchoring (memory-local
  in `graph.py`, **not** shared `signature.py`), L2a static device-profile
  availability, L4 row-tracked sidebar-wheel first move. All gated by
  `settings_ipad_root_projection` (env `GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION`,
  `glassbox/config.py:437`).
- **Acceptance tooling**: `skills/regression/ios_settings/state_machine_acceptance.py`
  + `make ipad-settings-state-machine` (parametrized for both A/B arms — see §4).
- **Offline gate**: `make check` green (1514 smoke). 3 follow-up commits on the branch
  (Makefile A/B parametrization, verifier list|bool hardening, doc as-built).
- **First rig pass**: preflight + smoke + 1 clean B-arm + 1 clean A-arm (en/HK).
  Evidence in §2. The artifacts live under `artifacts/ios_settings/ab/`
  (`pass1_snapshot/B_1.json`, `pass1_snapshot/A_1.json` are the md5-verified clean
  pair; the rest of that dir is contaminated — see §3).

## 2. What the first rig pass proved (n=1/arm — NOT enough to ship)

en/HK, iPad mini 7, PicoKVM `c1ab32fb9200e390`, back-to-back same session:

| metric | A_1 (flag OFF) | B_1 (flag ON / L1) | reading |
|---|---|---|---|
| `entered_graph` | **0** | **7** | C5 "silent no-op" flips — graph coverage live |
| `root_to_detail` success edges | **0** | **14** | L1 root-sourced edges materialize on device |
| root nodes / signatures | 0 / 0 | 2 / **2** | L1 mints + collapses (passes ≤2 gate; ideal 1) |
| `nav_proxy` | 0.952 | **1.0** | — |
| outcome | **crash `SettingsRootUnreachable` rc≠0** | `state-machine OK` | A can't return to root |

**The A-arm crash is the headline finding, and it is the C1 root cause L1 targets — not
a harness bug and not an L1 regression.** With the flag off there is no `settings/root`
node and `via_memory` return is default-off, so `return_to_settings_root`
(`recovery.py:85-122`) exhausts its 12 retries on the heuristic `back_to_settings_root`
after a fling overshoot and raises `SettingsRootUnreachable` (`recovery.py:122`). B-arm
does **not** crash because L1 lets `scene_is_settings_root` recognize the composite root
in-place (`recovery.py:93-94`) so no physical return is needed.

**Caveats already visible (quantify these against the A-arm in the rerun):**
- Root collapsed to **2** signatures, not 1. Root cause: OCR case drift on the *sidebar*
  text (`BluetOOth` / `NOtificatiOns`, o→O). **Terminology — keep this consistent with the
  design doc:** the design doc is right that *root*-signature collapse is **L1's own
  sub-item #2 (sidebar-scoped signature), not L3b** (L3b is detail-page signatures). What
  the rig exposed is that L1's sidebar-scoped signature is built from **raw OCR text that
  still carries case drift**, so it splits 2-vs-1. The fix is an **OCR case-fold on the
  sidebar text feeding L1's root signature**, applied at the **locale seam**
  (`docs/design/locale_seam_english_first.md`) so it is shared, not a second canonicalizer.
  Call it the *"L1 sidebar-signature case-fold (via the locale seam)"* — it is an
  L1-completion item that reuses the seam, **not** an extension of L3b's detail-page work.
- **B's `sidebar_exhaustive` was a FALSE positive this run, and it masked the verdict.**
  B marked 5 roots `sidebar_absent` → `device_unavailable` → `entry_exempt`
  (声音与触感 / 专注模式 / 屏幕使用时间 / Face ID与密码 / 隐私与安全性), which dropped
  them from the required set and let `required_missing=[]` + acceptance go green. But the
  **A-arm entered all 5 of those same roots** (5/5 overlap) — they are reachable; B's fling
  just didn't reach them, so "sidebar never surfaced them" was wrong. This is the L2b /
  sidebar-exhaustive oracle firing on a non-exhaustive sidebar walk — exactly the failure
  the design doc warns about ("can't tell device-unavailable from fling-overshoot until L4
  makes the walk exhaustive"). **Consequence for the verdict: acceptance-green is NOT
  sufficient. The verdict MUST cross-check that B's `sidebar_absent`/`entry_exempt` set does
  not include any root that the A-arm (or any B round) actually entered** — if it does, the
  exemption is spurious and the green is hollow (see §5 T3).
- Coverage gap is **L4 (fling overshoot)**, orthogonal to L1: B_1 missed 5 roots its
  fling didn't reach; A_1 happened to fling-hit them (`ticks=12`) before crashing.
  Do **not** read A's wider `entered`=11 as "A better" — that is per-frame coverage that
  the design explicitly distrusts; the graph-authoritative `entered_graph` is A=0 / B=7.
- A_1 also lost a required root (`蓝牙`) to OCR garble (`Cameral` / the connected-SSID row
  text), same OCR-case / locale-seam family as the root-signature split above.

## 3. Bug to fix before the rerun — matrix driver self-restart (data corruption)

The first background matrix run **duplicated itself**: two concurrent `ab_matrix.sh` +
two `run_full` processes were observed driving the **same** PicoKVM and writing the
**same** fixed filenames. Two processes on one rig corrupts both. It was killed after
one clean B+A pair; everything after `B_2` in `artifacts/ios_settings/ab/` is suspect.

Root cause is a re-invocation of the backgrounded driver (the exact trigger was not
pinned down — treat it as "the driver must be safe to invoke twice", not "find the one
trigger"). **The repo has no `flock`/lockfile pattern to copy — add one.**

**Required driver properties (the rerun script must have all four):**
1. **Single-instance lock** — refuse to start if another instance holds the lock
   (`flock` on a lockfile, or `mkdir`-based lock; fail loud, do not queue).
2. **Per-(arm,round) unique filenames** — never write a fixed path a second instance
   could clobber. Include arm+round (and ideally a session stamp passed in as an arg,
   since the runtime forbids `Date.now()` inside workflow scripts but a shell `date` is
   fine here).
3. **rc-tolerant harvest** — `run_full` exits non-zero when the A-arm crashes, but the
   report is still written (`crawl_readonly_settings` emits it in a `finally`,
   `crawler.py:70-76`). The driver MUST harvest metrics from the report regardless of
   rc, and record the crash as a datapoint (`crash=true`), **not** abort the matrix.
4. **Do not suppress the A-arm crash** — it is the C1 baseline signal. Record it; don't
   `--skip-verify` it away (and note `--skip-verify` wouldn't help anyway: the crash is
   in the crawler, before verification).

A corrected driver is embedded in §5; start from it.

## 4. The A/B entry points (already wired, verified with `make -n`)

B-arm (projection ON + acceptance asserted) — default:
```
make ipad-settings-state-machine \
  IPAD_SETTINGS_REPORT=artifacts/ios_settings/ab/B_<round>_<locale>.json \
  IPAD_SETTINGS_EXTRA_ARGS='--language en --region HK'
```

A-arm (projection OFF + acceptance emptied — required, since flag-off projects no root
so the structural assertions would fail by construction):
```
make ipad-settings-state-machine \
  IPAD_SETTINGS_ROOT_PROJECTION=0 IPAD_SETTINGS_ACCEPTANCE= \
  IPAD_SETTINGS_REPORT=artifacts/ios_settings/ab/A_<round>_<locale>.json \
  IPAD_SETTINGS_EXTRA_ARGS='--language en --region HK'
```
Distinct `IPAD_SETTINGS_REPORT` paths give isolated UTG stores (verified:
`report.with_suffix('.artifacts')/<run_id>/memory`), so arms don't cross-pollute.
Override via make **variables**, not a shell env var — the recipe sets
`GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` from `IPAD_SETTINGS_ROOT_PROJECTION`.

Rig preflight (cheap, run first):
```
GLASSBOX_PHONE_MODEL=ipad_mini_7 GLASSBOX_PLATFORM=ipados GLASSBOX_PICOKVM=1 \
  uv run python -m skills.regression.ios_settings.diagnose --require-ready --json
```

## 5. Historical task list (completed; see §0 for results)

**T1 — Harden the matrix driver** (the §3 four properties). This driver is now
committed as `skills/regression/ios_settings/ab_matrix.sh` (single-instance lock,
rc-tolerant harvest, per-`(arm,round)` filenames, interleaved B/A over
`en:HK zh-Hans:CN` × 3 rounds, row-count check). The extractor contract it depends
on is committed alongside as `skills/regression/ios_settings/ab_extract.py`.
Required extractor behaviour (the invariant that hardening is for):
- **Always print exactly ONE JSONL line and exit 0**, even when the report file is missing,
  empty, or not valid JSON, or the UTG can't be loaded. On any such failure emit a line
  carrying the call args plus `"extraction_error": "<reason>"` (e.g. `report_missing`,
  `json_decode_error`, `utg_missing`) — never crash, never print zero lines. The driver
  has a belt-and-suspenders fallback line too, but the extractor owning this keeps RESULTS
  row-complete and the reason machine-readable. **A silently missing row is the failure
  mode to design against** (it's how the first pass would have hidden a dead run).
- Fields on a successful line, at least: `arm, round, locale, rc, crash(bool — derive from
  rc≠0 and/or `metrics.exception_hit`), entered_graph, entered (per-frame, for the
  per-frame-vs-graph contrast), root_to_detail, detail_to_root, root_nodes, root_sigs,
  nav_proxy, required_missing, missing, visit_count, hid_no_progress`.
- **`sidebar_absent` and `entry_exempt`** (the raw label lists, not just counts) — these
  are what the T3 exemption cross-check consumes to detect spurious `sidebar_exhaustive`.
- Add a tiny smoke test feeding it (a) a good report, (b) a missing path, (c) a truncated
  JSON file, asserting one line out each time and `extraction_error` present for (b)/(c).

**T2 — Run the matrix**: ≥3 B + ≥3 A per locale (en/HK **and** zh-Hans/CN), interleaved,
back-to-back on the same device in one session. ~3 min/run → ~36 min for the full 4×3
matrix. Watch `results_<stamp>.jsonl`.

**T3 — Compute the verdict** against the gate in
`docs/design/ipad_settings_state_machine.md` §4:
- **Acceptance-green is necessary but NOT sufficient — do not read it as the verdict.**
  The first pass went green partly by spurious exemption (see the §2 false-positive
  caveat). Compute every signal below; a green run that fails the exemption cross-check is
  a hollow green.
- **Ship-positive (necessary, all required):**
  - `entered_graph` **median B strictly > median A** (expect A≈0, B≫0). This is the
    primary signal — graph-authoritative, not per-frame `entered`.
  - `root_to_detail` median B ≫ 0 (A=0 by construction).
  - root collapses to **≤2 signatures** (track whether the L1 sidebar-signature case-fold
    would get it to 1 — see §6).
  - `nav_proxy` Δ **> the run-to-run band** (`nav_proxy` historically swings
    0.808–0.840 → demand Δ>~0.05) — but read this jointly with crash rate.
  - **A-arm crash rate vs B-arm crash rate** — B should not crash; if A crashes in a
    meaningful fraction, that is direct C1-elimination evidence for L1.
  - **`required_missing` AND `task_completion`** for B vs A — not just acceptance. A run
    can show `required_missing=[]` only because roots were exempted; report the raw
    required-set size alongside it.
- **Exemption cross-check (MANDATORY anti-gaming gate):** for each B round, take its
  `root_coverage.sidebar_absent` / `entry_exempt` set and confirm **none of those roots was
  entered by any A round or any other B round** at the same locale. The first pass FAILED
  this: B_1 exempted 5 roots (声音与触感/专注模式/屏幕使用时间/Face ID与密码/隐私与安全性)
  that A_1 entered (5/5). Any overlap ⇒ `sidebar_exhaustive` is a false positive, the
  exemption is spurious, and that run's green does not count toward ship. Have `ab_extract.py`
  emit `sidebar_absent` and `entry_exempt` explicitly so this is computable offline.
- **Report medians, not single pairs.** State n per cell, and report crash count + the
  exemption-overlap count per arm.

**T4 — Decide & record:**
- If the gate passes on **both** locales: propose flipping `settings_ipad_root_projection`
  default-on in a separate commit, citing the medians. Keep it a deliberate, reviewed flip
  (main is not branch-protected).
- If it passes en/HK but not zh (likely if OCR case drift is locale-sensitive): land the
  **L1 sidebar-signature case-fold (via the locale seam)** first (see §6), then re-measure.
- Either way: write the medians into the design doc's as-built section and update the
  memory `ipad-settings-state-machine.md`.

## 6. Known follow-on work surfaced by the rig (not blocking the A/B, but likely gating default-on)

- **L1 sidebar-signature case-fold (via the locale seam) — collapses root 2→1.** NOTE the
  terminology: this is **completing L1's own sub-item #2** (the sidebar-scoped root
  signature), **not** an extension of L3b (L3b is detail-page signatures — keep this
  consistent with the design doc, which is explicit that root-signature collapse belongs to
  L1, not L3b). The shipped L1 builds the root signature from raw OCR text that still
  carries case drift (`BluetOOth`), so it splits. Fold OCR case **at the locale seam**
  (`docs/design/locale_seam_english_first.md`) so the fold is shared, not a second
  canonicalizer. Add a smoke test asserting `BluetOOth`≡`Bluetooth` collapse for the root
  projection. (Same `[[locale-seam-english-first]]` o→O mechanism that A_1's `蓝牙`-as-garble
  loss also needs.)
- **L2b / sidebar-exhaustive oracle is unsafe until L4 lands.** The first pass proved it
  fires on a non-exhaustive walk and spuriously exempts reachable roots (§2). Until L4 makes
  the sidebar walk exhaustive, either keep `sidebar_exhaustive` reporting-only (don't let it
  drive `entry_exempt`/required-set), or gate it behind L4. The verdict's exemption
  cross-check (§5 T3) is the interim guard.
- **L4 — the fling-overshoot ceiling is the real source of "missing".** Independent of
  L1. If L4 reliably lands on each unentered row, B-arm coverage rises to ~12/12 and the
  whole SEARCH-as-availability apparatus (C2) shrinks. Consider promoting L4 alongside L2.
- **Open design items (from the doc's review passes, still open):** iPhone/iPad sharing
  `page_id="settings/root"` vs the `screen_state_fsm.md` "root = no forward parent"
  invariant; and the "un-reverts Option-1 intent" claim is still pending the median A/B.

## 7. Hard constraints / gotchas

- **Never run two matrices against one rig.** T1's lock enforces this; respect it.
- **A-arm crash ≠ test failure.** It is the measured baseline. Harvest its report.
- **Flag stays default-off** until T3's medians say otherwise. Don't flip it to make a
  run green.
- iPad-only routing (`platforms.py`): the flag is inert on iPhone, but the shared
  `settings/root` page_id is not — see the open FSM-invariant item before relying on
  device-agnostic graph logic.
- `make -n` both arms before a long run to confirm the recipe expands as expected
  (projection env = 0 and zero acceptance flags on the A-arm).
