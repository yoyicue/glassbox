from __future__ import annotations

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.target_planner import TargetPlanner


def _el(text: str, x: int, y: int, *, w: int = 80, h: int = 24) -> UIElement:
    return UIElement(type="text", text=text, box=Box(x=x, y=y, w=w, h=h), confidence=0.95)


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=1, timestamp=0.0, elements=list(elements), viewport_size=(640, 989))


class _Geometry:
    model = "ipad_mini_7"


class _Phone:
    device_geometry = _Geometry()

    def __init__(self, scenes: list[Scene] | None = None) -> None:
        self.scenes = scenes or []
        self.scrolls: list[str] = []

    def viewport_size(self) -> tuple[int, int]:
        return 640, 989

    def perceive(self) -> Scene:
        if len(self.scenes) > 1:
            return self.scenes.pop(0)
        return self.scenes[0]


@pytest.mark.smoke
def test_target_planner_finds_label_inside_ipad_settings_sidebar_region():
    scene = _scene(
        _el("Screen Time", 70, 360, w=82),
        _el("Lock Screen Time Settings", 318, 845, w=178),
    )
    planner = TargetPlanner(_Phone([scene]))

    def canonical(text: str) -> str | None:
        return "屏幕使用时间" if text in {"屏幕使用时间", "Screen Time"} else None

    hit = planner.find_visible_label(
        scene,
        ("屏幕使用时间",),
        region="ipados_settings_sidebar",
        canonicalizer=canonical,
    )

    assert hit is not None
    assert hit.text == "Screen Time"


@pytest.mark.smoke
def test_target_planner_sidebar_region_ignores_matching_detail_text():
    scene = _scene(
        _el("Camera", 70, 360, w=72),
        _el("Screen Time", 370, 360, w=82),
    )
    planner = TargetPlanner(_Phone([scene]))

    assert planner.find_visible_label(
        scene,
        ("Screen Time",),
        region="ipados_settings_sidebar",
    ) is None


@pytest.mark.smoke
def test_target_planner_matches_split_sidebar_row_label():
    scene = _scene(
        _el("Home Screen &", 70, 360, w=118),
        _el("App Library", 70, 382, w=90),
    )
    planner = TargetPlanner(_Phone([scene]))

    hit = planner.find_visible_label(
        scene,
        ("Home Screen & App Library",),
        region="ipados_settings_sidebar",
    )

    assert hit is not None
    assert hit.text == "Home Screen &"


@pytest.mark.smoke
def test_target_planner_scrolls_until_label_is_visible():
    scenes = [
        _scene(_el("Camera", 70, 360, w=72)),
        _scene(_el("Screen Time", 70, 360, w=82)),
    ]
    phone = _Phone(scenes)
    planner = TargetPlanner(phone)

    hit = planner.scroll_to_visible_label(
        ("Screen Time",),
        region="ipados_settings_sidebar",
        scroll_down=lambda: phone.scrolls.append("down"),
        scroll_up=lambda: phone.scrolls.append("up"),
        settle_s=0,
    )

    assert hit is not None
    assert hit.text == "Screen Time"
    assert phone.scrolls == ["down"]
