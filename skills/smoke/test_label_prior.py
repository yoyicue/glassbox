from __future__ import annotations

from glassbox.cognition.label_prior import ordered_label_candidates


def test_ordered_label_candidates_rejects_non_positive_candidate_limit():
    labels = ("General", "Wi-Fi", "Bluetooth")

    assert ordered_label_candidates(labels, [], 0, max_candidates=0) == ()
    assert ordered_label_candidates(labels, [], 0, max_candidates=-1) == ()

