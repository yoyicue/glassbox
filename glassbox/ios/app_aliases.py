"""Localized app-name aliases for launch targets (platform-owned data).

The facade accepts platform-neutral app identifiers ("settings", a bundle id);
which on-screen label that maps to — and in which device language — is iOS
platform knowledge, so the table lives here rather than in ``glassbox/ai.py``
(snapshot item 5: no localized platform data hardcoded in the facade). The
default device locale is zh-Hans (see AGENTS.md), hence the zh primary labels;
English aliases keep en-locale rigs working.
"""

from __future__ import annotations

# app identifier -> (primary on-screen label, fallback aliases)
_APP_ALIASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "com.apple.Preferences": ("设置", ("Settings",)),
    "settings": ("设置", ("Settings",)),
    "Settings": ("设置", ("Settings",)),
    "设置": ("设置", ("Settings",)),
}


def app_launch_label(app: str) -> tuple[str, tuple[str, ...]]:
    """Resolve an app identifier to (primary label, default aliases).

    Unknown identifiers pass through unchanged with no aliases.
    """
    return _APP_ALIASES.get(app, (app, ()))
