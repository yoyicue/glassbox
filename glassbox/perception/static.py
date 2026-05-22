"""glassbox/perception/static.py — StaticFrameSource

Lets fixtures / unit tests run without depending on an HDMI capture card.

Usage:
    src = StaticFrameSource("baseline/login_screen.png")
    frame = src.snapshot()      # always returns this image
    list(src.stream())          # StopIteration after one frame

Or cycle through multiple images (to simulate navigation):
    src = StaticFrameSource(["splash.png", "list.png", "settings.png"])
    src.snapshot()  # splash
    src.advance()
    src.snapshot()  # list
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import cv2
from loguru import logger

from glassbox.perception.source import Frame


class StaticFrameSource:
    """Reads static images as a frame source. Used by M2a tests."""

    def __init__(self, source: str | Path | list[str | Path]):
        if isinstance(source, (str, Path)):
            self._paths = [Path(source)]
        else:
            self._paths = [Path(p) for p in source]
        for p in self._paths:
            if not p.exists():
                raise FileNotFoundError(f"frame image does not exist: {p}")
        self._index = 0

    # —— context manager (matches the AVFFrameSource interface) ——
    def __enter__(self) -> StaticFrameSource:
        return self

    def __exit__(self, *_):
        pass

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    # —— frame grabbing ——
    def snapshot(self) -> Frame:
        return self._read_frame(self._index)

    def stream(self) -> Iterator[Frame]:
        """Finite frame stream from the current index through the configured list."""
        for index in range(self._index, len(self._paths)):
            yield self._read_frame(index)

    def _read_frame(self, index: int) -> Frame:
        img = self._decode_image(index)
        return Frame(img=img, ts=time.monotonic())

    def _decode_image(self, index: int):
        img = cv2.imread(str(self._paths[index]))
        if img is None:
            raise RuntimeError(f"cv2 failed to decode: {self._paths[index]}")
        return img

    # —— multi-image mode ——
    def advance(self) -> bool:
        """Switch to the next image. Returns True on success, False if
        already at the end."""
        if self._index + 1 < len(self._paths):
            self._index += 1
            logger.info(f"StaticFrameSource → frame #{self._index}: {self._paths[self._index].name}")
            return True
        return False

    def reset(self) -> None:
        self._index = 0

    @property
    def resolution(self) -> tuple[int, int]:
        img = self._decode_image(self._index)
        h, w = img.shape[:2]
        return w, h

    @property
    def fps(self) -> float:
        return 0.0  # meaningless for a static source

    @property
    def coordinate_space(self) -> str:
        return "frame_px"
