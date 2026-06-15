"""Diff and patch tools for bea-team agents."""
from __future__ import annotations

from ._base import ToolResult, _timed
from ._git import _git


@_timed
def tool_generate_diff(base: str = "master") -> ToolResult:
    """Generate a minimal, human-readable diff against base."""
    stat = _git(f"diff {base} --stat")
    diff = _git(f"diff {base}")
    files_changed = _git(f"diff {base} --name-only").splitlines()
    additions = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    return ToolResult(
        success=True, tool="generate_diff",
        data={
            "stat": stat, "diff": diff[:15000],
            "files_changed": files_changed,
            "additions": additions, "deletions": deletions,
            "base": base,
        },
    )


@_timed
def tool_diff_summary(base: str = "master") -> ToolResult:
    """Structured summary of changes without full diff text."""
    stat = _git(f"diff {base} --stat")
    files = _git(f"diff {base} --name-only").splitlines()
    numstat = _git(f"diff {base} --numstat")
    changes = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            changes.append({
                "file": parts[2],
                "additions": int(parts[0]) if parts[0] != "-" else 0,
                "deletions": int(parts[1]) if parts[1] != "-" else 0,
            })
    return ToolResult(
        success=True, tool="diff_summary",
        data={
            "files_changed": len(files),
            "changes": changes,
            "stat": stat,
            "base": base,
        },
    )
