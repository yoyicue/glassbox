"""Compatibility imports for iOS gesture AssistiveTouch helpers."""

from glassbox.ios.assistive_touch import (
    AssistiveTouchCandidate,
    AssistiveTouchMenuItem,
    AssistiveTouchPrimitive,
    assistive_touch_menu_box,
    assistive_touch_primitive,
    assistive_touch_primitive_catalog,
    assistive_touch_safe_primitives,
    canonical_assistive_touch_label,
    detect_assistive_touch_button,
    find_assistive_touch_menu_item,
    is_assistive_touch_unsafe,
    scene_has_assistive_touch_labels,
)

__all__ = [
    "AssistiveTouchCandidate",
    "AssistiveTouchMenuItem",
    "AssistiveTouchPrimitive",
    "assistive_touch_menu_box",
    "assistive_touch_primitive",
    "assistive_touch_primitive_catalog",
    "assistive_touch_safe_primitives",
    "canonical_assistive_touch_label",
    "detect_assistive_touch_button",
    "find_assistive_touch_menu_item",
    "is_assistive_touch_unsafe",
    "scene_has_assistive_touch_labels",
]
