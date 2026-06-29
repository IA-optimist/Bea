from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_github.issues import ClassifiedIssue, IssueKind
from agent_github.mission_loop import GitHubMissionLoop
from agent_memory.codebase import CodebaseMemoryService
from agent_memory.models import MemoryType, StructuredMemory
from agent_memory.store import AgentMemoryStore
from agent_runtime.actions import ActionRequest, ActionType
from agent_runtime.executor import ACIExecutor
from agent_runtime.policy import CommandPolicy, RiskLevel
from agent_runtime.registry import get_default_registry
from agent_workflows.review_gate import FinalReviewVerdict, ReviewGate


def _policy(tmp_path: Path) -> CommandPolicy:
    return CommandPolicy(
        allowed_actions=set(ActionType),
        allowed_paths=[str(tmp_path)],
        allowed_realms={"code"},
        require_approval_above_risk=RiskLevel.CRITICAL,
    )


def test_action_request_requires_identity_fields() -> None:
    with pytest.raises(Exception):
        ActionRequest(mission_id="", agent_id="agent", action_type=ActionType.READ_FILE, realm="code")
    with pytest.raises(Exception):
        ActionRequest(mission_id="mission", agent_id="", action_type=ActionType.READ_FILE, realm="code")
    with pytest.raises(Exception):
        ActionRequest(mission_id="mission", agent_id="agent", action_type=ActionType.READ_FILE, realm="")


def test_action_outside_realm_is_blocked(tmp_path: Path) -> None:
    req = ActionRequest(
        mission_id="m1",
        agent_id="a1",
        action_type=ActionType.READ_FILE,
        realm="research",
        payload={"path": str(tmp_path / "x.py")},
    )
    executor = ACIExecutor(get_default_registry(), agent_capabilities={"read"})

    result = executor.execute(req, _policy(tmp_path))

    assert result.status == "blocked"
    assert "realm" in (result.error or "").lower()


def test_executor_audit_redacts_payload_secrets(tmp_path: Path) -> None:
    audit: list[dict] = []
    target = tmp_path / "report.txt"
    req = ActionRequest(
        mission_id="m1",
        agent_id="a1",
        action_type=ActionType.WRITE_REPORT,
        realm="code",
        payload={"path": str(target), "content": "token=sk-or-v1-secretsecretsecret"},
    )
    executor = ACIExecutor(
        get_default_registry(),
        agent_capabilities={"write"},
        audit_sink=audit,
    )

    result = executor.execute(req, _policy(tmp_path))

    assert audit
    assert result.audit_ref == "audit:0"
    assert audit[-1]["allowed"] is True
    assert "sk-or-v1" not in audit[-1]["payload_summary"]
    assert "[REDACTED]" in audit[-1]["payload_summary"]


def test_apply_patch_blocks_traversal_and_empty_patch(tmp_path: Path) -> None:
    executor = ACIExecutor(get_default_registry(), agent_capabilities={"write", "sandbox"})
    policy = _policy(tmp_path)

    traversal = ActionRequest(
        mission_id="m1",
        agent_id="a1",
        action_type=ActionType.APPLY_PATCH,
        realm="code",
        payload={"target": "../outside.py", "patch": "*** Begin Patch\n*** End Patch\n"},
    )
    empty = traversal.model_copy(update={"payload": {"target": str(tmp_path / "x.py"), "patch": ""}})

    assert executor.execute(traversal, policy).status == "blocked"
    assert executor.execute(empty, policy).status == "blocked"


def test_apply_patch_updates_file_and_returns_diff_summary(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Update File: mod.py
@@
-def f():
-    return 1
+def f():
+    return 2
*** End Patch
"""
    executor = ACIExecutor(get_default_registry(), agent_capabilities={"write", "sandbox"})
    req = ActionRequest(
        mission_id="m1",
        agent_id="a1",
        action_type=ActionType.APPLY_PATCH,
        realm="code",
        payload={"target": str(target), "patch": patch},
    )

    result = executor.execute(req, _policy(tmp_path))

    assert result.status == "success"
    assert "return 2" in target.read_text(encoding="utf-8")
    assert result.output["diff_summary"]["changed_files"] == [str(target)]


def test_memory_delete_expiry_and_secret_redaction() -> None:
    store = AgentMemoryStore()
    expired = StructuredMemory(
        memory_type=MemoryType.FACT,
        realm="code",
        source="test",
        confidence=0.9,
        content="This memory is expired and should not be recalled.",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    secret = StructuredMemory(
        memory_type=MemoryType.FACT,
        realm="code",
        source="test",
        confidence=0.9,
        sensitive=True,
        content="API token sk-or-v1-secretsecretsecret should be redacted.",
    )

    expired_id = store.add(expired)
    secret_id = store.add(secret)

    recalled = store.recall(realm="code")
    assert expired_id not in {m.memory_id for m in recalled}
    assert "sk-or-v1" not in store.get(secret_id).content
    assert store.delete(secret_id)
    assert store.get(secret_id) is None


def test_codebase_memory_v1_api(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    tests = tmp_path / "tests"
    pkg.mkdir()
    tests.mkdir()
    (pkg / "service.py").write_text("import os\n\ndef target_func():\n    return os.getcwd()\n", encoding="utf-8")
    (tests / "test_service.py").write_text("from pkg.service import target_func\n\ndef test_target_func():\n    assert target_func()\n", encoding="utf-8")
    svc = CodebaseMemoryService(tmp_path)

    snapshot = svc.index_repo(force=True)

    assert snapshot.file_count == 2
    assert svc.find_symbol("target_func")
    assert svc.search_code("os.getcwd")
    assert "os" in svc.imports_for_file("pkg/service.py")
    assert svc.symbols_for_file("pkg/service.py")
    assert "tests/test_service.py" in svc.likely_tests_for_change("pkg/service.py")
    assert "tests/test_service.py" in svc.impacted_files("pkg/service.py")


def test_review_gate_blocks_sensitive_change_without_security_agent() -> None:
    verdict = FinalReviewVerdict(
        verdict="approve",
        severity="P3",
        confidence=0.9,
        reason="Looks fine",
        required_changes=[],
        tests_run=["pytest"],
        tests_missing=[],
        security_findings=[],
        files_reviewed=["core/tool_executor.py"],
        risk_areas=["tools"],
        human_summary="Sensitive tool path changed.",
    )

    gated = ReviewGate().evaluate(verdict, mission_type="code", reviewers=["ReviewerAgent"])

    assert gated.verdict == "block"
    assert gated.severity == "P1"
    assert "SecurityAgent" in gated.reason


def test_review_gate_needs_changes_when_code_tests_missing() -> None:
    verdict = FinalReviewVerdict(
        verdict="approve",
        severity="P3",
        confidence=0.9,
        reason="No issues found",
        required_changes=[],
        tests_run=[],
        tests_missing=["pytest"],
        security_findings=[],
        files_reviewed=["agent_runtime/actions.py"],
        risk_areas=[],
        human_summary="Missing tests.",
    )

    gated = ReviewGate().evaluate(verdict, mission_type="code", reviewers=["ReviewerAgent", "SecurityAgent"])

    assert gated.verdict == "needs_changes"


def test_github_pr_body_requires_tests_and_verdict() -> None:
    loop = GitHubMissionLoop()
    issue = ClassifiedIssue(
        issue_number=77,
        title="Fix runtime issue",
        kind=IssueKind.BUG,
        confidence=0.9,
        is_actionable=True,
        requires_human_approval=False,
        labels=["bea:fix"],
    )
    plan = loop.plan(issue)
    verdict = FinalReviewVerdict(
        verdict="approve",
        severity="P3",
        confidence=0.9,
        reason="Ready for draft PR",
        required_changes=[],
        tests_run=["pytest tests/agent_runtime/test_agentic_hardening.py -q"],
        tests_missing=[],
        security_findings=[],
        files_reviewed=["agent_runtime/actions.py"],
        risk_areas=[],
        human_summary="Draft PR only.",
    )

    body = loop.build_pr_body(plan, tests_run=verdict.tests_run, tests_missing=[], review_verdict=verdict)

    assert "## Mission" in body
    assert "## Tests run" in body
    assert "## Reviewer verdict" in body
    assert "Auto-merge: disabled" in body
