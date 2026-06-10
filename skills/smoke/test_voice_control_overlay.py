from __future__ import annotations

import numpy as np
import pytest

from glassbox.cognition import Box, Scene, UIElement, WhiteboxHint
from glassbox.cognition.voice_control_overlay import (
    VoiceControlOverlayMarker,
    apply_voice_control_overlay_hints,
    overlay_number,
    parse_voice_control_overlay,
)


def _el(
    text: str,
    *,
    x: int = 10,
    y: int = 10,
    w: int = 24,
    h: int = 16,
    element_id: int = 0,
) -> UIElement:
    return UIElement(
        type="text",
        box=Box(x=x, y=y, w=w, h=h),
        text=text,
        confidence=0.9,
        element_id=element_id,
    )


def _frame_with_badges(*boxes: Box) -> np.ndarray:
    frame = np.full((220, 220, 3), 235, dtype=np.uint8)
    for box in boxes:
        x1 = max(0, box.x - 4)
        y1 = max(0, box.y - 4)
        x2 = min(frame.shape[1], box.x2 + 4)
        y2 = min(frame.shape[0], box.y2 + 4)
        frame[y1:y2, x1:x2] = 55
    return frame


def _scene(*elements: UIElement) -> Scene:
    return Scene(frame_id=1, timestamp=1.0, elements=list(elements))


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("8", 8),
        ("(20", 20),
        ("|27", 27),
        ("［22", 22),
        ("120", 20),
        ("(31", 31),
        ("(10)", 10),
        ("8)", 8),
        ("2:05PM Thu 4 Jun", None),
        ("100%", None),
        ("Item Numbers", None),
    ],
)
def test_overlay_number_handles_voice_control_ocr_noise(text, expected):
    assert overlay_number(text) == expected


@pytest.mark.smoke
def test_parse_item_numbers_ignores_regular_text_when_dark_badge_required():
    number = _el("18", x=20, y=40, element_id=18)
    regular = _el("19", x=120, y=40, element_id=19)
    frame = _frame_with_badges(number.box)

    markers = parse_voice_control_overlay(
        [regular, number, _el("2:05PM Thu 4 Jun", x=10, y=5, w=120)],
        mode="item_numbers",
        frame_img=frame,
    )

    assert [marker.number for marker in markers] == [18]
    marker = markers[0]
    assert marker.kind == "item_number"
    assert marker.accessibility_id == "vc:item_number:18"
    assert marker.source_element_id == 18


@pytest.mark.smoke
def test_parse_item_names_uses_dark_badge_visual_filter_and_slugs_label():
    overlay = _el("Search field", x=20, y=40, w=80, element_id=7)
    normal = _el("Search", x=20, y=90, w=60, element_id=8)
    frame = _frame_with_badges(overlay.box)

    markers = parse_voice_control_overlay(
        [normal, overlay],
        mode="item_names",
        frame_img=frame,
    )

    assert [(marker.kind, marker.text, marker.accessibility_id) for marker in markers] == [
        ("item_name", "Search field", "vc:item-name:search-field")
    ]


@pytest.mark.smoke
def test_parse_item_names_filters_status_bar_badges_from_real_overlay_frame():
    status = _el("2:07PM Thu 4 Jun", x=10, y=12, w=120, element_id=1)
    overlay = _el("Voice", x=100, y=70, w=45, element_id=2)
    frame = _frame_with_badges(status.box, overlay.box)

    markers = parse_voice_control_overlay(
        [status, overlay],
        mode="item_names",
        frame_img=frame,
    )

    assert [(marker.text, marker.accessibility_id) for marker in markers] == [
        ("Voice", "vc:item-name:voice")
    ]


@pytest.mark.smoke
def test_parse_numbered_grid_marks_grid_numbers_separately():
    first = _el("1", x=20, y=40, element_id=1)
    second = _el("24", x=120, y=160, element_id=24)
    frame = _frame_with_badges(first.box, second.box)

    markers = parse_voice_control_overlay(
        [second, first],
        mode="numbered_grid",
        frame_img=frame,
    )

    assert [(marker.kind, marker.number) for marker in markers] == [
        ("grid_number", 1),
        ("grid_number", 24),
    ]
    assert [marker.accessibility_id for marker in markers] == [
        "vc:grid_number:1",
        "vc:grid_number:24",
    ]


@pytest.mark.smoke
def test_parse_item_numbers_collapses_narrow_duplicate_nine_ocr():
    narrow = _el("99", x=20, y=40, w=14, element_id=9)
    wide = _el("99", x=80, y=40, w=24, element_id=99)
    frame = _frame_with_badges(narrow.box, wide.box)

    markers = parse_voice_control_overlay([wide, narrow], mode="item_numbers", frame_img=frame)

    assert [(marker.number, marker.accessibility_id) for marker in markers] == [
        (9, "vc:item_number:9"),
        (99, "vc:item_number:99"),
    ]


@pytest.mark.smoke
def test_apply_overlay_hints_matches_row_badge_by_y_band():
    badge = _el("18", x=10, y=48, element_id=18)
    row = _el("Sounds", x=90, y=50, w=80, element_id=2)
    marker = VoiceControlOverlayMarker(
        kind="item_number",
        text="18",
        number=18,
        box=badge.box,
        confidence=0.9,
        source_element_id=18,
        accessibility_id="vc:item_number:18",
    )

    scene = apply_voice_control_overlay_hints(
        _scene(badge, row),
        [marker],
        include_frame_local_numbers=True,
    )

    assert badge.whitebox_hint is None
    assert scene.elements[1].whitebox_hint == WhiteboxHint(accessibility_id="vc:item_number:18")


@pytest.mark.smoke
def test_apply_overlay_hints_preserves_existing_asset_match():
    row = _el("Settings", x=70, y=40, w=80, element_id=2)
    row.whitebox_hint = WhiteboxHint(asset_match="settings_icon")
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Settings",
        box=Box(x=12, y=18, w=60, h=16),
        confidence=0.9,
        source_element_id=9,
        accessibility_id="vc:item-name:settings",
    )

    apply_voice_control_overlay_hints(_scene(row), [marker], include_names=True)

    assert row.whitebox_hint == WhiteboxHint(
        asset_match="settings_icon",
        accessibility_id="vc:item-name:settings",
    )


@pytest.mark.smoke
def test_apply_overlay_hints_keeps_existing_accessibility_id_by_default():
    row = _el("Login", x=70, y=40, w=80, element_id=2)
    row.whitebox_hint = WhiteboxHint(accessibility_id="native:login")
    marker = VoiceControlOverlayMarker(
        kind="item_number",
        text="4",
        number=4,
        box=Box(x=12, y=42, w=18, h=16),
        confidence=0.9,
        source_element_id=9,
        accessibility_id="vc:item_number:4",
    )

    apply_voice_control_overlay_hints(_scene(row), [marker])

    assert row.whitebox_hint.accessibility_id == "native:login"


@pytest.mark.smoke
def test_apply_overlay_hints_skips_frame_local_number_ids_by_default():
    row = _el("Login", x=70, y=40, w=80, element_id=2)
    marker = VoiceControlOverlayMarker(
        kind="item_number",
        text="4",
        number=4,
        box=Box(x=12, y=42, w=18, h=16),
        confidence=0.9,
        source_element_id=9,
        accessibility_id="vc:item_number:4",
    )

    apply_voice_control_overlay_hints(_scene(row), [marker])

    assert row.whitebox_hint is None


@pytest.mark.smoke
def test_apply_overlay_hints_skips_item_name_ids_by_default():
    row = _el("Settings", x=70, y=40, w=80, element_id=2)
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Settings",
        box=Box(x=12, y=18, w=60, h=16),
        confidence=0.9,
        source_element_id=9,
        accessibility_id="vc:item-name:settings",
    )

    apply_voice_control_overlay_hints(_scene(row), [marker])

    assert row.whitebox_hint is None


@pytest.mark.smoke
def test_apply_overlay_hints_skips_far_marker():
    target = _el("Login", x=160, y=160, w=80, element_id=2)
    marker = VoiceControlOverlayMarker(
        kind="item_number",
        text="4",
        number=4,
        box=Box(x=12, y=20, w=18, h=16),
        confidence=0.9,
        source_element_id=9,
        accessibility_id="vc:item_number:4",
    )

    apply_voice_control_overlay_hints(
        _scene(target),
        [marker],
        include_frame_local_numbers=True,
    )

    assert target.whitebox_hint is None


@pytest.mark.smoke
def test_apply_overlay_hints_prefers_text_target_over_nearby_image():
    marker = VoiceControlOverlayMarker(
        kind="item_number",
        text="23",
        number=23,
        box=Box(x=0, y=806, w=22, h=14),
        confidence=0.9,
        source_element_id=23,
        accessibility_id="vc:item_number:23",
    )
    icon = UIElement(
        type="image",
        box=Box(x=0, y=776, w=27, h=43),
        confidence=0.9,
        element_id=1,
    )
    label = _el("iCloud", x=38, y=823, w=72, h=15, element_id=2)

    apply_voice_control_overlay_hints(
        _scene(icon, label),
        [marker],
        include_frame_local_numbers=True,
    )

    assert icon.whitebox_hint is None
    assert label.whitebox_hint == WhiteboxHint(accessibility_id="vc:item_number:23")


@pytest.mark.smoke
def test_apply_item_name_hint_targets_control_below_badge():
    above = _el("Overlay", x=424, y=44, w=52, h=16, element_id=1)
    badge = _el("Search field", x=94, y=66, w=74, h=16, element_id=2)
    target = _el("Q Search", x=36, y=90, w=70, h=16, element_id=3)
    adjacent = _el("None", x=280, y=110, w=38, h=12, element_id=4)
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Search field",
        box=badge.box,
        confidence=0.9,
        source_element_id=2,
        accessibility_id="vc:item-name:search-field",
    )

    apply_voice_control_overlay_hints(
        _scene(above, badge, target, adjacent),
        [marker],
        include_names=True,
    )

    assert above.whitebox_hint is None
    assert badge.whitebox_hint is None
    assert target.whitebox_hint == WhiteboxHint(accessibility_id="vc:item-name:search-field")
    assert adjacent.whitebox_hint is None


@pytest.mark.smoke
def test_apply_item_name_hint_skips_distant_text_mismatch():
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Dictate",
        box=Box(x=192, y=78, w=46, h=12),
        confidence=0.9,
        source_element_id=2,
        accessibility_id="vc:item-name:dictate",
    )
    search = _el("Q Search", x=36, y=90, w=70, h=16, element_id=3)
    none = _el("None", x=280, y=110, w=38, h=12, element_id=4)

    apply_voice_control_overlay_hints(_scene(search, none), [marker], include_names=True)

    assert search.whitebox_hint is None
    assert none.whitebox_hint is None


@pytest.mark.smoke
def test_apply_item_name_hint_allows_detail_row_label_offset():
    badge = _el("Item Numbers", x=402, y=128, w=86, h=12, element_id=8)
    target = _el("Item Numbers", x=278, y=156, w=96, h=12, element_id=11)
    next_row = _el("Item Names", x=278, y=202, w=82, h=19, element_id=15)
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Item Numbers",
        box=badge.box,
        confidence=0.9,
        source_element_id=8,
        accessibility_id="vc:item-name:item-numbers",
    )

    apply_voice_control_overlay_hints(
        _scene(badge, target, next_row),
        [marker],
        include_names=True,
    )

    assert target.whitebox_hint == WhiteboxHint(accessibility_id="vc:item-name:item-numbers")
    assert next_row.whitebox_hint is None


@pytest.mark.smoke
def test_apply_item_name_hint_targets_control_above_badge():
    target = _el("Wallpaper", x=64, y=442, w=70, h=16, element_id=33)
    badge = _el("Wallpaper)", x=98, y=468, w=64, h=18, element_id=34)
    next_row = _el("Notifications", x=68, y=494, w=82, h=14, element_id=35)
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Wallpaper)",
        box=badge.box,
        confidence=0.9,
        source_element_id=34,
        accessibility_id="vc:item-name:wallpaper",
    )

    apply_voice_control_overlay_hints(
        _scene(target, badge, next_row),
        [marker],
        include_names=True,
    )

    assert target.whitebox_hint == WhiteboxHint(accessibility_id="vc:item-name:wallpaper")
    assert next_row.whitebox_hint is None


@pytest.mark.smoke
def test_apply_item_name_hint_accepts_typo_without_shifting_to_next_row():
    target = _el("Notifications", x=68, y=494, w=82, h=14, element_id=35)
    badge = _el("Notfications", x=92, y=518, w=88, h=14, element_id=36)
    next_row = _el("Sounds", x=68, y=540, w=48, h=14, element_id=37)
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Notfications",
        box=badge.box,
        confidence=0.9,
        source_element_id=36,
        accessibility_id="vc:item-name:notfications",
    )

    apply_voice_control_overlay_hints(
        _scene(target, badge, next_row),
        [marker],
        include_names=True,
    )

    assert target.whitebox_hint == WhiteboxHint(accessibility_id="vc:item-name:notfications")
    assert next_row.whitebox_hint is None


@pytest.mark.smoke
def test_apply_item_name_hint_does_not_shift_to_next_row_when_target_text_absent():
    fused_badge = _el("Came Camera", x=64, y=118, w=90, h=18, element_id=8)
    next_row = _el("Control Centre", x=64, y=164, w=102, h=14, element_id=11)
    marker = VoiceControlOverlayMarker(
        kind="item_name",
        text="Came Camera",
        box=fused_badge.box,
        confidence=0.9,
        source_element_id=8,
        accessibility_id="vc:item-name:came-camera",
    )

    apply_voice_control_overlay_hints(
        _scene(fused_badge, next_row),
        [marker],
        include_names=True,
    )

    assert next_row.whitebox_hint is None
