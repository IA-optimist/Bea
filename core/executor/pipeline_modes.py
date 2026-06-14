"""
core.executor.pipeline_modes
==============================
PipelineModesMixin: per-mode execution pipelines for BeaOrchestrator.
Covers: chat, night, improve, workflow.
"""
from __future__ import annotations
import asyncio
import structlog

from core.state import BeaSession
from .constants import CB

log = structlog.get_logger()


class PipelineModesMixin:
    """Mixin providing _run_chat, _run_night, _run_improve, _run_workflow."""

    async def _run_chat(self, session: BeaSession, emit: CB):
        """Reponse directe sans agents — protégée par circuit breaker."""
        from langchain_core.messages import SystemMessage, HumanMessage
        from core.llm_factory import LLMFactory

        messages = [
            SystemMessage(content=(
                f"Tu es {self.s.bea_name}, assistant personnel. "
                "Reponds de facon concise et directe."
            )),
            HumanMessage(content=session.user_input),
        ]
        try:
            factory = LLMFactory(self.s)
            # Timeout: 120s to accommodate Ollama CPU inference. Cloud providers respond in <5s.
            resp = await factory.safe_invoke(messages, role="fast", timeout=120.0)
            session.final_report = resp.content
            await emit(resp.content[:3500])
        except asyncio.TimeoutError:
            msg = "Le modele ne repond pas (timeout). Verifiez /status."
            session.final_report = msg
            await emit(msg)
        except Exception as e:
            log.error("chat_llm_error", mission_id=session.session_id, err=str(e)[:100])
            msg = f"Erreur LLM : {str(e)[:200]}"
            session.final_report = msg
            await emit(msg)

    async def _run_night(self, session: BeaSession, emit: CB):
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

    async def _run_improve(self, session: BeaSession, emit: CB):
        # Audit S8 / issue #15: migrated from `core.self_improvement_engine`
        # legacy shim to the canonical SelfImprovementEngine. The legacy
        # facade returned a coroutine (because it never awaited) — the
        # previous `await run_improvement_cycle()` worked only by accident.
        from core.self_improvement.engine import SelfImprovementEngine
        engine = SelfImprovementEngine()
        result = await engine.run_cycle()
        if emit:
            await emit(f"Self-improvement: {result.get('status', 'done')}")
        session.final_report = str(result.get("summary", "improvement cycle complete"))

    async def _run_workflow(self, session: BeaSession, emit: CB):
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
