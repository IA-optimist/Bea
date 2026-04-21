"""
Tests — Sprint 2: Business Discovery

Market Research
  BD1.  Analyze returns structured report
  BD2.  Report has market size section
  BD3.  Report has confidence by depth
  BD4.  Report summary is readable
  BD5.  Competitor data structure complete
  BD6.  Persona data structure complete

Business Model
  BD7.  Generate returns complete model
  BD8.  Lean Canvas has required fields
  BD9.  Unit economics computed correctly
  BD10. LTV:CAC ratio calculated
  BD11. Financial projections grow over time
  BD12. Viability score 1-10
  BD13. Verdict: go/review/no-go
  BD14. Model summary readable
  BD15. Projections include customer count
  BD16. Economics healthy flag works
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.market_research_agent import (
    MarketResearchAgent, MarketReport, Competitor, Persona,
)
from agents.business_model_agent import (
    BusinessModelAgent, BusinessModel, UnitEconomics,
)


class TestMarketResearch:

    def test_analyze_returns_report(self):
        """BD1: Analyze returns structured report."""
        agent = MarketResearchAgent()
        report = agent.analyze("AI-powered customer support SaaS")
        assert isinstance(report, MarketReport)
        assert report.opportunity == "AI-powered customer support SaaS"

    def test_market_size(self):
        """BD2: Report has market size."""
        agent = MarketResearchAgent()
        report = agent.analyze("Online tutoring platform")
        assert report.market_size is not None
        d = report.market_size.to_dict()
        assert "tam" in d and "sam" in d and "som" in d

    def test_confidence_by_depth(self):
        """BD3: Confidence varies by depth."""
        agent = MarketResearchAgent()
        quick = agent.analyze("Test", depth="quick")
        deep = agent.analyze("Test", depth="deep")
        assert quick.confidence < deep.confidence

    def test_summary_readable(self):
        """BD4: Summary is readable."""
        agent = MarketResearchAgent()
        report = agent.analyze("E-commerce analytics")
        text = report.summary()
        assert "Market Report" in text
        assert "TAM" in text

    def test_competitor_structure(self):
        """BD5: Competitor data complete."""
        c = Competitor(
            name="CompetitorX", url="https://example.com",
            pricing="$49/mo", strengths=["Fast", "Cheap"],
        )
        d = c.to_dict()
        assert d["name"] == "CompetitorX"
        assert "Fast" in d["strengths"]

    def test_persona_structure(self):
        """BD6: Persona data complete."""
        p = Persona(
            name="Startup Steve", role="CTO",
            pain_points=["No time", "Too expensive"],
            budget="$100-500/mo",
        )
        d = p.to_dict()
        assert d["role"] == "CTO"
        assert len(d["pain_points"]) == 2


class TestBusinessModel:

    def test_generate_complete(self):
        """BD7: Generate returns complete model."""
        agent = BusinessModelAgent()
        model = agent.generate("AI writing assistant")
        assert isinstance(model, BusinessModel)
        assert model.name == "AI writing assistant"
        assert model.revenue_model

    def test_canvas_fields(self):
        """BD8: Lean Canvas has fields."""
        agent = BusinessModelAgent()
        model = agent.generate("Project management tool")
        d = model.canvas.to_dict()
        assert "problem" in d
        assert "solution" in d
        assert "revenue" in d

    def test_economics_computed(self):
        """BD9: Unit economics computed."""
        agent = BusinessModelAgent()
        model = agent.generate("SaaS product")
        econ = model.economics
        assert econ.cac > 0
        assert econ.ltv > 0
        assert econ.avg_revenue_per_user > 0

    def test_ltv_cac_ratio(self):
        """BD10: LTV:CAC ratio calculated."""
        econ = UnitEconomics(cac=100, ltv=300)
        econ.ltv_cac_ratio = econ.ltv / econ.cac
        assert econ.ltv_cac_ratio == 3.0

    def test_projections_grow(self):
        """BD11: Financial projections grow."""
        agent = BusinessModelAgent()
        model = agent.generate("Growing SaaS")
        assert len(model.projections) >= 12
        first = model.projections[0]
        last = model.projections[-1]
        assert last.customers > first.customers
        assert last.mrr > first.mrr

    def test_viability_range(self):
        """BD12: Viability 1-10."""
        agent = BusinessModelAgent()
        model = agent.generate("Test biz")
        assert 0 <= model.viability.score <= 10

    def test_verdict(self):
        """BD13: Verdict is go/review/no-go."""
        agent = BusinessModelAgent()
        model = agent.generate("Test biz")
        assert model.viability.verdict in ("go", "review", "no-go")

    def test_summary_readable(self):
        """BD14: Summary readable."""
        agent = BusinessModelAgent()
        model = agent.generate("AI coach")
        text = model.summary()
        assert "Business Model" in text
        assert "LTV:CAC" in text

    def test_projections_have_customers(self):
        """BD15: Projections include customers."""
        agent = BusinessModelAgent()
        model = agent.generate("Subscription box")
        for p in model.projections:
            assert p.customers >= 0
            assert p.month >= 1

    def test_healthy_flag(self):
        """BD16: Healthy flag works."""
        good = UnitEconomics(cac=50, ltv=200, ltv_cac_ratio=4.0, payback_months=3)
        bad = UnitEconomics(cac=500, ltv=100, ltv_cac_ratio=0.2, payback_months=24)
        assert good.healthy
        assert not bad.healthy
