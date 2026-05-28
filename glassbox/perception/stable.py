"""perception/stable.py — wait for the screen to settle

Frames grabbed during iOS UI animations (transition / spinner / loading)
cannot be trusted. Strategy: grab two consecutive frames, compute the mean
absolute diff, and treat it as stable if below a threshold.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from glassbox.perception.source import AVFFrameSource, Frame


@dataclass(frozen=True)
class StabilityPolicy:
    enabled: bool = False
    after_action_only: bool = True
    timeout: float = 3.0
    diff_threshold: float = 0.005
    consecutive: int = 2
    poll_interval: float = 0.05


@dataclass(frozen=True)
class StabilityResult:
    frame: Frame
    stable: bool
    stability_score: float
    last_diff: float | None
    policy: StabilityPolicy


def frame_diff_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Compute the difference ratio between two frames (0.0 = identical,
    1.0 = completely different).

    Uses grayscale + 8-bit mean absolute diff normalized by 255. Fast enough
    (< 1ms), 30x simpler than SSIM yet equally sensitive to UI animations
    (large block color changes).
    """
    if a.shape != b.shape:
        return 1.0
    g_a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if a.ndim == 3 else a
    g_b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    diff = cv2.absdiff(g_a, g_b)
    return float(diff.mean() / 255.0)


def wait_stable(
    src: AVFFrameSource,
    *,
    timeout: float = 3.0,
    diff_threshold: float = 0.005,    # 0.5% mean absdiff counts as stable
    consecutive: int = 2,              # at least `consecutive` stable frames in a row
    poll_interval: float = 0.05,       # interval between frame grabs
    initial_frame: Frame | None = None,
    fresh_start: bool = False,
) -> Frame:
    """Block until the screen settles. Returns the last frame.

    If still not stable when timeout elapses, raise TimeoutError (let the
    caller decide whether to retry or abort).
    """
    return wait_stable_result(
        src,
        timeout=timeout,
        diff_threshold=diff_threshold,
        consecutive=consecutive,
        poll_interval=poll_interval,
        initial_frame=initial_frame,
        fresh_start=fresh_start,
    ).frame


def wait_stable_result(
    src: AVFFrameSource,
    *,
    timeout: float = 3.0,
    diff_threshold: float = 0.005,
    consecutive: int = 2,
    poll_interval: float = 0.05,
    initial_frame: Frame | None = None,
    fresh_start: bool = False,
) -> StabilityResult:
    """Block until the screen settles and return frame plus stability metadata."""

    policy = StabilityPolicy(
        enabled=True,
        timeout=timeout,
        diff_threshold=diff_threshold,
        consecutive=consecutive,
        poll_interval=poll_interval,
    )
    if initial_frame is not None:
        prev = initial_frame
    elif fresh_start:
        fresh_snapshot = getattr(src, "fresh_snapshot", None)
        prev = fresh_snapshot() if callable(fresh_snapshot) else src.snapshot()
    else:
        prev = src.snapshot()
    deadline = time.monotonic() + timeout
    stable_count = 0
    last_diff: float | None = None
    required = max(1, consecutive)

    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        cur = src.snapshot()
        d = frame_diff_ratio(prev.img, cur.img)
        last_diff = d
        if d < diff_threshold:
            stable_count += 1
            if stable_count >= required:
                return StabilityResult(
                    frame=cur,
                    stable=True,
                    stability_score=1.0,
                    last_diff=last_diff,
                    policy=policy,
                )
        else:
            stable_count = 0
        prev = cur

    diff_text = f"{last_diff:.4f}" if last_diff is not None else "n/a"
    score = min(1.0, stable_count / required)
    raise TimeoutError(
        f"wait_stable: the screen did not settle within {timeout}s "
        f"(last diff={diff_text}, thresh={diff_threshold}, stability_score={score:.3f})"
    )
