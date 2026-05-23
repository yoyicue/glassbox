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
from dataclasses import dataclass

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

_BUILTIN_LOCALES: tuple[Locale, ...] = (
    Locale("zh-Hans", None, _ZH_OCR_LANGUAGES, DEFAULT_CONFUSION_CLASSES),
    # China-region Chinese — region only matters for section aliases (Phase 2);
    # perception knobs are the same as base zh.
    Locale("zh-Hans", "CN", _ZH_OCR_LANGUAGES, DEFAULT_CONFUSION_CLASSES),
    Locale("en", "US", _EN_OCR_LANGUAGES, ()),
    # China-region English (WLAN / Mobile Service) — section-alias overlay is
    # Phase 2; perception knobs match base English.
    Locale("en", "CN", _EN_OCR_LANGUAGES, ()),
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

        Base = the bare-language key if registered, else the first-registered
        pack of that language (registration order puts the base first).
        """
        if code in self._by_code:
            return self._by_code[code]
        language = code.split("-", 1)[0]
        if language in self._by_code:
            return self._by_code[language]
        for locale in self._by_code.values():
            if locale.language == language:
                return locale
        raise KeyError(f"unknown locale {code!r}; registered={self.codes()}")


DEFAULT_LOCALE_REGISTRY = LocaleRegistry(_BUILTIN_LOCALES)


def select_locale_code(cfg: AgentConfig) -> str:
    """Compose the active pack key from config (default ``zh-Hans``)."""
    language = getattr(cfg, "language", None) or "zh-Hans"
    region = getattr(cfg, "region", None)
    return f"{language}-{region}" if region else language


def resolve_locale(cfg: AgentConfig, *, registry: LocaleRegistry | None = None) -> Locale:
    """Resolve the active `Locale` for this config."""
    return (registry or DEFAULT_LOCALE_REGISTRY).resolve(select_locale_code(cfg))


__all__ = [
    "DEFAULT_LOCALE_REGISTRY",
    "Locale",
    "LocaleRegistry",
    "resolve_locale",
    "select_locale_code",
]
