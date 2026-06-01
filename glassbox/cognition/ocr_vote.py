"""Multi-frame OCR voting (D) — stabilize row text across repeated reads.

A scrolling list OCRs slightly differently every frame; the same row reads
`待机見示` in one frame and `待机显示` in the next. Reading a *stable* screen
several times and voting per row turns that frame-to-frame jitter into a
consensus instead of betting on whichever frame was sampled.

The module clusters whole-Scene OCR elements by box position, then decides each
cluster with whole-string majority, character consensus, or latest-sample
degradation.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.text_match import norm_text

TextNormalizer = Callable[[str | None], str]
_VOLATILE_TEXT_RE = re.compile(r"^[HLhl:：+\-\d.,°%]+$")


def _distance_to_cluster(cluster: dict, el: UIElement) -> float:
    cx, cy = el.box.center
    return abs(float(cluster["cx"]) - cx) + abs(float(cluster["cy"]) - cy)


def _dedupe_evidence(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _scene_presence(members: list[tuple[int, UIElement]]) -> int:
    return len({scene_index for scene_index, _ in members})


def _latest_member(members: list[tuple[int, UIElement]]) -> UIElement:
    return max(members, key=lambda item: item[0])[1]


def _looks_like_volatile_text(text: str | None) -> bool:
    value = norm_text(text).replace(" ", "")
    if not value or not any(ch.isdigit() for ch in value):
        return False
    if "°" in value or "%" in value or ":" in value or "：" in value:
        return True
    return bool(_VOLATILE_TEXT_RE.fullmatch(value))


def _volatile_cluster(readings: list[str]) -> bool:
    if not readings or not any(_looks_like_volatile_text(text) for text in readings):
        return False
    values = {norm_text(text) for text in readings if norm_text(text)}
    return len(values) > 1


def _char_consensus(
    readings: list[str],
    *,
    normalizer: TextNormalizer | None,
) -> tuple[str, bool]:
    normalize = normalizer or norm_text
    norms = [text for text in (normalize(reading) for reading in readings) if text]
    if not norms:
        return "", False
    same_len = _modal_length_values(norms)
    chars: list[str] = []
    ambiguous = False
    for index in range(len(same_len[0])):
        counts = Counter(text[index] for text in same_len)
        ranked = counts.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            ambiguous = True
        chars.append(ranked[0][0])
    return "".join(chars), ambiguous


def _decide_text(
    readings: list[str],
    *,
    normalizer: TextNormalizer | None,
) -> tuple[str, str]:
    normalize = normalizer or norm_text
    norms = [text for text in (normalize(reading) for reading in readings) if text]
    if not norms:
        return "", "empty"
    winner, votes = Counter(norms).most_common(1)[0]
    if votes > len(norms) / 2:
        return _best_raw_for_normalized(readings, winner, normalizer=normalizer), "whole_string_majority"
    consensus, ambiguous = _char_consensus(readings, normalizer=normalizer)
    if consensus and not ambiguous:
        return _best_raw_for_normalized(readings, consensus, normalizer=normalizer), "char_consensus"
    return "", "degraded_latest"


def _modal_length_values(values: list[str]) -> list[str]:
    modal_len = Counter(len(text) for text in values).most_common(1)[0][0]
    return [text for text in values if len(text) == modal_len]


def _best_raw_for_normalized(
    readings: list[str],
    normalized: str,
    *,
    normalizer: TextNormalizer | None,
) -> str:
    normalize = normalizer or norm_text
    if not normalized.isascii():
        return normalized
    matches = [reading for reading in readings if normalize(reading) == normalized]
    if matches:
        return Counter(matches).most_common(1)[0][0]
    return normalized


def vote_scenes(
    scenes: list[Scene],
    *,
    pos_tol: int = 20,
    min_presence: int = 2,
    text_normalizer: TextNormalizer | None = None,
) -> Scene:
    """Vote element texts across several Scenes of the *same* stable screen.

    Elements from all sampled scenes are clustered by position. Each cluster
    text is decided by whole-string majority first, then character consensus,
    then latest-sample degradation. Returns a copy of the first scene with
    voted texts, including elements that were missed in the first frame but
    recovered in later frames. Pass `text_normalizer` only for closed-set flows
    that need domain-specific OCR folding.

    Caller MUST ensure the screen did not scroll/navigate between the reads.
    """
    if not scenes:
        raise ValueError("vote_scenes: no scenes")
    base = scenes[0]
    valid_scenes = [s for s in scenes if s is not None]
    if len(valid_scenes) == 1:
        return base

    clusters: list[dict] = []
    for scene_index, scene in enumerate(valid_scenes):
        used_clusters: set[int] = set()
        for el in scene.elements:
            best_i: int | None = None
            best_d = 1e18
            for i, cluster in enumerate(clusters):
                if i in used_clusters:
                    continue
                if cluster["type"] != el.type:
                    continue
                d = _distance_to_cluster(cluster, el)
                if d <= pos_tol and d < best_d:
                    best_i, best_d = i, d
            if best_i is None:
                cx, cy = el.box.center
                clusters.append({
                    "type": el.type,
                    "elements": [(scene_index, el)],
                    "cx": float(cx),
                    "cy": float(cy),
                })
                used_clusters.add(len(clusters) - 1)
                continue
            cluster = clusters[best_i]
            cluster["elements"].append((scene_index, el))
            n = len(cluster["elements"])
            cx, cy = el.box.center
            cluster["cx"] = (cluster["cx"] * (n - 1) + cx) / n
            cluster["cy"] = (cluster["cy"] * (n - 1) + cy) / n
            used_clusters.add(best_i)

    voted: list[UIElement] = []
    stats = {
        "frames": len(valid_scenes),
        "clusters": len(clusters),
        "min_presence": max(1, int(min_presence)),
        "pos_tol": int(pos_tol),
        "stable_clusters": 0,
        "transient_clusters": 0,
        "volatile_clusters": 0,
        "degraded_clusters": 0,
    }
    for cluster in clusters:
        members = cluster["elements"]
        representative = next(
            (el for scene_index, el in members if scene_index == 0),
            members[0][1],
        )
        readings = [el.text or "" for _, el in members]
        presence = _scene_presence(members)
        region_status = "stable" if presence >= max(1, int(min_presence)) else "transient"
        stats[f"{region_status}_clusters"] += 1
        volatile = _volatile_cluster(readings)
        if volatile:
            stats[f"{region_status}_clusters"] -= 1
            representative = _latest_member(members)
            consensus = representative.text or ""
            text_status = "volatile_latest"
            region_status = "volatile_latest"
            stats["volatile_clusters"] += 1
        else:
            consensus, text_status = _decide_text(readings, normalizer=text_normalizer)
            if not consensus:
                representative = _latest_member(members)
                consensus = representative.text or ""
        if text_status == "degraded_latest":
            stats["degraded_clusters"] += 1
        confidence = representative.confidence
        if members:
            confidence = min(
                1.0,
                sum(el.confidence for _, el in members) / len(members)
                * (len(members) / len(valid_scenes)),
            )
        evidence = [
            *representative.type_evidence,
            f"ocr_vote_status:{region_status}",
            f"ocr_vote_text_status:{text_status}",
            f"ocr_vote_frames:{len(valid_scenes)}",
            f"ocr_vote_samples:{presence}",
        ]
        updates = {
            "confidence": confidence,
            "type_evidence": _dedupe_evidence(evidence),
        }
        if consensus:
            updates["text"] = consensus
        voted.append(representative.model_copy(update=updates))
    metadata = {
        **base.ocr_vote_metadata,
        **stats,
        "enabled": True,
    }
    return base.model_copy(update={"elements": voted, "ocr_vote_metadata": metadata})
