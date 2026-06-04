"""
JARVIS — Tool Performance Tracker
====================================
Tracks real execution signals from ToolExecutor: success/failure rates,
latency, error patterns, per-tool reliability scores.

This is NOT another isolated intelligence layer. It:
1. Gets called FROM tool_executor._execute_with_retry()
2. Feeds data TO tool_registry for smart tool selection
3. Exposes data TO the Jarvis app via API
4. Persists TO workspace/tool_performance.jsonl

Zero external dependencies. Fail-open everywhere.
"""
from __future__ import annotations

import json
import structlog
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = structlog.get_logger("jarvis.tool_performance")

# ── Data Structures ────────────────────────────────────────────────────────────

@dataclass
class ToolExecution:
    """Single tool execution record."""
    tool: str
    success: bool
    latency_ms: float
    error_type: str = ""
    error_msg: str = ""
    mission_id: str = ""
    timestamp: float = 0.0
    retried: bool = False
    blocked_by_policy: bool = False

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class ToolStats:
    """Aggregated stats for a single tool."""
    tool: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    policy_blocks: int = 0
    retries: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    error_counts: dict = field(default_factory=dict)
    last_success: float = 0.0
    last_failure: float = 0.0
    last_error: str = ""
    # Calculated
    _recent_window: list = field(default_factory=list)  # last 50 executions

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successes / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def recent_success_rate(self) -> float:
        """Success rate over last 50 executions (more responsive to trends)."""
        if not self._recent_window:
            return self.success_rate
        return sum(1 for ok in self._recent_window if ok) / len(self._recent_window)

    @property
    def reliability_score(self) -> float:
        """
        Combined reliability score 0.0-1.0.
        Weights: recent success 60%, overall success 25%, latency penalty 15%.
        """
        recent = self.recent_success_rate
        overall = self.success_rate
        latency_penalty = min(self.avg_latency_ms / 5000.0, 1.0)  # >5s = max penalty
        return round(recent * 0.60 + overall * 0.25 + (1.0 - latency_penalty) * 0.15, 3)

    @property
    def top_errors(self) -> list[tuple[str, int]]:
        """Top 5 error types by frequency."""
        return sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    @property
    def health_status(self) -> str:
        """healthy / degraded / failing / unknown."""
        if self.total_calls == 0:
            return "unknown"
        if self.recent_success_rate >= 0.90:
            return "healthy"
        if self.recent_success_rate >= 0.60:
            return "degraded"
        return "failing"

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "failures": self.failures,
            "policy_blocks": self.policy_blocks,
            "retries": self.retries,
            "success_rate": round(self.success_rate, 3),
            "recent_success_rate": round(self.recent_success_rate, 3),
            "reliability_score": self.reliability_score,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "min_latency_ms": round(self.min_latency_ms, 1) if self.min_latency_ms != float("inf") else 0,
            "max_latency_ms": round(self.max_latency_ms, 1),
            "health_status": self.health_status,
            "top_errors": self.top_errors,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_error": self.last_error,
        }


# ── Performance Tracker ────────────────────────────────────────────────────────

class ToolPerformanceTracker:
    """
    Central tracker for all tool executions.

    Called from ToolExecutor after every tool call.
    Bounded: 200 tools max, 50 recent executions per tool.
    """

    MAX_TOOLS = 200
    RECENT_WINDOW = 50
    PERSIST_FILE = "workspace/tool_performance.jsonl"

    def __init__(self, persist_path: Optional[str] = None):
        self._stats: dict[str, ToolStats] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._dirty = False
        self._call_count = 0
        self._auto_save_interval = 50  # save every 50 calls

    def record(self, execution: ToolExecution) -> None:
        """Record a tool execution. Called after every tool call."""
        tool = execution.tool
        if not tool:
            return

        # Bounded: LRU eviction if at capacity
        if tool not in self._stats and len(self._stats) >= self.MAX_TOOLS:
            oldest = min(self._stats.values(),
                         key=lambda s: max(s.last_success, s.last_failure))
            del self._stats[oldest.tool]

        stats = self._stats.setdefault(tool, ToolStats(tool=tool))

        stats.total_calls += 1
        stats.total_latency_ms += execution.latency_ms
        stats.min_latency_ms = min(stats.min_latency_ms, execution.latency_ms)
        stats.max_latency_ms = max(stats.max_latency_ms, execution.latency_ms)

        if execution.blocked_by_policy:
            stats.policy_blocks += 1

        if execution.retried:
            stats.retries += 1

        if execution.success:
            stats.successes += 1
            stats.last_success = execution.timestamp
        else:
            stats.failures += 1
            stats.last_failure = execution.timestamp
            stats.last_error = execution.error_msg[:200]
            if execution.error_type:
                stats.error_counts[execution.error_type] = \
                    stats.error_counts.get(execution.error_type, 0) + 1

        # Recent window
        stats._recent_window.append(execution.success)
        if len(stats._recent_window) > self.RECENT_WINDOW:
            stats._recent_window = stats._recent_window[-self.RECENT_WINDOW:]

        # Auto-save
        self._dirty = True
        self._call_count += 1
        if self._call_count % self._auto_save_interval == 0:
            self.save()

    def get_stats(self, tool: str) -> Optional[ToolStats]:
        """Get stats for a specific tool."""
        return self._stats.get(tool)

    def get_all_stats(self) -> dict[str, ToolStats]:
        """Get stats for all tracked tools."""
        return dict(self._stats)

    def get_reliability_ranking(self) -> list[dict]:
        """Tools ranked by reliability score, descending."""
        return sorted(
            [s.to_dict() for s in self._stats.values() if s.total_calls > 0],
            key=lambda x: x["reliability_score"],
            reverse=True,
        )

    def get_failing_tools(self) -> list[dict]:
        """Tools with health_status = degraded or failing."""
        return [
            s.to_dict() for s in self._stats.values()
            if s.health_status in ("degraded", "failing")
        ]

    def get_tool_for_capability(
        self,
        candidates: list[str],
        min_reliability: float = 0.3,
    ) -> Optional[str]:
        """
        Given candidate tools, return the most reliable one.
        Used by planner for intelligent tool selection.

        Falls back to first candidate if no performance data exists.
        """
        if not candidates:
            return None

        scored = []
        for tool in candidates:
            stats = self._stats.get(tool)
            if stats and stats.total_calls >= 3:
                scored.append((tool, stats.reliability_score))
            else:
                scored.append((tool, 0.5))  # unknown = neutral

        scored.sort(key=lambda x: x[1], reverse=True)
        best_tool, best_score = scored[0]

        if best_score < min_reliability:
            logger.warning(
                "all_tools_low_reliability",
                tools=candidates, best=best_tool, score=best_score,
            )

        return best_tool

    def get_fallback_tool(
        self,
        primary: str,
        alternatives: list[str],
    ) -> Optional[str]:
        """
        If primary tool is degraded/failing, suggest the best alternative.
        Returns None if primary is healthy or no alternatives exist.
        """
        primary_stats = self._stats.get(primary)
        if primary_stats and primary_stats.health_status == "healthy":
            return None

        return self.get_tool_for_capability(
            [t for t in alternatives if t != primary]
        )

    def get_dashboard_data(self) -> dict:
        """Full dashboard payload for Jarvis app."""
        all_stats = [s.to_dict() for s in self._stats.values()]
        healthy = sum(1 for s in self._stats.values() if s.health_status == "healthy")
        degraded = sum(1 for s in self._stats.values() if s.health_status == "degraded")
        failing = sum(1 for s in self._stats.values() if s.health_status == "failing")
        unknown = sum(1 for s in self._stats.values() if s.health_status == "unknown")

        total_calls = sum(s.total_calls for s in self._stats.values())
        total_successes = sum(s.successes for s in self._stats.values())

        return {
            "summary": {
                "total_tools_tracked": len(self._stats),
                "healthy": healthy,
                "degraded": degraded,
                "failing": failing,
                "unknown": unknown,
                "total_executions": total_calls,
                "overall_success_rate": round(total_successes / max(total_calls, 1), 3),
            },
            "tools": sorted(all_stats, key=lambda x: x["total_calls"], reverse=True),
            "failing_tools": self.get_failing_tools(),
            "reliability_ranking": self.get_reliability_ranking()[:20],
        }

    # ── Persistence ────────────────────────────────────────────────────────

    def save(self) -> bool:
        """Save stats to JSONL. Returns True on success."""
        if not self._dirty:
            return True
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                for stats in self._stats.values():
                    record = stats.to_dict()
                    record["_recent_window"] = stats._recent_window[-self.RECENT_WINDOW:]
                    f.write(json.dumps(record) + "\n")
            self._dirty = False
            logger.debug("tool_performance_saved", tools=len(self._stats))
            return True
        except Exception as e:
            logger.warning("tool_performance_save_failed: %s", str(e)[:80])
            return False

    def load(self) -> bool:
        """Load stats from JSONL. Returns True on success."""
        if not os.path.exists(self._persist_path):
            return False
        try:
            self._stats.clear()
            with open(self._persist_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    tool = data.get("tool", "")
                    if not tool:
                        continue
                    stats = ToolStats(tool=tool)
                    stats.total_calls = data.get("total_calls", 0)
                    stats.successes = data.get("successes", 0)
                    stats.failures = data.get("failures", 0)
                    stats.policy_blocks = data.get("policy_blocks", 0)
                    stats.retries = data.get("retries", 0)
                    stats.total_latency_ms = data.get("avg_latency_ms", 0) * data.get("total_calls", 0)
                    stats.last_success = data.get("last_success", 0)
                    stats.last_failure = data.get("last_failure", 0)
                    stats.last_error = data.get("last_error", "")
                    stats.error_counts = dict(data.get("top_errors", []))
                    stats._recent_window = data.get("_recent_window", [])
                    self._stats[tool] = stats
            logger.info("tool_performance_loaded", tools=len(self._stats))
            return True
        except Exception as e:
            logger.warning("tool_performance_load_failed: %s", str(e)[:80])
            return False


# ── Singleton ──────────────────────────────────────────────────────────────────

_tracker: Optional[ToolPerformanceTracker] = None


def get_tool_performance_tracker() -> ToolPerformanceTracker:
    """Get or create the global tool performance tracker."""
    global _tracker
    if _tracker is None:
        _tracker = ToolPerformanceTracker()
        _tracker.load()
    return _tracker
