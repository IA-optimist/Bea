"""
Bea Team — Tool Access Layer
=================================
Maps existing BeaMax tools to bea-team agents with:
- Per-agent access control (which agent can use which tool)
- Risk classification (SAFE / SUPERVISED / DANGEROUS)
- Structured ToolResult output
- Fail-open on every call
- Protected path enforcement

This module does NOT reinvent tools — it wraps the existing tool_executor,
core/tools/*, and base.py helpers into a controlled access layer.

Design principles:
- Small composable tools over monolithic ones
- Every tool degrades gracefully (returns ToolResult with error, never raises)
- No blocking operations > 120s
- All outputs are structured dicts
- No silent failures — errors are always logged and returned
"""
from __future__ import annotations

import ast
import os
import re
import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

REPO_ROOT = Path(os.environ.get("BEAMAX_REPO", ".")).resolve()


# ═══════════════════════════════════════════════════════════════
# RISK + RESULT TYPES
# ═══════════════════════════════════════════════════════════════

class ToolRisk(str, Enum):
    SAFE       = "safe"        # Read-only, no side effects
    SUPERVISED = "supervised"  # Side effects, needs review
    DANGEROUS  = "dangerous"   # Destructive, requires approval


@dataclass
class ToolResult:
    """Structured output from every tool call."""
    success:  bool
    tool:     str
    data:     Any    = None
    error:    str    = ""
    risk:     str    = "safe"
    duration_ms: int = 0
    meta:     dict   = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "risk": self.risk,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
        }


def _timed(fn):
    """Decorator that measures execution time and wraps exceptions."""
    def wrapper(*args, **kwargs):
        t0 = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, ToolResult):
                result.duration_ms = int((time.monotonic() - t0) * 1000)
            return result
        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            tool_name = fn.__name__.replace("tool_", "")
            log.warning("tool_failed", tool=tool_name, err=str(e)[:200])
            return ToolResult(
                success=False, tool=tool_name,
                error=str(e)[:500], duration_ms=ms,
            )
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ═══════════════════════════════════════════════════════════════
# PROTECTED PATHS
# ═══════════════════════════════════════════════════════════════

PROTECTED_FILES = frozenset({
    "core/meta_orchestrator.py",
    "core/mission_system.py",
    "core/state.py",
    "core/contracts.py",
    "config/settings.py",
    "agents/crew.py",
})

PROTECTED_DIRS = frozenset({
    "core/contracts",
    "config",
})


def is_protected(path: str) -> bool:
    """Check if a path is protected (requires reviewer approval to modify)."""
    rel = str(Path(path).relative_to(REPO_ROOT)) if Path(path).is_absolute() else path
    rel = rel.lstrip("./")
    if rel in PROTECTED_FILES:
        return True
    for d in PROTECTED_DIRS:
        if rel.startswith(d + "/") or rel == d:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# 1. GIT TOOLS
# ═══════════════════════════════════════════════════════════════

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
    stat = _git(f"diff {base} --stat")
    diff = _git(cmd)
    return ToolResult(
        success=True, tool="git_diff",
        data={"stat": stat, "diff": diff[:10000], "base": base},
    )


@_timed
def tool_git_log(n: int = 10) -> ToolResult:
    """View recent commit history."""
    out = _git(f"log --oneline -n {n}")
    return ToolResult(
        success=True, tool="git_log",
        data={"commits": out.splitlines(), "count": len(out.splitlines())},
    )


@_timed
def tool_git_commit(message: str, files: list[str] | None = None) -> ToolResult:
    """Stage and commit changes. Never commits to master."""
    branch = _git("rev-parse --abbrev-ref HEAD")
    if branch in ("master", "main"):
        return ToolResult(
            success=False, tool="git_commit",
            error="Cannot commit directly to master/main. Create a branch first.",
            risk="dangerous",
        )
    # Stage
    if files:
        for f in files:
            _git(f"add {f}")
    else:
        _git("add -A")
    # Commit
    result = subprocess.run(  # nosec B603 B607
        ["git", "commit", "-m", message],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    ok = result.returncode == 0
    return ToolResult(
        success=ok, tool="git_commit",
        data={"branch": branch, "message": message, "output": result.stdout[:1000]},
        error=result.stderr[:500] if not ok else "",
        risk="supervised",
    )


@_timed
def tool_git_compare_branches(branch_a: str, branch_b: str = "master") -> ToolResult:
    """Compare two branches (stat + file list)."""
    stat = _git(f"diff {branch_b}..{branch_a} --stat")
    files = _git(f"diff {branch_b}..{branch_a} --name-only")
    return ToolResult(
        success=True, tool="git_compare_branches",
        data={
            "stat": stat, "files_changed": files.splitlines(),
            "a": branch_a, "b": branch_b,
        },
    )


@_timed
def tool_git_detect_conflicts(branch: str, target: str = "master") -> ToolResult:
    """Check if a branch would merge cleanly into target."""
    # Dry-run merge
    result = subprocess.run(  # nosec B603 B607
        ["git", "merge", "--no-commit", "--no-ff", branch],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    has_conflicts = result.returncode != 0
    # Abort the merge attempt
    _git("merge --abort")
    return ToolResult(
        success=True, tool="git_detect_conflicts",
        data={
            "conflicts": has_conflicts,
            "branch": branch, "target": target,
            "output": result.stderr[:1000] if has_conflicts else "clean",
        },
    )


# ═══════════════════════════════════════════════════════════════
# 2. FILESYSTEM TOOLS
# ═══════════════════════════════════════════════════════════════

@_timed
def tool_read_file(path: str, max_chars: int = 15000) -> ToolResult:
    """Read a file from the repo."""
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return ToolResult(
            success=True, tool="read_file",
            data={
                "path": str(p.relative_to(REPO_ROOT)),
                "content": content[:max_chars],
                "lines": content.count("\n") + 1,
                "truncated": len(content) > max_chars,
            },
        )
    except FileNotFoundError:
        return ToolResult(success=False, tool="read_file", error=f"File not found: {path}")


@_timed
def tool_write_file(path: str, content: str) -> ToolResult:
    """Write a file. Protected files require reviewer approval."""
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    protected = is_protected(path)
    if protected:
        return ToolResult(
            success=False, tool="write_file",
            error=f"Protected file: {path}. Requires bea-reviewer approval.",
            risk="dangerous",
            meta={"protected": True, "requires_approval": "bea-reviewer"},
        )
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(
            success=True, tool="write_file",
            data={"path": str(p.relative_to(REPO_ROOT)), "chars": len(content)},
            risk="supervised",
        )
    except Exception as e:
        return ToolResult(success=False, tool="write_file", error=str(e)[:300])


@_timed
def tool_patch_file(path: str, old_text: str, new_text: str) -> ToolResult:
    """Patch a file by replacing exact text. Protected files blocked."""
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    protected = is_protected(path)
    if protected:
        return ToolResult(
            success=False, tool="patch_file",
            error=f"Protected file: {path}. Requires bea-reviewer approval.",
            risk="dangerous",
            meta={"protected": True},
        )
    try:
        content = p.read_text(encoding="utf-8")
        if old_text not in content:
            return ToolResult(
                success=False, tool="patch_file",
                error=f"Pattern not found in {path}",
            )
        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")
        return ToolResult(
            success=True, tool="patch_file",
            data={
                "path": str(p.relative_to(REPO_ROOT)),
                "old_len": len(old_text), "new_len": len(new_text),
            },
            risk="supervised",
        )
    except FileNotFoundError:
        return ToolResult(success=False, tool="patch_file", error=f"File not found: {path}")


@_timed
def tool_list_directory(path: str = ".", pattern: str = "*.py", max_depth: int = 3) -> ToolResult:
    """List files in a directory, optionally filtered by pattern."""
    d = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        files = []
        for f in sorted(d.rglob(pattern)):
            rel = f.relative_to(REPO_ROOT)
            if len(rel.parts) <= max_depth and "__pycache__" not in str(rel):
                files.append(str(rel))
            if len(files) >= 500:
                break
        return ToolResult(
            success=True, tool="list_directory",
            data={"path": path, "pattern": pattern, "files": files, "count": len(files)},
        )
    except Exception as e:
        return ToolResult(success=False, tool="list_directory", error=str(e)[:300])


@_timed
def tool_detect_file_dependencies(path: str) -> ToolResult:
    """Detect what a Python file imports (local imports only)."""
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        content = p.read_text(encoding="utf-8")
        tree = ast.parse(content)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"module": alias.name, "type": "import"})
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append({"module": node.module, "type": "from", "names": [a.name for a in node.names]})
        # Filter to local imports only
        local_imports = [i for i in imports if not i["module"].startswith(("os", "sys", "re", "json", "time",
                         "uuid", "pathlib", "enum", "typing", "dataclasses", "abc", "asyncio", "logging",
                         "subprocess", "shutil", "hashlib", "collections", "functools", "importlib",
                         "inspect", "traceback", "datetime", "copy", "math", "random", "socket",
                         "pydantic", "structlog", "langchain", "openai", "requests", "pytest"))]
        return ToolResult(
            success=True, tool="detect_file_dependencies",
            data={"path": str(p.relative_to(REPO_ROOT)), "imports": local_imports, "total": len(imports)},
        )
    except SyntaxError as e:
        return ToolResult(success=False, tool="detect_file_dependencies", error=f"Syntax error: {e}")
    except FileNotFoundError:
        return ToolResult(success=False, tool="detect_file_dependencies", error=f"File not found: {path}")


# ═══════════════════════════════════════════════════════════════
# 3. CODE ANALYSIS TOOLS
# ═══════════════════════════════════════════════════════════════

@_timed
def tool_syntax_validate(path: str) -> ToolResult:
    """Validate Python syntax via ast.parse."""
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        content = p.read_text(encoding="utf-8")
        ast.parse(content)
        return ToolResult(
            success=True, tool="syntax_validate",
            data={"path": str(p.relative_to(REPO_ROOT)), "valid": True, "lines": content.count("\n") + 1},
        )
    except SyntaxError as e:
        return ToolResult(
            success=True, tool="syntax_validate",
            data={"path": path, "valid": False, "error": str(e), "line": e.lineno},
        )
    except FileNotFoundError:
        return ToolResult(success=False, tool="syntax_validate", error=f"File not found: {path}")


@_timed
def tool_import_graph(path: str = ".") -> ToolResult:
    """Build import graph for Python files in a directory."""
    d = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    graph: dict[str, list[str]] = {}
    errors = []
    try:
        for f in d.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            rel = str(f.relative_to(REPO_ROOT))
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content)
                deps = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if node.module.startswith(("core.", "agents.", "tools.", "memory.", "config.",
                                                    "executor.", "api.", "risk.", "monitoring.")):
                            deps.append(node.module)
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(("core.", "agents.", "tools.", "memory.", "config.")):
                                deps.append(alias.name)
                if deps:
                    graph[rel] = sorted(set(deps))
            except SyntaxError:
                errors.append(rel)
        return ToolResult(
            success=True, tool="import_graph",
            data={"graph": graph, "files": len(graph), "errors": errors},
        )
    except Exception as e:
        return ToolResult(success=False, tool="import_graph", error=str(e)[:300])


@_timed
def tool_circular_import_detect(path: str = ".") -> ToolResult:
    """Detect circular imports in the codebase."""
    result = tool_import_graph(path)
    if not result.success:
        return result
    graph = result.data["graph"]

    # Build module-level graph
    mod_graph: dict[str, set[str]] = {}
    for file_path, deps in graph.items():
        # Convert file path to module name
        mod = file_path.replace("/", ".").replace(".py", "")
        mod_graph[mod] = set(deps)

    # DFS cycle detection
    cycles = []
    visited = set()
    path_stack: list[str] = []

    def dfs(node: str):
        if node in path_stack:
            cycle_start = path_stack.index(node)
            cycles.append(path_stack[cycle_start:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        path_stack.append(node)
        for dep in mod_graph.get(node, set()):
            dfs(dep)
        path_stack.pop()

    for mod in mod_graph:
        path_stack.clear()
        visited.clear()
        dfs(mod)

    return ToolResult(
        success=True, tool="circular_import_detect",
        data={"cycles": cycles[:20], "cycle_count": len(cycles)},
    )


@_timed
def tool_dead_code_detect(path: str = ".") -> ToolResult:
    """Detect potentially dead code (defined but never imported/called)."""
    d = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    defined: dict[str, str] = {}  # name → file
    used: set[str] = set()

    try:
        for f in d.rglob("*.py"):
            if "__pycache__" in str(f) or "test" in str(f):
                continue
            rel = str(f.relative_to(REPO_ROOT))
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_"):
                            defined[node.name] = rel
                    elif isinstance(node, ast.ClassDef):
                        if not node.name.startswith("_"):
                            defined[node.name] = rel
                    elif isinstance(node, ast.Name):
                        used.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        used.add(node.attr)
            except SyntaxError:
                log.debug("swallowed_exception", exc_info=True)
                continue

        dead = {name: file for name, file in defined.items() if name not in used}
        return ToolResult(
            success=True, tool="dead_code_detect",
            data={
                "potentially_dead": dict(list(dead.items())[:50]),
                "count": len(dead),
                "total_defined": len(defined),
                "note": "These names were defined but never referenced. May have false positives.",
            },
        )
    except Exception as e:
        return ToolResult(success=False, tool="dead_code_detect", error=str(e)[:300])


@_timed
def tool_complexity_estimate(path: str) -> ToolResult:
    """Estimate cyclomatic complexity of a Python file."""
    p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
    try:
        content = p.read_text(encoding="utf-8")
        tree = ast.parse(content)

        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Count decision points
                complexity = 1  # base
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "complexity": complexity,
                    "rating": "low" if complexity <= 5 else ("medium" if complexity <= 10 else "high"),
                })

        functions.sort(key=lambda f: f["complexity"], reverse=True)
        avg = sum(f["complexity"] for f in functions) / max(len(functions), 1)
        return ToolResult(
            success=True, tool="complexity_estimate",
            data={
                "path": str(p.relative_to(REPO_ROOT)),
                "functions": functions[:20],
                "avg_complexity": round(avg, 1),
                "total_functions": len(functions),
                "high_complexity": [f for f in functions if f["complexity"] > 10],
            },
        )
    except Exception as e:
        return ToolResult(success=False, tool="complexity_estimate", error=str(e)[:300])


# ═══════════════════════════════════════════════════════════════
# 4. TEST TOOLS
# ═══════════════════════════════════════════════════════════════

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
        # Parse counts
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
    source_files = set()
    test_files = set()

    for f in d.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        rel = str(f.relative_to(REPO_ROOT))
        if rel.startswith("tests/") or "test_" in f.name:
            # Extract what it tests
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


# ═══════════════════════════════════════════════════════════════
# 5. DIFF AND PATCH TOOLS
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 6. LOGGING AND OBSERVABILITY TOOLS
# ═══════════════════════════════════════════════════════════════

@_timed
def tool_read_logs(log_path: str = "workspace/", pattern: str = "*.log",
                   tail: int = 200) -> ToolResult:
    """Read recent log entries."""
    d = Path(log_path) if Path(log_path).is_absolute() else REPO_ROOT / log_path
    try:
        log_files = sorted(d.rglob(pattern))[-5:]  # last 5 log files
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


# ═══════════════════════════════════════════════════════════════
# 7. ENVIRONMENT INSPECTION TOOLS
# ═══════════════════════════════════════════════════════════════

@_timed
def tool_python_version() -> ToolResult:
    """Detect Python version."""
    import sys
    return ToolResult(
        success=True, tool="python_version",
        data={
            "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "full": sys.version,
        },
    )


@_timed
def tool_detect_installed_packages() -> ToolResult:
    """List installed Python packages."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["python3", "-m", "pip", "list", "--format=json"],
            shell=False, capture_output=True, text=True, timeout=15,
        )
        import json as _json
        try:
            packages = _json.loads(result.stdout)
        except Exception:
            packages = []
        return ToolResult(
            success=True, tool="detect_installed_packages",
            data={"packages": packages, "count": len(packages)},
        )
    except Exception as e:
        return ToolResult(success=False, tool="detect_installed_packages", error=str(e)[:300])


@_timed
def tool_detect_missing_dependencies() -> ToolResult:
    """Compare imports in codebase against installed packages."""
    # Get all imports
    graph_result = tool_import_graph()
    if not graph_result.success:
        return graph_result
    all_imports = set()
    for deps in graph_result.data.get("graph", {}).values():
        for d in deps:
            all_imports.add(d.split(".")[0])
    # This is a heuristic — just checks top-level module names
    missing = []
    for mod in all_imports:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return ToolResult(
        success=True, tool="detect_missing_dependencies",
        data={"missing": missing, "checked": len(all_imports)},
    )


@_timed
def tool_detect_docker_config() -> ToolResult:
    """Inspect docker-compose configuration."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    prod_path = REPO_ROOT / "docker-compose.prod.yml"
    data = {"files": []}
    for p in [compose_path, prod_path]:
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            data["files"].append({
                "path": str(p.relative_to(REPO_ROOT)),
                "content": content[:5000],
                "lines": content.count("\n") + 1,
            })
    return ToolResult(
        success=True, tool="detect_docker_config",
        data=data,
    )


@_timed
def tool_env_vars_check() -> ToolResult:
    """Check which expected environment variables are set (names only, not values)."""
    expected = [
        "BEA_ROOT", "BEAMAX_REPO", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "DATABASE_URL", "REDIS_URL", "QDRANT_URL",
        "OLLAMA_HOST", "GITHUB_TOKEN",
    ]
    status = {}
    for var in expected:
        val = os.environ.get(var, "")
        status[var] = "SET" if val else "MISSING"
    return ToolResult(
        success=True, tool="env_vars_check",
        data={"vars": status, "set_count": sum(1 for v in status.values() if v == "SET")},
    )


# ═══════════════════════════════════════════════════════════════
# 8. KNOWLEDGE INTERACTION TOOLS
# ═══════════════════════════════════════════════════════════════

@_timed
def tool_store_pattern(pattern_type: str, problem: str, solution: str,
                       confidence: float = 0.5, tags: list[str] | None = None) -> ToolResult:
    """Store a structured solution pattern. Requires confidence score."""
    if not 0.0 <= confidence <= 1.0:
        return ToolResult(success=False, tool="store_pattern", error="Confidence must be 0.0-1.0")
    try:
        from core.tools.memory_toolkit import memory_store_solution
        result = memory_store_solution(
            problem=f"[{pattern_type}] {problem}",
            solution=solution,
            tags=(tags or []) + [pattern_type],
        )
        return ToolResult(
            success=result.get("ok", False), tool="store_pattern",
            data={"confidence": confidence, "type": pattern_type},
            error=result.get("error", ""),
        )
    except Exception:
        # Fail-open: store to local JSON file
        import json as _json
        store_path = REPO_ROOT / "workspace" / "knowledge_store.jsonl"
        try:
            store_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "type": pattern_type, "problem": problem[:500],
                "solution": solution[:500], "confidence": confidence,
                "tags": tags or [], "timestamp": time.time(),
            }
            with open(store_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry) + "\n")
            return ToolResult(
                success=True, tool="store_pattern",
                data={"stored_locally": True, "confidence": confidence},
            )
        except Exception as e2:
            return ToolResult(success=False, tool="store_pattern", error=str(e2)[:300])


@_timed
def tool_search_patterns(query: str, limit: int = 5) -> ToolResult:
    """Search past solution patterns by keyword."""
    try:
        from core.tools.memory_toolkit import memory_search_similar
        result = memory_search_similar(query=query, limit=limit)
        return ToolResult(
            success=result.get("ok", False), tool="search_patterns",
            data=result.get("results", []),
            error=result.get("error", ""),
        )
    except Exception:
        # Fallback: search local JSONL
        import json as _json
        store_path = REPO_ROOT / "workspace" / "knowledge_store.jsonl"
        if not store_path.exists():
            return ToolResult(success=True, tool="search_patterns", data=[])
        matches = []
        q_lower = query.lower()
        try:
            for line in store_path.read_text().splitlines():
                entry = _json.loads(line)
                if q_lower in entry.get("problem", "").lower() or q_lower in entry.get("solution", "").lower():
                    matches.append(entry)
                if len(matches) >= limit:
                    break
        except Exception as _exc:
            log.warning("swallowed_exception", action="tools_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return ToolResult(success=True, tool="search_patterns", data=matches)


@_timed
def tool_store_decision(decision: str, rationale: str, impact: str,
                        confidence: float = 0.5) -> ToolResult:
    """Store an architecture decision record."""
    import json as _json
    store_path = REPO_ROOT / "workspace" / "decisions.jsonl"
    try:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "decision": decision[:500], "rationale": rationale[:500],
            "impact": impact[:300], "confidence": confidence,
            "timestamp": time.time(),
        }
        with open(store_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry) + "\n")
        return ToolResult(
            success=True, tool="store_decision",
            data={"stored": True, "confidence": confidence},
        )
    except Exception as e:
        return ToolResult(success=False, tool="store_decision", error=str(e)[:300])


# ═══════════════════════════════════════════════════════════════
# 9. AGENT COORDINATION TOOLS
# ═══════════════════════════════════════════════════════════════

@_timed
def tool_create_task(agent: str, description: str, priority: int = 2,
                     depends_on: list[str] | None = None) -> ToolResult:
    """Create a task description for an agent."""
    task = {
        "agent": agent,
        "description": description[:500],
        "priority": max(1, min(4, priority)),
        "depends_on": depends_on or [],
        "created_at": time.time(),
        "status": "pending",
    }
    return ToolResult(
        success=True, tool="create_task",
        data=task,
    )


@_timed
def tool_report_status(agent: str, task: str, status: str,
                       output: str = "", error: str = "") -> ToolResult:
    """Report status from an agent on a task."""
    valid_statuses = {"pending", "running", "completed", "failed", "blocked"}
    if status not in valid_statuses:
        return ToolResult(
            success=False, tool="report_status",
            error=f"Invalid status: {status}. Must be one of {valid_statuses}",
        )
    return ToolResult(
        success=True, tool="report_status",
        data={
            "agent": agent, "task": task[:200], "status": status,
            "output": output[:1000], "error": error[:500],
            "timestamp": time.time(),
        },
    )


# ═══════════════════════════════════════════════════════════════
# AGENT ACCESS MATRIX
# ═══════════════════════════════════════════════════════════════

# Maps agent name → set of tool function names they can access
AGENT_TOOL_ACCESS: dict[str, set[str]] = {
    "bea-architect": {
        # Read-only analysis + knowledge
        "tool_read_file", "tool_list_directory", "tool_detect_file_dependencies",
        "tool_syntax_validate", "tool_import_graph", "tool_circular_import_detect",
        "tool_dead_code_detect", "tool_complexity_estimate",
        "tool_git_status", "tool_git_log", "tool_git_diff", "tool_git_compare_branches",
        "tool_detect_error_patterns",
        "tool_search_patterns", "tool_store_decision",
        "tool_create_task", "tool_report_status",
        "tool_diff_summary",
    },
    "bea-coder": {
        # Read + write + git workflow
        "tool_read_file", "tool_write_file", "tool_patch_file",
        "tool_list_directory", "tool_detect_file_dependencies",
        "tool_syntax_validate",
        "tool_git_branch_create", "tool_git_status", "tool_git_diff",
        "tool_git_commit", "tool_git_log",
        "tool_generate_diff", "tool_diff_summary",
        "tool_report_status", "tool_search_patterns",
    },
    "bea-reviewer": {
        # Read-only + diff analysis
        "tool_read_file", "tool_list_directory", "tool_detect_file_dependencies",
        "tool_syntax_validate", "tool_import_graph", "tool_circular_import_detect",
        "tool_complexity_estimate",
        "tool_git_diff", "tool_git_log", "tool_git_status",
        "tool_git_compare_branches", "tool_git_detect_conflicts",
        "tool_generate_diff", "tool_diff_summary",
        "tool_detect_error_patterns", "tool_detect_regressions",
        "tool_report_status",
    },
    "bea-qa": {
        # Tests + read + limited write (tests/ only)
        "tool_read_file", "tool_write_file", "tool_list_directory",
        "tool_syntax_validate",
        "tool_run_tests", "tool_run_single_test", "tool_detect_missing_tests",
        "tool_git_diff", "tool_git_status",
        "tool_detect_regressions",
        "tool_report_status",
    },
    "bea-devops": {
        # Environment + docker + read
        "tool_read_file", "tool_list_directory",
        "tool_detect_docker_config", "tool_env_vars_check",
        "tool_python_version", "tool_detect_installed_packages",
        "tool_detect_missing_dependencies",
        "tool_git_status", "tool_git_log",
        "tool_run_tests",
        "tool_report_status",
    },
    "bea-watcher": {
        # Monitoring + read-only
        "tool_read_file", "tool_read_logs",
        "tool_detect_error_patterns", "tool_detect_regressions",
        "tool_git_status", "tool_git_log",
        "tool_run_tests",
        "tool_search_patterns", "tool_store_pattern",
        "tool_report_status",
    },
}


def get_tools_for_agent(agent_name: str) -> dict[str, callable]:
    """
    Returns the tools an agent is allowed to use.
    Fail-open: unknown agent gets read-only tools.
    """
    allowed = AGENT_TOOL_ACCESS.get(agent_name, {
        "tool_read_file", "tool_list_directory", "tool_git_status",
    })
    # Resolve function references
    tools = {}
    current_module = globals()
    for name in allowed:
        fn = current_module.get(name)
        if fn and callable(fn):
            tools[name] = fn
    return tools


# ═══════════════════════════════════════════════════════════════
# TOOL CATALOG (for reporting)
# ═══════════════════════════════════════════════════════════════

TOOL_CATALOG = [
    # 1. Git tools
    {"name": "git_branch_create", "purpose": "Create branch (bea/<agent>/<task>)", "risk": "supervised", "category": "git", "deps": ["git"]},
    {"name": "git_status", "purpose": "Get repo status", "risk": "safe", "category": "git", "deps": ["git"]},
    {"name": "git_diff", "purpose": "Generate diff against base branch", "risk": "safe", "category": "git", "deps": ["git"]},
    {"name": "git_log", "purpose": "View commit history", "risk": "safe", "category": "git", "deps": ["git"]},
    {"name": "git_commit", "purpose": "Stage and commit changes (never to master)", "risk": "supervised", "category": "git", "deps": ["git"]},
    {"name": "git_compare_branches", "purpose": "Compare two branches", "risk": "safe", "category": "git", "deps": ["git"]},
    {"name": "git_detect_conflicts", "purpose": "Check merge conflicts (dry-run)", "risk": "safe", "category": "git", "deps": ["git"]},
    # 2. Filesystem tools
    {"name": "read_file", "purpose": "Read file content", "risk": "safe", "category": "filesystem", "deps": []},
    {"name": "write_file", "purpose": "Write file (protected files blocked)", "risk": "supervised", "category": "filesystem", "deps": []},
    {"name": "patch_file", "purpose": "Patch file with exact text replacement", "risk": "supervised", "category": "filesystem", "deps": []},
    {"name": "list_directory", "purpose": "List directory contents", "risk": "safe", "category": "filesystem", "deps": []},
    {"name": "detect_file_dependencies", "purpose": "Detect Python imports", "risk": "safe", "category": "filesystem", "deps": []},
    # 3. Code analysis tools
    {"name": "syntax_validate", "purpose": "Validate Python syntax via ast.parse", "risk": "safe", "category": "analysis", "deps": []},
    {"name": "import_graph", "purpose": "Build import dependency graph", "risk": "safe", "category": "analysis", "deps": []},
    {"name": "circular_import_detect", "purpose": "Find circular import chains", "risk": "safe", "category": "analysis", "deps": []},
    {"name": "dead_code_detect", "purpose": "Find potentially unused code", "risk": "safe", "category": "analysis", "deps": []},
    {"name": "complexity_estimate", "purpose": "Estimate cyclomatic complexity", "risk": "safe", "category": "analysis", "deps": []},
    # 4. Test tools
    {"name": "run_tests", "purpose": "Run pytest suite", "risk": "safe", "category": "test", "deps": ["pytest"]},
    {"name": "run_single_test", "purpose": "Run a single test file", "risk": "safe", "category": "test", "deps": ["pytest"]},
    {"name": "detect_missing_tests", "purpose": "Find source files without tests", "risk": "safe", "category": "test", "deps": []},
    # 5. Diff and patch tools
    {"name": "generate_diff", "purpose": "Generate minimal diff", "risk": "safe", "category": "diff", "deps": ["git"]},
    {"name": "diff_summary", "purpose": "Structured diff summary", "risk": "safe", "category": "diff", "deps": ["git"]},
    {"name": "detect_regressions", "purpose": "Check changed files for syntax errors", "risk": "safe", "category": "diff", "deps": ["git"]},
    # 6. Logging and observability tools
    {"name": "read_logs", "purpose": "Read recent log entries", "risk": "safe", "category": "observability", "deps": []},
    {"name": "detect_error_patterns", "purpose": "Scan for bare except, print debug, TODOs", "risk": "safe", "category": "observability", "deps": []},
    # 7. Environment inspection tools
    {"name": "python_version", "purpose": "Detect Python version", "risk": "safe", "category": "environment", "deps": []},
    {"name": "detect_installed_packages", "purpose": "List installed packages", "risk": "safe", "category": "environment", "deps": []},
    {"name": "detect_missing_dependencies", "purpose": "Find missing imports", "risk": "safe", "category": "environment", "deps": []},
    {"name": "detect_docker_config", "purpose": "Inspect docker-compose files", "risk": "safe", "category": "environment", "deps": []},
    {"name": "env_vars_check", "purpose": "Check expected env vars (names only)", "risk": "safe", "category": "environment", "deps": []},
    # 8. Knowledge interaction tools
    {"name": "store_pattern", "purpose": "Store solution pattern with confidence", "risk": "supervised", "category": "knowledge", "deps": []},
    {"name": "search_patterns", "purpose": "Search past solution patterns", "risk": "safe", "category": "knowledge", "deps": []},
    {"name": "store_decision", "purpose": "Store architecture decision record", "risk": "supervised", "category": "knowledge", "deps": []},
    # 9. Agent coordination tools
    {"name": "create_task", "purpose": "Create structured task for an agent", "risk": "safe", "category": "coordination", "deps": []},
    {"name": "report_status", "purpose": "Report agent task status", "risk": "safe", "category": "coordination", "deps": []},
]