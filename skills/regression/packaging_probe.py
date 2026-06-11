"""Wheel-install packaging probe — the on-wheel half of `make packaging-smoke`.

Run INSIDE an isolated environment that has the built glassbox wheel installed
and does NOT have the repo root on sys.path (the Makefile target arranges
this via `uv run --no-project --with <wheel>`). The editable dev install puts
the repo root on sys.path, which masks the whole core→skills breakage class —
this probe proves the published install surface actually works:

- every declared console script imports and resolves its callable,
- every advertised `glassbox.*` entry point loads (and registration factories
  are callable),
- the crawl-policy registry resolves, and checkout-only policies degrade with
  an actionable error instead of a bare ModuleNotFoundError,
- the PEP 561 `py.typed` marker ships in the wheel,
- the core import surface (facade, runtime, config) imports clean.

This file is intentionally dependency-free harness code (no skills imports —
they would defeat the point). Its offline pyproject-level twin is
skills/smoke/test_packaging_guard.py.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from importlib.metadata import distribution
from pathlib import Path

FAILURES: list[str] = []


def check(label: str, fn: Callable[[], object]) -> None:
    try:
        fn()
    except Exception as exc:  # probe reports every failure kind, never aborts
        FAILURES.append(f"{label}: {type(exc).__name__}: {exc}")


def main() -> int:
    import glassbox

    # The probe is meaningless if the repo (and thus skills/) is importable.
    try:
        importlib.import_module("skills")
    except ImportError:
        pass
    else:
        print(
            "FATAL: 'skills' is importable in the probe environment — run via "
            "`make packaging-smoke` so the wheel is probed in isolation."
        )
        return 2

    dist_eps = list(distribution("glassbox").entry_points)

    # 1. Console scripts must import + resolve from the wheel alone.
    console = [ep for ep in dist_eps if ep.group == "console_scripts"]
    if not console:
        FAILURES.append("console_scripts: none declared by the glassbox distribution")
    for ep in console:
        check(f"console script {ep.name} ({ep.value})", ep.load)

    # 2. Every advertised plugin seam must load; registration factories must call.
    seam_eps = [ep for ep in dist_eps if ep.group.startswith("glassbox.")]
    seam_groups = sorted({ep.group for ep in seam_eps})
    if not seam_groups:
        FAILURES.append("entry points: wheel advertises no glassbox.* groups")
    for ep in seam_eps:

        def load_and_call(ep=ep) -> None:
            loaded = ep.load()
            if callable(loaded):
                loaded()

        check(f"entry point {ep.group}:{ep.name} ({ep.value})", load_and_call)

    # 3. Crawl-policy registry: generic works; checkout-only adapters degrade
    #    with the documented actionable error.
    def crawl_registry_checks() -> None:
        from glassbox.crawl_policies import DEFAULT_CRAWL_POLICY_REGISTRY

        names = DEFAULT_CRAWL_POLICY_REGISTRY.names()
        assert "generic" in names, f"generic policy missing: {names}"
        DEFAULT_CRAWL_POLICY_REGISTRY.create("generic")
        for checkout_only in ("ios_settings", "ipados_settings"):
            try:
                DEFAULT_CRAWL_POLICY_REGISTRY.create(checkout_only)
            except RuntimeError as exc:
                assert "checkout" in str(exc), f"{checkout_only}: undocumented error: {exc}"
            else:
                raise AssertionError(f"{checkout_only} unexpectedly creatable without skills/")

    check("crawl-policy registry", crawl_registry_checks)

    # 4. PEP 561 marker ships.
    def py_typed_ships() -> None:
        marker = Path(glassbox.__file__).parent / "py.typed"
        assert marker.exists(), "py.typed missing from wheel"

    check("py.typed marker", py_typed_ships)

    # 5. Core import surface.
    for mod in ("glassbox.ai", "glassbox.phone", "glassbox.runtime", "glassbox.config"):
        check(f"import {mod}", lambda mod=mod: importlib.import_module(mod))

    if FAILURES:
        print("packaging probe FAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(
        f"packaging probe OK: {len(console)} console scripts, "
        f"{len(seam_groups)} seam groups, generic crawl policy resolves, py.typed ships"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
