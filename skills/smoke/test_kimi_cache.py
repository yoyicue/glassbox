"""skills/smoke/test_kimi_cache.py

Unit tests for the VLM describe-scene cache. Fully offline; FakeInner counts
how often it is called.

Coverage:
  - first call is a miss (calls inner + writes to disk)
  - a second call with the same frame+elements+hint is a hit (does not call inner)
  - different image / different elements / different hint → different key
  - a cross-instance hit (same cache_dir) also hits
  - the rehydrated VLMResponse has complete fields
  - wrap_with_cache_if_enabled checks the env
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from glassbox.cognition import Box, UIElement, VLMRequest
from glassbox.cognition.vlm_kimi import VLMResponse, describe_prompt_cache_key
from glassbox.obs import (
    CachedKimi,
    CachedVLM,
    wrap_vlm_cache_if_enabled,
    wrap_with_cache_if_enabled,
)
from glassbox.perception.source import Frame


# ─── counting inner ──────────────────────────────────────────────────
@dataclass
class FakeInner:
    """Implements the describe_scene protocol; records every call."""

    response: VLMResponse
    calls: int = 0
    model: str = "fake"
    last_kwargs: dict[str, Any] | None = None

    def describe_scene(
        self,
        *,
        frame_image,
        elements,
        scene_hint=None,
        system_prompt=None,
        set_of_mark=False,
    ):
        self.calls += 1
        self.last_kwargs = {
            "frame_image": frame_image,
            "elements": elements,
            "scene_hint": scene_hint,
            "system_prompt": system_prompt,
            "set_of_mark": set_of_mark,
        }
        return self.response


def _resp(intent_label: str = "确认登录") -> VLMResponse:
    return VLMResponse(
        raw_content=f'{{"scene_type":"login_form","elements":[{{"id":0,"intent_label":"{intent_label}"}}]}}',
        parsed={"scene_type": "login_form",
                "elements": [{"id": 0, "intent_label": intent_label}]},
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        model="fake",
        elapsed_ms=42,
    )


# ─── basic miss / hit ────────────────────────────────────────────────
@pytest.mark.smoke
def test_first_call_is_miss_then_writes(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedVLM(inner, cache_dir=tmp_path)

    r = cached.describe_scene(
        frame_image=b"<png>",
        elements=[{"id": 0, "text": "登录", "type": "button"}],
    )
    assert inner.calls == 1
    assert cached.stats == {"hits": 0, "misses": 1, "writes": 1}
    assert r.parsed["scene_type"] == "login_form"
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


@pytest.mark.smoke
def test_cached_kimi_is_legacy_alias():
    assert CachedKimi is CachedVLM
    assert wrap_with_cache_if_enabled is wrap_vlm_cache_if_enabled


@pytest.mark.smoke
def test_second_call_with_same_input_hits(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    payload = {
        "frame_image": b"<png>",
        "elements": [{"id": 0, "text": "登录", "type": "button"}],
        "scene_hint": "登录走查",
    }
    cached.describe_scene(**payload)
    cached.describe_scene(**payload)   # this one should hit the cache
    assert inner.calls == 1
    assert cached.stats == {"hits": 1, "misses": 1, "writes": 1}


@pytest.mark.smoke
def test_vlm_request_is_normalized_for_cache_and_inner_call(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    request = VLMRequest(
        image=Frame(img=np.zeros((10, 10, 3), dtype=np.uint8), ts=1.0),
        elements=[
            UIElement(
                type="text",
                box=Box(x=1, y=2, w=3, h=4),
                text="登录",
                confidence=0.9,
                element_id=7,
            )
        ],
        scene_hint="登录走查",
        system_prompt="prompt",
        set_of_mark=True,
    )

    cached.describe_scene(request)

    assert inner.calls == 1
    assert inner.last_kwargs["frame_image"].startswith(b"\x89PNG")
    assert inner.last_kwargs["elements"] == [
        {"id": 7, "text": "登录", "type": "text", "box": [1, 2, 4, 6]},
    ]
    assert inner.last_kwargs["scene_hint"] == "登录走查"
    assert inner.last_kwargs["system_prompt"] == "prompt"
    assert inner.last_kwargs["set_of_mark"] is True


@pytest.mark.smoke
def test_different_image_misses(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    cached.describe_scene(frame_image=b"A", elements=[], scene_hint=None)
    cached.describe_scene(frame_image=b"B", elements=[], scene_hint=None)
    assert inner.calls == 2
    assert cached.stats["misses"] == 2


@pytest.mark.smoke
def test_different_elements_misses(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    cached.describe_scene(frame_image=b"x", elements=[{"id": 0}], scene_hint=None)
    cached.describe_scene(frame_image=b"x", elements=[{"id": 1}], scene_hint=None)
    assert inner.calls == 2


@pytest.mark.smoke
def test_different_hint_misses(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    cached.describe_scene(frame_image=b"x", elements=[], scene_hint="A")
    cached.describe_scene(frame_image=b"x", elements=[], scene_hint="B")
    assert inner.calls == 2


@pytest.mark.smoke
def test_prompt_and_set_of_mark_are_forwarded_and_keyed(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    payload = {"frame_image": b"x", "elements": [], "scene_hint": "hint"}

    cached.describe_scene(**payload, system_prompt="prompt A", set_of_mark=True)
    cached.describe_scene(**payload, system_prompt="prompt B", set_of_mark=True)
    cached.describe_scene(**payload, system_prompt="prompt A", set_of_mark=True)

    assert inner.calls == 2
    assert cached.stats == {"hits": 1, "misses": 2, "writes": 2}
    assert inner.last_kwargs["system_prompt"] == "prompt B"
    assert inner.last_kwargs["set_of_mark"] is True


@pytest.mark.smoke
def test_model_is_part_of_cache_key(tmp_path):
    inner1 = FakeInner(response=_resp(), model="fake-1")
    inner2 = FakeInner(response=_resp("model 2"), model="fake-2")
    c1 = CachedKimi(inner1, cache_dir=tmp_path)
    c2 = CachedKimi(inner2, cache_dir=tmp_path)
    payload = {"frame_image": b"x", "elements": [], "scene_hint": None}

    c1.describe_scene(**payload)
    r2 = c2.describe_scene(**payload)

    assert inner1.calls == 1
    assert inner2.calls == 1
    assert r2.parsed["elements"][0]["intent_label"] == "model 2"


@pytest.mark.smoke
def test_default_describe_prompt_version_is_part_of_cache_key():
    base = {
        "frame_image": b"x",
        "elements": [],
        "scene_hint": None,
        "model": "fake",
    }

    current = CachedKimi._key(**base)
    future = CachedKimi._key(
        **base,
        prompt_cache_key=describe_prompt_cache_key("future default prompt"),
    )

    assert current != future


@pytest.mark.smoke
def test_element_order_does_not_affect_key(tmp_path):
    """The JSON is sorted before hashing, so key order should not matter."""
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    cached.describe_scene(
        frame_image=b"x",
        elements=[{"a": 1, "b": 2}],
        scene_hint=None,
    )
    cached.describe_scene(
        frame_image=b"x",
        elements=[{"b": 2, "a": 1}],   # fields out of order
        scene_hint=None,
    )
    assert inner.calls == 1


@pytest.mark.smoke
def test_cross_instance_hit_same_cache_dir(tmp_path):
    """Two CachedKimi instances sharing a cache_dir should hit each other's entries."""
    inner1 = FakeInner(response=_resp())
    inner2 = FakeInner(response=_resp("不该被调"))
    c1 = CachedKimi(inner1, cache_dir=tmp_path)
    c2 = CachedKimi(inner2, cache_dir=tmp_path)

    c1.describe_scene(frame_image=b"x", elements=[], scene_hint=None)
    r2 = c2.describe_scene(frame_image=b"x", elements=[], scene_hint=None)
    assert inner1.calls == 1
    assert inner2.calls == 0
    # the rehydrated value is the one c1 wrote
    assert r2.parsed["elements"][0]["intent_label"] == "确认登录"


@pytest.mark.smoke
def test_rehydrated_response_full_fields(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)
    cached.describe_scene(frame_image=b"x", elements=[], scene_hint=None)

    # a new instance reads from disk
    inner2 = FakeInner(response=_resp("不该调"))
    cached2 = CachedKimi(inner2, cache_dir=tmp_path)
    r = cached2.describe_scene(frame_image=b"x", elements=[], scene_hint=None)
    assert r.usage == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    assert r.elapsed_ms == 42
    assert r.model == "fake"
    assert r.raw_content.startswith("{")


@pytest.mark.smoke
def test_corrupt_cache_file_is_treated_as_miss(tmp_path):
    payload = {
        "frame_image": b"bad-cache",
        "elements": [{"id": 0}],
        "scene_hint": "hint",
    }
    inner = FakeInner(response=_resp())
    key = CachedKimi._key(
        payload["frame_image"],
        payload["elements"],
        payload["scene_hint"],
        model=inner.model,
    )
    (tmp_path / f"{key}.json").write_text("{not-json", encoding="utf-8")
    cached = CachedKimi(inner, cache_dir=tmp_path)

    r = cached.describe_scene(**payload)

    assert inner.calls == 1
    assert cached.stats == {"hits": 0, "misses": 1, "writes": 1}
    assert r.parsed["scene_type"] == "login_form"
    assert (tmp_path / f"{key}.json").read_text(encoding="utf-8").startswith("{")


@pytest.mark.smoke
def test_cache_write_leaves_no_temp_files_on_success(tmp_path):
    inner = FakeInner(response=_resp())
    cached = CachedKimi(inner, cache_dir=tmp_path)

    cached.describe_scene(frame_image=b"x", elements=[], scene_hint=None)

    assert list(tmp_path.glob("*.tmp")) == []
    assert len(list(tmp_path.glob("*.json"))) == 1


# ─── wrap_with_cache_if_enabled ──────────────────────────────────────
@pytest.mark.smoke
def test_wrap_returns_inner_when_no_env(monkeypatch):
    monkeypatch.delenv("GLASSBOX_VLM_CACHE_DIR", raising=False)
    monkeypatch.delenv("GLASSBOX_KIMI_CACHE_DIR", raising=False)
    inner = FakeInner(response=_resp())
    out = wrap_vlm_cache_if_enabled(inner)
    assert out is inner   # passes straight through


@pytest.mark.smoke
def test_wrap_wraps_when_neutral_env_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GLASSBOX_VLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("GLASSBOX_KIMI_CACHE_DIR", str(tmp_path / "legacy"))
    inner = FakeInner(response=_resp())
    out = wrap_vlm_cache_if_enabled(inner)
    assert isinstance(out, CachedVLM)
    assert out.cache_dir == tmp_path


@pytest.mark.smoke
def test_wrap_wraps_when_legacy_env_set(monkeypatch, tmp_path):
    monkeypatch.delenv("GLASSBOX_VLM_CACHE_DIR", raising=False)
    monkeypatch.setenv("GLASSBOX_KIMI_CACHE_DIR", str(tmp_path))
    inner = FakeInner(response=_resp())
    out = wrap_vlm_cache_if_enabled(inner)
    assert isinstance(out, CachedVLM)
    assert out.cache_dir == tmp_path


@pytest.mark.smoke
def test_wrap_with_explicit_cache_dir(tmp_path):
    """Passing cache_dir explicitly does not depend on the env."""
    inner = FakeInner(response=_resp())
    out = wrap_vlm_cache_if_enabled(inner, cache_dir=tmp_path)
    assert isinstance(out, CachedVLM)


@pytest.mark.smoke
def test_wrap_explicit_disabled_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GLASSBOX_KIMI_CACHE_DIR", str(tmp_path))
    inner = FakeInner(response=_resp())

    out = wrap_vlm_cache_if_enabled(inner, enabled=False)

    assert out is inner


@pytest.mark.smoke
def test_wrap_explicit_enabled_uses_explicit_cache_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GLASSBOX_VLM_CACHE_DIR", raising=False)
    monkeypatch.delenv("GLASSBOX_KIMI_CACHE_DIR", raising=False)
    inner = FakeInner(response=_resp())

    out = wrap_vlm_cache_if_enabled(inner, enabled=True, cache_dir=tmp_path)

    assert isinstance(out, CachedVLM)
