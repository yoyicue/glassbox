.PHONY: lint test check regression-gate regression-compare ab-semantic-plan \
	computer-use-success-rate-ios-settings

# CUQ-3.3: the reliability merge gate. `make check` is device-independent (no
# PicoKVM/HDMI rig needed) and is what CI runs on every PR so a reliability
# regression cannot merge silently. Keep it green before pushing.
lint:
	uv run ruff check glassbox skills

test:
	uv run pytest skills/smoke -q

check: lint test regression-gate

ROUNDS ?= 1
OUT ?= artifacts/computer_use_success_rate/benchmark.json
ARTIFACT_ROOT ?= artifacts/computer_use_success_rate/runs
REPORT_DIR ?= artifacts/computer_use_success_rate/reports
TERMINAL_EXPECTED_STATE ?= {"kind":"page_id","payload":{"page_id":"settings/root"}}
COMPUTER_USE_SUCCESS_RATE ?= uv run python -m skills.regression.computer_use_success_rate

computer-use-success-rate-ios-settings:
	$(COMPUTER_USE_SUCCESS_RATE) run-ios-settings \
		--rounds $(ROUNDS) \
		--out "$(OUT)" \
		--artifact-root "$(ARTIFACT_ROOT)" \
		--report-dir "$(REPORT_DIR)" \
		--terminal-expected-state '$(TERMINAL_EXPECTED_STATE)' \
		$(EXTRA_ARGS)

# Offline half of the Step-0 reliability gate (folded into `make check`, runs in
# CI with no hardware): prove the committed baseline floor is still schema-valid
# and that the comparator catches a regression (rc 1) / rejects a malformed
# candidate (rc 2). The on-rig time-series companion is rig-nightly.yml.
RELIABILITY_BASELINE ?= skills/regression/fixtures/reliability_baseline.json
regression-gate:
	$(COMPUTER_USE_SUCCESS_RATE) validate "$(RELIABILITY_BASELINE)"
	uv run pytest skills/smoke/test_computer_use_regression_gate.py -q

# Compare a freshly-produced benchmark ($(CANDIDATE)) against the committed floor,
# failing (rc 1) on any success-rate regression beyond $(TOLERANCE). This is the
# on-rig gate the nightly workflow runs after a real device run.
CANDIDATE ?= artifacts/computer_use_success_rate/benchmark.json
TOLERANCE ?= 0.0
regression-compare:
	$(COMPUTER_USE_SUCCESS_RATE) compare "$(RELIABILITY_BASELINE)" "$(CANDIDATE)" --tolerance $(TOLERANCE)

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
