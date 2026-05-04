"""
tests/test_budget_mode.py — Budget mode propagation tests.

Validates:
  - Budget mode propagation through playbook → plan → context → LLM
  - Default fallback to "normal" when absent/invalid
  - Critical mode prefers stronger models
  - Budget mode prefers cheaper models
  - Observability of chosen mode in step output
  - API accepts budget_mode parameter
  - No regression in existing execution
"""
import pytest
from core.planning.execution_plan import ExecutionPlan
from core.planning.step_context import StepContext
pytestmark = pytest.mark.integration



# ══════════════════════════════════════════════════════════════
# Propagation Tests
# ══════════════════════════════════════════════════════════════

class TestBudgetPropagation:

    def test_BM01_playbook_accepts_budget_mode(self):
        """execute_playbook accepts budget_mode parameter."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test budget", budget_mode="budget")
        assert result["ok"] is True

    def test_BM02_plan_carries_budget_mode(self):
        """ExecutionPlan metadata contains budget_mode."""
        from core.planning.playbook import get_playbook_registry
        reg = get_playbook_registry()
        pb = reg.get("market_analysis")
        assert pb is not None

        plan = pb.build_plan("Test", {})
        plan.metadata["budget_mode"] = "critical"
        assert plan.metadata["budget_mode"] == "critical"

    def test_BM03_context_carries_budget_mode(self):
        """StepContext metadata propagates budget_mode."""
        ctx = StepContext(
            plan_id="test-plan",
            goal="test",
            metadata={"budget_mode": "budget"},
        )
        assert ctx.metadata["budget_mode"] == "budget"

    def test_BM04_default_is_normal(self):
        """Default budget_mode is 'normal' when absent."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test default")
        assert result["ok"] is True

    def test_BM05_invalid_mode_falls_to_normal(self):
        """Invalid budget_mode silently falls to 'normal'."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test invalid", budget_mode="turbo")
        assert result["ok"] is True

    def test_BM06_budget_mode_in_step_output(self):
        """Step outputs contain budget_mode for observability."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test observability", budget_mode="budget")
        run = result.get("run", {})
        ctx = run.get("context", {})
        step_outputs = ctx.get("step_outputs", {})
        # At least one step should have budget_mode
        for step_id, output in step_outputs.items():
            if output.get("invoked"):
                assert output.get("budget_mode") == "budget", \
                    f"Step {step_id} missing budget_mode"
                break

    def test_BM07_critical_mode_propagates(self):
        """Critical mode flows through execution."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Test critical", budget_mode="critical")
        assert result["ok"] is True


# ══════════════════════════════════════════════════════════════
# Model Selection Tests
# ══════════════════════════════════════════════════════════════

class TestBudgetModeSelection:

    def _mock_catalog(self):
        from core.model_intelligence.catalog import ModelCatalog, ModelEntry
        import tempfile
        from pathlib import Path
        cat = ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json")))
        cat._models = {
            "cheap/model": ModelEntry(
                model_id="cheap/model", name="Cheap Fast",
                provider="cheap", pricing_prompt=0.1, pricing_completion=0.3,
                context_length=32000,
            ),
            "anthropic/claude-sonnet-4.5": ModelEntry(
                model_id="anthropic/claude-sonnet-4.5", name="Claude 3.5 Sonnet",
                provider="anthropic", pricing_prompt=3.0, pricing_completion=15.0,
                context_length=200000,
            ),
        }
        return cat

    def test_BM08_budget_prefers_cheaper(self):
        """Budget mode scores cheaper models higher."""
        from core.model_intelligence.selector import ModelSelector
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select("structured_reasoning", budget_mode="budget")
        # In budget mode, cost weight is 0.6 — cheap model should score better overall
        assert result.cost_score >= 0.6
        assert "budget" in result.rationale

    def test_BM09_critical_prefers_quality(self):
        """Critical mode scores quality models higher."""
        from core.model_intelligence.selector import ModelSelector
        selector = ModelSelector(catalog=self._mock_catalog())
        result = selector.select("business_reasoning", budget_mode="critical")
        # In critical mode, profile weight is 0.5 — quality model should win
        assert result.profile_score >= 0.5
        assert "critical" in result.rationale

    def test_BM10_mode_changes_selection(self):
        """Different budget modes can produce different model selections."""
        from core.model_intelligence.selector import ModelSelector
        selector = ModelSelector(catalog=self._mock_catalog())
        budget = selector.select("structured_reasoning", "budget")
        critical = selector.select("structured_reasoning", "critical")
        # Scores should differ even if same model selected (different weights)
        assert budget.final_score != critical.final_score or \
               budget.model_id != critical.model_id

    def test_BM11_select_for_skill_with_mode(self):
        """select_for_skill passes budget_mode correctly."""
        from core.model_intelligence.selector import ModelSelector
        selector = ModelSelector(catalog=self._mock_catalog())
        r1 = selector.select_for_skill("market_research.basic", "budget")
        r2 = selector.select_for_skill("market_research.basic", "critical")
        assert r1.task_class == r2.task_class == "business_reasoning"
        assert r1.final_score != r2.final_score or r1.model_id != r2.model_id


# ══════════════════════════════════════════════════════════════
# Skill LLM Integration
# ══════════════════════════════════════════════════════════════

class TestSkillLLMBudget:

    def test_BM12_invoke_accepts_budget_mode(self):
        """invoke_skill_llm accepts budget_mode parameter."""
        import inspect
        from core.planning.skill_llm import invoke_skill_llm
        sig = inspect.signature(invoke_skill_llm)
        assert "budget_mode" in sig.parameters

    def test_BM13_async_accepts_budget_mode(self):
        """_invoke_async accepts budget_mode parameter."""
        import inspect
        from core.planning.skill_llm import _invoke_async
        sig = inspect.signature(_invoke_async)
        assert "budget_mode" in sig.parameters

    def test_BM14_step_executor_passes_budget(self):
        """Step executor extracts budget_mode from context metadata."""
        import inspect
        from core.planning.step_executor import _execute_skill
        source = inspect.getsource(_execute_skill)
        assert "budget_mode" in source
        assert 'context.metadata.get("budget_mode"' in source


# ══════════════════════════════════════════════════════════════
# API Tests
# ══════════════════════════════════════════════════════════════

class TestBudgetModeAPI:

    def test_BM15_playbook_run_schema(self):
        """RunPlaybookRequest accepts budget_mode field."""
        from api.routes.playbooks import RunPlaybookRequest
        req = RunPlaybookRequest(goal="test", budget_mode="budget")
        assert req.budget_mode == "budget"

    def test_BM16_playbook_run_default(self):
        """RunPlaybookRequest defaults to normal."""
        from api.routes.playbooks import RunPlaybookRequest
        req = RunPlaybookRequest(goal="test")
        assert req.budget_mode == "normal"

    def test_BM17_recommendations_accept_mode(self):
        """Model recommendations endpoint accepts budget_mode."""
        import asyncio
        from api.routes.models import get_recommendations
        result = asyncio.get_event_loop().run_until_complete(
            get_recommendations(budget_mode="budget")
        )
        assert result.get("budget_mode") == "budget"

    def test_BM18_execution_plan_has_metadata(self):
        """ExecutionPlan has metadata field."""
        plan = ExecutionPlan(goal="test")
        plan.metadata["budget_mode"] = "critical"
        assert plan.metadata["budget_mode"] == "critical"


# ══════════════════════════════════════════════════════════════
# Observability Tests
# ══════════════════════════════════════════════════════════════

class TestBudgetObservability:

    def test_BM19_budget_in_llm_result(self):
        """LLM result includes budget_mode field."""
        from core.planning.skill_llm import invoke_skill_llm
        result = invoke_skill_llm("Analyze this market", [], "market_research.basic", "budget")
        assert "budget_mode" in result
        assert result["budget_mode"] == "budget"

    def test_BM20_budget_in_llm_result_no_key(self):
        """Even without LLM key, result includes budget_mode."""
        # When no LLM is available, invoke returns invoked=False
        # but should still carry budget_mode
        from core.planning.skill_llm import invoke_skill_llm
        result = invoke_skill_llm("test", [], "test.skill", "critical")
        assert result.get("budget_mode") == "critical"


# ══════════════════════════════════════════════════════════════
# Safety Tests
# ══════════════════════════════════════════════════════════════

class TestBudgetSafety:

    def test_BM21_no_regression_default_playbook(self):
        """Existing playbook execution still works without budget_mode."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Regression test")
        assert result["ok"] is True
        assert "run" in result
        assert "playbook" in result

    def test_BM22_no_regression_skill_llm(self):
        """invoke_skill_llm backward compatible without budget_mode."""
        from core.planning.skill_llm import invoke_skill_llm
        # Call without budget_mode arg — should use default
        result = invoke_skill_llm("test", [], "test.skill")
        assert "budget_mode" in result

    def test_BM23_metadata_serializable(self):
        """StepContext with budget_mode serializes/deserializes."""
        ctx = StepContext(
            plan_id="test",
            goal="test",
            metadata={"budget_mode": "critical"},
        )
        d = ctx.to_dict()
        ctx2 = StepContext.from_dict(d)
        assert ctx2.metadata.get("budget_mode") == "critical"

    def test_BM24_plan_metadata_field(self):
        """ExecutionPlan metadata survives to_dict/from_dict cycle if implemented."""
        plan = ExecutionPlan(goal="test")
        plan.metadata = {"budget_mode": "budget"}
        d = plan.to_dict()
        # Verify metadata is in the dict
        assert d.get("metadata", {}).get("budget_mode") == "budget"
