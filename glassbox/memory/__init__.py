"""glassbox.memory — UI Transition Graph / screen memory.

The agent's *learned* memory of an app: which screens it has seen and where
their elements are. Complements glassbox/profile.py (the static factory prior).
Optional layer — env-gated by GLASSBOX_ENABLE_MEMORY, off by default.

See docs/design/screen_memory.md.
"""

from glassbox.memory.graph import ScreenMemory
from glassbox.memory.recording import build_from_recording
from glassbox.memory.schema import (
    UTG,
    ActionRecord,
    RememberedElement,
    ScreenEdge,
    ScreenNode,
    ScreenSignature,
)
from glassbox.memory.signature import compute_signature, dhash, similarity
from glassbox.memory.store import (
    load_utg,
    save_utg,
    utg_path,
    wrap_with_memory_if_enabled,
)

__all__ = [
    "UTG",
    "ActionRecord",
    "RememberedElement",
    "ScreenEdge",
    "ScreenMemory",
    "ScreenNode",
    "ScreenSignature",
    "build_from_recording",
    "compute_signature",
    "dhash",
    "load_utg",
    "save_utg",
    "similarity",
    "utg_path",
    "wrap_with_memory_if_enabled",
]
