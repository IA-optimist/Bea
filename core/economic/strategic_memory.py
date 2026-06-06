"""
core/economic/strategic_memory.py — Strategic memory for economic reasoning.

Phase B: Remember which strategies produce good economic results.

Stores:
  - Economic execution records (playbook → schema → outcome)
  - Strategy evaluations (what worked, what didn't, why)
  - Context features for similarity matching

Design:
  - In-memory with JSON persistence (no vector DB)
  - Simple keyword+score similarity (heuristic)
  - Integrates with kernel performance layer
  - Fail-open: degraded memory never blocks execution
"""
from __future__ import annotations

import json
import time
import threading
import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = structlog.get_logger("economic.strategic_memory")


@dataclass
class StrategicRecord:
    """A record of a strategic decision and its outcome."""
    record_id: str = ""
    strategy_type: str = ""  # "market_analysis", "product_creation", etc.
    playbook_id: str = ""
    run_id: str = ""
    context_features: dict = field(default_factory=dict)  # sector, audience, etc.
    schema_type: str = ""  # "OpportunityReport", "BusinessConcept", etc.
    outcome_score: float = 0.0  # 0.0-1.0
    confidence: float = 0.5
    completeness: float = 0.0  # schema completeness
    duration_ms: float = 0.0
    goal: str = ""
    key_findings: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "strategy_type": self.strategy_type,
            "playbook_id": self.playbook_id,
            "run_id": self.run_id,
            "context_features": self.context_features,
            "schema_type": self.schema_type,
            "outcome_score": round(self.outcome_score, 3),
            "confidence": round(self.confidence, 3),
            "completeness": round(self.completeness, 3),
            "duration_ms": self.duration_ms,
            "goal": self.goal[:300],
            "key_findings": self.key_findings[:10],
            "failure_reasons": self.failure_reasons[:10],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategicRecord":
        return cls(
            record_id=d.get("record_id", ""),
            strategy_type=d.get("strategy_type", ""),
            playbook_id=d.get("playbook_id", ""),
            run_id=d.get("run_id", ""),
            context_features=dict(d.get("context_features", {})),
            schema_type=d.get("schema_type", ""),
            outcome_score=float(d.get("outcome_score", 0)),
            confidence=float(d.get("confidence", 0.5)),
            completeness=float(d.get("completeness", 0)),
            duration_ms=float(d.get("duration_ms", 0)),
            goal=d.get("goal", ""),
            key_findings=list(d.get("key_findings", [])),
            failure_reasons=list(d.get("failure_reasons", [])),
            timestamp=float(d.get("timestamp", time.time())),
        )


class StrategicMemoryStore:
    """
    Persistent memory for strategic decisions and outcomes.

    Features:
      - CRUD for StrategicRecord
      - Keyword-based similarity search
      - Performance aggregation per strategy type
      - JSON file persistence
    """

    def __init__(self, store_path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._records: list[StrategicRecord] = []
        self._path = store_path or Path("data/strategic_memory.json")
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                with open(self._path) as f:
                    data = json.load(f)
                self._records = [StrategicRecord.from_dict(r)
                                for r in data.get("records", [])]
                log.debug("strategic_memory_loaded", count=len(self._records))
        except Exception as e:
            log.debug("strategic_memory_load_failed", err=str(e)[:80])

    def _save(self) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump({
                    "version": 1,
                    "records": [r.to_dict() for r in self._records[-500:]],
                    "saved_at": time.time(),
                }, f, indent=2)
            tmp.replace(self._path)
            return True
        except Exception as e:
            log.debug("strategic_memory_save_failed", err=str(e)[:80])
            return False

    def record(self, rec: StrategicRecord) -> None:
        """Add a strategic record."""
        with self._lock:
            if not rec.record_id:
                import uuid
                rec.record_id = f"sr-{uuid.uuid4().hex[:8]}"
            self._records.append(rec)
            self._save()
        log.info("strategic_record_added",
                 strategy=rec.strategy_type,
                 score=rec.outcome_score,
                 playbook=rec.playbook_id)

    def query(
        self,
        strategy_type: str = "",
        min_score: float = 0.0,
        limit: int = 20,
    ) -> list[StrategicRecord]:
        """Query records by type and minimum score."""
        with self._lock:
            results = self._records[:]

        if strategy_type:
            results = [r for r in results if r.strategy_type == strategy_type]
        if min_score > 0:
            results = [r for r in results if r.outcome_score >= min_score]

        # Sort by timestamp descending (most recent first)
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def find_similar(
        self,
        goal: str,
        context_features: dict | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        Find similar past strategies using keyword overlap scoring.

        Returns list of {"record": StrategicRecord, "similarity": float}
        """
        goal_words = set(goal.lower().split())
        ctx_words = set()
        if context_features:
            for v in context_features.values():
                if isinstance(v, str):
                    ctx_words.update(v.lower().split())

        all_words = goal_words | ctx_words

        scored = []
        with self._lock:
            for rec in self._records:
                rec_words = set(rec.goal.lower().split())
                for v in rec.context_features.values():
                    if isinstance(v, str):
                        rec_words.update(v.lower().split())

                if not all_words or not rec_words:
                    continue

                # Jaccard similarity
                intersection = len(all_words & rec_words)
                union = len(all_words | rec_words)
                similarity = intersection / union if union > 0 else 0.0

                if similarity > 0.05:
                    scored.append({
                        "record": rec.to_dict(),
                        "similarity": round(similarity, 3),
                    })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]

    def get_strategy_stats(self, strategy_type: str) -> dict:
        """Aggregate performance stats for a strategy type."""
        with self._lock:
            recs = [r for r in self._records if r.strategy_type == strategy_type]

        if not recs:
            return {"strategy_type": strategy_type, "count": 0}

        scores = [r.outcome_score for r in recs]
        return {
            "strategy_type": strategy_type,
            "count": len(recs),
            "avg_score": round(sum(scores) / len(scores), 3),
            "best_score": round(max(scores), 3),
            "worst_score": round(min(scores), 3),
            "recent_trend": _compute_trend(scores[-10:]),
        }

    def get_all_stats(self) -> list[dict]:
        """Get stats for all strategy types."""
        types = set()
        with self._lock:
            for r in self._records:
                types.add(r.strategy_type)
        return [self.get_strategy_stats(t) for t in sorted(types)]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._records)


def _compute_trend(scores: list[float]) -> str:
    """Simple trend detection from score series."""
    if len(scores) < 3:
        return "insufficient_data"
    first_half = sum(scores[:len(scores)//2]) / max(len(scores)//2, 1)
    second_half = sum(scores[len(scores)//2:]) / max(len(scores) - len(scores)//2, 1)
    diff = second_half - first_half
    if diff > 0.1:
        return "improving"
    elif diff < -0.1:
        return "degrading"
    return "stable"


# ── Singleton ─────────────────────────────────────────────────

_store: StrategicMemoryStore | None = None


def get_strategic_memory() -> StrategicMemoryStore:
    global _store
    if _store is None:
        _store = StrategicMemoryStore()
    return _store
