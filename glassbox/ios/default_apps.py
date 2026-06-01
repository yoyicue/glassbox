"""Launch profiles for built-in iOS/iPadOS apps."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from glassbox.cognition.base import Scene
from glassbox.cognition.text_match import confusion_compact


@dataclass(frozen=True)
class DefaultAppLaunchProfile:
    key: str
    labels: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ("ios", "ipados")
    preferred_open: str = "icon_or_spotlight"
    spotlight_query: str | None = None
    require_visible_spotlight_result: bool = False
    require_post_open_verification: bool = False
    verify_markers: tuple[str, ...] = ()
    min_verify_markers: int = 1
    accepts_scene_kind_prefixes: tuple[str, ...] = ()
    accepts_exact_label: bool = True
    climb_unknown_subpages: bool = False

    @property
    def all_labels(self) -> tuple[str, ...]:
        return (*self.labels, *self.aliases)


@dataclass(frozen=True)
class DefaultAppLabelMatch:
    profile: DefaultAppLaunchProfile
    label: str
    canonical_label: str
    score: float


DEFAULT_APP_LAUNCH_PROFILES: tuple[DefaultAppLaunchProfile, ...] = (
    DefaultAppLaunchProfile(
        key="settings",
        labels=("Settings", "设置"),
        aliases=("com.apple.preferences",),
        require_post_open_verification=True,
        accepts_scene_kind_prefixes=("settings_",),
        accepts_exact_label=False,
        climb_unknown_subpages=True,
    ),
    DefaultAppLaunchProfile(
        key="app_store",
        labels=("App Store",),
        aliases=("AppStore",),
        preferred_open="spotlight",
        spotlight_query="app store",
        require_visible_spotlight_result=True,
        require_post_open_verification=True,
        verify_markers=("Today", "Games", "Apps", "Arcade", "Search", "搜索", "游戏", "应用", "更新"),
        min_verify_markers=2,
    ),
    DefaultAppLaunchProfile(
        key="notes",
        labels=("Notes", "备忘录"),
        preferred_open="icon_or_spotlight",
        spotlight_query="notes",
        require_post_open_verification=True,
        verify_markers=("Notes", "备忘录", "Folders", "文件夹", "iCloud", "Recently Deleted", "最近删除"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="weather",
        labels=("Weather", "天气"),
        preferred_open="icon_or_spotlight",
        spotlight_query="weather",
        require_post_open_verification=True,
        verify_markers=("Weather", "天气", "10-DAY FORECAST", "Search for a city", "°"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="safari",
        labels=("Safari", "Safari 浏览器"),
        spotlight_query="safari",
        require_post_open_verification=True,
        verify_markers=("Safari", "Search or enter website name", "Tab Groups", "Private", "Bookmarks"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="mail",
        labels=("Mail", "邮件"),
        spotlight_query="mail",
        require_post_open_verification=True,
        verify_markers=("Mailboxes", "Inbox", "邮件", "收件箱", "Compose"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="messages",
        labels=("Messages", "信息"),
        spotlight_query="messages",
        require_post_open_verification=True,
        verify_markers=("Messages", "信息", "New Message", "iMessage", "Edit"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="phone",
        labels=("Phone", "电话"),
        platforms=("ios",),
        spotlight_query="phone",
        require_post_open_verification=True,
        verify_markers=("Favorites", "Recents", "Contacts", "Keypad", "Voicemail", "个人收藏", "最近通话", "通讯录", "拨号键盘"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="facetime",
        labels=("FaceTime", "FaceTime 通话"),
        spotlight_query="facetime",
        require_post_open_verification=True,
        verify_markers=("FaceTime", "New FaceTime", "Create Link", "通话"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="calendar",
        labels=("Calendar", "日历"),
        spotlight_query="calendar",
        require_post_open_verification=True,
        verify_markers=("Calendar", "日历", "Today", "Calendars", "Inbox", "今天"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="camera",
        labels=("Camera", "相机"),
        spotlight_query="camera",
        require_post_open_verification=True,
        verify_markers=("Photo", "Video", "Portrait", "Pano", "照片", "视频", "人像"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="photos",
        labels=("Photos", "照片"),
        spotlight_query="photos",
        require_post_open_verification=True,
        verify_markers=("Photos", "照片", "Library", "Albums", "For You", "图库", "相簿"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="reminders",
        labels=("Reminders", "提醒事项"),
        spotlight_query="reminders",
        require_post_open_verification=True,
        verify_markers=("Reminders", "提醒事项", "Today", "Scheduled", "Flagged", "今天", "已计划"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="maps",
        labels=("Maps", "地图"),
        spotlight_query="maps",
        require_post_open_verification=True,
        verify_markers=("Maps", "地图", "Search Maps", "搜索地图", "Directions", "路线"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="files",
        labels=("Files", "文件"),
        spotlight_query="files",
        require_post_open_verification=True,
        verify_markers=("Files", "文件", "Browse", "Recents", "iCloud Drive", "浏览", "最近项目"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="find_my",
        labels=("Find My", "查找"),
        spotlight_query="find my",
        require_post_open_verification=True,
        verify_markers=("Find My", "查找", "People", "Devices", "Items", "Me", "联系人", "设备", "物品"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="music",
        labels=("Music", "音乐"),
        spotlight_query="music",
        require_post_open_verification=True,
        verify_markers=("Music", "音乐", "Library", "Listen Now", "Browse", "Radio", "资料库"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="tv",
        labels=("Apple TV", "TV", "视频"),
        aliases=("Videos", "atv", "stv"),
        spotlight_query="tv",
        require_post_open_verification=True,
        verify_markers=("Apple TV", "TV", "Watch Now", "Library", "Store", "体育", "资料库"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="podcasts",
        labels=("Podcasts", "播客"),
        spotlight_query="podcasts",
        require_post_open_verification=True,
        verify_markers=("Podcasts", "播客", "Listen Now", "Browse", "Library", "资料库"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="books",
        labels=("Books", "图书"),
        spotlight_query="books",
        require_post_open_verification=True,
        verify_markers=("Books", "图书", "Reading Now", "Library", "Book Store", "资料库"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="clock",
        labels=("Clock", "时钟"),
        spotlight_query="clock",
        require_post_open_verification=True,
        verify_markers=("Clock", "时钟", "World Clock", "Alarm", "Stopwatch", "Timer", "世界时钟", "闹钟", "秒表", "计时器"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="contacts",
        labels=("Contacts", "通讯录"),
        spotlight_query="contacts",
        require_post_open_verification=True,
        verify_markers=("Contacts", "通讯录", "Lists", "All Contacts", "所有联系人"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="shortcuts",
        labels=("Shortcuts", "快捷指令"),
        spotlight_query="shortcuts",
        require_post_open_verification=True,
        verify_markers=("Shortcuts", "快捷指令", "Automation", "Gallery", "自动化", "快捷指令中心"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="home",
        labels=("Home", "家庭"),
        spotlight_query="home",
        require_post_open_verification=True,
        verify_markers=("Home", "家庭", "Rooms", "Automation", "Discover", "房间", "自动化"),
        min_verify_markers=2,
        accepts_exact_label=False,
    ),
    DefaultAppLaunchProfile(
        key="health",
        labels=("Health", "健康"),
        platforms=("ios",),
        spotlight_query="health",
        require_post_open_verification=True,
        verify_markers=("Health", "健康", "Summary", "Sharing", "Browse", "摘要", "共享", "浏览"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="wallet",
        labels=("Wallet", "钱包"),
        platforms=("ios",),
        spotlight_query="wallet",
        require_post_open_verification=True,
        verify_markers=("Wallet", "钱包", "Apple Pay", "Cards", "Passes"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="passwords",
        labels=("Passwords", "密码"),
        spotlight_query="passwords",
        require_post_open_verification=True,
        verify_markers=("Passwords", "密码", "All", "Security", "Passkeys", "全部", "安全性"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="freeform",
        labels=("Freeform", "无边记"),
        spotlight_query="freeform",
        require_post_open_verification=True,
        verify_markers=("Freeform", "无边记", "Boards", "Recents", "Shared", "看板", "最近项目"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="stocks",
        labels=("Stocks", "股市"),
        spotlight_query="stocks",
        require_post_open_verification=True,
        verify_markers=("Stocks", "股市", "Watchlist", "Business News", "关注列表"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="tips",
        labels=("Tips", "提示"),
        spotlight_query="tips",
        require_post_open_verification=True,
        verify_markers=("Tips", "提示", "Collections", "Featured", "精选"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="translate",
        labels=("Translate", "翻译"),
        platforms=("ios",),
        spotlight_query="translate",
        require_post_open_verification=True,
        verify_markers=("Translate", "翻译", "Conversation", "Camera", "Favorites", "对话", "相机"),
        min_verify_markers=1,
    ),
    DefaultAppLaunchProfile(
        key="voice_memos",
        labels=("Voice Memos", "语音备忘录"),
        spotlight_query="voice memos",
        require_post_open_verification=True,
        verify_markers=("Voice Memos", "语音备忘录", "All Recordings", "所有录音"),
        min_verify_markers=1,
    ),
)


def default_launch_profile_for_labels(
    labels: Iterable[str],
    *,
    platform: str | None = None,
) -> DefaultAppLaunchProfile | None:
    requested = {_normalize(label) for label in labels if str(label).strip()}
    if not requested:
        return None
    for profile in DEFAULT_APP_LAUNCH_PROFILES:
        if platform is not None and platform not in profile.platforms:
            continue
        known = {_normalize(label) for label in profile.all_labels}
        if requested & known:
            return profile
    return None


def canonical_default_app_label(
    text: str | None,
    *,
    platform: str | None = None,
    min_score: float = 0.78,
    margin: float = 0.10,
) -> DefaultAppLabelMatch | None:
    """Map a noisy Home icon label to one unambiguous built-in app label."""
    text_key = _label_match_key(text)
    if not text_key:
        return None
    by_profile: dict[str, DefaultAppLabelMatch] = {}
    for profile in DEFAULT_APP_LAUNCH_PROFILES:
        if platform is not None and platform not in profile.platforms:
            continue
        for label in profile.all_labels:
            label_key = _label_match_key(label)
            if not label_key:
                continue
            score = _label_match_score(text_key, label_key)
            if score >= min_score:
                match = DefaultAppLabelMatch(
                    profile=profile,
                    label=label,
                    canonical_label=profile.labels[0],
                    score=score,
                )
                current = by_profile.get(profile.key)
                if current is None or match.score > current.score:
                    by_profile[profile.key] = match
    scored = list(by_profile.values())
    if not scored:
        return None
    scored.sort(key=lambda item: item.score, reverse=True)
    best = scored[0]
    second = scored[1].score if len(scored) > 1 else 0.0
    if best.score - second < margin:
        return None
    return best


def verify_default_app_opened(
    profile: DefaultAppLaunchProfile,
    scene: Scene,
    *,
    labels: Iterable[str] = (),
    classified_kind: str = "",
) -> bool:
    kind = str(classified_kind or "")
    if profile.accepts_scene_kind_prefixes and any(
        kind.startswith(prefix) for prefix in profile.accepts_scene_kind_prefixes
    ):
        return True
    texts = tuple((getattr(el, "text", "") or "").strip() for el in scene.elements)
    if profile.accepts_exact_label and _scene_has_any_label(texts, (*labels, *profile.all_labels)):
        return True
    marker_hits = sum(1 for marker in profile.verify_markers if _scene_has_marker(texts, marker))
    return marker_hits >= profile.min_verify_markers


def _scene_has_any_label(texts: Iterable[str], labels: Iterable[str]) -> bool:
    text_keys = {_normalize(text) for text in texts if text.strip()}
    return any(_normalize(label) in text_keys for label in labels if str(label).strip())


def _scene_has_marker(texts: Iterable[str], marker: str) -> bool:
    key = _normalize(marker)
    if not key:
        return False
    if len(key) <= 2:
        return any(key == _normalize(text) for text in texts)
    if _ascii_words(marker):
        return any(_contains_ascii_phrase(text, marker) for text in texts)
    return any(key in _normalize(text) for text in texts)


def _ascii_words(value: str) -> bool:
    return bool(value.strip()) and all(ch.isascii() and (ch.isalnum() or ch.isspace() or ch in {"-", "&"}) for ch in value)


def _contains_ascii_phrase(text: str, marker: str) -> bool:
    words = re.findall(r"[A-Za-z0-9]+", marker.casefold())
    if not words:
        return False
    haystack = re.findall(r"[A-Za-z0-9]+", str(text or "").casefold())
    if len(words) == 1:
        return words[0] in haystack
    width = len(words)
    return any(tuple(haystack[index:index + width]) == tuple(words) for index in range(len(haystack) - width + 1))


def _normalize(value: str) -> str:
    return str(value or "").strip().casefold().replace(" ", "")


def _label_match_key(value: str | None) -> str:
    return confusion_compact(value).casefold().replace(" ", "")


def _label_match_score(text_key: str, label_key: str) -> float:
    if text_key == label_key:
        return 1.0
    if text_key.endswith(label_key):
        prefix = text_key[: len(text_key) - len(label_key)]
        if 0 < len(prefix) <= 4:
            return 1.0
    return difflib.SequenceMatcher(None, text_key, label_key).ratio()


__all__ = [
    "DEFAULT_APP_LAUNCH_PROFILES",
    "DefaultAppLabelMatch",
    "DefaultAppLaunchProfile",
    "canonical_default_app_label",
    "default_launch_profile_for_labels",
    "verify_default_app_opened",
]
