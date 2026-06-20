"""
executor/capability_health.py — Capability health tracking.

Tracks success/failure rates per capability.
Enables: "don't use tool X, it's been failing" during planning.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import ClassVar

import structlog

log = structlog.get_logger("executor.capability_health")


@dataclass
class CapabilityStats:
    capability_id: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    total_ms: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    last_error: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successes / self.total_calls

    @property
    def avg_latency_ms(self) -> int:
        if self.total_calls == 0:
            return 0
        return self.total_ms // self.total_calls

    def is_healthy(self, min_rate: float = 0.5) -> bool:
        if self.total_calls < 3:
            return True  # not enough data
        return self.success_rate >= min_rate

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "total_calls": self.total_calls,
            "success_rate": round(self.success_rate, 3),
            "avg_latency_ms": self.avg_latency_ms,
            "healthy": self.is_healthy(),
            "last_error": self.last_error[:100],
        }


class CapabilityHealthTracker:
    """
    Singleton tracker for capability health.
    Thread-safe. Used by MetaOrchestrator for capability-aware planning.
    """

    _instance: ClassVar[CapabilityHealthTracker | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _stats: dict[str, CapabilityStats]
    _slock: threading.Lock

    def __new__(cls) -> CapabilityHealthTracker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._stats = {}
                    cls._instance._slock = threading.Lock()
        return cls._instance

    def record_success(self, capability_id: str, duration_ms: int = 0) -> None:
        with self._slock:
            s = self._stats.setdefault(capability_id, CapabilityStats(capability_id))
            s.total_calls += 1
            s.successes += 1
            s.total_ms += duration_ms
            s.last_success_at = time.time()

    def record_failure(self, capability_id: str, error: str = "", duration_ms: int = 0) -> None:
        with self._slock:
            s = self._stats.setdefault(capability_id, CapabilityStats(capability_id))
            s.total_calls += 1
            s.failures += 1
            s.total_ms += duration_ms
            s.last_failure_at = time.time()
            s.last_error = error[:200]

    def get_health(self, capability_id: str) -> CapabilityStats | None:
        return self._stats.get(capability_id)

    def is_healthy(self, capability_id: str) -> bool:
        s = self._stats.get(capability_id)
        if s is None:
            return True  # unknown = assume healthy
        return s.is_healthy()

    def unhealthy_capabilities(self) -> list[str]:
        return [cid for cid, s in self._stats.items() if not s.is_healthy()]

    def all_stats(self) -> list[dict[str, object]]:
        return [s.to_dict() for s in self._stats.values()]

    def reset(self) -> None:
        with self._slock:
            self._stats.clear()
