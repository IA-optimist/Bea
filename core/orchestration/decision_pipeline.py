"""
core/orchestration/decision_pipeline.py — AI OS Canonical Decision Pipeline.

Normalizes the 8-step reasoning flow across all mission types.
Each step emits structured output for traceability.
Planner reasons in terms of capabilities, not arbitrary text.

Wraps existing MetaOrchestrator phases into a formal pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal
import time
import logging

log = logging.getLogger("bea.decision_pipeline")

PipelinePhase = Literal[
    "intent_classification",
    "goal_decomposition",
    "capability_selection",
    "plan_generation",
    "execution",
    "review",
    "memory_update",
    "trace_finalization",
]

PHASE_ORDER = [
    "intent_classification",
    "goal_decomposition",
    "capability_selection",
    "plan_generation",
    "execution",
    "review",
    "memory_update",
    "trace_finalization",
]


@dataclass
class PhaseResult:
    """Structured output from a pipeline phase."""
    phase: PipelinePhase
    status: Literal["completed", "skipped", "failed"] = "completed"
    output: dict = field(default_factory=dict)
    duration_ms: int = 0
    error: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PipelineState:
    """Full pipeline execution state."""
    mission_id: str = ""
    goal: str = ""
    phases: list[PhaseResult] = field(default_factory=list)
    current_phase: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    status: str = "running"
    
    def record_phase(self, phase: PipelinePhase, output: dict,
                     status: str = "completed", error: str = "", duration_ms: int = 0):
        self.phases.append(PhaseResult(
            phase=phase, status=status, output=output,
            duration_ms=duration_ms, error=error,
        ))
        self.current_phase = phase
    
    def complete(self, status: str = "done"):
        self.completed_at = time.time()
        self.status = status
    
    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal[:100],
            "status": self.status,
            "phases": [p.to_dict() for p in self.phases],
            "duration_ms": int((self.completed_at or time.time()) - self.started_at) * 1000,
        }
    
    def summary(self) -> str:
        completed = sum(1 for p in self.phases if p.status == "completed")
        failed = sum(1 for p in self.phases if p.status == "failed")
        return f"{completed}/{len(self.phases)} phases completed, {failed} failed"


def create_pipeline(mission_id: str, goal: str) -> PipelineState:
    """Create a new pipeline state for a mission."""
    return PipelineState(mission_id=mission_id, goal=goal)
