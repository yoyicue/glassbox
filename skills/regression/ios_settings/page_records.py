"""Visit and candidate record helpers for iOS Settings crawler runs.

Owns conversion from observed scenes into report input records. It should not
drive the device; callers supply scenes and mutable result collections.
"""

from __future__ import annotations

from glassbox.cognition.label_prior import ordered_label_candidates
from glassbox.cognition.text_match import compact_text, confusion_compact
from glassbox.ios.progress import screen_signature
from skills.regression.ios_settings import context as settings_context
from skills.regression.ios_settings import graph_state as settings_graph_state
from skills.regression.ios_settings import reporting as settings_reporting
from skills.regression.ios_settings import scene_state as settings_scene_state
from skills.regression.ios_settings import vlm_rows
from skills.regression.ios_settings.policy import (
    DEFAULT_SETTINGS_POLICY,
    EXPECTED_ROOT_NAV_TEXT_ZH,
    ROOT_NAV_VISUAL_ORDER_ZH,
)

PageVisit = settings_reporting.PageVisit
BlockedPage = settings_reporting.BlockedPage
RejectedCandidate = settings_reporting.RejectedCandidate
NavigationFailure = settings_reporting.NavigationFailure

ViewportKey = tuple[tuple[str, ...], tuple[str, ...]]


def root_coverage(visits: list[PageVisit], *, phone=None) -> dict[str, list[str]]:
    base = DEFAULT_SETTINGS_POLICY.root_coverage(visits)
    graph_entered = settings_graph_state.root_entered_labels(phone)
    sidebar_absent = settings_context.sidebar_absent_root_labels(phone)
    sidebar_exhaustive = settings_context.root_sidebar_exhaustive(phone) if phone is not None else False
    if not graph_entered and not sidebar_absent and not sidebar_exhaustive:
        return base
    expected = list(base["expected"])
    visited = set(base["visited"]) | graph_entered
    out = {
        **base,
        "visited": [label for label in expected if label in visited],
        "missing": [label for label in expected if label not in visited],
        "entered_graph": [label for label in expected if label in graph_entered],
    }
    if sidebar_absent:
        out["sidebar_absent"] = [label for label in expected if label in sidebar_absent]
    if sidebar_exhaustive:
        out["sidebar_exhaustive"] = ["true"]
    return out


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
    phone=None,
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
        if (
            path == ("Settings",)
            and rejected.reason == "unknown_navigation_label"
            and _vlm_resolves_root_candidate(phone, scene, rejected.text)
        ):
            continue
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


def _vlm_resolves_root_candidate(phone, scene, text: str) -> bool:
    """Return True when VLM row OCR maps an unknown root candidate to a known root row.

    The report verifier treats unknown root candidates as policy gaps. Before
    surfacing one, give the perception stack a chance to re-read that exact row
    with the VLM. This keeps the policy strict while making the crawler smarter
    about unstable OCR on Settings root rows.
    """
    target = compact_text(text)
    target_confused = confusion_compact(text)
    for element in scene.elements:
        element_text = (element.text or "").strip()
        if (
            element_text != text
            and compact_text(element_text) != target
            and confusion_compact(element_text) != target_confused
        ):
            continue
        if _same_row_has_known_root_label(scene, element):
            return True
        if phone is None:
            return False
        priors = _root_row_label_priors(scene, element, visited=())
        return vlm_rows.recover_root_label(
            phone,
            element,
            force=True,
            candidate_labels=priors,
        ) is not None
    return False


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
    evidence_text: str | None = None,
) -> bool:
    texts = settings_scene_state.texts(scene)
    if evidence_text and evidence_text not in texts:
        texts = [*texts, evidence_text]
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
    settings_scene_state.annotate_root_row_intents(scene)
    visited = set(DEFAULT_SETTINGS_POLICY.root_coverage(visits)["visited"])
    rows: list[tuple[int, str, str]] = []
    for element in scene.elements:
        text = (element.text or "").strip()
        label = DEFAULT_SETTINGS_POLICY.visible_root_row_label(element)
        if label is None:
            priors = _root_row_label_priors(scene, element, visited=visited)
            if priors is not None:
                label = vlm_rows.recover_root_label(
                    phone,
                    element,
                    candidate_labels=priors,
                )
        if label is None or label in visited:
            continue
        rows.append((element.box.center[1], label, text))
    for _, label, _text in sorted(rows):
        if label in visited:
            continue
        path = ("Settings", label)
        key = (path, screen_signature([label]))
        if key in seen_sigs:
            continue
        seen_sigs.add(key)
        visits.append(PageVisit(path=path, title=label, texts=(label,)))
        print(f"[ios_settings] visit {len(visits)} depth=1 path={' > '.join(path)}", flush=True)
        visited.add(label)


def _root_row_label_priors(scene, element, *, visited) -> tuple[str, ...] | None:
    text = (element.text or "").strip()
    if not text:
        return None
    cx, cy = element.box.center
    if cx > 260 or cy < 70 or cy > 900:
        return None
    if DEFAULT_SETTINGS_POLICY.potential_navigation_row_text(element) is None:
        return None
    if DEFAULT_SETTINGS_POLICY.is_unsafe_navigation_text(
        text,
        allow_sensitive_root_labels=True,
    ):
        return None
    visited_set = set(visited)
    missing = tuple(label for label in EXPECTED_ROOT_NAV_TEXT_ZH if label not in visited_set)
    if 0 < len(missing) <= 2:
        return missing
    observed: list[tuple[str, int]] = []
    for other in scene.elements:
        if other is element:
            continue
        label = DEFAULT_SETTINGS_POLICY.visible_root_row_label(other)
        if label is None:
            other_text = (other.text or "").strip()
            ox, oy = other.box.center
            if other_text and ox <= 260 and 70 <= oy <= 900:
                label = DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(other_text)
        if label is not None:
            observed.append((label, other.box.center[1]))
    if not observed:
        return EXPECTED_ROOT_NAV_TEXT_ZH
    return ordered_label_candidates(
        ROOT_NAV_VISUAL_ORDER_ZH,
        observed,
        cy,
        exclude=visited,
        max_candidates=2,
    )


def _same_row_has_known_root_label(scene, element) -> bool:
    _, cy = element.box.center
    for other in scene.elements:
        if other is element:
            continue
        text = (other.text or "").strip()
        if not text:
            continue
        if abs(other.box.center[1] - cy) > 24:
            continue
        if other.box.center[0] <= element.box.center[0]:
            continue
        if DEFAULT_SETTINGS_POLICY.canonical_expected_root_label(text) is not None or any(
            DEFAULT_SETTINGS_POLICY.title_matches_navigation_label(text, label)
            for label in EXPECTED_ROOT_NAV_TEXT_ZH
        ):
            return True
    return False
