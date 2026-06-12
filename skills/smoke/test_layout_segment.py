from __future__ import annotations

import pytest

from glassbox.cognition.base import Box, Scene, UIElement
from glassbox.cognition.layout_segment import segment_layout


def _scene(*elements: UIElement, size: tuple[int, int]) -> Scene:
    return Scene(frame_id=1, timestamp=0.0, elements=list(elements), viewport_size=size)


def _el(
    element_type: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    text: str | None = None,
    element_id: int = 0,
) -> UIElement:
    return UIElement(
        type=element_type,
        box=Box(x=x, y=y, w=w, h=h),
        text=text,
        confidence=0.9,
        element_id=element_id,
    )


@pytest.mark.smoke
@pytest.mark.parametrize("size", [(440, 956), (744, 1133)])
def test_layout_segmentation_groups_icon_label_rows_in_reading_order_on_phone_and_ipad(size):
    width, height = size
    icon = max(22, int(width * 0.055))
    row1_y = int(height * 0.22)
    row2_y = int(height * 0.29)
    x = int(width * 0.08)
    gap = max(10, int(width * 0.025))
    label_h = max(18, int(height * 0.02))
    scene = _scene(
        _el("text", x=x + icon + gap, y=row2_y + 2, w=96, h=label_h, text="Bluetooth", element_id=10),
        _el("image", x=x, y=row1_y, w=icon, h=icon, element_id=1),
        _el("text", x=x + icon + gap, y=row1_y + 2, w=64, h=label_h, text="WLAN", element_id=2),
        _el("image", x=x, y=row2_y, w=icon, h=icon, element_id=3),
        size=size,
    )

    segment_layout(scene, viewport_size=size)

    assert [element.text for element in scene.elements] == ["WLAN", "Bluetooth"]
    assert [element.element_id for element in scene.elements] == [0, 1]
    assert all(element.type == "list_item" for element in scene.elements)
    assert all(element.suggested_actions == ["tap"] for element in scene.elements)
    assert all(element.type_source == "layout_segmenter" for element in scene.elements)
    assert all("layout_segment:icon_label" in element.type_evidence for element in scene.elements)


@pytest.mark.smoke
def test_layout_segmentation_groups_springboard_icon_with_below_label_and_preserves_intent():
    text = _el("text", x=52, y=185, w=72, h=18, text="日 Notes", element_id=4)
    text.intent_label = "Notes"
    text.intent_source = "springboard_lexicon"
    scene = _scene(
        _el("image", x=60, y=120, w=56, h=56, element_id=3),
        text,
        size=(440, 956),
    )

    segment_layout(scene, viewport_size=(440, 956))

    assert len(scene.elements) == 1
    grouped = scene.elements[0]
    assert grouped.type == "button"
    assert grouped.text == "日 Notes"
    assert grouped.intent_label == "Notes"
    assert grouped.intent_source == "springboard_lexicon"
    assert grouped.preferred_tap_point == (88, 148)
    assert "layout_orientation:vertical" in grouped.type_evidence


@pytest.mark.smoke
def test_layout_segmentation_promotes_icon_only_control_without_captioning():
    scene = _scene(
        _el("image", x=360, y=300, w=32, h=32, element_id=7),
        size=(440, 956),
    )

    segment_layout(scene, viewport_size=(440, 956))

    assert len(scene.elements) == 1
    icon = scene.elements[0]
    assert icon.type == "button"
    assert icon.text is None
    assert icon.suggested_actions == ["tap"]
    assert icon.preferred_tap_point == (376, 316)
    assert "layout_segment:icon_only" in icon.type_evidence


@pytest.mark.smoke
def test_layout_segmentation_does_not_promote_low_confidence_unpaired_icon_candidate():
    icon = _el("image", x=360, y=300, w=32, h=32, element_id=7)
    icon.confidence = 0.3
    scene = _scene(icon, size=(440, 956))

    segment_layout(scene, viewport_size=(440, 956))

    assert len(scene.elements) == 1
    assert scene.elements[0].type == "image"
    assert scene.elements[0].suggested_actions == []
    assert scene.elements[0].type_source is None
    assert "layout_segment:icon_only" not in scene.elements[0].type_evidence


@pytest.mark.smoke
def test_layout_segmentation_merges_trailing_accessory_into_leading_row():
    scene = _scene(
        _el("image", x=52, y=250, w=24, h=24, element_id=1),
        _el("text", x=88, y=252, w=120, h=20, text="Notifications", element_id=2),
        _el("image", x=392, y=252, w=18, h=18, element_id=3),
        size=(440, 956),
    )

    segment_layout(scene, viewport_size=(440, 956))

    assert len(scene.elements) == 1
    row = scene.elements[0]
    assert row.type == "list_item"
    assert row.text == "Notifications"
    assert row.box.x2 == 410
    assert row.preferred_tap_point == row.box.center
    assert "layout_accessory:3" in row.type_evidence
    assert "layout_segment:icon_only" not in row.type_evidence


@pytest.mark.smoke
def test_layout_segmentation_does_not_merge_vertical_home_neighbor_icon():
    scene = _scene(
        _el("image", x=60, y=120, w=56, h=56, element_id=1),
        _el("text", x=52, y=185, w=72, h=18, text="Notes", element_id=2),
        _el("image", x=160, y=120, w=56, h=56, element_id=3),
        size=(440, 956),
    )

    segment_layout(scene, viewport_size=(440, 956))

    assert [(element.type, element.text) for element in scene.elements] == [
        ("button", "Notes"),
        ("button", None),
    ]
    assert "layout_orientation:vertical" in scene.elements[0].type_evidence
    assert "layout_segment:icon_only" in scene.elements[1].type_evidence


@pytest.mark.smoke
def test_layout_segmentation_leaves_ambiguous_equidistant_icon_unpaired():
    scene = _scene(
        _el("text", x=40, y=300, w=70, h=20, text="Left", element_id=1),
        _el("image", x=122, y=298, w=24, h=24, element_id=2),
        _el("text", x=158, y=300, w=70, h=20, text="Right", element_id=3),
        size=(440, 956),
    )

    segment_layout(scene, viewport_size=(440, 956))

    assert [(element.type, element.text) for element in scene.elements] == [
        ("text", "Left"),
        ("button", None),
        ("text", "Right"),
    ]


@pytest.mark.smoke
def test_layout_segmentation_does_not_pair_cross_row_label():
    scene = _scene(
        _el("image", x=52, y=220, w=24, h=24, element_id=1),
        _el("text", x=88, y=292, w=120, h=20, text="Notifications", element_id=2),
        size=(440, 956),
    )

    segment_layout(scene, viewport_size=(440, 956))

    assert [(element.type, element.text) for element in scene.elements] == [
        ("button", None),
        ("text", "Notifications"),
    ]


@pytest.mark.smoke
@pytest.mark.parametrize("size", [(440, 956), (744, 1133)])
def test_layout_segmentation_promotes_settings_sidebar_text_rows_on_phone_and_ipad(size):
    width, height = size
    scene = _scene(
        _el(
            "text",
            x=int(width * 0.14),
            y=int(height * 0.30),
            w=92,
            h=18,
            text="Notifications",
            element_id=1,
        ),
        size=size,
    )
    scene.scene_type = "settings_detail"
    scene.safe_actions = ["tap_root_row", "scroll"]

    segment_layout(scene, viewport_size=size)

    assert len(scene.elements) == 1
    row = scene.elements[0]
    assert row.type == "list_item"
    assert row.text == "Notifications"
    assert row.suggested_actions == ["tap"]
    assert row.type_source == "layout_segmenter"
    assert "layout_segment:text_row" in row.type_evidence
    assert row.preferred_tap_point == row.box.center


@pytest.mark.smoke
def test_layout_segmentation_does_not_use_large_detector_regions_as_vertical_icons():
    scene = _scene(
        _el("image", x=10, y=60, w=236, h=88, element_id=58),
        _el("text", x=68, y=162, w=96, h=14, text="Control Centre", element_id=5),
        size=(640, 989),
    )
    scene.scene_type = "settings_detail"
    scene.safe_actions = ["tap_root_row", "scroll"]

    segment_layout(scene, viewport_size=(640, 989))

    rows = [element for element in scene.elements if element.text == "Control Centre"]
    assert len(rows) == 1
    assert rows[0].type == "list_item"
    assert "layout_segment:text_row" in rows[0].type_evidence
    assert "layout_orientation:vertical" not in rows[0].type_evidence
    assert all("layout_orientation:vertical" not in element.type_evidence for element in scene.elements)


@pytest.mark.smoke
def test_layout_segmentation_does_not_promote_settings_secondary_or_paragraph_text():
    scene = _scene(
        _el(
            "text",
            x=280,
            y=270,
            w=252,
            h=12,
            text="Choose the default for how notifications appear.",
            element_id=1,
        ),
        _el("text", x=318, y=681, w=154, h=14, text="Banners, Sounds, Badges", element_id=2),
        _el("text", x=204, y=314, w=20, h=12, text="On", element_id=3),
        _el("text", x=580, y=410, w=12, h=14, text=">", element_id=4),
        _el("text", x=94, y=178, w=52, h=12, text="and more", element_id=5),
        _el("text", x=180, y=268, w=46, h=16, text="homenet", element_id=6),
        size=(640, 989),
    )
    scene.scene_type = "settings_detail"
    scene.safe_actions = ["tap_root_row", "scroll"]

    segment_layout(scene, viewport_size=(640, 989))

    assert [(element.type, element.text) for element in scene.elements] == [
        ("text", "and more"),
        ("text", "homenet"),
        ("text", "Choose the default for how notifications appear."),
        ("text", "On"),
        ("text", ">"),
        ("text", "Banners, Sounds, Badges"),
    ]


@pytest.mark.smoke
def test_layout_segmentation_does_not_pair_status_value_as_vertical_label():
    scene = _scene(
        _el("image", x=548, y=310, w=72, h=72, element_id=1),
        _el("text", x=561, y=408, w=20, h=12, text="On", element_id=2),
        size=(640, 989),
    )
    scene.scene_type = "settings_detail"

    segment_layout(scene, viewport_size=(640, 989))

    assert [(element.type, element.text) for element in scene.elements] == [
        ("button", None),
        ("text", "On"),
    ]
    assert all("layout_segment:icon_label" not in element.type_evidence for element in scene.elements)
