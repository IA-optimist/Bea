# ruff: noqa: T201
"""Sprint 3 worktree CLI.

Creates isolated git worktrees for coding-agent missions, runs the local
test/lint gate, prints a diff, and exposes a rollback command.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BASE_BRANCH = os.getenv("SPRINT3_BASE_BRANCH", "main")
WORKTREE_ROOT = Path(".sprint3-worktrees")


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    output: str

    def to_dict(self) -> dict:
        return {"ok": self.ok, "output": self.output}


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> CommandResult:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (proc.stdout + proc.stderr).strip()
    return CommandResult(proc.returncode == 0, output)


def _repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError(f"Not inside a git repository from {current}")


def _worktree_path(root: Path, task_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in task_id).strip("-") or "task"
    return root / WORKTREE_ROOT / safe


def _branch_name(task_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in task_id).strip("-") or "task"
    return f"sprint3/{safe}"


def create_worktree(root: Path, task_id: str, base: str = BASE_BRANCH) -> dict:
    path = _worktree_path(root, task_id)
    branch = _branch_name(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "worktree", "add", "-b", branch, str(path), base], root)
    if not result.ok:
        return {"ok": False, "worktree": str(path), "branch": branch, "error": result.output}
    return {"ok": True, "worktree": str(path), "branch": branch, "rollback": f"git worktree remove --force {path} && git branch -D {branch}"}


def run_gates(worktree: Path) -> dict:
    checks = [
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("pytest", [sys.executable, "-m", "pytest", "tests", "-q", "-m", "not integration"]),
    ]
    results: dict[str, dict] = {}
    ok = True
    for name, cmd in checks:
        result = _run(cmd, worktree)
        results[name] = result.to_dict()
        ok = ok and result.ok
    return {"ok": ok, "checks": results}


def diff(worktree: Path, base: str = BASE_BRANCH) -> dict:
    result = _run(["git", "diff", base, "--"], worktree)
    return {"ok": result.ok, "diff": result.output}


def rollback(root: Path, worktree: Path, branch: str | None = None) -> dict:
    if branch:
        result = _run(["git", "worktree", "remove", "--force", str(worktree)], root)
        branch_result = _run(["git", "branch", "-D", branch], root)
        return {"ok": result.ok and branch_result.ok, "output": "\n".join([result.output, branch_result.output])}
    result = _run(["git", "worktree", "remove", "--force", str(worktree)], root)
    return {"ok": result.ok, "output": result.output}


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sprint 3 git worktree helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("task_id")
    create.add_argument("--base", default=BASE_BRANCH)

    run_gates_parser = sub.add_parser("run-gates")
    run_gates_parser.add_argument("task_id")

    diff_parser = sub.add_parser("diff")
    diff_parser.add_argument("task_id")

    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("task_id")

    args = parser.parse_args(list(argv) if argv is not None else None)
    root = _repo_root()

    if args.command == "create":
        sys.stdout.write(f"{create_worktree(root, args.task_id, args.base)}\n")
        return 0

    if args.command == "run-gates":
        path = _worktree_path(root, args.task_id)
        result = run_gates(path)
        sys.stdout.write(f"{result}\n")
        return 0 if result["ok"] else 1

    if args.command == "diff":
        path = _worktree_path(root, args.task_id)
        sys.stdout.write(f"{diff(path)}\n")
        return 0

    if args.command == "rollback":
        path = _worktree_path(root, args.task_id)
        branch = _branch_name(args.task_id)
        sys.stdout.write(f"{rollback(root, path, branch)}\n")
        return 0

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
