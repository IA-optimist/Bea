"""
tests/test_economic_cognition.py — Economic cognition layer tests.

Covers all 6 phases:
  A: Economic output parsing + validation
  B: Strategic memory
  C: Playbook composition
  D: Strategy evaluation
  E: Economic KPI metrics
  F: Decision traceability
"""


# ══════════════════════════════════════════════════════════════
# Phase A — Economic Output Reliability
# ══════════════════════════════════════════════════════════════

class TestEconomicOutput:

    def test_EI01_playbook_schema_mapping(self):
        """All 6 playbooks map to a schema type."""
        from core.economic.economic_output import PLAYBOOK_SCHEMA_MAP
        assert len(PLAYBOOK_SCHEMA_MAP) == 6
        assert PLAYBOOK_SCHEMA_MAP["market_analysis"] == "OpportunityReport"
        assert PLAYBOOK_SCHEMA_MAP["product_creation"] == "BusinessConcept"
        assert PLAYBOOK_SCHEMA_MAP["growth_experiment"] == "VenturePlan"

    def test_EI02_validate_complete_report(self):
        from core.economic.economic_output import validate_economic_output
        data = {
            "problem_description": "SMBs need invoicing",
            "pain_intensity": 0.8,
            "confidence": 0.7,
        }
        result = validate_economic_output(data, "OpportunityReport")
        assert result["valid"] is True
        assert result["completeness"] == 1.0

    def test_EI03_validate_missing_fields(self):
        from core.economic.economic_output import validate_economic_output
        result = validate_economic_output({}, "OpportunityReport")
        assert result["valid"] is False
        assert result["completeness"] == 0.0
        assert len(result["issues"]) >= 3

    def test_EI04_validate_low_confidence(self):
        from core.economic.economic_output import validate_economic_output
        data = {"problem_description": "x", "pain_intensity": 0.5,
                "confidence": 0.05}
        result = validate_economic_output(data, "OpportunityReport")
        assert any("confidence" in i for i in result["issues"])

    def test_EI05_assemble_from_steps(self):
        from core.economic.economic_output import assemble_economic_output
        steps = [
            {"skill_id": "market_research.basic", "content": {
                "tam": "$500M", "problems": "Manual invoicing is slow",
                "risks": ["Saturated market"],
            }},
            {"skill_id": "persona.basic", "content": {
                "persona": ["Freelancers", "Small agencies"],
            }},
        ]
        result = assemble_economic_output("market_analysis", steps)
        assert result["schema"] == "OpportunityReport"
        assert result["data"].get("market_size_estimate") == "$500M"
        assert result["data"].get("problem_description") == "Manual invoicing is slow"

    def test_EI06_assemble_unknown_playbook(self):
        from core.economic.economic_output import assemble_economic_output
        result = assemble_economic_output("unknown_pb", [])
        assert result["schema"] == ""
        assert result["validation"]["valid"] is False

    def test_EI07_validation_fail_open(self):
        from core.economic.economic_output import validate_economic_output
        # Should never crash, even with bad input
        result = validate_economic_output(None, "OpportunityReport")
        assert result["valid"] is False

    def test_EI08_skill_schema_fields_exist(self):
        """All mapped skills have field mappings."""
        from core.economic.economic_output import SKILL_SCHEMA_FIELDS
        assert len(SKILL_SCHEMA_FIELDS) >= 12


# ══════════════════════════════════════════════════════════════
# Phase B — Strategic Memory
# ══════════════════════════════════════════════════════════════

class TestStrategicMemory:

    def _fresh_store(self):
        import tempfile
        from pathlib import Path
        from core.economic.strategic_memory import StrategicMemoryStore
        return StrategicMemoryStore(store_path=Path(tempfile.mktemp(suffix=".json")))

    def test_EI09_record_and_query(self):
        from core.economic.strategic_memory import StrategicRecord
        store = self._fresh_store()
        store.record(StrategicRecord(
            strategy_type="market_analysis",
            playbook_id="market_analysis",
            outcome_score=0.8,
            goal="Analyze AI chatbot market",
        ))
        results = store.query(strategy_type="market_analysis")
        assert len(results) == 1
        assert results[0].outcome_score == 0.8

    def test_EI10_query_min_score(self):
        from core.economic.strategic_memory import StrategicRecord
        store = self._fresh_store()
        store.record(StrategicRecord(strategy_type="x", outcome_score=0.3))
        store.record(StrategicRecord(strategy_type="x", outcome_score=0.8))
        results = store.query(strategy_type="x", min_score=0.5)
        assert len(results) == 1
        assert results[0].outcome_score == 0.8

    def test_EI11_find_similar(self):
        from core.economic.strategic_memory import StrategicRecord
        store = self._fresh_store()
        store.record(StrategicRecord(
            strategy_type="market_analysis",
            goal="Analyze AI chatbot market",
            outcome_score=0.9,
        ))
        similar = store.find_similar("AI chatbot market analysis")
        assert len(similar) >= 1
        assert similar[0]["similarity"] > 0.1

    def test_EI12_strategy_stats(self):
        from core.economic.strategic_memory import StrategicRecord
        store = self._fresh_store()
        store.record(StrategicRecord(strategy_type="x", outcome_score=0.6))
        store.record(StrategicRecord(strategy_type="x", outcome_score=0.8))
        stats = store.get_strategy_stats("x")
        assert stats["count"] == 2
        assert abs(stats["avg_score"] - 0.7) < 0.01

    def test_EI13_persistence_roundtrip(self):
        import tempfile
        from pathlib import Path
        from core.economic.strategic_memory import StrategicMemoryStore, StrategicRecord

        path = Path(tempfile.mktemp(suffix=".json"))
        store1 = StrategicMemoryStore(store_path=path)
        store1.record(StrategicRecord(
            strategy_type="test", outcome_score=0.7, goal="persist me",
        ))

        store2 = StrategicMemoryStore(store_path=path)
        assert store2.count == 1
        assert store2.query()[0].goal == "persist me"

    def test_EI14_get_all_stats(self):
        from core.economic.strategic_memory import StrategicRecord
        store = self._fresh_store()
        store.record(StrategicRecord(strategy_type="a", outcome_score=0.5))
        store.record(StrategicRecord(strategy_type="b", outcome_score=0.9))
        stats = store.get_all_stats()
        assert len(stats) == 2

    def test_EI15_record_auto_id(self):
        from core.economic.strategic_memory import StrategicRecord
        store = self._fresh_store()
        rec = StrategicRecord(strategy_type="x", outcome_score=0.5)
        store.record(rec)
        assert rec.record_id.startswith("sr-")


# ══════════════════════════════════════════════════════════════
# Phase C — Playbook Composition
# ══════════════════════════════════════════════════════════════

class TestPlaybookComposition:

    def test_EI16_validate_valid_chain(self):
        from core.economic.playbook_composition import (
            PlaybookChain, CompositionStep, validate_chain
        )
        chain = PlaybookChain(
            name="Test Chain",
            steps=[
                CompositionStep(playbook_id="market_analysis"),
                CompositionStep(playbook_id="product_creation"),
                CompositionStep(playbook_id="growth_experiment"),
            ],
        )
        result = validate_chain(chain)
        assert result["valid"] is True
        assert len(result["bridges"]) == 2

    def test_EI17_validate_invalid_chain(self):
        from core.economic.playbook_composition import (
            PlaybookChain, CompositionStep, validate_chain
        )
        chain = PlaybookChain(
            steps=[
                CompositionStep(playbook_id="growth_experiment"),
                CompositionStep(playbook_id="market_analysis"),  # cannot feed back
            ],
        )
        result = validate_chain(chain)
        assert result["valid"] is False
        assert len(result["issues"]) >= 1

    def test_EI18_map_outputs_to_inputs(self):
        from core.economic.playbook_composition import map_outputs_to_inputs
        outputs = {
            "target_users": ["freelancers"],
            "problem_description": "slow invoicing",
            "market_size_estimate": "$500M",
        }
        mapped = map_outputs_to_inputs("market_analysis", "product_creation", outputs)
        assert "audience" in mapped
        assert "business_context" in mapped

    def test_EI19_builtin_chains_exist(self):
        from core.economic.playbook_composition import BUILT_IN_CHAINS
        assert "venture_creation" in BUILT_IN_CHAINS
        assert "offer_launch" in BUILT_IN_CHAINS

    def test_EI20_venture_chain_valid(self):
        from core.economic.playbook_composition import BUILT_IN_CHAINS, validate_chain
        chain = BUILT_IN_CHAINS["venture_creation"]
        result = validate_chain(chain)
        assert result["valid"] is True
        assert result["step_count"] == 3

    def test_EI21_execute_chain(self):
        """Chain execution runs all steps."""
        from core.economic.playbook_composition import (
            PlaybookChain, CompositionStep, execute_chain
        )
        chain = PlaybookChain(
            steps=[
                CompositionStep(playbook_id="market_analysis"),
                CompositionStep(playbook_id="product_creation"),
            ],
        )
        result = execute_chain(chain, "Analyze AI market")
        assert result["ok"] is True
        assert result["steps_completed"] == 2
        assert len(result["results"]) == 2

    def test_EI22_invalid_chain_fails_fast(self):
        from core.economic.playbook_composition import (
            PlaybookChain, CompositionStep, execute_chain
        )
        chain = PlaybookChain(
            steps=[
                CompositionStep(playbook_id="growth_experiment"),
                CompositionStep(playbook_id="market_analysis"),
            ],
        )
        result = execute_chain(chain, "test")
        assert result["ok"] is False
        assert "Invalid chain" in result.get("error", "")


# ══════════════════════════════════════════════════════════════
# Phase D — Strategy Evaluation
# ══════════════════════════════════════════════════════════════

class TestStrategyEvaluation:

    def test_EI23_evaluate_strategy(self):
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        result = evaluator.evaluate("market_analysis")
        assert "score" in result.to_dict()
        assert "trend" in result.to_dict()
        assert "recommendations" in result.to_dict()

    def test_EI24_evaluate_all(self):
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        results = evaluator.evaluate_all()
        assert len(results) >= 6  # 6 playbook types
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_EI25_suggest_no_history(self):
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        rec = evaluator.suggest_next_playbook("Completely new domain")
        assert rec is not None
        assert rec.recommendation_type == "use_playbook"

    def test_EI26_routing_hints(self):
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        hints = evaluator.get_routing_hints("market_analysis")
        assert "strategy_score" in hints
        assert "trend" in hints

    def test_EI27_evaluation_has_recommendations(self):
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        result = evaluator.evaluate("market_analysis")
        # Should have at least one recommendation (even if "no data, try it")
        assert len(result.recommendations) >= 1

    def test_EI28_recommendation_serializable(self):
        from core.economic.strategy_evaluation import StrategyRecommendation
        rec = StrategyRecommendation(
            recommendation_type="use_playbook",
            playbook_id="market_analysis",
            confidence=0.8,
            rationale="Strong performance",
        )
        d = rec.to_dict()
        assert d["recommendation_type"] == "use_playbook"
        assert d["confidence"] == 0.8


# ══════════════════════════════════════════════════════════════
# Phase E — Economic Metrics
# ══════════════════════════════════════════════════════════════

class TestEconomicMetrics:

    def test_EI29_create_roi_kpi(self):
        from core.economic.economic_metrics import create_roi_kpi
        kpi = create_roi_kpi(target_percent=200, current=50)
        d = kpi.to_dict()
        assert d["kpi_type"] == "roi"
        assert d["name"] == "expected_roi"
        assert d["target_value"] == 200
        assert d["progress"] == 0.25

    def test_EI30_create_payback_kpi(self):
        from core.economic.economic_metrics import create_payback_kpi
        kpi = create_payback_kpi(target_months=6, current=12)
        d = kpi.to_dict()
        assert d["kpi_type"] == "payback"
        assert d["direction"] == "down"  # lower is better
        assert d["progress"] == 0.5  # target=6, current=12: 6/12=0.5

    def test_EI31_create_cac_kpi(self):
        from core.economic.economic_metrics import create_cac_kpi
        kpi = create_cac_kpi(target_cost=50, current=100)
        d = kpi.to_dict()
        assert d["kpi_type"] == "cac"
        assert d["direction"] == "down"

    def test_EI32_create_ltv_kpi(self):
        from core.economic.economic_metrics import create_ltv_kpi
        kpi = create_ltv_kpi(target_value=1000, current=500)
        assert kpi.metric.progress == 0.5

    def test_EI33_create_mrr_kpi(self):
        from core.economic.economic_metrics import create_mrr_kpi
        kpi = create_mrr_kpi(target_mrr=10000, current=5000)
        d = kpi.to_dict()
        assert d["kpi_type"] == "mrr"
        assert d["time_period"] == "monthly"

    def test_EI34_set_economic_kpis(self):
        from core.economic.economic_metrics import (
            create_roi_kpi, create_mrr_kpi, set_economic_kpis,
        )
        kpis = [
            create_roi_kpi(200),
            create_mrr_kpi(10000),
        ]
        result = set_economic_kpis("test-obj", kpis)
        assert result is True

    def test_EI35_kpi_roundtrip(self):
        from core.economic.economic_metrics import EconomicKPI, create_margin_kpi
        kpi = create_margin_kpi(target_percent=60, current=30, margin_type="gross")
        d = kpi.to_dict()
        kpi2 = EconomicKPI.from_dict(d)
        assert kpi2.kpi_type == "margin"
        assert kpi2.metric.target_value == 60


# ══════════════════════════════════════════════════════════════
# Phase F — Decision Traceability
# ══════════════════════════════════════════════════════════════

class TestDecisionTrace:

    def test_EI36_trace_validation(self):
        from core.economic.decision_trace import DecisionTrace
        trace = DecisionTrace(
            rationale="Market is growing",
            assumptions=["TAM $500M"],
            confidence=0.8,
        )
        assert trace.validate() == []
        assert trace.trace_id.startswith("dt-")

    def test_EI37_trace_validation_catches_missing(self):
        from core.economic.decision_trace import DecisionTrace
        trace = DecisionTrace()
        errors = trace.validate()
        assert len(errors) >= 2  # rationale + assumptions

    def test_EI38_build_trace_from_opportunity(self):
        from core.economic.decision_trace import build_trace_from_output
        data = {
            "report_id": "opp-test",
            "feasibility_reasoning": "Large growing market",
            "market_size_estimate": "$500M",
            "pain_intensity": 0.8,
            "risk_flags": ["Regulatory risk"],
            "confidence": 0.7,
            "data_sources": ["Market reports"],
        }
        trace = build_trace_from_output("OpportunityReport", data, {})
        assert trace.rationale == "Large growing market"
        assert trace.confidence == 0.7
        assert len(trace.risk_factors) >= 1
        assert "opp-test" in trace.schema_ref

    def test_EI39_build_trace_from_concept(self):
        from core.economic.decision_trace import build_trace_from_output
        data = {
            "concept_id": "biz-test",
            "differentiation_hypothesis": "AI-powered automation",
            "target_segment": "SMBs",
            "delivery_mechanism": "SaaS",
            "revenue_logic": "subscription",
        }
        trace = build_trace_from_output("BusinessConcept", data, {})
        assert trace.rationale == "AI-powered automation"
        assert len(trace.assumptions) >= 3

    def test_EI40_enrich_output(self):
        from core.economic.decision_trace import (
            DecisionTrace, enrich_output_with_trace,
        )
        output = {"ok": True, "data": {"some": "result"}}
        trace = DecisionTrace(rationale="test", assumptions=["a"])
        enriched = enrich_output_with_trace(output, trace)
        assert "decision_trace" in enriched
        assert enriched["decision_trace"]["rationale"] == "test"
        # Original not modified
        assert "decision_trace" not in output

    def test_EI41_trace_roundtrip(self):
        from core.economic.decision_trace import DecisionTrace
        trace = DecisionTrace(
            decision_type="opportunity_selected",
            rationale="High viability",
            assumptions=["Growing market"],
            risk_factors=["Competition"],
            confidence=0.75,
        )
        d = trace.to_dict()
        trace2 = DecisionTrace.from_dict(d)
        assert trace2.rationale == trace.rationale
        assert trace2.confidence == trace.confidence

    def test_EI42_trace_fail_open(self):
        """build_trace_from_output never crashes."""
        from core.economic.decision_trace import build_trace_from_output
        # Bad data
        trace = build_trace_from_output("UnknownSchema", {}, {})
        assert trace is not None
        assert trace.trace_id.startswith("dt-")


# ══════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════

class TestIntegration:

    def test_EI43_playbook_execution_still_works(self):
        """No regression in basic playbook execution."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test integration")
        assert result["ok"] is True
        assert result["run"]["steps_completed"] == 4

    def test_EI44_economic_output_from_simulated_run(self):
        """Can assemble economic output from simulated skill outputs."""
        from core.economic.economic_output import assemble_economic_output

        # Simulate what a real LLM-backed run would produce
        step_outputs = [
            {"skill_id": "market_research.basic", "invoked": True, "content": {
                "tam": "$2B", "problems": "Manual invoicing wastes 10hrs/week",
                "opportunities": "AI automation", "risks": ["Market saturation"],
                "trends": "Growing 20% YoY",
            }},
            {"skill_id": "persona.basic", "invoked": True, "content": {
                "persona": ["Freelancers", "Agencies"], "pain_points": ["Slow", "Expensive"],
            }},
            {"skill_id": "competitor.analysis", "invoked": True, "content": {
                "competitors": "FreshBooks, QuickBooks, Wave",
                "gaps": "No AI-powered automation",
            }},
            {"skill_id": "positioning.basic", "invoked": True, "content": {
                "positioning_statement": "AI-first invoicing for modern freelancers",
                "unique_attributes": "Zero-click invoice generation",
            }},
        ]

        assembled = assemble_economic_output("market_analysis", step_outputs)
        assert assembled["schema"] == "OpportunityReport"
        assert assembled["source_steps"] == 4
        assert assembled["data"].get("market_size_estimate") == "$2B"
        assert assembled["data"].get("problem_description") == "Manual invoicing wastes 10hrs/week"

    def test_EI45_full_pipeline_trace(self):
        """Can build decision trace from assembled output."""
        from core.economic.economic_output import assemble_economic_output
        from core.economic.decision_trace import build_trace_from_output

        assembled = assemble_economic_output("market_analysis", [
            {"skill_id": "market_research.basic", "content": {
                "tam": "$500M", "problems": "Slow process",
            }},
        ])
        trace = build_trace_from_output(
            assembled["schema"],
            assembled["data"],
            assembled["validation"],
        )
        assert trace.decision_type == "opportunityreport_generated"
        assert trace.trace_id.startswith("dt-")
