"""Backward-compatible imports for the VLM describe-scene cache."""

from glassbox.obs.vlm_cache import (
    CachedKimi,
    CachedVLM,
    wrap_vlm_cache_if_enabled,
    wrap_with_cache_if_enabled,
)

__all__ = [
    "CachedKimi",
    "CachedVLM",
    "wrap_vlm_cache_if_enabled",
    "wrap_with_cache_if_enabled",
]
