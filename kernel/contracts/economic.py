"""
kernel/contracts/economic.py — Economic intelligence contracts.

Structured schemas for business reasoning outputs:
  - OpportunityReport
  - BusinessConcept
  - VenturePlan
  - FinancialModel
  - ComplianceChecklist

Design:
  - Pure dataclasses, zero external deps
  - Compatible with kernel contracts (to_dict/from_dict/validate)
  - Usable inside missions, playbooks, and skill outputs
  - All outputs are ADVISORY — no execution authority
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════════════════
# OpportunityReport
# ══════════════════════════════════════════════════════════════

@dataclass
class OpportunityReport:
    """
    Structured assessment of a market opportunity.

    Output of market intelligence reasoning.
    All estimates are heuristic — not financial advice.
    """
    report_id: str = ""
    problem_description: str = ""
    target_users: list[str] = field(default_factory=list)
    pain_intensity: float = 0.0  # 0.0 to 1.0
    market_size_estimate: str = ""  # "~$50M TAM" or "niche (<$5M)"
    market_size_reasoning: str = ""
    competition_overview: str = ""
    feasibility_reasoning: str = ""
    estimated_difficulty: float = 0.5  # 0.0 (easy) to 1.0 (very hard)
    confidence: float = 0.5  # 0.0 to 1.0
    risk_flags: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.report_id:
            self.report_id = f"opp-{uuid.uuid4().hex[:8]}"

    def validate(self) -> list[str]:
        errors = []
        if not self.problem_description:
            errors.append("problem_description is required")
        if not 0.0 <= self.pain_intensity <= 1.0:
            errors.append("pain_intensity must be 0.0-1.0")
        if not 0.0 <= self.confidence <= 1.0:
            errors.append("confidence must be 0.0-1.0")
        if not 0.0 <= self.estimated_difficulty <= 1.0:
            errors.append("estimated_difficulty must be 0.0-1.0")
        return errors

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "schema": "OpportunityReport",
            "version": "1.0",
            "problem_description": self.problem_description,
            "target_users": self.target_users,
            "pain_intensity": round(self.pain_intensity, 3),
            "market_size_estimate": self.market_size_estimate,
            "market_size_reasoning": self.market_size_reasoning,
            "competition_overview": self.competition_overview[:500],
            "feasibility_reasoning": self.feasibility_reasoning[:500],
            "estimated_difficulty": round(self.estimated_difficulty, 3),
            "confidence": round(self.confidence, 3),
            "risk_flags": self.risk_flags[:10],
            "data_sources": self.data_sources[:10],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityReport":
        return cls(
            report_id=d.get("report_id", ""),
            problem_description=d.get("problem_description", ""),
            target_users=list(d.get("target_users", [])),
            pain_intensity=float(d.get("pain_intensity", 0)),
            market_size_estimate=d.get("market_size_estimate", ""),
            market_size_reasoning=d.get("market_size_reasoning", ""),
            competition_overview=d.get("competition_overview", ""),
            feasibility_reasoning=d.get("feasibility_reasoning", ""),
            estimated_difficulty=float(d.get("estimated_difficulty", 0.5)),
            confidence=float(d.get("confidence", 0.5)),
            risk_flags=list(d.get("risk_flags", [])),
            data_sources=list(d.get("data_sources", [])),
            created_at=float(d.get("created_at", time.time())),
        )

    @property
    def viability_score(self) -> float:
        """
        Quick viability heuristic (0.0-1.0).
        High pain + low difficulty + high confidence = high viability.
        """
        return round(
            0.4 * self.pain_intensity
            + 0.3 * (1.0 - self.estimated_difficulty)
            + 0.3 * self.confidence,
            3
        )


# ══════════════════════════════════════════════════════════════
# BusinessConcept
# ══════════════════════════════════════════════════════════════

@dataclass
class BusinessConcept:
    """
    Structured description of a business idea.

    Output of product design / strategy reasoning.
    """
    concept_id: str = ""
    value_proposition: str = ""
    target_segment: str = ""
    solution_description: str = ""
    differentiation_hypothesis: str = ""
    delivery_mechanism: str = ""  # "SaaS", "API", "marketplace", "service"
    revenue_logic: str = ""  # "subscription", "usage-based", "freemium", etc.
    scalability_potential: str = ""  # "low", "medium", "high"
    estimated_complexity: float = 0.5  # 0.0-1.0
    opportunity_report_id: str = ""  # links back to OpportunityReport
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.concept_id:
            self.concept_id = f"biz-{uuid.uuid4().hex[:8]}"

    def validate(self) -> list[str]:
        errors = []
        if not self.value_proposition:
            errors.append("value_proposition is required")
        if not self.target_segment:
            errors.append("target_segment is required")
        if not self.solution_description:
            errors.append("solution_description is required")
        return errors

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "schema": "BusinessConcept",
            "version": "1.0",
            "value_proposition": self.value_proposition,
            "target_segment": self.target_segment,
            "solution_description": self.solution_description[:500],
            "differentiation_hypothesis": self.differentiation_hypothesis[:300],
            "delivery_mechanism": self.delivery_mechanism,
            "revenue_logic": self.revenue_logic,
            "scalability_potential": self.scalability_potential,
            "estimated_complexity": round(self.estimated_complexity, 3),
            "opportunity_report_id": self.opportunity_report_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BusinessConcept":
        return cls(
            concept_id=d.get("concept_id", ""),
            value_proposition=d.get("value_proposition", ""),
            target_segment=d.get("target_segment", ""),
            solution_description=d.get("solution_description", ""),
            differentiation_hypothesis=d.get("differentiation_hypothesis", ""),
            delivery_mechanism=d.get("delivery_mechanism", ""),
            revenue_logic=d.get("revenue_logic", ""),
            scalability_potential=d.get("scalability_potential", ""),
            estimated_complexity=float(d.get("estimated_complexity", 0.5)),
            opportunity_report_id=d.get("opportunity_report_id", ""),
            created_at=float(d.get("created_at", time.time())),
        )


# ══════════════════════════════════════════════════════════════
# VenturePlan
# ══════════════════════════════════════════════════════════════

@dataclass
class Milestone:
    """A milestone in a venture plan."""
    name: str = ""
    description: str = ""
    target_week: int = 0  # estimated week from start
    validation_criteria: str = ""
    status: str = "pending"  # pending, in_progress, completed, blocked

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "target_week": self.target_week,
            "validation_criteria": self.validation_criteria,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Milestone":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class VenturePlan:
    """
    Structured plan for bringing a business concept to reality.

    Output of venture planning reasoning.
    Milestones are advisory — not auto-scheduled.
    """
    plan_id: str = ""
    concept_id: str = ""  # links to BusinessConcept
    milestones: list[Milestone] = field(default_factory=list)
    mvp_scope: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    estimated_timeline_weeks: int = 0
    execution_risks: list[str] = field(default_factory=list)
    validation_steps: list[str] = field(default_factory=list)
    playbook_ids: list[str] = field(default_factory=list)  # linked playbooks
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"vp-{uuid.uuid4().hex[:8]}"

    def validate(self) -> list[str]:
        errors = []
        if not self.mvp_scope:
            errors.append("mvp_scope is required")
        if not self.milestones:
            errors.append("At least one milestone is required")
        if self.estimated_timeline_weeks <= 0:
            errors.append("estimated_timeline_weeks must be > 0")
        return errors

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "schema": "VenturePlan",
            "version": "1.0",
            "concept_id": self.concept_id,
            "milestones": [m.to_dict() for m in self.milestones],
            "mvp_scope": self.mvp_scope[:500],
            "required_capabilities": self.required_capabilities[:20],
            "estimated_timeline_weeks": self.estimated_timeline_weeks,
            "execution_risks": self.execution_risks[:10],
            "validation_steps": self.validation_steps[:10],
            "playbook_ids": self.playbook_ids[:10],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VenturePlan":
        return cls(
            plan_id=d.get("plan_id", ""),
            concept_id=d.get("concept_id", ""),
            milestones=[Milestone.from_dict(m) for m in d.get("milestones", [])],
            mvp_scope=d.get("mvp_scope", ""),
            required_capabilities=list(d.get("required_capabilities", [])),
            estimated_timeline_weeks=int(d.get("estimated_timeline_weeks", 0)),
            execution_risks=list(d.get("execution_risks", [])),
            validation_steps=list(d.get("validation_steps", [])),
            playbook_ids=list(d.get("playbook_ids", [])),
            created_at=float(d.get("created_at", time.time())),
        )


# ══════════════════════════════════════════════════════════════
# FinancialModel
# ══════════════════════════════════════════════════════════════

@dataclass
class FinancialModel:
    """
    Heuristic financial model for a business concept.

    NOT accounting — rough estimation for decision support.
    All figures are estimates with explicit assumptions.
    """
    model_id: str = ""
    concept_id: str = ""
    pricing_logic: str = ""  # "freemium with $29/mo pro tier"
    cost_estimation: dict = field(default_factory=dict)  # {"hosting": "$50/mo", "api": "$200/mo"}
    break_even_estimate: str = ""  # "~150 paying users" or "6-9 months"
    break_even_reasoning: str = ""
    expected_margin: str = ""  # "high (>60%)", "medium (30-60%)", "low (<30%)"
    margin_classification: str = ""  # "software", "service", "marketplace"
    sensitivity_assumptions: list[str] = field(default_factory=list)
    monthly_revenue_estimate: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.model_id:
            self.model_id = f"fin-{uuid.uuid4().hex[:8]}"

    def validate(self) -> list[str]:
        errors = []
        if not self.pricing_logic:
            errors.append("pricing_logic is required")
        if not self.sensitivity_assumptions:
            errors.append("At least one sensitivity assumption is required")
        return errors

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "schema": "FinancialModel",
            "version": "1.0",
            "concept_id": self.concept_id,
            "pricing_logic": self.pricing_logic,
            "cost_estimation": self.cost_estimation,
            "break_even_estimate": self.break_even_estimate,
            "break_even_reasoning": self.break_even_reasoning[:300],
            "expected_margin": self.expected_margin,
            "margin_classification": self.margin_classification,
            "sensitivity_assumptions": self.sensitivity_assumptions[:10],
            "monthly_revenue_estimate": self.monthly_revenue_estimate,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FinancialModel":
        return cls(
            model_id=d.get("model_id", ""),
            concept_id=d.get("concept_id", ""),
            pricing_logic=d.get("pricing_logic", ""),
            cost_estimation=dict(d.get("cost_estimation", {})),
            break_even_estimate=d.get("break_even_estimate", ""),
            break_even_reasoning=d.get("break_even_reasoning", ""),
            expected_margin=d.get("expected_margin", ""),
            margin_classification=d.get("margin_classification", ""),
            sensitivity_assumptions=list(d.get("sensitivity_assumptions", [])),
            monthly_revenue_estimate=d.get("monthly_revenue_estimate", ""),
            created_at=float(d.get("created_at", time.time())),
        )


# ══════════════════════════════════════════════════════════════
# ComplianceChecklist
# ══════════════════════════════════════════════════════════════

@dataclass
class ComplianceItem:
    """A single compliance consideration."""
    area: str = ""  # "data_privacy", "tax", "licensing", "consumer_protection"
    description: str = ""
    risk_level: str = "unknown"  # "low", "medium", "high", "unknown"
    requires_human_validation: bool = True
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "area": self.area,
            "description": self.description,
            "risk_level": self.risk_level,
            "requires_human_validation": self.requires_human_validation,
            "notes": self.notes[:200],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComplianceItem":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ComplianceChecklist:
    """
    Regulatory/compliance considerations for a business concept.

    EXPLICITLY NOT LEGAL ADVICE.
    All items marked with uncertainty level.
    Human validation required before any action.
    """
    checklist_id: str = ""
    concept_id: str = ""
    jurisdiction_assumptions: list[str] = field(default_factory=list)
    items: list[ComplianceItem] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    human_validation_required: bool = True  # always True
    disclaimer: str = "This is a preliminary checklist, NOT legal advice. Professional review required."
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.checklist_id:
            self.checklist_id = f"cpl-{uuid.uuid4().hex[:8]}"
        self.human_validation_required = True  # enforced, cannot be False

    def validate(self) -> list[str]:
        errors = []
        if not self.jurisdiction_assumptions:
            errors.append("At least one jurisdiction assumption is required")
        if not self.items:
            errors.append("At least one compliance item is required")
        return errors

    def to_dict(self) -> dict:
        return {
            "checklist_id": self.checklist_id,
            "schema": "ComplianceChecklist",
            "version": "1.0",
            "concept_id": self.concept_id,
            "jurisdiction_assumptions": self.jurisdiction_assumptions[:10],
            "items": [i.to_dict() for i in self.items[:20]],
            "risk_flags": self.risk_flags[:10],
            "human_validation_required": True,
            "disclaimer": self.disclaimer,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComplianceChecklist":
        return cls(
            checklist_id=d.get("checklist_id", ""),
            concept_id=d.get("concept_id", ""),
            jurisdiction_assumptions=list(d.get("jurisdiction_assumptions", [])),
            items=[ComplianceItem.from_dict(i) for i in d.get("items", [])],
            risk_flags=list(d.get("risk_flags", [])),
            disclaimer=d.get("disclaimer", ""),
            created_at=float(d.get("created_at", time.time())),
        )


# ══════════════════════════════════════════════════════════════
# Schema registry helper
# ══════════════════════════════════════════════════════════════

ECONOMIC_SCHEMAS = {
    "OpportunityReport": OpportunityReport,
    "BusinessConcept": BusinessConcept,
    "VenturePlan": VenturePlan,
    "FinancialModel": FinancialModel,
    "ComplianceChecklist": ComplianceChecklist,
}


def parse_economic_output(data: dict) -> object | None:
    """
    Parse a dict into the appropriate economic schema based on 'schema' field.
    Returns None if schema is unknown.
    """
    schema_name = data.get("schema", "")
    cls = ECONOMIC_SCHEMAS.get(schema_name)
    if cls is None:
        return None
    try:
        return cls.from_dict(data)
    except Exception:
        return None
