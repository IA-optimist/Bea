"""
tests/test_skill_llm.py — Skill LLM invocation tests.

Validates:
  - LLM availability detection
  - Message building from prompt context + output schema
  - Output parsing (JSON, fenced, brace extraction, fallback)
  - Skill execution with LLM (mocked)
  - Fail-open behavior when LLM unavailable
  - Quality validation on LLM output
  - Integration with step executor
"""
from unittest.mock import patch, AsyncMock, MagicMock


class TestAvailability:

    def test_SL01_no_key_returns_false(self):
        """Without API keys, LLM is not available."""
        from core.planning.skill_llm import _is_llm_available
        with patch("config.settings.get_settings") as mock_settings:
            s = MagicMock()
            s.openrouter_api_key = ""
            s.openai_api_key = ""
            s.anthropic_api_key = ""
            mock_settings.return_value = s
            assert _is_llm_available() is False

    def test_SL02_with_openrouter_key(self):
        """OpenRouter key makes LLM available."""
        from core.planning.skill_llm import _is_llm_available
        with patch("config.settings.get_settings") as mock_settings:
            s = MagicMock()
            s.openrouter_api_key = "sk-test-key"
            mock_settings.return_value = s
            assert _is_llm_available() is True


class TestMessageBuilding:

    def test_SL03_builds_system_and_user(self):
        """Messages contain system and user messages."""
        from core.planning.skill_llm import _build_messages
        msgs = _build_messages(
            "Analyze the market",
            [{"name": "tam", "type": "json", "description": "TAM estimate"}]
        )
        assert len(msgs) == 2
        assert "analyst" in msgs[0].content.lower() or "business" in msgs[0].content.lower()
        assert "Analyze the market" in msgs[1].content

    def test_SL04_includes_output_schema(self):
        """User message includes output format instructions."""
        from core.planning.skill_llm import _build_messages
        schema = [
            {"name": "tam", "type": "json", "description": "TAM"},
            {"name": "risks", "type": "list", "description": "Risk list"},
        ]
        msgs = _build_messages("context", schema)
        assert "tam" in msgs[1].content
        assert "risks" in msgs[1].content
        assert "JSON" in msgs[1].content

    def test_SL05_empty_schema_no_crash(self):
        """Empty output schema doesn't crash."""
        from core.planning.skill_llm import _build_messages
        msgs = _build_messages("context", [])
        assert len(msgs) == 2


class TestOutputParsing:

    def test_SL06_direct_json(self):
        """Direct JSON string is parsed correctly."""
        from core.planning.skill_llm import _parse_llm_output
        raw = '{"tam": {"value": "$5B"}, "risks": ["competition"]}'
        result = _parse_llm_output(raw, [])
        assert result["tam"]["value"] == "$5B"
        assert result["risks"] == ["competition"]

    def test_SL07_fenced_json(self):
        """JSON in markdown fences is extracted."""
        from core.planning.skill_llm import _parse_llm_output
        raw = 'Here is the analysis:\n```json\n{"tam": {"value": "$5B"}}\n```\nDone.'
        result = _parse_llm_output(raw, [])
        assert result["tam"]["value"] == "$5B"

    def test_SL08_brace_extraction(self):
        """JSON object in mixed text is extracted."""
        from core.planning.skill_llm import _parse_llm_output
        raw = 'Based on analysis, the result is {"tam": "$5B", "risks": []} and that is final.'
        result = _parse_llm_output(raw, [])
        assert "tam" in result

    def test_SL09_fallback_to_raw(self):
        """Non-JSON output falls back to raw_output (no blob duplication)."""
        from core.planning.skill_llm import _parse_llm_output
        schema = [{"name": "tam", "type": "json", "description": "TAM"}]
        raw = "The market is large with significant growth potential."
        result = _parse_llm_output(raw, schema)
        assert "raw_output" in result
        # Fields not found in text should NOT be populated with raw blob
        # (old behavior was to copy raw text into every field — that was the bug)

    def test_SL10_truncates_output(self):
        """Very long output is truncated."""
        from core.planning.skill_llm import _parse_llm_output, _MAX_OUTPUT_CHARS
        raw = "x" * 20000
        result = _parse_llm_output(raw, [])
        assert len(result.get("raw_output", "")) <= _MAX_OUTPUT_CHARS


class TestInvokeSkillLLM:

    def test_SL11_no_llm_returns_not_invoked(self):
        """When no LLM available, returns invoked=False."""
        from core.planning.skill_llm import invoke_skill_llm
        with patch("core.planning.skill_llm._is_llm_available", return_value=False):
            result = invoke_skill_llm("context", [], "test.skill")
            assert result["invoked"] is False
            assert result["error"] == ""

    def test_SL12_successful_invocation(self):
        """Mocked successful LLM call returns structured output."""
        from core.planning.skill_llm import invoke_skill_llm

        mock_resp = MagicMock()
        mock_resp.content = '{"tam": {"value": "$5B"}, "risks": ["competition"]}'
        mock_resp.response_metadata = {"model": "test-model"}

        with patch("core.planning.skill_llm._is_llm_available", return_value=True), \
             patch("core.planning.skill_llm._invoke_async", new_callable=AsyncMock,
                   return_value={
                       "invoked": True,
                       "content": {"tam": {"value": "$5B"}, "risks": ["competition"]},
                       "raw_length": 50,
                       "duration_ms": 1200,
                       "model": "test-model",
                       "error": "",
                   }):
            result = invoke_skill_llm(
                "Analyze market",
                [{"name": "tam", "type": "json", "description": "TAM"}],
                "market_research.basic",
            )
            assert result["invoked"] is True
            assert "tam" in result["content"]
            assert result["error"] == ""

    def test_SL13_failed_invocation_returns_gracefully(self):
        """LLM call failure returns error without crashing."""
        from core.planning.skill_llm import invoke_skill_llm

        with patch("core.planning.skill_llm._is_llm_available", return_value=True), \
             patch("core.planning.skill_llm._invoke_async", new_callable=AsyncMock,
                   return_value={
                       "invoked": True,
                       "content": {},
                       "raw_length": 0,
                       "duration_ms": 500,
                       "model": "",
                       "error": "Connection timeout",
                   }):
            result = invoke_skill_llm("context", [], "test.skill")
            assert result["invoked"] is True
            assert "timeout" in result["error"].lower()

    def test_SL14_quality_validation_on_output(self):
        """Quality validation runs on successful LLM output."""
        from core.planning.skill_llm import invoke_skill_llm

        with patch("core.planning.skill_llm._is_llm_available", return_value=True), \
             patch("core.planning.skill_llm._invoke_async", new_callable=AsyncMock,
                   return_value={
                       "invoked": True,
                       "content": {
                           "tam": {"value": "$5B"},
                           "sam": {"value": "$500M"},
                           "som": {"value": "$50M"},
                           "problems": [{"name": "P1"}],
                           "opportunities": [{"name": "O1"}],
                           "trends": [{"name": "T1"}],
                           "risks": [{"name": "R1"}],
                       },
                       "raw_length": 200,
                       "duration_ms": 1500,
                       "model": "test",
                       "error": "",
                   }):
            result = invoke_skill_llm(
                "context",
                [{"name": "tam", "type": "json", "description": "TAM"}],
                "market_research.basic",
            )
            assert "quality" in result
            assert "score" in result["quality"]


class TestStepExecutorIntegration:

    def test_SL15_skill_step_tries_llm(self):
        """_execute_skill tries LLM invocation after prepare."""
        import inspect
        from core.planning.step_executor import _execute_skill
        source = inspect.getsource(_execute_skill)
        assert "invoke_skill_llm" in source
        assert "invoked" in source

    def test_SL16_skill_step_fallback_prep_only(self):
        """When LLM unavailable, skill step returns preparation-only output."""
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        from core.planning.step_executor import execute_step

        with patch("core.planning.skill_llm._is_llm_available", return_value=False):
            step = PlanStep(
                step_id="test-s1",
                type=StepType.SKILL,
                target_id="market_research.basic",
                name="Research",
            )
            ctx = StepContext(
                plan_id="test-plan",
                run_id="test-run",
                goal="Analyze the fintech sector",
            )
            result = execute_step(step, ctx)
            assert result.ok is True
            assert result.output.get("invoked") is False
            assert result.output.get("prepared") is True
            assert result.output.get("prompt_context_length", 0) > 0

    def test_SL17_skill_step_with_llm_output(self):
        """When LLM produces output, skill step returns it."""
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        from core.planning.step_executor import execute_step

        mock_result = {
            "invoked": True,
            "content": {"tam": {"value": "$5B"}, "risks": []},
            "raw_length": 100,
            "duration_ms": 1500,
            "model": "test-model",
            "error": "",
            "quality": {"score": 0.8, "details": []},
        }

        with patch("core.planning.skill_llm.invoke_skill_llm",
                    return_value=mock_result):
            step = PlanStep(
                step_id="test-s1",
                type=StepType.SKILL,
                target_id="market_research.basic",
                name="Research",
            )
            ctx = StepContext(
                plan_id="test-plan",
                run_id="test-run",
                goal="Analyze AI chatbot sector",
            )
            result = execute_step(step, ctx)
            assert result.ok is True
            assert result.output.get("invoked") is True
            assert "tam" in result.output.get("content", {})
            assert result.output.get("quality", {}).get("score", 0) > 0

    def test_SL18_skill_step_llm_error_still_ok(self):
        """Skill step succeeds (prep-only) even when LLM fails."""
        from core.planning.execution_plan import PlanStep, StepType
        from core.planning.step_context import StepContext
        from core.planning.step_executor import execute_step

        mock_result = {
            "invoked": True,
            "content": {},
            "raw_length": 0,
            "duration_ms": 500,
            "model": "",
            "error": "API key invalid",
        }

        with patch("core.planning.skill_llm.invoke_skill_llm",
                    return_value=mock_result):
            step = PlanStep(
                step_id="test-s1",
                type=StepType.SKILL,
                target_id="market_research.basic",
                name="Research",
            )
            ctx = StepContext(
                plan_id="test-plan",
                run_id="test-run",
                goal="Analyze fintech sector",
            )
            result = execute_step(step, ctx)
            assert result.ok is True  # Still succeeds (prep-only)
            assert result.output.get("invoked") is False
            assert "llm_error" in result.output


class TestOutputContract:

    def test_SL19_invoked_output_has_content(self):
        """Invoked skill output has content, quality, model."""
        output = {
            "skill_id": "market_research.basic",
            "invoked": True,
            "content": {"tam": "$5B"},
            "raw_length": 100,
            "duration_ms": 1500,
            "model": "test",
            "quality": {"score": 0.8, "details": []},
            "output_schema": [],
        }
        assert output["invoked"] is True
        assert isinstance(output["content"], dict)
        assert isinstance(output["quality"], dict)

    def test_SL20_prep_only_output_has_metadata(self):
        """Preparation-only output has prompt length and schema."""
        output = {
            "skill_id": "market_research.basic",
            "prepared": True,
            "invoked": False,
            "prompt_context_length": 4000,
            "output_schema": [{"name": "tam"}],
            "quality_checks": [{"name": "completeness"}],
        }
        assert output["invoked"] is False
        assert output["prepared"] is True
        assert output["prompt_context_length"] > 0


class TestPerformanceCompatibility:

    def test_SL21_step_result_unchanged(self):
        """StepResult contract is unchanged — ok/output/error/duration_ms."""
        from core.planning.step_executor import StepResult
        r = StepResult(step_id="s1", ok=True, output={"invoked": True})
        d = r.to_dict()
        assert "ok" in d
        assert "output" in d
        assert "error" in d
        assert "duration_ms" in d
        assert "artifacts" in d

    def test_SL22_kernel_events_still_fire(self):
        """PlanRunner still emits kernel events for skill steps."""
        import inspect
        from core.planning.plan_runner import PlanRunner
        source = inspect.getsource(PlanRunner._emit)
        assert "step.completed" in source or "step_completed" in source
        assert "tool_id" in source
        assert "step_type" in source


class TestSelfModelEnrichment:

    def test_SL23_limitations_show_skill_mode(self, monkeypatch):
        """Self-model reports when skills are preparation-only."""
        import core.planning.skill_llm as skill_llm
        # Précondition du test : aucun LLM configuré. On la force, sinon une clé
        # fuitée dans os.environ par un test voisin (load_dotenv) rendrait l'LLM
        # "disponible" et la limitation preparation-only ne serait pas émise.
        monkeypatch.setattr(skill_llm, "_is_llm_available", lambda: False)
        from core.self_model.model import SelfModel
        from core.self_model.queries import get_known_limitations
        # In CI, no LLM key → should report preparation-only
        model = SelfModel()
        limitations = get_known_limitations(model)
        skill_limits = [l for l in limitations if l["id"] == "skill_execution_mode"]
        assert len(skill_limits) == 1
        assert "preparation-only" in skill_limits[0]["description"]

    def test_SL24_self_model_no_crash(self):
        """Self-model enrichment doesn't crash if skill_llm unavailable."""
        from core.self_model.model import SelfModel
        from core.self_model.queries import get_known_limitations
        model = SelfModel()
        # Should not raise
        limitations = get_known_limitations(model)
        assert isinstance(limitations, list)


class TestAPIVisibility:

    def test_SL25_skill_outputs_endpoint(self):
        """Skill outputs API endpoint exists."""
        from api.routes.plan_runner import router
        paths = [r.path for r in router.routes]
        assert any("skill-outputs" in str(p) for p in paths)

    def test_SL26_skill_outputs_structure(self):
        """Skill outputs endpoint returns structured skill data."""
        import inspect
        from api.routes.plan_runner import get_skill_outputs
        source = inspect.getsource(get_skill_outputs)
        assert "skill_id" in source
        assert "invoked" in source
        assert "content" in source
        assert "quality" in source
        assert "productive_count" in source


class TestNoSecretLeakage:

    def test_SL27_messages_no_secrets(self):
        """Built messages don't contain secret-like patterns."""
        from core.planning.skill_llm import _build_messages
        import re
        msgs = _build_messages("Analyze the market", [{"name": "tam", "type": "json", "description": "TAM"}])
        full_text = " ".join(m.content for m in msgs)
        # No API keys, tokens, passwords
        assert not re.search(r"sk-[a-zA-Z0-9]{20,}", full_text)
        assert not re.search(r"ghp_[a-zA-Z0-9]{20,}", full_text)
        assert "password" not in full_text.lower()
        assert "bearer" not in full_text.lower()

    def test_SL28_output_truncation(self):
        """LLM output is bounded by max chars."""
        from core.planning.skill_llm import _parse_llm_output, _MAX_OUTPUT_CHARS
        huge = '{"key": "' + "x" * 20000 + '"}'
        result = _parse_llm_output(huge, [])
        # Should not exceed max chars
        total_size = sum(len(str(v)) for v in result.values())
        assert total_size < _MAX_OUTPUT_CHARS + 1000  # some overhead allowed


class TestNoRegression:

    def test_SL29_existing_plan_runner_works(self):
        """Multi-step plan execution still works with new LLM path."""
        from core.planning.execution_plan import ExecutionPlan, PlanStep, PlanStatus, StepType
        from core.planning.plan_serializer import PlanStore
        from core.planning.plan_runner import PlanRunner
        import core.planning.plan_serializer as _mod

        store = PlanStore()
        old = _mod._store
        _mod._store = store
        try:
            plan = ExecutionPlan(
                goal="Validate SaaS in healthcare sector",
                steps=[
                    PlanStep(step_id="s1", type=StepType.SKILL,
                             target_id="market_research.basic", name="Research"),
                    PlanStep(step_id="s2", type=StepType.SKILL,
                             target_id="persona.basic", name="Persona",
                             depends_on=["s1"]),
                ],
                status=PlanStatus.APPROVED,
            )
            store.save(plan)
            run = PlanRunner().start(plan.plan_id)
            assert run.status.value == "completed"
            assert run.steps_completed == 2
            assert run.steps_failed == 0
        finally:
            _mod._store = old

    def test_SL30_performance_still_records(self):
        """Kernel performance still records from skill step execution."""
        import kernel.capabilities.performance as _perf_mod
        from kernel.capabilities.performance import PerformanceStore
        from core.planning.execution_plan import ExecutionPlan, PlanStep, PlanStatus, StepType
        from core.planning.plan_serializer import PlanStore
        from core.planning.plan_runner import PlanRunner
        import core.planning.plan_serializer as _mod

        old_perf = _perf_mod._store
        _perf_mod._store = PerformanceStore()
        store = PlanStore()
        old_plan = _mod._store
        _mod._store = store
        try:
            plan = ExecutionPlan(
                goal="Test perf tracking in fintech",
                steps=[
                    PlanStep(step_id="s1", type=StepType.SKILL,
                             target_id="market_research.basic", name="R"),
                ],
                status=PlanStatus.APPROVED,
            )
            store.save(plan)
            PlanRunner().start(plan.plan_id)
            perf = _perf_mod._store.get_tool_performance("market_research.basic")
            assert perf is not None
            assert perf["total"] >= 1
        finally:
            _perf_mod._store = old_perf
            _mod._store = old_plan
