"""Routing mixin extracted mechanically from core.meta_orchestrator."""
from __future__ import annotations


import structlog

from core.meta_orchestrator_state import MissionContext

log = structlog.get_logger(__name__)


class RoutingMixin:
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
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="subplan_metrics_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
                    log.debug("swallowed_exception", exc_info=True)

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
