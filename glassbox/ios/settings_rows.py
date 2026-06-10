"""Closed-set recognition for built-in iOS/iPadOS Settings root rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.text_match import canonical_label
from glassbox.ios._scene_common import scene_size_with_default

SETTINGS_ROOT_INTENT_SOURCE = "settings_root_lexicon"

SETTINGS_ROOT_LABELS_ZH: tuple[str, ...] = (
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

SETTINGS_ROOT_LABEL_ALIASES: dict[str, str] = {
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

GREATER_CHINA_EN_ROOT_LABEL_ALIASES = {
    "WLAN": "无线局域网",
    "Mobile Service": "蜂窝网络",
}

SETTINGS_ROOT_LABEL_LOCALE_ALIASES: dict[str, dict[str, str]] = {
    "en-CN": GREATER_CHINA_EN_ROOT_LABEL_ALIASES,
    "en-HK": GREATER_CHINA_EN_ROOT_LABEL_ALIASES,
}


def canonical_settings_root_row_label(
    text: str | None,
    *,
    aliases: Mapping[str, str] | None = None,
    fuzzy: float = 0.82,
    fuzzy_aliases: bool = False,
    max_leading_noise_chars: int = 1,
) -> str | None:
    """Return the canonical Settings root row label for noisy OCR text."""
    return canonical_label(
        text,
        SETTINGS_ROOT_LABELS_ZH,
        aliases=aliases if aliases is not None else SETTINGS_ROOT_LABEL_ALIASES,
        fuzzy=fuzzy,
        max_leading_noise_chars=max_leading_noise_chars,
        fuzzy_aliases=fuzzy_aliases,
    )


def settings_root_label_aliases_for_config(config: Any) -> dict[str, str]:
    """Return root-row aliases for the active device locale."""
    aliases = dict(SETTINGS_ROOT_LABEL_ALIASES)
    try:
        from glassbox.locale import resolve_locale

        overlay = SETTINGS_ROOT_LABEL_LOCALE_ALIASES.get(resolve_locale(config).code)
    except Exception:
        overlay = None
    if overlay:
        aliases.update(overlay)
    return aliases


def settings_root_fuzzy_aliases_for_config(config: Any) -> bool:
    """Whether active-locale Settings aliases should use OCR-tolerant matching."""
    language = str(getattr(config, "language", "") or "")
    return bool(getattr(config, "settings_locale_fuzzy_resolution", False)) and not language.startswith(
        "zh"
    )


def annotate_settings_root_row_intents(
    scene: Scene,
    *,
    viewport_size: tuple[int, int] | None = None,
    aliases: Mapping[str, str] | None = None,
    fuzzy_aliases: bool = False,
) -> int:
    """Attach canonical Settings root-row names to visible row OCR elements."""
    if not _settings_root_rows_visible(scene):
        return 0
    w, h = scene_size_with_default(scene, viewport_size, default_size=(448, 973))
    updated = 0
    for element in scene.elements:
        if not _is_settings_root_row_region(element, scene=scene, viewport_size=(w, h)):
            continue
        if annotate_settings_root_row_intent(
            element,
            viewport_size=(w, h),
            aliases=aliases,
            fuzzy_aliases=fuzzy_aliases,
        ):
            updated += 1
    return updated


def annotate_settings_root_row_intent(
    element: UIElement,
    *,
    viewport_size: tuple[int, int] | None = None,
    aliases: Mapping[str, str] | None = None,
    fuzzy_aliases: bool = False,
) -> bool:
    label = visible_settings_root_row_label(
        element,
        viewport_size=viewport_size,
        aliases=aliases,
        fuzzy_aliases=fuzzy_aliases,
    )
    if label is None:
        return False
    if element.intent_label and element.intent_source != SETTINGS_ROOT_INTENT_SOURCE:
        return False
    evidence = list(element.type_evidence)
    evidence.extend([
        SETTINGS_ROOT_INTENT_SOURCE,
        f"settings_root_label:{label}",
    ])
    evidence = list(dict.fromkeys(evidence))
    changed = (
        element.intent_label != label
        or element.intent_source != SETTINGS_ROOT_INTENT_SOURCE
        or element.intent_confidence != 1.0
        or element.type_evidence != evidence
    )
    element.intent_label = label
    element.intent_source = SETTINGS_ROOT_INTENT_SOURCE
    element.intent_confidence = 1.0
    element.type_evidence = evidence
    return changed


def visible_settings_root_row_label(
    element: UIElement,
    *,
    viewport_size: tuple[int, int] | None = None,
    aliases: Mapping[str, str] | None = None,
    fuzzy_aliases: bool = False,
) -> str | None:
    intent = (element.intent_label or "").strip()
    if intent and element.intent_source == SETTINGS_ROOT_INTENT_SOURCE:
        label = canonical_settings_root_row_label(
            intent,
            aliases=aliases,
            fuzzy_aliases=fuzzy_aliases,
        )
        if label is not None:
            return label
    text = (element.text or "").strip()
    if not text:
        return None
    if len(text) > 32:
        return None
    cy = element.box.center[1]
    if viewport_size is not None:
        _w, h = viewport_size
        if cy < int(h * 0.10) or cy > int(h * 0.94):
            return None
    elif cy < 110 or cy > 910:
        return None
    return canonical_settings_root_row_label(
        text,
        aliases=aliases,
        fuzzy_aliases=fuzzy_aliases,
    )


def settings_root_row_label(element: UIElement) -> str:
    intent = (element.intent_label or "").strip()
    if intent and element.intent_source == SETTINGS_ROOT_INTENT_SOURCE:
        return intent
    return (element.text or "").strip()


def _settings_root_rows_visible(scene: Scene) -> bool:
    kind = str(scene.platform_scene_kind or scene.scene_type or scene.semantic_scene_type or "")
    if kind == "settings_root":
        return True
    if kind == "settings_detail":
        evidence = set(scene.classification_evidence or ())
        return "tap_root_row" in set(scene.safe_actions or ()) or "ipad_split_view" in evidence
    return False


def _is_settings_root_row_region(
    element: UIElement,
    *,
    scene: Scene,
    viewport_size: tuple[int, int],
) -> bool:
    _w, h = viewport_size
    _cx, cy = element.box.center
    if cy < int(h * 0.10) or cy > int(h * 0.94):
        return False
    kind = str(scene.platform_scene_kind or scene.scene_type or scene.semantic_scene_type or "")
    if kind == "settings_detail":
        evidence = set(scene.classification_evidence or ())
        if "ipad_split_view" in evidence or "tap_root_row" in set(scene.safe_actions or ()):
            try:
                from glassbox.ipados.scene import sidebar_right_x

                return element.box.center[0] <= sidebar_right_x(viewport_size[0]) + 24
            except Exception:
                return element.box.center[0] <= int(viewport_size[0] * 0.44) + 24
    return True


__all__ = [
    "GREATER_CHINA_EN_ROOT_LABEL_ALIASES",
    "SETTINGS_ROOT_INTENT_SOURCE",
    "SETTINGS_ROOT_LABELS_ZH",
    "SETTINGS_ROOT_LABEL_ALIASES",
    "SETTINGS_ROOT_LABEL_LOCALE_ALIASES",
    "annotate_settings_root_row_intent",
    "annotate_settings_root_row_intents",
    "canonical_settings_root_row_label",
    "settings_root_fuzzy_aliases_for_config",
    "settings_root_label_aliases_for_config",
    "settings_root_row_label",
    "visible_settings_root_row_label",
]
