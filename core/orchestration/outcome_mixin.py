"""Outcome mixin extracted mechanically from core.meta_orchestrator."""
from __future__ import annotations

import time

import structlog

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
