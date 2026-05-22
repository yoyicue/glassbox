"""Disk cache for VLM describe_scene calls.

For replays, re-runs, and scenes where the same screenshot recurs, read
straight from the on-disk cache instead of spending another network call.

Cache key = sha256(frame_image_bytes + request-shape JSON)
Cache value = one complete VLM response JSON.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from glassbox.cognition.contracts import VLMRequest
from glassbox.cognition.vlm_kimi import (
    VLMResponse,
    describe_prompt_cache_key,
    normalize_describe_scene_args,
)


class CachedVLM:
    """Disk cache around any backend's describe_scene."""

    def __init__(self, inner, cache_dir: str | Path):
        self.inner = inner
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"hits": 0, "misses": 0, "writes": 0}
        self.last_hit: bool = False

    @property
    def model(self) -> str:
        return getattr(self.inner, "model", "?")

    def read_text_region(self, *, region_image: bytes) -> str:
        """Row-level OCR fallback — delegated to the wrapped client."""
        return self.inner.read_text_region(region_image=region_image)

    def describe_scene(
        self,
        request: VLMRequest | None = None,
        *,
        frame_image: bytes | None = None,
        elements: list[dict[str, Any]] | None = None,
        scene_hint: str | None = None,
        system_prompt: str | None = None,
        set_of_mark: bool = False,
    ) -> VLMResponse:
        args = normalize_describe_scene_args(
            request,
            frame_image=frame_image,
            elements=elements,
            scene_hint=scene_hint,
            system_prompt=system_prompt,
            set_of_mark=set_of_mark,
        )
        frame_image = args["frame_image"]
        elements = args["elements"]
        scene_hint = args["scene_hint"]
        system_prompt = args["system_prompt"]
        set_of_mark = args["set_of_mark"]
        key = self._key(
            frame_image,
            elements,
            scene_hint,
            system_prompt=system_prompt,
            set_of_mark=set_of_mark,
            model=self.model,
            prompt_cache_key=describe_prompt_cache_key(system_prompt),
        )
        path = self.cache_dir / f"{key}.json"

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"[CachedVLM] ignoring corrupt cache {path}: {e}")
                with contextlib.suppress(OSError):
                    path.unlink()
            else:
                self.stats["hits"] += 1
                self.last_hit = True
                return VLMResponse(
                    raw_content=data.get("raw_content", ""),
                    parsed=data.get("parsed"),
                    usage=data.get("usage", {}),
                    model=data.get("model", self.model),
                    elapsed_ms=data.get("elapsed_ms", 0),
                )

        self.stats["misses"] += 1
        self.last_hit = False
        kwargs = {
            "frame_image": frame_image,
            "elements": elements,
            "scene_hint": scene_hint,
        }
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if set_of_mark:
            kwargs["set_of_mark"] = set_of_mark
        resp = self.inner.describe_scene(**kwargs)
        try:
            tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(
                json.dumps(
                    {
                        "raw_content": resp.raw_content,
                        "parsed": resp.parsed,
                        "usage": resp.usage,
                        "model": resp.model,
                        "elapsed_ms": resp.elapsed_ms,
                        "_meta": {
                            "n_elements": len(elements),
                            "scene_hint": scene_hint,
                            "system_prompt": system_prompt,
                            "prompt_cache_key": describe_prompt_cache_key(system_prompt),
                            "set_of_mark": set_of_mark,
                            "model": self.model,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp_path.replace(path)
            self.stats["writes"] += 1
        except OSError as e:
            print(f"[CachedVLM] failed to write cache {path}: {e}")
            with contextlib.suppress(OSError, UnboundLocalError):
                tmp_path.unlink()
        return resp

    @staticmethod
    def _key(
        frame_image: bytes,
        elements: list[dict[str, Any]],
        scene_hint: str | None,
        *,
        system_prompt: str | None = None,
        set_of_mark: bool = False,
        model: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> str:
        h = hashlib.sha256()
        h.update(frame_image)
        request_shape = {
            "version": 2,
            "elements": elements,
            "scene_hint": scene_hint or "",
            "system_prompt": system_prompt or "",
            "prompt_cache_key": prompt_cache_key or describe_prompt_cache_key(system_prompt),
            "set_of_mark": bool(set_of_mark),
            "model": model or "",
        }
        h.update(
            json.dumps(
                request_shape,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return h.hexdigest()[:24]


def wrap_vlm_cache_if_enabled(
    client,
    *,
    enabled: bool | None = None,
    cache_dir: str | Path | None = None,
):
    """Wrap the client in a CachedVLM layer when configured.

    `enabled=None` keeps the legacy behavior where a configured cache directory
    turns caching on. Runtime assembly should pass AgentConfig fields
    explicitly so callers do not need to monkeypatch environment variables.
    """
    if enabled is False:
        return client
    cache_dir = cache_dir or os.environ.get("GLASSBOX_VLM_CACHE_DIR") or os.environ.get(
        "GLASSBOX_KIMI_CACHE_DIR"
    )
    if enabled is True and not cache_dir:
        return client
    if not cache_dir:
        return client
    return CachedVLM(client, cache_dir=cache_dir)


CachedKimi = CachedVLM
wrap_with_cache_if_enabled = wrap_vlm_cache_if_enabled


__all__ = [
    "CachedKimi",
    "CachedVLM",
    "wrap_vlm_cache_if_enabled",
    "wrap_with_cache_if_enabled",
]
