"""Sequential FrameSource over a committed obs/recorder run (Tier B replay).

Feeds recorded PNGs back through the real perception stack so the offline
suite can assert that ``Perceptor.perceive()`` still reconstructs the recorded
``Scene`` within tolerance (``glassbox/perception/replay_assert.py``). Design:
``docs/design/log_sim_replay_regression.md`` §5.

This is the *on-rails* accessor: ``snapshot()``/``advance()`` walk the
recording's snapshot events in order, mirroring ``StaticFrameSource``
(``static.py``) — at the end it stays clamped on the last frame. It is NOT the
UTG sim's node-indexed random-access accessor (that design names
``UTGFrameAccessor`` to avoid collision).
"""

from __future__ import annotations

from pathlib import Path

from glassbox.memory.recording import _load_frame_img, _scene_from_event, _snapshot_frames
from glassbox.obs.recorder import iter_events
from glassbox.perception.source import Frame, FrameContext


class RecordingFrameSource:
    """FrameSource (boundaries.py Protocol) over a recorded run directory.

    Pairs each recorded observe-``Scene`` with its frame via the recorder's
    ``snapshot_seq`` link, exposed as :attr:`scene_by_seq` for the replay
    asserter. Snapshot events without a saved frame (failed grabs,
    ``save_frames=False``) are skipped — ``_snapshot_frames`` already filters
    them, and the walk order is built from the frames actually present. A
    scene recorded before any snapshot carries ``snapshot_seq=-1`` and is
    excluded. When several observe scenes share one snapshot (perceive-cache
    hits are recorded too), the last one wins — deliberately: it is the scene
    the run acted on.
    """

    coordinate_space = "frame_px"  # matches PicoKVM/AVF raw frames

    def __init__(self, run_dir: Path | str, *, fps: float = 60.0):
        run_dir = Path(run_dir)
        events = list(iter_events(run_dir))
        self._frames = _snapshot_frames(run_dir, events)  # {snapshot seq -> png Path}
        self._order = sorted(self._frames)
        if not self._order:
            raise ValueError(f"recording at {run_dir} has no snapshot frames")
        self.scene_by_seq = {
            ev["snapshot_seq"]: _scene_from_event(ev)
            for ev in events
            if ev.get("type") == "scene"
            and ev.get("scene_event") == "observe"
            and ev.get("snapshot_seq", -1) in self._frames
        }
        self._i = 0
        self._fps = fps

    # —— FrameSource Protocol ──────────────────────────────────────
    def snapshot(self) -> Frame:
        seq = self.current_seq
        img = _load_frame_img(self._frames[seq])
        if img is None:
            raise RuntimeError(f"failed to load frame png for snapshot seq {seq}")
        # Deterministic ts (unlike StaticFrameSource's time.monotonic()):
        # replay must be reproducible run-to-run.
        return Frame(img=img, ts=self._i / self._fps, context=FrameContext())

    def close(self) -> None:
        self._frames = {}
        self._order = []

    @property
    def resolution(self) -> tuple[int, int]:
        return self.snapshot().shape

    @property
    def fps(self) -> float:
        return self._fps

    # —— replay extras (duck-typed, like StaticFrameSource) ───────
    def fresh_snapshot(self) -> Frame:
        # No live device to re-grab from; "fresh" is the current frame. Does
        # NOT advance, so runtime's one-time post-connect freshen is harmless.
        return self.snapshot()

    def advance(self) -> bool:
        """Move to the next recorded snapshot. Mirrors StaticFrameSource:
        returns False (and stays on the last frame) at the end."""
        if self._i + 1 < len(self._order):
            self._i += 1
            return True
        return False

    def reset(self) -> None:
        self._i = 0

    @property
    def current_seq(self) -> int:
        """Snapshot seq of the frame snapshot() currently returns."""
        return self._order[min(self._i, len(self._order) - 1)]
