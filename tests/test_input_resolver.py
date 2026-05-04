"""
tests/test_input_resolver.py — Step input resolution tests.

Validates:
  - Goal extraction populates required skill inputs
  - Context propagation from previous steps
  - Semantic equivalences fill missing fields
  - Fallback to goal text when no pattern matches
  - Explicit step.inputs override everything
  - Empty goals don't crash
  - Full execution path completes with resolved inputs
"""


class TestGoalExtraction:

    def test_IR01_sector_from_goal(self):
        """Sector is extracted from 'in the X sector' pattern."""
        from core.planning.input_resolver import _extract_from_goal
        result = _extract_from_goal("Validate a micro-SaaS in the AI chatbot sector")
        assert "sector" in result
        assert "chatbot" in result["sector"].lower() or "ai" in result["sector"].lower()

    def test_IR02_product_from_goal(self):
        """Product is extracted from 'build X' pattern."""
        from core.planning.input_resolver import _extract_from_goal
        result = _extract_from_goal("Build a SaaS dashboard for analytics")
        assert "product" in result
        # The pattern captures after 'build'
        assert len(result["product"]) > 3

    def test_IR03_sector_from_for_pattern(self):
        """Sector extracted from 'for X' pattern."""
        from core.planning.input_resolver import _extract_from_goal
        result = _extract_from_goal("Research market for healthcare automation")
        assert "sector" in result

    def test_IR04_empty_goal(self):
        """Empty goal returns empty dict."""
        from core.planning.input_resolver import _extract_from_goal
        result = _extract_from_goal("")
        assert result == {}

    def test_IR05_fallback_to_goal_text(self):
        """When no patterns match, goal text itself is used."""
        from core.planning.input_resolver import _extract_from_goal
        result = _extract_from_goal("Explore potential opportunities")
        # Should use the goal as fallback for common fields
        assert "sector" in result or "product" in result


class TestInputResolution:

    def test_IR06_resolves_required_input(self):
        """Required input is resolved from goal."""
        from core.planning.input_resolver import resolve_step_inputs
        result = resolve_step_inputs(
            step_target_id="market_research.basic",
            step_inputs={},
            goal="Analyze the fintech sector",
            context_outputs={},
        )
        assert "sector" in result
        assert len(result["sector"]) > 0

    def test_IR07_explicit_inputs_override(self):
        """Step inputs take priority over goal extraction."""
        from core.planning.input_resolver import resolve_step_inputs
        result = resolve_step_inputs(
            step_target_id="market_research.basic",
            step_inputs={"sector": "healthcare"},
            goal="Analyze the fintech sector",
            context_outputs={},
        )
        assert result["sector"] == "healthcare"

    def test_IR08_context_propagation(self):
        """Previous step outputs are available to next step."""
        from core.planning.input_resolver import resolve_step_inputs
        result = resolve_step_inputs(
            step_target_id="persona.basic",
            step_inputs={},
            goal="Analyze crypto market",
            context_outputs={"target_market": "crypto traders"},
        )
        assert result["target_market"] == "crypto traders"

    def test_IR09_equivalence_resolution(self):
        """Semantic equivalences fill missing fields."""
        from core.planning.input_resolver import resolve_step_inputs
        result = resolve_step_inputs(
            step_target_id="offer_design.basic",
            step_inputs={},
            goal="Design offering for AI chatbot product",
            context_outputs={"product": "AI chatbot assistant"},
        )
        assert "opportunity" in result

    def test_IR10_goal_always_added(self):
        """Goal text is always available as 'goal' input."""
        from core.planning.input_resolver import resolve_step_inputs
        result = resolve_step_inputs(
            step_target_id="market_research.basic",
            step_inputs={},
            goal="Test goal text",
            context_outputs={},
        )
        assert result.get("goal") == "Test goal text"

    def test_IR11_unknown_skill_passthrough(self):
        """Unknown skill gets inputs passed through without modification."""
        from core.planning.input_resolver import resolve_step_inputs
        result = resolve_step_inputs(
            step_target_id="nonexistent.skill.xyz",
            step_inputs={"custom": "value"},
            goal="Some goal",
            context_outputs={"prev": "data"},
        )
        assert result["custom"] == "value"
        assert result["prev"] == "data"


class TestStepExecutorIntegration:

    def test_IR12_skill_step_succeeds_with_goal(self):
        """Skill step executes successfully when goal provides inputs."""
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        from core.planning.step_executor import execute_step

        step = PlanStep(
            step_id="test-s1",
            type=StepType.SKILL,
            target_id="market_research.basic",
            name="Research",
        )
        ctx = StepContext(
            plan_id="test-plan",
            run_id="test-run",
            goal="Validate micro-SaaS in AI chatbot sector",
        )
        result = execute_step(step, ctx)
        assert result.ok, f"Step failed: {result.error}"
        assert result.output.get("prepared") is True

    def test_IR13_multi_step_execution(self):
        """Multi-step plan executes end-to-end with input resolution."""
        from core.planning.execution_plan import ExecutionPlan, PlanStep, PlanStatus, StepType
        from core.planning.plan_serializer import PlanStore
        from core.planning.plan_runner import PlanRunner

        store = PlanStore()
        plan = ExecutionPlan(
            goal="Validate micro-SaaS in the healthcare sector",
            steps=[
                PlanStep(step_id="s1", type=StepType.SKILL,
                         target_id="market_research.basic", name="Research"),
                PlanStep(step_id="s2", type=StepType.SKILL,
                         target_id="persona.basic", name="Persona", depends_on=["s1"]),
            ],
            status=PlanStatus.APPROVED,
        )
        store.save(plan)

        import core.planning.plan_serializer as _mod
        old = _mod._store
        _mod._store = store
        try:
            runner = PlanRunner()
            run = runner.start(plan.plan_id)
            assert run.status.value == "completed", f"Run failed: {run.error}"
            assert run.steps_completed == 2
            assert run.steps_failed == 0
        finally:
            _mod._store = old

    def test_IR14_step_executor_fail_open(self):
        """If input resolver errors, step still attempts execution."""
        import inspect
        from core.planning.step_executor import _execute_skill
        source = inspect.getsource(_execute_skill)
        assert "resolve_step_inputs" in source
        # Must be in try/except with fallback
        assert "except Exception" in source


class TestAllSkills:

    def test_IR15_all_skills_resolvable(self):
        """Every domain skill can resolve its required inputs from a goal."""
        from core.planning.input_resolver import resolve_step_inputs

        skills = [
            ("market_research.basic", "Analyze the AI chatbot market"),
            ("persona.basic", "Build personas for AI chatbot users"),
            ("offer_design.basic", "Design offering for AI chatbot platform"),
            ("acquisition.basic", "Plan acquisition for chatbot product"),
            ("saas_scope.basic", "Scope a SaaS product for chatbots"),
            ("automation_opportunity.basic", "Find automation opportunities in customer support"),
            ("pricing.strategy", "Design pricing for AI platform"),
            ("competitor.analysis", "Analyze competitors in AI sector"),
            ("value_proposition.design", "Design value prop for AI product"),
            ("funnel.design", "Design acquisition funnel for AI tool"),
        ]
        for skill_id, goal in skills:
            result = resolve_step_inputs(
                step_target_id=skill_id,
                step_inputs={},
                goal=goal,
                context_outputs={},
            )
            # Should have resolved the required input (not be empty)
            assert len(result) > 1, f"{skill_id} got empty resolution from '{goal}'"

    def test_IR16_all_skills_prepare_successfully(self):
        """Every skill prepares successfully with goal-resolved inputs."""
        from core.planning.input_resolver import resolve_step_inputs
        from core.skills.domain_executor import get_skill_executor

        executor = get_skill_executor()
        skills = [
            "market_research.basic", "persona.basic", "offer_design.basic",
            "acquisition.basic", "saas_scope.basic", "automation_opportunity.basic",
            "pricing.strategy", "competitor.analysis",
            "value_proposition.design", "funnel.design",
        ]
        for skill_id in skills:
            inputs = resolve_step_inputs(
                step_target_id=skill_id,
                step_inputs={},
                goal="Validate micro-SaaS in the AI automation sector",
                context_outputs={},
            )
            prep = executor.prepare(skill_id, inputs)
            assert "error" not in prep, f"{skill_id} failed: {prep.get('error')}"
            assert prep.get("prepared", False) or "prompt_context" in prep, \
                f"{skill_id} not prepared"
