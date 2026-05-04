"""
JARVIS MAX — Business Agents Suite (Sprint 3+4)
=================================================
6 business agents for Build + Operate phases.

Sprint 3 — BUILD:
  TechBuilderAgent  — MVP creation, deployment, domain
  ContentAgent      — Copywriting, email sequences, social posts
  LegalAgent        — Contracts, CGV, RGPD, legal structure

Sprint 4 — OPERATE:
  FinanceAgent      — Stripe, invoicing, P&L, expense tracking
  GrowthAgent       — Acquisition, A/B testing, campaigns
  CustomerAgent     — Support, NPS, churn detection

All agents output structured data. Human approval gates enforced.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════
# APPROVAL GATE
# ═══════════════════════════════════════════════════════════════

class ApprovalCategory:
    LAUNCH = "launch"
    SPEND_HIGH = "spend_above_500"
    SPEND_LOW = "spend_above_100"
    CONTRACT = "contract_signature"
    CAMPAIGN = "paid_campaign"
    REFUND = "refund_above_50"
    PIVOT = "strategic_pivot"
    CREDENTIAL = "new_api_credential"


@dataclass
class ApprovalRequest:
    """Request for human approval."""
    category: str
    description: str
    context: dict = field(default_factory=dict)
    amount: float = 0.0
    currency: str = "EUR"
    approved: bool | None = None   # None = pending
    timestamp: float = field(default_factory=time.time)

    @property
    def pending(self) -> bool:
        return self.approved is None

    def to_dict(self) -> dict:
        return {
            "category": self.category, "description": self.description[:200],
            "amount": self.amount, "currency": self.currency,
            "status": "pending" if self.pending else ("approved" if self.approved else "denied"),
        }


def requires_approval(category: str, amount: float = 0) -> bool:
    """Check if an action requires human approval."""
    always = {ApprovalCategory.LAUNCH, ApprovalCategory.CONTRACT,
              ApprovalCategory.PIVOT, ApprovalCategory.CREDENTIAL}
    if category in always:
        return True
    if category == ApprovalCategory.SPEND_HIGH and amount > 500:
        return True
    if category == ApprovalCategory.SPEND_LOW and amount > 100:
        return True
    if category == ApprovalCategory.CAMPAIGN and amount > 0:
        return True
    if category == ApprovalCategory.REFUND and amount > 50:
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# SPRINT 3 — BUILD AGENTS
# ═══════════════════════════════════════════════════════════════

@dataclass
class MVPSpec:
    """MVP specification output."""
    name: str
    tech_stack: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    deploy_target: str = ""      # vercel, railway, self-hosted
    domain: str = ""
    estimated_hours: float = 0
    status: str = "planned"      # planned, building, deployed, live

    def to_dict(self) -> dict:
        return {
            "name": self.name, "stack": self.tech_stack,
            "pages": self.pages, "features": self.features[:10],
            "deploy": self.deploy_target, "domain": self.domain,
            "hours": self.estimated_hours, "status": self.status,
        }


class TechBuilderAgent:
    """Creates and deploys MVPs."""

    def plan_mvp(self, business_name: str, model: dict | None = None) -> MVPSpec:
        """Plan an MVP based on business model."""
        return MVPSpec(
            name=business_name,
            tech_stack=["Next.js", "Tailwind", "Supabase"],
            pages=["landing", "pricing", "signup", "dashboard"],
            features=["Auth", "Payments", "Core product"],
            deploy_target="vercel",
            estimated_hours=40,
            status="planned",
        )

    def build_landing(self, spec: MVPSpec) -> dict:
        """Generate landing page. Stub — will use code generation."""
        return {"status": "ready_for_llm", "spec": spec.to_dict()}

    def deploy(self, spec: MVPSpec) -> dict:
        """Deploy MVP. Stub — will use Vercel/Railway API."""
        return {
            "status": "requires_approval",
            "approval": ApprovalRequest(
                category=ApprovalCategory.LAUNCH,
                description=f"Deploy {spec.name} to {spec.deploy_target}",
            ).to_dict(),
        }


@dataclass
class ContentAssets:
    """Marketing content package."""
    landing_copy: dict = field(default_factory=dict)
    email_sequences: list[dict] = field(default_factory=list)
    social_posts: list[dict] = field(default_factory=list)
    blog_outlines: list[dict] = field(default_factory=list)
    seo_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "landing": bool(self.landing_copy),
            "emails": len(self.email_sequences),
            "social": len(self.social_posts),
            "blogs": len(self.blog_outlines),
            "keywords": self.seo_keywords[:20],
        }


class ContentMarketingAgent:
    """Creates and distributes marketing content."""

    def create_assets(self, business_name: str) -> ContentAssets:
        """Create full content package. Stub — will be LLM generated."""
        return ContentAssets(
            landing_copy={"headline": f"Welcome to {business_name}", "status": "ready_for_llm"},
            email_sequences=[{"name": "welcome", "emails": 3}],
            social_posts=[{"platform": "twitter", "count": 5}],
            seo_keywords=["requires_research"],
        )

    def launch_campaign(self, assets: ContentAssets, budget: float = 0) -> dict:
        """Launch marketing campaign."""
        if budget > 0 and requires_approval(ApprovalCategory.CAMPAIGN, budget):
            return {"status": "requires_approval", "budget": budget}
        return {"status": "launched", "budget": budget}


@dataclass
class LegalDocSet:
    """Legal document set."""
    terms_of_service: str = ""
    privacy_policy: str = ""
    contracts: list[dict] = field(default_factory=list)
    structure: str = ""     # SAS, SARL, auto-entrepreneur, LLC
    rgpd_compliant: bool = False

    def to_dict(self) -> dict:
        return {
            "has_tos": bool(self.terms_of_service),
            "has_privacy": bool(self.privacy_policy),
            "contracts": len(self.contracts),
            "structure": self.structure,
            "rgpd": self.rgpd_compliant,
        }


class LegalAgent:
    """Manages legal structure and documents."""

    def setup_structure(self, business_name: str, country: str = "FR") -> LegalDocSet:
        """Generate legal documents. Stub — will be template + LLM."""
        return LegalDocSet(
            terms_of_service="ready_for_llm",
            privacy_policy="ready_for_llm",
            structure="auto-entrepreneur" if country == "FR" else "LLC",
            rgpd_compliant=country in ("FR", "DE", "ES", "IT", "NL"),
        )

    def review_contract(self) -> dict:
        """Review a contract. Always requires human approval."""
        return {
            "status": "requires_approval",
            "approval": ApprovalRequest(
                category=ApprovalCategory.CONTRACT,
                description="Contract review and signature required",
            ).to_dict(),
        }


# ═══════════════════════════════════════════════════════════════
# SPRINT 4 — OPERATE AGENTS
# ═══════════════════════════════════════════════════════════════

@dataclass
class FinancialDashboard:
    """Financial metrics snapshot."""
    mrr: float = 0.0
    arr: float = 0.0
    total_revenue: float = 0.0
    total_expenses: float = 0.0
    profit: float = 0.0
    customers: int = 0
    invoices_pending: int = 0

    def to_dict(self) -> dict:
        return {
            "mrr": round(self.mrr, 2), "arr": round(self.arr, 2),
            "revenue": round(self.total_revenue, 2),
            "expenses": round(self.total_expenses, 2),
            "profit": round(self.profit, 2),
            "customers": self.customers,
            "invoices_pending": self.invoices_pending,
        }


class FinanceAgent:
    """Manages business finances."""

    def setup_stripe(self, business_name: str) -> dict:
        """Configure Stripe. Stub — will use Stripe API."""
        return {"status": "requires_integration", "provider": "stripe"}

    def get_dashboard(self) -> FinancialDashboard:
        """Get current financial metrics."""
        return FinancialDashboard()

    def create_invoice(self, customer: str, amount: float, description: str) -> dict:
        """Create an invoice. Stub — will use Stripe Invoicing."""
        return {"status": "ready_for_integration", "customer": customer, "amount": amount}

    def approve_expense(self, amount: float, description: str) -> dict:
        """Approve an expense. High amounts require human gate."""
        cat = ApprovalCategory.SPEND_HIGH if amount > 500 else ApprovalCategory.SPEND_LOW
        if requires_approval(cat, amount):
            return {
                "status": "requires_approval",
                "approval": ApprovalRequest(
                    category=cat, description=description, amount=amount,
                ).to_dict(),
            }
        return {"status": "approved", "amount": amount}


@dataclass
class GrowthMetrics:
    """Growth performance metrics."""
    new_signups_week: int = 0
    conversion_rate: float = 0.0
    cac: float = 0.0
    active_campaigns: int = 0
    ab_tests_running: int = 0
    top_channel: str = ""

    def to_dict(self) -> dict:
        return {
            "signups_week": self.new_signups_week,
            "conversion": f"{self.conversion_rate:.1%}",
            "cac": round(self.cac, 2),
            "campaigns": self.active_campaigns,
            "ab_tests": self.ab_tests_running,
            "top_channel": self.top_channel,
        }


class GrowthAgent:
    """Acquisition and retention optimization."""

    def get_metrics(self) -> GrowthMetrics:
        return GrowthMetrics()

    def launch_campaign(self, channel: str, budget: float, target: str) -> dict:
        """Launch paid campaign. Always requires approval."""
        if requires_approval(ApprovalCategory.CAMPAIGN, budget):
            return {
                "status": "requires_approval",
                "approval": ApprovalRequest(
                    category=ApprovalCategory.CAMPAIGN,
                    description=f"Launch {channel} campaign targeting {target}",
                    amount=budget,
                ).to_dict(),
            }
        return {"status": "launched", "channel": channel}

    def run_ab_test(self, variant_a: str, variant_b: str) -> dict:
        """Start A/B test. No approval needed."""
        return {"status": "running", "variants": [variant_a, variant_b]}


@dataclass
class SupportMetrics:
    """Customer support metrics."""
    open_tickets: int = 0
    avg_response_hours: float = 0.0
    nps_score: float = 0.0
    churn_risk_customers: int = 0
    satisfaction_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "open_tickets": self.open_tickets,
            "avg_response_h": round(self.avg_response_hours, 1),
            "nps": round(self.nps_score, 1),
            "churn_risk": self.churn_risk_customers,
            "satisfaction": f"{self.satisfaction_rate:.0%}",
        }


class CustomerSuccessAgent:
    """Customer support and satisfaction."""

    def get_metrics(self) -> SupportMetrics:
        return SupportMetrics()

    def respond_ticket(self, ticket_id: str, message: str) -> dict:
        """Respond to support ticket. Stub — will be LLM + email."""
        return {"status": "ready_for_llm", "ticket": ticket_id}

    def process_refund(self, customer: str, amount: float, reason: str) -> dict:
        """Process refund. Over €50 requires approval."""
        if requires_approval(ApprovalCategory.REFUND, amount):
            return {
                "status": "requires_approval",
                "approval": ApprovalRequest(
                    category=ApprovalCategory.REFUND,
                    description=f"Refund {amount}€ to {customer}: {reason}",
                    amount=amount,
                ).to_dict(),
            }
        return {"status": "processed", "amount": amount}
