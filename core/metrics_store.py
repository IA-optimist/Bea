"""
JARVIS MAX — Unified Metrics Store
====================================
Production-grade in-memory metrics with optional JSON persistence.
Thread-safe counters, histograms, and gauges covering:

  A. Mission metrics
  B. Orchestrator metrics
  C. Executor/tool metrics
  D. Model routing metrics
  E. Memory metrics
  F. Multimodal metrics
  G. Improvement loop metrics

Design:
  - Single global registry via get_metrics()
  - All metric ops are O(1) and fail-open
  - Labels support dimensional data (model_id, mission_type, etc.)
  - Snapshot export for diagnostics endpoints
  - No external dependencies (stdlib only + structlog)

Usage:
    m = get_metrics()
    m.inc("missions_submitted_total", labels={"type": "code_review"})
    m.observe("mission_duration_ms", 4200, labels={"type": "code_review"})
    m.set_gauge("executor_active_tasks", 3)
    snapshot = m.snapshot()
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# METRIC TYPES
# ═══════════════════════════════════════════════════════════════

class Counter:
    """Monotonically increasing counter with label support."""
    __slots__ = ("_values", "_lock")

    def __init__(self):
        self._values: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, labels_key: str = "", value: float = 1.0) -> None:
        with self._lock:
            self._values[labels_key] += value

    def get(self, labels_key: str = "") -> float:
        return self._values.get(labels_key, 0.0)

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def total(self) -> float:
        with self._lock:
            return sum(self._values.values())


class Histogram:
    """Records observations and computes count, sum, avg, p50, p95, p99, max."""
    __slots__ = ("_values", "_lock", "_max_samples")

    def __init__(self, max_samples: int = 1000):
        self._values: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._max_samples = max_samples

    def observe(self, value: float, labels_key: str = "") -> None:
        with self._lock:
            buf = self._values[labels_key]
            buf.append(value)
            if len(buf) > self._max_samples:
                # Keep last N samples (sliding window)
                self._values[labels_key] = buf[-self._max_samples:]

    def stats(self, labels_key: str = "") -> dict[str, float]:
        with self._lock:
            buf = self._values.get(labels_key, [])
            if not buf:
                return {"count": 0, "sum": 0, "avg": 0, "p50": 0,
                        "p95": 0, "p99": 0, "max": 0, "min": 0}
            s = sorted(buf)
            n = len(s)
            return {
                "count": n,
                "sum": round(sum(s), 2),
                "avg": round(sum(s) / n, 2),
                "min": round(s[0], 2),
                "p50": round(s[int(n * 0.50)], 2),
                "p95": round(s[min(int(n * 0.95), n - 1)], 2),
                "p99": round(s[min(int(n * 0.99), n - 1)], 2),
                "max": round(s[-1], 2),
            }

    def get_all_keys(self) -> list[str]:
        with self._lock:
            return list(self._values.keys())


class Gauge:
    """Point-in-time value."""
    __slots__ = ("_values", "_lock")

    def __init__(self):
        self._values: dict[str, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels_key: str = "") -> None:
        with self._lock:
            self._values[labels_key] = value

    def get(self, labels_key: str = "") -> float:
        return self._values.get(labels_key, 0.0)

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)


# ═══════════════════════════════════════════════════════════════
# FAILURE PATTERN TRACKER
# ═══════════════════════════════════════════════════════════════

@dataclass
class FailureRecord:
    category: str       # timeout, auth, provider, validation, tool_crash, memory_miss, approval_timeout, multimodal
    component: str      # which subsystem
    message: str
    timestamp: float = field(default_factory=time.time)
    mission_id: str = ""
    model_id: str = ""
    tool_name: str = ""


class FailureAggregator:
    """Tracks recurring failure patterns by category."""

    def __init__(self, max_records: int = 500):
        self._records: list[FailureRecord] = []
        self._lock = threading.Lock()
        self._max = max_records

    def record(self, failure: FailureRecord) -> None:
        with self._lock:
            self._records.append(failure)
            if len(self._records) > self._max:
                self._records = self._records[-self._max:]

    def by_category(self, window_s: float = 3600) -> dict[str, int]:
        cutoff = time.time() - window_s
        with self._lock:
            counts: dict[str, int] = defaultdict(int)
            for r in self._records:
                if r.timestamp >= cutoff:
                    counts[r.category] += 1
            return dict(counts)

    def top_failures(self, limit: int = 10, window_s: float = 3600) -> list[dict]:
        cutoff = time.time() - window_s
        with self._lock:
            recent = [r for r in self._records if r.timestamp >= cutoff]
        # Group by (category, component)
        groups: dict[tuple, list[FailureRecord]] = defaultdict(list)
        for r in recent:
            groups[(r.category, r.component)].append(r)
        ranked = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
        return [
            {
                "category": k[0], "component": k[1],
                "count": len(v), "last_message": v[-1].message[:200],
                "last_at": v[-1].timestamp,
            }
            for k, v in ranked[:limit]
        ]

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [asdict(r) for r in self._records[-limit:]]


# ═══════════════════════════════════════════════════════════════
# COST TRACKER
# ═══════════════════════════════════════════════════════════════

# Conservative estimated cost per 1M tokens (input) by model tier
_COST_TIERS: dict[str, float] = {
    "free":      0.00,
    "nano":      0.10,   # gemini flash lite, gpt-4o-mini
    "cheap":     0.50,   # deepseek, minimax
    "standard":  3.00,   # claude sonnet, gpt-4o
    "premium":   15.00,  # claude opus, gpt-4.5
    "local":     0.00,   # ollama
}


class CostTracker:
    """Tracks estimated LLM costs by model and mission."""

    def __init__(self):
        self._by_model: dict[str, float] = defaultdict(float)
        self._by_mission: dict[str, float] = defaultdict(float)
        self._total: float = 0.0
        self._lock = threading.Lock()

    def record(self, model_id: str, tokens: int, cost_tier: str = "standard",
               mission_id: str = "", actual_cost: float | None = None) -> None:
        cost = actual_cost if actual_cost is not None else (
            tokens / 1_000_000 * _COST_TIERS.get(cost_tier, 3.0))
        with self._lock:
            self._by_model[model_id] += cost
            if mission_id:
                self._by_mission[mission_id] += cost
            self._total += cost

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_estimated_usd": round(self._total, 4),
                "by_model": {k: round(v, 4) for k, v in sorted(
                    self._by_model.items(), key=lambda x: x[1], reverse=True)},
                "top_missions": dict(sorted(
                    self._by_mission.items(), key=lambda x: x[1], reverse=True)[:10]),
            }


# ═══════════════════════════════════════════════════════════════
# UNIFIED METRICS REGISTRY
# ═══════════════════════════════════════════════════════════════

class MetricsRegistry:
    """
    Central metrics store for all JarvisMax subsystems.

    Thread-safe. Fail-open (never crashes caller).
    All metric names are strings; labels are encoded as `key=val,key=val`.
    """

    def __init__(self):
        self._counters: dict[str, Counter] = defaultdict(Counter)
        self._histograms: dict[str, Histogram] = defaultdict(Histogram)
        self._gauges: dict[str, Gauge] = defaultdict(Gauge)
        self.failures = FailureAggregator()
        self.costs = CostTracker()
        self._created_at = time.time()

    # ── Label encoding ────────────────────────────────────────

    @staticmethod
    def _labels_key(labels: dict[str, str] | None) -> str:
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))

    # ── Counter ops ───────────────────────────────────────────

    def inc(self, name: str, value: float = 1.0,
            labels: dict[str, str] | None = None) -> None:
        try:
            self._counters[name].inc(self._labels_key(labels), value)
        except Exception:
            _silent_log.debug("suppressed_exception", src='metrics_store.py')

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        return self._counters[name].get(self._labels_key(labels))

    def get_counter_total(self, name: str) -> float:
        return self._counters[name].total()

    # ── Histogram ops ─────────────────────────────────────────

    def observe(self, name: str, value: float,
                labels: dict[str, str] | None = None) -> None:
        try:
            self._histograms[name].observe(value, self._labels_key(labels))
        except Exception:
            _silent_log.debug("suppressed_exception", src='metrics_store.py')

    def get_histogram(self, name: str,
                      labels: dict[str, str] | None = None) -> dict[str, float]:
        return self._histograms[name].stats(self._labels_key(labels))

    # ── Gauge ops ─────────────────────────────────────────────

    def set_gauge(self, name: str, value: float,
                  labels: dict[str, str] | None = None) -> None:
        try:
            self._gauges[name].set(value, self._labels_key(labels))
        except Exception:
            _silent_log.debug("suppressed_exception", src='metrics_store.py')

    def get_gauge(self, name: str,
                  labels: dict[str, str] | None = None) -> float:
        return self._gauges[name].get(self._labels_key(labels))

    # ── Failure tracking ──────────────────────────────────────

    def record_failure(self, category: str, component: str, message: str,
                       mission_id: str = "", model_id: str = "",
                       tool_name: str = "") -> None:
        try:
            self.failures.record(FailureRecord(
                category=category, component=component, message=message[:500],
                mission_id=mission_id, model_id=model_id, tool_name=tool_name))
            self.inc("failures_total", labels={"category": category, "component": component})
        except Exception:
            _silent_log.debug("suppressed_exception", src='metrics_store.py')

    # ── Cost tracking ─────────────────────────────────────────

    def record_cost(self, model_id: str, tokens: int, cost_tier: str = "standard",
                    mission_id: str = "", actual_cost: float | None = None) -> None:
        try:
            self.costs.record(model_id, tokens, cost_tier, mission_id, actual_cost)
            self.inc("estimated_cost_total", labels={"model_id": model_id})
        except Exception:
            _silent_log.debug("suppressed_exception", src='metrics_store.py')

    # ── Snapshot ──────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Full metrics snapshot for diagnostics endpoint."""
        result: dict[str, Any] = {
            "uptime_s": int(time.time() - self._created_at),
            "snapshot_at": time.time(),
        }

        # Counters
        counters: dict[str, Any] = {}
        for name, counter in sorted(self._counters.items()):
            all_vals = counter.get_all()
            if len(all_vals) == 1 and "" in all_vals:
                counters[name] = all_vals[""]
            else:
                counters[name] = {"_total": counter.total(), **all_vals}
        result["counters"] = counters

        # Histograms
        histograms: dict[str, Any] = {}
        for name, histogram in sorted(self._histograms.items()):
            keys = histogram.get_all_keys()
            if len(keys) == 1 and keys[0] == "":
                histograms[name] = histogram.stats("")
            else:
                histograms[name] = {k or "_default": histogram.stats(k) for k in keys}
        result["histograms"] = histograms

        # Gauges
        gauges: dict[str, Any] = {}
        for name, gauge in sorted(self._gauges.items()):
            all_vals = gauge.get_all()
            if len(all_vals) == 1 and "" in all_vals:
                gauges[name] = all_vals[""]
            else:
                gauges[name] = all_vals
        result["gauges"] = gauges

        # Failures
        result["failure_patterns"] = self.failures.by_category()
        result["top_failures"] = self.failures.top_failures(limit=5)

        # Costs
        result["costs"] = self.costs.snapshot()

        return result

    def human_summary(self) -> str:
        """Human-readable status overview."""
        s = self.snapshot()
        c = s["counters"]
        g = s["gauges"]

        lines = ["═══ JARVISMAX SYSTEM STATUS ═══"]
        lines.append(f"Uptime: {s['uptime_s']}s")
        lines.append("")

        # Missions
        submitted = c.get("missions_submitted_total", 0)
        completed = c.get("missions_completed_total", 0)
        failed = c.get("missions_failed_total", 0)
        if isinstance(submitted, dict): submitted = submitted.get("_total", 0)
        if isinstance(completed, dict): completed = completed.get("_total", 0)
        if isinstance(failed, dict): failed = failed.get("_total", 0)
        rate = round(completed / submitted * 100, 1) if submitted > 0 else 0
        lines.append(f"── Missions ──")
        lines.append(f"  Submitted: {int(submitted)}  Completed: {int(completed)}  Failed: {int(failed)}  Rate: {rate}%")

        # Mission duration
        dur = s["histograms"].get("mission_duration_ms", {})
        if dur and dur.get("count", 0) > 0:
            lines.append(f"  Duration: avg={dur['avg']}ms  p95={dur['p95']}ms  max={dur['max']}ms")

        # Model routing
        model_selected = c.get("model_selected_total", {})
        if isinstance(model_selected, dict) and model_selected:
            lines.append(f"\n── Model Routing ──")
            for k, v in sorted(model_selected.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0):
                if k == "_total": continue
                lines.append(f"  {k}: {int(v)} calls")

        fallbacks = c.get("fallback_used_total", 0)
        if isinstance(fallbacks, dict): fallbacks = fallbacks.get("_total", 0)
        if fallbacks:
            lines.append(f"  Fallbacks: {int(fallbacks)}")

        # Executor
        tool_total = c.get("tool_invocations_total", 0)
        tool_fail = c.get("tool_failures_total", 0)
        if isinstance(tool_total, dict): tool_total = tool_total.get("_total", 0)
        if isinstance(tool_fail, dict): tool_fail = tool_fail.get("_total", 0)
        if tool_total:
            lines.append(f"\n── Executor ──")
            lines.append(f"  Tool calls: {int(tool_total)}  Failures: {int(tool_fail)}  "
                         f"Rate: {round((1 - tool_fail / tool_total) * 100, 1) if tool_total > 0 else 0}%")
            active = g.get("executor_active_tasks", 0)
            if active: lines.append(f"  Active tasks: {int(active)}")

        # Memory
        mem_total = c.get("memory_entries_total", 0)
        if isinstance(mem_total, dict): mem_total = mem_total.get("_total", 0)
        if mem_total:
            lines.append(f"\n── Memory ──")
            lines.append(f"  Entries: {int(mem_total)}")
            hit_rate = g.get("memory_search_hit_rate", 0)
            if hit_rate: lines.append(f"  Search hit rate: {round(hit_rate * 100, 1)}%")

        # Improvement loop
        exp_started = c.get("experiments_started_total", 0)
        if isinstance(exp_started, dict): exp_started = exp_started.get("_total", 0)
        if exp_started:
            exp_promoted = c.get("experiments_promoted_total", 0)
            exp_rejected = c.get("experiments_rejected_total", 0)
            if isinstance(exp_promoted, dict): exp_promoted = exp_promoted.get("_total", 0)
            if isinstance(exp_rejected, dict): exp_rejected = exp_rejected.get("_total", 0)
            lines.append(f"\n── Improvement Loop ──")
            lines.append(f"  Experiments: {int(exp_started)}  Promoted: {int(exp_promoted)}  Rejected: {int(exp_rejected)}")

        # Failure patterns
        fp = s["failure_patterns"]
        if fp:
            lines.append(f"\n── Failure Patterns (1h) ──")
            for cat, count in sorted(fp.items(), key=lambda x: -x[1]):
                lines.append(f"  {cat}: {count}")

        # Costs
        costs = s["costs"]
        if costs["total_estimated_usd"] > 0:
            lines.append(f"\n── Estimated Cost ──")
            lines.append(f"  Total: ${costs['total_estimated_usd']:.4f}")
            for m, c_val in list(costs["by_model"].items())[:5]:
                lines.append(f"  {m}: ${c_val:.4f}")

        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metrics (for tests)."""
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()
        self.failures = FailureAggregator()
        self.costs = CostTracker()
        self._created_at = time.time()


# ═══════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════

_instance: MetricsRegistry | None = None
_instance_lock = threading.Lock()


def get_metrics() -> MetricsRegistry:
    """Get the global MetricsRegistry singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MetricsRegistry()
    return _instance


def reset_metrics() -> MetricsRegistry:
    """Reset and return a fresh MetricsRegistry (for tests)."""
    global _instance
    with _instance_lock:
        _instance = MetricsRegistry()
    return _instance


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE EMITTERS (import-and-call from any subsystem)
# ═══════════════════════════════════════════════════════════════

def emit_mission_submitted(mission_type: str = "unknown") -> None:
    m = get_metrics()
    m.inc("missions_submitted_total", labels={"type": mission_type})

def emit_mission_completed(mission_type: str = "unknown", duration_ms: float = 0) -> None:
    m = get_metrics()
    m.inc("missions_completed_total", labels={"type": mission_type})
    if duration_ms > 0:
        m.observe("mission_duration_ms", duration_ms, labels={"type": mission_type})

def emit_mission_failed(mission_type: str = "unknown", reason: str = "") -> None:
    m = get_metrics()
    m.inc("missions_failed_total", labels={"type": mission_type})
    if reason:
        m.record_failure("mission_failure", "mission_system", reason)

def emit_mission_timeout(mission_type: str = "unknown") -> None:
    m = get_metrics()
    m.inc("mission_timeout_total", labels={"type": mission_type})

def emit_tool_invocation(tool_name: str, success: bool, duration_ms: float = 0) -> None:
    m = get_metrics()
    m.inc("tool_invocations_total", labels={"tool": tool_name})
    if not success:
        m.inc("tool_failures_total", labels={"tool": tool_name})
    if duration_ms > 0:
        m.observe("tool_latency_ms", duration_ms, labels={"tool": tool_name})

def emit_tool_timeout(tool_name: str) -> None:
    get_metrics().inc("tool_timeout_total", labels={"tool": tool_name})

def emit_model_selected(model_id: str, locality: str = "cloud") -> None:
    m = get_metrics()
    m.inc("model_selected_total", labels={"model_id": model_id})
    if locality == "local":
        m.inc("local_only_route_total")
    else:
        m.inc("cloud_route_total")

def emit_model_failure(model_id: str, error: str = "") -> None:
    m = get_metrics()
    m.inc("model_failure_total", labels={"model_id": model_id})
    if error:
        m.record_failure("provider", "model_routing", error, model_id=model_id)

def emit_model_latency(model_id: str, latency_ms: float) -> None:
    get_metrics().observe("model_latency_ms", latency_ms, labels={"model_id": model_id})

def emit_fallback_used(from_model: str = "", to_model: str = "") -> None:
    get_metrics().inc("fallback_used_total", labels={"from": from_model, "to": to_model})

def emit_memory_search(hit: bool, latency_ms: float = 0) -> None:
    m = get_metrics()
    m.inc("memory_search_total")
    if hit:
        m.inc("memory_search_hits")
    if latency_ms > 0:
        m.observe("memory_search_latency_ms", latency_ms)

def emit_experiment(outcome: str, score_delta: float = 0) -> None:
    m = get_metrics()
    m.inc("experiments_started_total")
    if outcome == "promoted":
        m.inc("experiments_promoted_total")
    elif outcome == "rejected":
        m.inc("experiments_rejected_total")
    elif outcome == "blocked":
        m.inc("regressions_blocked_total")
    m.inc("lessons_learned_total")
    if score_delta != 0:
        m.observe("score_delta", score_delta)

def emit_multimodal_task(modality: str, success: bool, latency_ms: float = 0) -> None:
    m = get_metrics()
    m.inc("multimodal_tasks_total", labels={"modality": modality})
    if not success:
        m.inc("multimodal_failures_total", labels={"modality": modality})
    if modality == "vision" and latency_ms > 0:
        m.observe("vision_latency_ms", latency_ms)
    if not success and modality == "vision":
        m.inc("vision_fallback_total")

def emit_circuit_breaker(state: str) -> None:
    m = get_metrics()
    if state == "open":
        m.inc("circuit_breaker_open_total")
    m.set_gauge("circuit_breaker_state", {"closed": 0, "half_open": 1, "open": 2}.get(state, -1))

def emit_orchestrator_timing(phase: str, latency_ms: float) -> None:
    get_metrics().observe(f"{phase}_latency_ms", latency_ms)

def emit_retry(component: str = "executor") -> None:
    get_metrics().inc("retry_attempts_total", labels={"component": component})
