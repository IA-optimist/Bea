"""
agent_workflows/engine.py — SOPWorkflowEngine: runs structured SOP workflows.

Inspired by MetaGPT's SOP pattern:
- Each step has a role, an async handler, and produces ReviewVerdicts.
- P0 verdicts STOP the workflow immediately.
- P1 verdicts mark the workflow as failed but allow remaining steps to run.
- Full audit trail via structlog (no secrets).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

import structlog

from agent_workflows.verdicts import (
    ReviewVerdict,
    VerdictSeverity,
    WorkflowVerdict,
)

log = structlog.get_logger("bea.sop.engine")

StepHandler = Callable[["SOPContext"], Awaitable[list[ReviewVerdict]]]


@dataclass
class SOPStep:
    """A single step in a SOP workflow."""

    step_id: str
    name: str
    role: str                   # AgentRole.value
    handler: StepHandler
    description: str = ""
    required: bool = True       # if False, failure does not block next steps


@dataclass
class SOPContext:
    """Mutable context passed through the workflow."""

    workflow_id: str
    mission_id: str
    goal: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    verdicts: list[ReviewVerdict] = field(default_factory=list)
    current_step: str = ""
    stopped: bool = False
    stop_reason: str = ""


@dataclass
class WorkflowResult:
    """Final result of a workflow run."""

    workflow_id: str
    mission_id: str
    goal: str
    passed: bool
    verdict: WorkflowVerdict
    steps_completed: list[str] = field(default_factory=list)
    steps_skipped: list[str] = field(default_factory=list)
    stopped_at: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] workflow={self.workflow_id} "
            f"steps={len(self.steps_completed)} "
            f"skipped={len(self.steps_skipped)} "
            f"{self.verdict.summary()}"
        )


class SOPWorkflowEngine:
    """
    Runs a list of SOPSteps in order, collecting ReviewVerdicts.

    Rules:
    - P0 verdict → stop immediately (steps_skipped records the rest)
    - P1 verdict → workflow marked failed, but steps continue
    - P2/P3 → informational, workflow continues
    - Non-required step failure → logged but does not fail workflow
    """

    def __init__(self, steps: list[SOPStep]) -> None:
        self._steps = steps

    async def run(self, mission_id: str, goal: str) -> WorkflowResult:
        workflow_id = str(uuid.uuid4())[:12]
        ctx = SOPContext(workflow_id=workflow_id, mission_id=mission_id, goal=goal)
        completed: list[str] = []
        skipped: list[str] = []
        stopped_at: str | None = None
        _log = log.bind(workflow_id=workflow_id, mission_id=mission_id)
        _log.info("sop_workflow_start", steps=len(self._steps), goal=goal[:80])

        for step in self._steps:
            if ctx.stopped:
                skipped.append(step.step_id)
                continue

            ctx.current_step = step.step_id
            _log.info("sop_step_start", step=step.step_id, role=step.role)
            try:
                verdicts = await step.handler(ctx)
            except Exception as exc:
                _log.exception("sop_step_error", step=step.step_id, error=str(exc)[:200])
                if step.required:
                    ctx.verdicts.append(ReviewVerdict(
                        step_id=step.step_id,
                        category="engine_error",
                        severity=VerdictSeverity.P1,
                        description=f"Step '{step.step_id}' raised an unexpected exception: {exc!s:.120}",
                    ))
                completed.append(step.step_id)
                continue

            ctx.verdicts.extend(verdicts)
            completed.append(step.step_id)
            p0 = [v for v in verdicts if v.is_p0]
            if p0:
                ctx.stopped = True
                ctx.stop_reason = p0[0].description[:80]
                stopped_at = step.step_id
                _log.warning(
                    "sop_workflow_stopped_p0",
                    step=step.step_id,
                    reason=ctx.stop_reason,
                )
                break  # remaining steps become skipped
            _log.info("sop_step_done", step=step.step_id, verdicts=len(verdicts))

        # Any steps that ctx.stopped prevented from running go to skipped
        completed_set = set(completed)
        for step in self._steps:
            if step.step_id not in completed_set and step.step_id not in skipped:
                skipped.append(step.step_id)

        wv = WorkflowVerdict(workflow_id=workflow_id, verdicts=ctx.verdicts)
        result = WorkflowResult(
            workflow_id=workflow_id,
            mission_id=mission_id,
            goal=goal,
            passed=wv.passed,
            verdict=wv,
            steps_completed=completed,
            steps_skipped=skipped,
            stopped_at=stopped_at,
            finished_at=datetime.utcnow(),
        )
        _log.info(
            "sop_workflow_done",
            passed=result.passed,
            p0=len(wv.p0_verdicts),
            blocking=len(wv.blocking_verdicts),
        )
        return result
