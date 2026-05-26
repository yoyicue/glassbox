"""iPadOS scene classification.

The iPad Settings app keeps its root navigation in a left sidebar while the
selected page is rendered in a right detail pane. The iOS classifier remains the
fallback for non-split surfaces; this module only overrides the Settings split
view cases that the iPhone geometry cannot model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.text_match import confusion_compact, fuzzy_ratio, text_contains, texts_match
from glassbox.ios.scene import (
    SETTINGS_DETAIL_SEMANTIC_COPY_MARKERS,
    SETTINGS_DETAIL_SEMANTIC_NOUN_MARKERS,
    SETTINGS_ROOT_MARKERS,
    SETTINGS_SCREEN_TIME_MARKERS,
    SETTINGS_SEARCH_LABELS,
    SETTINGS_TITLE_LABELS,
    IOSSceneClassification,
    classify_ios_scene,
)

_TIME_RE = re.compile(r"^\d{1,2}[:：.]?\d{2}[A-Za-z]?$")
_IPAD_SETTINGS_SIDEBAR_MARKERS = (
    *SETTINGS_ROOT_MARKERS,
    "WLAN", "Mobile Service", "Apple Pencil", "Camera",
    "Control Centre", "Control Center",
)


def classify_ipados_scene(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> IOSSceneClassification:
    w, h = _scene_size(scene, viewport_size)
    sidebar = _settings_sidebar_evidence(scene, viewport_size=(w, h))
    if sidebar is None:
        settings_search = _settings_top_search_evidence(scene, viewport_size=(w, h))
        if settings_search and _strong_settings_top_search(settings_search):
            return IOSSceneClassification(
                kind="settings_search_results",
                confidence=0.84,
                title=_detail_pane_title(scene, viewport_size=(w, h)),
                safe_actions=("tap_search_result", "clear_search", "home"),
                evidence=("ipad_settings_top_search", *settings_search),
            )
        if _looks_like_ipad_system_search(scene, viewport_size=(w, h)):
            return IOSSceneClassification(
                kind="system_search",
                confidence=0.82,
                safe_actions=("tap_search_result", "home"),
                evidence=("ipad_system_search_overlay",),
            )
        if _looks_like_ipad_home_widgets(scene, viewport_size=(w, h)):
            return IOSSceneClassification(
                kind="springboard",
                confidence=0.78,
                safe_actions=("scan_icons", "search_app"),
                evidence=("ipad_home_widgets",),
            )
        if settings_search:
            return IOSSceneClassification(
                kind="settings_search_results",
                confidence=0.82,
                title=_detail_pane_title(scene, viewport_size=(w, h)),
                safe_actions=("tap_search_result", "clear_search", "home"),
                evidence=("ipad_settings_top_search", *settings_search),
            )
        ios = classify_ios_scene(scene, viewport_size=(w, h))
        if ios.kind == "settings_detail":
            return IOSSceneClassification(
                kind="unknown",
                confidence=0.25,
                title=ios.title,
                safe_actions=("trace", "vlm_on_uncertain"),
                evidence=("ipados_no_settings_sidebar", *ios.evidence[:3]),
            )
        return ios

    title = _detail_pane_title(scene, viewport_size=(w, h))
    detail_evidence = _detail_pane_evidence(scene, viewport_size=(w, h), title=title)
    evidence = ("ipad_split_view", *sidebar, *detail_evidence)
    if title and detail_evidence:
        return IOSSceneClassification(
            kind="settings_detail",
            confidence=0.88,
            page_id=f"settings/{title}",
            title=title,
            safe_actions=("tap_root_row", "scroll", "back"),
            evidence=evidence,
        )
    return IOSSceneClassification(
        kind="settings_root",
        confidence=0.86,
        page_id="settings/root",
        title="Settings",
        safe_actions=("tap_root_row", "open_search", "scroll"),
        evidence=("ipad_split_view", *sidebar),
    )


def _strong_settings_top_search(evidence: tuple[str, ...]) -> bool:
    """Return True when top-search evidence should beat Home-widget heuristics."""
    return "settings_search_no_results" in evidence or any(
        item.startswith("settings_detail_pane_visible:")
        for item in evidence
    )


def _scene_size(scene: Scene, viewport_size: tuple[int, int] | None) -> tuple[int, int]:
    if viewport_size is not None:
        return viewport_size
    if scene.viewport_size is not None:
        return scene.viewport_size
    width = max((e.box.x2 for e in scene.elements), default=744)
    height = max((e.box.y2 for e in scene.elements), default=1133)
    return max(width, 744), max(height, 1133)


def _text(el: UIElement) -> str:
    return (el.text or "").strip()


def _matches(text: str, labels: Iterable[str], *, fuzzy: float = 0.78) -> bool:
    norm = confusion_compact(text)
    for label in labels:
        if texts_match(text, label) or text_contains(text, label):
            return True
        if fuzzy_ratio(text, label) >= fuzzy:
            return True
        if norm and norm == confusion_compact(label):
            return True
    return False


def sidebar_right_x(width: int) -> int:
    """Right edge of the iPad Settings sidebar in current frame coordinates."""
    if width >= 900:
        return min(int(width * 0.42), 560)
    return int(width * 0.44)


def _settings_sidebar_evidence(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> tuple[str, ...] | None:
    w, h = viewport_size
    right = sidebar_right_x(w)
    title_hit = False
    search_hit = False
    account_hit = False
    marker_hits = 0
    seen: set[str] = set()
    for el in scene.elements:
        text = _text(el)
        if not text or el.box.center[0] > right:
            continue
        _cx, cy = el.box.center
        if _matches(text, SETTINGS_TITLE_LABELS, fuzzy=0.88) and cy <= h * 0.18:
            title_hit = True
        if cy <= h * 0.28 and _matches(text.lstrip("• "), SETTINGS_SEARCH_LABELS, fuzzy=0.78):
            search_hit = True
        if cy <= h * 0.36 and ("Apple Account" in text or "iCloud" in text or "Apple 账户" in text):
            account_hit = True
        if h * 0.10 <= cy <= h * 0.96 and text not in seen and _matches(
            text,
            _IPAD_SETTINGS_SIDEBAR_MARKERS,
            fuzzy=0.82,
        ):
            marker_hits += 1
            seen.add(text)
    if marker_hits >= 3 and (title_hit or search_hit or account_hit or marker_hits >= 4):
        evidence = [f"settings_sidebar_rows:{min(marker_hits, 6)}"]
        if title_hit:
            evidence.append("settings_sidebar_title")
        if search_hit:
            evidence.append("settings_sidebar_search")
        if account_hit:
            evidence.append("settings_sidebar_account")
        return tuple(evidence)
    return None


def _settings_top_search_evidence(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> tuple[str, ...]:
    """Recognize iPad Settings when active search hides the normal sidebar rows."""
    w, h = viewport_size
    right = sidebar_right_x(w)
    top_search_affordance = False
    top_query_text = False
    edit_menu = False
    no_results = False
    right_pane_items = 0
    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        cx, cy = el.box.center
        if cx <= right + 24 and h * 0.105 <= cy <= h * 0.17 and text in {
            "Paste", "Select", "Select All", "AutoFill", "AutoFil", "AutoFI", "Cut", "粘贴", "全选", "剪切",
        }:
            edit_menu = True
        if cx <= right + 8 and h * 0.075 <= cy <= h * 0.115:
            compact = re.sub(r"\s+", "", text)
            if compact.isdigit():
                continue
            if _matches(text, SETTINGS_SEARCH_LABELS, fuzzy=0.76) or compact.lower().startswith("q"):
                top_search_affordance = True
            elif (
                cx <= right * 0.62
                and 2 <= len(compact) <= 24
                and not _matches(text, SETTINGS_TITLE_LABELS, fuzzy=0.9)
            ):
                top_query_text = True
        if cx <= right + 24 and h * 0.12 <= cy <= h * 0.65 and (
            "No Results" in text
            or "Check the spelling" in text
            or "无结果" in text
            or "没有结果" in text
        ):
            no_results = True
        if cx > right and h * 0.05 <= cy <= h * 0.96:
            right_pane_items += 1
    top_search = top_search_affordance or (top_query_text and (edit_menu or no_results))
    if not top_search:
        return ()
    evidence: list[str] = []
    if no_results:
        evidence.append("settings_search_no_results")
    if right_pane_items >= 3:
        evidence.append(f"settings_detail_pane_visible:{min(right_pane_items, 6)}")
    return tuple(evidence) if evidence else ()


def _looks_like_ipad_system_search(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> bool:
    w, h = viewport_size
    has_result_label = False
    has_search_ui = False
    for el in scene.elements:
        text = _text(el)
        if not text:
            continue
        cx, cy = el.box.center
        if cx <= w * 0.46 and h * 0.07 <= cy <= h * 0.34 and _matches(text, SETTINGS_TITLE_LABELS, fuzzy=0.86):
            has_result_label = True
        if (
            "Top Hit" in text
            or "Suggestions" in text
            or "Search in App" in text
            or text in {"最佳匹配", "建议"}
        ):
            has_search_ui = True
    return has_result_label and has_search_ui


def _detail_pane_title(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> str | None:
    w, h = viewport_size
    left = sidebar_right_x(w)
    candidates: list[UIElement] = []
    repeatable: list[UIElement] = []
    ignored = {
        "<", "‹", "〈", "返回", "Back",
        "编辑", "Edit", "完成", "Done", "搜索", "Search", "设置", "Settings",
    }
    top_detail_back_y = _top_detail_back_y(scene, viewport_size=(w, h))
    for el in scene.elements:
        text = _text(el)
        if (
            not text
            or text in ignored
            or el.type == "nav_back"
            or _TIME_RE.match(text)
            or _looks_like_top_search_query_text(text)
            or _looks_like_detail_metric_title_noise(text)
            or len(text) > 32
        ):
            continue
        cx, cy = el.box.center
        if cx <= left or cy < h * 0.04 or cy > h * 0.96:
            continue
        if top_detail_back_y is not None and cy < top_detail_back_y - h * 0.02:
            continue
        semantic_chars = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff& ]+", "", text).strip()
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", semantic_chars)
        if len(semantic_chars) < 3 and len(cjk_chars) < 2:
            continue
        repeatable.append(el)
        if cy < h * 0.04 or cy > h * 0.22:
            continue
        candidates.append(el)
    semantic = _semantic_detail_pane_title(scene, viewport_size=(w, h))
    if semantic is not None:
        return semantic
    if not candidates:
        repeated = _repeated_detail_title_candidate(repeatable)
        if repeated is not None:
            return repeated
        return None
    detail_center = left + (w - left) / 2
    candidates.sort(key=lambda el: (
        _detail_title_band(el, viewport_height=h),
        abs(el.box.center[0] - detail_center),
        el.box.center[1],
        -el.box.w,
    ))
    return _text(candidates[0])


def _top_detail_back_y(scene: Scene, *, viewport_size: tuple[int, int]) -> int | None:
    w, h = viewport_size
    left = sidebar_right_x(w)
    back_markers = [
        el.box.center[1]
        for el in scene.elements
        if _text(el) in {"<", "‹", "〈", "Back", "返回"}
        and el.box.center[0] >= left - 24
        and h * 0.04 <= el.box.center[1] <= h * 0.18
    ]
    return min(back_markers) if back_markers else None


def _detail_title_band(el: UIElement, *, viewport_height: int) -> int:
    cy = el.box.center[1]
    if cy <= viewport_height * 0.08:
        return 0
    if cy <= viewport_height * 0.14:
        return 1
    return 2


def _looks_like_top_search_query_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).casefold()
    return compact.startswith("qsearch") or compact.startswith("q搜索")


def _looks_like_detail_metric_title_noise(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).casefold()
    if not compact:
        return False
    if "%" in text or "％" in text:
        return True
    if re.fullmatch(r"\d+h(?:\d+m)?", compact) or re.fullmatch(r"\d+m", compact):
        return True
    if re.fullmatch(r"\d+(?:小时|分钟|分)", compact):
        return True
    if compact in {"avg", "•avg", "-avg"}:
        return True
    return compact in {
        "dailyaverage",
        "日均",
        "每日平均",
    }


def _semantic_detail_pane_title(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> str | None:
    if _looks_like_ipad_screen_time_detail(scene, viewport_size=viewport_size):
        return _sidebar_label_for(scene, ("Screen Time", "屏幕使用时间", "屏幕时间"), viewport_size=viewport_size) or "Screen Time"
    return None


def _looks_like_ipad_screen_time_detail(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> bool:
    w, h = viewport_size
    left = sidebar_right_x(w)
    right_texts = [
        _text(el)
        for el in scene.elements
        if _text(el)
        and el.type != "status_bar"
        and el.box.center[0] > left
        and h * 0.04 <= el.box.center[1] <= h * 0.97
    ]
    if not right_texts:
        return False
    seen_markers: set[str] = set()
    marker_hits = 0
    joined = "\n".join(right_texts)
    for marker in SETTINGS_SCREEN_TIME_MARKERS:
        if marker and marker in joined and marker not in seen_markers:
            marker_hits += 1
            seen_markers.add(marker)
    has_usage_controls = any(
        marker in joined
        for marker in (
            "Downtime", "App Limits", "Always Allowed", "Screen Distance",
            "Communication Limits", "Communication Safety", "Content & Privacy",
            "停用时间", "App限额", "始终允许", "屏幕距离", "限定通信", "通信安全",
        )
    )
    has_dashboard_metrics = any(
        marker in joined
        for marker in ("Daily Average", "Updated today", "from last week", "日均", "更新于")
    ) or any(re.search(r"\b\d+\s*h(?:\s*\d+\s*m)?\b", text, re.I) for text in right_texts)
    return marker_hits >= 4 and has_usage_controls and has_dashboard_metrics


def _sidebar_label_for(
    scene: Scene,
    labels: Iterable[str],
    *,
    viewport_size: tuple[int, int],
) -> str | None:
    w, h = viewport_size
    right = sidebar_right_x(w)
    matches = [
        el for el in scene.elements
        if _text(el)
        and el.box.center[0] <= right
        and h * 0.10 <= el.box.center[1] <= h * 0.96
        and _matches(_text(el), labels, fuzzy=0.86)
    ]
    if not matches:
        return None
    matches.sort(key=lambda el: (el.box.center[1], el.box.center[0]))
    return _text(matches[0])


def _repeated_detail_title_candidate(elements: Iterable[UIElement]) -> str | None:
    groups: list[tuple[str, list[UIElement]]] = []
    for el in elements:
        text = _text(el)
        if not text:
            continue
        for label, matches in groups:
            if texts_match(text, label):
                matches.append(el)
                break
        else:
            groups.append((text, [el]))
    repeated = [(label, matches) for label, matches in groups if len(matches) >= 2]
    if not repeated:
        return None
    repeated.sort(key=lambda item: (
        min(el.box.center[1] for el in item[1]),
        -max(el.box.w for el in item[1]),
    ))
    return repeated[0][0]


def _detail_pane_evidence(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
    title: str | None = None,
) -> tuple[str, ...]:
    w, h = viewport_size
    left = sidebar_right_x(w)
    visible = [
        el for el in scene.elements
        if _text(el)
        and el.type != "status_bar"
        and el.box.center[0] > left
        and h * 0.10 <= el.box.center[1] <= h * 0.97
    ]
    all_right = [
        el for el in scene.elements
        if _text(el)
        and el.type != "status_bar"
        and el.box.center[0] > left
        and h * 0.04 <= el.box.center[1] <= h * 0.97
    ]
    if not visible:
        return ()
    joined = "\n".join(_text(el) for el in visible).casefold()
    noun_hits = _marker_hits(joined, SETTINGS_DETAIL_SEMANTIC_NOUN_MARKERS)
    copy_hits = _marker_hits(joined, SETTINGS_DETAIL_SEMANTIC_COPY_MARKERS)
    long_lines = sum(1 for el in visible if el.box.w >= (w - left) * 0.42 or len(_text(el)) >= 18)
    row_bins = {
        round(el.box.center[1] / max(1, h * 0.055))
        for el in visible
        if len(_text(el)) <= 36
    }
    evidence: list[str] = []
    if noun_hits:
        evidence.append(f"detail_nouns:{min(noun_hits, 4)}")
    if copy_hits:
        evidence.append(f"detail_copy:{min(copy_hits, 4)}")
    if long_lines:
        evidence.append(f"detail_long_lines:{min(long_lines, 4)}")
    if len(row_bins) >= 3:
        evidence.append(f"detail_rows:{min(len(row_bins), 6)}")
    if title and _detail_title_repeated(all_right, title):
        evidence.append("detail_repeated_title")
    return tuple(evidence)


def _detail_title_repeated(elements: Iterable[UIElement], title: str) -> bool:
    if not title:
        return False
    return sum(1 for el in elements if texts_match(_text(el), title)) >= 2


def _looks_like_ipad_home_widgets(
    scene: Scene,
    *,
    viewport_size: tuple[int, int],
) -> bool:
    _w, h = viewport_size
    texts = [_text(el) for el in scene.elements if _text(el)]
    if not texts:
        return False
    joined = "\n".join(texts)
    has_date_or_time = any(
        ("月" in text and ("日" in text or "周" in text))
        or bool(re.search(r"\d{1,2}[:：]\d{2}", text))
        for text in texts
    )
    has_widget_label = any(
        marker in joined
        for marker in (
            "备忘录", "Notes", "日历", "Calendar", "天气", "Weather",
            "电池", "Batteries", "提醒事项", "Reminders",
        )
    )
    has_widget_grid_geometry = sum(
        1 for el in scene.elements
        if _text(el) and h * 0.08 <= el.box.center[1] <= h * 0.88 and el.box.w >= 40
    ) >= 4
    return has_date_or_time and has_widget_label and has_widget_grid_geometry


def _marker_hits(joined_casefold: str, markers: Iterable[str]) -> int:
    hits = 0
    seen: set[str] = set()
    for marker in markers:
        compact = marker.casefold()
        if compact and compact not in seen and compact in joined_casefold:
            seen.add(compact)
            hits += 1
    return hits


__all__ = ["classify_ipados_scene", "sidebar_right_x"]
