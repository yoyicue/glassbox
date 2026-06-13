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

# Structural markers (generic iOS chrome, not personal values).
# The account subtitle renders as "Apple Account, iCloud and more" on iPhone
# and truncates to "Apple Account, iCloud" (sometimes with a separate
# "and more" row) on the iPad sidebar.
_ACCOUNT_MARKER_COMPACTS = ("appleaccounticloudandmore", "appleaccounticloud")
_DATE_MARKER_COMPACT = "dateadded"
_NETWORK_LIST_MARKERS = {"My Networks", "Other Networks"}
_NETWORK_CHROME = {"WLAN", "Wi-Fi", "WiFi", "Edit", "My Networks", "Other Networks", "Networks"}
_BLUETOOTH_SECTION_MARKERS = {"Devices", "My Devices", "Other Devices"}
_BLUETOOTH_CHROME = {
    "Bluetooth", "Devices", "My Devices", "Other Devices",
    "On", "Off", "Connected", "Not Connected", "Now Discoverable",
}
# Settings rows whose right-hand value is the *connected* network name.
_WIFI_ROW_LABELS = {"WLAN", "Wi-Fi", "WiFi", "无线局域网"}
# Status/nav words that legitimately render in the WLAN/Wi-Fi row's band:
# row-value states, neighbouring row labels, and the nav-bar back label that
# shares the title band with "WLAN" on sub-pages mid-transition.
_WIFI_ROW_VALUE_CHROME = _NETWORK_CHROME | _BLUETOOTH_CHROME | {
    "Airplane Mode", "Not Connected", "Settings", "设置", "Back",
}


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


def _is_account_name_candidate(text: str) -> bool:
    """Guard for the account-name rule: >= 2 chars and at least one letter (any
    script), so OCR chevron/symbol fragments ('>', '•', '①') are never
    collected — collecting '>' would substring-rewrite every disclosure
    chevron in the corpus."""
    stripped = text.strip()
    return len(stripped) >= 2 and any(ch.isalpha() for ch in stripped)


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


def _is_network_list_scene(scene: dict[str, Any]) -> bool:
    return any(t.strip() in _NETWORK_LIST_MARKERS for t in _texts(scene))


def _is_bluetooth_scene(scene: dict[str, Any]) -> bool:
    texts = [t.strip() for t in _texts(scene)]
    return "Bluetooth" in texts and any(t in _BLUETOOTH_SECTION_MARKERS for t in texts)


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
    # "Apple Account, iCloud"). Walk up past rows that fail the candidate
    # guard — OCR sometimes slips a disclosure chevron between the name and
    # the subtitle.
    for idx, text in enumerate(texts):
        if _compact(text) not in _ACCOUNT_MARKER_COMPACTS:
            continue
        cursor = idx
        while True:
            prev_idx = prev_nonempty(cursor)
            if prev_idx is None:
                break
            candidate = texts[prev_idx]
            if candidate.startswith(PLACEHOLDER_PREFIX):
                break
            if _is_account_name_candidate(candidate):
                findings.append(("account_name", prev_idx, candidate))
                break
            cursor = prev_idx
    # Date value following a "Date added:" label.
    for idx, text in enumerate(texts[:-1]):
        if _compact(text) == _DATE_MARKER_COMPACT:
            nxt = texts[idx + 1]
            if nxt.strip() and not nxt.startswith(PLACEHOLDER_PREFIX):
                findings.append(("date", idx + 1, nxt))
    # Game Center nickname: single-token line immediately above an e-mail
    # (or above an already-scrubbed e-mail placeholder).
    for idx, text in enumerate(texts[1:], start=1):
        emailish = bool(_EMAIL_RE.search(text)) or text.startswith(f"{PLACEHOLDER_PREFIX}EMAIL")
        if not emailish:
            continue
        prev_idx = prev_nonempty(idx)
        if prev_idx is None:
            continue
        prev = texts[prev_idx].strip()
        if " " not in prev and not prev.startswith(PLACEHOLDER_PREFIX):
            findings.append(("nickname", prev_idx, texts[prev_idx]))
    # Network names in a network-list scene (WLAN / Wi-Fi page).
    if _is_network_list_scene(scene):
        for idx, text in enumerate(texts):
            stripped = text.strip()
            if stripped in _NETWORK_CHROME or not _looks_like_name_row(text):
                continue
            findings.append(("ssid", idx, text))
    # Bluetooth device names: list rows after a Devices section marker.
    if _is_bluetooth_scene(scene):
        started = False
        for idx, text in enumerate(texts):
            stripped = text.strip()
            if stripped in _BLUETOOTH_SECTION_MARKERS:
                started = True
                continue
            if not started or stripped in _BLUETOOTH_CHROME:
                continue
            if _looks_like_name_row(text):
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
            if not _looks_like_name_row(text):
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
    # map stays keyed on the actual SSID.
    _TRAILING_DECORATION_RE = re.compile(r"[\s>›＞]+$")

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
