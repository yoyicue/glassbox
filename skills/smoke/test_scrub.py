"""Unit tests for the shared structural personal-data detector + scrubber.

skills/regression/scrub.py is the single scrub core used by the S1 transition
corpus extractor, the Tier-A golden harvest and the repo privacy guard. No
personal literals appear here — every fixture string is a neutral stand-in.
"""

from __future__ import annotations

import pytest

from skills.regression.scrub import PLACEHOLDER_PREFIX, Scrubber, find_personal_texts

_FULL_MARKER = "Apple Account, iCloud and more"
_TRUNCATED_MARKER = "Apple Account, iCloud"  # iPad sidebar truncation


def _scene(*texts: str) -> dict:
    return {"elements": [{"text": text} for text in texts]}


def _findings_of(scene: dict, kind: str) -> list[tuple[str, int, str]]:
    return [f for f in find_personal_texts(scene) if f[0] == kind]


@pytest.mark.smoke
def test_account_name_detected_above_full_marker():
    scene = _scene("Settings", "Jo Doe", _FULL_MARKER)
    assert _findings_of(scene, "account_name") == [("account_name", 1, "Jo Doe")]


@pytest.mark.smoke
def test_account_name_candidate_must_have_two_chars_and_a_letter():
    """The guard that fixes the '>' false positive: an OCR chevron/symbol
    fragment right above the marker must never be collected — collecting '>'
    would substring-rewrite every disclosure chevron in a corpus."""
    assert _findings_of(_scene(">", _FULL_MARKER), "account_name") == []
    assert _findings_of(_scene("1234", _FULL_MARKER), "account_name") == []  # no letter
    assert _findings_of(_scene("A", _FULL_MARKER), "account_name") == []  # too short
    # ... while letters in any script qualify.
    assert _findings_of(_scene("李雷", _FULL_MARKER), "account_name") == [
        ("account_name", 0, "李雷")
    ]


@pytest.mark.smoke
def test_account_name_walks_past_chevron_to_the_real_name():
    """OCR sometimes slips the disclosure chevron (and empty rows) between the
    name and the subtitle; the rule must reject the fragment AND still find
    the name above it."""
    scene = _scene("Settings", "Jo Doe", "", ">", _FULL_MARKER)
    assert _findings_of(scene, "account_name") == [("account_name", 1, "Jo Doe")]


@pytest.mark.smoke
def test_account_name_detected_above_ipad_truncated_marker():
    scene = _scene("Q Search", "Jo Doe", _TRUNCATED_MARKER, "and more")
    assert _findings_of(scene, "account_name") == [("account_name", 1, "Jo Doe")]


@pytest.mark.smoke
def test_connected_ssid_on_wifi_row_is_detected_geometrically():
    """The Settings root / iPad sidebar renders the joined network on the
    WLAN row itself (same row band, right of the label) — a run that never
    opens the network list still leaks it there."""
    scene = {
        "elements": [
            {"text": "Airplane Mode", "box": {"x": 703, "y": 273, "w": 100, "h": 17}},
            {"text": "WLAN", "box": {"x": 703, "y": 318, "w": 47, "h": 14}},
            {"text": "Bluetooth", "box": {"x": 706, "y": 363, "w": 67, "h": 17}},
            {"text": "mynet42", "box": {"x": 820, "y": 318, "w": 45, "h": 14}},
            {"text": "On", "box": {"x": 840, "y": 363, "w": 25, "h": 14}},
        ]
    }
    assert _findings_of(scene, "ssid") == [("ssid", 3, "mynet42")]


@pytest.mark.smoke
def test_wifi_row_rule_supports_list_boxes_and_ignores_other_rows():
    scene = {
        "elements": [
            {"text": "WLAN", "box": [40, 236, 68, 20]},
            {"text": "below-the-row", "box": [40, 300, 80, 20]},  # not in the band
            {"text": "Edit", "box": [378, 240, 34, 18]},  # chrome, same band
        ]
    }
    assert _findings_of(scene, "ssid") == []


@pytest.mark.smoke
def test_scrubber_strips_trailing_chevron_from_collected_value():
    scene = {
        "elements": [
            {"text": "WLAN", "box": {"x": 80, "y": 370, "w": 60, "h": 16}},
            {"text": "mynet42 >", "box": {"x": 300, "y": 370, "w": 90, "h": 16}},
        ]
    }
    scrubber = Scrubber()
    scrubber.collect(scene)
    assert scrubber.scrub_text("mynet42 >") == f"{PLACEHOLDER_PREFIX}SSID_1 >"
    assert scrubber.scrub_text("joined mynet42 yesterday") == (
        f"joined {PLACEHOLDER_PREFIX}SSID_1 yesterday"
    )


@pytest.mark.smoke
def test_scrubber_loose_pass_catches_case_and_whitespace_garbles():
    scene = _scene("Jo Doe", _FULL_MARKER)
    scrubber = Scrubber()
    scrubber.collect(scene)
    placeholder = f"{PLACEHOLDER_PREFIX}ACCOUNT_NAME"
    assert scrubber.scrub_text("Jo Doe") == placeholder
    assert scrubber.scrub_text("JoDoe") == placeholder  # OCR drops the space
    assert scrubber.scrub_text("JO  DOE row") == f"{placeholder} row"
    # ... but never rewrites the inside of unrelated words or snake_case tokens.
    assert scrubber.scrub_text("majodoesty") == "majodoesty"
    assert scrubber.scrub_text("x_jodoe_y") == "x_jodoe_y"


@pytest.mark.smoke
def test_scrub_is_idempotent_on_placeholders():
    scene = _scene(f"{PLACEHOLDER_PREFIX}ACCOUNT_NAME", _FULL_MARKER)
    assert find_personal_texts(scene) == []
