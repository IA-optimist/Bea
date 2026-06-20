# ruff: noqa: T201
"""End-to-end Sprint 3 gate for coding-agent work.

Creates an isolated git worktree, applies a deterministic sample patch, runs the
local test/lint loop, prints a PR-ready body, and rolls back the worktree.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.coding_agent.failure_memory import FailureMemory
from core.coding_agent.repo_map import build_repo_map
from core.coding_agent.swe_lite import run_swe_lite_v1

DEFAULT_BASE_BRANCH = os.getenv("SPRINT3_BASE_BRANCH", "main")


@dataclass(frozen=True)
class GateResult:
    ok: bool
    task_id: str
    issue_title: str
    worktree: str
    branch: str
    score: float
    pr_body: str
    diff: str
    rollback_command: str
    memory_suggestions: tuple[dict, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-")
    return safe or "task"


def _worktree_path(root: Path, task_id: str) -> Path:
    return root / ".sprint3-worktrees" / _safe_id(task_id)


def _branch_name(task_id: str) -> str:
    return f"sprint3/{_safe_id(task_id)}"


def _create_worktree(root: Path, task_id: str, base: str) -> tuple[bool, Path, str, str]:
    path = _worktree_path(root, task_id)
    branch = _branch_name(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, output = _run(["git", "worktree", "add", "-b", branch, str(path), base], root, timeout=180)
    if not ok:
        return False, path, branch, output
    return True, path, branch, ""


def _apply_sample_patch(worktree: Path) -> tuple[bool, str]:
    path = worktree / "core" / "coding_agent" / "repo_map.py"
    try:
        text = path.read_text(encoding="utf-8")
        if "DEFAULT_MAX_FILES" not in text:
            marker = "EXCLUDED_DIRS = {\n"
            end = text.index(marker) + len(marker)
            close = text.index("}\n", end) + 2
            insert = (
                "    \".git\",\n"
                "    \".venv\",\n"
                "    \".venv-c4-prep\",\n"
                "    \"venv\",\n"
                "    \"env\",\n"
                "    \"build\",\n"
                "    \"dist\",\n"
                "    \"__pycache__\",\n"
                "    \".pytest_cache\",\n"
                "    \".mypy_cache\",\n"
                "    \".ruff_cache\",\n"
                "    \"node_modules\",\n"
                "    \".dart_tool\",\n"
                "}\n\n\nDEFAULT_MAX_FILES = 1000\n"
            )
            text = text[:end] + text[close:]
            text = text.replace(marker, insert, 1)
        text = text.replace("max_files: int = 1000", "max_files: int = DEFAULT_MAX_FILES")
        path.write_text(text, encoding="utf-8")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _run_gates(worktree: Path) -> tuple[bool, dict[str, dict[str, object]]]:
    checks = {
        "ruff": [sys.executable, "-m", "ruff", "check", "core/coding_agent/repo_map.py", "tests/test_sprint3_agent_coder.py"],
        "pytest": [sys.executable, "-m", "pytest", "tests/test_sprint3_agent_coder.py", "-q"],
    }
    results: dict[str, dict[str, object]] = {}
    ok = True
    for name, cmd in checks.items():
        passed, output = _run(cmd, worktree, timeout=180)
        results[name] = {"passed": passed, "output_tail": output[-800:]}
        ok = ok and passed
    return ok, results


def _diff(worktree: Path) -> str:
    ok, output = _run(["git", "diff", "HEAD", "--", "core/coding_agent/repo_map.py"], worktree, timeout=60)
    return output if ok else ""


def _changed_files(worktree: Path, base: str = "HEAD") -> list[str]:
    ok, output = _run(["git", "diff", base, "--name-only"], worktree, timeout=60)
    return [line.strip() for line in output.splitlines() if line.strip()] if ok else []


def _rollback(root: Path, path: Path, branch: str) -> tuple[bool, str]:
    outputs: list[str] = []
    ok1, out1 = _run(["git", "worktree", "remove", "--force", str(path)], root, timeout=120)
    outputs.append(out1)
    ok2, out2 = _run(["git", "branch", "-D", branch], root, timeout=60)
    outputs.append(out2)
    return ok1 and ok2, "\n".join(outputs)


def render_pr_body(issue_title: str, score: float, diff: str, gates: dict[str, dict[str, object]], memory_suggestions: tuple[dict, ...]) -> str:
    gate_lines = []
    for name, result in gates.items():
        gate_lines.append(f"- {name}: {'passed' if result.get('passed') else 'failed'}")

    suggestion_lines = ["### Past similar issues", ""]
    if memory_suggestions:
        for item in memory_suggestions:
            rec = item["record"]
            suggestion_lines.append(f"- **{rec['issue']}** ({rec['outcome']}, score={item['score']:.2f})")
            suggestion_lines.append(f"  - cause: {rec['cause']}")
            suggestion_lines.append(f"  - fix: {rec['successful_correction']}")
    else:
        suggestion_lines.append("- No matching issues in memory yet.")

    return "\n".join(
        [
            f"## {issue_title}",
            "",
            "### Sprint 3 gate",
            "- worktree: isolated `git worktree`",
            "- patch: deterministic repo-map cleanup",
            "- test/lint loop: ruff + pytest",
            "- rollback: worktree removed after gate",
            "",
            "### Gate results",
            *gate_lines,
            "",
            f"Score: {score:.3f}",
            "",
            *suggestion_lines,
            "",
            "### Diff",
            "```diff",
            diff.strip(),
            "```",
        ]
    )


def run_gate(root: str | Path = ".", task_id: str = f"sprint3-{int(time.time())}", issue_title: str = "Sprint 3 gate", base: str = DEFAULT_BASE_BRANCH, rollback: bool = True, print_body: bool = True) -> GateResult:
    root_path = Path(root).resolve()
    memory_path = root_path / "workspace" / "coding_agent" / "failure_memory.json"
    memory = FailureMemory(memory_path)

    ok, worktree, branch, error = _create_worktree(root_path, task_id, base)
    if not ok:
        result = GateResult(
            False, task_id, issue_title, str(worktree), branch, 0.0, "", "",
            f"git worktree remove --force {worktree}", (),
        )
        if print_body:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return result

    prior_suggestions = memory.search(issue_title, top_k=3)
    suggestion_payload = tuple({"score": score, "record": rec.to_dict()} for score, rec in prior_suggestions)

    patch_ok, patch_error = _apply_sample_patch(worktree)
    if not patch_ok:
        _rollback(root_path, worktree, branch)
        failure_rec = memory.record_failure(
            issue=issue_title,
            cause="deterministic sample patch could not be applied",
            files_touched=(),
            error_text=patch_error,
            tags=("sprint3-gate",),
        )
        result = GateResult(
            False, task_id, issue_title, str(worktree), branch, 0.0, "", "",
            f"git worktree remove --force {worktree}",
            ({"score": 1.0, "record": failure_rec.to_dict()},),
        )
        if print_body:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return result

    repo_map = build_repo_map(worktree, max_files=1000)
    gates_ok, gates = _run_gates(worktree)
    swe = run_swe_lite_v1(worktree)
    diff = _diff(worktree)
    changed_files = _changed_files(worktree)
    score = round(
        (0.35 if gates_ok else 0.0)
        + (0.35 if swe.passed else 0.0)
        + (0.15 if repo_map.symbols else 0.0)
        + (0.15 if diff.strip() else 0.0),
        3,
    )

    rollback_ok = True
    rollback_output = ""
    if rollback:
        rollback_ok, rollback_output = _rollback(root_path, worktree, branch)

    ok = patch_ok and gates_ok and swe.passed and bool(repo_map.symbols) and bool(diff.strip()) and rollback_ok

    if ok:
        record = memory.record_success(
            issue=issue_title,
            cause="Sprint 3 gate passed: ruff + pytest + swe-lite OK",
            files_touched=changed_files,
            error_text="",
            successful_correction="Factorise EXCLUDED_DIRS and adds DEFAULT_MAX_FILES in core/coding_agent/repo_map.py.",
            tags=("sprint3-gate",),
        )
    else:
        failed_gate = next((name for name, res in gates.items() if not res.get("passed")), "unknown")
        record = memory.record_failure(
            issue=issue_title,
            cause=f"gate failed at step: {failed_gate}",
            files_touched=changed_files,
            error_text=(gates.get(failed_gate, {}).get("output_tail", "") if failed_gate in gates else "") or rollback_output,
            tags=("sprint3-gate",),
        )

    suggestions = suggestion_payload + ({"score": 1.0, "record": record.to_dict()},)
    pr_body = render_pr_body(issue_title, score, diff, gates, suggestions)
    result = GateResult(
        ok, task_id, issue_title, str(worktree), branch, score, pr_body, diff,
        f"git worktree remove --force {worktree} && git branch -D {branch}",
        suggestions,
    )
    if print_body:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return result


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Sprint 3 coding-agent gate.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--task-id", default=f"sprint3-{int(time.time())}")
    parser.add_argument("--issue", default="Sprint 3 gate")
    parser.add_argument("--base", default=DEFAULT_BASE_BRANCH)
    parser.add_argument("--no-rollback", action="store_true")
    parser.add_argument("--no-print", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = run_gate(
        root=args.root,
        task_id=args.task_id,
        issue_title=args.issue,
        base=args.base,
        rollback=not args.no_rollback,
        print_body=not args.no_print,
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
