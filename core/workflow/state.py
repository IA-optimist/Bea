"""
BEA Workflow — State dataclasses (Phase 2 — data layer)
=========================================================
WorkflowStep and WorkflowExecution hold the mutable state of a running workflow.
No I/O here — pure data structures.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    step_id: int = 0
    name: str = ""
    action: str = ""            # connector name or tool name
    params: dict = field(default_factory=dict)
    status: str = "pending"     # pending | running | completed | failed | skipped
    result: Any = None
    error: str = ""
    retries: int = 0
    max_retries: int = 3
    started_at: float = 0.0
    completed_at: float = 0.0
    depends_on: list = field(default_factory=list)  # step_ids

    def to_dict(self) -> dict:
        d = asdict(self)
        # Ensure result is serializable
        try:
            json.dumps(d["result"])
        except (TypeError, ValueError):
            d["result"] = str(d["result"])[:500]
        return d

    @property
    def duration_s(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0


@dataclass
class WorkflowExecution:
    """A running workflow instance."""
    execution_id: str = ""
    workflow_name: str = ""
    version: int = 1
    steps: list = field(default_factory=list)  # list[WorkflowStep] stored as dicts
    status: str = "created"     # created | running | paused | completed | failed | cancelled
    current_step: int = 0
    created_at: float = 0.0
    started_at: float = 0.0
    paused_at: float = 0.0
    completed_at: float = 0.0
    total_retries: int = 0
    error_summary: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        from dataclasses import asdict as _asdict
        return _asdict(self)

    @property
    def duration_s(self) -> float:
        end = self.completed_at or self.paused_at or time.time()
        return end - self.started_at if self.started_at else 0.0

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if isinstance(s, dict)
                        and s.get("status") in ("completed", "skipped"))
        return round(completed / len(self.steps), 3)

    @property
    def step_objects(self) -> list[WorkflowStep]:
        """Convert step dicts back to WorkflowStep objects."""
        result = []
        for s in self.steps:
            if isinstance(s, dict):
                result.append(WorkflowStep(
                    **{k: v for k, v in s.items() if k in WorkflowStep.__dataclass_fields__}
                ))
            elif isinstance(s, WorkflowStep):
                result.append(s)
        return result
