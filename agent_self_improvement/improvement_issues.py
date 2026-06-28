"""
agent_self_improvement/improvement_issues.py — ImprovementIssue creation.

Self-improvement NEVER patches the codebase directly.
It creates a GitHub issue that the GitHub Mission Loop handles.
Security improvements ALWAYS require human_approval=True.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator
import structlog

log = structlog.get_logger("bea.self_improve.issues")


class ImprovementKind(str, Enum):
    PROMPT = "prompt"               # improve agent prompt/instructions
    PLANNING = "planning"           # improve planning logic
    TOOL_USAGE = "tool_usage"       # improve how tools are used
    SKILL = "skill"                 # add/update a skill
    BUG_FIX = "bug_fix"            # fix a bug found through self-reflection
    SECURITY = "security"           # security improvement (ALWAYS human gate)
    PERFORMANCE = "performance"     # performance improvement
    TEST = "test"                   # add/fix tests


# Kinds that always require human approval (never auto-submitted)
_ALWAYS_HUMAN: frozenset[ImprovementKind] = frozenset({
    ImprovementKind.SECURITY,
})


class ImprovementIssue(BaseModel):
    """
    A self-improvement proposal to be filed as a GitHub issue.

    INVARIANTS:
    - human_approval_required=True for SECURITY kind (enforced by validator)
    - creates_direct_patch=False always (never self-patch)
    - proposed_files is informational only, not auto-applied
    """

    issue_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    kind: ImprovementKind
    title: str = Field(min_length=10, max_length=256)
    description: str = Field(min_length=30, max_length=8000)
    motivation: str = Field(min_length=20, max_length=2000)  # why this improvement?
    proposed_files: list[str] = Field(default_factory=list)  # informational only
    human_approval_required: bool = True   # always True
    creates_direct_patch: bool = False     # always False
    detected_by: str                       # which reflection/metric triggered this
    created_at: datetime = Field(default_factory=datetime.utcnow)
    mission_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_invariants(self) -> "ImprovementIssue":
        # Security always requires human
        if self.kind in _ALWAYS_HUMAN and not self.human_approval_required:
            raise ValueError(
                f"ImprovementKind.{self.kind.value} always requires human_approval_required=True"
            )
        # No direct patching, ever
        if self.creates_direct_patch:
            raise ValueError(
                "creates_direct_patch=True is forbidden — "
                "self-improvement must go through GitHub issues and the Mission Loop"
            )
        return self

    def to_github_body(self) -> str:
        """Format as GitHub issue body."""
        lines = [
            "## Self-Improvement Proposal",
            f"\n**Kind:** `{self.kind.value}`",
            f"**Detected by:** {self.detected_by}",
            f"**Human approval required:** {'YES' if self.human_approval_required else 'no'}",
            "",
            "## Motivation",
            self.motivation,
            "",
            "## Description",
            self.description,
        ]
        if self.proposed_files:
            lines += [
                "",
                "## Proposed Files (informational)",
                *(f"- `{f}`" for f in self.proposed_files),
                "",
                "> ⚠️ These files are proposed only — no direct patch will be applied.",
            ]
        lines += [
            "",
            "---",
            "*This issue was created by Béa's self-reflection loop.*",
            "*No code has been changed. Review and approve before implementation begins.*",
        ]
        return "\n".join(lines)


class ImprovementIssueFactory:
    """Creates ImprovementIssues from reflection data."""

    def from_failure(
        self,
        *,
        what_failed: str,
        why: str,
        kind: ImprovementKind,
        detected_by: str,
        mission_id: str | None = None,
    ) -> ImprovementIssue:
        return ImprovementIssue(
            kind=kind,
            title=f"[self-improvement] Fix: {what_failed[:80]}",
            description=f"Failure: {what_failed}\n\nRoot cause: {why}\n\nThis proposal requires review before any patch is applied.",
            motivation=f"Béa encountered a failure that could be prevented: {what_failed[:200]}",
            detected_by=detected_by,
            human_approval_required=True,
            creates_direct_patch=False,
            mission_id=mission_id,
        )

    def from_lesson(
        self,
        *,
        lesson: str,
        kind: ImprovementKind,
        detected_by: str,
        proposed_files: list[str] | None = None,
        mission_id: str | None = None,
    ) -> ImprovementIssue:
        return ImprovementIssue(
            kind=kind,
            title=f"[self-improvement] Lesson: {lesson[:80]}",
            description=f"A lesson was learned during a mission:\n\n{lesson}\n\nThis proposal requires review before any patch is applied.",
            motivation=f"Applying this lesson could improve future performance: {lesson[:200]}",
            proposed_files=proposed_files or [],
            detected_by=detected_by,
            human_approval_required=True,
            creates_direct_patch=False,
            mission_id=mission_id,
        )
