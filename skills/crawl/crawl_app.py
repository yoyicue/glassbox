"""Generic cold-start app crawl — the cold-start chain as one runnable walkthrough.

This is the integration point ("串链") for the cold-start pieces, which until now
were only chained inside the A/B probe script:

    foreground app
      → clear interstitial gauntlet      (glassbox/ios/gauntlet.py)
      → perceive (settled, voted)         (this module + Phone)
      → cold-start VLM annotation         (glassbox/cognition/coldstart.py)
      → navigable candidates              (glassbox/cognition/candidates.py)
      → tap each, classify, recurse       (this module + glassbox/ios/crawl.py primitives)

Unlike the Settings regression — which carries Settings-specific page policy —
this crawl is app-agnostic: no expected-row list, no per-app allowlist.

Depth-N DFS. Return-to-a-screen uses path replay (re-foreground + re-tap the
label path) rather than a back-gesture stack: replay is deterministic and does
not depend on back-gesture unwinding, which the A/B phase showed to be fragile.
A screen's identity is its stable-text signature, so a screen reached by two
paths is explored once.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from glassbox.action.semantics import action_accepted
from glassbox.cognition.candidates import TapCandidate, annotation_tap_candidates
from glassbox.crawl_policies import GenericCrawlPolicyAdapter
from glassbox.ios.crawl import CrawlMetrics
from glassbox.ios.gauntlet import clear_cold_start_gauntlet
from glassbox.ios.progress import same_visible_page, screen_signature


def _texts(scene: Any) -> list[str]:
    return [(e.text or "").strip() for e in scene.elements if (e.text or "").strip()]


def _read(phone: Any, *, settle_s: float = 0.0, votes: int = 2) -> Any:
    """Settled, multi-frame-voted perceive — the crawl's noise-reduced read.

    A bare single-frame perceive on a real device is jittery: OCR text wobbles
    frame to frame, so the `same_visible_page` screen-change classification
    mis-fires. This settles (sleep) past a transition, invalidates the cache,
    then votes `votes` frames (perceive_voted, the D-layer primitive) so the
    text the crawl compares is stable.
    """
    if settle_s > 0:
        time.sleep(settle_s)
    invalidate = getattr(phone, "invalidate_perceive_cache", None)
    if callable(invalidate):
        invalidate()
    voted = getattr(phone, "perceive_voted", None)
    if callable(voted):
        return voted(votes)
    return phone.perceive()


@dataclass
class CrawlEntry:
    """One tapped candidate and what it did."""

    label: str
    source: str            # ocr | vlm_anchored | vlm_only
    outcome: str           # navigated | noop
    depth: int = 0         # depth of the screen the candidate was tapped from


@dataclass
class CrawlReport:
    """Outcome of one generic cold-start crawl."""

    status: str                                  # ok | gauntlet_blocked | gauntlet_stuck
    strategy: str                                # vlm | ocr | -
    gauntlet_steps: list = field(default_factory=list)
    metrics: CrawlMetrics = field(default_factory=CrawlMetrics)
    entries: list[CrawlEntry] = field(default_factory=list)

    @property
    def navigations(self) -> int:
        return sum(1 for e in self.entries if e.outcome == "navigated")


# iOS standard "back" is Cmd+[ — a deterministic keyboard shortcut. (This is
# also what phone.back_gesture sends now; this local helper keeps a bool return
# + getattr guard for crawl's optional-capability flow.)
_IOS_BACK_MOD = 0x08   # Command
_IOS_BACK_KEY = 0x2F   # [


def _keyboard_back(phone: Any) -> bool:
    """Press the iOS keyboard back shortcut (Cmd+[). False if unsupported."""
    key = getattr(phone, "key", None)
    if not callable(key):
        return False
    return action_accepted(key(_IOS_BACK_MOD, _IOS_BACK_KEY))


def _sig_key(texts: list[str]) -> tuple[str, ...]:
    """Stable-text signature — a screen's identity, tolerant of volatile rows."""
    return screen_signature(texts)


def _replay(phone: Any, path: list[str], *, settle_s: float) -> bool:
    """Tap a label path from the current (launch) screen. True if every hop landed."""
    for label in path:
        scene = _read(phone)
        hit = next((e for e in scene.elements if (e.text or "").strip() == label), None)
        if hit is None:
            return False
        if not action_accepted(phone.tap_xy(*hit.box.center)):
            return False
        time.sleep(settle_s)
    return True


def _goto(
    phone: Any,
    foreground: Callable[[], None],
    path: list[str],
    screen_texts: list[str],
    *,
    settle_s: float,
) -> bool:
    """Return to the screen identified by `path` — re-perceive, keyboard back
    (Cmd+[), else re-foreground + replay the path. Position is judged by
    stable-text overlap, not UTG node id (node identity drifts on volatile
    content)."""
    if same_visible_page(screen_texts, _texts(_read(phone))):
        return True
    if _keyboard_back(phone):                    # deterministic Cmd+[ — not edge swipe
        time.sleep(1.0)
        if same_visible_page(screen_texts, _texts(_read(phone))):
            return True
    foreground()
    time.sleep(2.0)
    clear_cold_start_gauntlet(phone)
    if path and not _replay(phone, path, settle_s=settle_s):
        return False
    return same_visible_page(screen_texts, _texts(_read(phone)))


def _candidate_from_policy_action(action: dict[str, Any]) -> TapCandidate | None:
    label = str(action.get("label") or action.get("text") or "").strip()
    if not label:
        return None
    center = action.get("center")
    if isinstance(center, list | tuple) and len(center) == 2:
        try:
            x, y = int(center[0]), int(center[1])
        except (TypeError, ValueError):
            return None
        return TapCandidate(
            label=label,
            center=(x, y),
            source=str(action.get("source") or "policy"),
            role=str(action.get("role") or action.get("action") or ""),
            page_id=_candidate_page_id(action),
        )
    box = action.get("box")
    if isinstance(box, list | tuple) and len(box) == 4:
        try:
            x1, y1, x2, y2 = (int(v) for v in box)
        except (TypeError, ValueError):
            return None
        return TapCandidate(
            label=label,
            center=((x1 + x2) // 2, (y1 + y2) // 2),
            source=str(action.get("source") or "policy"),
            role=str(action.get("role") or action.get("action") or ""),
            page_id=_candidate_page_id(action),
        )
    return None


def _candidate_page_id(action: dict[str, Any]) -> str | None:
    page_id = str(action.get("page_id") or "").strip()
    return page_id or None


def _policy_tap_candidates(policy: Any, scene: Any) -> list[TapCandidate]:
    out: list[TapCandidate] = []
    for action in policy.candidates(scene):
        if not isinstance(action, dict):
            continue
        if not policy.is_safe(action, scene):
            continue
        candidate = _candidate_from_policy_action(action)
        if candidate is not None:
            out.append(candidate)
    return out


def _policy_should_stop(policy: Any | None, scene: Any, entries: list[CrawlEntry]) -> bool:
    if policy is None:
        return False
    should_stop = getattr(policy, "should_stop", None)
    if not callable(should_stop):
        return False
    history = [
        {
            "label": entry.label,
            "source": entry.source,
            "outcome": entry.outcome,
            "depth": entry.depth,
        }
        for entry in entries
    ]
    return bool(should_stop(scene, history))


def _try_candidate_memory_navigation(phone: Any, candidate: TapCandidate) -> tuple[Any | None, bool]:
    page_id = str(candidate.page_id or "").strip()
    if not page_id:
        return None, False
    navigate = getattr(phone, "navigate_to_page", None)
    if not callable(navigate):
        return None, False
    try:
        result = navigate(page_id)
    except Exception:
        return None, True
    reached = (
        getattr(result, "reached", False) is True
        or getattr(result, "semantic_status", None) == "succeeded"
        or getattr(result, "ok", False) is True
    )
    return (result if reached else None), True


def crawl_app(
    phone: Any,
    *,
    foreground: Callable[[], None],
    annotator: Any | None = None,
    crawl_policy: Any | None = None,
    max_depth: int = 2,
    max_actions: int = 24,
    max_candidates: int = 12,
    tap_settle_s: float = 1.4,
) -> CrawlReport:
    """Run a generic cold-start crawl (depth-N DFS) of the foregrounded app.

    `foreground` (re)launches the app to its start screen. With `annotator` (a
    ColdStartAnnotator) the crawl explores the VLM `navigable` candidate set;
    otherwise the CrawlPolicy fills the candidate/decide slot. A screen is
    explored once (by stable-text signature); navigation stops at
    `max_depth` / `max_actions`.
    """
    foreground()
    gauntlet = clear_cold_start_gauntlet(phone)
    if gauntlet.status != "stable":
        return CrawlReport(status=f"gauntlet_{gauntlet.status}", strategy="-",
                           gauntlet_steps=gauntlet.handled)

    if annotator is None and crawl_policy is None:
        crawl_policy = GenericCrawlPolicyAdapter()
    strategy = "vlm" if annotator is not None else "policy"
    visited: set = set()
    reached: set = set()
    entries: list[CrawlEntry] = []
    budget = {"actions": max_actions}
    counts = {"actions": 0, "noop": 0}

    def _candidates(scene: Any) -> list:
        if annotator is not None:
            icon_frames = [phone.snapshot().img for _ in range(3)]
            key = "screen:" + "|".join(_sig_key(_texts(scene)))[:80]
            ann = annotator.annotate(key, scene, icon_frames[0], icon_frames=icon_frames)
            cands = annotation_tap_candidates(ann)
        else:
            cands = _policy_tap_candidates(crawl_policy, scene)
        seen: set[str] = set()
        out = []
        for c in cands:
            k = c.label.strip().casefold()
            if k and k not in seen:
                seen.add(k)
                out.append(c)
        return out[:max_candidates]

    def _explore(path: list[str], screen_texts: list[str], depth: int) -> None:
        sig = _sig_key(screen_texts)
        if sig in visited:
            return
        visited.add(sig)
        scene = _read(phone, settle_s=0.6)
        if _policy_should_stop(crawl_policy, scene, entries):
            return
        candidates = _candidates(scene)
        for cand in candidates:
            if budget["actions"] <= 0:
                return
            if not _goto(phone, foreground, path, screen_texts, settle_s=tap_settle_s):
                break
            result, memory_navigation_attempted = _try_candidate_memory_navigation(phone, cand)
            if result is None:
                if memory_navigation_attempted and not _goto(
                    phone,
                    foreground,
                    path,
                    screen_texts,
                    settle_s=tap_settle_s,
                ):
                    break
                result = phone.tap_xy(*cand.center)
            budget["actions"] -= 1
            counts["actions"] += 1
            if not action_accepted(result):
                counts["noop"] += 1
                entries.append(CrawlEntry(cand.label, cand.source, "rejected", depth))
                continue
            after = _texts(_read(phone, settle_s=tap_settle_s))
            if same_visible_page(screen_texts, after):
                counts["noop"] += 1
                entries.append(CrawlEntry(cand.label, cand.source, "noop", depth))
                continue
            reached.add(_sig_key(after))
            entries.append(CrawlEntry(cand.label, cand.source, "navigated", depth))
            if depth + 1 < max_depth and _sig_key(after) not in visited:
                _explore([*path, cand.label], after, depth + 1)

    start_texts = _texts(_read(phone, settle_s=0.8))
    _explore([], start_texts, 0)

    metrics = CrawlMetrics(
        pages_visited=len(reached) + 1,
        actions=counts["actions"],
        no_progress_actions=counts["noop"],
    )
    return CrawlReport(status="ok", strategy=strategy, gauntlet_steps=gauntlet.handled,
                       metrics=metrics, entries=entries)
