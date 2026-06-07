"""
Tests d'intégration minimalistes pour les 7 modules AGI.
Chaque test vérifie que le module s'importe et que ses classes
s'instancient sans erreur (smoke tests).

Pas de réseau requis — les modules ont des fallbacks (hash embed, dry-run, etc.)
"""
import pytest
import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────
# 1. AlignmentLayer
# ─────────────────────────────────────────────────────────────────

class TestAlignmentLayer:
    def test_import(self):
        from core.orchestration.alignment_layer import AlignmentLayer
        al = AlignmentLayer()
        assert al is not None

    def test_check_action_returns_decision(self):
        from core.orchestration.alignment_layer import AlignmentLayer, AlignmentDecision
        al = AlignmentLayer()
        result = al.check_action("Analyse le code Python", {})
        # Must return an AlignmentDecision with .allowed attribute
        assert isinstance(result, AlignmentDecision)
        assert hasattr(result, "allowed")
        assert isinstance(result.allowed, bool)

    def test_safe_action_allowed(self):
        from core.orchestration.alignment_layer import AlignmentLayer
        al = AlignmentLayer()
        result = al.check_action("Lire un fichier texte", {})
        # Reading a file is a safe action — should not be forbidden
        assert result.allowed is True

    def test_decision_has_reasoning(self):
        from core.orchestration.alignment_layer import AlignmentLayer
        al = AlignmentLayer()
        result = al.check_action("Résumer un document", {})
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0


# ─────────────────────────────────────────────────────────────────
# 2. ContinualMemory
# ─────────────────────────────────────────────────────────────────

class TestContinualMemory:
    def test_import(self):
        from core.orchestration.continual_memory import ContinualMemory
        cm = ContinualMemory()
        assert cm is not None

    def test_compute_surprise_range(self):
        """compute_surprise uses hash-based fallback when Ollama is unavailable."""
        from core.orchestration.continual_memory import ContinualMemory
        cm = ContinualMemory()
        score = cm.compute_surprise("goal text", "result text")
        assert isinstance(score, (int, float))
        assert 0.0 <= score <= 1.0

    def test_compute_surprise_identical_texts(self):
        """Identical texts should yield a low surprise score."""
        from core.orchestration.continual_memory import ContinualMemory
        cm = ContinualMemory()
        score = cm.compute_surprise("same text", "same text")
        assert score < 0.2  # near-zero for identical embeddings

    def test_build_context_injection_empty(self):
        from core.orchestration.continual_memory import ContinualMemory
        cm = ContinualMemory()
        result = cm.build_context_injection([])
        assert result == ""


# ─────────────────────────────────────────────────────────────────
# 3. CausalModule
# ─────────────────────────────────────────────────────────────────

class TestCausalModule:
    def test_import_integration(self):
        from core.orchestration.causal_module import BeaMaxCausalIntegration
        c = BeaMaxCausalIntegration()
        assert c is not None

    def test_import_causal_graph(self):
        from core.orchestration.causal_module import CausalGraph
        g = CausalGraph()
        assert g is not None

    def test_causal_graph_add_edge(self):
        from core.orchestration.causal_module import CausalGraph
        g = CausalGraph()
        g.add_edge("A", "B", strength=0.8, mechanism="direct")
        assert g.graph.has_edge("A", "B")

    def test_causal_graph_no_selfloop(self):
        from core.orchestration.causal_module import CausalGraph
        g = CausalGraph()
        with pytest.raises(ValueError):
            g.add_edge("A", "A")


# ─────────────────────────────────────────────────────────────────
# 4. CreativeEngine
# ─────────────────────────────────────────────────────────────────

class TestCreativeEngine:
    def test_import_artificial_curiosity(self):
        from core.orchestration.creative_engine import ArtificialCuriosity
        ac = ArtificialCuriosity()
        assert ac is not None

    def test_compute_surprise_score_failsafe(self):
        """Should return 0.0 (fail-safe) when LLM unavailable (no loop running)."""
        from core.orchestration.creative_engine import ArtificialCuriosity
        ac = ArtificialCuriosity()
        score = ac.compute_surprise_score("goal", "result")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_import_creative_engine_class(self):
        from core.orchestration.creative_engine import CreativeEngine
        assert CreativeEngine is not None  # just verify importable

    def test_solution_dataclass(self):
        from core.orchestration.creative_engine import Solution
        s = Solution(id="s1", content="test solution", domain_origin="direct")
        assert s.novelty_hash != ""  # auto-computed in __post_init__


# ─────────────────────────────────────────────────────────────────
# 5. GoalRegistry
# ─────────────────────────────────────────────────────────────────

class TestGoalRegistry:
    def test_import(self):
        from core.orchestration.goal_registry import GoalRegistry
        gr = GoalRegistry()
        assert gr is not None

    def test_instantiate_with_tmp_path(self, tmp_path):
        from core.orchestration.goal_registry import GoalRegistry
        gr = GoalRegistry(storage_path=tmp_path / "goals.json")
        assert gr is not None

    def test_add_and_get_goal(self, tmp_path):
        from core.orchestration.goal_registry import GoalRegistry, Goal
        import time
        gr = GoalRegistry(storage_path=tmp_path / "goals.json")
        goal = Goal(
            id="g1",
            description="Test goal",
            horizon="immediate",
            priority=5,
            progress=0.0,
            next_action="do something",
            created_at=time.time(),
            last_checked=time.time(),
        )
        added = gr.add_goal(goal)
        assert added.id == "g1"
        fetched = gr.get_goal("g1")
        assert fetched is not None
        assert fetched.description == "Test goal"

    def test_invalid_horizon_raises(self, tmp_path):
        from core.orchestration.goal_registry import GoalRegistry, Goal
        import time
        gr = GoalRegistry(storage_path=tmp_path / "goals.json")
        with pytest.raises(ValueError):
            gr.add_goal(Goal(
                id="bad", description="x", horizon="invalid_horizon",
                priority=5, progress=0.0, next_action="x",
                created_at=time.time(), last_checked=time.time(),
            ))


# ─────────────────────────────────────────────────────────────────
# 6. ProactiveLoop
# ─────────────────────────────────────────────────────────────────

class TestProactiveLoop:
    def test_import(self):
        from core.orchestration.proactive_loop import ProactiveAgent
        pa = ProactiveAgent()
        assert pa is not None

    def test_instantiate_with_registry(self, tmp_path):
        from core.orchestration.proactive_loop import ProactiveAgent
        from core.orchestration.goal_registry import GoalRegistry
        gr = GoalRegistry(storage_path=tmp_path / "goals.json")
        pa = ProactiveAgent(registry=gr, dry_run=True)
        assert pa is not None
        assert pa.dry_run is True

    def test_risk_levels_defined(self):
        from core.orchestration.proactive_loop import RiskLevel
        assert RiskLevel.NONE is not None
        assert RiskLevel.CRITICAL is not None


# ─────────────────────────────────────────────────────────────────
# 7. MemorySystem
# ─────────────────────────────────────────────────────────────────

class TestMemorySystem:
    def test_import_unified_memory(self):
        from core.orchestration.memory_system import UnifiedMemory
        um = UnifiedMemory()
        assert um is not None

    def test_import_memory_system_class(self):
        from core.orchestration.memory_system import MemorySystem
        ms = MemorySystem(session_id="test-session")
        assert ms is not None

    def test_unified_memory_has_recall_and_store(self):
        from core.orchestration.memory_system import UnifiedMemory
        um = UnifiedMemory(session_id="smoke-test")
        assert hasattr(um, "recall")
        assert hasattr(um, "store")
        assert inspect.iscoroutinefunction(um.recall)
        assert inspect.iscoroutinefunction(um.store)


# ─────────────────────────────────────────────────────────────────
# 8. ComprehensionChecker
# ─────────────────────────────────────────────────────────────────

class TestComprehensionChecker:
    def test_import(self):
        from core.orchestration.comprehension_checker import ComprehensionChecker
        cc = ComprehensionChecker()
        assert cc is not None

    def test_check_method_is_async(self):
        from core.orchestration.comprehension_checker import ComprehensionChecker
        cc = ComprehensionChecker()
        assert hasattr(cc, "check"), "check() method must exist"
        assert inspect.iscoroutinefunction(cc.check), "check() must be async"

    def test_has_test_data(self):
        """Module-level test data should be present."""
        from core.orchestration import comprehension_checker as cc_mod
        assert hasattr(cc_mod, "PHYSICAL_CAUSALITY_QUESTIONS")
        assert len(cc_mod.PHYSICAL_CAUSALITY_QUESTIONS) > 0
