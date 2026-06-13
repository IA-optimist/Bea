"""Execution mixin extracted mechanically from core.meta_orchestrator."""
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
            from core.orchestration.creative_engine import BeaCreativePipeline, BeaLLMClient, BeaMissionStore
            _creative = BeaCreativePipeline(llm_client=BeaLLMClient(role="fast"), mission_store=BeaMissionStore())
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
            from core.orchestration.causal_module import BeaMaxCausalIntegration
            _causal = BeaMaxCausalIntegration()
            _causal_ctx = _causal.get_causal_context(enriched_goal)
            if _causal_ctx and _causal_ctx.strip() and "No causal" not in _causal_ctx:
                enriched_goal = enriched_goal + "\n\n" + _causal_ctx
                log.info("causal_module.context_injected", mission_id=mid)
            try:
                _causal.update_graph_from_text(enriched_goal[:500])
            except Exception as _exc:
                log.warning("swallowed_exception", action="causal_graph_update", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
            log.debug("swallowed_exception", exc_info=True)
        # Cap enriched_goal to avoid overwhelming agents with huge context
        if len(enriched_goal) > 2000:
            enriched_goal = enriched_goal[:2000] + "\n[...context truncated for performance...]"
            log.debug("enriched_goal_capped", mission_id=mid, original_len=len(enriched_goal))
        from core.orchestration.execution_supervisor import supervise
        delegate = self.v2 if use_budget else self.bea
        
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
            except Exception as _exc:
                log.warning("swallowed_exception", action="phase0c_routing_log", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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

        # FAST PATH: chat direct via BeaLLMClient (no crew, no shadow-advisor)
        # Skip fast-path if mission needs approval or contains destructive keywords
        from core.meta_chat_fast_path import (
            CHAT_DESTRUCTIVE_REFUSAL,
            build_fast_path_prompt,
            should_skip_fast_path,
        )
        _fp_skip_risk = should_skip_fast_path(
            goal,
            needs_approval=needs_approval,
            risk_level=ctx.metadata.get("classification", {}).get("risk_level", "low"),
        )
        # Refus immédiat pour commandes destructives en mode chat
        # Évite le crew complet (3-5min) pour une réponse de refus simple
        if _is_chat_mode and _fp_skip_risk and not needs_approval:
            _refusal = CHAT_DESTRUCTIVE_REFUSAL
            ctx.result = _refusal
            ctx.status = MissionStatus.DONE
            ctx.completed_at = time.time()
            log.info("chat_destructive_refused", mission_id=mid, goal=goal[:60])
            try:
                from core.mission_persistence import get_mission_persistence
                get_mission_persistence().persist(ctx)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
            return

        if _is_chat_mode and not _fp_skip_risk:
            try:
                from core.orchestration.creative_engine import BeaLLMClient
                _fp_llm = BeaLLMClient(role="fast")
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
                    log.debug("swallowed_exception", exc_info=True)
                _fp_prompt = build_fast_path_prompt(goal, memory=_fp_mem, context=_fp_ctx)
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
                    log.debug("swallowed_exception", exc_info=True)
                # Persist to both stores so UI sees consistent status
                try:
                    from core.mission_persistence import get_mission_persistence
                    get_mission_persistence().persist(ctx)
                except Exception:
                    log.debug("swallowed_exception", exc_info=True)
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
                    log.debug("swallowed_exception", exc_info=True)
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
                    log.debug("swallowed_exception", exc_info=True)
                try:
                    self._cleanup_event_stream(mid)
                except Exception:
                    log.debug("swallowed_exception", exc_info=True)
                return
            except Exception as _fe:
                log.warning("chat_fast_path_fail", err=str(_fe)[:120])
                # Fall through to full crew

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # PHASE 4: AGI COGNITION WRAPPER
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        _base_timeout = getattr(self.s, "mission_timeout_s", 120)
        # Multi-agent modes need a longer window: analyst waves (~142s) + forge-builder Codex (~300s) + buffer.
        _LONG_MODE_TIMEOUT = 600
        _mission_timeout = _LONG_MODE_TIMEOUT if mode in (
            "business", "code", "auto", "plan", "research", "night", "improve"
        ) else _base_timeout
        
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
                
                # Preserve the structured outcome. Converting it to text turns
                # failures into non-empty strings and creates ghost-DONE missions.
                outcome = await _cog.execute_mission_with_delegate_cognition(
                    delegate=delegate,
                    supervise_fn=supervise,
                    mission_payload=_payload,
                    timeout=_mission_timeout,
                )
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
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="provider_override_reset", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                # Pass 43: reset safer_model ContextVar
                if _safer_token is not None:
                    try:
                        from core.llm_factory import _safer_model_active as _sma
                        _sma.reset(_safer_token)
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="safer_model_reset", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Store execution context for post-processing helpers
        ctx.metadata["_exec_enriched_goal"] = enriched_goal
        ctx.metadata["_exec_risk"] = risk
        ctx.metadata["_exec_delegate"] = delegate
        ctx.metadata["_exec_mission_timeout"] = _mission_timeout
        ctx.metadata["_exec_needs_approval"] = needs_approval
        
        return outcome
