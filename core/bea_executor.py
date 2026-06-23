"""
core.bea_executor
=================
BeaOrchestrator — internal execution delegate used by MetaOrchestrator.

External callers: use get_meta_orchestrator() from core.meta_orchestrator.
BeaOrchestrator is an internal component, not a public API.

All heavy logic lives in the executor mixins under core/executor/:
  LazyComponentsMixin   — lazy subsystem properties
  PipelineAutoMixin     — _run_auto, _run_parallel, _run_observer,
                          _process_actions, _evaluate_session_async,
                          classify_intent, _compute_mission_complexity
  PipelineModesMixin    — _run_chat, _run_night, _run_improve, _run_workflow
  ReportingMixin        — _compute_session_status, _generate_report
"""
from __future__ import annotations
import asyncio
import uuid
import structlog
from typing import Callable, Awaitable

from core.state import BeaSession, SessionStatus, TaskMode  # noqa: F401 (re-exported)
from core.task_router import TaskRouter
from config.settings import get_settings
from core.executor.lazy_components import LazyComponentsMixin
from core.executor.pipeline_auto import PipelineAutoMixin
from core.executor.pipeline_modes import PipelineModesMixin
from core.executor.reporting import ReportingMixin

log = structlog.get_logger()
CB = Callable[[str], Awaitable[None]]

SESSION_TIMEOUTS: dict[str, int] = {
    "auto":     600,
    "night":    1800,
    "improve":  900,
    "chat":     60,
    "business": 720,
    "code":     600,
    "plan":     600,
    "research": 600,
}


class BeaOrchestrator(
    LazyComponentsMixin,
    PipelineAutoMixin,
    PipelineModesMixin,
    ReportingMixin,
):
    """
    Internal execution delegate for MetaOrchestrator.

    Dispatches a BeaSession to the appropriate pipeline mixin based on mode:
      auto/code/business/plan/research → PipelineAutoMixin._run_auto
      chat                             → PipelineModesMixin._run_chat
      night                            → PipelineModesMixin._run_night
      improve                          → PipelineModesMixin._run_improve
      workflow                         → PipelineModesMixin._run_workflow
    """

    INTENT_MAP: dict[str, str] = {
        "improve":  "self_improve",
        "code":     "forge-builder",
        "research": "scout-research",
        "plan":     "map-planner",
        "night":    "night-worker",
        "chat":     "shadow-advisor",
        "workflow": "workflow-agent",
        "default":  "shadow-advisor",
    }

    def __init__(self, settings=None):
        self.s      = settings or get_settings()
        self.router = TaskRouter()
        # Lazy component slots (populated by LazyComponentsMixin)
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
        self._circuit_breakers = None
        self._policy       = None
        self._goal_mgr     = None
        self._sys_state    = None
        self._replay       = None
        self._agent_memory = None
        self._bg_tasks: set = set()

    # ── Public entry point ────────────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        mode: str = "auto",
        session_id: str | None = None,
        chat_id: int = 0,
        callback: CB | None = None,
    ) -> BeaSession:
        self.s.ensure_dirs()
        session = BeaSession(
            session_id=session_id or str(uuid.uuid4())[:8],
            user_input=user_input,
            mode=mode,
        )
        # Ensure a shared PolicyEngine session tracker exists for this mission.
        try:
            self.policy.ensure_session(session.session_id, mode)
        except Exception as _pol_err:
            log.debug("policy_session_ensure_failed", mission_id=session.session_id, err=str(_pol_err)[:80])

        async def emit(text: str):
            if callback:
                try:
                    await callback(text)
                except Exception as e:
                    log.warning("emit_failed", err=str(e))

        timeout = SESSION_TIMEOUTS.get(mode, 600)
        try:
            await asyncio.wait_for(self._dispatch(session, mode, emit), timeout=timeout)
            session.status = SessionStatus.COMPLETED
        except asyncio.TimeoutError:
            session.status = SessionStatus.ERROR
            session.error  = f"Session timeout apres {timeout}s"
            await emit(f"Timeout de session apres {timeout}s. Resultats partiels disponibles.")
            log.error("session_timeout", mission_id=session.session_id, timeout=timeout)
        except asyncio.CancelledError:
            session.status = SessionStatus.CANCELLED
            await emit("Session annulee.")
        except Exception as e:
            log.error("orchestrator_error", mission_id=session.session_id, err=str(e))
            session.status = SessionStatus.ERROR
            session.error  = str(e)
            await emit(f"Erreur interne : {str(e)[:200]}")

        # ── Inject provider/model metadata into session.metadata ──────────────
        # Reads from session_meta_bus: actual LLM calls (llm_factory) take precedence
        # over planned routing (execution_supervised_runner).  Never overwrites an
        # existing value — older code paths that populate metadata directly are
        # respected.  No API keys are read or stored here.
        try:
            from core.executor.session_meta_bus import build_session_metadata_patch
            patch = build_session_metadata_patch(session.metadata)
            if patch:
                session.metadata.update(patch)
                log.debug(
                    "session_metadata_injected",
                    sid=session.session_id,
                    keys=list(patch.keys()),
                )
        except Exception as _bus_exc:
            log.debug("session_metadata_inject_failed", err=str(_bus_exc)[:80])

        return session

    # ── Mode dispatcher ───────────────────────────────────────────────────

    async def _dispatch(self, session: BeaSession, mode: str, emit: CB):
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
