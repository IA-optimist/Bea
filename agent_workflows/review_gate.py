"""
agent_workflows/review_gate.py - machine-readable final review gate.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


Verdict = Literal["approve", "needs_changes", "block"]
Severity = Literal["P0", "P1", "P2", "P3"]

_SENSITIVE_PATH_MARKERS = (
    "auth",
    "security",
    "sandbox",
    "tool_executor",
    "tools/",
    "approval",
    "memory",
)


class FinalReviewVerdict(BaseModel):
    verdict: Verdict
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=3)
    required_changes: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    tests_missing: list[str] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)
    files_reviewed: list[str] = Field(default_factory=list)
    risk_areas: list[str] = Field(default_factory=list)
    human_summary: str = Field(min_length=3)

    @model_validator(mode="after")
    def severity_controls_verdict(self) -> "FinalReviewVerdict":
        if self.severity in {"P0", "P1"} and self.verdict != "block":
            self.verdict = "block"
        return self


class ReviewGate:
    """Applies final non-negotiable review policy."""

    def __init__(self, *, min_confidence: float = 0.65) -> None:
        self.min_confidence = min_confidence

    def evaluate(
        self,
        verdict: FinalReviewVerdict | object,
        *,
        mission_type: str,
        reviewers: list[str],
    ) -> FinalReviewVerdict:
        if not isinstance(verdict, FinalReviewVerdict):
            return self._block("Malformed review verdict", files_reviewed=[])
        if not reviewers:
            return self._block("Reviewer absent", files_reviewed=verdict.files_reviewed)

        if verdict.severity in {"P0", "P1"}:
            return verdict.model_copy(update={"verdict": "block"})

        sensitive = self._touches_sensitive_area(verdict)
        if sensitive and "SecurityAgent" not in reviewers:
            return self._block(
                "SecurityAgent required for auth/sandbox/tools/approval/memory changes",
                files_reviewed=verdict.files_reviewed,
                risk_areas=sorted(set(verdict.risk_areas + ["security-review"])),
            )

        if mission_type == "code" and verdict.tests_missing and verdict.verdict == "approve":
            return verdict.model_copy(update={"verdict": "needs_changes"})

        if verdict.confidence < self.min_confidence and verdict.verdict == "approve":
            return verdict.model_copy(update={"verdict": "needs_changes"})

        return verdict

    def _touches_sensitive_area(self, verdict: FinalReviewVerdict) -> bool:
        haystack = "\n".join(verdict.files_reviewed + verdict.risk_areas).lower()
        return any(marker in haystack for marker in _SENSITIVE_PATH_MARKERS)

    @staticmethod
    def _block(
        reason: str,
        *,
        files_reviewed: list[str],
        risk_areas: list[str] | None = None,
    ) -> FinalReviewVerdict:
        return FinalReviewVerdict(
            verdict="block",
            severity="P1",
            confidence=1.0,
            reason=reason,
            required_changes=[reason],
            tests_run=[],
            tests_missing=[],
            security_findings=[reason],
            files_reviewed=files_reviewed,
            risk_areas=risk_areas or [],
            human_summary=reason,
        )
