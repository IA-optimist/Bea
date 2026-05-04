"""
Anti tool-spam protection.
Tracks per-task tool usage and enforces limits.
Fail-open: if check fails, always returns (allowed=True).
"""
import logging
from collections import defaultdict
from typing import Dict, List
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger(__name__)

MAX_SAME_TOOL_STREAK = 4
MAX_RETRY_PER_TASK = 3
MAX_TOTAL_TOOLS_PER_OBJECTIVE = 30

# In-memory state (resets on container restart — intentional, lightweight)
_task_tool_history: Dict[str, List[str]] = defaultdict(list)
_objective_tool_counts: Dict[str, int] = defaultdict(int)

def check_tool_allowed(tool_name: str, task_id: str = "", objective_id: str = "") -> dict:
    """
    Returns {allowed: bool, reason: str, action: str}.
    action: 'proceed' | 'replan' | 'request_validation' | 'stop'
    """
    try:
        history = _task_tool_history.get(task_id, [])
        obj_count = _objective_tool_counts.get(objective_id, 0)

        # Check streak
        if len(history) >= MAX_SAME_TOOL_STREAK:
            streak = history[-MAX_SAME_TOOL_STREAK:]
            if all(t == tool_name for t in streak):
                logger.warning(
                    "[AntiSpam] streak limit: tool=%s task=%s streak=%d",
                    tool_name, task_id, MAX_SAME_TOOL_STREAK
                )
                return {"allowed": False, "reason": f"same_tool_streak_{MAX_SAME_TOOL_STREAK}", "action": "replan"}

        # Check objective total
        if obj_count >= MAX_TOTAL_TOOLS_PER_OBJECTIVE:
            logger.warning("[AntiSpam] objective tool limit reached: obj=%s count=%d", objective_id, obj_count)
            return {"allowed": False, "reason": "objective_tool_limit", "action": "request_validation"}

        return {"allowed": True, "reason": "ok", "action": "proceed"}

    except Exception as e:
        logger.warning("[AntiSpam] check failed (fail-open): %s", e)
        return {"allowed": True, "reason": "check_error_failopen", "action": "proceed"}


def record_tool_used(tool_name: str, task_id: str = "", objective_id: str = "") -> None:
    """Record that a tool was used (for streak/count tracking)."""
    try:
        if task_id:
            _task_tool_history[task_id].append(tool_name)
            # Keep last 50 per task
            if len(_task_tool_history[task_id]) > 50:
                _task_tool_history[task_id] = _task_tool_history[task_id][-50:]
        if objective_id:
            _objective_tool_counts[objective_id] += 1
    except Exception as e:
        logger.warning("[AntiSpam] record failed: %s", e)


def reset_task(task_id: str) -> None:
    """Clear tracking state for a completed/failed task."""
    try:
        _task_tool_history.pop(task_id, None)
    except Exception:
        _silent_log.debug("suppressed_exception", src='anti_spam.py')
