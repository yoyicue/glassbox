"""Runtime configuration contract for iOS Settings probes."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from skills.regression.ios_settings.policy import EXPECTED_ROOT_NAV_TEXT_ZH

DEFAULT_SETTINGS_WHEEL_TICKS_PER_SWIPE = 12


@dataclass(frozen=True)
class SettingsRunConfig:
    min_pages: int
    max_pages: int
    max_depth: int
    max_scrolls_per_page: int
    root_coverage_mode: bool
    max_child_scrolls_per_page: int
    child_navigation_enabled: bool
    strict_child_candidate_audit: bool
    max_candidates_per_page: int
    require_exhaustive: bool
    report_path: str | None = None
    run_id: str | None = None
    trace_actions: bool = False
    save_view_snapshots: bool = False
    artifact_dir: str | None = None
    memory_dir: str | None = None
    memory_reuse: bool = False
    page_id_route_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SettingsRunConfig:
        env = os.environ if env is None else env
        max_scrolls = _env_int(env, "IOS_SETTINGS_MAX_SCROLLS_PER_PAGE", 8)
        root_coverage_mode = _env_bool(env, "IOS_SETTINGS_ROOT_COVERAGE_MODE", default=True)
        return cls(
            min_pages=_env_int(env, "IOS_SETTINGS_MIN_PAGES", 6),
            max_pages=_env_int(env, "IOS_SETTINGS_MAX_PAGES", 12),
            max_depth=_env_int(env, "IOS_SETTINGS_MAX_DEPTH", 2),
            max_scrolls_per_page=max_scrolls,
            root_coverage_mode=root_coverage_mode,
            max_child_scrolls_per_page=_env_int(
                env,
                "IOS_SETTINGS_MAX_CHILD_SCROLLS_PER_PAGE",
                1 if root_coverage_mode else max_scrolls,
            ),
            child_navigation_enabled=_env_bool(
                env,
                "IOS_SETTINGS_CHILD_NAVIGATION_ENABLED",
                default=not root_coverage_mode,
            ),
            strict_child_candidate_audit=_env_bool(
                env,
                "IOS_SETTINGS_STRICT_CHILD_CANDIDATE_AUDIT",
                default=not root_coverage_mode,
            ),
            max_candidates_per_page=_env_int(env, "IOS_SETTINGS_MAX_CANDIDATES_PER_PAGE", 3),
            require_exhaustive=env.get("IOS_SETTINGS_REQUIRE_EXHAUSTIVE") == "1",
            report_path=env.get("IOS_SETTINGS_REPORT"),
            run_id=env.get("IOS_SETTINGS_RUN_ID"),
            trace_actions=env.get("IOS_SETTINGS_TRACE_ACTIONS") == "1",
            save_view_snapshots=env.get("IOS_SETTINGS_SAVE_VIEW_SNAPSHOTS") == "1",
            artifact_dir=env.get("IOS_SETTINGS_ARTIFACT_DIR"),
            memory_dir=env.get("IOS_SETTINGS_MEMORY_DIR") or env.get("GLASSBOX_MEMORY_DIR"),
            memory_reuse=env.get("IOS_SETTINGS_MEMORY_REUSE") == "1",
            page_id_route_enabled=_env_bool(
                env,
                "IOS_SETTINGS_PAGE_ID_ROUTE",
                default=_env_bool(
                    env,
                    "GLASSBOX_SETTINGS_NAVIGATION_PAGE_ID_ROUTE",
                    default=False,
                ),
            ),
        )

    @classmethod
    def for_child_audit(
        cls,
        *,
        max_depth: int,
        max_pages: int,
        max_child_scrolls_per_page: int,
        max_candidates_per_page: int,
        strict_child_candidate_audit: bool,
    ) -> SettingsRunConfig:
        return cls(
            min_pages=0,
            max_pages=max_pages,
            max_depth=max_depth,
            max_scrolls_per_page=max_child_scrolls_per_page,
            root_coverage_mode=True,
            max_child_scrolls_per_page=max_child_scrolls_per_page,
            child_navigation_enabled=True,
            strict_child_candidate_audit=strict_child_candidate_audit,
            max_candidates_per_page=max_candidates_per_page,
            require_exhaustive=False,
            trace_actions=os.environ.get("IOS_SETTINGS_TRACE_ACTIONS") == "1",
            save_view_snapshots=os.environ.get("IOS_SETTINGS_SAVE_VIEW_SNAPSHOTS") == "1",
            artifact_dir=os.environ.get("IOS_SETTINGS_ARTIFACT_DIR"),
        )

    def to_report_config(self) -> dict[str, object]:
        return {
            "min_pages": self.min_pages,
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "max_scrolls_per_page": self.max_scrolls_per_page,
            "root_coverage_mode": self.root_coverage_mode,
            "max_child_scrolls_per_page": self.max_child_scrolls_per_page,
            "child_navigation_enabled": self.child_navigation_enabled,
            "strict_child_candidate_audit": self.strict_child_candidate_audit,
            "max_candidates_per_page": self.max_candidates_per_page,
            "require_exhaustive": self.require_exhaustive,
            "trace_actions": self.trace_actions,
            "save_view_snapshots": self.save_view_snapshots,
            "artifact_dir": self.artifact_dir,
            "memory_dir": self.memory_dir,
            "memory_reuse": self.memory_reuse,
            "page_id_route_enabled": self.page_id_route_enabled,
        }

    def to_walkthrough_globals(self) -> dict[str, object]:
        return {
            "MIN_PAGES_VISITED": self.min_pages,
            "MAX_PAGES_VISITED": self.max_pages,
            "MAX_DEPTH": self.max_depth,
            "MAX_SCROLLS_PER_PAGE": self.max_scrolls_per_page,
            "ROOT_COVERAGE_MODE": self.root_coverage_mode,
            "MAX_CHILD_SCROLLS_PER_PAGE": self.max_child_scrolls_per_page,
            "CHILD_NAVIGATION_ENABLED": self.child_navigation_enabled,
            "STRICT_CHILD_CANDIDATE_AUDIT": self.strict_child_candidate_audit,
            "MAX_CANDIDATES_PER_PAGE": self.max_candidates_per_page,
            "REQUIRE_EXHAUSTIVE": self.require_exhaustive,
            "PAGE_ID_ROUTE_ENABLED": self.page_id_route_enabled,
        }

    def to_walkthrough_runtime_globals(self) -> dict[str, object]:
        values = self.to_walkthrough_globals()
        values.update({
            "REPORT_PATH": self.report_path,
            "RUN_ID": self.run_id,
            "TRACE_ACTIONS": self.trace_actions,
            "SAVE_VIEW_SNAPSHOTS": self.save_view_snapshots,
            "ARTIFACT_DIR": self.artifact_dir,
            "MEMORY_DIR": self.memory_dir,
            "MEMORY_REUSE": self.memory_reuse,
            "PAGE_ID_ROUTE_ENABLED": self.page_id_route_enabled,
        })
        return values

    def to_child_audit_report_config(self) -> dict[str, object]:
        return {
            "max_depth": self.max_depth,
            "max_pages": self.max_pages,
            "max_child_scrolls_per_page": self.max_child_scrolls_per_page,
            "max_candidates_per_page": self.max_candidates_per_page,
            "strict_child_candidate_audit": self.strict_child_candidate_audit,
            "trace_actions": self.trace_actions,
            "save_view_snapshots": self.save_view_snapshots,
            "artifact_dir": self.artifact_dir,
        }


def build_full_run_env(
    report: Path,
    *,
    base_env: Mapping[str, str] | None = None,
    picokvm: bool = True,
    run_id: str | None = None,
    memory_dir: Path | None = None,
    reuse_memory: bool = False,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    env["PYTHONUNBUFFERED"] = "1"
    if picokvm:
        env.setdefault("GLASSBOX_PICOKVM", "1")
    if run_id is not None:
        env["IOS_SETTINGS_RUN_ID"] = run_id
    env["IOS_SETTINGS_REQUIRE_EXHAUSTIVE"] = "1"
    env["IOS_SETTINGS_REPORT"] = str(report)
    env.setdefault("IOS_SETTINGS_MAX_PAGES", "800")
    env.setdefault("IOS_SETTINGS_MAX_DEPTH", "6")
    env.setdefault("IOS_SETTINGS_MAX_SCROLLS_PER_PAGE", "16")
    env.setdefault("GLASSBOX_WHEEL_TICKS_PER_SCROLL", str(DEFAULT_SETTINGS_WHEEL_TICKS_PER_SWIPE))
    env.setdefault("IOS_SETTINGS_WHEEL_TICKS_PER_SWIPE", env["GLASSBOX_WHEEL_TICKS_PER_SCROLL"])
    env.setdefault("IOS_SETTINGS_ROOT_COVERAGE_MODE", "1")
    env.setdefault("IOS_SETTINGS_MAX_CHILD_SCROLLS_PER_PAGE", "1")
    env.setdefault("IOS_SETTINGS_CHILD_NAVIGATION_ENABLED", "0")
    env.setdefault("IOS_SETTINGS_STRICT_CHILD_CANDIDATE_AUDIT", "0")
    env.setdefault("IOS_SETTINGS_MAX_CANDIDATES_PER_PAGE", "0")
    env.setdefault("IOS_SETTINGS_MIN_PAGES", str(len(EXPECTED_ROOT_NAV_TEXT_ZH) + 1))
    env.setdefault("IOS_SETTINGS_TRACE_ACTIONS", "1")
    env.setdefault(
        "IOS_SETTINGS_PAGE_ID_ROUTE",
        env.get("GLASSBOX_SETTINGS_NAVIGATION_PAGE_ID_ROUTE", "0"),
    )
    # Arm the per-recognize() OCR watchdog on the live rig (the only path with
    # the camera-preview hang; see AgentConfig.ocr_timeout). 20s is far above
    # any legitimate full-frame .accurate OCR latency, so it only fires on a
    # real hang. The global default stays 0 (off) for offline callers.
    env.setdefault("GLASSBOX_OCR_TIMEOUT", "20")
    # Enable the VLM (Layer 3) for live cold-start runs. build_phone already
    # creates the SpringBoard icon-map + wires phone.kimi; the only thing gating
    # the springboard's VLM visual icon-grounding fallback (and the row-OCR
    # recovery) is the default-off VLM. It only fires on a deterministic-path
    # miss (icon-tap opened a non-target app / ambiguous row OCR), so cost stays
    # bounded while precision improves. Override with GLASSBOX_ENABLE_VLM=0.
    env.setdefault("GLASSBOX_ENABLE_VLM", "1")
    # Persist the VLM SpringBoard icon map across runs (layout-keyed, multi-device
    # safe). A stable cross-run path — NOT the per-run isolated memory dir — so the
    # VLM icon-naming cost is paid once per Home layout, then reused on cold start.
    env.setdefault(
        "GLASSBOX_SPRINGBOARD_ICON_MAP_PATH",
        str(Path.home() / ".cache" / "glassbox" / "springboard_icon_map.json"),
    )
    env.setdefault(
        "GLASSBOX_VLM_CACHE_DIR",
        str(Path.home() / ".cache" / "glassbox" / "vlm_describe"),
    )
    env.setdefault("GLASSBOX_ENABLE_MEMORY", "1")
    env.setdefault("GLASSBOX_MEMORY_BUNDLE", "com.apple." + "Preferences")
    if not reuse_memory:
        default_memory_dir = memory_dir or (
            report.with_suffix(".artifacts") / (run_id or "manual") / "memory"
        )
        env["GLASSBOX_MEMORY_DIR"] = str(default_memory_dir)
        env["IOS_SETTINGS_MEMORY_REUSE"] = "0"
    elif memory_dir is not None:
        env["GLASSBOX_MEMORY_DIR"] = str(memory_dir)
        env["IOS_SETTINGS_MEMORY_REUSE"] = "1"
    else:
        env.setdefault("IOS_SETTINGS_MEMORY_REUSE", "1")
    if env.get("GLASSBOX_MEMORY_DIR"):
        env["IOS_SETTINGS_MEMORY_DIR"] = env["GLASSBOX_MEMORY_DIR"]
    return env


def _env_bool(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return raw == "1"


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    return int(raw)
