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
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

log = structlog.get_logger(__name__)

CB = Callable[[str], Awaitable[None]]


# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker — prevents cascade failures when the delegate is broken
# ─────────────────────────────────────────────────────────────────────────────

class _CircuitBreaker:
    """
    Simple two-state circuit breaker (CLOSED / OPEN).

    CLOSED → normal operation.
    OPEN   → fast-fail for `_reset_s` seconds after `_threshold` consecutive
             failures, then auto-reset to CLOSED for the next probe.

    Thread-safe. Never raises.
    """

    def __init__(self, failure_threshold: int = 5, reset_s: float = 60.0):
        self._threshold = failure_threshold
        self._reset_s   = reset_s
        self._failures  = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        """Return True if the circuit is open (fast-fail mode)."""
        with self._lock:
            if self._open_until == 0.0:
                return False
            if time.time() >= self._open_until:
                # Auto-reset: allow one probe through
                self._open_until = 0.0
                self._failures   = 0
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures   = 0
            self._open_until = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._open_until = time.time() + self._reset_s
                log.warning(
                    "meta_orchestrator.circuit_open",
                    failures=self._failures,
                    open_for_s=self._reset_s,
                )

    def status(self) -> dict:
        with self._lock:
            return {
                "open": self._open_until > time.time(),
                "failures": self._failures,
                "open_until": self._open_until,
            }


# ─────────────────────────────────────────────────────────────────────────────
# State machine — KERNEL-CANONICAL: kernel/state/mission_state.py
# ─────────────────────────────────────────────────────────────────────────────
# MissionContext and VALID_TRANSITIONS now live in the kernel.
# MetaOrchestrator imports them and owns the side-effect layer
# (event emission, persistence) on top of kernel state transitions.
from core.state import MissionStatus  # noqa: F811  — single source of truth enum

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
            from core.orchestrator import JarvisOrchestrator
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
                asyncio.ensure_future(_stream.append(_evt))
        except Exception:
            pass
        # Persist state to disk (fail-open)
        try:
            from core.mission_persistence import get_mission_persistence
            get_mission_persistence().persist(ctx)
        except Exception as _pe:
            log.debug("mission_persist_failed", err=str(_pe)[:80])

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

    # ── Public API ───────────────────────────────────────────────────────────

    async def run_mission(
        self,
        goal: str,
        mode: str = "auto",
        mission_id: str | None = None,
        callback: CB | None = None,
        use_budget: bool = False,
        force_approved: bool = False,
    ) -> MissionContext:
        """
        Enhanced mission lifecycle with classification, context assembly,
        supervised execution, and structured decision tracing.

        force_approved=True bypasses the approval gate (used when a human
        has already approved the mission via /api/v2/missions/{id}/approve).
        """
        mid = mission_id or uuid.uuid4().hex[:16]
        now = time.time()

        ctx = MissionContext(
            mission_id=mid,
            goal=goal,
            mode=mode,
            status=MissionStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._missions[mid] = ctx

        # ── EventStream: create and register for WebSocket consumers ──
        try:
            from core.event_stream import EventStream, register_mission_stream
            from api.ws import register_stream
            _event_stream = EventStream(mid)
            register_mission_stream(mid, _event_stream)  # for agents/supervisor lookup
            register_stream(mid, _event_stream)           # for api/ws WebSocket endpoint
            ctx.metadata["event_stream"] = _event_stream
        except Exception as _es_err:
            log.debug("event_stream_register_skipped", err=str(_es_err)[:60])

        # ── Circuit breaker guard ─────────────────────────────────
        if self._circuit_breaker.is_open:
            ctx.error = "Circuit breaker open: too many consecutive delegate failures. Retry later."
            self._transition(ctx, MissionStatus.FAILED, reason="circuit_breaker_open")
            log.warning("mission.circuit_breaker_rejected",
                        mission_id=mid, cb_status=self._circuit_breaker.status())
            return ctx

        # ── Decision trace ────────────────────────────────────────
        from core.orchestration.decision_trace import DecisionTrace
        trace = DecisionTrace(mission_id=mid)
        needs_approval = False  # initialized early; may be set True by confidence_policy or kernel

        log.info("mission.created", mission_id=mid, mode=mode, goal=goal[:80])

        # ── Cognitive journal: mission created ────────────────────
        try:
            from core.cognitive_events.emitter import emit_mission_created
            emit_mission_created(mission_id=mid, goal=goal, mode=mode)
        except Exception:
            pass
        # ── Kernel event: mission created (dual emission) ─────────
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.created", mission_id=mid, goal=goal, mode=mode)
        except Exception:
            pass

        # ── Mission guards: iteration limit + budget (P10+P5) ────
        try:
            from core.mission_guards import get_guardian
            get_guardian().register_mission(mid, max_steps=50)
        except Exception as _mg_err:
            log.debug("mission_guard_init_skipped", err=str(_mg_err)[:60])

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

        # ── Cognitive pre-mission analysis ────────────────────────
        try:
            from core.cognitive_bridge import get_bridge
            _cognitive = get_bridge().pre_mission(goal, agent_id=mode)
            if _cognitive:
                ctx.metadata["cognitive"] = _cognitive
        except Exception as _cb_err:
            log.debug("cognitive_pre_mission_skipped", err=str(_cb_err)[:60])

        # ── Reasoning pre-pass (intelligence upgrade) ─────────
        # NOTE (2026-04-04): skip reasoning prepass for CHAT mode (short messages /
        # greetings). Calling reason() on "bonjour presente toi" produced
        # shape=patch (default small_fix fallback, English-only patterns) which
        # caused forge-builder to be selected and LensReviewer to score 3/10.
        # The task_mode is available in ctx.metadata["task_mode"] when set by
        # the missions router; we also guard on raw goal length as a safety net.
        _task_mode_str = ctx.metadata.get("task_mode", "")
        _is_chat_mode  = (_task_mode_str == "chat") or (len(goal.strip()) <= 30)
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

        try:
            # ── Phase 1: Classify ─────────────────────────────────
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
                            pass
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
            except Exception as _exc:
                log.warning("phase_failed", phase="context_assemble", err=str(_exc)[:100])
                rich_ctx = None

            # CREATED -> PLANNED
            self._transition(ctx, MissionStatus.PLANNED)
            trace.record("plan", "planned",
                         reason=f"approach={getattr(rich_ctx, 'suggested_approach', 'default')}")

            # PLANNED -> RUNNING
            self._transition(ctx, MissionStatus.RUNNING)

            # ── Phase 3: Supervised execution ─────────────────────
            risk = ctx.metadata.get("classification", {}).get("risk_level", "low")

            # ── Phase 3-kagents: Kernel Agent Registry lookup (BLOC 3 — R7) ──────
            # The kernel is the authority on which agents are available and healthy.
            # Query the KernelAgentRegistry to record candidates for this mission.
            # This closes the observability gap: ctx.metadata["kernel_agent_candidates"]
            # tracks which kernel-registered agents could handle this task.
            # Note: actual execution still uses delegate.run() (JarvisOrchestrator).
            # When a specialized agent is registered for the task_type, the kernel
            # will be able to dispatch directly without the delegate (future).
            try:
                from kernel.contracts.agent import get_agent_registry as _get_kreg
                _kreg = _get_kreg()
                _task_type_str = str(
                    ctx.metadata.get("classification", {}).get("task_type", "")
                    or ""
                )
                if hasattr(_task_type_str, "value"):
                    _task_type_str = _task_type_str.value
                # Look for agents matching mission task type AND general "mission_execution"
                _candidates = (
                    _kreg.list_by_capability(_task_type_str) if _task_type_str else []
                ) + _kreg.list_by_capability("mission_execution")
                # Deduplicate by agent_id
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
            # Inject reasoning pre-pass context (includes structured header for execution)
            if _reasoning_result:
                reasoning_injection = _reasoning_result.to_prompt_injection()
                _shape = _reasoning_result.output_shape.value if hasattr(_reasoning_result.output_shape, 'value') else str(_reasoning_result.output_shape)
                _cx = _reasoning_result.frame.complexity_class if hasattr(_reasoning_result, 'frame') else ""
                # Structured header: parseable by JarvisOrchestrator for smart routing
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
            # Gives the executor a structured execution plan from the kernel.
            # Only injected when plan has multiple steps (single-step = direct execution).
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
            # kernel.run_cognitive_cycle() retrieved lessons from similar past
            # missions (classify→plan→route→retrieve). Inject into enriched_goal
            # so the executor benefits from accumulated experience.
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
            # Build explicit state model (initial→target, preconditions,
            # expected effects, success criteria, failure modes) before exec.
            # Only for non-trivial missions. Fail-open. (Pass 42 — Phase 1)
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
                    # Inject state model into enriched_goal for agents
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
            pre_assess = None
            try:
                from core.orchestration.pre_execution import assess_before_execution
                pre_assess = assess_before_execution(
                    goal=goal,
                    classification=ctx.metadata.get("classification", {}),
                    prior_skills=rich_ctx.prior_skills if rich_ctx else [],
                    relevant_memories=rich_ctx.relevant_memories if rich_ctx else [],
                )
                ctx.metadata["pre_assessment"] = pre_assess.to_dict()
                trace.record("pre_check", pre_assess.strategy_suggestion or "proceed",
                             confidence=pre_assess.estimated_confidence,
                             reason=f"tools_ok={pre_assess.tool_health_ok} failures={len(pre_assess.similar_failures)}")
                if pre_assess.similar_failures:
                    enriched_goal += "\n\nWARNING: Similar tasks have failed before. Use caution."
            except Exception as _exc:
                log.warning("phase_failed", phase="pre_assessment", err=str(_exc)[:100])

            # ── Phase 2-P42: Confidence Policy ────────────────────────────
            # Confidence now CHANGES runtime behavior (not just reporting).
            # PolicyDecision may override needs_approval, inject prompt, or abort.
            # (Pass 42 — Phase 2)
            if not _is_chat_mode and pre_assess is not None:
                try:
                    from core.orchestration.confidence_policy import get_confidence_policy
                    _classification_dict = ctx.metadata.get("classification", {})
                    _cp_decision = get_confidence_policy().decide(
                        confidence=pre_assess.estimated_confidence,
                        risk_level=str(_classification_dict.get("risk_level", "low") or "low"),
                        task_type=str(_classification_dict.get("task_type", "") or ""),
                        goal=goal,
                        strategy_suggestion=pre_assess.strategy_suggestion or "",
                        has_prior_failures=bool(pre_assess.similar_failures),
                        is_destructive=(
                            str(_classification_dict.get("task_type", "")) in
                            ("deployment", "deletion", "database_write")
                        ),
                    )
                    ctx.metadata["confidence_policy"] = _cp_decision.to_dict()

                    # ── Apply behavioral changes ────────────────────────────
                    if _cp_decision.abort:
                        # Abort mission — confidence below safe threshold
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
                            confidence=pre_assess.estimated_confidence,
                            reason=_cp_decision.approval_reason,
                        )

                    if _cp_decision.prompt_additions:
                        for _pa in _cp_decision.prompt_additions:
                            enriched_goal += f"\n\n[POLICY] {_pa}"

                    trace.record(
                        "pre_check", f"confidence_policy:{_cp_decision.tier.value}",
                        tier=_cp_decision.tier.value,
                        confidence=pre_assess.estimated_confidence,
                        require_approval=_cp_decision.require_approval,
                        abort=_cp_decision.abort,
                    )
                except RuntimeError:
                    raise   # Re-raise abort
                except Exception as _cp_err:
                    log.warning("phase_failed", phase="confidence_policy",
                                err=str(_cp_err)[:100])

            # ── Pass 43: decompose_mission — restructure enriched_goal ─────────────
            # When confidence_policy decided the mission needs decomposition,
            # REPLACE the generic DECOMPOSE_MODE prompt with an explicit numbered
            # step list derived from MissionReasoningState.candidate_actions.
            # This gives agents a concrete plan to follow, not just an instruction.
            # Fail-open: if _mission_state is unavailable, original goal is unchanged.
            _cp_meta_decompose = ctx.metadata.get("confidence_policy", {})
            if _cp_meta_decompose.get("decompose_mission") and _mission_state is not None:
                try:
                    _actions = _mission_state.candidate_actions
                    if _actions:
                        _steps = "\n".join(
                            f"  Step {i + 1}: {a}"
                            for i, a in enumerate(_actions[:5])
                        )
                        # Restructure goal: explicit numbered plan + original goal appended
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

            from core.orchestration.execution_supervisor import supervise
            delegate = self.v2 if use_budget else self.jarvis
            # Wire the capability dispatcher onto the delegate instance so that
            # tool routing (native / plugin / MCP) is available during execution.
            # Both orchestrators expose no-**kwargs run() on JarvisOrchestrator, so
            # we attach it as an attribute rather than passing via call signature.
            if _cap_dispatcher is not None:
                try:
                    delegate.capability_dispatcher = _cap_dispatcher
                    log.debug("meta_orchestrator.capability_dispatcher_wired",
                              mission_id=mid, delegate=type(delegate).__name__)
                except Exception as _wex:
                    log.warning("meta_orchestrator.capability_dispatcher_wire_failed",
                                mission_id=mid, err=str(_wex)[:60])
            # Wire reasoning result via enriched_goal metadata (session-safe, no shared state)
            # The delegate reads it from session._reasoning_result, not self._reasoning_result
            # This avoids race conditions when multiple missions share the delegate instance.
            #
            # Preserve confidence_policy require_approval before classification reassignment.
            # Bug (Pass 42): line below overwrote needs_approval=True set by confidence_policy.
            # Fix: save flag, reassign from classification, then merge. (Pass 42 fix — P42b)
            _cp_approval_preserved = needs_approval  # True if confidence_policy raised it
            needs_approval = (
                False if force_approved
                else ctx.metadata.get("classification", {}).get("needs_approval", False)
            )
            if _cp_approval_preserved and not force_approved:
                needs_approval = True

            # ── Phase 3-kernel: Kernel policy check ───────────────────────────────
            # Run mission through kernel RiskEngine + KernelPolicyEngine.
            # If kernel requires approval, merge with existing needs_approval.
            # Fail-open: never blocks execution if kernel is unavailable.
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
                    # Kernel blocked the action — treat as needs_approval escalation
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

            # ── Phase 3-slayer: SecurityLayer business governance check (BLOC 4 — R3/R10) ──
            # The kernel policy check above covers kernel-level safety.
            # The SecurityLayer adds business governance: PolicyRuleSet first-match
            # (payment/deployment/self-improvement escalation) + immutable AuditTrail.
            # This is the NON-BYPASSABLE security gate for domain-sensitive missions.
            # task_type → action_type mapping: deployment/improvement → SecurityLayer rules.
            # Fail-open: never blocks mission if SecurityLayer is unavailable.
            try:
                _task_type_sl = str(
                    ctx.metadata.get("classification", {}).get("task_type", "") or ""
                )
                if hasattr(_task_type_sl, "value"):
                    _task_type_sl = _task_type_sl.value
                # Map kernel task_type → SecurityLayer action_type
                _SL_ACTION_MAP = {
                    "deployment":   "deployment",
                    "improvement":  "self_improvement",
                    "business":     "payment",  # business tasks may involve payments
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
                # BLOC D: security_layer failure must be visible — WARNING not DEBUG.
                # Store error in metadata so downstream audit can detect the gap.
                log.warning("phase_failed", phase="security_layer", err=str(_sl_err)[:80])
                ctx.metadata.setdefault("security_layer", {
                    "skipped": True,
                    "error": str(_sl_err)[:80],
                    "allowed": None,
                })

            # ── Phase 3-kmem: Kernel working memory write ─────────────────────────
            # Write mission context to kernel working memory so the kernel has a live
            # view of the running mission. Used by kernel event queries during execution.
            # Fail-open: never delays mission start.
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
            # The Phase 0c capability routing computed ctx.metadata["routed_provider"].
            # We inject it into LLMFactory._provider_override so it influences
            # provider selection for this mission's execution only (async-safe).
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
                    pass

            # ── Pass 43: use_safer_model — activate ContextVar before execution ──
            # When confidence_policy.use_safer_model=True, LLMFactory.get() will
            # prefer ollama over cloud providers for the duration of this mission.
            # Scoped to this coroutine via ContextVar token. Fail-open: never blocks.
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

            # Enforce a hard mission deadline — prevents infinite hangs.
            _mission_timeout = getattr(self.s, "mission_timeout_s", 600)
            try:
                outcome = await asyncio.wait_for(
                    supervise(
                        delegate.run,
                        mission_id=mid,
                        goal=enriched_goal,
                        mode=mode,
                        session_id=mid,
                        risk_level=risk,
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
                        pass
                # Pass 43: reset safer_model ContextVar
                if _safer_token is not None:
                    try:
                        from core.llm_factory import _safer_model_active as _sma
                        _sma.reset(_safer_token)
                    except Exception:
                        pass

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

            # ── Phase 1-P42 post-exec: update_observed ────────────────────────
            # Close the loop on MissionReasoningState: fill observed effects
            # and compute expected vs observed diff. Fail-open.
            if _mission_state is not None:
                try:
                    _mission_state.update_observed(
                        result=outcome.result if outcome.success else "",
                        error=outcome.error if hasattr(outcome, "error") else "",
                    )
                    ctx.metadata["mission_reasoning_state"] = _mission_state.to_dict()
                    trace.record(
                        "evaluate", "mission_state_observed",
                        satisfied=_mission_state.state_satisfied,
                        coverage=_mission_state.expected_vs_observed.get("coverage_ratio", 0),
                    )
                except Exception as _mso_err:
                    log.warning("phase_failed", phase="mission_state_observe",
                                err=str(_mso_err)[:80])

            if outcome.success:
                self._circuit_breaker.record_success()
                # RUNNING -> REVIEW
                self._transition(ctx, MissionStatus.REVIEW)
                ctx.result = outcome.result

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

                # REVIEW -> DONE
                self._transition(ctx, MissionStatus.DONE,
                                 result_len=len(ctx.result),
                                 retries=outcome.retries,
                                 duration_ms=outcome.duration_ms,
                                 confidence=result_confidence)
                # ── Skill Store: persist successful mission pattern (Voyager pattern) ──
                # Store if confidence >= threshold (default 0.70).
                # Fail-open: any exception is silently swallowed.
                try:
                    from core.skill_store import get_skill_store
                    _plan_to_store = ctx.metadata.get("context", {})
                    if not _plan_to_store:
                        _plan_to_store = {"steps": ["direct_execution"], "result_len": len(ctx.result)}
                    _mission_type_for_skill = str(
                        ctx.metadata.get("classification", {}).get("task_type", "general") or "general"
                    )
                    asyncio.ensure_future(get_skill_store().store(
                        mission_id=mid,
                        goal=goal,
                        plan=_plan_to_store,
                        confidence=result_confidence,
                        mission_type=_mission_type_for_skill,
                        tags=[mode, _mission_type_for_skill],
                    ))
                    log.info("skill_store_triggered", mission_id=mid, confidence=result_confidence)
                except Exception as _ss_err:
                    log.debug("skill_store_skip", err=str(_ss_err)[:80])
                # Journal: mission completed
                try:
                    from core.cognitive_events.emitter import emit_mission_completed
                    emit_mission_completed(
                        mission_id=mid, duration_ms=outcome.duration_ms,
                        confidence=result_confidence,
                    )
                except Exception:
                    pass
                # Metrics store counter (admin panel)
                try:
                    from core.metrics_store import emit_mission_completed as _ms_completed
                    _ms_completed("canonical", duration_ms=outcome.duration_ms)
                except Exception:
                    pass
                # Kernel event: mission completed (dual emission)
                try:
                    from kernel.convergence.event_bridge import emit_kernel_event
                    emit_kernel_event("mission.completed", mission_id=mid,
                                      duration_ms=outcome.duration_ms,
                                      confidence=result_confidence)
                except Exception:
                    pass
                # Kernel working memory: clear mission slot (it is done)
                try:
                    from kernel.runtime.boot import get_runtime as _get_kernel_rt
                    _get_kernel_rt().memory.clear_working(mission_id=mid)
                except Exception:
                    pass
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

                # ── Phase 3a: Output formatting ───────────────
                try:
                    from core.orchestration.output_formatter import format_output
                    task_type = ctx.metadata.get("classification", {}).get("task_type", "other")
                    ctx.result = format_output(ctx.result, task_type=task_type, goal=goal)
                except Exception as _exc:
                    log.debug("phase_failed", phase="output_format", err=str(_exc)[:100])

                # ── Phase 3b: Learning loop (kernel-authoritative — R5 / Pass 23) ──
                # R5: structured learning via kernel.learn() — JarvisKernel is the
                # single authority. Uses KernelScore fields (verdict, confidence,
                # weaknesses, improvement_suggestion) from kernel.evaluator (Pass 8).
                # Falls back to core extract_lesson if kernel unavailable.
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

                # ── Phase 4: Record skill + refine prior ─────────
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

                # ── Phase 5: Store to memory ──────────────────────
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

            elif outcome.error_class == "awaiting_approval":
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

            else:
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
                    pass
                # Metrics store counter (admin panel)
                try:
                    from core.metrics_store import emit_mission_failed as _ms_failed
                    _ms_failed("canonical", reason=outcome.error_class)
                except Exception:
                    pass
                # Kernel event: mission failed (dual emission)
                try:
                    from kernel.convergence.event_bridge import emit_kernel_event
                    emit_kernel_event("mission.failed", mission_id=mid,
                                      error=outcome.error[:200],
                                      error_class=outcome.error_class)
                except Exception:
                    pass

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
        try:
            from core.mission_guards import get_guardian
            get_guardian().release_mission(mid)
        except Exception:
            pass

        # ── Post-mission: record routing outcome for learning ─────
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

        # ── Deregister EventStream (mission complete or failed) ────────
        try:
            from api.ws import deregister_stream
            from core.event_stream import deregister_mission_stream
            deregister_stream(mid)
            deregister_mission_stream(mid)
        except Exception:
            pass

        return ctx

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
            pass

        # Journal event
        try:
            from core.cognitive_events.emitter import emit_approval_resolved
            emit_approval_resolved(mission_id, granted=granted,
                                    item_id=ctx.metadata.get("approval_item_id", ""))
        except Exception:
            pass

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
