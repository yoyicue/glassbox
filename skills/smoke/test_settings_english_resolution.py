"""English Settings resolution through the live policy path.

Proves the crawl's existing resolver (`canonical_expected_root_label`, used by
coverage/dedup) maps English UI text to the canonical section, and that the
China-region variants WLAN / Mobile Service resolve ONLY under an active
``region=CN`` locale (locale-bound, not globally accepted).
"""

from __future__ import annotations

import pytest

from glassbox.config import get_config
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY as P
from skills.regression.ios_settings.sections import (
    RootSection,
    root_section_for_canonical_label,
    section_vocab_for,
)

# Standard English labels resolve in any locale (base alias map).
_EN_BASE = {
    "Wi-Fi": RootSection.WIFI,
    "Bluetooth": RootSection.BLUETOOTH,
    "Cellular": RootSection.CELLULAR,
    "General": RootSection.GENERAL,
    "Accessibility": RootSection.ACCESSIBILITY,
    "Battery": RootSection.BATTERY,
    "Face ID & Passcode": RootSection.FACE_ID_PASSCODE,
}
# Greater-China English (en-CN / en-HK): resolve only under those packs.
_GREATER_CHINA_EN = {"WLAN": RootSection.WIFI, "Mobile Service": RootSection.CELLULAR}


@pytest.fixture
def _locale(monkeypatch):
    def _set(language: str | None, region: str | None):
        for key, value in (("GLASSBOX_LANGUAGE", language), ("GLASSBOX_REGION", region)):
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        get_config.cache_clear()
    yield _set
    monkeypatch.delenv("GLASSBOX_LANGUAGE", raising=False)
    monkeypatch.delenv("GLASSBOX_REGION", raising=False)
    get_config.cache_clear()


@pytest.mark.smoke
@pytest.mark.parametrize(("text", "section"), list(_EN_BASE.items()))
def test_policy_resolves_standard_english(text, section):
    canon = P.canonical_expected_root_label(text)
    assert canon is not None and root_section_for_canonical_label(canon) is section


@pytest.mark.smoke
@pytest.mark.parametrize(("text", "section"), list(_GREATER_CHINA_EN.items()))
def test_greater_china_english_is_pack_bound(text, section, _locale):
    # Accepted under the greater-China English packs (en-CN, en-HK).
    for region in ("CN", "HK"):
        _locale("en", region)
        canon = P.canonical_expected_root_label(text)
        assert canon is not None and root_section_for_canonical_label(canon) is section, region
    # Rejected by zh default, en-US, AND zh-Hans-CN (language+region bound).
    for language, region in ((None, None), ("en", "US"), ("zh-Hans", "CN")):
        _locale(language, region)
        assert P.canonical_expected_root_label(text) is None


@pytest.mark.smoke
@pytest.mark.parametrize("region", ["CN", "HK"])
@pytest.mark.parametrize("text,section", [*_EN_BASE.items(), *_GREATER_CHINA_EN.items()])
def test_greater_china_en_vocab_resolves_to_section(text, section, region):
    assert section_vocab_for("en", region).resolve(text) is section


# —— settings_locale_fuzzy_resolution flag (Fix 1+2): OCR-garble crediting ——
@pytest.mark.smoke
@pytest.mark.parametrize("garble,section", [
    ("Screem Time", RootSection.SCREEN_TIME),    # the exact en-HK regression rows
    ("Screen/Time", RootSection.SCREEN_TIME),
    ("Accessibilityl", RootSection.ACCESSIBILITY),
    ("Bluetootn", RootSection.BLUETOOTH),
    ("Genera1", RootSection.GENERAL),
])
def test_en_ocr_garble_credits_required_page_when_flag_on(garble, section, _locale, monkeypatch):
    monkeypatch.setenv("GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION", "1")
    _locale("en", "HK")  # _locale cache_clears after env is set
    canon = P.canonical_expected_root_label(garble)
    assert canon is not None and root_section_for_canonical_label(canon) is section


@pytest.mark.smoke
@pytest.mark.parametrize("garble", ["Screem Time", "Accessibilityl", "Bluetootn", "Genera1"])
def test_en_ocr_garble_not_credited_when_flag_off(garble, _locale, monkeypatch):
    """Flag explicitly off restores exact-only resolution — the garble does not
    resolve (the default is now ON, so this opts out)."""
    monkeypatch.setenv("GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION", "0")
    _locale("en", "HK")
    assert P.canonical_expected_root_label(garble) is None


@pytest.mark.smoke
@pytest.mark.parametrize("text", ["Sound", "Notification", "Genera", "SE"])
def test_en_fuzzy_does_not_overmatch_bare_singular(text, _locale, monkeypatch):
    """A bare singular / short token must NOT be credited as a root by the fuzzy
    tier, and — since the safety gate `is_safe_known_navigation_label` rides on
    this resolver — the flag must not make that gate any more permissive than the
    flag-off baseline (the prefix-truncation + short-key guards)."""
    monkeypatch.setenv("GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION", "0")
    _locale("en", "HK")  # flag off baseline
    safe_off = P.is_safe_known_navigation_label(text)
    assert P.canonical_expected_root_label(text) is None
    monkeypatch.setenv("GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION", "1")
    _locale("en", "HK")  # flag on
    assert P.canonical_expected_root_label(text) is None  # not over-credited
    assert P.is_safe_known_navigation_label(text) == safe_off  # no new permissiveness


@pytest.mark.smoke
def test_en_exact_labels_still_resolve_with_flag_on(_locale, monkeypatch):
    monkeypatch.setenv("GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION", "1")
    _locale("en", "HK")
    for text, section in _EN_BASE.items():
        canon = P.canonical_expected_root_label(text)
        assert canon is not None and root_section_for_canonical_label(canon) is section, text


@pytest.mark.smoke
def test_zh_resolver_unchanged_when_flag_on(_locale, monkeypatch):
    """The en fuzzy tier is gated to non-zh locales (avoids the zh-vocab legacy
    recursion); a zh run is unaffected and an EN garble does not resolve under zh."""
    monkeypatch.setenv("GLASSBOX_SETTINGS_LOCALE_FUZZY_RESOLUTION", "1")
    _locale("zh-Hans", None)
    assert P.canonical_expected_root_label("待机見示") == "待机显示"
    assert P.canonical_expected_root_label("Screem Time") is None
