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


def _decoded(seed: int) -> np.ndarray:
    """A frame with real spatial variance (passes _frame_looks_decoded)."""
    return (np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3) + seed).astype(np.uint8)


def _flat() -> np.ndarray:
    """A degenerate near-zero-variance frame (a partial/garbled H.264 decode)."""
    return np.zeros((4, 6, 3), dtype=np.uint8)


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
    stale = _decoded(10)
    warm_a, warm_b, fresh = _decoded(20), _decoded(30), _decoded(40)
    captures = [
        FakeCapture([(True, stale)]),
        # 2 warmup frames are discarded, then the first decoded frame returned.
        FakeCapture([(True, warm_a), (True, warm_b), (True, fresh)]),
    ]
    created = []
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")

    def factory(_url):
        cap = captures.pop(0)
        created.append(cap)
        return cap

    source = PicoKVMFrameSource(config=cfg, capture_factory=factory, fresh_warmup_frames=2)

    first = source.snapshot()
    second = source.fresh_snapshot()

    assert first.img is stale
    assert second.img is fresh
    assert created[0].released is True
    assert created[1].released is False


@pytest.mark.smoke
def test_fresh_snapshot_skips_degenerate_frames_after_warmup():
    """A partial/garbled (flat) decode after warmup is skipped for a real frame."""
    good = _decoded(50)
    captures = [
        FakeCapture(
            [(True, _flat()), (True, _flat()), (True, _flat()), (True, good)]
        ),
    ]
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")
    source = PicoKVMFrameSource(
        config=cfg, capture_factory=lambda _u: captures.pop(0), fresh_warmup_frames=2
    )

    result = source.fresh_snapshot()

    assert result.img is good


@pytest.mark.smoke
def test_fresh_snapshot_falls_back_to_snapshot_when_settle_budget_exhausted():
    """If no clean frame appears in the settle budget, defer to snapshot() retry
    rather than returning a garbled frame."""
    recovered = _decoded(60)
    captures = [
        # fresh_snapshot's reopen: warmup eats 2, settle reads 4 flats and
        # rejects all -> budget exhausted with no clean frame.
        FakeCapture([(True, _flat())] * 6),
        # snapshot()'s reopen-on-empty-read path then yields a real frame.
        FakeCapture([(True, recovered)]),
    ]
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")
    source = PicoKVMFrameSource(
        config=cfg,
        capture_factory=lambda _u: captures.pop(0),
        fresh_warmup_frames=2,
        fresh_settle_reads=4,
    )

    result = source.fresh_snapshot()

    # fresh_snapshot never returned a garbled frame; it deferred to snapshot(),
    # whose reopen-on-empty-read recovered a real frame.
    assert result.img is recovered


@pytest.mark.smoke
def test_robust_snapshot_recovers_after_garbled_frames(monkeypatch):
    """CUQ-3.13: in robust_capture mode, snapshot() rejects garbled/partial
    decodes and reconnects up to the budget, returning the first clean frame."""
    monkeypatch.setattr("glassbox.perception.picokvm_source.time.sleep", lambda *_: None)
    recovered = _decoded(7)
    captures = [
        FakeCapture([(True, _flat())]),    # attempt 1: garbled -> reconnect
        FakeCapture([(False, None)]),      # attempt 2: read failed -> reconnect
        FakeCapture([(True, recovered)]),  # attempt 3: clean
    ]
    cfg = PicoKVMEffectorConfig(
        _env_file=None, base_url="http://picokvm.test",
        robust_capture=True, snapshot_reconnect_attempts=4,
    )
    source = PicoKVMFrameSource(config=cfg, capture_factory=lambda _u: captures.pop(0))

    result = source.snapshot()

    assert result.img is recovered


@pytest.mark.smoke
def test_robust_snapshot_raises_when_budget_exhausted(monkeypatch):
    """CUQ-3.13: a stream that never produces a clean frame raises after the
    bounded reconnect budget instead of returning a corrupt frame."""
    monkeypatch.setattr("glassbox.perception.picokvm_source.time.sleep", lambda *_: None)
    captures = [FakeCapture([(True, _flat())]) for _ in range(3)]
    cfg = PicoKVMEffectorConfig(
        _env_file=None, base_url="http://picokvm.test",
        robust_capture=True, snapshot_reconnect_attempts=3,
    )
    source = PicoKVMFrameSource(config=cfg, capture_factory=lambda _u: captures.pop(0))

    with pytest.raises(RuntimeError, match="garbled/partial"):
        source.snapshot()


@pytest.mark.smoke
def test_default_snapshot_returns_first_ok_frame_even_if_flat():
    """CUQ-3.13 default-safe: with robust_capture off (default), snapshot()
    returns the first ok frame WITHOUT garble rejection (byte-identical)."""
    flat = _flat()
    captures = [FakeCapture([(True, flat)])]
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")
    assert cfg.robust_capture is False
    source = PicoKVMFrameSource(config=cfg, capture_factory=lambda _u: captures.pop(0))

    result = source.snapshot()

    assert result.img is flat


@pytest.mark.smoke
def test_fresh_snapshot_uses_production_warmup_settle_defaults():
    """CUQ-3.10 (audit fix): fresh_snapshot's warmup-discard + settle behavior is
    a DEFAULT-ON change, but production constructs PicoKVMFrameSource(config=...)
    with no warmup args. Lock the constructor defaults (2 / 4) so a regression in
    them is visible (every other fresh_snapshot test passes them explicitly)."""
    cfg = PicoKVMEffectorConfig(_env_file=None, base_url="http://picokvm.test")
    source = PicoKVMFrameSource(config=cfg)  # no warmup args -> production defaults

    assert source._fresh_warmup_frames == 2
    assert source._fresh_settle_reads == 4

    # And the default warmup is actually applied: 2 warmup frames are discarded,
    # the first decoded frame after them is returned.
    fresh = _decoded(9)
    captures = [FakeCapture([(True, _decoded(1)), (True, _decoded(2)), (True, fresh)])]
    source2 = PicoKVMFrameSource(config=cfg, capture_factory=lambda _u: captures.pop(0))
    assert source2.fresh_snapshot().img is fresh


def test_open_retries_through_transient_wedge(monkeypatch):
    """The single-consumer H.264 stream intermittently refuses a fresh open
    when consumers cycle quickly (observed twice live on 2026-06-11, killing a
    canonical-primitives benchmark at a round boundary). open() must ride
    through with bounded backoff instead of raising on the first refusal."""
    import glassbox.perception.picokvm_source as src_mod
    from glassbox.perception.picokvm_source import PicoKVMFrameSource

    sleeps: list[float] = []
    monkeypatch.setattr(src_mod.time, "sleep", sleeps.append)

    class _Refused:
        released = 0

        def isOpened(self):
            return False

        def release(self):
            type(self).released += 1

    class _Opened:
        def isOpened(self):
            return True

    captures = [_Refused(), _Refused(), _Opened()]
    source = PicoKVMFrameSource(capture_factory=lambda _url: captures.pop(0))

    source.open()

    assert isinstance(source._capture, _Opened)
    assert _Refused.released == 2  # refused handles are released, not leaked
    assert sleeps == [2.0, 4.0]  # linear backoff between attempts


def test_open_raises_after_retry_budget(monkeypatch):
    import glassbox.perception.picokvm_source as src_mod
    from glassbox.perception.picokvm_source import PicoKVMFrameSource

    monkeypatch.setattr(src_mod.time, "sleep", lambda _s: None)

    class _Refused:
        def isOpened(self):
            return False

        def release(self):
            pass

    source = PicoKVMFrameSource(capture_factory=lambda _url: _Refused())

    with pytest.raises(RuntimeError, match="did not open after 4 attempts"):
        source.open()


def test_open_retry_budget_is_env_tunable():
    from glassbox.perception.picokvm_config import PicoKVMVideoConfig

    assert PicoKVMVideoConfig().open_retry_attempts == 4
    assert PicoKVMVideoConfig(open_retry_attempts=2).open_retry_attempts == 2
    with pytest.raises(ValueError):
        PicoKVMVideoConfig(open_retry_attempts=0)
