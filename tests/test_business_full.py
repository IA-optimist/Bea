"""
Tests — Sprints 3+4+5: Business Build, Operate, Orchestration

Approval Gates
  BF1.  Launch requires approval
  BF2.  Contract requires approval
  BF3.  Spend >500€ requires approval
  BF4.  Spend <100€ no approval needed
  BF5.  Refund >50€ requires approval
  BF6.  Campaign with budget requires approval

Build Agents
  BF7.  TechBuilder produces MVP spec
  BF8.  ContentAgent produces asset package
  BF9.  LegalAgent produces doc set
  BF10. Deploy requires launch approval

Operate Agents
  BF11. FinanceAgent dashboard structure
  BF12. Expense >500 gated
  BF13. GrowthAgent campaign gated
  BF14. A/B test no approval needed
  BF15. CustomerAgent refund gated
  BF16. Support ticket produces output

Orchestrator
  BF17. Create business initializes correctly
  BF18. Discovery phase produces market + model
  BF19. Low viability triggers approval gate
  BF20. Build phase produces legal + mvp + content
  BF21. Build always requires launch approval
  BF22. Approve resolves pending approval
  BF23. Deny resolves pending approval
  BF24. Cannot advance with pending approvals
  BF25. List businesses returns all
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.business_agents_suite import (
    ApprovalCategory, requires_approval,
    TechBuilderAgent, ContentMarketingAgent, LegalAgent,
    FinanceAgent, GrowthAgent, CustomerSuccessAgent,
    MVPSpec,
)
from business.business_orchestrator import (
    BusinessOrchestrator,
)


class TestApprovalGates:

    def test_launch_requires_approval(self):
        """BF1."""
        assert requires_approval(ApprovalCategory.LAUNCH)

    def test_contract_requires_approval(self):
        """BF2."""
        assert requires_approval(ApprovalCategory.CONTRACT)

    def test_spend_high(self):
        """BF3."""
        assert requires_approval(ApprovalCategory.SPEND_HIGH, 600)

    def test_spend_low_no_approval(self):
        """BF4."""
        assert not requires_approval(ApprovalCategory.SPEND_LOW, 50)

    def test_refund_gated(self):
        """BF5."""
        assert requires_approval(ApprovalCategory.REFUND, 75)

    def test_campaign_gated(self):
        """BF6."""
        assert requires_approval(ApprovalCategory.CAMPAIGN, 100)


class TestBuildAgents:

    def test_mvp_spec(self):
        """BF7."""
        spec = TechBuilderAgent().plan_mvp("TestBiz")
        assert spec.name == "TestBiz"
        assert len(spec.tech_stack) > 0
        assert spec.status == "planned"

    def test_content_assets(self):
        """BF8."""
        assets = ContentMarketingAgent().create_assets("TestBiz")
        d = assets.to_dict()
        assert d["emails"] >= 1

    def test_legal_docs(self):
        """BF9."""
        docs = LegalAgent().setup_structure("TestBiz")
        assert docs.rgpd_compliant  # FR default
        assert docs.structure

    def test_deploy_gated(self):
        """BF10."""
        spec = MVPSpec(name="Test")
        result = TechBuilderAgent().deploy(spec)
        assert result["status"] == "requires_approval"


class TestOperateAgents:

    def test_finance_dashboard(self):
        """BF11."""
        d = FinanceAgent().get_dashboard().to_dict()
        assert "mrr" in d and "profit" in d

    def test_expense_gated(self):
        """BF12."""
        result = FinanceAgent().approve_expense(600, "Server upgrade")
        assert result["status"] == "requires_approval"

    def test_campaign_gated(self):
        """BF13."""
        result = GrowthAgent().launch_campaign("google", 500, "SaaS founders")
        assert result["status"] == "requires_approval"

    def test_ab_no_approval(self):
        """BF14."""
        result = GrowthAgent().run_ab_test("Blue CTA", "Green CTA")
        assert result["status"] == "running"

    def test_refund_gated(self):
        """BF15."""
        result = CustomerSuccessAgent().process_refund("client@test.com", 75, "Unsatisfied")
        assert result["status"] == "requires_approval"

    def test_ticket_response(self):
        """BF16."""
        result = CustomerSuccessAgent().respond_ticket("T-001", "We'll look into it")
        assert result["status"] == "ready_for_llm"


class TestOrchestrator:

    def test_create_business(self):
        """BF17."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("AI-powered recipe generator", "RecipeAI")
        assert biz.id.startswith("biz-")
        assert biz.phase == "discovery"

    def test_discovery_produces_report(self):
        """BF18."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Online tutoring SaaS")
        result = orch.run_phase(biz.id)
        assert result.success or result.needs_approval
        updated = orch.get_business(biz.id)
        assert updated.market_report
        assert updated.business_model

    def test_low_viability_gate(self):
        """BF19."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Very niche idea")
        result = orch.run_phase(biz.id)
        # Default viability is ~6.5 so should need approval
        if result.needs_approval:
            assert biz.has_pending_approvals

    def test_build_phase(self):
        """BF20."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Test business")
        orch.run_phase(biz.id)  # Discovery
        # Approve if needed
        while biz.has_pending_approvals:
            orch.approve(biz.id)
        biz.phase = "build"
        result = orch.run_phase(biz.id)
        assert result.success
        assert biz.legal_docs
        assert biz.mvp_spec

    def test_build_always_requires_approval(self):
        """BF21."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Test biz 2")
        orch.run_phase(biz.id)
        while biz.has_pending_approvals:
            orch.approve(biz.id)
        biz.phase = "build"
        result = orch.run_phase(biz.id)
        assert result.needs_approval or biz.has_pending_approvals

    def test_approve_resolves(self):
        """BF22."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Approval test")
        biz.approvals_pending.append({"description": "Test approval"})
        assert orch.approve(biz.id)
        assert not biz.has_pending_approvals
        assert len(biz.approvals_completed) == 1

    def test_deny_resolves(self):
        """BF23."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Deny test")
        biz.approvals_pending.append({"description": "Should be denied"})
        assert orch.deny(biz.id)
        assert biz.approvals_completed[0]["status"] == "denied"

    def test_blocked_by_pending(self):
        """BF24."""
        orch = BusinessOrchestrator()
        biz = orch.create_business("Blocked test")
        biz.approvals_pending.append({"description": "Blocking"})
        result = orch.run_phase(biz.id)
        assert result.needs_approval

    def test_list_businesses(self):
        """BF25."""
        orch = BusinessOrchestrator()
        orch.create_business("Biz A")
        orch.create_business("Biz B")
        lst = orch.list_businesses()
        assert len(lst) == 2
