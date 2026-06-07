"""
BEA — Execution Engine (core/ version)
=============================
NOTE: A parallel executor/execution_engine.py (542L) also exists.
  - core/execution_engine.py (this file) — higher-level wrapper
  - executor/execution_engine.py — task DAG execution
Both are active. core/ wraps tool_executor; executor/ handles DAG tasks.

Wraps tool_executor + tool_runner with intelligent execution:

1. Pre-execution health check (skip known-broken tools)
2. Adaptive retry with parameter variation
3. Fallback tool chains (if primary fails, try alternatives)
4. Per-step telemetry (duration, errors, retries per step)
5. Post-mission quality evaluation
6. Recovery strategy memory (what recoveries worked)

This is NOT a parallel execution system. It wraps the existing
tool_executor.execute() call with intelligence around it.

Called from:
- tool_runner.run_tools_for_mission() (enhanced version)
- api/main.py _run_mission() (post-execution evaluation)

Zero external dependencies. Fail-open everywhere.
"""
from __future__ import annotations

import structlog
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = structlog.get_logger("bea.execution_engine")
log = logger  # M3 emitter alias

# ═══════════════════════════════════════════════════════════════
# CONFIGURABLE EXECUTION LIMITS
# ═══════════════════════════════════════════════════════════════

# Max seconds a single tool execution can take before timeout
MAX_TOOL_TIMEOUT_S = int(os.environ.get("BEA_MAX_TOOL_TIMEOUT", "120"))

# Max retries per tool invocation (overridable via env)
MAX_RETRIES = int(os.environ.get("BEA_MAX_RETRIES", "3"))

# Max total execution time for a mission (seconds)
MAX_MISSION_DURATION_S = int(os.environ.get("BEA_MAX_MISSION_DURATION", "600"))

# Max steps per mission (prevent runaway decomposition)
MAX_MISSION_STEPS = int(os.environ.get("BEA_MAX_MISSION_STEPS", "20"))


def get_execution_limits() -> dict:
    """Return current execution limits (for cockpit / API)."""
    return {
        "max_tool_timeout_s": MAX_TOOL_TIMEOUT_S,
        "max_retries": MAX_RETRIES,
        "max_mission_duration_s": MAX_MISSION_DURATION_S,
        "max_mission_steps": MAX_MISSION_STEPS,
    }

# ═══════════════════════════════════════════════════════════════
# 1. TOOL HEALTH GATE
# ═══════════════════════════════════════════════════════════════

def check_tool_health(tool_name: str) -> dict:
    """
    Pre-execution health check. Returns:
    {"healthy": bool, "status": str, "recommendation": str}

    If unhealthy, suggests alternative or advises skip.
    """
    result = {"healthy": True, "status": "unknown", "recommendation": "proceed"}

    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        stats = tracker.get_stats(tool_name)

        if not stats or stats.total_calls < 3:
            result["status"] = "insufficient_data"
            return result

        result["status"] = stats.health_status

        if stats.health_status == "failing":
            result["healthy"] = False
            result["recommendation"] = "skip_or_fallback"
            result["success_rate"] = round(stats.recent_success_rate, 3)
            result["last_error"] = stats.last_error[:100]

        elif stats.health_status == "degraded":
            result["healthy"] = True  # still try, but log warning
            result["recommendation"] = "proceed_with_caution"
            result["success_rate"] = round(stats.recent_success_rate, 3)

    except Exception:
        logger.debug("swallowed_exception", exc_info=True)

    return result


# ═══════════════════════════════════════════════════════════════
# 2. FALLBACK TOOL CHAINS
# ═══════════════════════════════════════════════════════════════

# Alternative tools when primary fails
TOOL_ALTERNATIVES = {
    "shell_command":    ["run_command_safe"],
    "run_command_safe": ["shell_command"],
    "read_file":        ["search_codebase"],
    "search_codebase":  ["read_file"],
    "vector_search":    ["search_codebase"],
    "http_get":         ["fetch_url", "check_url_status"],
    "write_file":       ["file_create"],
    "check_logs":       ["run_command_safe"],
    "test_endpoint":    ["http_get", "check_url_status"],
}


def get_fallback_tool(failed_tool: str) -> Optional[str]:
    """
    Get the best alternative tool when primary fails.
    Checks alternatives' health before recommending.
    """
    alternatives = TOOL_ALTERNATIVES.get(failed_tool, [])
    if not alternatives:
        return None

    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        best = tracker.get_tool_for_capability(alternatives, min_reliability=0.3)
        return best
    except Exception:
        return alternatives[0] if alternatives else None


# ═══════════════════════════════════════════════════════════════
# 3. ADAPTIVE RETRY
# ═══════════════════════════════════════════════════════════════

def should_retry(tool_name: str, attempt: int) -> bool:
    """
    Decide whether retrying is worthwhile based on telemetry.
    Returns False if the tool shows volatile behavior (oscillating success/failure).
    """
    try:
        from core.tool_performance_tracker import get_tool_performance_tracker
        tracker = get_tool_performance_tracker()
        stats = tracker.get_stats(tool_name)
        if not stats or stats.total_calls < 5:
            return True  # insufficient data, try

        # Volatility check: if recent window alternates, retrying wastes time
        window = stats._recent_window[-10:] if len(stats._recent_window) >= 10 else stats._recent_window
        if len(window) >= 6:
            flips = sum(1 for i in range(1, len(window)) if window[i] != window[i-1])
            volatility = flips / (len(window) - 1)
            if volatility > 0.6:
                # Highly volatile — retry unlikely to help
                logger.info(
                    "retry_skipped_volatile",
                    tool=tool_name,
                    volatility=round(volatility, 2),
                    attempt=attempt,
                )
                return attempt < 1  # allow 1 retry max for volatile tools

        # If tool is consistently failing (< 20%), skip retry
        if stats.recent_success_rate < 0.20:
            logger.info("retry_skipped_low_success", tool=tool_name, rate=stats.recent_success_rate)
            return False

    except Exception:
        logger.debug("swallowed_exception", exc_info=True)

    return True


def adapt_params(tool_name: str, params: dict, attempt: int, last_error: str) -> dict:
    """
    Vary parameters on retry based on error type.
    Returns modified params dict.
    """
    adapted = dict(params)

    # Timeout errors → increase timeout
    if "timeout" in last_error.lower() or "timed out" in last_error.lower():
        current_timeout = adapted.get("timeout", 10)
        adapted["timeout"] = min(current_timeout * 2, 60)
        logger.debug("adaptive_retry_timeout", tool=tool_name, new_timeout=adapted["timeout"])

    # File not found → try workspace prefix
    if "not found" in last_error.lower() or "no such file" in last_error.lower():
        path = adapted.get("path", "")
        if path and not path.startswith("workspace/"):
            adapted["path"] = f"workspace/{path}"
            logger.debug("adaptive_retry_path", tool=tool_name, new_path=adapted["path"])

    # Connection errors → add retry delay
    if "connection" in last_error.lower() or "refused" in last_error.lower():
        adapted["_retry_delay"] = min(1.0 * (attempt + 1), 5.0)

    # Reduce max_lines on large file reads
    if tool_name in ("read_file",) and "too large" in last_error.lower():
        adapted["max_lines"] = max(10, adapted.get("max_lines", 50) // 2)

    return adapted


# ═══════════════════════════════════════════════════════════════
# 4. EXECUTION TELEMETRY
# ═══════════════════════════════════════════════════════════════

@dataclass
class StepTelemetry:
    """Telemetry for a single execution step."""
    step_id: str
    tool: str
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0
    success: bool = False
    retries: int = 0
    fallback_used: str = ""
    error_type: str = ""
    error_msg: str = ""
    params_adapted: bool = False
    health_status: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "duration_ms": round(self.duration_ms, 1),
            "success": self.success,
            "retries": self.retries,
            "fallback_used": self.fallback_used,
            "error_type": self.error_type,
            "params_adapted": self.params_adapted,
            "health_status": self.health_status,
        }


@dataclass
class ExecutionTelemetry:
    """Full execution telemetry for a mission."""
    mission_id: str
    steps: list[StepTelemetry] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    total_tools_called: int = 0
    total_retries: int = 0
    total_fallbacks: int = 0
    tools_skipped_unhealthy: int = 0

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at) * 1000 if self.finished_at else 0

    @property
    def success_rate(self) -> float:
        if not self.steps:
            return 0.0
        return sum(1 for s in self.steps if s.success) / len(self.steps)

    @property
    def stability_score(self) -> float:
        """0.0-1.0 — higher = more stable execution."""
        if not self.steps:
            return 0.5
        sr = self.success_rate
        retry_penalty = min(self.total_retries * 0.05, 0.3)
        fallback_penalty = min(self.total_fallbacks * 0.1, 0.3)
        return max(0.0, sr - retry_penalty - fallback_penalty)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "duration_ms": round(self.duration_ms, 1),
            "total_tools_called": self.total_tools_called,
            "total_retries": self.total_retries,
            "total_fallbacks": self.total_fallbacks,
            "tools_skipped_unhealthy": self.tools_skipped_unhealthy,
            "success_rate": round(self.success_rate, 3),
            "stability_score": round(self.stability_score, 3),
            "steps": [s.to_dict() for s in self.steps],
        }


# In-memory telemetry buffer (last 200 missions)
_telemetry_buffer: list[dict] = []
_MAX_TELEMETRY = 200


def record_telemetry(telemetry: ExecutionTelemetry) -> None:
    """Record mission execution telemetry."""
    global _telemetry_buffer
    _telemetry_buffer.append(telemetry.to_dict())
    if len(_telemetry_buffer) > _MAX_TELEMETRY:
        _telemetry_buffer = _telemetry_buffer[-_MAX_TELEMETRY:]


def get_recent_telemetry(limit: int = 20) -> list[dict]:
    """Get recent execution telemetry."""
    return _telemetry_buffer[-limit:]


def get_telemetry_summary() -> dict:
    """Aggregate telemetry statistics."""
    if not _telemetry_buffer:
        return {
            "total_missions": 0,
            "avg_stability": 0.0,
            "avg_retries": 0.0,
            "avg_fallbacks": 0.0,
        }
    total = len(_telemetry_buffer)
    return {
        "total_missions": total,
        "avg_stability": round(
            sum(t.get("stability_score", 0) for t in _telemetry_buffer) / total, 3
        ),
        "avg_retries": round(
            sum(t.get("total_retries", 0) for t in _telemetry_buffer) / total, 1
        ),
        "avg_fallbacks": round(
            sum(t.get("total_fallbacks", 0) for t in _telemetry_buffer) / total, 1
        ),
        "avg_success_rate": round(
            sum(t.get("success_rate", 0) for t in _telemetry_buffer) / total, 3
        ),
    }


# ═══════════════════════════════════════════════════════════════
# 5. INTELLIGENT TOOL EXECUTION
# ═══════════════════════════════════════════════════════════════

def execute_tool_intelligently(
    tool_name: str,
    params: dict,
    mission_id: str = "",
    step_id: str = "",
    approval_mode: str = "SUPERVISED",
    max_retries: int = 2,
    allow_fallback: bool = True,
) -> tuple[dict, StepTelemetry]:
    """
    Execute a tool with health check, adaptive retry, and fallback.

    Returns:
        (result_dict, step_telemetry)
    """
    telemetry = StepTelemetry(
        step_id=step_id or f"step-{int(time.time()*1000)}",
        tool=tool_name,
        started_at=time.time(),
    )

    # Pre-execution health check
    health = check_tool_health(tool_name)
    telemetry.health_status = health["status"]

    if not health["healthy"] and health["recommendation"] == "skip_or_fallback":
        logger.warning(
            "tool_unhealthy_skipping",
            tool=tool_name,
            status=health["status"],
            last_error=health.get("last_error", ""),
        )
        # Try fallback immediately
        if allow_fallback:
            fallback = get_fallback_tool(tool_name)
            if fallback:
                logger.info("using_fallback_tool", primary=tool_name, fallback=fallback)
                telemetry.fallback_used = fallback
                result, _ = execute_tool_intelligently(
                    fallback, params, mission_id, step_id,
                    approval_mode, max_retries=1, allow_fallback=False,
                )
                telemetry.success = result.get("ok", False)
                telemetry.finished_at = time.time()
                telemetry.duration_ms = (telemetry.finished_at - telemetry.started_at) * 1000
                return result, telemetry

        # No fallback available
        telemetry.success = False
        telemetry.error_type = "tool_unhealthy"
        telemetry.error_msg = f"Tool '{tool_name}' is failing and no fallback available"
        telemetry.finished_at = time.time()
        telemetry.duration_ms = (telemetry.finished_at - telemetry.started_at) * 1000
        return {"ok": False, "error": telemetry.error_msg, "result": ""}, telemetry

    # Consult recovery memory for known fixes
    _recovery_hint = None
    try:
        error_hint = health.get("last_error", "")
        if error_hint:
            _recovery_hint = get_best_recovery(tool_name, error_hint.split(":")[0] if ":" in error_hint else error_hint[:30])
    except Exception as _exc:
        log.warning("swallowed_exception", action="execution_engine_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Execute with adaptive retry
    try:
        from core.tool_executor import get_tool_executor
        executor = get_tool_executor()
    except ImportError:
        telemetry.error_type = "executor_unavailable"
        telemetry.finished_at = time.time()
        return {"ok": False, "error": "tool_executor unavailable"}, telemetry

    result = {"ok": False, "error": "not_executed"}
    current_params = dict(params)

    # Apply recovery hint if available (pre-adapt params)
    if _recovery_hint and _recovery_hint.get("recovery_type") == "retry_adapted":
        # Previous successful recovery suggests parameter adaptation helps
        telemetry.params_adapted = True
        logger.debug("applying_recovery_hint", tool=tool_name, hint=_recovery_hint["error_type"])

    for attempt in range(max_retries + 1):
        result = executor.execute(tool_name, current_params, approval_mode)

        if result.get("ok"):
            telemetry.success = True
            telemetry.retries = attempt
            break

        # Adaptive parameter variation on retry
        if attempt < max_retries:
            # Check if retrying is worthwhile
            if not should_retry(tool_name, attempt):
                telemetry.retries = attempt
                break  # skip to fallback

            error_msg = result.get("error", "")
            adapted = adapt_params(tool_name, current_params, attempt, error_msg)
            if adapted != current_params:
                telemetry.params_adapted = True
                current_params = adapted

            delay = adapted.pop("_retry_delay", 0.3 * (attempt + 1))
            time.sleep(min(delay, 3.0))
            telemetry.retries = attempt + 1
            logger.info(
                "adaptive_retry",
                tool=tool_name,
                attempt=attempt + 2,
                adapted=telemetry.params_adapted,
            )

    # If still failed, try fallback (prefer recovery hint's fallback if available)
    if not result.get("ok") and allow_fallback:
        fallback = None
        if _recovery_hint and _recovery_hint.get("fallback_tool"):
            fallback = _recovery_hint["fallback_tool"]
            logger.info("fallback_from_recovery_memory", primary=tool_name, fallback=fallback)
        else:
            fallback = get_fallback_tool(tool_name)
        if fallback:
            logger.info("fallback_after_retries", primary=tool_name, fallback=fallback)
            telemetry.fallback_used = fallback
            fb_result = executor.execute(fallback, params, approval_mode)
            if fb_result.get("ok"):
                result = fb_result
                telemetry.success = True

    if not telemetry.success:
        telemetry.error_type = result.get("error_class", "unknown")
        telemetry.error_msg = result.get("error", "")[:200]

    telemetry.finished_at = time.time()
    telemetry.duration_ms = (telemetry.finished_at - telemetry.started_at) * 1000
    return result, telemetry


# ═══════════════════════════════════════════════════════════════
# 6. POST-MISSION EVALUATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class MissionEvaluation:
    """Post-mission quality evaluation."""
    mission_id: str
    goal_completion: float = 0.0     # 0.0-1.0
    tool_efficiency: float = 0.0     # 0.0-1.0
    execution_stability: float = 0.0 # 0.0-1.0
    agent_effectiveness: float = 0.0 # 0.0-1.0
    overall_score: float = 0.0       # weighted average
    timestamp: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_mission(
    mission_id: str,
    success: bool,
    final_output: str,
    goal: str,
    agents_used: list[str],
    tools_used: list[str],
    duration_s: float,
    plan_steps: int,
    telemetry: Optional[ExecutionTelemetry] = None,
) -> MissionEvaluation:
    """
    Evaluate a completed mission's quality.

    Scoring:
    - Goal completion: based on output presence + success flag
    - Tool efficiency: fewer retries/fallbacks = better
    - Execution stability: from telemetry stability_score
    - Agent effectiveness: from performance tracker

    Returns MissionEvaluation with 0.0-1.0 scores.
    """
    evaluation = MissionEvaluation(
        mission_id=mission_id,
        timestamp=time.time(),
    )

    # Goal completion (0.0-1.0)
    if success and final_output and len(final_output.strip()) >= 20:
        evaluation.goal_completion = 1.0
    elif success and final_output:
        evaluation.goal_completion = 0.7
    elif success:
        evaluation.goal_completion = 0.5
    else:
        evaluation.goal_completion = 0.0

    # Tool efficiency (0.0-1.0)
    if telemetry:
        retry_penalty = min(telemetry.total_retries * 0.1, 0.4)
        fallback_penalty = min(telemetry.total_fallbacks * 0.15, 0.3)
        skip_penalty = min(telemetry.tools_skipped_unhealthy * 0.1, 0.2)
        evaluation.tool_efficiency = max(0.0, 1.0 - retry_penalty - fallback_penalty - skip_penalty)
    else:
        evaluation.tool_efficiency = 0.7 if success else 0.3

    # Execution stability (0.0-1.0)
    if telemetry:
        evaluation.execution_stability = telemetry.stability_score
    else:
        evaluation.execution_stability = 0.8 if success else 0.2

    # Agent effectiveness (0.0-1.0)
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        tracker = get_mission_performance_tracker()
        total_rate = 0.0
        count = 0
        for agent in agents_used:
            agent_stats = tracker._agent_stats.get(agent)
            if agent_stats and agent_stats.total_missions >= 3:
                total_rate += agent_stats.success_rate
                count += 1
        evaluation.agent_effectiveness = total_rate / max(count, 1) if count else (0.7 if success else 0.3)
    except Exception:
        evaluation.agent_effectiveness = 0.7 if success else 0.3

    # Overall score (weighted)
    evaluation.overall_score = round(
        evaluation.goal_completion * 0.40
        + evaluation.tool_efficiency * 0.25
        + evaluation.execution_stability * 0.20
        + evaluation.agent_effectiveness * 0.15,
        3,
    )

    # Notes
    if evaluation.goal_completion < 0.5:
        evaluation.notes.append("Goal may not be fully completed")
    if evaluation.tool_efficiency < 0.5:
        evaluation.notes.append("Tool execution had significant issues")
    if evaluation.execution_stability < 0.5:
        evaluation.notes.append("Execution was unstable")
    if evaluation.agent_effectiveness < 0.5:
        evaluation.notes.append("Agents may not be well-suited for this task")
    if evaluation.overall_score >= 0.8:
        evaluation.notes.append("High quality execution")

    return evaluation


# Evaluation history (last 500)
_evaluations: list[dict] = []
_MAX_EVALUATIONS = 500


def store_evaluation(evaluation: MissionEvaluation) -> None:
    global _evaluations
    _evaluations.append(evaluation.to_dict())
    if len(_evaluations) > _MAX_EVALUATIONS:
        _evaluations = _evaluations[-_MAX_EVALUATIONS:]


def get_evaluation_history(limit: int = 20) -> list[dict]:
    return _evaluations[-limit:]


def get_evaluation_trends() -> dict:
    """Aggregate evaluation trends."""
    if not _evaluations:
        return {"total": 0}
    recent = _evaluations[-50:]
    return {
        "total": len(_evaluations),
        "recent_count": len(recent),
        "avg_overall": round(sum(e["overall_score"] for e in recent) / len(recent), 3),
        "avg_goal_completion": round(sum(e["goal_completion"] for e in recent) / len(recent), 3),
        "avg_tool_efficiency": round(sum(e["tool_efficiency"] for e in recent) / len(recent), 3),
        "avg_stability": round(sum(e["execution_stability"] for e in recent) / len(recent), 3),
        "avg_agent_effectiveness": round(sum(e["agent_effectiveness"] for e in recent) / len(recent), 3),
    }


# ═══════════════════════════════════════════════════════════════
# 7. RECOVERY STRATEGY MEMORY
# ═══════════════════════════════════════════════════════════════

@dataclass
class RecoveryRecord:
    """Record of a recovery attempt."""
    tool: str
    error_type: str
    recovery_type: str   # "retry_adapted", "fallback", "skip"
    fallback_tool: str = ""
    success: bool = False
    count: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


_recovery_memory: dict[str, RecoveryRecord] = {}
_MAX_RECOVERIES = 200


def record_recovery(
    tool: str,
    error_type: str,
    recovery_type: str,
    fallback_tool: str = "",
    success: bool = False,
) -> None:
    """Record a recovery attempt for future reuse."""
    key = f"{tool}:{error_type}:{recovery_type}"
    if key in _recovery_memory:
        _recovery_memory[key].count += 1
        if success:
            _recovery_memory[key].success = True
    else:
        if len(_recovery_memory) >= _MAX_RECOVERIES:
            oldest_key = min(_recovery_memory, key=lambda k: _recovery_memory[k].count)
            del _recovery_memory[oldest_key]
        _recovery_memory[key] = RecoveryRecord(
            tool=tool,
            error_type=error_type,
            recovery_type=recovery_type,
            fallback_tool=fallback_tool,
            success=success,
        )


def get_best_recovery(tool: str, error_type: str) -> Optional[dict]:
    """Get the most effective recovery for a tool+error combo."""
    candidates = [
        (k, r) for k, r in _recovery_memory.items()
        if r.tool == tool and r.error_type == error_type and r.success
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1].count)
    return best[1].to_dict()


def get_recovery_stats() -> dict:
    """Recovery strategy effectiveness stats."""
    total = len(_recovery_memory)
    successful = sum(1 for r in _recovery_memory.values() if r.success)
    return {
        "total_strategies": total,
        "successful": successful,
        "success_rate": round(successful / max(total, 1), 3),
        "top_recoveries": sorted(
            [r.to_dict() for r in _recovery_memory.values() if r.success],
            key=lambda x: x["count"],
            reverse=True,
        )[:10],
    }
