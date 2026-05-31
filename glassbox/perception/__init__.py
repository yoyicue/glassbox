"""glassbox.perception — HDMI frame grabbing + screen-stability detection + static test source + letterbox calibration"""

from glassbox.perception.letterbox import LetterboxCrop, detect_letterbox
from glassbox.perception.picokvm_config import PicoKVMVideoConfig, PicoKVMVideoSettings
from glassbox.perception.picokvm_source import PicoKVMFrameSource
from glassbox.perception.source import (
    FRAME_CONTRACT_VERSION,
    AVFFrameSource,
    DeviceLockedError,
    Frame,
    FrameContext,
    list_avfoundation_devices,
    recover_capture_device,
)
from glassbox.perception.stable import (
    StabilityPolicy,
    StabilityResult,
    frame_diff_ratio,
    wait_stable,
    wait_stable_result,
)
from glassbox.perception.static import StaticFrameSource

__all__ = [
    "FRAME_CONTRACT_VERSION",
    "AVFFrameSource",
    "DeviceLockedError",
    "Frame",
    "FrameContext",
    "LetterboxCrop",
    "PicoKVMFrameSource",
    "PicoKVMVideoConfig",
    "PicoKVMVideoSettings",
    "StabilityPolicy",
    "StabilityResult",
    "StaticFrameSource",
    "detect_letterbox",
    "frame_diff_ratio",
    "list_avfoundation_devices",
    "recover_capture_device",
    "wait_stable",
    "wait_stable_result",
]
