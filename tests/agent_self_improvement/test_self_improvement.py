"""
tests/agent_self_improvement/test_self_improvement.py — Self-improvement tests.
"""
from __future__ import annotations

import pytest

from agent_self_improvement.skill_library import Skill, SkillLibrary, SkillStatus
from agent_self_improvement.improvement_issues import (
    ImprovementIssue,
    ImprovementIssueFactory,
    ImprovementKind,
)
from agent_self_improvement.reflection import ReflectionAgent
from agent_memory.store import AgentMemoryStore
from agent_memory.models import MemoryType, StructuredMemory


# ── Helpers ───────────────────────────────────────────────────────────────────

def _skill(**kwargs) -> Skill:
    defaults = dict(
        name="my_test_skill",
        description="A skill that does something useful for testing purposes.",
        code="def my_test_skill():\n    return 42",
        test_code="def test_my_test_skill():\n    assert my_test_skill() == 42",
        source_ref="issue #42 / PR #43",
        realm="code",
        created_by="test",
    )
    defaults.update(kwargs)
    return Skill(**defaults)


def _failure_memory(content: str) -> StructuredMemory:
    return StructuredMemory(
        memory_type=MemoryType.LESSON,
        realm="code",
        source="test-agent",
        confidence=0.8,
        content=content,
        tags=["failure", "lesson"],
    )


# ── Skill tests ───────────────────────────────────────────────────────────────

class TestSkill:
    def test_valid_skill_created(self):
        s = _skill()
        assert s.name == "my_test_skill"
        assert s.status == SkillStatus.DRAFT

    def test_missing_test_code_rejected(self):
        with pytest.raises(Exception, match="test_code"):
            _skill(test_code="")

    def test_missing_source_ref_rejected(self):
        with pytest.raises(Exception, match="source_ref"):
            _skill(source_ref="")

    def test_human_verified_default_false(self):
        s = _skill()
        assert not s.human_verified


class TestSkillLibrary:
    def setup_method(self):
        self.lib = SkillLibrary()

    def test_register_and_get(self):
        s = _skill()
        sid = self.lib.register(s)
        retrieved = self.lib.get("my_test_skill")
        assert retrieved is not None
        assert retrieved.skill_id == sid

    def test_duplicate_name_rejected(self):
        self.lib.register(_skill())
        with pytest.raises(ValueError, match="already registered"):
            self.lib.register(_skill())

    def test_deprecate(self):
        self.lib.register(_skill())
        result = self.lib.deprecate("my_test_skill")
        assert result is True
        # Re-register after deprecate is allowed
        self.lib.register(_skill())

    def test_mark_used_increments(self):
        self.lib.register(_skill(status=SkillStatus.TESTED))
        self.lib.mark_used("my_test_skill")
        s = self.lib.get("my_test_skill")
        assert s.use_count == 1

    def test_mark_used_3_times_verifies(self):
        self.lib.register(_skill(status=SkillStatus.TESTED))
        for _ in range(3):
            self.lib.mark_used("my_test_skill")
        s = self.lib.get("my_test_skill")
        assert s.status == SkillStatus.VERIFIED

    def test_human_verify(self):
        self.lib.register(_skill())
        self.lib.human_verify("my_test_skill")
        s = self.lib.get("my_test_skill")
        assert s.human_verified is True

    def test_list_by_realm(self):
        self.lib.register(_skill(realm="code"))
        self.lib.register(_skill(name="research_skill_x",
                                 description="A research skill with enough description length here.",
                                 realm="research"))
        code_skills = self.lib.list_by_realm("code")
        assert len(code_skills) == 1

    def test_stats(self):
        self.lib.register(_skill())
        stats = self.lib.stats()
        assert stats["total"] == 1
        assert stats["human_verified"] == 0


# ── ImprovementIssue tests ────────────────────────────────────────────────────

class TestImprovementIssue:
    def test_security_always_human(self):
        issue = ImprovementIssue(
            kind=ImprovementKind.SECURITY,
            title="Security improvement needed here",
            description="A security improvement that needs careful human review and approval.",
            motivation="This security issue was detected during reflection analysis.",
            detected_by="reflection_agent",
            human_approval_required=True,
            creates_direct_patch=False,
        )
        assert issue.human_approval_required

    def test_security_without_human_rejected(self):
        with pytest.raises(Exception, match="human_approval_required"):
            ImprovementIssue(
                kind=ImprovementKind.SECURITY,
                title="Security improvement here",
                description="Security improvement with sufficient description length.",
                motivation="Security improvement motivation with sufficient length.",
                detected_by="agent",
                human_approval_required=False,   # FORBIDDEN for SECURITY
                creates_direct_patch=False,
            )

    def test_creates_direct_patch_always_false(self):
        with pytest.raises(Exception, match="creates_direct_patch"):
            ImprovementIssue(
                kind=ImprovementKind.BUG_FIX,
                title="Bug fix improvement proposal",
                description="Bug fix improvement with sufficient description for validation.",
                motivation="Bug fix motivation with sufficient length for validation.",
                detected_by="agent",
                human_approval_required=True,
                creates_direct_patch=True,   # ALWAYS FORBIDDEN
            )

    def test_to_github_body_contains_human_gate(self):
        issue = ImprovementIssue(
            kind=ImprovementKind.BUG_FIX,
            title="Bug fix improvement here",
            description="Bug fix description with sufficient length for validation.",
            motivation="Motivation for this bug fix with sufficient length for validation.",
            detected_by="reflection_agent",
            human_approval_required=True,
            creates_direct_patch=False,
        )
        body = issue.to_github_body()
        assert "Human approval required" in body or "human" in body.lower()
        assert "no code has been changed" in body.lower() or "no direct patch" in body.lower()

    def test_factory_from_failure(self):
        factory = ImprovementIssueFactory()
        issue = factory.from_failure(
            what_failed="apply_patch timed out",
            why="sandbox timeout too short",
            kind=ImprovementKind.BUG_FIX,
            detected_by="tester",
        )
        assert not issue.creates_direct_patch
        assert issue.human_approval_required

    def test_factory_from_lesson(self):
        factory = ImprovementIssueFactory()
        issue = factory.from_lesson(
            lesson="using pytest --tb=short improves signal-to-noise ratio",
            kind=ImprovementKind.TEST,
            detected_by="tester",
            proposed_files=["tests/conftest.py"],
        )
        assert not issue.creates_direct_patch
        assert any("conftest.py" in f for f in issue.proposed_files)


# ── ReflectionAgent tests ─────────────────────────────────────────────────────

class TestReflectionAgent:
    def setup_method(self):
        self.store = AgentMemoryStore()
        self.agent = ReflectionAgent(self.store)

    def test_reflect_no_failures_returns_empty(self):
        issues = self.agent.reflect()
        assert issues == []

    def test_reflect_below_threshold_no_issues(self):
        # Add 2 identical failures (threshold is 3)
        for _ in range(2):
            self.store.add(_failure_memory("What failed: apply_patch timed out in sandbox"))
        issues = self.agent.reflect()
        assert issues == []

    def test_reflect_at_threshold_creates_issue(self):
        # Add 3 identical failures (exactly at threshold)
        for _ in range(3):
            self.store.add(_failure_memory("What failed: apply_patch timed out in sandbox"))
        issues = self.agent.reflect()
        assert len(issues) == 1
        assert not issues[0].creates_direct_patch
        assert issues[0].human_approval_required

    def test_reflect_respects_max_per_run(self):
        # Many different failure categories → only 1 issue (MAX_PER_RUN=1)
        categories = [
            "What failed: test_run_failed in sandbox",
            "What failed: security_scan raised exception",
            "What failed: planning failed with timeout",
        ]
        for cat in categories:
            for _ in range(3):
                self.store.add(_failure_memory(cat))
        issues = self.agent.reflect()
        assert len(issues) <= 1  # gate caps at 1 per run

    def test_reflect_issues_never_direct_patch(self):
        for _ in range(3):
            self.store.add(_failure_memory("What failed: security auth bypass detected"))
        issues = self.agent.reflect()
        for issue in issues:
            assert not issue.creates_direct_patch
