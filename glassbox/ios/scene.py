"""Lightweight iOS scene classification from OCR geometry and text.

This module intentionally stays OCR-first. VLM can refine low-confidence or
stuck states later, but the hot path should be deterministic, cheap, and easy
to unit test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.contracts import (
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR,
    SceneClassification,
    SceneClassificationPrior,
)
from glassbox.cognition.text_match import (
    confusion_compact,
    fuzzy_ratio,
    text_contains,
)
from glassbox.ios._scene_common import (
    element_text,
    marker_hits,
    matches_label,
    scene_size_with_default,
)
from glassbox.ios.weather_surface import looks_like_weather_app_surface

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
# Auto-presented full-screen card sheets (e.g. the Apple Account safety sheet
# "Is this still your phone number?") carry a close-X at the top-right and a
# single card of wide copy plus a bottom action stack. They are NOT
# back-navigable: Cmd-[ / edge-back / top-LEFT corner taps are mirror misses,
# and the loose icon-grid tail of `_looks_like_springboard` mistakes their
# short value rows ("+1 …", "Date added:") for app labels. Veto + anchor +
# abstain: only the close glyph in the top-right band counts as the close
# affordance, and the sheet verdict additionally needs card-shaped copy or the
# known safety-sheet vocabulary — anything weaker falls through unchanged.
MODAL_SHEET_CLOSE_GLYPHS = frozenset({"x", "×", "✕", "✗", "╳"})
# Known auto-presented safety-sheet vocabulary (observed live on the Apple
# Account trusted-number sheet, en). System UI strings, not personal data.
MODAL_SAFETY_SHEET_MARKERS = (
    "is this still your phone number",
    "trusted phone number",
    "trusted number",
    "verify your identity",
)
SETTINGS_DETAIL_SEMANTIC_NOUN_MARKERS = (
    "无线局域网", "Wi-Fi", "WLAN", "蓝牙", "Bluetooth", "蜂窝网络", "Cellular",
    "通知", "Notifications", "声音", "Sounds", "专注", "Focus",
    "屏幕使用时间", "Screen Time", "通用", "General", "辅助功能", "Accessibility",
    "操作按钮", "Action Button", "静音模式", "Silent Mode",
    "面容ID", "Face ID", "Passcode", "密码", "隐私", "Privacy",
    "音频与视觉", "Audio & Visual", "音量控制", "耳机", "联系人", "通讯录",
    "储存空间", "Storage", "系统数据", "卸载未使用", "Offload Unused Apps",
    "电池", "Battery", "电池健康", "充电", "电量模式",
    "屏幕时间", "使用限制", "停用时间", "App限额", "始终允许", "屏幕距离",
    "健康数据", "Health Data", "医疗详细信息", "Medical Details", "医疗急救卡",
    "Location Services", "Tracking", "Calendars", "Contacts", "Files & Folders",
    "Devices", "iPhone Unlock", "Password AutoFill",
)
SETTINGS_DETAIL_SEMANTIC_COPY_MARKERS = (
    "connect to", "view available networks", "manage settings", "nearby hotspots",
    "learn more", "discoverable", "settings is open", "pair an apple watch",
    "manage apps", "access settings", "change your passcode", "use face id",
    "control which apps", "access your data", "location, camera", "microphone",
    "safety protections", "switch between", "silent and ring", "alerts",
    "接入", "可用网络", "附近热点", "进一步了解", "访问", "默认", "管理",
    "控制哪些", "定位服务", "麦克风", "安全保护",
)


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


@dataclass(frozen=True)
class IOSSceneSemanticGuess:
    kind: str
    confidence: float
    title: str | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)


def classify_ios_scene(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
    strict_settings_detail: bool = False,
    prior: SceneClassificationPrior | None = None,
) -> IOSSceneClassification:
    """Classify common iOS surfaces from OCR output.

    Kinds are intentionally broad:
    harness_console, settings_root, settings_search_home,
    settings_search_results, settings_detail, settings_blocked_safety,
    system_search, modal_sheet, springboard, app_library, unknown. The
    confidence field is a deterministic heuristic score, not a calibrated
    probability.
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

    if looks_like_weather_app_surface(scene):
        return IOSSceneClassification(
            kind="unknown",
            confidence=0.30,
            title=title,
            safe_actions=("home", "open_app"),
            evidence=("weather_app_surface",),
        )

    if _looks_like_platform_home_widget_surface(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="springboard",
            confidence=0.84,
            title=title,
            safe_actions=("scan_icons", "search_app"),
            evidence=("platform_springboard", "home_widget_surface"),
        )

    if _looks_like_settings_search_results(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="settings_search_results",
            confidence=0.84,
            title=title,
            safe_actions=("clear_search", "tap_settings_tab", "tap_root_result"),
            evidence=("search_result_rows",),
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

    semantic_detail = settings_detail_semantic_guess(
        scene, viewport_size=(w, h), strict=strict_settings_detail
    )
    if semantic_detail is not None:
        if _settings_detail_resisted_by_prior(
            prior,
            read_confidence=semantic_detail.confidence,
        ):
            return _settings_detail_prior_abstain(
                title=semantic_detail.title or title,
                prior=prior,
                evidence=semantic_detail.evidence,
            )
        # C2 fix (S3, docs/design/iphone_settings_transition.md): mint the page
        # identity from the nav-band title when one is visible. The semantic
        # guess scans the body band (cy >= h*0.11) and structurally excludes
        # the real centered nav title (cy≈92px on iPhone frames), so it minted
        # first content rows like 'Silent Mode' over the visible real title
        # 'Sounds & Haptics'. Prefer `_page_title` and fall back to the guess —
        # aligning this branch with the settings_detail sibling below. The
        # nav-band winner must carry >=3 semantic chars, or >=2 CJK chars (the
        # same rule the semantic candidate applies), or OCR junk like '+' /
        # 'I!I,' from the nav bar would replace a correct body-derived identity.
        nav_title = title if has_semantic_title_chars(title) else None
        detail_title = nav_title or semantic_detail.title
        return IOSSceneClassification(
            kind="settings_detail",
            confidence=semantic_detail.confidence,
            page_id=f"settings/{detail_title}" if detail_title else None,
            title=detail_title or title,
            safe_actions=("back", "edge_back"),
            evidence=semantic_detail.evidence,
        )

    if _looks_like_purchase_paywall(scene, viewport_size=(w, h)):
        # A foreign app's in-app-purchase paywall (e.g. a drifted-into RemoteAC).
        # Not Home and not a Settings page: return unknown so recovery backs out
        # instead of "tapping the Settings icon" (which could hit Subscribe).
        return IOSSceneClassification(
            kind="unknown",
            confidence=0.30,
            title=title,
            safe_actions=("edge_back", "back", "trace"),
            evidence=("purchase_paywall",),
        )

    appstore_evidence = _app_store_chrome_evidence(scene, viewport_size=(w, h))
    if appstore_evidence is not None:
        return IOSSceneClassification(
            kind="unknown",
            confidence=0.34,
            title=title,
            safe_actions=("trace", "vlm_on_uncertain"),
            evidence=appstore_evidence,
        )

    modal_evidence = modal_sheet_overlay_evidence(scene, viewport_size=(w, h))
    if modal_evidence is not None:
        # Must outrank the springboard icon-grid tail below: the live Apple
        # Account safety sheet's short value rows spread like app labels and
        # were classified springboard(0.82, icon_grid), sending recovery into
        # a useless springboard climb instead of tapping the close-X.
        return IOSSceneClassification(
            kind="modal_sheet",
            confidence=0.86,
            title=title,
            safe_actions=("dismiss_modal", "trace"),
            evidence=modal_evidence,
        )

    if _looks_like_springboard(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="springboard",
            confidence=0.82,
            title=title,
            safe_actions=("scan_icons", "search_app"),
            evidence=("icon_grid",),
        )

    if _has_settings_search_chrome(scene, viewport_size=(w, h)):
        return IOSSceneClassification(
            kind="settings_search_home",
            confidence=0.86,
            title=title,
            safe_actions=("clear_search", "tap_settings_tab", "type_query"),
            evidence=("bottom_search_chrome",),
        )

    if _looks_like_settings_detail(scene, viewport_size=(w, h), strict_body=strict_settings_detail):
        if not _has_settings_distinguishing_signal(scene):
            return IOSSceneClassification(
                kind="unknown",
                confidence=0.24,
                title=title,
                safe_actions=("trace", "vlm_on_uncertain"),
                evidence=("settings_detail_abstain", "missing_settings_anchor"),
            )
        if _settings_detail_resisted_by_prior(prior, read_confidence=0.78):
            return _settings_detail_prior_abstain(
                title=title,
                prior=prior,
                evidence=("center_title_or_back", "detail_rows"),
            )
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
    prior: SceneClassificationPrior | None = None,
) -> IOSSceneClassification:
    """Project the iOS classifier result onto a Scene.

    This keeps the platform-specific classifier outside generic memory:
    callers that are intentionally operating on iOS surfaces run this helper
    before handing the Scene to ScreenMemory. Existing Layer 3/profile
    `scene_type` is preserved unless `overwrite_scene_type=True`.
    """
    classified = classify_ios_scene(scene, viewport_size=viewport_size, prior=prior)
    DEFAULT_SCENE_CLASSIFICATION_PROJECTOR.project(
        scene,
        [classified.to_scene_classification()],
        overwrite_scene_type=overwrite_scene_type,
    )
    scene.classification_source = "ios"
    return classified


_SETTINGS_PRIOR_RESIST_MARGIN = 0.08


def _settings_detail_resisted_by_prior(
    prior: SceneClassificationPrior | None,
    *,
    read_confidence: float,
) -> bool:
    """Return True when a weak Settings-detail read conflicts with a known app prior."""
    if prior is None:
        return False
    try:
        recognition_score = float(prior.recognition_score)
    except (TypeError, ValueError):
        return False
    if recognition_score < float(read_confidence) + _SETTINGS_PRIOR_RESIST_MARGIN:
        return False
    prior_page = str(prior.page_id or "").strip().lower()
    prior_kind = str(prior.platform_scene_kind or prior.semantic_scene_type or prior.scene_type or "").strip().lower()
    if prior_page.startswith("settings/") or prior_kind.startswith("settings"):
        return False
    action = str(prior.last_action_op or "").strip().lower()
    target = str(prior.last_action_target or "").casefold()
    if action in {"open_app", "launch_app"} and target in {"settings", "设置"}:
        return False
    if prior_kind in {"app_store", "appstore", "app_store_search"}:
        return True
    if prior_page.startswith(("app_store", "appstore")):
        return True
    return bool(prior_page) and not prior_page.startswith(("springboard", "home", "app_library"))


def _settings_detail_prior_abstain(
    *,
    title: str | None,
    prior: SceneClassificationPrior | None,
    evidence: tuple[str, ...],
) -> IOSSceneClassification:
    prior_kind = str(getattr(prior, "platform_scene_kind", None) or getattr(prior, "page_id", None) or "unknown")
    return IOSSceneClassification(
        kind="unknown",
        confidence=0.26,
        title=title,
        safe_actions=("trace", "vlm_on_uncertain"),
        evidence=("settings_detail_prior_abstain", f"prior:{prior_kind}", *evidence[:3]),
    )


def _scene_size(scene: Scene, viewport_size: tuple[int, int] | None) -> tuple[int, int]:
    return scene_size_with_default(scene, viewport_size, default_size=(448, 973))


def _text(el: UIElement) -> str:
    return element_text(el)


def _matches(text: str, labels, *, fuzzy: float = 0.78) -> bool:
    # OCR visual-confusion tolerance lives in the shared iOS-family matcher.
    return matches_label(text, labels, fuzzy=fuzzy)


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
        # A bare "Suggestions"/"建议" title is the WEAK signal owned by the
        # branch below; without this exclusion it fuzzy-leaks into the hard
        # markers via "Siri Suggestions" (ratio ≈0.81 ≥ 0.78) and bypasses the
        # weak branch's geometry gates and abstain veto entirely.
        and _text(el) not in {"建议", "Suggestions"}
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
    if not (has_unqueried_search and (has_app_category or has_recent_label)):
        return False
    # Weak-branch abstain veto: the Settings app's OWN untyped search pane also
    # shows a "Suggestions" title, a "Recents" section, and bottom search
    # chrome — but its rows are Settings root labels (General, Screen Time,
    # Privacy & Security, …), while genuine Spotlight suggests *apps*. Claiming
    # system_search here is a task-killer (callers mark Settings search
    # unavailable and press Home before any query is typed; live:
    # iphone_transition_n1 view_0065), whereas falling through to
    # settings_search_home is recoverable — typed Spotlight re-enters via the
    # hard-marker branch above, which this veto never touches.
    return _settings_root_label_row_count(scene, viewport_size=(w, h)) < 2


def _settings_root_label_row_count(scene: Scene, *, viewport_size: tuple[int, int]) -> int:
    """Distinct left-column list-band texts that are known Settings root labels."""
    w, h = viewport_size
    counted: set[str] = set()
    for el in scene.elements:
        text = _text(el)
        if not text or text in counted:
            continue
        cx, cy = el.box.center
        if cx > w * 0.45 or not (h * 0.10 <= cy <= h * 0.86):
            continue
        if _is_known_settings_root_label(text):
            counted.add(text)
    return len(counted)


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


def modal_sheet_close_affordance(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> UIElement | None:
    """Find a sheet close-X affordance in the top-right band, else None.

    Anchor discipline: only a bare close glyph whose center sits at
    cx >= 0.80w and 0.04h <= cy <= 0.16h qualifies (the live Apple Account
    safety sheet renders its X at ~(0.90w, 0.11h)). Bottom search-field clear
    buttons (cy >= 0.86h) and left-side chrome can never match.
    """
    w, h = _scene_size(scene, viewport_size)
    for el in scene.elements:
        text = _text(el)
        if not text or text.casefold() not in MODAL_SHEET_CLOSE_GLYPHS:
            continue
        cx, cy = el.box.center
        if cx >= w * 0.80 and h * 0.04 <= cy <= h * 0.16:
            return el
    return None


def modal_sheet_close_point(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Tap point for dismissing a modal sheet: the OCR'd X if present, else the
    canonical top-right close region (~0.90w, 0.11h). Always inside the
    top-right band — never a content/button row."""
    w, h = _scene_size(scene, viewport_size)
    close = modal_sheet_close_affordance(scene, viewport_size=(w, h))
    if close is not None:
        cx, cy = close.box.center
        return int(cx), int(cy)
    return round(w * 0.90), round(h * 0.11)


def modal_sheet_overlay_evidence(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> tuple[str, ...] | None:
    """Detect an auto-presented full-screen card sheet; None means abstain.

    Veto: scenes that already carry strong root/search/home/App-Library/blocked
    evidence are never a dismissible sheet. Anchors (either suffices):

    - close-X affordance in the top-right band PLUS a card shape (>= 2 distinct
      safety-vocabulary hits, or >= 3 wide copy lines with a centered bottom
      action stack);
    - >= 3 distinct safety-sheet vocabulary hits (covers perceives where the
      small X glyph dropped out of OCR).
    """
    w, h = _scene_size(scene, viewport_size)
    if (
        _blocked_safety_marker(scene) is not None
        or _is_settings_root(scene, viewport_size=(w, h))
        or _has_settings_search_chrome(scene, viewport_size=(w, h))
        or _looks_like_system_search(scene, viewport_size=(w, h))
        or _app_library_evidence(scene, viewport_size=(w, h)) is not None
        or _has_strong_home_evidence(scene, viewport_size=(w, h))
    ):
        return None

    joined = "\n".join(_text(el) for el in scene.elements if _text(el)).casefold()
    vocab_hits = marker_hits(joined, MODAL_SAFETY_SHEET_MARKERS)
    close = modal_sheet_close_affordance(scene, viewport_size=(w, h))

    wide_copy = 0
    bottom_actions = 0
    for el in scene.elements:
        text = _text(el)
        if not text or el.type == "status_bar":
            continue
        cx, cy = el.box.center
        if el.box.w >= w * 0.55 and h * 0.16 <= cy <= h * 0.85:
            wide_copy += 1
        if (
            h * 0.78 <= cy <= h * 0.97
            and abs(cx - w / 2) <= w * 0.25
            and 8 <= len(text) <= 40
        ):
            bottom_actions += 1

    evidence: list[str] = []
    if close is not None:
        evidence.append("modal_close_affordance")
    if vocab_hits:
        evidence.append(f"safety_sheet_vocabulary:{min(vocab_hits, 4)}")
    if wide_copy >= 3:
        evidence.append(f"sheet_card_copy:{min(wide_copy, 6)}")
    if bottom_actions:
        evidence.append(f"sheet_action_stack:{min(bottom_actions, 3)}")

    if close is not None and (vocab_hits >= 2 or (wide_copy >= 3 and bottom_actions >= 1)):
        return tuple(evidence)
    if vocab_hits >= 3:
        return tuple(evidence)
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


def settings_detail_semantic_guess(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
    strict: bool = False,
) -> IOSSceneSemanticGuess | None:
    """Classify ambiguous iOS Settings detail pages from OCR text and geometry.

    This is deliberately a fallback, not a replacement for hard scene gates:
    root/search/blocked/App Library/Home evidence wins before this can return.

    CUQ-2.6: when ``strict``, require at least one Settings system-noun
    (Wi-Fi/Bluetooth/Face ID/…) — a guess resting only on locale-generic copy
    markers (访问/管理/默认/…) is the third-party-app false-positive.
    """
    w, h = _scene_size(scene, viewport_size)
    if (
        _blocked_safety_marker(scene) is not None
        or _is_settings_root(scene, viewport_size=(w, h))
        or _has_settings_search_chrome(scene, viewport_size=(w, h))
        or _looks_like_settings_search_results(scene, viewport_size=(w, h))
        or _looks_like_system_search(scene, viewport_size=(w, h))
        or _app_library_evidence(scene, viewport_size=(w, h)) is not None
        or _has_strong_home_evidence(scene, viewport_size=(w, h))
    ):
        return None

    visible = [
        el for el in scene.elements
        if _text(el)
        and el.type != "status_bar"
        and not _TIME_RE.match(_text(el))
        and 0 <= el.box.center[1] <= h
    ]
    if not visible:
        return None

    joined = "\n".join(_text(el) for el in visible).casefold()
    noun_hits = marker_hits(joined, SETTINGS_DETAIL_SEMANTIC_NOUN_MARKERS)
    copy_hits = marker_hits(joined, SETTINGS_DETAIL_SEMANTIC_COPY_MARKERS)
    title = _semantic_detail_title_candidate(visible, viewport_size=(w, h))
    has_back = _has_back_affordance(scene)
    intro_copy_lines = sum(
        1 for el in visible
        if h * 0.10 <= el.box.center[1] <= h * 0.78
        and (el.box.w >= w * 0.42 or len(_text(el)) >= 24)
    )
    left_rows = sum(
        1 for el in visible
        if h * 0.14 <= el.box.center[1] <= h * 0.97
        and el.box.center[0] <= w * 0.48
        and len(_text(el)) <= 36
    )
    grouped_rows = _semantic_grouped_row_bins(visible, viewport_size=(w, h))

    evidence: list[str] = ["semantic_settings_detail"]
    if title:
        evidence.append("semantic_title")
    if has_back:
        evidence.append("back_affordance")
    if noun_hits:
        evidence.append(f"settings_nouns:{min(noun_hits, 4)}")
    if copy_hits:
        evidence.append(f"settings_copy:{min(copy_hits, 4)}")
    if intro_copy_lines:
        evidence.append(f"intro_copy:{min(intro_copy_lines, 4)}")
    if grouped_rows:
        evidence.append(f"grouped_rows:{min(grouped_rows, 6)}")

    score = 0
    score += 3 if title else 0
    score += 3 if copy_hits else 0
    score += 2 if noun_hits else 0
    score += 2 if has_back else 0
    score += 1 if intro_copy_lines else 0
    score += 1 if left_rows >= 2 else 0
    score += 1 if grouped_rows >= 3 else 0

    # CUQ-2.6: under strict, a settings_detail guess must rest on a real Settings
    # system-noun, not locale-generic copy markers alone (third-party-app FP).
    if strict and not noun_hits:
        return None

    if has_back and (copy_hits or noun_hits >= 2) and score >= 6:
        return IOSSceneSemanticGuess(
            kind="settings_detail",
            confidence=0.80,
            title=title,
            evidence=tuple(evidence),
        )
    if title and copy_hits and noun_hits and intro_copy_lines and score >= 8:
        return IOSSceneSemanticGuess(
            kind="settings_detail",
            confidence=0.76,
            title=title,
            evidence=tuple(evidence),
        )
    if title and copy_hits >= 2 and intro_copy_lines and (left_rows >= 2 or grouped_rows >= 3):
        return IOSSceneSemanticGuess(
            kind="settings_detail",
            confidence=0.74,
            title=title,
            evidence=tuple(evidence),
        )
    return None


def has_strong_ios_home_evidence(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
) -> bool:
    return _has_strong_home_evidence(scene, viewport_size=_scene_size(scene, viewport_size))


_SEMANTIC_TITLE_JUNK_RE = re.compile(r"[^0-9A-Za-z一-鿿& ]+")
_CJK_TITLE_CHAR_RE = re.compile(r"[一-鿿]")


def has_semantic_title_chars(text: str | None) -> bool:
    """True when the text carries enough semantic characters to name a page.

    Junk like ``+`` or ``I!I,`` (OCR misreads of nav-bar buttons/icons) fails;
    real titles pass. Two CJK characters are a complete page name (通用, 蓝牙,
    电池 …), so CJK titles need >= 2 semantic chars while Latin titles need
    >= 3 — the same rule the iPadOS detail-pane title picker applies. Without
    the CJK arm, the S3 nav-band mint below discards real zh titles and
    replaces them with the first body row (e.g. 通用 → 关于本机).
    """
    if not text:
        return False
    semantic = _SEMANTIC_TITLE_JUNK_RE.sub("", text).strip()
    return len(semantic) >= 3 or len(_CJK_TITLE_CHAR_RE.findall(semantic)) >= 2


def _semantic_detail_title_candidate(
    visible: list[UIElement],
    *,
    viewport_size: tuple[int, int],
) -> str | None:
    w, h = viewport_size
    candidates: list[UIElement] = []
    ignored = {"编辑", "Edit", "完成", "Done", "搜索", "Search", "Q Search", "Q 搜索"}
    for el in visible:
        text = _text(el)
        if not text or text in ignored or len(text) > 32:
            continue
        if not has_semantic_title_chars(text):
            continue
        cx, cy = el.box.center
        if not (h * 0.11 <= cy <= h * 0.72):
            continue
        if cx <= w * 0.56 or abs(cx - w / 2) <= w * 0.22:
            candidates.append(el)
    if not candidates:
        return None
    candidates.sort(key=lambda el: (el.box.center[1], abs(el.box.center[0] - w / 2), -el.box.w))
    return _text(candidates[0])


def _semantic_grouped_row_bins(
    visible: list[UIElement],
    *,
    viewport_size: tuple[int, int],
) -> int:
    w, h = viewport_size
    bins: set[int] = set()
    for el in visible:
        text = _text(el)
        cx, cy = el.box.center
        if not text or cy < h * 0.18 or cy > h * 0.97:
            continue
        if (
            (cx <= w * 0.58 and len(text) <= 36)
            or (cx >= w * 0.56 and len(text) <= 28 and not text_contains(text, "Search"))
        ):
            bins.add(round(cy / max(1, h * 0.055)))
    return len(bins)


def _has_strong_home_evidence(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    w, h = viewport_size
    if _app_library_evidence(scene, viewport_size=(w, h)) is not None:
        return True
    has_bottom_home_search = any(
        _is_home_search_pill_text(_text(el))
        and el.box.center[1] > h * 0.78
        for el in scene.elements
    )
    if not has_bottom_home_search:
        return False
    labels = [
        el for el in scene.elements
        if _text(el)
        and el.type not in {"status_bar", "nav_back", "tab_bar_item"}
        and h * 0.12 <= el.box.center[1] <= h * 0.80
        and el.box.w <= w * 0.45
        and el.box.h <= h * 0.08
        and len(_text(el)) <= 18
    ]
    if len(labels) < 4:
        return False
    rows = len({round(el.box.center[1] / max(1, h * 0.11)) for el in labels})
    cols = len({round(el.box.center[0] / max(1, w * 0.18)) for el in labels})
    spread_x = max(el.box.center[0] for el in labels) - min(el.box.center[0] for el in labels)
    return rows >= 2 and cols >= 2 and spread_x >= w * 0.34


def _is_home_search_pill_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if "搜索App" in compact or "SearchApp" in compact:
        return False
    return (
        compact in {"搜索", "Q搜索", "Search", "QSearch"}
        or _matches(text, HOME_SEARCH_LABELS, fuzzy=0.86)
    )


def _looks_like_settings_detail(
    scene: Scene, *, viewport_size: tuple[int, int], strict_body: bool = False
) -> bool:
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
    if _looks_like_settings_detail_body(scene, viewport_size=(w, h), strict=strict_body):
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
            or any(marker in _text(el) for marker in ("iPhone", "Apple", "Siri", "隐私", "默认"))
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
    # A bottom Spotlight "Search" pill is a Home/SpringBoard signal — a Settings
    # grouped-control DETAIL page never has one. Without this guard the Today/
    # widget home (weather widget + app-label grid + a top "title") trips the
    # left-rows heuristic and is mis-read as a Settings detail, which then breaks
    # the SpringBoard icon-grid detection and the crawl's home() grounding.
    if any(
        _matches(_text(el), HOME_SEARCH_LABELS, fuzzy=0.78) and el.box.center[1] > h * 0.78
        for el in scene.elements
    ):
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


# CUQ-2.6: footnote phrases that, like the semantic-noun markers, are a
# Settings-specific signal (a Settings detail section almost always carries a
# "Learn More" / 进一步了解 footnote or a recognizable system noun) — used to
# distinguish a real Settings detail page from a third-party app screen that
# merely contains locale-generic body words (允许 / 访问 / App / 通知 ...).
_SETTINGS_LEARN_MORE_MARKERS = (
    "进一步了解", "了解更多", "更多信息", "更多详细信息",
    "Learn More", "More Information", "More Info",
)


def _has_settings_distinguishing_signal(scene: Scene) -> bool:
    """CUQ-2.6: True if the scene carries a Settings-specific marker (a system
    noun like Wi-Fi/Bluetooth/Face ID, or a Learn-More footnote) — not just the
    locale-generic body words that also appear on third-party app screens."""
    for el in scene.elements:
        text = _text(el)
        if not text:
            continue
        if any(marker in text for marker in SETTINGS_DETAIL_SEMANTIC_NOUN_MARKERS):
            return True
        if any(marker in text for marker in _SETTINGS_LEARN_MORE_MARKERS):
            return True
    return False


def _looks_like_settings_detail_body(
    scene: Scene, *, viewport_size: tuple[int, int], strict: bool = False
) -> bool:
    """Recognize scrolled Settings detail pages whose nav bar/title OCR is missing.

    CUQ-2.6: when ``strict``, also require a Settings-distinguishing signal so a
    third-party app screen carrying only locale-generic body words does not
    false-positive as ``settings_detail``.
    """
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

    if not (long_copy >= 1 and left_rows >= 4 and marker_hits >= 3):
        return False
    return not (strict and not _has_settings_distinguishing_signal(scene))


def _looks_like_app_library(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    return _app_library_evidence(scene, viewport_size=viewport_size) is not None


def _app_library_evidence(scene: Scene, *, viewport_size: tuple[int, int]) -> tuple[str, ...] | None:
    w, h = viewport_size
    has_title = any(
        _matches_app_library_title(_text(el))
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


def _matches_app_library_title(text: str) -> bool:
    """Match only the App Library chrome label, not Settings rows mentioning it."""
    compact = confusion_compact(text)
    candidates = [compact]
    # OCR/search-bar prefixes often make the title look like "Q App Library" or
    # "• App Library"; strip one short leading prefix but reject longer copy like
    # "Home Screen & App Library" or "Show App Library in Dock".
    if len(compact) > 1 and compact[0].casefold() in {"q", "o", "0", "•"}:
        candidates.append(compact[1:])
    for label in APP_LIBRARY_LABELS:
        label_compact = confusion_compact(label)
        for candidate in candidates:
            if not candidate:
                continue
            if candidate == label_compact:
                return True
            if abs(len(candidate) - len(label_compact)) <= 2 and fuzzy_ratio(candidate, label_compact) >= 0.82:
                return True
    return False


# In-app purchase / subscription paywalls (a foreign app's, e.g. a drifted-into
# RemoteAC) trip the SpringBoard icon-grid heuristic — feature bullets + plan
# cards + a device mockup spread like an app grid. Misreading one as Home is a
# SAFETY bug: bootstrap would "tap the Settings icon" and could hit Subscribe /
# Continue, triggering a purchase. These commerce tokens never appear on the iOS
# Home screen, so they veto SpringBoard (the frame then falls through to unknown,
# whose recovery backs out instead of tapping content).
_PAYWALL_PRICE_RE = re.compile(
    r"[$¥€£₩]\s?\d"
    r"|\b(?:hk|us)\$|\b(?:rmb|cny|usd|eur|gbp)\b"
    r"|/\s?(?:wk|week|mo|month|yr|year)\b"
    r"|per\s+(?:week|month|year)\b"
    r"|\b(?:weekly|monthly|yearly|annually)\b"
    r"|free\s+trial",
    re.IGNORECASE,
)
_PAYWALL_RESTORE_RE = re.compile(r"\brestore\b", re.IGNORECASE)
_PAYWALL_CTA = (
    "subscribe", "start free trial", "start free", "try free", "free for",
    "unlock", "upgrade", "get pro", "go premium", "claim offer",
)
_PAYWALL_LEGAL = (
    "terms of use", "terms of service", "terms & conditions", "privacy policy",
    "auto-renew", "auto renew", "cancel anytime", "subscription",
)
_APP_STORE_TAB_LABELS = {
    "today",
    "games",
    "apps",
    "arcade",
    "search",
}
_APP_STORE_PRICE_RE = re.compile(r"[$¥€£₩]\s?\d")
_APP_STORE_COMMERCE_LABELS = {
    "get",
    "open",
    "inapppurchases",
    "inapppurchase",
}


def _looks_like_purchase_paywall(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    blob = " ".join(t for t in (_text(el) for el in scene.elements) if t).casefold()
    if not blob:
        return False
    categories = (
        bool(_PAYWALL_PRICE_RE.search(blob)),
        bool(_PAYWALL_RESTORE_RE.search(blob)),
        any(cta in blob for cta in _PAYWALL_CTA),
        any(legal in blob for legal in _PAYWALL_LEGAL),
    )
    # Require ≥2 distinct commerce signals so a lone word (e.g. a Settings page
    # mentioning "Privacy") can never veto a real Home screen.
    return sum(categories) >= 2


def _app_store_chrome_evidence(scene: Scene, *, viewport_size: tuple[int, int]) -> tuple[str, ...] | None:
    w, h = viewport_size
    top_tabs: dict[str, UIElement] = {}
    bottom_tabs: dict[str, UIElement] = {}
    commerce_hits = 0

    for el in scene.elements:
        text = _text(el)
        if not text:
            continue
        compact = re.sub(r"[^0-9a-z]+", "", text.casefold())
        if not compact:
            continue
        cx, cy = el.box.center
        if compact in _APP_STORE_TAB_LABELS:
            if h * 0.04 <= cy <= h * 0.18 and w * 0.20 <= cx <= w * 0.82:
                top_tabs[compact] = el
            if cy >= h * 0.78:
                bottom_tabs[compact] = el
        if _APP_STORE_PRICE_RE.search(text) or compact in _APP_STORE_COMMERCE_LABELS:
            commerce_hits += 1

    evidence: list[str] = []
    for label, tabs in (("appstore_top_tabs", top_tabs), ("appstore_bottom_tabs", bottom_tabs)):
        if len(tabs) < 3:
            continue
        centers = [el.box.center for el in tabs.values()]
        spread_x = max(x for x, _ in centers) - min(x for x, _ in centers)
        spread_y = max(y for _, y in centers) - min(y for _, y in centers)
        if spread_x >= w * 0.08 and spread_y <= h * 0.06:
            evidence.append(label)
    if not evidence:
        return None
    if commerce_hits >= 2:
        evidence.append("appstore_commerce")
    return ("appstore_chrome", *evidence)


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
    if settings_detail_semantic_guess(scene, viewport_size=(w, h)) is not None:
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


def _looks_like_platform_home_widget_surface(scene: Scene, *, viewport_size: tuple[int, int]) -> bool:
    """Recognize iPad Home/Today widget pages before Settings-detail guesses.

    Live iPad widget pages can contain a large weather panel plus short app
    labels; the generic Settings-detail semantic guess may otherwise latch onto
    labels such as Camera/Settings and misclassify Home as Settings detail.
    Only trust this shortcut when the capture stack already reports SpringBoard.
    """
    if str(getattr(scene, "platform_scene_kind", "") or "") != "springboard":
        return False
    w, h = viewport_size
    texts = [_text(el) for el in scene.elements if _text(el)]
    if not texts:
        return False
    widget_markers = {
        "No Events Today",
        "No Notes",
        "Sunny",
        "Cloudy",
        "Drizzle",
        "Rain",
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    }
    weatherish = sum(1 for text in texts if "°" in text or text in widget_markers)
    has_widget_copy = weatherish >= 4 or any(text in {"No Events Today", "No Notes"} for text in texts)
    short_labels = [
        el for el in scene.elements
        if 0.12 * h <= el.box.center[1] <= 0.94 * h
        and 0.06 * w <= el.box.center[0] <= 0.94 * w
        and 1 <= len(_text(el)) <= 18
        and el.box.w <= w * 0.25
    ]
    if len(short_labels) < 4:
        return False
    spread_x = max(el.box.center[0] for el in short_labels) - min(el.box.center[0] for el in short_labels)
    rows = len({round(el.box.center[1] / max(1, h * 0.11)) for el in short_labels})
    app_label_hits = sum(
        1
        for text in texts
        if text in {
            "Settings", "设置", "App Store", "Camera", "Home", "Files", "Maps",
            "Books", "Videos", "FaceTime", "Facetime", "Reminders", "Games",
        }
    )
    return has_widget_copy and (app_label_hits >= 2 or (spread_x >= w * 0.35 and rows >= 2))
