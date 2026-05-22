"""AssistiveTouch image and menu helpers for iOS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from glassbox.cognition import Box, Scene, UIElement


@dataclass(frozen=True)
class AssistiveTouchCandidate:
    center: tuple[int, int]
    radius: int
    score: float
    method: str

    def to_report(self) -> dict[str, Any]:
        return {
            "center": {"x": self.center[0], "y": self.center[1]},
            "radius": self.radius,
            "score": round(self.score, 3),
            "method": self.method,
        }


@dataclass(frozen=True)
class AssistiveTouchMenuItem:
    label: str
    tap_point: tuple[int, int]
    matched_text: str
    unsafe: bool = False
    method: str = "ocr"
    source_box: tuple[int, int, int, int] | None = None
    menu_box: tuple[int, int, int, int] | None = None

    def to_report(self) -> dict[str, Any]:
        report = {
            "label": self.label,
            "tap_point": {"x": self.tap_point[0], "y": self.tap_point[1]},
            "matched_text": self.matched_text,
            "unsafe": self.unsafe,
            "method": self.method,
        }
        if self.source_box is not None:
            report["source_box"] = _box_report(self.source_box)
        if self.menu_box is not None:
            report["menu_box"] = _box_report(self.menu_box)
            x, y, w, h = self.menu_box
            if w > 0 and h > 0:
                report["relative_to_menu"] = {
                    "x": round((self.tap_point[0] - x) / w, 4),
                    "y": round((self.tap_point[1] - y) / h, 4),
                }
        return report


@dataclass(frozen=True)
class AssistiveTouchPrimitive:
    name: str
    label: str
    path: tuple[str, ...]
    level: str
    effect: str
    safe: bool = True

    def to_report(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "path": list(self.path),
            "level": self.level,
            "effect": self.effect,
            "safe": self.safe,
        }


ASSISTIVE_TOUCH_UNSAFE_LABELS = frozenset({
    "SOS",
    "重新启动",
    "重启",
    "关机",
    "关闭电源",
    "锁定屏幕",
    "锁屏",
    "操作按钮",
    "Lock Screen",
    "Action Button",
    "Restart",
    "Power Off",
    "Emergency SOS",
})

ASSISTIVE_TOUCH_UNSAFE_REASONS: dict[str, str] = {
    "SOS": "system emergency flow; blocked before physical input",
    "重新启动": "destructive system action; blocked before physical input",
    "关机": "destructive system action; blocked before physical input",
    "关闭电源": "destructive system action; blocked before physical input",
    "锁定屏幕": "automation-unsafe lock state; can require manual unlock and break the run",
    "锁屏": "automation-unsafe lock state; can require manual unlock and break the run",
    "操作按钮": "device-specific Action Button behavior; may trigger SOS, camera, shortcut, or another configured action",
}

ASSISTIVE_TOUCH_ALIASES: dict[str, tuple[str, ...]] = {
    "通知中心": ("通知中心", "通知 中心", "Notification Center"),
    "控制中心": ("控制中心", "控制 中心", "Control Center"),
    "App切换器": ("App切换器", "App 切换器", "App Switcher"),
    "设备": ("设备", "Device"),
    "主屏幕": ("主屏幕", "Home"),
    "按住并拖移": ("按住并拖移", "按住 并拖移", "Dwell", "Hold and Drag"),
    "锁定屏幕": ("锁定屏幕", "锁定 屏幕", "Lock Screen"),
    "旋转屏幕": ("旋转屏幕", "旋转 屏幕", "Rotate Screen"),
    "调高音量": ("调高音量", "调高 音量", "Volume Up"),
    "调低音量": ("调低音量", "调低 音量", "Volume Down"),
    "操作按钮": ("操作按钮", "操作 按钮", "Action Button"),
    "更多": ("更多", "More"),
    "截屏": ("截屏", "Screenshot"),
    "摇动": ("摇动", "Shake"),
    "重新启动": ("重新启动", "重启", "Restart"),
    "辅助功能快捷键": ("辅助功能快捷键", "Accessibility Shortcut"),
    "便捷访问": ("便捷访问", "Reachability"),
    "SOS": ("SOS", "Emergency SOS"),
}

_SPLIT_PARTS: dict[str, tuple[str, ...]] = {
    "通知中心": ("通知", "中心"),
    "控制中心": ("控制", "中心"),
    "锁定屏幕": ("锁定", "屏幕"),
    "旋转屏幕": ("旋转", "屏幕"),
    "调高音量": ("调高", "音量"),
    "调低音量": ("调低", "音量"),
    "操作按钮": ("操作", "按钮"),
}

_GRID_RELATIVE_POINTS: dict[str, tuple[float, float]] = {
    # Level 1
    "通知中心": (0.53, 0.25),
    "App切换器": (0.28, 0.40),
    "设备": (0.79, 0.40),
    "按住并拖移": (0.28, 0.66),
    "主屏幕": (0.53, 0.77),
    "控制中心": (0.79, 0.68),
    # Device submenu
    "锁定屏幕": (0.37, 0.25),
    "旋转屏幕": (0.67, 0.25),
    "调高音量": (0.22, 0.53),
    "调低音量": (0.38, 0.75),
    "操作按钮": (0.83, 0.53),
    "更多": (0.67, 0.73),
    # More submenu
    "SOS": (0.28, 0.38),
    "截屏": (0.79, 0.23),
    "摇动": (0.79, 0.50),
    "重新启动": (0.31, 0.77),
    "辅助功能快捷键": (0.53, 0.77),
    "便捷访问": (0.76, 0.77),
}

_GRID_CONTEXT_LABELS: dict[str, tuple[str, ...]] = {
    "level1": ("通知中心", "App切换器", "设备", "按住并拖移", "主屏幕", "控制中心"),
    "device": ("锁定屏幕", "旋转屏幕", "调高音量", "调低音量", "操作按钮", "更多"),
    "more": ("App切换器", "SOS", "截屏", "摇动", "重新启动", "辅助功能快捷键", "便捷访问"),
}

_GRID_CONTEXT_SIZE: dict[str, tuple[int, int]] = {
    "level1": (332, 352),
    "device": (338, 374),
    "more": (338, 350),
}

_MORE_MENU_GRID_RELATIVE_POINTS: dict[str, tuple[float, float]] = {
    # App Switcher appears in both the first-level menu and the More submenu.
    # In More it is the upper-left icon. The label center sits on the boundary
    # with the SOS row on this iOS build, so target the icon center.
    "App切换器": (0.28, 0.12),
}

_ASSISTIVE_TOUCH_SAFE_PRIMITIVES: tuple[AssistiveTouchPrimitive, ...] = (
    AssistiveTouchPrimitive(
        name="assistive_touch.notification_center",
        label="通知中心",
        path=(),
        level="level1",
        effect="open_notification_center",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.app_switcher",
        label="App切换器",
        path=(),
        level="level1",
        effect="open_app_switcher",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.device",
        label="设备",
        path=(),
        level="level1",
        effect="open_device_menu",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.hold_and_drag",
        label="按住并拖移",
        path=(),
        level="level1",
        effect="enter_hold_and_drag",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.home",
        label="主屏幕",
        path=(),
        level="level1",
        effect="go_home",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.control_center",
        label="控制中心",
        path=(),
        level="level1",
        effect="open_control_center",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.rotate_screen",
        label="旋转屏幕",
        path=("设备",),
        level="device",
        effect="open_rotate_screen_menu",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.volume_up",
        label="调高音量",
        path=("设备",),
        level="device",
        effect="volume_up",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.volume_down",
        label="调低音量",
        path=("设备",),
        level="device",
        effect="volume_down",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.more",
        label="更多",
        path=("设备",),
        level="device",
        effect="open_more_menu",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.screenshot",
        label="截屏",
        path=("设备", "更多"),
        level="more",
        effect="take_screenshot",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.shake",
        label="摇动",
        path=("设备", "更多"),
        level="more",
        effect="shake",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.accessibility_shortcut",
        label="辅助功能快捷键",
        path=("设备", "更多"),
        level="more",
        effect="accessibility_shortcut",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.reachability",
        label="便捷访问",
        path=("设备", "更多"),
        level="more",
        effect="reachability",
    ),
    AssistiveTouchPrimitive(
        name="assistive_touch.more_app_switcher",
        label="App切换器",
        path=("设备", "更多"),
        level="more",
        effect="open_app_switcher",
    ),
)

_ASSISTIVE_TOUCH_SAFE_PRIMITIVE_BY_NAME = {
    primitive.name: primitive
    for primitive in _ASSISTIVE_TOUCH_SAFE_PRIMITIVES
}


def detect_assistive_touch_button(img: np.ndarray) -> AssistiveTouchCandidate | None:
    """Return the most likely AssistiveTouch button in a screenshot."""
    if img is None or img.size == 0:
        return None
    gray = _to_gray(img)
    h, w = gray.shape[:2]
    min_dim = min(w, h)
    min_radius = max(13, int(min_dim * 0.035))
    max_radius = max(min_radius + 4, int(min_dim * 0.095))

    candidates: list[AssistiveTouchCandidate] = []
    blurred = cv2.GaussianBlur(gray, (7, 7), 1.5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(32, min_dim // 8),
        param1=80,
        param2=20,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is not None:
        for x, y, r in np.round(circles[0]).astype(int):
            score = _candidate_total_score(img, gray, x, y, r)
            if score > 0:
                candidates.append(AssistiveTouchCandidate((int(x), int(y)), int(r), score, "hough"))

    candidates.extend(_contour_candidates(img, gray, min_radius=min_radius, max_radius=max_radius))
    candidates.extend(_edge_overlay_scan_candidates(img, gray, min_radius=min_radius, max_radius=max_radius))
    candidates = [candidate for candidate in candidates if candidate.score >= 1.0]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.score, reverse=True)
    return _prefer_structural_circle_candidate(candidates, frame_width=w)


def find_assistive_touch_menu_item(scene: Scene, label: str) -> AssistiveTouchMenuItem | None:
    canonical = canonical_assistive_touch_label(label)
    aliases = ASSISTIVE_TOUCH_ALIASES.get(canonical, (canonical,))
    menu_box = assistive_touch_menu_box(scene)
    merged = _find_merged_grid_row_item(scene, canonical, menu_box=menu_box)
    if merged is not None:
        return merged
    more_app_switcher = _find_more_menu_app_switcher_item(scene, canonical, menu_box=menu_box)
    if more_app_switcher is not None:
        return more_app_switcher
    exact = _find_exact_text_item(scene, canonical, aliases, menu_box=menu_box)
    if exact is not None:
        return exact
    split = _find_split_text_item(scene, canonical, menu_box=menu_box)
    if split is not None:
        return split
    fallback = _find_menu_relative_grid_item(scene, canonical, menu_box=menu_box)
    if fallback is not None:
        return fallback
    return None


def canonical_assistive_touch_label(label: str) -> str:
    wanted = _norm(label)
    for canonical, aliases in ASSISTIVE_TOUCH_ALIASES.items():
        if wanted == _norm(canonical):
            return canonical
        if any(wanted == _norm(alias) for alias in aliases):
            return canonical
    return label.strip()


def is_assistive_touch_unsafe(label: str) -> bool:
    canonical = canonical_assistive_touch_label(label)
    canonical_norm = _norm(canonical)
    for unsafe in ASSISTIVE_TOUCH_UNSAFE_LABELS:
        unsafe_norm = _norm(unsafe)
        if unsafe_norm and (canonical_norm == unsafe_norm or unsafe_norm in canonical_norm):
            return True
    return False


def assistive_touch_unsafe_reason(label: str) -> str | None:
    canonical = canonical_assistive_touch_label(label)
    if canonical in ASSISTIVE_TOUCH_UNSAFE_REASONS:
        return ASSISTIVE_TOUCH_UNSAFE_REASONS[canonical]
    canonical_norm = _norm(canonical)
    for unsafe, reason in ASSISTIVE_TOUCH_UNSAFE_REASONS.items():
        unsafe_norm = _norm(unsafe)
        if unsafe_norm and (canonical_norm == unsafe_norm or unsafe_norm in canonical_norm):
            return reason
    return None


def assistive_touch_layout_model() -> dict[str, Any]:
    return {
        "contexts": {
            name: {
                "labels": list(labels),
                "nominal_size": {
                    "w": _GRID_CONTEXT_SIZE[name][0],
                    "h": _GRID_CONTEXT_SIZE[name][1],
                },
            }
            for name, labels in _GRID_CONTEXT_LABELS.items()
        },
        "relative_points": {
            label: {"x": rel[0], "y": rel[1]}
            for label, rel in _GRID_RELATIVE_POINTS.items()
        },
        "context_relative_overrides": {
            "more": {
                label: {"x": rel[0], "y": rel[1]}
                for label, rel in _MORE_MENU_GRID_RELATIVE_POINTS.items()
            },
        },
    }


def assistive_touch_safe_primitives() -> tuple[AssistiveTouchPrimitive, ...]:
    return _ASSISTIVE_TOUCH_SAFE_PRIMITIVES


def assistive_touch_primitive(name: str) -> AssistiveTouchPrimitive | None:
    return _ASSISTIVE_TOUCH_SAFE_PRIMITIVE_BY_NAME.get(name)


def assistive_touch_primitive_catalog() -> dict[str, Any]:
    primitives = [primitive.to_report() for primitive in _ASSISTIVE_TOUCH_SAFE_PRIMITIVES]
    return {
        "schema_version": 1,
        "source": "glassbox.ios.assistive_touch.assistive_touch_safe_primitives",
        "safety_policy": {
            "default": "safe primitives only; unsafe menu labels are excluded and blocked before physical input",
            "unsafe_labels": sorted(ASSISTIVE_TOUCH_UNSAFE_REASONS),
        },
        "count": len(primitives),
        "primitives": primitives,
    }


def scene_has_assistive_touch_labels(scene: Scene, labels: tuple[str, ...]) -> bool:
    return all(find_assistive_touch_menu_item(scene, label) is not None for label in labels)


def assistive_touch_menu_box(scene: Scene) -> tuple[int, int, int, int] | None:
    """Approximate the current AssistiveTouch menu bounds from visible labels.

    The floating menu can appear at different screen positions depending on
    where the button was parked. This box lets callers record a menu-relative
    target point instead of treating a previous absolute coordinate as stable.
    """
    boxes: list[Box] = []
    known = tuple(ASSISTIVE_TOUCH_ALIASES)
    for element in scene.elements:
        text_norm = _norm(" ".join(
            part for part in (str(element.text or ""), str(element.intent_label or "")) if part
        ))
        if not text_norm:
            continue
        if any(_norm(label) in text_norm for label in known):
            boxes.append(element.box)
            continue
        for parts in _SPLIT_PARTS.values():
            if any(_norm(part) in text_norm for part in parts):
                boxes.append(element.box)
                break
    if not boxes:
        return None
    x1 = min(box.x for box in boxes)
    y1 = min(box.y for box in boxes)
    x2 = max(box.x2 for box in boxes)
    y2 = max(box.y2 for box in boxes)
    pad_x = max(20, int((x2 - x1) * 0.25))
    pad_y = max(20, int((y2 - y1) * 0.35))
    viewport = scene.viewport_size
    max_w = viewport[0] if viewport else x2 + pad_x
    max_h = viewport[1] if viewport else y2 + pad_y
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(max_w, x2 + pad_x)
    y2 = min(max_h, y2 + pad_y)
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))


def _find_exact_text_item(
    scene: Scene,
    canonical: str,
    aliases: tuple[str, ...],
    *,
    menu_box: tuple[int, int, int, int] | None,
) -> AssistiveTouchMenuItem | None:
    wanted = [_norm(alias) for alias in aliases if _norm(alias)]
    best: UIElement | None = None
    for element in scene.elements:
        text = str(element.text or "").strip()
        intent = str(element.intent_label or "").strip()
        searchable = " ".join(part for part in (text, intent) if part)
        text_norm = _norm(searchable)
        if not text_norm:
            continue
        if any(text_norm == alias or alias in text_norm for alias in wanted):
            current = str(best.text or best.intent_label or "") if best is not None else ""
            if best is None or len(searchable) < len(current):
                best = element
    if best is None:
        return None
    return AssistiveTouchMenuItem(
        label=canonical,
        tap_point=best.box.center,
        matched_text=str(best.text or best.intent_label or "").strip(),
        unsafe=is_assistive_touch_unsafe(canonical),
        method="ocr_exact",
        source_box=_box_tuple(best.box),
        menu_box=menu_box,
    )


def _find_split_text_item(
    scene: Scene,
    canonical: str,
    *,
    menu_box: tuple[int, int, int, int] | None,
) -> AssistiveTouchMenuItem | None:
    parts = _SPLIT_PARTS.get(canonical)
    if not parts:
        return None
    matched: list[UIElement] = []
    for part in parts:
        part_norm = _norm(part)
        candidates = [
            element for element in scene.elements
            if part_norm and part_norm in _norm(str(element.text or ""))
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda el: (el.box.y, el.box.x))
        if matched:
            anchor = matched[-1].box.center
            candidates.sort(key=lambda el: abs(el.box.center[0] - anchor[0]) + abs(el.box.center[1] - anchor[1]))
        matched.append(candidates[0])
    if len(matched) != len(parts):
        return None
    xs = [el.box.x for el in matched]
    ys = [el.box.y for el in matched]
    x2s = [el.box.x + el.box.w for el in matched]
    y2s = [el.box.y + el.box.h for el in matched]
    tap_point = ((min(xs) + max(x2s)) // 2, (min(ys) + max(y2s)) // 2)
    return AssistiveTouchMenuItem(
        label=canonical,
        tap_point=tap_point,
        matched_text=" ".join(str(el.text or "").strip() for el in matched),
        unsafe=is_assistive_touch_unsafe(canonical),
        method="ocr_split",
        source_box=(min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys)),
        menu_box=menu_box,
    )


def _find_merged_grid_row_item(
    scene: Scene,
    canonical: str,
    *,
    menu_box: tuple[int, int, int, int] | None,
) -> AssistiveTouchMenuItem | None:
    # Apple Vision sometimes merges the three bottom labels in the "More"
    # submenu into one wide row. Split that row into thirds to recover precise
    # hit points for Restart / Accessibility Shortcut / Reachability.
    row_items = ("重新启动", "辅助功能快捷键", "便捷访问")
    if canonical not in row_items:
        return None
    for element in scene.elements:
        text = str(element.text or "").strip()
        text_norm = _norm(text)
        if not all(_norm(item) in text_norm for item in row_items):
            continue
        index = row_items.index(canonical)
        x = int(element.box.x + element.box.w * ((index + 0.5) / len(row_items)))
        y = element.box.center[1]
        return AssistiveTouchMenuItem(
            label=canonical,
            tap_point=(x, y),
            matched_text=text,
            unsafe=is_assistive_touch_unsafe(canonical),
            method="ocr_merged_grid_row",
            source_box=_box_tuple(element.box),
            menu_box=menu_box,
        )
    return None


def _find_more_menu_app_switcher_item(
    scene: Scene,
    canonical: str,
    *,
    menu_box: tuple[int, int, int, int] | None,
) -> AssistiveTouchMenuItem | None:
    if canonical != "App切换器" or not _looks_like_more_menu(scene):
        return None
    sos_element = _find_text_element(scene, "SOS")
    if sos_element is not None:
        viewport = scene.viewport_size
        reference_h = viewport[1] if viewport else 956
        x = sos_element.box.center[0]
        y = max(0, round(sos_element.box.center[1] - reference_h * 0.11))
    elif menu_box is not None:
        x0, y0, w, h = menu_box
        x = round(x0 + w * 0.28)
        y = round(y0 + h * 0.08)
    else:
        return None
    return AssistiveTouchMenuItem(
        label=canonical,
        tap_point=(x, y),
        matched_text=str(sos_element.text or "") if sos_element is not None else "",
        unsafe=is_assistive_touch_unsafe(canonical),
        method="more_menu_app_switcher_grid",
        source_box=_box_tuple(sos_element.box) if sos_element is not None else None,
        menu_box=menu_box,
    )


def _find_menu_relative_grid_item(
    scene: Scene,
    canonical: str,
    *,
    menu_box: tuple[int, int, int, int] | None,
) -> AssistiveTouchMenuItem | None:
    """Fallback for Apple's partial OCR on known AssistiveTouch grids.

    This does not use a previous absolute coordinate. It only fires when the
    current scene already exposes enough AssistiveTouch labels to estimate the
    current menu box, then maps a known AssistiveTouch slot to that box.
    """
    rel = _menu_relative_grid_point(scene, canonical)
    if rel is None:
        return None
    inferred_from_anchor = False
    if menu_box is None:
        inferred = _infer_assistive_touch_grid_box(scene)
        if inferred is None:
            return None
        menu_box = inferred
        inferred_from_anchor = True
    elif menu_box[2] < 250 or menu_box[3] < 200:
        inferred = _infer_assistive_touch_grid_box(scene)
        if inferred is not None:
            menu_box = inferred
            inferred_from_anchor = True
    label_hits = 0
    for element in scene.elements:
        text_norm = _norm(" ".join(
            part for part in (str(element.text or ""), str(element.intent_label or "")) if part
        ))
        if not text_norm:
            continue
        if any(_norm(label) in text_norm for label in ASSISTIVE_TOUCH_ALIASES):
            label_hits += 1
            continue
        if any(_norm(part) in text_norm for parts in _SPLIT_PARTS.values() for part in parts):
            label_hits += 1
    if label_hits < 3 and not inferred_from_anchor:
        return None
    x, y, w, h = menu_box
    tap_point = (round(x + w * rel[0]), round(y + h * rel[1]))
    return AssistiveTouchMenuItem(
        label=canonical,
        tap_point=tap_point,
        matched_text="",
        unsafe=is_assistive_touch_unsafe(canonical),
        method="menu_relative_grid",
        source_box=None,
        menu_box=menu_box,
    )


def _find_text_element(scene: Scene, label: str) -> UIElement | None:
    wanted = _norm(label)
    for element in scene.elements:
        text_norm = _norm(" ".join(
            part for part in (str(element.text or ""), str(element.intent_label or "")) if part
        ))
        if wanted and (text_norm == wanted or wanted in text_norm):
            return element
    return None


def _infer_assistive_touch_grid_box(scene: Scene) -> tuple[int, int, int, int] | None:
    context = _assistive_touch_grid_context(scene)
    if context is None:
        return None
    labels = _GRID_CONTEXT_LABELS[context]
    nominal_w, nominal_h = _GRID_CONTEXT_SIZE[context]
    for label in labels:
        rel = _menu_relative_grid_point_for_context(context, label)
        if rel is None:
            continue
        anchor = _find_grid_anchor_element(scene, label)
        if anchor is None:
            continue
        center_x, center_y = anchor.box.center
        x = round(center_x - nominal_w * rel[0])
        y = round(center_y - nominal_h * rel[1])
        viewport = scene.viewport_size
        max_w = viewport[0] if viewport else x + nominal_w
        max_h = viewport[1] if viewport else y + nominal_h
        x = max(0, min(x, max(0, max_w - nominal_w)))
        y = max(0, min(y, max(0, max_h - nominal_h)))
        return (x, y, nominal_w, nominal_h)
    return None


def _assistive_touch_grid_context(scene: Scene) -> str | None:
    if _looks_like_more_menu(scene):
        return "more"
    if _scene_has_any_label(scene, _GRID_CONTEXT_LABELS["device"]):
        return "device"
    if _scene_has_any_label(scene, _GRID_CONTEXT_LABELS["level1"]):
        return "level1"
    return None


def _scene_has_any_label(scene: Scene, labels: tuple[str, ...]) -> bool:
    return any(_find_grid_anchor_element(scene, label) is not None for label in labels)


def _menu_relative_grid_point_for_context(context: str, label: str) -> tuple[float, float] | None:
    if context == "more":
        return _MORE_MENU_GRID_RELATIVE_POINTS.get(label) or _GRID_RELATIVE_POINTS.get(label)
    return _GRID_RELATIVE_POINTS.get(label)


def _find_grid_anchor_element(scene: Scene, label: str) -> UIElement | None:
    canonical = canonical_assistive_touch_label(label)
    aliases = ASSISTIVE_TOUCH_ALIASES.get(canonical, (canonical,))
    wanted = [_norm(alias) for alias in aliases if _norm(alias)]
    for element in scene.elements:
        text_norm = _norm(" ".join(
            part for part in (str(element.text or ""), str(element.intent_label or "")) if part
        ))
        if not text_norm:
            continue
        if any(text_norm == alias or alias in text_norm for alias in wanted):
            return element
    parts = _SPLIT_PARTS.get(canonical)
    if not parts:
        return None
    part_hits = [
        element for element in scene.elements
        if any(_norm(part) in _norm(str(element.text or "")) for part in parts)
    ]
    return part_hits[0] if part_hits else None


def _menu_relative_grid_point(scene: Scene, canonical: str) -> tuple[float, float] | None:
    if _looks_like_more_menu(scene):
        more_rel = _MORE_MENU_GRID_RELATIVE_POINTS.get(canonical)
        if more_rel is not None:
            return more_rel
    return _GRID_RELATIVE_POINTS.get(canonical)


def _looks_like_more_menu(scene: Scene) -> bool:
    more_markers = ("SOS", "截屏", "摇动", "重新启动", "辅助功能快捷键", "便捷访问")
    texts = [
        _norm(" ".join(part for part in (str(element.text or ""), str(element.intent_label or "")) if part))
        for element in scene.elements
    ]
    hits = 0
    for marker in more_markers:
        marker_norm = _norm(marker)
        if any(marker_norm and marker_norm in text for text in texts):
            hits += 1
    return hits >= 2


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if not ch.isspace() and ch not in "|·•.＞>")


def _box_tuple(box: Box) -> tuple[int, int, int, int]:
    return (box.x, box.y, box.w, box.h)


def _box_report(box: tuple[int, int, int, int]) -> dict[str, int]:
    x, y, w, h = box
    return {"x": x, "y": y, "w": w, "h": h}


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _candidate_score(gray: np.ndarray, x: int, y: int, radius: int) -> float:
    h, w = gray.shape[:2]
    if radius <= 0 or x < radius or y < radius or x >= w - radius or y >= h - radius:
        return 0.0
    edge_distance = min(x, y, w - x, h - y)
    edge_limit = min(w, h) * 0.24
    if edge_distance > edge_limit:
        return 0.0
    patch = gray[max(0, y - radius):min(h, y + radius), max(0, x - radius):min(w, x + radius)]
    if patch.size == 0:
        return 0.0
    contrast = float(np.percentile(patch, 90) - np.percentile(patch, 10))
    if contrast < 18:
        return 0.0
    edge_score = max(0.0, 1.0 - edge_distance / edge_limit)
    edge_gap = min(x - radius, y - radius, w - (x + radius), h - (y + radius))
    edge_contact_limit = min(w, h) * 0.08
    edge_contact_score = max(0.0, 1.0 - max(0.0, edge_gap) / max(1.0, edge_contact_limit))
    contrast_score = min(1.0, contrast / 90.0)
    size_score = 1.0 - min(0.6, abs(radius - min(w, h) * 0.065) / max(1.0, min(w, h) * 0.09))
    return edge_score * 2.5 + edge_contact_score * 2.6 + contrast_score + size_score * 1.8


def _candidate_appearance_score(img: np.ndarray, x: int, y: int, radius: int) -> float:
    h, w = img.shape[:2]
    if radius <= 0 or x < radius or y < radius or x >= w - radius or y >= h - radius:
        return 0.0
    patch = img[max(0, y - radius):min(h, y + radius), max(0, x - radius):min(w, x + radius)]
    if patch.size == 0 or patch.ndim != 3:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    sat_p75 = float(np.percentile(hsv[:, :, 1], 75))
    val_std = float(hsv[:, :, 2].std())
    low_saturation = max(0.0, 1.0 - max(0.0, sat_p75 - 45.0) / 90.0)
    smooth_value = max(0.0, 1.0 - val_std / 85.0)
    return low_saturation * 0.8 + smooth_value * 0.4


def _contour_candidates(
    img: np.ndarray,
    gray: np.ndarray,
    *,
    min_radius: int,
    max_radius: int,
) -> list[AssistiveTouchCandidate]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[AssistiveTouchCandidate] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area <= 0:
            continue
        (x, y), radius_f = cv2.minEnclosingCircle(contour)
        radius = round(radius_f)
        if radius < min_radius or radius > max_radius:
            continue
        circle_area = np.pi * radius_f * radius_f
        circularity = float(area / circle_area) if circle_area else 0.0
        if circularity < 0.45:
            continue
        center_x = round(x)
        center_y = round(y)
        base_score = _candidate_score(gray, center_x, center_y, radius)
        if base_score <= 0:
            continue
        score = base_score + _candidate_appearance_score(img, center_x, center_y, radius)
        score += _candidate_bubble_signature_score(img, gray, center_x, center_y, radius)
        candidates.append(
            AssistiveTouchCandidate(
                (center_x, center_y),
                radius,
                score + min(1.0, circularity),
                "contour",
            )
        )
    return candidates


def _edge_overlay_scan_candidates(
    img: np.ndarray,
    gray: np.ndarray,
    *,
    min_radius: int,
    max_radius: int,
) -> list[AssistiveTouchCandidate]:
    """Recover translucent edge-docked buttons that Hough/contours miss."""
    h, w = gray.shape[:2]
    candidates: list[AssistiveTouchCandidate] = []
    y_start = max(min_radius + 2, int(h * 0.12))
    y_stop = min(h - min_radius - 2, int(h * 0.90))
    if y_stop <= y_start:
        return candidates
    for radius in range(min_radius, max_radius + 1, max(4, (max_radius - min_radius) // 3 or 4)):
        step = max(4, radius // 3)
        left_stop = min(radius + 20, w - radius)
        right_start = max(radius, w - radius - 20)
        xs = [*range(radius + 2, left_stop, 4), *range(right_start, w - radius - 1, 4)]
        for x in xs:
            for y in range(y_start, y_stop, step):
                score = _candidate_total_score(img, gray, x, y, radius)
                if score < 3.8:
                    continue
                candidates.append(
                    AssistiveTouchCandidate(
                        (int(x), int(y)),
                        int(radius),
                        score,
                        "edge_scan",
                    )
                )
    return candidates


def _candidate_total_score(img: np.ndarray, gray: np.ndarray, x: int, y: int, radius: int) -> float:
    base = _candidate_score(gray, x, y, radius)
    if base <= 0:
        return 0.0
    return (
        base
        + _candidate_appearance_score(img, x, y, radius)
        + _candidate_bubble_signature_score(img, gray, x, y, radius)
    )


def _prefer_structural_circle_candidate(
    candidates: list[AssistiveTouchCandidate],
    *,
    frame_width: int | None = None,
) -> AssistiveTouchCandidate:
    best = candidates[0]
    if frame_width:
        right_edge = frame_width * 0.78
        left_edge = frame_width * 0.22
        if best.center[0] <= left_edge:
            right_candidates = [
                candidate
                for candidate in candidates
                if candidate.center[0] >= right_edge and candidate.score >= best.score - 1.2
            ]
            if right_candidates:
                return max(
                    right_candidates,
                    key=lambda candidate: candidate.score + min(candidate.radius, 40) / 80.0,
                )
    if best.method != "edge_scan":
        return best
    for candidate in candidates:
        if candidate.method == "edge_scan":
            continue
        dx = candidate.center[0] - best.center[0]
        dy = candidate.center[1] - best.center[1]
        if (dx * dx + dy * dy) ** 0.5 > max(best.radius, candidate.radius) * 1.8:
            continue
        if candidate.score >= best.score - 1.5:
            return candidate
    return best


def _candidate_bubble_signature_score(
    img: np.ndarray,
    gray: np.ndarray,
    x: int,
    y: int,
    radius: int,
) -> float:
    h, w = gray.shape[:2]
    if radius <= 0 or x < radius or y < radius or x >= w - radius or y >= h - radius:
        return 0.0
    yy, xx = np.ogrid[:h, :w]
    distance = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    inner = gray[distance < radius * 0.45]
    middle = gray[(distance >= radius * 0.45) & (distance < radius * 0.75)]
    if inner.size == 0 or middle.size == 0:
        return 0.0

    patch = img[max(0, y - radius):min(h, y + radius), max(0, x - radius):min(w, x + radius)]
    if patch.size == 0 or patch.ndim != 3:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    sat_p75 = float(np.percentile(hsv[:, :, 1], 75))
    val_std = float(hsv[:, :, 2].std())

    center_highlight = max(0.0, min(1.0, (float(inner.mean()) - float(middle.mean())) / 16.0))
    dark_middle_ring = max(0.0, min(1.0, (150.0 - float(middle.mean())) / 90.0)) * center_highlight
    low_saturation = max(0.0, 1.0 - max(0.0, sat_p75 - 18.0) / 45.0)
    saturated_icon_penalty = max(0.0, (sat_p75 - 80.0) / 80.0)
    smooth_value = max(0.0, 1.0 - val_std / 45.0)
    ragged_large_object_penalty = max(0.0, (val_std - 34.0) / 18.0)
    return (
        center_highlight * 1.4
        + dark_middle_ring * 3.2
        + low_saturation * 0.8
        + smooth_value * 0.7
        - saturated_icon_penalty * 2.5
        - ragged_large_object_penalty
    )
