"""Git tools for bea-team agents."""
from __future__ import annotations

import re
import subprocess  # nosec B404

from ._base import REPO_ROOT, ToolResult, _timed


def _git(cmd: str, timeout: int = 30) -> str:
    """Run git command, return stdout. Fail-open: returns '' on error."""
    import shlex
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git"] + shlex.split(cmd), shell=False, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


@_timed
def tool_git_branch_create(branch_name: str) -> ToolResult:
    """Create a new branch. Convention: bea/<agent>/<task>."""
    if not re.match(r'^bea/[a-z\-]+/[a-z0-9\-]+$', branch_name):
        return ToolResult(
            success=False, tool="git_branch_create",
            error=f"Invalid branch name: {branch_name}. Must match bea/<agent>/<task>",
        )
    _git(f"checkout -b {branch_name}")
    current = _git("rev-parse --abbrev-ref HEAD")
    ok = current == branch_name
    return ToolResult(
        success=ok, tool="git_branch_create",
        data={"branch": current, "created": ok},
        risk="supervised",
    )


@_timed
def tool_git_status() -> ToolResult:
    """Get git status (short format)."""
    out = _git("status --short")
    branch = _git("rev-parse --abbrev-ref HEAD")
    return ToolResult(
        success=True, tool="git_status",
        data={"branch": branch, "status": out or "(clean)", "dirty": bool(out)},
    )


@_timed
def tool_git_diff(base: str = "master", path: str | None = None) -> ToolResult:
    """Generate diff against base branch."""
    cmd = f"diff {base}"
    if path:
        cmd += f" -- {path}"
    diff = _git(cmd)
    stat = _git(f"diff {base} --stat")
    return ToolResult(
        success=True, tool="git_diff",
        data={"diff": diff[:10000], "stat": stat, "base": base},
    )


@_timed
def tool_git_log(n: int = 10) -> ToolResult:
    """Get recent git commit history."""
    log_out = _git(f"log --oneline -{n}")
    entries = [line for line in log_out.splitlines() if line.strip()]
    return ToolResult(
        success=True, tool="git_log",
        data={"entries": entries, "count": len(entries)},
    )


@_timed
def tool_git_commit(message: str, files: list[str] | None = None) -> ToolResult:
    """Stage and commit changes. Never commits to master."""
    branch = _git("rev-parse --abbrev-ref HEAD")
    if branch in ("master", "main"):
        return ToolResult(
            success=False, tool="git_commit",
            error="Direct commits to master/main are forbidden. Create a feature branch first.",
            risk="dangerous",
        )
    if not message or len(message) < 5:
        return ToolResult(success=False, tool="git_commit", error="Commit message too short (< 5 chars)")
    if files:
        for f in files:
            _git(f"add {f}")
    else:
        _git("add -A")
    result = subprocess.run(  # nosec B603 B607
        ["git", "commit", "-m", message],
        shell=False, cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=30,
    )
    ok = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return ToolResult(
        success=ok, tool="git_commit",
        data={"branch": branch, "message": message, "output": output[:500]},
        risk="supervised",
        error="" if ok else output[:300],
    )


@_timed
def tool_git_compare_branches(branch_a: str, branch_b: str = "master") -> ToolResult:
    """Compare two branches."""
    diff = _git(f"diff {branch_b}..{branch_a} --stat")
    commits = _git(f"log {branch_b}..{branch_a} --oneline")
    return ToolResult(
        success=True, tool="git_compare_branches",
        data={
            "branch_a": branch_a, "branch_b": branch_b,
            "stat": diff, "commits": commits.splitlines(),
        },
    )


@_timed
def tool_git_detect_conflicts(branch: str, target: str = "master") -> ToolResult:
    """Detect potential merge conflicts (dry-run only)."""
    result = subprocess.run(  # nosec B603 B607
        ["git", "merge", "--no-commit", "--no-ff", branch],
        shell=False, cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=30,
    )
    has_conflicts = "CONFLICT" in result.stdout or "CONFLICT" in result.stderr
    _git("merge --abort")
    return ToolResult(
        success=True, tool="git_detect_conflicts",
        data={
            "branch": branch, "target": target,
            "has_conflicts": has_conflicts,
            "output": (result.stdout + result.stderr)[:500],
        },
    )
