"""Architecture guards for snapshot item 5 (platform seepage + logging).

Two rules this repo wants to keep after paying the debt down:

1. Platform-NEUTRAL modules (assembly, facade, registries, planners) must not
   import iOS modules at import time — platform code loads lazily at the call
   sites that are platform-specific by construction. (The Platform seam is the
   long-term owner; these guards stop regression meanwhile.)
2. Library code reports through loguru, not print() — real failure paths (UTG
   save, profile load) used to report via print and were invisible to any log
   collector. print() remains legitimate only in CLI/demo entry points.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The exact imports that used to leak (snapshot item 5); extend when fixing more.
_FIXED_SEEPAGE_MODULES = (
    "glassbox.ios.settings_rows",  # was: runtime.py / target_planner.py header
    "glassbox.ios.scene",          # was: app_policies.py header
    "glassbox.ios.app_aliases",    # facade alias data, now lazy in launch_app()
)

_NEUTRAL_IMPORTERS = (
    "glassbox.runtime",
    "glassbox.target_planner",
    "glassbox.app_policies",
    "glassbox.ai",
)


@pytest.mark.smoke
def test_platform_neutral_modules_do_not_import_ios_eagerly():
    code = (
        "import sys\n"
        + "\n".join(f"import {mod}" for mod in _NEUTRAL_IMPORTERS)
        + "\nleaks = [m for m in "
        + repr(list(_FIXED_SEEPAGE_MODULES))
        + " if m in sys.modules]\n"
        + "raise SystemExit(', '.join(leaks) if leaks else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert proc.returncode == 0, (
        f"platform-neutral modules eagerly import iOS modules again: {proc.stderr.strip()} "
        "(make the import lazy at its platform-specific call site)"
    )


# Files where print() IS the interface (CLI/demo/stdio protocol), not logging.
_PRINT_ALLOWED = (
    "glassbox/demo/",
    "glassbox/mcp/",
    "glassbox/ai_session.py",
    "glassbox/cognition/vlm_kimi.py",  # __main__ smoke CLI block
    "glassbox/obs/replay.py",          # replay CLI output
)

_PRINT_CALL = re.compile(r"(?<![\w.])print\(")


@pytest.mark.smoke
def test_library_code_logs_via_loguru_not_print():
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "glassbox").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(allowed) for allowed in _PRINT_ALLOWED):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _PRINT_CALL.search(stripped):
                offenders.append(f"{rel}:{lineno}: {stripped[:80]}")
    assert not offenders, (
        "library code must log via loguru, not print() (print is only the UI of "
        "CLI/demo modules):\n  " + "\n  ".join(offenders)
    )
