"""Language-neutral Settings root-section identity + locale vocab packs.

Part of the English-first / Chinese-switchable architecture
(docs/design/locale_seam_english_first.md). The **identity schema** (the
`RootSection` enum + the expected/coverage/safety ID-sets) is owned HERE, by the
Settings domain — locale packs only map OCR text ↔ these ids and ids → display.

This module is additive: it does not yet rewire the existing zh-string call
sites (that mechanical migration is sequenced in the design). It provides the
typed identity + the `SectionVocab` so new code (and tests) can key on ids.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from glassbox.cognition.text_match import Normalizer, fuzzy_ratio


class RootSection(StrEnum):
    # Explicit values REQUIRED: `.value` is the stable wire token (report ids,
    # VLM id_token) and must equal the name — no auto() / implicit values.
    WIFI = "WIFI"
    BLUETOOTH = "BLUETOOTH"
    CELLULAR = "CELLULAR"
    NOTIFICATIONS = "NOTIFICATIONS"
    SOUNDS_HAPTICS = "SOUNDS_HAPTICS"
    FOCUS = "FOCUS"
    SCREEN_TIME = "SCREEN_TIME"
    GENERAL = "GENERAL"
    ACCESSIBILITY = "ACCESSIBILITY"
    ACTION_BUTTON = "ACTION_BUTTON"
    STANDBY = "STANDBY"
    FACE_ID_PASSCODE = "FACE_ID_PASSCODE"
    SIRI = "SIRI"
    EMERGENCY_SOS = "EMERGENCY_SOS"
    PRIVACY_SECURITY = "PRIVACY_SECURITY"
    BATTERY = "BATTERY"
    WALLET = "WALLET"


# iOS visual order (same order as EXPECTED_ROOT_NAV_TEXT_ZH today).
EXPECTED_ROOT_SECTIONS: tuple[RootSection, ...] = (
    RootSection.WIFI, RootSection.BLUETOOTH, RootSection.CELLULAR,
    RootSection.NOTIFICATIONS, RootSection.SOUNDS_HAPTICS, RootSection.FOCUS,
    RootSection.SCREEN_TIME, RootSection.GENERAL, RootSection.ACCESSIBILITY,
    RootSection.SIRI, RootSection.ACTION_BUTTON, RootSection.STANDBY,
    RootSection.FACE_ID_PASSCODE, RootSection.EMERGENCY_SOS,
    RootSection.PRIVACY_SECURITY, RootSection.BATTERY, RootSection.WALLET,
)
COVERAGE_ONLY: frozenset[RootSection] = frozenset({RootSection.WALLET})
ROOT_ONLY_UNSAFE_OVERRIDE: frozenset[RootSection] = frozenset({RootSection.FACE_ID_PASSCODE})

# Chinese canonical label (today's `EXPECTED_ROOT_NAV_TEXT_ZH`) → RootSection.
# The zh vocab reuses the existing battle-tested zh resolver and maps through
# this — so the rich OCR-garble alias coverage is inherited, not duplicated.
_ZH_CANON_TO_SECTION: dict[str, RootSection] = {
    "无线局域网": RootSection.WIFI,
    "蓝牙": RootSection.BLUETOOTH,
    "蜂窝网络": RootSection.CELLULAR,
    "通知": RootSection.NOTIFICATIONS,
    "声音与触感": RootSection.SOUNDS_HAPTICS,
    "专注模式": RootSection.FOCUS,
    "屏幕使用时间": RootSection.SCREEN_TIME,
    "通用": RootSection.GENERAL,
    "辅助功能": RootSection.ACCESSIBILITY,
    "Siri": RootSection.SIRI,
    "操作按钮": RootSection.ACTION_BUTTON,
    "待机显示": RootSection.STANDBY,
    "Face ID与密码": RootSection.FACE_ID_PASSCODE,
    "紧急 SOS": RootSection.EMERGENCY_SOS,
    "隐私与安全性": RootSection.PRIVACY_SECURITY,
    "电池": RootSection.BATTERY,
    "钱包与 Apple Pay": RootSection.WALLET,
}
_SECTION_TO_ZH_CANON: dict[RootSection, str] = {v: k for k, v in _ZH_CANON_TO_SECTION.items()}


def root_section_for_canonical_label(label: str | None) -> RootSection | None:
    """Return the stable section identity for today's Chinese canonical label.

    This is the compatibility exit for code that still uses the live crawl's
    Chinese canonical labels as its internal pivot. Report/verifier code should
    call this rather than reaching into this module's private mapping directly.
    """
    text = (label or "").strip()
    if not text:
        return None
    return _ZH_CANON_TO_SECTION.get(text)


def root_section_ids_for_canonical_labels(labels: Iterable[str]) -> list[str]:
    """Project Chinese canonical labels to stable RootSection wire tokens."""
    out: list[str] = []
    for label in labels:
        section = root_section_for_canonical_label(label)
        if section is not None:
            out.append(section.value)
    return out

# Pinyin search queries (today's root_search_query), keyed by section.
_ZH_SEARCH: dict[RootSection, str] = {
    RootSection.WIFI: "wuxianjuyuwang", RootSection.BLUETOOTH: "lanya",
    RootSection.CELLULAR: "fengwowangluo", RootSection.NOTIFICATIONS: "tongzhi",
    RootSection.SOUNDS_HAPTICS: "shengyin", RootSection.FOCUS: "zhuanzhumoshi",
    RootSection.SCREEN_TIME: "pingmushiyongshijian", RootSection.GENERAL: "tongyong",
    RootSection.ACCESSIBILITY: "fuzhugongneng", RootSection.SIRI: "siri",
    RootSection.ACTION_BUTTON: "caozuoanniu", RootSection.STANDBY: "daijixianshi",
    RootSection.FACE_ID_PASSCODE: "mianrongidmima", RootSection.EMERGENCY_SOS: "jinjisos",
    RootSection.PRIVACY_SECURITY: "yinsiyuanquan", RootSection.BATTERY: "dianchi",
    RootSection.WALLET: "qianbao",
}

# English display labels (US base).
_EN_DISPLAY: dict[RootSection, str] = {
    RootSection.WIFI: "Wi-Fi", RootSection.BLUETOOTH: "Bluetooth",
    RootSection.CELLULAR: "Cellular", RootSection.NOTIFICATIONS: "Notifications",
    RootSection.SOUNDS_HAPTICS: "Sounds & Haptics", RootSection.FOCUS: "Focus",
    RootSection.SCREEN_TIME: "Screen Time", RootSection.GENERAL: "General",
    RootSection.ACCESSIBILITY: "Accessibility", RootSection.SIRI: "Siri",
    RootSection.ACTION_BUTTON: "Action Button", RootSection.STANDBY: "StandBy",
    RootSection.FACE_ID_PASSCODE: "Face ID & Passcode",
    RootSection.EMERGENCY_SOS: "Emergency SOS",
    RootSection.PRIVACY_SECURITY: "Privacy & Security", RootSection.BATTERY: "Battery",
    RootSection.WALLET: "Wallet & Apple Pay",
}
_EN_ALIASES: dict[RootSection, tuple[str, ...]] = {
    RootSection.WIFI: ("WiFi",),
    RootSection.SOUNDS_HAPTICS: ("Sounds",),
}
# Greater-China English overlay (live-observed in en-CN and en-HK): WLAN / Mobile
# Service. Applied for these regions only; en-US shows Wi-Fi / Cellular.
_GREATER_CHINA_EN_REGIONS = frozenset({"CN", "HK"})
_GREATER_CHINA_EN_ALIASES: dict[RootSection, tuple[str, ...]] = {
    RootSection.WIFI: ("WLAN",),
    RootSection.CELLULAR: ("Mobile Service",),
}


@dataclass(frozen=True)
class VlmCandidate:
    """What the VLM sees; it emits `id_token` (== id.value), never a label."""

    id: RootSection
    id_token: str
    label: str
    aliases: tuple[str, ...]


class SectionVocab:
    """Locale-bound section vocabulary: text ↔ RootSection ↔ display.

    `resolve()` returns a typed `RootSection` (or None) — never a display
    string. Root-classifier terms derive from here (labels+aliases), so there
    is no second copy of root vocabulary in the scene-classifier surfaces.
    """

    def __init__(
        self,
        *,
        code: str,
        display: dict[RootSection, str],
        aliases: dict[RootSection, tuple[str, ...]],
        search: dict[RootSection, str],
        fuzzy_threshold: float = 0.82,
        confusion_classes: Iterable[str] = (),
        legacy_zh: bool = False,
    ) -> None:
        self.code = code
        self._display = display
        self._aliases = aliases
        self._search = search
        self._fuzzy = fuzzy_threshold
        self._legacy_zh = legacy_zh
        self._norm = Normalizer(confusion_classes)
        # normalized term -> section (display + aliases)
        self._index: dict[str, RootSection] = {}
        for section in EXPECTED_ROOT_SECTIONS:
            for term in (display[section], *aliases.get(section, ())):
                self._index[self._norm(term)] = section

    def label(self, section: RootSection) -> str:
        return self._display[section]

    def search_query(self, section: RootSection) -> str | None:
        return self._search.get(section)

    def all_terms(self, section: RootSection) -> tuple[str, ...]:
        return (self._display[section], *self._aliases.get(section, ()))

    def root_classifier_terms(self, sections: Iterable[RootSection]) -> tuple[str, ...]:
        terms: list[str] = []
        for section in sections:
            terms.extend(self.all_terms(section))
        return tuple(terms)

    def resolve(self, ocr_text: str | None) -> RootSection | None:
        text = (ocr_text or "").strip()
        if not text:
            return None
        key = self._norm(text)
        hit = self._index.get(key)
        if hit is not None:
            return hit
        best: RootSection | None = None
        best_ratio = 0.0
        for term_key, section in self._index.items():
            ratio = fuzzy_ratio(key, term_key)
            if ratio > best_ratio:
                best_ratio, best = ratio, section
        if best is not None and best_ratio >= self._fuzzy:
            return best
        if self._legacy_zh:
            # Inherit the existing zh resolver's full OCR-garble alias coverage.
            from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

            canon = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(text)
            if canon is not None:
                return root_section_for_canonical_label(canon)
        return None

    def vlm_candidates(self) -> tuple[VlmCandidate, ...]:
        return tuple(
            VlmCandidate(
                id=section,
                id_token=section.value,
                label=self._display[section],
                aliases=self._aliases.get(section, ()),
            )
            for section in EXPECTED_ROOT_SECTIONS
        )


def _zh_vocab(code: str) -> SectionVocab:
    from glassbox.cognition.text_match import DEFAULT_CONFUSION_CLASSES

    return SectionVocab(
        code=code,
        display=dict(_SECTION_TO_ZH_CANON),
        aliases={},
        search=dict(_ZH_SEARCH),
        confusion_classes=DEFAULT_CONFUSION_CLASSES,
        legacy_zh=True,
    )


def _en_vocab(code: str, *, region: str | None) -> SectionVocab:
    aliases = {k: tuple(v) for k, v in _EN_ALIASES.items()}
    display = dict(_EN_DISPLAY)
    if region in _GREATER_CHINA_EN_REGIONS:
        for section, regional in _GREATER_CHINA_EN_ALIASES.items():
            # Greater-China English devices SHOW the regional term (WLAN / Mobile
            # Service), so it is the faithful display label here; keep the US term
            # (Wi-Fi / Cellular) resolvable as an alias for robustness.
            us_term = display[section]
            display[section] = regional[0]
            aliases[section] = (*aliases.get(section, ()), us_term, *regional[1:])
    return SectionVocab(
        code=code,
        display=display,
        aliases=aliases,
        search={s: display[s] for s in EXPECTED_ROOT_SECTIONS},
    )


def section_vocab_for(language: str, region: str | None = None) -> SectionVocab:
    """Build the `SectionVocab` for a (language, region)."""
    code = f"{language}-{region}" if region else language
    if language.startswith("zh"):
        return _zh_vocab(code)
    return _en_vocab(code, region=region)


__all__ = [
    "COVERAGE_ONLY",
    "EXPECTED_ROOT_SECTIONS",
    "ROOT_ONLY_UNSAFE_OVERRIDE",
    "RootSection",
    "SectionVocab",
    "VlmCandidate",
    "root_section_for_canonical_label",
    "root_section_ids_for_canonical_labels",
    "section_vocab_for",
]
