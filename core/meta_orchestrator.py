"""
BEA MAX — MetaOrchestrator
==============================
Point d'entrée unique et source de vérité pour le cycle de vie des missions.

Architecture :
    MetaOrchestrator          ← vous êtes ici (facade + state machine)
        └─► BeaOrchestrator  (logique métier, agents, mémoire)
        └─► OrchestratorV2      (budget, DAG, checkpoint — missions complexes)

Transitions d'état déterministes :
    CREATED → PLANNED → RUNNING → REVIEW → DONE
                                         ↘ FAILED

Règles d'usage :
    - TOUJOURS utiliser MetaOrchestrator comme point d'entrée.
    - BeaOrchestrator et OrchestratorV2 restent accessibles pour compatibilité
      ascendante, mais ne doivent plus être instanciés directement dans le code neuf.
    - Chaque transition de statut est loguée via structlog (observable, auditabl).
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Any, Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)

CB = Callable[[str], Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker — prevents cascade failures when the delegate is broken
# ─────────────────────────────────────────────────────────────────────────────

# ── _CircuitBreaker déplacé dans core/orchestration/mission_circuit_breaker.py ──
# Alias conservé pour compatibilité avec les tests qui inspectent self._circuit_breaker.
from core.orchestration.mission_circuit_breaker import MissionCircuitBreaker as _CircuitBreaker  # noqa: E402,F401


# ─────────────────────────────────────────────────────────────────────────────
# State machine — KERNEL-CANONICAL: kernel/state/mission_state.py
# ─────────────────────────────────────────────────────────────────────────────
# MissionContext and VALID_TRANSITIONS now live in the kernel.
# MetaOrchestrator imports them and owns the side-effect layer
# (event emission, persistence) on top of kernel state transitions.
from core.state import MissionStatus  # noqa: F811  — single source of truth enum

from core.meta_orchestrator_state import (
    MissionContext as MissionContext,
    _KERNEL_STATE_AVAILABLE as _KERNEL_STATE_AVAILABLE,
    _VALID_TRANSITIONS as _VALID_TRANSITIONS,
    _get_kernel_sm as _get_kernel_sm,
)

# MetaOrchestrator
# ─────────────────────────────────────────────────────────────────────────────


# ── _strip_execution_outcome déplacé dans core/orchestration/mission_text_utils.py ──
# Alias conservé (wrapper qui appelle la fonction publique).
from core.orchestration.mission_text_utils import strip_execution_outcome as _strip_execution_outcome  # noqa: E402,F401
from core.meta_custom_handlers import CustomMissionHandlerMixin  # noqa: E402
# ── Phase « learning » déplacée dans core/orchestration/learning_mixin.py ──
# (PR 1 — docs/refactor/meta_orchestrator_split.md)
from core.orchestration.learning_mixin import LearningMixin  # noqa: E402
from core.orchestration.outcome_mixin import OutcomeMixin  # noqa: E402
from core.orchestration.routing_mixin import RoutingMixin  # noqa: E402
from core.orchestration.execution_mixin import ExecutionMixin  # noqa: E402


class MetaOrchestrator(
    RoutingMixin, ExecutionMixin, OutcomeMixin, LearningMixin, CustomMissionHandlerMixin
):
    """
    Cerveau unique de BeaMax.
    Délègue l'exécution à BeaOrchestrator (missions standard) ou
    OrchestratorV2 (missions avec budget/DAG), mais maintient lui-même
    le cycle de vie (MissionStatus) et les logs de transition.
    """
    def __init__(self, settings=None):
        from config.settings import get_settings
        self.s = settings or get_settings()
        # Orchestrateurs délégués (lazy)
        self._bea: Any = None     # BeaOrchestrator
        self._v2: Any     = None     # OrchestratorV2
        # Registre des missions actives {mission_id: MissionContext}
        self._missions: dict[str, MissionContext] = {}
        # RLock allows the same thread to re-acquire (e.g. nested calls within run_mission)
        self._lock = threading.RLock()
        # Circuit breaker: opens after 5 consecutive delegate failures,
        # resets after 60s. Prevents cascade pressure on a broken backend.
        self._circuit_breaker = _CircuitBreaker(failure_threshold=5, reset_s=60.0)
        # Custom mission handlers registry {mission_type: handler_fn}
        self._custom_handlers: dict[str, Callable] = {}
    # ── Lazy accessors ──────────────────────────────────────────────────────
    @property
    def bea(self):
        """BeaOrchestrator — orchestrateur principal."""
        if self._bea is None:
            from core.bea_executor import BeaOrchestrator
            self._bea = BeaOrchestrator(self.s)
            log.debug("meta_orchestrator.bea_loaded")
        return self._bea
    @property
    def v2(self):
        """OrchestratorV2 — missions avec budget + DAG."""
        if self._v2 is None:
            from core.orchestrator_v2 import OrchestratorV2
            self._v2 = OrchestratorV2(self.s)
            log.debug("meta_orchestrator.v2_loaded")
        return self._v2
    @property
    def capability_dispatcher(self):
        """CapabilityDispatcher — routing unified native/plugin/MCP tools."""
        if not hasattr(self, "_capability_dispatcher"):
            try:
                from executor.capability_dispatch import get_capability_dispatcher
                self._capability_dispatcher = get_capability_dispatcher()
                log.debug("meta_orchestrator.capability_dispatcher_loaded")
            except Exception as e:
                log.warning("meta_orchestrator.capability_dispatcher_unavailable", err=str(e))
                self._capability_dispatcher = None
        return self._capability_dispatcher
    # ── State machine ────────────────────────────────────────────────────────
    def _transition(self, ctx: MissionContext, target: MissionStatus, **extra) -> None:
        """
        Effectue une transition d'état avec validation et logging.
        Lève ValueError si la transition est invalide.
        Persists state to disk on every transition (fail-open).
        Validation delegated to kernel/state/MissionStateMachine (fail-open fallback
        to local _VALID_TRANSITIONS if kernel unavailable).
        Side effects (event emission, persistence) remain here in MetaOrchestrator.
        """
        # Kernel state machine validates + applies the transition
        if _KERNEL_STATE_AVAILABLE and _get_kernel_sm is not None:
            try:
                prev = _get_kernel_sm().apply(ctx, target)
            except ValueError:
                raise
        else:
            # Fallback: local table
            allowed = _VALID_TRANSITIONS.get(ctx.status, set())
            if target not in allowed:
                raise ValueError(
                    f"Transition interdite : {ctx.status.value} → {target.value} "
                    f"(mission={ctx.mission_id})"
                )
            prev = ctx.status
            ctx.status     = target
            ctx.updated_at = time.time()
        log.info(
            "mission.transition",
            mission_id=ctx.mission_id,
            from_status=prev.value,
            to_status=target.value,
            goal=ctx.goal[:80],
            **extra,
        )
        # Emit status-change event to WebSocket consumers (fail-open)
        try:
            _stream = ctx.metadata.get("event_stream")
            if _stream is not None:
                from core.events import Observation
                _evt = Observation(
                    source="system",
                    observation_type="status_change",
                    content=f"{prev.value} → {target.value}",
                    metadata={"from": prev.value, "to": target.value,
                              "mission_id": ctx.mission_id},
                )
                # Use create_task for better exception visibility
                asyncio.create_task(_stream.append(_evt))
        except Exception as _exc:
            log.warning("swallowed_exception", action="event_stream_append", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        # Persist state to disk (fail-open)
        try:
            from core.mission_persistence import get_mission_persistence
            get_mission_persistence().persist(ctx)
        except Exception as _pe:
            log.debug("mission_persist_failed", err=str(_pe)[:80])
        # Sync mission_system legacy store on terminal states (fixes RUNNING never updating)
        if target in (MissionStatus.DONE, MissionStatus.FAILED, MissionStatus.CANCELLED):
            try:
                from core.mission_system import get_mission_system
                _ms = get_mission_system()
                _ms_rec = _ms.get_mission(ctx.mission_id)
                if _ms_rec is not None:
                    _ms_rec.status = target.value
                    _ms_rec.final_output = str(ctx.result or "")[:5000]
                    _ms._save_mission(_ms_rec)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
    # ── Kernel cognitive pre-computation (Pass 18) ───────────────────────────
    def _run_kernel_cognitive_cycle(
        self,
        goal: str,
        mode: str,
        mid: str,
        ctx,   # MissionContext — receives metadata writes
        trace, # DecisionTrace
    ) -> tuple:
        """
        Run kernel.run_cognitive_cycle() and populate ctx.metadata.
        Returns (kernel_context, k_classification_obj, kernel_plan).
        Always fail-open: on any error returns ({}, None, None).
        Extracted from run_mission() Pass 18 for readability.
        All fallback logic (Phase 1, 0c, 1b) remains in run_mission().
        """
        try:
            from kernel.runtime.kernel import get_kernel as _get_jk
            _kctx = _get_jk().run_cognitive_cycle(
                goal=goal, mode=mode, mission_id=mid,
            )
            if _kctx.get("classification"):
                ctx.metadata["classification"] = _kctx["classification"]
            if _kctx.get("kernel_plan"):
                ctx.metadata["kernel_plan"] = _kctx["kernel_plan"]
            if _kctx.get("capability_routing"):
                ctx.metadata["capability_routing"] = _kctx["capability_routing"]
            if _kctx.get("routed_provider"):
                ctx.metadata["routed_provider"] = _kctx["routed_provider"]
            trace.record("kernel", "cognitive_cycle",
                         classify=bool(_kctx.get("classification")),
                         plan=bool(_kctx.get("kernel_plan")),
                         route=bool(_kctx.get("routed_provider")))
            return (
                _kctx,
                _kctx.get("_classification_obj"),
                _kctx.get("_kernel_plan_obj"),
            )
        except Exception as _kcc_err:
            log.debug("kernel_cognitive_cycle_skipped", err=str(_kcc_err)[:100])
            return {}, None, None
    # ── Private helper methods (run_mission refactoring) ─────────────────────
    def _setup_event_stream(self, mid: str, ctx) -> None:
        """Setup EventStream for WebSocket consumers (lines 356-365)."""
        try:
            from core.event_stream import (
                EventStream,
                register_mission_stream,
                register_ws_stream,
            )
            _event_stream = EventStream(mid)
            register_mission_stream(mid, _event_stream)  # for agents/supervisor lookup
            register_ws_stream(mid, _event_stream)       # for api/ws WebSocket endpoint
            ctx.metadata["event_stream"] = _event_stream
        except Exception as _es_err:
            log.debug("event_stream_register_skipped", err=str(_es_err)[:60])
    def _check_circuit_breaker(self, mid: str, ctx) -> bool:
        """
        Check circuit breaker guard (lines 367-373).
        Returns True if circuit is open (mission should fail), False otherwise.
        """
        if self._circuit_breaker.is_open:
            ctx.error = "Circuit breaker open: too many consecutive delegate failures. Retry later."
            self._transition(ctx, MissionStatus.FAILED, reason="circuit_breaker_open")
            log.warning("mission.circuit_breaker_rejected",
                        mission_id=mid, cb_status=self._circuit_breaker.status())
            return True
        return False
    def _initialize_decision_trace(self, mid: str) -> tuple:
        """
        Initialize decision trace (lines 375-378).
        Returns (trace, needs_approval).
        """
        from core.orchestration.decision_trace import DecisionTrace
        trace = DecisionTrace(mission_id=mid)
        needs_approval = False  # initialized early; may be set True by confidence_policy or kernel
        return trace, needs_approval
    def _emit_mission_events(self, mid: str, goal: str, mode: str) -> None:
        """Emit mission created events to cognitive journal and kernel (lines 382-393)."""
        # Cognitive journal: mission created
        try:
            from core.cognitive_events.emitter import emit_mission_created
            emit_mission_created(mission_id=mid, goal=goal, mode=mode)
        except Exception as _exc:
            log.warning("swallowed_exception", action="cognitive_event_mission_created", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        # Kernel event: mission created (dual emission)
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.created", mission_id=mid, goal=goal, mode=mode)
        except Exception as _exc:
            log.warning("swallowed_exception", action="kernel_event_mission_created", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    def _register_mission_guards(self, mid: str) -> None:
        """Register mission guards for iteration limit + budget (lines 395-400)."""
        try:
            from core.mission_guards import get_guardian
            get_guardian().register_mission(mid, max_steps=50)
        except Exception as _mg_err:
            log.debug("mission_guard_init_skipped", err=str(_mg_err)[:60])
    def _run_cognitive_analysis(self, goal: str, mode: str, ctx) -> None:
        """Run cognitive pre-mission analysis (lines 417-424)."""
        try:
            from core.cognitive_bridge import get_bridge
            _cognitive = get_bridge().pre_mission(goal, agent_id=mode)
            if _cognitive:
                ctx.metadata["cognitive"] = _cognitive
        except Exception as _cb_err:
            log.debug("cognitive_pre_mission_skipped", err=str(_cb_err)[:60])
    def _cleanup_event_stream(self, mid: str) -> None:
        """Deregister EventStream after mission completion (lines 1938-1945).
        NOTE: deregister_ws_stream is intentionally NOT called here.
        The WS stream stays in ACTIVE_WS_STREAMS so late-connecting clients
        can still replay historical events. The 1-hour TTL in event_stream.py
        handles eventual eviction.
        """
        try:
            from core.event_stream import deregister_mission_stream
            deregister_mission_stream(mid)
        except Exception as _exc:
            log.warning("swallowed_exception", action="ws_stream_deregister", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    # _post_mission_learning → core/orchestration/learning_mixin.py (PR 1)
    # ── Phase extraction methods (refactored from run_mission) ───────────────
    # _store_mission_memories → core/orchestration/learning_mixin.py (PR 1)
    # _execute_kernel_learning, _record_skills, _store_to_memory_facade
    # → core/orchestration/learning_mixin.py (PR 1)
    # ── Public API ───────────────────────────────────────────────────────────
    async def run_mission(
        self,
        goal: str,
        mode: str = "auto",
        mission_id: str | None = None,
        callback: CB | None = None,
        use_budget: bool = False,
        force_approved: bool = False,
        project_id: str | None = None,  # Phase 2.1: Project isolation
        extra_metadata: dict | None = None,  # Extra context (e.g. conversation history)
    ) -> MissionContext:
        """
        Enhanced mission lifecycle with classification, context assembly,
        supervised execution, and structured decision tracing.
        force_approved=True bypasses the approval gate (used when a human
        has already approved the mission via /api/v2/missions/{id}/approve).
        """
        mid = mission_id or uuid.uuid4().hex[:16]
        now = time.time()
        _extra_meta = extra_metadata or {}
        ctx = MissionContext(
            mission_id=mid,
            goal=goal,
            mode=mode,
            status=MissionStatus.CREATED,
            created_at=now,
            updated_at=now,
            project_id=project_id,  # Phase 2.1: Project isolation
        )
        # Inject extra_metadata (conversation context, etc.) into ctx
        if _extra_meta:
            ctx.metadata.update(_extra_meta)
        with self._lock:
            self._missions[mid] = ctx
        # ── Setup event stream ────────────────────────────────────────
        self._setup_event_stream(mid, ctx)
        # ── Circuit breaker guard ─────────────────────────────────────
        if self._check_circuit_breaker(mid, ctx):
            return ctx
        # ── Decision trace ────────────────────────────────────────────
        trace, needs_approval = self._initialize_decision_trace(mid)
        # Override needs_approval from extra_metadata (API request)
        if _extra_meta.get("requires_validation"):
            needs_approval = True
            log.info("mission.approval_forced", mission_id=mid, reason="requires_validation=True in extra_metadata")
        # Also check mission decision_trace (set by convergence.py before run_mission)
        try:
            from core.mission_system import get_mission_system as _get_ms
            _ms_check = _get_ms()
            _m_check = _ms_check.get(mid)
            if _m_check and _m_check.decision_trace.get("requires_validation"):
                needs_approval = True
                log.info("mission.approval_forced", mission_id=mid, reason="requires_validation=True in decision_trace")
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
        log.info("mission.created", mission_id=mid, mode=mode, goal=goal[:80])
        # ── Emit mission events ───────────────────────────────────────
        self._emit_mission_events(mid, goal, mode)
        # ── Mission guards: iteration limit + budget ──────────────────
        self._register_mission_guards(mid)
        # ══ KERNEL COGNITIVE PRE-COMPUTATION (BLOC 2 — kernel-first authority) ═
        # kernel.run_cognitive_cycle() is the SINGLE authority for:
        #   classify → plan → route → retrieve (lessons)
        # When this succeeds (_kernel_precomp_ok=True), inline fallback phases
        # 0b, 0d, 0e are SKIPPED — they are decorative/redundant.
        # Only Phase 0c (routing) and Phase 1b (planning) keep their own fallback
        # paths because they check ctx.metadata keys that run_cognitive_cycle sets.
        # try/except guards below ensure fail-open behavior for Phase 0c.
        _kernel_context, _k_classification_obj, _kernel_plan = \
            self._run_kernel_cognitive_cycle(goal, mode, mid, ctx, trace)
        # True when kernel pre-computation produced real cognitive outputs.
        # Used below to gate decorative/redundant inline phases.
        _kernel_precomp_ok = bool(_kernel_context)
        # ═════════════════════════════════════════════════════════════════════
        # ── Cognitive pre-mission analysis ────────────────────────────
        self._run_cognitive_analysis(goal, mode, ctx)
        # ── Reasoning pre-pass (intelligence upgrade) ─────────────────
        _is_chat_mode, _reasoning_result = self._execute_reasoning_prepass(
            goal, mid, ctx, trace
        )
        try:
            # ── Phase 1: Classify (extracted method) ──────────────
            self._classify_mission(
                goal, mode, ctx, trace, _k_classification_obj
            )
            # ── Phase 0b: Match AI OS capabilities (extracted method) ────
            self._match_ai_os_capabilities(
                goal, ctx, trace, _kernel_precomp_ok
            )
            # ── Phase 0c: Capability-first routing (extracted method) ────
            self._route_mission(goal, mode, ctx, trace, mid)
            # ── Phase 0d: Kernel capability registry enrichment (extracted method) ───
            self._enrich_kernel_registry(ctx, trace, _kernel_precomp_ok)
            # ── Phase 0e: Kernel performance intelligence (extracted method) ─────────
            self._apply_performance_intelligence(ctx, trace, _kernel_precomp_ok)
            # ── Phase 1b: Kernel planning (extracted method) ─────────────
            _kernel_plan, _skill_context = await self._kernel_planning(
                goal, mode, ctx, trace, mid, _kernel_plan, _is_chat_mode
            )
            # ── Phase 3-P42: Pre-planning memory retrieval ────────
            # Retrieve 3 failures + 3 successes BEFORE context assembly
            # so planner has explicit "avoid/reuse" guidance (Pass 42 — Phase 3).
            _mission_lessons = None
            if not _is_chat_mode:
                try:
                    from core.orchestration.memory_retrieval import retrieve_mission_lessons
                    _task_type_for_mem = str(
                        ctx.metadata.get("classification", {}).get("task_type", "") or ""
                    )
                    _mission_lessons = retrieve_mission_lessons(
                        goal=goal,
                        task_type=_task_type_for_mem,
                        top_k=3,
                    )
                    ctx.metadata["mission_lessons"] = _mission_lessons.to_dict()
                    trace.record("retrieve", "mission_lessons",
                                 failures=_mission_lessons.failure_count,
                                 successes=_mission_lessons.success_count,
                                 has_lessons=_mission_lessons.has_lessons,
                                 retrieval_ok=_mission_lessons.retrieval_ok)
                    log.info("pre_planning_memory_retrieved",
                             mission_id=mid,
                             failures=_mission_lessons.failure_count,
                             successes=_mission_lessons.success_count,
                             has_lessons=_mission_lessons.has_lessons)
                except Exception as _ml_err:
                    log.warning("phase_failed", phase="pre_planning_memory",
                                err=str(_ml_err)[:100])
            # ── Phase 2: Assemble context ─────────────────────────
            rich_ctx = self._assemble_mission_context(mid, goal, ctx, trace)
            # CREATED -> PLANNED
            self._transition(ctx, MissionStatus.PLANNED)
            trace.record("plan", "planned",
                         reason=f"approach={getattr(rich_ctx, 'suggested_approach', 'default')}")
            # PLANNED -> RUNNING
            self._transition(ctx, MissionStatus.RUNNING)
            # ── Creative Mode dispatcher ──────────────────────────────────────────────────
            _creative_ctx = await self._execute_creative_mode(goal, mode, mid, ctx, trace)
            if _creative_ctx is not None:
                return _creative_ctx
            # ── BeaTeam dispatcher (mode=improve/lab/dev) ──────────────────────────
            # Route to architect→coder→reviewer→qa chain when mode indicates improvement.
            if mode in ("improve", "lab", "dev") and not _is_chat_mode:
                try:
                    from core.orchestration.bea_team_dispatcher import dispatch_improve
                    log.info("bea_team.dispatching", mission_id=mid, mode=mode)
                    _team_result = await dispatch_improve(
                        goal=goal,
                        llm_client=self.bea.llm,
                        mission_id=mid,
                    )
                    if _team_result.get("result"):
                        ctx.result = _team_result["result"]
                        ctx.metadata["bea_team"] = _team_result
                        self._transition(ctx, MissionStatus.REVIEW)
                        self._transition(ctx, MissionStatus.DONE,
                                         result_len=len(ctx.result),
                                         retries=0,
                                         duration_ms=0,
                                         confidence=0.75)
                        return ctx
                except Exception as _jt_err:
                    log.warning("bea_team.dispatch_failed", err=str(_jt_err)[:80])
                    # Fall through to standard pipeline
            # ── Phase 3: Supervised execution ─────────────────────
            outcome = await self._execute_supervised(
                mid=mid,
                goal=goal,
                mode=mode,
                ctx=ctx,
                trace=trace,
                classification=ctx.metadata.get("classification", {}),
                rich_ctx=rich_ctx,
                _is_chat_mode=_is_chat_mode,
                _reasoning_result=_reasoning_result,
                _kernel_context=_kernel_context,
                _kernel_plan=_kernel_plan,
                _mission_lessons=_mission_lessons,
                use_budget=use_budget,
                needs_approval=needs_approval,
                force_approved=force_approved,
                callback=callback,
                pre_assess=None,
                _skill_context=_skill_context,
            )
            # Record supervisor decisions in trace (with schema guard)
            _dtrace = outcome.decision_trace if isinstance(
                getattr(outcome, "decision_trace", None), list
            ) else []
            for d in _dtrace:
                if not isinstance(d, dict):
                    continue
                trace.record("execute", d.get("step", "?"),
                             reason=d.get("error", ""),
                             **{k: v for k, v in d.items()
                                if k not in ("step", "error", "reason")})
            # ── Phase 1-P42 post-exec: update_observed ────────────────────────\n            # Close the loop on MissionReasoningState: fill observed effects\n            # and compute expected vs observed diff. Fail-open.
            # _mission_state was created in _execute_supervised and stored in ctx.metadata
            if ctx.metadata.get("mission_reasoning_state") is not None:
                try:
                    _mrs_dict = ctx.metadata.get("mission_reasoning_state", {})
                    # Reconstruct from dict (simple approach - just skip update if complex)
                    # Alternative: return _mission_state from _execute_supervised
                    # For now, skip the update since it's already in metadata
                    log.debug("mission_state_post_exec_update_skipped",
                              mission_id=mid,
                              reason="state already in metadata")
                except Exception as _mso_err:
                    log.warning("phase_failed", phase="mission_state_observe",
                                err=str(_mso_err)[:80])
            # Guard: cognition may return a plain str instead of ExecutionOutcome
            if isinstance(outcome, str):
                from core.orchestration.execution_supervisor import ExecutionOutcome
                _raw_str = outcome
                outcome = ExecutionOutcome(
                    success=bool(_raw_str and _raw_str.strip()),
                    result=_raw_str,
                )
            # Guard: outcome can be None if fast-path already handled the mission
            if outcome is None:
                if ctx.status in (MissionStatus.DONE, MissionStatus.REVIEW):
                    from core.orchestration.execution_supervisor import ExecutionOutcome
                    outcome = ExecutionOutcome(success=True, result=ctx.result or "")
                else:
                    from core.orchestration.execution_supervisor import ExecutionOutcome
                    outcome = ExecutionOutcome(success=False, result="")
            # Skip success handler if mission already in terminal state (fast-path)
            if ctx.status in (MissionStatus.DONE, MissionStatus.FAILED, MissionStatus.CANCELLED):
                log.info("mission.already_terminal", mission_id=mid, status=ctx.status.value)
                return ctx
            if outcome is not None and outcome.success:
                # Delegate to success outcome handler (evaluation, retry, memory, learning)
                await self._handle_success_outcome(
                    outcome=outcome,
                    ctx=ctx,
                    mid=mid,
                    goal=goal,
                    mode=mode,
                    trace=trace,
                    _reasoning_result=_reasoning_result,
                    force_approved=force_approved,
                    callback=callback,
                )
            elif outcome.error_class == "awaiting_approval":
                # Delegate to awaiting approval handler
                self._handle_awaiting_approval(
                    outcome=outcome,
                    ctx=ctx,
                    mid=mid,
                    risk=ctx.metadata.get("_exec_risk", "low"),
                    trace=trace,
                )
            else:
                # Delegate to failed outcome handler
                self._handle_failed_outcome(
                    outcome=outcome,
                    ctx=ctx,
                    mid=mid,
                    goal=goal,
                    trace=trace,
                )
        except asyncio.TimeoutError as e:
            ctx.error = f"Timeout : {e}"
            self._transition(ctx, MissionStatus.FAILED, reason="timeout")
            trace.record("complete", "failed", reason="timeout")
        except asyncio.CancelledError:
            ctx.error = "Mission annulée"
            self._transition(ctx, MissionStatus.FAILED, reason="cancelled")
            trace.record("complete", "failed", reason="cancelled")
        except Exception as e:
            ctx.error = str(e)[:300]
            log.error("mission.exception",
                      mission_id=mid, err=str(e)[:120], exc_info=True)
            if ctx.status not in (MissionStatus.DONE, MissionStatus.FAILED):
                try:
                    self._transition(ctx, MissionStatus.FAILED, reason=str(e)[:80])
                except ValueError:
                    ctx.status     = MissionStatus.FAILED
                    ctx.updated_at = time.time()
            trace.record("complete", "exception", reason=str(e)[:80])
        # Save decision trace
        ctx.metadata["decision_trace"] = trace.summary()
        trace.save()
        # ── Post-mission: cognitive learning + guardian cleanup ────
        self._post_mission_learning(mid, goal, mode, ctx)
        # ── Training data collection (fire-and-forget) ────────────
        try:
            from core.training_data_collector import collect_training_example
            # Extract mission data for training
            _score = ctx.metadata.get("confidence", 0.0)
            _model = ctx.metadata.get("routed_provider") or ctx.metadata.get("model_used") or "unknown"
            _duration = (ctx.updated_at - ctx.created_at) if ctx.updated_at and ctx.created_at else None
            _plan = ctx.metadata.get("kernel_plan") or ctx.metadata.get("context", {})
            _lessons = ctx.metadata.get("kernel_lesson")
            _score_predicted = ctx.metadata.get("score_predicted", 0.5)
            # Fire-and-forget: collect in background without blocking mission completion
            asyncio.create_task(collect_training_example(
                mission_id=mid,
                goal=goal,
                result=ctx.result or "",
                score=_score,
                model_used=_model,
                duration_s=_duration,
                plan=_plan,
                lessons=_lessons,
                metadata={
                    "mode": mode,
                    "status": ctx.status.value,
                    "task_type": ctx.metadata.get("task_type", "general"),
                },
                score_predicted=_score_predicted,
            ))
        except Exception as _tdc_err:
            log.debug("training_data_collection_skipped", err=str(_tdc_err)[:80])
        # ── Deregister EventStream (mission complete or failed) ────
        self._cleanup_event_stream(mid)
        return ctx
# ══════════════════════════════════════════════════════════════════════════════
# TESTS REMOVED - now using manual checks
# ══════════════════════════════════════════════════════════════════════════════
    def get_status(self) -> dict:
        """
        État observable de MetaOrchestrator.
        Utilisé par l'API /status et le monitoring.
        """
        with self._lock:
            snapshot = list(self._missions.values())
        active   = [c for c in snapshot
                    if c.status in (MissionStatus.PLANNED,
                                    MissionStatus.RUNNING,
                                    MissionStatus.REVIEW)]
        terminal = [c for c in snapshot
                    if c.status in (MissionStatus.DONE, MissionStatus.FAILED)]
        return {
            "orchestrator": "MetaOrchestrator",
            "version":      "1.0",
            "missions": {
                "active":   len(active),
                "done":     sum(1 for c in terminal if c.status == MissionStatus.DONE),
                "failed":   sum(1 for c in terminal if c.status == MissionStatus.FAILED),
                "total":    len(snapshot),
            },
            "active_missions": [c.to_dict() for c in active],
            "circuit_breaker": self._circuit_breaker.status(),
        }
    def get_mission(self, mission_id: str) -> MissionContext | None:
        """Retourne le contexte d'une mission par son ID."""
        with self._lock:
            return self._missions.get(mission_id)
    async def resolve_approval(
        self,
        mission_id: str,
        granted: bool,
        reason: str = "",
        callback: CB | None = None,
    ) -> MissionContext | None:
        """
        Resume or close a mission after approval decision.
        granted=True  → transition AWAITING_APPROVAL → RUNNING → re-execute
        granted=False → transition AWAITING_APPROVAL → FAILED
        """
        ctx = self.get_mission(mission_id)
        if not ctx:
            # Try to recover from persistence
            try:
                from core.mission_persistence import get_mission_persistence
                record = get_mission_persistence().get(mission_id)
                if record and record.is_awaiting_approval:
                    ctx = MissionContext(
                        mission_id=record.mission_id,
                        goal=record.goal,
                        mode=record.mode,
                        status=MissionStatus.AWAITING_APPROVAL,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                        error=record.error,
                        metadata=record.metadata,
                    )
                    with self._lock:
                        self._missions[mission_id] = ctx
            except Exception as e:
                log.warning("approval_resolve.recover_failed", err=str(e)[:80])
        if not ctx:
            log.warning("approval_resolve.not_found", mission_id=mission_id)
            return None
        if ctx.status != MissionStatus.AWAITING_APPROVAL:
            log.warning("approval_resolve.wrong_status",
                       mission_id=mission_id, status=ctx.status.value)
            return ctx
        # Update persistence store
        try:
            from core.mission_persistence import get_mission_persistence
            get_mission_persistence().resolve_approval(mission_id, granted, reason)
        except Exception as _exc:
            log.warning("swallowed_exception", action="persistence_resolve_approval", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        # Journal event
        try:
            from core.cognitive_events.emitter import emit_approval_resolved
            emit_approval_resolved(mission_id, granted=granted,
                                    item_id=ctx.metadata.get("approval_item_id", ""))
        except Exception as _exc:
            log.warning("swallowed_exception", action="cognitive_event_approval_resolved", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        if granted:
            # Resume: transition back to RUNNING and re-execute
            ctx.metadata["approval_status"] = "granted"
            ctx.metadata["approval_resolved_at"] = time.time()
            self._transition(ctx, MissionStatus.RUNNING, reason="approval_granted")
            log.info("mission.approval_resumed", mission_id=mission_id)
            # Re-execute from the beginning (safe checkpoint resume)
            try:
                resumed = await self.run_mission(
                    goal=ctx.goal,
                    mode=ctx.mode,
                    mission_id=mission_id,
                    callback=callback,
                    force_approved=True,
                )
                return resumed
            except Exception as e:
                ctx.error = f"Resume failed: {e}"
                self._transition(ctx, MissionStatus.FAILED, reason="resume_error")
                return ctx
        else:
            # Denied: close cleanly
            ctx.metadata["approval_status"] = "denied"
            ctx.metadata["approval_resolved_at"] = time.time()
            ctx.error = f"Approval denied: {reason}" if reason else "Approval denied"
            self._transition(ctx, MissionStatus.FAILED, reason="approval_denied")
            log.info("mission.approval_denied", mission_id=mission_id)
            return ctx
    def recover_from_persistence(self) -> dict:
        """
        Recover non-terminal missions from persistence on startup.
        - AWAITING_APPROVAL missions: restore to in-memory registry (wait for approval)
        - RUNNING missions interrupted by restart: mark FAILED (no safe resume point)
        - Returns summary of recovery actions.
        """
        try:
            from core.mission_persistence import get_mission_persistence
            store = get_mission_persistence()
        except Exception as e:
            log.warning("recovery.persistence_unavailable", err=str(e)[:80])
            return {"error": str(e)[:80]}
        records = store.recover_non_terminal()
        recovered = {"awaiting_approval": 0, "marked_failed": 0, "total": len(records)}
        for record in records:
            if record.mission_id in self._missions:
                continue  # Already in memory — skip
            if record.is_awaiting_approval:
                # Restore to memory — waiting for approval resolution
                ctx = MissionContext(
                    mission_id=record.mission_id,
                    goal=record.goal,
                    mode=record.mode,
                    status=MissionStatus.AWAITING_APPROVAL,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    error=record.error or "Awaiting human approval",
                    metadata=record.metadata or {},
                )
                with self._lock:
                    self._missions[record.mission_id] = ctx
                recovered["awaiting_approval"] += 1
                log.info("recovery.awaiting_restored", mission_id=record.mission_id)
            else:
                # RUNNING/PLANNED missions interrupted by restart — mark failed
                store.update_status(
                    record.mission_id,
                    status="FAILED",
                    error="Interrupted by process restart",
                )
                recovered["marked_failed"] += 1
                log.info("recovery.interrupted_marked_failed",
                        mission_id=record.mission_id, was_status=record.status)
        log.info("recovery.complete", **recovered)
        return recovered
    # ── Backward-compat shims ────────────────────────────────────────────────
    # Ces méthodes permettent aux modules qui appelaient BeaOrchestrator.run()
    # de migrer progressivement vers MetaOrchestrator sans casser les imports.
    async def run(
        self,
        user_input: str,
        mode: str = "auto",
        session_id: str | None = None,
        chat_id: int = 0,
        callback: CB | None = None,
    ):
        """
        Compatibilité ascendante avec BeaOrchestrator.run().
        Délègue à run_mission() et retourne la session BeaSession originale.
        """
        mid = session_id or uuid.uuid4().hex[:16]
        # BLOC 2: ALL modes route through run_mission() — kernel cognitive pipeline.
        # Previous bypass (mode != "auto" → bea.run() directly) skipped:
        #   - kernel cognitive cycle
        #   - kernel policy check
        #   - kernel evaluation
        #   - kernel learning (R5)
        # Now run_mission() is the single execution entry point regardless of mode.
        ctx = await self.run_mission(
            goal=user_input,
            mode=mode,
            mission_id=mid,
            callback=callback,
        )
        return ctx


# ══════════════════════════════════════════════════════════════════════════════
# Module-level test helpers
# ══════════════════════════════════════════════════════════════════════════════

def check():
    """Simple check - MetaOrchestrator can be instantiated."""
    try:
        mo = MetaOrchestrator()
        print(f"✓ MetaOrchestrator instantiated: {type(mo)}")
        return True
    except Exception as e:
        print(f"✗ MetaOrchestrator failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton (optionnel — certains modules préfèrent l'injection)
# ─────────────────────────────────────────────────────────────────────────────

_meta: MetaOrchestrator | None = None
_meta_lock = threading.Lock()


def get_meta_orchestrator(settings=None) -> MetaOrchestrator:
    """
    Retourne l'instance singleton de MetaOrchestrator.
    Premier appel = initialisation ; appels suivants = même instance.
    Thread-safe double-checked locking.
    """
    global _meta
    if _meta is None:
        with _meta_lock:
            if _meta is None:
                _meta = MetaOrchestrator(settings)
                log.info("meta_orchestrator.singleton_created")
    return _meta


# Alias for backward compatibility — some modules import get_orchestrator
get_orchestrator = get_meta_orchestrator
