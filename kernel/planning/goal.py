"""
kernel/planning/goal.py — Kernel-level goal and plan data contracts.

Pure data types used by KernelPlanner. No imports from core/.
These are the kernel's internal representation of goals and plans —
independent of LangChain, LLM providers, or business domain logic.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class StepStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    FAILED   = "failed"
    SKIPPED  = "skipped"


class PlanComplexity(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


@dataclass
class KernelGoal:
    """
    A structured goal understood by the kernel.
    Created from raw user input by the task router / goal decomposer.
    """
    description:  str
    goal_type:    str  = "general"     # create, research, analyze, code, improve…
    priority:     int  = 5             # 1 (highest) to 10 (lowest)
    constraints:  list[str] = field(default_factory=list)
    context:      dict      = field(default_factory=dict)
    created_at:   float     = field(default_factory=time.time)
    goal_id:      str       = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict:
        return {
            "goal_id":     self.goal_id,
            "description": self.description,
            "goal_type":   self.goal_type,
            "priority":    self.priority,
            "constraints": self.constraints,
            "created_at":  self.created_at,
        }

    @classmethod
    def from_text(cls, text: str, goal_type: str = "general") -> "KernelGoal":
        """Create a KernelGoal from a raw text string."""
        return cls(description=text.strip(), goal_type=goal_type)


@dataclass
class KernelPlanStep:
    """A single step in a kernel plan."""
    step_id:    int
    action:     str                    # what to do
    agent_hint: str       = ""         # suggested agent role
    tool_hint:  str       = ""         # suggested tool
    complexity: PlanComplexity = PlanComplexity.MEDIUM
    depends_on: list[int] = field(default_factory=list)  # step_ids this depends on
    retryable:  bool      = True
    status:     StepStatus = StepStatus.PENDING
    result:     str        = ""
    metadata:   dict       = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step_id":    self.step_id,
            "action":     self.action,
            "agent_hint": self.agent_hint,
            "tool_hint":  self.tool_hint,
            "complexity": self.complexity.value,
            "depends_on": self.depends_on,
            "retryable":  self.retryable,
            "status":     self.status.value,
            "result":     self.result,
        }


@dataclass
class KernelPlan:
    """
    A kernel-level plan: a goal broken into steps, ready for execution.
    """
    plan_id:    str
    goal:       KernelGoal
    steps:      list[KernelPlanStep] = field(default_factory=list)
    complexity: PlanComplexity       = PlanComplexity.MEDIUM
    created_at: float                = field(default_factory=time.time)
    source:     str                  = "kernel_planner"  # who generated this plan

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def is_empty(self) -> bool:
        return len(self.steps) == 0

    @property
    def pending_steps(self) -> list[KernelPlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    @property
    def done_steps(self) -> list[KernelPlanStep]:
        return [s for s in self.steps if s.status == StepStatus.DONE]

    @property
    def success_rate(self) -> float:
        if not self.steps:
            return 0.0
        return len(self.done_steps) / len(self.steps)

    def to_dict(self) -> dict:
        return {
            "plan_id":    self.plan_id,
            "goal":       self.goal.to_dict(),
            "steps":      [s.to_dict() for s in self.steps],
            "complexity": self.complexity.value,
            "step_count": self.step_count,
            "created_at": self.created_at,
            "source":     self.source,
        }
