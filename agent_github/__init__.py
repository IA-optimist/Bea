"""
agent_github — GitHub Mission Loop (AutoPR/Sweep/Dosu pattern).

Pipeline: issue → classify → plan → branch/worktree → implement → tests → PR draft
INVARIANT: Never auto-merge.  PR draft creation is the terminal step.

Public surface:
    from agent_github import BEA_LABELS, IssueClassifier, GitHubMissionLoop
    from agent_github import IssueKind, ClassifiedIssue, MissionPlan
"""
from __future__ import annotations

from agent_github.labels import BEA_LABELS
from agent_github.issues import IssueKind, ClassifiedIssue, IssueClassifier
from agent_github.mission_loop import MissionPlan, GitHubMissionLoop

__all__ = [
    "BEA_LABELS",
    "IssueKind",
    "ClassifiedIssue",
    "IssueClassifier",
    "MissionPlan",
    "GitHubMissionLoop",
]
