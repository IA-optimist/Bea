"""
core/result_aggregator.py — Aggregation layer for mission results.

Responsibilities:
- Collect agent outputs from action queue
- Resolve final status (FAILED if any critical agent fails, COMPLETED otherwise)
- Generate final summary
- Return FinalOutput envelope
"""
from __future__ import annotations

import time
import logging

from core.schemas.final_output import (
    FinalOutput, AgentOutput, AgentError, DecisionStep, OutputMetrics,
)

log = logging.getLogger("jarvis.result_aggregator")


def aggregate_mission_result(
    mission_id: str,
    mission_status: str = "DONE",
    start_time: float = 0.0,
    summary: str = "",
) -> FinalOutput:
    """
    Aggregate all agent outputs for a mission into a FinalOutput envelope.

    Pulls from:
    - Action queue (executor results)
    - MissionStateStore (agent log events)
    - MissionSystem (decision trace, metadata)
    """
    agent_outputs: list[AgentOutput] = []
    decision_trace_raw: dict = {}

    # 1. Collect from action queue
    try:
        from core.action_queue import get_action_queue
        aq = get_action_queue()
        actions = aq.for_mission(mission_id)
        for a in actions:
            result_text = getattr(a, "result", "") or ""
            raw_target = getattr(a, "target", "") or ""
            agent_name = (
                raw_target.replace("agent:", "")
                if raw_target.startswith("agent:")
                else (getattr(a, "description", "")[:40] or "agent")
            )
            status = "SUCCESS" if getattr(a, "status", "") == "EXECUTED" else (
                "ERROR" if getattr(a, "status", "") == "FAILED" else "SKIPPED"
            )
            error = None
            if status == "ERROR":
                error = AgentError(
                    type="execution_failure",
                    message=result_text[:200] if result_text else "Agent execution failed",
                    recoverable=False,
                )
            agent_outputs.append(AgentOutput(
                agent_name=agent_name,
                status=status,
                output_text=result_text[:3000] if result_text else None,
                error=error,
            ))
    except Exception as e:
        log.warning("aggregate_action_queue_failed", extra={"error": str(e)})

    # 1b. Collect tool usage trace from capability registry
    try:
        from core.capabilities.registry import get_capability_registry
        cap_reg = get_capability_registry()
        # Add capability stats to decision trace
        decision_trace_raw["capability_stats"] = cap_reg.stats()
    except Exception:
        _silent_log.debug("suppressed_exception", src='result_aggregator.py')

    # 2. Collect decision trace from mission
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        mission = ms.get(mission_id)
        if mission:
            decision_trace_raw = getattr(mission, "decision_trace", {}) or {}
            if not summary:
                summary = getattr(mission, "summary", "") or getattr(mission, "plan_summary", "") or ""
            if start_time <= 0:
                start_time = getattr(mission, "created_at", 0.0)
    except Exception as e:
        log.warning("aggregate_mission_data_failed", extra={"error": str(e)})

    # 3. Resolve final status
    status_map = {
        "DONE": "COMPLETED", "REJECTED": "CANCELLED", "BLOCKED": "FAILED",
        "COMPLETED": "COMPLETED", "FAILED": "FAILED", "CANCELLED": "CANCELLED",
    }
    canonical_status = status_map.get(str(mission_status).upper(), "COMPLETED")

    # Override: if any agent failed, mission is FAILED
    has_critical_failure = any(
        a.status == "ERROR" and (a.error is None or not a.error.recoverable)
        for a in agent_outputs
    )
    if has_critical_failure and canonical_status == "COMPLETED":
        canonical_status = "FAILED"

    # 4. Build decision steps
    decision_steps = []
    for key in ("mission_type", "complexity", "risk_score", "confidence_score",
                "selected_agents", "skipped_agents"):
        val = decision_trace_raw.get(key)
        if val is not None:
            decision_steps.append(DecisionStep(phase=key, result=str(val)))

    # 5. Metrics
    duration = (time.time() - start_time) if start_time > 0 else None
    metrics = OutputMetrics(duration_seconds=round(duration, 2) if duration else None)

    # 6. Generate summary if missing
    if not summary and agent_outputs:
        ok = sum(1 for a in agent_outputs if a.status == "SUCCESS")
        total = len(agent_outputs)
        summary = f"{ok}/{total} agents completed successfully."

    # Get trace_id from context or decision_trace
    trace_id = decision_trace_raw.get("trace_id", "")
    if not trace_id:
        try:
            from core.observability.event_envelope import get_trace_id
            trace_id = get_trace_id() or ""
        except Exception:
            _silent_log.debug("suppressed_exception", src='result_aggregator.py')

    return FinalOutput(
        mission_id=mission_id,
        trace_id=trace_id,
        status=canonical_status,
        summary=summary[:500],
        agent_outputs=agent_outputs,
        decision_trace=decision_steps,
        metrics=metrics,
    )
