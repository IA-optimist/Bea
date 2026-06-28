"""
agent_github/mission_loop.py — GitHubMissionLoop: issue → plan → PR draft.

CRITICAL INVARIANTS (never remove):
  1. PR drafts are NEVER auto-merged.
  2. Security and self-improvement issues ALWAYS require human approval.
  3. No business/financial/cyber action without human approval.
  4. Branch names are always prefixed bea/issue-<number>/.

Inspired by AutoPR / Sweep patterns.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
import structlog

from agent_github.issues import ClassifiedIssue, IssueKind

log = structlog.get_logger("bea.github.mission_loop")

# Kinds that are never auto-planned — require human review first
_ALWAYS_HUMAN: frozenset[IssueKind] = frozenset({
    IssueKind.SECURITY,
    IssueKind.SELF_IMPROVEMENT,
})


class MissionStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    PR_DRAFT_CREATED = "pr_draft_created"
    HUMAN_REVIEW = "human_review"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ABORTED = "aborted"


class MissionPlan(BaseModel):
    """Plan for addressing a GitHub issue."""

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    issue_number: int
    issue_kind: IssueKind
    branch_name: str        # always bea/issue-<number>/...
    goal_summary: str       # one-line goal
    steps: list[str]        # implementation steps
    requires_human_approval: bool
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: MissionStatus = MissionStatus.PENDING
    pr_url: str | None = None
    pr_draft: bool = True   # ALWAYS draft


class LoopEvent(BaseModel):
    """Audit event for the mission loop."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    issue_number: int
    plan_id: str | None = None
    event_type: str
    description: str
    at: datetime = Field(default_factory=datetime.utcnow)


class GitHubMissionLoop:
    """
    Orchestrates the GitHub issue → plan → PR draft pipeline.

    Never calls merge.  Never bypasses human approval for security/self-improvement.
    All events are logged to structlog.
    """

    def __init__(self) -> None:
        self._events: list[LoopEvent] = []
        self._plans: dict[int, MissionPlan] = {}

    def _emit(self, issue_number: int, event_type: str, desc: str, plan_id: str | None = None) -> None:
        ev = LoopEvent(
            issue_number=issue_number,
            plan_id=plan_id,
            event_type=event_type,
            description=desc,
        )
        self._events.append(ev)
        log.info(
            "github_loop_event",
            issue=issue_number,
            ev_type=event_type,
            desc=desc[:100],
            plan=plan_id,
        )

    def plan(self, classified: ClassifiedIssue) -> MissionPlan:
        """
        Create a MissionPlan from a ClassifiedIssue.

        Security and self-improvement issues are immediately flagged
        as HUMAN_REVIEW — no implementation steps are generated.
        """
        num = classified.issue_number
        branch = self._branch_name(num, classified.kind)

        if classified.kind in _ALWAYS_HUMAN:
            plan = MissionPlan(
                issue_number=num,
                issue_kind=classified.kind,
                branch_name=branch,
                goal_summary=f"[HUMAN REVIEW REQUIRED] {classified.title[:120]}",
                steps=[
                    "1. Human reviews this issue (security/self-improvement scope)",
                    "2. Human approves or rejects the plan",
                    "3. Only after approval: implementation begins",
                ],
                requires_human_approval=True,
                status=MissionStatus.HUMAN_REVIEW,
            )
            self._plans[num] = plan
            self._emit(num, "plan_human_required",
                       f"issue kind={classified.kind.value} requires human approval",
                       plan.plan_id)
            return plan

        if not classified.is_actionable:
            plan = MissionPlan(
                issue_number=num,
                issue_kind=classified.kind,
                branch_name=branch,
                goal_summary=f"[NOT ACTIONABLE] {classified.title[:120]}",
                steps=["Issue is not actionable (question/unknown) — no implementation"],
                requires_human_approval=False,
                status=MissionStatus.BLOCKED,
            )
            self._plans[num] = plan
            self._emit(num, "plan_not_actionable", f"kind={classified.kind.value}", plan.plan_id)
            return plan

        steps = self._generate_steps(classified)
        plan = MissionPlan(
            issue_number=num,
            issue_kind=classified.kind,
            branch_name=branch,
            goal_summary=classified.title[:120],
            steps=steps,
            requires_human_approval=classified.requires_human_approval,
            status=MissionStatus.PLANNING,
        )
        self._plans[num] = plan
        self._emit(num, "plan_created", f"steps={len(steps)} branch={branch}", plan.plan_id)
        return plan

    def mark_pr_draft_created(self, issue_number: int, pr_url: str) -> MissionPlan:
        """Record that a PR draft was created.  NEVER auto-merges."""
        plan = self._plans.get(issue_number)
        if plan is None:
            raise KeyError(f"no plan for issue #{issue_number}")
        # model_copy for immutability
        updated = plan.model_copy(update={
            "status": MissionStatus.PR_DRAFT_CREATED,
            "pr_url": pr_url,
            "pr_draft": True,
        })
        self._plans[issue_number] = updated
        self._emit(
            issue_number,
            "pr_draft_created",
            f"PR draft at {pr_url} — awaiting human review",
            plan.plan_id,
        )
        return updated

    def events_for(self, issue_number: int) -> list[LoopEvent]:
        return [e for e in self._events if e.issue_number == issue_number]

    @staticmethod
    def _branch_name(issue_number: int, kind: IssueKind) -> str:
        kind_slug = kind.value.lower().replace("_", "-")
        return f"bea/issue-{issue_number}/{kind_slug}"

    @staticmethod
    def _generate_steps(classified: ClassifiedIssue) -> list[str]:
        base = [
            f"1. Classify issue #{classified.issue_number}: {classified.kind.value} (confidence={classified.confidence:.0%})",
            "2. Create worktree from main (branch: " + GitHubMissionLoop._branch_name(classified.issue_number, classified.kind) + ")",
            "3. Implement changes in ACI sandbox (deny-by-default, path-scoped)",
            "4. Run tests: pytest --tb=short -q",
            "5. Run linter: ruff check",
            "6. Self-review diff — produce ReviewVerdicts",
        ]
        if classified.kind == IssueKind.BUG:
            base.insert(3, "   3a. Write regression test BEFORE fix")
        if classified.kind == IssueKind.ENHANCEMENT:
            base.insert(3, "   3a. Write failing tests FIRST (TDD)")
        base.append("7. Create PR draft — NEVER auto-merge")
        base.append("8. Add label 'pr-draft' and 'agentic'")
        base.append("9. Notify human for review")
        return base
