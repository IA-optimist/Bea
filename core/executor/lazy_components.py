"""
core.executor.lazy_components
==============================
LazyComponentsMixin: all lazy @property loaders for BeaOrchestrator.
Each property is instantiated on first access and cached on ``self``.
"""
from __future__ import annotations
import structlog

log = structlog.get_logger()


class LazyComponentsMixin:
    """Mixin providing lazy-loaded sub-system properties."""

    # ── LLM ───────────────────────────────────────────────────

    @property
    def llm(self):
        """
        LLM client for cognition wrapper.
        Returns default role LLM (OpenRouter claude-3.7-sonnet).
        """
        from core.llm_factory import LLMFactory
        factory = LLMFactory(self.s)
        return factory.get(role="default")

    # ── Agent infrastructure ──────────────────────────────────

    @property
    def agents(self):
        if not self._agents:
            from agents.crew import AgentCrew
            self._agents = AgentCrew(self.s)
        return self._agents

    @property
    def risk(self):
        if not self._risk:
            from risk.engine import RiskEngine
            self._risk = RiskEngine()
        return self._risk

    @property
    def executor(self):
        if not self._executor:
            from executor.runner import ActionExecutor
            self._executor = ActionExecutor(self.s)
        return self._executor

    @property
    def supervised(self):
        """SupervisedExecutor : point d'entrée unique pour les actions supervisées."""
        if not self._supervised:
            from executor.supervised_executor import SupervisedExecutor
            self._supervised = SupervisedExecutor(self.s)
        return self._supervised

    # ── Memory ────────────────────────────────────────────────

    @property
    def memory(self):
        if not self._memory:
            from memory.store import MemoryStore
            self._memory = MemoryStore(self.s)
        return self._memory

    @property
    def vector_memory(self):
        """VectorMemory : mémoire contextuelle locale (sentence-transformers)."""
        if not self._vector_mem:
            try:
                from memory.vector_memory import VectorMemory
                self._vector_mem = VectorMemory(self.s)
            except Exception as e:
                log.debug("orchestrator_no_vector_memory", err=str(e)[:60])
        return self._vector_mem

    @property
    def memory_bus(self):
        """MemoryBus : interface unifiée sur les 4 backends mémoire."""
        if not getattr(self, "_memory_bus", None):
            try:
                from memory.memory_bus import MemoryBus
                self._memory_bus = MemoryBus(self.s)
            except Exception as e:
                log.debug("orchestrator_no_memory_bus", err=str(e)[:60])
                self._memory_bus = None
        return self._memory_bus

    @property
    def agent_memory(self):
        """AgentMemory : mémoire per-agent des sorties réussies (Phase 4)."""
        if not getattr(self, "_agent_memory", None):
            try:
                from memory.agent_memory import AgentMemory
                self._agent_memory = AgentMemory(self.s)
            except Exception as e:
                log.debug("orchestrator_no_agent_memory", err=str(e)[:60])
                self._agent_memory = None
        return self._agent_memory

    # ── Cognition / analytics ─────────────────────────────────

    @property
    def escalation(self):
        """EscalationEngine : désactivé par défaut, activé si API key configurée."""
        if not self._escalation:
            from core.escalation_engine import EscalationEngine
            self._escalation = EscalationEngine(self.s)
        return self._escalation

    @property
    def learning(self):
        """LearningEngine : analyse et recommandations basées sur l'historique."""
        if not self._learning:
            try:
                from core.learning.learning_engine import LearningEngine
                self._learning = LearningEngine(self.s)
            except Exception as e:
                log.debug("orchestrator_no_learning", err=str(e)[:60])
        return self._learning

    @property
    def metrics(self):
        """MetricsCollector : observabilité légère sans dépendance externe."""
        if not self._metrics:
            try:
                from core.observability.metrics import MetricsCollector
                self._metrics = MetricsCollector(self.s)
            except Exception as e:
                log.debug("orchestrator_no_metrics", err=str(e)[:60])
        return self._metrics

    @property
    def model_selector(self):
        """ModelSelector : sélection adaptative du modèle LLM."""
        if not self._model_sel:
            try:
                from core.model_selector import ModelSelector
                self._model_sel = ModelSelector(self.s)
            except Exception as e:
                log.debug("orchestrator_no_model_selector", err=str(e)[:60])
        return self._model_sel

    @property
    def evaluator(self):
        """AgentEvaluator : LLM-as-judge pour évaluer les sorties agents."""
        if not getattr(self, "_evaluator", None):
            try:
                from agents.evaluator import AgentEvaluator
                self._evaluator = AgentEvaluator(self.s)
            except Exception as e:
                log.debug("orchestrator_no_evaluator", err=str(e)[:60])
                self._evaluator = None
        return self._evaluator

    @property
    def llm_perf(self):
        """LLMPerformanceMonitor : détection de drift latence/erreur."""
        if not getattr(self, "_llm_perf", None):
            try:
                from core.observability.metrics import LLMPerformanceMonitor
                self._llm_perf = LLMPerformanceMonitor(self.s)
            except Exception as e:
                log.debug("orchestrator_no_llm_perf", err=str(e)[:60])
                self._llm_perf = None
        return self._llm_perf

    @property
    def agent_factory(self):
        """AgentFactory : création et registre d'agents dynamiques."""
        if not getattr(self, "_agent_factory", None):
            try:
                from agents.agent_factory import AgentFactory
                self._agent_factory = AgentFactory(self.s)
            except Exception as e:
                log.debug("orchestrator_no_agent_factory", err=str(e)[:60])
                self._agent_factory = None
        return self._agent_factory

    # ── Phase 3/5 components ──────────────────────────────────

    @property
    def policy(self):
        """PolicyEngine : autorisation actions + routage LLM."""
        if self._policy is None:
            try:
                from core.policy_engine import get_policy_engine
                self._policy = get_policy_engine(self.s)
            except Exception as e:
                log.debug("orchestrator_no_policy", err=str(e)[:60])
        return self._policy

    @property
    def goal_manager(self):
        """GoalManager : missions en cours + historique."""
        if self._goal_mgr is None:
            try:
                from core.goal_manager import GoalManager
                self._goal_mgr = GoalManager(self.s)
            except Exception as e:
                log.debug("orchestrator_no_goal_mgr", err=str(e)[:60])
        return self._goal_mgr

    @property
    def system_state(self):
        """SystemState : santé modules + erreurs récentes."""
        if self._sys_state is None:
            try:
                from core.system_state import SystemState
                self._sys_state = SystemState(self.s)
            except Exception as e:
                log.debug("orchestrator_no_sys_state", err=str(e)[:60])
        return self._sys_state

    @property
    def replay(self):
        """DecisionReplay : historique des décisions pour audit."""
        if self._replay is None:
            try:
                from core.decision_replay import DecisionReplay
                self._replay = DecisionReplay(self.s)
            except Exception as e:
                log.debug("orchestrator_no_replay", err=str(e)[:60])
        return self._replay
