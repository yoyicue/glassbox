"""Tolerant Scene comparison for Tier-B perception replay.

``compare_scenes(recorded, replayed, tol)`` asserts a replayed
``Perceptor.perceive()`` reconstruction matches the recorded ``Scene`` within
``SceneTolerance``. Hard gates (page_id, raw scene_type) catch
classifier/verifier-relevant drift; tolerant gates (text jaccard, element
count, box IoU) absorb OCR nondeterminism without letting real perception
regressions through. Design: ``docs/design/log_sim_replay_regression.md`` §5.

Notes pinned at implementation time:
- ``scene_type`` is compared RAW (``Scene.scene_type``), not via
  ``compute_scene_diff``'s coalesced ``semantic_scene_type or scene_type`` —
  a recording captured with VLM annotation would otherwise hard-fail an
  OCR-only replay for a non-perception reason.
- Box IoU is computed from ``Scene.elements`` directly (``SceneDiff`` carries
  no boxes), pairing elements greedily by exact text match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from glassbox.verification.diff import compute_scene_diff


@dataclass
class SceneTolerance:
    """Tolerances for recorded-vs-replayed Scene comparison.

    Defaults were tuned against the committed ``skills/golden/recordings``
    corpus (B.0 characterization, see the smoke test's module docstring) —
    re-tune if the corpus changes materially.
    """

    page_id_must_match: bool = True       # verifier-relevant → hard gate
    scene_type_must_match: bool = True    # raw Scene.scene_type → hard gate
    text_jaccard_min: float = 0.85        # set similarity over element texts
    element_count_delta_max: int = 2
    box_iou_min: float = 0.6              # per matched-text element
    box_iou_check: bool = True


@dataclass
class SceneMatchReport:
    ok: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def explain(self) -> str:
        lines = [f"scene match: {'OK' if self.ok else 'FAILED'}"]
        lines += [f"  FAIL: {f}" for f in self.failures]
        lines += [f"  {k} = {v}" for k, v in self.metrics.items()]
        return "\n".join(lines)


def _box_iou(a, b) -> float:
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx2, by2 = b.x + b.w, b.y + b.h
    ix = max(0, min(ax2, bx2) - max(a.x, b.x))
    iy = max(0, min(ay2, by2) - max(a.y, b.y))
    inter = ix * iy
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def _matched_text_ious(recorded, replayed) -> list[tuple[str, float]]:
    """Greedy best-IoU pairing of elements that share an exact (stripped)
    text on both sides. Only matched texts are IoU-checked: texts that OCR
    jitter dropped/garbled are already covered by the jaccard gate."""
    by_text_rec: dict[str, list] = {}
    for el in recorded.elements:
        text = (el.text or "").strip()
        if text:
            by_text_rec.setdefault(text, []).append(el)
    ious: list[tuple[str, float]] = []
    used: set[tuple[str, int]] = set()
    for el in replayed.elements:
        text = (el.text or "").strip()
        candidates = by_text_rec.get(text)
        if not candidates:
            continue
        best_iou, best_idx = -1.0, None
        for idx, rec_el in enumerate(candidates):
            if (text, idx) in used:
                continue
            iou = _box_iou(rec_el.box, el.box)
            if iou > best_iou:
                best_iou, best_idx = iou, idx
        if best_idx is not None:
            used.add((text, best_idx))
            ious.append((text, best_iou))
    return ious


def compare_scenes(recorded, replayed, tol: SceneTolerance) -> SceneMatchReport:
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    diff = compute_scene_diff(recorded, replayed)
    if diff is None:
        return SceneMatchReport(ok=False, failures=["one of the scenes is None"])

    # —— hard gates ────────────────────────────────────────────────
    if tol.page_id_must_match and diff.page_id_before != diff.page_id_after:
        failures.append(
            f"page_id mismatch: recorded={diff.page_id_before!r} replayed={diff.page_id_after!r}"
        )
    metrics["page_id"] = f"{diff.page_id_before!r} -> {diff.page_id_after!r}"

    raw_rec_type = getattr(recorded, "scene_type", None)
    raw_rep_type = getattr(replayed, "scene_type", None)
    if tol.scene_type_must_match and raw_rec_type != raw_rep_type:
        failures.append(
            f"scene_type mismatch: recorded={raw_rec_type!r} replayed={raw_rep_type!r}"
        )
    metrics["scene_type"] = f"{raw_rec_type!r} -> {raw_rep_type!r}"

    # —— tolerant gates ────────────────────────────────────────────
    common = len(diff.texts_common)
    total = common + len(diff.texts_added) + len(diff.texts_removed)
    jaccard = common / total if total else 1.0
    metrics["text_jaccard"] = round(jaccard, 4)
    if jaccard < tol.text_jaccard_min:
        failures.append(
            f"text jaccard {jaccard:.3f} < {tol.text_jaccard_min}"
            f" (added={sorted(diff.texts_added)[:5]} removed={sorted(diff.texts_removed)[:5]})"
        )

    metrics["element_count_delta"] = diff.element_count_delta
    if abs(diff.element_count_delta) > tol.element_count_delta_max:
        failures.append(
            f"element count delta {diff.element_count_delta} exceeds ±{tol.element_count_delta_max}"
        )

    if tol.box_iou_check:
        ious = _matched_text_ious(recorded, replayed)
        if ious:
            worst_text, worst_iou = min(ious, key=lambda t: t[1])
            metrics["box_iou_min_observed"] = round(worst_iou, 4)
            metrics["box_iou_pairs"] = len(ious)
            if worst_iou < tol.box_iou_min:
                failures.append(
                    f"box IoU {worst_iou:.3f} < {tol.box_iou_min} for matched text {worst_text!r}"
                )

    return SceneMatchReport(ok=not failures, failures=failures, metrics=metrics)
