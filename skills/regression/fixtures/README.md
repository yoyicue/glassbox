# Reliability regression fixtures

`reliability_baseline.json` is the **committed success-rate floor** for the
Step-0 harness (`docs/design/computer_use_success_rate.md`). It is a real
benchmark aggregated from a recorded iOS-Settings rig run, with the provenance
fields (`run_id` / `started_at` / `git_sha`) pinned so the fixture is
deterministic and reviewable.

Current floor: a **failed** real iPad mini 7 (en/HK) Settings drill-down with the
P2 strategy ladder default-on (2026-05-29): `task_completion_rate = 0.0` and
`tasks[0].outcome = "failed"`. The high `action_success_rate ≈ 0.955` is a
scroll-excluded, back-heavy task-action ACK proxy, not the reliability headline.
`unknown_rate ≈ 0.036`, `strategy_switches = 5` (the ladder switched primitives
5× in production), and VLM did not fire. It is a **single round**, so it must be
replaced by a completed multi-round floor before it can serve as the ratcheting
baseline.

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

`vlm_enabled=false` here (the win is the OCR + P2 ladder path, not VLM). After an
on-rig A/B validates a further reliability flag (per
`docs/goals/computer_use_quality_rig_validation.md` — e.g. `make ab-semantic-plan`),
regenerate and overwrite this fixture from the better run so the floor ratchets
up and future regressions below the new level are caught:

```bash
uv run python -m skills.regression.computer_use_success_rate aggregate \
  --run-dir <the validated artifact run dir> \
  --task settings_readonly_walkthrough \
  --out skills/regression/fixtures/reliability_baseline.json
# then re-pin run_id/started_at/git_sha (and trim config to {phone_model,
# language, region, vlm_enabled, semantic_plan_ops, note}) for determinism,
# and `make regression-gate`.
```

> Note on the en device: `make computer-use-success-rate-ios-settings` hard-checks
> coverage against a **zh** expected-root list, so on an English iPad it fails the
> final verification even though navigation succeeds. Aggregate the artifact run
> dir directly (as above) — `aggregate` does not enforce that zh list — or run
> `python -m skills.regression.ios_settings.run_full --language en --region HK
> --drill-down` and aggregate its run dir.
