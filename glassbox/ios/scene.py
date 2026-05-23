"""Lightweight iOS scene classification from OCR geometry and text.

This module intentionally stays OCR-first. VLM can refine low-confidence or
stuck states later, but the hot path should be deterministic, cheap, and easy
to unit test.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.contracts import (
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    SceneClassification,
)
from glassbox.cognition.text_match import (
    confusion_compact,
    fuzzy_ratio,
    text_contains,
    texts_match,
)

SETTINGS_TITLE_LABELS = ("设置", "Settings")
SETTINGS_ROOT_MARKERS = (
    "无线局域网", "Wi-Fi", "蓝牙", "Bluetooth", "蜂窝网络", "Cellular",
    "通知", "Notifications", "声音与触感", "Sounds & Haptics",
    "专注模式", "Focus", "屏幕使用时间", "屏幕时间", "Screen Time",
    "通用", "General", "辅助功能", "Accessibility",
    "操作按钮", "Action Button", "待机显示", "待机見示", "StandBy",
    "面容ID与密码", "Face ID与密码", "Face ID & Passcode",
    "Siri",
    "紧急 SOS", "Emergency SOS", "隐私与安全性", "Privacy & Security",
    "电池", "Battery", "钱包与 Apple Pay", "Wallet & Apple Pay",
    "Game Center",
)
SETTINGS_SEARCH_LABELS = ("搜索", "Search")
APP_LIBRARY_LABELS = ("App资源库", "App 资源库", "App Library")
APP_LIBRARY_CATEGORY_MARKERS = (
    "建议", "Suggestions", "最近添加", "Recently Added",
    "社交", "Social", "效率与财务", "效率与財务", "Productivity & Finance",
    "创意", "Creativity", "其他", "Other", "工具", "Utilities",
    "娱乐", "Entertainment", "购物与美食", "Shopping & Food",
    "信息与阅读", "Information & Reading", "健康与健身", "Health & Fitness",
    "旅游", "Travel",
)
SYSTEM_SEARCH_MARKERS = ("最佳搜索结果", "Top Hit", "Siri建议", "Siri Suggestions", "在App中搜索", "Search in App")
BLOCKED_SAFETY_MARKERS = (
    "输入密码", "输入iPhone密码", "输入 iPhone 密码", "Enter Passcode",
    "欢迎来到 Game Center", "自定义你的个人资料",
)
# GlassboxHelper —— glassbox 自己的被控端控制台。走查必须先认出它,否则会把自己的
# 控制面板误判成 settings_detail 并对「停止服务」等按钮发动作,等于把链路点断。
# 这些字串是 GlassboxHelper 专有,iOS 设置内不会出现。
HARNESS_CONSOLE_MARKERS = (
    "停止服务", "启动服务", "服务运行中", "服务已停止", "服务有问题",
    "Mac 大脑", "Mac大脑", "远程控制链路", "最近活动", "暂无命令",
)
SETTINGS_DETAIL_BODY_MARKERS = (
    "允许", "访问", "账户", "Apple", "App", "Siri", "搜索", "隐私",
    "默认", "通知", "密码", "位置", "联系人", "照片", "相机", "麦克风",
    "共享", "显示", "关闭", "提供商", "进一步了解",
)
SETTINGS_ABOUT_MARKERS = (
    "关于本机", "About", "iOS版本", "iOS Version", "型号名称", "Model Name",
    "型号", "Model Number", "序列号", "Serial Number", "有限保修",
    "总容量", "Capacity", "可用容量", "Available", "无线局域网地址",
)
SETTINGS_SOFTWARE_UPDATE_MARKERS = (
    "软件更新", "Software Update", "自动更新", "Automatic Updates",
    "iOS已是最新版本", "iOS is up to date", "iOS 26", "iOS",
    "更多详细信息", "More Information",
)
SETTINGS_STORAGE_MARKERS = (
    "iPhone储存空间", "iPhone Storage", "已使用", "used",
    "推荐", "Recommendations", "卸载未使用的App", "Offload Unused Apps",
    "应用程序", "Apps", "系统数据", "System Data", "大小", "Size",
)
SETTINGS_SCREEN_TIME_MARKERS = (
    "屏幕使用时间", "屏幕时间", "Screen Time", "每周", "每天",
    "Weekly", "Daily", "最常使用", "Most Used", "更新于", "Updated",
    "日均", "Daily Average", "查看所有App与网站活动", "See All App & Website Activity",
    "使用限制", "Limit Usage", "停用时间", "Downtime", "App限额", "App Limits",
    "始终允许", "Always Allowed", "屏幕距离", "Screen Distance",
    "限定通信", "Communication Limits", "通信安全", "Communication Safety",
)
SETTINGS_HEALTH_DATA_MARKERS = (
    "健康数据", "Health Data", "医疗详细信息", "Medical Details",
    "健康详细信息", "Health Details", "医疗急救卡", "Medical ID",
    "数据访问与设备", "Data Access & Devices",
)
HOME_SEARCH_LABELS = SETTINGS_SEARCH_LABELS
_TIME_RE = re.compile(r"^\d{1,2}[:：.]?\d{2}[A-Za-z]?$")


@dataclass(frozen=True)
class IOSSceneClassification:
    kind: str
    # Heuristic ordering score, not a calibrated probability. Downstream code
    # should use kind/evidence/safe_actions rather than thresholding this alone.
    confidence: float
    page_id: str | None = None
    title: str | None = None
    safe_actions: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_scene_classification(self) -> SceneClassification:
        return SceneClassification(
            page_id=self.page_id,
            platform_scene_kind=self.kind,
            confidence=self.confidence,
            source="platform",
            safe_actions=self.safe_actions,
            evidence=self.evidence,
        )


def classify_ios_scene(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> IOSSceneClassification:
    """Classify common iOS surfaces from OCR output.

    Kinds are intentionally broad:
    harness_console, settings_root, settings_search_home,
    settings_search_results, settings_detail, settings_blocked_safety,
    system_search, springboard, app_library, unknown. The confidence field is
    a deterministic heuristic score, not a calibrated probability.
    """
    w, h = _scene_size(scene, viewport_size)
    title = _page_title(scene, viewport_size=(w, h))

    # 最先判:这是 glassbox 自己的 GlassboxHelper 控制台,不是被测 App。
    # 走查在此只能 home 退出,绝不能 tap —— 否则可能点停自己的服务。
    console_evidence = _harness_console_evidence(scene)
    if console_evidence is not None:
        return IOSSceneClassification(
            kind="harness_console",
            confidence=0.95,
            title=title,
            safe_actions=("home",),
            evidence=console_evidence,
        )

    if _is_settings_root(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="settings_root",
            confidence=0.92,
            page_id="settings/root",
            title=title,
            safe_actions=("tap_root_row", "open_search", "scroll"),
            evidence=("settings_title", "root_markers"),
        )

    app_library_evidence = _app_library_evidence(scene, viewport_size=(w, h))
    if app_library_evidence is not None:
        return IOSSceneClassification(
            kind="app_library",
            confidence=0.90,
            title=title,
            safe_actions=("search_app", "open_app"),
            evidence=app_library_evidence,
        )

    if _looks_like_system_search(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="system_search",
            confidence=0.88,
            title=title,
            safe_actions=("home", "open_app"),
            evidence=("suggestions_title", "app_category", "bottom_search_chrome"),
        )

    if _looks_like_springboard(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="springboard",
            confidence=0.82,
            title=title,
            safe_actions=("scan_icons", "search_app"),
            evidence=("icon_grid",),
        )

    if _looks_like_settings_search_results(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="settings_search_results",
            confidence=0.84,
            title=title,
            safe_actions=("clear_search", "tap_settings_tab", "tap_root_result"),
            evidence=("search_result_rows",),
        )

    if _has_settings_search_chrome(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="settings_search_home",
            confidence=0.86,
            title=title,
            safe_actions=("clear_search", "tap_settings_tab", "type_query"),
            evidence=("bottom_search_chrome",),
        )

    blocked = _blocked_safety_marker(scene)
    if blocked is not None:
        return IOSSceneClassification(
            kind="settings_blocked_safety",
            confidence=0.88,
            title=title,
            safe_actions=("record_blocked",),
            evidence=(blocked,),
        )

    if _looks_like_settings_detail(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="settings_detail",
            confidence=0.78,
            page_id=f"settings/{title}" if title else None,
            title=title,
            safe_actions=("back", "edge_back"),
            evidence=("center_title_or_back", "detail_rows"),
        )

    return IOSSceneClassification(
        kind="unknown",
        confidence=0.20,
        title=title,
        safe_actions=("trace", "vlm_on_uncertain"),
        evidence=(),
    )


def apply_ios_classification(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
    overwrite_scene_type: bool = False,
) -> IOSSceneClassification:
    """Project the iOS classifier result onto a Scene.

    This keeps the platform-specific classifier outside generic memory:
    callers that are intentionally operating on iOS surfaces run this helper
    before handing the Scene to ScreenMemory. Existing Layer 3/profile
    `scene_type` is preserved unless `overwrite_scene_type=True`.
    """
    classified = classify_ios_scene(scene, viewport_size=viewport_size)
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR.project(
        scene,
        [classified.to_scene_classification()],
        overwrite_scene_type=overwrite_scene_type,
    )
    scene.classification_source = "ios"
    return classified


def _scene_size(scene: Scene, viewport_size: tuple[int, int] | None) -> tuple[int, int]:
    if viewport_size is not None:
        return viewport_size
    if scene.viewport_size is not None:
        return scene.viewport_size
    width = max((e.box.x2 for e in scene.elements), default=448)
    height = max((e.box.y2 for e in scene.elements), default=973)
    return max(width, 448), max(height, 973)


def _text(el: UIElement) -> str:
    return (el.text or "").strip()


def _matches(text: str, labels: Iterable[str], *, fuzzy: float = 0.78) -> bool:
    norm = confusion_compact(text)
    for label in labels:
        if texts_match(text, label) or text_contains(text, label):
            return True
        if fuzzy_ratio(text, label) >= fuzzy:
            return True
        # OCR 视觉混淆容忍:归一后相等也算命中。让 scene 分类的 marker 判定
        # (Settings 根页 / App 资源库网格 / system search)不被形近字噪音
        # 拖垮 —— 例如 App 资源库分类「效率与财务」被 OCR 成「效率与財务」。
        if norm and norm == confusion_compact(label):
            return True
    return False


def _has_back_affordance(scene: Scene) -> bool:
    return any(
        (
            el.type == "nav_back"
            or _text(el) in {"<", "‹", "〈", "返回", "Back"}
        )
        # The status-bar clock sits top-left and is sometimes typed `nav_back`;
        # its OCR is noisy ("3:50C", "3:516", "21:23") so it can masquerade as a
        # Back button and wrongly disqualify the Settings root. A real nav-bar
        # Back affordance lives below the status bar, so require the element to
        # sit in the nav-bar band (and still drop any time-pattern text).
        and not _TIME_RE.match(_text(el))
        and 50 <= el.box.center[1] <= 180
        and el.box.center[0] <= 120
        for el in scene.elements
    )


def _page_title(scene: Scene, *, viewport_size: tuple[int, int]) -> str | None:
    w, _ = viewport_size
    candidates = [
        el for el in scene.elements
        if _text(el)
        and el.type != "nav_back"
        and _text(el) not in {"<", "‹", "〈", "返回", "Back"}
        and _text(el) not in {"编辑", "Edit", "完成", "Done"}
        and not _TIME_RE.match(_text(el))
        and 50 <= el.box.center[1] <= 170
        and len(_text(el)) <= 28
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda el: (abs(el.box.center[1] - 90), abs(el.box.center[0] - w / 2)))
    return _text(candidates[0])


def _is_settings_root(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    _, h = viewport_size
    if _has_back_affordance(scene):
        return False
    has_title = any(
        _matches(_text(el), SETTINGS_TITLE_LABELS, fuzzy=0.88)
        and el.box.center[1] <= h * 0.18
        for el in scene.elements
    )
    marker_count = 0
    seen: set[str] = set()
    for el in scene.elements:
        text = _text(el)
        if not text or text in seen:
            continue
        seen.add(text)
        if _matches(text, SETTINGS_ROOT_MARKERS, fuzzy=0.82):
            marker_count += 1
    return has_title and marker_count >= 2


def _is_search_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if "搜索App" in compact or "SearchApp" in compact:
        return False
    return (
        _matches(text, SETTINGS_SEARCH_LABELS, fuzzy=0.82)
        or "搜索" in text
        or "Search" in text
    )


def _has_settings_search_chrome(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    _, h = viewport_size
    bottom_text = "".join(
        _text(el)
        for el in scene.elements
        if el.box.center[1] >= h * 0.86
    )
    bottom_compact = re.sub(r"\s+", "", bottom_text)
    if "搜索App" in bottom_compact or "SearchApp" in bottom_compact:
        return False
    has_bottom_search = any(
        el.box.center[1] >= h * 0.86 and _is_search_text(_text(el))
        for el in scene.elements
    )
    has_bottom_clear = any(
        _text(el) in {"×", "X"}
        and el.box.center[0] >= viewport_size[0] * 0.66
        and el.box.center[1] >= h * 0.86
        for el in scene.elements
    )
    return has_bottom_search or has_bottom_clear


def _looks_like_system_search(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    w, h = viewport_size
    has_global_search_marker = any(
        _matches(_text(el), SYSTEM_SEARCH_MARKERS, fuzzy=0.78)
        for el in scene.elements
    )
    if has_global_search_marker and _has_settings_search_chrome(scene, viewport_size=viewport_size):
        return True
    has_suggestions_title = any(
        _text(el) in {"建议", "Suggestions"}
        and el.box.center[0] <= w * 0.25
        and h * 0.06 <= el.box.center[1] <= h * 0.16
        for el in scene.elements
    )
    if not has_suggestions_title or not _has_settings_search_chrome(scene, viewport_size=viewport_size):
        return False
    has_app_category = any(
        _text(el) in {"App", "Apps"}
        and el.box.center[0] <= w * 0.25
        and h * 0.11 <= el.box.center[1] <= h * 0.24
        for el in scene.elements
    )
    has_recent_label = any(
        re.search(r"(最近|[取蕺]近|Recent)", _text(el))
        and el.box.center[0] <= w * 0.25
        and h * 0.30 <= el.box.center[1] <= h * 0.48
        for el in scene.elements
    )
    has_unqueried_search = any(
        el.box.center[1] >= h * 0.86
        and _matches(_text(el), SETTINGS_SEARCH_LABELS, fuzzy=0.78)
        for el in scene.elements
    )
    return has_unqueried_search and (has_app_category or has_recent_label)


def _looks_like_settings_search_results(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    if _has_back_affordance(scene):
        return False
    if _looks_like_settings_detail_body(scene, viewport_size=viewport_size):
        return False
    _, h = viewport_size
    root_hits = 0
    path_hint_hits = 0
    for el in scene.elements:
        text = _text(el)
        if not text:
            continue
        cx, cy = el.box.center
        if cy < h * 0.09 or cy > h * 0.93:
            continue
        if (
            cx <= viewport_size[0] * 0.42
            and len(text) <= 18
            and el.box.w <= viewport_size[0] * 0.50
            and _is_known_settings_root_label(text)
        ):
            root_hits += 1
        if _looks_like_settings_search_path_hint(text):
            path_hint_hits += 1
    return root_hits >= 2 and path_hint_hits >= 1


def _looks_like_settings_search_path_hint(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if "～" in compact:
        return True
    if not (">" in compact or "›" in compact or "＞" in compact):
        return False
    if len(compact) < 4:
        return False
    return _is_known_settings_root_label(compact) or any(
        _matches(part, SETTINGS_ROOT_MARKERS + SETTINGS_TITLE_LABELS, fuzzy=0.82)
        for part in re.split(r"[>›＞]", compact)
        if part
    )


def _is_known_settings_root_label(text: str) -> bool:
    return _matches(text, SETTINGS_ROOT_MARKERS + SETTINGS_TITLE_LABELS, fuzzy=0.82)


def _blocked_safety_marker(scene: Scene) -> str | None:
    joined = "\n".join(_text(el) for el in scene.elements if _text(el))
    for marker in BLOCKED_SAFETY_MARKERS:
        if marker in joined:
            return marker
    return None


def _harness_console_evidence(scene: Scene) -> tuple[str, ...] | None:
    """Detect GlassboxHelper — the glassbox's own control console on the device.

    Matches on GlassboxHelper-exclusive strings (`停止服务`, `Mac 大脑`, `最近活动`, ...).
    Requires ≥2 distinct markers so a stray OCR token cannot trip it. Returns
    the matched markers, or None when this is not the console.
    """
    hits: list[str] = []
    for marker in HARNESS_CONSOLE_MARKERS:
        compact = re.sub(r"\s+", "", marker)
        for el in scene.elements:
            text = re.sub(r"\s+", "", _text(el))
            if text and (compact in text or (text in compact and len(text) >= 3)):
                hits.append(marker)
                break
    if len(hits) >= 2:
        return tuple(hits)
    return None


def _looks_like_settings_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    w, h = viewport_size
    if _looks_like_app_library(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_grouped_control_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_wifi_settings_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_settings_about_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_settings_software_update_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_settings_storage_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_settings_screen_time_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_settings_health_data_detail(scene, viewport_size=(w, h)):
        return True
    if _looks_like_settings_detail_body(scene, viewport_size=(w, h)):
        return True
    has_back = _has_back_affordance(scene)
    title = _page_title(scene, viewport_size=(w, h))
    if not title:
        return False
    has_center_title = any(
        _text(el) == title
        and el.box.center[1] <= h * 0.18
        and abs(el.box.center[0] - w / 2) <= w * 0.24
        for el in scene.elements
    )
    has_large_left_title = any(
        _text(el) == title
        and el.box.center[1] <= h * 0.18
        and el.box.center[0] <= w * 0.42
        for el in scene.elements
    )
    has_settings_copy = any(
        el.box.center[1] <= h * 0.55
        and (
            el.box.w >= w * 0.45
            or len(_text(el)) >= 18
            or any(marker in _text(el) for marker in ("iPhone", "Apple", "Siri", "隐私", "默认", "App"))
        )
        for el in scene.elements
    )
    if has_back and not has_settings_copy:
        return False
    if not has_center_title and not (has_large_left_title and has_settings_copy):
        return False
    long_rows = 0
    left_rows = 0
    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar" or el.box.center[1] <= h * 0.16:
            continue
        if el.box.w >= w * 0.45 or len(text) >= 18:
            long_rows += 1
        if el.box.center[0] <= w * 0.42 and len(text) <= 28:
            left_rows += 1
    if has_large_left_title and has_settings_copy:
        return left_rows >= 3
    required_long_rows = 2
    return long_rows >= required_long_rows and left_rows >= 2


def _looks_like_settings_grouped_control_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize generic iOS Settings pages made of grouped control rows.

    These pages can lose their back affordance in OCR but still have a centered
    nav title, left-aligned setting labels, and right-side values/chevrons or
    explanatory copy. This guards the icon-grid SpringBoard heuristic from
    treating dense Settings rows as home-screen app labels.
    """
    w, h = viewport_size
    title = _page_title(scene, viewport_size=(w, h))
    if not title or _has_settings_search_chrome(scene, viewport_size=(w, h)):
        return False
    has_nav_title = any(
        _text(el) == title
        and el.box.center[1] <= h * 0.18
        and abs(el.box.center[0] - w / 2) <= w * 0.30
        and len(_text(el)) <= 16
        for el in scene.elements
    )
    if not has_nav_title:
        return False

    left_rows = 0
    button_rows = 0
    right_value_rows = 0
    explanatory_lines = 0
    row_bins: set[int] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        cx, cy = el.box.center
        if cy <= h * 0.16 or cy >= h * 0.96:
            continue
        row_bins.add(round(cy / max(1, h * 0.045)))
        if cx <= w * 0.46 and len(text) <= 32:
            left_rows += 1
        if el.type == "button" and cx <= w * 0.58 and len(text) <= 36:
            button_rows += 1
        if cx >= w * 0.66 and ("›" in text or ">" in text or "＞" in text or len(text) <= 12):
            right_value_rows += 1
        if el.box.w >= w * 0.48 or len(text) >= 18:
            explanatory_lines += 1

    return (
        len(row_bins) >= 4
        and left_rows >= 4
        and (right_value_rows >= 1 or explanatory_lines >= 1 or button_rows >= 4)
    )


def _looks_like_wifi_settings_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize Wi-Fi Settings when the nav title/back affordance is pure icon."""
    w, h = viewport_size
    has_wifi_label = False
    has_wifi_copy = False
    section_hits = 0
    network_rows = 0

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        cx, cy = el.box.center
        if cy <= h * 0.12 or cy >= h * 0.96:
            continue
        if _matches(text, ("无线局域网", "Wi-Fi"), fuzzy=0.86):
            has_wifi_label = True
        if (
            "接入无线局域网" in text
            or "可用网络" in text
            or "附近热点" in text
            or "进一步了解" in text
        ):
            has_wifi_copy = True
        if text in {"我的网络", "其他网络", "My Networks", "Other Networks"}:
            section_hits += 1
        if (
            cx <= w * 0.55
            and h * 0.35 <= cy <= h * 0.94
            and 3 <= len(text) <= 28
            and text not in {"我的网络", "其他网络"}
        ):
            network_rows += 1

    return has_wifi_label and has_wifi_copy and (section_hits >= 1 or network_rows >= 3)


def _looks_like_settings_about_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize Settings > General > About when the nav back icon is OCR-missing."""
    w, h = viewport_size
    marker_hits = 0
    left_rows = 0
    seen_markers: set[str] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        cx, cy = el.box.center
        if cy <= h * 0.08 or cy >= h * 0.98:
            continue
        if cx <= w * 0.46 and len(text) <= 32:
            left_rows += 1
        for marker in SETTINGS_ABOUT_MARKERS:
            if marker in text and marker not in seen_markers:
                seen_markers.add(marker)
                marker_hits += 1

    return marker_hits >= 4 and left_rows >= 5


def _looks_like_settings_software_update_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize Settings > General > Software Update when nav OCR is missing."""
    _w, h = viewport_size
    title_seen = False
    marker_hits = 0
    seen_markers: set[str] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        _cx, cy = el.box.center
        if cy <= h * 0.06 or cy >= h * 0.96:
            continue
        if _matches(text, ("软件更新", "Software Update"), fuzzy=0.86):
            title_seen = True
        for marker in SETTINGS_SOFTWARE_UPDATE_MARKERS:
            if marker in text and marker not in seen_markers:
                seen_markers.add(marker)
                marker_hits += 1

    return title_seen and marker_hits >= 3


def _looks_like_settings_storage_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize Settings > General > iPhone Storage when nav OCR is missing."""
    _w, h = viewport_size
    title_seen = False
    marker_hits = 0
    app_rows = 0
    seen_markers: set[str] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        _cx, cy = el.box.center
        if cy <= h * 0.06 or cy >= h * 0.98:
            continue
        if _matches(text, ("iPhone储存空间", "iPhone Storage"), fuzzy=0.86):
            title_seen = True
        if "GB" in text or "MB" in text:
            app_rows += 1
        for marker in SETTINGS_STORAGE_MARKERS:
            if marker in text and marker not in seen_markers:
                seen_markers.add(marker)
                marker_hits += 1

    return title_seen and marker_hits >= 4 and app_rows >= 2


def _looks_like_settings_screen_time_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize Settings > Screen Time detail when the nav back icon is OCR-missing."""
    _w, h = viewport_size
    title_seen = False
    marker_hits = 0
    chart_rows = 0
    seen_markers: set[str] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        _cx, cy = el.box.center
        if cy <= h * 0.06 or cy >= h * 0.98:
            continue
        if cy <= h * 0.18 and _matches(text, ("iPhone", "屏幕使用时间", "屏幕时间", "Screen Time"), fuzzy=0.86):
            title_seen = True
        if any(token in text for token in ("小时", "分钟", "hour", "min", "时")):
            chart_rows += 1
        for marker in SETTINGS_SCREEN_TIME_MARKERS:
            if marker in text and marker not in seen_markers:
                seen_markers.add(marker)
                marker_hits += 1

    return title_seen and (
        (marker_hits >= 3 and chart_rows >= 3)
        or marker_hits >= 5
    )


def _looks_like_settings_health_data_detail(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize Settings > General > Health Data when nav OCR is missing."""
    _w, h = viewport_size
    title_seen = False
    marker_hits = 0
    seen_markers: set[str] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        _cx, cy = el.box.center
        if cy <= h * 0.06 or cy >= h * 0.96:
            continue
        if _matches(text, ("健康数据", "Health Data"), fuzzy=0.86):
            title_seen = True
        for marker in SETTINGS_HEALTH_DATA_MARKERS:
            if marker in text and marker not in seen_markers:
                seen_markers.add(marker)
                marker_hits += 1

    return title_seen and marker_hits >= 4


def _looks_like_settings_detail_body(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize scrolled Settings detail pages whose nav bar/title OCR is missing."""
    w, h = viewport_size
    long_copy = 0
    left_rows = 0
    marker_hits = 0
    seen_markers: set[str] = set()

    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        cx, cy = el.box.center
        if cy <= h * 0.10 or cy >= h * 0.98:
            continue
        if el.box.w >= w * 0.55 or len(text) >= 18:
            long_copy += 1
        if cx <= w * 0.45 and len(text) <= 32:
            left_rows += 1
        for marker in SETTINGS_DETAIL_BODY_MARKERS:
            if marker in text and marker not in seen_markers:
                seen_markers.add(marker)
                marker_hits += 1

    return long_copy >= 1 and left_rows >= 4 and marker_hits >= 3


def _looks_like_app_library(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    return _app_library_evidence(scene, viewport_size=viewport_size) is not None


def _app_library_evidence(scene: Scene, *, viewport_size: tuple[int, int]) -> tuple[str, ...] | None:
    w, h = viewport_size
    has_title = any(
        _matches(_text(el), APP_LIBRARY_LABELS, fuzzy=0.80)
        and el.box.center[1] <= h * 0.18
        for el in scene.elements
    )
    if has_title:
        return ("app_library_label",)

    category_hits: set[str] = set()
    for el in scene.elements:
        text = _text(el)
        if not text:
            continue
        cx, cy = el.box.center
        if cy < h * 0.05 or cy > h * 0.98 or cx > w * 0.95:
            continue
        for marker in APP_LIBRARY_CATEGORY_MARKERS:
            if _matches(text, (marker,), fuzzy=0.82):
                category_hits.add(marker)
                break
    if len(category_hits) < 3:
        return None
    bottom_home_search = any(
        _matches(_text(el), HOME_SEARCH_LABELS, fuzzy=0.78)
        and el.box.center[1] > h * 0.78
        for el in scene.elements
    )
    if bottom_home_search:
        return None
    return ("app_library_categories",)


def _looks_like_springboard(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    w, h = viewport_size
    if _looks_like_settings_grouped_control_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_wifi_settings_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_about_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_software_update_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_storage_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_screen_time_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_health_data_detail(scene, viewport_size=(w, h)):
        return False
    if _looks_like_settings_detail_body(scene, viewport_size=(w, h)):
        return False
    labels: list[UIElement] = []
    for el in scene.elements:
        text = _text(el)
        if not text or el.type in {"nav_back", "status_bar"}:
            continue
        _cx, cy = el.box.center
        if cy < h * 0.10 or cy > h * 0.94:
            continue
        if el.box.w > w * 0.55 or el.box.h > h * 0.06:
            continue
        if len(text) > 18:
            continue
        labels.append(el)
    if len(labels) < 3:
        return False
    xs = [el.box.center[0] for el in labels]
    ys = [el.box.center[1] for el in labels]
    spread_x = max(xs) - min(xs)
    row_count = len({round(y / max(1, h * 0.11)) for y in ys})
    col_count = len({round(x / max(1, w * 0.18)) for x in xs})
    if len(labels) >= 6 and spread_x >= w * 0.45 and row_count >= 3 and col_count >= 3:
        return True
    bottom_search = any(
        _matches(_text(el), HOME_SEARCH_LABELS, fuzzy=0.78)
        and el.box.center[1] > h * 0.78
        for el in scene.elements
    )
    if bottom_search and spread_x >= w * 0.40 and row_count >= 2:
        return True
    if _looks_like_settings_detail(scene, viewport_size=(w, h)):
        return False
    return spread_x >= w * 0.40 and row_count >= 2
