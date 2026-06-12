"""Floor + scrub assertions for the committed iOS Settings transition corpus.

Corpus: ``skills/golden/ios_settings_transitions`` (S1 of
docs/design/iphone_settings_transition.md; provenance + generator command in
its README). Two jobs:

- **floor** — the corpus stays non-empty, the candidate-tap group count stays
  pinned, and every group file loads with the schema replay relies on.
- **scrub** — every committed scene stays free of personal data. Assertions
  are shape-based (e-mail shape, long digit runs, SSID-ish tokens, structural
  detector) so no personal string is ever enumerated here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from skills.regression.extract_transition_corpus import (
    PLACEHOLDER_PREFIX,
    find_personal_texts,
)

CORPUS_DIR = Path(__file__).resolve().parents[2] / "skills" / "golden" / "ios_settings_transitions"
GROUP_PATHS = sorted(CORPUS_DIR.glob("grp_*.json"))
GROUP_COUNT = 22  # candidate tap groups in run_2026_06_12_06_04_38_737160

_EMAIL_SHAPE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Collapse digit-run separators, then any >=7-digit run is a phone-number shape.
_DIGIT_SEPARATORS = re.compile(r"[\s().+\-:/]")
_LONG_DIGIT_RUN = re.compile(r"\d{7,}")
# Underscore-joined tokens are router/IoT-SSID shaped; iOS UI chrome never is.
_SSID_SHAPE = re.compile(r"^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+$")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _scene_files() -> list[tuple[str, dict]]:
    scenes = [("root_scene", _load(CORPUS_DIR / "root_scene.json"))]
    scenes += [(path.stem, _load(path)["after_scene"]) for path in GROUP_PATHS]
    return scenes


def _all_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for child in value.values() for s in _all_strings(child)]
    if isinstance(value, list):
        return [s for child in value for s in _all_strings(child)]
    return []


@pytest.mark.smoke
def test_corpus_floor_non_empty_and_group_count_pinned():
    assert CORPUS_DIR.is_dir()
    assert (CORPUS_DIR / "root_scene.json").is_file()
    assert len(GROUP_PATHS) == GROUP_COUNT


@pytest.mark.smoke
@pytest.mark.parametrize("path", GROUP_PATHS, ids=lambda p: p.stem)
def test_corpus_group_loads_with_replay_schema(path: Path):
    group = _load(path)
    assert group["group_id"] == path.stem
    assert str(group["target"] or "").strip()
    expected = group["expected_state"]
    assert expected["kind"] == "page_id"
    any_of = expected["payload"]["any_of"]
    assert any_of and all(isinstance(item, str) and item for item in any_of)
    assert group["recorded_verdict"] in {"succeeded", "failed"}
    assert group["verified_via"] in {"page_id", "vlm_escalation", None}
    assert group["verified_live"] is (group["verified_via"] is not None)
    scene = group["after_scene"]
    assert "page_id" in scene
    assert scene["platform_scene_kind"]
    assert scene["elements"]
    for element in scene["elements"]:
        assert set(element) == {"text", "box", "type"}


@pytest.mark.smoke
def test_corpus_root_scene_is_settings_root():
    root = _load(CORPUS_DIR / "root_scene.json")
    assert root["platform_scene_kind"] == "settings_root"
    assert root["elements"]


@pytest.mark.smoke
def test_corpus_live_verdict_distribution_pinned():
    groups = [_load(path) for path in GROUP_PATHS]
    verdicts = sorted(group["recorded_verdict"] for group in groups)
    assert verdicts.count("succeeded") == 14
    assert verdicts.count("failed") == 8
    by_via = {via: 0 for via in ("page_id", "vlm_escalation", None)}
    for group in groups:
        by_via[group["verified_via"]] += 1
    # 16 candidates verified live = 10 via a direct page_id match + 6 only via
    # billed VLM escalation; 6 were rejected live (2 correctly, 4 falsely).
    assert by_via == {"page_id": 10, "vlm_escalation": 6, None: 6}


@pytest.mark.smoke
@pytest.mark.parametrize("name_scene", _scene_files(), ids=lambda item: item[0])
def test_corpus_scene_has_no_personal_data_shapes(name_scene):
    _name, scene = name_scene
    assert find_personal_texts(scene) == []
    for element in scene["elements"]:
        text = element.get("text") or ""
        assert not _EMAIL_SHAPE.search(text), "e-mail shape survived the scrub"
        collapsed = _DIGIT_SEPARATORS.sub("", text)
        assert not _LONG_DIGIT_RUN.search(collapsed), "long digit run survived the scrub"
        if not text.startswith(PLACEHOLDER_PREFIX):
            assert not _SSID_SHAPE.match(text.strip()), "SSID-shaped token survived the scrub"
            assert not text.strip().startswith("DIRECT-"), "Wi-Fi Direct SSID survived the scrub"


@pytest.mark.smoke
@pytest.mark.parametrize("path", GROUP_PATHS, ids=lambda p: p.stem)
def test_corpus_group_free_text_has_no_personal_data_shapes(path: Path):
    # Verdict reasons / notes are free text from the live run; they must be as
    # clean as the scenes themselves.
    group = _load(path)
    for text in _all_strings({"reason": group["recorded_reason"], "notes": group["notes"]}):
        assert not _EMAIL_SHAPE.search(text)
        assert not _LONG_DIGIT_RUN.search(_DIGIT_SEPARATORS.sub("", text))


@pytest.mark.smoke
def test_corpus_scrub_placeholders_prove_scrubber_ran():
    # Presence assertions: an accidentally-empty corpus or a no-op scrubber
    # must not pass the shape tests by vacuity.
    texts_by_scene = {name: [e.get("text") or "" for e in scene["elements"]]
                      for name, scene in _scene_files()}
    all_texts = [text for texts in texts_by_scene.values() for text in texts]
    root_texts = texts_by_scene["root_scene"]
    assert any(t.startswith(f"{PLACEHOLDER_PREFIX}ACCOUNT_NAME") for t in root_texts)
    ssids = {t for t in all_texts if t.startswith(f"{PLACEHOLDER_PREFIX}SSID_")}
    assert len(ssids) >= 5  # the WLAN after-scene lists the neighbourhood
    assert any(f"{PLACEHOLDER_PREFIX}PHONE_" in t for t in all_texts)
    assert any(t.startswith(f"{PLACEHOLDER_PREFIX}DATE_") for t in all_texts)
    assert any(t.startswith(f"{PLACEHOLDER_PREFIX}EMAIL_") for t in all_texts)
    assert any(t.startswith(f"{PLACEHOLDER_PREFIX}GC_NICKNAME_") for t in all_texts)
