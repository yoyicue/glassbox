from __future__ import annotations

import pytest

from skills.regression.ios_settings.sections import (
    COVERAGE_ONLY,
    EXPECTED_ROOT_SECTIONS,
    ROOT_ONLY_UNSAFE_OVERRIDE,
    RootSection,
    root_section_for_canonical_label,
    root_section_ids_for_canonical_labels,
    section_vocab_for,
)

_VOCABS = {
    "zh-Hans": section_vocab_for("zh-Hans"),
    "zh-Hans-CN": section_vocab_for("zh-Hans", "CN"),
    "en-US": section_vocab_for("en", "US"),
    "en-CN": section_vocab_for("en", "CN"),
    "en-HK": section_vocab_for("en", "HK"),
}


@pytest.mark.smoke
def test_section_schema_is_complete_and_stable():
    assert len(EXPECTED_ROOT_SECTIONS) == 17
    assert len(set(EXPECTED_ROOT_SECTIONS)) == 17
    assert {RootSection.WALLET} == COVERAGE_ONLY
    assert {RootSection.FACE_ID_PASSCODE} == ROOT_ONLY_UNSAFE_OVERRIDE
    # id_token contract: enum value equals the name (stable ASCII wire token).
    for section in RootSection:
        assert section.value == section.name


@pytest.mark.smoke
@pytest.mark.parametrize("code", list(_VOCABS))
def test_every_section_has_label_and_search_query(code):
    vocab = _VOCABS[code]
    for section in EXPECTED_ROOT_SECTIONS:
        assert vocab.label(section)
        assert vocab.search_query(section)


@pytest.mark.smoke
@pytest.mark.parametrize("code", list(_VOCABS))
def test_no_alias_collision_within_vocab(code):
    vocab = _VOCABS[code]
    seen: dict[str, RootSection] = {}
    for section in EXPECTED_ROOT_SECTIONS:
        for term in vocab.all_terms(section):
            key = term.strip().casefold()
            assert key not in seen or seen[key] == section, (
                f"{code}: term {term!r} maps to both {seen.get(key)} and {section}"
            )
            seen[key] = section


@pytest.mark.smoke
@pytest.mark.parametrize("code", list(_VOCABS))
def test_vlm_candidates_round_trip(code):
    vocab = _VOCABS[code]
    tokens = [c.id_token for c in vocab.vlm_candidates()]
    assert len(tokens) == len(set(tokens)) == 17        # unique stable tokens
    for cand in vocab.vlm_candidates():
        assert cand.id_token == cand.id.value
        assert vocab.resolve(cand.label) == cand.id     # label round-trips
        for alias in cand.aliases:
            assert vocab.resolve(alias) == cand.id       # each alias round-trips


@pytest.mark.smoke
@pytest.mark.parametrize("code", list(_VOCABS))
def test_resolve_returns_typed_id_or_none(code):
    vocab = _VOCABS[code]
    assert vocab.resolve("definitely not a settings row") is None
    assert vocab.resolve("") is None
    got = vocab.resolve(vocab.label(RootSection.GENERAL))
    assert isinstance(got, RootSection) and got is RootSection.GENERAL


@pytest.mark.smoke
def test_zh_resolves_chinese_and_ocr_garble():
    zh = _VOCABS["zh-Hans"]
    assert zh.resolve("无线局域网") is RootSection.WIFI
    assert zh.resolve("通用") is RootSection.GENERAL
    # OCR garble inherited from the existing zh resolver:
    assert zh.resolve("待机見示") is RootSection.STANDBY


@pytest.mark.smoke
def test_canonical_label_projection_uses_shared_exit():
    labels = ["无线局域网", "通用", "not a section"]
    assert root_section_for_canonical_label("无线局域网") is RootSection.WIFI
    assert root_section_for_canonical_label("not a section") is None
    assert root_section_ids_for_canonical_labels(labels) == [
        RootSection.WIFI.value,
        RootSection.GENERAL.value,
    ]


@pytest.mark.smoke
def test_english_and_greater_china_region_overlay():
    en = _VOCABS["en-US"]
    assert en.resolve("General") is RootSection.GENERAL
    assert en.resolve("Wi-Fi") is RootSection.WIFI
    assert en.resolve("WLAN") is None                    # not a US-English label
    assert en.resolve("Mobile Service") is None          # not a US-English label
    # Greater-China English (CN + HK, live-observed) accepts WLAN / Mobile Service.
    for code in ("en-CN", "en-HK"):
        assert _VOCABS[code].resolve("WLAN") is RootSection.WIFI
        assert _VOCABS[code].resolve("Mobile Service") is RootSection.CELLULAR


@pytest.mark.smoke
def test_all_packs_expose_same_section_set():
    # Stable-id discipline: every pack covers the same RootSection set.
    for vocab in _VOCABS.values():
        covered = {c.id for c in vocab.vlm_candidates()}
        assert covered == set(EXPECTED_ROOT_SECTIONS)
