"""skills/smoke/test_source_recovery.py — capture card device-lock detection / recovery.

The cv2 AVFoundation backend leaks an AVCaptureSession on repeated
open/close, and once the CoreMediaIO daemons enter a bad state the device
locks (isOpened=True but read always False). These tests cover the detection
logic + recovery tool; no physical device needed (subprocess / cv2 are both
mocked).
"""

from __future__ import annotations

import subprocess

import pytest

from glassbox.config import get_config
from glassbox.perception import DeviceLockedError, Frame
from glassbox.perception.source import AVFFrameSource, recover_capture_device
from glassbox.perception.static import StaticFrameSource


# ─── DeviceLockedError ───────────────────────────────────────────────
@pytest.mark.smoke
def test_device_locked_error_is_runtimeerror():
    """DeviceLockedError is a RuntimeError subclass -- conftest's
    `except RuntimeError` can catch it and turn it into a skip."""
    assert issubclass(DeviceLockedError, RuntimeError)


@pytest.mark.smoke
def test_static_frame_source_stream_is_finite(tmp_path):
    import cv2
    import numpy as np

    paths = []
    for i, value in enumerate((10, 20)):
        path = tmp_path / f"{i}.png"
        cv2.imwrite(str(path), np.full((2, 3, 3), value, dtype=np.uint8))
        paths.append(path)

    src = StaticFrameSource(paths)
    frames = list(src.stream())

    assert len(frames) == 2
    assert [int(frame.img[0, 0, 0]) for frame in frames] == [10, 20]


@pytest.mark.smoke
def test_static_frame_source_resolution_reports_decode_failure(tmp_path):
    path = tmp_path / "broken.png"
    path.write_text("not a png", encoding="utf-8")
    src = StaticFrameSource(path)

    with pytest.raises(RuntimeError, match="cv2 failed to decode"):
        _ = src.resolution


# ─── recover_capture_device ──────────────────────────────────────────
@pytest.mark.smoke
def test_recover_returns_false_when_sudo_needs_password(monkeypatch):
    """In a non-NOPASSWD sudo environment, recover returns False without raising."""
    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(
            a[0], returncode=1, stdout="",
            stderr="sudo: a password is required",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert recover_capture_device() is False


@pytest.mark.smoke
def test_recover_returns_true_on_success(monkeypatch):
    """killall dispatched successfully -> True."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a[0], 0, "", ""))
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert recover_capture_device() is True


@pytest.mark.smoke
def test_recover_handles_killall_missing(monkeypatch):
    """killall does not exist (non-macOS) -> False, no raise."""
    def boom(*a, **kw):
        raise FileNotFoundError("killall")
    monkeypatch.setattr(subprocess, "run", boom)
    assert recover_capture_device() is False


@pytest.mark.smoke
def test_recover_handles_timeout(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired("sudo", 10)
    monkeypatch.setattr(subprocess, "run", boom)
    assert recover_capture_device() is False


# ─── AVFFrameSource probe / open logic ───────────────────────────────
class _FakeCap:
    """Fake cv2.VideoCapture. alive=False simulates a lock (read always False)."""

    def __init__(self, alive=True):
        self._alive = alive
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        if self._alive:
            import numpy as np
            return True, np.zeros((4, 4, 3), dtype="uint8")
        return False, None

    def set(self, *a):
        return True

    def get(self, prop):
        return 1920.0 if prop == 3 else (1080.0 if prop == 4 else 30.0)

    def release(self):
        self.released = True


class _SequenceCap(_FakeCap):
    """Fake cap with explicit read outcomes."""

    def __init__(self, outcomes: list[bool]):
        super().__init__(alive=True)
        self.outcomes = list(outcomes)

    def read(self):
        ok = self.outcomes.pop(0) if self.outcomes else False
        if ok:
            import numpy as np
            return True, np.zeros((4, 4, 3), dtype="uint8")
        return False, None


@pytest.mark.smoke
def test_open_probe_passes_on_alive_device(monkeypatch):
    """Device healthy -> open() succeeds, probe passes."""
    import cv2
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=True))
    src = AVFFrameSource(device_index=0)
    src.open(auto_recover=False)
    assert src.cap is not None
    src.close()


@pytest.mark.smoke
def test_open_uses_injected_config_without_global_lookup(monkeypatch):
    """Runtime-created AVF sources should not read global AgentConfig."""
    import cv2

    from glassbox import config as config_mod

    def fail_get_config():
        raise AssertionError("AVFFrameSource should use injected config")

    monkeypatch.setattr(config_mod, "get_config", fail_get_config)
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=True))

    src = AVFFrameSource(device_index=4, fps_target=24, auto_recover_capture=False)
    src.open()

    assert src.device_index == 4
    assert src.fps_target == 24
    assert src.auto_recover_capture is False
    src.close()


@pytest.mark.smoke
def test_open_probe_raises_device_locked(monkeypatch):
    """Device locked + no auto_recover -> raises DeviceLockedError."""
    import cv2
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=False))
    monkeypatch.setattr(AVFFrameSource, "_enable_ffmpeg_fallback", lambda self: False)
    src = AVFFrameSource(device_index=0)
    with pytest.raises(DeviceLockedError, match="locked"):
        src.open(auto_recover=False)
    assert src.cap is None   # cap is cleared after the failure


@pytest.mark.smoke
def test_open_default_does_not_auto_recover_without_opt_in(monkeypatch):
    """Default open() must not restart CoreMediaIO daemons."""
    import cv2

    from glassbox.perception import source as src_mod

    monkeypatch.setenv("GLASSBOX_AUTO_RECOVER_CAPTURE", "0")
    get_config.cache_clear()
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=False))
    monkeypatch.setattr(AVFFrameSource, "_enable_ffmpeg_fallback", lambda self: False)

    called = False

    def fake_recover():
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(src_mod, "recover_capture_device", fake_recover)
    try:
        src = AVFFrameSource(device_index=0)
        with pytest.raises(DeviceLockedError, match="locked"):
            src.open()
    finally:
        get_config.cache_clear()
    assert called is False


@pytest.mark.smoke
def test_open_default_auto_recover_is_opt_in_by_config(monkeypatch):
    import cv2

    from glassbox.perception import source as src_mod

    monkeypatch.setenv("GLASSBOX_AUTO_RECOVER_CAPTURE", "1")
    get_config.cache_clear()
    caps = [_FakeCap(alive=False), _FakeCap(alive=True)]
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: caps.pop(0))
    monkeypatch.setattr(src_mod, "recover_capture_device", lambda: True)
    monkeypatch.setattr("time.sleep", lambda _: None)
    try:
        src = AVFFrameSource(device_index=0)
        src.open()
    finally:
        get_config.cache_clear()
    assert src.cap is not None
    src.close()


@pytest.mark.smoke
def test_open_auto_recover_retries_after_recover(monkeypatch):
    """Locked -> auto_recover calls recover_capture_device -> the second open succeeds."""
    import cv2

    from glassbox.perception import source as src_mod

    caps = [_FakeCap(alive=False), _FakeCap(alive=True)]
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: caps.pop(0))
    monkeypatch.setattr(src_mod, "recover_capture_device", lambda: True)
    monkeypatch.setattr("time.sleep", lambda _: None)

    src = AVFFrameSource(device_index=0)
    src.open(auto_recover=True)   # should not raise
    assert src.cap is not None
    src.close()


@pytest.mark.smoke
def test_open_auto_recover_retries_multiple_reopens(monkeypatch):
    """CoreMediaIO can need more than one reopen after daemon restart."""
    import cv2

    from glassbox.perception import source as src_mod

    caps = [_FakeCap(alive=False), _FakeCap(alive=False), _FakeCap(alive=True)]
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: caps.pop(0))
    monkeypatch.setattr(src_mod, "recover_capture_device", lambda: True)
    monkeypatch.setattr("time.sleep", lambda _: None)

    src = AVFFrameSource(device_index=0)
    src.open(auto_recover=True)

    assert src.cap is not None
    assert len(caps) == 0
    src.close()


@pytest.mark.smoke
def test_open_auto_recover_gives_up_when_recover_fails(monkeypatch):
    """recover cannot save it either -> still raises DeviceLockedError."""
    import cv2

    from glassbox.perception import source as src_mod

    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=False))
    monkeypatch.setattr(src_mod, "recover_capture_device", lambda: False)
    monkeypatch.setattr(AVFFrameSource, "_enable_ffmpeg_fallback", lambda self: False)

    src = AVFFrameSource(device_index=0)
    with pytest.raises(DeviceLockedError):
        src.open(auto_recover=True)


@pytest.mark.smoke
def test_open_uses_ffmpeg_fallback_when_cv2_stays_locked(monkeypatch):
    import cv2
    import numpy as np

    from glassbox.perception import source as src_mod

    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=False))
    monkeypatch.setattr(src_mod, "recover_capture_device", lambda: False)
    monkeypatch.setattr(
        AVFFrameSource,
        "_ffmpeg_snapshot",
        lambda self: Frame(img=np.zeros((4, 6, 3), dtype="uint8"), ts=0.0),
    )

    src = AVFFrameSource(device_index=0)
    src.open(auto_recover=True)

    assert src._ffmpeg_fallback is True
    assert src.resolution == (6, 4)
    assert src.fps == 30.0


@pytest.mark.smoke
def test_wait_stable_zero_timeout_raises_timeout_error():
    import numpy as np

    from glassbox.perception.stable import wait_stable

    class OneFrameSource:
        def snapshot(self):
            return Frame(img=np.zeros((2, 2, 3), dtype="uint8"), ts=0.0)

    with pytest.raises(TimeoutError, match="last diff=n/a"):
        wait_stable(OneFrameSource(), timeout=0.0)


@pytest.mark.smoke
def test_wait_stable_starts_timeout_after_baseline_frame(monkeypatch):
    import numpy as np

    from glassbox.perception.stable import wait_stable

    now = {"value": 0.0}

    class SlowFirstFrameSource:
        calls = 0

        def snapshot(self):
            self.calls += 1
            if self.calls == 1:
                now["value"] += 2.0
            return Frame(img=np.zeros((2, 2, 3), dtype="uint8"), ts=now["value"])

    monkeypatch.setattr("glassbox.perception.stable.time.monotonic", lambda: now["value"])
    monkeypatch.setattr("glassbox.perception.stable.time.sleep", lambda seconds: now.__setitem__("value", now["value"] + seconds))

    frame = wait_stable(
        SlowFirstFrameSource(),
        timeout=1.0,
        consecutive=1,
        poll_interval=0.1,
    )

    assert frame.shape == (2, 2)


@pytest.mark.smoke
def test_snapshot_waits_between_transient_failed_reads(monkeypatch):
    cap = _SequenceCap([False, False, True])
    src = AVFFrameSource(device_index=0)
    src.cap = cap
    sleeps: list[float] = []
    monkeypatch.setattr("glassbox.perception.source.time.sleep", lambda seconds: sleeps.append(seconds))

    frame = src.snapshot(retries=3, retry_delay_s=0.01, reopen_on_failure=False)

    assert frame.shape == (4, 4)
    assert sleeps == [0.01, 0.01]


@pytest.mark.smoke
def test_snapshot_reopens_once_after_idle_read_failures(monkeypatch):
    import cv2

    stale = _SequenceCap([False])
    reopened = _SequenceCap([True, True, True, True, True, True])
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: reopened)

    src = AVFFrameSource(device_index=0)
    src.cap = stale
    frame = src.snapshot(retries=1, retry_delay_s=0.0, reopen_on_failure=True)

    assert stale.released
    assert src.cap is reopened
    assert frame.shape == (4, 4)
    src.close()


@pytest.mark.smoke
def test_snapshot_reopen_respects_auto_recover_opt_in(monkeypatch):
    import cv2

    from glassbox.perception import source as src_mod

    stale = _SequenceCap([False])
    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=False))
    monkeypatch.setattr(AVFFrameSource, "_enable_ffmpeg_fallback", lambda self: False)
    called = False

    def fake_recover():
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(src_mod, "recover_capture_device", fake_recover)
    src = AVFFrameSource(device_index=0, fps_target=30, auto_recover_capture=False)
    src.cap = stale
    with pytest.raises(DeviceLockedError, match="locked"):
        src.snapshot(retries=1, retry_delay_s=0.0, reopen_on_failure=True)
    assert stale.released
    assert called is False


@pytest.mark.smoke
def test_open_auto_recover_gives_up_after_reopen_retries(monkeypatch):
    import cv2

    from glassbox.perception import source as src_mod

    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **kw: _FakeCap(alive=False))
    monkeypatch.setattr(src_mod, "recover_capture_device", lambda: True)
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr(AVFFrameSource, "_enable_ffmpeg_fallback", lambda self: False)

    src = AVFFrameSource(device_index=0)
    with pytest.raises(DeviceLockedError):
        src.open(auto_recover=True)
