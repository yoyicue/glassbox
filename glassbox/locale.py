"""Locale seam — device language + region as a selectable pack.

English-first / Chinese-switchable architecture (see
docs/design/locale_seam_english_first.md). Phase 1 scope: a `Locale` carries
the active language/region context plus the **perception** knobs that vary by
language — the OCR recognition languages and the confusion-fold classes. The
per-app section vocabulary (`app()`) and OS-chrome vocabulary (`chrome`) land in
later phases; they are intentionally NOT part of this scaffold.

The default stays `zh-Hans` so current behavior is unchanged; the global flip to
English is the last migration step.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from glassbox.cognition.text_match import DEFAULT_CONFUSION_CLASSES
from glassbox.config import AgentConfig


@dataclass(frozen=True)
class Locale:
    """Active language/region context + perception knobs.

    `ocr_languages` and `confusion_classes` are the only language-varying knobs
    wired in Phase 1. Section identity vocabulary is owned by the app domain
    (e.g. the Settings policy) and only *resolved* through later locale fields.
    """

    language: str
    region: str | None
    ocr_languages: tuple[str, ...]
    confusion_classes: tuple[str, ...]
    # OCR-engine knobs that vary by language. Both default to the exact
    # VisionOCR.__init__ literals so a pack that omits them (every built-in pack
    # below) resolves byte-identically to today's single-kwarg engine call —
    # this is the zh non-regression hinge, locked by test_locale.py.
    uses_language_correction: bool = False
    custom_words: tuple[str, ...] = ("+", "-")

    @property
    def code(self) -> str:
        """Composite pack key, e.g. ``en-CN`` / ``zh-Hans``."""
        return f"{self.language}-{self.region}" if self.region else self.language


# ── Built-in packs (data, not code) ────────────────────────────────────────
# zh-Hans MUST equal today's globals exactly so Chinese behavior is unchanged:
#   VisionOCR default languages == ("zh-Hans", "en-US")
#   confusion folds == text_match.DEFAULT_CONFUSION_CLASSES
_ZH_OCR_LANGUAGES = ("zh-Hans", "en-US")
_EN_OCR_LANGUAGES = ("en-US",)

# iOS proper nouns that NL language correction must NOT "fix" into dictionary
# words. Seeded with the walkthrough "+"/"-", then the iOS brand tokens that
# recur in the en/HK Settings corpus (e.g. WLAN — the en-HK/en-CN label for
# Wi-Fi). Membership is pinned by
# skills/smoke/test_locale.py::test_en_ocr_correction_on_with_flag. Only consumed
# when uses_language_correction=True (the flag-gated English path,
# `resolve_ocr_locale`); zh keeps the ("+","-") default and is unaffected.
_EN_CUSTOM_WORDS = (
    "+",
    "-",
    "WLAN",
    "AirDrop",
    "iCloud",
    "FaceTime",
    "VoiceOver",
    "AirPlay",
    "AirPods",
    "AppleCare",
    "Siri",
    "iPadOS",
    "Bluetooth",
)

_BUILTIN_LOCALES: tuple[Locale, ...] = (
    Locale("zh-Hans", None, _ZH_OCR_LANGUAGES, DEFAULT_CONFUSION_CLASSES),
    # China-region Chinese — region only matters for section aliases (Phase 2);
    # perception knobs are the same as base zh.
    Locale("zh-Hans", "CN", _ZH_OCR_LANGUAGES, DEFAULT_CONFUSION_CLASSES),
    Locale("en", "US", _EN_OCR_LANGUAGES, ()),
    # Greater-China English (CN + HK) — live-observed to show WLAN / Mobile
    # Service. The section-alias overlay is in the Settings policy / vocab;
    # perception knobs match base English.
    Locale("en", "CN", _EN_OCR_LANGUAGES, ()),
    Locale("en", "HK", _EN_OCR_LANGUAGES, ()),
)


class LocaleRegistry:
    """Resolves a composite pack key to a `Locale`, with language fallback."""

    def __init__(self, locales: Iterable[Locale] | None = None) -> None:
        self._by_code: dict[str, Locale] = {}
        for locale in locales or ():
            self.register(locale)

    def register(self, locale: Locale) -> None:
        self._by_code[locale.code] = locale

    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_code))

    def resolve(self, code: str) -> Locale:
        """Exact pack key, else fall back to that language's base pack.

        Language tags may themselves contain hyphens (e.g. ``zh-Hans``), so the
        region is stripped from the END (``rsplit``), not the first hyphen — i.e.
        ``zh-Hans-ZZ`` falls back to ``zh-Hans``, not ``zh``. If the stripped
        base is not a registered code, fall back to the first-registered pack of
        that base language (registration order puts the base first).
        """
        if code in self._by_code:
            return self._by_code[code]
        base = code.rsplit("-", 1)[0]  # strip region overlay; keep multi-part lang
        if base in self._by_code:
            return self._by_code[base]
        for locale in self._by_code.values():
            if locale.language == base:
                return locale
        raise KeyError(f"unknown locale {code!r}; registered={self.codes()}")


DEFAULT_LOCALE_REGISTRY = LocaleRegistry(_BUILTIN_LOCALES)


def select_locale_code(cfg: AgentConfig) -> str:
    """Compose the active pack key from config (default ``zh-Hans``)."""
    language = getattr(cfg, "language", None) or "zh-Hans"
    region = getattr(cfg, "region", None)
    return f"{language}-{region}" if region else language


def resolve_locale(cfg: AgentConfig, *, registry: LocaleRegistry | None = None) -> Locale:
    """Resolve the active `Locale` for this config.

    Pure registry lookup — the OCR-engine knobs (`uses_language_correction`,
    `custom_words`) come back at their pack defaults. Use `resolve_ocr_locale`
    where those knobs feed the OCR engine, so the flag-gated English overlay is
    applied.
    """
    return (registry or DEFAULT_LOCALE_REGISTRY).resolve(select_locale_code(cfg))


def resolve_ocr_locale(cfg: AgentConfig, *, registry: LocaleRegistry | None = None) -> Locale:
    """Locale for OCR-engine config: `resolve_locale` + the flag-gated English
    language-correction overlay.

    The overlay is English-only and OFF by default (`cfg.en_ocr_correction`,
    env GLASSBOX_EN_OCR_CORRECTION), so:
      * zh (and any non-English locale) is returned untouched — its OCR-engine
        knobs stay at the byte-identical defaults regardless of the flag;
      * English with the flag OFF is also untouched (today's behavior);
      * English with the flag ON gains NL correction + the proper-noun
        `_EN_CUSTOM_WORDS` whitelist. This path is net-negative on offline OCR
        coverage and MUST clear an on-rig task_completion A/B before defaulting on.
    """
    loc = resolve_locale(cfg, registry=registry)
    if loc.language == "en" and cfg.en_ocr_correction:
        return replace(loc, uses_language_correction=True, custom_words=_EN_CUSTOM_WORDS)
    return loc


__all__ = [
    "DEFAULT_LOCALE_REGISTRY",
    "Locale",
    "LocaleRegistry",
    "resolve_locale",
    "resolve_ocr_locale",
    "select_locale_code",
]
