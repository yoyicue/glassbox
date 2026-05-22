"""glassbox/memory/store.py — UTG disk persistence (one JSON per app).

Mirrors the JSON-per-file + env-gated-factory pattern of glassbox/obs/kimi_cache.py.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path

from glassbox.memory.graph import ScreenMemory
from glassbox.memory.schema import UTG, UTG_RUNTIME_COMPAT, UTG_SCHEMA_VERSION

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "memory" / "utg"
_TRUE_ENV_VALUES = {"1", "true", "t", "yes", "y", "on"}


def utg_path(bundle_id: str, memory_dir: str | Path | None = None) -> Path:
    base = Path(memory_dir) if memory_dir else _DEFAULT_DIR
    return base / f"{bundle_id}.json"


def load_utg(
    bundle_id: str,
    *,
    app_version: str | None = None,
    memory_dir: str | Path | None = None,
) -> UTG:
    """Load an app's UTG, or a fresh empty one. A version mismatch (app
    updated → screens changed) cold-starts rather than trusting a stale graph."""
    path = utg_path(bundle_id, memory_dir)
    if not path.exists():
        return UTG(bundle_id=bundle_id, app_version=app_version)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("UTG root is not an object")
        payload = _migrate_payload(payload)
        schema_version = int(payload.get("schema_version", 0) or 0)
        if schema_version != UTG_SCHEMA_VERSION:
            print(
                f"[memory] {bundle_id} UTG schema v{schema_version}, "
                f"want v{UTG_SCHEMA_VERSION} — cold start"
            )
            return UTG(bundle_id=bundle_id, app_version=app_version)
        runtime_compat = payload.get("runtime_compat") or {}
        if not _runtime_compat_ok(runtime_compat):
            print(f"[memory] {bundle_id} UTG runtime compatibility changed — cold start")
            return UTG(bundle_id=bundle_id, app_version=app_version)
        payload["runtime_compat"] = dict(UTG_RUNTIME_COMPAT)
        utg = UTG.model_validate(payload)
    except Exception as e:                       # corrupt file → don't crash the run
        print(f"[memory] failed to load {path}: {e} — cold start")
        return UTG(bundle_id=bundle_id, app_version=app_version)
    if app_version is not None and utg.app_version not in (None, app_version):
        print(f"[memory] {bundle_id} UTG is v{utg.app_version}, want v{app_version} — cold start")
        return UTG(bundle_id=bundle_id, app_version=app_version)
    return utg


def _migrate_payload(payload: dict) -> dict:
    if "schema_version" not in payload:
        return payload
    version = int(payload.get("schema_version", 0) or 0)
    if version >= UTG_SCHEMA_VERSION:
        return payload
    if version != 1:
        return payload
    migrated = dict(payload)
    migrated["schema_version"] = UTG_SCHEMA_VERSION
    migrated["runtime_compat"] = dict(UTG_RUNTIME_COMPAT)
    for edge in migrated.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        action_kwargs = edge.get("action_kwargs")
        if isinstance(action_kwargs, dict) and action_kwargs.get("coordinate_space") == "phone":
            action_kwargs = dict(action_kwargs)
            action_kwargs["coordinate_space"] = "frame_px"
            edge["action_kwargs"] = action_kwargs
        action = edge.get("action")
        if isinstance(action, dict) and action.get("coordinate_space") == "phone":
            action = dict(action)
            action["coordinate_space"] = "frame_px"
            edge["action"] = action
    return migrated


def _runtime_compat_ok(value: dict) -> bool:
    if not value:
        return False
    for key, expected in UTG_RUNTIME_COMPAT.items():
        actual = value.get(key)
        if actual != expected:
            return False
    return True


def save_utg(utg: UTG, *, memory_dir: str | Path | None = None) -> None:
    path = utg_path(utg.bundle_id, memory_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(utg.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError as e:
        print(f"[memory] failed to save {path}: {e}")
        with contextlib.suppress(OSError, UnboundLocalError):
            tmp_path.unlink()


def wrap_with_memory_if_enabled(
    *,
    bundle_id: str | None,
    app_version: str | None = None,
    enabled: bool | None = None,
    memory_dir: str | Path | None = None,
) -> ScreenMemory | None:
    """A ScreenMemory over the app's stored UTG when memory is enabled.

    `enabled=None` keeps the legacy env-gated behavior. Runtime assembly should
    pass AgentConfig fields explicitly so tests and scripts do not depend on
    process-global environment reads.
    """
    if enabled is None:
        enabled = (os.environ.get("GLASSBOX_ENABLE_MEMORY") or "").strip().lower() in _TRUE_ENV_VALUES
    if not enabled or not bundle_id:
        return None
    memory_dir = memory_dir or os.environ.get("GLASSBOX_MEMORY_DIR")
    utg = load_utg(bundle_id, app_version=app_version, memory_dir=memory_dir)
    return ScreenMemory(utg)
