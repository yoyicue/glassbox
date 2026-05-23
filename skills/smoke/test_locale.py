from __future__ import annotations

import pytest

from glassbox.cognition.text_match import (
    DEFAULT_CONFUSION_CLASSES,
    Normalizer,
    confusion_compact,
)
from glassbox.config import AgentConfig
from glassbox.locale import (
    DEFAULT_LOCALE_REGISTRY,
    Locale,
    resolve_locale,
    select_locale_code,
)


@pytest.mark.smoke
def test_default_locale_is_zh_and_matches_current_globals():
    # Default config must resolve to zh-Hans with the exact pre-seam OCR
    # languages + confusion folds, so Chinese behavior is unchanged.
    cfg = AgentConfig(_env_file=None)
    assert select_locale_code(cfg) == "zh-Hans"
    loc = resolve_locale(cfg)
    assert loc.language == "zh-Hans"
    assert loc.region is None
    assert loc.ocr_languages == ("zh-Hans", "en-US")
    assert loc.confusion_classes == DEFAULT_CONFUSION_CLASSES


@pytest.mark.smoke
def test_english_locale_drops_chinese_and_confusion():
    cfg = AgentConfig(_env_file=None, language="en", region="US")
    assert select_locale_code(cfg) == "en-US"
    loc = resolve_locale(cfg)
    assert loc.ocr_languages == ("en-US",)
    assert loc.confusion_classes == ()


@pytest.mark.smoke
def test_region_overlay_and_language_fallback():
    # en-CN is a distinct pack key (China-region English).
    cfg = AgentConfig(_env_file=None, language="en", region="CN")
    assert resolve_locale(cfg).code == "en-CN"
    # Unknown region falls back to the base language pack.
    assert DEFAULT_LOCALE_REGISTRY.resolve("en-ZZ").code == "en-US"
    # Hyphenated language: region stripped from the END, so zh-Hans-ZZ -> zh-Hans
    # (NOT "zh"). Guards the rsplit fallback.
    assert DEFAULT_LOCALE_REGISTRY.resolve("zh-Hans-ZZ").code == "zh-Hans"
    # en-HK resolves to its own pack (greater-China English), not en-US.
    assert DEFAULT_LOCALE_REGISTRY.resolve("en-HK").code == "en-HK"
    assert {"zh-Hans", "zh-Hans-CN", "en-US", "en-CN", "en-HK"}.issubset(
        set(DEFAULT_LOCALE_REGISTRY.codes())
    )


@pytest.mark.smoke
def test_parameterized_normalizer_folds_per_locale():
    zh = Normalizer(DEFAULT_CONFUSION_CLASSES)
    # zh folds visual-confusion glyphs to the canonical representative.
    assert zh("待机見示") == "待机显示"
    assert zh("侍机显示") == "待机显示"
    assert zh("S0S") == "SOS"
    # The module-global keeps the same (zh) behavior — compatibility default.
    assert confusion_compact("待机見示") == zh("待机見示")
    # An empty-class (English) normalizer is compact-only: no folding.
    en = Normalizer(())
    assert en("S0S") == "S0S"
    assert en(" Wi-Fi ") == "Wi-Fi"


@pytest.mark.smoke
def test_locale_code_property():
    assert Locale("en", "CN", ("en-US",), ()).code == "en-CN"
    assert Locale("zh-Hans", None, ("zh-Hans",), ()).code == "zh-Hans"
