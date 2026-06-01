"""iOS SpringBoard helpers.

These helpers deliberately use only the glassbox perception/action surface:
OCR elements, Home, horizontal swipes, and taps. They do not rely on Settings
URLs or host-side app activation.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from loguru import logger

from glassbox.boundaries import AppLaunchTarget
from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.text_match import fuzzy_ratio, text_contains, texts_match
from glassbox.ios.default_apps import (
    DefaultAppLaunchProfile,
    default_launch_profile_for_labels,
    verify_default_app_opened,
)
from glassbox.ios.scene import classify_ios_scene
from glassbox.ios.weather_surface import looks_like_weather_app_surface

HOME_SEARCH_LABELS = ("搜索", "Search")
HOME_FOLDER_LABELS = ("其他", "工具", "实用工具", "Utilities", "Other")
SPOTLIGHT_MARKERS = ("最佳搜索结果", "Top Hit", "Siri建议", "Siri Suggestions", "在App中搜索", "Search in App")
ASSISTIVE_TOUCH_MENU_LABELS = (
    "App Switcher", "Notification Centre", "Notification Center",
    "Notification", "Device", "Gestures",
    "Control Centre", "Control Center", "Control", "Centre",
)
NON_HOME_APP_MARKERS = (
    "服务有问题", "服务运行中", "Mac 大脑", "最近活动", "停止服务",
    "桥已连接", "已连接 8C1822", "标定",
    "World Clock", "Alarms", "Stopwatch", "Timers",
)
_MOD_META_LEFT = 0x08
_KEY_A = 0x04
_KEY_BACKSPACE = 0x2A
_KEY_SPACE = 0x2C
_KEY_RETURN = 0x28


@dataclass(frozen=True)
class SpringboardIcon:
    """A likely iOS Home screen icon label and the tap point for its icon."""

    element: UIElement
    tap_point: tuple[int, int]


def _scene_size(scene: Scene, viewport_size: tuple[int, int] | None) -> tuple[int, int]:
    if viewport_size is not None:
        return viewport_size
    if scene.viewport_size is not None:
        return scene.viewport_size
    width = max((e.box.x2 for e in scene.elements), default=440)
    height = max((e.box.y2 for e in scene.elements), default=956)
    return max(width, 440), max(height, 956)


def _text(el: UIElement) -> str:
    return (el.text or "").strip()


def _classify_scene_for_phone(phone, scene: Scene):
    model = str(getattr(getattr(phone, "device_geometry", None), "model", "") or "")
    if model.lower().replace("-", "_").startswith("ipad"):
        try:
            from glassbox.ipados.scene import classify_ipados_scene

            return classify_ipados_scene(scene, viewport_size=_viewport_size(phone))
        except Exception:
            pass
    return classify_ios_scene(scene, viewport_size=_viewport_size(phone))


def _matches(text: str, labels: Iterable[str], *, fuzzy: float = 0.72) -> bool:
    for label in labels:
        if texts_match(text, label) or text_contains(text, label):
            return True
        if fuzzy_ratio(text, label) >= fuzzy:
            return True
    return False


def _icon_label_candidates(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> list[UIElement]:
    """Return OCR labels whose geometry looks like Home screen app labels."""
    w, h = _scene_size(scene, viewport_size)
    assistive_menu_bounds = _assistive_touch_menu_bounds(scene, viewport_size=(w, h))
    candidates: list[UIElement] = []
    for el in scene.elements:
        text = _text(el)
        if not text or el.type in {"nav_back", "status_bar"}:
            continue
        if assistive_menu_bounds is not None and _point_in_bounds(el.box.center, assistive_menu_bounds):
            continue
        _cx, cy = el.box.center
        min_label_y = h * 0.10
        if cy < min_label_y or cy > h * 0.98:
            continue
        if el.box.w > w * 0.55 or el.box.h > h * 0.06:
            continue
        if len(text) > 18:
            continue
        if _looks_like_home_widget_text(text, viewport_width=w):
            continue
        candidates.append(el)
    return candidates


def _assistive_touch_menu_bounds(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    """Bounding box for the AssistiveTouch menu overlay, if visible."""
    _w, h = viewport_size
    hits = [
        el for el in scene.elements
        if _matches(_text(el), ASSISTIVE_TOUCH_MENU_LABELS, fuzzy=0.86)
        and el.box.center[1] >= h * 0.45
    ]
    matched = {
        label for label in ASSISTIVE_TOUCH_MENU_LABELS
        if any(_matches(_text(el), (label,), fuzzy=0.86) for el in hits)
    }
    if len(matched) < 4:
        return None
    x1 = min(el.box.x for el in hits)
    y1 = min(el.box.y for el in hits)
    x2 = max(el.box.x2 for el in hits)
    y2 = max(el.box.y2 for el in hits)
    return (max(0, x1 - 64), max(0, y1 - 96), x2 + 64, y2 + 64)


def _point_in_bounds(point: tuple[int, int], bounds: tuple[int, int, int, int]) -> bool:
    x, y = point
    x1, y1, x2, y2 = bounds
    return x1 <= x <= x2 and y1 <= y <= y2


def _looks_like_home_widget_text(text: str, *, viewport_width: int) -> bool:
    if viewport_width < 600:
        return False
    stripped = text.strip()
    if not stripped:
        return True
    if not (stripped[0].isalnum() or "\u4e00" <= stripped[0] <= "\u9fff"):
        return True
    compact = stripped.replace(" ", "")
    if compact.replace(":", "").isdigit():
        return True
    if compact.rstrip("%").isdigit() and "%" in compact:
        return True
    if "°" in stripped:
        return True
    if "km/h" in stripped:
        return True
    if stripped in {"Sunny", "Cloudy", "Drizzle", "Rain", "Showers", "Windy", "Now"}:
        return True
    if stripped in {"Today", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
        return True
    if stripped.upper() in {"AM", "PM", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}:
        return True
    return stripped in {"No Events Today", "No Notes"}


def _looks_like_today_widget_surface(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None,
) -> bool:
    """Return True for iPad Today/widget pages that are Home but not icon pages."""
    texts = [_text(el) for el in scene.elements if _text(el)]
    if any(text in {"SUGGESTED", "Suggested"} for text in texts):
        return True
    if any("Search for a city" in text or "10-DAY FORECAST" in text for text in texts):
        return True
    weatherish = sum(1 for text in texts if "°" in text or text in {"Sunny", "Cloudy", "Drizzle"})
    return weatherish >= 3


def _looks_like_ipad_home_widget_page(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> bool:
    w, _h = viewport_size
    if w < 600:
        return False
    texts = [_text(el) for el in scene.elements if _text(el)]
    if not texts:
        return False
    joined = "\n".join(texts)
    has_widget_evidence = (
        any("°" in text for text in texts)
        or any(text in {"No Notes", "无备忘录", "No Events Today", "今天无日程"} for text in texts)
        or any(marker in joined for marker in ("Daxing", "Weather", "天气", "Notes", "备忘录", "Calendar", "日历"))
    )
    if not has_widget_evidence:
        return False
    default_icon_hits = 0
    icon_labels = (
        "App Store", "Settings", "Camera", "Files", "Maps", "Books", "Videos", "FaceTime",
        "设置", "相机", "文件", "地图", "图书", "视频", "FaceTime 通话",
    )
    for text in texts:
        if any(_matches(text, (label,), fuzzy=0.78) for label in icon_labels):
            default_icon_hits += 1
    if default_icon_hits < 3:
        return False
    app_store_chrome = sum(1 for marker in ("Today", "Games", "Apps", "Arcade") if marker in texts)
    return app_store_chrome < 2


def _has_strong_icon_grid(labels: list[UIElement], *, viewport_size: tuple[int, int]) -> bool:
    w, h = viewport_size
    if len(labels) < 6:
        return False
    xs = [el.box.center[0] for el in labels]
    ys = [el.box.center[1] for el in labels]
    spread_x = max(xs) - min(xs)
    row_count = len({round(y / max(1, h * 0.11)) for y in ys})
    col_count = len({round(x / max(1, w * 0.18)) for x in xs})
    return spread_x >= w * 0.45 and row_count >= 3 and col_count >= 3


def is_ios_home_screen(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
    strict_springboard: bool = False,
) -> bool:
    """Heuristic recognizer for iOS SpringBoard Home pages.

    Settings pages are mostly left-aligned list rows. Home pages expose short
    app labels spread across multiple columns, often with the bottom Search
    affordance. This is intentionally conservative: false is better than
    tapping a Settings row as if it were a Home icon.

    ``strict_springboard`` (CUQ-2.2): when True, a bare ``springboard``
    classification is NOT trusted on its own — it must be corroborated by a real
    icon grid (or the structural spread checks below). This closes the
    false-positive where a Settings detail page the single-frame classifier
    mislabels ``springboard`` is treated as Home (so SpringBoard nav taps a
    settings row as an app icon). Default off keeps today's behavior.
    """
    w, h = _scene_size(scene, viewport_size)
    if any(el.type == "nav_back" for el in scene.elements):
        return False
    if any(_matches(_text(el), NON_HOME_APP_MARKERS, fuzzy=0.78) for el in scene.elements):
        return False
    if looks_like_weather_app_surface(scene):
        return False
    platform_kind = str(getattr(scene, "platform_scene_kind", "") or "")
    if platform_kind == "app_library":
        return True
    if platform_kind == "springboard" and not strict_springboard:
        return True
    if platform_kind.startswith("settings"):
        return False

    labels = _icon_label_candidates(scene, viewport_size=(w, h))
    has_spotlight_marker = _looks_like_spotlight_results(scene)
    if not has_spotlight_marker and _looks_like_ipad_home_widget_page(scene, viewport_size=(w, h)):
        return True
    if not has_spotlight_marker and _has_strong_icon_grid(labels, viewport_size=(w, h)):
        return True

    classified = classify_ios_scene(scene, viewport_size=(w, h))
    if classified.kind == "app_library":
        return True
    if classified.kind in {
        "settings_root",
        "settings_search_results",
        "settings_detail",
        "settings_blocked_safety",
        "system_search",
    }:
        return False
    if classified.kind == "springboard" and not strict_springboard:
        return True
    if not has_spotlight_marker and _looks_like_ipad_home_widget_page(scene, viewport_size=(w, h)):
        return True

    if len(labels) < 3:
        return False

    xs = [el.box.center[0] for el in labels]
    ys = [el.box.center[1] for el in labels]
    spread_x = max(xs) - min(xs)
    row_count = len({round(y / max(1, h * 0.11)) for y in ys})
    bottom_search = any(
        _matches(_text(el), HOME_SEARCH_LABELS, fuzzy=0.78)
        and el.box.center[1] > h * 0.78
        for el in scene.elements
    )

    if bottom_search and spread_x >= w * 0.25:
        return True
    return spread_x >= w * 0.40 and row_count >= 2


def find_springboard_icon(
    scene: Scene,
    labels: Iterable[str],
    *,
    viewport_size: tuple[int, int] | None = None,
    fuzzy: float = 0.72,
) -> SpringboardIcon | None:
    """Find an app icon by its visible Home screen label."""
    if any(_matches(_text(el), NON_HOME_APP_MARKERS, fuzzy=0.78) for el in scene.elements):
        return None

    w, h = _scene_size(scene, viewport_size)
    best: UIElement | None = None
    best_ratio = fuzzy
    for el in _icon_label_candidates(scene, viewport_size=(w, h)):
        text = _text(el)
        for label in labels:
            if texts_match(text, label) or text_contains(text, label):
                best = el
                best_ratio = 1.0
                break
            ratio = fuzzy_ratio(text, label)
            if ratio >= best_ratio:
                best = el
                best_ratio = ratio
        if best is el and best_ratio >= 1.0:
            break
    if best is None:
        return None

    cx, _ = best.box.center
    # OCR sees the label below the icon; tap the icon cell above the label.
    if w >= 600:
        offset = max(28, int(h * 0.030)) if best.box.center[1] > h * 0.75 else max(28, int(h * 0.040))
    else:
        offset = max(70, int(h * 0.09)) if best.box.center[1] > h * 0.75 else max(28, int(h * 0.045))
    tap_y = max(int(h * 0.05), best.box.y - offset)
    tap_x = min(max(cx, int(w * 0.05)), int(w * 0.95))
    return SpringboardIcon(element=best, tap_point=(tap_x, tap_y))


def springboard_signature(scene: Scene) -> tuple[tuple[str, int, int], ...]:
    """Stable enough page signature for detecting Home page boundaries."""
    items: list[tuple[str, int, int]] = []
    for el in scene.elements:
        text = _text(el)
        if not text:
            continue
        cx, cy = el.box.center
        items.append((text, round(cx / 20), round(cy / 20)))
    return tuple(items[:20])


def _viewport_size(phone) -> tuple[int, int] | None:
    try:
        return phone.viewport_size()
    except Exception:
        return None


def _strict_home(phone) -> bool:
    """CUQ-2.2: whether home recognition should require icon-grid corroboration
    for a bare 'springboard' classification (opt-in via config)."""
    return bool(getattr(phone, "require_home_icon_grid_enabled", False))


def _perceive_after_settle(phone, settle_s: float) -> Scene:
    time.sleep(settle_s)
    phone.invalidate_perceive_cache()
    return phone.perceive()


def _current_home_scene(phone) -> Scene | None:
    try:
        scene = phone.perceive()
    except Exception:
        return None
    return scene if is_ios_home_screen(scene, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)) else None


def _ensure_home_scene(phone, settle_s: float, *, attempts: int = 1) -> Scene:
    scene = _current_home_scene(phone)
    if scene is not None:
        return scene
    # A single home() can fail to reach a clean springboard from a dirty entry
    # state (a foregrounded third-party app, a modal/permission sheet). Each
    # press backgrounds the current surface, so retry — but only while a press
    # keeps changing the screen: once home() stops making progress, more presses
    # won't help, so fall through to the caller's wait/spotlight fallback.
    scene = None
    prev_sig = None
    for i in range(max(1, attempts)):
        phone.home()
        scene = _perceive_after_settle(phone, settle_s)
        if is_ios_home_screen(scene, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
            if i:
                print(f"[sb] reached Home after {i + 1} home() presses", flush=True)
            return scene
        sig = springboard_signature(scene)
        if sig == prev_sig:
            break  # another home() press did not change the screen
        prev_sig = sig
    return scene


def _tap_icon_if_visible(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    settle_s: float,
) -> bool:
    labels = tuple(labels)
    icon = find_springboard_icon(scene, labels, viewport_size=_viewport_size(phone))
    if icon is None:
        print(f"[sb] ocr: no icon for {labels}", flush=True)
        return False
    print(f"[sb] ocr: tap {labels} @{icon.tap_point}", flush=True)
    phone.tap_xy(*icon.tap_point)
    scene_after_tap = _perceive_after_settle(phone, settle_s)
    if is_ios_home_screen(scene_after_tap, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
        print("[sb] ocr: tap stayed on Home", flush=True)
        return False
    opened = _opened_expected_app_or_recover(phone, scene_after_tap, labels, settle_s=settle_s)
    print(f"[sb] ocr: opened_expected={opened}", flush=True)
    return opened


# VLM icon-map builds are the only paid step in a SpringBoard scan. A multi-page
# sweep would otherwise call build_icon_map once per Settings-less page (observed
# ~1 build/page). Cap builds per cold-start scan; cache hits are free and do not
# count. Reset at the start of each open_app_from_springboard scan.
_ICON_MAP_BUILD_BUDGET = 4
_icon_map_builds = 0


def _reset_icon_map_build_budget() -> None:
    global _icon_map_builds
    _icon_map_builds = 0


def _tap_icon_via_map_if_visible(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    icon_map,
    settle_s: float,
) -> bool:
    """VLM-icon-map fallback for ``_tap_icon_if_visible``.

    OCR cannot read Home icon labels reliably; this detects icon cells, has the
    VLM name them (cached per layout), and taps the matched cell. A tap that
    fails to leave Home invalidates the cached map for that layout.
    """
    labels = tuple(labels)
    if icon_map is None or getattr(phone, "kimi", None) is None:
        print(f"[sb] vlm-map: disabled (icon_map={icon_map is not None}, "
              f"kimi={getattr(phone, 'kimi', None) is not None})", flush=True)
        return False
    viewport = _viewport_size(phone)
    if not is_ios_home_screen(scene, viewport_size=viewport, strict_springboard=True):
        print("[sb] vlm-map: skipped; scene is not a strict Home icon grid", flush=True)
        return False
    if _looks_like_today_widget_surface(scene, viewport_size=viewport):
        print("[sb] vlm-map: skipped; widget surface is not an app icon page", flush=True)
        return False
    from glassbox.cognition.icon_detect import detect_icons_voted
    from glassbox.ios.springboard_map import build_icon_map, match_entry

    try:
        frame = phone.snapshot()
    except Exception:
        print("[sb] vlm-map: snapshot failed", flush=True)
        return False
    text_boxes = tuple(
        (e.box.x, e.box.y, e.box.w, e.box.h) for e in scene.elements if e.box
    )
    regions = detect_icons_voted([frame.img], text_boxes=text_boxes, min_frames=1)
    if not regions:
        print("[sb] vlm-map: no icon regions detected", flush=True)
        return False

    global _icon_map_builds
    entries = icon_map.get(regions)
    print(f"[sb] vlm-map: regions={len(regions)} cache={'hit' if entries is not None else 'miss'}", flush=True)
    if entries is None:
        if _icon_map_builds >= _ICON_MAP_BUILD_BUDGET:
            print(f"[sb] vlm-map: build budget exhausted ({_ICON_MAP_BUILD_BUDGET})", flush=True)
            return False
        _icon_map_builds += 1
        try:
            key, entries = build_icon_map([frame.img], vlm=phone.kimi, text_boxes=text_boxes)
        except Exception as exc:
            logger.warning(f"springboard icon-map build failed: {exc}")
            print(f"[sb] vlm-map: build failed: {exc}", flush=True)
            return False
        icon_map.put(key, entries)
        print(f"[sb] vlm-map: built {len(entries)} entries: {[e.app for e in entries][:10]}", flush=True)

    entry = match_entry(entries, labels)
    if entry is None:
        print(f"[sb] vlm-map: no match for {labels} among {[e.app for e in entries][:10]}", flush=True)
        return False
    print(f"[sb] vlm-map: tap {entry.app!r} @{entry.center}", flush=True)
    phone.tap_xy(*entry.center)
    after = _perceive_after_settle(phone, settle_s)
    if is_ios_home_screen(after, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
        print("[sb] vlm-map: tap stayed on Home (invalidate)", flush=True)
        icon_map.invalidate(regions)        # tap stayed on Home → map drifted
        return False
    if not _opened_expected_app_or_recover(phone, after, labels, settle_s=settle_s):
        print("[sb] vlm-map: opened non-target (invalidate)", flush=True)
        icon_map.invalidate(regions)
        return False
    print(f"[sb] vlm-map: opened {entry.app!r} OK", flush=True)
    return True


def _tap_icon_any(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    icon_map,
    settle_s: float,
) -> bool:
    """Tap an app icon: OCR-label path first, then the VLM icon-map fallback."""
    if _tap_icon_if_visible(phone, scene, labels, settle_s=settle_s):
        return True
    return _tap_icon_via_map_if_visible(
        phone, scene, labels, icon_map=icon_map, settle_s=settle_s)


def _tap_target_inside_home_folder_if_visible(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    settle_s: float,
    attempted_home_signatures: set[tuple[tuple[str, int, int], ...]] | None = None,
) -> bool:
    home_sig = springboard_signature(scene)
    if attempted_home_signatures is not None and home_sig in attempted_home_signatures:
        return False
    viewport_size = _viewport_size(phone)
    folder = _find_home_folder_icon(scene, viewport_size=viewport_size)
    if folder is None:
        return False
    if attempted_home_signatures is not None:
        attempted_home_signatures.add(home_sig)
    folder_label = _text(folder.element)
    phone.tap_xy(*folder.tap_point)
    folder_scene = _perceive_after_settle(phone, settle_s)
    folder_viewport = _viewport_size(phone)
    if not _looks_like_home_folder_contents(
        folder_scene,
        folder_label=folder_label,
        viewport_size=folder_viewport,
    ):
        phone.home()
        _perceive_after_settle(phone, settle_s)
        return False
    if _tap_icon_if_visible(phone, folder_scene, labels, settle_s=settle_s):
        return True
    phone.home()
    _perceive_after_settle(phone, settle_s)
    return False


def _find_home_folder_icon(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None,
) -> SpringboardIcon | None:
    """Return a real Home-page folder candidate, not an App Library category."""
    if _is_known_non_home_folder_surface(scene, viewport_size=viewport_size):
        return None
    classified = classify_ios_scene(scene, viewport_size=viewport_size)
    if classified.kind != "springboard" and not is_ios_home_screen(scene, viewport_size=viewport_size):
        return None
    return find_springboard_icon(scene, HOME_FOLDER_LABELS, viewport_size=viewport_size, fuzzy=0.78)


def _looks_like_home_folder_contents(
    scene: Scene,
    *,
    folder_label: str,
    viewport_size: tuple[int, int] | None,
) -> bool:
    """Confirm a folder tap opened a Home folder overlay before tapping inside it."""
    if _is_known_non_home_folder_surface(scene, viewport_size=viewport_size):
        return False
    w, h = _scene_size(scene, viewport_size)
    has_folder_title = bool(folder_label) and any(
        _matches(_text(el), (folder_label,), fuzzy=0.78)
        and el.box.center[1] <= h * 0.24
        for el in scene.elements
    )
    if not has_folder_title:
        return False
    icon_labels = [
        el for el in _icon_label_candidates(scene, viewport_size=(w, h))
        if el.box.center[1] > h * 0.12
    ]
    return bool(icon_labels)


def _is_known_non_home_folder_surface(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None,
) -> bool:
    platform_kind = str(getattr(scene, "platform_scene_kind", "") or "")
    if platform_kind in {"app_library", "system_search"} or platform_kind.startswith("settings"):
        return True
    classified = classify_ios_scene(scene, viewport_size=viewport_size)
    return classified.kind in {
        "app_library",
        "system_search",
        "settings_root",
        "settings_search_results",
        "settings_detail",
        "settings_blocked_safety",
    }


def _tap_home_search_if_visible(phone, scene: Scene) -> bool:
    if not hasattr(phone, "tap_xy"):
        return False
    w, h = _scene_size(scene, _viewport_size(phone))
    candidates = [
        el for el in scene.elements
        if _matches(_text(el), HOME_SEARCH_LABELS, fuzzy=0.78)
        and el.box.center[1] > h * 0.78
    ]
    if not candidates:
        return False
    candidates.sort(key=lambda el: abs(el.box.center[0] - w / 2))
    cx, cy = candidates[0].box.center
    phone.tap_xy(cx, cy)
    return True


def _looks_like_spotlight_results(scene: Scene) -> bool:
    return any(_matches(_text(el), SPOTLIGHT_MARKERS, fuzzy=0.78) for el in scene.elements)


def _tap_spotlight_result_if_visible(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    settle_s: float,
) -> bool:
    if not hasattr(phone, "tap_xy"):
        return False
    candidates = _spotlight_result_candidates(scene, labels)
    if not candidates:
        return False
    candidates.sort(key=lambda el: (el.box.center[1], el.box.center[0]))
    target = candidates[0]
    _, cy = target.box.center
    # Spotlight app rows are easier to open by tapping the icon/row lead than
    # the OCR text box, especially when the label is very narrow.
    tap_x = max(24, target.box.x - 24)
    phone.tap_xy(tap_x, cy)
    scene_after_tap = _perceive_after_settle(phone, settle_s)
    classified = classify_ios_scene(scene_after_tap, viewport_size=_viewport_size(phone))
    if (
        is_ios_home_screen(scene_after_tap, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone))
        or _looks_like_spotlight_results(scene_after_tap)
        or classified.kind == "system_search"
    ):
        return False
    return _opened_expected_app_or_recover(phone, scene_after_tap, labels, settle_s=settle_s)


def _spotlight_result_candidates(scene: Scene, labels: Iterable[str]) -> list[UIElement]:
    if not _looks_like_spotlight_results(scene):
        return []
    w, h = _scene_size(scene, None)
    return [
        el for el in scene.elements
        if _matches(_text(el), labels, fuzzy=0.78)
        and h * 0.10 <= el.box.center[1] <= h * 0.75
        and el.box.center[0] <= w * 0.75
    ]


def wait_for_ios_home_screen(phone, *, timeout: float = 5.0) -> Scene | None:
    """Wait until glassbox perception sees an iOS Home page."""
    deadline = time.monotonic() + timeout
    last: Scene | None = None
    while time.monotonic() < deadline:
        last = phone.perceive()
        if is_ios_home_screen(last, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
            return last
        time.sleep(0.35)
    return last if last is not None and is_ios_home_screen(last, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)) else None


def _keyboard_query(labels: Iterable[str]) -> str | None:
    for label in labels:
        text = label.strip()
        if text and text.isascii() and any(c.isalpha() for c in text):
            return text.lower()
    return None


def open_app_via_spotlight(
    phone,
    labels: Iterable[str],
    *,
    query: str | None = None,
    require_visible_result: bool = False,
    settle_s: float = 0.8,
) -> bool:
    """Open an app with SpringBoard/Spotlight keyboard search.

    This is still a glassbox-only foregrounding path: Meta+Space, type a query,
    Return the best result. It avoids URLs and host-side app activation.
    """
    app_labels = tuple(labels)
    search_query = query or _keyboard_query(app_labels)
    if search_query is None:
        return False

    scene = _ensure_home_scene(phone, settle_s)
    if is_ios_home_screen(scene, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
        opened_search = _tap_home_search_if_visible(phone, scene)
    else:
        opened_search = False
    if not opened_search:
        phone.key(_MOD_META_LEFT, _KEY_SPACE)
    time.sleep(settle_s)
    phone.invalidate_perceive_cache()
    _clear_spotlight_query(phone, settle_s=settle_s)
    phone.type(search_query)
    time.sleep(settle_s)
    phone.invalidate_perceive_cache()
    scene = phone.perceive()
    if require_visible_result:
        return _tap_spotlight_result_if_visible(phone, scene, app_labels, settle_s=settle_s)
    if _open_spotlight_result_with_return_if_visible(phone, scene, app_labels, settle_s=settle_s):
        return True
    if _tap_spotlight_result_if_visible(phone, scene, app_labels, settle_s=settle_s):
        return True
    phone.key(0, _KEY_RETURN)
    scene = _perceive_after_settle(phone, settle_s)
    if is_ios_home_screen(scene, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
        return False
    return _opened_expected_app_or_recover(phone, scene, app_labels, settle_s=settle_s)


def _clear_spotlight_query(phone, *, settle_s: float) -> None:
    phone.key(_MOD_META_LEFT, _KEY_A)
    time.sleep(min(settle_s, 0.2))
    phone.key(0, _KEY_BACKSPACE)
    time.sleep(min(settle_s, 0.2))
    phone.invalidate_perceive_cache()


def _open_spotlight_result_with_return_if_visible(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    settle_s: float,
) -> bool:
    if not _spotlight_result_candidates(scene, labels):
        return False
    phone.key(0, _KEY_RETURN)
    scene_after_return = _perceive_after_settle(phone, settle_s)
    classified = classify_ios_scene(scene_after_return, viewport_size=_viewport_size(phone))
    if (
        is_ios_home_screen(scene_after_return, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone))
        or _looks_like_spotlight_results(scene_after_return)
        or classified.kind == "system_search"
    ):
        return False
    return _opened_expected_app_or_recover(phone, scene_after_return, labels, settle_s=settle_s)


def _scene_has_target_label(scene: Scene, labels: Iterable[str]) -> bool:
    return any(_matches(_text(el), labels, fuzzy=0.78) for el in scene.elements)


def _platform_key_for_phone(phone) -> str | None:
    model = str(getattr(getattr(phone, "device_geometry", None), "model", "") or "").lower().replace("-", "_")
    if model.startswith("ipad"):
        return "ipados"
    if model:
        return "ios"
    return None


def _launch_profile(labels: Iterable[str], *, phone=None) -> DefaultAppLaunchProfile | None:
    return default_launch_profile_for_labels(labels, platform=_platform_key_for_phone(phone))


def _requires_post_open_target_label(labels: Iterable[str], *, phone=None) -> bool:
    profile = _launch_profile(labels, phone=phone)
    return bool(profile and profile.require_post_open_verification)


def _climb_out_to_target(
    phone,
    labels: Iterable[str],
    *,
    settle_s: float,
    max_steps: int = 4,
) -> bool:
    """Tap Back to escape an unrecognized sub-page; accept if the target surfaces.

    A launch can reopen the target app on a sub-page whose chrome defeats
    detection (e.g. Settings stuck on the Action-Button carousel with a live
    camera preview). Going Home would not clear that app's nav stack, so the
    next reopen would land here again. back_gesture can climb such pages (it
    blind-taps the top-left chevron on unknown scenes), so try a few steps and
    accept once the target app's root is recognizable.
    """
    back = getattr(phone, "back_gesture", None)
    if not callable(back):
        return False
    for _ in range(max_steps):
        try:
            result = back()
        except Exception:
            return False
        if getattr(result, "ok", False) is not True:
            return False
        scene = _perceive_after_settle(phone, settle_s)
        if is_ios_home_screen(scene, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
            return False  # climbed past the app to Home — it was the wrong app
        classified = _classify_scene_for_phone(phone, scene)
        if classified.kind.startswith("settings_") or _scene_has_target_label(scene, labels):
            return True
    return False


def _opened_expected_app_or_recover(
    phone,
    scene: Scene,
    labels: Iterable[str],
    *,
    settle_s: float,
) -> bool:
    """Reject known wrong app launches for targets with recognizable roots."""
    app_labels = tuple(labels)
    if not _requires_post_open_target_label(app_labels, phone=phone):
        return True
    profile = _launch_profile(app_labels, phone=phone)
    classified = _classify_scene_for_phone(phone, scene)
    if profile is not None and verify_default_app_opened(
        profile,
        scene,
        labels=app_labels,
        classified_kind=classified.kind,
    ):
        return True
    # An "unknown" scene may be the target app reopened onto a sub-page whose
    # chrome defeats detection. Try climbing out before giving up — recovering
    # Home leaves that app's nav stack intact, so a reopen would just loop here.
    if (
        profile is not None
        and profile.climb_unknown_subpages
        and classified.kind == "unknown"
        and _climb_out_to_target(phone, app_labels, settle_s=settle_s)
    ):
        return True
    logger.warning(
        "springboard tap opened a non-target app for labels={} kind={}; recovering Home",
        app_labels,
        classified.kind,
    )
    try:
        phone.home()
        _perceive_after_settle(phone, settle_s)
    except Exception:
        pass
    return False


def open_app_via_icon_map(
    phone,
    labels: Iterable[str],
    *,
    icon_map,
    settle_s: float = 0.8,
) -> bool:
    """Open an app via the VLM icon map — a direct path.

    Home → detect icon cells → VLM-named map (cached) → tap the matched cell.
    Unlike ``open_app_from_springboard`` this does not run the OCR-label path
    or the ``is_ios_home_screen`` heuristic first: the detected icon grid plus
    VLM naming *is* the Home-screen understanding. Returns True if the tap left
    the Home screen.
    """
    scene = _ensure_home_scene(phone, settle_s)
    return _tap_icon_via_map_if_visible(
        phone, scene, labels, icon_map=icon_map, settle_s=settle_s)


def open_app_from_springboard(
    phone,
    labels: Iterable[str],
    *,
    max_pages: int = 8,
    settle_s: float = 0.8,
    icon_map=None,
) -> bool:
    """Open an app from SpringBoard by scanning Home pages left/right.

    The scan starts with a glassbox Home action, checks the current page, sweeps
    right toward the earlier pages/Today boundary, then sweeps left across the
    app pages. Returns True after tapping the target icon.

    ``icon_map``: an optional ``SpringboardIconMap``. When given (and the phone
    has a VLM), each page also gets a VLM-named icon-map lookup as a fallback to
    the OCR-label path — OCR cannot read Home icon labels reliably.
    """
    app_labels = tuple(labels)
    profile = _launch_profile(app_labels, phone=phone)
    _reset_icon_map_build_budget()
    print(f"[sb] open_app_from_springboard start labels={app_labels}", flush=True)
    if profile is not None and profile.preferred_open == "spotlight":
        print("[sb] spotlight preferred for this target", flush=True)
        if open_app_via_spotlight(
            phone,
            app_labels,
            query=profile.spotlight_query,
            require_visible_result=profile.require_visible_spotlight_result,
            settle_s=settle_s,
        ):
            return True
        print("[sb] spotlight preferred path failed → Home scan fallback", flush=True)

    # Cold-start scan may enter from a dirty state (foregrounded app, modal), so
    # retry home() while it makes progress. The Spotlight path keeps the default
    # single press (it works from any surface).
    scene = _ensure_home_scene(phone, settle_s, attempts=3)
    if not is_ios_home_screen(scene, viewport_size=_viewport_size(phone), strict_springboard=_strict_home(phone)):
        waited = wait_for_ios_home_screen(phone, timeout=2.0)
        if waited is None:
            print("[sb] could not reach Home → spotlight fallback", flush=True)
            return open_app_via_spotlight(phone, app_labels, settle_s=settle_s)
        scene = waited
    if _looks_like_today_widget_surface(scene, viewport_size=_viewport_size(phone)):
        print("[sb] widget surface without icon grid → spotlight fallback", flush=True)
        return open_app_via_spotlight(phone, app_labels, settle_s=settle_s)
    if _tap_icon_any(phone, scene, app_labels, icon_map=icon_map, settle_s=settle_s):
        return True
    attempted_folder_pages: set[tuple[tuple[str, int, int], ...]] = set()
    if _tap_target_inside_home_folder_if_visible(
        phone,
        scene,
        app_labels,
        settle_s=settle_s,
        attempted_home_signatures=attempted_folder_pages,
    ):
        return True

    seen = {springboard_signature(scene)}

    for _ in range(max_pages):
        previous = springboard_signature(scene)
        phone.swipe_right()
        scene = _perceive_after_settle(phone, settle_s)
        if _tap_icon_any(phone, scene, app_labels, icon_map=icon_map, settle_s=settle_s):
            return True
        if _tap_target_inside_home_folder_if_visible(
            phone,
            scene,
            app_labels,
            settle_s=settle_s,
            attempted_home_signatures=attempted_folder_pages,
        ):
            return True
        sig = springboard_signature(scene)
        if sig == previous or sig in seen:
            break
        seen.add(sig)

    forward_seen: set[tuple[tuple[str, int, int], ...]] = set()
    for _ in range(max_pages * 2 + 1):
        previous = springboard_signature(scene)
        phone.swipe_left()
        scene = _perceive_after_settle(phone, settle_s)
        if _tap_icon_any(phone, scene, app_labels, icon_map=icon_map, settle_s=settle_s):
            return True
        if _tap_target_inside_home_folder_if_visible(
            phone,
            scene,
            app_labels,
            settle_s=settle_s,
            attempted_home_signatures=attempted_folder_pages,
        ):
            return True
        sig = springboard_signature(scene)
        if sig == previous or sig in forward_seen:
            break
        forward_seen.add(sig)

    print("[sb] all page sweeps failed → spotlight fallback", flush=True)
    return open_app_via_spotlight(phone, app_labels, settle_s=settle_s)


class IOSSpringboardProvider:
    """iOS Platform SpringBoard sub-capability."""

    def open_app(
        self,
        phone,
        target: AppLaunchTarget,
        *,
        max_pages: int = 8,
        settle_s: float = 0.8,
        icon_map=None,
    ) -> bool:
        return open_app_from_springboard(
            phone,
            (*target.labels, *target.aliases),
            max_pages=max_pages,
            settle_s=settle_s,
            icon_map=icon_map,
        )

    def foreground_app(
        self,
        phone,
        target: AppLaunchTarget,
        *,
        settle_s: float = 0.8,
        icon_map=None,
    ) -> bool:
        ok = open_app_via_icon_map(
            phone,
            (*target.labels, *target.aliases),
            icon_map=icon_map,
            settle_s=settle_s,
        )
        time.sleep(settle_s)
        return ok

    def go_home(self, ctx) -> bool:
        metadata = getattr(ctx, "metadata", None) or {}
        phone = metadata.get("phone") or getattr(ctx, "phone", None)
        if phone is None:
            return False
        phone.home()
        return True
