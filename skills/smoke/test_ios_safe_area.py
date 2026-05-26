from __future__ import annotations

import pytest

from glassbox.ios.safe_area import IOSSafeArea, IPadOSSafeArea


@pytest.mark.smoke
def test_ios_safe_area_bottom_hit_points_distinguish_tab_bar_and_bottom_controls():
    safe = IOSSafeArea.from_viewport((448, 973))

    assert safe.bottom_hit_point(fallback_x_fraction=0.18) == (80, 885)
    assert safe.bottom_hit_point(x=311, y=929, element_type="tab_bar_item") == (311, 885)
    assert safe.bottom_hit_point(x=78, y=921, element_type="text") == (78, 921)
    assert safe.bottom_hit_point(x=78, y=960, element_type="text") == (78, 924)


@pytest.mark.smoke
def test_ios_safe_area_normalizes_invalid_viewport_size():
    safe = IOSSafeArea.from_viewport((0, 0))

    assert safe.width == 1
    assert safe.height == 1


@pytest.mark.smoke
def test_ipados_safe_area_bottom_controls_can_hit_lower_than_iphone():
    safe = IPadOSSafeArea.from_viewport((744, 1133))

    assert safe.bottom_hit_point(fallback_x_fraction=0.18) == (133, 1065)
    assert safe.bottom_hit_point(x=640, y=1115, element_type="tab_bar_item") == (640, 1065)
    assert safe.bottom_hit_point(x=640, y=1115, element_type="text") == (640, 1099)
