"""glassbox/perception/device.py — screen resolutions for known iOS/iPadOS devices

Two coordinate sizes matter:
  - pixel_size: native rendered pixels used by HDMI mirror and frame-space actions.
  - point_size: UIKit points used by iOS platform geometry helpers.

Data source: Apple developer Display Size documentation (2026-05).
"""

from __future__ import annotations

# (native rendered pixel_w, pixel_h) — portrait orientation
IPHONE_17_PRO_MAX: tuple[int, int] = (1320, 2868)
IPHONE_17_PRO: tuple[int, int] = (1206, 2622)
IPHONE_17: tuple[int, int] = (1179, 2556)

IPHONE_16_PRO_MAX: tuple[int, int] = (1320, 2868)
IPHONE_16_PRO: tuple[int, int] = (1206, 2622)
IPHONE_16: tuple[int, int] = (1179, 2556)

IPHONE_15_PRO_MAX: tuple[int, int] = (1290, 2796)
IPHONE_15_PRO: tuple[int, int] = (1179, 2556)
IPHONE_15: tuple[int, int] = (1179, 2556)

IPAD_MINI_7: tuple[int, int] = (1488, 2266)
# iPad mini 6 and 7 ship the identical 8.3" panel (2266x1488 px, 1133x744 pt) and
# both use USB-C; they differ only in SoC, which glassbox does not depend on, so
# they share one geometry/fit.
IPAD_MINI_6: tuple[int, int] = IPAD_MINI_7


DEVICES: dict[str, tuple[int, int]] = {
    "iphone_17_pro_max": IPHONE_17_PRO_MAX,
    "iphone_17_pro":     IPHONE_17_PRO,
    "iphone_17":         IPHONE_17,
    "iphone_16_pro_max": IPHONE_16_PRO_MAX,
    "iphone_16_pro":     IPHONE_16_PRO,
    "iphone_16":         IPHONE_16,
    "iphone_15_pro_max": IPHONE_15_PRO_MAX,
    "iphone_15_pro":     IPHONE_15_PRO,
    "iphone_15":         IPHONE_15,
    "ipad_mini_6":        IPAD_MINI_6,
    "ipad_mini_7":        IPAD_MINI_7,
}

DEVICE_POINTS: dict[str, tuple[int, int]] = {
    "iphone_17_pro_max": (440, 956),
    "iphone_17_pro":     (402, 874),
    "iphone_17":         (393, 852),
    "iphone_16_pro_max": (440, 956),
    "iphone_16_pro":     (402, 874),
    "iphone_16":         (393, 852),
    "iphone_15_pro_max": (430, 932),
    "iphone_15_pro":     (393, 852),
    "iphone_15":         (393, 852),
    "ipad_mini_6":        (744, 1133),
    "ipad_mini_7":        (744, 1133),
}


def get(name: str) -> tuple[int, int]:
    """Look up a model's resolution by key. Raises KeyError on an unknown name."""
    key = name.lower().replace(" ", "_").replace("-", "_")
    if key not in DEVICES:
        raise KeyError(
            f"unknown device {name!r}; known: {sorted(DEVICES)}"
        )
    return DEVICES[key]


def get_points(name: str) -> tuple[int, int]:
    """Look up a model's UIKit point size by key. Raises KeyError on unknown."""
    key = name.lower().replace(" ", "_").replace("-", "_")
    if key not in DEVICE_POINTS:
        raise KeyError(
            f"unknown device {name!r}; known: {sorted(DEVICE_POINTS)}"
        )
    return DEVICE_POINTS[key]
