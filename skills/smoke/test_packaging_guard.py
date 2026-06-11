"""Packaging-surface guards — the offline half of `make packaging-smoke`.

The wheel ships only ``glassbox/`` (pyproject ``[tool.hatch.build.targets.wheel]``),
so anything pyproject advertises to installed consumers — console scripts,
entry points — must resolve inside the shipped package. The editable dev
install masks violations (the repo root rides sys.path), which is exactly how
a core→skills console script and entry point shipped broken; these tests make
the breakage class visible offline, and ``skills/regression/packaging_probe.py``
proves the same from a real wheel install.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _shipped_top_level_packages(pyproject: dict) -> set[str]:
    return {
        Path(pkg).name for pkg in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    }


@pytest.mark.smoke
def test_console_scripts_target_shipped_packages_only(pyproject):
    shipped = _shipped_top_level_packages(pyproject)
    for name, target in pyproject["project"]["scripts"].items():
        module = target.split(":", 1)[0]
        assert module.split(".", 1)[0] in shipped, (
            f"console script {name!r} targets {module!r}, which the wheel does not ship — "
            "it would ModuleNotFoundError on any non-checkout install"
        )


@pytest.mark.smoke
def test_entry_points_target_shipped_packages_only(pyproject):
    shipped = _shipped_top_level_packages(pyproject)
    for group, eps in pyproject["project"]["entry-points"].items():
        for name, target in eps.items():
            module = target.split(":", 1)[0]
            assert module.split(".", 1)[0] in shipped, (
                f"entry point {group}:{name} targets {module!r}, which the wheel does not ship"
            )


@pytest.mark.smoke
def test_py_typed_marker_exists_inside_package():
    # PEP 561: the marker must live inside the shipped package dir to ride the wheel.
    assert (REPO_ROOT / "glassbox" / "py.typed").exists()


@pytest.mark.smoke
def test_packaging_smoke_is_wired_into_the_merge_gate():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "packaging-smoke:" in makefile
    assert "packaging_probe.py" in makefile
    check_line = next(
        line for line in makefile.splitlines() if line.startswith("check:")
    )
    assert "packaging-smoke" in check_line, "packaging-smoke must be part of `make check`"


@pytest.mark.smoke
def test_checkout_only_crawl_policies_degrade_with_actionable_error(monkeypatch):
    """On a wheel install (no skills/), the Settings adapters must raise the
    documented checkout-required error, not a bare ModuleNotFoundError."""
    from glassbox import crawl_policies

    for blocked in (
        "skills",
        "skills.regression",
        "skills.regression.ios_settings",
        "skills.regression.ios_settings.policy",
    ):
        monkeypatch.setitem(sys.modules, blocked, None)

    with pytest.raises(RuntimeError, match="repo checkout"):
        crawl_policies._ios_settings_crawl_policy_factory()
    with pytest.raises(RuntimeError, match="repo checkout"):
        crawl_policies._ipados_settings_crawl_policy_factory()


@pytest.mark.smoke
def test_one_broken_entry_point_does_not_poison_the_registry(monkeypatch):
    """A single broken third-party plugin used to abort entry-point loading:
    the exception propagated out of the first names()/create() call AND every
    later entry point was silently dropped. Now it is skipped loudly."""
    from glassbox import crawl_policies

    class BrokenEntryPoint:
        name = "broken"

        def load(self):
            raise ImportError("boom — plugin env is missing its deps")

    class GoodEntryPoint:
        name = "good"

        def load(self):
            return crawl_policies.CrawlPolicyRegistration(
                name="good", factory=lambda **_kwargs: object()
            )

    monkeypatch.setattr(
        crawl_policies,
        "entry_points",
        lambda group=None: (
            [BrokenEntryPoint(), GoodEntryPoint()]
            if group == "glassbox.crawl_policies"
            else []
        ),
    )

    registry = crawl_policies.CrawlPolicyRegistry()
    assert "good" in registry.names()
    assert registry.create("good") is not None
