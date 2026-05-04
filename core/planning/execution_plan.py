"""
core/planning/execution_plan.py — Structured execution plans.

An ExecutionPlan describes an ordered sequence of steps Jarvis will execute.
Each step is either a business_action, a tool invocation, or a skill execution.

Plans are:
  - Inspectable (fully serializable to JSON)
  - Validated (before execution)
  - Cancellable (at any step boundary)
  - Resumable (from last completed step)
  - Approval-gated (whole plan or individual steps)
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
_silent_log = __import__("structlog").get_logger(__name__)


class StepType(str, Enum):
    BUSINESS_ACTION = "business_action"
    TOOL = "tool"
    SKILL = "skill"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    step_id: str = ""
    type: StepType = StepType.BUSINESS_ACTION
    target_id: str = ""  # action/tool/skill ID
    name: str = ""
    inputs: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: dict = field(default_factory=dict)
    started_at: float = 0
    completed_at: float = 0

    def __post_init__(self):
        if not self.step_id:
            self.step_id = f"step-{uuid.uuid4().hex[:8]}"
        if isinstance(self.type, str):
            self.type = StepType(self.type)

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return round((self.completed_at - self.started_at) * 1000)
        return 0

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "type": self.type.value,
            "target_id": self.target_id,
            "name": self.name,
            "inputs": self.inputs,
            "depends_on": self.depends_on,
            "status": self.status,
            "result": self.result,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlanStep:
        return cls(
            step_id=d.get("step_id", ""),
            type=StepType(d.get("type", "business_action")),
            target_id=d.get("target_id", d.get("id", "")),
            name=d.get("name", ""),
            inputs=d.get("inputs", {}),
            depends_on=d.get("depends_on", []),
            status=d.get("status", "pending"),
            result=d.get("result", {}),
        )


@dataclass
class ExecutionPlan:
    """A complete execution plan with ordered steps."""
    plan_id: str = ""
    goal: str = ""
    description: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    risk_score: str = "low"  # computed from steps
    requires_approval: bool = False
    template_id: str = ""  # if derived from a workflow template
    mission_id: str = ""
    created_at: float = 0
    updated_at: float = 0
    approval: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)  # plan-level metadata (budget_mode, etc.)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()
        if isinstance(self.status, str):
            self.status = PlanStatus(self.status)

    def compute_risk(self) -> str:
        """Compute aggregate risk from step targets."""
        risks = set()
        for step in self.steps:
            if step.type == StepType.TOOL:
                risks.add("medium")  # tools have external effects
        if "critical" in risks:
            return "critical"
        elif "high" in risks:
            return "high"
        elif "medium" in risks:
            return "medium"
        return "low"

    def compute_approval_required(self) -> bool:
        """Check if any step requires approval."""
        for step in self.steps:
            if step.type == StepType.TOOL:
                try:
                    from core.tools_operational.tool_registry import get_tool_registry
                    tool = get_tool_registry().get(step.target_id)
                    if tool and tool.requires_approval:
                        return True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='execution_plan.py')
            if step.type == StepType.BUSINESS_ACTION:
                try:
                    from core.business_actions import ACTION_REGISTRY
                    action = ACTION_REGISTRY.get(step.target_id)
                    if action and action.requires_approval:
                        return True
                except Exception:
                    _silent_log.debug("suppressed_exception", src='execution_plan.py')
        return False

    @property
    def current_step(self) -> PlanStep | None:
        """Get the next pending step."""
        for s in self.steps:
            if s.status == "pending":
                return s
        return None

    @property
    def completed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == "completed"]

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0
        return round(len(self.completed_steps) / len(self.steps), 3)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "risk_score": self.risk_score,
            "requires_approval": self.requires_approval,
            "template_id": self.template_id,
            "mission_id": self.mission_id,
            "progress": self.progress,
            "step_count": len(self.steps),
            "approval": self.approval,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ExecutionPlan:
        steps = [PlanStep.from_dict(s) for s in d.get("steps", [])]
        plan = cls(
            plan_id=d.get("plan_id", ""),
            goal=d.get("goal", ""),
            description=d.get("description", ""),
            steps=steps,
            status=PlanStatus(d.get("status", "draft")),
            risk_score=d.get("risk_score", "low"),
            requires_approval=d.get("requires_approval", False),
            template_id=d.get("template_id", ""),
            mission_id=d.get("mission_id", ""),
            approval=d.get("approval", {}),
            metadata=d.get("metadata", {}),
        )
        plan.risk_score = plan.compute_risk()
        plan.requires_approval = plan.compute_approval_required()
        return plan

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_json(cls, s: str) -> ExecutionPlan:
        return cls.from_dict(json.loads(s))
