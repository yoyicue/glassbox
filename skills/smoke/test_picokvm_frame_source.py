from __future__ import annotations

import numpy as np
import pytest

from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.perception.picokvm_source import PicoKVMFrameSource


class FakeCapture:
    def __init__(self, reads):
        self.reads = list(reads)
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        if self.reads:
            return self.reads.pop(0)
        return False, None

    def release(self):
        self.released = True


@pytest.mark.smoke
def test_picokvm_frame_source_reopens_after_empty_read():
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    captures = [
        FakeCapture([(False, None)]),
        FakeCapture([(True, frame)]),
    ]
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")
    source = PicoKVMFrameSource(config=cfg, capture_factory=lambda _url: captures.pop(0))

    result = source.snapshot()

    assert result.img is frame


@pytest.mark.smoke
def test_picokvm_frame_source_fresh_snapshot_reopens_stream():
    stale = np.zeros((4, 6, 3), dtype=np.uint8)
    fresh = np.full((4, 6, 3), 200, dtype=np.uint8)
    captures = [
        FakeCapture([(True, stale)]),
        FakeCapture([(True, fresh)]),
    ]
    created = []
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")

    def factory(_url):
        cap = captures.pop(0)
        created.append(cap)
        return cap

    source = PicoKVMFrameSource(config=cfg, capture_factory=factory)

    first = source.snapshot()
    second = source.fresh_snapshot()

    assert first.img is stale
    assert second.img is fresh
    assert created[0].released is True
    assert created[1].released is False
