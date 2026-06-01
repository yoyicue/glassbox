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
so future work should still route row entry through the semantic/expected-state
path before attributing wins to those gates.

It is load-bearing in two places:

- **Offline (CI, every PR):** `make regression-gate` validates that this fixture
  is a completed floor, is still schema-valid, and that `compare_benchmarks`
  catches a regression (rc 1) and rejects a malformed candidate (rc 2). Pinned
  by `skills/smoke/test_computer_use_regression_gate.py`. No hardware needed.
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
