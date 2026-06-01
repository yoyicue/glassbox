"""iOS viewport safe-area hit helpers.

These helpers keep UI chrome hit targets out of per-crawler magic constants.
They are intentionally geometry-only: no device state, no environment knobs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IOSSafeArea:
    width: int
    height: int

    @classmethod
    def from_viewport(cls, viewport_size: tuple[int, int]) -> IOSSafeArea:
        width, height = viewport_size
        return cls(width=max(1, int(width)), height=max(1, int(height)))

    @property
    def bottom_bar_y(self) -> int:
        """Conservative y for tab-bar icon/label elements."""
        return int(self.height * 0.91)

    @property
    def bottom_control_y(self) -> int:
        """Lower y cap for visible bottom controls such as Settings search."""
        return int(self.height * 0.95)

    def bottom_hit_point(
        self,
        *,
        x: int | None = None,
        y: int | None = None,
        element_type: str | None = None,
        fallback_x_fraction: float = 0.5,
    ) -> tuple[int, int]:
        hit_x = int(x) if x is not None else int(self.width * float(fallback_x_fraction))
        if y is None:
            return hit_x, self.bottom_bar_y
        cap = self.bottom_bar_y if element_type == "tab_bar_item" else self.bottom_control_y
        return hit_x, min(int(y), cap)


class IOSSafeAreaProvider:
    """iOS Platform safe-area sub-capability."""

    def bottom_hit_point(
        self,
        viewport_size: tuple[int, int],
        *,
        x: int | None = None,
        y: int | None = None,
        element_type: str | None = None,
        fallback_x_fraction: float = 0.5,
    ) -> tuple[int, int]:
        return IOSSafeArea.from_viewport(viewport_size).bottom_hit_point(
            x=x,
            y=y,
            element_type=element_type,
            fallback_x_fraction=fallback_x_fraction,
        )


@dataclass(frozen=True)
class IPadOSSafeArea(IOSSafeArea):
    """iPadOS safe-area hit helpers.

    iPad mini uses native pointer navigation rather than the iPhone
    home-indicator/AssistiveTouch geometry, so bottom controls can be hit lower
    in the viewport while still avoiding edge chrome.
    """

    @classmethod
    def from_viewport(cls, viewport_size: tuple[int, int]) -> IPadOSSafeArea:
        width, height = viewport_size
        return cls(width=max(1, int(width)), height=max(1, int(height)))

    @property
    def bottom_bar_y(self) -> int:
        return int(self.height * 0.94)

    @property
    def bottom_control_y(self) -> int:
        return int(self.height * 0.97)


class IPadOSSafeAreaProvider(IOSSafeAreaProvider):
    """iPadOS Platform safe-area sub-capability."""

    def bottom_hit_point(
        self,
        viewport_size: tuple[int, int],
        *,
        x: int | None = None,
        y: int | None = None,
        element_type: str | None = None,
        fallback_x_fraction: float = 0.5,
    ) -> tuple[int, int]:
        return IPadOSSafeArea.from_viewport(viewport_size).bottom_hit_point(
            x=x,
            y=y,
            element_type=element_type,
            fallback_x_fraction=fallback_x_fraction,
        )
