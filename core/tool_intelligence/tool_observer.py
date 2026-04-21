"""
Observes every tool call and persists usage data.
Fail-open: any error → silent log, no crash.
Storage: JSON fallback (workspace/tool_intelligence/observations.json)
"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)
_OBS_PATH = Path("workspace/tool_intelligence/observations.json")

def record_tool_call(
    tool_name: str,
    success: bool,
    execution_time: float = 0.0,
    retry_count: int = 0,
    rollback_triggered: bool = False,
    error_type: str = "",
    objective_id: str = "",
    task_id: str = "",
    sequence_position: int = 0,
    difficulty_label: str = "",
    output_quality: float = -1.0,
) -> dict:
    """Record one tool usage. Returns the entry dict. Never raises."""
    try:
        entry = {
            "tool_name": tool_name,
            "success": success,
            "execution_time": round(execution_time, 3),
            "retry_count": retry_count,
            "rollback_triggered": rollback_triggered,
            "error_type": error_type,
            "objective_id": objective_id,
            "task_id": task_id,
            "sequence_position": sequence_position,
            "difficulty_label": difficulty_label,
            "output_quality": output_quality,
            "timestamp": time.time(),
        }
        _append_observation(entry)
        return entry
    except Exception as e:
        logger.warning("[ToolObserver] record failed: %s", e)
        return {}

def _append_observation(entry: dict) -> None:
    try:
        _OBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if _OBS_PATH.exists():
            try:
                existing = json.loads(_OBS_PATH.read_text("utf-8"))
            except Exception:
                existing = []
        existing.append(entry)
        # Keep last 10000 entries
        if len(existing) > 10000:
            existing = existing[-10000:]
        tmp = _OBS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2), "utf-8")
        tmp.replace(_OBS_PATH)
    except Exception as e:
        logger.warning("[ToolObserver] _append failed: %s", e)

def get_observations(tool_name: str = "", limit: int = 500) -> list:
    """Load observations, optionally filtered by tool_name."""
    try:
        if not _OBS_PATH.exists():
            return []
        data = json.loads(_OBS_PATH.read_text("utf-8"))
        if tool_name:
            data = [d for d in data if d.get("tool_name") == tool_name]
        return data[-limit:]
    except Exception as e:
        logger.warning("[ToolObserver] get failed: %s", e)
        return []
