"""Multi-frame OCR voting (D) — stabilise row text across repeated reads.

A scrolling list OCRs slightly differently every frame; the same row reads
`待机見示` in one frame and `待机显示` in the next. Reading a *stable* screen
several times and voting per row turns that frame-to-frame jitter into a
consensus instead of betting on whichever frame was sampled.

Pairs with text_match.vote_ocr_texts (per-row char voting); this module lifts
it to whole Scenes by matching elements across reads by box position.
"""
from __future__ import annotations

from collections.abc import Callable

from glassbox.cognition.base import Scene, UIElement
from glassbox.cognition.text_match import vote_ocr_texts

TextNormalizer = Callable[[str | None], str]


def _nearest(elements: list[UIElement], cx: float, cy: float) -> UIElement | None:
    best: UIElement | None = None
    best_d = 1e18
    for el in elements:
        ex, ey = el.box.center
        d = abs(ex - cx) + abs(ey - cy)
        if d < best_d:
            best, best_d = el, d
    return best


def _distance_to_cluster(cluster: dict, el: UIElement) -> float:
    cx, cy = el.box.center
    return abs(float(cluster["cx"]) - cx) + abs(float(cluster["cy"]) - cy)


def vote_scenes(
    scenes: list[Scene],
    *,
    pos_tol: int = 20,
    text_normalizer: TextNormalizer | None = None,
) -> Scene:
    """Vote element texts across several Scenes of the *same* stable screen.

    Elements from all sampled scenes are clustered by position. The group's
    text is decided by `vote_ocr_texts`. Returns a copy of the first scene with
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
    for cluster in clusters:
        members = cluster["elements"]
        representative = next(
            (el for scene_index, el in members if scene_index == 0),
            members[0][1],
        )
        readings = [el.text or "" for _, el in members]
        consensus = vote_ocr_texts(readings, normalizer=text_normalizer)
        confidence = representative.confidence
        if members:
            confidence = min(
                1.0,
                sum(el.confidence for _, el in members) / len(members)
                * (len(members) / len(valid_scenes)),
            )
        evidence = [
            *representative.type_evidence,
            f"ocr_vote_frames:{len(valid_scenes)}",
            f"ocr_vote_samples:{len(members)}",
        ]
        updates = {
            "confidence": confidence,
            "type_evidence": evidence,
        }
        if consensus:
            updates["text"] = consensus
        voted.append(representative.model_copy(update=updates))
    return base.model_copy(update={"elements": voted})
