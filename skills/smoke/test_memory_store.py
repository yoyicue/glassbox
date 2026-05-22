"""skills/smoke/test_memory_store.py

Phase c — UTG disk persistence + env-gated factory. Fully offline.

Coverage:
  - save_utg → load_utg round-trips nodes and edges
  - a missing file → a fresh empty UTG (cold start, no crash)
  - an app-version mismatch cold-starts rather than trusting a stale graph
  - wrap_with_memory_if_enabled respects GLASSBOX_ENABLE_MEMORY and bundle_id
"""

from __future__ import annotations

import json

import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.memory import (
    UTG,
    ScreenMemory,
    load_utg,
    save_utg,
    wrap_with_memory_if_enabled,
)
from glassbox.memory.schema import UTG_RUNTIME_COMPAT


def _scene(*texts):
    els = [UIElement(type="button", box=Box(x=i * 10, y=i * 10, w=80, h=30),
                     text=t, confidence=0.9, element_id=i) for i, t in enumerate(texts)]
    return Scene(frame_id=0, timestamp=0.0, elements=els)


def _populated_utg(bundle_id="com.x", app_version="1.0") -> UTG:
    mem = ScreenMemory(UTG(bundle_id=bundle_id, app_version=app_version))
    mem.observe(_scene("登录", "密码", "忘记密码"))
    mem.observe(_scene("设置", "隐私", "关于"), last_action=("tap", {"target": "设置"}))
    return mem.utg


@pytest.mark.smoke
def test_save_load_roundtrip(tmp_path):
    utg = _populated_utg()
    save_utg(utg, memory_dir=tmp_path)
    assert list(tmp_path.glob("*.tmp")) == []
    loaded = load_utg("com.x", memory_dir=tmp_path)
    assert loaded.bundle_id == "com.x"
    assert set(loaded.nodes) == set(utg.nodes)
    assert len(loaded.edges) == len(utg.edges) == 1
    assert loaded.edges[0].element_key == "text:设置"
    assert loaded.edges[0].action_kwargs == {"target": "设置"}
    assert loaded.edges[0].success_count == 1
    assert loaded.edges[0].no_progress_count == 0
    assert loaded.edges[0].success_rate == 1.0
    assert loaded.schema_version >= 2
    assert loaded.runtime_compat


@pytest.mark.smoke
def test_load_missing_file_is_fresh(tmp_path):
    utg = load_utg("com.never.saved", memory_dir=tmp_path)
    assert utg.bundle_id == "com.never.saved"
    assert not utg.nodes and not utg.edges


@pytest.mark.smoke
def test_version_mismatch_cold_starts(tmp_path):
    save_utg(_populated_utg(app_version="1.0"), memory_dir=tmp_path)
    fresh = load_utg("com.x", app_version="2.0", memory_dir=tmp_path)
    assert not fresh.nodes                       # stale graph discarded
    # same version → kept
    kept = load_utg("com.x", app_version="1.0", memory_dir=tmp_path)
    assert kept.nodes


@pytest.mark.smoke
def test_load_incompatible_schema_cold_starts(tmp_path):
    path = tmp_path / "com.x.json"
    path.write_text(json.dumps({
        "schema_version": 999,
        "bundle_id": "com.x",
        "nodes": {"stale": {"screen_id": "stale"}},
        "edges": [],
    }), encoding="utf-8")

    loaded = load_utg("com.x", memory_dir=tmp_path)

    assert loaded.bundle_id == "com.x"
    assert loaded.nodes == {}


@pytest.mark.smoke
def test_schema_less_legacy_utg_cold_starts_without_backfilled_compat(tmp_path):
    path = tmp_path / "com.x.json"
    path.write_text(json.dumps({
        "bundle_id": "com.x",
        "nodes": {"LegacyViewController": {"screen_id": "LegacyViewController"}},
        "edges": [{"from_id": "LegacyViewController", "to_id": "LegacyViewController"}],
    }), encoding="utf-8")

    loaded = load_utg("com.x", memory_dir=tmp_path)

    assert loaded.bundle_id == "com.x"
    assert loaded.nodes == {}


@pytest.mark.smoke
def test_current_schema_missing_runtime_compat_cold_starts(tmp_path):
    path = tmp_path / "com.x.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "bundle_id": "com.x",
        "nodes": {"scr_1": {"screen_id": "scr_1"}},
        "edges": [],
    }), encoding="utf-8")

    loaded = load_utg("com.x", memory_dir=tmp_path)

    assert loaded.nodes == {}


@pytest.mark.smoke
def test_current_schema_partial_runtime_compat_cold_starts(tmp_path):
    path = tmp_path / "com.x.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "runtime_compat": {"action_identity": UTG_RUNTIME_COMPAT["action_identity"]},
        "bundle_id": "com.x",
        "nodes": {"scr_1": {"screen_id": "scr_1"}},
        "edges": [],
    }), encoding="utf-8")

    loaded = load_utg("com.x", memory_dir=tmp_path)

    assert loaded.nodes == {}


@pytest.mark.smoke
def test_wrap_respects_env_and_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("GLASSBOX_ENABLE_MEMORY", raising=False)
    assert wrap_with_memory_if_enabled(bundle_id="com.x") is None

    monkeypatch.setenv("GLASSBOX_ENABLE_MEMORY", "1")
    assert wrap_with_memory_if_enabled(bundle_id=None) is None      # no app → no memory
    mem = wrap_with_memory_if_enabled(bundle_id="com.x", memory_dir=str(tmp_path))
    assert isinstance(mem, ScreenMemory)


@pytest.mark.smoke
def test_wrap_accepts_explicit_enabled_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GLASSBOX_ENABLE_MEMORY", raising=False)

    mem = wrap_with_memory_if_enabled(
        bundle_id="com.x",
        enabled=True,
        memory_dir=str(tmp_path),
    )

    assert isinstance(mem, ScreenMemory)


@pytest.mark.smoke
def test_wrap_explicit_disabled_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GLASSBOX_ENABLE_MEMORY", "1")

    assert wrap_with_memory_if_enabled(
        bundle_id="com.x",
        enabled=False,
        memory_dir=str(tmp_path),
    ) is None


@pytest.mark.smoke
@pytest.mark.parametrize("value", ["0", "false", "False", "off", "no"])
def test_wrap_treats_false_env_values_as_disabled(tmp_path, monkeypatch, value):
    monkeypatch.setenv("GLASSBOX_ENABLE_MEMORY", value)

    assert wrap_with_memory_if_enabled(bundle_id="com.x", memory_dir=str(tmp_path)) is None


@pytest.mark.smoke
def test_fixture_memory_teardown_saves_to_configured_dir(tmp_path):
    from skills.conftest import _save_memory_utg

    mem = ScreenMemory(UTG(bundle_id="com.fixture"))
    mem.observe(_scene("首页"))

    _save_memory_utg(mem, memory_dir=str(tmp_path))

    assert (tmp_path / "com.fixture.json").exists()
