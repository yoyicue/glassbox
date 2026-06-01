"""多帧 OCR 投票(D)—— vote_scenes。"""
from __future__ import annotations

import pytest

from glassbox.cognition import Box, Scene, UIElement
from glassbox.cognition.ocr_vote import vote_scenes
from glassbox.cognition.text_match import confusion_compact


def _el(text: str, x: int, y: int) -> UIElement:
    return UIElement(type="text", box=Box(x=x, y=y, w=90, h=20), text=text, confidence=0.9)


def _scene(*els: UIElement) -> Scene:
    return Scene(frame_id=0, timestamp=0.0, elements=list(els))


@pytest.mark.smoke
def test_vote_scenes_votes_text_per_matched_position():
    """同位置元素跨帧读数不同 → 多数票;位置就近匹配。"""
    s1 = _scene(_el("待机見示", 80, 300), _el("通用", 80, 360))
    s2 = _scene(_el("待机显示", 82, 301), _el("通用", 81, 359))
    s3 = _scene(_el("侍机昰示", 79, 302), _el("通用", 80, 361))

    voted = vote_scenes([s1, s2, s3], text_normalizer=confusion_compact)

    by_y = {round(e.box.center[1] / 10): e.text for e in voted.elements}
    assert by_y[round(310 / 10)] == "待机显示"   # 三帧混淆归一后一致
    assert by_y[round(370 / 10)] == "通用"


@pytest.mark.smoke
def test_vote_scenes_single_scene_passthrough():
    s1 = _scene(_el("通用", 80, 360))
    assert vote_scenes([s1]) is s1


@pytest.mark.smoke
def test_vote_scenes_default_preserves_generic_app_text():
    s1 = _scene(_el("Game Center", 80, 300), _el("消息", 80, 360))
    s2 = _scene(_el("Game Center", 81, 301), _el("消息", 81, 361))

    voted = vote_scenes([s1, s2])

    assert [e.text for e in voted.elements] == ["Game Center", "消息"]


@pytest.mark.smoke
def test_vote_scenes_normalized_majority_writes_back_representative_raw_text():
    s1 = _scene(_el("Game Center", 80, 300))
    s2 = _scene(_el("GameCenter", 81, 301))
    s3 = _scene(_el("Game Center", 80, 302))

    voted = vote_scenes([s1, s2, s3], text_normalizer=confusion_compact)

    assert voted.elements[0].text == "Game Center"
    assert "ocr_vote_text_status:whole_string_majority" in voted.elements[0].type_evidence


@pytest.mark.smoke
def test_vote_scenes_char_consensus_path_recovers_text():
    s1 = _scene(_el("Xbc", 80, 300))
    s2 = _scene(_el("aYc", 81, 301))
    s3 = _scene(_el("abZ", 80, 302))

    voted = vote_scenes([s1, s2, s3])

    assert voted.elements[0].text == "abc"
    assert "ocr_vote_text_status:char_consensus" in voted.elements[0].type_evidence


@pytest.mark.smoke
def test_vote_scenes_keeps_element_when_no_consensus_change():
    """投票结果与原文一致时保留原 element(不无谓替换)。"""
    s1 = _scene(_el("通用", 80, 360))
    s2 = _scene(_el("通用", 81, 361))
    voted = vote_scenes([s1, s2])
    assert voted.elements[0].text == "通用"


@pytest.mark.smoke
def test_vote_scenes_includes_element_missing_from_first_frame():
    s1 = _scene(_el("通用", 80, 360))
    s2 = _scene(_el("无线局域网", 80, 300), _el("通用", 81, 361))
    s3 = _scene(_el("无线局域网", 79, 302), _el("通用", 80, 361))

    voted = vote_scenes([s1, s2, s3])

    by_text = {e.text: e for e in voted.elements}
    assert "无线局域网" in by_text
    assert "ocr_vote_frames:3" in by_text["无线局域网"].type_evidence
    assert "ocr_vote_samples:2" in by_text["无线局域网"].type_evidence
    assert "ocr_vote_status:stable" in by_text["无线局域网"].type_evidence
    assert by_text["无线局域网"].confidence < 0.9


@pytest.mark.smoke
def test_vote_scenes_marks_transient_without_dropping_text():
    s1 = _scene(_el("通用", 80, 360))
    s2 = _scene(_el("弹窗", 80, 420), _el("通用", 81, 361))
    s3 = _scene(_el("通用", 80, 361))

    voted = vote_scenes([s1, s2, s3], min_presence=2)

    popup = next(element for element in voted.elements if element.text == "弹窗")
    assert "ocr_vote_status:transient" in popup.type_evidence
    assert "ocr_vote_samples:1" in popup.type_evidence


@pytest.mark.smoke
def test_vote_scenes_volatile_numeric_cluster_prefers_latest_not_frankenstein():
    s1 = _scene(_el("330", 80, 300))
    s2 = _scene(_el("33°", 81, 301))
    s3 = _scene(_el("34°", 80, 302))

    voted = vote_scenes([s1, s2, s3])

    assert voted.elements[0].text == "34°"
    assert "ocr_vote_status:volatile_latest" in voted.elements[0].type_evidence
    assert "ocr_vote_text_status:volatile_latest" in voted.elements[0].type_evidence
    assert voted.ocr_vote_metadata["stable_clusters"] == 0
    assert voted.ocr_vote_metadata["volatile_clusters"] == 1


@pytest.mark.smoke
def test_vote_scenes_does_not_claim_leading_cjk_noise_was_voted_fixed():
    s1 = _scene(_el("口 Notes", 80, 300))
    s2 = _scene(_el("日 Notes", 81, 301))
    s3 = _scene(_el("Notes", 80, 302))

    voted = vote_scenes([s1, s2, s3])

    assert voted.elements[0].text == "Notes"
    assert "ocr_vote_text_status:degraded_latest" in voted.elements[0].type_evidence


@pytest.mark.smoke
def test_vote_scenes_writes_metadata_on_explicit_scene_field():
    s1 = _scene(_el("待机見示", 80, 300))
    s2 = _scene(_el("待机显示", 81, 301))
    s3 = _scene(_el("侍机昰示", 80, 302))

    voted = vote_scenes([s1, s2, s3], text_normalizer=confusion_compact)

    assert voted.ocr_vote_metadata["enabled"] is True
    assert voted.ocr_vote_metadata["frames"] == 3
    assert voted.ocr_vote_metadata["stable_clusters"] == 1
