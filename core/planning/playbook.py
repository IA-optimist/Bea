"""
core/planning/playbook.py — Strategic playbook system.

A playbook is a reusable multi-step business strategy that:
  1. Defines a structured skill sequence for a business outcome
  2. Maps each step to a domain skill with expected outputs
  3. Translates to an ExecutionPlan for PlanRunner execution
  4. Tracks playbook-level performance across executions
  5. Is versionable and extensible (JSON-based, on-disk)

Playbooks live in business/playbooks/ as JSON files.
They are NOT workflow templates (business/workflows/) — those are
legacy action-based templates. Playbooks are skill-first.

Design:
  - Deterministic: same playbook + inputs → same plan structure
  - Observable: execution metrics tracked per playbook
  - Composable: playbooks reference skills by ID
  - Fail-open: missing playbook returns None, bad step is skipped
"""
from __future__ import annotations

import json
import os
import time
import threading
import structlog
from dataclasses import dataclass, field
from pathlib import Path

from core.planning.execution_plan import ExecutionPlan, PlanStep, PlanStatus, StepType

log = structlog.get_logger("planning.playbook")

_PLAYBOOKS_DIR = Path(os.path.dirname(__file__)).parent.parent / "business" / "playbooks"


# ── Playbook schema ───────────────────────────────────────────

@dataclass
class PlaybookStep:
    """A step in a playbook — maps to a skill execution."""
    skill_id: str
    name: str
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    optional: bool = False

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "depends_on": self.depends_on,
            "expected_outputs": self.expected_outputs,
            "optional": self.optional,
        }


@dataclass
class Playbook:
    """
    A reusable strategic playbook.

    Contains a sequence of skill-based steps that together
    accomplish a business outcome.
    """
    playbook_id: str
    name: str
    description: str
    version: str = "1.0"
    tier: str = "business"  # business, technical, growth, strategy
    goal_template: str = ""  # Template with {placeholders}
    steps: list[PlaybookStep] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    estimated_duration_min: int = 0

    def to_dict(self) -> dict:
        return {
            "playbook_id": self.playbook_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tier": self.tier,
            "goal_template": self.goal_template,
            "steps": [s.to_dict() for s in self.steps],
            "step_count": len(self.steps),
            "skills_used": list({s.skill_id for s in self.steps}),
            "success_criteria": self.success_criteria,
            "tags": self.tags,
            "estimated_duration_min": self.estimated_duration_min,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Playbook":
        """Load a playbook from a dict (JSON-parsed)."""
        steps = []
        for s in data.get("steps", []):
            steps.append(PlaybookStep(
                skill_id=s["skill_id"],
                name=s.get("name", s["skill_id"]),
                description=s.get("description", ""),
                depends_on=s.get("depends_on", []),
                expected_outputs=s.get("expected_outputs", []),
                optional=s.get("optional", False),
            ))
        return cls(
            playbook_id=data["playbook_id"],
            name=data.get("name", data["playbook_id"]),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            tier=data.get("tier", "business"),
            goal_template=data.get("goal_template", ""),
            steps=steps,
            success_criteria=data.get("success_criteria", []),
            tags=data.get("tags", []),
            estimated_duration_min=data.get("estimated_duration_min", 0),
        )

    def build_plan(self, goal: str, inputs: dict | None = None) -> ExecutionPlan:
        """
        Convert this playbook into an ExecutionPlan.

        The plan uses the existing PlanRunner infrastructure:
        input resolution → skill preparation → LLM invocation → performance tracking.
        """
        plan_steps = []
        for i, pb_step in enumerate(self.steps):
            step = PlanStep(
                step_id=f"pb-{self.playbook_id}-s{i+1}",
                type=StepType.SKILL,
                target_id=pb_step.skill_id,
                name=pb_step.name,
                depends_on=pb_step.depends_on or (
                    [f"pb-{self.playbook_id}-s{i}"] if i > 0 else []
                ),
                inputs=dict(inputs or {}),
            )
            plan_steps.append(step)

        plan = ExecutionPlan(
            goal=goal or self.goal_template,
            description=f"Playbook: {self.name} — {self.description}",
            steps=plan_steps,
            template_id=self.playbook_id,
            status=PlanStatus.APPROVED,  # Playbooks are pre-approved
        )
        return plan


# ── Playbook registry ─────────────────────────────────────────

class PlaybookRegistry:
    """Load and manage playbooks from disk."""

    def __init__(self):
        self._playbooks: dict[str, Playbook] = {}
        self._loaded = False

    def load_all(self) -> int:
        """Load all playbooks from business/playbooks/."""
        if not _PLAYBOOKS_DIR.is_dir():
            _PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
            return 0

        count = 0
        for f in sorted(_PLAYBOOKS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text("utf-8"))
                pb = Playbook.from_dict(data)
                self._playbooks[pb.playbook_id] = pb
                count += 1
            except Exception as e:
                log.debug("playbook_load_failed", path=str(f), err=str(e)[:80])

        self._loaded = True
        log.info("playbooks_loaded", count=count)
        return count

    def get(self, playbook_id: str) -> Playbook | None:
        if not self._loaded:
            self.load_all()
        return self._playbooks.get(playbook_id)

    def list_all(self) -> list[dict]:
        if not self._loaded:
            self.load_all()
        return [pb.to_dict() for pb in self._playbooks.values()]

    def list_by_tier(self, tier: str) -> list[dict]:
        if not self._loaded:
            self.load_all()
        return [pb.to_dict() for pb in self._playbooks.values()
                if pb.tier == tier]

    def save(self, playbook: Playbook) -> bool:
        """Save a playbook to disk."""
        try:
            _PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
            path = _PLAYBOOKS_DIR / f"{playbook.playbook_id}.json"
            data = playbook.to_dict()
            # Remove computed fields before saving
            data.pop("step_count", None)
            data.pop("skills_used", None)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self._playbooks[playbook.playbook_id] = playbook
            return True
        except Exception as e:
            log.debug("playbook_save_failed", err=str(e)[:80])
            return False


# ── Playbook performance tracker ──────────────────────────────

@dataclass
class PlaybookExecution:
    """Record of a single playbook execution."""
    playbook_id: str
    run_id: str
    started_at: float
    completed_at: float = 0
    status: str = "running"  # running, completed, failed
    steps_completed: int = 0
    steps_total: int = 0
    quality_scores: dict[str, float] = field(default_factory=dict)


class PlaybookPerformanceTracker:
    """Track playbook execution performance."""

    def __init__(self):
        self._lock = threading.Lock()
        self._executions: list[PlaybookExecution] = []

    def record_start(self, playbook_id: str, run_id: str, steps_total: int) -> None:
        with self._lock:
            self._executions.append(PlaybookExecution(
                playbook_id=playbook_id,
                run_id=run_id,
                started_at=time.time(),
                steps_total=steps_total,
            ))

    def record_complete(self, run_id: str, status: str,
                        steps_completed: int, quality_scores: dict | None = None) -> None:
        with self._lock:
            for ex in reversed(self._executions):
                if ex.run_id == run_id:
                    ex.status = status
                    ex.completed_at = time.time()
                    ex.steps_completed = steps_completed
                    if quality_scores:
                        ex.quality_scores = quality_scores
                    break

    def get_stats(self, playbook_id: str) -> dict:
        """Get performance stats for a playbook."""
        with self._lock:
            execs = [e for e in self._executions if e.playbook_id == playbook_id]

        if not execs:
            return {"playbook_id": playbook_id, "executions": 0}

        completed = [e for e in execs if e.status == "completed"]
        failed = [e for e in execs if e.status == "failed"]
        total = len(execs)
        success_rate = len(completed) / total if total else 0

        avg_duration = 0
        if completed:
            durations = [e.completed_at - e.started_at for e in completed if e.completed_at]
            avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "playbook_id": playbook_id,
            "executions": total,
            "completed": len(completed),
            "failed": len(failed),
            "success_rate": round(success_rate, 3),
            "avg_duration_s": round(avg_duration, 1),
        }

    def get_all_stats(self) -> list[dict]:
        """Get stats for all playbooks."""
        with self._lock:
            ids = {e.playbook_id for e in self._executions}
        return [self.get_stats(pid) for pid in ids]


# ── Playbook executor ─────────────────────────────────────────

def execute_playbook(
    playbook_id: str,
    goal: str,
    inputs: dict | None = None,
    budget_mode: str = "normal",
) -> dict:
    """
    Execute a playbook end-to-end.

    1. Loads the playbook
    2. Builds an ExecutionPlan from it
    3. Saves the plan
    4. Runs it via PlanRunner
    5. Records performance
    6. Returns results

    Returns:
        {"ok": bool, "run": dict, "playbook": dict, "performance": dict}
    """
    registry = get_playbook_registry()
    playbook = registry.get(playbook_id)
    if not playbook:
        return {"ok": False, "error": f"Playbook not found: {playbook_id}"}

    # Validate budget mode
    _valid_modes = ("budget", "normal", "critical")
    if budget_mode not in _valid_modes:
        budget_mode = "normal"

    # Build plan
    plan = playbook.build_plan(goal, inputs)

    # Propagate budget mode into plan metadata
    if not hasattr(plan, "metadata"):
        plan.metadata = {}
    plan.metadata["budget_mode"] = budget_mode

    # Save plan
    from core.planning.plan_serializer import get_plan_store
    get_plan_store().save(plan)

    # Execute
    from core.planning.plan_runner import PlanRunner
    runner = PlanRunner()
    run = runner.start(plan.plan_id)

    # Track performance using run_id from actual execution
    tracker = get_performance_tracker()
    tracker.record_start(playbook_id, run.run_id, len(plan.steps))

    status = "completed" if run.status.value == "completed" else "failed"
    quality_scores = {}
    for sid, output in run.context.step_outputs.items():
        quality = output.get("quality", {})
        if isinstance(quality, dict) and "score" in quality:
            quality_scores[sid] = quality["score"]

    tracker.record_complete(run.run_id, status, run.steps_completed, quality_scores)

    # Feed objective horizon (if objective_id provided)
    objective_id = (inputs or {}).get("objective_id", "")
    if objective_id:
        try:
            from core.objectives.objective_horizon import get_horizon_manager
            get_horizon_manager().record_execution(
                objective_id=objective_id,
                playbook_id=playbook_id,
                run_id=run.run_id,
                status=status,
                steps_completed=run.steps_completed,
                steps_total=len(plan.steps),
                quality_scores=quality_scores,
            )
        except Exception:
            pass  # fail-open

    # Auto-create strategic record (Phase 2 economic wiring)
    try:
        from core.economic.economic_output import assemble_economic_output
        from core.economic.strategic_memory import get_strategic_memory, StrategicRecord
        from core.economic.decision_trace import build_trace_from_output

        step_outputs = list(run.context.step_outputs.values())
        assembled = assemble_economic_output(playbook_id, step_outputs)
        validation = assembled.get("validation", {})

        # Only record if we have meaningful output (at least 1 field)
        if validation.get("field_count", 0) >= 1 or status == "failed":
            trace = build_trace_from_output(
                assembled.get("schema", ""),
                assembled.get("data", {}),
                validation,
            )
            avg_quality = (
                sum(quality_scores.values()) / len(quality_scores)
                if quality_scores else 0.0
            )
            get_strategic_memory().record(StrategicRecord(
                strategy_type=playbook_id,
                playbook_id=playbook_id,
                run_id=run.run_id,
                context_features=(inputs or {}),
                schema_type=assembled.get("schema", ""),
                outcome_score=avg_quality if avg_quality > 0 else (
                    0.7 if status == "completed" else 0.2
                ),
                confidence=validation.get("completeness", 0.0),
                completeness=validation.get("completeness", 0.0),
                goal=goal,
                key_findings=[],
                failure_reasons=validation.get("issues", [])[:5],
            ))
    except Exception:
        pass  # fail-open: strategic memory write never blocks execution

    # Record execution strategy for comparison/promotion (Phase 1 strategy v2)
    try:
        from core.execution.strategy_memory import StrategyRecord, get_strategy_memory
        avg_q = (
            sum(quality_scores.values()) / len(quality_scores)
            if quality_scores else 0.0
        )
        strategy_id = f"{budget_mode}_{playbook_id}"
        get_strategy_memory().record(StrategyRecord(
            task_type=playbook_id,
            strategy_id=strategy_id,
            budget_mode=budget_mode,
            template_used=playbook_id,
            success=(status == "completed"),
            quality_score=avg_q,
            duration_ms=run.context.metadata.get("duration_ms", 0),
        ))
        # Check if a better strategy should be promoted
        from core.execution.strategy_registry import get_strategy_registry
        get_strategy_registry().check_promotion(playbook_id)

        # Record in learning memory for future learning
        from core.planning.learning_memory import get_learning_memory
        get_learning_memory().record_mission(
            mission_id=run.run_id,
            goal=goal,
            playbook_id=playbook_id,
            success=(status == "completed"),
            quality_score=avg_q,
            model_used=run.context.metadata.get("model", ""),
            cost=run.context.metadata.get("cost", 0.0),
            duration_ms=run.context.metadata.get("duration_ms", 0.0),
        )
    except Exception:
        pass  # fail-open

    result = {
        "ok": run.status.value == "completed",
        "run": run.to_dict(),
        "playbook": playbook.to_dict(),
        "performance": tracker.get_stats(playbook_id),
    }

    # Self-review before delivery (fail-open)
    try:
        from core.planning.self_review import review_mission_result
        review = review_mission_result(
            goal=goal,
            run_result=result,
        )
        result["review"] = review.to_dict()
    except Exception:
        _silent_log.debug("suppressed_exception", src='playbook.py')

    return result


# ── Singletons ────────────────────────────────────────────────

_registry: PlaybookRegistry | None = None
_tracker: PlaybookPerformanceTracker | None = None


def get_playbook_registry() -> PlaybookRegistry:
    global _registry
    if _registry is None:
        _registry = PlaybookRegistry()
    return _registry


def get_performance_tracker() -> PlaybookPerformanceTracker:
    global _tracker
    if _tracker is None:
        _tracker = PlaybookPerformanceTracker()
    return _tracker
