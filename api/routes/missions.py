"""
api/routes/missions.py — Mission, task, and agent endpoints.
Single source for all /api/v2/task, /api/v2/tasks, /api/v2/missions, /api/v2/agents routes.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from api.mission_outputs import extract_agent_outputs
from api.mission_agents import list_registered_agents, schedule_agent_trigger
from api.mission_approval import (
    approve_mission_for_resume,
    approve_task_payload,
    reject_mission_payload,
    reject_task_payload,
)
from api.mission_response import build_mission_response_data
from api.mission_system_mode import get_system_mode_payload, set_system_mode_payload
from api.mission_legacy import legacy_health_payload, legacy_stats_payload, legacy_stream_response
from api.schemas_missions import (
    AbortRequest,
    ApproveRequest,
    MissionSubmitRequest,
    ModeRequest,
    TaskRequest,
    TriggerRequest,
)
from api._deps import (
    _check_auth,
    _extract_final_output,
    _get_mission_system,
    _get_orchestrator,
    _get_task_queue,
    # BLOC E: _get_kernel removed — dead import, never called.
    # Use _get_kernel_adapter()
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


# Pydantic request schemas live in api.schemas_missions.

@router.post("/api/v2/task", status_code=201)
async def submit_task(
    req: TaskRequest,
    background_tasks: BackgroundTasks,
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Soumettre une nouvelle tâche/mission."""
    _check_auth(x_bea_token, authorization)
    ms      = _get_mission_system()
    result  = ms.submit(req.input)
    # Persister le mode demandé : la reprise post-approbation
    # (approve_mission_for_resume) relançait TOUT en mode "auto", perdant
    # le mode BUSINESS/CODE choisi à la soumission.
    try:
        result.decision_trace["mode"] = req.mode
    except Exception:
        log.debug("mode_trace_skip", mission_id=result.mission_id)

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
        _mission_start = time.time()

        # ── Event stream registration (fail-open) ──────────────────────────
        # Register BEFORE execution so WS clients can connect immediately.
        # The stream persists for 1 hour after completion (TTL in event_stream.py)
        # allowing late-connecting clients to replay the full history.
        _ws_stream = None
        try:
            from core.event_stream import EventStream, register_ws_stream, register_mission_stream
            from core.events import Observation
            _ws_stream = EventStream(str(result.mission_id))
            register_mission_stream(str(result.mission_id), _ws_stream)
            register_ws_stream(str(result.mission_id), _ws_stream)
            await _ws_stream.append(Observation(
                source="system",
                observation_type="mission_started",
                content=f"Mission démarrée : {req.input[:200]}",
                metadata={"mission_id": str(result.mission_id), "mode": req.mode},
            ))
        except Exception as _es_err:
            log.debug("ws_stream_register_skipped", err=str(_es_err)[:80])

        async def _ws_emit(content: str, otype: str = "info", source: str = "system", is_error: bool = False) -> None:
            if _ws_stream is None:
                return
            try:
                from core.events import Observation
                await _ws_stream.append(Observation(
                    source=source, observation_type=otype,
                    content=content, is_error=is_error,
                ))
            except Exception:
                pass

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
                except Exception as _exc:
                    log.warning("swallowed_exception", action="mission_telemetry_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
                except Exception as _exc:
                    log.warning("swallowed_exception", action="knowledge_match_trace", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
                except Exception as _exc:
                    log.warning("swallowed_exception", action="tool_executor_trace", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
            except Exception as _exc:
                log.warning("swallowed_exception", action="context_enrichment", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            # ── end tool pre-execution ────────────────────────────────────────

            # ── kernel.execute() via KernelAdapter (Pass 26 — R8) ───────────
            # R8: API never touches kernel internals directly.
            # KernelAdapter is the ONLY sanctioned bridge (interfaces/).
            # Fallback chain: KernelAdapter → legacy orch.run()
            _adapter = _get_kernel_adapter()
            if _adapter is not None:
                await _ws_emit("Exécution via KernelAdapter…", otype="kernel_start", source="kernel")
                session = await _adapter.submit(
                    goal=_enriched_input,
                    mission_id=str(result.mission_id),
                    mode=req.mode,
                )
                log.debug("api_kernel_adapter_used", mission_id=result.mission_id)
                _adapter_out = getattr(session, "output", "") or ""
                if _adapter_out:
                    await _ws_emit(_adapter_out[:2000], otype="result", source="kernel")
                _adapter_err = getattr(session, "error", "") or ""
                if _adapter_err:
                    await _ws_emit(_adapter_err[:500], otype="error", source="kernel", is_error=True)
            else:
                # Fallback: legacy MetaOrchestrator.run() path
                await _ws_emit("Exécution via MetaOrchestrator…", otype="orch_start", source="orchestrator")
                orch    = _get_orchestrator()
                session = await orch.run(
                    user_input=_enriched_input,
                    mode=req.mode,
                    session_id=result.mission_id,
                )
                log.debug("api_kernel_execute_fallback", mission_id=result.mission_id)

            # ── Handle AWAITING_APPROVAL (MetaOrchestrator paused for human review) ──
            # AdapterResult.status is a lowercase string; BeaSession has an enum.
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
                # BeaSession — pipeline multi-agents avec outputs nommés
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
                _workspace_agent_outputs = extract_agent_outputs(result.mission_id)
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
                _agent_outputs = extract_agent_outputs(result.mission_id)
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
                        agent_outputs=extract_agent_outputs(result.mission_id),
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
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="mission_telemetry_emit_v2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                    # ── Knowledge Memory confidence bonus ──────────────────────────────
                    try:
                        if _km_bonus_confidence > 0:
                            _current_conf = float(_ms_ref.decision_trace.get("confidence_score", 0.5))
                            _ms_ref.decision_trace["confidence_score"] = min(1.0, round(_current_conf + _km_bonus_confidence, 3))
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="confidence_bonus_apply", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                    # ── end km bonus ───────────────────────────────────────────────────
                    # ── Mission Planning trace ─────────────────────────────────────────
                    try:
                        _ms_ref.decision_trace["plan_used"] = _plan_used
                        _ms_ref.decision_trace["plan_steps"] = _plan_steps_count
                        _ms_ref.decision_trace["plan_success_rate"] = _plan_success_rate
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="plan_trace_record", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                    # ── end plan trace ─────────────────────────────────────────────────
            except Exception as _exc:
                log.warning("swallowed_exception", action="plan_trace_wrap", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
                except Exception as _exc:
                    log.warning("swallowed_exception", action="execution_policy_trace", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
                except Exception as _exc:
                    log.warning("swallowed_exception", action="policy_mode_default", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            # ── Tool results dans decision_trace (fail-open) ──────────────────
            try:
                _ms_tr2 = ms.get(result.mission_id)
                if _ms_tr2 is not None and _tool_run_results:
                    _ms_tr2.decision_trace["tools_executed"] = list(_tool_run_results.keys())
                    _ms_tr2.decision_trace["tool_results_ok"] = [
                        k for k, v in _tool_run_results.items() if v.get("ok")
                    ]
            except Exception as _exc:
                log.warning("swallowed_exception", action="tool_run_results_aggregate", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
                except Exception as _exc:
                    log.warning("swallowed_exception", action="mission_completion_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

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
            except Exception as _exc:
                log.warning("swallowed_exception", action="decision_metrics_record", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
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
            except Exception as _exc:
                log.warning("swallowed_exception", action="mission_event_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            try:
                from core.self_improvement import get_self_improvement_manager
                _sim = get_self_improvement_manager()
                # Analyse asynchrone legere — ne bloque pas la reponse
                _sim.analyze_patterns()  # resultat ignore ici, mis en cache implicitement
            except Exception as _exc:
                log.warning("swallowed_exception", action="self_improvement_pattern_analyze", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            # ── fin Observability ─────────────────────────────────────────────────

        except Exception as e:
            log.error("background_mission_failed", err=str(e)[:100])
            await _ws_emit(f"Erreur interne : {str(e)[:200]}", otype="error", source="system", is_error=True)
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
            await _ws_emit(
                f"Mission terminée en {int((time.time() - _mission_start)*1000)} ms",
                otype="mission_done", source="system",
            )
            _running_missions.discard(result.mission_id)

    background_tasks.add_task(_run_mission)

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

    return JSONResponse(content=_response_data, headers={"X-Bea-Stack": "bea_core", "X-Trace-Time": str(time.time())})

@router.get("/api/v2/task/{task_id}")
async def get_task(task_id: str, x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Statut d'une tâche."""
    _check_auth(x_bea_token, authorization)
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
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Lister les tâches — source='missions' (MissionSystem) ou source='queue' (CoreTaskQueue)."""
    _check_auth(x_bea_token, authorization)
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

    # Inject PENDING_VALIDATION missions as PENDING for approval flow
    pending_val = ms.list_missions(status="PENDING_VALIDATION", limit=50)
    pending_ids = {m.mission_id for m in missions}
    for m in pending_val:
        if m.mission_id not in pending_ids:
            d = m.to_dict()
            d["status"] = "PENDING"
            d["approvalRequired"] = True
            d["approvalReason"] = d.get("note", "Approbation humaine requise")
            missions = list(missions) + [type("M", (), {"to_dict": lambda self, _d=d: _d})()]
            pending_ids.add(m.mission_id)

    return {"ok": True, "data": {
        "tasks": [m.to_dict() for m in missions],
        "total": len(missions),
    }}


@router.get("/api/v2/tasks/{task_id}")
async def get_background_task(
    task_id: str,
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Statut et résultat d'une tâche de fond (CoreTaskQueue)."""
    _check_auth(x_bea_token, authorization)
    from core.task_queue import get_core_task_queue
    q    = get_core_task_queue()
    task = await q.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return {"ok": True, "data": task.to_dict()}


@router.delete("/api/v2/tasks/{task_id}", status_code=200)
async def cancel_background_task(
    task_id: str,
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Annuler une tâche de fond (CoreTaskQueue)."""
    _check_auth(x_bea_token, authorization)
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
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Annuler une mission en cours."""
    _check_auth(x_bea_token, authorization)
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
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Soumettre une mission (interface Flutter — champ `goal` + `mode`)."""
    _check_auth(x_bea_token, authorization)
    try:
        task_req = TaskRequest(input=req.goal, mode=req.mode)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await submit_task(task_req, background_tasks, x_bea_token, authorization)


@router.get("/api/v2/missions")
async def list_missions(
    status: Optional[str] = Query(None),
    limit:  int           = Query(20, ge=1, le=200),
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    _check_auth(x_bea_token, authorization)
    ms       = _get_mission_system()
    missions = ms.list_missions(status=status, limit=limit)
    stats    = ms.stats()
    return {"ok": True, "data": {
        "missions": [m.to_dict() for m in missions],
        "stats":    stats,
    }}


@router.get("/api/v2/missions/{mission_id}")
async def get_mission(mission_id: str, x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    _check_auth(x_bea_token, authorization)
    ms = _get_mission_system()
    r  = ms.get(mission_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' introuvable.")
    data = build_mission_response_data(mission_id, r)
    return {"ok": True, "data": data}


# ══════════════════════════════════════════════════════════════
# AGENTS
# ══════════════════════════════════════════════════════════════

@router.get("/api/v2/agents")
async def list_agents(x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Liste tous les agents enregistrés."""
    _check_auth(x_bea_token, authorization)
    return list_registered_agents()



@router.post("/api/v2/agents/{agent_id}/trigger")
async def trigger_agent(
    agent_id: str,
    req: TriggerRequest,
    background_tasks: BackgroundTasks,
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Déclencher un agent manuellement."""
    _check_auth(x_bea_token, authorization)

    return schedule_agent_trigger(
        background_tasks=background_tasks,
        agent_id=agent_id,
        mission=req.mission,
        get_orchestrator=_get_orchestrator,
        logger=log,
    )

# ══════════════════════════════════════════════════════════════
# COMPATIBILITÉ v1
# ══════════════════════════════════════════════════════════════

@router.post("/api/mission", status_code=201, deprecated=True)
async def legacy_post_mission(
    req: TaskRequest,
    background_tasks: BackgroundTasks,
    x_bea_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Alias v1 → POST /api/v2/task"""
    return await submit_task(req, background_tasks, x_bea_token, authorization)


@router.get("/api/health")
async def legacy_health():
    """Alias v1 → GET /api/v2/health"""
    return await legacy_health_payload()


@router.get("/api/missions", deprecated=True)
async def legacy_missions(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    x_bea_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Alias v1 → GET /api/v2/missions"""
    return await list_missions(
        status=status,
        limit=limit,
        x_bea_token=x_bea_token,
        authorization=authorization,
    )


@router.get("/api/stats", deprecated=True)
async def legacy_stats():
    """Alias v1 → GET /api/v2/metrics. Used by mobile."""
    return legacy_stats_payload(_get_mission_system)


# ── Task approve/reject (Flutter uses these) ──────────────────

@router.post("/api/v2/tasks/{task_id}/approve")
async def approve_task(task_id: str, x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Approve a pending action/task."""
    _check_auth(x_bea_token, authorization)
    return approve_task_payload(task_id)

@router.post("/api/v2/tasks/{task_id}/reject")
async def reject_task(
    task_id: str,
    req: Optional[AbortRequest] = None,
    x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None,
):
    """Reject a pending action/task."""
    _check_auth(x_bea_token, authorization)
    note = req.reason if req else "Rejected via API"
    return reject_task_payload(task_id, note)

# ── Mission-level approve/reject + resumption ────────────────

@router.post("/api/v2/missions/{mission_id}/approve")
async def approve_mission(
    mission_id: str,
    background_tasks: BackgroundTasks,
    req: Optional[ApproveRequest] = None,
    x_bea_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Approve a mission that is PENDING_VALIDATION and resume its execution.
    The approval gate is bypassed on re-run (force_approved=True).
    """
    _check_auth(x_bea_token, authorization)
    note = (req.note if req else None) or "Approved by human supervisor"
    return approve_mission_for_resume(
        mission_id=mission_id,
        note=note,
        mission_system=_get_mission_system(),
        background_tasks=background_tasks,
        get_orchestrator=_get_orchestrator,
        logger=log,
        silent_logger=log,
    )

@router.post("/api/v2/missions/{mission_id}/reject")
async def reject_mission(
    mission_id: str,
    req: Optional[AbortRequest] = None,
    x_bea_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Reject a mission that is PENDING_VALIDATION."""
    _check_auth(x_bea_token, authorization)
    note = (req.reason if req else None) or "Rejected by human supervisor"
    return reject_mission_payload(
        mission_id=mission_id,
        note=note,
        mission_system=_get_mission_system(),
        logger=log,
        silent_logger=log,
    )

# ── System mode (Flutter setMode uses POST /api/system/mode) ──
@router.get("/api/system/mode")
async def get_system_mode(x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Get current system operation mode."""
    _check_auth(x_bea_token, authorization)
    return get_system_mode_payload()


@router.post("/api/system/mode")
async def set_system_mode(req: ModeRequest, x_bea_token: Annotated[Optional[str], Header()] = None, authorization: Annotated[Optional[str], Header()] = None):
    """Change system operation mode (MANUAL / SUPERVISED / AUTO)."""
    _check_auth(x_bea_token, authorization)
    try:
        return set_system_mode_payload(req.mode, req.changed_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

# ── Legacy SSE alias (Flutter may call this path) ─────────────

@router.get("/api/mission/{mission_id}/stream")
# NOTE: /api/v1/missions/{mission_id}/stream is handled by mission_control_router
# (prefix="/api/v1", mounted first at line ~178 in main.py). Duplicate removed.
async def stream_mission_compat(mission_id: str):
    """SSE stream — legacy alias; /api/v1/missions/{id}/stream handled by mission_control."""
    try:
        return await legacy_stream_response(mission_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Livrable export endpoint ───────────────────────────────────────────────────

@router.get("/api/v3/missions/{mission_id}/livrable")
async def get_mission_livrable(
    mission_id: str,
    fmt: str = "markdown",  # "markdown" ou "html"
    x_bea_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Retourne le livrable client generé pour cette mission.
    fmt=markdown -> texte .md
    fmt=html     -> HTML complet pour impression/PDF
    """
    _check_auth(x_bea_token, authorization)
    try:
        from pathlib import Path
        livrable_dir = Path('/opt/beamax-app/workspace/livrables')
        # Chercher un fichier contenant le mission_id court
        mid_short = mission_id[:8]
        candidates = list(livrable_dir.glob(f'*{mid_short}*.md'))

        if not candidates:
            # Générer à la demande si la mission est COMPLETED
            ms = _get_mission_system()
            m = ms.get(mission_id)
            if not m:
                raise HTTPException(status_code=404, detail="Mission not found")
            result = m.get('result', '') or m.get('output', '')
            if not result:
                raise HTTPException(status_code=404, detail="No result available")
            goal = m.get('goal', '')
            from core.livrable_export import LivrableExport
            exp = LivrableExport()
            paths = exp.save(result, '', goal, mission_id)
            md_path = Path(paths['markdown'])
            html_path = Path(paths['html'])
        else:
            md_path = candidates[0]
            html_path = md_path.with_suffix('.html')

        if fmt == 'html' and html_path.exists():
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=html_path.read_text(encoding='utf-8'))
        elif md_path.exists():
            content = md_path.read_text(encoding='utf-8')
            return {"ok": True, "data": {"content": content, "filename": md_path.name, "format": "markdown"}}
        else:
            raise HTTPException(status_code=404, detail="Livrable not found")
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}
