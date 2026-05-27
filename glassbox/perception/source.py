"""perception/source.py — grab a frame from HDMI

MVP implementation: cv2.VideoCapture (backed by AVFoundation, no system
dependencies). Switch to ffmpeg-python or native PyObjC later if the frame
rate / format proves insufficient.

UVC-class HDMI capture cards (Elgato / Magewell / Cam Link, etc.) show up
automatically as AVFoundation devices on macOS; just open them by index.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import ClassVar

import cv2
import numpy as np
from loguru import logger

FRAME_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class FrameProjection:
    """One crop/projection hop in a frame's coordinate lineage."""

    name: str
    source_coordinate_space: str
    target_coordinate_space: str
    source_shape: tuple[int, int]
    crop_bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class FrameContext:
    """Coordinate metadata that travels with a frame."""

    CONTRACT_VERSION: ClassVar[int] = FRAME_CONTRACT_VERSION

    coordinate_space: str = "frame_px"
    source_coordinate_space: str = "frame_px"
    source_shape: tuple[int, int] | None = None
    crop_bbox: tuple[int, int, int, int] | None = None
    projection: str | None = None
    projection_chain: tuple[FrameProjection, ...] = ()

    def with_crop(
        self,
        *,
        source_shape: tuple[int, int],
        crop_bbox: tuple[int, int, int, int],
        projection: str,
        name: str = "crop",
    ) -> FrameContext:
        return FrameContext(
            coordinate_space=projection,
            source_coordinate_space=self.source_coordinate_space,
            source_shape=self.source_shape or source_shape,
            crop_bbox=crop_bbox,
            projection=projection,
            projection_chain=(
                *self.projection_chain,
                FrameProjection(
                    name=name,
                    source_coordinate_space=self.coordinate_space,
                    target_coordinate_space=projection,
                    source_shape=source_shape,
                    crop_bbox=crop_bbox,
                ),
            ),
        )


@dataclass
class Frame:
    """A single grabbed frame."""

    CONTRACT_VERSION: ClassVar[int] = FRAME_CONTRACT_VERSION

    img: np.ndarray          # H x W x 3 (BGR uint8, cv2 standard)
    ts: float                # monotonic timestamp (seconds) when grabbed
    context: FrameContext = field(default_factory=FrameContext)

    @property
    def shape(self) -> tuple[int, int]:
        """Return (W, H)."""
        h, w = self.img.shape[:2]
        return w, h


class DeviceLockedError(RuntimeError):
    """The capture card is locked by macOS -- cap.isOpened()=True but
    read() always returns False.

    Cause: cv2's AVFoundation backend leaks an AVCaptureSession on repeated
    open/close, and UVCAssistant / VDCAssistant (the CoreMediaIO daemons)
    accumulate bad state, treating the device as permanently occupied.

    Recovery: restart the CoreMediaIO daemons (launchd respawns clean ones):
        sudo killall UVCAssistant VDCAssistant
    or physically unplug and replug the USB capture card. See
    recover_capture_device().
    """


def recover_capture_device() -> bool:
    """Try to recover a locked capture card by restarting the CoreMediaIO
    daemons.

    `killall` requires root (the daemons belong to _cmiodalassistants).
    Run `scripts/setup_camera_recover.sh` once to install a tightly-scoped
    NOPASSWD sudoers rule, after which this function is fully automatic.
    Without it, this returns False and the caller should prompt the user to
    run `sudo killall UVCAssistant VDCAssistant` manually or replug the USB.

    Returns True if the restart command was dispatched successfully (this
    does not guarantee the device recovers; the caller must still retry).
    """
    try:
        proc = subprocess.run(
            ["sudo", "-n", "killall", "UVCAssistant", "VDCAssistant"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    # killall returns returncode!=0 when no process is found, but that is
    # fine as long as it is not a sudo password failure
    if "password is required" in proc.stderr or "a password is required" in proc.stderr:
        return False
    logger.info("recover_capture_device: restarted the CoreMediaIO daemons")
    time.sleep(3)   # wait for launchd to respawn + device to re-handshake
    return True


class AVFFrameSource:
    """HDMI frame grabbing (generic AVFoundation UVC device).

    Usage:
        with AVFFrameSource(device_index=1) as src:
            while True:
                frame = src.snapshot()
                cv2.imshow("preview", frame.img)
                if cv2.waitKey(1) == 27: break

    device_index:
        - 0 is usually the Mac's built-in camera
        - 1, 2, ... are USB-UVC devices in plug-in order
        - use `list_avfoundation_devices()` to enumerate all candidates

    fps_target: desired frame rate (requested from the device; the actual
        rate depends on the device's capabilities)
    """

    def __init__(
        self,
        device_index: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps_target: int | None = None,
        auto_recover_capture: bool | None = None,
    ):
        """Create an AVFoundation-backed frame source.

        Runtime construction should inject all config-derived values. The
        fallback config lookup keeps existing direct construction call sites
        working for demos/tests.
        """
        cfg = None
        if device_index is None or fps_target is None or auto_recover_capture is None:
            from glassbox.config import get_config
            cfg = get_config()
        self.device_index = cfg.hdmi_index if device_index is None else device_index
        self.requested_size = (width, height) if width and height else None
        self.fps_target = cfg.hdmi_fps if fps_target is None else fps_target
        self.auto_recover_capture = (
            cfg.auto_recover_capture if auto_recover_capture is None else auto_recover_capture
        )
        self.cap: cv2.VideoCapture | None = None
        self._ffmpeg_fallback = False
        self._ffmpeg_resolution: tuple[int, int] | None = None

    # —— context manager ——
    def __enter__(self) -> AVFFrameSource:
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # —— lifecycle ——
    def open(self, *, auto_recover: bool | None = None) -> None:
        """Open the capture card.

        Right after opening, probe one frame -- if the device is locked
        (isOpened=True but read always False), raise DeviceLockedError
        instead of only discovering it on the first snapshot.

        auto_recover=None uses the instance's injected recovery setting.
        Explicit True is still available for recovery tools that intentionally
        restart the CoreMediaIO camera daemons.
        """
        if self.cap is not None:
            return
        if auto_recover is None:
            auto_recover = self.auto_recover_capture
        try:
            self._open_raw()
        except RuntimeError:
            if self._enable_ffmpeg_fallback():
                return
            raise
        if self._probe_alive():
            return
        # device locked
        logger.warning("probe failed after opening the device -- likely a CoreMediaIO lock")
        self.close()
        if auto_recover and recover_capture_device():
            for attempt in range(3):
                self._open_raw()
                if self._probe_alive(attempts=12):
                    logger.info(f"device recovered after recover attempt {attempt + 1}")
                    return
                self.close()
                time.sleep(1.0)
        if self._enable_ffmpeg_fallback():
            return
        raise DeviceLockedError(
            f"capture card index={self.device_index} is locked (cap.read keeps "
            f"returning ok=False). Manual recovery: `sudo killall UVCAssistant "
            f"VDCAssistant` or replug the USB capture card."
        )

    def _open_raw(self) -> None:
        """Actually open cv2.VideoCapture + request params + warm up. No
        liveness probe."""
        logger.info(f"opening AVFoundation device index={self.device_index}")
        # cv2.CAP_AVFOUNDATION pins the backend explicitly (so cv2 does not
        # fall back to legacy interfaces like QTKit on macOS)
        cap = cv2.VideoCapture(self.device_index, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            raise RuntimeError(
                f"cannot open AVFoundation device index={self.device_index}. "
                f"Run `python -m glassbox.demo.list_devices` to see available devices."
            )

        # request desired params (the driver may ignore them; read actual
        # values back with get())
        if self.requested_size:
            w, h = self.requested_size
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, self.fps_target)

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        logger.info(f"device opened: {actual_w}x{actual_h} @ {actual_fps:.1f}fps")

        self.cap = cap
        # warm up: the first few frames are usually garbage (the driver's
        # buffer is not filled yet at startup)
        for _ in range(3):
            cap.read()

    def _probe_alive(self, attempts: int = 8) -> bool:
        """Probe whether the device can actually grab frames (distinguishes
        a healthy device from a locked one)."""
        if self.cap is None:
            return False
        for _ in range(attempts):
            ok, img = self.cap.read()
            if ok and img is not None:
                return True
        return False

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            # the cv2 AVFoundation backend relies on GC as a fallback to
            # release the AVCaptureSession; force a gc pass to lower the
            # chance of a session leak leading to a device lock.
            import gc
            gc.collect()
            logger.info("device closed")
        self._ffmpeg_fallback = False

    # —— frame grabbing ——
    def snapshot(
        self,
        *,
        retries: int = 3,
        retry_delay_s: float = 0.15,
        reopen_on_failure: bool = True,
    ) -> Frame:
        """Grab one frame synchronously. Raises RuntimeError on failure.

        The first frame after reopening the device occasionally comes back
        ok=False (the cv2 buffer is not full yet); retry `retries` times
        before giving up. AVFoundation can also stop returning frames after
        the capture handle sits idle during a long setup step; in that case,
        reopen the device once and retry before surfacing the failure.
        """
        if self._ffmpeg_fallback:
            return self._ffmpeg_snapshot()
        if self.cap is None:
            raise RuntimeError("device not opened; call open() or use as context manager")
        frame = self._read_snapshot_frame(retries=max(retries, 1), retry_delay_s=retry_delay_s)
        if frame is not None:
            return frame
        if reopen_on_failure:
            logger.warning("frame grab failed; reopening AVFoundation device once")
            self.close()
            self.open(auto_recover=None)
            if self._ffmpeg_fallback:
                return self._ffmpeg_snapshot()
            frame = self._read_snapshot_frame(
                retries=max(retries, 8),
                retry_delay_s=retry_delay_s,
            )
            if frame is not None:
                return frame
        raise RuntimeError(
            f"frame grab failed after {retries} retries (cap.read keeps returning ok=False)"
        )

    def _read_snapshot_frame(self, *, retries: int, retry_delay_s: float) -> Frame | None:
        if self.cap is None:
            return None
        for attempt in range(max(retries, 1)):
            ok, img = self.cap.read()
            if ok and img is not None:
                return Frame(img=img, ts=time.monotonic())
            if attempt + 1 < retries and retry_delay_s > 0:
                time.sleep(retry_delay_s)
        return None

    def _enable_ffmpeg_fallback(self) -> bool:
        """Use ffmpeg's AVFoundation reader when cv2's reader is stuck."""
        try:
            self._ffmpeg_fallback = True
            probe = self._ffmpeg_snapshot()
        except Exception as exc:
            self._ffmpeg_fallback = False
            self._ffmpeg_resolution = None
            logger.warning(f"ffmpeg AVFoundation fallback unavailable: {exc}")
            return False
        self._ffmpeg_resolution = probe.shape
        logger.info(
            "using ffmpeg AVFoundation fallback for device "
            f"index={self.device_index} resolution={self._ffmpeg_resolution}"
        )
        return True

    def _ffmpeg_snapshot(self) -> Frame:
        argv = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "avfoundation",
            "-framerate",
            str(self.fps_target),
        ]
        if self.requested_size:
            w, h = self.requested_size
            argv += ["-video_size", f"{w}x{h}"]
        argv += [
            "-i",
            f"{self.device_index}:none",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=10, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("ffmpeg snapshot timed out") from exc
        if proc.returncode != 0 or not proc.stdout:
            stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"ffmpeg snapshot failed rc={proc.returncode}: {stderr.strip()}")
        arr = np.frombuffer(proc.stdout, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("ffmpeg snapshot did not decode as an image")
        return Frame(img=img, ts=time.monotonic())

    def stream(self) -> Iterator[Frame]:
        """Lazy frame stream. Terminate with Ctrl-C."""
        while True:
            yield self.snapshot()

    # —— metadata ——
    @property
    def coordinate_space(self) -> str:
        return "frame_px"

    @property
    def resolution(self) -> tuple[int, int]:
        """Return the current frame resolution (w, h)."""
        if self._ffmpeg_fallback:
            if self._ffmpeg_resolution is None:
                self._ffmpeg_resolution = self._ffmpeg_snapshot().shape
            return self._ffmpeg_resolution
        if self.cap is None:
            raise RuntimeError("device not opened")
        return (
            int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    @property
    def fps(self) -> float:
        if self._ffmpeg_fallback:
            return float(self.fps_target)
        if self.cap is None:
            raise RuntimeError("device not opened")
        return self.cap.get(cv2.CAP_PROP_FPS)


# ─── device enumeration ──────────────────────────────────────────────
def list_avfoundation_devices() -> list[dict]:
    """Enumerate all AVFoundation video devices on the system (runs an
    ffmpeg subprocess; ffmpeg must be installed locally).

    Returns [{"index": int, "name": str}, ...].
    If ffmpeg is not on PATH, returns [] plus a warning.
    """
    try:
        # this command prints the device list to stderr; capturing stderr
        # normally is enough
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        logger.warning("ffmpeg is not installed -- run `brew install ffmpeg` to enumerate device names")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg enumeration timed out")
        return []

    devices: list[dict] = []
    in_video_section = False
    for line in proc.stderr.splitlines():
        if "AVFoundation video devices" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices" in line:
            in_video_section = False
            continue
        if in_video_section and "] [" in line:
            # line format: [AVFoundation indev @ 0x...] [0] FaceTime HD Camera
            try:
                idx_part = line.split("] [")[1].split("]")[0]
                name_part = line.split("] ", 2)[2].strip()
                devices.append({"index": int(idx_part), "name": name_part})
            except (IndexError, ValueError):
                continue
    return devices
