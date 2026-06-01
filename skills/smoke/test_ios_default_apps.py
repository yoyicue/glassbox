from __future__ import annotations

from glassbox.cognition import Box, Scene, UIElement
from glassbox.ios.default_apps import (
    DEFAULT_APP_LAUNCH_PROFILES,
    canonical_default_app_label,
    default_launch_profile_for_labels,
    verify_default_app_opened,
)


def _el(text: str) -> UIElement:
    return UIElement(type="text", box=Box(x=0, y=0, w=100, h=20), text=text, confidence=0.9)


def _scene(*texts: str) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=[_el(text) for text in texts])


def test_default_app_profiles_cover_common_built_in_apps():
    keys = {profile.key for profile in DEFAULT_APP_LAUNCH_PROFILES}

    assert {
        "settings",
        "app_store",
        "safari",
        "mail",
        "messages",
        "phone",
        "facetime",
        "calendar",
        "camera",
        "photos",
        "notes",
        "reminders",
        "maps",
        "weather",
        "files",
        "find_my",
        "music",
        "tv",
        "podcasts",
        "books",
        "clock",
        "contacts",
        "shortcuts",
        "home",
        "health",
        "wallet",
        "passwords",
        "freeform",
        "stocks",
        "tips",
        "translate",
        "voice_memos",
    } <= keys


def test_default_app_profile_lookup_handles_aliases_and_platforms():
    assert default_launch_profile_for_labels(("AppStore",)).key == "app_store"
    assert default_launch_profile_for_labels(("备忘录",)).key == "notes"
    assert default_launch_profile_for_labels(("Phone",), platform="ios").key == "phone"
    assert default_launch_profile_for_labels(("Phone",), platform="ipados") is None
    assert default_launch_profile_for_labels(("Health",), platform="ipados") is None


def test_default_app_label_canonicalizes_noisy_home_icon_labels():
    assert canonical_default_app_label("日 Notes", platform="ipados").canonical_label == "Notes"
    assert canonical_default_app_label("Facefime", platform="ipados").canonical_label == "FaceTime"
    assert canonical_default_app_label("stv", platform="ipados").canonical_label == "Apple TV"
    assert canonical_default_app_label("AppStore", platform="ipados").canonical_label == "App Store"


def test_app_store_profile_requires_multiple_chrome_markers_not_notes_label():
    profile = default_launch_profile_for_labels(("App Store",))
    assert profile is not None

    assert not verify_default_app_opened(profile, _scene("Notes", "No Notes"), labels=("App Store",))
    assert verify_default_app_opened(profile, _scene("Today", "Games", "Apps", "Search"), labels=("App Store",))


def test_settings_profile_uses_scene_kind_not_bare_label():
    profile = default_launch_profile_for_labels(("Settings",))
    assert profile is not None

    assert not verify_default_app_opened(profile, _scene("Settings"), labels=("Settings",), classified_kind="unknown")
    assert verify_default_app_opened(
        profile,
        _scene("Settings"),
        labels=("Settings",),
        classified_kind="settings_root",
    )


def test_default_app_verifier_rejects_shared_short_substrings():
    find_my = default_launch_profile_for_labels(("Find My",))
    home = default_launch_profile_for_labels(("Home",))
    weather = default_launch_profile_for_labels(("Weather",))
    assert find_my is not None
    assert home is not None
    assert weather is not None

    assert not verify_default_app_opened(find_my, _scene("Some", "Time"), labels=("Find My",))
    assert not verify_default_app_opened(home, _scene("Home", "Library"), labels=("Home",))
    assert not verify_default_app_opened(weather, _scene("34°", "Daxing"), labels=("Weather",))
