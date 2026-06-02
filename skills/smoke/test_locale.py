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
    resolve_ocr_locale,
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
def test_zh_ocr_engine_params_byte_identical_to_vision_defaults():
    """zh non-regression hinge: every OCR-engine knob the vision factory forwards
    for the default (zh) locale must equal the live VisionOCR.__init__ default, so
    the resolved call is byte-identical to today's languages-only call. Reading the
    defaults off the signature (not re-typed literals) makes a drift on EITHER side
    fail — the allow-list-over-hand-count discipline.
    """
    import inspect

    from glassbox.cognition.ocr_vision import VisionOCR

    sig = inspect.signature(VisionOCR.__init__).parameters
    loc = resolve_ocr_locale(AgentConfig(_env_file=None))  # zh-Hans default, flag off
    assert tuple(loc.ocr_languages) == tuple(sig["languages"].default)
    assert loc.uses_language_correction is sig["uses_language_correction"].default
    assert tuple(loc.custom_words) == tuple(sig["custom_words"].default)
    assert sig["minimum_text_height"].default is None


@pytest.mark.smoke
def test_en_ocr_correction_off_by_default():
    # English with the flag off keeps the engine defaults (today's behavior).
    cfg = AgentConfig(_env_file=None, language="en", region="HK")
    loc = resolve_ocr_locale(cfg)
    assert loc.uses_language_correction is False
    assert tuple(loc.custom_words) == ("+", "-")


@pytest.mark.smoke
def test_en_ocr_correction_on_with_flag():
    # Flag ON: English gains NL correction + the proper-noun whitelist.
    cfg = AgentConfig(_env_file=None, language="en", region="HK", en_ocr_correction=True)
    loc = resolve_ocr_locale(cfg)
    assert loc.uses_language_correction is True
    assert {"WLAN", "Siri", "iCloud"}.issubset(set(loc.custom_words))
    # Whitelist keeps the walkthrough +/- seeds.
    assert loc.custom_words[:2] == ("+", "-")


@pytest.mark.smoke
@pytest.mark.parametrize("region", ["US", "CN", "HK"])
def test_en_ocr_correction_covers_every_english_region(region):
    """The overlay keys on language=="en", so it must apply to ALL English packs
    — en-US, en-CN AND en-HK (the iPad mini 7 rig locale) — not just en-US."""
    off = resolve_ocr_locale(AgentConfig(_env_file=None, language="en", region=region))
    assert off.uses_language_correction is False  # default behavior unchanged
    on = resolve_ocr_locale(
        AgentConfig(_env_file=None, language="en", region=region, en_ocr_correction=True)
    )
    assert on.code == f"en-{region}"
    assert on.uses_language_correction is True
    assert "WLAN" in on.custom_words  # the en-HK / en-CN Wi-Fi label


@pytest.mark.smoke
@pytest.mark.parametrize("region", [None, "CN"])
def test_en_ocr_correction_flag_never_touches_zh(region):
    # The overlay is English-only: every zh pack stays byte-identical even with
    # the flag set.
    cfg = AgentConfig(_env_file=None, language="zh-Hans", region=region, en_ocr_correction=True)
    loc = resolve_ocr_locale(cfg)
    assert loc.language == "zh-Hans"
    assert loc.uses_language_correction is False
    assert tuple(loc.custom_words) == ("+", "-")


@pytest.mark.smoke
def test_vision_factory_forwards_locale_ocr_params(monkeypatch):
    """The vision OCR factory must forward the resolved per-locale knobs. Patches
    VisionOCR with a recorder so this runs offline (no pyobjc)."""
    import glassbox.backend_registry as br

    captured: dict = {}

    class _FakeVisionOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(br, "VisionOCR", _FakeVisionOCR)

    # zh default → engine-default knobs (byte-identical call).
    br._vision_ocr_factory(cfg=AgentConfig(_env_file=None))
    assert tuple(captured["languages"]) == ("zh-Hans", "en-US")
    assert captured["uses_language_correction"] is False
    assert tuple(captured["custom_words"]) == ("+", "-")
    assert "minimum_text_height" not in captured
    assert "confidence_threshold" not in captured
    assert "unsharp_mask" not in captured
    assert "unsharp_sigma" not in captured
    assert "unsharp_amount" not in captured

    # en + flag → correction on + whitelist forwarded.
    captured.clear()
    br._vision_ocr_factory(
        cfg=AgentConfig(_env_file=None, language="en", region="HK", en_ocr_correction=True)
    )
    assert tuple(captured["languages"]) == ("en-US",)
    assert captured["uses_language_correction"] is True
    assert "WLAN" in captured["custom_words"]

    # Explicit Vision knobs are opt-in and must forward even falsy 0.0/False.
    captured.clear()
    br._vision_ocr_factory(
        cfg=AgentConfig(
            _env_file=None,
            ocr_minimum_text_height=0.0,
            ocr_confidence_threshold=0.2,
            ocr_unsharp_mask=False,
            ocr_unsharp_sigma=0.8,
            ocr_unsharp_amount=1.2,
        )
    )
    assert captured["minimum_text_height"] == 0.0
    assert captured["confidence_threshold"] == 0.2
    assert captured["unsharp_mask"] is False
    assert captured["unsharp_sigma"] == 0.8
    assert captured["unsharp_amount"] == 1.2


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
