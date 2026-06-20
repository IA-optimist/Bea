"""
tests/test_execution_reliability.py — Tests for execution reliability upgrades.

ER01-ER70: Step retry, output enforcement, model fallback, quality gate,
execution memory, self-review, mission trace.
"""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _temp_artifact(content: str, suffix: str):
    """Écrit `content` dans un fichier temporaire FERMÉ puis yield son chemin.

    Sur Windows, lire/supprimer un NamedTemporaryFile encore ouvert lève
    PermissionError [WinError 32] (verrou de partage). On ferme donc le handle
    avant de céder le chemin, et on nettoie dans le finally.
    """
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
    try:
        f.write(content)
    finally:
        f.close()
    try:
        yield f.name
    finally:
        try:
            os.unlink(f.name)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════
# PHASE 1: Step-Level Adaptive Retry (SR01-SR15)
# ═══════════════════════════════════════════════════════════════

class TestStepRetry:

    def test_SR01_detect_raw_output(self):
        from core.planning.step_retry import detect_incomplete_output
        schema = [{"name": "analysis", "type": "text"}]
        issues = detect_incomplete_output({"raw_output": "garbage"}, schema)
        assert any("json_parse_failed" in i for i in issues)

    def test_SR02_detect_missing_fields(self):
        from core.planning.step_retry import detect_incomplete_output
        schema = [{"name": "analysis", "type": "text"}, {"name": "score", "type": "number"}]
        issues = detect_incomplete_output({"analysis": "good"}, schema)
        assert any("missing_field" in i and "score" in i for i in issues)

    def test_SR03_detect_placeholder(self):
        from core.planning.step_retry import detect_incomplete_output
        schema = [{"name": "analysis", "type": "text"}]
        issues = detect_incomplete_output({"analysis": "TODO: fill this in"}, schema)
        assert any("placeholder" in i for i in issues)

    def test_SR04_detect_empty_fields(self):
        from core.planning.step_retry import detect_incomplete_output
        schema = [{"name": "analysis", "type": "text"}]
        issues = detect_incomplete_output({"analysis": ""}, schema)
        assert any("empty_field" in i for i in issues)

    def test_SR05_good_output_no_issues(self):
        from core.planning.step_retry import detect_incomplete_output
        schema = [{"name": "analysis", "type": "text"}, {"name": "score", "type": "number"}]
        issues = detect_incomplete_output({"analysis": "Real content here", "score": 0.8}, schema)
        assert len(issues) == 0

    def test_SR06_should_retry_on_issues(self):
        from core.planning.step_retry import should_retry
        assert should_retry(["missing_field: x"], attempt=0) is True

    def test_SR07_no_retry_after_max(self):
        from core.planning.step_retry import should_retry, MAX_RETRIES
        assert should_retry(["missing_field: x"], attempt=MAX_RETRIES) is False

    def test_SR08_escalation_chain(self):
        from core.planning.step_retry import get_retry_strategy, RetryStrategyType
        s0 = get_retry_strategy(0)
        s1 = get_retry_strategy(1)
        s2 = get_retry_strategy(2)
        assert s0.strategy_type == RetryStrategyType.SAME_MODEL
        assert s1.strategy_type == RetryStrategyType.LOWER_TEMP
        assert s2.strategy_type == RetryStrategyType.SWITCH_MODEL

    def test_SR09_first_is_same_model(self):
        from core.planning.step_retry import get_retry_strategy, RetryStrategyType
        assert get_retry_strategy(0).strategy_type == RetryStrategyType.SAME_MODEL

    def test_SR10_second_has_lower_temp(self):
        from core.planning.step_retry import get_retry_strategy
        s = get_retry_strategy(1)
        assert s.temperature == 0.1

    def test_SR11_third_switches_model(self):
        from core.planning.step_retry import get_retry_strategy
        s = get_retry_strategy(2)
        assert s.budget_mode == "budget"

    def test_SR12_beyond_max_returns_none(self):
        from core.planning.step_retry import get_retry_strategy
        assert get_retry_strategy(3) is None
        assert get_retry_strategy(10) is None

    def test_SR13_strategy_serializes(self):
        from core.planning.step_retry import get_retry_strategy
        d = get_retry_strategy(0).to_dict()
        assert "strategy_type" in d
        assert d["strategy_type"] == "same_model"

    def test_SR14_apply_strategy_to_prompt(self):
        from core.planning.step_retry import apply_strategy_to_prompt, get_retry_strategy
        original = "Analyze the market"
        modified = apply_strategy_to_prompt(original, get_retry_strategy(0))
        assert "JSON" in modified
        assert "Analyze the market" in modified

    def test_SR15_simplify_removes_examples(self):
        from core.planning.step_retry import apply_strategy_to_prompt, get_retry_strategy
        original = "Analyze market.\nExample: This is a sample.\n\nNext section"
        s = get_retry_strategy(2)  # SWITCH_MODEL with simplify=True
        modified = apply_strategy_to_prompt(original, s)
        assert "This is a sample" not in modified

    def test_SR16_detect_empty_dict(self):
        from core.planning.step_retry import detect_incomplete_output
        issues = detect_incomplete_output({}, [{"name": "x", "type": "text"}])
        assert len(issues) > 0

    def test_SR17_retry_trace_serializes(self):
        from core.planning.step_retry import RetryTrace
        t = RetryTrace(total_attempts=2, strategies_used=[{"s": "same_model"}])
        d = t.to_dict()
        assert d["total_attempts"] == 2


# ═══════════════════════════════════════════════════════════════
# PHASE 2: Structured Output Enforcement (OE01-OE15)
# ═══════════════════════════════════════════════════════════════

class TestOutputEnforcer:

    def test_OE01_good_output_valid(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "analysis", "type": "text"}, {"name": "score", "type": "number"}]
        r = e.validate_against_schema({"analysis": "Good stuff", "score": 0.8}, schema)
        assert r.valid is True
        assert r.overall_score == 1.0

    def test_OE02_missing_fields(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "a", "type": "text"}, {"name": "b", "type": "number"}]
        r = e.validate_against_schema({"a": "ok"}, schema)
        assert not r.valid
        assert any("missing" in i for i in r.issues)

    def test_OE03_wrong_types(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "count", "type": "number"}]
        r = e.validate_against_schema({"count": "not a number"}, schema)
        assert not r.valid
        assert any("wrong_type" in i for i in r.issues)

    def test_OE04_repair_string_to_list(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "items", "type": "list"}]
        repaired = e.auto_repair({"items": "one\ntwo\nthree"}, schema)
        assert isinstance(repaired["items"], list)
        assert len(repaired["items"]) == 3

    def test_OE05_repair_string_to_number(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "score", "type": "number"}]
        repaired = e.auto_repair({"score": "about 0.75 points"}, schema)
        assert isinstance(repaired["score"], (int, float))
        assert repaired["score"] == 0.75

    def test_OE06_repair_string_to_dict(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "meta", "type": "dict"}]
        repaired = e.auto_repair({"meta": '{"key": "value"}'}, schema)
        assert isinstance(repaired["meta"], dict)
        assert repaired["meta"]["key"] == "value"

    def test_OE07_repair_missing_fills_default(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "items", "type": "list"}, {"name": "count", "type": "number"}]
        repaired = e.auto_repair({}, schema)
        assert repaired["items"] == []
        assert repaired["count"] == 0

    def test_OE08_repair_null_fills_default(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "text", "type": "string"}]
        repaired = e.auto_repair({"text": None}, schema)
        assert repaired["text"] == ""

    def test_OE09_repair_preserves_correct(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "a", "type": "text"}, {"name": "b", "type": "number"}]
        repaired = e.auto_repair({"a": "hello", "b": 42}, schema)
        assert repaired["a"] == "hello"
        assert repaired["b"] == 42

    def test_OE10_field_scores_reflect_repair(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "a", "type": "text"}, {"name": "b", "type": "number"}]
        r = e.validate_against_schema({"a": "ok", "b": "not_number"}, schema)
        assert r.field_scores["a"] == 1.0
        assert r.field_scores["b"] < 1.0

    def test_OE11_correction_prompt_includes_issues(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        prompt = e.build_correction_prompt(
            {"a": "bad"}, [{"name": "a", "type": "text"}], ["wrong_type: a"]
        )
        assert "wrong_type" in prompt

    def test_OE12_correction_prompt_includes_output(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        prompt = e.build_correction_prompt(
            {"field": "value"}, [{"name": "field", "type": "text"}], ["issue"]
        )
        assert "value" in prompt

    def test_OE13_overall_score_computed(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "a", "type": "text"}, {"name": "b", "type": "text"}]
        r = e.validate_against_schema({"a": "ok"}, schema)
        assert r.overall_score == 0.5  # 1.0 + 0.0 / 2

    def test_OE14_empty_output_score_zero(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        schema = [{"name": "a", "type": "text"}]
        r = e.validate_against_schema({}, schema)
        assert r.overall_score == 0.0

    def test_OE15_no_schema_permissive(self):
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        r = e.validate_against_schema({"anything": "goes"}, [])
        assert r.valid is True
        assert r.overall_score == 1.0


# ═══════════════════════════════════════════════════════════════
# PHASE 3: Model Fallback Chains (MF01-MF15)
# ═══════════════════════════════════════════════════════════════

class TestModelFallback:

    def test_MF01_budget_returns_cheaper(self):
        from core.model_intelligence.fallback_chain import BUDGET_FALLBACKS
        assert BUDGET_FALLBACKS["budget"]["structured_reasoning"] == "openai/gpt-4o-mini"

    def test_MF02_normal_returns_standard(self):
        from core.model_intelligence.fallback_chain import BUDGET_FALLBACKS
        assert BUDGET_FALLBACKS["normal"]["structured_reasoning"] == "anthropic/claude-sonnet-4.5"

    def test_MF03_critical_returns_premium(self):
        from core.model_intelligence.fallback_chain import BUDGET_FALLBACKS
        assert BUDGET_FALLBACKS["critical"]["business_reasoning"] == "anthropic/claude-sonnet-4.5"

    def test_MF04_invalid_mode_fallback(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        chain = m.get_chain("coding", "invalid_mode")
        assert len(chain.chain) >= 2  # still builds a chain

    def test_MF05_chain_has_minimum_models(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        for tc in ["coding", "business_reasoning"]:
            chain = m.get_chain(tc, "normal")
            assert len(chain.chain) >= 2
        # cheap_simple has only gpt-4o-mini (fallback == absolute fallback, deduped)
        chain = m.get_chain("cheap_simple", "normal")
        assert len(chain.chain) >= 1

    def test_MF06_next_model_skips_failed(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        chain = m.get_chain("coding", "normal", primary_model="anthropic/claude-sonnet-4.5")
        first = chain.next_model()
        assert first == "anthropic/claude-sonnet-4.5"
        second = chain.next_model(failed_models={"anthropic/claude-sonnet-4.5"})
        assert second != "anthropic/claude-sonnet-4.5"

    def test_MF07_all_failed_returns_none(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        chain = m.get_chain("coding", "budget")
        all_models = set(chain.chain)
        assert chain.next_model(failed_models=all_models) is None

    def test_MF08_chain_order(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        chain = m.get_chain("coding", "critical", primary_model="custom/model")
        assert chain.chain[0] == "custom/model"
        assert chain.chain[-1] == "openai/gpt-4o-mini"

    def test_MF09_failure_tracking(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        m.record_failure("coding", "bad/model")
        stats = m.get_stats()
        assert "bad/model" in stats.get("coding", [])

    def test_MF10_analyst_routes_openrouter(self):
        from core.llm_factory import ROLE_PROVIDERS
        assert ROLE_PROVIDERS.get("analyst") == "openrouter"

    def test_MF11_budget_selector_uses_fallback_chain(self):
        from core.model_intelligence.catalog import ModelCatalog
        from core.model_intelligence.selector import ModelSelector
        # Catalogue VIDE => sélection déterministe via la fallback chain hardcodée
        # (sinon le cache OpenRouter de l'environnement fait dériver les noms de modèles).
        sel = ModelSelector(catalog=ModelCatalog(catalog_path=Path(tempfile.mktemp(suffix=".json"))))
        budget = sel.select("business_reasoning", "budget")
        normal = sel.select("business_reasoning", "normal")
        assert budget.model_id == "openai/gpt-4o-mini"
        assert "claude" in normal.model_id or normal.model_id == "openai/gpt-4o-mini"

    def test_MF12_budget_all_cheap(self):
        from core.model_intelligence.fallback_chain import BUDGET_FALLBACKS
        for tc, model in BUDGET_FALLBACKS["budget"].items():
            if tc != "long_context":
                assert model == "openai/gpt-4o-mini"

    def test_MF13_critical_all_premium(self):
        from core.model_intelligence.fallback_chain import BUDGET_FALLBACKS
        for tc, model in BUDGET_FALLBACKS["critical"].items():
            if tc not in ("cheap_simple", "fallback_only"):
                assert "claude" in model or "sonnet" in model

    def test_MF14_chain_serializes(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        chain = m.get_chain("coding", "normal")
        d = chain.to_dict()
        assert "chain" in d
        assert isinstance(d["chain"], list)

    def test_MF15_get_chain_returns_list(self):
        from core.model_intelligence.fallback_chain import FallbackChainManager
        m = FallbackChainManager()
        chain = m.get_chain("coding", "budget")
        assert isinstance(chain.chain, list)


# ═══════════════════════════════════════════════════════════════
# PHASE 4: Quality Gate (QG01-QG15)
# ═══════════════════════════════════════════════════════════════

class TestQualityGate:

    def test_QG01_valid_html_passes(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = "<html><head><title>Test</title></head><body><h1>Hello</h1>" + "x" * 500 + "</body></html>"
        with _temp_artifact(content, ".html") as path:
            r = ArtifactQualityGate().verify(path, "landing_page")
            assert r.passed
            assert r.score >= 0.8

    def test_QG02_placeholder_html_fails(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = "<html><body><h1>TODO: Add title</h1>Lorem ipsum dolor sit amet" + "x" * 500 + "</body></html>"
        with _temp_artifact(content, ".html") as path:
            r = ArtifactQualityGate().verify(path, "landing_page")
            assert len(r.issues) > 0

    def test_QG03_empty_file_critical(self):
        from core.execution.quality_gate import ArtifactQualityGate
        with _temp_artifact("", ".html") as path:
            r = ArtifactQualityGate().verify(path, "landing_page")
            assert not r.passed
            assert any(i.severity == "critical" for i in r.issues)

    def test_QG04_nonexistent_file(self):
        from core.execution.quality_gate import ArtifactQualityGate
        r = ArtifactQualityGate().verify("/nonexistent/file.html", "landing_page")
        assert not r.passed
        assert any(i.severity == "critical" for i in r.issues)

    def test_QG05_valid_python_passes(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'ok': True}\n"
        with _temp_artifact(content, ".py") as path:
            r = ArtifactQualityGate().verify(path, "api_service")
            assert r.passed

    def test_QG06_python_syntax_error(self):
        from core.execution.quality_gate import ArtifactQualityGate
        with _temp_artifact("def broken(\n  return None\n", ".py") as path:
            r = ArtifactQualityGate().verify(path, "api_service")
            assert any(i.severity == "critical" for i in r.issues)

    def test_QG07_python_hardcoded_secret(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = 'api_key = "sk-abcdefghij1234567890abcdefghij"\ndef run(): pass\n'
        with _temp_artifact(content, ".py") as path:
            r = ArtifactQualityGate().verify(path, "api_service")
            assert any("secret" in i.description for i in r.issues)

    def test_QG08_auto_correct_placeholder(self):
        from core.execution.quality_gate import ArtifactQualityGate, QualityIssue
        with _temp_artifact("<h1>TODO: Add content</h1>", ".html") as path:
            gate = ArtifactQualityGate()
            issues = [QualityIssue(category="placeholder", severity="warning",
                                    description="placeholder", auto_correctable=True)]
            result = gate.auto_correct(path, issues)
            assert result.corrected
            content = Path(path).read_text(encoding="utf-8")
            assert "TODO" not in content

    def test_QG09_score_no_issues(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = "<html><head></head><body><h1>Real Content</h1>" + "text " * 200 + "</body></html>"
        with _temp_artifact(content, ".html") as path:
            r = ArtifactQualityGate().verify(path, "landing_page")
            assert r.score >= 0.9

    def test_QG10_score_critical_penalty(self):
        from core.execution.quality_gate import ArtifactQualityGate
        r = ArtifactQualityGate().verify("/nonexistent", "landing_page")
        assert r.score <= 0.7

    def test_QG11_report_serializes(self):
        from core.execution.quality_gate import ArtifactQualityGate
        r = ArtifactQualityGate().verify("/nonexistent", "landing_page")
        d = r.to_dict()
        assert "passed" in d
        assert "score" in d
        assert "issues" in d

    def test_QG12_content_asset_word_count(self):
        from core.execution.quality_gate import ArtifactQualityGate
        with _temp_artifact("Short.", ".md") as path:
            r = ArtifactQualityGate().verify(path, "content_asset")
            assert any("word" in i.description for i in r.issues)

    def test_QG13_json_workflow_valid(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = json.dumps({"trigger": "webhook", "steps": [{"action": "send_email"}]})
        with _temp_artifact(content, ".json") as path:
            r = ArtifactQualityGate().verify(path, "automation_workflow")
            assert r.passed

    def test_QG14_correctable_flag(self):
        from core.execution.quality_gate import ArtifactQualityGate
        content = "<html><body>TODO placeholder</body></html>" + "x" * 500
        with _temp_artifact(content, ".html") as path:
            r = ArtifactQualityGate().verify(path, "landing_page")
            assert r.correctable  # placeholder issues are auto-correctable

    def test_QG15_quality_gate_in_build_pipeline(self):
        """Verify quality gate is called during build."""
        from core.execution.execution_graph import build_execution_graph
        from core.execution.build_pipeline import BuildPipeline
        g = build_execution_graph("BusinessConcept", "Test product")
        node = g.get_next_buildable()
        r = BuildPipeline().build(node.artifact)
        # Quality gate should have been called (check build_log)
        quality_entries = [e for e in r.build_log if "QUALITY" in e or "confidence" in e.lower()]
        assert len(quality_entries) > 0


# ═══════════════════════════════════════════════════════════════
# PHASE 5: Execution Memory (EM01-EM15)
# ═══════════════════════════════════════════════════════════════

class TestExecutionMemory:

    def test_EM01_record_mission(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_mission("m1", "AI tutoring market analysis", "market_analysis",
                           True, 0.8, "sonnet", 0.01, 5000)
            assert len(m._missions) == 1

    def test_EM02_record_step(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_step_outcome("s1", "market_research", "sonnet", True, 0.9)
            assert len(m._steps) == 1

    def test_EM03_strategy_for_similar_goal(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_mission("m1", "AI tutoring market analysis", "market_analysis",
                           True, 0.8, "sonnet", 0.01, 5000)
            strategy = m.get_strategy_for_goal("AI tutoring market research")
            assert strategy is not None
            assert strategy.playbook_id == "market_analysis"

    def test_EM04_no_strategy_for_unrelated(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_mission("m1", "AI tutoring market analysis", "market_analysis",
                           True, 0.8)
            strategy = m.get_strategy_for_goal("quantum physics simulation")
            assert strategy is None

    def test_EM05_best_model_for_skill(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_step_outcome("s1", "market_research", "sonnet", True, 0.9)
            m.record_step_outcome("s2", "market_research", "gpt4o", True, 0.6)
            best = m.get_best_model_for_skill("market_research")
            assert best == "sonnet"

    def test_EM06_no_model_for_unknown_skill(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            assert m.get_best_model_for_skill("unknown_skill") is None

    def test_EM07_retry_recommendation(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_step_outcome("s1", "market_research", "sonnet", True, 0.8,
                                retry_count=2, issues=["json_parse_failed"])
            rec = m.get_retry_recommendation("market_research", "json_parse")
            assert rec is not None

    def test_EM08_no_retry_for_unknown_error(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            assert m.get_retry_recommendation("unknown", "unknown_error") is None

    def test_EM09_persistence_roundtrip(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m1 = ExecutionMemory(data_dir=td)
            m1.record_mission("m1", "test goal", "test_pb", True, 0.7)
            # Create new instance reading same file
            m2 = ExecutionMemory(data_dir=td)
            m2._ensure_loaded()
            assert len(m2._missions) == 1
            assert m2._missions[0]["goal"] == "test goal"

    def test_EM10_fifo_eviction(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory, _MAX_MISSIONS
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            for i in range(_MAX_MISSIONS + 10):
                m.record_mission(f"m{i}", f"goal {i}", "pb", True, 0.5)
            assert len(m._missions) <= _MAX_MISSIONS

    def test_EM11_confidence_based_on_samples(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            for i in range(5):
                m.record_mission(f"m{i}", "AI market analysis", "market_analysis", True, 0.8)
            strategy = m.get_strategy_for_goal("AI market research")
            assert strategy is not None
            assert strategy.confidence == 1.0  # 5 samples = max confidence

    def test_EM12_stats(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            m.record_mission("m1", "g1", "pb1", True, 0.8)
            m.record_mission("m2", "g2", "pb2", False, 0.3)
            stats = m.get_stats()
            assert stats["total_missions"] == 2
            assert stats["success_rate"] == 0.5

    def test_EM13_jaccard_similarity(self):
        from core.planning.learning_memory import _jaccard_similarity
        assert _jaccard_similarity("AI market analysis", "AI market research") > 0.3
        assert _jaccard_similarity("AI market analysis", "quantum physics") < 0.3

    def test_EM14_empty_memory(self):
        from core.planning.learning_memory import LearningMemory as ExecutionMemory
        with tempfile.TemporaryDirectory() as td:
            m = ExecutionMemory(data_dir=td)
            assert m.get_strategy_for_goal("anything") is None
            assert m.get_best_model_for_skill("anything") is None
            stats = m.get_stats()
            assert stats["total_missions"] == 0

    def test_EM15_singleton(self):
        from core.planning.learning_memory import get_learning_memory as get_execution_memory
        a = get_execution_memory()
        b = get_execution_memory()
        assert a is b


# ═══════════════════════════════════════════════════════════════
# PHASE 8: Self-Review (RV01-RV10)
# ═══════════════════════════════════════════════════════════════

class TestSelfReview:

    def test_RV01_successful_mission_passes(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("test goal", {
            "ok": True,
            "run": {"steps_completed": 3, "steps_total": 3,
                    "context": {"step_outputs": {
                        "s1": {"invoked": True, "content": {"analysis": "test goal analysis"}},
                    }}},
        })
        assert r.passed
        assert r.score >= 0.7

    def test_RV02_failed_mission_low_score(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("goal", {"ok": False, "run": {"steps_completed": 0, "steps_total": 3,
                                           "context": {"step_outputs": {}}}})
        assert not r.passed

    def test_RV03_partial_steps_warning(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("goal", {
            "ok": True,
            "run": {"steps_completed": 1, "steps_total": 4,
                    "context": {"step_outputs": {}}},
        })
        assert any(i.category == "completeness" for i in r.issues)

    def test_RV04_empty_content_warning(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("goal", {
            "ok": True,
            "run": {"steps_completed": 1, "steps_total": 1,
                    "context": {"step_outputs": {
                        "s1": {"invoked": True, "content": {}},
                    }}},
        })
        assert any("empty" in i.description for i in r.issues)

    def test_RV05_coherence_check(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("AI tutoring market analysis", {
            "ok": True,
            "run": {"steps_completed": 1, "steps_total": 1,
                    "context": {"step_outputs": {
                        "s1": {"invoked": True, "content": {"text": "completely unrelated pizza recipe"}},
                    }}},
        })
        assert any("coherence" in i.category or "overlap" in i.description for i in r.issues)

    def test_RV06_result_serializes(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("goal", {"ok": True, "run": {"steps_completed": 1, "steps_total": 1,
                                           "context": {"step_outputs": {}}}})
        d = r.to_dict()
        assert "passed" in d
        assert "score" in d
        assert "issues" in d

    def test_RV07_prep_only_info(self):
        from core.planning.self_review import review_mission_result
        r = review_mission_result("goal", {
            "ok": True,
            "run": {"steps_completed": 1, "steps_total": 1,
                    "context": {"step_outputs": {
                        "s1": {"prepared": True, "invoked": False},
                    }}},
        })
        assert any("not invoked" in i.description for i in r.issues)


# ═══════════════════════════════════════════════════════════════
# PHASE 9: Mission Trace (MT01-MT08)
# ═══════════════════════════════════════════════════════════════

class TestMissionTrace:

    def test_MT01_record_events(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace("m1", "test goal")
        t.record_planning("market_analysis", 4, "normal")
        t.record_step_start("s1", "market_research")
        t.record_step_complete("s1", True, 1500)
        assert len(t._entries) == 3

    def test_MT02_serializes(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace("m1", "goal")
        t.record("execution", "test_event", key="value")
        d = t.to_dict()
        assert d["mission_id"] == "m1"
        assert len(d["entries"]) == 1

    def test_MT03_summary_counts(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace("m1", "goal")
        t.record_planning("pb", 3, "normal")
        t.record_step_start("s1", "skill1")
        t.record_step_complete("s1", True, 1000)
        t.record_retry("s2", 1, "lower_temp")
        s = t.summary()
        assert s["retries"] == 1
        assert s["total_events"] == 4

    def test_MT04_model_selection_traced(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace("m1", "goal")
        t.record_model_selection("market_research", "sonnet", "normal")
        assert t._entries[0].event == "model_selected"

    def test_MT05_review_traced(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace()
        t.record_review(0.8, True, 2)
        assert t._entries[0].data["score"] == 0.8

    def test_MT06_delivery_traced(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace()
        t.record_delivery(True, 0.9)
        assert t._entries[0].data["ok"] is True

    def test_MT07_duration_tracked(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace()
        d = t.to_dict()
        assert "duration_ms" in d

    def test_MT08_error_count(self):
        from core.planning.mission_trace import MissionTrace
        t = MissionTrace()
        t.record_step_complete("s1", False, 100)
        t.record_step_complete("s2", True, 200)
        s = t.summary()
        assert s["errors"] == 1
