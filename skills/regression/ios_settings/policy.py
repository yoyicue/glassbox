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
    "打开", "关闭", "开", "关", "On", "Off",
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
    "Sounds & Haptics": "声音与触感",
    "Focus": "专注模式",
    "Screen Time": "屏幕使用时间",
    "General": "通用",
    "Accessibility": "辅助功能",
    "Action Button": "操作按钮",
    "StandBy": "待机显示",
    "Face ID & Passcode": "Face ID与密码",
    "Emergency SOS": "紧急 SOS",
    "Privacy & Security": "隐私与安全性",
    "Battery": "电池",
    "Wallet & Apple Pay": "钱包与 Apple Pay",
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
EXACT_UNSAFE_OR_NON_NAV_TEXT = {"App"}
BLOCKED_CHILD_NAVIGATION_MARKERS = (
    ("输入密码", (), "authentication required"),
    ("输入iPhone密码", (), "authentication required"),
    ("输入 iPhone 密码", (), "authentication required"),
    ("Enter Passcode", (), "authentication required"),
    ("iPhone Passcode", (), "authentication required"),
    ("欢迎来到 Game Center", (), "game center onboarding requires action"),
    ("自定义你的个人资料", (), "game center profile setup requires action"),
    ("接入无线局域网", (), "dynamic Wi-Fi rows"),
    ("无线局域网", ("我的网络", "其他网络", "忽略此网络", "自动加入"), "dynamic Wi-Fi rows"),
    ("Wi-Fi", ("My Networks", "Other Networks", "Forget This Network", "Auto-Join"), "dynamic Wi-Fi rows"),
    ("蓝牙", ("我的设备", "其他设备"), "dynamic Bluetooth device rows"),
    ("蓝牙", ("设备",), "dynamic Bluetooth device rows"),
    ("Bluetooth", ("My Devices", "Other Devices"), "dynamic Bluetooth device rows"),
    ("Bluetooth", ("Devices",), "dynamic Bluetooth device rows"),
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
        if classified is not None and classified.kind != "unknown":
            return classified.kind == "settings_detail"
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
            aliases=ROOT_LABEL_ALIASES,
            fuzzy=0.82,
            max_leading_noise_chars=1,
        )

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
        if text.strip().casefold() in {value.casefold() for value in EXACT_UNSAFE_OR_NON_NAV_TEXT}:
            return True
        if allow_sensitive_root_labels:
            for label in ROOT_ONLY_UNSAFE_OVERRIDES:
                if self.matches_label(text, label):
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
        texts = stable_visible_texts(self.texts(scene))
        joined = "\n".join(texts)
        for page_marker, row_markers, reason in BLOCKED_CHILD_NAVIGATION_MARKERS:
            page_key = compact_text(page_marker).casefold()
            row_keys = tuple(compact_text(marker).casefold() for marker in row_markers)
            if page_key in joined and (not row_keys or any(marker in joined for marker in row_keys)):
                return reason
        return None

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
        matches: list[UIElement] = []
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


DEFAULT_SETTINGS_POLICY = SettingsPolicy()
