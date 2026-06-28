"""
agent_research/reports.py — ResearchReport: structured, source-backed research output.

Every claim in the report must be backed by at least one ResearchSource.
Reports are READ-ONLY artifacts — they cannot trigger actions directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from agent_research.sources import ResearchSource


class ReportSection(BaseModel):
    """A section in a research report."""

    title: str = Field(min_length=3)
    content: str = Field(min_length=10, max_length=10_000)
    source_urls: list[str] = Field(default_factory=list)  # references into ResearchReport.sources

    @model_validator(mode="after")
    def section_needs_sources(self) -> "ReportSection":
        if not self.source_urls:
            raise ValueError(
                f"ReportSection '{self.title[:40]}' must reference at least one source URL"
            )
        return self


class ResearchReport(BaseModel):
    """
    Structured, source-backed research report.

    Constraints:
    - At least 1 source required
    - At least 1 section required
    - All section source_urls must be in the sources list
    - No personal/private data
    - read_only: True always
    """

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    title: str = Field(min_length=5, max_length=256)
    query: str = Field(min_length=5)
    sources: list[ResearchSource] = Field(min_length=1)
    sections: list[ReportSection] = Field(min_length=1)
    summary: str = Field(min_length=20, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    contains_personal_data: bool = False
    read_only: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str | None = None
    mission_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cross_references(self) -> "ResearchReport":
        if self.contains_personal_data:
            raise ValueError(
                "reports containing personal data are not allowed — "
                "strip PII before creating a ResearchReport"
            )
        known_urls = {s.url for s in self.sources}
        for section in self.sections:
            for url in section.source_urls:
                if url not in known_urls:
                    raise ValueError(
                        f"section '{section.title[:40]}' references unknown source URL: {url}"
                    )
        return self

    def to_markdown(self) -> str:
        """Render the report as Markdown (for PR comments, docs, etc.)."""
        lines = [
            f"# {self.title}",
            f"\n**Query:** {self.query}",
            f"**Confidence:** {self.confidence:.0%}",
            f"**Generated:** {self.created_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Summary",
            self.summary,
            "",
        ]
        for section in self.sections:
            lines.append(f"## {section.title}")
            lines.append(section.content)
            lines.append("\n**Sources:**")
            for url in section.source_urls:
                src = next((s for s in self.sources if s.url == url), None)
                if src:
                    lines.append(f"- [{src.title}]({url}) ({src.kind.value})")
                else:
                    lines.append(f"- {url}")
            lines.append("")
        lines.append("## All Sources")
        for i, s in enumerate(self.sources, 1):
            lines.append(f"{i}. **{s.title}** ({s.kind.value}) — {s.url}")
        return "\n".join(lines)
