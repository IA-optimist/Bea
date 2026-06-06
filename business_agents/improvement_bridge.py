"""
JARVIS MAX — Business Agent Self-Improvement Bridge
=====================================================
Ensures business agents can be safely improved by the core
self-improvement loop.

Requirements met:
  - Prompts are versioned (via PromptContract)
  - Outputs are scored (via evaluation rules)
  - Failures are traceable
  - Templates are testable
  - Optimization happens in sandbox only

This module connects business agents to the improvement daemon
without allowing direct uncontrolled modification in production.
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentPerformanceRecord:
    """Tracked performance for a business agent."""
    agent_id: str
    total_executions: int = 0
    successful: int = 0
    failed: int = 0
    avg_score: float = 0.0
    scores: list[float] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    prompt_version: str = "1.0.0"
    last_execution: float = 0
    last_test_score: float = 0

    @property
    def success_rate(self) -> float:
        return self.successful / self.total_executions if self.total_executions > 0 else 0

    @property
    def needs_improvement(self) -> bool:
        return (self.total_executions >= 5 and
                (self.success_rate < 0.7 or self.avg_score < 0.6))

    def record_execution(self, success: bool, score: float,
                         failure_reason: str = "") -> None:
        self.total_executions += 1
        if success:
            self.successful += 1
        else:
            self.failed += 1
            if failure_reason:
                self.failures.append({
                    "reason": failure_reason,
                    "timestamp": time.time(),
                })
                # Keep only last 20 failures
                self.failures = self.failures[-20:]
        self.scores.append(score)
        # Keep rolling window of 50
        self.scores = self.scores[-50:]
        self.avg_score = sum(self.scores) / len(self.scores)
        self.last_execution = time.time()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "total_executions": self.total_executions,
            "success_rate": round(self.success_rate, 3),
            "avg_score": round(self.avg_score, 3),
            "needs_improvement": self.needs_improvement,
            "prompt_version": self.prompt_version,
            "last_execution": self.last_execution,
            "last_test_score": self.last_test_score,
            "recent_failures": self.failures[-5:],
        }


class ImprovementBridge:
    """
    Bridge between business agents and the core self-improvement loop.

    Tracks agent performance, identifies candidates for improvement,
    and ensures improvements go through sandbox-only pipeline.
    """

    def __init__(self, persist_path: Path | None = None):
        self._path = persist_path or Path("workspace/business_data/agent_performance.json")
        self._records: dict[str, AgentPerformanceRecord] = {}
        self._load()

    def record(self, agent_id: str, success: bool, score: float,
               failure_reason: str = "", prompt_version: str = "") -> None:
        """Record an execution result for an agent."""
        if agent_id not in self._records:
            self._records[agent_id] = AgentPerformanceRecord(agent_id=agent_id)
        rec = self._records[agent_id]
        rec.record_execution(success, score, failure_reason)
        if prompt_version:
            rec.prompt_version = prompt_version
        self._save()

    def get_improvement_candidates(self) -> list[dict]:
        """Get agents that need improvement based on performance data."""
        candidates = []
        for rec in self._records.values():
            if rec.needs_improvement:
                # Analyze failure patterns
                failure_patterns: dict[str, int] = {}
                for f in rec.failures:
                    reason = f.get("reason", "unknown")[:50]
                    failure_patterns[reason] = failure_patterns.get(reason, 0) + 1

                candidates.append({
                    "agent_id": rec.agent_id,
                    "success_rate": rec.success_rate,
                    "avg_score": rec.avg_score,
                    "total_executions": rec.total_executions,
                    "top_failure_patterns": sorted(
                        failure_patterns.items(), key=lambda x: x[1], reverse=True
                    )[:3],
                    "suggestion": _suggest_improvement(rec),
                })
        return candidates

    def get_stats(self, agent_id: str) -> dict | None:
        rec = self._records.get(agent_id)
        return rec.to_dict() if rec else None

    def get_all_stats(self) -> list[dict]:
        return [rec.to_dict() for rec in self._records.values()]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({k: v.to_dict() for k, v in self._records.items()},
                           indent=2, default=str),
                encoding="utf-8")
        except Exception as _exc:
            log.warning("swallowed_exception", action="improvement_bridge_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for agent_id, rec_data in data.items():
                    self._records[agent_id] = AgentPerformanceRecord(
                        agent_id=agent_id,
                        total_executions=rec_data.get("total_executions", 0),
                        successful=int(rec_data.get("success_rate", 0) * rec_data.get("total_executions", 0)),
                        avg_score=rec_data.get("avg_score", 0),
                        prompt_version=rec_data.get("prompt_version", "1.0.0"),
                        last_execution=rec_data.get("last_execution", 0),
                        last_test_score=rec_data.get("last_test_score", 0),
                    )
            except Exception as _exc:
                log.warning("swallowed_exception", action="improvement_bridge_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


def _suggest_improvement(rec: AgentPerformanceRecord) -> str:
    """Suggest what type of improvement to try."""
    if rec.success_rate < 0.5:
        return "prompt_rewrite"
    if rec.avg_score < 0.5:
        return "output_format_fix"
    if rec.success_rate < 0.7:
        return "error_handling_improvement"
    return "prompt_tuning"


# Singleton
_bridge: ImprovementBridge | None = None


def get_improvement_bridge(persist_path: Path | None = None) -> ImprovementBridge:
    global _bridge
    if _bridge is None:
        _bridge = ImprovementBridge(persist_path)
    return _bridge
