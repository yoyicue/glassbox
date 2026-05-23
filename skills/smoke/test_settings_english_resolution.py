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
    ZH_CANON_TO_SECTION,
    RootSection,
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
    assert canon is not None and ZH_CANON_TO_SECTION[canon] is section


@pytest.mark.smoke
@pytest.mark.parametrize(("text", "section"), list(_GREATER_CHINA_EN.items()))
def test_greater_china_english_is_pack_bound(text, section, _locale):
    # Accepted under the greater-China English packs (en-CN, en-HK).
    for region in ("CN", "HK"):
        _locale("en", region)
        canon = P.canonical_expected_root_label(text)
        assert canon is not None and ZH_CANON_TO_SECTION[canon] is section, region
    # Rejected by zh default, en-US, AND zh-Hans-CN (language+region bound).
    for language, region in ((None, None), ("en", "US"), ("zh-Hans", "CN")):
        _locale(language, region)
        assert P.canonical_expected_root_label(text) is None


@pytest.mark.smoke
@pytest.mark.parametrize("region", ["CN", "HK"])
@pytest.mark.parametrize("text,section", [*_EN_BASE.items(), *_GREATER_CHINA_EN.items()])
def test_greater_china_en_vocab_resolves_to_section(text, section, region):
    assert section_vocab_for("en", region).resolve(text) is section
