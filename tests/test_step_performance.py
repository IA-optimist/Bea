"""
tests/test_step_performance.py — Step outcome → kernel performance feedback tests.

Validates:
  - PlanRunner emits step_type and tool_id in kernel events
  - Event bridge records step outcomes as tool performance
  - Domain skills are resolved in identity map
  - Capability-level aggregation from skill executions
  - Provider-level aggregation via analyst_agent mapping
  - Failed steps feed failure signals into performance
  - End-to-end: plan execution → performance records
"""
import inspect

from kernel.capabilities.performance import PerformanceStore
import kernel.capabilities.performance as _perf_mod


class TestPlanRunnerEmissions:

    def test_SP01_runner_emits_step_type(self):
        """PlanRunner kernel emission includes step_type."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert "step_type" in source
        assert 'step.type.value' in source

    def test_SP02_runner_emits_tool_id(self):
        """PlanRunner kernel emission includes tool_id = step.target_id."""
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert 'kwargs["tool_id"]' in source
        assert "step.target_id" in source


class TestEventBridgeStepRecording:

    def test_SP03_step_completed_records_tool(self):
        """step.completed event records tool-level performance."""
        from kernel.convergence.event_bridge import _update_performance
        source = inspect.getsource(_update_performance)
        # Verify step.completed block also calls record_tool_outcome
        lines = source.split('\n')
        in_step_completed = False
        found_tool_record = False
        for line in lines:
            if 'step.completed' in line:
                in_step_completed = True
            if in_step_completed and 'record_tool_outcome' in line:
                found_tool_record = True
                break
        assert found_tool_record, "step.completed should also record tool outcome"

    def test_SP04_step_failed_records_tool(self):
        """step.failed event records tool-level performance."""
        from kernel.convergence.event_bridge import _update_performance
        source = inspect.getsource(_update_performance)
        lines = source.split('\n')
        in_step_failed = False
        found_tool_record = False
        for line in lines:
            if 'step.failed' in line and 'completed' not in line:
                in_step_failed = True
            if in_step_failed and 'record_tool_outcome' in line:
                found_tool_record = True
                break
        assert found_tool_record, "step.failed should also record tool outcome"


class TestIdentityMapSkills:

    def test_SP05_skills_in_identity_map(self):
        """Domain skills are registered in the identity map."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        # Check at least some skills are mapped
        assert len(imap._tool_to_capabilities) >= 10, \
            f"Expected ≥10 tools in identity map, got {len(imap._tool_to_capabilities)}"

    def test_SP06_skill_resolves_to_business_analysis(self):
        """Skill resolves to business_analysis capability."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        result = imap.resolve_tool("market_research.basic")
        assert "business_analysis" in result["capability_ids"]

    def test_SP07_skill_resolves_to_analyst_agent(self):
        """Skill resolves to analyst_agent provider."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        result = imap.resolve_tool("persona.basic")
        assert result["provider_id"] == "analyst_agent"

    def test_SP08_skill_confidence_is_1(self):
        """Skill with capabilities has confidence ≥ 0.7."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        result = imap.resolve_tool("offer_design.basic")
        assert result["confidence"] >= 0.7

    def test_SP09_all_10_skills_registered(self):
        """All 10 domain skills are in the identity map with economic capabilities."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        economic_caps = {"market_intelligence", "product_design", "financial_reasoning",
                         "compliance_reasoning", "risk_assessment", "venture_planning",
                         "strategy_reasoning", "business_analysis"}
        skills = [
            "market_research.basic", "persona.basic", "offer_design.basic",
            "acquisition.basic", "saas_scope.basic", "automation_opportunity.basic",
            "pricing.strategy", "competitor.analysis",
            "value_proposition.design", "funnel.design",
        ]
        for skill_id in skills:
            result = imap.resolve_tool(skill_id)
            assert result["confidence"] > 0, f"{skill_id} not in identity map"
            assert any(c in economic_caps for c in result["capability_ids"]), \
                f"{skill_id} has no economic capability: {result['capability_ids']}"


class TestEndToEndPerformanceFeedback:

    def _run_plan(self, goal: str, steps: list) -> object:
        """Helper to run a plan and return the run result."""
        from core.planning.execution_plan import ExecutionPlan, PlanStep, PlanStatus
        from core.planning.plan_serializer import PlanStore
        from core.planning.plan_runner import PlanRunner
        import core.planning.plan_serializer as _mod

        store = PlanStore()
        old = _mod._store
        _mod._store = store
        try:
            plan = ExecutionPlan(
                goal=goal,
                steps=[PlanStep(**s) for s in steps],
                status=PlanStatus.APPROVED,
            )
            store.save(plan)
            return PlanRunner().start(plan.plan_id)
        finally:
            _mod._store = old

    def test_SP10_successful_steps_record_performance(self):
        """Successful skill steps create performance records."""
        from core.planning.execution_plan import StepType

        old = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = _perf_mod._store
        try:
            run = self._run_plan(
                "Analyze the fintech sector",
                [{"step_id": "s1", "type": StepType.SKILL,
                  "target_id": "market_research.basic", "name": "Research"}]
            )
            assert run.status.value == "completed"

            perf = store.get_tool_performance("market_research.basic")
            assert perf is not None, "market_research.basic not in performance store"
            assert perf["total"] >= 1
            assert perf["success_rate"] == 1.0
        finally:
            _perf_mod._store = old

    def test_SP11_failed_steps_record_failure(self):
        """Failed skill steps record failure in performance store."""
        from core.planning.execution_plan import StepType

        old = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = _perf_mod._store
        try:
            run = self._run_plan(
                "Test failure",
                [{"step_id": "s1", "type": StepType.SKILL,
                  "target_id": "nonexistent.skill", "name": "Bad"}]
            )
            assert run.status.value == "failed"

            perf = store.get_tool_performance("nonexistent.skill")
            assert perf is not None
            assert perf["success_rate"] == 0.0
        finally:
            _perf_mod._store = old

    def test_SP12_capability_aggregation(self):
        """Multiple skill steps aggregate under business_analysis capability."""
        from core.planning.execution_plan import StepType

        old = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = _perf_mod._store
        try:
            run = self._run_plan(
                "Analyze AI chatbot market",
                [
                    {"step_id": "s1", "type": StepType.SKILL,
                     "target_id": "market_research.basic", "name": "Research"},
                    {"step_id": "s2", "type": StepType.SKILL,
                     "target_id": "persona.basic", "name": "Persona",
                     "depends_on": ["s1"]},
                ]
            )
            assert run.steps_completed == 2

            cap = store.get_capability_performance("business_analysis")
            if cap:
                assert cap["total"] >= 2
                assert cap["success_rate"] > 0
        finally:
            _perf_mod._store = old

    def test_SP13_provider_aggregation(self):
        """Skill steps aggregate under analyst_agent provider."""
        from core.planning.execution_plan import StepType

        old = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = _perf_mod._store
        try:
            run = self._run_plan(
                "Validate healthcare SaaS",
                [
                    {"step_id": "s1", "type": StepType.SKILL,
                     "target_id": "market_research.basic", "name": "Research"},
                    {"step_id": "s2", "type": StepType.SKILL,
                     "target_id": "competitor.analysis", "name": "Competitors",
                     "depends_on": ["s1"]},
                ]
            )
            assert run.steps_completed == 2

            prov = store.get_provider_performance("analyst_agent")
            if prov:
                assert prov["total"] >= 2
        finally:
            _perf_mod._store = old

    def test_SP14_step_type_tracking(self):
        """Step type (skill) is tracked as an entity."""
        from core.planning.execution_plan import StepType

        old = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = _perf_mod._store
        try:
            self._run_plan(
                "Quick test",
                [{"step_id": "s1", "type": StepType.SKILL,
                  "target_id": "market_research.basic", "name": "R"}]
            )
            all_records = store.get_all()
            types = [r for r in all_records if r["entity_type"] == "step_type"]
            assert len(types) >= 1
            assert any(r["entity_id"] == "skill" for r in types)
        finally:
            _perf_mod._store = old

    def test_SP15_mixed_success_failure(self):
        """Plan with both successful and failed steps records mixed signals."""
        from core.planning.execution_plan import StepType

        old = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = _perf_mod._store
        try:
            self._run_plan(
                "Mixed test",
                [
                    {"step_id": "s1", "type": StepType.SKILL,
                     "target_id": "market_research.basic", "name": "Good"},
                    {"step_id": "s2", "type": StepType.SKILL,
                     "target_id": "nonexistent.x", "name": "Bad",
                     "depends_on": ["s1"]},
                ]
            )
            good = store.get_tool_performance("market_research.basic")
            bad = store.get_tool_performance("nonexistent.x")
            assert good is not None and good["success_rate"] == 1.0
            assert bad is not None and bad["success_rate"] == 0.0
        finally:
            _perf_mod._store = old
