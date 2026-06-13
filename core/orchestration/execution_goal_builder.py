"""Goal enrichment for supervised mission execution.

Extracted from ExecutionMixin._execute_supervised — goal-enrichment phase only.
Handles: reasoning injection, kernel plan/lessons, skill context, mission reasoning
state, memory lessons, pre-execution assessment, confidence policy, and decompose.

Returns (enriched_goal, pre_assess_local, mission_state, confidence_needs_approval).
"""
from __future__ import annotations

import asyncio
import structlog

from typing import Any

log = structlog.get_logger(__name__)


async def build_enriched_goal(
    goal: str,
    mid: str,
    ctx,
    trace,
    rich_ctx,
    _reasoning_result: Any,
    _kernel_plan: Any,
    _kernel_context: dict,
    _skill_context: str,
    _mission_lessons: Any,
    _is_chat_mode: bool,
    pre_assess: Any,
) -> tuple[str, Any, Any, bool]:
    """Build enriched goal with all planning and memory context injected.

    Returns:
        (enriched_goal, pre_assess_local, mission_state, confidence_needs_approval)
        confidence_needs_approval is True if the confidence policy escalated approval.
    """
    enriched_goal = goal

    # ── Reasoning pre-pass injection ───────────────────────────────────────────
    if _reasoning_result:
        reasoning_injection = _reasoning_result.to_prompt_injection()
        _shape = (
            _reasoning_result.output_shape.value
            if hasattr(_reasoning_result.output_shape, "value")
            else str(_reasoning_result.output_shape)
        )
        _cx = (
            _reasoning_result.frame.complexity_class
            if hasattr(_reasoning_result, "frame")
            else ""
        )
        enriched_goal = (
            goal
            + f"\n\n[ROUTING:shape={_shape},complexity={_cx}]"
            + "\n---\nReasoning:\n" + reasoning_injection
        )

    # ── Prior experience context from rich_ctx ─────────────────────────────────
    if rich_ctx:
        planning_ctx = rich_ctx.planning_prompt_context()
        if planning_ctx:
            enriched_goal += "\n\n---\nContext from prior experience:\n" + planning_ctx
            trace.record("plan", "context_injected",
                         reason=f"{len(planning_ctx)} chars of prior context")

    # ── Kernel plan steps ──────────────────────────────────────────────────────
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

    # ── Kernel memory lessons ──────────────────────────────────────────────────
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

    # ── Skill context (Voyager pattern) ───────────────────────────────────────
    if _skill_context:
        enriched_goal += "\n\n---\nProven strategies from past missions:\n" + _skill_context
        trace.record("retrieve", "skill_context_injected", chars=len(_skill_context))

    # ── Mission Reasoning State ────────────────────────────────────────────────
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

    # ── Phase 3 memory lessons ─────────────────────────────────────────────────
    if _mission_lessons is not None and _mission_lessons.has_lessons:
        _lessons_injection = _mission_lessons.to_prompt_injection()
        if _lessons_injection:
            enriched_goal += "\n\n---\n" + _lessons_injection
            trace.record("retrieve", "mission_lessons_injected",
                         avoid=len(_mission_lessons.avoid),
                         reuse=len(_mission_lessons.reuse))

    # ── Pre-execution assessment ───────────────────────────────────────────────
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
            trace.record("pre_check",
                         pre_assess_local.strategy_suggestion or "proceed",
                         confidence=pre_assess_local.estimated_confidence,
                         reason=(
                             f"tools_ok={pre_assess_local.tool_health_ok} "
                             f"failures={len(pre_assess_local.similar_failures)}"
                         ))
            if pre_assess_local.similar_failures:
                enriched_goal += "\n\nWARNING: Similar tasks have failed before. Use caution."
        except Exception as _exc:
            log.warning("phase_failed", phase="pre_assessment", err=str(_exc)[:100])

    # ── Confidence Policy ──────────────────────────────────────────────────────
    confidence_needs_approval = False
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

            if _cp_decision.abort:
                raise RuntimeError(
                    f"Mission aborted by confidence policy: {_cp_decision.abort_reason}"
                )
            if _cp_decision.require_approval:
                confidence_needs_approval = True
                log.info("confidence_policy_requires_approval",
                         mission_id=mid,
                         tier=_cp_decision.tier.value,
                         confidence=pre_assess_local.estimated_confidence,
                         reason=_cp_decision.approval_reason)
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
            raise
        except Exception as _cp_err:
            log.warning("phase_failed", phase="confidence_policy",
                        err=str(_cp_err)[:100])

    # ── Mission decomposition ──────────────────────────────────────────────────
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
                trace.record("plan", "mission_decomposed",
                             steps=len(_actions[:5]),
                             reason="confidence_policy:decompose_mission")
                log.info("mission_goal_decomposed",
                         mission_id=mid,
                         steps=len(_actions[:5]),
                         first_step=_actions[0][:60])
        except Exception as _de:
            log.debug("decompose_mission_failed", err=str(_de)[:60])

    return enriched_goal, pre_assess_local, _mission_state, confidence_needs_approval
