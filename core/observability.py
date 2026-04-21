"""
Observability — stocke les métriques des 100 dernières missions en mémoire circulaire.
~8 KB RAM max (100 × ~80 bytes). Expose stats agrégées.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class MissionMetrics:
    mission_id: str
    mission_type: str
    selected_agents: List[str]
    execution_policy_decision: str   # AUTO_APPROVED | REQUIRES_APPROVAL | BLOCKED
    fallback_level_used: int
    confidence_score: float
    duration_ms: int
    tools_used: List[str] = field(default_factory=list)
    ts: int = field(default_factory=lambda: int(time.time()))


class ObservabilityStore:
    """Buffer circulaire en mémoire des 100 dernières missions."""

    def __init__(self, max_size: int = 100):
        self._metrics: deque[MissionMetrics] = deque(maxlen=max_size)

    def record(self, m: MissionMetrics) -> None:
        try:
            self._metrics.append(m)
        except Exception as e:
            logger.warning(f"[Observability] record error: {e}")

    def get_recent(self, n: int = 20) -> List[dict]:
        entries = list(self._metrics)[-n:]
        return [
            {
                "mission_id": m.mission_id,
                "mission_type": m.mission_type,
                "agents": m.selected_agents,
                "policy_decision": m.execution_policy_decision,
                "fallback_level": m.fallback_level_used,
                "confidence": m.confidence_score,
                "duration_ms": m.duration_ms,
                "tools": m.tools_used,
                "ts": m.ts,
            }
            for m in entries
        ]

    def get_stats(self) -> dict:
        """Calcule les stats agrégées sur toutes les entrées en mémoire."""
        try:
            entries = list(self._metrics)
            if not entries:
                return {"count": 0}

            total = len(entries)
            avg_conf = sum(m.confidence_score for m in entries) / total
            avg_dur = sum(m.duration_ms for m in entries) / total
            fallback_count = sum(1 for m in entries if m.fallback_level_used >= 1)
            approval_count = sum(1 for m in entries if m.execution_policy_decision == "REQUIRES_APPROVAL")

            # Most used agents
            from collections import Counter
            agent_counter: Counter = Counter()
            tool_counter: Counter = Counter()
            for m in entries:
                agent_counter.update(m.selected_agents)
                tool_counter.update(m.tools_used)

            return {
                "count": total,
                "avg_confidence": round(avg_conf, 3),
                "avg_duration_ms": round(avg_dur, 1),
                "fallback_rate": round(fallback_count / total, 3),
                "approval_rate": round(approval_count / total, 3),
                "most_used_agents": agent_counter.most_common(5),
                "most_used_tools": tool_counter.most_common(5),
            }
        except Exception as e:
            logger.warning(f"[Observability] get_stats error: {e}")
            return {"count": 0, "error": str(e)}


# Singleton
_store: Optional[ObservabilityStore] = None

def get_observability_store() -> ObservabilityStore:
    global _store
    if _store is None:
        _store = ObservabilityStore()
    return _store
