from __future__ import annotations

import time

import numpy as np
import pytest

from glassbox.obs.stream import ObservationBuffer
from glassbox.perception.source import Frame


def _frame(ts: float) -> Frame:
    return Frame(img=np.zeros((2, 2, 3), dtype=np.uint8), ts=ts)


@pytest.mark.smoke
def test_observation_buffer_selects_nearest_frame_at_or_before_timestamp():
    buffer = ObservationBuffer(min_retention_ms=10000, min_retention_frames=10)
    buffer.append(_frame(1.0))
    buffer.append(_frame(2.0))
    buffer.append(_frame(3.0))

    assert buffer.nearest_at_or_before(2.5).frame.ts == 2.0
    assert buffer.nearest_at_or_before(0.5).frame.ts == 1.0
    assert buffer.latest().frame.ts == 3.0


@pytest.mark.smoke
def test_observation_buffer_retains_minimum_frame_count():
    buffer = ObservationBuffer(min_retention_ms=1, min_retention_frames=2)
    buffer.append(_frame(1.0))
    time.sleep(0.002)
    buffer.append(_frame(2.0))
    time.sleep(0.002)
    buffer.append(_frame(3.0))

    retained = buffer.snapshot()
    assert len(retained) == 2
    assert [item.frame.ts for item in retained] == [2.0, 3.0]
