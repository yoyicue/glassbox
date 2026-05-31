"""FrameSource for Luckfox PicoKVM HTTP video stream."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import cv2

from glassbox.perception.picokvm_config import PicoKVMVideoConfig, PicoKVMVideoSettings
from glassbox.perception.source import Frame

# A fully-decoded iOS screen always has real spatial variance (status bar, text,
# chrome). A near-flat frame (std ~0) coming straight off the H.264 stream is a
# partial / pre-keyframe decode or an empty buffer, not a usable screen.
_MIN_DECODED_STD = 1.0


class PicoKVMFrameSource:
    """Decode PicoKVM's HTTP stream.

    Bring-up on App 0.1.3 found ``GET /video/stream`` returns raw H.264
    (``video/x-h264``). OpenCV's FFmpeg backend can consume this URL directly in
    the production path; tests can inject a ``cv2.VideoCapture`` compatible
    object via ``capture``.
    """

    coordinate_space = "frame_px"

    def __init__(
        self,
        *,
        config: PicoKVMVideoSettings | None = None,
        capture: Any = None,
        capture_factory: Any = None,
        fresh_warmup_frames: int = 2,
        fresh_settle_reads: int = 4,
    ):
        self.config = config or PicoKVMVideoConfig()
        self.stream_url = f"{self.config.base_url}{self.config.stream_path}"
        self._capture = capture
        self._capture_factory = capture_factory or cv2.VideoCapture
        self._owns_capture = capture is None
        # After a reopen the first decoded frame(s) of the long-lived H.264
        # stream are frequently pre-keyframe / partial decodes (smeared or
        # near-empty). Discard a few, then return the first frame that looks
        # fully decoded. Latency is paid only on the explicit freshness
        # boundary (fresh_snapshot), which the reliability design accepts.
        self._fresh_warmup_frames = max(0, fresh_warmup_frames)
        self._fresh_settle_reads = max(1, fresh_settle_reads)

    def __enter__(self) -> PicoKVMFrameSource:
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def open(self) -> None:
        if self._capture is None:
            self._capture = self._capture_factory(self.stream_url)
        if hasattr(self._capture, "isOpened") and not self._capture.isOpened():
            raise RuntimeError(f"PicoKVM video stream did not open: {self.stream_url}")

    def close(self) -> None:
        if self._capture is not None and self._owns_capture and hasattr(self._capture, "release"):
            self._capture.release()
        self._capture = None

    def snapshot(self) -> Frame:
        if self._capture is None:
            self.open()
        if getattr(self.config, "robust_capture", False):
            return self._robust_snapshot()
        last_error = None
        for attempt in range(2):
            ok, img = self._capture.read()
            if ok and img is not None:
                return Frame(img=img, ts=time.monotonic())
            last_error = f"attempt {attempt + 1} returned no frame"
            self.close()
            time.sleep(0.15)
            self.open()
        raise RuntimeError(f"PicoKVM video stream read failed: {self.stream_url}: {last_error}")

    def _robust_snapshot(self) -> Frame:
        """CUQ-3.13: bounded reconnect + H.264 garble detection.

        Returns the first fully-decoded frame within the attempt budget,
        reopening the stream with linear backoff after a read failure OR a
        partial/garbled decode (so a transiently stalled or smeared stream
        recovers instead of returning a corrupt frame or raising after two
        tries). Raises only when the whole budget is exhausted.
        """
        attempts = max(1, int(getattr(self.config, "snapshot_reconnect_attempts", 4)))
        last_error = None
        for attempt in range(attempts):
            ok, img = self._capture.read()
            if ok and img is not None:
                if self._frame_looks_decoded(img):
                    return Frame(img=img, ts=time.monotonic())
                last_error = f"attempt {attempt + 1} returned a garbled/partial frame"
            else:
                last_error = f"attempt {attempt + 1} returned no frame"
            if attempt < attempts - 1:
                self.close()
                time.sleep(0.15 * (attempt + 1))
                self.open()
        raise RuntimeError(f"PicoKVM video stream read failed: {self.stream_url}: {last_error}")

    def fresh_snapshot(self) -> Frame:
        """Grab a frame after reopening the HTTP stream.

        OpenCV can return stale buffered frames from PicoKVM's long-lived H.264
        stream after HID actions. Reopening is slower than ``snapshot()``, but it
        gives callers an explicit freshness boundary when they need visual
        evidence after an action.

        The first frame(s) decoded right after a reopen are often pre-keyframe /
        partial decodes that would corrupt OCR/verification if returned as
        "fresh evidence". Discard the warmup frames, then return the first
        fully-decoded frame; fall back to the normal retry path if none of the
        settle reads produce a usable frame.
        """
        self.close()
        time.sleep(0.05)
        self.open()
        for _ in range(self._fresh_warmup_frames):
            ok, _img = self._capture.read()
            if not ok:
                break
        for _ in range(self._fresh_settle_reads):
            ok, img = self._capture.read()
            if ok and self._frame_looks_decoded(img):
                return Frame(img=img, ts=time.monotonic())
        # No clean frame within the settle budget: defer to snapshot()'s own
        # reopen-and-retry rather than silently returning a garbled frame.
        return self.snapshot()

    @staticmethod
    def _frame_looks_decoded(img: Any) -> bool:
        """Reject empty / degenerate-variance frames (partial H.264 decodes)."""
        if img is None or getattr(img, "size", 0) == 0:
            return False
        return float(img.std()) > _MIN_DECODED_STD

    def stream(self) -> Iterator[Frame]:
        while True:
            yield self.snapshot()

    @property
    def resolution(self) -> tuple[int, int]:
        frame = self.snapshot()
        return frame.shape

    @property
    def fps(self) -> float:
        return 60.0
