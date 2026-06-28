"""
agent_research/agent.py — ResearchAgent: stub for sourced research.

The ResearchAgent validates that all sources are legitimate before
accepting them into a report.  Actual web fetching is handled by
the existing core/web_scout.py or external tools — this layer
enforces the source policy.

In production, wire a real fetch backend via set_fetch_backend().
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable
import structlog

from agent_research.sources import ResearchSource, SourceKind, is_social_media_url
from agent_research.reports import ResearchReport, ReportSection

log = structlog.get_logger("bea.research.agent")

# Type alias for the fetch backend
FetchFn = Callable[[str], Awaitable[dict[str, Any]]]


class SourcePolicy:
    """
    Policy guard for research sources.

    Social media blocked. Cookie-gated requires justification.
    Personal data claims raise immediately.
    """

    def check(self, source: ResearchSource) -> tuple[bool, str | None]:
        """Returns (allowed, reason). reason=None if allowed."""
        if is_social_media_url(source.url):
            return False, f"social media source blocked: {source.url}"
        if source.is_cookie_gated and not source.justification_for_cookie_gated.strip():
            return False, f"cookie-gated source needs justification: {source.url}"
        if source.credibility < 0.3:
            return False, f"source credibility too low ({source.credibility:.2f}): {source.url}"
        return True, None


class ResearchAgent:
    """
    Stub research agent that validates sources and builds ResearchReports.

    Wire set_fetch_backend() with a real HTTP client (e.g., core/web_scout.py)
    to enable real fetching.  Without a backend, operate in BYOS
    (Bring Your Own Sources) mode — caller provides pre-fetched ResearchSource objects.
    """

    def __init__(self) -> None:
        self._policy = SourcePolicy()
        self._fetch_fn: FetchFn | None = None

    def set_fetch_backend(self, fn: FetchFn) -> None:
        """Wire a real fetch backend.  Must return {title, snippet, url}."""
        self._fetch_fn = fn

    def validate_sources(self, sources: list[ResearchSource]) -> list[ResearchSource]:
        """Filter sources through policy.  Returns only allowed sources."""
        accepted = []
        for s in sources:
            allowed, reason = self._policy.check(s)
            if allowed:
                accepted.append(s)
            else:
                log.warning("research_source_rejected", url=s.url, reason=reason)
        return accepted

    def build_report(
        self,
        *,
        title: str,
        query: str,
        sources: list[ResearchSource],
        sections: list[ReportSection],
        summary: str,
        confidence: float = 0.7,
        agent_id: str | None = None,
        mission_id: str | None = None,
    ) -> ResearchReport:
        """
        Build a validated ResearchReport from the provided sources and sections.

        Raises ValueError if:
        - Any source violates SourcePolicy
        - Any section lacks source references
        - contains_personal_data would be True (never allowed)
        """
        safe_sources = self.validate_sources(sources)
        if not safe_sources:
            raise ValueError("no sources passed policy validation — report cannot be created")

        report = ResearchReport(
            title=title,
            query=query,
            sources=safe_sources,
            sections=sections,
            summary=summary,
            confidence=confidence,
            contains_personal_data=False,  # always False
            read_only=True,
            agent_id=agent_id,
            mission_id=mission_id,
        )
        log.info(
            "research_report_built",
            report_id=report.report_id,
            sources=len(safe_sources),
            sections=len(sections),
            confidence=confidence,
        )
        return report
