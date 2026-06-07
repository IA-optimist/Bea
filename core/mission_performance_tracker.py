"""
BEA — Mission Performance Tracker
========================================
Tracks mission outcomes for real planning intelligence.

Called from:
- mission_system.complete() — records successful missions
- mission_system.reject() — records rejected missions
- api/main.py _run_mission() — records failure/timeout

Feeds data to:
- planner: which strategies work for which mission types
- agent selection: which agents perform well for which domains
- UI: mission success trends, failure patterns

Zero external dependencies. Fail-open everywhere.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("bea.mission_performance")


@dataclass
class MissionOutcome:
    """Single mission outcome record."""
    mission_id: str
    goal: str = ""
    mission_type: str = "unknown"
    success: bool = True
    duration_s: float = 0.0
    agents_used: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    plan_steps: int = 0
    complexity: str = "medium"
    risk_score: float = 0.0
    error_category: str = ""
    error_msg: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class MissionTypeStats:
    """Aggregated stats for a mission type."""
    mission_type: str
    total: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_s: float = 0.0
    avg_steps: float = 0.0
    best_agents: dict[str, int] = field(default_factory=dict)  # agent → success count
    best_tools: dict[str, int] = field(default_factory=dict)   # tool → success count
    error_patterns: dict[str, int] = field(default_factory=dict)
    _recent: list[bool] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successes / max(self.total, 1)

    @property
    def recent_success_rate(self) -> float:
        if not self._recent:
            return self.success_rate
        return sum(1 for ok in self._recent if ok) / len(self._recent)

    @property
    def avg_duration_s(self) -> float:
        return self.total_duration_s / max(self.total, 1)

    def to_dict(self) -> dict:
        return {
            "mission_type": self.mission_type,
            "total": self.total,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 3),
            "recent_success_rate": round(self.recent_success_rate, 3),
            "avg_duration_s": round(self.avg_duration_s, 1),
            "avg_steps": round(self.avg_steps, 1),
            "top_agents": sorted(
                self.best_agents.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "top_tools": sorted(
                self.best_tools.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "top_errors": sorted(
                self.error_patterns.items(), key=lambda x: x[1], reverse=True
            )[:5],
        }


@dataclass
class AgentPerformance:
    """Per-agent performance tracking."""
    agent: str
    total_missions: int = 0
    successes: int = 0
    failures: int = 0
    domain_success: dict[str, list[int]] = field(default_factory=dict)  # type → [success, total]

    @property
    def success_rate(self) -> float:
        return self.successes / max(self.total_missions, 1)

    def domain_success_rate(self, mission_type: str) -> float:
        counts = self.domain_success.get(mission_type, [0, 0])
        return counts[0] / max(counts[1], 1)

    def to_dict(self) -> dict:
        domains = {}
        for mt, counts in self.domain_success.items():
            domains[mt] = {
                "successes": counts[0] if len(counts) > 0 else 0,
                "total": counts[1] if len(counts) > 1 else 0,
                "rate": round(counts[0] / max(counts[1], 1), 3) if len(counts) > 1 else 0,
            }
        return {
            "agent": self.agent,
            "total_missions": self.total_missions,
            "success_rate": round(self.success_rate, 3),
            "domains": domains,
        }


class MissionPerformanceTracker:
    """
    Tracks mission outcomes for planning intelligence.

    Bounded: 100 mission types, 50 agents, 500 recent outcomes.
    Persists to workspace/mission_performance.jsonl.
    """

    MAX_TYPES = 100
    MAX_AGENTS = 50
    RECENT_WINDOW = 30
    PERSIST_FILE = "workspace/mission_performance.jsonl"

    def __init__(self, persist_path: Optional[str] = None):
        self._type_stats: dict[str, MissionTypeStats] = {}
        self._agent_stats: dict[str, AgentPerformance] = {}
        self._recent_outcomes: list[dict] = []  # last 500
        self._persist_path = persist_path or self.PERSIST_FILE
        self._dirty = False
        self._count = 0

    def record(self, outcome: MissionOutcome) -> None:
        """Record a mission outcome."""
        mt = outcome.mission_type or "unknown"

        # Mission type stats
        if mt not in self._type_stats and len(self._type_stats) >= self.MAX_TYPES:
            oldest = min(self._type_stats.values(), key=lambda s: s.total)
            del self._type_stats[oldest.mission_type]

        stats = self._type_stats.setdefault(mt, MissionTypeStats(mission_type=mt))
        stats.total += 1
        stats.total_duration_s += outcome.duration_s
        stats.avg_steps = (
            (stats.avg_steps * (stats.total - 1) + outcome.plan_steps) / stats.total
        )

        if outcome.success:
            stats.successes += 1
            for agent in outcome.agents_used:
                stats.best_agents[agent] = stats.best_agents.get(agent, 0) + 1
            for tool in outcome.tools_used:
                stats.best_tools[tool] = stats.best_tools.get(tool, 0) + 1
        else:
            stats.failures += 1
            if outcome.error_category:
                stats.error_patterns[outcome.error_category] = \
                    stats.error_patterns.get(outcome.error_category, 0) + 1

        stats._recent.append(outcome.success)
        if len(stats._recent) > self.RECENT_WINDOW:
            stats._recent = stats._recent[-self.RECENT_WINDOW:]

        # Agent stats
        for agent in outcome.agents_used:
            if agent not in self._agent_stats and len(self._agent_stats) >= self.MAX_AGENTS:
                worst = min(self._agent_stats.values(), key=lambda a: a.success_rate)
                del self._agent_stats[worst.agent]

            ap = self._agent_stats.setdefault(agent, AgentPerformance(agent=agent))
            ap.total_missions += 1
            if outcome.success:
                ap.successes += 1
            else:
                ap.failures += 1

            if mt not in ap.domain_success:
                ap.domain_success[mt] = [0, 0]
            ap.domain_success[mt][1] += 1
            if outcome.success:
                ap.domain_success[mt][0] += 1

        # Recent outcomes (for UI)
        self._recent_outcomes.append({
            "mission_id": outcome.mission_id,
            "goal": outcome.goal[:100],
            "type": mt,
            "success": outcome.success,
            "duration_s": round(outcome.duration_s, 1),
            "agents": outcome.agents_used[:5],
            "timestamp": outcome.timestamp,
        })
        if len(self._recent_outcomes) > 500:
            self._recent_outcomes = self._recent_outcomes[-500:]

        self._dirty = True
        self._count += 1
        if self._count % 20 == 0:
            self.save()

    def get_best_agents_for_type(self, mission_type: str, top_k: int = 3) -> list[str]:
        """Return agents with highest success rate for a mission type."""
        scored = []
        for agent, ap in self._agent_stats.items():
            rate = ap.domain_success_rate(mission_type)
            total = (ap.domain_success.get(mission_type, [0, 0]))[1] if mission_type in ap.domain_success else 0
            if total > 0:
                scored.append((agent, rate, total))

        scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [a for a, _, _ in scored[:top_k]]

    def get_strategy_for_type(self, mission_type: str) -> dict:
        """Return best-known strategy for a mission type based on past successes."""
        stats = self._type_stats.get(mission_type)
        if not stats or stats.total < 2:
            return {}

        return {
            "mission_type": mission_type,
            "success_rate": round(stats.success_rate, 3),
            "recommended_agents": sorted(
                stats.best_agents.items(), key=lambda x: x[1], reverse=True
            )[:3],
            "recommended_tools": sorted(
                stats.best_tools.items(), key=lambda x: x[1], reverse=True
            )[:5],
            "avg_steps": round(stats.avg_steps, 1),
            "avg_duration_s": round(stats.avg_duration_s, 1),
            "common_errors": sorted(
                stats.error_patterns.items(), key=lambda x: x[1], reverse=True
            )[:3],
            "sample_size": stats.total,
        }

    def get_dashboard_data(self) -> dict:
        """Full dashboard payload for Bea app."""
        total = sum(s.total for s in self._type_stats.values())
        successes = sum(s.successes for s in self._type_stats.values())
        return {
            "summary": {
                "total_missions_tracked": total,
                "overall_success_rate": round(successes / max(total, 1), 3),
                "mission_types_tracked": len(self._type_stats),
                "agents_tracked": len(self._agent_stats),
            },
            "by_type": sorted(
                [s.to_dict() for s in self._type_stats.values()],
                key=lambda x: x["total"], reverse=True,
            ),
            "agent_performance": sorted(
                [a.to_dict() for a in self._agent_stats.values()],
                key=lambda x: x["total_missions"], reverse=True,
            ),
            "recent_outcomes": self._recent_outcomes[-20:],
        }

    # ── Persistence ────────────────────────────────────────────────────────

    def save(self) -> bool:
        if not self._dirty:
            return True
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            data = {
                "type_stats": {k: v.to_dict() for k, v in self._type_stats.items()},
                "agent_stats": {k: v.to_dict() for k, v in self._agent_stats.items()},
                "recent_outcomes": self._recent_outcomes[-100:],
            }
            with open(self._persist_path, "w") as f:
                json.dump(data, f, indent=2)
            self._dirty = False
            return True
        except Exception as e:
            logger.warning("mission_perf_save_failed: %s", str(e)[:80])
            return False

    def load(self) -> bool:
        if not os.path.exists(self._persist_path):
            return False
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            self._recent_outcomes = data.get("recent_outcomes", [])
            # Reconstruct type stats from saved data
            for mt, sd in data.get("type_stats", {}).items():
                stats = MissionTypeStats(mission_type=mt)
                stats.total = sd.get("total", 0)
                stats.successes = sd.get("successes", 0)
                stats.failures = sd.get("failures", 0)
                stats.total_duration_s = sd.get("avg_duration_s", 0) * sd.get("total", 0)
                stats.avg_steps = sd.get("avg_steps", 0)
                stats.best_agents = dict(sd.get("top_agents", []))
                stats.best_tools = dict(sd.get("top_tools", []))
                stats.error_patterns = dict(sd.get("top_errors", []))
                self._type_stats[mt] = stats
            return True
        except Exception as e:
            logger.warning("mission_perf_load_failed: %s", str(e)[:80])
            return False


_tracker: Optional[MissionPerformanceTracker] = None


def get_mission_performance_tracker() -> MissionPerformanceTracker:
    global _tracker
    if _tracker is None:
        _tracker = MissionPerformanceTracker()
        _tracker.load()
    return _tracker


def reset_mission_performance_tracker() -> None:
    """Reset the singleton (useful for tests)."""
    global _tracker
    _tracker = None
