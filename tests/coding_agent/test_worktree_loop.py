from __future__ import annotations

import json
from pathlib import Path

from core.coding_agent.worktree_loop import (
    CodingAgentRunner,
    CommandExecution,
    MissionInput,
    select_targeted_tests,
)


class FakeCommands:
    def __init__(self, *, git_available: bool = True, tests_pass: bool = True, lint_pass: bool = True) -> None:
        self.git_available = git_available
        self.tests_pass = tests_pass
        self.lint_pass = lint_pass
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path, timeout_s: int) -> CommandExecution:
        self.calls.append((command, cwd))
        if command[:2] == ["git", "rev-parse"]:
            return CommandExecution(0 if self.git_available else 1, "", "not a repo")
        if command[:2] == ["git", "worktree"] and "add" in command:
            Path(command[-2]).mkdir(parents=True, exist_ok=True)
            return CommandExecution(0, "created", "")
        if command[:2] == ["git", "status"]:
            return CommandExecution(0, " M core/coding_agent/example.py\n", "")
        if command[:2] == ["git", "apply"]:
            return CommandExecution(0, "applied", "")
        if "ruff" in command:
            return CommandExecution(0 if self.lint_pass else 1, "lint", "")
        if "pytest" in command:
            return CommandExecution(0 if self.tests_pass else 1, "tests", "")
        return CommandExecution(0, "", "")


def test_select_targeted_tests_prefers_requested_tests(tmp_path: Path) -> None:
    mission = MissionInput(
        title="Fix parser",
        description="Run exact tests",
        requested_tests=["tests/unit/test_parser.py"],
    )

    assert select_targeted_tests(mission, ["core/coding_agent/parser.py"], tmp_path) == ["tests/unit/test_parser.py"]


def test_select_targeted_tests_uses_file_heuristics(tmp_path: Path) -> None:
    (tmp_path / "tests" / "self_improvement").mkdir(parents=True)
    mission = MissionInput(title="Patch SI", description="Target self improvement")

    tests = select_targeted_tests(mission, ["core/self_improvement/git_agent.py"], tmp_path)

    assert tests == ["tests/self_improvement"]


def test_select_targeted_tests_uses_coding_agent_heuristics(tmp_path: Path) -> None:
    (tmp_path / "tests" / "coding_agent").mkdir(parents=True)
    mission = MissionInput(title="Patch coder", description="Target coding agent")

    tests = select_targeted_tests(mission, ["core/coding_agent/worktree_loop.py"], tmp_path)

    assert tests == ["tests/coding_agent"]


def test_select_targeted_tests_deduplicates_requested_tests(tmp_path: Path) -> None:
    mission = MissionInput(
        title="Normalize tests",
        description="Requested tests may arrive twice",
        requested_tests=["tests/unit/test_parser.py", ".\\tests\\unit\\test_parser.py"],
    )

    assert select_targeted_tests(mission, ["README.md"], tmp_path) == ["tests/unit/test_parser.py"]


def test_select_targeted_tests_falls_back_to_safe_minimal(tmp_path: Path) -> None:
    mission = MissionInput(title="Docs", description="No direct tests")

    assert select_targeted_tests(mission, ["README.md"], tmp_path) == ["tests/test_sprint3_agent_coder.py"]


def test_coding_mission_creates_worktree_and_does_not_modify_main(tmp_path: Path) -> None:
    fake = FakeCommands()
    runner = CodingAgentRunner(repo_root=tmp_path, command_runner=fake)
    mission = MissionInput(
        title="Small coding patch",
        description="Patch a safe file",
        target_files=["core/coding_agent/example.py"],
        requested_tests=["tests/test_sprint3_agent_coder.py"],
    )

    run = runner.run(mission, unified_diff="diff --git a/core/coding_agent/example.py b/core/coding_agent/example.py\n")

    assert run.status == "READY_FOR_REVIEW"
    assert run.worktree_path
    assert Path(run.worktree_path).exists()
    assert run.branch_name.startswith("codex/agent-")
    assert any(call[0][:3] == ["git", "worktree", "add"] for call in fake.calls)
    assert any(call[0][:3] == ["git", "apply", "--ignore-space-change"] for call in fake.calls)
    assert all(call[1] != tmp_path for call in fake.calls if "pytest" in call[0] or "ruff" in call[0])


def test_git_unavailable_fails_without_ready_for_review(tmp_path: Path) -> None:
    runner = CodingAgentRunner(repo_root=tmp_path, command_runner=FakeCommands(git_available=False))
    mission = MissionInput(title="No git", description="Should fail", target_files=["core/coding_agent/example.py"])

    run = runner.run(mission)

    assert run.status == "FAILED"
    assert run.status != "READY_FOR_REVIEW"
    assert run.security_gate_status == "FAILED"


def test_protected_file_is_rejected(tmp_path: Path) -> None:
    runner = CodingAgentRunner(repo_root=tmp_path, command_runner=FakeCommands())
    mission = MissionInput(title="Protected", description="Bad target", target_files=["api/auth.py"])

    run = runner.run(mission)

    assert run.status == "REJECTED"
    assert run.security_gate_status == "REJECTED"
    assert run.status != "READY_FOR_REVIEW"


def test_reports_json_and_markdown_are_generated(tmp_path: Path) -> None:
    runner = CodingAgentRunner(repo_root=tmp_path, command_runner=FakeCommands())
    mission = MissionInput(
        title="Report mission",
        description="Generate reports",
        target_files=["core/coding_agent/example.py"],
        requested_tests=["tests/test_sprint3_agent_coder.py"],
    )

    run = runner.run(mission)

    report_path = Path(run.report_path)
    markdown_path = report_path.with_suffix(".md")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert data["run_id"] == run.run_id
    assert data["decision"] == "READY_FOR_REVIEW"
    assert "Rollback instructions" in markdown
    assert "Human next actions" in markdown


def test_reports_include_mission_learning_fields(tmp_path: Path) -> None:
    runner = CodingAgentRunner(repo_root=tmp_path, command_runner=FakeCommands())
    mission = MissionInput(
        title="Learning mission",
        description="Fields for mission ingestion",
        target_files=["core/coding_agent/example.py"],
        requested_tests=["tests/test_sprint3_agent_coder.py"],
    )

    run = runner.run(mission)
    data = json.loads(Path(run.report_path).read_text(encoding="utf-8"))

    assert data["mission_id"] == run.run_id
    assert data["goal"] == mission.description
    assert data["mission_type"] == "coding_task"
    assert data["success"] is True
    assert data["agents_used"] == []
    assert data["tools_used"] == ["git", "ruff", "pytest"]
    assert data["plan_steps"] >= 2
    assert data["complexity"] == "low"
    assert data["error_category"] == ""
    assert data["duration_s"] >= 0.0
    assert data["report_path"] == run.report_path


def test_failed_tests_need_fix_and_never_promote(tmp_path: Path) -> None:
    runner = CodingAgentRunner(repo_root=tmp_path, command_runner=FakeCommands(tests_pass=False))
    mission = MissionInput(
        title="Broken patch",
        description="Tests fail",
        target_files=["core/coding_agent/example.py"],
        requested_tests=["tests/test_sprint3_agent_coder.py"],
    )

    run = runner.run(mission)

    assert run.status == "NEEDS_FIX"
    assert run.tests_passed is False
    assert run.status != "PROMOTE"
