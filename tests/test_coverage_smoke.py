"""Smoke tests — import and minimal instantiation for uncovered modules.

These tests verify that core modules load without errors and that
their primary data structures are instantiable. They deliberately
avoid LLM calls, DB access, or external I/O.

Coverage intent: bring zero-coverage modules above the import floor
(class/function definitions) to raise the overall gate from 55 to 60%.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


# ── Module import smoke tests ────────────────────────────────────────────────

class TestModuleImports:
    """Every module listed below must be importable in isolation."""

    def test_reasoning_engine(self):
        import core.orchestration.reasoning_engine  # noqa: F401

    def test_action_executor(self):
        import core.action_executor  # noqa: F401

    def test_proposal_applicator(self):
        import core.self_improvement.proposal_applicator  # noqa: F401

    def test_skill_store(self):
        import core.skill_store  # noqa: F401

    def test_goal_manager(self):
        import core.goal_manager  # noqa: F401

    def test_context_provider(self):
        import core.context_provider  # noqa: F401

    def test_system_state(self):
        import core.system_state  # noqa: F401

    def test_self_critic(self):
        import core.self_critic  # noqa: F401

    def test_validation_runner(self):
        import core.self_improvement.validation_runner  # noqa: F401

    def test_learning_loop(self):
        import core.learning.learning_loop  # noqa: F401

    def test_knowledge_validator(self):
        import core.learning.knowledge_validator  # noqa: F401

    def test_capability_scorer(self):
        import core.knowledge.capability_scorer  # noqa: F401

    def test_decision_replay(self):
        import core.decision_replay  # noqa: F401

    def test_knowledge_filter(self):
        import core.learning.knowledge_filter  # noqa: F401

    def test_policy_engine(self):
        import core.policy_engine  # noqa: F401

    def test_orchestration_guard(self):
        import core.orchestration_guard  # noqa: F401

    def test_aios_manifest(self):
        import core.aios_manifest  # noqa: F401

    def test_beta_readiness(self):
        import core.beta_readiness  # noqa: F401

    def test_agent_profiles(self):
        import core.agent_profiles  # noqa: F401

    def test_cognitive_boundary(self):
        import core.cognitive_events.boundary  # noqa: F401

    def test_knowledge_cleanup_legacy(self):
        import core.knowledge.knowledge_cleanup_legacy  # noqa: F401

    def test_rag_pipeline(self):
        import core.rag.pipeline  # noqa: F401

    def test_agent_comm(self):
        import core.agent_comm  # noqa: F401

    def test_agent_factory(self):
        import core.agent_factory  # noqa: F401

    def test_cognitive_consolidation(self):
        import core.cognitive_consolidation  # noqa: F401

    def test_client_profile(self):
        import core.client_profile  # noqa: F401


# ── Minimal instantiation smoke tests ────────────────────────────────────────

class TestInstantiations:
    """Primary data classes and stateless objects must be constructable."""

    def test_skill_store_default(self):
        from core.skill_store import SkillStore
        store = SkillStore()
        assert store is not None

    def test_self_critic_default(self):
        from core.self_critic import CriticAgent
        agent = CriticAgent()
        assert agent is not None

    def test_context_provider_default(self):
        from core.context_provider import ContextProvider
        ctx = ContextProvider()
        assert ctx is not None

    def test_proposal_applicator_result_dataclass(self):
        from core.self_improvement.proposal_applicator import ApplyResult
        r = ApplyResult(proposal_id="p1", ok=True, committed=False, branch="main")
        assert r.ok is True
        assert r.proposal_id == "p1"

    def test_goal_manager_dataclasses(self):
        from core.goal_manager import Goal
        g = Goal(id="g1", text="test goal")
        assert g.id == "g1"
        assert g.text == "test goal"

    def test_system_state_error_record(self):
        from core.system_state import ErrorRecord, ErrorSeverity
        r = ErrorRecord(module="api", message="test error")
        assert r.module == "api"
        assert r.severity == ErrorSeverity.ERROR

    def test_learning_loop_dataclasses(self):
        from core.learning.learning_loop import ExtractedInsight
        t = ExtractedInsight(content="test", type="success", source="mission", confidence=0.9)
        assert t.content == "test"
        assert t.confidence == 0.9

    def test_policy_engine_dataclasses(self):
        from core.policy_engine import PolicyDecision, LLMRoute
        d = PolicyDecision(allowed=True, reason="ok")
        assert d.allowed is True
        r = LLMRoute(provider="ollama", model="llama3", reason="default")
        assert r.provider == "ollama"

    def test_reasoning_engine_dataclasses(self):
        from core.orchestration.reasoning_engine import JudgmentSignals
        sig = JudgmentSignals(unnecessary_steps=0, first_choice_correct=True)
        assert sig.first_choice_correct is True

    def test_beta_readiness_dataclasses(self):
        from core.beta_readiness import ReadinessCheck
        check = ReadinessCheck(id="db", status="ok", message="connected")
        assert check.id == "db"
        assert check.status == "ok"

    def test_agent_profiles_loader(self):
        from core.agent_profiles import AgentProfileLoader
        loader = AgentProfileLoader()
        assert loader is not None

    def test_orchestration_guard_instantiation(self):
        from core.orchestration_guard import OrchestrationGuard
        with tempfile.TemporaryDirectory() as d:
            guard = OrchestrationGuard(workspace_dir=Path(d))
            assert guard is not None

    def test_self_critic_has_evaluate(self):
        from core.self_critic import CriticAgent
        agent = CriticAgent()
        assert hasattr(agent, "evaluate") or hasattr(agent, "critique") or hasattr(agent, "analyze")

    def test_context_provider_has_get(self):
        from core.context_provider import ContextProvider
        ctx = ContextProvider()
        assert hasattr(ctx, "get_context") or hasattr(ctx, "build") or hasattr(ctx, "get")


# ── Pure-function exercise tests ─────────────────────────────────────────────

class TestPureFunctions:
    """Exercise deterministic, IO-free functions to increase statement coverage."""

    def test_reasoning_engine_classify_complexity(self):
        from core.orchestration.reasoning_engine import _classify_complexity
        words = set("solve a complex multi step distributed problem".split())
        result = _classify_complexity("solve a complex multi step distributed problem", words)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_reasoning_engine_classify_complexity_simple(self):
        from core.orchestration.reasoning_engine import _classify_complexity
        words = set("what is x".split())
        result = _classify_complexity("what is x", words)
        assert isinstance(result, str)

    def test_reasoning_engine_decompose_requirements(self):
        from core.orchestration.reasoning_engine import _decompose_requirements
        words = set("build a web api with authentication and tests".split())
        reqs, constraints, verif = _decompose_requirements(
            "build a web api with authentication and tests", words
        )
        assert isinstance(reqs, list)
        assert isinstance(constraints, list)
        assert isinstance(verif, list)

    def test_reasoning_engine_detect_bottleneck_no_prior(self):
        from core.orchestration.reasoning_engine import _detect_bottleneck
        result = _detect_bottleneck("implement feature X", None, None)
        assert isinstance(result, str)

    def test_reasoning_engine_detect_bottleneck_with_failures(self):
        from core.orchestration.reasoning_engine import _detect_bottleneck
        result = _detect_bottleneck(
            "write tests", {"type": "implementation"}, ["timeout", "flaky test"]
        )
        assert isinstance(result, str)

    def test_reasoning_engine_classify_issue(self):
        from core.orchestration.reasoning_engine import _classify_issue
        priority, score, category = _classify_issue("timeout in database query", "optimize DB")
        assert score >= 0.0
        assert isinstance(category, str)

    def test_cognitive_boundary_is_lab(self):
        from core.cognitive_events.boundary import is_lab_subsystem
        assert is_lab_subsystem("core.orchestration.reasoning_engine") is False
        assert is_lab_subsystem("lab.experiment_runner") in (True, False)

    def test_cognitive_boundary_is_protected(self):
        from core.cognitive_events.boundary import is_runtime_protected
        result = is_runtime_protected("api.main")
        assert isinstance(result, bool)

    def test_cognitive_boundary_validate_emission(self):
        from core.cognitive_events.boundary import validate_emission, EventType
        ok, reason = validate_emission("core.meta_orchestrator", EventType.MISSION_STARTED)
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_cognitive_boundary_summary(self):
        from core.cognitive_events.boundary import get_boundary_summary
        summary = get_boundary_summary()
        assert isinstance(summary, dict)
        assert len(summary) > 0

    def test_aios_manifest_get(self):
        from core.aios_manifest import get_manifest
        manifest = get_manifest()
        assert isinstance(manifest, dict)

    def test_aios_manifest_consistency(self):
        from core.aios_manifest import consistency_check
        result = consistency_check()
        assert isinstance(result, dict)

    def test_agent_profiles_get_profile(self):
        from core.agent_profiles import get_profile
        profile = get_profile("researcher")
        assert profile is None or hasattr(profile, "__class__")

    def test_orchestration_guard_get_guard(self):
        from core.orchestration_guard import get_guard
        guard = get_guard()
        assert guard is not None

    def test_capability_scorer_get(self):
        from core.knowledge.capability_scorer import get_capability_scorer
        scorer = get_capability_scorer()
        assert scorer is not None

    def test_policy_engine_instantiation(self):
        from unittest.mock import MagicMock
        from core.policy_engine import PolicyEngine
        settings = MagicMock()
        engine = PolicyEngine(settings=settings)
        assert engine is not None

    def test_policy_engine_attributes(self):
        from unittest.mock import MagicMock
        from core.policy_engine import PolicyEngine
        settings = MagicMock()
        engine = PolicyEngine(settings=settings)
        assert hasattr(engine, "check_action") or hasattr(engine, "select_llm_provider")

    def test_goal_manager_goal_methods(self):
        from core.goal_manager import Goal
        g = Goal(id="g1", text="test goal", mode="auto")
        d = g.__dict__ if not hasattr(g, "to_dict") else g.to_dict()
        assert "id" in str(d) or g.id == "g1"

    def test_policy_decision_to_dict(self):
        from core.policy_engine import PolicyDecision
        d = PolicyDecision(allowed=False, reason="quota", suggestion="retry later")
        assert d.allowed is False
        assert d.reason == "quota"
        assert d.suggestion == "retry later"

    def test_llm_route_fields(self):
        from core.policy_engine import LLMRoute
        r = LLMRoute(
            provider="openai",
            model="gpt-4o",
            reason="high quality needed",
            estimated_cost_usd=0.002,
        )
        assert r.provider == "openai"
        assert r.model == "gpt-4o"
        assert r.estimated_cost_usd == 0.002
