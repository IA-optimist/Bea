"""
JARVIS MAX — Agent Evaluation Engine
=======================================
Structured scoring of agent quality to guide self-improvement priorities.

Consumes data from:
  - metrics_store (counters, histograms, failures, cost)
  - trace_intelligence (mission traces)
  - tool_reliability (tool health)
  - improvement_loop (lesson memory)

Outputs:
  - AgentScore (weighted composite)
  - ImprovementPriority list (ranked weaknesses)
  - Score history (evolution tracking)

Design:
  - Aggregated metrics only — no per-request overhead
  - Lazy collection — metrics pulled on evaluate(), not continuously
  - Fail-open — missing data sources produce neutral scores, never crash
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PART 2 — METRICS COLLECTION
# ═══════════════════════════════════════════════════════════════

@dataclass
class EvaluationMetrics:
    """Aggregated metrics snapshot for evaluation."""
    # Mission outcomes
    missions_total: int = 0
    missions_succeeded: int = 0
    missions_failed: int = 0

    # Rates (0.0 - 1.0)
    success_rate: float = 0.0
    retry_rate: float = 0.0
    timeout_rate: float = 0.0
    approval_rate: float = 0.0

    # Performance
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    p95_latency_ms: float = 0.0

    # Tools
    tool_calls_total: int = 0
    tool_success_rate: float = 0.0
    tool_timeout_count: int = 0

    # Self-improvement
    patch_success_rate: float = 0.0
    lessons_total: int = 0

    # Exceptions
    exception_count: int = 0
    unique_error_types: int = 0

    collected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "missions_total": self.missions_total,
            "missions_succeeded": self.missions_succeeded,
            "missions_failed": self.missions_failed,
            "success_rate": round(self.success_rate, 4),
            "retry_rate": round(self.retry_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
            "approval_rate": round(self.approval_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "avg_cost_usd": round(self.avg_cost_usd, 6),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "tool_calls_total": self.tool_calls_total,
            "tool_success_rate": round(self.tool_success_rate, 4),
            "tool_timeout_count": self.tool_timeout_count,
            "patch_success_rate": round(self.patch_success_rate, 4),
            "lessons_total": self.lessons_total,
            "exception_count": self.exception_count,
            "unique_error_types": self.unique_error_types,
            "collected_at": self.collected_at,
        }


class MetricsCollector:
    """
    Collects aggregated metrics from all runtime sources.
    Fail-open: missing sources produce neutral values.
    """

    def collect(self) -> EvaluationMetrics:
        """Pull metrics from all available sources. Non-blocking."""
        m = EvaluationMetrics()

        self._collect_missions(m)
        self._collect_tools(m)
        self._collect_performance(m)
        self._collect_exceptions(m)
        self._collect_improvement(m)

        return m

    def _collect_missions(self, m: EvaluationMetrics) -> None:
        try:
            from core.metrics_store import get_metrics
            store = get_metrics()
            m.missions_succeeded = int(store.get_counter("mission_completed_total"))
            m.missions_failed = int(store.get_counter("mission_failed_total"))
            m.missions_total = m.missions_succeeded + m.missions_failed

            if m.missions_total > 0:
                m.success_rate = m.missions_succeeded / m.missions_total
            else:
                m.success_rate = 1.0  # No data → neutral

            # Retry rate
            retry_total = store.get_counter("retry_attempts_total")
            if m.missions_total > 0:
                m.retry_rate = min(1.0, retry_total / max(m.missions_total, 1))

            # Approval rate
            approvals = store.get_counter("approval_requested_total")
            if m.missions_total > 0:
                m.approval_rate = min(1.0, approvals / max(m.missions_total, 1))
        except Exception:
            pass

    def _collect_tools(self, m: EvaluationMetrics) -> None:
        try:
            from core.metrics_store import get_metrics
            store = get_metrics()
            tool_ok = store.get_counter("tool_success_total")
            tool_fail = store.get_counter("tool_failure_total")
            m.tool_calls_total = int(tool_ok + tool_fail)
            m.tool_timeout_count = int(store.get_counter("tool_timeout_total"))

            if m.tool_calls_total > 0:
                m.tool_success_rate = tool_ok / m.tool_calls_total
            else:
                m.tool_success_rate = 1.0

            # Timeout rate
            if m.missions_total > 0:
                m.timeout_rate = min(1.0, m.tool_timeout_count / max(m.missions_total, 1))
        except Exception:
            pass

    def _collect_performance(self, m: EvaluationMetrics) -> None:
        try:
            from core.metrics_store import get_metrics
            store = get_metrics()
            hist = store.get_histogram("mission_latency_ms")
            if hist and hist.get("count", 0) > 0:
                m.avg_latency_ms = hist.get("mean", 0)
                m.p95_latency_ms = hist.get("p95", 0)

            cost_hist = store.get_histogram("mission_cost_usd")
            if cost_hist and cost_hist.get("count", 0) > 0:
                m.avg_cost_usd = cost_hist.get("mean", 0)
        except Exception:
            pass

    def _collect_exceptions(self, m: EvaluationMetrics) -> None:
        try:
            from core.metrics_store import get_metrics
            store = get_metrics()
            failures = store.failures.top_failures(limit=50, window_s=86400)
            m.exception_count = sum(f.get("count", 0) for f in failures)
            m.unique_error_types = len(failures)
        except Exception:
            pass

    def _collect_improvement(self, m: EvaluationMetrics) -> None:
        try:
            from core.self_improvement_loop import LessonMemory
            mem = LessonMemory()
            all_lessons = mem.get_all()
            m.lessons_total = len(all_lessons)
            if all_lessons:
                successes = sum(1 for l in all_lessons if l.get("result") == "success")
                m.patch_success_rate = successes / len(all_lessons)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# PART 3 — SCORING MODEL
# ═══════════════════════════════════════════════════════════════

@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""
    name: str
    value: float       # 0.0 - 10.0
    weight: float      # 0.0 - 1.0
    weighted: float = 0.0
    detail: str = ""

    def __post_init__(self):
        self.weighted = round(self.value * self.weight, 4)


@dataclass
class AgentScore:
    """Composite agent quality score."""
    overall: float = 0.0          # 0.0 - 10.0
    dimensions: list[DimensionScore] = field(default_factory=list)
    metrics: EvaluationMetrics | None = None
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 2),
            "dimensions": [
                {"name": d.name, "value": round(d.value, 2),
                 "weight": d.weight, "weighted": round(d.weighted, 2),
                 "detail": d.detail}
                for d in self.dimensions
            ],
            "computed_at": self.computed_at,
        }


# Default weights — sum to 1.0
DEFAULT_WEIGHTS = {
    "success_rate": 0.25,
    "stability": 0.15,
    "reasoning_quality": 0.15,
    "cost_efficiency": 0.15,
    "tool_accuracy": 0.15,
    "autonomy": 0.15,
}


class ScoringModel:
    """
    Computes weighted composite agent score from metrics.

    Dimensions:
    1. success_rate    (0.25) — mission completion rate
    2. stability       (0.15) — low retries, low timeouts, low exceptions
    3. reasoning_quality (0.15) — inferred from retry rate + patch success
    4. cost_efficiency (0.15) — lower cost per successful mission
    5. tool_accuracy   (0.15) — tool success rate
    6. autonomy        (0.15) — low approval rate
    """

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = weights or DEFAULT_WEIGHTS

    def score(self, metrics: EvaluationMetrics) -> AgentScore:
        """Compute composite score from metrics."""
        dims: list[DimensionScore] = []

        # 1. Success rate → direct mapping (0-1 → 0-10)
        dims.append(DimensionScore(
            name="success_rate",
            value=metrics.success_rate * 10,
            weight=self._weights["success_rate"],
            detail=f"{metrics.missions_succeeded}/{metrics.missions_total} missions",
        ))

        # 2. Stability → inverse of failure signals
        stability = 10.0
        if metrics.retry_rate > 0:
            stability -= min(3.0, metrics.retry_rate * 10)
        if metrics.timeout_rate > 0:
            stability -= min(3.0, metrics.timeout_rate * 10)
        if metrics.exception_count > 0:
            stability -= min(2.0, metrics.exception_count * 0.2)
        stability = max(0.0, stability)
        dims.append(DimensionScore(
            name="stability",
            value=stability,
            weight=self._weights["stability"],
            detail=f"retry={metrics.retry_rate:.0%} timeout={metrics.timeout_rate:.0%} exceptions={metrics.exception_count}",
        ))

        # 3. Reasoning quality → inferred from retry rate + patch success
        reasoning = 7.0  # baseline
        if metrics.retry_rate > 0.3:
            reasoning -= 2.0  # high retries suggest poor reasoning
        if metrics.patch_success_rate > 0.5:
            reasoning += 1.5
        elif metrics.patch_success_rate < 0.2 and metrics.lessons_total > 3:
            reasoning -= 1.0
        reasoning = max(0.0, min(10.0, reasoning))
        dims.append(DimensionScore(
            name="reasoning_quality",
            value=reasoning,
            weight=self._weights["reasoning_quality"],
            detail=f"patch_success={metrics.patch_success_rate:.0%} retries={metrics.retry_rate:.0%}",
        ))

        # 4. Cost efficiency → lower is better
        if metrics.avg_cost_usd <= 0 or metrics.missions_total == 0:
            cost_score = 8.0  # no data → generous
        elif metrics.avg_cost_usd < 0.01:
            cost_score = 10.0
        elif metrics.avg_cost_usd < 0.05:
            cost_score = 9.0
        elif metrics.avg_cost_usd < 0.20:
            cost_score = 7.0
        elif metrics.avg_cost_usd < 1.00:
            cost_score = 5.0
        else:
            cost_score = max(1.0, 5.0 - (metrics.avg_cost_usd - 1.0))
        dims.append(DimensionScore(
            name="cost_efficiency",
            value=cost_score,
            weight=self._weights["cost_efficiency"],
            detail=f"avg=${metrics.avg_cost_usd:.4f}/mission",
        ))

        # 5. Tool accuracy → tool success rate
        dims.append(DimensionScore(
            name="tool_accuracy",
            value=metrics.tool_success_rate * 10,
            weight=self._weights["tool_accuracy"],
            detail=f"{metrics.tool_calls_total} calls, {metrics.tool_timeout_count} timeouts",
        ))

        # 6. Autonomy → inverse of approval rate
        autonomy = 10.0 - (metrics.approval_rate * 10)
        autonomy = max(0.0, min(10.0, autonomy))
        dims.append(DimensionScore(
            name="autonomy",
            value=autonomy,
            weight=self._weights["autonomy"],
            detail=f"approval_rate={metrics.approval_rate:.0%}",
        ))

        # Composite
        overall = sum(d.weighted for d in dims)

        return AgentScore(
            overall=overall,
            dimensions=dims,
            metrics=metrics,
        )


# ═══════════════════════════════════════════════════════════════
# PART 4 — WEAKNESS DETECTION
# ═══════════════════════════════════════════════════════════════

class WeaknessType(str, Enum):
    FREQUENT_FAILURES = "frequent_failures"
    INEFFICIENT_MODEL = "inefficient_model"
    EXCESSIVE_RETRIES = "excessive_retries"
    FREQUENT_TIMEOUTS = "frequent_timeouts"
    POOR_TOOL_SELECTION = "poor_tool_selection"
    HIGH_COST = "high_cost"
    LOW_AUTONOMY = "low_autonomy"


@dataclass
class ImprovementPriority:
    """A prioritized weakness for the improvement loop to address."""
    weakness_type: str
    severity: str       # low, medium, high, critical
    component: str      # which part of the system
    description: str
    impact_score: float  # 0-1, estimated improvement impact
    suggested_action: str
    metrics_evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.weakness_type,
            "severity": self.severity,
            "component": self.component,
            "description": self.description,
            "impact": round(self.impact_score, 3),
            "action": self.suggested_action,
            "evidence": self.metrics_evidence,
        }


class WeaknessDetector:
    """
    Detects systematic weaknesses from evaluation metrics and score dimensions.
    Produces prioritized improvement targets.
    """

    # Thresholds
    FAILURE_THRESHOLD = 0.85       # success rate below this
    RETRY_THRESHOLD = 0.20         # retry rate above this
    TIMEOUT_THRESHOLD = 0.10       # timeout rate above this
    TOOL_FAILURE_THRESHOLD = 0.85  # tool success below this
    COST_THRESHOLD = 0.50          # avg cost above this USD
    APPROVAL_THRESHOLD = 0.40      # approval rate above this

    def detect(self, score: AgentScore, metrics: EvaluationMetrics) -> list[ImprovementPriority]:
        """Detect weaknesses and return prioritized list."""
        priorities: list[ImprovementPriority] = []

        # 1. Frequent failures
        if metrics.success_rate < self.FAILURE_THRESHOLD and metrics.missions_total >= 3:
            severity = "critical" if metrics.success_rate < 0.5 else "high"
            priorities.append(ImprovementPriority(
                weakness_type=WeaknessType.FREQUENT_FAILURES,
                severity=severity,
                component="mission_executor",
                description=f"Mission success rate {metrics.success_rate:.0%} below {self.FAILURE_THRESHOLD:.0%} threshold",
                impact_score=1.0 - metrics.success_rate,
                suggested_action="Analyze failure traces, improve error handling in executor",
                metrics_evidence={"success_rate": metrics.success_rate,
                                  "failed": metrics.missions_failed},
            ))

        # 2. Excessive retries
        if metrics.retry_rate > self.RETRY_THRESHOLD:
            severity = "high" if metrics.retry_rate > 0.5 else "medium"
            priorities.append(ImprovementPriority(
                weakness_type=WeaknessType.EXCESSIVE_RETRIES,
                severity=severity,
                component="retry_policy",
                description=f"Retry rate {metrics.retry_rate:.0%} above {self.RETRY_THRESHOLD:.0%} threshold",
                impact_score=min(1.0, metrics.retry_rate),
                suggested_action="Tune retry policy, improve first-attempt success",
                metrics_evidence={"retry_rate": metrics.retry_rate},
            ))

        # 3. Frequent timeouts
        if metrics.timeout_rate > self.TIMEOUT_THRESHOLD:
            severity = "high" if metrics.timeout_rate > 0.3 else "medium"
            priorities.append(ImprovementPriority(
                weakness_type=WeaknessType.FREQUENT_TIMEOUTS,
                severity=severity,
                component="tool_executor",
                description=f"Timeout rate {metrics.timeout_rate:.0%} with {metrics.tool_timeout_count} tool timeouts",
                impact_score=min(1.0, metrics.timeout_rate * 2),
                suggested_action="Increase timeouts or optimize slow tools",
                metrics_evidence={"timeout_rate": metrics.timeout_rate,
                                  "timeout_count": metrics.tool_timeout_count},
            ))

        # 4. Poor tool selection
        if metrics.tool_success_rate < self.TOOL_FAILURE_THRESHOLD and metrics.tool_calls_total >= 5:
            severity = "high" if metrics.tool_success_rate < 0.6 else "medium"
            priorities.append(ImprovementPriority(
                weakness_type=WeaknessType.POOR_TOOL_SELECTION,
                severity=severity,
                component="tool_intelligence",
                description=f"Tool success rate {metrics.tool_success_rate:.0%} below {self.TOOL_FAILURE_THRESHOLD:.0%}",
                impact_score=1.0 - metrics.tool_success_rate,
                suggested_action="Improve tool selection heuristics, add fallback tools",
                metrics_evidence={"tool_success_rate": metrics.tool_success_rate,
                                  "tool_calls": metrics.tool_calls_total},
            ))

        # 5. High cost
        if metrics.avg_cost_usd > self.COST_THRESHOLD and metrics.missions_total >= 3:
            severity = "medium" if metrics.avg_cost_usd < 2.0 else "high"
            priorities.append(ImprovementPriority(
                weakness_type=WeaknessType.HIGH_COST,
                severity=severity,
                component="llm_routing",
                description=f"Avg cost ${metrics.avg_cost_usd:.3f}/mission exceeds ${self.COST_THRESHOLD:.2f} threshold",
                impact_score=min(1.0, metrics.avg_cost_usd / 5.0),
                suggested_action="Route simpler tasks to cheaper models, reduce token waste",
                metrics_evidence={"avg_cost": metrics.avg_cost_usd},
            ))

        # 6. Low autonomy
        if metrics.approval_rate > self.APPROVAL_THRESHOLD and metrics.missions_total >= 5:
            priorities.append(ImprovementPriority(
                weakness_type=WeaknessType.LOW_AUTONOMY,
                severity="medium",
                component="policy_engine",
                description=f"Approval rate {metrics.approval_rate:.0%} — too many actions need manual approval",
                impact_score=min(1.0, metrics.approval_rate),
                suggested_action="Review approval policy, pre-approve safe patterns",
                metrics_evidence={"approval_rate": metrics.approval_rate},
            ))

        # 7. Inefficient model usage (from dimension scores)
        for dim in score.dimensions:
            if dim.name == "cost_efficiency" and dim.value < 5.0:
                if not any(p.weakness_type == WeaknessType.HIGH_COST for p in priorities):
                    priorities.append(ImprovementPriority(
                        weakness_type=WeaknessType.INEFFICIENT_MODEL,
                        severity="medium",
                        component="llm_routing",
                        description=f"Cost efficiency score {dim.value:.1f}/10 — model selection suboptimal",
                        impact_score=0.5,
                        suggested_action="Enable adaptive routing, use cheaper models for simple tasks",
                        metrics_evidence={"cost_score": dim.value},
                    ))

        # Sort by impact (highest first)
        priorities.sort(key=lambda p: p.impact_score, reverse=True)
        return priorities


# ═══════════════════════════════════════════════════════════════
# PART 6 — EVALUATION MEMORY (score history + evolution)
# ═══════════════════════════════════════════════════════════════

@dataclass
class EvaluationSnapshot:
    """A point-in-time evaluation record."""
    score: float
    dimensions: dict[str, float]
    priorities_count: int
    top_weakness: str
    metrics_summary: dict
    timestamp: float = field(default_factory=time.time)


class EvaluationMemory:
    """Persistent storage of evaluation history for trend tracking."""

    def __init__(self, persist_path: Path | None = None):
        self._path = persist_path or Path("workspace/evaluation_history.json")
        self._history: list[EvaluationSnapshot] = []
        self._load()

    def record(self, score: AgentScore, priorities: list[ImprovementPriority]) -> None:
        """Store an evaluation snapshot."""
        snap = EvaluationSnapshot(
            score=score.overall,
            dimensions={d.name: round(d.value, 2) for d in score.dimensions},
            priorities_count=len(priorities),
            top_weakness=priorities[0].weakness_type if priorities else "none",
            metrics_summary={
                "success_rate": score.metrics.success_rate if score.metrics else 0,
                "retry_rate": score.metrics.retry_rate if score.metrics else 0,
                "tool_success": score.metrics.tool_success_rate if score.metrics else 0,
            },
        )
        self._history.append(snap)
        # Keep bounded
        if len(self._history) > 1000:
            self._history = self._history[-500:]
        self._save()

    def get_trend(self, last_n: int = 20) -> list[dict]:
        """Get recent score trend."""
        recent = self._history[-last_n:]
        return [
            {"score": round(s.score, 2), "timestamp": s.timestamp,
             "priorities": s.priorities_count, "top_weakness": s.top_weakness}
            for s in recent
        ]

    def get_evolution(self) -> dict:
        """Compare latest vs previous evaluation."""
        if len(self._history) < 2:
            return {"status": "insufficient_data", "evaluations": len(self._history)}

        current = self._history[-1]
        previous = self._history[-2]
        delta = round(current.score - previous.score, 2)

        # Per-dimension deltas
        dim_changes = {}
        for dim_name, current_val in current.dimensions.items():
            prev_val = previous.dimensions.get(dim_name, current_val)
            change = round(current_val - prev_val, 2)
            if abs(change) > 0.01:
                dim_changes[dim_name] = {
                    "from": prev_val, "to": current_val,
                    "delta": change, "direction": "improved" if change > 0 else "regressed",
                }

        return {
            "status": "ok",
            "current_score": round(current.score, 2),
            "previous_score": round(previous.score, 2),
            "delta": delta,
            "direction": "improved" if delta > 0 else "regressed" if delta < 0 else "stable",
            "dimension_changes": dim_changes,
            "regression_detected": delta < -0.5,
        }

    def detect_regression(self, window: int = 5) -> bool:
        """Check if score has been declining over recent evaluations."""
        if len(self._history) < window:
            return False
        recent = self._history[-window:]
        # Check if monotonically decreasing
        for i in range(1, len(recent)):
            if recent[i].score >= recent[i - 1].score:
                return False
        return True

    def get_history_count(self) -> int:
        return len(self._history)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = []
            for s in self._history:
                data.append({
                    "score": s.score, "dimensions": s.dimensions,
                    "priorities_count": s.priorities_count,
                    "top_weakness": s.top_weakness,
                    "metrics_summary": s.metrics_summary,
                    "timestamp": s.timestamp,
                })
            self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for d in data:
                    self._history.append(EvaluationSnapshot(
                        score=d.get("score", 0),
                        dimensions=d.get("dimensions", {}),
                        priorities_count=d.get("priorities_count", 0),
                        top_weakness=d.get("top_weakness", ""),
                        metrics_summary=d.get("metrics_summary", {}),
                        timestamp=d.get("timestamp", 0),
                    ))
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# PART 5 + MAIN — AgentEvaluationEngine
# ═══════════════════════════════════════════════════════════════

@dataclass
class EvaluationReport:
    """Complete evaluation report."""
    score: AgentScore
    priorities: list[ImprovementPriority]
    evolution: dict
    regression_detected: bool
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "score": self.score.to_dict(),
            "priorities": [p.to_dict() for p in self.priorities],
            "evolution": self.evolution,
            "regression_detected": self.regression_detected,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        """Human-readable summary for logs/status."""
        lines = [f"Agent Score: {self.score.overall:.1f}/10"]

        # Dimension breakdown
        for d in self.score.dimensions:
            arrow = "▲" if d.value >= 7.0 else "▼" if d.value < 5.0 else "●"
            lines.append(f"  {arrow} {d.name}: {d.value:.1f}/10 ({d.detail})")

        # Evolution
        evo = self.evolution
        if evo.get("status") == "ok":
            delta = evo.get("delta", 0)
            symbol = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
            lines.append(f"\n{symbol} Score: {evo.get('previous_score', '?')} → {evo.get('current_score', '?')} ({'+' if delta > 0 else ''}{delta})")

            for dim, change in evo.get("dimension_changes", {}).items():
                if change["delta"] > 0:
                    lines.append(f"  ✅ {dim}: +{change['delta']:.1f}")
                else:
                    lines.append(f"  ⚠️ {dim}: {change['delta']:.1f}")

        # Priorities
        if self.priorities:
            lines.append(f"\n🎯 Top {min(3, len(self.priorities))} improvement targets:")
            for p in self.priorities[:3]:
                lines.append(f"  [{p.severity.upper()}] {p.description}")
                lines.append(f"    → {p.suggested_action}")

        if self.regression_detected:
            lines.append("\n⚠️ REGRESSION DETECTED — score declining over recent evaluations")

        return "\n".join(lines)


class AgentEvaluationEngine:
    """
    Main evaluation engine. Orchestrates:
    1. Metrics collection
    2. Scoring
    3. Weakness detection
    4. History recording
    5. Reporting

    Integration with self-improvement loop:
    - evaluate() returns EvaluationReport with priorities
    - get_improvement_signals() converts priorities to ImprovementSignals
    - Feed into JarvisImprovementLoop.collector.add()
    """

    def __init__(self,
                 weights: dict[str, float] | None = None,
                 history_path: Path | None = None):
        self._collector = MetricsCollector()
        self._scorer = ScoringModel(weights)
        self._detector = WeaknessDetector()
        self._memory = EvaluationMemory(history_path)

    def evaluate(self) -> EvaluationReport:
        """Run full evaluation cycle. Returns complete report."""
        # 1. Collect
        metrics = self._collector.collect()

        # 2. Score
        score = self._scorer.score(metrics)

        # 3. Detect weaknesses
        priorities = self._detector.detect(score, metrics)

        # 4. Record history
        self._memory.record(score, priorities)

        # 5. Build report
        evolution = self._memory.get_evolution()
        regression = self._memory.detect_regression()

        return EvaluationReport(
            score=score,
            priorities=priorities,
            evolution=evolution,
            regression_detected=regression,
        )

    def evaluate_from_metrics(self, metrics: EvaluationMetrics) -> EvaluationReport:
        """Evaluate from pre-collected metrics (for testing)."""
        score = self._scorer.score(metrics)
        priorities = self._detector.detect(score, metrics)
        self._memory.record(score, priorities)
        evolution = self._memory.get_evolution()
        regression = self._memory.detect_regression()
        return EvaluationReport(
            score=score, priorities=priorities,
            evolution=evolution, regression_detected=regression,
        )

    def get_improvement_signals(self, report: EvaluationReport) -> list[dict]:
        """
        Convert evaluation priorities to ImprovementSignal-compatible dicts.
        Feed these into JarvisImprovementLoop.collector.add().
        """
        signals = []
        for p in report.priorities:
            signals.append({
                "type": f"eval_{p.weakness_type}",
                "component": p.component,
                "severity": p.severity,
                "frequency": max(1, int(p.impact_score * 10)),
                "context": {
                    "description": p.description,
                    "action": p.suggested_action,
                    "evidence": p.metrics_evidence,
                },
            })
        return signals

    def get_trend(self, last_n: int = 20) -> list[dict]:
        """Get score trend for dashboards."""
        return self._memory.get_trend(last_n)

    def get_evolution(self) -> dict:
        """Get latest vs previous comparison."""
        return self._memory.get_evolution()

    @property
    def history(self) -> EvaluationMemory:
        return self._memory


# Compat alias — main.py imports EvaluationEngine (legacy name)
EvaluationEngine = AgentEvaluationEngine