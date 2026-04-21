"""
core/planning/step_context.py — Shared execution context across plan steps.

Carries plan-wide state, outputs from previous steps, artifacts,
and approval decisions. Serializable for pause/resume.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class StepContext:
    """
    Shared execution context that flows through all steps in a plan run.

    Each step can read outputs from previous steps and write its own.
    The context is serializable for pause/resume support.
    """
    plan_id: str = ""
    run_id: str = ""
    goal: str = ""
    current_step_index: int = 0
    step_outputs: dict[str, dict] = field(default_factory=dict)  # step_id → output
    artifacts: list[str] = field(default_factory=list)
    approval_decisions: dict[str, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    started_at: float = 0
    updated_at: float = 0

    def __post_init__(self):
        if not self.run_id:
            self.run_id = f"run-{uuid.uuid4().hex[:8]}"
        if not self.started_at:
            self.started_at = time.time()

    def set_step_output(self, step_id: str, output: dict) -> None:
        """Record the output from a completed step."""
        self.step_outputs[step_id] = output
        self.updated_at = time.time()

    def get_step_output(self, step_id: str) -> dict:
        """Get the output from a specific step."""
        return self.step_outputs.get(step_id, {})

    def get_all_outputs(self) -> dict:
        """
        Get merged outputs from all completed steps (later steps override).

        Extracts the 'content' subdict from skill step outputs so that
        downstream steps receive actual analysis fields (tam, problems, etc.)
        rather than step metadata (skill_id, invoked, quality, etc.).
        """
        merged = {}
        for output in self.step_outputs.values():
            if isinstance(output, dict):
                # If this is a skill step with LLM content, extract it
                content = output.get("content")
                if isinstance(content, dict) and content:
                    merged.update(content)
                else:
                    # Non-skill step or prep-only — merge as-is
                    # but skip metadata fields that would pollute inputs
                    _METADATA_KEYS = {
                        "skill_id", "invoked", "prepared", "quality",
                        "output_schema", "quality_checks",
                        "prompt_context_length", "raw_length",
                        "duration_ms", "model", "llm_error",
                    }
                    for k, v in output.items():
                        if k not in _METADATA_KEYS:
                            merged[k] = v
        return merged

    def add_artifact(self, path: str) -> None:
        if path and path not in self.artifacts:
            self.artifacts.append(path)

    def record_approval(self, step_id: str, approved: bool, reason: str = "") -> None:
        self.approval_decisions[step_id] = {
            "approved": approved,
            "reason": reason,
            "timestamp": time.time(),
        }

    @property
    def duration_ms(self) -> float:
        if self.started_at:
            end = self.updated_at or time.time()
            return round((end - self.started_at) * 1000)
        return 0

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "goal": self.goal,
            "current_step_index": self.current_step_index,
            "step_outputs": self.step_outputs,
            "artifacts": self.artifacts,
            "approval_decisions": self.approval_decisions,
            "metadata": self.metadata,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StepContext:
        return cls(
            plan_id=d.get("plan_id", ""),
            run_id=d.get("run_id", ""),
            goal=d.get("goal", ""),
            current_step_index=d.get("current_step_index", 0),
            step_outputs=d.get("step_outputs", {}),
            artifacts=d.get("artifacts", []),
            approval_decisions=d.get("approval_decisions", {}),
            metadata=d.get("metadata", {}),
            started_at=d.get("started_at", 0),
            updated_at=d.get("updated_at", 0),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_json(cls, s: str) -> StepContext:
        return cls.from_dict(json.loads(s))
