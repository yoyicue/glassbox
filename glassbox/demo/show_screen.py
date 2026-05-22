"""glassbox/demo/show_screen.py — live HDMI screen capture display (M0 acceptance)

How to run:
    python -m glassbox.demo.show_screen                    # default index=1
    python -m glassbox.demo.show_screen --device 2          # specify index
    python -m glassbox.demo.show_screen --device 2 --save out.mp4   # record
    python -m glassbox.demo.show_screen --bench             # measure frame rate

Keys (with focus on the OpenCV window):
    ESC / Q     quit
    SPACE       save the current frame as frame_<ts>.png
    S           start/stop recording (same effect as --save)
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

import cv2
from loguru import logger

from glassbox.perception.source import AVFFrameSource, list_avfoundation_devices


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="live HDMI screen capture display (M0 acceptance demo)")
    p.add_argument("--device", "-d", type=int, default=1,
                   help="AVFoundation device index (default 1; 0 is usually the built-in camera)")
    p.add_argument("--width", type=int, default=None, help="requested frame width (optional)")
    p.add_argument("--height", type=int, default=None, help="requested frame height (optional)")
    p.add_argument("--fps", type=int, default=30, help="requested frame rate")
    p.add_argument("--save", type=str, default=None, help="save the recording to the given mp4")
    p.add_argument("--bench", action="store_true", help="only run the frame rate test, exit after 30s")
    p.add_argument("--list", action="store_true", help="list all devices then exit")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.list:
        from glassbox.demo.list_devices import main as list_main
        return list_main()

    devices = list_avfoundation_devices()
    if devices:
        logger.info(f"available devices: {devices}")
    else:
        logger.warning("ffmpeg not installed / enumeration failed; try opening directly with --device")

    try:
        src = AVFFrameSource(
            device_index=args.device,
            width=args.width,
            height=args.height,
            fps_target=args.fps,
        )
        src.open()
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    writer: cv2.VideoWriter | None = None
    if args.save:
        w, h = src.resolution
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(args.save, fourcc, src.fps or 30, (w, h))
        logger.info(f"recording → {args.save}")

    window = "HDMI Preview (ESC / Q to quit)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    # FPS measurement (sliding window)
    ts_window: deque[float] = deque(maxlen=60)
    start = time.monotonic()
    frame_count = 0

    try:
        while True:
            frame = src.snapshot()
            frame_count += 1
            ts_window.append(frame.ts)
            if writer is not None:
                writer.write(frame.img)

            # HUD text
            if len(ts_window) >= 2:
                fps_actual = (len(ts_window) - 1) / (ts_window[-1] - ts_window[0])
            else:
                fps_actual = 0.0
            hud = f"{src.resolution[0]}x{src.resolution[1]}  {fps_actual:.1f} fps  #{frame_count}"
            cv2.putText(frame.img, hud, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 0), 2, cv2.LINE_AA)

            cv2.imshow(window, frame.img)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            elif key == ord(" "):
                fname = f"frame_{int(frame.ts*1000)}.png"
                cv2.imwrite(fname, frame.img)
                logger.info(f"saved snapshot: {fname}")

            if args.bench and (time.monotonic() - start) > 30:
                logger.info(f"bench done: {frame_count} frames / 30s = "
                            f"{frame_count/30:.1f} fps average")
                break
    except KeyboardInterrupt:
        logger.info("interrupted")
    finally:
        if writer is not None:
            writer.release()
            logger.info(f"recording saved: {Path(args.save).resolve()}")
        cv2.destroyAllWindows()
        src.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
