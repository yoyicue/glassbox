"""iOS Settings crawl policy.

This module owns Settings-specific labels and safety decisions. It must remain
free of device actions, sleeps, test-runner control flow, and walkthrough imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from glassbox.cognition import UIElement
from glassbox.cognition.text_match import canonical_label, compact_text, fuzzy_ratio
from glassbox.crawl.policy import CrawlState, NavigationCandidate, PageInfo
from glassbox.ios.progress import is_time_text, stable_visible_texts
from glassbox.ios.scene import (
    SETTINGS_TITLE_LABELS,
    IOSSceneClassification,
    classify_ios_scene,
    settings_detail_semantic_guess,
)
from skills.regression.ios_settings.sections import (
    root_section_for_canonical_label,
    section_vocab_for,
)

ROOT_TITLE = SETTINGS_TITLE_LABELS
HARNESS_APP_MARKERS = ("GlassboxHelper", "Mac 大脑", "服务有问题", "最近活动")
FAILURE_CATEGORY_KEYS = ("perception", "operation", "recovery", "efficiency", "safety")

UNSAFE_OR_NON_NAV_TEXT = (
    "飞行模式", "Airplane Mode",
    "VPN",
    "个人热点", "Personal Hotspot",
    "我的网络", "My Networks", "其他网络", "Other Networks", "其他", "Other",
    "我的设备", "My Devices", "其他设备", "Other Devices",
    "忽略此网络", "Forget This Network", "自动加入", "Auto-Join",
    "密码", "Password", "低数据模式", "Low Data Mode",
    "私有无线局域网地址", "Private Wi-Fi Address", "无线局域网地址", "Wi-Fi Address",
    "配置IP", "Configure IP", "IP地址", "IP Address",
    "自动", "Auto",
    "搜索", "Search",
    "编辑", "Edit",
    "删除", "Delete",
    "抹掉", "Erase",
    "还原", "Reset",
    "退出登录", "Sign Out",
    "Apple账户", "Apple 账户", "iCloud", "登录与安全性", "Media & Purchases",
    "媒体与购买项目",
    "进一步了解", "Learn More",
    "Game Center",
)

EXPECTED_ROOT_NAV_TEXT = (
    "无线局域网", "Wi-Fi",
    "蓝牙", "Bluetooth",
    "蜂窝网络", "Cellular",
    "通知", "Notifications",
    "声音与触感", "Sounds & Haptics",
    "专注模式", "Focus",
    "屏幕使用时间", "Screen Time",
    "通用", "General",
    "辅助功能", "Accessibility",
    "Siri",
    "操作按钮", "Action Button",
    "待机显示", "伴机息示", "待机見示", "StandBy",
    "Face ID与密码", "Face ID & Passcode",
    "紧急 SOS", "Emergency SOS", "隐私与安全性", "Privacy & Security",
    "电池", "Battery", "钱包与 Apple Pay", "Wallet & Apple Pay",
)

SAFE_NAV_TEXT = (
    *EXPECTED_ROOT_NAV_TEXT,
    # Top-level read-only Settings pages that are not in the shared 17-label
    # acceptance vocabulary but are safe to enter and observe. iOS does not always
    # render a detectable disclosure chevron for these, so they need an explicit
    # safe-known decision (otherwise they are rejected as unknown_navigation_label
    # at root).
    "相机", "Camera",
    "墙纸", "Wallpaper",
    "控制中心", "Control Centre", "Control Center",
    "显示与亮度", "Display & Brightness",
    "多任务与手势", "Multitasking & Gestures",
    "Apple Pencil",
    "主屏幕与 App 资源库", "Home Screen & App Library", "Home Screen &",
    "App 资源库", "App Library",
    "Safari浏览器", "Safari",
    "FaceTime 通话", "FaceTime",
    "Apps",
    "Game Center",
    "Weather",
    "Books",
    "Translate",
    "关于本机", "About",
    "软件更新", "Software Update",
    "iPhone 储存空间", "iPhone Storage",
    "AppleCare与保修", "AppleCare & Warranty",
    "隔空投送", "AirDrop",
    "隔空播放与连续互通", "AirPlay & Continuity",
    "画中画", "Picture in Picture",
    "屏幕捕捉", "Screen Capture",
    "CarPlay车载", "CarPlay",
    "语言与地区", "Language & Region",
    "词典", "Dictionary",
    "VPN与设备管理", "VPN & Device Management",
    "日期与时间", "Date & Time",
    "键盘", "Keyboard",
    "字体", "Fonts",
    "传输或还原iPhone", "Transfer or Reset iPhone",
    "停用时间", "Downtime",
    "App限额", "App Limits",
    "始终允许", "Always Allowed",
    "屏幕距离", "Screen Distance",
    "限定通信", "Communication Limits",
    "通信安全", "Communication Safety",
    "内容与隐私限制", "Content & Privacy Restrictions",
)

EXPECTED_ROOT_NAV_TEXT_ZH = (
    "无线局域网",
    "蓝牙",
    "蜂窝网络",
    "通知",
    "声音与触感",
    "专注模式",
    "屏幕使用时间",
    "通用",
    "辅助功能",
    "Siri",
    "操作按钮",
    "待机显示",
    "Face ID与密码",
    "紧急 SOS",
    "隐私与安全性",
    "电池",
    "钱包与 Apple Pay",
)

ROOT_NAV_VISUAL_ORDER_ZH = (
    "无线局域网",
    "蓝牙",
    "蜂窝网络",
    "电池",
    "通用",
    "辅助功能",
    "操作按钮",
    "待机显示",
    "Siri",
    "通知",
    "声音与触感",
    "专注模式",
    "屏幕使用时间",
    "Face ID与密码",
    "紧急 SOS",
    "隐私与安全性",
    "钱包与 Apple Pay",
)

ROOT_LABEL_ALIASES = {
    "伴机息示": "待机显示",
    "伴机見示": "待机显示",
    "伴机貝示": "待机显示",
    "供机息示": "待机显示",
    "供机見示": "待机显示",
    "供机貝示": "待机显示",
    "待机見示": "待机显示",
    "待机貝示": "待机显示",
    "0日": "待机显示",
    "9日": "待机显示",
    "O日": "待机显示",
    "〇日": "待机显示",
    "0E": "待机显示",
    "OE": "待机显示",
    "〇E": "待机显示",
    "甩池": "电池",
    "声效与触感反馈": "声音与触感",
    "声音与触感反馈": "声音与触感",
    "声音与触感": "声音与触感",
    "屏幕时间": "屏幕使用时间",
    "SOS": "紧急 SOS",
    "SOS紧急联络": "紧急 SOS",
    "SOS 紧急联络": "紧急 SOS",
    "紧急联络": "紧急 SOS",
    "面容ID与密码": "Face ID与密码",
    "面容 ID与密码": "Face ID与密码",
    "面容 ID 与密码": "Face ID与密码",
    "Wi-Fi": "无线局域网",
    "Bluetooth": "蓝牙",
    "Cellular": "蜂窝网络",
    "Notifications": "通知",
    "Sounds": "声音与触感",
    "Sounds & Haptics": "声音与触感",
    "Focus": "专注模式",
    "Screen Time": "屏幕使用时间",
    "All Devices": "屏幕使用时间",
    "General": "通用",
    "Accessibility": "辅助功能",
    "Action Button": "操作按钮",
    "StandBy": "待机显示",
    "Face ID & Passcode": "Face ID与密码",
    "Touch ID & Passcode": "Face ID与密码",
    "Emergency SOS": "紧急 SOS",
    "Privacy & Security": "隐私与安全性",
    "Battery": "电池",
    "Wallet & Apple Pay": "钱包与 Apple Pay",
}

# Locale-overlay aliases, applied only when the active resolved PACK KEY matches
# (NOT folded into the global map). Keyed by language+region pack key, not bare
# region: greater-China *English* labels (WLAN / Mobile Service) are live-observed
# in both en-CN and en-HK, but NOT in en-US or any zh pack (zh shows Chinese).
_GREATER_CHINA_EN_OVERLAY = {
    "WLAN": "无线局域网",
    "Mobile Service": "蜂窝网络",
}
ROOT_LABEL_LOCALE_ALIASES: dict[str, dict[str, str]] = {
    "en-CN": _GREATER_CHINA_EN_OVERLAY,
    "en-HK": _GREATER_CHINA_EN_OVERLAY,
}

ROOT_SEARCH_QUERIES = {
    "无线局域网": "wuxianjuyuwang",
    "蓝牙": "lanya",
    "蜂窝网络": "fengwowangluo",
    "通知": "tongzhi",
    "声音与触感": "shengyin",
    "专注模式": "zhuanzhumoshi",
    "屏幕使用时间": "pingmushiyongshijian",
    "通用": "tongyong",
    "辅助功能": "fuzhugongneng",
    "Siri": "siri",
    "操作按钮": "caozuoanniu",
    "待机显示": "daijixianshi",
    "Face ID与密码": "mianrongidmima",
    "紧急 SOS": "jinjisos",
    "隐私与安全性": "yinsiyuanquan",
    "电池": "dianchi",
    "钱包与 Apple Pay": "qianbao",
}

ROOT_SEARCH_QUERIES_EN = {
    "无线局域网": "Wi-Fi",
    "蓝牙": "Bluetooth",
    "蜂窝网络": "Cellular",
    "通知": "Notifications",
    "声音与触感": "Sounds",
    "专注模式": "Focus",
    "屏幕使用时间": "Screen Time",
    "通用": "General",
    "辅助功能": "Accessibility",
    "Siri": "Siri",
    "操作按钮": "Action Button",
    "待机显示": "StandBy",
    "Face ID与密码": "Touch ID & Passcode",
    "紧急 SOS": "Emergency SOS",
    "隐私与安全性": "Privacy & Security",
    "电池": "Battery",
    "钱包与 Apple Pay": "Wallet",
}

ROOT_SEARCH_QUERIES_GREATER_CHINA_EN = {
    **ROOT_SEARCH_QUERIES_EN,
    "无线局域网": "WLAN",
    "蜂窝网络": "Mobile Service",
}
IPAD_ROOT_SEARCH_QUERIES_EN = {
    # iPadOS top search on the live rig can collapse spaces/ampersands while
    # typing, producing no-results for exact multi-token queries. Use shorter
    # stable prefixes for iPad-only search fallback; title-checking still gates
    # whether the opened result credits the requested root.
    "屏幕使用时间": "Screen",
    "Face ID与密码": "Passcode",
    "隐私与安全性": "Privacy",
}
IPAD_EXTRA_TOP_LEVEL_ROOT_SEARCH_QUERIES_EN = {
    "Camera": "Camera",
    "Wallpaper": "Wallpaper",
    "Control Centre": "Control Centre",
    "Control Center": "Control Center",
    "Display & Brightness": "Display",
    "Multitasking & Gestures": "Multitasking",
    "Apple Pencil": "Apple Pencil",
    "Home Screen & App Library": "Home Screen",
    "Safari": "Safari",
    "Safari浏览器": "Safari",
    "FaceTime": "FaceTime",
    "FaceTime 通话": "FaceTime",
    "Apps": "Apps",
    "Game Center": "Game Center",
    "Weather": "Weather",
    "Books": "Books",
    "Translate": "Translate",
}

NAV_TITLE_ALIASES = {
    "Safari浏览器": ("Safari",),
    "FaceTime 通话": ("FaceTime",),
    "主屏幕与 App 资源库": ("主屏幕", "Home Screen"),
    "钱包与 Apple Pay": ("钱包", "Wallet"),
    "操作按钮": ("静音模式", "Silent Mode"),
}
ROOT_ONLY_UNSAFE_OVERRIDES = (
    "Face ID与密码",
    "Face ID & Passcode",
    "密码",
    "Passwords",
)
ROOT_COVERAGE_ONLY_LABELS = (
    "钱包与 Apple Pay",
    "Wallet & Apple Pay",
)
IPAD_SEARCH_ABSENT_DEVICE_UNAVAILABLE_ROOT_LABELS = (
    # These are expected iPhone-oriented roots in the shared Settings vocabulary,
    # but they are device/profile-dependent on iPadOS. Treat them as unavailable
    # only after an iPad report records Settings search as no-result, so a
    # capable iPad/iPhone still has to prove entry.
    "蜂窝网络",
    "操作按钮",
    "待机显示",
    "紧急 SOS",
)

# A no-SIM iPhone shows one of these on the Mobile Service row and the row is
# tap-inert (it does not open a detail page), so 蜂窝网络 is *device-unavailable*,
# not a coverage miss. Detected from what the crawl actually saw — on a SIM'd
# device none of these appear and Cellular stays a required, enterable section.
_NO_SIM_MARKERS = (
    "No SIM", "No SIM Card", "Insert a SIM",
    "无 SIM", "无SIM", "未安装 SIM", "未插入 SIM", "无 SIM 卡",
)


def detect_device_unavailable_root_labels(
    visits,
    navigation_failures=(),
    *,
    platform: str | None = None,
    phone_model: str | None = None,
) -> set[str]:
    """Canonical root labels this *device* cannot open, inferred from seen text.

    Returns canonical zh labels so callers can treat them as entry-exempt
    without a manual flag. Cellular remains required by default; on iPadOS,
    iPhone-oriented roots are exempted only when Settings search itself reports
    no result for that root in the captured run."""
    joined = "\n".join(
        str(t)
        for v in visits or ()
        for t in (getattr(v, "texts", None) if not isinstance(v, dict) else v.get("texts")) or ()
    ).casefold()
    out: set[str] = set()
    if any(marker.casefold() in joined for marker in _NO_SIM_MARKERS):
        out.add("蜂窝网络")
    if _is_ipad_device_context(platform=platform, phone_model=phone_model):
        ipad_unavailable = {
            canonical_label(
                label,
                EXPECTED_ROOT_NAV_TEXT_ZH,
                aliases={**ROOT_LABEL_ALIASES, **_GREATER_CHINA_EN_OVERLAY},
                fuzzy=0.82,
                max_leading_noise_chars=1,
            )
            for label in IPAD_SEARCH_ABSENT_DEVICE_UNAVAILABLE_ROOT_LABELS
        }
        for failure in navigation_failures or ():
            if (getattr(failure, "reason", None) if not isinstance(failure, dict) else failure.get("reason")) != "search_no_result":
                continue
            text = getattr(failure, "text", None) if not isinstance(failure, dict) else failure.get("text")
            label = canonical_label(
                str(text or ""),
                EXPECTED_ROOT_NAV_TEXT_ZH,
                aliases={**ROOT_LABEL_ALIASES, **_GREATER_CHINA_EN_OVERLAY},
                fuzzy=0.82,
                max_leading_noise_chars=1,
            )
            if label in ipad_unavailable:
                out.add(label)
    return out


def _is_ipad_device_context(*, platform: str | None, phone_model: str | None) -> bool:
    platform_key = str(platform or "").lower().replace("-", "_")
    model_key = str(phone_model or "").lower().replace("-", "_")
    return platform_key == "ipados" or model_key.startswith("ipad")


def _active_section_vocab():
    from glassbox.config import get_config

    cfg = get_config()
    return section_vocab_for(cfg.language, cfg.region)
# Whole-label-only non-nav tokens. These are toggle/picker *state values*, not
# topics: a row is non-navigational only when its ENTIRE label is the token.
# Kept out of the substring tier (UNSAFE_OR_NON_NAV_TEXT) because as substrings
# they over-match real English nav rows ("On" inside "NotificatiOns"/
# "ActiOnButtOn") and even Chinese ("关" inside "关于本机"/About). Matched on
# compacted+casefolded text so OCR spacing/case doesn't slip a toggle through.
EXACT_UNSAFE_OR_NON_NAV_TEXT = {"App", "打开", "关闭", "开", "关", "On", "Off"}
BLOCKED_CHILD_NAVIGATION_MARKERS = (
    ("输入密码", (), "authentication required"),
    ("输入iPhone密码", (), "authentication required"),
    ("输入 iPhone 密码", (), "authentication required"),
    ("Enter Passcode", (), "authentication required"),
    ("iPhone Passcode", (), "authentication required"),
    ("欢迎来到 Game Center", (), "game center onboarding requires action"),
    ("Welcome to Game Center", (), "game center onboarding requires action"),
    ("自定义你的个人资料", (), "game center profile setup requires action"),
    ("Customize Your Profile", (), "game center profile setup requires action"),
    ("接入无线局域网", (), "dynamic Wi-Fi rows"),
    ("无线局域网", ("我的网络", "其他网络", "忽略此网络", "自动加入"), "dynamic Wi-Fi rows"),
    ("Wi-Fi", ("My Networks", "Other Networks", "Forget This Network", "Auto-Join"), "dynamic Wi-Fi rows"),
    ("WLAN", ("Networks", "Other", "Auto-Join"), "dynamic Wi-Fi rows"),
    ("蓝牙", ("我的设备", "其他设备"), "dynamic Bluetooth device rows"),
    ("蓝牙", ("设备",), "dynamic Bluetooth device rows"),
    ("Bluetooth", ("My Devices", "Other Devices"), "dynamic Bluetooth device rows"),
    ("Bluetooth", ("Devices",), "dynamic Bluetooth device rows"),
    ("Allow Safari to Access", ("Siri", "Search"), "app permission/access selector rows"),
    ("Allow Weather to Access", ("Location", "Siri", "Search"), "app permission/access selector rows"),
    (
        "Allow Location Access",
        ("Never", "Ask Next Time", "While Using", "Always", "Precise Location"),
        "app permission/access selector rows",
    ),
    ("Control Centre", ("Customise Control Centre", "Reset Control Centre"), "control centre customization/reset rows"),
    ("Wallpaper", ("Customise", "Add New Wallpaper", "Lock Screen"), "wallpaper customization rows"),
    (
        "Home Screen & App Library",
        ("Newly Downloaded Apps", "Add to Home Screen", "App Library Only", "Use Large App Icons"),
        "home screen layout selector rows",
    ),
    (
        "Multitasking & Gestures",
        ("Full-Screen Apps", "Windowed Apps", "Stage Manager"),
        "multitasking layout selector rows",
    ),
    ("Touch ID & Passcode", ("Use Touch ID For", "Fingerprints", "Turn Passcode On", "Change Passcode"), "passcode and biometric settings"),
    ("Face ID & Passcode", ("Use Face ID For", "Face ID", "Turn Passcode On", "Change Passcode"), "passcode and biometric settings"),
    ("电池", ("充电上限", "优化电池充电", "电池百分比"), "Battery selector/toggle rows"),
    ("Battery", ("Charging Limit", "Optimized Battery Charging", "Battery Percentage"), "Battery selector/toggle rows"),
    ("通知", ("显示为", "定时推送摘要", "显示预览", "通知样式"), "Notification selector/toggle rows"),
    ("Notifications", ("Display As", "Scheduled Summary", "Show Previews", "Notification Style"), "Notification selector/toggle rows"),
    ("通知", ("允许通知", "即时通知", "提醒", "声音", "标记"), "Notification app selector/toggle rows"),
    ("Notifications", ("Allow Notifications", "Immediate Delivery", "Alerts", "Sounds", "Badges"), "Notification app selector/toggle rows"),
    ("显示预览", ("始终", "解锁时", "永不"), "Notification preview selector rows"),
    ("Show Previews", ("Always", "When Unlocked", "Never"), "Notification preview selector rows"),
    ("隔空投送", ("接收关闭", "仅限联系人", "所有人（10分钟）"), "AirDrop selector rows"),
    ("AirDrop", ("Receiving Off", "Contacts Only", "Everyone"), "AirDrop selector rows"),
)


def _blocked_child_navigation_reason_from_texts(texts: list[str] | tuple[str, ...]) -> str | None:
    stable = stable_visible_texts(texts)
    joined = "\n".join(stable)
    for page_marker, row_markers, reason in BLOCKED_CHILD_NAVIGATION_MARKERS:
        page_key = compact_text(page_marker).casefold()
        row_keys = tuple(compact_text(marker).casefold() for marker in row_markers)
        if page_key in joined and (not row_keys or any(marker in joined for marker in row_keys)):
            return reason
    return None


class PageVisitLike(Protocol):
    path: tuple[str, ...]


@dataclass(frozen=True)
class CandidateRejection:
    text: str
    reason: str


class SettingsPolicy:
    """Pure Settings crawl decisions."""

    def classify(self, observation) -> PageInfo:
        """AI facade policy hook over ``ObservationSummary``.

        The existing Settings crawler still uses the richer ``Scene`` methods
        below. This adapter keeps Settings-specific labels in this policy module
        without teaching ``glassbox.ai`` about Settings pages.
        """
        texts = tuple(text for text in getattr(observation, "visible_texts", ()) if text)
        if getattr(observation, "page_id", None):
            return PageInfo(
                page_id=observation.page_id,
                title=texts[0] if texts else None,
                confidence=0.8,
                evidence=texts[:5],
            )
        if any(self.canonical_expected_root_label(text) for text in texts):
            return PageInfo("settings/root", title="Settings", confidence=0.7, evidence=texts[:5])
        if any(self.matches_label(text, "关于本机") or self.matches_label(text, "About") for text in texts):
            return PageInfo("settings/general", title="General", confidence=0.7, evidence=texts[:5])
        return PageInfo(None, confidence=0.0, evidence=texts[:5])

    def candidates(self, observation) -> list[NavigationCandidate]:
        out: list[NavigationCandidate] = []
        seen: set[str] = set()
        for text in getattr(observation, "visible_texts", ()):
            text = str(text).strip()
            if not text or text in seen or self.is_unsafe_navigation_text(text):
                continue
            seen.add(text)
            if self.is_safe_known_navigation_label(text):
                out.append(NavigationCandidate(label=text, action="tap", confidence=0.6, reason="visible_settings_label"))
        return out

    def is_safe(self, candidate: NavigationCandidate, _observation) -> bool:
        return candidate.action == "tap" and not self.is_unsafe_navigation_text(candidate.label)

    def should_stop(self, state: CrawlState) -> bool:
        return bool(state.found) or int(state.steps) >= 40

    def classify_scene(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> IOSSceneClassification | None:
        try:
            if viewport_size is not None:
                return classify_ios_scene(scene, viewport_size=viewport_size)
            return classify_ios_scene(scene)
        except Exception:
            return None

    def scene_type(self, scene, *, viewport_size: tuple[int, int] | None = None) -> str:
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        if classified is not None:
            return classified.kind
        if self.scene_is_settings_root(scene, viewport_size=viewport_size):
            return "settings_root"
        if self.is_settings_search_scene(scene, viewport_size=viewport_size):
            return (
                "settings_search_results"
                if self.looks_like_settings_search_results(scene)
                else "settings_search_home"
            )
        if self.blocked_child_navigation_reason(scene) is not None:
            return "settings_blocked_safety"
        if self.scene_looks_like_settings_detail(scene, viewport_size=viewport_size):
            return "settings_detail"
        try:
            from glassbox.ios.springboard import is_ios_home_screen

            if is_ios_home_screen(scene, viewport_size=viewport_size):
                return "springboard_or_app_library"
        except Exception:
            pass
        return "unknown"

    def scene_kind(self, scene, *, viewport_size: tuple[int, int] | None = None) -> str:
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        if classified is not None:
            return classified.kind
        return self.scene_type(scene, viewport_size=viewport_size)

    def scene_is_settings_root(self, scene, *, viewport_size: tuple[int, int] | None = None) -> bool:
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        return classified is not None and classified.kind == "settings_root"

    def scene_looks_like_settings_detail(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> bool:
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        if classified is not None:
            if classified.kind == "settings_detail":
                return True
            if classified.kind in {"springboard", "springboard_or_app_library"}:
                return settings_detail_semantic_guess(scene, viewport_size=viewport_size) is not None
            if classified.kind != "unknown":
                return False
        if self.scene_is_settings_root(scene, viewport_size=viewport_size) or self.is_settings_search_scene(
            scene,
            viewport_size=viewport_size,
        ):
            return False
        if self.has_visible_back_affordance(scene):
            return True
        title = self.page_title(scene)
        if title == "?":
            return False
        has_center_title = any(
            (element.text or "").strip() == title
            and 50 <= element.box.center[1] <= 170
            and 120 <= element.box.center[0] <= 328
            for element in scene.elements
        )
        if not has_center_title:
            return False
        long_rows = 0
        left_rows = 0
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text or element.type == "status_bar" or element.box.center[1] <= 160:
                continue
            if element.box.w >= 200 or len(text) >= 18:
                long_rows += 1
            if element.box.center[0] <= 190 and len(text) <= 28:
                left_rows += 1
        return long_rows >= 2 and left_rows >= 2

    def is_safe_top_left_back_fallback_scene(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> bool:
        if self.blocked_child_navigation_reason(scene) is not None:
            return False
        kind = self.scene_kind(scene, viewport_size=viewport_size)
        if kind == "settings_detail" or self.scene_looks_like_settings_detail(scene, viewport_size=viewport_size):
            return True
        title = self.page_title(scene)
        return self.canonical_expected_root_label(title) is not None or self.is_safe_known_navigation_label(title)

    def is_settings_search_scene(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> bool:
        if self.has_visible_back_affordance(scene) or self.scene_is_settings_root(scene, viewport_size=viewport_size):
            return False
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        if classified is not None:
            if classified.kind in {"settings_search_home", "settings_search_results"}:
                return True
            if classified.kind in {
                "settings_root",
                "settings_detail",
                "settings_blocked_safety",
                "system_search",
                "springboard",
                "app_library",
            }:
                return False
        texts = set(self.texts(scene))
        if any(text.startswith("未找到") for text in texts):
            return True
        return self.settings_search_has_bottom_chrome(scene) or self.looks_like_settings_search_results(scene)

    def settings_search_has_bottom_chrome(self, scene) -> bool:
        bottom_compact = re.sub(
            r"\s+",
            "",
            "".join(
                (element.text or "").strip()
                for element in scene.elements
                if element.box.center[1] >= 850
            ),
        )
        if "搜索App" in bottom_compact or "SearchApp" in bottom_compact:
            return False
        has_bottom_search_field = any(
            element.box.center[1] >= 850
            and self.is_settings_search_affordance_text((element.text or "").strip())
            for element in scene.elements
        )
        has_bottom_clear = any(
            (element.text or "").strip() in {"×", "X"}
            and element.box.center[0] >= 300
            and element.box.center[1] >= 850
            for element in scene.elements
        )
        has_bottom_query = any(
            self._is_bottom_search_query_candidate(element, has_clear_button=has_bottom_clear)
            for element in scene.elements
        )
        return has_bottom_search_field or has_bottom_clear or has_bottom_query

    def looks_like_settings_search_results(self, scene) -> bool:
        if self.has_visible_back_affordance(scene):
            return False
        root_hits = 0
        path_hint_hits = 0
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text:
                continue
            cx, cy = element.box.center
            if cy < 95 or cy > 900:
                continue
            if cx <= 180 and self.canonical_expected_root_label(text) is not None:
                root_hits += 1
            if self._looks_like_settings_search_path_hint(text):
                path_hint_hits += 1
        return root_hits >= 2 and path_hint_hits >= 1

    def _looks_like_settings_search_path_hint(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        if "～" in compact:
            return True
        if not (">" in compact or "›" in compact or "＞" in compact):
            return False
        if len(compact) < 4:
            return False
        parts = [part for part in re.split(r"[>›＞]", compact) if part]
        return self.canonical_expected_root_label(compact) is not None or any(
            self.canonical_expected_root_label(part) is not None for part in parts
        )

    def is_settings_search_affordance_text(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        if compact in {"Q", "q"}:
            return False
        if "搜索App" in compact or "SearchApp" in compact:
            return False
        return "搜索" in text or "Search" in text or fuzzy_ratio(text, "搜索") >= 0.78 or fuzzy_ratio(text, "Search") >= 0.78

    def _is_bottom_search_query_candidate(self, element, *, has_clear_button: bool) -> bool:
        text = (element.text or "").strip()
        if not text or element.box.center[1] < 850:
            return False
        compact = re.sub(r"\s+", "", text)
        if compact in {"Q", "q", "×", "X"}:
            return False
        if "搜索App" in compact or "SearchApp" in compact:
            return False
        if self.is_settings_search_affordance_text(text):
            return False
        if element.type == "tab_bar_item" and not has_clear_button:
            return False
        if element.box.center[0] > 300:
            return False
        return len(compact) >= 2

    def settings_search_has_query_text(self, scene) -> bool:
        has_clear_button = self.find_search_clear_button(scene) is not None
        for element in scene.elements:
            if self._is_bottom_search_query_candidate(element, has_clear_button=has_clear_button):
                return True
        return False

    def find_system_search_root_result(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> tuple[UIElement, str] | None:
        if self.scene_kind(scene, viewport_size=viewport_size) != "system_search":
            return None
        candidates: list[tuple[int, UIElement, str]] = []
        seen: set[str] = set()
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text:
                continue
            label = self.canonical_expected_root_label(text)
            if label is None or label in seen:
                continue
            if self.is_unsafe_navigation_text(label):
                continue
            cx, cy = element.box.center
            if cy < 150 or cy > 860 or cx > 240:
                continue
            candidates.append((cy, element, label))
            seen.add(label)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        _cy, element, label = candidates[0]
        return element, label

    def find_settings_tab_in_search(self, scene) -> UIElement | None:
        if not self.is_settings_search_scene(scene):
            return None
        tabs = [
            element for element in scene.elements
            if (element.text or "").strip() in ROOT_TITLE
            and element.box.center[1] >= 840
        ]
        if not tabs:
            return None
        tabs.sort(key=lambda element: (element.box.center[1], element.box.center[0]))
        return tabs[0]

    def find_visible_root_result_from_search(self, scene) -> UIElement | None:
        if not self.is_settings_search_scene(scene) or self.looks_like_settings_search_results(scene):
            return None
        candidates: list[tuple[int, UIElement]] = []
        seen: set[str] = set()
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text:
                continue
            label = self.canonical_expected_root_label(text)
            if label is None or label in seen:
                continue
            cx, cy = element.box.center
            if cy < 300 or cy > 860 or cx > 280:
                continue
            candidates.append((cy, element))
            seen.add(label)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def find_search_clear_button(self, scene) -> UIElement | None:
        close_buttons = [
            element for element in scene.elements
            if (element.text or "").strip() in {"×", "X"}
            and element.box.center[0] >= 300
            and element.box.center[1] >= 850
        ]
        if not close_buttons:
            return None
        close_buttons.sort(key=lambda element: element.box.center[0], reverse=True)
        return close_buttons[0]

    def find_root_search_tab(self, scene) -> UIElement | None:
        search_tabs = [
            element for element in scene.elements
            if self.is_settings_search_affordance_text((element.text or "").strip())
            and element.box.center[1] >= 850
        ]
        if not search_tabs:
            return None
        search_tabs.sort(key=lambda element: element.box.center[1], reverse=True)
        return search_tabs[0]

    def find_search_field(self, scene) -> UIElement | None:
        clear_button = self.find_search_clear_button(scene)
        fields = []
        if clear_button is not None:
            fields.extend(
                element for element in scene.elements
                if self._is_bottom_search_query_candidate(element, has_clear_button=True)
                and element.box.center[0] < clear_button.box.center[0]
            )
        if not fields:
            fields = [
                element for element in scene.elements
                if element.box.center[1] >= 850
                and self.is_settings_search_affordance_text((element.text or "").strip())
            ]
        if not fields:
            return None
        fields.sort(key=lambda element: element.box.center[0])
        return fields[0]

    def page_title(self, scene) -> str:
        candidates = [
            element for element in scene.elements
            if (
                element.text
                and element.type != "nav_back"
                and element.text.strip() not in {"<", "‹", "〈", "返回", "Back"}
                and not is_time_text(element.text)
                and 50 <= element.box.center[1] <= 170
                and len(element.text.strip()) <= 18
            )
        ]
        if not candidates:
            texts = self.texts(scene)
            return texts[0] if texts else "?"
        candidates.sort(key=lambda element: (abs(element.box.center[1] - 90), abs(element.box.center[0] - 224)))
        return candidates[0].text.strip()

    def matches_label(self, text: str, label: str) -> bool:
        normalized = compact_text(text)
        candidate = compact_text(label)
        return normalized == candidate or fuzzy_ratio(normalized, candidate) >= 0.82

    def title_matches_navigation_label(self, title: str, label: str) -> bool:
        if self.matches_label(title, label):
            return True
        return any(self.matches_label(title, alias) for alias in NAV_TITLE_ALIASES.get(label, ()))

    def canonical_expected_root_label(self, text: str) -> str | None:
        return canonical_label(
            text,
            EXPECTED_ROOT_NAV_TEXT_ZH,
            aliases=self._active_root_aliases(),
            fuzzy=0.82,
            max_leading_noise_chars=1,
        )

    @staticmethod
    def _active_root_aliases() -> dict[str, str]:
        """Base aliases + the active locale PACK's overlay (if any).

        Compatibility bridge: reads the active locale from the global config
        (resolved pack key, e.g. ``en-CN``) rather than a per-instance injected
        SectionVocab. Locale-pack-specific labels (China-region English WLAN /
        Mobile Service) are accepted ONLY under their pack (``en-CN``) — a zh,
        en-US, or zh-Hans-CN run does not resolve them. The full DI model
        (`SettingsPolicy(sections=locale.app("settings").sections)`) is deferred.
        """
        from glassbox.config import get_config
        from glassbox.locale import resolve_locale

        overlay = ROOT_LABEL_LOCALE_ALIASES.get(resolve_locale(get_config()).code)
        if not overlay:
            return ROOT_LABEL_ALIASES
        return {**ROOT_LABEL_ALIASES, **overlay}

    def is_safe_known_navigation_label(self, text: str) -> bool:
        if self.canonical_expected_root_label(text) is not None:
            return True
        return any(self.matches_label(text, label) for label in SAFE_NAV_TEXT)

    def is_unsafe_navigation_text(
        self,
        text: str,
        *,
        allow_sensitive_root_labels: bool = False,
    ) -> bool:
        if compact_text(text).casefold() in {
            compact_text(value).casefold() for value in EXACT_UNSAFE_OR_NON_NAV_TEXT
        }:
            return True
        if allow_sensitive_root_labels:
            # Match the override against the raw text AND its canonical root
            # label. OCR often reads e.g. "面容ID与密码" (Chinese) which does not
            # fuzzy-match the English "Face ID与密码" override but canonicalizes
            # to it; without this it falls through to the "密码" substring rule
            # and the row is wrongly dropped as unsafe at the root.
            canonical = self.canonical_expected_root_label(text)
            for label in ROOT_ONLY_UNSAFE_OVERRIDES:
                if self.matches_label(text, label) or (
                    canonical is not None and self.matches_label(canonical, label)
                ):
                    return False
        if not self.is_root_only_unsafe_override(text) and self.is_exact_safe_navigation_label(text):
            return False
        compact = compact_text(text).casefold()
        return any(compact_text(bad).casefold() in compact for bad in UNSAFE_OR_NON_NAV_TEXT)

    def is_exact_safe_navigation_label(self, text: str) -> bool:
        normalized = compact_text(text)
        return any(normalized == compact_text(label) for label in SAFE_NAV_TEXT)

    def is_root_only_unsafe_override(self, text: str) -> bool:
        return any(self.matches_label(text, label) for label in ROOT_ONLY_UNSAFE_OVERRIDES)

    def blocked_child_navigation_reason(self, scene) -> str | None:
        # The Settings ROOT is never a "blocked child page": its sibling rows
        # (e.g. a "Notifications" row next to a "Sounds & Haptics" row) can
        # spuriously match a child page_marker+row_marker pair and falsely block
        # the root, aborting the crawl. Detail pages still classify normally.
        if self.scene_is_settings_root(scene):
            return None
        return _blocked_child_navigation_reason_from_texts(self.texts(scene))

    def blocks_child_navigation(self, scene) -> bool:
        return self.blocked_child_navigation_reason(scene) is not None

    def safe_navigation_candidates(
        self,
        scene,
        *,
        allow_sensitive_root_labels: bool = False,
        allow_known_without_affordance: bool = True,
    ) -> list[UIElement]:
        if self.blocks_child_navigation(scene):
            return []

        candidates: list[UIElement] = []
        seen: set[str] = set()
        for element in scene.elements:
            text = self.potential_navigation_row_text(element)
            if not text or text in seen:
                continue
            seen.add(text)
            if self.is_settings_section_header(scene, element):
                continue
            if (
                self.is_unsafe_navigation_text(
                    text,
                    allow_sensitive_root_labels=allow_sensitive_root_labels,
                )
                or (
                    allow_sensitive_root_labels
                    and self.canonical_expected_root_label(text) in ROOT_COVERAGE_ONLY_LABELS
                )
            ):
                continue
            if not self.is_safe_known_navigation_label(text):
                if not self.has_navigation_affordance(scene, element):
                    continue
            elif not allow_known_without_affordance and not self.has_navigation_affordance(scene, element):
                continue
            candidates.append(element)
        candidates.sort(key=lambda element: element.box.center[1])
        return candidates

    def rejected_candidate_rows(
        self,
        scene,
        *,
        allow_sensitive_root_labels: bool,
        allow_known_without_affordance: bool,
    ) -> list[CandidateRejection]:
        if self.blocks_child_navigation(scene):
            return []
        rejected: list[CandidateRejection] = []
        seen_texts: set[str] = set()
        for element in scene.elements:
            text = self.potential_navigation_row_text(element)
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            if (
                self.is_unsafe_navigation_text(
                    text,
                    allow_sensitive_root_labels=allow_sensitive_root_labels,
                )
                or (
                    allow_sensitive_root_labels
                    and self.canonical_expected_root_label(text) in ROOT_COVERAGE_ONLY_LABELS
                )
            ):
                reason = "unsafe_text"
            else:
                if self.has_navigation_affordance(scene, element):
                    continue
                if self.is_safe_known_navigation_label(text):
                    reason = (
                        "missing_navigation_affordance"
                        if not allow_known_without_affordance else "unknown_navigation_label"
                    )
                    if allow_known_without_affordance:
                        continue
                else:
                    reason = "unknown_navigation_label"
            rejected.append(CandidateRejection(text=text, reason=reason))
        return rejected

    def potential_navigation_row_text(self, element: UIElement) -> str | None:
        text = (element.text or "").strip()
        if not text:
            return None
        cx, cy = element.box.center
        if cy < 260 or cy > 900 or cx > 260:
            return None
        if len(text) <= 3 and (text[0] in "([（【〈《" or text[-1] in ")]）】〉》"):
            return None
        if len(text) <= 1 or text.replace(":", "").isdigit():
            return None
        if re.fullmatch(r"[\d\s%％.,/:-]+", text):
            return None
        if len(text) <= 2 and text.isascii() and not self.is_safe_known_navigation_label(text):
            return None
        if text.isascii() and not text[0].isalnum() and not self.is_safe_known_navigation_label(text):
            return None
        if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
            return None
        if len(text) > 48:
            return None
        if text in ROOT_TITLE or text in HARNESS_APP_MARKERS:
            return None
        return text

    def is_settings_section_header(self, scene, element: UIElement) -> bool:
        if not self.has_visible_back_affordance(scene):
            return False
        text = (element.text or "").strip()
        if not text or self.is_safe_known_navigation_label(text):
            return False
        if element.box.x > 60 or element.box.w > 110:
            return False
        _, cy = element.box.center
        has_indented_row_below = any(
            (other.text or "").strip()
            and other is not element
            and other.box.x >= element.box.x + 24
            and 18 <= other.box.center[1] - cy <= 96
            and other.box.center[0] <= 260
            for other in scene.elements
        )
        has_same_row_trailing = any(
            (other.text or "").strip()
            and other is not element
            and abs(other.box.center[1] - cy) <= 16
            and other.box.center[0] > element.box.x + element.box.w
            for other in scene.elements
        )
        return has_indented_row_below or not has_same_row_trailing

    def has_navigation_affordance(self, scene, element: UIElement) -> bool:
        if element.type in {"list_item", "button"}:
            return True
        _, cy = element.box.center
        return any(
            (other.text or "").strip() in (">", "›", "→", "❯", "˃")
            and abs(other.box.center[1] - cy) < 32
            and other.box.center[0] > 320
            for other in scene.elements
        )

    def has_visible_back_affordance(self, scene) -> bool:
        return self.find_visible_back(scene) is not None

    def find_visible_back(self, scene) -> UIElement | None:
        candidates = [
            element for element in scene.elements
            if self.is_visible_back_element(element)
            and element.box.center[0] <= 120
            and element.box.center[1] <= 180
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda element: (element.box.center[0], element.box.center[1]))
        return candidates[0]

    def is_visible_back_element(self, element: UIElement) -> bool:
        return (
            element.type == "nav_back"
            or (element.text or "").strip() in {"<", "‹", "〈", "返回", "Back"}
        )

    def root_coverage(self, visits: list[PageVisitLike]) -> dict[str, list[str]]:
        visited: set[str] = set()
        for visit in visits:
            if len(visit.path) < 2:
                continue
            label = self.canonical_expected_root_label(visit.path[1])
            if label is not None:
                visited.add(label)
        expected = list(EXPECTED_ROOT_NAV_TEXT_ZH)
        return {
            "expected": expected,
            "visited": [label for label in expected if label in visited],
            "missing": [label for label in expected if label not in visited],
        }

    def root_search_query(self, label: str) -> str | None:
        try:
            from glassbox.config import get_config
            from glassbox.locale import resolve_locale

            locale = resolve_locale(get_config())
            if locale.language == "en":
                if locale.code in {"en-CN", "en-HK"}:
                    return ROOT_SEARCH_QUERIES_GREATER_CHINA_EN.get(label)
                return ROOT_SEARCH_QUERIES_EN.get(label)
        except Exception:
            pass
        return ROOT_SEARCH_QUERIES.get(label)

    def visible_root_row_label(self, element: UIElement) -> str | None:
        text = (element.text or "").strip()
        if not text:
            return None
        cy = element.box.center[1]
        if cy < 110 or cy > 910:
            return None
        return self.canonical_expected_root_label(text)

    def should_recover_root_row_ocr(self, element: UIElement) -> bool:
        text = (element.text or "").strip()
        return 2 <= len(text) <= 14 and element.box.center[0] < 200

    def find_search_result(self, scene, label: str) -> UIElement | None:
        matches: list[tuple[int, UIElement]] = []
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text:
                continue
            cx, cy = element.box.center
            if cy < 95 or cy > 860 or cx > 280:
                continue
            if self.canonical_expected_root_label(text) == label or self.matches_label(text, label):
                matches.append(element)
        if not matches:
            return None
        matches.sort(key=lambda element: (element.box.center[1], element.box.center[0]))
        return matches[0]

    def find_search_query_suggestion(self, scene, label: str) -> UIElement | None:
        label_compact = re.sub(r"\s+", "", label)
        matches: list[tuple[int, UIElement]] = []
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text:
                continue
            _cx, cy = element.box.center
            if cy < 840 or cy > 905:
                continue
            if text.startswith(("Q", "q")) or text in {"×", "X"}:
                continue
            candidate = re.sub(r"^\s*\d+\s*", "", text)
            candidate_compact = re.sub(r"\s+", "", candidate)
            if not candidate_compact:
                continue
            canonical = self.canonical_expected_root_label(candidate)
            if canonical == label or label_compact in candidate_compact:
                score = 0
            elif self.matches_label(candidate, label):
                score = 1
            else:
                continue
            matches.append((score, element))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], item[1].box.center[1], item[1].box.center[0]))
        return matches[0][1]

    def texts(self, scene) -> list[str]:
        out: list[str] = []
        for element in scene.elements:
            text = (element.text or "").strip()
            if text:
                out.append(text)
        return out


class IPadSettingsPolicy(SettingsPolicy):
    """Settings policy variant for iPadOS split-view Settings."""

    _RELAXABLE_SELECTOR_BLOCK_REASONS = frozenset({
        "Battery selector/toggle rows",
        "Notification selector/toggle rows",
    })

    def classify_scene(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> IOSSceneClassification | None:
        try:
            from glassbox.ipados.scene import classify_ipados_scene

            return classify_ipados_scene(scene, viewport_size=viewport_size)
        except Exception:
            return None

    def scene_is_settings_root(self, scene, *, viewport_size: tuple[int, int] | None = None) -> bool:
        if self._ipad_search_active(scene):
            return False
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        if classified is None:
            return False
        if classified.kind == "settings_root":
            return True
        return "ipad_split_view" in set(classified.evidence or ()) and "tap_root_row" in set(
            classified.safe_actions or (),
        )

    def is_settings_search_scene(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> bool:
        if getattr(scene, "platform_scene_kind", None) == "springboard":
            return False
        if self._ipad_search_active(scene):
            return True
        return super().is_settings_search_scene(scene, viewport_size=viewport_size)

    def settings_search_has_query_text(self, scene) -> bool:
        if getattr(scene, "platform_scene_kind", None) == "springboard":
            return False
        if self._ipad_top_search_field(scene, allow_query=True) is not None:
            return self._ipad_search_query_text(scene) is not None
        return super().settings_search_has_query_text(scene)

    def find_root_search_tab(self, scene) -> UIElement | None:
        field = self._ipad_top_search_field(scene, allow_query=False)
        if field is not None:
            return field
        return super().find_root_search_tab(scene)

    def find_search_field(self, scene) -> UIElement | None:
        field = self._ipad_top_search_field(scene, allow_query=True)
        if field is not None:
            return field
        return super().find_search_field(scene)

    def find_search_result(self, scene, label: str) -> UIElement | None:
        ipad_search_active = self._ipad_search_active(scene)
        if not ipad_search_active and not self.looks_like_settings_search_results(scene):
            return None
        viewport_size = getattr(scene, "viewport_size", None) or self._scene_extent(scene)
        from glassbox.ipados.scene import sidebar_right_x

        sidebar_right = sidebar_right_x(viewport_size[0])
        matches: list[tuple[int, UIElement]] = []
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text:
                continue
            cx, cy = element.box.center
            if cy < 140 or cy > int(viewport_size[1] * 0.94) or cx > sidebar_right + 24:
                continue
            primary = self._search_result_primary_label(text)
            if (
                self.canonical_expected_root_label(primary) == label
                or self.canonical_expected_root_label(text) == label
                or self.matches_label(primary, label)
                or self.matches_label(text, label)
            ):
                if self._is_query_suggestion_result_line(scene, element, label):
                    continue
                anchor = self._search_result_row_anchor(scene, element, label)
                matches.append((self._root_search_result_rank(text, label), anchor))
        if matches:
            matches.sort(key=lambda item: (item[0], item[1].box.center[1], item[1].box.center[0]))
            return matches[0][1]
        if ipad_search_active:
            return None
        return super().find_search_result(scene, label)

    def root_search_query(self, label: str) -> str | None:
        try:
            from glassbox.config import get_config
            from glassbox.locale import resolve_locale

            locale = resolve_locale(get_config())
            if locale.language == "en":
                override = IPAD_ROOT_SEARCH_QUERIES_EN.get(label)
                if override is not None:
                    return override
                extra = IPAD_EXTRA_TOP_LEVEL_ROOT_SEARCH_QUERIES_EN.get(label)
                if extra is not None:
                    return extra
        except Exception:
            pass
        return super().root_search_query(label)

    def find_system_search_root_result(
        self,
        scene,
        *,
        viewport_size: tuple[int, int] | None = None,
    ) -> tuple[UIElement, str] | None:
        if self.scene_kind(scene, viewport_size=viewport_size) != "system_search":
            return None
        open_buttons = [
            element for element in scene.elements
            if (element.text or "").strip() in {"Open", "打开"}
            and element.box.center[1] <= 160
        ]
        if open_buttons:
            open_buttons.sort(key=lambda element: (element.box.center[1], element.box.center[0]))
            return open_buttons[0], "Settings"
        settings_hits = [
            element for element in scene.elements
            if (element.text or "").strip() in ROOT_TITLE
            and 120 <= element.box.center[1] <= 340
            and element.box.center[0] <= 260
        ]
        if settings_hits:
            settings_hits.sort(key=lambda element: (element.box.center[1], element.box.center[0]))
            return settings_hits[0], "Settings"
        return super().find_system_search_root_result(scene, viewport_size=viewport_size)

    def page_title(self, scene) -> str:
        viewport_size = getattr(scene, "viewport_size", None)
        classified = self.classify_scene(scene, viewport_size=viewport_size)
        if classified is not None and classified.title:
            return classified.title
        return super().page_title(scene)

    def blocked_child_navigation_reason(self, scene) -> str | None:
        reason = super().blocked_child_navigation_reason(scene)
        if reason is None:
            reason = _blocked_child_navigation_reason_from_texts(self.texts(scene))
        if reason not in self._RELAXABLE_SELECTOR_BLOCK_REASONS:
            return reason
        if self._ipad_search_active(scene):
            return reason
        if self._has_safe_detail_disclosure_candidate(scene):
            return None
        return reason

    def safe_navigation_candidates(
        self,
        scene,
        *,
        allow_sensitive_root_labels: bool = False,
        allow_known_without_affordance: bool = True,
    ) -> list[UIElement]:
        if self.blocks_child_navigation(scene):
            return []
        viewport_size = getattr(scene, "viewport_size", None) or self._scene_extent(scene)
        from glassbox.ipados.scene import sidebar_right_x

        sidebar_right = sidebar_right_x(viewport_size[0])
        candidates: list[UIElement] = []
        seen: set[str] = set()
        current_detail_title = None if allow_sensitive_root_labels else self.page_title(scene)
        current_detail_canonical = (
            self.canonical_expected_root_label(current_detail_title or "")
            if current_detail_title else None
        )
        for element in scene.elements:
            if allow_sensitive_root_labels:
                text = self._potential_sidebar_navigation_row_text(
                    element,
                    viewport_size=viewport_size,
                    sidebar_right=sidebar_right,
                )
            else:
                text = self._potential_detail_navigation_row_text(
                    element,
                    viewport_size=viewport_size,
                    sidebar_right=sidebar_right,
                )
            if not text or text in seen:
                continue
            if current_detail_title and (
                self.title_matches_navigation_label(current_detail_title, text)
                or (
                    current_detail_canonical is not None
                    and self.canonical_expected_root_label(text) == current_detail_canonical
                )
            ):
                continue
            seen.add(text)
            if self.is_settings_section_header(scene, element):
                continue
            if (
                self.is_unsafe_navigation_text(
                    text,
                    allow_sensitive_root_labels=allow_sensitive_root_labels,
                )
                or (
                    allow_sensitive_root_labels
                    and self.canonical_expected_root_label(text) in ROOT_COVERAGE_ONLY_LABELS
                )
            ):
                continue
            if not self.is_safe_known_navigation_label(text):
                if not self.has_navigation_affordance(scene, element):
                    continue
            elif (
                not allow_known_without_affordance
                and not self.has_navigation_affordance(scene, element)
                and not self.is_exact_safe_navigation_label(text)
            ):
                continue
            candidates.append(element)
        candidates.sort(key=lambda element: element.box.center[1])
        return candidates

    def has_navigation_affordance(self, scene, element: UIElement) -> bool:
        if element.type in {"list_item", "button"}:
            return True
        viewport_size = getattr(scene, "viewport_size", None) or self._scene_extent(scene)
        from glassbox.ipados.scene import sidebar_right_x

        sidebar_right = sidebar_right_x(viewport_size[0])
        cx, cy = element.box.center
        if cx > sidebar_right + 24:
            return any(
                self._text_has_disclosure_affordance(other.text or "")
                and abs(other.box.center[1] - cy) < 32
                and other.box.center[0] > max(element.box.center[0], element.box.x + element.box.w)
                and other.box.center[0] > sidebar_right + 24
                for other in scene.elements
            )
        return any(
            self._text_has_disclosure_affordance(other.text or "")
            and abs(other.box.center[1] - cy) < 32
            and element.box.center[0] < other.box.center[0] <= sidebar_right + 32
            for other in scene.elements
        )

    @staticmethod
    def _text_has_disclosure_affordance(text: str) -> bool:
        return bool(re.search(r"[>›→❯˃＞]\s*$", (text or "").strip()))

    def _has_safe_detail_disclosure_candidate(self, scene) -> bool:
        viewport_size = getattr(scene, "viewport_size", None) or self._scene_extent(scene)
        from glassbox.ipados.scene import sidebar_right_x

        sidebar_right = sidebar_right_x(viewport_size[0])
        current_detail_title = self.page_title(scene)
        for element in scene.elements:
            text = self._potential_detail_navigation_row_text(
                element,
                viewport_size=viewport_size,
                sidebar_right=sidebar_right,
            )
            if not text:
                continue
            if current_detail_title and self.title_matches_navigation_label(current_detail_title, text):
                continue
            if self.is_settings_section_header(scene, element) or self.is_unsafe_navigation_text(text):
                continue
            if self.has_navigation_affordance(scene, element):
                return True
        return False

    def find_visible_back(self, scene) -> UIElement | None:
        classified = self.classify_scene(scene, viewport_size=getattr(scene, "viewport_size", None))
        if classified is not None and "ipad_split_view" in set(classified.evidence or ()):
            viewport_size = getattr(scene, "viewport_size", None) or self._scene_extent(scene)
            from glassbox.ipados.scene import sidebar_right_x

            sidebar_right = sidebar_right_x(viewport_size[0])
            candidates = [
                element for element in scene.elements
                if self.is_visible_back_element(element)
                and element.box.center[0] >= sidebar_right - 8
                and element.box.x <= sidebar_right + 48
                and element.box.center[1] <= int(viewport_size[1] * 0.18)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda element: (element.box.center[1], element.box.center[0]))
            return candidates[0]
        return super().find_visible_back(scene)

    def _potential_sidebar_navigation_row_text(
        self,
        element: UIElement,
        *,
        viewport_size: tuple[int, int],
        sidebar_right: int,
    ) -> str | None:
        text = (element.text or "").strip()
        if not text:
            return None
        _w, h = viewport_size
        cx, cy = element.box.center
        if cy < int(h * 0.10) or cy > int(h * 0.96) or cx > sidebar_right:
            return None
        if cy <= int(h * 0.18) and re.match(r"^[Qq]\s+", text):
            return None
        if len(text) <= 3 and (text[0] in "([（【〈《" or text[-1] in ")]）】〉》"):
            return None
        if len(text) <= 1 or text.replace(":", "").isdigit():
            return None
        if re.fullmatch(r"[\d\s%％.,/:-]+", text):
            return None
        if len(text) <= 2 and text.isascii() and not self.is_safe_known_navigation_label(text):
            return None
        if text.isascii() and not text[0].isalnum() and not self.is_safe_known_navigation_label(text):
            return None
        if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
            return None
        if len(text) > 48:
            return None
        if text in ROOT_TITLE or text in HARNESS_APP_MARKERS:
            return None
        return text

    def _potential_detail_navigation_row_text(
        self,
        element: UIElement,
        *,
        viewport_size: tuple[int, int],
        sidebar_right: int,
    ) -> str | None:
        text = re.sub(r"\s*[>›→❯˃＞]\s*$", "", (element.text or "").strip()).strip()
        if not text:
            return None
        _w, h = viewport_size
        cx, cy = element.box.center
        if cy < int(h * 0.12) or cy > int(h * 0.96) or cx <= sidebar_right + 24:
            return None
        if len(text) <= 3 and (text[0] in "([（【〈《" or text[-1] in ")]）】〉》"):
            return None
        if len(text) <= 1 or text.replace(":", "").isdigit():
            return None
        if re.fullmatch(r"[\d\s%％.,/:-]+", text):
            return None
        if len(text) <= 2 and text.isascii() and not self.is_safe_known_navigation_label(text):
            return None
        if text.isascii() and not text[0].isalnum() and not self.is_safe_known_navigation_label(text):
            return None
        if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
            return None
        if len(text) > 64:
            return None
        if text in ROOT_TITLE or text in HARNESS_APP_MARKERS:
            return None
        return text

    def _ipad_search_active(self, scene) -> bool:
        if self._ipad_search_query_text(scene) is not None:
            return True
        if self._ipad_top_search_field(scene, allow_query=True) is not None and self._ipad_search_panel_visible(scene):
            return True
        return any(
            (element.text or "").strip() in {"AutoFill", "AutoFil", "AutoFI", "Select", "Select All", "全选"}
            and element.box.center[0] <= self._ipad_sidebar_right(scene) + 24
            and 110 <= element.box.center[1] <= 170
            for element in scene.elements
        )

    def _ipad_search_panel_visible(self, scene) -> bool:
        sidebar_right = self._ipad_sidebar_right(scene)
        return any(
            (element.text or "").strip() in {"Suggestions", "Recents", "建议", "最近"}
            and element.box.center[0] <= sidebar_right + 24
            and 115 <= element.box.center[1] <= 340
            for element in scene.elements
        )

    def _ipad_search_query_text(self, scene) -> str | None:
        field = self._ipad_top_search_field(scene, allow_query=True)
        if field is None:
            return None
        text = (field.text or "").strip()
        compact = re.sub(r"\s+", "", text)
        if compact.lower() in {"q", "qsearch", "search", "q搜索", "搜索"}:
            return None
        if self.is_settings_search_affordance_text(text):
            return None
        if compact.lower().startswith("qsearch"):
            return compact[len("qsearch"):] or None
        if compact.startswith("Q搜索"):
            return compact[len("Q搜索"):] or None
        return text

    def _ipad_top_search_field(self, scene, *, allow_query: bool) -> UIElement | None:
        sidebar_right = self._ipad_sidebar_right(scene)
        candidates: list[tuple[bool, UIElement]] = []
        for element in scene.elements:
            text = (element.text or "").strip()
            if not text or element.type == "status_bar":
                continue
            if text in ROOT_TITLE:
                continue
            cx, cy = element.box.center
            if cx > sidebar_right + 8 or cy < 72 or cy > 112:
                continue
            compact = re.sub(r"\s+", "", text)
            if compact.isdigit():
                continue
            is_placeholder = (
                self.is_settings_search_affordance_text(text)
                or compact.lower() in {"q", "qsearch"}
                or compact in {"Q搜索"}
            )
            if not is_placeholder and cx > sidebar_right * 0.62:
                continue
            if not allow_query and not is_placeholder:
                continue
            if allow_query and len(compact) > 32:
                continue
            candidates.append((is_placeholder, element))
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                1 if allow_query and item[0] else 0,
                abs(item[1].box.center[1] - 96),
                item[1].box.center[0],
            ),
        )
        return candidates[0][1]

    def _ipad_sidebar_right(self, scene) -> int:
        viewport_size = getattr(scene, "viewport_size", None) or self._scene_extent(scene)
        from glassbox.ipados.scene import sidebar_right_x

        return sidebar_right_x(viewport_size[0])

    @staticmethod
    def _search_result_primary_label(text: str) -> str:
        primary = re.sub(r"^\s*\d+\s*", "", text.strip())
        return re.split(r"\s*(?:→|>|›|＞)\s*", primary, maxsplit=1)[0].strip()

    def _root_search_result_rank(self, text: str, label: str) -> int:
        """Prefer exact root display labels over aliases that also match children.

        Example: searching "Sounds" on iPad can show both a generic child result
        "Sounds" and the root "Sounds & Haptics"; both canonicalize to the same
        root, but only the latter is the root detail we want to tap.
        """
        primary = self._search_result_primary_label(text)
        exact_terms = {label}
        try:
            vocab = _active_section_vocab()
            section = root_section_for_canonical_label(label)
            if section is not None:
                exact_terms.add(vocab.label(section))
        except Exception:
            pass
        exact_norms = {compact_text(term).casefold() for term in exact_terms if term}
        primary_norm = compact_text(primary).casefold()
        text_norm = compact_text(text).casefold()
        if primary_norm in exact_norms:
            return 0
        if text_norm in exact_norms:
            return 1
        return 2

    def _is_query_suggestion_result_line(self, scene, element: UIElement, label: str) -> bool:
        """Skip search query suggestions that masquerade as root results.

        iPad Settings can render a compact suggestion title like ``ScreenTime 6``
        followed by a display line ``Screen Time``. Tapping either line updates
        the query rather than opening the root page, so neither should be used
        as a root result.
        """
        exact = self._exact_root_display_compact(label)
        if not exact:
            return False
        primary = self._search_result_primary_label(element.text or "")
        if self._looks_like_numbered_query_suggestion(primary, exact=exact):
            return True
        ex, ey = element.box.center
        return any(
            self._looks_like_numbered_query_suggestion(
                self._search_result_primary_label(other.text or ""),
                exact=exact,
            )
            for other in scene.elements
            if other is not element
            and (other.text or "").strip()
            and 0 < ey - other.box.center[1] <= 48
            and abs(other.box.center[0] - ex) <= 28
        )

    def _search_result_row_anchor(self, scene, element: UIElement, label: str) -> UIElement:
        """Return the tappable primary row label for split multi-line results.

        iPad Settings search can OCR a result as a primary compact title
        (``ScreenTime 6``) with the actual root display label (``Screen Time``)
        on the next line. Tapping the lower display label does not always open
        the row; prefer the primary line only when it compact-normalizes to the
        same exact display term. This avoids turning generic aliases such as
        ``Sounds`` into anchors for ``Sounds & Haptics``.
        """
        exact = self._exact_root_display_compact(label)
        if not exact:
            return element
        ex, ey = element.box.center
        candidates = [
            other for other in scene.elements
            if other is not element
            and (other.text or "").strip()
            and 0 < ey - other.box.center[1] <= 48
            and abs(other.box.center[0] - ex) <= 28
            and not self._looks_like_numbered_query_suggestion(
                self._search_result_primary_label(other.text or ""),
                exact=exact,
            )
            and self._compact_without_trailing_count(self._search_result_primary_label(other.text or "")) == exact
        ]
        if not candidates:
            return element
        candidates.sort(key=lambda other: (other.box.center[1], other.box.center[0]))
        return candidates[0]

    def _exact_root_display_compact(self, label: str) -> str | None:
        try:
            vocab = _active_section_vocab()
            section = root_section_for_canonical_label(label)
            if section is None:
                return None
            return self._compact_without_trailing_count(vocab.label(section))
        except Exception:
            return None

    @staticmethod
    def _compact_without_trailing_count(text: str) -> str:
        compacted = compact_text(text).casefold()
        return re.sub(r"\d+$", "", compacted)

    def _looks_like_numbered_query_suggestion(self, text: str, *, exact: str) -> bool:
        compacted = compact_text(text).casefold()
        return compacted != exact and compacted.endswith(tuple("0123456789")) and re.sub(r"\d+$", "", compacted) == exact

    @staticmethod
    def _scene_extent(scene) -> tuple[int, int]:
        width = max((element.box.x2 for element in scene.elements), default=744)
        height = max((element.box.y2 for element in scene.elements), default=1133)
        return max(width, 744), max(height, 1133)


def _default_settings_policy() -> SettingsPolicy:
    try:
        from glassbox.config import get_config

        cfg = get_config()
        platform = str(getattr(cfg, "platform", "") or "").lower()
        model = str(getattr(cfg, "phone_model", "") or "").lower().replace("-", "_")
        if platform == "ipados" or model.startswith("ipad"):
            return IPadSettingsPolicy()
    except Exception:
        pass
    return SettingsPolicy()


DEFAULT_SETTINGS_POLICY = _default_settings_policy()
