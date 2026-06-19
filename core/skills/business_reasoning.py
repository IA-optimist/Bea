"""
core/skills/business_reasoning.py — Business opportunity detection & structuring.

NOT a new agent or orchestrator. A skill module that provides structured
business reasoning for MetaOrchestrator missions classified as "creation"
or "analysis" with business intent.

Capabilities:
- Opportunity detection from problem patterns
- Offer structuring
- Feasibility scoring
- Landing page structure generation
- Acquisition strategy generation
- BE/EU compliance awareness checks
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger("skills.business")


# ── Compliance: domains to avoid ────────────────────────────────────────

_HIGH_RISK_DOMAINS = frozenset({
    "financial advisory", "investment advice", "medical advice",
    "legal advice", "gambling", "regulated substances", "weapons",
    "insurance brokering", "credit scoring", "debt collection",
    "pharmaceutical", "crypto trading advice",
})

_GDPR_TRIGGERS = frozenset({
    "email", "contact", "newsletter", "signup", "registration",
    "user data", "personal data", "tracking", "analytics",
    "customer list", "lead", "prospect",
})


# ── Data structures ─────────────────────────────────────────────────────

class OpportunityType(str, Enum):
    AUTOMATION_SERVICE = "automation_service"
    CONTENT_SERVICE = "content_service"
    ANALYSIS_SERVICE = "analysis_service"
    MICRO_SAAS = "micro_saas"
    PRODUCTIZED_SERVICE = "productized_service"
    DOCUMENT_GENERATION = "document_generation"


@dataclass
class FeasibilityScore:
    complexity: float = 0.5        # 0=trivial, 1=very complex
    estimated_demand: float = 0.5  # 0=no demand, 1=high demand
    competition: float = 0.5       # 0=no competition, 1=saturated
    implementation_effort: float = 0.5  # 0=trivial, 1=months
    time_to_first_result: float = 0.5   # 0=days, 1=months
    legal_simplicity: float = 0.5  # 0=simple, 1=heavily regulated
    required_cost: float = 0.5     # 0=free, 1=expensive

    @property
    def score(self) -> float:
        """
        Overall feasibility: higher = more feasible.
        Inverts negative factors (complexity, competition, etc.)
        """
        return round(
            (1 - self.complexity) * 0.2
            + self.estimated_demand * 0.25
            + (1 - self.competition) * 0.1
            + (1 - self.implementation_effort) * 0.15
            + (1 - self.time_to_first_result) * 0.1
            + (1 - self.legal_simplicity) * 0.1
            + (1 - self.required_cost) * 0.1,
            3,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "complexity": self.complexity,
            "estimated_demand": self.estimated_demand,
            "competition": self.competition,
            "implementation_effort": self.implementation_effort,
            "time_to_first_result": self.time_to_first_result,
            "legal_simplicity": self.legal_simplicity,
            "required_cost": self.required_cost,
            "overall_score": self.score,
        }


@dataclass
class BusinessOpportunity:
    """Structured business opportunity output."""
    summary: str = ""
    target_customer: str = ""
    problem: str = ""
    solution: str = ""
    value_proposition: str = ""
    opportunity_type: OpportunityType = OpportunityType.PRODUCTIZED_SERVICE
    delivery_format: str = ""
    pricing_model: str = ""
    acquisition_idea: str = ""
    compliance_notes: list[str] = field(default_factory=list)
    feasibility: FeasibilityScore = field(default_factory=FeasibilityScore)
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "target_customer": self.target_customer,
            "problem": self.problem,
            "solution": self.solution,
            "value_proposition": self.value_proposition,
            "type": self.opportunity_type.value,
            "delivery_format": self.delivery_format,
            "pricing_model": self.pricing_model,
            "acquisition_idea": self.acquisition_idea,
            "compliance_notes": self.compliance_notes,
            "feasibility": self.feasibility.to_dict(),
            "next_steps": self.next_steps,
        }

    def to_markdown(self) -> str:
        lines = [
            f"## {self.summary}",
            f"**Type**: {self.opportunity_type.value}",
            f"**Target**: {self.target_customer}",
            f"**Problem**: {self.problem}",
            f"**Solution**: {self.solution}",
            f"**Value**: {self.value_proposition}",
            f"**Delivery**: {self.delivery_format}",
            f"**Pricing**: {self.pricing_model}",
            f"**Acquisition**: {self.acquisition_idea}",
            f"**Feasibility**: {self.feasibility.score}/1.0",
        ]
        if self.compliance_notes:
            lines.append("**Compliance**:")
            for note in self.compliance_notes:
                lines.append(f"  - {note}")
        if self.next_steps:
            lines.append("**Next steps**:")
            for step in self.next_steps:
                lines.append(f"  1. {step}")
        return "\n".join(lines)


@dataclass
class LandingPageStructure:
    headline: str = ""
    problem_statement: str = ""
    solution_explanation: str = ""
    key_benefits: list[str] = field(default_factory=list)
    process_steps: list[str] = field(default_factory=list)
    trust_elements: list[str] = field(default_factory=list)
    call_to_action: str = ""
    contact_method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "problem_statement": self.problem_statement,
            "solution_explanation": self.solution_explanation,
            "key_benefits": self.key_benefits,
            "process_steps": self.process_steps,
            "trust_elements": self.trust_elements,
            "call_to_action": self.call_to_action,
            "contact_method": self.contact_method,
        }


# ── Compliance checks ───────────────────────────────────────────────────

def check_compliance(opportunity: BusinessOpportunity) -> list[str]:
    """
    Basic BE/EU compliance awareness. NOT legal advice.
    Returns list of compliance notes to include.
    """
    notes: list[str] = []
    text = f"{opportunity.summary} {opportunity.solution} {opportunity.delivery_format}".lower()

    # High-risk domain check
    for domain in _HIGH_RISK_DOMAINS:
        if domain in text:
            notes.append(f"CAUTION: '{domain}' is a regulated domain — seek legal counsel")

    # GDPR triggers
    for trigger in _GDPR_TRIGGERS:
        if trigger in text:
            notes.append("GDPR: Include privacy notice, purpose limitation, minimal data collection")
            notes.append("GDPR: Provide clear opt-out mechanism")
            break

    # Always include
    notes.append("Identify service provider clearly (name, address, VAT if applicable)")
    notes.append("No false guarantees or misleading claims")
    notes.append("Clear service description and terms")

    return notes


# ── Feasibility estimation ──────────────────────────────────────────────

def estimate_feasibility(
    opportunity_type: OpportunityType,
    description: str = "",
) -> FeasibilityScore:
    """
    Heuristic feasibility estimation by opportunity type.
    """
    fs = FeasibilityScore()
    desc = description.lower()

    # Type-based defaults
    if opportunity_type == OpportunityType.AUTOMATION_SERVICE:
        fs.complexity = 0.3
        fs.estimated_demand = 0.7
        fs.implementation_effort = 0.3
        fs.time_to_first_result = 0.2
    elif opportunity_type == OpportunityType.CONTENT_SERVICE:
        fs.complexity = 0.2
        fs.estimated_demand = 0.6
        fs.implementation_effort = 0.2
        fs.time_to_first_result = 0.1
        fs.required_cost = 0.2
    elif opportunity_type == OpportunityType.ANALYSIS_SERVICE:
        fs.complexity = 0.4
        fs.estimated_demand = 0.6
        fs.implementation_effort = 0.3
        fs.time_to_first_result = 0.2
    elif opportunity_type == OpportunityType.MICRO_SAAS:
        fs.complexity = 0.6
        fs.estimated_demand = 0.5
        fs.implementation_effort = 0.6
        fs.time_to_first_result = 0.5
        fs.required_cost = 0.4
    elif opportunity_type == OpportunityType.DOCUMENT_GENERATION:
        fs.complexity = 0.2
        fs.estimated_demand = 0.6
        fs.implementation_effort = 0.2
        fs.time_to_first_result = 0.1
        fs.required_cost = 0.1

    # Keyword adjustments
    if "ai" in desc or "automation" in desc:
        fs.estimated_demand += 0.1
    if "enterprise" in desc:
        fs.competition += 0.2
        fs.complexity += 0.2
    if "niche" in desc or "specific" in desc:
        fs.competition -= 0.1

    # Clamp
    for attr in ("complexity", "estimated_demand", "competition",
                 "implementation_effort", "time_to_first_result",
                 "legal_simplicity", "required_cost"):
        setattr(fs, attr, max(0.0, min(1.0, getattr(fs, attr))))

    return fs


# ── Landing page generation ─────────────────────────────────────────────

def generate_landing_structure(opportunity: BusinessOpportunity) -> LandingPageStructure:
    """Generate a landing page structure from an opportunity."""
    return LandingPageStructure(
        headline=opportunity.value_proposition or opportunity.summary,
        problem_statement=opportunity.problem,
        solution_explanation=opportunity.solution,
        key_benefits=[
            opportunity.value_proposition,
            f"Delivered as: {opportunity.delivery_format}",
            f"For: {opportunity.target_customer}",
        ],
        process_steps=[
            "Describe your need",
            "Receive a tailored proposal",
            "Get results delivered",
        ],
        trust_elements=[
            "Clear pricing — no hidden fees",
            "GDPR compliant data handling",
            "Satisfaction-focused delivery",
        ],
        call_to_action=f"Get started — {opportunity.pricing_model}",
        contact_method="Email or contact form",
    )


# ── Acquisition strategies ──────────────────────────────────────────────

_ACQUISITION_STRATEGIES = {
    OpportunityType.AUTOMATION_SERVICE: [
        "Direct outreach to businesses with manual processes",
        "LinkedIn content about automation ROI",
        "Niche community engagement (Reddit, forums)",
        "Case study from first free/discounted client",
    ],
    OpportunityType.CONTENT_SERVICE: [
        "SEO blog posts demonstrating expertise",
        "Social media content samples",
        "Free templates as lead magnets",
        "Partnership with agencies needing overflow capacity",
    ],
    OpportunityType.ANALYSIS_SERVICE: [
        "Free sample analysis for target prospects",
        "LinkedIn thought leadership posts",
        "Cold outreach with specific insights about prospect",
        "Referral program from satisfied clients",
    ],
    OpportunityType.MICRO_SAAS: [
        "Product Hunt / indie hacker launches",
        "SEO for specific pain point keywords",
        "Free tier to build user base",
        "Integration partnerships with complementary tools",
    ],
    OpportunityType.DOCUMENT_GENERATION: [
        "Direct outreach to professionals needing documents",
        "Template marketplace listings",
        "Partnership with consultants/accountants",
        "Content marketing about document efficiency",
    ],
}


def suggest_acquisition(opportunity_type: OpportunityType) -> list[str]:
    """Suggest acquisition strategies for an opportunity type."""
    return _ACQUISITION_STRATEGIES.get(
        opportunity_type,
        ["Direct outreach", "Content marketing", "Community engagement"],
    )


# ── Business intent detection ───────────────────────────────────────────

_BUSINESS_KEYWORDS = frozenset({
    "business", "opportunity", "revenue", "profit", "service",
    "offer", "customer", "client", "pricing", "saas", "automation",
    "landing page", "acquisition", "prospect", "monetize", "startup",
    "side project", "freelance", "consulting", "agency",
    "business idea", "make money", "generate income",
})


def is_business_mission(goal: str) -> bool:
    """Detect if a mission goal has business intent."""
    g = goal.lower()
    return any(kw in g for kw in _BUSINESS_KEYWORDS)
