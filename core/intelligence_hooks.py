"""
JARVIS MAX — Intelligence Hooks
===================================
Wires observability, capability, and self-improvement intelligence
into the runtime execution path without modifying existing code.

These hooks are called from the convergence API layer and optionally
from the orchestration bridge. Each hook is fail-open (never blocks
the main execution path).

Feature flag: JARVIS_INTELLIGENCE_HOOKS=1 (default OFF)

Hooks:
    1. post_mission_submit  — after mission creation
    2. post_step_complete   — after each step
    3. post_mission_complete — after mission finishes
    4. periodic_health      — called from /system/status
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import os

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    log = structlog.get_logger(__name__)


def _hooks_enabled() -> bool:
    return os.environ.get("JARVIS_INTELLIGENCE_HOOKS", "").lower() in ("1", "true", "yes")


def post_mission_submit(mission_id: str, goal: str, **kwargs) -> dict:
    """
    Called after a mission is submitted.

    Actions:
    - Record in observability intelligence
    - Query knowledge graph for similar missions (pre-plan context)
    - Log to self-improvement signals

    Returns enrichment data (empty if hooks disabled).
    """
    if not _hooks_enabled():
        return {}

    enrichment = {}
    try:
        # Knowledge graph: find similar missions
        try:
            from core.memory.knowledge_graph import get_knowledge_graph, find_similar_missions
            graph = get_knowledge_graph(auto_load=True)
            similar = find_similar_missions(graph, goal=goal, top_k=3)
            if similar:
                enrichment["similar_missions"] = [
                    {"id": s["mission_id"], "similarity": s["similarity"]}
                    for s in similar[:3]
                ]
        except ImportError as _exc:
            log.warning("swallowed_exception", action="core_planner_hook_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        except Exception as e:
            log.debug("hook_kg_err", err=str(e)[:60])

    except Exception as e:
        log.debug("post_submit_hook_err", err=str(e)[:60])

    return enrichment


def post_step_complete(
    mission_id: str,
    step_id: str,
    success: bool,
    tool: str = "",
    duration_s: float = 0.0,
    error_type: str = "",
    **kwargs,
) -> None:
    """
    Called after each mission step completes.

    Actions:
    - Record tool metric in observability
    - Update tool performance model in evolution engine

    Never raises.
    """
    if not _hooks_enabled():
        return

    try:
        # Observability: record tool metric
        if tool:
            try:
                from core.observability_intelligence import record_tool_metric, ToolMetricEntry
                record_tool_metric(ToolMetricEntry(
                    tool=tool,
                    success=success,
                    duration_ms=duration_s * 1000,
                    error_type=error_type,
                ))
            except ImportError as _exc:
                log.warning("swallowed_exception", action="meta_chat_hook_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Tool evolution: update performance model
        if tool:
            try:
                from core.tools.evolution_engine import update_tool_performance
                update_tool_performance(
                    tool=tool, success=success,
                    latency_ms=duration_s * 1000,
                    error_type=error_type,
                    mission_id=mission_id,
                )
            except ImportError as _exc:
                log.warning("swallowed_exception", action="mission_complete_hook_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    except Exception as e:
        log.debug("post_step_hook_err", err=str(e)[:60])


def post_mission_complete(
    mission_id: str,
    goal: str,
    success: bool,
    duration_s: float = 0.0,
    agents_used: list[str] | None = None,
    tools_used: list[str] | None = None,
    errors: list[str] | None = None,
    strategy: str = "",
    **kwargs,
) -> None:
    """
    Called after a mission completes.

    Actions:
    - Record mission metric in observability
    - Ingest into knowledge graph
    - Record agent metrics

    Never raises.
    """
    if not _hooks_enabled():
        return

    try:
        # Observability: mission metric
        try:
            from core.observability_intelligence import record_mission_metric, MissionMetricEntry
            record_mission_metric(MissionMetricEntry(
                mission_id=mission_id,
                status="COMPLETED" if success else "FAILED",
                duration_s=duration_s,
                agents_used=agents_used or [],
                tools_used=tools_used or [],
                failure_category=errors[0] if errors else "",
            ))
        except ImportError as _exc:
            log.warning("swallowed_exception", action="mission_failed_hook_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Knowledge graph: ingest mission log
        try:
            from core.memory.knowledge_graph import (
                get_knowledge_graph, ingest_mission_log, MissionLog,
            )
            graph = get_knowledge_graph(auto_load=True)
            ingest_mission_log(graph, MissionLog(
                mission_id=mission_id,
                goal=goal,
                status="COMPLETED" if success else "FAILED",
                agents_used=agents_used or [],
                tools_used=tools_used or [],
                errors=errors or [],
                strategy=strategy,
                duration_s=duration_s,
            ))
        except ImportError as _exc:
            log.warning("swallowed_exception", action="mission_resume_hook_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Agent metrics
        if agents_used:
            try:
                from core.observability_intelligence import record_agent_metric, AgentMetricEntry
                for agent in agents_used:
                    record_agent_metric(AgentMetricEntry(
                        agent=agent,
                        success=success,
                        duration_s=duration_s / max(len(agents_used), 1),
                        tools_used=tools_used or [],
                    ))
            except ImportError as _exc:
                log.warning("swallowed_exception", action="mission_paused_hook_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    except Exception as e:
        log.debug("post_mission_hook_err", err=str(e)[:60])


def periodic_health() -> dict:
    """
    Periodic health check that gathers intelligence layer status.

    Called from /api/v3/system/status. Returns summary dict.
    """
    if not _hooks_enabled():
        return {"hooks_enabled": False}

    status = {"hooks_enabled": True, "components": {}}

    try:
        # Observability health
        try:
            from core.observability_intelligence import get_system_health
            status["components"]["observability"] = get_system_health()
        except ImportError:
            status["components"]["observability"] = {"status": "not_installed"}

        # Knowledge graph stats
        try:
            from core.memory.knowledge_graph import get_knowledge_graph
            graph = get_knowledge_graph(auto_load=False)
            status["components"]["knowledge_graph"] = graph.stats()
        except ImportError:
            status["components"]["knowledge_graph"] = {"status": "not_installed"}

        # Tool evolution pending proposals
        try:
            from core.tools.evolution_engine import _PROPOSALS, _WEAKNESSES
            status["components"]["tool_evolution"] = {
                "pending_proposals": len(_PROPOSALS),
                "tracked_weaknesses": len(_WEAKNESSES),
            }
        except ImportError:
            status["components"]["tool_evolution"] = {"status": "not_installed"}

    except Exception as e:
        log.debug("periodic_health_err", err=str(e)[:60])

    return status
