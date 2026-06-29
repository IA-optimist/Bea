from __future__ import annotations

from pathlib import Path

from agent_github.issues import ClassifiedIssue, IssueKind
from agent_github.mission_loop import GitHubMissionLoop
from agent_memory.learning import learn_from_failure
from agent_memory.models import MemoryType
from agent_memory.store import AgentMemoryStore
from agent_runtime.actions import ActionRequest, ActionType
from agent_runtime.executor import ACIExecutor
from agent_runtime.policy import CommandPolicy, RiskLevel
from agent_runtime.registry import get_default_registry
from agent_self_improvement.reflection import ReflectionAgent
from agent_workflows.review_gate import FinalReviewVerdict, ReviewGate


def test_code_mission_happy_path_reaches_draft_pr(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("def answer():\n    return 1\n", encoding="utf-8")

    policy = CommandPolicy(
        allowed_actions={ActionType.APPLY_PATCH},
        allowed_realms={"code"},
        allowed_paths={str(tmp_path)},
        require_approval_above_risk=RiskLevel.HIGH,
    )
    executor = ACIExecutor(
        registry=get_default_registry(),
        agent_capabilities={"write", "sandbox"},
        audit_sink=[],
    )
    request = ActionRequest(
        mission_id="mission-1",
        agent_id="coder",
        action_type=ActionType.APPLY_PATCH,
        capability="code.patch",
        realm="code",
        risk=RiskLevel.MEDIUM,
        target_path=str(target),
        payload={
            "target": str(target),
            "patch": (
                "*** Begin Patch\n"
                "*** Update File: module.py\n"
                "@@\n"
                "-def answer():\n"
                "-    return 1\n"
                "+def answer():\n"
                "+    return 42\n"
                "*** End Patch\n"
            ),
        },
    )

    action_result = executor.execute(request, policy)
    assert action_result.status == "success"
    assert action_result.output["diff_summary"]["changed_files"] == [str(target)]

    review = ReviewGate().evaluate(
        FinalReviewVerdict(
            verdict="approve",
            severity="P3",
            confidence=0.92,
            reason="Regression test passed.",
            tests_run=["pytest tests/test_module.py -q"],
            files_reviewed=["module.py"],
            human_summary="Simple code mission approved.",
        ),
        mission_type="code",
        reviewers=["ReviewerAgent"],
    )
    assert review.verdict == "approve"

    loop = GitHubMissionLoop()
    plan = loop.plan(
        ClassifiedIssue(
            issue_number=42,
            title="Fix answer bug",
            body="Return the expected answer.",
            labels=["bug"],
            kind=IssueKind.BUG,
            confidence=0.9,
            requires_human_approval=False,
        )
    )
    body = loop.build_pr_body(
        plan,
        tests_run=review.tests_run,
        tests_missing=review.tests_missing,
        review_verdict=review,
        changes=["Updated module.py through ACI apply_patch."],
        risks=review.risk_areas,
        artifacts=["runtime audit event emitted"],
    )
    assert plan.pr_draft is True
    assert "Auto-merge: disabled" in body
    assert "## Reviewer verdict" in body


def test_sensitive_code_mission_blocks_without_security_agent() -> None:
    review = ReviewGate().evaluate(
        FinalReviewVerdict(
            verdict="approve",
            severity="P3",
            confidence=0.9,
            reason="Reviewer missed the sensitive auth path.",
            tests_run=["pytest tests/test_auth.py -q"],
            files_reviewed=["api/auth.py"],
            human_summary="Auth change reviewed without SecurityAgent.",
        ),
        mission_type="code",
        reviewers=["ReviewerAgent"],
    )

    assert review.verdict == "block"
    assert review.severity == "P1"
    assert any("SecurityAgent" in item for item in review.required_changes)


def test_learning_loop_creates_memory_and_issue_without_direct_patch() -> None:
    store = AgentMemoryStore()
    for _ in range(3):
        learn_from_failure(
            store,
            agent_id="coder",
            mission_id="mission-learning",
            what_failed="tests missing for sandbox policy",
            why_it_failed="review gate did not require security tests",
            how_to_avoid="require SecurityAgent for sandbox or tool changes",
            confidence=0.8,
            realm="code",
        )

    lessons = store.recall(memory_type=MemoryType.LESSON, realm="code", tags=["failure"])
    assert len(lessons) == 3

    issues = ReflectionAgent(store).reflect(agent_id="reflection-test")
    assert len(issues) == 1
    assert issues[0].creates_direct_patch is False
    assert issues[0].human_approval_required is True
    assert "Self-Improvement Proposal" in issues[0].to_github_body()
