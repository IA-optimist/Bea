"""Supervised execution runner for missions.

Extracted from ExecutionMixin._execute_supervised — execution phase.
Handles: chat fast-path (destructive refusal + BeaLLMClient), CognitionOrchestrator
wrapper, supervise() fallback, and ContextVar cleanup on exit.

Returns the execution outcome (or None for chat fast-path completions).
"""
from __future__ import annotations

import asyncio
import time
import structlog

from typing import Any, Callable

from core.state import MissionStatus

log = structlog.get_logger(__name__)


async def run_execution(
    goal: str,
    mid: str,
    mode: str,
    ctx,
    trace,
    enriched_goal: str,
    needs_approval: bool,
    force_approved: bool,
    risk: str,
    delegate: Any,
    provider_token: Any,
    safer_token: Any,
    cap_dispatcher: Any,
    is_chat_mode: bool,
    pre_assess_local: Any,
    mission_timeout_s: int,
    callback: Any,
    transition_fn: Callable,
    cleanup_fn: Callable,
) -> Any:
    """Execute the mission via fast-path or supervised crew.

    Returns:
        outcome object from supervise(), or None if fast-path completed the
        mission directly (ctx already in DONE state on return).
    """
    from core.meta_chat_fast_path import (
        CHAT_DESTRUCTIVE_REFUSAL,
        build_fast_path_prompt,
        should_skip_fast_path,
    )
    from core.orchestration.execution_supervisor import supervise

    _fp_skip_risk = should_skip_fast_path(
        goal,
        needs_approval=needs_approval,
        risk_level=ctx.metadata.get("classification", {}).get("risk_level", "low"),
    )

    # ── Immediate refusal for destructive commands in chat mode ───────────────
    if is_chat_mode and _fp_skip_risk and not needs_approval:
        ctx.result = CHAT_DESTRUCTIVE_REFUSAL
        ctx.status = MissionStatus.DONE
        ctx.completed_at = time.time()
        log.info("chat_destructive_refused", mission_id=mid, goal=goal[:60])
        try:
            from core.mission_persistence import get_mission_persistence
            get_mission_persistence().persist(ctx)
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
        return

    # ── Chat fast-path: BeaLLMClient (no crew) ────────────────────────────────
    if is_chat_mode and not _fp_skip_risk:
        try:
            from core.orchestration.creative_engine import BeaLLMClient
            _fp_llm = BeaLLMClient(role="fast")
            _fp_ctx = str(ctx.metadata.get("context", "") or "")
            _fp_mem = ""
            try:
                from core.orchestration.memory_system import UnifiedMemory
                _um_fp = UnifiedMemory()
                _mems = await asyncio.wait_for(
                    _um_fp.recall(goal, top_k=3), timeout=3
                )
                if _mems:
                    _fp_mem = "\n".join(
                        f"- {m['content'][:150]}"
                        for m in _mems
                        if m.get("content")
                    )
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
            _fp_prompt = build_fast_path_prompt(goal, memory=_fp_mem,
                                                context=_fp_ctx)
            _fp_text = await asyncio.wait_for(
                _fp_llm.complete(_fp_prompt, max_tokens=2000), timeout=45
            )
            if not _fp_text or len(str(_fp_text).strip()) < 3:
                raise ValueError("empty_response")
            ctx.result = str(_fp_text)
            ctx.status = MissionStatus.DONE
            ctx.completed_at = time.time()
            log.info("chat_fast_path_ok", mission_id=mid,
                     chars=len(str(_fp_text)))
            # Store fast-path exchange in knowledge memory
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
                log.debug("swallowed_exception", exc_info=True)
            # Persist so UI sees consistent status
            try:
                from core.mission_persistence import get_mission_persistence
                get_mission_persistence().persist(ctx)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
            # Extract and store lesson
            try:
                from core.orchestration.learning_loop import extract_lesson, store_lesson
                _lesson = extract_lesson(
                    mission_id=mid,
                    goal=goal[:200],
                    result=str(ctx.result)[:300],
                    reflection_verdict=ctx.metadata.get("reflection_verdict",
                                                        "accept"),
                    reflection_confidence=float(
                        ctx.metadata.get("confidence_score", 0.8)
                    ),
                    error_class=ctx.metadata.get("error_class", ""),
                    retries=ctx.metadata.get("retries", 0),
                )
                if _lesson:
                    store_lesson(_lesson)
                    log.info("learning_loop.lesson_stored", mission_id=mid,
                             confidence=_lesson.confidence)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
            # Sync mission_system store
            try:
                from core.mission_system import get_mission_system
                _ms = get_mission_system()
                _ms_rec = _ms.get_mission(mid)
                if _ms_rec is not None:
                    _ms_rec.status = "DONE"
                    _ms_rec.final_output = ctx.result
                    _ms._save_mission(_ms_rec)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
            try:
                cleanup_fn(mid)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
            return
        except Exception as _fe:
            log.warning("chat_fast_path_fail", err=str(_fe)[:120])
            # Fall through to full crew

    # ── Phase 3b: Inject planned routing metadata for session_meta_bus ──────────
    # Propagate provider_id, mission_type, and fallback_used from ctx.metadata so
    # bea_executor can inject them into session.metadata even when no LLM call fires.
    try:
        from core.executor.session_meta_bus import reset as _bus_reset, set_initial_meta
        _bus_reset()
        _routed = ctx.metadata.get("routed_provider") or {}
        _caps = ctx.metadata.get("capability_routing") or []
        _fallback_planned = any(
            r.get("fallback_used") for r in _caps if isinstance(r, dict)
        )
        _task_type = str(
            (ctx.metadata.get("classification") or {}).get("task_type", "") or ""
        )
        _agents_hint = [
            a.get("agent") for a in (ctx.metadata.get("agents_plan") or [])
            if isinstance(a, dict) and a.get("agent")
        ]
        set_initial_meta({
            "provider_used":  _routed.get("provider_id") if isinstance(_routed, dict) else None,
            "mission_type":   _task_type or mode,
            "fallback_used":  _fallback_planned,
            "agents_used":    _agents_hint or None,
        })
        log.debug(
            "session_meta_bus_initialized",
            provider=_routed.get("provider_id") if isinstance(_routed, dict) else None,
            mission_type=_task_type or mode,
            fallback_planned=_fallback_planned,
        )
    except Exception as _bus_err:
        log.debug("session_meta_bus_init_failed", err=str(_bus_err)[:80])

    # ── Phase 4: AGI Cognition wrapper + supervise() ──────────────────────────
    _base_timeout = mission_timeout_s
    _LONG_MODE_TIMEOUT = 600
    _mission_timeout = (
        _LONG_MODE_TIMEOUT
        if mode in ("business", "code", "auto", "plan", "research", "night", "improve")
        else _base_timeout
    )

    _use_cognition = (
        not is_chat_mode
        and pre_assess_local is not None
        and pre_assess_local.estimated_confidence < 0.9
        and len(goal) > 50
    )

    outcome = None
    if _use_cognition:
        log.info("cognition.activating", mission_id=mid,
                 conf=pre_assess_local.estimated_confidence)
        try:
            from core.cognition.orchestrator import CognitionOrchestrator
            _cog = CognitionOrchestrator(llm_client=delegate.llm)
            _payload = {
                "mission_id":        mid,
                "goal":              enriched_goal,
                "mode":              mode,
                "session_id":        mid,
                "risk_level":        risk,
                "requires_approval": needs_approval,
                "skip_approval":     force_approved,
                "callback":          callback,
                "classification":    ctx.metadata.get("classification", {}),
            }
            outcome = await _cog.execute_mission_with_delegate_cognition(
                delegate=delegate,
                supervise_fn=supervise,
                mission_payload=_payload,
                timeout=_mission_timeout,
            )
            trace.record("cognition", "success",
                         conf=pre_assess_local.estimated_confidence)
        except Exception as _cog_err:
            log.warning("cognition.failed", mission_id=mid,
                        err=str(_cog_err)[:100])
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
                    risk_level=(
                        "high"
                        if needs_approval and not force_approved
                        else risk
                    ),
                    requires_approval=needs_approval,
                    skip_approval=force_approved,
                    callback=callback,
                ),
                timeout=_mission_timeout,
            )
        finally:
            # Always reset ContextVars after execution
            if provider_token is not None:
                try:
                    from core.llm_factory import _provider_override as _pov
                    _pov.reset(provider_token)
                except Exception as _exc:
                    log.warning("swallowed_exception",
                                action="provider_override_reset",
                                exc_type=type(_exc).__name__,
                                exc_msg=str(_exc)[:200])
            if safer_token is not None:
                try:
                    from core.llm_factory import _safer_model_active as _sma
                    _sma.reset(safer_token)
                except Exception as _exc:
                    log.warning("swallowed_exception",
                                action="safer_model_reset",
                                exc_type=type(_exc).__name__,
                                exc_msg=str(_exc)[:200])

    return outcome
