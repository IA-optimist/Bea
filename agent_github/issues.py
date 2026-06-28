"""
agent_github/issues.py — IssueClassifier: keyword + label based issue classification.

No LLM call in the classifier — intentionally deterministic and fast.
The LLM-based planning step happens in mission_loop.py.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IssueKind(str, Enum):
    BUG = "bug"
    ENHANCEMENT = "enhancement"
    SECURITY = "security"
    RESEARCH = "research"
    DATA = "data"
    SELF_IMPROVEMENT = "self_improvement"
    QUESTION = "question"
    UNKNOWN = "unknown"


# Business / financial / cyber actions that always need human approval
_HUMAN_REQUIRED_KINDS = frozenset({
    IssueKind.SECURITY,
    IssueKind.SELF_IMPROVEMENT,
})

_KIND_PATTERNS: list[tuple[IssueKind, list[str]]] = [
    (IssueKind.SECURITY,         ["security", "vulnerability", "CVE", "injection", "XSS", "CSRF", "auth"]),
    (IssueKind.SELF_IMPROVEMENT, ["self-improvement", "self_improvement", "bea improve", "train", "fine-tune"]),
    (IssueKind.DATA,             ["sql", "database", "query", "data agent", "SELECT", "postgres", "qdrant"]),
    (IssueKind.RESEARCH,         ["research", "investigate", "explore", "survey", "find out"]),
    (IssueKind.BUG,              ["bug", "error", "crash", "exception", "fail", "broken", "fix", "regression"]),
    (IssueKind.ENHANCEMENT,      ["feature", "add", "improve", "enhance", "refactor", "performance", "support"]),
    (IssueKind.QUESTION,         ["how", "why", "what", "clarif", "explain", "understand"]),
]


class ClassifiedIssue(BaseModel):
    """Result of classifying a GitHub issue."""

    issue_number: int
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    kind: IssueKind
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_approval: bool
    rationale: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.kind not in (IssueKind.QUESTION, IssueKind.UNKNOWN)


class IssueClassifier:
    """
    Deterministic keyword-based issue classifier.

    Checks GitHub labels first (highest precedence),
    then title + body keyword matches.
    """

    def classify(self, issue: dict[str, Any]) -> ClassifiedIssue:
        number = issue.get("number", 0)
        title = issue.get("title", "")
        body = issue.get("body", "") or ""
        labels = [
            (l.get("name") if isinstance(l, dict) else str(l))
            for l in issue.get("labels", [])
        ]

        kind, confidence, rationale = self._classify_text(title, body, labels)
        requires_human = kind in _HUMAN_REQUIRED_KINDS

        return ClassifiedIssue(
            issue_number=number,
            title=title,
            body=body,
            labels=labels,
            kind=kind,
            confidence=confidence,
            requires_human_approval=requires_human,
            rationale=rationale,
        )

    def _classify_text(
        self, title: str, body: str, labels: list[str]
    ) -> tuple[IssueKind, float, str]:
        text = f"{title}\n{body}".lower()
        label_set = {l.lower() for l in labels}

        # Label override
        if "security" in label_set:
            return IssueKind.SECURITY, 0.95, "label:security"
        if "self-improvement" in label_set or "self_improvement" in label_set:
            return IssueKind.SELF_IMPROVEMENT, 0.95, "label:self-improvement"
        if "bug" in label_set:
            return IssueKind.BUG, 0.90, "label:bug"
        if "enhancement" in label_set:
            return IssueKind.ENHANCEMENT, 0.90, "label:enhancement"
        if "research" in label_set:
            return IssueKind.RESEARCH, 0.85, "label:research"
        if "data" in label_set:
            return IssueKind.DATA, 0.85, "label:data"

        # Keyword matching
        for kind, keywords in _KIND_PATTERNS:
            for kw in keywords:
                if kw.lower() in text:
                    return kind, 0.70, f"keyword:{kw}"

        return IssueKind.UNKNOWN, 0.3, "no match"
