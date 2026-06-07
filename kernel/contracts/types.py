"""
kernel/contracts/types.py — Canonical domain types for BeaMax kernel.

All kernel-level communication uses these contracts. They define:
  - Required fields
  - Validation rules (via __post_init__)
  - Serialization format (to_dict / from_dict)
  - Invariants (documented, enforced where practical)

Versioned: changes to contracts require explicit version bump.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ══════════════════════════════════════════════════════════════
# Enumerations
# ══════════════════════════════════════════════════════════════

class StepType(str, Enum):
    """What kind of execution a step represents."""
    BUSINESS_ACTION = "business_action"
    TOOL = "tool"
    SKILL = "skill"
    COGNITIVE = "cognitive"  # internal reasoning step


class MissionStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DELEGATE = "delegate"
    ESCALATE = "escalate"
    DEFER = "defer"


# ══════════════════════════════════════════════════════════════
# Core Contracts
# ══════════════════════════════════════════════════════════════

@dataclass
class Goal:
    """A structured objective that drives mission creation."""
    description: str
    constraints: list[str] = field(default_factory=list)
    priority: int = 5  # 1 (highest) to 10 (lowest)
    deadline: float = 0  # unix timestamp, 0 = no deadline
    source: str = ""  # who/what created this goal

    def validate(self) -> list[str]:
        errors = []
        if not self.description or not self.description.strip():
            errors.append("Goal description is required")
        if not 1 <= self.priority <= 10:
            errors.append("Priority must be 1-10")
        return errors

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "constraints": self.constraints,
            "priority": self.priority,
            "deadline": self.deadline,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Goal:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Mission:
    """
    A mission is the top-level unit of work.

    Invariants:
      - mission_id is globally unique
      - status transitions are validated
      - goal is immutable after creation
    """
    mission_id: str = ""
    goal: Goal = field(default_factory=lambda: Goal(description=""))
    status: MissionStatus = MissionStatus.PENDING
    plan_id: str = ""
    run_id: str = ""
    created_at: float = 0
    updated_at: float = 0
    metadata: dict = field(default_factory=dict)

    _VALID_TRANSITIONS: dict = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not self.mission_id:
            self.mission_id = f"mission-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()
        self._VALID_TRANSITIONS = {
            MissionStatus.PENDING: {MissionStatus.PLANNING, MissionStatus.CANCELLED},
            MissionStatus.PLANNING: {MissionStatus.EXECUTING, MissionStatus.FAILED, MissionStatus.CANCELLED},
            MissionStatus.EXECUTING: {MissionStatus.AWAITING_APPROVAL, MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED},
            MissionStatus.AWAITING_APPROVAL: {MissionStatus.EXECUTING, MissionStatus.FAILED, MissionStatus.CANCELLED},
            MissionStatus.COMPLETED: set(),
            MissionStatus.FAILED: set(),
            MissionStatus.CANCELLED: set(),
        }

    def can_transition(self, target: MissionStatus) -> bool:
        return target in self._VALID_TRANSITIONS.get(self.status, set())

    def transition(self, target: MissionStatus) -> bool:
        if not self.can_transition(target):
            return False
        self.status = target
        self.updated_at = time.time()
        return True

    def validate(self) -> list[str]:
        errors = self.goal.validate()
        if not self.mission_id:
            errors.append("mission_id is required")
        return errors

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal.to_dict(),
            "status": self.status.value,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Mission:
        goal = Goal.from_dict(d.get("goal", {})) if isinstance(d.get("goal"), dict) else Goal(description=str(d.get("goal", "")))
        return cls(
            mission_id=d.get("mission_id", ""),
            goal=goal,
            status=MissionStatus(d.get("status", "pending")),
            plan_id=d.get("plan_id", ""),
            run_id=d.get("run_id", ""),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
            metadata=d.get("metadata", {}),
        )


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    step_id: str = ""
    type: StepType = StepType.BUSINESS_ACTION
    target_id: str = ""
    name: str = ""
    inputs: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    result: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.step_id:
            self.step_id = f"step-{uuid.uuid4().hex[:8]}"
        if isinstance(self.type, str):
            self.type = StepType(self.type)

    def validate(self) -> list[str]:
        errors = []
        if not self.target_id:
            errors.append(f"Step {self.step_id}: target_id is required")
        return errors

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
class Plan:
    """An execution plan — ordered steps to achieve a goal."""
    plan_id: str = ""
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    template_id: str = ""
    created_at: float = 0

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()

    def validate(self) -> list[str]:
        errors = []
        if not self.goal:
            errors.append("Plan must have a goal")
        if not self.steps:
            errors.append("Plan must have at least one step")
        for step in self.steps:
            errors.extend(step.validate())
        return errors

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "template_id": self.template_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        return cls(
            plan_id=d.get("plan_id", ""),
            goal=d.get("goal", ""),
            steps=[PlanStep.from_dict(s) for s in d.get("steps", [])],
            status=PlanStatus(d.get("status", "draft")),
            risk_level=RiskLevel(d.get("risk_level", "low")),
            requires_approval=d.get("requires_approval", False),
            template_id=d.get("template_id", ""),
            created_at=d.get("created_at", 0),
        )


@dataclass
class Action:
    """A discrete action the system can take."""
    action_id: str = ""
    action_type: str = ""  # tool_invoke, skill_execute, file_write, etc.
    target: str = ""
    inputs: dict = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    source: str = ""  # which step/agent requested this

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id or f"act-{uuid.uuid4().hex[:8]}",
            "action_type": self.action_type,
            "target": self.target,
            "inputs": self.inputs,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "source": self.source,
        }


@dataclass
class Decision:
    """A decision made by the system or a human."""
    decision_id: str = ""
    decision_type: DecisionType = DecisionType.APPROVE
    target_id: str = ""
    reason: str = ""
    confidence: float = 1.0  # 0.0 to 1.0
    decided_by: str = ""  # agent role, "operator", "system"
    timestamp: float = 0

    def __post_init__(self):
        if not self.decision_id:
            self.decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = time.time()

    def validate(self) -> list[str]:
        errors = []
        if not 0.0 <= self.confidence <= 1.0:
            errors.append("Confidence must be 0.0-1.0")
        return errors

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "target_id": self.target_id,
            "reason": self.reason,
            "confidence": self.confidence,
            "decided_by": self.decided_by,
            "timestamp": self.timestamp,
        }


@dataclass
class Observation:
    """An observation from execution — what the system perceived."""
    observation_id: str = ""
    source: str = ""  # tool, skill, agent, environment
    content: Any = None
    confidence: float = 1.0
    timestamp: float = 0
    mission_id: str = ""
    step_id: str = ""

    def __post_init__(self):
        if not self.observation_id:
            self.observation_id = f"obs-{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "source": self.source,
            "content": str(self.content)[:1000] if self.content else None,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "mission_id": self.mission_id,
            "step_id": self.step_id,
        }


@dataclass
class ExecutionResult:
    """Result of executing any action, step, or plan."""
    ok: bool
    output: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    artifacts: list[str] = field(default_factory=list)
    step_id: str = ""
    mission_id: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "artifacts": self.artifacts,
            "step_id": self.step_id,
            "mission_id": self.mission_id,
        }


@dataclass
class PolicyDecision:
    """A policy engine decision about whether an action is allowed."""
    allowed: bool
    action_id: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    reason: str = ""
    policy_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "action_id": self.action_id,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "policy_version": self.policy_version,
        }


@dataclass
class MemoryRecord:
    """A typed memory entry."""
    record_id: str = ""
    memory_type: str = ""  # working, episodic, execution, procedural, semantic
    content: dict = field(default_factory=dict)
    mission_id: str = ""
    plan_id: str = ""
    step_id: str = ""
    confidence: float = 1.0
    source: str = ""
    timestamp: float = 0
    ttl: float = 0  # time-to-live in seconds, 0 = permanent

    def __post_init__(self):
        if not self.record_id:
            self.record_id = f"mem-{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = time.time()

    @property
    def expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return time.time() > self.timestamp + self.ttl

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "confidence": self.confidence,
            "source": self.source,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "expired": self.expired,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MemoryRecord:
        return cls(**{k: v for k, v in d.items()
                     if k in cls.__dataclass_fields__ and k != "expired"})


@dataclass
class SystemEvent:
    """A canonical system event for the cognitive journal."""
    event_id: str = ""
    event_type: str = ""  # mission_created, plan_generated, step_completed, etc.
    source: str = ""
    summary: str = ""
    mission_id: str = ""
    plan_id: str = ""
    step_id: str = ""
    severity: str = "info"  # debug, info, warning, error, critical
    payload: dict = field(default_factory=dict)
    timestamp: float = 0

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"evt-{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = time.time()

    def validate(self) -> list[str]:
        errors = []
        if not self.event_type:
            errors.append("event_type is required")
        if not self.summary:
            errors.append("summary is required")
        return errors

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "summary": self.summary,
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "severity": self.severity,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SystemEvent:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
