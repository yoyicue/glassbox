"""FrameSource for Luckfox PicoKVM HTTP video stream."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import cv2

from glassbox.effectors.picokvm.config import PicoKVMEffectorConfig
from glassbox.perception.source import Frame


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
        config: PicoKVMEffectorConfig | None = None,
        capture: Any = None,
        capture_factory: Any = None,
    ):
        self.config = config or PicoKVMEffectorConfig()
        self.stream_url = f"{self.config.base_url}{self.config.stream_path}"
        self._capture = capture
        self._capture_factory = capture_factory or cv2.VideoCapture
        self._owns_capture = capture is None

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

    def fresh_snapshot(self) -> Frame:
        """Grab a frame after reopening the HTTP stream.

        OpenCV can return stale buffered frames from PicoKVM's long-lived H.264
        stream after HID actions. Reopening is slower than ``snapshot()``, but it
        gives callers an explicit freshness boundary when they need visual
        evidence after an action.
        """
        self.close()
        time.sleep(0.05)
        self.open()
        return self.snapshot()

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
