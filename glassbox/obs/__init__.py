"""glassbox.obs — observability (recording / replay / caching)

recorder  — recording of the frame + scene + action + verdict streams
replay    — replay from a recording later (M5+)
vlm_cache — disk cache for VLM calls (M5b)
"""

from glassbox.obs.recorder import Event, Recorder, open_recorder
from glassbox.obs.replay import Replay, ReplaySummary
from glassbox.obs.vlm_cache import (
    CachedKimi,
    CachedVLM,
    wrap_vlm_cache_if_enabled,
    wrap_with_cache_if_enabled,
)

__all__ = [
    "CachedKimi",
    "CachedVLM",
    "Event",
    "Recorder",
    "Replay",
    "ReplaySummary",
    "open_recorder",
    "wrap_vlm_cache_if_enabled",
    "wrap_with_cache_if_enabled",
]
