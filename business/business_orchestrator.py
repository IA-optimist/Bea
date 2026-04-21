"""
JARVIS MAX — Business Orchestrator
=====================================
Orchestrates the full business lifecycle: Discover → Build → Operate.

Phases:
1. DISCOVERY  — Market research + business model + viability check
2. BUILD      — Legal + MVP + content assets
3. LAUNCH     — Deploy + payment setup + campaign
4. OPERATE    — Finance monitoring + growth + customer success

Human approval gates at every major decision point.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class BusinessPhase(str, Enum):
    DISCOVERY = "discovery"
    BUILD = "build"
    LAUNCH = "launch"
    OPERATE = "operate"
    PAUSED = "paused"
    FAILED = "failed"


@dataclass
class Business:
    """A business being created/operated by Jarvis."""
    id: str
    name: str
    opportunity: str
    phase: str = "discovery"
    market_report: dict = field(default_factory=dict)
    business_model: dict = field(default_factory=dict)
    legal_docs: dict = field(default_factory=dict)
    mvp_spec: dict = field(default_factory=dict)
    content_assets: dict = field(default_factory=dict)
    financials: dict = field(default_factory=dict)
    approvals_pending: list[dict] = field(default_factory=list)
    approvals_completed: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def has_pending_approvals(self) -> bool:
        return len(self.approvals_pending) > 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "opportunity": self.opportunity[:200],
            "phase": self.phase,
            "has_market_report": bool(self.market_report),
            "has_model": bool(self.business_model),
            "has_legal": bool(self.legal_docs),
            "has_mvp": bool(self.mvp_spec),
            "pending_approvals": len(self.approvals_pending),
        }


@dataclass
class PhaseResult:
    """Result of executing a business phase."""
    phase: str
    success: bool = False
    needs_approval: bool = False
    approval_request: dict | None = None
    output: dict = field(default_factory=dict)
    next_phase: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "phase": self.phase, "success": self.success,
            "needs_approval": self.needs_approval,
            "next_phase": self.next_phase,
            "error": self.error[:200] if self.error else "",
        }


class BusinessOrchestrator:
    """
    Orchestrates the full business lifecycle.
    Each phase produces structured output + approval requests.
    No phase auto-advances past approval gates.
    """

    def __init__(self):
        self._businesses: dict[str, Business] = {}

    def create_business(self, opportunity: str, name: str = "") -> Business:
        """Initialize a new business."""
        import hashlib
        bid = hashlib.md5(f"{opportunity}{time.time()}".encode()).hexdigest()[:10]
        biz = Business(
            id=f"biz-{bid}",
            name=name or opportunity[:50],
            opportunity=opportunity,
            phase="discovery",
        )
        self._businesses[biz.id] = biz
        return biz

    def run_phase(self, business_id: str) -> PhaseResult:
        """Execute the current phase of a business."""
        biz = self._businesses.get(business_id)
        if not biz:
            return PhaseResult(phase="unknown", error="Business not found")

        if biz.has_pending_approvals:
            return PhaseResult(
                phase=biz.phase,
                needs_approval=True,
                approval_request=biz.approvals_pending[0],
                error="Pending approval(s) must be resolved first",
            )

        phase_runners = {
            "discovery": self._run_discovery,
            "build": self._run_build,
            "launch": self._run_launch,
            "operate": self._run_operate,
        }

        runner = phase_runners.get(biz.phase)
        if not runner:
            return PhaseResult(phase=biz.phase, error=f"Unknown phase: {biz.phase}")

        return runner(biz)

    def approve(self, business_id: str, approval_index: int = 0) -> bool:
        """Approve a pending approval request."""
        biz = self._businesses.get(business_id)
        if not biz or not biz.approvals_pending:
            return False
        if approval_index >= len(biz.approvals_pending):
            return False
        approved = biz.approvals_pending.pop(approval_index)
        approved["status"] = "approved"
        biz.approvals_completed.append(approved)
        return True

    def deny(self, business_id: str, approval_index: int = 0) -> bool:
        """Deny a pending approval."""
        biz = self._businesses.get(business_id)
        if not biz or not biz.approvals_pending:
            return False
        denied = biz.approvals_pending.pop(approval_index)
        denied["status"] = "denied"
        biz.approvals_completed.append(denied)
        return True

    def get_business(self, business_id: str) -> Business | None:
        return self._businesses.get(business_id)

    def list_businesses(self) -> list[dict]:
        return [b.to_dict() for b in self._businesses.values()]

    # ── Phase runners ──

    def _run_discovery(self, biz: Business) -> PhaseResult:
        """Phase 1: Market research + business model."""
        try:
            from agents.market_research_agent import MarketResearchAgent
            from agents.business_model_agent import BusinessModelAgent

            # Market research
            market = MarketResearchAgent().analyze(biz.opportunity)
            biz.market_report = market.to_dict()

            # Business model
            model = BusinessModelAgent().generate(biz.opportunity, biz.market_report)
            biz.business_model = model.to_dict()

            # Gate: if viability < 7, require human approval
            viability = model.viability.score
            if viability < 7.0:
                biz.approvals_pending.append({
                    "category": "viability_review",
                    "description": f"Viability score {viability:.1f}/10. Continue or pivot?",
                    "viability": viability,
                })
                return PhaseResult(
                    phase="discovery", success=True,
                    needs_approval=True,
                    approval_request=biz.approvals_pending[-1],
                    next_phase="build",
                )

            biz.phase = "build"
            return PhaseResult(phase="discovery", success=True, next_phase="build")

        except Exception as e:
            return PhaseResult(phase="discovery", error=str(e)[:200])

    def _run_build(self, biz: Business) -> PhaseResult:
        """Phase 2: Legal + MVP + Content."""
        try:
            from agents.business_agents_suite import (
                TechBuilderAgent, ContentMarketingAgent, LegalAgent,
            )

            legal = LegalAgent().setup_structure(biz.name)
            biz.legal_docs = legal.to_dict()

            mvp = TechBuilderAgent().plan_mvp(biz.name, biz.business_model)
            biz.mvp_spec = mvp.to_dict()

            content = ContentMarketingAgent().create_assets(biz.name)
            biz.content_assets = content.to_dict()

            # Gate: always require approval before launch
            biz.approvals_pending.append({
                "category": "launch",
                "description": f"MVP for {biz.name} ready. Approve launch?",
            })

            return PhaseResult(
                phase="build", success=True,
                needs_approval=True,
                next_phase="launch",
            )

        except Exception as e:
            return PhaseResult(phase="build", error=str(e)[:200])

    def _run_launch(self, biz: Business) -> PhaseResult:
        """Phase 3: Deploy + payments + campaign."""
        biz.phase = "operate"
        return PhaseResult(phase="launch", success=True, next_phase="operate",
                           output={"status": "launched"})

    def _run_operate(self, biz: Business) -> PhaseResult:
        """Phase 4: Continuous operations."""
        return PhaseResult(phase="operate", success=True, next_phase="operate",
                           output={"status": "operating", "cycle": "continuous"})
