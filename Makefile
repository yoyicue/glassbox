.PHONY: lint test check worktree regression-gate regression-compare regression-compare-l2-advisory machinery-probe-gate ab-semantic-plan \
	human-baseline-template human-baseline-validate \
	golden-harvest golden-audit packaging-smoke \
	computer-use-success-rate-ios-settings ipad-settings-state-machine ipad-settings-ab-matrix ios-settings-ab-matrix

# CUQ-3.3: the reliability merge gate. `make check` is device-independent (no
# PicoKVM/HDMI rig needed) and is what CI runs on every PR so a reliability
# regression cannot merge silently. Keep it green before pushing.
lint:
	uv run ruff check glassbox skills

test:
	uv run pytest skills/smoke -q

check: lint test regression-gate golden-audit packaging-smoke

# Wheel-install packaging smoke: build the wheel and probe it from an isolated
# env WITHOUT the repo on sys.path — console scripts resolve, advertised entry
# points load, checkout-only crawl policies degrade with an actionable error,
# py.typed ships. The editable dev install masks this entire breakage class
# (the repo root rides sys.path), which is how a core→skills import shipped
# broken in the published wheel. Needs the uv cache (or network) for the
# wheel's dependencies — CI has both.
PACKAGING_SMOKE_DIST ?= dist/_packaging_smoke
PACKAGING_SMOKE_PYTHON ?= 3.11
packaging-smoke:
	rm -rf "$(PACKAGING_SMOKE_DIST)"
	uv build --wheel --out-dir "$(PACKAGING_SMOKE_DIST)" >/dev/null
	uv venv --python $(PACKAGING_SMOKE_PYTHON) "$(PACKAGING_SMOKE_DIST)/venv" >/dev/null
	uv pip install --python "$(PACKAGING_SMOKE_DIST)/venv" --quiet $(PACKAGING_SMOKE_DIST)/*.whl
	"$(PACKAGING_SMOKE_DIST)/venv/bin/python" skills/regression/packaging_probe.py

# Create a git worktree pre-linked with the gitignored local-only config that
# `git worktree add` otherwise silently omits — `.env` (without it the effector
# is selected as NoOp: no HID) and the AGPL omniparser plugin. Symlinks, single
# source of truth. Each worktree still needs its own `uv sync --extra dev`
# (separate .venv). See scripts/new-worktree.sh. Usage:
#   make worktree DEST=../gb-foo BRANCH=feature/foo
worktree:
	scripts/new-worktree.sh "$(DEST)" "$(BRANCH)"

ROUNDS ?= 1
OUT ?= artifacts/computer_use_success_rate/benchmark.json
ARTIFACT_ROOT ?= artifacts/computer_use_success_rate/runs
REPORT_DIR ?= artifacts/computer_use_success_rate/reports
TERMINAL_EXPECTED_STATE ?= {"kind":"root_coverage_complete","payload":{}}
COMPUTER_USE_SUCCESS_RATE ?= uv run python -m skills.regression.computer_use_success_rate

computer-use-success-rate-ios-settings:
	GLASSBOX_PICOKVM_ROBUST_CAPTURE=$${GLASSBOX_PICOKVM_ROBUST_CAPTURE:-1} \
	$(COMPUTER_USE_SUCCESS_RATE) run-ios-settings \
		--rounds $(ROUNDS) \
		--out "$(OUT)" \
		--artifact-root "$(ARTIFACT_ROOT)" \
		--report-dir "$(REPORT_DIR)" \
		--terminal-expected-state '$(TERMINAL_EXPECTED_STATE)' \
		$(EXTRA_ARGS)

# Offline half of the Step-0 reliability gate (folded into `make check`, runs in
# CI with no hardware): prove the committed completion floor and human-control
# template are still schema-valid, and that the comparator catches a regression
# (rc 1) / rejects a malformed candidate (rc 2). The on-rig time-series companion
# is rig-nightly.yml.
RELIABILITY_BASELINE ?= skills/regression/fixtures/reliability_baseline.json
HUMAN_BASELINE ?= skills/regression/fixtures/human_baseline_settings_template.json
HUMAN_BASELINE_VALIDATE_ARGS ?= --allow-template
HUMAN_BASELINE_CLI ?= uv run python -m skills.regression.human_baseline
regression-gate:
	$(COMPUTER_USE_SUCCESS_RATE) validate "$(RELIABILITY_BASELINE)"
	$(HUMAN_BASELINE_CLI) validate "$(HUMAN_BASELINE)" $(HUMAN_BASELINE_VALIDATE_ARGS)
	uv run pytest skills/smoke/test_computer_use_regression_gate.py skills/smoke/test_human_baseline.py \
		skills/smoke/test_clock_tabs_floor.py skills/smoke/test_verifier_alignment.py -q

human-baseline-template:
	$(HUMAN_BASELINE_CLI) template --out "$(HUMAN_BASELINE)"

human-baseline-validate:
	$(HUMAN_BASELINE_CLI) validate "$(HUMAN_BASELINE)" $(HUMAN_BASELINE_VALIDATE_ARGS)

# Tier A (log-sim): harvest verifier golden-cases from run ledgers into the
# committed corpus. Manual/dev target — re-run and commit when ledgers change.
# The replay+floor guard rides `make test` (skills/smoke/test_golden_ingest.py).
GOLDEN_INGEST ?= uv run python -m skills.regression.golden_ingest
HARVESTED_DIR ?= skills/golden/computer_use/_harvested
golden-harvest:
	$(GOLDEN_INGEST) harvest --roots artifacts --out "$(HARVESTED_DIR)"

# Fail (rc 1) if the committed harvested corpus drifts from a fresh harvest.
# No-ops (rc 0) in CI where artifacts/ is gitignored — folded into `make check`
# so it guards on hosts that have ledgers without breaking hardware-free CI.
golden-audit:
	$(GOLDEN_INGEST) audit --roots artifacts --against "$(HARVESTED_DIR)"

# Compare a freshly-produced benchmark ($(CANDIDATE)) against the committed floor,
# failing (rc 1) on any success-rate regression beyond $(TOLERANCE). This is the
# on-rig gate the nightly workflow runs after a real device run.
CANDIDATE ?= artifacts/computer_use_success_rate/benchmark.json
TOLERANCE ?= 0.0
regression-compare:
	$(COMPUTER_USE_SUCCESS_RATE) compare "$(RELIABILITY_BASELINE)" "$(CANDIDATE)" --tolerance $(TOLERANCE)

# ADVISORY L2 coverage report (NON-blocking on purpose). Compare a fresh VLM-on
# Settings run ($(L2_CANDIDATE), produce it with
# `make computer-use-success-rate-ios-settings EXTRA_ARGS="--vlm --drill-down --language en --region HK" OUT=$(L2_CANDIDATE)`
# on a rig with VLM credentials) against the committed L2 coverage snapshot, and
# PRINT the vlm_action_coverage / strategy_switches deltas for human inspection.
#
# It deliberately does NOT fail the build (`-` prefix ignores the compare rc): a
# DROP in these "machine-escalated" metrics can mean the path got MORE reliable
# (fewer escalations needed), not a regression — blocking on it would be perverse.
# The committed snapshot's coverage is guarded offline by
# test_l2_expected_state_snapshot_fixture_is_load_bearing_and_scrubbed; the real
# BLOCKING machinery-regression gate is the failure-injection eval, not this.
L2_SNAPSHOT ?= skills/regression/fixtures/l2_settings_expected_state_snapshot.json
# A11y cell snapshot (Voice Control overlay ON) — advisory-only readout; the
# cell is never a floor candidate and never a regression-compare CANDIDATE.
A11Y_VC_SNAPSHOT ?= skills/regression/fixtures/a11y_voice_control_cell_snapshot.json
L2_CANDIDATE ?= artifacts/computer_use_success_rate/l2_benchmark.json
regression-compare-l2-advisory:
	@echo "=== ADVISORY L2 coverage report (non-blocking) — VLM/strategy deltas for inspection ==="
	-$(COMPUTER_USE_SUCCESS_RATE) compare "$(L2_SNAPSHOT)" "$(L2_CANDIDATE)" --tolerance $(TOLERANCE)
	@echo "=== advisory only: a coverage DROP may mean the path got more reliable, not a regression ==="

# P2/P3 machinery probe — the BLOCKING teeth for the strategy ladder + recovery
# the clean floor can't see. Injects a controlled verification failure on the rig
# (tap a present row, declare an unreachable page) and FAILS (rc 1) unless the
# ladder advanced (strategy_switches>=1) AND recovery fired (recoveries>=1). Unlike
# the perverse "coverage must not drop", "the machine must fire on an injected
# fault" is a true, non-flaky invariant. Rig-only; needs the strategy ladder
# enabled (GLASSBOX_SEMANTIC_PLAN_OPS). The gate logic is unit-tested offline in
# test_machinery_probe.py. Add `--vlm` via EXTRA to also probe P1 escalation.
MACHINERY_PROBE_OUT ?= artifacts/computer_use_success_rate/machinery_probe_benchmark.json
machinery-probe-gate:
	$(COMPUTER_USE_SUCCESS_RATE) run-machinery-probe \
		--rounds $(ROUNDS) \
		--out "$(MACHINERY_PROBE_OUT)" \
		--artifact-root "$(ARTIFACT_ROOT)" \
		$(EXTRA_ARGS)

# One-command on-rig A/B for the P1/P2 strategy ladder (CUQ-0.1: back/scroll/tap
# route through default_semantic_action_plan with verified-failure strategy
# switching). Runs the canonical primitives twice on the rig — flags-off baseline
# vs GLASSBOX_SEMANTIC_PLAN_OPS=$(AB_OPS) candidate — then gates: rc 0 means the
# ladder did not regress and is safe to flip default-on (set semantic_plan_ops in
# config.py); rc 1 means it regressed, keep it off. Needs a live PicoKVM rig.
AB_DIR ?= artifacts/computer_use_success_rate/ab
AB_OPS ?= back,scroll,tap
ab-semantic-plan:
	@echo ">>> baseline: strategy ladder OFF (semantic_plan_ops empty)"
	GLASSBOX_SEMANTIC_PLAN_OPS= $(COMPUTER_USE_SUCCESS_RATE) run-canonical-primitives \
		--rounds $(ROUNDS) --out "$(AB_DIR)/baseline.json" --artifact-root "$(AB_DIR)/baseline_runs"
	@echo ">>> candidate: strategy ladder ON ($(AB_OPS))"
	GLASSBOX_SEMANTIC_PLAN_OPS=$(AB_OPS) $(COMPUTER_USE_SUCCESS_RATE) run-canonical-primitives \
		--rounds $(ROUNDS) --out "$(AB_DIR)/candidate.json" --artifact-root "$(AB_DIR)/candidate_runs"
	@echo ">>> gate: candidate must not regress vs baseline (rc 1 = regression -> keep ladder off)"
	$(COMPUTER_USE_SUCCESS_RATE) compare "$(AB_DIR)/baseline.json" "$(AB_DIR)/candidate.json" --tolerance $(TOLERANCE)

# One-command on-rig acceptance for docs/design/ipad_settings_state_machine.md.
# Default (B-arm): root projection ON + the state-machine acceptance asserted.
# For the flag-off A-arm of the rig A/B, override BOTH make variables — turn the
# projection off AND empty the acceptance flags, because with the flag off no
# settings/root node is projected, so the structural assertions would fail by
# construction. Use a distinct report path so the arms get isolated UTG stores:
#   make ipad-settings-state-machine \
#       IPAD_SETTINGS_ROOT_PROJECTION=0 IPAD_SETTINGS_ACCEPTANCE= \
#       IPAD_SETTINGS_REPORT=artifacts/ios_settings/baseline.json \
#       IPAD_SETTINGS_EXTRA_ARGS='--language en --region HK'
# Override via make VARIABLES, not a shell env var: the recipe sets
# GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION explicitly from IPAD_SETTINGS_ROOT_PROJECTION.
IPAD_SETTINGS_REPORT ?= artifacts/ios_settings/state_machine.json
IPAD_SETTINGS_RUN_FULL ?= uv run python -m skills.regression.ios_settings.run_full
IPAD_SETTINGS_MIN_RETURN_EDGES ?= 0
IPAD_SETTINGS_PHONE_MODEL ?= ipad_mini_7
IPAD_SETTINGS_PLATFORM ?= ipados
IPAD_SETTINGS_ROOT_PROJECTION ?= 1
IPAD_SETTINGS_ACCEPTANCE ?= --state-machine-acceptance --state-machine-require-sidebar-exhaustive --state-machine-min-detail-to-root-edges $(IPAD_SETTINGS_MIN_RETURN_EDGES)
IPAD_SETTINGS_EXTRA_ARGS ?=
ipad-settings-state-machine:
	GLASSBOX_PHONE_MODEL=$(IPAD_SETTINGS_PHONE_MODEL) \
	GLASSBOX_PLATFORM=$(IPAD_SETTINGS_PLATFORM) \
	GLASSBOX_SETTINGS_IPAD_ROOT_PROJECTION=$(IPAD_SETTINGS_ROOT_PROJECTION) $(IPAD_SETTINGS_RUN_FULL) \
		--report "$(IPAD_SETTINGS_REPORT)" \
		--drill-down \
		$(IPAD_SETTINGS_ACCEPTANCE) \
		$(IPAD_SETTINGS_EXTRA_ARGS)

# Interleaved on-rig matrix for the default-off OCR/layout switches from
# docs/goals/ocr_max_out_vision_levers.md and
# docs/goals/ui_element_layout_segmentation.md. Override arms/rounds/locales via
# IPAD_SETTINGS_AB_* env vars; add iPhone/iPad parity with
# IPAD_SETTINGS_AB_DEVICES='ipad_mini_7:ipados:state_machine iphone_17_pro_max:ios:none'.
# The script writes JSONL rows with the tested config switches copied from each report.
ipad-settings-ab-matrix:
	skills/regression/ios_settings/ab_matrix.sh

ios-settings-ab-matrix: ipad-settings-ab-matrix
