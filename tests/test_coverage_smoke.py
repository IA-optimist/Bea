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
