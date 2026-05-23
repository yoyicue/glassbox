"""Closed-set label priors for ordered UI lists."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def ordered_label_candidates(
    labels: Sequence[str],
    observed: Iterable[tuple[str, int]],
    target_y: int,
    *,
    exclude: Iterable[str] = (),
    max_candidates: int = 3,
) -> tuple[str, ...]:
    """Infer likely labels for an unknown row in an ordered list.

    `observed` contains already-recognized `(label, y)` rows from the same
    viewport. The result is a small closed set around the target row's expected
    position in `labels`, suitable for a local VLM choice prompt.
    """
    if max_candidates <= 0:
        return ()
    label_index = {label: idx for idx, label in enumerate(labels)}
    excluded = set(exclude)
    anchors = sorted(
        (y, label_index[label])
        for label, y in observed
        if label in label_index
    )
    if not anchors:
        return tuple(label for label in labels if label not in excluded)[:max_candidates]

    before = [idx for y, idx in anchors if y < target_y]
    after = [idx for y, idx in anchors if y > target_y]
    lo = max(before) + 1 if before else 0
    hi = min(after) if after else len(labels)
    window = [
        label for label in labels[lo:hi]
        if label not in excluded
    ]
    if window:
        return tuple(window[:max_candidates])

    nearest_y, nearest_idx = min(anchors, key=lambda item: abs(item[0] - target_y))
    direction = 1 if target_y >= nearest_y else -1
    candidates: list[str] = []
    idx = nearest_idx + direction
    while 0 <= idx < len(labels) and len(candidates) < max_candidates:
        label = labels[idx]
        if label not in excluded:
            candidates.append(label)
        idx += direction
    return tuple(candidates)
