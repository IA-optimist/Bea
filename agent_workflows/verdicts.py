"""
agent_workflows/verdicts.py — ReviewVerdict: structured output from any review step.

VerdictSeverity follows the same P0/P1/P2/P3 scale as the beta testing rubric:
    P0 — blocker: workflow MUST stop immediately
    P1 — critical: must be fixed before merge / next phase
    P2 — major: should be fixed in this sprint
    P3 — minor / informational: non-blocking
"""
from __future__ import annotations

from enum import Enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class VerdictSeverity(str, Enum):
    P0 = "P0"  # blocker — stop everything
    P1 = "P1"  # critical — must fix before next phase
    P2 = "P2"  # major — fix in sprint
    P3 = "P3"  # minor / info


# P0 and P1 are blocking by default
_BLOCKING_SEVERITIES = frozenset({VerdictSeverity.P0, VerdictSeverity.P1})


class ReviewVerdict(BaseModel):
    """
    Structured verdict from any review step in a SOP workflow.

    - category: arbitrary string, e.g. "security", "tests", "style"
    - severity: P0 stops the workflow entirely, P1 marks the result as failed
    - description: human-readable explanation (required)
    - evidence: optional supporting data (file path, line, test output)
    - auto_fix_hint: optional suggestion for automated remediation
    """

    step_id: str
    category: str
    severity: VerdictSeverity
    description: str = Field(min_length=10)
    evidence: str | None = None
    auto_fix_hint: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.severity in _BLOCKING_SEVERITIES

    @property
    def is_p0(self) -> bool:
        return self.severity == VerdictSeverity.P0


class WorkflowVerdict(BaseModel):
    """Aggregated verdict for a complete workflow run."""

    workflow_id: str
    verdicts: list[ReviewVerdict] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def blocking_verdicts(self) -> list[ReviewVerdict]:
        return [v for v in self.verdicts if v.is_blocking]

    @property
    def p0_verdicts(self) -> list[ReviewVerdict]:
        return [v for v in self.verdicts if v.is_p0]

    @property
    def passed(self) -> bool:
        return len(self.blocking_verdicts) == 0

    @property
    def severity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in VerdictSeverity}
        for v in self.verdicts:
            counts[v.severity.value] += 1
        return counts

    def summary(self) -> str:
        counts = self.severity_counts
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] workflow={self.workflow_id} "
            f"P0={counts['P0']} P1={counts['P1']} P2={counts['P2']} P3={counts['P3']}"
        )
