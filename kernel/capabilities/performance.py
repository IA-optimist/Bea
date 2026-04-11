"""
kernel/capabilities/performance.py — Capability performance intelligence.

Tracks real-world execution outcomes to compute:
  - success_rate per capability / provider / tool
  - avg_duration per entity
  - recent trend (exponential moving average)
  - confidence score (how reliable is our estimate)

Design:
  - In-memory, no external deps
  - Exponential moving average (α=0.2) for recent trend
  - Sliding window for recent sample tracking
  - Thread-safe
  - All operations fail-open
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("kernel.capabilities.performance")

# EMA smoothing factor: higher = more weight on recent events
_EMA_ALPHA = 0.2
# Minimum samples before we trust the data
_MIN_CONFIDENCE_SAMPLES = 5
# Recent window size
_RECENT_WINDOW = 50


@dataclass
class PerformanceRecord:
    """Performance metrics for a single entity (capability, provider, or tool)."""
    entity_id: str
    entity_type: str  # "capability", "provider", "tool"

    # Counters
    total: int = 0
    successes: int = 0
    failures: int = 0

    # Duration tracking (milliseconds)
    total_duration_ms: float = 0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0

    # Exponential moving average of success (0.0 to 1.0)
    ema_success: float = 0.5  # start neutral

    # Recent window (circular buffer of booleans: True=success)
    _recent: list[bool] = field(default_factory=list)

    # Timestamps
    first_seen: float = 0
    last_seen: float = 0
    last_success: float = 0
    last_failure: float = 0

    def record_outcome(self, success: bool, duration_ms: float = 0) -> None:
        """Record an execution outcome."""
        now = time.time()
        self.total += 1
        if not self.first_seen:
            self.first_seen = now
        self.last_seen = now

        if success:
            self.successes += 1
            self.last_success = now
        else:
            self.failures += 1
            self.last_failure = now

        # Duration
        if duration_ms > 0:
            self.total_duration_ms += duration_ms
            self.min_duration_ms = min(self.min_duration_ms, duration_ms)
            self.max_duration_ms = max(self.max_duration_ms, duration_ms)

        # EMA update
        outcome = 1.0 if success else 0.0
        self.ema_success = _EMA_ALPHA * outcome + (1 - _EMA_ALPHA) * self.ema_success

        # Recent window
        self._recent.append(success)
        if len(self._recent) > _RECENT_WINDOW:
            self._recent = self._recent[-_RECENT_WINDOW:]

    @property
    def success_rate(self) -> float:
        """Overall success rate (0.0 to 1.0)."""
        return self.successes / self.total if self.total > 0 else 0.0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.total if self.total > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.total if self.total > 0 else 0.0

    @property
    def recent_success_rate(self) -> float:
        """Success rate over recent window only."""
        if not self._recent:
            return 0.0
        return sum(1 for r in self._recent if r) / len(self._recent)

    @property
    def confidence(self) -> float:
        """
        How confident are we in this performance estimate?

        Factors:
          - Sample size (more samples = higher confidence)
          - Recency (recent data = higher confidence)
          - Consistency (stable rate = higher confidence)
        """
        if self.total == 0:
            return 0.0

        # Sample size factor: ramps from 0 to 1 over _MIN_CONFIDENCE_SAMPLES
        sample_factor = min(self.total / _MIN_CONFIDENCE_SAMPLES, 1.0)

        # Recency factor: decays if last event was long ago
        age_seconds = time.time() - self.last_seen if self.last_seen else 3600
        recency_factor = max(0.1, 1.0 - (age_seconds / 86400))  # decays over 24h

        # Consistency: how close is EMA to overall rate?
        if self.total >= 3:
            consistency = 1.0 - abs(self.ema_success - self.success_rate)
        else:
            consistency = 0.5

        return round(sample_factor * 0.5 + recency_factor * 0.3 + consistency * 0.2, 3)

    @property
    def trend(self) -> str:
        """Recent trend: improving, degrading, stable, or unknown."""
        if len(self._recent) < 4:
            return "unknown"
        half = len(self._recent) // 2
        first_half = sum(1 for r in self._recent[:half] if r) / half
        second_half = sum(1 for r in self._recent[half:] if r) / (len(self._recent) - half)
        diff = second_half - first_half
        if diff > 0.15:
            return "improving"
        elif diff < -0.15:
            return "degrading"
        return "stable"

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "total": self.total,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 3),
            "failure_rate": round(self.failure_rate, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "min_duration_ms": round(self.min_duration_ms, 1) if self.min_duration_ms != float("inf") else None,
            "max_duration_ms": round(self.max_duration_ms, 1),
            "ema_success": round(self.ema_success, 3),
            "recent_success_rate": round(self.recent_success_rate, 3),
            "confidence": self.confidence,
            "trend": self.trend,
            "recent_samples": len(self._recent),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    def to_persistent_dict(self) -> dict:
        """Serializable dict including internal state for persistence."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "total": self.total,
            "successes": self.successes,
            "failures": self.failures,
            "total_duration_ms": self.total_duration_ms,
            "min_duration_ms": self.min_duration_ms if self.min_duration_ms != float("inf") else None,
            "max_duration_ms": self.max_duration_ms,
            "ema_success": round(self.ema_success, 6),
            "recent": self._recent[-_RECENT_WINDOW:],
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
        }

    @classmethod
    def from_persistent_dict(cls, data: dict) -> "PerformanceRecord":
        """Restore a PerformanceRecord from persistent dict."""
        record = cls(
            entity_id=data["entity_id"],
            entity_type=data["entity_type"],
        )
        record.total = data.get("total", 0)
        record.successes = data.get("successes", 0)
        record.failures = data.get("failures", 0)
        record.total_duration_ms = data.get("total_duration_ms", 0)
        min_d = data.get("min_duration_ms")
        record.min_duration_ms = min_d if min_d is not None else float("inf")
        record.max_duration_ms = data.get("max_duration_ms", 0)
        record.ema_success = data.get("ema_success", 0.5)
        record._recent = data.get("recent", [])[-_RECENT_WINDOW:]
        record.first_seen = data.get("first_seen", 0)
        record.last_seen = data.get("last_seen", 0)
        record.last_success = data.get("last_success", 0)
        record.last_failure = data.get("last_failure", 0)
        return record


class PerformanceStore:
    """
    Thread-safe store for capability/provider/tool performance metrics.

    All public methods are fail-open — never raises.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._records: dict[str, PerformanceRecord] = {}

    def _key(self, entity_type: str, entity_id: str) -> str:
        return f"{entity_type}:{entity_id}"

    def _get_or_create(self, entity_type: str, entity_id: str) -> PerformanceRecord:
        key = self._key(entity_type, entity_id)
        if key not in self._records:
            self._records[key] = PerformanceRecord(
                entity_id=entity_id,
                entity_type=entity_type,
            )
        return self._records[key]

    # ── Recording ─────────────────────────────────────────────

    def record_tool_outcome(self, tool_id: str, success: bool,
                            duration_ms: float = 0,
                            capability_id: str = "",
                            provider_id: str = "") -> None:
        """Record a tool execution outcome. Updates tool, capability, and provider records."""
        with self._lock:
            # Tool level
            self._get_or_create("tool", tool_id).record_outcome(success, duration_ms)

            # Capability level (if known)
            if capability_id:
                self._get_or_create("capability", capability_id).record_outcome(success, duration_ms)

            # Provider level (if known)
            if provider_id:
                self._get_or_create("provider", provider_id).record_outcome(success, duration_ms)

    def record_step_outcome(self, step_id: str, success: bool,
                            step_type: str = "",
                            capability_id: str = "",
                            provider_id: str = "") -> None:
        """Record a step execution outcome."""
        with self._lock:
            if capability_id:
                self._get_or_create("capability", capability_id).record_outcome(success)
            if provider_id:
                self._get_or_create("provider", provider_id).record_outcome(success)
            if step_type:
                self._get_or_create("step_type", step_type).record_outcome(success)

    # ── Querying ──────────────────────────────────────────────

    def get_performance(self, entity_type: str, entity_id: str) -> dict | None:
        """Get performance for a specific entity."""
        with self._lock:
            key = self._key(entity_type, entity_id)
            record = self._records.get(key)
            return record.to_dict() if record else None

    def get_tool_performance(self, tool_id: str) -> dict | None:
        return self.get_performance("tool", tool_id)

    def get_capability_performance(self, capability_id: str) -> dict | None:
        return self.get_performance("capability", capability_id)

    def get_provider_performance(self, provider_id: str) -> dict | None:
        return self.get_performance("provider", provider_id)

    def get_all(self, entity_type: str = "") -> list[dict]:
        """Get all performance records, optionally filtered by type."""
        with self._lock:
            records = []
            for key, record in self._records.items():
                if entity_type and record.entity_type != entity_type:
                    continue
                records.append(record.to_dict())
            return sorted(records, key=lambda r: r["total"], reverse=True)

    def get_degraded(self, threshold: float = 0.5) -> list[dict]:
        """Get entities with success rate below threshold."""
        with self._lock:
            return [
                r.to_dict() for r in self._records.values()
                if r.total >= _MIN_CONFIDENCE_SAMPLES and r.success_rate < threshold
            ]

    def get_summary(self) -> dict:
        """Get aggregate performance summary."""
        with self._lock:
            by_type: dict[str, dict] = {}
            for record in self._records.values():
                t = record.entity_type
                if t not in by_type:
                    by_type[t] = {"count": 0, "total_executions": 0, "total_successes": 0}
                by_type[t]["count"] += 1
                by_type[t]["total_executions"] += record.total
                by_type[t]["total_successes"] += record.successes

            for t, stats in by_type.items():
                total = stats["total_executions"]
                stats["avg_success_rate"] = round(
                    stats["total_successes"] / total, 3
                ) if total > 0 else None

            return {
                "total_entities": len(self._records),
                "by_type": by_type,
            }

    def reset(self) -> None:
        """Clear all performance data."""
        with self._lock:
            self._records.clear()

    # ── Persistence ───────────────────────────────────────────

    def save_to_file(self, path: str | Path) -> bool:
        """
        Save all performance records to a JSON file.

        Atomic write (write to .tmp then rename) to prevent corruption.
        Returns True on success, False on failure (fail-open).
        """
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                data = {
                    "version": 1,
                    "saved_at": time.time(),
                    "record_count": len(self._records),
                    "records": {
                        key: record.to_persistent_dict()
                        for key, record in self._records.items()
                    },
                }

            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(str(tmp_path), str(path))

            log.info("performance_saved", path=str(path),
                     records=data["record_count"])
            return True

        except Exception as e:
            log.debug("performance_save_failed", err=str(e)[:80])
            return False

    def load_from_file(self, path: str | Path) -> int:
        """
        Load performance records from a JSON file.

        Merges with existing records: loaded records that don't exist
        in memory are added; existing records are left untouched
        (runtime data takes priority over stale disk data).

        Returns number of records loaded. Returns 0 on failure (fail-open).
        """
        try:
            path = Path(path)
            if not path.exists():
                return 0

            with open(path) as f:
                data = json.load(f)

            if data.get("version") != 1:
                log.debug("performance_load_skip", reason="unknown version")
                return 0

            loaded = 0
            with self._lock:
                for key, record_data in data.get("records", {}).items():
                    # Only load records that don't already exist in memory
                    # Runtime observations are fresher than disk snapshots
                    if key not in self._records:
                        try:
                            record = PerformanceRecord.from_persistent_dict(record_data)
                            self._records[key] = record
                            loaded += 1
                        except Exception as e:
                            log.debug("performance_record_skip",
                                      key=key, err=str(e)[:60])

            log.info("performance_loaded", path=str(path),
                     loaded=loaded, total=len(self._records))
            return loaded

        except Exception as e:
            log.debug("performance_load_failed", err=str(e)[:80])
            return 0

    def merge_from_file(self, path: str | Path) -> int:
        """
        Merge performance records from a file, combining with existing.

        Unlike load_from_file (which skips existing), this merges:
        - For existing records: keeps the one with more total observations
        - For new records: adds them

        Returns number of records merged/added.
        """
        try:
            path = Path(path)
            if not path.exists():
                return 0

            with open(path) as f:
                data = json.load(f)

            if data.get("version") != 1:
                return 0

            merged = 0
            with self._lock:
                for key, record_data in data.get("records", {}).items():
                    try:
                        disk_record = PerformanceRecord.from_persistent_dict(record_data)
                        existing = self._records.get(key)
                        if existing is None or disk_record.total > existing.total:
                            self._records[key] = disk_record
                            merged += 1
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='performance.py')

            log.info("performance_merged", path=str(path), merged=merged)
            return merged

        except Exception as e:
            log.debug("performance_merge_failed", err=str(e)[:80])
            return 0


# ── Singleton ─────────────────────────────────────────────────

_store: PerformanceStore | None = None
_store_lock = threading.Lock()


def get_performance_store() -> PerformanceStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = PerformanceStore()
    return _store
