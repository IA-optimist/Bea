"""
tests/agent_github/test_github_loop.py — GitHub Mission Loop tests.
"""
from __future__ import annotations

import pytest

from agent_github.labels import BEA_LABELS, LABEL_NAMES
from agent_github.issues import IssueClassifier, IssueKind, ClassifiedIssue
from agent_github.mission_loop import GitHubMissionLoop, MissionStatus


# ── Helpers ───────────────────────────────────────────────────────────────────

def _issue(number: int, title: str, body: str = "", labels: list[str] | None = None) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": lbl} for lbl in (labels or [])],
    }


# ── Label tests ───────────────────────────────────────────────────────────────

class TestBEALabels:
    def test_labels_non_empty(self):
        assert len(BEA_LABELS) > 0

    def test_severity_labels_present(self):
        names = {lbl.name for lbl in BEA_LABELS}
        assert {"P0", "P1", "P2", "P3"}.issubset(names)

    def test_agentic_label_present(self):
        assert "agentic" in LABEL_NAMES

    def test_human_review_label_present(self):
        assert "human-review-required" in LABEL_NAMES

    def test_all_colors_valid_hex(self):
        import re
        for label in BEA_LABELS:
            assert re.fullmatch(r"[0-9a-fA-F]{6}", label.color), (
                f"Label '{label.name}' has invalid color '{label.color}'"
            )


# ── IssueClassifier tests ─────────────────────────────────────────────────────

class TestIssueClassifier:
    def setup_method(self):
        self.clf = IssueClassifier()

    def test_classifies_bug_by_label(self):
        r = self.clf.classify(_issue(1, "Something broken", labels=["bug"]))
        assert r.kind == IssueKind.BUG
        assert r.confidence >= 0.8

    def test_classifies_security_by_label(self):
        r = self.clf.classify(_issue(2, "XSS in endpoint", labels=["security"]))
        assert r.kind == IssueKind.SECURITY
        assert r.requires_human_approval

    def test_classifies_self_improvement_by_label(self):
        r = self.clf.classify(_issue(3, "Bea should improve its prompts", labels=["self-improvement"]))
        assert r.kind == IssueKind.SELF_IMPROVEMENT
        assert r.requires_human_approval

    def test_classifies_bug_by_keyword(self):
        r = self.clf.classify(_issue(4, "Exception thrown on startup — fix needed"))
        assert r.kind == IssueKind.BUG

    def test_classifies_enhancement_by_keyword(self):
        r = self.clf.classify(_issue(5, "Add support for multi-tenancy"))
        assert r.kind == IssueKind.ENHANCEMENT

    def test_classifies_security_by_keyword(self):
        r = self.clf.classify(_issue(6, "SQL injection in search endpoint"))
        assert r.kind == IssueKind.SECURITY

    def test_classifies_data_by_keyword(self):
        r = self.clf.classify(_issue(7, "Data agent SQL query returns wrong results"))
        assert r.kind == IssueKind.DATA

    def test_unknown_issue(self):
        r = self.clf.classify(_issue(8, "Lorem ipsum xyz"))
        assert r.kind == IssueKind.UNKNOWN

    def test_question_not_actionable(self):
        r = self.clf.classify(_issue(9, "How does the mission loop work?"))
        assert r.kind == IssueKind.QUESTION
        assert not r.is_actionable

    def test_label_overrides_keyword(self):
        # Title says "bug" but label says "enhancement" — label wins
        r = self.clf.classify(_issue(10, "Bug in the feature", labels=["enhancement"]))
        assert r.kind == IssueKind.ENHANCEMENT


# ── GitHubMissionLoop tests ───────────────────────────────────────────────────

class TestGitHubMissionLoop:
    def setup_method(self):
        self.clf = IssueClassifier()
        self.loop = GitHubMissionLoop()

    def test_plan_bug_issue(self):
        classified = self.clf.classify(_issue(10, "Crash in the parser module", labels=["bug"]))
        plan = self.loop.plan(classified)
        assert plan.issue_number == 10
        assert plan.branch_name.startswith("bea/issue-10/")
        assert plan.status == MissionStatus.PLANNING
        assert not plan.requires_human_approval
        # Regression test step should be mentioned for bugs
        steps_text = "\n".join(plan.steps)
        assert "regression" in steps_text.lower()

    def test_plan_security_requires_human(self):
        classified = self.clf.classify(_issue(11, "XSS vulnerability in cockpit", labels=["security"]))
        plan = self.loop.plan(classified)
        assert plan.requires_human_approval
        assert plan.status == MissionStatus.HUMAN_REVIEW

    def test_plan_self_improvement_requires_human(self):
        classified = self.clf.classify(_issue(12, "Bea self-improvement needed", labels=["self-improvement"]))
        plan = self.loop.plan(classified)
        assert plan.requires_human_approval
        assert plan.status == MissionStatus.HUMAN_REVIEW

    def test_plan_unknown_is_blocked(self):
        classified = self.clf.classify(_issue(13, "Random question xyz"))
        # Override to UNKNOWN for determinism
        classified = classified.model_copy(update={"kind": IssueKind.UNKNOWN})
        plan = self.loop.plan(classified)
        assert plan.status == MissionStatus.BLOCKED

    def test_pr_draft_created_never_merges(self):
        classified = self.clf.classify(_issue(20, "Add pagination to API", labels=["enhancement"]))
        self.loop.plan(classified)
        updated = self.loop.mark_pr_draft_created(20, "https://github.com/test/repo/pull/999")
        assert updated.status == MissionStatus.PR_DRAFT_CREATED
        assert updated.pr_draft is True  # never auto-merge
        assert updated.pr_url is not None

    def test_pr_draft_unknown_issue_raises(self):
        with pytest.raises(KeyError):
            self.loop.mark_pr_draft_created(9999, "https://example.com/pr/1")

    def test_events_logged(self):
        classified = self.clf.classify(_issue(30, "Fix crash", labels=["bug"]))
        self.loop.plan(classified)
        events = self.loop.events_for(30)
        assert len(events) >= 1
        assert events[0].issue_number == 30

    def test_branch_name_format(self):
        classified = self.clf.classify(_issue(42, "Security issue", labels=["security"]))
        plan = self.loop.plan(classified)
        assert plan.branch_name == "bea/issue-42/security"

    def test_enhancement_has_tdd_step(self):
        classified = self.clf.classify(_issue(50, "Add rate limit feature", labels=["enhancement"]))
        plan = self.loop.plan(classified)
        steps_text = "\n".join(plan.steps)
        assert "TDD" in steps_text or "failing tests" in steps_text.lower()
