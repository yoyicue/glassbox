from __future__ import annotations

import pytest

from glassbox.config import get_config
from skills.regression.ios_settings.policy import EXPECTED_ROOT_NAV_TEXT_ZH
from skills.regression.ios_settings.reporting import (
    classify_root_coverage,
    computed_root_coverage,
)
from skills.regression.ios_settings.sections import (
    EXPECTED_ROOT_SECTIONS,
    RootSection,
    root_section_for_canonical_label,
)


def _visit(*path: str, texts: tuple[str, ...] = ()):
    return {"path": list(path), "title": path[-1], "texts": list(texts or path)}


@pytest.fixture
def _locale(monkeypatch):
    def _set(language: str | None, region: str | None):
        for key, value in (("GLASSBOX_LANGUAGE", language), ("GLASSBOX_REGION", region)):
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        get_config.cache_clear()

    yield _set
    monkeypatch.delenv("GLASSBOX_LANGUAGE", raising=False)
    monkeypatch.delenv("GLASSBOX_REGION", raising=False)
    get_config.cache_clear()


@pytest.mark.smoke
def test_coverage_carries_stable_section_ids_alongside_labels():
    visits = [
        _visit("Settings"),
        _visit("Settings", "无线局域网", texts=("无线局域网",)),
        _visit("Settings", "通用", texts=("通用",)),
    ]
    cov = computed_root_coverage(visits)
    # v0.1 labels unchanged (primary).
    assert "无线局域网" in cov["visited"] and "通用" in cov["visited"]
    # v0.2 additive ids: language-neutral, derived from the same labels.
    assert set(cov["visited_ids"]) == {RootSection.WIFI.value, RootSection.GENERAL.value}
    assert cov["expected_ids"] == [s.value for s in
                                   (root_section_for_canonical_label(lbl) for lbl in cov["expected"])]
    # missing ids are the complement, all valid section tokens.
    assert RootSection.BLUETOOTH.value in cov["missing_ids"]
    assert set(cov["expected_ids"]) == {s.value for s in EXPECTED_ROOT_SECTIONS}


@pytest.mark.smoke
def test_coverage_ids_and_labels_stay_aligned():
    cov = computed_root_coverage([])
    # Every expected label maps 1:1 to its id, same order.
    assert len(cov["expected"]) == len(cov["expected_ids"]) == 17
    for label, id_value in zip(cov["expected"], cov["expected_ids"], strict=True):
        section = root_section_for_canonical_label(label)
        assert section is not None and section.value == id_value


def _base_with_wifi_entered():
    return (
        {
            "expected": list(EXPECTED_ROOT_NAV_TEXT_ZH),
            "visited": ["无线局域网"],
            "missing": [s for s in EXPECTED_ROOT_NAV_TEXT_ZH if s != "无线局域网"],
        },
        [_visit("Settings", "无线局域网", texts=("无线局域网", "WLAN", "Ask to Join Networks"))],
    )


@pytest.mark.smoke
def test_classify_renders_active_locale_display_en_hk(_locale):
    """The live report path (classify_root_coverage) renders coverage in the run's
    own language: an en-HK run reads "WLAN" / "Mobile Service", not Chinese —
    while the zh labels + neutral ids stay primary."""
    _locale("en", "HK")
    base, visits = _base_with_wifi_entered()
    cov = classify_root_coverage(base, visits, [])
    # zh labels stay primary (internal pivot unchanged).
    assert cov["entered"] == ["无线局域网"]
    # neutral ids are wired into the live path (were previously absent).
    assert cov["entered_ids"] == [RootSection.WIFI.value]
    assert RootSection.CELLULAR.value in cov["missing_ids"]
    # display is the greater-China English the device actually shows.
    assert cov["entered_display"] == ["WLAN"]
    assert "Mobile Service" in cov["missing_display"]


@pytest.mark.smoke
def test_classify_display_is_chinese_under_zh(_locale):
    _locale("zh-Hans", None)
    base, visits = _base_with_wifi_entered()
    cov = classify_root_coverage(base, visits, [])
    assert cov["entered_display"] == ["无线局域网"]
    assert cov["entered_ids"] == [RootSection.WIFI.value]
