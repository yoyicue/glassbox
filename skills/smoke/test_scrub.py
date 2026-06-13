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


# ————————————————————————————————————————————————————————————————————————
# Precision suite (2026-06-13): the structural detector must be precise enough
# that the privacy guard can derive its known-value set from ALL artifact scene
# layouts — springboard, App-Library, Settings-detail, Screen-Time — without
# anchoring generic iOS UI strings. Every value here is SYNTHETIC: the repo is
# public + MIT, so no real display name / SSID / device / email may appear.
#
# Each kind gets a POSITIVE control (the real on-rig shape — account card, WLAN
# list, Bluetooth page, Game-Center e-mail, date row — must STILL be caught) and
# a NEGATIVE control that mirrors a real over-fire example with a synthetic-
# equivalent generic scene (must yield ZERO derivations for that kind).
# ————————————————————————————————————————————————————————————————————————

# Synthetic personal values — obviously fake, never a real person/network/device.
_FAKE_NAME = "Sy Nthetic"           # two-word display name
_FAKE_SSID = "synthnet_5g"          # network-name shape
_FAKE_BT = "Synth Buds Pro"         # bluetooth device-name shape
_FAKE_NICK = "synthplayer"          # single-token game-center handle
_FAKE_EMAIL = "nobody@example.invalid"

_VIEWPORT = [448, 992]  # matches the committed iPhone/iPad floor viewport band.


def _el(text: str, cx: float, cy: float, *, w: float = 120, h: float = 16) -> dict:
    """A scene element with a centred box (the committed dict box shape)."""
    return {"text": text, "box": {"x": cx - w / 2.0, "y": cy - h / 2.0, "w": w, "h": h}}


def _elL(text: str, left_x: float, cy: float, *, w: float = 120, h: float = 16) -> dict:
    """A scene element pinned by its LEFT edge — for the account card, where the
    name row and the subtitle marker share a left edge (same text column)."""
    return {"text": text, "box": {"x": left_x, "y": cy - h / 2.0, "w": w, "h": h}}


def _geo_scene(*elements: dict, viewport=_VIEWPORT) -> dict:
    return {"elements": list(elements), "viewport_size": list(viewport)}


# —— account_name ——————————————————————————————————————————————————————————

@pytest.mark.smoke
def test_account_name_positive_in_upper_card_region():
    """POSITIVE control: the name row and the card subtitle share a left edge
    (same text column), the name a single row directly above the subtitle in the
    upper card band (cy ~= 0.22 of the viewport — the real cy~221 on a 992-tall
    viewport). Both geometry guards (card region + same-column abutment) pass."""
    scene = _geo_scene(
        _el("9:41", 80, 41),                 # status bar
        _el("Settings", 80, 94),             # nav title (must NOT be reached)
        _elL(_FAKE_NAME, 110, 198),          # name row, left edge 110
        _elL(_FULL_MARKER, 110, 221, w=300),  # subtitle, SAME left edge, +23px below
    )
    assert _findings_of(scene, "account_name") == [("account_name", 2, _FAKE_NAME)]


@pytest.mark.smoke
def test_account_name_rejected_when_name_in_a_different_column():
    """NEGATIVE control mirroring the report-view over-fire (account_name=14,
    generic labels like 'Airplane Mode'): a full-frame OCR dump where the marker
    is a LEFT sidebar row and a generic label sits in the RIGHT detail pane (same
    y-band, very different left edge). The same-column abutment guard rejects it
    even though the label is in the card-region y-band and directly precedes the
    marker in reading order."""
    scene = _geo_scene(
        _elL("Display & Brightness", 280, 198),  # right detail-pane label (left edge 280)
        _elL(_FULL_MARKER, 94, 221, w=120),       # sidebar marker (left edge 94) — dx=186
    )
    assert _findings_of(scene, "account_name") == []


@pytest.mark.smoke
def test_account_name_stops_at_first_substantive_row_never_reaches_nav_title():
    """NEGATIVE control mirroring the 'Airplane Mode' over-fire: when the real
    name row is absent/garbled, the walk-up must STOP at the first substantive
    row (here a scrolled root row) and reject it as generic UI chrome — it must
    NOT climb to the nav title ('Settings') above it."""
    scene = _geo_scene(
        _elL("Settings", 110, 94),            # nav title
        _elL("Airplane Mode", 110, 198),      # first substantive row above marker
        _elL(">", 360, 210, w=10),            # disclosure chevron (pure decoration)
        _elL(_FULL_MARKER, 110, 221, w=300),  # account subtitle in card band
    )
    assert _findings_of(scene, "account_name") == []


@pytest.mark.smoke
def test_account_name_rejected_when_marker_below_card_region():
    """NEGATIVE control: the subtitle string appearing far down the page (a
    scrolled list / search-results row, cy well past the card band) must not
    anchor a derivation even if a name-shaped row precedes it."""
    scene = _geo_scene(
        _elL(_FAKE_NAME, 110, 760),           # well below the card band
        _elL(_FULL_MARKER, 110, 783, w=300),  # marker at ~0.79 of viewport height
    )
    assert _findings_of(scene, "account_name") == []


@pytest.mark.smoke
def test_account_name_skips_decoration_but_keeps_text_only_compat():
    """Regression guard: text-only pseudo-scenes (no boxes, e.g. committed
    `texts`/`signature` dumps) carry no geometry, so the card-region gate must
    not block them — the chevron-skip behaviour is preserved there."""
    scene = _scene("Settings", _FAKE_NAME, "", ">", _FULL_MARKER)
    assert _findings_of(scene, "account_name") == [("account_name", 1, _FAKE_NAME)]


# —— bluetooth device name ——————————————————————————————————————————————————

@pytest.mark.smoke
def test_bt_device_positive_on_real_bluetooth_page():
    """POSITIVE control: a genuine Bluetooth page (title + 'My Devices'/'Other
    Devices' list structure) must still catch the device name."""
    scene = _scene("Bluetooth", "On", "My Devices", _FAKE_BT, "Connected", "Other Devices")
    assert _findings_of(scene, "bt_device") == [("bt_device", 3, _FAKE_BT)]


@pytest.mark.smoke
def test_bt_device_negative_on_screentime_sidebar_with_bare_devices():
    """NEGATIVE control mirroring the worst over-fire (bt_device=104 on 'Week'/
    'Day'): an iPad Settings-detail / Screen-Time scene whose sidebar carries a
    'Bluetooth' row, an 'On' status and a bare 'Devices' summary subtitle — but
    NO 'My Devices'/'Other Devices'/connection-status anchor — must yield zero
    bt_device derivations even though 'Week'/'Day' have the name-row shape."""
    scene = _scene(
        "Settings", "General", "Bluetooth", "On", "Devices",
        "Screen Time", "Week", "Day", "Today", "Accessibility", "Camera",
    )
    assert _findings_of(scene, "bt_device") == []


# —— ssid ————————————————————————————————————————————————————————————————

@pytest.mark.smoke
def test_ssid_positive_in_network_list_scene():
    """POSITIVE control: a WLAN page (My Networks / Other Networks) must still
    catch the network name."""
    scene = _scene("WLAN", "Edit", "My Networks", _FAKE_SSID, "Other Networks")
    assert _findings_of(scene, "ssid") == [("ssid", 3, _FAKE_SSID)]


@pytest.mark.smoke
def test_ssid_positive_on_wifi_row_geometrically():
    """POSITIVE control for the connected-SSID-on-the-WLAN-row rule (kept from
    the original suite, restated with the synthetic value)."""
    scene = {
        "elements": [
            _el("WLAN", 100, 318, w=47),
            _el("Bluetooth", 100, 363, w=67),
            _el(_FAKE_SSID, 300, 318, w=80),   # right of WLAN, same band
        ]
    }
    assert _findings_of(scene, "ssid") == [("ssid", 2, _FAKE_SSID)]


@pytest.mark.smoke
def test_ssid_negative_app_library_only_on_wifi_row_band():
    """NEGATIVE control mirroring the 'App Library Only' over-fire (ssid=26): on
    the iPad Settings root the 'Home Screen & App Library' detail pane renders
    'App Library Only' in the same y-band as, and to the right of, the WLAN
    sidebar row. It is generic UI chrome and must NOT be derived as an SSID."""
    scene = {
        "elements": [
            _el("WLAN", 100, 318, w=47),
            _el("App Library Only", 320, 318, w=122),  # generic, same band, right of WLAN
        ]
    }
    assert _findings_of(scene, "ssid") == []


@pytest.mark.smoke
def test_ssid_negative_app_library_only_in_network_list():
    """NEGATIVE control: even inside a network-list scene, the generic
    'App Library Only' string must be rejected (it can bleed into the iPad
    split view), while the synthetic SSID beside it is still caught."""
    scene = _scene("WLAN", "My Networks", _FAKE_SSID, "App Library Only", "Other Networks")
    assert _findings_of(scene, "ssid") == [("ssid", 2, _FAKE_SSID)]


# —— nickname ————————————————————————————————————————————————————————————

@pytest.mark.smoke
def test_nickname_positive_single_token_above_email():
    """POSITIVE control: a single-token Game-Center handle immediately above an
    e-mail row is still caught."""
    scene = _scene(_FAKE_NICK, _FAKE_EMAIL)
    assert _findings_of(scene, "nickname") == [("nickname", 0, _FAKE_NICK)]


@pytest.mark.smoke
def test_nickname_negative_generic_label_above_unrelated_email():
    """NEGATIVE control mirroring the 'Accessibility' over-fire (nickname=2): a
    generic single-token settings label that happens to render above an
    unrelated e-mail row must NOT be derived as a nickname."""
    scene = _scene("Accessibility", _FAKE_EMAIL)
    assert _findings_of(scene, "nickname") == []
    # The e-mail itself is of course still caught — only the bogus nickname is gone.
    assert _findings_of(scene, "email") == [("email", 1, _FAKE_EMAIL)]


# —— phone / email / date: precise kinds, restated as positive controls ——————

@pytest.mark.smoke
def test_phone_email_date_positive_controls_unchanged():
    """The phone/email/date kinds were already precise (no over-fire); restate
    them as positive controls so a future tightening cannot silently drop them."""
    assert _findings_of(_scene("+1 (555) 010-0042"), "phone") == [
        ("phone", 0, "+1 (555) 010-0042")
    ]
    assert _findings_of(_scene("6:23"), "phone") == []          # time, not a phone
    assert _findings_of(_scene(_FAKE_EMAIL), "email") == [("email", 0, _FAKE_EMAIL)]
    assert _findings_of(_scene("Date added:", "1 Jan 2020"), "date") == [
        ("date", 1, "1 Jan 2020")
    ]


# —— whole-scene negative controls: realistic generic scenes derive NOTHING ——

@pytest.mark.smoke
def test_springboard_with_app_labels_yields_no_derivations():
    """NEGATIVE control: a springboard / home-screen page of app labels —
    including the very strings that collide with the committed tree ('Settings'
    is in skills/crawl/crawl_app.py; 'Camera' is in the golden corpus) — must
    derive ZERO personal values of ANY kind."""
    scene = _scene(
        "Settings", "Camera", "Photos", "Maps", "Notes", "Reminders",
        "Clock", "Weather", "Calendar", "App Library",
    )
    assert find_personal_texts(scene) == []


@pytest.mark.smoke
def test_screen_time_detail_with_week_day_yields_no_derivations():
    """NEGATIVE control: a Screen-Time detail page ('Week'/'Day'/'Today') — the
    exact bt_device over-fire source — derives nothing."""
    scene = _scene(
        "Screen Time", "Week", "Day", "Today", "Most Used", "Pickups",
        "Notifications", "Limits", "See All Activity",
    )
    assert find_personal_texts(scene) == []


@pytest.mark.smoke
def test_app_library_page_yields_no_derivations():
    """NEGATIVE control: an App-Library page ('App Library Only') derives
    nothing."""
    scene = _scene(
        "App Library", "App Library Only", "Search", "Recently Added",
        "Suggestions", "Utilities", "Productivity",
    )
    assert find_personal_texts(scene) == []


@pytest.mark.smoke
def test_settings_detail_section_header_yields_no_derivations():
    """NEGATIVE control: a Settings-detail page whose section header and rows are
    all generic chrome derives nothing."""
    scene = _scene(
        "General", "About", "Software Update", "AirDrop", "AirPlay & Handoff",
        "Picture in Picture", "CarPlay", "Background App Refresh",
    )
    assert find_personal_texts(scene) == []


@pytest.mark.smoke
def test_full_scene_positive_controls_still_fire_per_kind():
    """Belt-and-braces: the union of the per-kind positive controls (all
    synthetic) is still detected end-to-end, so the negative controls above are
    not vacuously green from a globally-broken detector."""
    assert _findings_of(_geo_scene(
        _elL(_FAKE_NAME, 110, 198), _elL(_FULL_MARKER, 110, 221, w=300),
    ), "account_name") == [("account_name", 0, _FAKE_NAME)]
    assert _findings_of(
        _scene("Bluetooth", "My Devices", _FAKE_BT), "bt_device"
    ) == [("bt_device", 2, _FAKE_BT)]
    assert _findings_of(
        _scene("My Networks", _FAKE_SSID, "Other Networks"), "ssid"
    ) == [("ssid", 1, _FAKE_SSID)]
    assert _findings_of(_scene(_FAKE_NICK, _FAKE_EMAIL), "nickname") == [
        ("nickname", 0, _FAKE_NICK)
    ]
