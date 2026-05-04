"""
EventEmitter — thin wrapper that pushes structured events to MissionStateStore.
Called by agents and orchestrator throughout mission execution.
Fail-open: if MissionStateStore is unavailable, events are silently dropped.
"""
from __future__ import annotations

# Event type constants
MISSION_CREATED   = "MISSION_CREATED"
AGENT_STARTED     = "AGENT_STARTED"
AGENT_PROGRESS    = "AGENT_PROGRESS"
AGENT_RESULT      = "AGENT_RESULT"
AGENT_FAILED      = "AGENT_FAILED"
MISSION_COMPLETED = "MISSION_COMPLETED"
MISSION_ABORTED   = "MISSION_ABORTED"

_TYPE_MAP = None


def _get_type_map():
    global _TYPE_MAP
    if _TYPE_MAP is None:
        from api.models import LogEventType
        _TYPE_MAP = {
            MISSION_CREATED:   LogEventType.STATUS_CHANGE,
            AGENT_STARTED:     LogEventType.AGENT_DECISION,
            AGENT_PROGRESS:    LogEventType.AGENT_DECISION,
            AGENT_RESULT:      LogEventType.TOOL_RESULT,
            AGENT_FAILED:      LogEventType.ERROR,
            MISSION_COMPLETED: LogEventType.STATUS_CHANGE,
            MISSION_ABORTED:   LogEventType.STATUS_CHANGE,
        }
    return _TYPE_MAP


def emit(
    mission_id: str,
    event_type: str,
    message: str,
    agent: str = "",
    step: int = 0,
    status: str = "",
    payload: dict | None = None,
) -> None:
    """Push a structured event to MissionStateStore. Never raises."""
    try:
        from api.mission_store import MissionStateStore
        from api.models import MissionLogEvent

        type_map = _get_type_map()
        from api.models import LogEventType
        log_type = type_map.get(event_type, LogEventType.AGENT_DECISION)

        event = MissionLogEvent(
            mission_id=mission_id,
            event_type=log_type,
            message=message,
            agent_id=agent,
            data={
                "event_type": event_type,
                "step": step,
                "status": status,
                **(payload or {}),
            },
        )
        MissionStateStore.get().append_log(event)
    except Exception:
        pass  # fail-open — never block execution for observability


def emit_mission_created(mission_id: str, goal: str) -> None:
    emit(mission_id, MISSION_CREATED, f"Mission created: {goal[:200]}", status="CREATED")


def emit_agent_started(mission_id: str, agent: str, step: int = 0) -> None:
    emit(mission_id, AGENT_STARTED, f"Agent {agent} started", agent=agent, step=step, status="RUNNING")


def emit_agent_progress(mission_id: str, agent: str, message: str, step: int = 0) -> None:
    emit(mission_id, AGENT_PROGRESS, message, agent=agent, step=step, status="RUNNING")


def emit_agent_result(mission_id: str, agent: str, result: str, step: int = 0) -> None:
    """Store structured agent result. Parses JSON if available, falls back to raw string."""
    import json as _json

    structured: dict = {
        "reasoning": None,
        "decision": None,
        "confidence": None,
        "risks": None,
        "suggestions": None,
        "raw": result[:500],
    }

    # Best-effort JSON parse
    try:
        parsed = _json.loads(result)
        if isinstance(parsed, dict):
            structured["reasoning"]   = parsed.get("reasoning") or parsed.get("justification") or parsed.get("analysis")
            structured["decision"]    = parsed.get("decision") or parsed.get("verdict") or parsed.get("action")
            conf = parsed.get("confidence") or parsed.get("score") or 0.0
            structured["confidence"]  = float(conf) if conf is not None else 0.0
            structured["risks"]       = parsed.get("risks") or parsed.get("issues") or []
            structured["suggestions"] = (
                parsed.get("suggestions") or parsed.get("improvements")
                or parsed.get("next_actions") or []
            )
    except Exception:
        # Raw string fallback
        structured["reasoning"] = result[:500]

    emit(
        mission_id, AGENT_RESULT, result[:500],
        agent=agent, step=step, status="RUNNING",
        payload={"agent_result": structured, "full_output": result},
    )


def emit_agent_failed(mission_id: str, agent: str, error: str, step: int = 0) -> None:
    emit(mission_id, AGENT_FAILED, f"Agent {agent} failed: {error}", agent=agent, step=step, status="FAILED")


def emit_mission_completed(mission_id: str, summary: str = "") -> None:
    emit(mission_id, MISSION_COMPLETED, summary or "Mission completed", status="DONE")


def emit_mission_aborted(mission_id: str, reason: str = "") -> None:
    emit(mission_id, MISSION_ABORTED, reason or "Mission aborted", status="CANCELLED")
