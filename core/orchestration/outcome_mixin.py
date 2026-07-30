"""Outcome mixin extracted mechanically from core.meta_orchestrator."""
from __future__ import annotations

import asyncio
import time

import structlog

from core.orchestration.critic_policy import (
    CriticAction,
    CriticEvaluationError,
    CriticPipelineError,
    CriticQualityRejected,
    CriticResourceBlocked,
    CriticRerunFailed,
    decide_critic_action,
)
from core.orchestration.mission_text_utils import strip_execution_outcome as _strip_execution_outcome
from core.state import MissionStatus

log = structlog.get_logger(__name__)


class OutcomeMixin:
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
        delegate = ctx.metadata.get("_exec_delegate", self.bea)
        _mission_timeout = ctx.metadata.get("_exec_mission_timeout", 600)
        needs_approval = ctx.metadata.get("_exec_needs_approval", False)

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
            log.error("kernel_evaluation_failed", err=str(_keval_err)[:100])
            result_confidence = 0.0
            ctx.error = f"critic_evaluation_failed: {str(_keval_err)[:160]}"
            ctx.metadata["critic_terminal"] = {
                "status": "failed",
                "reason": "critic_evaluation_failed",
            }
            self._transition(
                ctx,
                MissionStatus.FAILED,
                reason="critic_evaluation_failed",
            )
            trace.record("evaluate", "critic_failed", reason="evaluation_error")
            return result_confidence

        # ── Kernel → canonical critic gate (one bounded attempt) ──
        try:
            result_confidence = await self._handle_kernel_retry(
                ctx, mid, goal, mode, trace, outcome, _reasoning_result,
                enriched_goal, risk, needs_approval, force_approved, callback,
                delegate, _mission_timeout, result_confidence, _shape_val,
                kernel_score=_kernel_score,
            )
        except CriticPipelineError as critic_error:
            ctx.error = str(critic_error)[:300]
            ctx.metadata["critic_terminal"] = {
                "status": "failed",
                "reason": type(critic_error).__name__,
            }
            self._transition(
                ctx,
                MissionStatus.FAILED,
                reason=type(critic_error).__name__,
            )
            trace.record(
                "evaluate",
                "critic_failed",
                reason=type(critic_error).__name__,
            )
            return result_confidence

        # REVIEW -> DONE
        final_score = ctx.metadata.get("kernel_score", {}).get("score")
        ctx.metadata["critic_terminal"] = {
            "status": "passed",
            "score": final_score,
        }
        self._circuit_breaker.record_success()
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
                _paths = _exp.save(ctx.result, _client_name or 'BeaMax', goal, mid)
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
        kernel_score,
    ) -> float:
        """Apply one mission-scoped, ResourceGuard-bounded critic decision."""
        from core.resource_guard import ResourceSnapshot, SystemStatus, get_resource_guard
        from core.wellbeing import FunctionalWellbeing

        try:
            resource_guard = get_resource_guard(self.s)
            resource_snapshot = resource_guard.get_status()
        except Exception as resource_error:
            log.warning(
                "critic_resource_status_failed",
                mission_id=mid,
                err=str(resource_error)[:80],
            )
            resource_guard = None
            resource_snapshot = ResourceSnapshot(status=SystemStatus.UNKNOWN)

        wellbeing = FunctionalWellbeing().observe_resource_snapshot(
            resource_snapshot
        )
        ctx.metadata["functional_wellbeing"] = wellbeing.to_dict()

        already_reran = bool(
            ctx.metadata.get("_canonical_critic_rerun_done")
            or mid.endswith("-critic-rerun")
            or mid.endswith("-retry")
        )
        decision = decide_critic_action(
            kernel_score,
            resource_snapshot.status,
            forced_enabled=bool(
                getattr(self.s, "critic_force_marginal_rerun", False)
            ),
            already_reran=already_reran,
            execution_retries=outcome.retries,
            goal_length=len(goal.strip()),
        )
        ctx.metadata["critic_decision"] = decision.to_dict()
        trace.record(
            "evaluate",
            "critic_decision",
            action=decision.action.value,
            score=decision.score,
            forced=decision.forced,
            resource_status=decision.resource_status,
        )

        if decision.action is CriticAction.ERROR:
            raise CriticEvaluationError(decision.reason)
        if decision.action is CriticAction.BLOCKED:
            if decision.reason == "resource_guard_unavailable":
                raise CriticResourceBlocked(decision.reason)
            raise CriticQualityRejected(decision.reason)
        if decision.action is CriticAction.ACCEPT:
            return result_confidence

        if resource_guard is None:
            if decision.forced:
                return result_confidence
            raise CriticResourceBlocked("resource_guard_unavailable")

        try:
            current_status = resource_guard.get_status().status
        except Exception as resource_error:
            log.warning(
                "critic_resource_recheck_failed",
                mission_id=mid,
                err=str(resource_error)[:80],
            )
            current_status = SystemStatus.UNKNOWN
        allowed_statuses = (
            {SystemStatus.NORMAL}
            if decision.forced
            else {SystemStatus.NORMAL, SystemStatus.SOFT_WARN}
        )
        if current_status not in allowed_statuses:
            if decision.forced:
                ctx.metadata["critic_rerun_skipped"] = "resource_status_changed"
                return result_confidence
            raise CriticResourceBlocked("resource_status_changed")

        weaknesses = "; ".join(
            str(weakness)[:160] for weakness in kernel_score.weaknesses[:3]
        )
        suggestion = str(kernel_score.improvement_suggestion)[:300]
        retry_goal = (
            f"{enriched_goal}\n\n"
            "---\nCANONICAL CRITIC REVIEW:\n"
            f"Weaknesses: {weaknesses or 'quality below canonical threshold'}\n"
            f"Improvement needed: {suggestion}\n"
            "Produce a more specific, complete, and actionable response."
        )

        slot_name = "canonical-critic-rerun"
        if not resource_guard.acquire_slot(slot_name, timeout=0.0):
            if decision.forced:
                ctx.metadata["critic_rerun_skipped"] = "resource_slot_unavailable"
                return result_confidence
            raise CriticResourceBlocked("resource_slot_unavailable")

        ctx.metadata["_canonical_critic_rerun_done"] = True

        from core.orchestration.execution_supervisor import supervise

        retry_outcome = None
        retry_error: Exception | None = None
        try:
            self._transition(
                ctx,
                MissionStatus.RUNNING,
                reason="canonical_critic_rerun",
            )
            try:
                retry_outcome = await asyncio.wait_for(
                    supervise(
                        delegate.run,
                        mission_id=f"{mid}-critic-rerun",
                        goal=retry_goal,
                        mode=mode,
                        session_id=f"{mid}-critic-rerun",
                        risk_level=risk,
                        requires_approval=needs_approval,
                        skip_approval=force_approved,
                        callback=callback,
                    ),
                    timeout=_mission_timeout,
                )
            except Exception as exc:
                retry_error = exc
            finally:
                self._transition(
                    ctx,
                    MissionStatus.REVIEW,
                    reason="post_canonical_critic_rerun",
                )
        finally:
            resource_guard.release_slot(slot_name)

        if retry_error is not None:
            log.warning(
                "canonical_critic_rerun_failed",
                mission_id=mid,
                forced=decision.forced,
                err=str(retry_error)[:80],
            )
            if decision.forced:
                return result_confidence
            raise CriticRerunFailed("canonical_critic_rerun_failed") from retry_error
        if (
            retry_outcome is None
            or not retry_outcome.success
            or not retry_outcome.result
        ):
            if decision.forced:
                return result_confidence
            raise CriticRerunFailed("canonical_critic_rerun_returned_no_result")

        from kernel.evaluation.scorer import get_evaluator

        task_type = (
            ctx.metadata.get("classification", {}).get("task_type", "") or ""
        )
        if hasattr(task_type, "value"):
            task_type = task_type.value
        try:
            retry_score = get_evaluator().evaluate(
                goal=goal,
                result=retry_outcome.result,
                task_type=str(task_type),
                mission_id=mid,
                duration_ms=retry_outcome.duration_ms,
                retries=retry_outcome.retries,
                output_shape=_shape_val,
                reasoning_frame=(
                    _reasoning_result.frame if _reasoning_result else None
                ),
            )
        except Exception as evaluation_error:
            if decision.forced:
                log.warning(
                    "forced_critic_rerun_evaluation_failed",
                    mission_id=mid,
                    err=str(evaluation_error)[:80],
                )
                return result_confidence
            raise CriticEvaluationError(
                "critic_rerun_evaluation_failed"
            ) from evaluation_error

        retry_decision = decide_critic_action(
            retry_score,
            resource_snapshot.status,
            forced_enabled=False,
            already_reran=True,
            execution_retries=0,
            goal_length=len(goal.strip()),
        )
        if retry_decision.action is CriticAction.ERROR:
            if decision.forced:
                return result_confidence
            raise CriticEvaluationError(retry_decision.reason)

        accepted = retry_score.score > kernel_score.score
        if accepted:
            ctx.result = retry_outcome.result
            ctx.metadata["kernel_score"] = retry_score.to_dict()
            if retry_score.critique_dict:
                ctx.metadata["critique"] = retry_score.critique_dict
            if retry_score.reflection_dict:
                ctx.metadata["reflection"] = retry_score.reflection_dict
            result_confidence = retry_score.confidence

        ctx.metadata["critic_rerun"] = {
            "before": round(kernel_score.score, 3),
            "after": round(retry_score.score, 3),
            "delta": round(retry_score.score - kernel_score.score, 3),
            "forced": decision.forced,
            "accepted": accepted,
        }
        log.info(
            "canonical_critic_rerun_complete",
            mission_id=mid,
            before=kernel_score.score,
            after=retry_score.score,
            forced=decision.forced,
            accepted=accepted,
        )

        if (
            decision.action is CriticAction.NATURAL_RERUN
            and retry_decision.action is not CriticAction.ACCEPT
        ):
            raise CriticQualityRejected("critic_quality_below_threshold_after_rerun")
        return result_confidence

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
        except Exception as _exc:
            log.warning("swallowed_exception", action="mission_outcome_emit_completed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Metrics store counter (admin panel)
        try:
            from core.metrics_store import emit_mission_completed as _ms_completed
            _ms_completed("canonical", duration_ms=outcome.duration_ms)
        except Exception as _exc:
            log.warning("swallowed_exception", action="metrics_store_emit_completed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Kernel event: mission completed (dual emission)
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.completed", mission_id=mid,
                              duration_ms=outcome.duration_ms,
                              confidence=result_confidence)
        except Exception as _exc:
            log.warning("swallowed_exception", action="cognitive_event_emit_completed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Kernel working memory: clear mission slot (it is done)
        try:
            from kernel.runtime.boot import get_runtime as _get_kernel_rt
            _get_kernel_rt().memory.clear_working(mission_id=mid)
        except Exception as _exc:
            log.warning("swallowed_exception", action="kernel_working_memory_clear", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
        except Exception as _exc:
            log.warning("swallowed_exception", action="mission_outcome_emit_failed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Metrics store counter (admin panel)
        try:
            from core.metrics_store import emit_mission_failed as _ms_failed
            _ms_failed("canonical", reason=outcome.error_class)
        except Exception as _exc:
            log.warning("swallowed_exception", action="metrics_store_emit_failed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Kernel event: mission failed (dual emission)
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("mission.failed", mission_id=mid,
                              error=outcome.error[:200],
                              error_class=outcome.error_class)
        except Exception as _exc:
            log.warning("swallowed_exception", action="cognitive_event_emit_failed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
