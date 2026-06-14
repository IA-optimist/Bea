"""Test execution tools for bea-team agents."""
from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path

from ._base import REPO_ROOT, ToolResult, _timed


@_timed
def tool_run_tests(test_path: str = "tests/", timeout: int = 120) -> ToolResult:
    """Run pytest on a path. Returns structured pass/fail counts."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["python3", "-m", "pytest", test_path, "-x", "-q", "--tb=short"],
            shell=False, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=timeout,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        passed = failed = errors = 0
        for line in output.splitlines():
            m = re.search(r"(\d+) passed", line)
            if m: passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m: failed = int(m.group(1))
            m = re.search(r"(\d+) error", line)
            if m: errors = int(m.group(1))
        return ToolResult(
            success=result.returncode == 0, tool="run_tests",
            data={
                "passed": passed, "failed": failed, "errors": errors,
                "output": output[:5000], "returncode": result.returncode,
            },
        )
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, tool="run_tests", error=f"Timeout after {timeout}s")


@_timed
def tool_run_single_test(test_file: str, timeout: int = 60) -> ToolResult:
    """Run a single test file."""
    return tool_run_tests(test_path=test_file, timeout=timeout)


@_timed
def tool_detect_missing_tests(path: str = ".") -> ToolResult:
    """Detect source files that have no corresponding test file."""
    d = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    source_files: set[str] = set()
    test_files: set[str] = set()

    for f in d.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        rel = str(f.relative_to(REPO_ROOT))
        if rel.startswith("tests/") or "test_" in f.name:
            tested = f.name.replace("test_", "").replace(".py", "")
            test_files.add(tested)
        elif rel.startswith(("core/", "agents/", "tools/", "executor/", "memory/")):
            source_files.add(f.stem)

    missing = source_files - test_files
    covered = source_files & test_files
    return ToolResult(
        success=True, tool="detect_missing_tests",
        data={
            "missing_tests": sorted(missing)[:50],
            "covered": sorted(covered),
            "coverage_pct": round(len(covered) / max(len(source_files), 1) * 100, 1),
            "source_count": len(source_files),
        },
    )
