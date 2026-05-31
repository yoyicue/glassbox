# Handoff — iPad Settings L1 rig A/B: finish the validation

Status: **L1 (+L2a/L3b-local/L4-first-move) implemented behind
`GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION` (default-off) and structurally validated
on the iPad mini 7 rig with n=1/arm. This handoff is the remaining work to reach a
median-backed ship/no-ship decision on flipping the flag default-on.**

Owner before handoff: state-machine implementation + first rig pass (2026-05-31).
Branch: **`settings-ipad-rig-ab`** (3 commits on top of `1069406`, not merged).
All paths below are relative to repo root `/Users/biu/glassbox`.

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
  text (`BluetOOth` / `NOtificatiOns`, o→O). This is an **L3b gap** — the shipped L3b
  anchors *detail-page* signatures only; it does not yet fold OCR case on the sidebar
  text that feeds the *root* signature. Route any fix through the locale seam
  (`docs/design/locale_seam_english_first.md`), do not add a second canonicalizer.
- Coverage gap is **L4 (fling overshoot)**, orthogonal to L1: B_1 missed 5 roots its
  fling didn't reach; A_1 happened to fling-hit them (`ticks=12`) before crashing.
  Do **not** read A's wider `entered`=11 as "A better" — that is per-frame coverage that
  the design explicitly distrusts; the graph-authoritative `entered_graph` is A=0 / B=7.
- A_1 also lost a required root (`蓝牙`) to OCR garble (`Cameral`/`kacier`), same L3b
  family.

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

## 5. Tasks (in order)

**T1 — Harden the matrix driver** (the §3 four properties). Starting point:

```bash
#!/bin/bash
# iPad Settings L1 rig A/B — single-instance, rc-tolerant, per-run filenames.
set -u
cd /Users/biu/glassbox
AB=artifacts/ios_settings/ab
LOCK="$AB/.matrix.lock"
mkdir -p "$AB"
# single-instance lock (mkdir is atomic; no flock dependency)
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "ERROR: another matrix instance holds $LOCK — refusing to start"; exit 3
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
STAMP=$(date +%Y%m%d_%H%M%S)
RESULTS="$AB/results_${STAMP}.jsonl"; : > "$RESULTS"
ROUNDS=3
LOCALES="en:HK zh:CN"

run_one() {
  local arm="$1" round="$2" lang="$3" region="$4"
  local tag="${arm}_${lang}${region}_r${round}_${STAMP}"
  local report="$AB/${tag}.json" log="$AB/${tag}.run.log"
  if [ "$arm" = "B" ]; then
    make ipad-settings-state-machine IPAD_SETTINGS_REPORT="$report" \
      IPAD_SETTINGS_EXTRA_ARGS="--language $lang --region $region" > "$log" 2>&1
  else
    make ipad-settings-state-machine IPAD_SETTINGS_ROOT_PROJECTION=0 \
      IPAD_SETTINGS_ACCEPTANCE= IPAD_SETTINGS_REPORT="$report" \
      IPAD_SETTINGS_EXTRA_ARGS="--language $lang --region $region" > "$log" 2>&1
  fi
  local rc=$?   # rc-tolerant: harvest regardless (report exists via crawler finally)
  uv run python skills/regression/ios_settings/ab_extract.py \
    "$arm" "$round" "$lang-$region" "$rc" "$report" >> "$RESULTS"
}

for loc in $LOCALES; do
  lang="${loc%%:*}"; region="${loc##*:}"
  for r in $(seq 1 $ROUNDS); do
    run_one B "$r" "$lang" "$region"   # interleave to control fling variance
    run_one A "$r" "$lang" "$region"
  done
done
echo "MATRIX_DONE $STAMP"
```
Promote the metrics extractor (the inline python from the first pass) into a committed
`skills/regression/ios_settings/ab_extract.py` so the driver isn't carrying a heredoc,
and so it's testable. It must emit one JSON line per run with at least:
`arm, round, locale, rc, crash(bool), entered_graph, root_to_detail, detail_to_root,
root_nodes, root_sigs, nav_proxy, required_missing, missing, visit_count, hid_no_progress`.

**T2 — Run the matrix**: ≥3 B + ≥3 A per locale (en/HK **and** zh/CN), interleaved,
back-to-back on the same device in one session. ~3 min/run → ~36 min for the full 4×3
matrix. Watch `results_<stamp>.jsonl`.

**T3 — Compute the verdict** against the gate in
`docs/design/ipad_settings_state_machine.md` §4:
- **Ship-positive (necessary, all required):**
  - `entered_graph` **median B strictly > median A** (expect A≈0, B≫0).
  - `root_to_detail` median B ≫ 0 (A=0 by construction).
  - root collapses to **≤2 signatures** (track whether L3b-on-sidebar would get it to 1).
  - `nav_proxy` Δ **> the run-to-run band** (`nav_proxy` historically swings
    0.808–0.840 → demand Δ>~0.05) — but read this jointly with crash rate.
  - **A-arm crash rate vs B-arm crash rate** — B should not crash; if A crashes in a
    meaningful fraction, that is direct C1-elimination evidence for L1.
  - No regression in `required_missing` / `task_completion` for B vs A.
- **Report medians, not single pairs.** State n per cell.

**T4 — Decide & record:**
- If the gate passes on **both** locales: propose flipping `settings_ipad_root_projection`
  default-on in a separate commit, citing the medians. Keep it a deliberate, reviewed flip
  (main is not branch-protected).
- If it passes en/HK but not zh (likely if OCR case drift is locale-sensitive): land the
  **L3b sidebar-text OCR case fold** first (see §6), then re-measure.
- Either way: write the medians into the design doc's as-built section and update the
  memory `ipad-settings-state-machine.md`.

## 6. Known follow-on work surfaced by the rig (not blocking the A/B, but likely gating default-on)

- **L3b extension — fold OCR case on the sidebar text feeding the root signature.** This
  is what collapses root 2→1. Route through the locale seam. Add a smoke test asserting
  `BluetOOth`≡`Bluetooth` collapse for the root projection. (The `[[locale-seam-english-first]]`
  o→O fold is the same mechanism.)
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
