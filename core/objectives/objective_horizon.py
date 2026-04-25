"""
core/objectives/objective_horizon.py — Long-horizon objective management.

Bridges objectives to execution outcomes:
  1. Links objectives to playbooks/missions
  2. Updates progress from execution results
  3. Generates strategy suggestions aligned with objectives
  4. Persists objective state across restarts

Design:
  - Fail-open: if any integration fails, objective state is unchanged
  - Observable: all progress updates logged
  - Safe: suggestions are advisory, not auto-executed
  - Deterministic: progress calculation is formula-based
"""
from __future__ import annotations

import time
import structlog
from dataclasses import dataclass, field

log = structlog.get_logger("objectives.horizon")


# ── Evaluation metric ─────────────────────────────────────────

@dataclass
class EvaluationMetric:
    """A measurable signal for objective progress."""
    name: str
    description: str
    target_value: float
    current_value: float = 0.0
    unit: str = ""  # "count", "percent", "score", "currency"
    direction: str = "up"  # "up" (higher is better) or "down" (lower is better)

    @property
    def progress(self) -> float:
        """Calculate progress toward target (0.0 to 1.0)."""
        if self.target_value == 0:
            return 1.0 if self.current_value >= 0 else 0.0
        if self.direction == "up":
            return min(self.current_value / self.target_value, 1.0)
        else:
            if self.current_value <= 0:
                return 1.0
            return min(self.target_value / self.current_value, 1.0)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "target_value": self.target_value,
            "current_value": round(self.current_value, 3),
            "unit": self.unit,
            "direction": self.direction,
            "progress": round(self.progress, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvaluationMetric":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            target_value=float(d.get("target_value", 0)),
            current_value=float(d.get("current_value", 0)),
            unit=d.get("unit", ""),
            direction=d.get("direction", "up"),
        )


# ── Time horizon ──────────────────────────────────────────────

@dataclass
class TimeHorizon:
    """Time boundary for an objective."""
    start: float = 0  # timestamp
    target_end: float = 0  # timestamp
    horizon_type: str = "ongoing"  # "fixed", "ongoing", "quarterly"

    @property
    def elapsed_ratio(self) -> float:
        """How much of the time horizon has elapsed (0.0 to 1.0)."""
        if self.horizon_type == "ongoing" or self.target_end <= self.start:
            return 0.0
        now = time.time()
        total = self.target_end - self.start
        elapsed = now - self.start
        return min(max(elapsed / total, 0.0), 1.0)

    @property
    def is_overdue(self) -> bool:
        if self.horizon_type == "ongoing":
            return False
        return time.time() > self.target_end if self.target_end > 0 else False

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "target_end": self.target_end,
            "horizon_type": self.horizon_type,
            "elapsed_ratio": round(self.elapsed_ratio, 3),
            "is_overdue": self.is_overdue,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimeHorizon":
        return cls(
            start=float(d.get("start", 0)),
            target_end=float(d.get("target_end", 0)),
            horizon_type=d.get("horizon_type", "ongoing"),
        )


# ── Playbook linkage ─────────────────────────────────────────

@dataclass
class PlaybookLink:
    """Links an objective to a playbook execution."""
    playbook_id: str
    run_id: str
    status: str  # "completed", "failed"
    steps_completed: int
    steps_total: int
    quality_scores: dict[str, float] = field(default_factory=dict)
    executed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "playbook_id": self.playbook_id,
            "run_id": self.run_id,
            "status": self.status,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "quality_scores": self.quality_scores,
            "executed_at": self.executed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlaybookLink":
        return cls(
            playbook_id=d.get("playbook_id", ""),
            run_id=d.get("run_id", ""),
            status=d.get("status", "unknown"),
            steps_completed=d.get("steps_completed", 0),
            steps_total=d.get("steps_total", 0),
            quality_scores=d.get("quality_scores", {}),
            executed_at=float(d.get("executed_at", time.time())),
        )


# ── Strategy suggestion ──────────────────────────────────────

@dataclass
class StrategySuggestion:
    """A suggested action aligned with an objective."""
    objective_id: str
    suggestion_type: str  # "run_playbook", "adjust_strategy", "investigate", "escalate"
    description: str
    playbook_id: str = ""
    confidence: float = 0.5
    rationale: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "objective_id": self.objective_id,
            "suggestion_type": self.suggestion_type,
            "description": self.description,
            "playbook_id": self.playbook_id,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


# ── Horizon manager ──────────────────────────────────────────

class ObjectiveHorizonManager:
    """
    Manages long-horizon objective tracking with execution feedback.

    Responsibilities:
      - Store evaluation metrics per objective
      - Link playbook/mission executions to objectives
      - Update progress from execution outcomes
      - Generate strategy suggestions
      - Provide objective health overview
    """

    def __init__(self):
        self._metrics: dict[str, list[EvaluationMetric]] = {}
        self._horizons: dict[str, TimeHorizon] = {}
        self._links: dict[str, list[PlaybookLink]] = {}

    def set_metrics(self, objective_id: str, metrics: list[EvaluationMetric]) -> None:
        """Set evaluation metrics for an objective."""
        self._metrics[objective_id] = metrics
        log.debug("metrics_set", objective_id=objective_id, count=len(metrics))

    def set_horizon(self, objective_id: str, horizon: TimeHorizon) -> None:
        """Set time horizon for an objective."""
        self._horizons[objective_id] = horizon

    def record_execution(
        self,
        objective_id: str,
        playbook_id: str,
        run_id: str,
        status: str,
        steps_completed: int,
        steps_total: int,
        quality_scores: dict | None = None,
    ) -> None:
        """Record a playbook/mission execution linked to an objective."""
        link = PlaybookLink(
            playbook_id=playbook_id,
            run_id=run_id,
            status=status,
            steps_completed=steps_completed,
            steps_total=steps_total,
            quality_scores=quality_scores or {},
        )
        self._links.setdefault(objective_id, []).append(link)

        # Update objective progress via engine
        try:
            from core.objectives.objective_engine import get_objective_engine
            engine = get_objective_engine()
            obj = engine.get(objective_id)
            if obj:
                obj.add_history_entry(
                    "execution_completed",
                    f"playbook={playbook_id} status={status} steps={steps_completed}/{steps_total}"
                )
                engine.update_progress(objective_id)
                engine.store.save(obj)
                log.info("objective_execution_recorded",
                         objective_id=objective_id,
                         playbook_id=playbook_id,
                         status=status)
        except Exception as e:
            log.debug("objective_update_failed", err=str(e)[:80])

    def update_metric(
        self,
        objective_id: str,
        metric_name: str,
        value: float,
    ) -> bool:
        """Update a specific evaluation metric value."""
        metrics = self._metrics.get(objective_id, [])
        for m in metrics:
            if m.name == metric_name:
                m.current_value = value
                log.debug("metric_updated", objective_id=objective_id,
                          metric=metric_name, value=value,
                          progress=round(m.progress, 3))
                return True
        return False

    def compute_progress(self, objective_id: str) -> float:
        """
        Compute aggregate progress from metrics and executions.

        Progress = weighted average of:
          - Metric progress (60%) — quantitative targets
          - Execution success rate (40%) — qualitative signal
        """
        metric_progress = 0.0
        metrics = self._metrics.get(objective_id, [])
        if metrics:
            metric_progress = sum(m.progress for m in metrics) / len(metrics)

        exec_progress = 0.0
        links = self._links.get(objective_id, [])
        if links:
            successful = sum(1 for l in links if l.status == "completed")
            exec_progress = successful / len(links)

        if metrics and links:
            progress = 0.6 * metric_progress + 0.4 * exec_progress
        elif metrics:
            progress = metric_progress
        elif links:
            progress = exec_progress
        else:
            progress = 0.0

        return round(min(progress, 1.0), 3)

    def get_suggestions(self, objective_id: str) -> list[StrategySuggestion]:
        """
        Generate strategy suggestions for an objective.

        Rules-based (no LLM):
          - Low progress + no executions → suggest first playbook
          - Failed executions → suggest investigation
          - Stagnant progress → suggest strategy adjustment
          - High progress → suggest completion check
        """
        suggestions: list[StrategySuggestion] = []
        progress = self.compute_progress(objective_id)
        links = self._links.get(objective_id, [])
        self._metrics.get(objective_id, [])
        horizon = self._horizons.get(objective_id, TimeHorizon())

        # No executions yet → suggest first playbook
        if not links:
            suggestions.append(StrategySuggestion(
                objective_id=objective_id,
                suggestion_type="run_playbook",
                description="Start with a market analysis playbook to establish baseline understanding.",
                playbook_id="market_analysis",
                confidence=0.7,
                rationale="No executions recorded yet. Market analysis is a safe first step.",
            ))

        # Failed executions → investigate
        recent_failures = [l for l in links[-5:] if l.status == "failed"]
        if len(recent_failures) >= 2:
            suggestions.append(StrategySuggestion(
                objective_id=objective_id,
                suggestion_type="investigate",
                description=f"Recent failures ({len(recent_failures)}/5): review execution logs and skill performance.",
                confidence=0.8,
                rationale="Multiple recent failures indicate a systematic issue.",
            ))

        # Stagnant progress → adjust strategy
        if progress > 0 and progress < 0.5 and len(links) >= 3:
            suggestions.append(StrategySuggestion(
                objective_id=objective_id,
                suggestion_type="adjust_strategy",
                description="Progress below 50% after 3+ executions. Consider a different approach.",
                confidence=0.6,
                rationale="Multiple attempts with limited progress suggests current strategy may be suboptimal.",
            ))

        # Overdue → escalate
        if horizon.is_overdue and progress < 0.8:
            suggestions.append(StrategySuggestion(
                objective_id=objective_id,
                suggestion_type="escalate",
                description="Objective is overdue with incomplete progress. Needs human review.",
                confidence=0.9,
                rationale="Time horizon exceeded before reaching target progress.",
            ))

        # High progress → completion check
        if progress >= 0.8:
            suggestions.append(StrategySuggestion(
                objective_id=objective_id,
                suggestion_type="investigate",
                description="Progress at 80%+. Review metrics and consider completing the objective.",
                confidence=0.7,
                rationale="Approaching target. Verify success criteria are met.",
            ))

        return suggestions

    def get_overview(self, objective_id: str) -> dict:
        """Get full horizon overview for an objective."""
        progress = self.compute_progress(objective_id)
        metrics = self._metrics.get(objective_id, [])
        horizon = self._horizons.get(objective_id, TimeHorizon())
        links = self._links.get(objective_id, [])
        suggestions = self.get_suggestions(objective_id)

        return {
            "objective_id": objective_id,
            "progress": progress,
            "metrics": [m.to_dict() for m in metrics],
            "time_horizon": horizon.to_dict(),
            "executions": len(links),
            "recent_executions": [l.to_dict() for l in links[-5:]],
            "suggestions": [s.to_dict() for s in suggestions],
        }

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {
            "metrics": {
                oid: [m.to_dict() for m in ms]
                for oid, ms in self._metrics.items()
            },
            "horizons": {
                oid: h.to_dict()
                for oid, h in self._horizons.items()
            },
            "links": {
                oid: [l.to_dict() for l in ls]
                for oid, ls in self._links.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ObjectiveHorizonManager":
        """Restore from persisted dict."""
        mgr = cls()
        for oid, ms in data.get("metrics", {}).items():
            mgr._metrics[oid] = [EvaluationMetric.from_dict(m) for m in ms]
        for oid, h in data.get("horizons", {}).items():
            mgr._horizons[oid] = TimeHorizon.from_dict(h)
        for oid, ls in data.get("links", {}).items():
            mgr._links[oid] = [PlaybookLink.from_dict(l) for l in ls]
        return mgr


# ── Singleton ─────────────────────────────────────────────────

_manager: ObjectiveHorizonManager | None = None


def get_horizon_manager() -> ObjectiveHorizonManager:
    global _manager
    if _manager is None:
        _manager = ObjectiveHorizonManager()
    return _manager
