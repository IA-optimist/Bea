"""
tests/test_economic_contracts.py — Economic intelligence layer tests.

Validates:
  - Schema structure and validation
  - Serialization round-trips
  - Capability cluster registration
  - Identity map skill→capability routing
  - Integration with playbooks/missions
  - Safety constraints (advisory-only)
  - Fail-open behavior
"""
from kernel.contracts.economic import (
    OpportunityReport, BusinessConcept, VenturePlan, Milestone,
    FinancialModel, ComplianceChecklist, ComplianceItem,
    ECONOMIC_SCHEMAS, parse_economic_output,
)


# ══════════════════════════════════════════════════════════════
# OpportunityReport
# ══════════════════════════════════════════════════════════════

class TestOpportunityReport:

    def test_EC01_valid_report(self):
        r = OpportunityReport(
            problem_description="SMBs struggle with invoicing",
            target_users=["freelancers", "small agencies"],
            pain_intensity=0.8,
            market_size_estimate="~$2B TAM",
            confidence=0.7,
        )
        assert r.validate() == []
        assert r.report_id.startswith("opp-")

    def test_EC02_validation_catches_errors(self):
        r = OpportunityReport(pain_intensity=1.5, confidence=-0.1)
        errors = r.validate()
        assert len(errors) >= 2  # problem + pain + confidence

    def test_EC03_viability_score(self):
        r = OpportunityReport(
            problem_description="x",
            pain_intensity=0.9,
            estimated_difficulty=0.2,
            confidence=0.8,
        )
        # 0.4*0.9 + 0.3*0.8 + 0.3*0.8 = 0.36 + 0.24 + 0.24 = 0.84
        assert abs(r.viability_score - 0.84) < 0.01

    def test_EC04_roundtrip(self):
        r = OpportunityReport(
            problem_description="test problem",
            target_users=["devs"],
            pain_intensity=0.7,
            market_size_estimate="$500M",
            risk_flags=["regulatory risk"],
        )
        d = r.to_dict()
        assert d["schema"] == "OpportunityReport"
        r2 = OpportunityReport.from_dict(d)
        assert r2.problem_description == r.problem_description
        assert r2.pain_intensity == r.pain_intensity
        assert r2.risk_flags == r.risk_flags

    def test_EC05_truncation(self):
        """Long fields are truncated in serialization."""
        r = OpportunityReport(
            problem_description="x",
            competition_overview="y" * 1000,
            feasibility_reasoning="z" * 1000,
        )
        d = r.to_dict()
        assert len(d["competition_overview"]) <= 500
        assert len(d["feasibility_reasoning"]) <= 500


# ══════════════════════════════════════════════════════════════
# BusinessConcept
# ══════════════════════════════════════════════════════════════

class TestBusinessConcept:

    def test_EC06_valid_concept(self):
        c = BusinessConcept(
            value_proposition="Automated invoicing for freelancers",
            target_segment="Freelancers earning $50k-200k/year",
            solution_description="SaaS tool with AI-generated invoices",
            delivery_mechanism="SaaS",
            revenue_logic="subscription",
        )
        assert c.validate() == []
        assert c.concept_id.startswith("biz-")

    def test_EC07_validation_catches_missing(self):
        c = BusinessConcept()
        errors = c.validate()
        assert len(errors) == 3  # value_prop + target + solution

    def test_EC08_roundtrip(self):
        c = BusinessConcept(
            value_proposition="Fast invoicing",
            target_segment="Freelancers",
            solution_description="AI invoices",
            scalability_potential="high",
            opportunity_report_id="opp-abc123",
        )
        d = c.to_dict()
        assert d["schema"] == "BusinessConcept"
        c2 = BusinessConcept.from_dict(d)
        assert c2.opportunity_report_id == "opp-abc123"
        assert c2.scalability_potential == "high"

    def test_EC09_links_to_report(self):
        """Concept can reference its source opportunity report."""
        c = BusinessConcept(
            value_proposition="x",
            target_segment="y",
            solution_description="z",
            opportunity_report_id="opp-test123",
        )
        d = c.to_dict()
        assert d["opportunity_report_id"] == "opp-test123"


# ══════════════════════════════════════════════════════════════
# VenturePlan
# ══════════════════════════════════════════════════════════════

class TestVenturePlan:

    def test_EC10_valid_plan(self):
        vp = VenturePlan(
            mvp_scope="Landing page + waitlist + 3 demo scenarios",
            milestones=[
                Milestone(name="Validate demand", target_week=2,
                         validation_criteria="100 signups"),
                Milestone(name="Build MVP", target_week=6,
                         validation_criteria="Working prototype"),
            ],
            estimated_timeline_weeks=8,
            execution_risks=["Technical complexity", "Market timing"],
            playbook_ids=["market_analysis", "product_creation"],
        )
        assert vp.validate() == []
        assert vp.plan_id.startswith("vp-")

    def test_EC11_validation_catches_missing(self):
        vp = VenturePlan()
        errors = vp.validate()
        assert len(errors) >= 3  # mvp + milestones + timeline

    def test_EC12_roundtrip(self):
        vp = VenturePlan(
            concept_id="biz-abc",
            mvp_scope="MVP scope",
            milestones=[Milestone(name="M1", target_week=4)],
            estimated_timeline_weeks=4,
            playbook_ids=["market_analysis"],
        )
        d = vp.to_dict()
        assert d["schema"] == "VenturePlan"
        vp2 = VenturePlan.from_dict(d)
        assert len(vp2.milestones) == 1
        assert vp2.milestones[0].name == "M1"
        assert vp2.playbook_ids == ["market_analysis"]

    def test_EC13_milestone_roundtrip(self):
        m = Milestone(name="Launch", target_week=8,
                     validation_criteria="First paying user", status="pending")
        d = m.to_dict()
        m2 = Milestone.from_dict(d)
        assert m2.name == "Launch"
        assert m2.target_week == 8


# ══════════════════════════════════════════════════════════════
# FinancialModel
# ══════════════════════════════════════════════════════════════

class TestFinancialModel:

    def test_EC14_valid_model(self):
        fm = FinancialModel(
            pricing_logic="Freemium with $29/mo pro tier",
            cost_estimation={"hosting": "$50/mo", "api_calls": "$200/mo"},
            break_even_estimate="~150 paying users",
            expected_margin="high (>60%)",
            sensitivity_assumptions=["Conversion rate 3-5%", "Churn <5%/mo"],
        )
        assert fm.validate() == []
        assert fm.model_id.startswith("fin-")

    def test_EC15_validation_catches_missing(self):
        fm = FinancialModel()
        errors = fm.validate()
        assert len(errors) >= 2  # pricing + assumptions

    def test_EC16_roundtrip(self):
        fm = FinancialModel(
            concept_id="biz-abc",
            pricing_logic="$29/mo",
            cost_estimation={"hosting": "$50"},
            sensitivity_assumptions=["conversion 3%"],
        )
        d = fm.to_dict()
        assert d["schema"] == "FinancialModel"
        fm2 = FinancialModel.from_dict(d)
        assert fm2.pricing_logic == "$29/mo"
        assert fm2.cost_estimation == {"hosting": "$50"}


# ══════════════════════════════════════════════════════════════
# ComplianceChecklist
# ══════════════════════════════════════════════════════════════

class TestComplianceChecklist:

    def test_EC17_valid_checklist(self):
        cc = ComplianceChecklist(
            jurisdiction_assumptions=["EU (GDPR)", "US (CCPA)"],
            items=[
                ComplianceItem(area="data_privacy", description="User data collection",
                              risk_level="high", requires_human_validation=True),
                ComplianceItem(area="tax", description="Sales tax obligations",
                              risk_level="medium"),
            ],
        )
        assert cc.validate() == []
        assert cc.checklist_id.startswith("cpl-")

    def test_EC18_always_requires_human(self):
        """human_validation_required is ALWAYS True, cannot be overridden."""
        cc = ComplianceChecklist(
            jurisdiction_assumptions=["US"],
            items=[ComplianceItem(area="x", description="y")],
            human_validation_required=False,
        )
        assert cc.human_validation_required is True
        d = cc.to_dict()
        assert d["human_validation_required"] is True

    def test_EC19_has_disclaimer(self):
        cc = ComplianceChecklist()
        assert "NOT legal advice" in cc.disclaimer

    def test_EC20_roundtrip(self):
        cc = ComplianceChecklist(
            concept_id="biz-abc",
            jurisdiction_assumptions=["EU"],
            items=[ComplianceItem(area="gdpr", description="Data processing")],
            risk_flags=["Cross-border data transfer"],
        )
        d = cc.to_dict()
        assert d["schema"] == "ComplianceChecklist"
        cc2 = ComplianceChecklist.from_dict(d)
        assert len(cc2.items) == 1
        assert cc2.items[0].area == "gdpr"


# ══════════════════════════════════════════════════════════════
# Schema Registry
# ══════════════════════════════════════════════════════════════

class TestSchemaRegistry:

    def test_EC21_all_5_schemas_registered(self):
        assert len(ECONOMIC_SCHEMAS) == 5
        expected = {"OpportunityReport", "BusinessConcept", "VenturePlan",
                    "FinancialModel", "ComplianceChecklist"}
        assert set(ECONOMIC_SCHEMAS.keys()) == expected

    def test_EC22_parse_opportunity(self):
        data = {"schema": "OpportunityReport", "problem_description": "test",
                "pain_intensity": 0.8}
        obj = parse_economic_output(data)
        assert isinstance(obj, OpportunityReport)
        assert obj.pain_intensity == 0.8

    def test_EC23_parse_unknown_returns_none(self):
        assert parse_economic_output({"schema": "UnknownSchema"}) is None
        assert parse_economic_output({}) is None


# ══════════════════════════════════════════════════════════════
# Capability Clusters
# ══════════════════════════════════════════════════════════════

class TestCapabilityClusters:

    def test_EC24_7_economic_capabilities(self):
        """All 7 economic capabilities registered in kernel."""
        from kernel.capabilities.registry import get_capability_registry
        reg = get_capability_registry()
        economic = reg.list_by_category("economic")
        ids = {c.id for c in economic}
        expected = {"market_intelligence", "product_design", "financial_reasoning",
                    "compliance_reasoning", "risk_assessment", "venture_planning",
                    "strategy_reasoning"}
        assert ids == expected

    def test_EC25_compliance_is_medium_risk(self):
        from kernel.capabilities.registry import get_capability_registry
        reg = get_capability_registry()
        cap = reg.get("compliance_reasoning")
        assert cap is not None
        assert cap.risk_level == "medium"

    def test_EC26_all_have_providers(self):
        from kernel.capabilities.registry import get_capability_registry
        reg = get_capability_registry()
        for cap in reg.list_by_category("economic"):
            assert len(cap.providers) >= 1, f"{cap.id} has no providers"


# ══════════════════════════════════════════════════════════════
# Identity Map — Skill → Capability Routing
# ══════════════════════════════════════════════════════════════

class TestIdentityRouting:

    def test_EC27_market_research_routes_to_market_intelligence(self):
        from kernel.capabilities.identity import CapabilityIdentityMap
        im = CapabilityIdentityMap()
        im._populated = False
        result = im.resolve_tool("market_research.basic")
        assert "market_intelligence" in result["capability_ids"]

    def test_EC28_pricing_routes_to_financial_reasoning(self):
        from kernel.capabilities.identity import CapabilityIdentityMap
        im = CapabilityIdentityMap()
        im._populated = False
        result = im.resolve_tool("pricing.strategy")
        assert "financial_reasoning" in result["capability_ids"]

    def test_EC29_strategy_routes_to_strategy_reasoning(self):
        from kernel.capabilities.identity import CapabilityIdentityMap
        im = CapabilityIdentityMap()
        im._populated = False
        result = im.resolve_tool("strategy.reasoning")
        assert "strategy_reasoning" in result["capability_ids"]

    def test_EC30_spec_routes_to_venture_planning(self):
        from kernel.capabilities.identity import CapabilityIdentityMap
        im = CapabilityIdentityMap()
        im._populated = False
        result = im.resolve_tool("spec.writing")
        assert "venture_planning" in result["capability_ids"]


# ══════════════════════════════════════════════════════════════
# Playbook Integration
# ══════════════════════════════════════════════════════════════

class TestPlaybookIntegration:

    def test_EC31_playbook_execution_produces_output(self):
        """Market analysis playbook executes and produces step results."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Analyze AI chatbot market")
        assert result["ok"] is True
        assert result["run"]["steps_completed"] == 4

    def test_EC32_schemas_usable_as_step_output(self):
        """Economic schemas can be serialized as step output dictionaries."""
        report = OpportunityReport(
            problem_description="Test",
            pain_intensity=0.8,
            confidence=0.7,
        )
        # This is how PlanRunner stores step results
        step_result = {
            "ok": True,
            "output": report.to_dict(),
            "step_id": "test-step",
        }
        assert step_result["output"]["schema"] == "OpportunityReport"
        # Can be parsed back
        parsed = parse_economic_output(step_result["output"])
        assert isinstance(parsed, OpportunityReport)
        assert parsed.pain_intensity == 0.8


# ══════════════════════════════════════════════════════════════
# Safety
# ══════════════════════════════════════════════════════════════

class TestSafety:

    def test_EC33_compliance_always_disclaims(self):
        """ComplianceChecklist always includes disclaimer."""
        cc = ComplianceChecklist(
            jurisdiction_assumptions=["US"],
            items=[ComplianceItem(area="x", description="y")],
        )
        d = cc.to_dict()
        assert "NOT legal advice" in d["disclaimer"]

    def test_EC34_financial_model_is_heuristic(self):
        """FinancialModel schema field names signal heuristic nature."""
        fm = FinancialModel(
            pricing_logic="$29/mo",
            sensitivity_assumptions=["conversion 3%"],
        )
        d = fm.to_dict()
        # "estimate" and "heuristic" in field names
        assert "break_even_estimate" in d
        assert "sensitivity_assumptions" in d

    def test_EC35_schemas_are_advisory(self):
        """No schema contains execution/action fields."""
        for name, cls in ECONOMIC_SCHEMAS.items():
            obj = cls()
            d = obj.to_dict()
            # Should not have action/execute/deploy/send fields
            for key in d:
                assert "execute" not in key.lower(), f"{name} has execute field: {key}"
                assert "deploy" not in key.lower(), f"{name} has deploy field: {key}"
                assert "send" not in key.lower(), f"{name} has send field: {key}"

    def test_EC36_all_schemas_have_version(self):
        """All serialized schemas include version for future evolution."""
        for name, cls in ECONOMIC_SCHEMAS.items():
            obj = cls()
            d = obj.to_dict()
            assert "version" in d, f"{name} missing version field"
            assert d["version"] == "1.0"
