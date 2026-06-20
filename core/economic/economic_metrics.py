"""
core/economic/economic_metrics.py — Economic KPI metrics for objectives.

Phase E: Extend objectives with business-specific evaluation metrics.

New metric types:
  - Expected ROI
  - Estimated margin
  - Payback period
  - Customer acquisition cost estimate
  - Lifetime value estimate

Integrates with ObjectiveHorizonManager's EvaluationMetric system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.objectives.objective_horizon import EvaluationMetric


@dataclass
class EconomicKPI:
    """An economic KPI with metadata for business reasoning."""
    metric: EvaluationMetric
    kpi_type: str  # "roi", "margin", "payback", "cac", "ltv", "mrr", "churn"
    currency: str = "USD"
    time_period: str = "monthly"  # monthly, quarterly, annual
    assumptions: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = dict(self.metric.to_dict())
        d.update({
            "kpi_type": self.kpi_type,
            "currency": self.currency,
            "time_period": self.time_period,
            "assumptions": (self.assumptions or [])[:5],
        })
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EconomicKPI":
        metric = EvaluationMetric.from_dict(d)
        return cls(
            metric=metric,
            kpi_type=d.get("kpi_type", ""),
            currency=d.get("currency", "USD"),
            time_period=d.get("time_period", "monthly"),
            assumptions=d.get("assumptions"),
        )


# ── KPI Templates ─────────────────────────────────────────────

def create_roi_kpi(target_percent: float, current: float = 0.0,
                   assumptions: list[str] | None = None) -> EconomicKPI:
    """Expected return on investment (%)."""
    return EconomicKPI(
        metric=EvaluationMetric(
            name="expected_roi",
            description="Expected return on investment percentage",
            target_value=target_percent,
            current_value=current,
            unit="percent",
            direction="up",
        ),
        kpi_type="roi",
        assumptions=assumptions or ["Based on comparable market analysis"],
    )


def create_margin_kpi(target_percent: float, current: float = 0.0,
                      margin_type: str = "gross") -> EconomicKPI:
    """Estimated profit margin (%)."""
    return EconomicKPI(
        metric=EvaluationMetric(
            name=f"estimated_{margin_type}_margin",
            description=f"Estimated {margin_type} margin percentage",
            target_value=target_percent,
            current_value=current,
            unit="percent",
            direction="up",
        ),
        kpi_type="margin",
        assumptions=[f"Based on {margin_type} margin calculation"],
    )


def create_payback_kpi(target_months: float, current: float = 0.0) -> EconomicKPI:
    """Payback period in months (lower is better)."""
    return EconomicKPI(
        metric=EvaluationMetric(
            name="payback_period",
            description="Time to recover initial investment",
            target_value=target_months,
            current_value=current,
            unit="months",
            direction="down",  # lower is better
        ),
        kpi_type="payback",
        assumptions=["Assumes steady revenue growth"],
    )


def create_cac_kpi(target_cost: float, current: float = 0.0,
                   currency: str = "USD") -> EconomicKPI:
    """Customer acquisition cost (lower is better)."""
    return EconomicKPI(
        metric=EvaluationMetric(
            name="customer_acquisition_cost",
            description="Average cost to acquire one customer",
            target_value=target_cost,
            current_value=current,
            unit=currency,
            direction="down",
        ),
        kpi_type="cac",
        currency=currency,
        assumptions=["Blended across all channels"],
    )


def create_ltv_kpi(target_value: float, current: float = 0.0,
                   currency: str = "USD") -> EconomicKPI:
    """Customer lifetime value."""
    return EconomicKPI(
        metric=EvaluationMetric(
            name="customer_lifetime_value",
            description="Expected revenue per customer over lifetime",
            target_value=target_value,
            current_value=current,
            unit=currency,
            direction="up",
        ),
        kpi_type="ltv",
        currency=currency,
        assumptions=["Based on average retention rate"],
    )


def create_mrr_kpi(target_mrr: float, current: float = 0.0,
                   currency: str = "USD") -> EconomicKPI:
    """Monthly recurring revenue."""
    return EconomicKPI(
        metric=EvaluationMetric(
            name="monthly_recurring_revenue",
            description="Monthly recurring revenue target",
            target_value=target_mrr,
            current_value=current,
            unit=currency,
            direction="up",
        ),
        kpi_type="mrr",
        currency=currency,
        time_period="monthly",
    )


def set_economic_kpis(
    objective_id: str,
    kpis: list[EconomicKPI],
) -> bool:
    """
    Set economic KPIs on an objective via the horizon manager.

    Converts EconomicKPI list to EvaluationMetric list.
    Fail-open: returns False on failure.
    """
    try:
        from core.objectives.objective_horizon import get_horizon_manager
        mgr = get_horizon_manager()
        metrics = [k.metric for k in kpis]
        mgr.set_metrics(objective_id, metrics)
        return True
    except Exception:
        return False
