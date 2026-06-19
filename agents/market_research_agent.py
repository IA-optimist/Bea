"""
BEA MAX — Market Research Agent
=====================================
Studies a market from A to Z: TAM/SAM/SOM, competitors, personas, pricing.

Capabilities:
1. Analyze opportunity → structured market report
2. Competitor analysis → top 10 with features/pricing
3. Persona generation → ideal customer profiles
4. Pain point extraction → from forums, reviews, social
5. Market sizing → TAM/SAM/SOM estimates

Design: LLM-first with tool augmentation (web search when available).
All outputs are structured data, never raw text blobs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Competitor:
    """Analyzed competitor."""
    name: str
    url: str = ""
    category: str = ""
    pricing: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    market_share_est: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "url": self.url, "category": self.category,
            "pricing": self.pricing,
            "strengths": self.strengths[:5], "weaknesses": self.weaknesses[:5],
            "market_share": self.market_share_est,
        }


@dataclass
class Persona:
    """Customer persona."""
    name: str
    role: str = ""
    age_range: str = ""
    pain_points: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    budget: str = ""
    channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "role": self.role, "age_range": self.age_range,
            "pain_points": self.pain_points[:5], "goals": self.goals[:3],
            "budget": self.budget, "channels": self.channels[:5],
        }


@dataclass
class MarketSize:
    """Market sizing estimates."""
    tam: str = ""           # Total Addressable Market
    sam: str = ""           # Serviceable Addressable Market
    som: str = ""           # Serviceable Obtainable Market
    growth_rate: str = ""
    currency: str = "USD"

    def to_dict(self) -> dict[str, object]:
        return {
            "tam": self.tam, "sam": self.sam, "som": self.som,
            "growth_rate": self.growth_rate, "currency": self.currency,
        }


@dataclass
class MarketReport:
    """Complete market research output."""
    opportunity: str
    market_size: MarketSize = field(default_factory=MarketSize)
    competitors: list[Competitor] = field(default_factory=list)
    personas: list[Persona] = field(default_factory=list)
    pain_points: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    pricing_range: str = ""
    confidence: float = 0.0     # 0-1 confidence in analysis
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity": self.opportunity,
            "market_size": self.market_size.to_dict(),
            "competitors": [c.to_dict() for c in self.competitors[:10]],
            "personas": [p.to_dict() for p in self.personas[:5]],
            "pain_points": self.pain_points[:10],
            "opportunities": self.opportunities[:5],
            "risks": self.risks[:5],
            "pricing_range": self.pricing_range,
            "confidence": round(self.confidence, 2),
        }

    def summary(self) -> str:
        lines = [
            f"═══ Market Report: {self.opportunity} ═══",
            f"TAM: {self.market_size.tam} | SAM: {self.market_size.sam} | SOM: {self.market_size.som}",
            f"Growth: {self.market_size.growth_rate}",
            f"Competitors: {len(self.competitors)}",
            f"Personas: {len(self.personas)}",
            f"Top pain points: {', '.join(self.pain_points[:3])}",
            f"Pricing range: {self.pricing_range}",
            f"Confidence: {self.confidence:.0%}",
        ]
        return "\n".join(lines)


class MarketResearchAgent:
    """
    Analyzes a market opportunity end-to-end.
    Currently LLM-driven; can be augmented with tool calls (web search, APIs).
    """

    def analyze(self, opportunity: str, depth: str = "standard") -> MarketReport:
        """
        Analyze a market opportunity.
        depth: "quick" (5 min), "standard" (30 min), "deep" (2h+)
        Returns structured report ready for BusinessModelAgent.
        """
        report = MarketReport(opportunity=opportunity)

        # Phase 1: Market sizing (LLM estimation — tool-augmented when available)
        report.market_size = self._estimate_market_size(opportunity)

        # Phase 2: Competitor identification
        report.competitors = self._identify_competitors(opportunity)

        # Phase 3: Customer personas
        report.personas = self._generate_personas(opportunity)

        # Phase 4: Pain points
        report.pain_points = self._extract_pain_points(opportunity)

        # Phase 5: Opportunities & risks
        report.opportunities = self._identify_opportunities(opportunity, report)
        report.risks = self._identify_risks(opportunity, report)

        # Confidence based on depth
        report.confidence = {"quick": 0.3, "standard": 0.6, "deep": 0.8}.get(depth, 0.5)

        return report

    def _estimate_market_size(self, opp: str) -> MarketSize:
        """Estimate TAM/SAM/SOM. Stub — will be LLM + search augmented."""
        return MarketSize(
            tam="Requires LLM analysis",
            sam="Requires LLM analysis",
            som="Requires LLM analysis",
            growth_rate="Requires LLM analysis",
        )

    def _identify_competitors(self, opp: str) -> list[Competitor]:
        """Identify top competitors. Stub — will be search augmented."""
        return []

    def _generate_personas(self, opp: str) -> list[Persona]:
        """Generate customer personas. Stub — will be LLM generated."""
        return []

    def _extract_pain_points(self, opp: str) -> list[str]:
        """Extract pain points. Stub — will be search + forum analysis."""
        return []

    def _identify_opportunities(self, opp: str, report: MarketReport) -> list[str]:
        """Identify market opportunities based on gaps."""
        return []

    def _identify_risks(self, opp: str, report: MarketReport) -> list[str]:
        """Identify market risks."""
        return []
