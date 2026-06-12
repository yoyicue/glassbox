"""Extract + scrub the committed iPhone Settings transition corpus (S1).

Design: docs/design/iphone_settings_transition.md (S1 — offline transition
replay corpus). Source of truth is a raw on-rig run ledger (actions.jsonl +
scenes/*.json); this generator selects the candidate-tap groups (the tap
attempts whose command carries a `page_id` expected_state and a row target),
keeps only what replay needs, and scrubs personal data **structurally** — the
personal strings themselves never appear in this file or in the tests.

Generator command (also embedded in the corpus README):

    uv run python -m skills.regression.extract_transition_corpus \
        --run artifacts/computer_use_success_rate/iphone_floor_runs/run_2026_06_12_06_04_38_737160 \
        --out skills/golden/ios_settings_transitions

Scrubbed classes (replaced with stable placeholders so replay still works):
  - Apple Account display name on the Settings root (SCRUBBED_ACCOUNT_NAME)
  - Wi-Fi/WLAN network names (SCRUBBED_SSID_n) — detected in network-list
    scenes, then substring-replaced everywhere (the root scene shows the
    connected SSID too)
  - Bluetooth device names (SCRUBBED_BT_DEVICE_n)
  - phone numbers / digit runs >= 7 (SCRUBBED_PHONE_n)
  - e-mail addresses (SCRUBBED_EMAIL_n)
  - Game Center nickname — the single-token line right above an e-mail
    (SCRUBBED_GC_NICKNAME_n)
  - account dates following a "Date added:" label (SCRUBBED_DATE_n)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

PLACEHOLDER_PREFIX = "SCRUBBED_"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Digit-ish span (optionally starting with "+") — personal iff it carries >= 7
# digits, so times ("6:23"), percentages and small counters survive untouched.
_PHONEISH_RE = re.compile(r"\+?\d[\d\s().\-]*\d")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_MIN_PHONE_DIGITS = 7

# Structural markers (generic iOS chrome, not personal values).
_ACCOUNT_MARKER_COMPACT = "appleaccounticloudandmore"
_DATE_MARKER_COMPACT = "dateadded"
_NETWORK_LIST_MARKERS = {"My Networks", "Other Networks"}
_NETWORK_CHROME = {"WLAN", "Wi-Fi", "WiFi", "Edit", "My Networks", "Other Networks", "Networks"}
_BLUETOOTH_SECTION_MARKERS = {"Devices", "My Devices", "Other Devices"}
_BLUETOOTH_CHROME = {
    "Bluetooth", "Devices", "My Devices", "Other Devices",
    "On", "Off", "Connected", "Not Connected", "Now Discoverable",
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


def _is_network_list_scene(scene: dict[str, Any]) -> bool:
    return any(t.strip() in _NETWORK_LIST_MARKERS for t in _texts(scene))


def _is_bluetooth_scene(scene: dict[str, Any]) -> bool:
    texts = [t.strip() for t in _texts(scene)]
    return "Bluetooth" in texts and any(t in _BLUETOOTH_SECTION_MARKERS for t in texts)


def find_personal_texts(scene: dict[str, Any]) -> list[tuple[str, int, str]]:
    """Structural personal-data detector: list of (kind, element_index, text).

    Shared with the smoke scrub test (which asserts it returns [] on every
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
    # and more" subtitle on the Settings root.
    for idx, text in enumerate(texts):
        if _compact(text) == _ACCOUNT_MARKER_COMPACT:
            prev_idx = prev_nonempty(idx)
            if prev_idx is not None and not texts[prev_idx].startswith(PLACEHOLDER_PREFIX):
                findings.append(("account_name", prev_idx, texts[prev_idx]))
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
    return findings


class _Scrubber:
    """Two-pass scrub: collect personal values across all scenes, then replace
    them (exact + substring, longest-first) everywhere — including free-text
    verdict reasons. Placeholders are stable per distinct value."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._counters: dict[str, int] = {}

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
        return label

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
                self._placeholder(kind, text.strip())

    def scrub_text(self, text: str | None) -> str | None:
        if not text:
            return text
        out = text
        for value in sorted(self._map, key=len, reverse=True):
            if value in out:
                out = out.replace(value, self._map[value])
        return out

    def scrub_scene(self, scene: dict[str, Any]) -> None:
        for element in scene.get("elements", []):
            element["text"] = self.scrub_text(element.get("text"))

    @property
    def replacement_count(self) -> int:
        return len(self._map)

    def counts(self) -> dict[str, int]:
        return dict(self._counters)


def _slim_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": scene.get("scene_id"),
        "page_id": scene.get("page_id"),
        "platform_scene_kind": scene.get("platform_scene_kind"),
        "elements": [
            {"text": e.get("text"), "box": e.get("box"), "type": e.get("type")}
            for e in scene.get("elements", [])
        ],
    }


def _load_scene(run_dir: Path, rel: str) -> dict[str, Any]:
    return json.loads((run_dir / rel).read_text())


def _candidate_and_wrapper_actions(
    actions: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Pair each candidate tap (page_id expected_state + row target) with its
    agent-actor wrapper attempts (same any_of payload, no target)."""

    def any_of_key(action: dict[str, Any]) -> tuple[str, ...] | None:
        expected = (action.get("command") or {}).get("expected_state") or {}
        if expected.get("kind") != "page_id":
            return None
        payload = expected.get("payload") or {}
        any_of = payload.get("any_of") or ([payload["page_id"]] if payload.get("page_id") else [])
        return tuple(str(item) for item in any_of)

    inner: dict[str, dict[str, Any]] = {}
    wrappers: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for action in actions:
        key = any_of_key(action)
        if key is None:
            continue
        if (action.get("command") or {}).get("target"):
            group_id = action["attempt_group_id"]
            if group_id in inner:
                raise ValueError(f"candidate group {group_id} has multiple tap attempts")
            inner[group_id] = action
        else:
            wrappers.setdefault(key, []).append(action)
    paired: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for group_id in sorted(inner):
        action = inner[group_id]
        paired.append((action, wrappers.get(any_of_key(action), [])))
    return paired


def _verified_via(inner: dict[str, Any], wrapper_attempts: list[dict[str, Any]]) -> str | None:
    """How the candidate verified live, with the inner tap taking precedence.

    The wrapper retries observe later/fresh frames, so their verdicts can
    diverge from the recorded after-scene; classification keys on the attempt
    whose after-scene the corpus actually commits.
    """
    verdicts = [inner.get("semantic") or {}] + [
        w.get("semantic") or {} for w in sorted(wrapper_attempts, key=lambda a: a["attempt_id"])
    ]
    for verdict in verdicts:
        if verdict.get("status") != "succeeded":
            continue
        if "after VLM escalation" in str(verdict.get("reason") or ""):
            return "vlm_escalation"
        return "page_id"
    return None


def extract(run_dir: Path, out_dir: Path) -> dict[str, Any]:
    actions = [
        json.loads(line)
        for line in (run_dir / "actions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    paired = _candidate_and_wrapper_actions(actions)
    if not paired:
        raise ValueError(f"no candidate tap groups found in {run_dir}")
    logger.info("found {} candidate tap groups", len(paired))

    # Root scene: the before_command scene of the first candidate tap.
    first_inner = min((inner for inner, _ in paired), key=lambda a: a["attempt_id"])
    root_scene_raw = _load_scene(run_dir, first_inner["before_command"]["scene"])
    if root_scene_raw.get("platform_scene_kind") != "settings_root":
        raise ValueError("first candidate tap does not start from the Settings root")

    root_scene = _slim_scene(root_scene_raw)
    groups: list[dict[str, Any]] = []
    for inner, wrapper_attempts in paired:
        command = inner["command"]
        semantic = inner.get("semantic") or {}
        after_scene = _slim_scene(_load_scene(run_dir, inner["after"]["scene"]))
        wrapper_ids = sorted({w["attempt_group_id"] for w in wrapper_attempts})
        if len(wrapper_ids) > 1:
            raise ValueError(f"group {inner['attempt_group_id']} pairs >1 wrapper: {wrapper_ids}")
        groups.append(
            {
                "schema": "ios_settings_transition_group.v1",
                "group_id": inner["attempt_group_id"],
                "wrapper_group_id": wrapper_ids[0] if wrapper_ids else None,
                "attempt_id": inner["attempt_id"],
                "target": command["target"],
                "expected_state": command["expected_state"],
                "recorded_verdict": semantic.get("status"),
                "recorded_reason": semantic.get("reason"),
                "verified_live": _verified_via(inner, wrapper_attempts) is not None,
                "verified_via": _verified_via(inner, wrapper_attempts),
                "after_scene": after_scene,
                "notes": {
                    "wrapper_attempts": [
                        {
                            "attempt_id": w["attempt_id"],
                            "status": (w.get("semantic") or {}).get("status"),
                            "reason": (w.get("semantic") or {}).get("reason"),
                        }
                        for w in sorted(wrapper_attempts, key=lambda a: a["attempt_id"])
                    ],
                },
            }
        )

    # Scrub: collect personal values across every scene first, then replace
    # everywhere (scenes + free-text verdict reasons).
    scrubber = _Scrubber()
    scrubber.collect(root_scene)
    for group in groups:
        scrubber.collect(group["after_scene"])
    scrubber.scrub_scene(root_scene)
    for group in groups:
        scrubber.scrub_scene(group["after_scene"])
        group["recorded_reason"] = scrubber.scrub_text(group["recorded_reason"])
        for attempt in group["notes"]["wrapper_attempts"]:
            attempt["reason"] = scrubber.scrub_text(attempt["reason"])

    # Hard post-condition: the detector must find nothing after scrubbing.
    for label, scene in [("root_scene", root_scene)] + [
        (g["group_id"], g["after_scene"]) for g in groups
    ]:
        leftovers = find_personal_texts(scene)
        if leftovers:
            raise ValueError(f"scrub left personal data in {label}: {leftovers}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "root_scene.json").write_text(
        json.dumps({"schema": "ios_settings_transition_root_scene.v1", **root_scene},
                   ensure_ascii=False, indent=1) + "\n"
    )
    for group in groups:
        (out_dir / f"{group['group_id']}.json").write_text(
            json.dumps(group, ensure_ascii=False, indent=1) + "\n"
        )
    summary = {
        "groups": len(groups),
        "scrub_replacements": scrubber.replacement_count,
        "scrub_counts": scrubber.counts(),
        "verified_via": {
            via: sum(1 for g in groups if g["verified_via"] == via)
            for via in ("page_id", "vlm_escalation", None)
        },
    }
    logger.info("corpus written to {}: {}", out_dir, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="raw run directory")
    parser.add_argument("--out", required=True, type=Path, help="corpus output directory")
    args = parser.parse_args()
    extract(args.run, args.out)


if __name__ == "__main__":
    main()
