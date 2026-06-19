"""Observability store for mission metrics.

The store is intentionally small but not ephemeral:
- bounded in-memory buffer for hot reads
- append-only JSONL persistence for replay / audits
- chained hashes to detect tampering
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MissionMetrics:
    mission_id: str
    mission_type: str
    selected_agents: List[str]
    execution_policy_decision: str
    fallback_level_used: int
    confidence_score: float
    duration_ms: int
    tools_used: List[str] = field(default_factory=list)
    ts: int = field(default_factory=lambda: int(time.time()))


class ObservabilityStore:
    """Bounded buffer with append-only replay persistence."""

    def __init__(self, max_size: int = 100, storage_path: str | Path | None = None):
        self._metrics: deque[MissionMetrics] = deque(maxlen=max_size)
        self._path = Path(storage_path) if storage_path else Path("workspace") / "observability_missions.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = "GENESIS"
        self._load()

    def _hash_record(self, m: MissionMetrics, prev_hash: str) -> str:
        payload = json.dumps(
            {
                "mission_id": m.mission_id,
                "mission_type": m.mission_type,
                "selected_agents": m.selected_agents,
                "execution_policy_decision": m.execution_policy_decision,
                "fallback_level_used": m.fallback_level_used,
                "confidence_score": m.confidence_score,
                "duration_ms": m.duration_ms,
                "tools_used": m.tools_used,
                "ts": m.ts,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text("utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                record = MissionMetrics(
                    mission_id=raw.get("mission_id", ""),
                    mission_type=raw.get("mission_type", ""),
                    selected_agents=list(raw.get("selected_agents", [])),
                    execution_policy_decision=raw.get("execution_policy_decision", ""),
                    fallback_level_used=int(raw.get("fallback_level_used", 0)),
                    confidence_score=float(raw.get("confidence_score", 0.0)),
                    duration_ms=int(raw.get("duration_ms", 0)),
                    tools_used=list(raw.get("tools_used", [])),
                    ts=int(raw.get("ts", int(time.time()))),
                )
                self._metrics.append(record)
                self._last_hash = raw.get("record_hash", self._last_hash)
        except Exception as e:
            logger.warning("[Observability] load error: %s", e)

    def record(self, m: MissionMetrics) -> None:
        try:
            self._metrics.append(m)
            record_hash = self._hash_record(m, self._last_hash)
            payload = {
                "mission_id": m.mission_id,
                "mission_type": m.mission_type,
                "selected_agents": m.selected_agents,
                "execution_policy_decision": m.execution_policy_decision,
                "fallback_level_used": m.fallback_level_used,
                "confidence_score": m.confidence_score,
                "duration_ms": m.duration_ms,
                "tools_used": m.tools_used,
                "ts": m.ts,
                "prev_hash": self._last_hash,
                "record_hash": record_hash,
            }
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._last_hash = record_hash
        except Exception as e:
            logger.warning("[Observability] record error: %s", e)

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
        """Aggregate stats over the in-memory buffer."""
        try:
            entries = list(self._metrics)
            if not entries:
                return {"count": 0}

            total = len(entries)
            avg_conf = sum(m.confidence_score for m in entries) / total
            avg_dur = sum(m.duration_ms for m in entries) / total
            fallback_count = sum(1 for m in entries if m.fallback_level_used >= 1)
            approval_count = sum(1 for m in entries if m.execution_policy_decision == "REQUIRES_APPROVAL")

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
            logger.warning("[Observability] get_stats error: %s", e)
            return {"count": 0, "error": str(e)}

    def replay(self) -> list[dict]:
        """Return the persisted append-only log in order."""
        try:
            if not self._path.exists():
                return []
            return [
                json.loads(line)
                for line in self._path.read_text("utf-8").splitlines()
                if line.strip()
            ]
        except Exception as e:
            logger.warning("[Observability] replay error: %s", e)
            return []

    def verify_chain(self) -> bool:
        """Verify chained hashes for the persisted log."""
        prev = "GENESIS"
        for entry in self.replay():
            m = MissionMetrics(
                mission_id=entry.get("mission_id", ""),
                mission_type=entry.get("mission_type", ""),
                selected_agents=list(entry.get("selected_agents", [])),
                execution_policy_decision=entry.get("execution_policy_decision", ""),
                fallback_level_used=int(entry.get("fallback_level_used", 0)),
                confidence_score=float(entry.get("confidence_score", 0.0)),
                duration_ms=int(entry.get("duration_ms", 0)),
                tools_used=list(entry.get("tools_used", [])),
                ts=int(entry.get("ts", 0)),
            )
            expected = self._hash_record(m, prev)
            if entry.get("prev_hash") != prev or entry.get("record_hash") != expected:
                return False
            prev = entry.get("record_hash", "")
        return True

    def clear(self) -> None:
        """Clear in-memory and persisted state."""
        self._metrics.clear()
        self._last_hash = "GENESIS"
        if self._path.exists():
            self._path.unlink()


_store: Optional[ObservabilityStore] = None


def get_observability_store() -> ObservabilityStore:
    global _store
    if _store is None:
        _store = ObservabilityStore()
    return _store
