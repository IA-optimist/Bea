"""
JARVIS MAX — Business Model Agent
=====================================
Generates and scores business models from market research.

Capabilities:
1. Generate Lean Canvas from market report
2. Financial projections (12/24/36 months)
3. Unit economics (CAC, LTV, payback period)
4. Viability scoring (1-10)
5. Revenue model selection

Design: structured computation + LLM reasoning.
All financial projections are clearly marked as estimates.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class LeanCanvas:
    """Lean Canvas business model."""
    problem: list[str] = field(default_factory=list)
    solution: list[str] = field(default_factory=list)
    unique_value: str = ""
    unfair_advantage: str = ""
    customer_segments: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    revenue_streams: list[str] = field(default_factory=list)
    cost_structure: list[str] = field(default_factory=list)
    key_metrics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "problem": self.problem[:3], "solution": self.solution[:3],
            "unique_value": self.unique_value, "unfair_advantage": self.unfair_advantage,
            "segments": self.customer_segments[:5], "channels": self.channels[:5],
            "revenue": self.revenue_streams[:3], "costs": self.cost_structure[:5],
            "metrics": self.key_metrics[:5],
        }


@dataclass
class UnitEconomics:
    """Unit economics for the business."""
    cac: float = 0.0            # Customer Acquisition Cost
    ltv: float = 0.0            # Lifetime Value
    ltv_cac_ratio: float = 0.0  # LTV:CAC ratio (>3 is good)
    payback_months: float = 0.0 # Months to recoup CAC
    monthly_churn: float = 0.0  # Monthly churn rate
    avg_revenue_per_user: float = 0.0

    @property
    def healthy(self) -> bool:
        return self.ltv_cac_ratio >= 3.0 and self.payback_months <= 12

    def to_dict(self) -> dict:
        return {
            "cac": round(self.cac, 2), "ltv": round(self.ltv, 2),
            "ltv_cac_ratio": round(self.ltv_cac_ratio, 2),
            "payback_months": round(self.payback_months, 1),
            "monthly_churn": f"{self.monthly_churn:.1%}",
            "arpu": round(self.avg_revenue_per_user, 2),
            "healthy": self.healthy,
        }


@dataclass
class Projection:
    """Revenue/cost projection for a time period."""
    month: int
    revenue: float = 0.0
    costs: float = 0.0
    customers: int = 0
    mrr: float = 0.0        # Monthly Recurring Revenue
    profit: float = 0.0
    note: str = "estimate"

    def to_dict(self) -> dict:
        return {
            "month": self.month, "revenue": round(self.revenue),
            "costs": round(self.costs), "customers": self.customers,
            "mrr": round(self.mrr), "profit": round(self.profit),
        }


@dataclass
class ViabilityScore:
    """Business viability assessment."""
    score: float = 0.0         # 1-10
    market_score: float = 0.0
    economics_score: float = 0.0
    execution_score: float = 0.0
    risk_score: float = 0.0
    verdict: str = ""          # go, review, no-go

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "market": round(self.market_score, 1),
            "economics": round(self.economics_score, 1),
            "execution": round(self.execution_score, 1),
            "risk": round(self.risk_score, 1),
            "verdict": self.verdict,
        }


@dataclass
class BusinessModel:
    """Complete business model output."""
    name: str
    canvas: LeanCanvas = field(default_factory=LeanCanvas)
    economics: UnitEconomics = field(default_factory=UnitEconomics)
    projections: list[Projection] = field(default_factory=list)
    viability: ViabilityScore = field(default_factory=ViabilityScore)
    revenue_model: str = ""     # subscription, one-time, freemium, marketplace
    pricing_suggestion: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "canvas": self.canvas.to_dict(),
            "economics": self.economics.to_dict(),
            "projections": [p.to_dict() for p in self.projections[:36]],
            "viability": self.viability.to_dict(),
            "revenue_model": self.revenue_model,
            "pricing": self.pricing_suggestion,
        }

    def summary(self) -> str:
        v = self.viability
        lines = [
            f"═══ Business Model: {self.name} ═══",
            f"Revenue model: {self.revenue_model}",
            f"Pricing: {self.pricing_suggestion}",
            f"LTV:CAC = {self.economics.ltv_cac_ratio:.1f}x "
            f"({'✅ healthy' if self.economics.healthy else '⚠️ needs improvement'})",
            f"Viability: {v.score:.1f}/10 → {v.verdict.upper()}",
        ]
        if self.projections:
            last = self.projections[-1]
            lines.append(f"Month {last.month}: {last.customers} customers, ${last.mrr:.0f} MRR")
        return "\n".join(lines)


class BusinessModelAgent:
    """
    Generates business models from market research.
    """

    def generate(self, opportunity: str, market_report: dict | None = None) -> BusinessModel:
        """Generate a business model for an opportunity."""
        model = BusinessModel(name=opportunity)

        # Phase 1: Lean Canvas
        model.canvas = self._build_canvas(opportunity, market_report)

        # Phase 2: Revenue model selection
        model.revenue_model = self._select_revenue_model(opportunity)

        # Phase 3: Unit economics
        model.economics = self._compute_economics(model)

        # Phase 4: Projections
        model.projections = self._project_financials(model)

        # Phase 5: Viability scoring
        model.viability = self._score_viability(model)

        return model

    def score_viability(self, model: BusinessModel) -> ViabilityScore:
        """Re-score viability on an existing model."""
        return self._score_viability(model)

    def _build_canvas(self, opp: str, market: dict | None) -> LeanCanvas:
        """Build Lean Canvas. Stub — will be LLM generated."""
        return LeanCanvas(
            problem=["Requires LLM analysis"],
            solution=["Requires LLM analysis"],
            unique_value="Requires LLM analysis",
        )

    def _select_revenue_model(self, opp: str) -> str:
        """Select best revenue model. Stub — will be LLM reasoned."""
        return "subscription"

    def _compute_economics(self, model: BusinessModel) -> UnitEconomics:
        """Compute unit economics from model assumptions."""
        # Default assumptions for SaaS
        arpu = 49.0
        churn = 0.05
        cac = 100.0
        avg_lifetime_months = 1 / max(churn, 0.01)
        ltv = arpu * avg_lifetime_months

        return UnitEconomics(
            cac=cac,
            ltv=ltv,
            ltv_cac_ratio=ltv / max(cac, 1),
            payback_months=cac / max(arpu, 1),
            monthly_churn=churn,
            avg_revenue_per_user=arpu,
        )

    def _project_financials(self, model: BusinessModel, months: int = 12) -> list[Projection]:
        """Generate monthly financial projections."""
        projections = []
        customers = 0
        growth_rate = 0.15  # 15% monthly growth
        churn = model.economics.monthly_churn
        arpu = model.economics.avg_revenue_per_user
        fixed_costs = 500  # Starting fixed costs

        for m in range(1, months + 1):
            new_customers = max(5, int(customers * growth_rate) + 5)
            churned = int(customers * churn)
            customers = customers + new_customers - churned

            mrr = customers * arpu
            revenue = mrr
            cac_costs = new_customers * model.economics.cac
            costs = fixed_costs + cac_costs
            profit = revenue - costs

            projections.append(Projection(
                month=m, revenue=revenue, costs=costs,
                customers=customers, mrr=mrr, profit=profit,
            ))

        return projections

    def _score_viability(self, model: BusinessModel) -> ViabilityScore:
        """Score business viability 1-10."""
        econ = model.economics

        # Economics score: LTV:CAC ratio
        econ_score = min(10, econ.ltv_cac_ratio * 2)

        # Market score (simplified — will use market report)
        market_score = 5.0  # Default

        # Execution score (simplified)
        exec_score = 6.0

        # Risk score (inverted — lower risk = higher score)
        risk_score = 7.0 if econ.monthly_churn < 0.1 else 4.0

        overall = (market_score * 0.3 + econ_score * 0.3 +
                   exec_score * 0.2 + risk_score * 0.2)

        if overall >= 7.0:
            verdict = "go"
        elif overall >= 5.0:
            verdict = "review"
        else:
            verdict = "no-go"

        return ViabilityScore(
            score=overall,
            market_score=market_score,
            economics_score=econ_score,
            execution_score=exec_score,
            risk_score=risk_score,
            verdict=verdict,
        )
