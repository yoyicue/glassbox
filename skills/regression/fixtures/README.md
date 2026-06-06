# Reliability regression fixtures

`reliability_baseline.json` is the **committed success-rate floor** for the
Step-0 harness (`docs/design/computer_use_success_rate.md`). It is a real
benchmark aggregated from a recorded iOS-Settings rig run, with the provenance
fields (`run_id` / `started_at` / `git_sha`) pinned so the fixture is
deterministic and reviewable.

Current floor: a **successful** real iPad mini 7 (en/HK) full Settings read-only
drill-down, 5 rounds, captured on 2026-06-01 at `git_sha=15d592c`.
`task_completion_rate = 1.0`, `task_completion_variance = 0.0`, every task
outcome is `succeeded`, and `root_pages_coverage = 1.0`. `action_success_rate =
1.0` and `unknown_rate = 0.0` are secondary task-action ACK metrics, not the
reliability headline. VLM and expected-state row verification did not fire on
this crawler path (`vlm_action_coverage = 0.0`, `expected_state_coverage = 0.0`),
so this floor proves completion reliability but not the semantic expected-state
row-entry path.

`l2_settings_expected_state_snapshot.json` is the committed **coverage-bearing
L2 eval snapshot** for that semantic expected-state row-entry path. It is a real
iPad mini 7 (en/HK) full Settings read-only drill-down n=5 run captured on
2026-06-06 at `git_sha=d9695ae`, after Settings row/search-result taps were
routed through `tap_element` + semantic `tap` with `page_id` expected-state.
It reports `task_completion_rate = 0.8`, `task_completion_variance = 0.16`,
`expected_state_coverage = 0.9760765550239234`, `root_pages_coverage =
0.9833333333333334`, and `recoveries = 0`. One sample failed with
`root_pages_missing = ["隐私与安全性"]`, so this snapshot is not the committed
completion floor. Its `final_state.visible_texts` and unvalidated element dumps
are scrubbed before commit to avoid preserving incidental account/modal OCR.

It is load-bearing in two places:

- **Offline (CI, every PR):** `make regression-gate` validates that this fixture
  is a completed floor, is still schema-valid, and that `compare_benchmarks`
  catches a regression (rc 1) and rejects a malformed candidate (rc 2). Pinned
  by `skills/smoke/test_computer_use_regression_gate.py`. The same smoke module
  also validates the L2 expected-state snapshot, asserts it stays scrubbed, and
  proves the real snapshot fails `compare_benchmarks` if expected-state coverage
  drops to zero. No hardware needed.
- **On-rig (nightly, self-hosted):** `.github/workflows/rig-nightly.yml` runs the
  canonical primitives and the Settings drill-down on a real device, then
  `make regression-compare CANDIDATE=<fresh benchmark>` fails the run on any drop
  in `task_completion_rate` / `action_success_rate` / `root_pages_coverage` or a
  rise in `unknown_rate` beyond `TOLERANCE`.

## Raising the floor

`vlm_enabled=false` here (the current floor is the deterministic OCR/sidebar
Settings crawler path, not VLM). After an on-rig A/B validates a further reliability flag (per
`docs/goals/computer_use_quality_rig_validation.md` — e.g. `make ab-semantic-plan`),
regenerate and overwrite this fixture from the better run so the floor ratchets
up and future regressions below the new level are caught:

```bash
uv run python -m skills.regression.computer_use_success_rate aggregate \
  --run-dir <the validated artifact run dir> \
  --task settings_readonly_walkthrough \
  --out skills/regression/fixtures/reliability_baseline.json
# then re-pin run_id/started_at/git_sha/config.note for reviewability,
# and `make regression-gate`.
```
