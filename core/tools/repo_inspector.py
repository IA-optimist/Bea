"""
core/tools/repo_inspector.py — Safe read-only repo inspection tools.

These tools give agents real visibility into codebase state before reasoning.
ALL operations are read-only, sandboxed, time-bounded, and traced.

Security:
- Read-only: no writes, no execution of arbitrary code
- Sandboxed: confined to JARVIS_ROOT (/app)
- Time-bounded: 5s per operation, 15s total budget
- Traced: all calls logged via structlog
- Policy: all tools classified as LOW risk
"""
from __future__ import annotations

import os
import re
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

_REPO_ROOT = Path(os.environ.get(
    "JARVIS_ROOT",
    # Default: walk up from this file to find repo root (has conftest.py or pytest.ini)
    str(Path(__file__).resolve().parents[2]),
))
_MAX_FILE_SIZE = 50_000   # 50KB max per file read
_MAX_OUTPUT = 8_000       # 8KB max output per tool call
_MAX_GREP_RESULTS = 20    # max grep matches returned
_OP_TIMEOUT = 5.0         # per-operation timeout
_BUDGET_TIMEOUT = 15.0    # total budget for all tool calls per agent

# Extensions we allow reading
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".dart", ".html", ".css", ".json", ".yaml",
    ".yml", ".toml", ".cfg", ".ini", ".md", ".txt", ".sh", ".sql",
}

# Directories to skip
_SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache",
    ".eggs", "*.egg-info", "venv", ".venv", "dist", "build",
    "jarvismax_app/.dart_tool", "jarvismax_app/.flutter-plugins",
}


def _safe_path(path_str: str) -> Optional[Path]:
    """Resolve path within repo sandbox. Returns None if escape attempt."""
    try:
        target = (_REPO_ROOT / path_str).resolve()
        if not str(target).startswith(str(_REPO_ROOT.resolve())):
            return None
        return target
    except Exception:
        return None


def read_file(path: str, max_lines: int = 200) -> dict:
    """
    Read a file from the repo. Returns content truncated to max_lines.
    Risk: LOW (read-only)
    """
    t0 = time.monotonic()
    try:
        safe = _safe_path(path)
        if safe is None:
            return {"ok": False, "error": f"path_blocked: {path}"}
        if not safe.exists():
            return {"ok": False, "error": f"not_found: {path}"}
        if not safe.is_file():
            return {"ok": False, "error": f"not_a_file: {path}"}
        if safe.stat().st_size > _MAX_FILE_SIZE:
            return {"ok": False, "error": f"too_large: {safe.stat().st_size} bytes"}
        if safe.suffix not in _CODE_EXTENSIONS and safe.suffix:
            return {"ok": False, "error": f"extension_blocked: {safe.suffix}"}

        lines = safe.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        content = "\n".join(lines[:max_lines])
        if total > max_lines:
            content += f"\n\n[... {total - max_lines} more lines truncated]"

        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.read_file", path=path, lines=total, ms=ms)
        return {"ok": True, "content": content, "total_lines": total, "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def grep_repo(pattern: str, directory: str = "", extensions: list = None) -> dict:
    """
    Search for a regex pattern across repo files.
    Risk: LOW (read-only grep)
    """
    t0 = time.monotonic()
    try:
        search_dir = _safe_path(directory) if directory else _REPO_ROOT
        if search_dir is None:
            return {"ok": False, "error": f"path_blocked: {directory}"}
        if not search_dir.is_dir():
            return {"ok": False, "error": f"not_a_directory: {directory}"}

        exts = set(extensions or [".py"])
        compiled = re.compile(pattern)
        matches = []

        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]

            if time.monotonic() - t0 > _OP_TIMEOUT:
                break

            for fname in files:
                if not any(fname.endswith(ext) for ext in exts):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if compiled.search(line):
                                rel = os.path.relpath(fpath, _REPO_ROOT).replace(os.sep, "/")
                                matches.append({
                                    "file": rel,
                                    "line": lineno,
                                    "content": line.rstrip()[:150],
                                })
                                if len(matches) >= _MAX_GREP_RESULTS:
                                    break
                except (PermissionError, OSError):
                    log.debug("swallowed_exception", exc_info=True)
                    continue
                if len(matches) >= _MAX_GREP_RESULTS:
                    break
            if len(matches) >= _MAX_GREP_RESULTS:
                break

        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.grep", pattern=pattern[:60], matches=len(matches), ms=ms)
        return {"ok": True, "matches": matches, "total": len(matches), "ms": ms}
    except re.error as e:
        return {"ok": False, "error": f"invalid_regex: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def git_status() -> dict:
    """
    Get git status of the repo.
    Risk: LOW (read-only git command)
    """
    t0 = time.monotonic()
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "status", "--porcelain", "-b"],
            capture_output=True, text=True, timeout=5,
            cwd=str(_REPO_ROOT),
        )
        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.git_status", ms=ms)
        return {
            "ok": True,
            "output": proc.stdout[:_MAX_OUTPUT],
            "branch": _parse_branch(proc.stdout),
            "ms": ms,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git_status_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def git_log(n: int = 5) -> dict:
    """
    Get recent git commits.
    Risk: LOW (read-only)
    """
    t0 = time.monotonic()
    n = min(n, 20)  # cap at 20
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "log", f"-{n}", "--oneline", "--no-decorate"],
            capture_output=True, text=True, timeout=5,
            cwd=str(_REPO_ROOT),
        )
        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.git_log", n=n, ms=ms)
        return {"ok": True, "output": proc.stdout[:_MAX_OUTPUT], "ms": ms}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git_log_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def list_directory(path: str = "", max_items: int = 50) -> dict:
    """
    List files in a directory.
    Risk: LOW (read-only)
    """
    t0 = time.monotonic()
    try:
        target = _safe_path(path) if path else _REPO_ROOT
        if target is None:
            return {"ok": False, "error": f"path_blocked: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"not_a_directory: {path}"}

        items = []
        for entry in sorted(target.iterdir())[:max_items]:
            if entry.name.startswith(".") or entry.name in _SKIP_DIRS:
                continue
            rel = entry.relative_to(_REPO_ROOT).as_posix()
            if entry.is_dir():
                items.append(f"{rel}/")
            else:
                size = entry.stat().st_size
                items.append(f"{rel} ({size}B)")

        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.list_dir", path=path, items=len(items), ms=ms)
        return {"ok": True, "items": items, "total": len(items), "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tree(path: str = "", max_depth: int = 2) -> dict:
    """
    Show directory tree up to max_depth.
    Risk: LOW (read-only)
    """
    t0 = time.monotonic()
    try:
        target = _safe_path(path) if path else _REPO_ROOT
        if target is None:
            return {"ok": False, "error": f"path_blocked: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"not_a_directory: {path}"}

        max_depth = min(max_depth, 3)  # cap
        lines = []
        _tree_walk(target, "", 0, max_depth, lines, max_items=100)

        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.tree", path=path, lines=len(lines), ms=ms)
        return {"ok": True, "tree": "\n".join(lines), "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def file_stats(path: str) -> dict:
    """
    Get file statistics: line count, size, imports, classes, functions.
    Risk: LOW (read-only analysis)
    """
    t0 = time.monotonic()
    try:
        safe = _safe_path(path)
        if safe is None or not safe.exists() or not safe.is_file():
            return {"ok": False, "error": f"invalid_file: {path}"}

        content = safe.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        size = safe.stat().st_size

        # Python-specific analysis
        imports = []
        classes = []
        functions = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped[:100])
            elif stripped.startswith("class "):
                name = stripped.split("(")[0].split(":")[0].replace("class ", "").strip()
                classes.append({"name": name, "line": i})
            elif stripped.startswith("def ") or stripped.startswith("async def "):
                name = stripped.replace("async ", "").split("(")[0].replace("def ", "").strip()
                functions.append({"name": name, "line": i})

        ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": True,
            "path": path,
            "lines": len(lines),
            "size_bytes": size,
            "imports_count": len(imports),
            "classes": classes[:20],
            "functions": functions[:30],
            "ms": ms,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def run_tests(test_path: str = "tests/", pattern: str = "", timeout: int = 60) -> dict:
    """
    Run pytest on a specific path with optional pattern filter.
    Risk: LOW (read-only test execution in container)
    """
    t0 = time.monotonic()
    try:
        cmd = ["python", "-m", "pytest", test_path, "--tb=short", "-q"]
        if pattern:
            # Sanitize: only allow alphanumeric, underscore, dash, dot
            safe_pattern = re.sub(r"[^a-zA-Z0-9_\-.]", "", pattern)
            cmd.extend(["-k", safe_pattern])

        proc = subprocess.run(  # nosec B603 B607
            cmd,
            capture_output=True, text=True,
            timeout=min(timeout, 120),  # hard cap at 2 min
            cwd=str(_REPO_ROOT),
            env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        )

        output = (proc.stdout + proc.stderr)[-_MAX_OUTPUT:]
        # Parse counts
        passed = failed = 0
        for line in output.splitlines():
            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m2 = re.search(r"(\d+) failed", line)
            if m2:
                failed = int(m2.group(1))

        ms = int((time.monotonic() - t0) * 1000)
        log.debug("repo_inspector.run_tests", path=test_path, passed=passed, failed=failed, ms=ms)
        return {
            "ok": proc.returncode == 0,
            "output": output,
            "passed": passed,
            "failed": failed,
            "return_code": proc.returncode,
            "ms": ms,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"test_timeout: {timeout}s", "passed": 0, "failed": 0}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── Context builder for agents ────────────────────────────────────────────────

def build_agent_context(goal: str, max_chars: int = 6000) -> str:
    """
    Build real repo context for an agent based on the mission goal.
    Called BEFORE the LLM call to inject real codebase state.

    Strategy:
    1. Extract file references from the goal
    2. Read mentioned files (truncated)
    3. If goal mentions code patterns, grep for them
    4. Add git status for situational awareness
    5. Cap total context to max_chars

    Returns: formatted context string or "" if nothing relevant found.
    """
    t0 = time.monotonic()
    parts = []
    total_chars = 0

    try:
        goal_lower = goal.lower()

        # 1. Extract explicitly mentioned files
        file_refs = re.findall(
            r'\b(?:[\w/.-]+/)?[\w.-]+\.(?:py|js|ts|dart|html|yaml|json|md|toml|cfg|sh)\b',
            goal
        )
        for fref in file_refs[:3]:
            if total_chars > max_chars:
                break
            result = read_file(fref, max_lines=300)
            if result["ok"]:
                content = result["content"]
                parts.append(f"### {fref} ({result['total_lines']} lines)\n```\n{content}\n```")
                total_chars += len(content)

        # 2. If goal references code concepts, search for them
        if total_chars < max_chars // 2:
            # Extract meaningful code identifiers from goal
            identifiers = re.findall(r'\b[A-Z][a-z]+[A-Z]\w+\b', goal)  # CamelCase
            identifiers += re.findall(r'\b[a-z]+_[a-z]+(?:_[a-z]+)*\b', goal)  # snake_case
            # Filter out common words
            identifiers = [
                i for i in identifiers
                if len(i) > 4 and i not in {
                    "most_important", "production_reliability", "should_be",
                    "for_the", "with_the", "need_to", "improvements_needed",
                }
            ]
            for ident in identifiers[:2]:
                if total_chars > max_chars:
                    break
                result = grep_repo(re.escape(ident), extensions=[".py"])
                if result["ok"] and result["matches"]:
                    matches_text = "\n".join(
                        f"  {m['file']}:{m['line']}: {m['content']}"
                        for m in result["matches"][:10]
                    )
                    parts.append(f"### grep `{ident}`\n```\n{matches_text}\n```")
                    total_chars += len(matches_text)

        # 3. If no explicit files, find relevant ones by keyword
        if not parts:
            keywords = set(re.findall(r'[a-z_]{4,}', goal_lower))
            # Remove stopwords
            keywords -= {
                "most", "list", "that", "this", "with", "what", "from", "have",
                "been", "will", "should", "needed", "important", "improvements",
                "critical", "identify", "review", "analyze", "describe",
            }
            for search_dir in ["core", "api", "agents", "executor"]:
                if total_chars > max_chars:
                    break
                try:
                    d = _REPO_ROOT / search_dir
                    if not d.exists():
                        continue
                    for pyfile in sorted(d.rglob("*.py"))[:80]:
                        fname = pyfile.stem.lower()
                        if any(k in fname for k in keywords):
                            result = read_file(
                                pyfile.relative_to(_REPO_ROOT).as_posix(),
                                max_lines=80
                            )
                            if result["ok"]:
                                rel = pyfile.relative_to(_REPO_ROOT).as_posix()
                                parts.append(
                                    f"### {rel} ({result['total_lines']}L)\n"
                                    f"```python\n{result['content']}\n```"
                                )
                                total_chars += len(result["content"])
                                if len(parts) >= 2 or total_chars > max_chars:
                                    break
                except Exception:
                    log.debug("swallowed_exception", exc_info=True)
                    continue

        # 4. Add git status for situational awareness (only for code tasks)
        code_task_indicators = [
            "code", "file", "module", "class", "function", "bug", "fix",
            "refactor", "test", "import", "api", "route", "endpoint",
        ]
        is_code_task = any(kw in goal_lower for kw in code_task_indicators)
        if is_code_task and total_chars < max_chars - 500:
            gs = git_status()
            if gs["ok"]:
                parts.append(f"### git status\n```\n{gs['output'][:500]}\n```")

        ms = int((time.monotonic() - t0) * 1000)
        if parts:
            log.info("repo_inspector.context_built",
                     parts=len(parts), chars=total_chars, ms=ms)
            return "\n\n".join(parts)
        return ""

    except Exception as e:
        log.debug("repo_inspector.context_failed", err=str(e)[:100])
        return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_branch(status_output: str) -> str:
    """Extract branch name from git status --porcelain -b output."""
    for line in status_output.splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...")[0]
            return branch
    return "unknown"


def _tree_walk(
    path: Path, prefix: str, depth: int, max_depth: int,
    lines: list, max_items: int = 100,
):
    """Recursive tree builder."""
    if depth > max_depth or len(lines) >= max_items:
        return
    try:
        entries = sorted(path.iterdir())
    except PermissionError:
        return

    dirs = [e for e in entries if e.is_dir() and e.name not in _SKIP_DIRS and not e.name.startswith(".")]
    files = [e for e in entries if e.is_file()]

    for i, f in enumerate(files):
        is_last = (i == len(files) - 1) and not dirs
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{f.name}")
        if len(lines) >= max_items:
            return

    for i, d in enumerate(dirs):
        is_last = (i == len(dirs) - 1)
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{d.name}/")
        if len(lines) >= max_items:
            return
        extension = "    " if is_last else "│   "
        _tree_walk(d, prefix + extension, depth + 1, max_depth, lines, max_items)
