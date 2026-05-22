"""Visit and candidate record helpers for iOS Settings crawler runs.

Owns conversion from observed scenes into report input records. It should not
drive the device; callers supply scenes and mutable result collections.
"""

from __future__ import annotations

from glassbox.ios.progress import screen_signature
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings import vlm_rows
from skills.regression.ios_settings.policy import DEFAULT_SETTINGS_POLICY

PageVisit = settings_reporting.PageVisit
BlockedPage = settings_reporting.BlockedPage
RejectedCandidate = settings_reporting.RejectedCandidate
NavigationFailure = settings_reporting.NavigationFailure

ViewportKey = tuple[tuple[str, ...], tuple[str, ...]]


def root_coverage(visits: list[PageVisit]) -> dict[str, list[str]]:
    return DEFAULT_SETTINGS_POLICY.root_coverage(visits)


def record_blocked_page(
    blocked_pages: list[BlockedPage],
    *,
    path: tuple[str, ...],
    scene,
    reason: str,
) -> None:
    if any(blocked.path == path and blocked.reason == reason for blocked in blocked_pages):
        return
    blocked_pages.append(BlockedPage(
        path=path,
        title=settings_scene_state.page_title(scene),
        reason=reason,
        texts=tuple(settings_scene_state.texts(scene)[:40]),
    ))


def record_rejected_candidates(
    rejected_candidates: list[RejectedCandidate],
    *,
    path: tuple[str, ...],
    scene,
    allow_sensitive_root_labels: bool,
    allow_known_without_affordance: bool,
) -> None:
    if settings_scene_state.blocks_child_navigation(scene):
        return
    title = settings_scene_state.page_title(scene)
    existing = {
        (candidate.path, candidate.text, candidate.reason)
        for candidate in rejected_candidates
    }
    for rejected in DEFAULT_SETTINGS_POLICY.rejected_candidate_rows(
        scene,
        allow_sensitive_root_labels=allow_sensitive_root_labels,
        allow_known_without_affordance=allow_known_without_affordance,
    ):
        key = (path, rejected.text, rejected.reason)
        if key in existing:
            continue
        rejected_candidates.append(RejectedCandidate(
            path=path,
            title=title,
            text=rejected.text,
            reason=rejected.reason,
        ))
        existing.add(key)


def record_navigation_failure(
    navigation_failures: list[NavigationFailure],
    *,
    path: tuple[str, ...],
    scene,
    text: str,
    reason: str,
) -> None:
    key = (path, text, reason)
    if any((failure.path, failure.text, failure.reason) == key for failure in navigation_failures):
        return
    navigation_failures.append(NavigationFailure(
        path=path,
        title=settings_scene_state.page_title(scene),
        text=text,
        reason=reason,
    ))


def record_visible_page(
    *,
    scene,
    path: tuple[str, ...],
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    depth: int,
    title_override: str | None = None,
) -> bool:
    texts = settings_scene_state.texts(scene)
    sig = screen_signature(texts)
    key = (path, sig)
    if key in seen_sigs:
        return False
    seen_sigs.add(key)
    visits.append(PageVisit(
        path=path,
        title=title_override or settings_scene_state.page_title(scene),
        texts=tuple(texts[:40]),
    ))
    print(f"[ios_settings] visit {len(visits)} depth={depth} path={' > '.join(path)}", flush=True)
    return True


def record_visible_root_row_visits(
    *,
    scene,
    visits: list[PageVisit],
    seen_sigs: set[ViewportKey],
    phone=None,
) -> None:
    if not settings_scene_state.scene_is_settings_root(scene):
        return
    visited = set(root_coverage(visits)["visited"])
    rows: list[tuple[int, str, str]] = []
    for element in scene.elements:
        text = (element.text or "").strip()
        label = DEFAULT_SETTINGS_POLICY.visible_root_row_label(element)
        if label is None:
            label = vlm_rows.recover_root_label(phone, element)
        if label is None or label in visited:
            continue
        rows.append((element.box.center[1], label, text))
    for _, label, text in sorted(rows):
        if label in visited:
            continue
        if record_visible_page(
            scene=scene,
            path=("Settings", label),
            visits=visits,
            seen_sigs=seen_sigs,
            depth=1,
            title_override=text,
        ):
            visited.add(label)
