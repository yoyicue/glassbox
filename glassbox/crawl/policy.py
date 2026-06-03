"""Generic crawl policy protocol for AI-facing traversal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from glassbox.ai import ObservationSummary


@dataclass(frozen=True)
class PageInfo:
    page_id: str | None
    title: str | None = None
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavigationCandidate:
    label: str
    action: str = "tap"
    confidence: float = 0.0
    reason: str | None = None
    page_id: str | None = None


@dataclass(frozen=True)
class CrawlState:
    steps: int = 0
    visited_pages: tuple[str, ...] = ()
    found: bool = False


class CrawlPolicy(Protocol):
    def classify(self, observation: ObservationSummary) -> PageInfo: ...
    def candidates(self, observation: ObservationSummary) -> list[NavigationCandidate]: ...
    def is_safe(self, candidate: NavigationCandidate, observation: ObservationSummary) -> bool: ...
    def should_stop(self, state: CrawlState) -> bool: ...
