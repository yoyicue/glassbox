"""Shared structural personal-data detector + scrubber for committed corpora.

Used by the S1 transition-corpus extractor (skills/regression/
extract_transition_corpus.py), the Tier-A golden harvest (skills/regression/
golden_ingest.py) and the repo-wide privacy guard (skills/smoke/
test_privacy_guard.py). Detection is **structural** — the personal strings
themselves never appear in this file or in the tests.

Scrubbed classes (replaced with stable placeholders so replay still works):
  - Apple Account display name on the Settings root (SCRUBBED_ACCOUNT_NAME) —
    anchored on the "Apple Account, iCloud …" subtitle (iPhone full and iPad
    truncated variants); a candidate row must be >= 2 chars and contain at
    least one letter, so OCR chevrons ('>') are never collected.
  - Wi-Fi/WLAN network names (SCRUBBED_SSID_n) — list rows in network-list
    scenes plus the connected-SSID value rendered on the WLAN/Wi-Fi row
    itself (same row band, to the right of the label).
  - Bluetooth device names (SCRUBBED_BT_DEVICE_n)
  - phone numbers / digit runs >= 7 (SCRUBBED_PHONE_n)
  - e-mail addresses (SCRUBBED_EMAIL_n)
  - Game Center nickname — the single-token line right above an e-mail
    (SCRUBBED_GC_NICKNAME_n)
  - account dates following a "Date added:" label (SCRUBBED_DATE_n)
"""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER_PREFIX = "SCRUBBED_"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Digit-ish span (optionally starting with "+") — personal iff it carries >= 7
# digits, so times ("6:23"), percentages and small counters survive untouched.
_PHONEISH_RE = re.compile(r"\+?\d[\d\s().\-]*\d")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_MIN_PHONE_DIGITS = 7
# A WLAN/SSID row value sometimes carries a trailing disclosure chevron in OCR
# ("mynet42 >"); strip it so the detector matches on the bare network name.
_TRAILING_DECORATION_RE = re.compile(r"[\s>›＞]+$")

# Structural markers (generic iOS chrome, not personal values).
# The account subtitle renders as "Apple Account, iCloud and more" on iPhone
# and truncates to "Apple Account, iCloud" (sometimes with a separate
# "and more" row) on the iPad sidebar.
_ACCOUNT_MARKER_COMPACTS = ("appleaccounticloudandmore", "appleaccounticloud")
_DATE_MARKER_COMPACT = "dateadded"
_NETWORK_LIST_MARKERS = {"My Networks", "Other Networks"}
_NETWORK_CHROME = {"WLAN", "Wi-Fi", "WiFi", "Edit", "My Networks", "Other Networks", "Networks"}
# Section subtitles that, on a *real* Bluetooth page, head the device list. The
# bare "Devices" line is deliberately NOT here: it is the Apple-Account-style
# summary subtitle and also renders on the iPad Settings sidebar of unrelated
# detail pages (Screen Time etc.), so it is too weak to anchor on (see
# _is_bluetooth_scene).
_BLUETOOTH_SECTION_MARKERS = {"My Devices", "Other Devices"}
# Strong connection-status context that only the Bluetooth page renders.
_BLUETOOTH_STATUS_MARKERS = {"Now Discoverable", "Connected", "Not Connected"}
_BLUETOOTH_CHROME = {
    "Bluetooth", "Devices", "My Devices", "Other Devices",
    "On", "Off", "Connected", "Not Connected", "Now Discoverable",
}
# Generic iOS chrome that the loose name-row shape used to mis-anchor as a
# personal value (BT device / SSID) on heterogeneous scenes. These are public
# Apple UI strings, never personal — listing them as a reject-set keeps the
# detector from over-deriving when the wider FIX-2 derivation scan feeds it
# springboard / Screen-Time / App-Library / Settings-detail scenes.
_GENERIC_UI_NONPERSONAL = {
    # Settings sidebar / section / nav chrome.
    "Settings", "General", "Accessibility", "Bluetooth", "Wallpaper",
    "Notifications", "Sounds", "Sounds & Haptics", "Display & Brightness",
    "Privacy", "Privacy & Security", "Battery", "Storage", "Focus",
    "Control Center", "Action Button", "Camera", "Photos", "Apps",
    "Airplane Mode", "Wi-Fi", "WLAN", "Cellular", "Mobile Data", "Hotspot",
    "Personal Hotspot", "VPN", "Search", "Edit", "Done", "Back", "More",
    "Home Screen & App Library", "App Library", "App Library Only",
    # Account-card chrome: the "and more" subtitle continuation and the iPad
    # search field render adjacent to the account marker but are NOT the name
    # ("Search" is already listed above under Settings chrome).
    "and more", "Q Search",
    # Screen-Time content that shares the iPad sidebar band ("Notifications"
    # is already listed above under Settings chrome).
    "Screen Time", "Week", "Day", "Today", "Yesterday", "This Week",
    "Most Used", "Pickups", "Limits", "Daily Average",
}


def _is_generic_ui_label(text: str) -> bool:
    """True for public Apple UI chrome that must never be derived as a personal
    value. Compared case-insensitively after whitespace collapse so OCR casing
    ('SETTINGS') and stray double-spaces still match."""
    collapsed = " ".join(text.split())
    folded = collapsed.casefold()
    return any(folded == g.casefold() for g in _GENERIC_UI_NONPERSONAL)


# Settings rows whose right-hand value is the *connected* network name.
_WIFI_ROW_LABELS = {"WLAN", "Wi-Fi", "WiFi", "无线局域网"}
# Status/nav words that legitimately render in the WLAN/Wi-Fi row's band:
# row-value states, neighbouring row labels, and the nav-bar back label that
# shares the title band with "WLAN" on sub-pages mid-transition.
_WIFI_ROW_VALUE_CHROME = _NETWORK_CHROME | _BLUETOOTH_CHROME | _GENERIC_UI_NONPERSONAL | {
    "Airplane Mode", "Not Connected", "Settings", "设置", "Back",
}

# The account card lives in the upper part of the Settings root: across the
# committed iPhone/iPad floor scenes the "Apple Account, iCloud and more"
# subtitle renders at cy ~= 0.18-0.25 of the viewport height (e.g. cy~221 on a
# 992-tall viewport). A generous ceiling rejects the same string appearing in a
# scrolled list or a search-results row further down the page.
_ACCOUNT_CARD_MAX_CY_FRACTION = 0.40
# Fallback ceiling (absolute px) when the scene carries no viewport size.
_ACCOUNT_CARD_MAX_CY_ABS = 420.0
# On a real account card the name row and the subtitle marker are stacked in the
# SAME text column (left-aligned to the right of the avatar), so their left
# edges coincide and the name sits a single row directly above the subtitle.
# Measured across the committed floor scenes: dx == 0 px and gap 7-34 px. The
# report-view OCR dumps mis-anchored generic labels (a sidebar marker vs a
# detail-pane label) showed |dx| 180-394 px or a negative / far gap — so these
# two box-geometry guards reject them when boxes are present. (Box-free
# pseudo-scenes — committed `texts`/`signature` dumps — skip the guards.)
_ACCOUNT_NAME_MAX_DX = 40.0
_ACCOUNT_NAME_MAX_GAP = 48.0


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (text or "").casefold())


def _texts(scene: dict[str, Any]) -> list[str]:
    return [str(e.get("text") or "") for e in scene.get("elements", [])]


def _digit_count(span: str) -> int:
    return sum(ch.isdigit() for ch in span)


def _looks_like_name_row(text: str) -> bool:
    """Short non-sentence line: the shape of an SSID / device-name list row."""
    stripped = text.strip()
    if len(stripped) < 2 or stripped.startswith(PLACEHOLDER_PREFIX):
        return False
    if _TIME_RE.match(stripped):
        return False
    if stripped.count(" ") >= 3:  # prose/sentences
        return False
    return not stripped.endswith((".", "…"))  # sentence fragments


# Characters that a network/device identifier almost always carries and a
# Title-Case UI label almost never does (digits, separators) — the signal that
# tells a router/IoT SSID apart from a settings phrase. (No real SSID literal
# appears here: this repo is public + MIT.)
_NET_ID_CHAR_RE = re.compile(r"[0-9_\-./:]")
# A network/device NAME must be at least this long: there are no real 2-3 char
# SSIDs / Bluetooth names in the corpus, and short fragments are OCR noise that
# substring-matches generic English ("in", "...").
_MIN_NAME_ROW_LEN = 4


def _looks_like_ui_phrase(text: str) -> bool:
    """A Title-Case English phrase with NO network identifier character — the
    shape of an iOS UI label ('App Store', 'Siri Requests', 'Light'), not an
    SSID / device name. These bled into the WLAN-row band / network list on
    full-frame report-view OCR dumps and were mis-derived as SSIDs."""
    stripped = text.strip()
    if _NET_ID_CHAR_RE.search(stripped):
        return False
    words = stripped.split()
    return bool(words) and all(w[:1].isupper() and w.isalpha() for w in words)


def _is_substantive_device_row(text: str) -> bool:
    """Stricter `_looks_like_name_row` for the Bluetooth-device rule: long enough
    (>= 4 chars) and not generic UI chrome. Real device names are often
    Title-Case ('Magic Keyboard'), so the UI-phrase reject is NOT applied here —
    `_is_bluetooth_scene` already gates this rule to a genuine Bluetooth page."""
    stripped = text.strip()
    if len(stripped) < _MIN_NAME_ROW_LEN:
        return False
    if _is_generic_ui_label(stripped):
        return False
    return _looks_like_name_row(stripped)


def _is_substantive_ssid_row(text: str) -> bool:
    """Stricter name-row shape for the SSID rules: a real network-name shape —
    long enough, not generic UI chrome, and not a Title-Case UI phrase. The
    network-list / WLAN-row rules can otherwise pick up detail-pane labels
    ('Siri Requests') that bled into the row band on full-frame report-view OCR;
    real SSIDs carry a network identifier char or are not Title-Case English."""
    stripped = text.strip()
    if len(stripped) < _MIN_NAME_ROW_LEN:
        return False
    if _is_generic_ui_label(stripped) or _looks_like_ui_phrase(stripped):
        return False
    return _looks_like_name_row(stripped)


def _is_account_name_candidate(text: str) -> bool:
    """Guard for the account-name rule: >= 2 chars and at least one letter (any
    script), so OCR chevron/symbol fragments ('>', '•', '①') are never
    collected — collecting '>' would substring-rewrite every disclosure
    chevron in the corpus."""
    stripped = text.strip()
    return len(stripped) >= 2 and any(ch.isalpha() for ch in stripped)


def _is_pure_decoration_row(text: str) -> bool:
    """A row that carries no substantive content and may sit between the account
    name and its subtitle (a disclosure chevron, a bullet/symbol, or a short
    fragment with no letter). The account walk-up skips ONLY these; it stops at
    the first substantive row so it can never reach the nav title or a scrolled
    root row far above the card."""
    stripped = text.strip()
    if not stripped:
        return True
    # Short fragment with no letter in any script (chevron '>', '•', '①', '...').
    return len(stripped) < 2 or not any(ch.isalpha() for ch in stripped)


def _box_xywh(box: Any) -> tuple[float, float, float, float] | None:
    """Normalise the two committed box shapes (dict and [x, y, w, h] list)."""
    if isinstance(box, dict):
        try:
            return float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(box, (list, tuple)) and len(box) == 4:
        try:
            x, y, w, h = (float(v) for v in box)
        except (TypeError, ValueError):
            return None
        return x, y, w, h
    return None


def _element_cy(element: dict[str, Any]) -> float | None:
    """Vertical centre of an element's box, or None if it has no usable box."""
    box = _box_xywh(element.get("box")) if isinstance(element, dict) else None
    if box is None:
        return None
    _x, y, _w, h = box
    return y + h / 2.0


def _viewport_height(scene: dict[str, Any]) -> float | None:
    """Scene viewport height from ``viewport_size`` ([w, h] or {"h": ...})."""
    vp = scene.get("viewport_size")
    if isinstance(vp, (list, tuple)) and len(vp) == 2:
        try:
            return float(vp[1])
        except (TypeError, ValueError):
            return None
    if isinstance(vp, dict):
        for key in ("h", "height"):
            if key in vp:
                try:
                    return float(vp[key])
                except (TypeError, ValueError):
                    return None
    return None


def _in_account_card_region(scene: dict[str, Any], marker_idx: int) -> bool:
    """The account subtitle anchors a derivation only when it sits in the upper
    card band — small cy relative to the viewport height (or, lacking a viewport
    size, under an absolute pixel ceiling). Rejects the same marker string when
    it appears in a scrolled list / search-results row further down the page."""
    elements = scene.get("elements", [])
    if not (0 <= marker_idx < len(elements)):
        return True  # no geometry to test against → don't block (text-only scenes)
    cy = _element_cy(elements[marker_idx])
    if cy is None:
        return True  # text-only pseudo-scene (no boxes) → geometry can't gate
    height = _viewport_height(scene)
    if height and height > 0:
        return cy <= height * _ACCOUNT_CARD_MAX_CY_FRACTION
    return cy <= _ACCOUNT_CARD_MAX_CY_ABS


def _name_abuts_account_card(scene: dict[str, Any], name_idx: int, marker_idx: int) -> bool:
    """The name row and the subtitle marker must be stacked in the same card text
    column — left edges aligned (|dx| small) and the name a single row directly
    above the marker (small positive cy gap). Applied only when BOTH carry a box;
    box-free pseudo-scenes (committed text dumps) bypass it so the structural
    shape scan and the text-only positive tests still work."""
    elements = scene.get("elements", [])
    if not (0 <= name_idx < len(elements) and 0 <= marker_idx < len(elements)):
        return True
    name_box = _box_xywh(elements[name_idx].get("box"))
    marker_box = _box_xywh(elements[marker_idx].get("box"))
    if name_box is None or marker_box is None:
        return True  # no geometry to test → don't block
    nx, ny, _nw, nh = name_box
    mx, my, _mw, mh = marker_box
    if abs(mx - nx) > _ACCOUNT_NAME_MAX_DX:
        return False  # name in a different column (sidebar marker vs detail pane)
    gap = (my + mh / 2.0) - (ny + nh / 2.0)
    return 0.0 < gap <= _ACCOUNT_NAME_MAX_GAP


def _is_network_list_scene(scene: dict[str, Any]) -> bool:
    return any(t.strip() in _NETWORK_LIST_MARKERS for t in _texts(scene))


def _is_bluetooth_scene(scene: dict[str, Any]) -> bool:
    """A *real* Bluetooth page: the "Bluetooth" title plus the device-list
    structure ("My Devices"/"Other Devices") or connection-status context
    ("Now Discoverable"/"Connected"/"Not Connected"). The bare "Bluetooth"+
    "Devices" pair is rejected — that combination also appears on the iPad
    Settings sidebar of unrelated detail pages (Screen Time), which used to make
    the device-name rule over-fire on generic labels ("Week", "Day")."""
    texts = [t.strip() for t in _texts(scene)]
    if "Bluetooth" not in texts:
        return False
    return any(t in _BLUETOOTH_SECTION_MARKERS or t in _BLUETOOTH_STATUS_MARKERS for t in texts)


def find_personal_texts(scene: dict[str, Any]) -> list[tuple[str, int, str]]:
    """Structural personal-data detector: list of (kind, element_index, text).

    Shared with the smoke scrub tests (which assert it returns [] on every
    committed scene): scrubbed placeholders are never reported, so the scrub is
    idempotent by construction.
    """
    findings: list[tuple[str, int, str]] = []
    texts = _texts(scene)
    for idx, text in enumerate(texts):
        if text.startswith(PLACEHOLDER_PREFIX):
            continue
        if _EMAIL_RE.search(text):
            findings.append(("email", idx, text))
        for match in _PHONEISH_RE.finditer(text):
            if _digit_count(match.group()) >= _MIN_PHONE_DIGITS:
                findings.append(("phone", idx, text))
                break
    def prev_nonempty(idx: int) -> int | None:
        """Nearest preceding element with text (OCR scenes interleave nulls)."""
        for back in range(idx - 1, -1, -1):
            if texts[back].strip():
                return back
        return None

    # Account display name: the row right above the "Apple Account, iCloud
    # and more" subtitle on the Settings root (iPad truncates the subtitle to
    # "Apple Account, iCloud"). Two structural guards keep this from walking
    # arbitrarily far when the real name row is absent / OCR-garbled or when the
    # subtitle string surfaces outside the card (search results, scrolled list):
    #   * POSITION — the subtitle must sit in the upper card region (small cy /
    #     near the top); see `_in_account_card_region`.
    #   * NEAREST SUBSTANTIVE ROW — the name is the immediately preceding
    #     substantive row. Skip ONLY pure-decoration rows (chevron / symbol /
    #     short-no-letter / empty), then STOP at the first substantive row even
    #     if it fails the name guard — never reach the nav title or a scrolled
    #     root row above it. Generic nav-title / root-row stop-words are
    #     rejected outright.
    #   * SAME-COLUMN ABUTMENT — when boxes are present, the name must be stacked
    #     directly above the marker in the same card column (`_name_abuts_
    #     account_card`); this rejects full-frame report-view OCR dumps where the
    #     marker (a left sidebar row) and a generic label (a right detail-pane
    #     row) merely share a y-band.
    for idx, text in enumerate(texts):
        if _compact(text) not in _ACCOUNT_MARKER_COMPACTS:
            continue
        if not _in_account_card_region(scene, idx):
            continue
        cursor = idx
        while True:
            prev_idx = prev_nonempty(cursor)
            if prev_idx is None:
                break
            candidate = texts[prev_idx]
            if candidate.startswith(PLACEHOLDER_PREFIX):
                break
            if _is_pure_decoration_row(candidate):
                cursor = prev_idx  # skip a chevron / avatar-symbol between name + subtitle
                continue
            # First substantive row reached — this is the name slot. Accept it
            # only if it passes the name guard, is not generic UI chrome, and
            # (when boxes exist) abuts the card subtitle in the same column;
            # either way we STOP here, never climbing to the nav title above.
            if (
                _is_account_name_candidate(candidate)
                and not _is_generic_ui_label(candidate)
                and _name_abuts_account_card(scene, prev_idx, idx)
            ):
                findings.append(("account_name", prev_idx, candidate))
            break
    # Date value following a "Date added:" label.
    for idx, text in enumerate(texts[:-1]):
        if _compact(text) == _DATE_MARKER_COMPACT:
            nxt = texts[idx + 1]
            if nxt.strip() and not nxt.startswith(PLACEHOLDER_PREFIX):
                findings.append(("date", idx + 1, nxt))
    # Game Center nickname: single-token line immediately above an e-mail
    # (or above an already-scrubbed e-mail placeholder). The single-token shape
    # alone also matches a generic settings label that happens to render above
    # an unrelated e-mail row, so reject known UI chrome ("Accessibility") and
    # require an actual nickname shape (>= 2 chars, at least one letter).
    for idx, text in enumerate(texts[1:], start=1):
        emailish = bool(_EMAIL_RE.search(text)) or text.startswith(f"{PLACEHOLDER_PREFIX}EMAIL")
        if not emailish:
            continue
        prev_idx = prev_nonempty(idx)
        if prev_idx is None:
            continue
        prev = texts[prev_idx].strip()
        if " " in prev or prev.startswith(PLACEHOLDER_PREFIX):
            continue
        if _is_generic_ui_label(prev) or not _is_account_name_candidate(prev):
            continue
        findings.append(("nickname", prev_idx, texts[prev_idx]))
    # Network names in a network-list scene (WLAN / Wi-Fi page). The substantive
    # name-row shape rejects generic iOS chrome ("App Library Only"), Title-Case
    # UI phrases ("Siri Requests") and short OCR fragments that share the loose
    # name-row shape but are not network names.
    if _is_network_list_scene(scene):
        for idx, text in enumerate(texts):
            if text.strip() in _NETWORK_CHROME:
                continue
            if not _is_substantive_ssid_row(text):
                continue
            findings.append(("ssid", idx, text))
    # Bluetooth device names: list rows after a Devices/My Devices/Other Devices
    # section marker (or once connection-status context has started the list).
    # `_is_bluetooth_scene` already requires the strong Bluetooth-page anchor,
    # so this only runs on a genuine Bluetooth page; the substantive name-row
    # shape is belt-and-braces against sidebar bleed-through.
    if _is_bluetooth_scene(scene):
        started = False
        for idx, text in enumerate(texts):
            stripped = text.strip()
            if stripped in _BLUETOOTH_SECTION_MARKERS or stripped in _BLUETOOTH_STATUS_MARKERS:
                started = True
                continue
            if not started or stripped in _BLUETOOTH_CHROME:
                continue
            if _is_substantive_device_row(text):
                findings.append(("bt_device", idx, text))
    # Connected-SSID value on the WLAN/Wi-Fi settings row itself: same row
    # band as the label, to its right (Settings root and the iPad sidebar
    # render the joined network there; the run may never open the network
    # list, so the list rule above cannot learn the value).
    elements = scene.get("elements", [])
    for idx, element in enumerate(elements):
        if str(element.get("text") or "").strip() not in _WIFI_ROW_LABELS:
            continue
        row = _box_xywh(element.get("box"))
        if row is None:
            continue
        row_x, row_y, row_w, row_h = row
        for jdx, other in enumerate(elements):
            if jdx == idx:
                continue
            text = str(other.get("text") or "")
            stripped = text.strip()
            if stripped in _WIFI_ROW_VALUE_CHROME or stripped in _WIFI_ROW_LABELS:
                continue
            # The connected-SSID value sits to the right of the WLAN label. The
            # substantive name-row shape rejects "App Library Only" and other
            # generic detail-pane labels that share the y-band on the iPad root.
            # The bare-value chevron variant ("mynet42 >") still qualifies — the
            # trailing chevron is stripped by the Scrubber, not here.
            value_stem = _TRAILING_DECORATION_RE.sub("", stripped)
            if not _is_substantive_ssid_row(value_stem):
                continue
            box = _box_xywh(other.get("box"))
            if box is None:
                continue
            x, y, _w, h = box
            center_y = y + h / 2.0
            if row_y <= center_y <= row_y + row_h and x >= row_x + row_w:
                findings.append(("ssid", jdx, text))
    return findings


class Scrubber:
    """Two-pass scrub: collect personal values across all scenes, then replace
    them (exact + substring, longest-first) everywhere — including free-text
    verdict reasons. Placeholders are stable per distinct value. A second,
    token-boundary-guarded loose pass catches OCR case/whitespace garbles of
    the collected values (e.g. a space dropped inside a display name)."""

    # The wifi-row rule reports the full row value; OCR appends the disclosure
    # chevron to it on some captures. Collect the bare name so the placeholder
    # map stays keyed on the actual SSID. (Module-level alias; the detector uses
    # the same pattern when shape-checking the wifi-row value.)
    _TRAILING_DECORATION_RE = _TRAILING_DECORATION_RE

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._loose: dict[str, re.Pattern[str]] = {}
        # Deferred (kind, value) observations for the deterministic union mode:
        # collected without assigning ordinals so the placeholder numbering can
        # be made independent of run/scene iteration order (see
        # ``collect_deferred`` / ``finalize_union``).
        self._deferred: dict[str, str] = {}  # value -> kind (first kind wins)

    def _placeholder(self, kind: str, value: str) -> str:
        if value in self._map:
            return self._map[value]
        if kind == "account_name":
            label = f"{PLACEHOLDER_PREFIX}ACCOUNT_NAME"
            if self._counters.get(kind):
                label = f"{label}_{self._counters[kind] + 1}"
        else:
            token = {
                "ssid": "SSID",
                "bt_device": "BT_DEVICE",
                "phone": "PHONE",
                "email": "EMAIL",
                "nickname": "GC_NICKNAME",
                "date": "DATE",
            }[kind]
            label = f"{PLACEHOLDER_PREFIX}{token}_{self._counters.get(kind, 0) + 1}"
        self._counters[kind] = self._counters.get(kind, 0) + 1
        self._map[value] = label
        self._loose[value] = self._loose_pattern(value)
        return label

    @staticmethod
    def _loose_pattern(value: str) -> re.Pattern[str]:
        """Case-insensitive, whitespace-elastic variant of the value, guarded
        by non-alphanumeric boundaries so short values cannot rewrite the
        inside of unrelated words."""
        parts = [re.escape(part) for part in value.split()] or [re.escape(value)]
        body = r"\s*".join(parts)
        return re.compile(rf"(?<![A-Za-z0-9_]){body}(?![A-Za-z0-9_])", re.IGNORECASE)

    def collect(self, scene: dict[str, Any]) -> None:
        texts = _texts(scene)
        for kind, idx, _text in find_personal_texts(scene):
            text = texts[idx]
            if kind in {"email", "phone"}:
                regex = _EMAIL_RE if kind == "email" else _PHONEISH_RE
                for match in regex.finditer(text):
                    span = match.group()
                    if kind == "phone" and _digit_count(span) < _MIN_PHONE_DIGITS:
                        continue
                    self._placeholder(kind, span)
            else:
                value = self._TRAILING_DECORATION_RE.sub("", text.strip())
                if value:
                    self._placeholder(kind, value)

    def collect_deferred(self, scene: dict[str, Any]) -> None:
        """Record this scene's personal values WITHOUT assigning placeholder
        ordinals yet. Used to build a *union* scrubber across many runs whose
        placeholder numbering must not depend on run/scene iteration order:
        call this over every run's scenes, then :meth:`finalize_union`.

        The recorded value is the same canonical span ``collect`` would store
        (the bare email/phone match, or the trailing-decoration-stripped name),
        so finalize produces exactly the placeholders ``collect`` would have."""
        texts = _texts(scene)
        for kind, idx, _text in find_personal_texts(scene):
            text = texts[idx]
            if kind in {"email", "phone"}:
                regex = _EMAIL_RE if kind == "email" else _PHONEISH_RE
                for match in regex.finditer(text):
                    span = match.group()
                    if kind == "phone" and _digit_count(span) < _MIN_PHONE_DIGITS:
                        continue
                    self._deferred.setdefault(span, kind)
            else:
                value = self._TRAILING_DECORATION_RE.sub("", text.strip())
                if value:
                    self._deferred.setdefault(value, kind)

    def finalize_union(self) -> None:
        """Assign placeholders to all deferred values in a DETERMINISTIC order
        (by kind, then value), so a fresh harvest yields the same union
        placeholders on any host regardless of which run was scanned first.
        Idempotent; values already assigned via ``collect`` keep their map."""
        for value, kind in sorted(self._deferred.items(), key=lambda kv: (kv[1], kv[0])):
            self._placeholder(kind, value)
        self._deferred.clear()

    def scrub_text(self, text: str | None, *, skip: set[str] | None = None) -> str | None:
        """Replace collected personal values with their placeholders.

        ``skip`` excludes specific values from substitution — used by the
        residual (union) pass so it only touches CROSS-RUN leaks the per-run
        scrubber already handled with its own ordinals, leaving the committed
        per-run placeholders byte-identical (no corpus churn)."""
        if not text:
            return text
        out = text
        active = [v for v in sorted(self._map, key=len, reverse=True) if not (skip and v in skip)]
        for value in active:
            if value in out:
                out = out.replace(value, self._map[value])
        # Loose pass: OCR case/whitespace garbles of already-collected values.
        for value in active:
            out = self._loose[value].sub(self._map[value], out)
        return out

    def scrub_scene(self, scene: dict[str, Any]) -> None:
        for element in scene.get("elements", []):
            element["text"] = self.scrub_text(element.get("text"))

    @property
    def replacement_count(self) -> int:
        return len(self._map)

    def counts(self) -> dict[str, int]:
        return dict(self._counters)

    def values(self) -> set[str]:
        """The collected personal values (for host-local sweeps; never commit)."""
        return set(self._map)
