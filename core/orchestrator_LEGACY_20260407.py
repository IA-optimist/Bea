# ══════════════════════════════════════════════════════
# DEPRECATED — Do not extend this module.
# Replaced by: core.meta_orchestrator.MetaOrchestrator
# Kept for backward compatibility only.
# ══════════════════════════════════════════════════════
# DEPRECATED: Use MetaOrchestrator.
# from core.meta_orchestrator import MetaOrchestrator, get_meta_orchestrator

"""
JARVIS MAX - Orchestrateur central
Responsabilites strictement separees :
  1. Reception de la mission
  2. Delegation au TaskRouter pour le plan
  3. Execution des agents
  4. Traitement des actions (risque + validation)
  5. Rapport final

L orchestrateur ne decide PAS du routing - c est le TaskRouter.
"""
from __future__ import annotations
import asyncio
import uuid
import structlog
from typing import Callable, Awaitable

from core.state import (
    JarvisSession, SessionStatus, ActionSpec,
    RiskLevel, TaskMode
)
from core.task_router import TaskRouter
from config.settings import get_settings

log = structlog.get_logger()
CB = Callable[[str], Awaitable[None]]

# Timeout global par mode (secondes)
SESSION_TIMEOUTS = {
    "auto":    600,    # 10 min
    "night":   1800,   # 30 min
    "improve": 900,    # 15 min
    "chat":    60,
}


class JarvisOrchestrator:
    """
    INTERNAL IMPLEMENTATION — NOT FOR DIRECT INSTANTIATION.

    This class is an internal delegate of MetaOrchestrator.
    External callers must use: get_meta_orchestrator() from core.
    Direct instantiation will trigger a DeprecationWarning.

    Migration target: inline this logic into MetaOrchestrator and remove this file.
    """

    # ── Mapping intent → composant — aucun LLM requis pour le routage ──
    INTENT_MAP: dict[str, str] = {
        "improve":  "self_improve",     # pipeline auto-amélioration
        "code":     "forge-builder",    # génération code
        "research": "scout-research",   # recherche et synthèse
        "plan":     "map-planner",      # planification
        "night":    "night-worker",     # travail long multi-cycles
        "chat":     "shadow-advisor",   # conversation rapide
        "workflow": "workflow-agent",   # création et exécution de workflows
        "default":  "shadow-advisor",   # fallback local garanti
    }

    def __init__(self, settings=None):
        import warnings
        warnings.warn(
            "JarvisOrchestrator is deprecated — use get_meta_orchestrator() from core.meta_orchestrator instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.s      = settings or get_settings()
        self.router = TaskRouter()
        self._agents       = None
        self._risk         = None
        self._executor     = None
        self._supervised   = None
        self._memory       = None
        self._escalation   = None
        self._learning     = None
        self._metrics      = None
        self._vector_mem   = None
        self._model_sel    = None
        # Phase 3/5 — nouveaux modules
        self._circuit_breakers = None
        self._policy       = None
        self._goal_mgr     = None
        self._sys_state    = None
        self._replay       = None
        # Phase 4 — mémoire per-agent
        self._agent_memory = None
        # Background task references — prevents fire-and-forget GC / exception loss
        self._bg_tasks: set = set()

    # ── Lazy properties ───────────────────────────────────────

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

    @property
    def memory(self):
        if not self._memory:
            from memory.store import MemoryStore
            self._memory = MemoryStore(self.s)
        return self._memory

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
                from learning.learning_engine import LearningEngine
                self._learning = LearningEngine(self.s)
            except Exception as e:
                log.debug("orchestrator_no_learning", err=str(e)[:60])
        return self._learning

    @property
    def metrics(self):
        """MetricsCollector : observabilité légère sans dépendance externe."""
        if not self._metrics:
            try:
                from monitoring.metrics import MetricsCollector
                self._metrics = MetricsCollector(self.s)
            except Exception as e:
                log.debug("orchestrator_no_metrics", err=str(e)[:60])
        return self._metrics

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
                from monitoring.metrics import LLMPerformanceMonitor
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

    @property
    def policy(self):
        """PolicyEngine : autorisation actions + routage LLM."""
        if self._policy is None:
            try:
                from core.policy_engine import PolicyEngine
                self._policy = PolicyEngine(self.s)
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

    # ── Classify intent (local, zero LLM) ────────────────────

    def classify_intent(self, user_input: str) -> str:
        """
        Classifie l'intention via regex locale (TaskRouter).
        Retourne une clé de INTENT_MAP.
        Aucun LLM requis — instanciable sans provider cloud.
        """
        decision = self.router.route(user_input)
        _mode_to_intent: dict[str, str] = {
            "improve":  "improve",
            "code":     "code",
            "research": "research",
            "plan":     "plan",
            "night":    "night",
            "chat":     "chat",
            "auto":     "default",
        }
        intent = _mode_to_intent.get(decision.mode.value, "default")
        log.debug("intent_classified",
                  input=user_input[:60], mode=decision.mode.value, intent=intent)
        return intent

    def _compute_mission_complexity(self, text: str) -> float:
        """
        Score de complexité 0.0–1.0 pour décider si AtlasDirector est nécessaire.
        Utilise ModelSelector si disponible, sinon heuristique locale (zéro LLM).

        > 0.60 → mission complexe → AtlasDirector
        ≤ 0.60 → plan statique TaskRouter (plus rapide)
        """
        try:
            if self.model_selector:
                return self.model_selector._compute_complexity(text)
        except Exception as _exc:
            log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:309")
        # Heuristique fallback — déterministe
        if not text:
            return 0.0
        length_score   = min(len(text) / 500.0, 0.35)
        keyword_score  = 0.0
        complex_kws    = (
            "architecture", "migration", "sécurité", "refactor",
            "système", "integr", "pipeline", "deploie", "configure",
            "optimise", "benchmark", "multi", "automatise",
        )
        matched = sum(1 for kw in complex_kws if kw in text.lower())
        keyword_score = min(matched * 0.10, 0.40)
        multi_sentence = 0.15 if text.count(".") >= 3 or text.count("\n") >= 2 else 0.0
        return round(min(length_score + keyword_score + multi_sentence, 1.0), 3)

    # ── Public API ────────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        mode: str = "auto",
        session_id: str | None = None,
        chat_id: int = 0,
        callback: CB | None = None,
    ) -> JarvisSession:

        self.s.ensure_dirs()
        session = JarvisSession(
            session_id=session_id or str(uuid.uuid4())[:8],
            user_input=user_input,
            mode=mode,
            # API_chat_id removed
        )

        async def emit(text: str):
            if callback:
                try:
                    await callback(text)
                except Exception as e:
                    log.warning("emit_failed", err=str(e))

        timeout = SESSION_TIMEOUTS.get(mode, 600)

        try:
            await asyncio.wait_for(
                self._dispatch(session, mode, emit),
                timeout=timeout,
            )
            session.status = SessionStatus.COMPLETED

        except asyncio.TimeoutError:
            session.status = SessionStatus.ERROR
            session.error  = f"Session timeout apres {timeout}s"
            await emit(f"Timeout de session apres {timeout}s. Resultats partiels disponibles.")
            log.error("session_timeout", sid=session.session_id, timeout=timeout)

        except asyncio.CancelledError:
            session.status = SessionStatus.CANCELLED
            await emit("Session annulee.")

        except Exception as e:
            log.error("orchestrator_error", sid=session.session_id, err=str(e))
            session.status = SessionStatus.ERROR
            session.error  = str(e)
            await emit(f"Erreur interne : {str(e)[:200]}")

        return session

    # ── Dispatch ──────────────────────────────────────────────

    async def _dispatch(self, session: JarvisSession, mode: str, emit: CB):
        if mode == "chat":
            await self._run_chat(session, emit)
        elif mode == "night":
            await self._run_night(session, emit)
        elif mode == "improve":
            await self._run_improve(session, emit)
        elif mode == "workflow":
            await self._run_workflow(session, emit)
        else:
            await self._run_auto(session, emit)

    # ── AUTO pipeline ─────────────────────────────────────────

    async def _run_auto(self, session: JarvisSession, emit: CB):
        # 0. GoalManager — enregistrer la mission
        try:
            if self.goal_manager:
                self.goal_manager.start(
                    text=session.user_input[:200],
                    mode=session.mode,
                    session_id=session.session_id,
                )
        except Exception as e:
            log.debug("goal_manager_start_failed", err=str(e)[:60])

        # 0b. DecisionReplay — démarrer l'enregistrement
        try:
            if self.replay:
                self.replay.record(session.session_id, "ROUTE", {
                    "mode": session.mode,
                    "input": session.user_input[:100],
                })
        except Exception as _exc:
            log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:414")

        # 1. Routing
        decision = self.router.route(session.user_input, explicit_mode=session.mode)
        session.task_mode    = decision.mode
        session.needs_actions = decision.needs_actions

        # 1b. Short-circuit: if TaskRouter decided CHAT, skip the full pipeline
        # and call _run_chat() directly (direct LLM call, ~1s instead of 5+ min).
        if decision.mode == TaskMode.CHAT:
            log.info("orchestrator_chat_shortcircuit",
                     sid=session.session_id,
                     reason=getattr(decision, "reason", ""),
                     input_len=len(session.user_input.strip()))
            return await self._run_chat(session, emit)

        # 2. Memoire en premier
        await emit("Rappel memoire...")
        await self.agents.run("vault-memory", session)

        # 3. Plan — adaptatif selon complexité de la mission
        # Missions complexes (score > 0.60) → AtlasDirector (plan LLM sur mesure)
        # Missions simples/standard → plan statique TaskRouter (rapide, déterministe)
        complexity   = self._compute_mission_complexity(session.user_input)
        use_director = (
            complexity > 0.60
            and decision.mode not in (TaskMode.CHAT,)
        )

        # 3a. Hierarchical decomposition (strategic layer) — fires before AtlasDirector
        # for high-complexity missions. Fail-open: if it fails, planning continues normally.
        if use_director:
            try:
                from core.hierarchical_planner import get_mission_decomposer
                _h_plan = get_mission_decomposer().decompose(
                    goal=session.user_input,
                    mission_type=str(getattr(decision, "mission_type", "general")),
                    complexity="high",
                    mission_id=session.session_id,
                )
                if _h_plan:
                    session._hierarchical_plan = _h_plan  # type: ignore[attr-defined]
                    await emit(
                        f"[HierarchicalPlanner] {len(_h_plan.macro_goals)} objectifs stratégiques, "
                        f"{_h_plan.total_tactical_steps} étapes tactiques."
                    )
                    log.info(
                        "hierarchical_plan_attached",
                        sid=session.session_id,
                        plan_id=_h_plan.plan_id,
                        macro_goals=len(_h_plan.macro_goals),
                        tactical_steps=_h_plan.total_tactical_steps,
                    )
            except Exception as _hp_exc:
                log.debug("hierarchical_plan_skip", err=str(_hp_exc)[:80])

        if use_director:
            await emit(f"Mission complexe (score={complexity:.2f}) — AtlasDirector planifie...")
            try:
                await self.agents.run("atlas-director", session)
                if not session.agents_plan:
                    raise ValueError("atlas-director a retourné un plan vide")
                log.info("auto_atlas_director_used",
                         sid=session.session_id, complexity=complexity,
                         agents=[a["agent"] for a in session.agents_plan])
            except Exception as e:
                log.warning("atlas_director_fallback_static",
                            err=str(e)[:80], complexity=complexity)
                # Fallback transparent vers plan statique
                session.mission_summary = session.user_input
                session.agents_plan     = [
                    a for a in decision.agents if a["agent"] != "vault-memory"
                ]
        else:
            # Plan statique TaskRouter — rapide et sans dépendance LLM
            session.mission_summary = session.user_input
            session.agents_plan     = [
                a for a in decision.agents if a["agent"] != "vault-memory"
            ]

        plan = session.agents_plan

        if session.agents_plan:
            planner    = "AtlasDirector" if use_director else "TaskRouter"
            agents_str = ", ".join(t["agent"] for t in session.agents_plan)
            await emit(
                f"Plan ({planner}) : {session.mission_summary[:100]}\n"
                f"Agents : {agents_str}"
            )

        # 3b. Smart agent selection — parse routing header from enriched goal
        try:
            import re as _re
            _shape = ""
            _complexity = ""
            # Parse structured header from enriched goal (session-safe, no shared state)
            _routing_match = _re.search(
                r'\[ROUTING:shape=(\w+),complexity=(\w*)\]',
                session.user_input or ""
            )
            if _routing_match:
                _shape = _routing_match.group(1)
                _complexity = _routing_match.group(2)

            if _shape and session.agents_plan:
                # Agent relevance map based on output shape
                _SHAPE_AGENTS = {
                    "direct_answer": {"scout-research"},
                    "diagnosis":     {"scout-research", "shadow-advisor"},
                    "patch":         {"scout-research", "forge-builder", "lens-reviewer"},
                    "plan":          {"scout-research", "map-planner", "forge-builder"},
                    "report":        {"scout-research", "map-planner", "lens-reviewer"},
                    "warning":       {"scout-research", "shadow-advisor"},
                }

                _relevant = _SHAPE_AGENTS.get(_shape)
                if _relevant and len(session.agents_plan) > 1:
                    _before = len(session.agents_plan)
                    session.agents_plan = [
                        a for a in session.agents_plan
                        if a.get("agent") in _relevant
                    ]
                    # Always keep at least 1 agent
                    if not session.agents_plan:
                        session.agents_plan = [{"agent": "scout-research", "task": session.mission_summary}]
                    _after = len(session.agents_plan)
                    if _after < _before:
                        log.info("smart_agent_selection",
                                 shape=_shape, before=_before, after=_after,
                                 agents=[a.get("agent") for a in session.agents_plan])
                        await emit(
                            f"[Routing] {_shape} → {_after} agent(s) sélectionné(s) "
                            f"(sur {_before})"
                        )
        except Exception as _ras_err:
            log.debug("smart_agent_selection_skipped", err=str(_ras_err)[:60])

        # 4. Agents paralleles par priorite
        await self._run_parallel(session, emit)

        # 4b. Mémoriser les sorties réussies dans AgentMemory (per-agent)
        try:
            if self.agent_memory and session.outputs:
                for name, out in session.outputs.items():
                    if out.success and out.content:
                        task_for_agent = next(
                            (t.get("task", "") for t in session.agents_plan
                             if t.get("agent") == name),
                            session.mission_summary or "",
                        )
                        self.agent_memory.record(
                            agent_name=name,
                            task=task_for_agent,
                            output=out.content,
                            success=True,
                            score=1.0,
                        )
        except Exception as e:
            log.debug("agent_memory_record_failed", err=str(e)[:80])

        # 5. Observer workspace
        await self._run_observer(session)

        # 6. Actions (seulement si needs_actions ET pulse-ops dans le plan)
        pulse_in_plan = any(
            t.get("agent") == "pulse-ops"
            for t in session.agents_plan
        )
        if session.needs_actions and pulse_in_plan:
            await self._process_actions(session, emit)
        elif session.needs_actions and not pulse_in_plan:
            log.info("skip_actions", reason="pulse-ops not in plan")

        # 7. Rapport final — statut calculé une seule fois ici (évite double log)
        session_status = self._compute_session_status(session)
        await self._generate_report(session, emit, session_status=session_status)
        mode_str = (session.task_mode.value if hasattr(session.task_mode, "value")
                    else str(session.task_mode))
        session_ok = (session_status["label"] != "FAILURE")

        try:
            if self.metrics:
                self.metrics.record_run(
                    mode=mode_str,
                    success=session_ok,
                    duration_s=0.0,
                )
        except Exception as e:
            log.debug("metrics_record_failed", err=str(e)[:60])

        # 8bis. LearningEngine — enregistrement réel (n'était jamais appelé)
        try:
            if self.learning:
                agents_ok:    dict[str, int] = {}
                agents_total: dict[str, int] = {}
                for name, out in session.outputs.items():
                    agents_total[name] = 1
                    agents_ok[name]    = 1 if out.success else 0

                self.learning.record_run({
                    "session_id":       session.session_id,
                    "mode":             mode_str,
                    "status":           session_status["label"],
                    "agents_ok":        session_status["ok"],
                    "agents_total":     session_status["total"],
                    "success_rate":     round(session_status["rate"], 3),
                    "patches_generated": len(getattr(session, "improve_pending", [])),
                    "patches_approved":  session.auto_count,
                    "patches_applied":   len(session.actions_executed),
                    "mission":          (session.mission_summary or "")[:100],
                    "agents_results":   {n: agents_ok.get(n, 0)
                                        for n in agents_total},
                })
        except Exception as e:
            log.debug("learning_record_failed", err=str(e)[:80])

        # 8b. LLM Performance Monitor — enregistrer latences agents + détecter drift
        try:
            if self.llm_perf:
                for name, out in session.outputs.items():
                    self.llm_perf.record(
                        role=name,
                        latency_ms=out.duration_ms if hasattr(out, "duration_ms") else 0,
                        error=not out.success,
                    )
                drift = self.llm_perf.get_drift_report()
                if drift.get("drifting"):
                    log.warning("llm_drift_detected", agents=list(drift.get("drifting", {}).keys()))
        except Exception as e:
            log.debug("llm_perf_record_failed", err=str(e)[:60])

        # 8c. Évaluation qualité session (tracked background task — ne bloque pas)
        try:
            if self.evaluator and session.outputs:
                _task = asyncio.create_task(
                    self._evaluate_session_async(session)
                )
                self._bg_tasks.add(_task)
                _task.add_done_callback(self._bg_tasks.discard)
        except Exception as e:
            log.debug("evaluator_schedule_failed", err=str(e)[:60])

        # 9. Mémoriser dans VectorMemory (contexte session)
        try:
            if self.vector_memory and session.final_report:
                self.vector_memory.add(
                    session.final_report[:1000],
                    metadata={"type": "session", "mode": str(session.task_mode),
                               "session_id": session.session_id},
                )
        except Exception as e:
            log.debug("vector_memory_store_failed", err=str(e)[:60])

        # 10. Memoriser (MemoryStore existant)
        try:
            await self.memory.store_session(session)
        except Exception as e:
            log.warning("memory_store_failed", err=str(e))

        # 10b. MemoryBus — mémoriser également via bus unifié
        try:
            if self.memory_bus and session.mission_summary:
                await self.memory_bus.remember_async(
                    text=session.mission_summary[:500],
                    metadata={
                        "session_id": session.session_id,
                        "mode": str(getattr(session.task_mode, "value", session.task_mode)),
                        "agents": [t.get("agent") for t in session.agents_plan],
                    },
                )
        except Exception as e:
            log.debug("memory_bus_store_failed", err=str(e)[:60])

        # 11. GoalManager — marquer la mission comme terminée
        try:
            if self.goal_manager:
                active = self.goal_manager.get_active()
                if active and active.session_id == session.session_id:
                    result_summary = (session.final_report or "")[:200]
                    has_error = bool(getattr(session, "error", None))
                    if has_error:
                        self.goal_manager.fail(active.id,
                                               error=str(session.error)[:100])
                    else:
                        self.goal_manager.complete(active.id,
                                                   result=result_summary)
        except Exception as e:
            log.debug("goal_manager_complete_failed", err=str(e)[:60])

        # 12. SystemState — enregistrer les métriques de la session
        try:
            if self.system_state and session.outputs:
                for name, out in session.outputs.items():
                    self.system_state.update_module(
                        name,
                        healthy=out.success,
                        latency_ms=getattr(out, "duration_ms", 0),
                        error=getattr(out, "error", "") or "",
                    )
        except Exception as e:
            log.debug("system_state_update_failed", err=str(e)[:60])

        # 13. DecisionReplay — enregistrer le résultat
        try:
            if self.replay:
                ok_agents = sum(1 for o in session.outputs.values() if o.success)
                self.replay.record(session.session_id, "RESULT", {
                    "status": getattr(session.status, "value", str(session.status)),
                    "agents_ok": ok_agents,
                    "has_report": bool(session.final_report),
                })
                self.replay.flush()
        except Exception as _exc:
            log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:642")

    async def _run_chat(self, session: JarvisSession, emit: CB):
        """Reponse directe sans agents — protégée par circuit breaker."""
        from langchain_core.messages import SystemMessage, HumanMessage
        from core.llm_factory import LLMFactory

        messages = [
            SystemMessage(content=(
                f"Tu es {self.s.jarvis_name}, assistant personnel. "
                "Reponds de facon concise et directe."
            )),
            HumanMessage(content=session.user_input),
        ]
        try:
            factory = LLMFactory(self.s)
            resp = await factory.safe_invoke(messages, role="fast", timeout=45.0)
            session.final_report = resp.content
            await emit(resp.content[:3500])
        except asyncio.TimeoutError:
            msg = "Le modele ne repond pas (timeout). Verifiez /status."
            session.final_report = msg
            await emit(msg)
        except Exception as e:
            log.error("chat_llm_error", sid=session.session_id, err=str(e)[:100])
            msg = f"Erreur LLM : {str(e)[:200]}"
            session.final_report = msg
            await emit(msg)

    async def _run_night(self, session: JarvisSession, emit: CB):
        # GoalManager — enregistrer la mission night
        goal_id: str | None = None
        try:
            if self.goal_manager:
                g = self.goal_manager.start(
                    text=session.user_input[:200],
                    mode="night",
                    session_id=session.session_id,
                )
                goal_id = g.id
                log.info("goal_started", goal_id=goal_id, mode="night",
                         sid=session.session_id)
        except Exception as e:
            log.debug("goal_manager_night_start_failed", err=str(e)[:60])

        try:
            from night_worker.worker import NightWorkerEngine
            engine = NightWorkerEngine(self.s, self.executor, self.risk)
            await engine.run(session, emit)

            # GoalManager — mission terminée
            try:
                if self.goal_manager and goal_id:
                    self.goal_manager.complete(
                        goal_id,
                        result=(session.final_report or "Night worker terminé")[:200],
                    )
                    log.info("goal_completed", goal_id=goal_id, mode="night")
            except Exception as e:
                log.debug("goal_manager_night_complete_failed", err=str(e)[:60])

        except Exception as exc:
            try:
                if self.goal_manager and goal_id:
                    self.goal_manager.fail(goal_id, error=str(exc)[:100])
                    log.warning("goal_failed", goal_id=goal_id, mode="night",
                                err=str(exc)[:80])
            except Exception as _exc:
                log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:710")
            raise

    async def _run_improve(self, session: JarvisSession, emit: CB):
        from core.self_improvement_engine import run_improvement_cycle
        result = await run_improvement_cycle()
        if emit:
            await emit(f"Self-improvement: {result.get('status', 'done')}")
        session.final_report = str(result.get("summary", "improvement cycle complete"))

    async def _run_workflow(self, session: JarvisSession, emit: CB):
        """Crée et/ou exécute un workflow depuis la demande utilisateur."""
        # GoalManager — enregistrer la mission workflow
        goal_id: str | None = None
        try:
            if self.goal_manager:
                g = self.goal_manager.start(
                    text=session.user_input[:200],
                    mode="workflow",
                    session_id=session.session_id,
                )
                goal_id = g.id
                log.info("goal_started", goal_id=goal_id, mode="workflow",
                         sid=session.session_id)
        except Exception as e:
            log.debug("goal_manager_workflow_start_failed", err=str(e)[:60])

        try:
            from agents.workflow_agent import WorkflowAgent
            agent  = WorkflowAgent(self.s)
            result = await agent.create_from_text(session.user_input, emit=emit)

            if result.get("status") == "created" and result.get("workflow_id"):
                wf_id   = result["workflow_id"]
                wf_name = result["workflow"].get("name", wf_id)
                await emit(f"Workflow '{wf_name}' créé. Exécution...")
                report  = await agent.run_workflow(wf_id, emit=emit)
                session.final_report = (
                    f"Workflow {wf_name} — {report.get('status', '?')}\n"
                    f"Étapes : {report.get('steps_done', 0)}/{report.get('steps_total', 0)}\n"
                    f"Durée  : {report.get('duration_s', 0)}s"
                )
                await emit(f"Rapport workflow\n\n{session.final_report}")
            else:
                session.final_report = (
                    f"Workflow non créé : {result.get('error', 'erreur inconnue')}"
                )
                await emit(session.final_report)

            # GoalManager — marquer terminé
            try:
                if self.goal_manager and goal_id:
                    has_error = result.get("status") != "created"
                    if has_error:
                        self.goal_manager.fail(
                            goal_id,
                            error=result.get("error", "workflow non créé")[:100],
                        )
                    else:
                        self.goal_manager.complete(
                            goal_id,
                            result=session.final_report[:200],
                        )
                    log.info("goal_completed", goal_id=goal_id, mode="workflow",
                             success=not has_error)
            except Exception as e:
                log.debug("goal_manager_workflow_complete_failed", err=str(e)[:60])

        except Exception as exc:
            try:
                if self.goal_manager and goal_id:
                    self.goal_manager.fail(goal_id, error=str(exc)[:100])
                    log.warning("goal_failed", goal_id=goal_id, mode="workflow",
                                err=str(exc)[:80])
            except Exception as _exc:
                log.debug("orchestrator_exception", err=str(_exc)[:120], location="orchestrator:785")
            raise

    # ── Parallel agent execution ──────────────────────────────

    async def _run_parallel(self, session: JarvisSession, emit: CB):
        """
        Exécution parallèle des agents via ParallelExecutor.
        Les agents sont regroupés par priorité et exécutés par vague :
          P1 (vault-memory) → P2 (scout, map-planner, forge, …) → P3 (lens-reviewer)
        Cela garantit que lens-reviewer (P3) dispose du contexte P2 complet
        avant de démarrer son évaluation.
        """
        from agents.parallel_executor import ParallelExecutor
        pex = ParallelExecutor(self.s)

        # Filtrer les agents non-supportés
        skip = {"atlas-director", "vault-memory"}
        tasks = [
            t for t in session.agents_plan
            if t.get("agent", "") not in skip
            and t.get("agent", "") in self.agents.registry
        ]

        if not tasks:
            log.debug("parallel_no_tasks")
            return

        mode_val = getattr(session.task_mode, "value", str(session.task_mode))

        # ── Exécution par vague de priorité ──────────────────────
        # group_by_priority() retourne une liste de listes ordonnées par priorité.
        # On exécute chaque vague séquentiellement, mais en parallèle à l'intérieur.
        priority_waves = ParallelExecutor.group_by_priority(tasks)
        all_results: dict = {}
        total_ok = 0
        total_failed: list[str] = []

        for wave_idx, wave_tasks in enumerate(priority_waves):
            wave_priorities = sorted({t.get("priority", 2) for t in wave_tasks})
            log.debug("parallel_wave_start",
                      wave=wave_idx, priorities=wave_priorities,
                      agents=[t.get("agent") for t in wave_tasks])

            # Replan dynamique uniquement sur les vagues non-P3 en mode non-chat
            has_critical = any(t.get("priority", 2) <= 2 for t in wave_tasks)
            use_replan   = (mode_val != "chat") and has_critical

            if use_replan:
                wave_results = await pex.run_with_replan(
                    wave_tasks, session, emit=emit, max_replan_rounds=1
                )
            else:
                wave_results = await pex.run(wave_tasks, session, emit=emit)

            all_results.update(wave_results)
            wave_ok     = sum(1 for r in wave_results.values() if r.success)
            wave_failed = [r.agent for r in wave_results.values() if not r.success]
            total_ok     += wave_ok
            total_failed += wave_failed

            log.info("parallel_wave_done",
                     wave=wave_idx, priorities=wave_priorities,
                     ok=wave_ok, failed=len(wave_failed))

        # Comptabiliser succès/échecs globaux
        msg = f"Parallel : {total_ok}/{len(all_results)} agents OK"
        if total_failed:
            msg += f" | Echecs : {', '.join(total_failed)}"
        await emit(msg)
        log.info("parallel_done", ok=total_ok, failed=len(total_failed),
                 waves=len(priority_waves))

    # ── Observer ──────────────────────────────────────────────

    async def _run_observer(self, session: JarvisSession):
        try:
            from observer.watcher import SystemObserver
            snap = await SystemObserver(self.s).snapshot_workspace()
            session.set_output("observer", snap, success=True)
        except Exception as e:
            log.warning("observer_failed", err=str(e))

    # ── Action processing ─────────────────────────────────────

    async def _process_actions(self, session: JarvisSession, emit: CB):
        """
        Traite les actions collectées par PulseOps via SupervisedExecutor.
        SupervisedExecutor centralise : analyse risque → décision → exécution.
        """
        raw = session._raw_actions
        if not raw:
            return

        # Construire les ActionSpec depuis les dicts bruts
        actions: list[ActionSpec] = []
        for item in raw:
            if session.auto_count >= self.s.max_auto_actions:
                await emit(f"Limite d actions auto atteinte ({self.s.max_auto_actions}).")
                break
            actions.append(ActionSpec(
                id=str(uuid.uuid4())[:8],
                action_type=item.get("action_type", ""),
                target=item.get("target", ""),
                content=item.get("content", ""),
                command=item.get("command", ""),
                old_str=item.get("old_str", ""),
                new_str=item.get("new_str", ""),
                description=item.get("description", ""),
            ))

        if not actions:
            return

        # Injecter l'emit dans SupervisedExecutor pour les notifications
        from executor.supervised_executor import SupervisedExecutor
        sup = SupervisedExecutor(self.s, emit=emit)

        executed, pending = await sup.execute_batch(
            actions,
            session_id=session.session_id,
            agent="pulse-ops",
            max_auto=self.s.max_auto_actions,
        )

        # Mettre à jour la session
        for result in executed:
            if result.success:
                session.actions_executed.append(result.to_dict())
                session.auto_count += 1

        session.actions_pending.extend(pending)

        auto_done = sum(1 for r in executed if r.success)
        if auto_done:
            await emit(f"{auto_done} action(s) executee(s) automatiquement")
        if pending:
            await emit(f"{len(pending)} action(s) en attente de validation")

    async def _evaluate_session_async(self, session: JarvisSession) -> None:
        """Évalue les sorties de la session via AgentEvaluator (fire-and-forget)."""
        try:
            report = await self.evaluator.evaluate_session(session)
            log.info(
                "session_evaluated",
                sid=session.session_id,
                avg_score=round(report.average_score, 2),
                agents=len(report.results),
            )
        except Exception as e:
            log.debug("session_eval_failed", err=str(e)[:60])

    # ── Session status (vérité sur le succès) ─────────────────

    def _compute_session_status(self, session: JarvisSession) -> dict:
        """
        Calcule le statut réel de la session : SUCCESS / PARTIAL / FAILURE.

        Règles :
            SUCCESS  : ≥80 % des agents planifiés ont réussi
            PARTIAL  : 20–79 % de succès
            FAILURE  : <20 % de succès OU erreur explicite de session

        Retourne :
            {
              "label":   "SUCCESS" | "PARTIAL" | "FAILURE",
              "badge":   "✅" | "⚠️" | "❌",
              "ok":      int,   # agents réussis
              "total":   int,   # agents planifiés
              "rate":    float, # 0.0 – 1.0
              "failed":  list[str],  # noms des agents échoués
            }
        """
        planned_names = [t.get("agent", "") for t in session.agents_plan if t.get("agent")]
        total = len(planned_names)

        if total == 0:
            # Aucun plan : statut basé sur la présence d'une erreur session
            if getattr(session, "error", None):
                return {"label": "FAILURE", "badge": "❌", "ok": 0, "total": 0,
                        "rate": 0.0, "failed": []}
            return {"label": "SUCCESS", "badge": "✅", "ok": 0, "total": 0,
                    "rate": 1.0, "failed": []}

        ok    = 0
        failed: list[str] = []
        for name in planned_names:
            out = session.outputs.get(name)
            if out and out.success and out.content:
                ok += 1
            else:
                failed.append(name)

        rate = ok / total

        if getattr(session, "error", None):
            label, badge = "FAILURE", "❌"
        elif rate >= 0.80:
            label, badge = "SUCCESS", "✅"
        elif rate >= 0.20:
            label, badge = "PARTIAL", "⚠️"
        else:
            label, badge = "FAILURE", "❌"

        log.info("session_status_computed",
                 label=label, ok=ok, total=total, rate=round(rate, 2),
                 failed=failed[:5], sid=session.session_id)

        return {
            "label": label, "badge": badge,
            "ok": ok, "total": total,
            "rate": rate, "failed": failed,
        }

    # ── Final report ──────────────────────────────────────────

    async def _generate_report(self, session: JarvisSession, emit: CB, session_status: dict | None = None):
        # Import messages uniquement — le LLM est invoqué via safe_invoke
        from langchain_core.messages import SystemMessage, HumanMessage

        # Exclure les agents internes du rapport visible
        exclude = {"vault-memory", "pulse-ops", "observer", "atlas-director"}
        raw_outputs = {
            k: v.content
            for k, v in session.outputs.items()
            if v.success and v.content and k not in exclude
        }

        # Synthèse heuristique des résultats multi-agents
        if len(raw_outputs) > 1:
            try:
                from agents.synthesizer_agent import SynthesizerAgent
                synth  = SynthesizerAgent(self.s)
                synth_result = await synth.synthesize(
                    raw_outputs, session.mission_summary, emit=emit, include_plan=False
                )
                snippets = synth_result.get("merged", "") or "\n\n".join(
                    f"[{k}]:\n{v[:600]}" for k, v in raw_outputs.items()
                )
            except Exception as e:
                log.warning("synthesizer_skipped", err=str(e)[:80])
                snippets = "\n\n".join(
                    f"[{k}]:\n{v[:600]}" for k, v in raw_outputs.items()
                )
        else:
            snippets = "\n\n".join(
                f"[{k}]:\n{v[:600]}" for k, v in raw_outputs.items()
            )

        if not snippets:
            snippets = "(aucun resultat agent)"

        actions_note = ""
        if session.actions_executed:
            actions_note += f"\n{len(session.actions_executed)} action(s) executee(s)"
        if session.actions_pending:
            actions_note += f"\n{len(session.actions_pending)} action(s) en attente de ta validation"

        # ── Statut réel de la session (vérité obligatoire dans le rapport) ──
        # Réutilise le statut précalculé (évite double émission session_status_computed)
        status_info = session_status if session_status is not None else self._compute_session_status(session)
        status_label = status_info["label"]
        status_badge = status_info["badge"]
        status_note  = (
            f"Statut réel : {status_badge} {status_label} "
            f"({status_info['ok']}/{status_info['total']} agents OK)"
        )
        if status_info["failed"]:
            status_note += f"\nAgents en échec : {', '.join(status_info['failed'])}"

        try:
            from core.llm_factory import LLMFactory
            factory  = LLMFactory(self.s)
            messages = [
                SystemMessage(content=(
                    f"Tu es {self.s.jarvis_name}. "
                    "Redige un rapport final concis pour Max.\n"
                    "1) Statut honnête (SUCCESS/PARTIAL/FAILURE) avec justification. "
                    "2) Synthese (2 phrases). "
                    "3) Points cles. "
                    "4) Prochaines etapes.\n"
                    "RÈGLE ABSOLUE : le statut dans ton rapport DOIT correspondre "
                    "au statut réel ci-dessous. Ne déclare jamais SUCCESS si des agents ont échoué."
                )),
                HumanMessage(content=(
                    f"Mission : {session.mission_summary}\n\n"
                    f"{status_note}\n\n"
                    f"Resultats agents :\n{snippets}{actions_note}"
                )),
            ]
            resp = await factory.safe_invoke(messages, role="fast", timeout=60.0)
            report_text = resp.content if resp else snippets[:2000]
            session.final_report = f"{status_badge} **{status_label}**\n\n{report_text}"
            await emit(f"Rapport final {status_badge}\n\n{report_text[:3500]}")
        except asyncio.TimeoutError:
            session.final_report = f"{status_badge} **{status_label}** (timeout LLM)\n\n{snippets[:2000]}"
            await emit(f"Rapport (timeout LLM)\n\n{snippets[:2000]}")
