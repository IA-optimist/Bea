"""
api/routes/missions.py — Mission, task, and agent endpoints.
Single source for all /api/v2/task, /api/v2/tasks, /api/v2/missions, /api/v2/agents routes.
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import time
from typing import Annotated, Any, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, field_validator

from api._deps import (
    _check_auth,
    _extract_final_output,
    _get_mission_system,
    _get_orchestrator,
    _get_task_queue,
    # BLOC E: _get_kernel removed — dead import, never called.
    # Use _get_kernel_adapter() (R8 canonical boundary) for all kernel access.
    _get_kernel_adapter,
)

log = structlog.get_logger()
logger = log

router = APIRouter(tags=["missions"])

# Anti-duplicate guard: prevents the same mission from being dispatched twice concurrently.
# asyncio.Lock makes the check-and-add atomic within a single-worker asyncio event loop.
# NOTE: does NOT protect across multiple uvicorn workers (--workers > 1).
# For multi-worker deployments use a Redis-backed set instead.
_running_missions: set[str] = set()
_running_missions_lock = asyncio.Lock()


# ── Pydantic models ───────────────────────────────────────────

class TaskRequest(BaseModel):
    input: str
    mode:  str = "auto"

    @field_validator("input", mode="before")
    @classmethod
    def input_not_empty(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Mission input cannot be empty")
        if len(v) > 50000:
            raise ValueError("Mission input too long (max 50000 chars)")
        # Sanitization anti-prompt injection
        from core.security.input_sanitizer import sanitize_user_input
        result = sanitize_user_input(v, strict=False)
        if result.warnings:
            import structlog as _sl
            _sl.get_logger().warning("mission_input_sanitized", warnings=result.warnings)
        return result.value


class ModeRequest(BaseModel):
    mode:       str = "SUPERVISED"
    changed_by: str = "api"


class TriggerRequest(BaseModel):
    mission: str = ""


class AbortRequest(BaseModel):
    reason: str = ""


class MissionSubmitRequest(BaseModel):
    goal: str = ""
    mode: str = "auto"


@router.post("/api/v2/task", status_code=201)
async def submit_task(
    req: TaskRequest,
    background_tasks: BackgroundTasks,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Soumettre une nouvelle tâche/mission."""
    _check_auth(x_jarvis_token, authorization)
    ms      = _get_mission_system()
    result  = ms.submit(req.input)

    # ── Anti-duplicate execution guard (atomic check-and-add) ────────
    async with _running_missions_lock:
        if result.mission_id in _running_missions:
            log.warning("mission_already_running", mission_id=result.mission_id)
            return {"ok": True, "data": {
                "task_id": result.mission_id, "mission_id": result.mission_id,
                "status": "already_running", "mode": req.mode,
                "created_at": result.created_at,
            }}
        _running_missions.add(result.mission_id)

    async def _run_mission():
        import time; open("/tmp/jarvis_trace.log", "a").write(f"[TRACE_B] RUN_MISSION_ENTER {time.time()}\n")
        _mission_start = time.time()
        try:
            from core.mission_system import is_capability_query, CAPABILITY_DEMO
            if is_capability_query(req.input):
                _r = ms.get(result.mission_id)
                if _r:
                    _r.agents_selected = []
                ms.set_final_output(result.mission_id, CAPABILITY_DEMO)
                ms.complete(result.mission_id, result_text=CAPABILITY_DEMO)
                try:
                    from memory.decision_memory import (
                        get_decision_memory, DecisionOutcome, classify_mission_type,
                    )
                    get_decision_memory().record(DecisionOutcome(
                        ts=int(time.time()),
                        mission_type="capability_query",
                        complexity="low",
                        risk_score=0,
                        confidence_score=1.0,
                        selected_agents=[],
                        approval_mode="AUTO",
                        approval_decision="auto_approved",
                        fallback_level_used=0,
                        latency_ms=int((time.time() - _mission_start) * 1000),
                        success=True,
                        user_override=False,
                        retry_count=0,
                        error_type="",
                    ))
                except Exception:
                    pass
                return
            # ── Knowledge Memory lookup (fail-open) ──────────────────────────
            _km_bonus_confidence = 0.0
            _km_priority_tools: list = []
            _km_priority_agents: list = []
            try:
                from core.knowledge_memory import get_knowledge_memory
                _km = get_knowledge_memory()
                _ms_km = ms.get(result.mission_id)
                _km_mtype = (_ms_km.decision_trace.get("mission_type", "unknown") if _ms_km else "unknown")
                _km_result = _km.find_similar(req.input, _km_mtype)
                if _km_result is not None:
                    _km_entry, _km_score = _km_result
                    _km_bonus_confidence = round(_km_score * 0.15, 3)
                    _km_priority_tools = _km_entry.tools_used
                    _km_priority_agents = _km_entry.agents_used
                    if _ms_km is not None:
                        _ms_km.decision_trace["knowledge_match"] = True
                        _ms_km.decision_trace["knowledge_score"] = _km_score
                        _ms_km.decision_trace["knowledge_priority_agents"] = _km_priority_agents
                else:
                    if _ms_km is not None:
                        _ms_km.decision_trace["knowledge_match"] = False
            except Exception:
                try:
                    _ms_km2 = ms.get(result.mission_id)
                    if _ms_km2 is not None:
                        _ms_km2.decision_trace["knowledge_match"] = False
                except Exception:
                    pass
            # ── end knowledge lookup ──────────────────────────────────────────

            # ── Mission Planning (fail-open) ──────────────────────────────────
            _plan_used = False
            _plan_steps_count = 0
            _plan_success_rate = 0.0
            try:
                from core.mission_planner import get_mission_planner, set_last_plan
                _planner = get_mission_planner()
                _ms_plan = ms.get(result.mission_id)
                _current_confidence = float((_ms_plan.decision_trace.get("confidence_score", 0.5)) if _ms_plan else 0.5)
                _current_complexity = (getattr(_ms_plan, "complexity", None) or "medium") if _ms_plan else "medium"
                _current_mission_type = ((_ms_plan.decision_trace.get("mission_type", "unknown")) if _ms_plan else "unknown")

                if _planner.should_plan(_current_complexity, _current_confidence, _current_mission_type):
                    _plan = _planner.build_plan(
                        goal=req.input,
                        mission_type=_current_mission_type,
                        complexity=_current_complexity,
                        mission_id=str(result.mission_id),
                    )
                    if _plan is not None:
                        set_last_plan(_plan)
                        _plan_used = True
                        _plan_steps_count = _plan.total_steps

                        # Exécution séquentielle des étapes via le routing normal
                        _all_step_results = []
                        for _step in _plan.steps:
                            _next = _planner.get_next_steps(_plan)
                            if not _next:
                                break
                            _step_to_run = _next[0]
                            _planner.execute_step(_step_to_run)
                            try:
                                # Build sub-goal for this step
                                _step_goal = f"{_step_to_run.description} — contexte: {req.input[:100]}"
                                # Select agents for this step (real routing)
                                from agents.crew import select_agents
                                _step_agents = select_agents(
                                    goal=_step_goal,
                                    risk_level="low",
                                    domain="",
                                    complexity=_step_to_run.estimated_complexity,
                                    mission_type=_step_to_run.mission_type,
                                )
                                # Step is PLANNED, not executed inline (execution via orchestrator)
                                # Marking as planned with selected agents for traceability
                                _step_result = {
                                    "step_id": _step_to_run.step_id,
                                    "description": _step_to_run.description,
                                    "status": "PLANNED",
                                    "agents_selected": _step_agents,
                                    "tools_required": _step_to_run.required_tools,
                                    "executed": False,
                                }
                                _planner.complete_step(_step_to_run, json.dumps(_step_result), success=True)
                                _plan.success_count += 1
                                _all_step_results.append(_step_result)
                            except Exception as _step_err:
                                _planner.complete_step(_step_to_run, str(_step_err), success=False)

                        _plan_success_rate = _plan.success_rate
            except Exception as _plan_err:
                logger.warning(f"[MissionPlanning] error (fail-open): {_plan_err}")
            # ── end Mission Planning ──────────────────────────────────────────

            # ── Tool trace (fail-open) — rend les tools VISIBLES dans decision_trace ──
            try:
                from core.tool_registry import get_tool_registry
                from core.tool_executor import get_tool_executor
                _ms_tt = ms.get(result.mission_id)
                _tt_mtype = (
                    (_ms_tt.decision_trace.get("mission_type", "unknown") if _ms_tt else "unknown")
                    or "unknown"
                )
                _tt_tools = get_tool_registry().get_tools_for_mission_type(_tt_mtype)
                _available_tools = [t.name for t in _tt_tools]
                get_tool_executor()  # init singleton
                if _ms_tt is not None:
                    _ms_tt.decision_trace["available_tools"] = _available_tools
                    _ms_tt.decision_trace["tool_executor_ready"] = True
            except Exception as _tt_err:
                try:
                    _ms_tt2 = ms.get(result.mission_id)
                    if _ms_tt2 is not None:
                        _ms_tt2.decision_trace["available_tools"] = []
                        _ms_tt2.decision_trace["tool_executor_ready"] = False
                except Exception:
                    pass
            # ── end tool trace ────────────────────────────────────────────────

            # ── Tool pre-execution (fail-open) ────────────────────────────────
            _enriched_input = req.input
            _tool_run_results: dict = {}
            try:
                from core.tool_runner import run_tools_for_mission, format_goal_with_context
                _ms_tr = ms.get(result.mission_id)
                _mission_type_for_tools = (
                    _ms_tr.decision_trace.get("mission_type", "info_query")
                    if _ms_tr else "info_query"
                ) or "info_query"
                _tool_context_prefix, _tool_run_results = run_tools_for_mission(
                    goal=req.input,
                    mission_type=_mission_type_for_tools,
                    approval_mode="SUPERVISED",
                    max_tools=2,
                )
                if _tool_context_prefix:
                    _enriched_input = format_goal_with_context(req.input, _tool_context_prefix)
            except Exception:
                pass
            # ── end tool pre-execution ────────────────────────────────────────

            # ── kernel.execute() via KernelAdapter (Pass 26 — R8) ───────────
            # R8: API never touches kernel internals directly.
            # KernelAdapter is the ONLY sanctioned bridge (interfaces/).
            # Fallback chain: KernelAdapter → legacy orch.run()
            _adapter = _get_kernel_adapter()
            if _adapter is not None:
                session = await _adapter.submit(
                    goal=_enriched_input,
                    mission_id=str(result.mission_id),
                    mode=req.mode,
                )
                log.debug("api_kernel_adapter_used", mission_id=result.mission_id)
            else:
                # Fallback: legacy MetaOrchestrator.run() path
                orch    = _get_orchestrator()
                session = await orch.run(
                    user_input=_enriched_input,
                    mode=req.mode,
                    session_id=result.mission_id,
                )
                log.debug("api_kernel_execute_fallback", mission_id=result.mission_id)

            # ── Handle AWAITING_APPROVAL (MetaOrchestrator paused for human review) ──
            # AdapterResult.status is a lowercase string; JarvisSession has an enum.
            _sess_status = getattr(session, "status", None)
            _status_val  = (_sess_status.value
                            if hasattr(_sess_status, "value")
                            else str(_sess_status or ""))
            if _status_val in ("AWAITING_APPROVAL", "awaiting_approval"):
                _ms_aw = ms.get(result.mission_id)
                if _ms_aw:
                    from core.mission_system import MissionStatus as _MS
                    _ms_aw.status = _MS.PENDING_VALIDATION
                    _ms_aw.decision_trace["awaiting_approval"] = True
                    _ms_aw.decision_trace["approval_item_id"] = (
                        getattr(session, "metadata", {}).get("approval_item_id", "")
                    )
                    _ms_aw.decision_trace["original_goal"] = req.input
                log.info("mission_awaiting_approval", mission_id=result.mission_id)
                return  # leave in PENDING_VALIDATION; do not call ms.complete()

            # Niveau 0 : extraire selon le type de session retournée
            _final = ""
            _fallback_level = 0
            _final_source = "agent"
            if hasattr(session, "get_output"):
                # JarvisSession — pipeline multi-agents avec outputs nommés
                for _agent in ("lens-reviewer", "shadow-advisor", "map-planner",
                               "scout-research", "forge-builder"):
                    _out = session.get_output(_agent)
                    if _out and len(_out.strip()) >= 10:
                        _final = _out
                        break
                if not _final:
                    _final = getattr(session, "final_report", "") or ""
            else:
                # AdapterResult (R8 path) — résultat dans .output
                # Legacy MissionContext (fallback path) — résultat dans .result
                _final = (
                    getattr(session, "output", None)
                    or getattr(session, "result", None)
                    or ""
                )
                _final_source = (
                    "kernel_adapter"
                    if getattr(session, "source", "") == "kernel"
                    else "meta_orchestrator"
                )
            _final = _extract_final_output(_final)

            # Niveau 0b: quality check — if _final is workspace noise (listing files
            # instead of answering the question), prefer agent_outputs synthesis.
            # Workspace noise pattern: contains "fichier(s)" or "Workspace :" in
            # the first 500 chars, which indicates repo_inspector injection, not
            # a real answer. The actual LLM responses are in agent_outputs.
            if _final and ("fichier(s)" in _final[:500] or "Workspace :" in _final[:500]):
                _workspace_agent_outputs = _extract_agent_outputs(result.mission_id)
                # Filter out vault-memory and internal agents — keep real analysis agents
                _useful = {k: v for k, v in _workspace_agent_outputs.items()
                           if k not in ("vault-memory", "pulse-ops", "observer")
                           and v and len(str(v).strip()) >= 10}
                if _useful:
                    _parts = []
                    for _aname, _aout in _useful.items():
                        if _aout and str(_aout).strip():
                            _parts.append(f"## {_aname}\n{str(_aout)[:1500]}")
                    if _parts:
                        _final = "# Résultats de mission\n\n" + "\n\n".join(_parts)
                        _final_source = "agent_outputs_preferred"
                        _fallback_level = 0

            # Niveau 1 : synthétiser depuis les agent_outputs bruts (MissionStateStore)
            if not _final or not _final.strip():
                _fallback_level = 1
                _final_source = "synthesis"
                _agent_outputs = _extract_agent_outputs(result.mission_id)
                if _agent_outputs:
                    _parts = []
                    for _aname, _aout in _agent_outputs.items():
                        if _aout and str(_aout).strip():
                            _parts.append(f"[{_aname}] {str(_aout)[:500]}")
                    if _parts:
                        _final = "Résultats de l'analyse :\n\n" + "\n\n".join(_parts)

            # Niveau 2 : message explicite — jamais vide
            if not _final or not _final.strip():
                _fallback_level = 2
                _final_source = "fallback_message"
                _final = (
                    f"Mission exécutée. Objectif traité : {req.input}\n\n"
                    "Aucun résultat structuré n'a été produit par les agents. "
                    "Reformulez la demande pour obtenir une réponse plus précise."
                )

            # ── LangGraph integration — fail-open, USE_LANGGRAPH=true to activate ──
            if os.getenv("USE_LANGGRAPH", "false").lower() == "true":
                try:
                    from core.orchestrator_lg.langgraph_flow import invoke as lg_invoke
                    _lg_result = lg_invoke(
                        user_input=req.input or "",
                        mission_id=str(result.mission_id or ""),
                    )
                    if _lg_result.get("final_answer"):
                        _final = _lg_result["final_answer"]
                        _final_source = "langgraph"
                        _fallback_level = 0
                except Exception as _lg_err:
                    log.error("langgraph_api_integration_failed", err=str(_lg_err)[:100])
                    # Continue with existing _final from legacy pipeline
            # ── end LangGraph integration ──────────────────────────────────────

            # Tracer la source du final_output dans decision_trace
            try:
                _ms_ref = ms.get(result.mission_id)
                if _ms_ref is not None:
                    _ms_ref.decision_trace["final_output_source"] = _final_source
                    _ms_ref.decision_trace["fallback_level_used"] = _fallback_level
                    from core.mission_system import compute_confidence_score
                    _ms_ref.decision_trace["confidence_score"] = compute_confidence_score(
                        fallback_level=_fallback_level,
                        agent_outputs=_extract_agent_outputs(result.mission_id),
                        complexity=_ms_ref.complexity,
                        skipped_agents=_ms_ref.decision_trace.get("skipped_agents", []),
                        agents_selected=list(getattr(_ms_ref, "agents_selected", None) or []),
                        goal=req.input,
                    )
                    try:
                        from memory.decision_memory import get_decision_memory, classify_mission_type
                        _dm = get_decision_memory()
                        _mtype = (
                            _ms_ref.decision_trace.get("mission_type")
                            or classify_mission_type(req.input, _ms_ref.complexity)
                        )
                        _ms_ref.decision_trace["mission_type"] = _mtype
                        _ms_ref.decision_trace["confidence_score"] = (
                            _dm.compute_adjusted_confidence(
                                _ms_ref.decision_trace["confidence_score"],
                                _mtype,
                                _ms_ref.complexity,
                            )
                        )
                    except Exception:
                        pass
                    # ── Knowledge Memory confidence bonus ──────────────────────────────
                    try:
                        if _km_bonus_confidence > 0:
                            _current_conf = float(_ms_ref.decision_trace.get("confidence_score", 0.5))
                            _ms_ref.decision_trace["confidence_score"] = min(1.0, round(_current_conf + _km_bonus_confidence, 3))
                    except Exception:
                        pass
                    # ── end km bonus ───────────────────────────────────────────────────
                    # ── Mission Planning trace ─────────────────────────────────────────
                    try:
                        _ms_ref.decision_trace["plan_used"] = _plan_used
                        _ms_ref.decision_trace["plan_steps"] = _plan_steps_count
                        _ms_ref.decision_trace["plan_success_rate"] = _plan_success_rate
                    except Exception:
                        pass
                    # ── end plan trace ─────────────────────────────────────────────────
            except Exception:
                pass

            # Ajout ExecutionPolicy dans decision_trace (fail-open)
            try:
                from core.execution_policy import get_execution_policy, ActionContext
                _pol = get_execution_policy()
                # Détermine action_type dominant à partir du mission_type
                _ACTION_FROM_MISSION = {
                    "coding_task": "write",
                    "debug_task": "execute",
                    "architecture_task": "write",
                    "system_task": "execute",
                    "planning_task": "write",
                    "business_task": "read",
                    "research_task": "read",
                    "info_query": "read",
                    "compare_query": "read",
                    "evaluation_task": "read",
                    "self_improvement_task": "self_modify",
                }
                _ms_ep = ms.get(result.mission_id)
                if _ms_ep is not None:
                    _action_type = _ACTION_FROM_MISSION.get(_ms_ep.decision_trace.get("mission_type", ""), "execute")
                    _ctx = ActionContext(
                        mission_type=_ms_ep.decision_trace.get("mission_type", "unknown"),
                        risk_score=_ms_ep.risk_score,
                        complexity=_ms_ep.complexity,
                        agent=_ms_ep.agents_selected[0] if _ms_ep.agents_selected else "unknown",
                        action_type=_action_type,
                        estimated_impact="high" if _ms_ep.complexity == "high" else ("medium" if _ms_ep.complexity == "medium" else "low"),
                        mode=getattr(_ms_ep, "approval_mode", None) or "SUPERVISED",
                    )
                    _pol_decision = _pol.evaluate(_ctx)
                    _ms_ep.decision_trace["execution_policy_decision"] = _pol_decision.decision
                    _ms_ep.decision_trace["execution_reason"] = _pol_decision.reason
            except Exception as _ep_err:
                try:
                    _ms_ep2 = ms.get(result.mission_id)
                    if _ms_ep2 is not None:
                        _ms_ep2.decision_trace["execution_policy_decision"] = "unknown"
                        _ms_ep2.decision_trace["execution_reason"] = str(_ep_err)
                except Exception:
                    pass

            # Policy mode
            try:
                from core.policy_mode import get_policy_mode_store
                _ms_pm = ms.get(result.mission_id)
                if _ms_pm is not None:
                    _ms_pm.decision_trace["policy_mode_used"] = get_policy_mode_store().get().value
            except Exception:
                try:
                    _ms_pm2 = ms.get(result.mission_id)
                    if _ms_pm2 is not None:
                        _ms_pm2.decision_trace["policy_mode_used"] = "BALANCED"
                except Exception:
                    pass

            # ── Tool results dans decision_trace (fail-open) ──────────────────
            try:
                _ms_tr2 = ms.get(result.mission_id)
                if _ms_tr2 is not None and _tool_run_results:
                    _ms_tr2.decision_trace["tools_executed"] = list(_tool_run_results.keys())
                    _ms_tr2.decision_trace["tool_results_ok"] = [
                        k for k, v in _tool_run_results.items() if v.get("ok")
                    ]
            except Exception:
                pass
            # ── end tool results trace ────────────────────────────────────────

            ms.set_final_output(result.mission_id, _final)
            # Garde-fou : ne pas marquer DONE si la mission attend une validation
            current = ms.get(result.mission_id)
            if current and current.status == "PENDING_VALIDATION":
                log.warning(
                    "background_task_skip_complete_pending",
                    id=result.mission_id,
                    hint="Mission requires human approval — not auto-completing",
                )
            else:
                ms.complete(result.mission_id, result_text=_final)
                try:
                    from memory.decision_memory import (
                        get_decision_memory, DecisionOutcome, classify_mission_type,
                    )
                    _ms_dm = ms.get(result.mission_id)
                    _dt_dm = (_ms_dm.decision_trace if _ms_dm else {}) or {}
                    _cx_dm = getattr(_ms_dm, "complexity", "medium") if _ms_dm else "medium"
                    get_decision_memory().record(DecisionOutcome(
                        ts=int(time.time()),
                        mission_type=_dt_dm.get("mission_type") or classify_mission_type(req.input, _cx_dm),
                        complexity=_cx_dm,
                        risk_score=int(getattr(_ms_dm, "risk_score", 0) if _ms_dm else 0),
                        confidence_score=float(_dt_dm.get("confidence_score", 0.0)),
                        selected_agents=list(getattr(_ms_dm, "agents_selected", []) or []),
                        approval_mode=str(_dt_dm.get("approval_mode", "")),
                        approval_decision=str(_dt_dm.get("approval_decision", "")),
                        fallback_level_used=int(_dt_dm.get("fallback_level_used", _fallback_level)),
                        latency_ms=int((time.time() - _mission_start) * 1000),
                        success=bool(_final and _final.strip()),
                        user_override=False,
                        retry_count=0,
                        error_type="" if (_final and _final.strip()) else "empty_output",
                    ))
                except Exception:
                    pass

            # ── Knowledge Memory store (fail-open) ────────────────────────────
            try:
                from core.knowledge_memory import get_knowledge_memory
                _km_store = get_knowledge_memory()
                _ms_km_s = ms.get(result.mission_id)
                _dt_km_s = (_ms_km_s.decision_trace if _ms_km_s else {}) or {}
                _km_store.store_if_useful(
                    goal=req.input,
                    mission_type=_dt_km_s.get("mission_type", "unknown"),
                    solution_summary=str(_final)[:500] if _final else "",
                    tools_used=_dt_km_s.get("knowledge_priority_tools", []),
                    agents_used=list(getattr(_ms_km_s, "agents_selected", None) or []),
                    confidence_score=float(_dt_km_s.get("confidence_score", 0.5)),
                    fallback_level=int(_dt_km_s.get("fallback_level_used", 0)),
                    execution_policy_decision=_dt_km_s.get("execution_policy_decision", "unknown"),
                )
            except Exception:
                pass
            # ── end km store ──────────────────────────────────────────────────

            # ── Observability + Self-Improvement trigger (fail-open) ──────────────
            try:
                from core.observability import get_observability_store, MissionMetrics
                import time as _time
                _obs = get_observability_store()
                _dur = int((getattr(ms, "_end_ts", _time.time()) - getattr(ms, "_start_ts", _time.time())) * 1000)
                _obs.record(MissionMetrics(
                    mission_id=str(result.mission_id),
                    mission_type=ms.get(result.mission_id).decision_trace.get("mission_type", "unknown") if ms.get(result.mission_id) else "unknown",
                    selected_agents=list(getattr(ms.get(result.mission_id), "agents_selected", None) or []),
                    execution_policy_decision=ms.get(result.mission_id).decision_trace.get("execution_policy_decision", "unknown") if ms.get(result.mission_id) else "unknown",
                    fallback_level_used=int(ms.get(result.mission_id).decision_trace.get("fallback_level_used", 0)) if ms.get(result.mission_id) else 0,
                    confidence_score=float(ms.get(result.mission_id).decision_trace.get("confidence_score", 0.5)) if ms.get(result.mission_id) else 0.5,
                    duration_ms=_dur,
                    tools_used=[],  # a enrichir quand les agents utiliseront le tool_registry
                ))
            except Exception:
                pass

            try:
                from core.self_improvement import get_self_improvement_manager
                _sim = get_self_improvement_manager()
                # Analyse asynchrone legere — ne bloque pas la reponse
                _sim.analyze_patterns()  # resultat ignore ici, mis en cache implicitement
            except Exception:
                pass
            # ── fin Observability ─────────────────────────────────────────────────

        except Exception as e:
            log.error("background_mission_failed", err=str(e)[:100])
            # Garantir que la mission se termine même en cas d'erreur interne
            try:
                _err_output = (
                    f"Mission exécutée. Objectif traité : {req.input}\n\n"
                    "Une erreur interne s'est produite lors du traitement. "
                    "Reformulez la demande pour obtenir une réponse plus précise."
                )
                _cur = ms.get(result.mission_id)
                if _cur and _cur.status not in ("DONE", "PENDING_VALIDATION"):
                    ms.set_final_output(result.mission_id, _err_output)
                    ms.complete(result.mission_id, result_text=_err_output)
            except Exception as _completion_err:
                log.error("mission_completion_failed",
                          mission_id=str(result.mission_id),
                          err=str(_completion_err)[:120])
        finally:
            _running_missions.discard(result.mission_id)

    background_tasks.add_task(_run_mission)
    with open("/tmp/jarvis_trace.log", "a") as _tf: _tf.write(f"[TRACE_A] ADD_TASK_CALLED {time.time()}\n")

    try:
        from api.event_emitter import emit_mission_created
        emit_mission_created(result.mission_id, req.input)
    except Exception as e:
        log.debug("emit_mission_created_skipped", mission=result.mission_id, err=str(e)[:80])

    _response_data = {"ok": True, "data": {
        "task_id":    result.mission_id,
        "mission_id": result.mission_id,
        "status":     result.status,
        "mode":       req.mode,
        "created_at": result.created_at,
    }}

    return JSONResponse(content=_response_data, headers={"X-Jarvis-Stack": "jarvis_core", "X-Trace-Time": str(time.time())})

@router.get("/api/v2/task/{task_id}")
async def get_task(task_id: str, x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Statut d'une tâche."""
    _check_auth(x_jarvis_token, authorization)
    ms = _get_mission_system()
    r  = ms.get(task_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Tâche '{task_id}' introuvable.")
    return {"ok": True, "data": r.to_dict()}


@router.get("/api/v2/tasks")
async def list_tasks(
    status: Optional[str] = Query(None),
    limit:  int           = Query(20, ge=1, le=200),
    source: str           = Query("missions", description="'missions' or 'queue'"),
    offset: int           = Query(0, ge=0),
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Lister les tâches — source='missions' (MissionSystem) ou source='queue' (CoreTaskQueue)."""
    _check_auth(x_jarvis_token, authorization)
    if source == "queue":
        from core.task_queue import get_core_task_queue, TaskState
        q = get_core_task_queue()
        state_filter = TaskState(status) if status else None
        tasks = await q.list_tasks(state=state_filter, limit=limit + offset)
        tasks = tasks[offset:offset + limit]
        stats = await q.stats()
        return {"ok": True, "data": {
            "tasks": [t.to_dict() for t in tasks],
            "total": stats["total"],
            "stats": stats,
        }}
    ms       = _get_mission_system()
    missions = ms.list_missions(status=status, limit=limit)
    return {"ok": True, "data": {
        "tasks": [m.to_dict() for m in missions],
        "total": len(missions),
    }}


@router.get("/api/v2/tasks/{task_id}")
async def get_background_task(
    task_id: str,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Statut et résultat d'une tâche de fond (CoreTaskQueue)."""
    _check_auth(x_jarvis_token, authorization)
    from core.task_queue import get_core_task_queue
    q    = get_core_task_queue()
    task = await q.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return {"ok": True, "data": task.to_dict()}


@router.delete("/api/v2/tasks/{task_id}", status_code=200)
async def cancel_background_task(
    task_id: str,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Annuler une tâche de fond (CoreTaskQueue)."""
    _check_auth(x_jarvis_token, authorization)
    from core.task_queue import get_core_task_queue
    q  = get_core_task_queue()
    ok = await q.cancel(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found or already terminal.")
    return {"ok": True, "data": {"task_id": task_id, "status": "cancelled"}}


@router.post("/api/v2/missions/{mission_id}/abort")
async def abort_mission(
    mission_id: str,
    req: AbortRequest,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Annuler une mission en cours."""
    _check_auth(x_jarvis_token, authorization)
    queue = _get_task_queue()
    await queue.cancel_mission(mission_id)
    ms = _get_mission_system()
    r  = ms.reject(mission_id, note=req.reason)
    if not r:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' introuvable.")
    return {"ok": True, "data": {"mission_id": mission_id, "status": r.status}}


# ══════════════════════════════════════════════════════════════
# MISSIONS
# ══════════════════════════════════════════════════════════════

@router.post("/api/v2/missions/submit", status_code=201)
async def submit_mission(
    req: MissionSubmitRequest,
    background_tasks: BackgroundTasks,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Soumettre une mission (interface Flutter — champ `goal` + `mode`)."""
    _check_auth(x_jarvis_token, authorization)
    try:
        task_req = TaskRequest(input=req.goal, mode=req.mode)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await submit_task(task_req, background_tasks, x_jarvis_token, authorization)


@router.get("/api/v2/missions")
async def list_missions(
    status: Optional[str] = Query(None),
    limit:  int           = Query(20, ge=1, le=200),
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    _check_auth(x_jarvis_token, authorization)
    ms       = _get_mission_system()
    missions = ms.list_missions(status=status, limit=limit)
    stats    = ms.stats()
    return {"ok": True, "data": {
        "missions": [m.to_dict() for m in missions],
        "stats":    stats,
    }}


def _extract_agent_outputs(mission_id: str) -> dict:
    """Extrait le texte brut de chaque agent depuis MissionStateStore.

    Retourne {agent_name: full_output_str} — directement utilisable côté Flutter
    (Map<String, String>). Chaque agent n'apparaît qu'une fois (dernière entrée gagne).
    """
    try:
        from api.mission_store import MissionStateStore
        from api.models import LogEventType
        store  = MissionStateStore.get()
        events = store.get_log(mission_id)
        outputs: dict[str, str] = {}
        for ev in events:
            if ev.event_type != LogEventType.TOOL_RESULT:
                continue
            agent = ev.agent_id
            if not agent:
                continue
            data = ev.data or {}
            # Priorité : full_output > reasoning (structured fallback) > message brut
            text = (
                data.get("full_output")
                or (data.get("agent_result") or {}).get("reasoning")
                or ev.message
                or ""
            )
            if text:
                outputs[agent] = str(text)[:3000]
        return outputs
    except Exception:
        return {}


@router.get("/api/v2/missions/{mission_id}")
async def get_mission(mission_id: str, x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    _check_auth(x_jarvis_token, authorization)
    ms = _get_mission_system()
    r  = ms.get(mission_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' introuvable.")
    data = r.to_dict()
    data["agent_outputs"]   = _extract_agent_outputs(mission_id)
    data["execution_trace"] = data.pop("execution_trace", [])
    # ── Result Envelope (Kensho-style) ─────────────────────────────────────
    # Try to parse stored FinalOutput JSON, otherwise build from raw data
    try:
        import json as _json
        raw_fo = data.get("final_output", "")
        parsed_envelope = None
        if raw_fo and raw_fo.strip().startswith("{"):
            try:
                parsed_envelope = _json.loads(raw_fo)
                # Validate it's a FinalOutput envelope
                if "agent_outputs" in parsed_envelope and "status" in parsed_envelope:
                    data["result_envelope"] = parsed_envelope
                    # Also set human-readable final_output from envelope
                    parts = []
                    for ao in parsed_envelope.get("agent_outputs", []):
                        if ao.get("output_text"):
                            parts.append(f"## {ao.get('agent_name', 'agent')}\n{ao['output_text'][:1500]}")
                    if parts:
                        data["final_output"] = f"# Résultats ({len(parts)} agents)\n\n" + "\n\n---\n\n".join(parts)
                    else:
                        data["final_output"] = parsed_envelope.get("summary", raw_fo)
                else:
                    parsed_envelope = None
            except (_json.JSONDecodeError, Exception):
                parsed_envelope = None
        if not parsed_envelope:
            # Fallback: build envelope from existing data
            try:
                from core.result_aggregator import aggregate_mission_result
                envelope = aggregate_mission_result(
                    mission_id=str(mission_id),
                    mission_status=str(getattr(r, "status", "DONE")),
                    start_time=getattr(r, "created_at", 0.0),
                    summary=data.get("plan_summary", "")[:500],
                )
                data["result_envelope"] = envelope.to_dict()
            except Exception:
                data["result_envelope"] = None
            # Keep existing pipeline_guard for final_output text
            try:
                from api.pipeline_guard import build_safe_final_output
                _ao_dict = data.get("agent_outputs") or {}
                _ao_list = [{"agent_name": k, "result": v} for k, v in _ao_dict.items()] if isinstance(_ao_dict, dict) else list(_ao_dict)
                data["final_output"] = build_safe_final_output(
                    raw_output=raw_fo or (data.get("plan_summary") or "")[:2000],
                    agent_outputs=_ao_list,
                    mission_id=str(mission_id or ""),
                )
            except Exception:
                if not data.get("final_output"):
                    data["final_output"] = "Mission exécutée. Réponse temporairement indisponible."
    except Exception as _env_err:
        import logging as _log
        _log.getLogger(__name__).error("[RESULT ENVELOPE] failed: %s", _env_err)
        data.setdefault("result_envelope", None)
        if not data.get("final_output"):
            data["final_output"] = "Mission exécutée. Réponse temporairement indisponible."
    data.setdefault("summary",         data.get("plan_summary", "")[:500])
    data.setdefault("agents_selected", [])
    data.setdefault("domain",          "general")
    data.setdefault("complexity",      getattr(r, "complexity", "medium"))
    # DQ v2 — champs Flutter
    _dt = getattr(r, "decision_trace", {}) or {}
    data["decision_trace"]       = _dt
    # Extract result_envelope from decision_trace (stored by executor)
    if "result_envelope" not in data or not data.get("result_envelope"):
        data["result_envelope"] = _dt.get("result_envelope")
    data["confidence_score"]     = _dt.get("confidence_score", 0.0)
    data["skipped_agents"]       = _dt.get("skipped_agents", [])
    data["final_output_source"]  = _dt.get("final_output_source", "unknown")
    data["fallback_level_used"]  = _dt.get("fallback_level_used", 0)
    data["approval_reason"]      = _dt.get("approval_reason", "")
    data["approval_decision"]    = _dt.get("approval_decision", "")
    data["risk_score"]           = getattr(r, "risk_score", 0)
    return {"ok": True, "data": data}


# ══════════════════════════════════════════════════════════════
# AGENTS
# ══════════════════════════════════════════════════════════════

@router.get("/api/v2/agents")
async def list_agents(x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Liste tous les agents enregistrés."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from config.settings import get_settings
        from agents.crew import AgentCrew
        crew   = AgentCrew(get_settings())
        agents = []
        for name, agent in crew.registry.items():
            agents.append({
                "name":    name,
                "role":    getattr(agent, "role", "?"),
                "timeout": getattr(agent, "timeout_s", "?"),
                "status":  "registered",
            })
        return {"ok": True, "data": {"agents": agents, "total": len(agents)}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/v2/agents/{agent_id}/trigger")
async def trigger_agent(
    agent_id: str,
    req: TriggerRequest,
    background_tasks: BackgroundTasks,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Déclencher un agent manuellement."""
    _check_auth(x_jarvis_token, authorization)

    async def _run():
        try:
            orch    = _get_orchestrator()
            session = __import__("core.state", fromlist=["JarvisSession"]).JarvisSession(
                session_id=f"manual-{agent_id}",
                user_input=req.mission,
                mode="auto",
            )
            session.mission_summary = req.mission
            session.agents_plan     = [{"agent": agent_id, "task": req.mission, "priority": 1}]
            await orch.agents.run(agent_id, session)
        except Exception as e:
            log.error("agent_trigger_failed", agent=agent_id, err=str(e)[:100])

    background_tasks.add_task(_run)
    return {"ok": True, "data": {"agent_id": agent_id, "status": "triggered"}}

# ══════════════════════════════════════════════════════════════
# COMPATIBILITÉ v1
# ══════════════════════════════════════════════════════════════

@router.post("/api/mission", status_code=201, deprecated=True)
async def legacy_post_mission(
    req: TaskRequest,
    background_tasks: BackgroundTasks,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Alias v1 → POST /api/v2/task"""
    return await submit_task(req, background_tasks, x_jarvis_token, authorization)


@router.get("/api/health")
async def legacy_health():
    """Alias v1 → GET /api/v2/health"""
    from api.routes.system import health
    return await health()


@router.get("/api/missions", deprecated=True)
async def legacy_missions(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Alias v1 → GET /api/v2/missions"""
    return await list_missions(
        status=status,
        limit=limit,
        x_jarvis_token=x_jarvis_token,
        authorization=authorization,
    )


@router.get("/api/stats", deprecated=True)
async def legacy_stats():
    """Alias v1 → GET /api/v2/metrics. Used by mobile."""
    try:
        ms = _get_mission_system()
        return {"ok": True, "data": {"missions": ms.stats()}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Task approve/reject (Flutter uses these) ──────────────────

@router.post("/api/v2/tasks/{task_id}/approve")
async def approve_task(task_id: str, x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Approve a pending action/task."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.action_queue import get_action_queue
        aq = get_action_queue()
        action = aq.approve(task_id, note="Approved via API")
        if action is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found or not pending.")
        return {"ok": True, "data": action.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/v2/tasks/{task_id}/reject")
async def reject_task(
    task_id: str,
    req: Optional[AbortRequest] = None,
    x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Reject a pending action/task."""
    _check_auth(x_jarvis_token, authorization)
    note = req.reason if req else "Rejected via API"
    try:
        from core.action_queue import get_action_queue
        aq = get_action_queue()
        action = aq.reject(task_id, note=note)
        if action is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
        return {"ok": True, "data": action.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Mission-level approve/reject + resumption ────────────────

class ApproveRequest(BaseModel):
    note: str = "Approved by human supervisor"


@router.post("/api/v2/missions/{mission_id}/approve")
async def approve_mission(
    mission_id: str,
    background_tasks: BackgroundTasks,
    req: Optional[ApproveRequest] = None,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Approve a mission that is PENDING_VALIDATION and resume its execution.
    The approval gate is bypassed on re-run (force_approved=True).
    """
    _check_auth(x_jarvis_token, authorization)
    note = (req.note if req else None) or "Approved by human supervisor"
    ms = _get_mission_system()

    # 1. Approve in MissionSystem (PENDING_VALIDATION → APPROVED)
    r = ms.approve(mission_id, note=note)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found.")
    if r.status not in ("APPROVED", "PENDING_VALIDATION"):
        return {"ok": False, "error": f"Mission is in status '{r.status}', cannot approve."}

    # 1b. Canonical bridge approval — updates canonical status + MetaOrchestrator + persists
    try:
        from core.orchestration_bridge import get_orchestration_bridge
        get_orchestration_bridge().approve_mission(mission_id, note=note)
    except Exception as _be:
        log.debug("bridge_approve_skipped", err=str(_be)[:60])

    # 2. Approve the pending approval_queue item (if any)
    try:
        from core.meta_orchestrator import get_meta_orchestrator
        _orch = get_meta_orchestrator()
        _ctx = _orch._missions.get(mission_id)
        if _ctx:
            _item_id = _ctx.metadata.get("approval_item_id", "")
            if _item_id:
                from core.approval_queue import approve as _aq_approve
                _aq_approve(_item_id, approved_by="human")
    except Exception as _ae:
        log.debug("approval_queue_approve_skipped", err=str(_ae)[:60])

    # 3. Re-run the mission with force_approved=True (bypass gate)
    _original_goal = r.user_input or r.decision_trace.get("original_goal", "")
    if not _original_goal:
        return {"ok": False, "error": "Cannot resume: original goal not found."}

    async def _resume_mission():
        try:
            orch = _get_orchestrator()
            session = await orch.run_mission(
                goal=_original_goal,
                mode="auto",
                mission_id=mission_id,
                force_approved=True,
            )
            _final = getattr(session, "result", "") or getattr(session, "final_report", "") or ""
            if _final:
                ms.set_final_output(mission_id, _final)
                ms.complete(mission_id, result_text=_final)
            else:
                ms.complete(mission_id, result_text="Mission approved and executed.")
            log.info("mission_resumed_completed", mission_id=mission_id)
        except Exception as _re:
            log.error("mission_resume_failed", mission_id=mission_id, err=str(_re)[:120])
            try:
                ms.complete(mission_id, result_text=f"Resumption error: {str(_re)[:200]}")
            except Exception:
                pass

    background_tasks.add_task(_resume_mission)
    return {
        "ok": True,
        "data": {
            "mission_id": mission_id,
            "status":     "resuming",
            "note":       note,
        }
    }


@router.post("/api/v2/missions/{mission_id}/reject")
async def reject_mission(
    mission_id: str,
    req: Optional[AbortRequest] = None,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Reject a mission that is PENDING_VALIDATION."""
    _check_auth(x_jarvis_token, authorization)
    note = (req.reason if req else None) or "Rejected by human supervisor"
    ms = _get_mission_system()

    r = ms.reject(mission_id, note=note)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found.")

    # Canonical bridge rejection — updates canonical status + MetaOrchestrator + persists
    try:
        from core.orchestration_bridge import get_orchestration_bridge
        get_orchestration_bridge().reject_mission(mission_id, note=note)
    except Exception as _be:
        log.debug("bridge_reject_skipped", err=str(_be)[:60])

    # Reject the approval_queue item too
    try:
        from core.meta_orchestrator import get_meta_orchestrator
        _ctx = get_meta_orchestrator()._missions.get(mission_id)
        if _ctx:
            _item_id = _ctx.metadata.get("approval_item_id", "")
            if _item_id:
                from core.approval_queue import reject as _aq_reject
                _aq_reject(_item_id, rejected_by="human")
    except Exception:
        pass

    ms.set_final_output(mission_id, f"Mission rejected: {note}")
    return {"ok": True, "data": {"mission_id": mission_id, "status": "rejected", "note": note}}


# ── System mode (Flutter setMode uses POST /api/system/mode) ──
@router.get("/api/system/mode")
async def get_system_mode(x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Get current system operation mode."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.mode_system import get_mode_system
        ms = get_mode_system()
        return {"ok": True, "data": ms.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}



@router.post("/api/system/mode")
async def set_system_mode(req: ModeRequest, x_jarvis_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Change system operation mode (MANUAL / SUPERVISED / AUTO)."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.mode_system import get_mode_system
        ms = get_mode_system()
        ms.set_mode(req.mode.upper(), changed_by=req.changed_by)
        return {"ok": True, "data": ms.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Legacy SSE alias (Flutter may call this path) ─────────────

@router.get("/api/mission/{mission_id}/stream")
# NOTE: /api/v1/missions/{mission_id}/stream is handled by mission_control_router
# (prefix="/api/v1", mounted first at line ~178 in main.py). Duplicate removed.
async def stream_mission_compat(mission_id: str):
    """SSE stream — legacy alias; /api/v1/missions/{id}/stream handled by mission_control."""
    try:
        from api.routes.mission_control import _sse_generator
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            _sse_generator(mission_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

