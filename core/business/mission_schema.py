"""
BEA MAX — Business Mission Schema
========================================
Core data models for structured multi-step business missions.

Mission: the top-level objective with steps, dependencies, results.
MissionStep: a single unit of work assigned to an agent with tools.
StepResult: outcome of executing a step.

States follow a strict lifecycle:
  draft → planned → running → (waiting_approval) → completed | failed
  Any running state can transition to paused.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════

class MissionStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


# ═══════════════════════════════════════════════════════════════
# STEP
# ═══════════════════════════════════════════════════════════════

@dataclass
class MissionStep:
    """A single executable step within a mission."""
    step_id: str = ""
    name: str = ""
    description: str = ""
    agent: str = ""                 # Agent ID to execute this step
    required_tools: list[str] = field(default_factory=list)
    required_connectors: list[str] = field(default_factory=list)
    required_identities: list[str] = field(default_factory=list)
    required_secrets: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # step_ids
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    status: str = StepStatus.PENDING.value
    approval_required: bool = False
    approved: bool = False              # Set True after human approval granted
    risk_level: str = RiskLevel.LOW.value
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    started_at: float | None = None
    completed_at: float | None = None
    error: str = ""
    execution_mode: str = ExecutionMode.SEQUENTIAL.value

    def __post_init__(self):
        if not self.step_id:
            self.step_id = f"step-{hashlib.sha256(os.urandom(8)).hexdigest()[:8]}"

    @property
    def is_terminal(self) -> bool:
        return self.status in (StepStatus.COMPLETED.value, StepStatus.FAILED.value, StepStatus.SKIPPED.value)

    @property
    def is_ready(self) -> bool:
        return self.status == StepStatus.PENDING.value

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return 0

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description[:300],
            "agent": self.agent,
            "required_tools": self.required_tools,
            "required_connectors": self.required_connectors,
            "required_identities": self.required_identities,
            "depends_on": self.depends_on,
            "status": self.status,
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "retry_count": self.retry_count,
            "timeout_seconds": self.timeout_seconds,
            "has_output": bool(self.output_data),
            "error": self.error[:200],
            "duration_ms": round(self.duration_ms, 1),
        }


# ═══════════════════════════════════════════════════════════════
# MISSION
# ═══════════════════════════════════════════════════════════════

@dataclass
class Mission:
    """A structured multi-step business mission."""
    mission_id: str = ""
    title: str = ""
    description: str = ""
    objective: str = ""
    priority: str = Priority.MEDIUM.value
    risk_level: str = RiskLevel.MEDIUM.value
    status: str = MissionStatus.DRAFT.value
    template_id: str = ""               # If created from template

    # Assignments
    assigned_agents: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_connectors: list[str] = field(default_factory=list)
    required_identities: list[str] = field(default_factory=list)

    # Execution
    steps: list[MissionStep] = field(default_factory=list)
    execution_mode: str = ExecutionMode.SEQUENTIAL.value
    max_parallel: int = 3

    # Results
    results: dict[str, Any] = field(default_factory=dict)
    logs: list[dict] = field(default_factory=list)

    # Timestamps
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    paused_at: float | None = None

    # Approval tracking
    pending_approval_id: str = ""       # approval_notifier ticket_id

    def __post_init__(self):
        if not self.mission_id:
            self.mission_id = f"mission-{hashlib.sha256(os.urandom(12)).hexdigest()[:12]}"

    # ── State queries ──

    @property
    def is_terminal(self) -> bool:
        return self.status in (MissionStatus.COMPLETED.value, MissionStatus.FAILED.value)

    @property
    def is_active(self) -> bool:
        return self.status in (MissionStatus.RUNNING.value, MissionStatus.WAITING_APPROVAL.value)

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.is_terminal)
        return round(done / len(self.steps) * 100, 1)

    @property
    def current_step(self) -> MissionStep | None:
        for s in self.steps:
            if s.status == StepStatus.RUNNING.value:
                return s
        return None

    @property
    def next_pending_step(self) -> MissionStep | None:
        for s in self.steps:
            if s.status == StepStatus.PENDING.value:
                # Check dependencies are met
                if all(self._step_completed(dep) for dep in s.depends_on):
                    return s
        return None

    @property
    def duration_seconds(self) -> float:
        if self.started_at:
            end = self.completed_at or time.time()
            return end - self.started_at
        return 0

    @property
    def failed_steps(self) -> list[MissionStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED.value]

    @property
    def completed_steps(self) -> list[MissionStep]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED.value]

    def _step_completed(self, step_id: str) -> bool:
        for s in self.steps:
            if s.step_id == step_id:
                return s.status == StepStatus.COMPLETED.value
        return True  # Unknown dep → assume met (fail-open)

    def get_step(self, step_id: str) -> MissionStep | None:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def add_log(self, event: str, data: dict | None = None):
        self.logs.append({
            "timestamp": time.time(),
            "event": event,
            "data": data or {},
        })

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "title": self.title,
            "description": self.description[:500],
            "objective": self.objective[:500],
            "priority": self.priority,
            "risk_level": self.risk_level,
            "status": self.status,
            "template_id": self.template_id,
            "assigned_agents": self.assigned_agents,
            "required_connectors": self.required_connectors,
            "required_identities": self.required_identities,
            "execution_mode": self.execution_mode,
            "steps": [s.to_dict() for s in self.steps],
            "progress": self.progress,
            "duration_seconds": round(self.duration_seconds, 1),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "pending_approval_id": self.pending_approval_id,
            "log_count": len(self.logs),
            "results_count": len(self.results),
        }

    def to_summary(self) -> dict:
        """Lightweight summary for list views."""
        return {
            "mission_id": self.mission_id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "progress": self.progress,
            "step_count": len(self.steps),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Mission":
        steps = [
            MissionStep(**{k: v for k, v in sd.items() if k in MissionStep.__dataclass_fields__})
            for sd in data.pop("steps", [])
        ]
        # Filter to only known fields
        known = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in data.items() if k in known}
        filtered["steps"] = steps
        return cls(**filtered)


# ═══════════════════════════════════════════════════════════════
# DEPENDENCY CHECK RESULT
# ═══════════════════════════════════════════════════════════════

@dataclass
class DependencyCheckResult:
    """Result of validating mission dependencies."""
    valid: bool = True
    missing_connectors: list[str] = field(default_factory=list)
    missing_secrets: list[str] = field(default_factory=list)
    missing_identities: list[str] = field(default_factory=list)
    missing_agents: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "missing_connectors": self.missing_connectors,
            "missing_secrets": self.missing_secrets,
            "missing_identities": self.missing_identities,
            "missing_agents": self.missing_agents,
            "missing_tools": self.missing_tools,
            "suggestions": self.suggestions,
        }
