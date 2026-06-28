"""
agent_research — Research Agent (GPT-Researcher / data-to-paper pattern).

Key constraints:
  - Sources are MANDATORY — no claim without a source
  - No social media, no cookie-based sources
  - No personal data (PII, medical, financial of individuals)
  - Reports are READ-ONLY artifacts, never auto-submitted

Public surface:
    from agent_research import ResearchSource, ResearchReport, ResearchAgent
"""
from __future__ import annotations

from agent_research.sources import ResearchSource, SourceKind
from agent_research.reports import ResearchReport, ReportSection
from agent_research.agent import ResearchAgent

__all__ = [
    "ResearchSource",
    "SourceKind",
    "ResearchReport",
    "ReportSection",
    "ResearchAgent",
]
