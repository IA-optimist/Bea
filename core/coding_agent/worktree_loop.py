"""Minimal worktree-first coding-agent loop.

This module is intentionally deterministic: it does not generate code by
itself. It receives a mission and an optional patch, creates an isolated git
worktree, applies the patch, runs targeted checks, and writes JSON/Markdown
reports for human review.
"""
from __future__ import annotations

import json
import re
import subprocess  # nosec B404
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from core.self_improvement.protected_paths import is_protected


RUN_STATUSES = frozenset({
    "PLANNED",
    "WORKTREE_CREATED",
    "PATCH_APPLIED",
    "TESTING",
    "NEEDS_FIX",
    "READY_FOR_REVIEW",
    "REJECTED",
    "FAILED",
    "ROLLED_BACK",
})

SAFE_MINIMAL_TESTS = ["tests/test_sprint3_agent_coder.py"]


@dataclass(frozen=True)
class CommandExecution:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


@dataclass
class MissionInput:
    title: str
    description: str
    target_files: list[str] = field(default_factory=list)
    risk_level: str = "low"
    requested_tests: list[str] = field(default_factory=list)


@dataclass
class CodingRun:
    run_id: str
    branch_name: str
    worktree_path: str
    status: str
    changed_files: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    tests_passed: bool = False
    lint_passed: bool = False
    security_gate_status: str = "PENDING"
    report_path: str = ""
    created_at: str = ""
    rollback_instructions: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    started_at_epoch: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


CommandRunner = Callable[[list[str], Path, int], CommandExecution]


def _default_command_runner(command: list[str], cwd: Path, timeout_s: int) -> CommandExecution:
    try:
        proc = subprocess.run(  # nosec B603
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return CommandExecution(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired as exc:
        return CommandExecution(124, exc.stdout or "", exc.stderr or "command timed out")
    except Exception as exc:
        return CommandExecution(1, "", str(exc))


def _normalize(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _existing_or_default(repo_root: Path, candidates: list[str], default: list[str]) -> list[str]:
    existing = [candidate for candidate in candidates if (repo_root / candidate).exists()]
    return existing or default


def _unique_normalized(items: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = _normalize(item)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def select_targeted_tests(mission: MissionInput, changed_files: list[str], repo_root: Path) -> list[str]:
    """Select a small deterministic test set for the mission."""
    if mission.requested_tests:
        return _unique_normalized(mission.requested_tests)

    files = [_normalize(path) for path in changed_files or mission.target_files]
    candidates: list[str] = []

    if any(path.startswith("api/routes/") for path in files):
        candidates.append("tests/api")
    if any(path.startswith("core/coding_agent/") for path in files):
        candidates.append("tests/coding_agent")
    if any(path.startswith("core/self_improvement/") for path in files):
        candidates.append("tests/self_improvement")
    if any(path.startswith("core/memory/") for path in files):
        candidates.append("tests/memory")
    if any(path.startswith("scripts/") for path in files):
        candidates.append("tests/scripts")
    candidates.extend(path for path in files if path.startswith("tests/") and path.endswith(".py"))

    return _existing_or_default(repo_root, list(dict.fromkeys(candidates)), SAFE_MINIMAL_TESTS)


def _slug(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.lower()).strip("-")
    return safe[:48] or "mission"


def _parse_changed_files(status_output: str) -> list[str]:
    files: list[str] = []
    for line in status_output.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(_normalize(path))
    return list(dict.fromkeys(files))


def _mission_type(mission: MissionInput) -> str:
    return "coding_task" if mission.target_files or mission.requested_tests else "documentation_task"


def _complexity(mission: MissionInput, run: CodingRun) -> str:
    if mission.risk_level in {"high", "critical"}:
        return "high"
    if len(run.changed_files) >= 2 or len(run.tests_run) >= 2:
        return "medium"
    return "low"


def _error_category(run: CodingRun) -> str:
    if run.status == "READY_FOR_REVIEW":
        return ""
    if run.status == "REJECTED":
        return "security_gate"
    if run.status == "FAILED":
        return "tool_failure"
    if run.status == "NEEDS_FIX":
        return "quality_gate"
    return ""


class CodingAgentRunner:
    """Run a coding mission in an isolated git worktree."""

    def __init__(
        self,
        repo_root: Path,
        *,
        worktree_root: Path | None = None,
        reports_root: Path | None = None,
        command_runner: CommandRunner = _default_command_runner,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.worktree_root = (worktree_root or self.repo_root.parent / ".bea-coding-agent-worktrees").resolve()
        self.reports_root = (reports_root or self.repo_root / "workspace" / "coding_agent" / "runs").resolve()
        self.command_runner = command_runner

    def run(self, mission: MissionInput, *, unified_diff: str = "") -> CodingRun:
        run = self._new_run(mission)
        protected = [path for path in mission.target_files if is_protected(path)]
        if protected:
            run.status = "REJECTED"
            run.security_gate_status = "REJECTED"
            run.error = f"Protected file requested: {protected[0]}"
            self._write_reports(mission, run)
            return run

        git_ok = self.command_runner(["git", "rev-parse", "--is-inside-work-tree"], self.repo_root, 30)
        if not git_ok.ok:
            run.status = "FAILED"
            run.security_gate_status = "FAILED"
            run.error = git_ok.output or "GitAgent unavailable"
            self._write_reports(mission, run)
            return run

        self.worktree_root.mkdir(parents=True, exist_ok=True)
        worktree = self.worktree_root / run.branch_name.replace("/", "-")
        create = self.command_runner(
            ["git", "worktree", "add", "-b", run.branch_name, str(worktree), "HEAD"],
            self.repo_root,
            120,
        )
        if not create.ok:
            run.status = "FAILED"
            run.security_gate_status = "FAILED"
            run.error = create.output or "git worktree add failed"
            self._write_reports(mission, run)
            return run

        run.status = "WORKTREE_CREATED"
        run.worktree_path = str(worktree)
        run.rollback_instructions = (
            f"git worktree remove --force {worktree}\n"
            f"git branch -D {run.branch_name}"
        )

        if unified_diff.strip():
            patch_file = worktree / ".coding_agent.patch"
            patch_file.write_text(unified_diff, encoding="utf-8")
            applied = self.command_runner(["git", "apply", "--ignore-space-change", str(patch_file)], worktree, 60)
            patch_file.unlink(missing_ok=True)
            if not applied.ok:
                run.status = "FAILED"
                run.security_gate_status = "FAILED"
                run.error = applied.output or "git apply failed"
                self._write_reports(mission, run)
                return run
            run.status = "PATCH_APPLIED"

        status = self.command_runner(["git", "status", "--porcelain"], worktree, 30)
        run.changed_files = _parse_changed_files(status.stdout) or [_normalize(path) for path in mission.target_files]
        protected_changed = [path for path in run.changed_files if is_protected(path)]
        if protected_changed:
            run.status = "REJECTED"
            run.security_gate_status = "REJECTED"
            run.error = f"Protected file changed: {protected_changed[0]}"
            self._write_reports(mission, run)
            return run

        run.security_gate_status = "PASS"
        run.tests_run = select_targeted_tests(mission, run.changed_files, self.repo_root)
        run.status = "TESTING"

        lint = self.command_runner([sys.executable, "-m", "ruff", "check", "."], worktree, 120)
        run.lint_passed = lint.ok
        test_results = [
            self.command_runner([sys.executable, "-m", "pytest", test, "-q"], worktree, 180)
            for test in run.tests_run
        ]
        run.tests_passed = bool(test_results) and all(result.ok for result in test_results)

        if run.tests_passed and run.lint_passed:
            run.status = "READY_FOR_REVIEW"
        else:
            run.status = "NEEDS_FIX"
            failed = [result.output for result in [lint, *test_results] if not result.ok]
            run.error = "\n".join(output for output in failed if output)[:1000]

        self._write_reports(mission, run)
        return run

    def _new_run(self, mission: MissionInput) -> CodingRun:
        run_id = uuid.uuid4().hex[:12]
        branch_name = f"codex/agent-{_slug(mission.title)}-{run_id}"
        return CodingRun(
            run_id=run_id,
            branch_name=branch_name,
            worktree_path="",
            status="PLANNED",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            started_at_epoch=time.time(),
        )

    def _write_reports(self, mission: MissionInput, run: CodingRun) -> None:
        report_dir = self.reports_root / run.run_id
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "report.json"
        md_path = report_dir / "report.md"
        run.report_path = str(json_path)

        payload = {
            "mission_id": run.run_id,
            "goal": mission.description or mission.title,
            "mission_type": _mission_type(mission),
            "success": run.status == "READY_FOR_REVIEW",
            "agents_used": [],
            "tools_used": ["git", "ruff", "pytest"],
            "plan_steps": len(run.tests_run) + 2,
            "complexity": _complexity(mission, run),
            "error_category": _error_category(run),
            "duration_s": round(time.time() - run.started_at_epoch, 3),
            "mission": asdict(mission),
            "run_id": run.run_id,
            "branch_name": run.branch_name,
            "worktree_path": run.worktree_path,
            "status": run.status,
            "decision": run.status,
            "changed_files": run.changed_files,
            "tests_run": run.tests_run,
            "tests_passed": run.tests_passed,
            "lint_passed": run.lint_passed,
            "security_gate_status": run.security_gate_status,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "report_path": str(json_path),
            "rollback_instructions": run.rollback_instructions,
            "error": run.error,
            "human_next_actions": self._human_next_actions(run),
        }
        run.finished_at = payload["finished_at"]
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(self._render_markdown(mission, run, payload["human_next_actions"]), encoding="utf-8")

    @staticmethod
    def _human_next_actions(run: CodingRun) -> list[str]:
        if run.status == "READY_FOR_REVIEW":
            return ["Review the worktree diff.", "Open a PR manually if the patch is acceptable.", "Merge only after human approval."]
        if run.status == "NEEDS_FIX":
            return ["Inspect failing checks in the worktree.", "Fix the patch or roll back the worktree."]
        if run.status == "REJECTED":
            return ["Do not promote this patch.", "Review the security gate reason.", "Rollback the worktree if one was created."]
        return ["Inspect the error.", "Rollback any created worktree.", "Retry only after the tool failure is resolved."]

    @staticmethod
    def _render_markdown(mission: MissionInput, run: CodingRun, human_next_actions: list[str]) -> str:
        lines = [
            f"# Coding Agent Report: {mission.title}",
            "",
            f"- Run ID: `{run.run_id}`",
            f"- Status: `{run.status}`",
            f"- Branch: `{run.branch_name}`",
            f"- Worktree: `{run.worktree_path or '(not created)'}`",
            f"- Security gate: `{run.security_gate_status}`",
            f"- Tests passed: `{run.tests_passed}`",
            f"- Lint passed: `{run.lint_passed}`",
            "",
            "## Changed files",
            *(f"- `{path}`" for path in (run.changed_files or ["(none)"])),
            "",
            "## Tests run",
            *(f"- `{test}`" for test in (run.tests_run or ["(none)"])),
            "",
            "## Rollback instructions",
            "```powershell",
            run.rollback_instructions or "# No worktree was created.",
            "```",
            "",
            "## Human next actions",
            *(f"- {action}" for action in human_next_actions),
        ]
        if run.error:
            lines.extend(["", "## Error", "```", run.error, "```"])
        return "\n".join(lines) + "\n"
