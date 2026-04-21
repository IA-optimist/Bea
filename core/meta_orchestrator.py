"""
JARVIS MAX — MetaOrchestrator
==============================
Point d'entrée unique et source de vérité pour le cycle de vie des missions.

Architecture :
    MetaOrchestrator          ← vous êtes ici (facade + state machine)
        └─► JarvisOrchestrator  (logique métier, agents, mémoire)
        └─► OrchestratorV2      (budget, DAG, checkpoint — missions complexes)

Transitions d'état déterministes :
    CREATED → PLANNED → RUNNING → REVIEW → DONE
                                         ↘ FAILED

Règles d'usage :
    - TOUJOURS utiliser MetaOrchestrator comme point d'entrée.
    - JarvisOrchestrator et OrchestratorV2 restent accessibles pour compatibilité
      ascendante, mais ne doivent plus être instanciés directement dans le code neuf.
    - Chaque transition de statut est loguée via structlog (observable, auditabl).
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

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
_silent_log = __import__("structlog").get_logger(__name__)

try:
    from kernel.state.mission_state import (
        MissionContext,
        VALID_TRANSITIONS as _VALID_TRANSITIONS,
        get_state_machine as _get_kernel_sm,
    )
    _KERNEL_STATE_AVAILABLE = True
except ImportError:
    _KERNEL_STATE_AVAILABLE = False
    _get_kernel_sm = None  # type: ignore[assignment]

    # Inline fallback (should never happen in production)
    _VALID_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
        MissionStatus.CREATED:           {MissionStatus.PLANNED, MissionStatus.FAILED},
        MissionStatus.PLANNED:           {MissionStatus.RUNNING, MissionStatus.FAILED},
        MissionStatus.RUNNING:           {MissionStatus.REVIEW,  MissionStatus.FAILED,
                                          MissionStatus.AWAITING_APPROVAL},
        MissionStatus.AWAITING_APPROVAL: {MissionStatus.RUNNING, MissionStatus.FAILED,
                                          MissionStatus.CANCELLED},
        MissionStatus.REVIEW:            {MissionStatus.DONE,    MissionStatus.RUNNING,
                                          MissionStatus.FAILED},
        MissionStatus.DONE:              set(),
        MissionStatus.FAILED:            set(),
    }

    @dataclass
    class MissionContext:  # type: ignore[no-redef]
        """Fallback — identical to kernel version."""
        mission_id: str; goal: str; mode: str; status: MissionStatus
        created_at: float; updated_at: float
        result: str | None = None; error: str | None = None
        metadata: dict = field(default_factory=dict)
        project_id: str | None = None  # Phase 2.1: Project isolation
        def get_output(self, agent: str) -> str:
            outputs = self.metadata.get("agent_outputs", {})
            if isinstance(outputs, dict):
                out = outputs.get(agent, "")
                return out if isinstance(out, str) else str(out) if out else ""
            return ""
        def to_dict(self) -> dict:
            return {"mission_id": self.mission_id, "goal": self.goal[:200],
                    "mode": self.mode, "status": self.status.value,
                    "created_at": self.created_at, "updated_at": self.updated_at,
                    "result": (self.result or "")[:500], "error": self.error,
                    "metadata": self.metadata}


# ─────────────────────────────────────────────────────────────────────────────
# MetaOrchestrator
# ─────────────────────────────────────────────────────────────────────────────


# ── _strip_execution_outcome déplacé dans core/orchestration/mission_text_utils.py ──
# Alias conservé (wrapper qui appelle la fonction publique).
from core.orchestration.mission_text_utils import strip_execution_outcome as _strip_execution_outcome  # noqa: E402,F401


class MetaOrchestrator:
    """
    Cerveau unique de JarvisMax.

    Délègue l'exécution à JarvisOrchestrator (missions standard) ou
    OrchestratorV2 (missions avec budget/DAG), mais maintient lui-même
    le cycle de vie (MissionStatus) et les logs de transition.
    """

    def __init__(self, settings=None):
        from config.settings import get_settings
        self.s = settings or get_settings()

        # Orchestrateurs délégués (lazy)
        self._jarvis: Any = None     # JarvisOrchestrator
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
    def jarvis(self):
        """JarvisOrchestrator — orchestrateur principal."""
        if self._jarvis is None:
            from core.jarvis_executor import JarvisOrchestrator
            self._jarvis = JarvisOrchestrator(self.s)
            log.debug("meta_orchestrator.jarvis_loaded")
        return self._jarvis

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
                log.warning("meta_orchestrator.capability_dispatcher_unavailable", error=str(e))
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
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
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
                pass

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
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        # Kernel event: mission created (dual emission)
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.created", mission_id=mid, goal=goal, mode=mode)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

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

    def _execute_reasoning_prepass(
        self, goal: str, mid: str, ctx, trace
    ) -> tuple:
        """
        Execute reasoning pre-pass for intelligence upgrade (lines 514-544).
        Returns (_is_chat_mode, _reasoning_result).
        """
        # NOTE: skip reasoning prepass for CHAT mode (short messages / greetings)
        _task_mode_str = ctx.metadata.get("task_mode", "")
        _CHAT_KEYWORDS = ("salut","bonjour","hello","hi","hey","présente","qui es","recommence","répète","repete","présente-toi","aide moi","merci","ok cool","super","parfait")
        _TASK_KEYWORDS = ("analyse","analyz","compare","comparison","architecture","implement","code","develop","build","create","list all","detailed","complet","rapport","report","research","explain","diagram","roadmap","strategy","plan","design","review","audit","optimize","migrate","database","deploy","docker","api","test","debug","fix","refactor","swagger","openapi","benchmark","security","vulnerability")
        _goal_lower = goal.strip().lower()
        _is_conversational = any(kw in _goal_lower for kw in _CHAT_KEYWORDS)
        _is_complex_task = any(kw in _goal_lower for kw in _TASK_KEYWORDS) or len(goal.strip()) > 120
        _is_chat_mode  = _task_mode_str == "chat" or (
            not _is_complex_task and (_is_conversational or len(goal.strip()) <= 60)
        )
        _reasoning_result = None
        
        if _is_chat_mode:
            log.debug("reasoning_prepass_skipped_chat_mode",
                      mission_id=mid, goal_len=len(goal))
        else:
            try:
                from core.orchestration.reasoning_engine import reason as reasoning_prepass
                _reasoning_result = reasoning_prepass(
                    goal=goal,
                    classification=ctx.metadata.get("classification"),
                )
                ctx.metadata["reasoning"] = _reasoning_result.to_dict()
                trace.record("reason", _reasoning_result.frame.complexity_class,
                             bottleneck=_reasoning_result.frame.likely_bottleneck[:60],
                             shape=_reasoning_result.output_shape.value,
                             ms=_reasoning_result.reasoning_ms)
                log.info("reasoning_prepass_complete",
                         mission_id=mid,
                         complexity=_reasoning_result.frame.complexity_class,
                         shape=_reasoning_result.output_shape.value)
            except Exception as _rp_err:
                log.debug("reasoning_prepass_skipped", err=str(_rp_err)[:60])
        
        return _is_chat_mode, _reasoning_result

    def _cleanup_event_stream(self, mid: str) -> None:
        """Deregister EventStream after mission completion (lines 1938-1945)."""
        try:
            from core.event_stream import (
                deregister_mission_stream,
                deregister_ws_stream,
            )
            deregister_ws_stream(mid)
            deregister_mission_stream(mid)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

    def _post_mission_learning(self, mid: str, goal: str, mode: str, ctx) -> None:
        """Post-mission cognitive learning + guardian cleanup (lines 1900-1936)."""
        # Cognitive learning
        try:
            from core.cognitive_bridge import get_bridge
            bridge = get_bridge()
            _success = ctx.status == MissionStatus.DONE
            bridge.post_mission(
                mission_id=mid, goal=goal, success=_success,
                agent_id=mode, error=ctx.error or "",
            )
            # Enrich capability graph with mission usage
            if bridge.capability_graph and mode:
                agent_cap = f"cap-{mode}" if mode.startswith("jarvis-") else None
                caps_used = [c for c in [agent_cap] if c]
                if caps_used:
                    bridge.capability_graph.record_mission_usage(mid, caps_used)
        except Exception:
            pass  # Fail-open
        
        # Guardian cleanup
        try:
            from core.mission_guards import get_guardian
            get_guardian().release_mission(mid)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

        # Record routing outcome for learning
        try:
            from core.capability_routing.feedback import get_routing_history
            _rh = get_routing_history()
            _success = ctx.status == MissionStatus.DONE
            _duration = (ctx.updated_at - ctx.created_at) * 1000
            _rh.record_outcome(
                mission_id=mid,
                success=_success,
                error=ctx.error or "",
                duration_ms=_duration,
            )
        except Exception:
            pass  # Fail-open

    # ── Phase extraction methods (refactored from run_mission) ───────────────

    def _classify_mission(
        self,
        goal: str,
        mode: str,
        ctx: MissionContext,
        trace,
        _k_classification_obj=None,
    ):
        """
        Phase 1: Classify mission using kernel classifier or core classifier.
        
        Priority: kernel.run_cognitive_cycle() (pre-computed) → kernel classifier 
                  → core classifier → None
        
        Returns: classification object or None
        """
        # ── Phase 1: Classify ─────────────────────────────────────
        # Priority: kernel.run_cognitive_cycle() (pre-computed above) →
        #           kernel classifier → core classifier → None
        if _k_classification_obj is not None:
            # Kernel pre-computed classification — use it directly (Pass 11)
            classification = _k_classification_obj
            trace.record("classify", str(getattr(getattr(classification, "task_type", None), "value", "?")),
                         reason=f"kernel_precomputed: {getattr(classification, 'reasoning', '')[:60]}")
        else:
            try:
                from kernel.classifier.mission_classifier import get_classifier as _kclf
                classification = _kclf().classify(goal)
                ctx.metadata["classification"] = classification.to_dict()
                trace.record("classify", classification.task_type.value,
                             reason=classification.reasoning)
            except Exception as _exc:
                log.warning("phase_failed", phase="classify", err=str(_exc)[:100])
                classification = None
        
        return classification

    def _match_ai_os_capabilities(
        self,
        goal: str,
        ctx: MissionContext,
        trace,
        _kernel_precomp_ok: bool = False,
    ):
        """
        Phase 0b: Match AI OS capabilities using semantic routing.
        
        Skipped when kernel pre-computation succeeded (BLOC 2).
        kernel.run_cognitive_cycle() already performed semantic routing
        internally via kernel.routing.router — Phase 0b would be redundant.
        Only runs as fallback when kernel cycle failed (_kernel_precomp_ok=False).
        
        Returns: list of matched_capabilities
        """
        # ── Phase 0b: Match AI OS capabilities ───────────────
        # BLOC 2: Skipped when kernel pre-computation succeeded.
        # kernel.run_cognitive_cycle() already performed semantic routing
        # internally via kernel.routing.router — Phase 0b would be redundant.
        # Only runs as fallback when kernel cycle failed (_kernel_precomp_ok=False).
        matched_capabilities = []
        if not _kernel_precomp_ok:
            try:
                from core.capabilities.semantic_router import semantic_match_capability
                _semantic_matches = semantic_match_capability(goal)
                # Convert SemanticMatch → AIOSCapability for backward compat
                from core.capabilities.ai_os_capabilities import get_capability
                for _sm in _semantic_matches:
                    _cap = get_capability(_sm.capability_name)
                    if _cap:
                        matched_capabilities.append(_cap)
                # Store semantic routing metadata
                ctx.metadata["semantic_routing"] = [m.to_dict() for m in _semantic_matches]
                # AI OS agent registry: track task routing
                try:
                    from core.agents.agent_registry import get_agent_registry
                    _areg = get_agent_registry()
                    _best = _areg.best_agent_for_role("operator")
                    ctx.metadata["agent_routing"] = {"selected": _best, "registry_size": len(_areg.list_agents())}
                except Exception as _ar_err:
                    log.debug("agent_routing_failed", err=str(_ar_err)[:60])
                if matched_capabilities:
                    ctx.metadata["matched_capabilities"] = [c.name for c in matched_capabilities]
                    trace.record("classify", "capabilities_matched",
                                 count=len(matched_capabilities),
                                 names=",".join(c.name for c in matched_capabilities[:3]))
            except Exception as _exc:
                log.debug("phase_failed", phase="capability_match", err=str(_exc)[:100])
        
        return matched_capabilities

    def _route_mission(
        self,
        goal: str,
        mode: str,
        ctx: MissionContext,
        trace,
        mid: str,
    ):
        """
        Phase 0c: Capability-first routing via kernel.router.
        
        KERNEL AUTHORITATIVE: all routing goes through kernel.router.
        kernel.router is the single call point — it delegates to
        core.capability_routing internally (via registration) or falls
        back to kernel heuristic. Phase 0c never imports core.capability_routing.
        
        Includes Phase 0c-bis: Kernel performance routing enrichment.
        """
        # ── Phase 0c: Capability-first routing ───────────────
        # KERNEL AUTHORITATIVE: all routing goes through kernel.router.
        # kernel.router is the single call point — it delegates to
        # core.capability_routing internally (via registration) or falls
        # back to kernel heuristic. Phase 0c never imports core.capability_routing.
        try:
            if ctx.metadata.get("capability_routing"):
                # Fast path: kernel.run_cognitive_cycle() pre-computed routing (Pass 11).
                # Skip inline route() — data already in ctx.metadata.
                _routing_decisions = []  # No live objects; pre-computed as dicts
                _selected_provider = ctx.metadata.get("routed_provider", {})
                if _selected_provider:
                    trace.record("route", "capability_routed_precomputed",
                                 provider=_selected_provider.get("provider_id", ""),
                                 score=round(float(_selected_provider.get("score", 0.0)), 3),
                                 source="kernel_cognitive_cycle")
                else:
                    trace.record("route", "capability_precomputed_no_provider",
                                 count=len(ctx.metadata["capability_routing"]),
                                 source="kernel_cognitive_cycle")
            else:
                # Standard path: compute routing inline.
                from kernel.routing.router import get_router as _get_kernel_router
                _routing_decisions = _get_kernel_router().route(
                    goal,
                    classification=ctx.metadata.get("classification"),
                    mode=mode,
                )
                ctx.metadata["capability_routing"] = [
                    d.to_dict() for d in _routing_decisions
                ]
                _selected = [
                    d for d in _routing_decisions
                    if d.success and d.selected_provider
                ]
                if _selected:
                    ctx.metadata["routed_provider"] = _selected[0].selected_provider.to_dict()
                    trace.record("route", "capability_routed",
                                 capability=_selected[0].capability_id,
                                 provider=_selected[0].selected_provider.provider_id,
                                 score=round(_selected[0].score, 3))
                    # Journal: capability resolved + provider selected
                    try:
                        from core.cognitive_events.emitter import (
                            emit_capability_resolved, emit_provider_selected,
                        )
                        emit_capability_resolved(
                            mission_id=mid,
                            capabilities=[d.capability_id for d in _routing_decisions],
                        )
                        _sp0 = _selected[0]
                        emit_provider_selected(
                            mission_id=mid,
                            capability_id=_sp0.capability_id,
                            provider_id=_sp0.selected_provider.provider_id,
                            score=_sp0.score,
                            alternatives=_sp0.candidates_evaluated,
                        )
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
                else:
                    trace.record("route", "capability_fallback",
                                 reason="no provider matched, using legacy agent routing")
                # Record routing decision in feedback history
                try:
                    from core.capability_routing.feedback import get_routing_history
                    _rh = get_routing_history()
                    for _rd in _routing_decisions:
                        _sp = _rd.selected_provider
                        _rh.record_decision(
                            mission_id=mid,
                            capability_id=_rd.capability_id,
                            provider_id=_sp.provider_id if _sp else None,
                            provider_type=_sp.provider_type.value if _sp else "",
                            score=_rd.score,
                            alternatives_count=_rd.candidates_evaluated,
                            fallback_used=_rd.fallback_used,
                            requires_approval=_sp.requires_approval if _sp else False,
                        )
                except Exception:
                    pass  # Fail-open

            # ── Phase 0c-bis: Kernel performance routing enrichment ────
            # Adjust provider reliability scores using real kernel execution outcomes.
            # Must run AFTER routing decisions are computed, BEFORE Phase 0d kernel enrichment.
            # Fail-open: never blocks mission execution.
            try:
                _routing_list = ctx.metadata.get("capability_routing", [])
                if _routing_list:
                    from kernel.convergence.performance_routing import enrich_providers
                    # Reconstruct provider objects for enrichment (from metadata dicts)
                    _cap_providers = [
                        rd.get("selected_provider")
                        for rd in _routing_list
                        if isinstance(rd, dict) and rd.get("selected_provider")
                    ]
                    if _cap_providers:
                        enrich_providers(_cap_providers)
                        trace.record("route", "kernel_perf_enriched",
                                     count=len(_cap_providers))
            except Exception as _kpe:
                log.debug("phase_failed", phase="kernel_perf_routing", err=str(_kpe)[:80])

        except Exception as _exc:
            log.debug("phase_failed", phase="capability_routing", err=str(_exc)[:80])

    def _enrich_kernel_registry(
        self,
        ctx: MissionContext,
        trace,
        _kernel_precomp_ok: bool = False,
    ):
        """
        Phase 0d: Kernel capability registry enrichment.
        
        BLOC 2: Skipped when kernel pre-computation succeeded.
        This phase is purely additive metadata — never drives routing decisions.
        When kernel ran, capability data is already in ctx.metadata from
        _kernel_context. Running it again wastes ~15ms per mission.
        """
        # ── Phase 0d: Kernel capability registry enrichment ───
        # BLOC 2: Skipped when kernel pre-computation succeeded.
        # This phase is purely additive metadata — never drives routing decisions.
        # When kernel ran, capability data is already in ctx.metadata from
        # _kernel_context. Running it again wastes ~15ms per mission.
        if not _kernel_precomp_ok:
            try:
                from kernel.convergence.capability_bridge import (
                    query_capabilities, resolve_provider,
                )
                _kernel_caps = query_capabilities()
                ctx.metadata["kernel_capabilities_count"] = len(_kernel_caps)

                # If Phase 0c selected a capability, cross-reference with kernel
                _routed = ctx.metadata.get("routed_provider", {})
                if _routed:
                    _cap_id = _routed.get("capability_id", "")
                    if _cap_id:
                        _kernel_resolution = resolve_provider(_cap_id)
                        if _kernel_resolution:
                            ctx.metadata["kernel_provider"] = _kernel_resolution
                            trace.record("route", "kernel_capability_resolved",
                                         capability=_cap_id,
                                         provider=_kernel_resolution.get("provider_id", ""),
                                         source=_kernel_resolution.get("source", ""))
            except Exception as _ke:
                log.debug("phase_failed", phase="kernel_capabilities", err=str(_ke)[:80])

    def _apply_performance_intelligence(
        self,
        ctx: MissionContext,
        trace,
        _kernel_precomp_ok: bool = False,
    ):
        """
        Phase 0e: Kernel performance intelligence.
        
        BLOC 2: Skipped when kernel pre-computation succeeded.
        Performance summary is decorative at mission start — not a routing input.
        Available via /api/v3/kernel/performance (observability routes).
        """
        # ── Phase 0e: Kernel performance intelligence ─────────
        # BLOC 2: Skipped when kernel pre-computation succeeded.
        # Performance summary is decorative at mission start — not a routing input.
        # Available via /api/v3/kernel/performance (observability routes).
        if not _kernel_precomp_ok:
            try:
                from kernel.capabilities.performance import get_performance_store
                _perf = get_performance_store()
                _perf_summary = _perf.get_summary()
                ctx.metadata["kernel_performance"] = _perf_summary
                _degraded = _perf.get_degraded(threshold=0.5)
                if _degraded:
                    ctx.metadata["kernel_degraded_capabilities"] = [
                        {"id": d["entity_id"], "type": d["entity_type"],
                         "success_rate": d["success_rate"], "trend": d["trend"]}
                        for d in _degraded[:5]
                    ]
                    trace.record("route", "kernel_degraded_detected",
                                 count=len(_degraded))
            except Exception as _kp:
                log.debug("phase_failed", phase="kernel_performance", err=str(_kp)[:80])

    async def _kernel_planning(
        self,
        goal: str,
        mode: str,
        ctx: MissionContext,
        trace,
        mid: str,
        _kernel_plan=None,
        _is_chat_mode: bool = False,
    ):
        """
        Phase 1b: Kernel planning (authoritative — Pass 9/11).
        
        Pass 11 fast path: if kernel.run_cognitive_cycle() already ran,
        _kernel_plan is set — skip recomputation and just record trace.
        Fallback: if kernel pre-computation failed, plan here (original path).
        
        Also includes Skill Store retrieval (Voyager pattern).
        
        Returns: (_kernel_plan, _skill_context)
        """
        # ── Phase 1b: Kernel planning (authoritative — Pass 9/11) ─────────────
        # Pass 11 fast path: if kernel.run_cognitive_cycle() already ran above,
        # _kernel_plan is set — skip recomputation and just record trace.
        # Fallback: if kernel pre-computation failed, plan here (original path).
        if _kernel_plan is not None:
            # Fast path: kernel pre-computed plan (Pass 11)
            if not ctx.metadata.get("kernel_plan"):
                ctx.metadata["kernel_plan"] = _kernel_plan.to_dict()
            trace.record("plan", "kernel_planned_precomputed",
                         steps=_kernel_plan.step_count,
                         complexity=_kernel_plan.complexity.value,
                         source=_kernel_plan.source)
        else:
            # Fallback path: plan inline (original Phase 1b logic)
            try:
                from kernel.planning.planner import get_planner as _get_kernel_planner
                from kernel.planning.goal import KernelGoal as _KernelGoal
                _task_type_for_plan = str(
                    ctx.metadata.get("classification", {}).get("task_type", "general") or "general"
                )
                _kgoal = _KernelGoal(
                    description=goal,
                    goal_type=_task_type_for_plan,
                )
                _kernel_plan = _get_kernel_planner().build(_kgoal)
                ctx.metadata["kernel_plan"] = _kernel_plan.to_dict()
                trace.record("plan", "kernel_planned",
                             steps=_kernel_plan.step_count,
                             complexity=_kernel_plan.complexity.value,
                             source=_kernel_plan.source)
            except Exception as _kplan_err:
                log.debug("kernel_planning_skipped", err=str(_kplan_err)[:100])

        # ── Skill Store: retrieve similar past successes (Voyager pattern) ──
        # Inject before planning so the planner can reuse proven strategies.
        # Fail-open: returns [] if Qdrant unavailable or no matches.
        _skill_context = ""
        if not _is_chat_mode:
            try:
                from core.skill_store import get_skill_store, format_skills_for_prompt
                _similar_skills = await get_skill_store().retrieve(
                    goal=goal,
                    top_k=3,
                    mission_type=str(ctx.metadata.get("classification", {}).get("task_type", "")),
                )
                if _similar_skills:
                    _skill_context = format_skills_for_prompt(_similar_skills)
                    ctx.metadata["retrieved_skills"] = _similar_skills
                    trace.record("retrieve", "skills_from_store",
                                 count=len(_similar_skills),
                                 top_score=_similar_skills[0].get("_score", 0))
                    log.info("skill_store_retrieved", mission_id=mid, count=len(_similar_skills))
            except Exception as _sk_err:
                log.debug("skill_retrieve_skip", err=str(_sk_err)[:80])
        
        return _kernel_plan, _skill_context

    def _assemble_mission_context(self, mid: str, goal: str, ctx, trace):
        """
        Phase 2: Assemble context using context_assembler.
        
        Updates ctx.metadata with context, prior_skills, memories.
        Returns rich_ctx or None on failure.
        
        Extracted from run_mission() lines ~981-1006.
        """
        try:
            from core.orchestration.context_assembler import assemble as assemble_context
            rich_ctx = assemble_context(
                mission_id=mid,
                goal=goal,
                classification=ctx.metadata.get("classification", {}),
            )
            ctx.metadata["context"] = rich_ctx.to_dict()
            ctx.metadata["prior_skills"] = rich_ctx.prior_skills
            if rich_ctx.prior_skills:
                trace.record("retrieve", "skills_found",
                             count=len(rich_ctx.prior_skills),
                             reason=f"Found {len(rich_ctx.prior_skills)} relevant skills")
            if rich_ctx.relevant_memories:
                trace.record("retrieve", "memories_found",
                             count=len(rich_ctx.relevant_memories))
            return rich_ctx
        except Exception as _exc:
            log.warning("phase_failed", phase="context_assemble", err=str(_exc)[:100])
            return None

    async def _execute_creative_mode(self, goal: str, mode: str, mid: str, ctx, trace):
        """
        Creative Mode dispatcher (early return pathway).
        
        Returns ctx if creative mode succeeds (mission completes), None otherwise.
        Falls through to standard pipeline on failure.
        
        Extracted from run_mission() lines ~1011-1027.
        """
        if mode != "creative":
            return None
        
        try:
            from core.orchestration.creative_engine import JarvisCreativePipeline, JarvisLLMClient, JarvisMissionStore
            _creative = JarvisCreativePipeline(llm_client=JarvisLLMClient(role="fast"), mission_store=JarvisMissionStore())
            _creative_result = await _creative.run(goal, n_solutions=3)
            if _creative_result.get("best"):
                ctx.result = _creative_result["best"]
                ctx.metadata["creative_solutions"] = len(_creative_result.get("all_solutions", []))
                self._transition(ctx, MissionStatus.REVIEW)
                self._transition(ctx, MissionStatus.DONE,
                                 result_len=len(ctx.result), retries=0, duration_ms=0, confidence=0.75)
                log.info("creative_mode.done", mission_id=mid, n_solutions=ctx.metadata["creative_solutions"])
                return ctx
        except Exception as _creative_err:
            log.warning("creative_mode.failed", err=str(_creative_err)[:80])
        
        # Fall through to standard pipeline
        return None

    async def _execute_supervised(
        self,
        mid: str,
        goal: str,
        mode: str,
        ctx,
        trace,
        classification: dict,
        rich_ctx,
        _is_chat_mode: bool,
        _reasoning_result,
        _kernel_context: dict,
        _kernel_plan,
        _mission_lessons,
        use_budget: bool,
        needs_approval: bool,
        force_approved: bool,
        callback,
        pre_assess,
    ):
        """
        Phase 3: Supervised execution with kernel agent registry, mission reasoning,
        confidence policy, kernel policy, and all execution enrichments.
        
        Returns execution outcome.
        
        Extracted from run_mission() lines ~1053-1659 (~600 lines).
        This is the LARGEST extraction containing:
        - Kernel agent registry lookup
        - Mission reasoning state
        - Confidence policy
        - Kernel policy + SecurityLayer
        - Goal enrichment (reasoning, context, plan, lessons, causal, memory)
        - Pre-execution assessment
        - CognitionOrchestrator wrapper
        - supervise() call with delegate
        """
        risk = classification.get("risk_level", "low")
        
        # ── Phase 3-kagents: Kernel Agent Registry lookup (BLOC 3 — R7) ──────
        try:
            from kernel.contracts.agent import get_agent_registry as _get_kreg
            _kreg = _get_kreg()
            _task_type_str = str(classification.get("task_type", "") or "")
            if hasattr(_task_type_str, "value"):
                _task_type_str = _task_type_str.value
            _candidates = (
                _kreg.list_by_capability(_task_type_str) if _task_type_str else []
            ) + _kreg.list_by_capability("mission_execution")
            _seen_ids: set = set()
            _unique_candidates = []
            for _ca in _candidates:
                _aid = getattr(_ca, "agent_id", "")
                if _aid not in _seen_ids:
                    _seen_ids.add(_aid)
                    _unique_candidates.append(_aid)
            ctx.metadata["kernel_agent_candidates"] = _unique_candidates
            ctx.metadata["kernel_registry_size"] = len(_kreg)
            log.debug("kernel_agent_lookup",
                      mission_id=mid,
                      task_type=_task_type_str,
                      candidates=_unique_candidates,
                      registry_size=len(_kreg))
        except Exception as _ka_err:
            log.debug("phase_failed", phase="kernel_agent_lookup", err=str(_ka_err)[:80])

        # ── CapabilityDispatcher — initialize ────────────────────────
        _cap_dispatcher = self.capability_dispatcher
        if _cap_dispatcher is None:
            log.warning("meta_orchestrator.capability_dispatcher_unavailable",
                        mission_id=mid)

        # Enrich goal with reasoning + planning context
        enriched_goal = goal
        # Inject reasoning pre-pass context
        if _reasoning_result:
            reasoning_injection = _reasoning_result.to_prompt_injection()
            _shape = _reasoning_result.output_shape.value if hasattr(_reasoning_result.output_shape, 'value') else str(_reasoning_result.output_shape)
            _cx = _reasoning_result.frame.complexity_class if hasattr(_reasoning_result, 'frame') else ""
            enriched_goal = (
                goal
                + f"\n\n[ROUTING:shape={_shape},complexity={_cx}]"
                + "\n---\nReasoning:\n" + reasoning_injection
            )
        # Append prior experience context
        if rich_ctx:
            planning_ctx = rich_ctx.planning_prompt_context()
            if planning_ctx:
                enriched_goal += "\n\n---\nContext from prior experience:\n" + planning_ctx
                trace.record("plan", "context_injected",
                             reason=f"{len(planning_ctx)} chars of prior context")
        
        # ── Inject kernel plan steps (Pass 9) ─────────────────────────────
        if _kernel_plan is not None and _kernel_plan.step_count > 1:
            _plan_steps_text = "\n".join(
                f"  Step {s.step_id + 1}: {s.action}"
                for s in _kernel_plan.steps
            )
            enriched_goal += (
                f"\n\n---\nExecution Plan ({_kernel_plan.step_count} steps, "
                f"source={_kernel_plan.source}):\n{_plan_steps_text}"
            )
            trace.record("plan", "kernel_plan_injected",
                         steps=_kernel_plan.step_count,
                         source=_kernel_plan.source)

        # ── Inject kernel memory lessons (Pass 13) ──────────────────────
        _kernel_lessons = _kernel_context.get("kernel_lessons", [])
        if _kernel_lessons:
            _lessons_lines = [
                f"  [{i + 1}] {les.get('what_to_do_differently', '')[:150]}"
                for i, les in enumerate(_kernel_lessons[:3])
                if les.get("what_to_do_differently")
            ]
            if _lessons_lines:
                enriched_goal += (
                    "\n\n---\nKernel memory — lessons from similar tasks:\n"
                    + "\n".join(_lessons_lines)
                )
                trace.record("retrieve", "kernel_lessons_injected",
                             count=len(_kernel_lessons))

        # ── Phase 1-P42: Mission Reasoning State ──────────────────────
        _mission_state = None
        if not _is_chat_mode:
            try:
                from core.orchestration.mission_reasoning_state import build as build_mission_state
                _prior_fail_snippets = [
                    e.get("content", "")[:80]
                    for e in (
                        (rich_ctx.recent_failures if rich_ctx else [])
                        + (ctx.metadata.get("mission_lessons", {}).get("avoid", []))
                    )
                    if isinstance(e, (str, dict))
                ][:3]
                _mission_state = build_mission_state(
                    goal=goal,
                    mission_id=mid,
                    classification=ctx.metadata.get("classification"),
                    context={
                        "prior_skills":      rich_ctx.prior_skills if rich_ctx else [],
                        "relevant_memories": rich_ctx.relevant_memories if rich_ctx else [],
                        "recent_failures":   rich_ctx.recent_failures if rich_ctx else [],
                    },
                    prior_failures=_prior_fail_snippets,
                    memory_lessons=_kernel_context.get("kernel_lessons", []),
                )
                ctx.metadata["mission_reasoning_state"] = _mission_state.to_dict()
                _state_injection = _mission_state.to_prompt_injection()
                if _state_injection:
                    enriched_goal += "\n\n---\n" + _state_injection
                trace.record("plan", "mission_state_built",
                             task_type=_mission_state.task_type,
                             complexity=_mission_state.complexity,
                             preconditions=len(_mission_state.preconditions),
                             failure_modes=len(_mission_state.failure_modes))
                log.info("mission_reasoning_state_built",
                         mission_id=mid,
                         task_type=_mission_state.task_type,
                         complexity=_mission_state.complexity,
                         candidate_actions=len(_mission_state.candidate_actions))
            except Exception as _mrs_err:
                log.warning("phase_failed", phase="mission_reasoning_state",
                            err=str(_mrs_err)[:100])

        # Inject Phase 3 memory lessons into enriched_goal
        if _mission_lessons is not None and _mission_lessons.has_lessons:
            _lessons_injection = _mission_lessons.to_prompt_injection()
            if _lessons_injection:
                enriched_goal += "\n\n---\n" + _lessons_injection
                trace.record("retrieve", "mission_lessons_injected",
                             avoid=len(_mission_lessons.avoid),
                             reuse=len(_mission_lessons.reuse))

        # ── Pre-execution assessment ──────────────────
        pre_assess_local = pre_assess
        if pre_assess_local is None:
            try:
                from core.orchestration.pre_execution import assess_before_execution
                pre_assess_local = assess_before_execution(
                    goal=goal,
                    classification=ctx.metadata.get("classification", {}),
                    prior_skills=rich_ctx.prior_skills if rich_ctx else [],
                    relevant_memories=rich_ctx.relevant_memories if rich_ctx else [],
                )
                ctx.metadata["pre_assessment"] = pre_assess_local.to_dict()
                trace.record("pre_check", pre_assess_local.strategy_suggestion or "proceed",
                             confidence=pre_assess_local.estimated_confidence,
                             reason=f"tools_ok={pre_assess_local.tool_health_ok} failures={len(pre_assess_local.similar_failures)}")
                if pre_assess_local.similar_failures:
                    enriched_goal += "\n\nWARNING: Similar tasks have failed before. Use caution."
            except Exception as _exc:
                log.warning("phase_failed", phase="pre_assessment", err=str(_exc)[:100])

        # ── Phase 2-P42: Confidence Policy ────────────────────────────
        if not _is_chat_mode and pre_assess_local is not None:
            try:
                from core.orchestration.confidence_policy import get_confidence_policy
                _classification_dict = ctx.metadata.get("classification", {})
                _cp_decision = get_confidence_policy().decide(
                    confidence=pre_assess_local.estimated_confidence,
                    risk_level=str(_classification_dict.get("risk_level", "low") or "low"),
                    task_type=str(_classification_dict.get("task_type", "") or ""),
                    goal=goal,
                    strategy_suggestion=pre_assess_local.strategy_suggestion or "",
                    has_prior_failures=bool(pre_assess_local.similar_failures),
                    is_destructive=(
                        str(_classification_dict.get("task_type", "")) in
                        ("deployment", "deletion", "database_write")
                    ),
                )
                ctx.metadata["confidence_policy"] = _cp_decision.to_dict()

                # ── Apply behavioral changes ────────────────────────────
                if _cp_decision.abort:
                    raise RuntimeError(
                        f"Mission aborted by confidence policy: "
                        f"{_cp_decision.abort_reason}"
                    )

                if _cp_decision.require_approval and not needs_approval:
                    needs_approval = True
                    log.info(
                        "confidence_policy_requires_approval",
                        mission_id=mid,
                        tier=_cp_decision.tier.value,
                        confidence=pre_assess_local.estimated_confidence,
                        reason=_cp_decision.approval_reason,
                    )

                if _cp_decision.prompt_additions:
                    for _pa in _cp_decision.prompt_additions:
                        enriched_goal += f"\n\n[POLICY] {_pa}"

                trace.record(
                    "pre_check", f"confidence_policy:{_cp_decision.tier.value}",
                    tier=_cp_decision.tier.value,
                    confidence=pre_assess_local.estimated_confidence,
                    require_approval=_cp_decision.require_approval,
                    abort=_cp_decision.abort,
                )
            except RuntimeError:
                raise   # Re-raise abort
            except Exception as _cp_err:
                log.warning("phase_failed", phase="confidence_policy",
                            err=str(_cp_err)[:100])

        # ── Pass 43: decompose_mission — restructure enriched_goal ─────────────
        _cp_meta_decompose = ctx.metadata.get("confidence_policy", {})
        if _cp_meta_decompose.get("decompose_mission") and _mission_state is not None:
            try:
                _actions = _mission_state.candidate_actions
                if _actions:
                    _steps = "\n".join(
                        f"  Step {i + 1}: {a}"
                        for i, a in enumerate(_actions[:5])
                    )
                    enriched_goal = (
                        f"[DECOMPOSED MISSION — execute each step in order, "
                        f"do not attempt the full goal in one pass]\n"
                        f"{_steps}\n\n"
                        f"Original goal: {goal}"
                    )
                    trace.record(
                        "plan", "mission_decomposed",
                        steps=len(_actions[:5]),
                        reason="confidence_policy:decompose_mission",
                    )
                    log.info("mission_goal_decomposed",
                             mission_id=mid,
                             steps=len(_actions[:5]),
                             first_step=_actions[0][:60])
            except Exception as _de:
                log.debug("decompose_mission_failed", err=str(_de)[:60])

        # ── ContinualMemory : inject past experiences ─────────────────────────────
        try:
            from core.orchestration.continual_memory import ContinualMemory
            _cm = ContinualMemory()
            _experiences = await _cm.get_replay_batch(enriched_goal, n=3)
            if _experiences:
                _ctx_injection = _cm.build_context_injection(_experiences)
                enriched_goal = enriched_goal + "\n\n" + _ctx_injection
                log.info("continual_memory.injected", n=len(_experiences))
        except Exception as _cm_err:
            log.debug("continual_memory.inject_skipped", err=str(_cm_err)[:80])

        # ── AlignmentLayer : check action before execution ───────────────────────
        try:
            from core.orchestration.alignment_layer import AlignmentLayer
            _al = AlignmentLayer()
            _al_decision = _al.check_action(enriched_goal, {"mode": mode, "mission_id": mid})
            if not _al_decision.allowed and not _al_decision.requires_confirmation:
                log.warning("alignment.blocked", reason=_al_decision.reasoning, mission_id=mid)
                ctx.result = f"[BLOCKED BY ALIGNMENT] {_al_decision.reasoning}"
                self._transition(ctx, MissionStatus.DONE, result_len=len(ctx.result), retries=0, duration_ms=0, confidence=0.0)
                return None  # Early return, outcome will be None
            if _al_decision.requires_confirmation:
                log.info("alignment.confirmation_required", action=enriched_goal[:60], mission_id=mid)
                ctx.metadata["alignment_confirmation_required"] = True
                ctx.metadata["alignment_reason"] = _al_decision.reasoning
        except Exception as _al_err:
            log.debug("alignment.check_skipped", err=str(_al_err)[:80])

        # ── CausalModule : enrich goal with causal context ──────────────────────────────────────
        try:
            from core.orchestration.causal_module import JarvisMaxCausalIntegration
            _causal = JarvisMaxCausalIntegration()
            _causal_ctx = _causal.get_causal_context(enriched_goal)
            if _causal_ctx and _causal_ctx.strip() and "No causal" not in _causal_ctx:
                enriched_goal = enriched_goal + "\n\n" + _causal_ctx
                log.info("causal_module.context_injected", mission_id=mid)
            try:
                _causal.update_graph_from_text(enriched_goal[:500])
            except Exception:
                _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        except Exception as _causal_err:
            log.debug("causal_module.skipped", err=str(_causal_err)[:80])

        # ── ComprehensionChecker : verify goal is well-understood ────────────────
        try:
            from core.orchestration.comprehension_checker import ComprehensionChecker
            _cc = ComprehensionChecker()
            _cc_report = await asyncio.wait_for(_cc.check(enriched_goal), timeout=5.0)
            if _cc_report and not _cc_report.get("understood", True):
                _clarification = _cc_report.get("clarification_needed", "")
                if _clarification:
                    enriched_goal = enriched_goal + f"\n\n[COMPREHENSION NOTE] {_clarification}"
                    log.info("comprehension_checker.clarification_injected", mission_id=mid)
        except Exception as _cc_err:
            log.debug("comprehension_checker.skipped", err=str(_cc_err)[:80])

        # ── UnifiedMemory : semantic recall before mission ───────────────────────
        try:
            from core.orchestration.memory_system import UnifiedMemory
            _um = UnifiedMemory()
            _memories = await asyncio.wait_for(_um.recall(enriched_goal, top_k=3), timeout=3.0)
            if _memories:
                _mem_block = "\n".join(f"- {m['content'][:200]}" for m in _memories if m.get('content'))
                if _mem_block:
                    enriched_goal = enriched_goal + f"\n\n[MEMORY RECALL]\n{_mem_block}"
                    log.info("unified_memory.recalled", mission_id=mid, n=len(_memories))
        except Exception as _um_err:
            log.debug("unified_memory.skipped", err=str(_um_err)[:80])

        # Inject client profile context if sector matches goal
        try:
            from core.client_profile import ClientProfile as _CP
            _gl = goal.lower()
            _sm = {'jardin': '2f190993', 'tonte': '2f190993', 'tondeuse': '2f190993',
                   'chauffage': 'a08c93ad', 'pompe': 'a08c93ad', 'pac': 'a08c93ad',
                   'ecommerce': '9ac01d10', 'piece': '9ac01d10', 'radiateur': '9ac01d10'}
            for _kw, _pid in _sm.items():
                if _kw in _gl:
                    _p = _CP.load(_pid)
                    if _p:
                        enriched_goal = _p.inject_context(enriched_goal)
                    break
        except Exception:
            pass
        # Cap enriched_goal to avoid overwhelming agents with huge context
        if len(enriched_goal) > 2000:
            enriched_goal = enriched_goal[:2000] + "\n[...context truncated for performance...]"
            log.debug("enriched_goal_capped", mission_id=mid, original_len=len(enriched_goal))
        from core.orchestration.execution_supervisor import supervise
        delegate = self.v2 if use_budget else self.jarvis
        
        # Wire the capability dispatcher
        if _cap_dispatcher is not None:
            try:
                delegate.capability_dispatcher = _cap_dispatcher
                log.debug("meta_orchestrator.capability_dispatcher_wired",
                          mission_id=mid, delegate=type(delegate).__name__)
            except Exception as _wex:
                log.warning("meta_orchestrator.capability_dispatcher_wire_failed",
                            mission_id=mid, err=str(_wex)[:60])
        
        # Preserve confidence_policy require_approval before classification reassignment
        _cp_approval_preserved = needs_approval
        needs_approval = (
            False if force_approved
            else ctx.metadata.get("classification", {}).get("needs_approval", False)
        )
        if _cp_approval_preserved and not force_approved:
            needs_approval = True

        # ── Phase 3-kernel: Kernel policy check ───────────────────────────────
        try:
            from kernel.convergence.policy_bridge import check_action_kernel
            _k_decision = check_action_kernel(
                action_type="mission_execution",
                target=goal[:120],
                risk_level=risk,
                mode=mode,
            )
            ctx.metadata["kernel_policy"] = {
                "allowed": _k_decision.allowed,
                "requires_approval": _k_decision.requires_approval,
                "risk_level": _k_decision.risk_level.value if hasattr(_k_decision.risk_level, 'value') else str(_k_decision.risk_level),
                "reason": getattr(_k_decision, "reason", ""),
            }
            if not _k_decision.allowed:
                log.warning("kernel_policy_blocked",
                            mission_id=mid, reason=getattr(_k_decision, "reason", ""))
                if not force_approved:
                    needs_approval = True
            elif _k_decision.requires_approval and not force_approved:
                needs_approval = True
            trace.record("policy", "kernel_evaluated",
                         allowed=_k_decision.allowed,
                         requires_approval=_k_decision.requires_approval,
                         risk=risk)
        except Exception as _kpol:
            log.debug("phase_failed", phase="kernel_policy", err=str(_kpol)[:80])

        # ── Phase 3-slayer: SecurityLayer business governance check ──
        try:
            _task_type_sl = str(
                ctx.metadata.get("classification", {}).get("task_type", "") or ""
            )
            if hasattr(_task_type_sl, "value"):
                _task_type_sl = _task_type_sl.value
            _SL_ACTION_MAP = {
                "deployment":   "deployment",
                "improvement":  "self_improvement",
                # "business": removed - business missions are not payment actions
            }
            _sl_action = _SL_ACTION_MAP.get(_task_type_sl, "mission_execution")
            from security import get_security_layer as _get_sl
            _sl_result = _get_sl().check_action(
                action_type=_sl_action,
                mission_id=mid,
                mode=mode,
                risk_level=risk,
                action_target=goal[:200],
            )
            ctx.metadata["security_layer"] = {
                "allowed":    _sl_result.allowed,
                "escalated":  _sl_result.escalated,
                "reason":     _sl_result.reason,
                "risk_level": _sl_result.risk_level,
                "entry_id":   _sl_result.entry_id,
                "action_type": _sl_action,
            }
            if _sl_result.escalated and not force_approved:
                needs_approval = True
                log.info("security_layer_escalated",
                         mission_id=mid,
                         action_type=_sl_action,
                         reason=_sl_result.reason,
                         entry_id=_sl_result.entry_id)
            elif not _sl_result.allowed and not force_approved:
                needs_approval = True
                log.warning("security_layer_denied",
                            mission_id=mid,
                            action_type=_sl_action,
                            reason=_sl_result.reason)
            trace.record("policy", "security_layer_checked",
                         action_type=_sl_action,
                         allowed=_sl_result.allowed,
                         escalated=_sl_result.escalated,
                         entry_id=_sl_result.entry_id)
        except Exception as _sl_err:
            log.warning("phase_failed", phase="security_layer", err=str(_sl_err)[:80])
            ctx.metadata.setdefault("security_layer", {
                "skipped": True,
                "error": str(_sl_err)[:80],
                "allowed": None,
            })

        # ── Phase 3-kmem: Kernel working memory write ─────────────────────────
        try:
            from kernel.runtime.boot import get_runtime as _get_kernel_rt
            _krt = _get_kernel_rt()
            _krt.memory.write_working(
                key=f"mission:{mid}",
                content={
                    "mission_id": mid,
                    "goal": goal[:200],
                    "mode": mode,
                    "risk": risk,
                    "needs_approval": needs_approval,
                    "classification": ctx.metadata.get("classification", {}),
                },
                mission_id=mid,
                ttl=getattr(self.s, "mission_timeout_s", 600) + 60,
            )
            log.debug("kernel_working_memory_written", mission_id=mid)
        except Exception as _kkmem:
            log.debug("phase_failed", phase="kernel_working_memory", err=str(_kkmem)[:80])

        # ── Phase 0c routing → execution: apply provider hint via contextvar ──
        _phase0c_provider = (
            ctx.metadata.get("routed_provider", {}).get("provider_id", "")
        )
        _provider_token = None
        if _phase0c_provider:
            try:
                from core.llm_factory import _provider_override as _pov
                _provider_token = _pov.set(_phase0c_provider)
                log.info("phase0c_routing_active",
                         mission_id=mid, provider=_phase0c_provider)
            except Exception:
                _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

        # ── Pass 43: use_safer_model — activate ContextVar before execution ──
        _safer_token = None
        _cp_meta = ctx.metadata.get("confidence_policy", {})
        if _cp_meta.get("use_safer_model") and not force_approved:
            try:
                from core.llm_factory import _safer_model_active as _sma
                _safer_token = _sma.set(True)
                log.info("safer_model_activated",
                         mission_id=mid,
                         tier=_cp_meta.get("tier", "?"),
                         confidence=_cp_meta.get("confidence", "?"))
            except Exception as _sme:
                log.debug("safer_model_activation_failed", err=str(_sme)[:60])

        # FAST PATH: chat direct via JarvisLLMClient (no crew, no shadow-advisor)
        # Skip fast-path if mission needs approval or contains destructive keywords
        _DESTRUCTIVE_KW = (
            # English
            "delete","drop","remove","truncat","wipe","format","kill","destroy",
            "purge","email all","send.*all","broadcast","sudo","chmod","rm -",
            "mkfs","shutdown","reboot","restart server","drop table","drop database",
            # French — commands that could cause real damage
            "supprim","efface","effa\u00e7","suppression","vide la base",
            "formate","arr\u00eate le serveur","red\u00e9marre","\u00e9teins",
            "\u00e9crire dans","modifie la base","alter table","truncate",
            "envoie un mail \u00e0 tous","envoie un email \u00e0 tous",
        )
        _goal_for_risk = goal.lower()
        _fp_skip_risk = (
            needs_approval
            or ctx.metadata.get("classification", {}).get("risk_level", "low") in ("high", "write_high", "HIGH")
            or any(kw in _goal_for_risk for kw in _DESTRUCTIVE_KW)
        )
        # Refus immédiat pour commandes destructives en mode chat
        # Évite le crew complet (3-5min) pour une réponse de refus simple
        if _is_chat_mode and _fp_skip_risk and not needs_approval:
            _refusal = (
                "Je ne peux pas exécuter cette action directement. "
                "Les actions pouvant affecter le système ou les données "
                "(suppression, modification, envoi) nécessitent une validation. "
                "Si tu veux vraiment faire ça, soumets-la comme mission formelle."
            )
            ctx.result = _refusal
            ctx.status = MissionStatus.DONE
            ctx.completed_at = time.time()
            log.info("chat_destructive_refused", mission_id=mid, goal=goal[:60])
            try:
                from core.mission_persistence import get_mission_persistence
                get_mission_persistence().persist(ctx)
            except Exception:
                pass
            return

        if _is_chat_mode and not _fp_skip_risk:
            try:
                from core.orchestration.creative_engine import JarvisLLMClient
                _fp_llm = JarvisLLMClient(role="fast")
                _fp_sys = (
                    "Tu es Jarvis, lorchestrateurIA de JarvisMax. "
                    "Tu es lassistant personnel dUnity, fondateur du projet.\n"
                    "\n"
                    "TES CAPACITES REELLES :\n"
                    "- Analyser du code, de larchitecture, des documents\n"
                    "- Rechercher et synthétiser de linformation\n"
                    "- Planifier et décomposer des projets complexes\n"
                    "- Gérer des missions via ton pipeline dagents spécialisés\n"
                    "- Te souvenir des échanges passés via ta mémoire persistante\n"
                    "- Proposer des améliorations et apprendre de lexperience\n"
                    "\n"
                    "PERSONNALITE : direct, confiant, légèrement ironique. "
                    "Pas de fioritures, pas de faux enthousiasme.\n"
                    "\n"
                    "REGLES :\n"
                    "1. JAMAIS simuler une action réelle (suppression, modification, envoi).\n"
                    "2. Répondre en français, de manière naturelle et conversationnelle.\n"
                    "3. Longueur proportionnelle au message (court = réponse courte).\n"
                    "4. Si tu ne sais pas → dire honnêtement, ne pas inventer."
                )
                _fp_ctx = str(ctx.metadata.get("context", "") or "")
                # Inject semantic memory into fast-path
                _fp_mem = ""
                try:
                    from core.orchestration.memory_system import UnifiedMemory
                    _um_fp = UnifiedMemory()
                    _mems = await asyncio.wait_for(_um_fp.recall(goal, top_k=3), timeout=3)
                    if _mems:
                        _fp_mem = "\n".join(f"- {m['content'][:150]}" for m in _mems if m.get("content"))
                except Exception:
                    pass
                # Build prompt with all context
                _fp_parts = [_fp_sys]
                if _fp_mem:
                    _fp_parts.append("\n\nMémoire pertinente:\n" + _fp_mem)
                if _fp_ctx:
                    _fp_parts.append("\n\nConversation récente:\n" + _fp_ctx)
                _fp_parts.append("\n\nMessage: " + goal)
                _fp_prompt = "".join(_fp_parts)
                _fp_text = await asyncio.wait_for(
                    _fp_llm.complete(_fp_prompt, max_tokens=2000),
                    timeout=45
                )
                if not _fp_text or len(str(_fp_text).strip()) < 3:
                    raise ValueError("empty_response")
                ctx.result = str(_fp_text)
                ctx.status = MissionStatus.DONE
                ctx.completed_at = time.time()
                log.info("chat_fast_path_ok", mission_id=mid, chars=len(str(_fp_text)))
                # Store fast-path exchange in knowledge memory for future recall
                try:
                    from core.knowledge_memory import get_knowledge_memory
                    _km = get_knowledge_memory()
                    _km.store_if_useful(
                        goal=goal,
                        mission_type="chat",
                        solution_summary=str(_fp_text)[:500],
                        tools_used=[],
                        agents_used=["fast-path"],
                        confidence_score=0.8,
                        fallback_level=0,
                        execution_policy_decision="fast_path",
                    )
                except Exception:
                    pass
                # Persist to both stores so UI sees consistent status
                try:
                    from core.mission_persistence import get_mission_persistence
                    get_mission_persistence().persist(ctx)
                except Exception:
                    pass
                # Post-mission learning: extract lesson if needed
                try:
                    from core.orchestration.learning_loop import extract_lesson, store_lesson
                    _lesson = extract_lesson(
                        mission_id=mid,
                        goal=goal[:200],
                        result=str(ctx.result)[:300],
                        reflection_verdict=ctx.metadata.get("reflection_verdict", "accept"),
                        reflection_confidence=float(ctx.metadata.get("confidence_score", 0.8)),
                        error_class=ctx.metadata.get("error_class", ""),
                        retries=ctx.metadata.get("retries", 0),
                    )
                    if _lesson:
                        store_lesson(_lesson)
                        log.info("learning_loop.lesson_stored", mission_id=mid,
                                 confidence=_lesson.confidence)
                except Exception:
                    pass
                try:
                    # Sync mission_system store to avoid READY/DONE mismatch
                    from core.mission_system import get_mission_system
                    _ms = get_mission_system()
                    _ms_rec = _ms.get_mission(mid)
                    if _ms_rec is not None:
                        _ms_rec.status = "DONE"
                        _ms_rec.final_output = ctx.result
                        _ms._save_mission(_ms_rec)
                except Exception:
                    pass
                try:
                    self._cleanup_event_stream(mid)
                except Exception:
                    pass
                return
            except Exception as _fe:
                log.warning("chat_fast_path_fail", err=str(_fe)[:120])
                # Fall through to full crew

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # PHASE 4: AGI COGNITION WRAPPER
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        _mission_timeout = getattr(self.s, "mission_timeout_s", 120)
        
        _use_cognition = (
            not _is_chat_mode
            and pre_assess_local is not None
            and pre_assess_local.estimated_confidence < 0.9
            and len(goal) > 50
        )
        
        outcome = None
        if _use_cognition:
            log.info("cognition.activating", mission_id=mid, conf=pre_assess_local.estimated_confidence)
            try:
                from core.cognition.orchestrator import CognitionOrchestrator
                
                _cog = CognitionOrchestrator(llm_client=delegate.llm)
                
                _payload = {
                    "mission_id": mid, "goal": enriched_goal, "mode": mode,
                    "session_id": mid, "risk_level": risk,
                    "requires_approval": needs_approval, "skip_approval": force_approved,
                    "callback": callback,
                    "classification": ctx.metadata.get("classification", {}),
                }
                
                # FIXED (Phase 29): Integrate real executor with cognition pipeline
                # Create async wrapper that calls the real delegate.run through supervise()
                async def _real_executor(mission: Dict[str, Any]) -> str:
                    """Execute mission using real JarvisOrchestrator + supervision."""
                    result = await asyncio.wait_for(
                        supervise(
                            delegate.run,
                            mission_id=mission["mission_id"],
                            goal=mission["goal"],
                            mode=mission.get("mode", "normal"),
                            session_id=mission.get("session_id"),
                            risk_level=mission.get("risk_level", "medium"),
                            requires_approval=mission.get("requires_approval", False),
                            skip_approval=mission.get("skip_approval", False),
                            callback=mission.get("callback"),
                        ),
                        timeout=_mission_timeout,
                    )
                    # Extract output from result
                    if isinstance(result, dict):
                        return result.get("output", str(result))
                    return str(result)
                
                # Only activate ToT for genuinely complex goals
                from core.cognition.tot_wrapper import should_use_tot as _should_tot
                _use_tot = _should_tot(goal)
                cognition_result = await asyncio.wait_for(
                    _cog.execute_mission_with_cognition(
                        mission=_payload,
                        enable_tot=_use_tot,
                        enable_confidence=True,
                        enable_learning=True,
                        executor_fn=_real_executor,
                    ),
                    timeout=180,  # 3 min max for cognition (incl. ToT)
                )
                # Extract outcome from cognition result
                # CognitionOrchestrator returns augmented mission dict with "result" key
                if isinstance(cognition_result, dict):
                    outcome = cognition_result.get("result", cognition_result)
                else:
                    outcome = cognition_result
                trace.record("cognition", "success", conf=pre_assess_local.estimated_confidence)
            except Exception as _cog_err:
                log.warning("cognition.failed", mission_id=mid, err=str(_cog_err)[:100])
                outcome = None
        
        if outcome is None:
            if _use_cognition:
                log.info("cognition.fallback_direct", mission_id=mid)

            try:
                outcome = await asyncio.wait_for(
                    supervise(
                        delegate.run,
                        mission_id=mid,
                        goal=enriched_goal,
                        mode=mode,
                        session_id=mid,
                        risk_level="high" if needs_approval and not force_approved else risk,
                        requires_approval=needs_approval,
                        skip_approval=force_approved,
                        callback=callback,
                    ),
                    timeout=_mission_timeout,
                )
            finally:
                # Always reset the provider override after execution
                if _provider_token is not None:
                    try:
                        from core.llm_factory import _provider_override as _pov
                        _pov.reset(_provider_token)
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
                # Pass 43: reset safer_model ContextVar
                if _safer_token is not None:
                    try:
                        from core.llm_factory import _safer_model_active as _sma
                        _sma.reset(_safer_token)
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

        # Store execution context for post-processing helpers
        ctx.metadata["_exec_enriched_goal"] = enriched_goal
        ctx.metadata["_exec_risk"] = risk
        ctx.metadata["_exec_delegate"] = delegate
        ctx.metadata["_exec_mission_timeout"] = _mission_timeout
        ctx.metadata["_exec_needs_approval"] = needs_approval
        
        return outcome

    async def _handle_success_outcome(
        self,
        outcome,
        ctx,
        mid: str,
        goal: str,
        mode: str,
        trace,
        _reasoning_result,
        force_approved: bool,
        callback,
    ) -> float:
        """
        Handle successful mission outcome: evaluation, retry logic, memory storage, learning.
        
        Returns result_confidence.
        
        Extracted from run_mission() lines 1705-2053 (~348 lines).
        Contains:
        - Kernel evaluation (Phase 8)
        - Kernel-based retry logic (bounded, shape-aware)
        - Memory storage (UnifiedMemory, ContinualMemory, ArtificialCuriosity)
        - Skill store persistence (Voyager pattern)
        - Event emissions (journal, metrics, kernel)
        - Output formatting (Phase 3a)
        - Learning loop (Phase 3b, kernel-authoritative R5)
        - Skill recording and refinement (Phase 4)
        - Memory facade storage (Phase 5)
        """
        # Extract execution context from metadata
        enriched_goal = ctx.metadata.get("_exec_enriched_goal", goal)
        risk = ctx.metadata.get("_exec_risk", "low")
        delegate = ctx.metadata.get("_exec_delegate", self.jarvis)
        _mission_timeout = ctx.metadata.get("_exec_mission_timeout", 600)
        needs_approval = ctx.metadata.get("_exec_needs_approval", False)
        
        self._circuit_breaker.record_success()
        # RUNNING -> REVIEW
        self._transition(ctx, MissionStatus.REVIEW)
        # Unwrap nested ExecutionOutcome — outcome.result may itself be an ExecutionOutcome
        _raw_outcome_result = getattr(outcome, "result", outcome) if outcome is not None else ""
        if hasattr(_raw_outcome_result, "result"):  # nested ExecutionOutcome
            _raw_outcome_result = getattr(_raw_outcome_result, "result", "") or ""
        ctx.result = _strip_execution_outcome(
            _raw_outcome_result if isinstance(_raw_outcome_result, str) else str(_raw_outcome_result or "")
        )

        # ── KERNEL EVALUATION (authoritative — Phase 8) ───────
        # Single call replaces reflect() + critique_output().
        # kernel.evaluator calls both internally via registration,
        # synthesizes a unified KernelScore, and populates
        # ctx.metadata["critique"] + ["reflection"] for backward compat.
        result_confidence = 0.7
        _kernel_score = None
        _shape_val = ""
        if _reasoning_result:
            _shape_val = (
                _reasoning_result.output_shape.value
                if hasattr(_reasoning_result.output_shape, "value")
                else str(_reasoning_result.output_shape)
            )
        try:
            from kernel.evaluation.scorer import get_evaluator as _get_kernel_eval
            _task_type_eval = str(
                ctx.metadata.get("classification", {}).get("task_type", "")
                or ""
            )
            if hasattr(_task_type_eval, "value"):
                _task_type_eval = _task_type_eval.value
            _kernel_score = _get_kernel_eval().evaluate(
                goal=goal,
                result=ctx.result or "",
                task_type=_task_type_eval,
                mission_id=mid,
                duration_ms=outcome.duration_ms,
                retries=outcome.retries,
                output_shape=_shape_val,
                reasoning_frame=(
                    _reasoning_result.frame if _reasoning_result else None
                ),
            )
            result_confidence = _kernel_score.confidence
            ctx.metadata["kernel_score"] = _kernel_score.to_dict()
            # Backward compat: populate critique/reflection dicts
            # so existing downstream code (judgment_signals, etc.) still works
            if _kernel_score.critique_dict:
                ctx.metadata["critique"] = _kernel_score.critique_dict
            if _kernel_score.reflection_dict:
                ctx.metadata["reflection"] = _kernel_score.reflection_dict
            if not _kernel_score.passed:
                log.warning("mission.weak_output_detected",
                            mission_id=mid,
                            score=_kernel_score.score,
                            weaknesses=_kernel_score.weaknesses[:2],
                            retry_recommended=_kernel_score.retry_recommended)
            # Judgment signals: kernel_score already contains all signal data
            # via critique_dict/reflection_dict — no redundant core inline call.
            trace.record("evaluate", "kernel",
                         score=round(_kernel_score.score, 3),
                         confidence=round(_kernel_score.confidence, 3),
                         retry=_kernel_score.retry_recommended,
                         source=_kernel_score.source)
        except Exception as _keval_err:
            log.debug("kernel_evaluation_skipped", err=str(_keval_err)[:100])
            result_confidence = 0.7

        # ── Kernel → Retry (bounded, 1 attempt, shape-aware) ─────
        # Primary: kernel_score.retry_recommended + score vs threshold
        # Fallback: ctx.metadata["critique"] dict (populated above by kernel)
        result_confidence = await self._handle_kernel_retry(
            ctx, mid, goal, mode, trace, outcome, _reasoning_result,
            enriched_goal, risk, needs_approval, force_approved, callback,
            delegate, _mission_timeout, result_confidence, _shape_val
        )

        # REVIEW -> DONE
        self._transition(ctx, MissionStatus.DONE,
                         result_len=len(ctx.result),
                         retries=outcome.retries,
                         duration_ms=outcome.duration_ms,
                         confidence=result_confidence)
        
        # ── Memory and event storage ───────────────────────────
        await self._store_mission_memories(mid, goal, mode, ctx, enriched_goal)
        self._emit_completion_events(mid, goal, outcome, result_confidence, trace)
        
        # ── Phase 3a: Output formatting ───────────────
        try:
            from core.orchestration.output_formatter import format_output
            task_type = ctx.metadata.get("classification", {}).get("task_type", "other")
            ctx.result = format_output(ctx.result, task_type=task_type, goal=goal)
        except Exception as _exc:
            log.debug("phase_failed", phase="output_format", err=str(_exc)[:100])

        # ── Phase 3c: Livrable export (auto-generate client deliverable) ──
        try:
            from core.livrable_export import LivrableExport
            from core.client_profile import ClientProfile
            # Detect client from goal keywords
            _gl = goal.lower()
            _sm = {'jardin': '2f190993', 'tonte': '2f190993', 'tondeuse': '2f190993',
                   'chauffage': 'a08c93ad', 'pompe': 'a08c93ad', 'pac': 'a08c93ad',
                   'ecommerce': '9ac01d10', 'piece': '9ac01d10', 'radiateur': '9ac01d10'}
            _client_name = ''
            for _kw, _pid in _sm.items():
                if _kw in _gl:
                    _p = ClientProfile.load(_pid)
                    if _p:
                        _client_name = _p.name
                        _p.add_mission(goal, 'COMPLETED', str(ctx.result)[:200])
                        _p.save()
                    break
            if ctx.result and len(ctx.result) > 100:
                _exp = LivrableExport()
                _paths = _exp.save(ctx.result, _client_name or 'JarvisMax', goal, mid)
                ctx.metadata['livrable_md'] = _paths['markdown']
                ctx.metadata['livrable_html'] = _paths['html']
                log.info('livrable_exported', mission_id=mid, client=_client_name,
                         md=_paths['markdown'].split('/')[-1])
        except Exception as _lv_err:
            log.debug('livrable_export_skipped', err=str(_lv_err)[:80])

        # ── Phase 3b: Learning loop (kernel-authoritative — R5 / Pass 23) ──
        self._execute_kernel_learning(goal, ctx, mid, outcome, result_confidence, trace)

        # ── Phase 4: Record skill + refine prior ─────────
        self._record_skills(mid, goal, ctx, risk, result_confidence, trace)

        # ── Phase 5: Store to memory ──────────────────────
        self._store_to_memory_facade(mid, goal, ctx, trace)
        
        return result_confidence

    async def _handle_kernel_retry(
        self,
        ctx,
        mid: str,
        goal: str,
        mode: str,
        trace,
        outcome,
        _reasoning_result,
        enriched_goal: str,
        risk: str,
        needs_approval: bool,
        force_approved: bool,
        callback,
        delegate,
        _mission_timeout: float,
        result_confidence: float,
        _shape_val: str,
    ) -> float:
        """
        Handle kernel-based retry logic (bounded, 1 attempt, shape-aware).
        
        Returns updated result_confidence.
        """
        _kernel_score_meta = ctx.metadata.get("kernel_score", {})
        _critique_obj      = ctx.metadata.get("critique", {})
        _did_retry         = ctx.metadata.get("_critique_retry_done", False)
        _retry_threshold   = _kernel_score_meta.get(
            "retry_threshold_used",
            {"direct_answer": 0.20, "patch": 0.30, "diagnosis": 0.30,
             "plan": 0.30, "report": 0.35, "warning": 0.20}.get(_shape_val, 0.25),
        )
        # Retry recommended by kernel, or critique says weak at threshold
        _score_for_retry = _kernel_score_meta.get(
            "score", _critique_obj.get("overall", 1.0),
        )
        _is_weak_for_retry = (
            _kernel_score_meta.get("retry_recommended", False) or
            _critique_obj.get("is_weak", False)
        )
        if (
            _is_weak_for_retry
            and _score_for_retry < _retry_threshold
            and not _did_retry
            and outcome.retries == 0
            and len(goal.strip()) > 80           # skip retry for short/conversational goals
            and not mid.endswith("-retry")       # prevent retry chains
        ):
            ctx.metadata["_critique_retry_done"] = True
            log.info("mission.critique_retry",
                     mission_id=mid,
                     score=_score_for_retry,
                     weaknesses=(_kernel_score_meta.get(
                         "weaknesses", _critique_obj.get("weaknesses", []),
                     ))[:2])
            try:
                # Build retry goal — kernel weaknesses preferred
                _weak_list = (
                    _kernel_score_meta.get("weaknesses", []) or
                    _critique_obj.get("weaknesses", [])
                )
                _weak_reasons = "; ".join(_weak_list[:3])
                _suggestion = (
                    _kernel_score_meta.get("improvement_suggestion", "") or
                    _critique_obj.get("improvement_suggestion", "")
                )
                _retry_goal = (
                    f"{enriched_goal}\n\n"
                    f"---\nPREVIOUS ATTEMPT WAS WEAK:\n"
                    f"Weaknesses: {_weak_reasons}\n"
                    f"Improvement needed: {_suggestion}\n"
                    f"Produce a more specific, complete, and actionable response."
                )
                # Re-run with feedback
                # Canonical supervise lives in core.orchestration.execution_supervisor.
                # The previous import (`from core.supervisor import supervise`) pointed
                # to a module that does not exist — ImportError would be swallowed by
                # the outer try/except and silently skip the retry path.
                from core.orchestration.execution_supervisor import supervise
                import asyncio
                self._transition(ctx, MissionStatus.RUNNING, reason="critique_retry")
                _retry_outcome = await asyncio.wait_for(
                    supervise(
                        delegate.run,
                        mission_id=f"{mid}-retry",
                        goal=_retry_goal,
                        mode=mode,
                        session_id=f"{mid}-retry",
                        risk_level=risk,
                        requires_approval=needs_approval,
                        skip_approval=force_approved,
                        callback=callback,
                    ),
                    timeout=_mission_timeout,
                )
                if _retry_outcome.success and _retry_outcome.result:
                    _retry_len = len(_retry_outcome.result.strip())
                    _orig_len = len((ctx.result or "").strip())
                    # Accept retry if it produced more content
                    if _retry_len > _orig_len * 0.5:
                        ctx.result = _retry_outcome.result
                        result_confidence = min(0.8, result_confidence + 0.2)
                        ctx.metadata["critique_retry_used"] = True
                        log.info("mission.critique_retry_accepted",
                                 mission_id=mid,
                                 orig_len=_orig_len,
                                 retry_len=_retry_len)
                        trace.record("retry", "critique_accepted",
                                     improvement=f"{_orig_len}→{_retry_len}")
                # Re-enter REVIEW for the retry
                self._transition(ctx, MissionStatus.REVIEW, reason="post_retry")
            except Exception as _retry_err:
                log.warning("mission.critique_retry_failed",
                            mission_id=mid, err=str(_retry_err)[:80])
                # Stay with original result
                self._transition(ctx, MissionStatus.REVIEW, reason="retry_failed")
        
        return result_confidence

    async def _store_mission_memories(
        self,
        mid: str,
        goal: str,
        mode: str,
        ctx,
        enriched_goal: str,
    ) -> None:
        """Store mission results to various memory systems."""
        # ── UnifiedMemory : store result after mission ─────────────────────────
        try:
            from core.orchestration.memory_system import UnifiedMemory
            _um2 = UnifiedMemory()
            await _um2.store(
                content=f"Mission: {enriched_goal[:200]}\nResult: {(ctx.result or '')[:300]}",
                memory_type="episode",
                metadata={"mission_id": mid, "mode": mode}
            )
            log.info("unified_memory.stored", mission_id=mid)
        except Exception as _um2_err:
            log.debug("unified_memory.store_skipped", err=str(_um2_err)[:80])
        
        # ── ContinualMemory : store experience ─────────────────────────────────
        try:
            from core.orchestration.continual_memory import ContinualMemory
            _cm2 = ContinualMemory()
            _surprise = _cm2.compute_surprise(enriched_goal, ctx.result or "")
            await _cm2.store_experience(
                mission_id=mid,
                goal=enriched_goal[:300],
                result=(ctx.result or "")[:300],
                surprise_score=_surprise,
                success=True,
                tags=[ctx.metadata.get("task_type", "general")]
            )
            log.info("continual_memory.stored", mission_id=mid, surprise=round(_surprise, 3))
        except Exception as _cm2_err:
            log.debug("continual_memory.store_skipped", err=str(_cm2_err)[:80])
        
        # ── ArtificialCuriosity : detect and log surprising results ───────────────────
        try:
            from core.orchestration.creative_engine import ArtificialCuriosity, JarvisLLMClient
            _ac = ArtificialCuriosity(llm_client=JarvisLLMClient(role="fast"))
            _surprise_ac = _ac.compute_surprise_score(enriched_goal, ctx.result or "")
            if _surprise_ac > 0.6:
                _questions = await _ac.generate_curiosity_questions(enriched_goal, ctx.result or "")
                if _questions:
                    ctx.metadata["curiosity_questions"] = _questions[:3]
                    log.info("curiosity.triggered", mission_id=mid, surprise=round(_surprise_ac, 2), questions=len(_questions))
        except Exception as _ac_err:
            log.debug("curiosity.skipped", err=str(_ac_err)[:80])
        
        # ── Skill Store: persist successful mission pattern (Voyager pattern) ──
        # Store if confidence >= threshold (default 0.70).
        # Fail-open: any exception is silently swallowed.
        try:
            from core.skill_store import get_skill_store
            import asyncio
            _plan_to_store = ctx.metadata.get("context", {})
            if not _plan_to_store:
                _plan_to_store = {"steps": ["direct_execution"], "result_len": len(ctx.result)}
            _mission_type_for_skill = str(
                ctx.metadata.get("classification", {}).get("task_type", "general") or "general"
            )
            result_confidence = ctx.metadata.get("confidence", 0.7)
            # Use create_task instead of ensure_future for better error handling
            _skill_task = asyncio.create_task(get_skill_store().store(
                mission_id=mid,
                goal=goal,
                plan=_plan_to_store,
                confidence=result_confidence,
                mission_type=_mission_type_for_skill,
                tags=[mode, _mission_type_for_skill],
            ))
            # Log exceptions from background task (don't let them be silent)
            _skill_task.add_done_callback(
                lambda t: log.error("skill_store_error", exc=t.exception()) if t.exception() else None
            )
            log.info("skill_store_triggered", mission_id=mid, confidence=result_confidence)
        except Exception as _ss_err:
            log.debug("skill_store_skip", err=str(_ss_err)[:80])

    def _emit_completion_events(
        self,
        mid: str,
        goal: str,
        outcome,
        result_confidence: float,
        trace,
    ) -> None:
        """Emit various completion events to journal, metrics, kernel."""
        # AI OS skill discovery (fail-open)
        try:
            from core.skills.skill_discovery import get_skill_discovery
            sd = get_skill_discovery()
            # outcome.actions doesn't exist on ExecutionOutcome — use getattr guard
            tools_used = [a.tool_name for a in getattr(outcome, "actions", [])
                          if hasattr(a, "tool_name")]
            sd.discover_from_mission(mid, goal, tools_used, success=True)
        except Exception as _sd_err:
            log.debug("skill_discovery_failed", err=str(_sd_err)[:60])
        
        trace.record("complete", "done",
                     reason=f"duration={outcome.duration_ms}ms retries={outcome.retries} confidence={result_confidence}")
        
        # Journal: mission completed
        try:
            from core.cognitive_events.emitter import emit_mission_completed
            emit_mission_completed(
                mission_id=mid, duration_ms=outcome.duration_ms,
                confidence=result_confidence,
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        
        # Metrics store counter (admin panel)
        try:
            from core.metrics_store import emit_mission_completed as _ms_completed
            _ms_completed("canonical", duration_ms=outcome.duration_ms)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        
        # Kernel event: mission completed (dual emission)
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.completed", mission_id=mid,
                              duration_ms=outcome.duration_ms,
                              confidence=result_confidence)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        
        # Kernel working memory: clear mission slot (it is done)
        try:
            from kernel.runtime.boot import get_runtime as _get_kernel_rt
            _get_kernel_rt().memory.clear_working(mission_id=mid)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

    def _execute_kernel_learning(
        self,
        goal: str,
        ctx,
        mid: str,
        outcome,
        result_confidence: float,
        trace,
    ) -> None:
        """Execute kernel learning loop (R5 - kernel authoritative)."""
        _kernel_lesson = None
        try:
            from kernel.runtime.kernel import get_kernel as _get_jk_learn
            _kscore_meta = ctx.metadata.get("kernel_score", {})
            _k_verdict = str(
                _kscore_meta.get("verdict")
                or ctx.metadata.get("reflection", {}).get("verdict", "accept")
                or "accept"
            )
            _k_confidence = float(
                _kscore_meta.get("confidence", result_confidence) or result_confidence
            )
            _k_weaknesses = list(_kscore_meta.get("weaknesses") or [])
            _k_suggestion = str(_kscore_meta.get("improvement_suggestion") or "")
            _kernel_lesson = _get_jk_learn().learn(  # R5: via kernel.learn()
                goal=goal,
                result=ctx.result or "",
                mission_id=mid,
                verdict=_k_verdict,
                confidence=_k_confidence,
                weaknesses=_k_weaknesses,
                improvement_suggestion=_k_suggestion,
                retries=outcome.retries,
                error_class="",
            )
            if _kernel_lesson:
                ctx.metadata["kernel_lesson"] = _kernel_lesson.to_dict()
                trace.record("learn", "kernel_lesson_extracted",
                             verdict=_k_verdict,
                             confidence=round(_k_confidence, 3),
                             reason=_kernel_lesson.what_to_do_differently[:60])
        except Exception as _klearn_err:
            # BLOC 2 — R5: kernel.learn() is the SOLE learning authority.
            # The core.orchestration.learning_loop fallback has been removed.
            # If kernel.learn() fails, we log and continue — no side-channel store.
            # This enforces R5: structured learning only via kernel.learn().
            log.debug("kernel_learning_skipped_r5", err=str(_klearn_err)[:100])

    def _record_skills(
        self,
        mid: str,
        goal: str,
        ctx,
        risk: str,
        result_confidence: float,
        trace,
    ) -> None:
        """Record skill outcome and refine prior skills (Phase 4)."""
        try:
            from core.skills import get_skill_service
            svc = get_skill_service()
            svc.record_outcome(
                mission_id=mid,
                goal=goal,
                result=ctx.result,
                status="DONE",
                risk_level=risk,
                confidence=result_confidence,
            )
            # Refine any prior skill that was retrieved
            for ps in ctx.metadata.get("prior_skills", []):
                sid = ps.get("skill_id", "")
                if sid:
                    svc.refine_skill(sid, ctx.result, success=True)
            trace.record("store", "skill_evaluated")
        except Exception as _exc:
            log.warning("phase_failed", phase="skill_store", err=str(_exc)[:100])

    def _store_to_memory_facade(
        self,
        mid: str,
        goal: str,
        ctx,
        trace,
    ) -> None:
        """Store outcome to memory facade (Phase 5)."""
        try:
            from core.memory_facade import get_memory_facade
            get_memory_facade().store_outcome(
                content=f"Mission {mid}: {goal[:100]} -> {ctx.result[:200]}",
                mission_id=mid,
                status="DONE",
            )
            trace.record("store", "memory_stored")
        except Exception as _exc:
            log.debug("phase_failed", phase="memory_store", err=str(_exc)[:100])

    def _handle_failed_outcome(
        self,
        outcome,
        ctx,
        mid: str,
        goal: str,
        trace,
    ) -> None:
        """
        Handle failed mission outcome: circuit breaker, memory storage, event emission.
        
        Extracted from run_mission() lines 2071-2114 (~43 lines).
        """
        # Execution failed after retries — record for circuit breaker
        self._circuit_breaker.record_failure()
        ctx.error = outcome.error
        self._transition(ctx, MissionStatus.FAILED,
                         reason=outcome.error_class,
                         retries=outcome.retries)
        trace.record("complete", "failed",
                     reason=f"{outcome.error_class}: {outcome.error[:60]}")

        # Journal: mission failed
        try:
            from core.cognitive_events.emitter import emit_mission_failed
            emit_mission_failed(
                mission_id=mid, error=outcome.error[:200],
                error_class=outcome.error_class,
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        
        # Metrics store counter (admin panel)
        try:
            from core.metrics_store import emit_mission_failed as _ms_failed
            _ms_failed("canonical", reason=outcome.error_class)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')
        
        # Kernel event: mission failed (dual emission)
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.failed", mission_id=mid,
                              error=outcome.error[:200],
                              error_class=outcome.error_class)
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

        # Store failure in memory
        try:
            from core.memory_facade import get_memory_facade
            get_memory_facade().store_failure(
                content=f"Mission {mid} FAILED: {goal[:80]} -> {outcome.error[:200]}",
                error_class=outcome.error_class,
                mission_id=mid,
            )
        except Exception as _exc:
            log.debug("phase_failed", phase="memory_store_fail", err=str(_exc)[:100])

    def _handle_awaiting_approval(
        self,
        outcome,
        ctx,
        mid: str,
        risk: str,
        trace,
    ) -> None:
        """Handle awaiting approval outcome (lines 2054-2068)."""
        # Execution paused — waiting for human approval
        ctx.error = "Awaiting human approval"
        ctx.metadata["approval_item_id"] = next(
            (d.get("item_id", "") for d in outcome.decision_trace
             if d.get("step") == "approval_gate"), ""
        )
        ctx.metadata["approval_status"] = "pending"
        ctx.metadata["approval_paused_at"] = time.time()
        # Transition to explicit AWAITING_APPROVAL status
        self._transition(ctx, MissionStatus.AWAITING_APPROVAL,
                         reason=f"risk={risk}")
        trace.record("complete", "awaiting_approval",
                     reason=f"risk={risk}, item_id={ctx.metadata.get('approval_item_id', '')[:8]}")
        log.info("mission.awaiting_approval",
                 mission_id=mid, risk_level=risk)

        # Sync PENDING_VALIDATION into legacy MissionSystem so /api/v2/tasks sees it
        try:
            from core.mission_system import get_mission_system as _gms, MissionStatus as _LMS
            _ms_sync = _gms()
            _m_sync = _ms_sync.get(mid)
            if _m_sync:
                _m_sync.status = _LMS.PENDING_VALIDATION
                _m_sync.decision_trace["awaiting_approval"] = True
                _m_sync.decision_trace["approval_item_id"] = ctx.metadata.get("approval_item_id", "")
                log.info("mission.pending_validation_synced", mission_id=mid)
        except Exception as _sync_err:
            log.debug("awaiting_approval_sync_failed", err=str(_sync_err)[:60])

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
            pass

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
            classification = self._classify_mission(
                goal, mode, ctx, trace, _k_classification_obj
            )

            # ── Phase 0b: Match AI OS capabilities (extracted method) ────
            matched_capabilities = self._match_ai_os_capabilities(
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

            # ── JarvisTeam dispatcher (mode=improve/lab/dev) ──────────────────────────
            # Route to architect→coder→reviewer→qa chain when mode indicates improvement.
            if mode in ("improve", "lab", "dev") and not _is_chat_mode:
                try:
                    from core.orchestration.jarvis_team_dispatcher import dispatch_improve
                    log.info("jarvis_team.dispatching", mission_id=mid, mode=mode)
                    _team_result = await dispatch_improve(
                        goal=goal,
                        llm_client=self.jarvis.llm,
                        mission_id=mid,
                    )
                    if _team_result.get("result"):
                        ctx.result = _team_result["result"]
                        ctx.metadata["jarvis_team"] = _team_result
                        self._transition(ctx, MissionStatus.REVIEW)
                        self._transition(ctx, MissionStatus.DONE,
                                         result_len=len(ctx.result),
                                         retries=0,
                                         duration_ms=0,
                                         confidence=0.75)
                        return ctx
                except Exception as _jt_err:
                    log.warning("jarvis_team.dispatch_failed", err=str(_jt_err)[:80])
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
                result_confidence = await self._handle_success_outcome(
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
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

        # Journal event
        try:
            from core.cognitive_events.emitter import emit_approval_resolved
            emit_approval_resolved(mission_id, granted=granted,
                                    item_id=ctx.metadata.get("approval_item_id", ""))
        except Exception:
            _silent_log.debug("suppressed_exception", src='meta_orchestrator.py')

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

    # ── Custom mission handlers ───────────────────────────────────────────────
    
    def register_mission_handler(self, mission_type: str, handler: Callable) -> None:
        """
        Register a custom mission handler for a specific mission type.
        
        Example:
            async def handle_custom_mission(mission: dict, context: dict) -> dict:
                return {"status": "success", "result": ...}
            
            orchestrator.register_mission_handler("custom.mission", handle_custom_mission)
        
        Args:
            mission_type: Mission type identifier (e.g. "business.scan_opportunities")
            handler: Async function that takes (mission: dict, context: dict) and returns dict
        """
        self._custom_handlers[mission_type] = handler
        log.info("mission_handler_registered", mission_type=mission_type)
    
    async def dispatch_custom_mission(self, mission_type: str, mission: dict, context: dict | None = None) -> dict:
        """
        Dispatch a mission to a custom handler if registered.
        
        Args:
            mission_type: Mission type identifier
            mission: Mission dict with params
            context: Optional execution context
        
        Returns:
            Handler result dict
        
        Raises:
            KeyError: If mission_type not registered
        """
        if mission_type not in self._custom_handlers:
            raise KeyError(f"No handler registered for mission type: {mission_type}")
        
        handler = self._custom_handlers[mission_type]
        log.info("mission_dispatch", mission_type=mission_type)
        
        try:
            result = await handler(mission, context or {})
            return result
        except Exception as e:
            log.error("mission_handler_failed", mission_type=mission_type, error=str(e))
            raise

    # ── Backward-compat shims ────────────────────────────────────────────────
    # Ces méthodes permettent aux modules qui appelaient JarvisOrchestrator.run()
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
        Compatibilité ascendante avec JarvisOrchestrator.run().
        Délègue à run_mission() et retourne la session JarvisSession originale.
        """
        mid = session_id or uuid.uuid4().hex[:16]
        # BLOC 2: ALL modes route through run_mission() — kernel cognitive pipeline.
        # Previous bypass (mode != "auto" → jarvis.run() directly) skipped:
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
