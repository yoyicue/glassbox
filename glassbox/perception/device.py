"""glassbox/perception/device.py — screen resolutions for known iPhone models

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
