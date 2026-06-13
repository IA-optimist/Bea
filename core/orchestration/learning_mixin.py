"""
LearningMixin — phase « apprentissage » du cycle de vie mission.

Extrait de core/meta_orchestrator.py (PR 1 du plan
docs/refactor/meta_orchestrator_split.md). Déplacement strict : aucune
logique modifiée. Les méthodes n'utilisent aucun attribut d'instance,
uniquement leurs paramètres — le mixin est donc sans état.

Hôte attendu : MetaOrchestrator (core/meta_orchestrator.py).
"""
from __future__ import annotations

import structlog

from core.state import MissionStatus

log = structlog.get_logger(__name__)


class LearningMixin:
    """Post-mission learning, mémoires et skills (aucun état propre)."""

    def _post_mission_learning(self, mid: str, goal: str, mode: str, ctx) -> None:
        """Post-mission cognitive learning + guardian cleanup."""
        # ── Episodic + procedural memory ──────────────────────────────────────
        try:
            from core.memory.episodic_store import store_episode
            from core.memory.procedural_store import record_outcome
            _success = ctx.status.value == "DONE" if hasattr(ctx.status, "value") else bool(ctx.status == "DONE")
            _domain = str(
                ctx.metadata.get("classification", {}).get("task_type", "general") or "general"
            )
            _agents = [mode] if mode else []
            _duration = int((ctx.updated_at - ctx.created_at) * 1000) if (
                hasattr(ctx, "updated_at") and hasattr(ctx, "created_at")
            ) else 0
            store_episode(
                mission_id=mid,
                goal=goal,
                agents=_agents,
                outcome_summary=(ctx.result or "")[:600],
                success=_success,
                domain=_domain,
                duration_ms=_duration,
            )
            record_outcome(domain=_domain, agent=mode or "unknown", success=_success)
        except Exception as _ep_err:
            import structlog as _sl
            _sl.get_logger(__name__).debug("episodic_store_skip", err=str(_ep_err)[:80])

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
                agent_cap = f"cap-{mode}" if mode.startswith("bea-") else None
                caps_used = [c for c in [agent_cap] if c]
                if caps_used:
                    bridge.capability_graph.record_mission_usage(mid, caps_used)
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

        # Guardian cleanup
        try:
            from core.mission_guards import get_guardian
            get_guardian().release_mission(mid)
        except Exception as _exc:
            log.warning("swallowed_exception", action="mission_guardian_release", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
            log.debug("swallowed_exception", exc_info=True)

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
            from core.orchestration.creative_engine import ArtificialCuriosity, BeaLLMClient
            _ac = ArtificialCuriosity(llm_client=BeaLLMClient(role="fast"))
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
