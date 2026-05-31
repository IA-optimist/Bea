"""
ToolRunner — exécute les tools pertinents AVANT les agents.
Injecte les résultats dans le contexte comme préfixe de prompt.
"""
from __future__ import annotations
import logging
import time

logger = logging.getLogger("jarvis.tool_runner")
log = logger  # alias for M3 emitter

# Pre-execution context gathering tools (READ-ONLY, safe to run before agents)
# NOTE: This is DIFFERENT from core.tool_registry._MISSION_TOOLS which maps
# mission execution tools (write-capable). This dict maps pre-execution
# read-only tools used to gather context BEFORE agent runs.
# See core/architecture_ownership.py for ownership documentation.
_PRE_EXEC_TOOLS: dict[str, list[str]] = {
    "coding_task":       ["read_file", "shell_command"],
    "debug_task":        ["read_file", "shell_command"],
    "system_task":       ["shell_command"],
    "research_task":     ["http_get", "vector_search"],
    "info_query":        ["vector_search"],
    "architecture_task": ["read_file", "vector_search"],
    "evaluation_task":   ["shell_command", "vector_search"],
}
# Alias for backward compatibility
_MISSION_TOOLS = _PRE_EXEC_TOOLS


def _default_params(tool_name: str, goal: str) -> dict:
    if tool_name == "shell_command":
        return {"cmd": "docker ps --format '{{.Names}} {{.Status}}' && echo '---' && ls workspace/ 2>/dev/null || true"}
    if tool_name == "read_file":
        return {"path": "workspace/last_result.txt", "max_lines": 50}
    if tool_name == "http_get":
        return {"url": "https://httpbin.org/get?q=" + goal[:50].replace(" ", "+")}
    if tool_name == "vector_search":
        return {"query": goal[:200], "collection": "jarvis_memory", "top_k": 3}
    return {}


def run_tools_for_mission(
    goal: str,
    mission_type: str,
    approval_mode: str = "SUPERVISED",
    max_tools: int = 2,
    mission_id: str = "",
) -> tuple[str, dict]:
    """
    Exécute les tools pertinents pour la mission.
    Uses execution engine for health check, adaptive retry, and fallback.

    Returns:
        context_prefix: str — texte à injecter en préfixe du prompt agent
        tool_results: dict — résultats bruts pour decision_trace
    """
    try:
        tools_to_run = _MISSION_TOOLS.get(mission_type, [])[:max_tools]
        if not tools_to_run:
            return "", {}

        # Try intelligent execution first (fail-open to legacy)
        _use_engine = True
        try:
            from core.safety_controls import is_execution_engine_enabled
            if not is_execution_engine_enabled():
                _use_engine = False
        except ImportError as _exc:
            log.warning("swallowed_exception", action="tool_runner_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        if _use_engine:
            try:
                from core.execution_engine import (
                    execute_tool_intelligently, ExecutionTelemetry,  # noqa: F401
                    record_telemetry, record_recovery,  # noqa: F401
                )
            except ImportError:
                _use_engine = False

        if _use_engine:
            return _run_with_engine(
                goal, tools_to_run, approval_mode, mission_id,
            )

        # Legacy path
        from core.tool_executor import get_tool_executor
        executor = get_tool_executor()

        results = {}
        context_parts = ["[CONTEXT RÉEL — données collectées avant exécution]"]

        for tool_name in tools_to_run:
            try:
                params = _default_params(tool_name, goal)
                result = executor.execute(tool_name, params, approval_mode)
                results[tool_name] = result

                if result.get("ok"):
                    output = result.get("result", "")[:500]
                    context_parts.append(f"[{tool_name.upper()}]\n{output}")
                    logger.info("tool_executed tool=%s ok=True chars=%d", tool_name, len(output))
                else:
                    err = result.get("error", "unknown")
                    context_parts.append(f"[{tool_name.upper()}] indisponible: {err}")
                    logger.warning("tool_failed tool=%s error=%s", tool_name, err)
            except Exception as e:
                results[tool_name] = {"ok": False, "error": str(e)}
                logger.debug("tool_exception tool=%s err=%s", tool_name, str(e))

        context_prefix = "\n".join(context_parts) + "\n[FIN CONTEXT]\n\n"
        return context_prefix, results

    except Exception as e:
        logger.debug("tool_runner_failed_open err=%s", str(e))
        return "", {}


def _run_with_engine(
    goal: str,
    tools_to_run: list[str],
    approval_mode: str,
    mission_id: str,
) -> tuple[str, dict]:
    """Execute tools using the intelligent execution engine."""
    from core.execution_engine import (
        execute_tool_intelligently, ExecutionTelemetry,
        record_telemetry, record_recovery,
    )

    telemetry = ExecutionTelemetry(mission_id=mission_id, started_at=time.time())
    results = {}
    context_parts = ["[CONTEXT RÉEL — données collectées avant exécution]"]

    for i, tool_name in enumerate(tools_to_run):
        params = _default_params(tool_name, goal)
        result, step_tel = execute_tool_intelligently(
            tool_name=tool_name,
            params=params,
            mission_id=mission_id,
            step_id=f"pre-{i}",
            approval_mode=approval_mode,
            max_retries=2,
            allow_fallback=True,
        )

        telemetry.steps.append(step_tel)
        telemetry.total_tools_called += 1
        telemetry.total_retries += step_tel.retries
        if step_tel.fallback_used:
            telemetry.total_fallbacks += 1
        if step_tel.health_status == "failing":
            telemetry.tools_skipped_unhealthy += 1

        # Record recovery if it happened
        if step_tel.retries > 0 or step_tel.fallback_used:
            record_recovery(
                tool=tool_name,
                error_type=step_tel.error_type,
                recovery_type="fallback" if step_tel.fallback_used else "retry_adapted",
                fallback_tool=step_tel.fallback_used,
                success=step_tel.success,
            )

        actual_tool = step_tel.fallback_used or tool_name
        results[actual_tool] = result

        if result.get("ok"):
            output = result.get("result", "")[:500]
            context_parts.append(f"[{actual_tool.upper()}]\n{output}")
            logger.info("tool_executed tool=%s ok=True chars=%d", actual_tool, len(output))
        else:
            err = result.get("error", "unknown")[:100]
            context_parts.append(f"[{actual_tool.upper()}] indisponible: {err}")
            logger.warning("tool_failed tool=%s error=%s", actual_tool, err)

    telemetry.finished_at = time.time()
    record_telemetry(telemetry)

    # ── Lifecycle: tools_executed ──────────────────────────────────────
    if mission_id:
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            get_lifecycle_tracker().record(mission_id, "tools_executed")
        except Exception as _exc:
            log.warning("swallowed_exception", action="tool_runner_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    context_prefix = "\n".join(context_parts) + "\n[FIN CONTEXT]\n\n"
    return context_prefix, results


def format_goal_with_context(goal: str, context_prefix: str) -> str:
    """Injecte le contexte des tools en tête du goal."""
    if not context_prefix:
        return goal
    return f"{context_prefix}MISSION : {goal}"
