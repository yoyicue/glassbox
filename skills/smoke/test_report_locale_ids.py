from __future__ import annotations

import pytest

from skills.regression.ios_settings.reporting import computed_root_coverage
from skills.regression.ios_settings.sections import (
    EXPECTED_ROOT_SECTIONS,
    ZH_CANON_TO_SECTION,
    RootSection,
)


def _visit(*path: str, texts: tuple[str, ...] = ()):
    return {"path": list(path), "title": path[-1], "texts": list(texts or path)}


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
                                   (ZH_CANON_TO_SECTION[lbl] for lbl in cov["expected"])]
    # missing ids are the complement, all valid section tokens.
    assert RootSection.BLUETOOTH.value in cov["missing_ids"]
    assert set(cov["expected_ids"]) == {s.value for s in EXPECTED_ROOT_SECTIONS}


@pytest.mark.smoke
def test_coverage_ids_and_labels_stay_aligned():
    cov = computed_root_coverage([])
    # Every expected label maps 1:1 to its id, same order.
    assert len(cov["expected"]) == len(cov["expected_ids"]) == 17
    for label, id_value in zip(cov["expected"], cov["expected_ids"], strict=True):
        assert ZH_CANON_TO_SECTION[label].value == id_value
