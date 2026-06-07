"""
BEA MAX — Agent Reputation Scoring
=========================================
Tracks real runtime performance per agent and produces reputation scores.
Used as a routing SIGNAL (not absolute truth). Manual override always available.

Metrics tracked:
  - success_rate, failure_rate, timeout_rate
  - avg_latency_ms, avg_cost_usd
  - regression_rate (patches that broke things)
  - escalation_rate (how often agent requires human approval)
  - confidence_calibration (predicted vs actual success)

Design:
  - In-memory + JSON persistence
  - Thread-safe, fail-open
  - Singleton via get_reputation_tracker()
  - Scores are 0.0-1.0 (1.0 = perfect)
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()

_PERSIST_PATH = os.environ.get("AGENT_REPUTATION_PATH", "data/agent_reputation.json")
_singleton: Optional["ReputationTracker"] = None
_lock = threading.Lock()


def get_reputation_tracker() -> "ReputationTracker":
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = ReputationTracker()
    return _singleton


@dataclass
class AgentRecord:
    """Rolling window performance record for one agent."""
    agent_id: str = ""
    total_tasks: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    regressions: int = 0
    escalations: int = 0
    confidence_predictions: int = 0
    confidence_correct: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        return self.successes / max(self.total_tasks, 1)

    @property
    def failure_rate(self) -> float:
        return self.failures / max(self.total_tasks, 1)

    @property
    def timeout_rate(self) -> float:
        return self.timeouts / max(self.total_tasks, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.total_tasks, 1)

    @property
    def avg_cost_usd(self) -> float:
        return self.total_cost_usd / max(self.total_tasks, 1)

    @property
    def regression_rate(self) -> float:
        return self.regressions / max(self.total_tasks, 1)

    @property
    def escalation_rate(self) -> float:
        return self.escalations / max(self.total_tasks, 1)

    @property
    def confidence_calibration(self) -> float:
        return self.confidence_correct / max(self.confidence_predictions, 1)

    @property
    def reputation_score(self) -> float:
        """Composite score 0.0-1.0. Higher = more reliable."""
        if self.total_tasks == 0:
            return 0.5  # Unknown agent — neutral
        sr = self.success_rate * 0.4
        reliability = (1.0 - self.timeout_rate) * 0.2
        stability = (1.0 - self.regression_rate) * 0.2
        autonomy = (1.0 - self.escalation_rate) * 0.1
        calibration = self.confidence_calibration * 0.1
        return min(1.0, max(0.0, sr + reliability + stability + autonomy + calibration))

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "avg_cost_usd": round(self.avg_cost_usd, 4),
            "regressions": self.regressions,
            "escalations": self.escalations,
            "reputation_score": round(self.reputation_score, 3),
            "success_rate": round(self.success_rate, 3),
            "confidence_calibration": round(self.confidence_calibration, 3),
        }


class ReputationTracker:
    """Singleton tracker for agent reputation scores."""

    def __init__(self, persist_path: str = _PERSIST_PATH):
        self._lock = threading.RLock()
        self._agents: Dict[str, AgentRecord] = {}
        self._path = Path(persist_path)
        self._load()

    def _get_or_create(self, agent_id: str) -> AgentRecord:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentRecord(agent_id=agent_id)
        return self._agents[agent_id]

    # ── Recording events ──

    def record_success(self, agent_id: str, latency_ms: float = 0, cost_usd: float = 0) -> None:
        with self._lock:
            r = self._get_or_create(agent_id)
            r.total_tasks += 1
            r.successes += 1
            r.total_latency_ms += latency_ms
            r.total_cost_usd += cost_usd
            r.last_updated = time.time()

    def record_failure(self, agent_id: str, latency_ms: float = 0, cost_usd: float = 0) -> None:
        with self._lock:
            r = self._get_or_create(agent_id)
            r.total_tasks += 1
            r.failures += 1
            r.total_latency_ms += latency_ms
            r.total_cost_usd += cost_usd
            r.last_updated = time.time()

    def record_timeout(self, agent_id: str) -> None:
        with self._lock:
            r = self._get_or_create(agent_id)
            r.total_tasks += 1
            r.timeouts += 1
            r.last_updated = time.time()

    def record_regression(self, agent_id: str) -> None:
        with self._lock:
            r = self._get_or_create(agent_id)
            r.regressions += 1
            r.last_updated = time.time()

    def record_escalation(self, agent_id: str) -> None:
        with self._lock:
            r = self._get_or_create(agent_id)
            r.escalations += 1
            r.last_updated = time.time()

    def record_confidence(self, agent_id: str, predicted_success: bool, actual_success: bool) -> None:
        with self._lock:
            r = self._get_or_create(agent_id)
            r.confidence_predictions += 1
            if predicted_success == actual_success:
                r.confidence_correct += 1
            r.last_updated = time.time()

    # ── Queries ──

    def get_score(self, agent_id: str) -> float:
        r = self._agents.get(agent_id)
        return r.reputation_score if r else 0.5

    def get_record(self, agent_id: str) -> Optional[Dict[str, Any]]:
        r = self._agents.get(agent_id)
        return r.to_dict() if r else None

    def get_all(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in sorted(
            self._agents.values(), key=lambda r: r.reputation_score, reverse=True
        )]

    def get_best_agent(self, candidates: List[str]) -> Optional[str]:
        """Return the highest-scoring agent from a list of candidates."""
        best_id, best_score = None, -1.0
        for aid in candidates:
            score = self.get_score(aid)
            if score > best_score:
                best_id, best_score = aid, score
        return best_id

    # ── Persistence ──

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {aid: {
                "total_tasks": r.total_tasks, "successes": r.successes,
                "failures": r.failures, "timeouts": r.timeouts,
                "total_latency_ms": r.total_latency_ms, "total_cost_usd": r.total_cost_usd,
                "regressions": r.regressions, "escalations": r.escalations,
                "confidence_predictions": r.confidence_predictions,
                "confidence_correct": r.confidence_correct,
            } for aid, r in self._agents.items()}
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.warning("reputation_save_failed", err=str(e))

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text())
            for aid, vals in data.items():
                r = AgentRecord(agent_id=aid, **{k: v for k, v in vals.items() if k != "agent_id"})
                self._agents[aid] = r
            log.info("reputation_loaded", agents=len(self._agents))
        except Exception as e:
            log.warning("reputation_load_failed", err=str(e))
