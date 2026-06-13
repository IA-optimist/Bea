"""Execution mixin — coordinator for supervised mission execution.

Refactored from the original 844-line monolith into 5 focused modules:
  execution_goal_builder.py     — goal enrichment (reasoning, plans, lessons)
  execution_memory_injector.py  — runtime memory context injection
  execution_policy_gate.py      — policy gates + delegate/ContextVar setup
  execution_supervised_runner.py — chat fast-path + cognition + supervise()
  execution_result_validator.py — post-execution ctx.metadata finalization

This module keeps only:
  - 3 helper methods (reasoning prepass, context assemble, creative mode)
  - _execute_supervised: a thin coordinator that sequences the sub-modules
"""
from __future__ import annotations

import asyncio
import time
import structlog

from core.state import MissionStatus

log = structlog.get_logger(__name__)


class ExecutionMixin:
    def _execute_reasoning_prepass(
        self, goal: str, mid: str, ctx, trace
    ) -> tuple:
        """Execute reasoning pre-pass for intelligence upgrade.
        Returns (_is_chat_mode, _reasoning_result).
        """
        _task_mode_str = ctx.metadata.get("task_mode", "")
        _CHAT_KEYWORDS = (
            "salut", "bonjour", "hello", "hi", "hey", "présente", "qui es",
            "recommence", "répète", "repete", "présente-toi", "aide moi",
            "merci", "ok cool", "super", "parfait",
        )
        _TASK_KEYWORDS = (
            "analyse", "analyz", "compare", "comparison", "architecture",
            "implement", "code", "develop", "build", "create", "list all",
            "detailed", "complet", "rapport", "report", "research", "explain",
            "diagram", "roadmap", "strategy", "plan", "design", "review",
            "audit", "optimize", "migrate", "database", "deploy", "docker",
            "api", "test", "debug", "fix", "refactor", "swagger", "openapi",
            "benchmark", "security", "vulnerability",
        )
        _goal_lower = goal.strip().lower()
        _is_conversational = any(kw in _goal_lower for kw in _CHAT_KEYWORDS)
        _is_complex_task = (
            any(kw in _goal_lower for kw in _TASK_KEYWORDS)
            or len(goal.strip()) > 120
        )
        _is_chat_mode = _task_mode_str == "chat" or (
            not _is_complex_task
            and (_is_conversational or len(goal.strip()) <= 60)
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
                trace.record(
                    "reason", _reasoning_result.frame.complexity_class,
                    bottleneck=_reasoning_result.frame.likely_bottleneck[:60],
                    shape=_reasoning_result.output_shape.value,
                    ms=_reasoning_result.reasoning_ms,
                )
                log.info("reasoning_prepass_complete",
                         mission_id=mid,
                         complexity=_reasoning_result.frame.complexity_class,
                         shape=_reasoning_result.output_shape.value)
            except Exception as _rp_err:
                log.debug("reasoning_prepass_skipped", err=str(_rp_err)[:60])

        return _is_chat_mode, _reasoning_result

    def _assemble_mission_context(self, mid: str, goal: str, ctx, trace):
        """Phase 2: Assemble context using context_assembler.
        Updates ctx.metadata with context, prior_skills, memories.
        Returns rich_ctx or None on failure.
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
            log.warning("phase_failed", phase="context_assemble",
                        err=str(_exc)[:100])
            return None

    async def _execute_creative_mode(self, goal: str, mode: str, mid: str,
                                      ctx, trace):
        """Creative Mode dispatcher (early return pathway).
        Returns ctx if creative mode succeeds, None otherwise.
        """
        if mode != "creative":
            return None
        try:
            from core.orchestration.creative_engine import (
                BeaCreativePipeline, BeaLLMClient, BeaMissionStore,
            )
            _creative = BeaCreativePipeline(
                llm_client=BeaLLMClient(role="fast"),
                mission_store=BeaMissionStore(),
            )
            _creative_result = await _creative.run(goal, n_solutions=3)
            if _creative_result.get("best"):
                ctx.result = _creative_result["best"]
                ctx.metadata["creative_solutions"] = len(
                    _creative_result.get("all_solutions", [])
                )
                self._transition(ctx, MissionStatus.REVIEW)
                self._transition(ctx, MissionStatus.DONE,
                                 result_len=len(ctx.result), retries=0,
                                 duration_ms=0, confidence=0.75)
                log.info("creative_mode.done", mission_id=mid,
                         n_solutions=ctx.metadata["creative_solutions"])
                return ctx
        except Exception as _creative_err:
            log.warning("creative_mode.failed", err=str(_creative_err)[:80])
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
        _skill_context: str = "",
    ):
        """Thin coordinator: sequence the execution sub-modules.

        Extractions:
          - execution_goal_builder    → build_enriched_goal()
          - execution_memory_injector → inject_memory_context()
          - execution_policy_gate     → setup_policy_and_delegate()
          - execution_supervised_runner → run_execution()
          - execution_result_validator  → finalize_execution_metadata()
        """
        from core.orchestration.execution_goal_builder import build_enriched_goal
        from core.orchestration.execution_memory_injector import inject_memory_context
        from core.orchestration.execution_policy_gate import setup_policy_and_delegate
        from core.orchestration.execution_supervised_runner import run_execution
        from core.orchestration.execution_result_validator import finalize_execution_metadata

        risk = classification.get("risk_level", "low")

        # ── Kernel Agent Registry lookup ───────────────────────────────────────
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
            log.debug("phase_failed", phase="kernel_agent_lookup",
                      err=str(_ka_err)[:80])

        _cap_dispatcher = self.capability_dispatcher
        if _cap_dispatcher is None:
            log.warning("meta_orchestrator.capability_dispatcher_unavailable",
                        mission_id=mid)

        # ── Phase 1: Build enriched goal ───────────────────────────────────────
        enriched_goal, pre_assess_local, _mission_state, confidence_needs_approval = \
            await build_enriched_goal(
                goal=goal, mid=mid, ctx=ctx, trace=trace,
                rich_ctx=rich_ctx,
                _reasoning_result=_reasoning_result,
                _kernel_plan=_kernel_plan,
                _kernel_context=_kernel_context,
                _skill_context=_skill_context,
                _mission_lessons=_mission_lessons,
                _is_chat_mode=_is_chat_mode,
                pre_assess=pre_assess,
            )

        # needs_approval is propagated as requires_approval into supervise() via run_execution
        if confidence_needs_approval and not force_approved:
            needs_approval = True

        # ── Phase 2: Inject runtime memory context ─────────────────────────────
        def _transition_fn(ctx_arg, status, **kw):
            self._transition(ctx_arg, status, **kw)

        maybe_goal = await inject_memory_context(
            goal=goal, mid=mid, mode=mode, ctx=ctx, trace=trace,
            enriched_goal=enriched_goal,
            transition_fn=_transition_fn,
        )
        if maybe_goal is None:
            return None  # AlignmentLayer blocked — ctx already set to DONE
        enriched_goal = maybe_goal

        # ── Phase 3: Policy gate + delegate setup ──────────────────────────────
        delegate, needs_approval, _provider_token, _safer_token = \
            setup_policy_and_delegate(
                goal=goal, mid=mid, mode=mode, ctx=ctx, trace=trace,
                risk=risk,
                needs_approval=needs_approval,
                force_approved=force_approved,
                use_budget=use_budget,
                cap_dispatcher=_cap_dispatcher,
                v2=self.v2,
                bea=self.bea,
                s=self.s,
            )

        # ── Phase 4: Execute mission ───────────────────────────────────────────
        def _cleanup_fn(mission_id: str) -> None:
            self._cleanup_event_stream(mission_id)

        outcome = await run_execution(
            goal=goal, mid=mid, mode=mode, ctx=ctx, trace=trace,
            enriched_goal=enriched_goal,
            needs_approval=needs_approval,
            force_approved=force_approved,
            risk=risk,
            delegate=delegate,
            provider_token=_provider_token,
            safer_token=_safer_token,
            cap_dispatcher=_cap_dispatcher,
            is_chat_mode=_is_chat_mode,
            pre_assess_local=pre_assess_local,
            mission_timeout_s=getattr(self.s, "mission_timeout_s", 120),
            callback=callback,
            transition_fn=_transition_fn,
            cleanup_fn=_cleanup_fn,
        )

        # ── Phase 5: Finalize execution metadata ───────────────────────────────
        finalize_execution_metadata(
            ctx=ctx,
            enriched_goal=enriched_goal,
            risk=risk,
            delegate=delegate,
            mission_timeout=getattr(self.s, "mission_timeout_s", 120),
            needs_approval=needs_approval,
        )

        return outcome
