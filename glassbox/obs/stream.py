"""In-process observation buffer for computer-use runtime."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from glassbox.perception.source import Frame


@dataclass(frozen=True)
class BufferedFrame:
    frame: Frame
    captured_at: float
    source: str


class ObservationBuffer:
    """Small monotonic-time ring buffer of raw frames.

    This is not the ledger. Frames in this buffer are volatile until the
    orchestrator promotes them into ArtifactStore, at which point `frame.captured`
    is written to audit.
    """

    def __init__(
        self,
        *,
        min_retention_ms: int = 10000,
        min_retention_frames: int = 120,
    ):
        self.min_retention_ms = int(min_retention_ms)
        self.min_retention_frames = int(min_retention_frames)
        self._frames: deque[BufferedFrame] = deque()

    def append(self, frame: Frame, *, source: str = "phone.snapshot") -> BufferedFrame:
        item = BufferedFrame(frame=frame, captured_at=time.monotonic(), source=source)
        self._frames.append(item)
        self._prune()
        return item

    def latest(self) -> BufferedFrame | None:
        return self._frames[-1] if self._frames else None

    def nearest_at_or_before(self, ts: float) -> BufferedFrame | None:
        candidate = None
        for item in self._frames:
            if item.frame.ts <= ts:
                candidate = item
            else:
                break
        return candidate or (self._frames[0] if self._frames else None)

    def snapshot(self) -> list[BufferedFrame]:
        return list(self._frames)

    def _prune(self) -> None:
        if not self._frames:
            return
        cutoff = time.monotonic() - self.min_retention_ms / 1000.0
        while (
            len(self._frames) > self.min_retention_frames
            and self._frames[0].captured_at < cutoff
        ):
            self._frames.popleft()
