"""Logging and observability tools for bea-team agents."""
from __future__ import annotations

import re
from pathlib import Path

import structlog

from ._base import REPO_ROOT, ToolResult, _timed
from ._git import _git

log = structlog.get_logger(__name__)


@_timed
def tool_read_logs(log_path: str = "workspace/", pattern: str = "*.log",
                   tail: int = 200) -> ToolResult:
    """Read recent log entries."""
    d = Path(log_path) if Path(log_path).is_absolute() else REPO_ROOT / log_path
    try:
        log_files = sorted(d.rglob(pattern))[-5:]
        entries = []
        for lf in log_files:
            try:
                lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()
                entries.extend(lines[-tail:])
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
                continue
        return ToolResult(
            success=True, tool="read_logs",
            data={"entries": entries[-tail:], "count": len(entries), "files": [str(f) for f in log_files]},
        )
    except Exception as e:
        return ToolResult(success=False, tool="read_logs", error=str(e)[:300])


@_timed
def tool_detect_error_patterns(path: str = ".") -> ToolResult:
    """Scan Python files for common error patterns."""
    d = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    patterns = {
        "bare_except": re.compile(r"^\s*except\s*:", re.MULTILINE),
        "print_debug": re.compile(r"\bprint\s*\(", re.MULTILINE),
        "todo_fixme": re.compile(r"#\s*(TODO|FIXME|HACK|XXX)", re.MULTILINE | re.IGNORECASE),
        "import_star": re.compile(r"from\s+\S+\s+import\s+\*", re.MULTILINE),
        "pass_in_except": re.compile(r"except.*:\s*\n\s*pass", re.MULTILINE),
    }
    findings: dict[str, list[dict]] = {k: [] for k in patterns}

    try:
        for f in d.rglob("*.py"):
            if "__pycache__" in str(f) or ".git" in str(f):
                continue
            rel = str(f.relative_to(REPO_ROOT))
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                for name, pat in patterns.items():
                    for m in pat.finditer(content):
                        lineno = content[:m.start()].count("\n") + 1
                        findings[name].append({"file": rel, "line": lineno})
                        if len(findings[name]) >= 20:
                            break
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
                continue

        total = sum(len(v) for v in findings.values())
        return ToolResult(
            success=True, tool="detect_error_patterns",
            data={"findings": findings, "total": total},
        )
    except Exception as e:
        return ToolResult(success=False, tool="detect_error_patterns", error=str(e)[:300])


@_timed
def tool_detect_regressions(base: str = "master") -> ToolResult:
    """Check if changed files still pass syntax validation."""
    from ._analysis import tool_syntax_validate
    changed = _git(f"diff {base} --name-only").splitlines()
    py_files = [f for f in changed if f.endswith(".py")]
    results = []
    for f in py_files:
        r = tool_syntax_validate(f)
        results.append({
            "file": f,
            "valid": r.data.get("valid", False) if r.success else False,
            "error": r.data.get("error", r.error) if r.data else r.error,
        })
    regressions = [r for r in results if not r["valid"]]
    return ToolResult(
        success=True, tool="detect_regressions",
        data={
            "files_checked": len(py_files),
            "regressions": regressions,
            "all_valid": len(regressions) == 0,
        },
    )
