.PHONY: lint test check computer-use-success-rate-ios-settings

# CUQ-3.3: the reliability merge gate. `make check` is device-independent (no
# PicoKVM/HDMI rig needed) and is what CI runs on every PR so a reliability
# regression cannot merge silently. Keep it green before pushing.
lint:
	uv run ruff check glassbox skills

test:
	uv run pytest skills/smoke -q

check: lint test

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
