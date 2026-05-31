"""
core/tools/file_tool.py — Structured file read/write tool + standalone functions.

LOW risk for read, MEDIUM for write.
Sandboxed to workspace directory.

Standalone functions (used by tool_executor.py):
    search_in_files, replace_in_file, create_directory,
    list_project_structure, count_lines,
    file_create, file_delete_safe, workspace_snapshot
"""
from __future__ import annotations

import os
import re
import logging
import subprocess  # nosec B404
from pathlib import Path

from core.tools.tool_template import BaseTool, ToolResult

log = logging.getLogger("jarvis.tools.file")

_WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/app/workspace"))
_MAX_READ_CHARS = 100_000
_MAX_WRITE_CHARS = 50_000
_ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".log", ".py", ".html"}


def _safe_path(path_str: str) -> Path | None:
    """Resolve path within workspace sandbox. Returns None if escape attempt."""
    try:
        target = (_WORKSPACE / path_str).resolve()
        if not str(target).startswith(str(_WORKSPACE.resolve())):
            return None
        return target
    except Exception:
        return None


class FileReadTool(BaseTool):
    name = "file_read"
    risk_level = "LOW"
    description = "Read file contents from workspace"
    timeout_seconds = 5.0

    def execute(self, path: str = "", **kw) -> ToolResult:
        if not path:
            return ToolResult(ok=False, error="missing_path")

        safe = _safe_path(path)
        if safe is None:
            return ToolResult(ok=False, error="path_escape: must stay within workspace")

        if not safe.exists():
            return ToolResult(ok=False, error=f"file_not_found: {path}")
        if not safe.is_file():
            return ToolResult(ok=False, error=f"not_a_file: {path}")
        if safe.suffix not in _ALLOWED_EXTENSIONS and safe.suffix:
            return ToolResult(ok=False, error=f"extension_not_allowed: {safe.suffix}")

        try:
            content = safe.read_text(encoding="utf-8")
            if len(content) > _MAX_READ_CHARS:
                content = content[:_MAX_READ_CHARS] + f"\n\n[truncated at {_MAX_READ_CHARS} chars]"
            return ToolResult(ok=True, result=content)
        except UnicodeDecodeError:
            return ToolResult(ok=False, error="binary_file: cannot read as text")
        except Exception as e:
            return ToolResult(ok=False, error=f"read_error: {str(e)[:200]}")


class FileWriteTool(BaseTool):
    name = "file_write"
    risk_level = "MEDIUM"
    description = "Write content to file in workspace"
    timeout_seconds = 5.0

    def execute(self, path: str = "", content: str = "", append: bool = False, **kw) -> ToolResult:
        if not path:
            return ToolResult(ok=False, error="missing_path")
        if not content:
            return ToolResult(ok=False, error="missing_content")
        if len(content) > _MAX_WRITE_CHARS:
            return ToolResult(ok=False, error=f"content_too_large: {len(content)} > {_MAX_WRITE_CHARS}")

        safe = _safe_path(path)
        if safe is None:
            return ToolResult(ok=False, error="path_escape: must stay within workspace")

        if safe.suffix not in _ALLOWED_EXTENSIONS and safe.suffix:
            return ToolResult(ok=False, error=f"extension_not_allowed: {safe.suffix}")

        try:
            safe.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(safe, mode, encoding="utf-8") as f:
                f.write(content)
            action = "appended to" if append else "wrote"
            return ToolResult(ok=True, result=f"{action} {path} ({len(content)} chars)")
        except Exception as e:
            return ToolResult(ok=False, error=f"write_error: {str(e)[:200]}")


# ── Standalone functions (used by tool_executor.py) ───────────────────────────
# These are the canonical tool functions called by the execution engine.
# All are sandboxed to _WORKSPACE and fail-open (return error strings, never raise).


def search_in_files(directory: str = ".", pattern: str = "", **kw) -> str:
    """Search for a text pattern in files recursively within the workspace.

    Uses subprocess grep for performance. Falls back to pure-Python if grep
    is unavailable.

    Args:
        directory: Relative path within workspace to search (default: root).
        pattern: Regex or literal pattern to search for.

    Returns:
        Matching lines as "file:line_number:content" or an error string.
    """
    if not pattern:
        return "error: missing 'pattern' argument"

    search_root = _safe_path(directory or ".")
    if search_root is None:
        return "error: path_escape — directory must be within workspace"
    if not search_root.exists():
        return f"error: directory not found: {directory}"

    try:
        result = subprocess.run(  # nosec B603 B607
            ["grep", "-rn", "--include=*.py", "--include=*.md", "--include=*.txt",
             "--include=*.json", "--include=*.yaml", "--include=*.yml",
             "--include=*.html", "--include=*.js", "--include=*.ts",
             "-I",  # skip binary files
             pattern, str(search_root)],
            capture_output=True, text=True, timeout=30,
            cwd=str(_WORKSPACE),
        )
        output = result.stdout.strip()
        if not output:
            return f"No matches found for pattern '{pattern}' in {directory}"
        # Truncate if too large
        lines = output.split("\n")
        if len(lines) > 200:
            output = "\n".join(lines[:200]) + f"\n\n[truncated: {len(lines)} total matches]"
        return output
    except FileNotFoundError:
        # grep not available — pure Python fallback
        return _search_in_files_python(search_root, pattern)
    except subprocess.TimeoutExpired:
        return "error: search timed out after 30s"
    except Exception as e:
        return f"error: {str(e)[:200]}"


def _search_in_files_python(root: Path, pattern: str) -> str:
    """Pure-Python fallback for search_in_files."""
    matches = []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = None

    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        if fpath.suffix not in _ALLOWED_EXTENSIONS:
            continue
        try:
            for i, line in enumerate(fpath.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                hit = (compiled.search(line) if compiled else pattern in line)
                if hit:
                    rel = fpath.relative_to(_WORKSPACE)
                    matches.append(f"{rel}:{i}:{line.rstrip()}")
                    if len(matches) >= 200:
                        matches.append("\n[truncated at 200 matches]")
                        return "\n".join(matches)
        except Exception:
            continue

    return "\n".join(matches) if matches else f"No matches found for '{pattern}'"


def replace_in_file(path: str = "", old_text: str = "", new_text: str = "", **kw) -> str:
    """Replace exact text in a file. Returns confirmation or error."""
    if not path or not old_text:
        return "error: missing 'path' or 'old_text' argument"

    safe = _safe_path(path)
    if safe is None:
        return "error: path_escape — must stay within workspace"
    if not safe.exists():
        return f"error: file not found: {path}"

    try:
        content = safe.read_text(encoding="utf-8")
        if old_text not in content:
            return f"error: old_text not found in {path}"
        new_content = content.replace(old_text, new_text, 1)
        safe.write_text(new_content, encoding="utf-8")
        return f"Replaced in {path} ({len(old_text)} chars → {len(new_text)} chars)"
    except Exception as e:
        return f"error: {str(e)[:200]}"


def create_directory(path: str = "", **kw) -> str:
    """Create a directory within the workspace."""
    if not path:
        return "error: missing 'path' argument"

    safe = _safe_path(path)
    if safe is None:
        return "error: path_escape — must stay within workspace"

    try:
        safe.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path}"
    except Exception as e:
        return f"error: {str(e)[:200]}"


def list_project_structure(directory: str = ".", max_depth: int = 3, **kw) -> str:
    """List project file structure as a tree."""
    root = _safe_path(directory or ".")
    if root is None:
        return "error: path_escape"
    if not root.exists():
        return f"error: directory not found: {directory}"

    lines = []
    _SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}

    def _walk(p: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return
        for i, entry in enumerate(entries):
            if entry.name in _SKIP:
                continue
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    lines.append(str(root.relative_to(_WORKSPACE)) if root != _WORKSPACE else ".")
    _walk(root, "", 1)

    output = "\n".join(lines)
    if len(output) > _MAX_READ_CHARS:
        output = output[:_MAX_READ_CHARS] + "\n[truncated]"
    return output


def count_lines(path: str = "", **kw) -> str:
    """Count lines in a file or directory."""
    safe = _safe_path(path or ".")
    if safe is None:
        return "error: path_escape"
    if not safe.exists():
        return f"error: not found: {path}"

    if safe.is_file():
        try:
            count = len(safe.read_text(encoding="utf-8", errors="ignore").splitlines())
            return f"{path}: {count} lines"
        except Exception as e:
            return f"error: {str(e)[:200]}"

    # Directory: count all source files
    total = 0
    file_counts = []
    for fpath in safe.rglob("*.py"):
        if "__pycache__" in str(fpath):
            continue
        try:
            c = len(fpath.read_text(encoding="utf-8", errors="ignore").splitlines())
            total += c
            file_counts.append((str(fpath.relative_to(_WORKSPACE)), c))
        except Exception:
            continue

    file_counts.sort(key=lambda x: -x[1])
    top = file_counts[:20]
    result = f"Total: {total} lines in {len(file_counts)} .py files\n\nTop 20:\n"
    for fp, c in top:
        result += f"  {c:>6}  {fp}\n"
    return result


def file_create(path: str = "", content: str = "", **kw) -> str:
    """Create a new file with content. Fails if file already exists."""
    if not path:
        return "error: missing 'path' argument"

    safe = _safe_path(path)
    if safe is None:
        return "error: path_escape"
    if safe.exists():
        return f"error: file already exists: {path} (use replace_in_file to modify)"

    try:
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content or "", encoding="utf-8")
        return f"Created {path} ({len(content or '')} chars)"
    except Exception as e:
        return f"error: {str(e)[:200]}"


def file_delete_safe(path: str = "", **kw) -> str:
    """Soft-delete a file by moving it to .trash/ in workspace."""
    if not path:
        return "error: missing 'path' argument"

    safe = _safe_path(path)
    if safe is None:
        return "error: path_escape"
    if not safe.exists():
        return f"error: not found: {path}"

    try:
        trash = _WORKSPACE / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / safe.name
        # Handle name collisions
        counter = 1
        while dest.exists():
            dest = trash / f"{safe.stem}_{counter}{safe.suffix}"
            counter += 1
        safe.rename(dest)
        return f"Moved {path} → .trash/{dest.name} (recoverable)"
    except Exception as e:
        return f"error: {str(e)[:200]}"


def workspace_snapshot(**kw) -> str:
    """Return a snapshot of the workspace: file count, total size, structure."""
    try:
        files = list(_WORKSPACE.rglob("*"))
        py_files = [f for f in files if f.suffix == ".py" and f.is_file() and "__pycache__" not in str(f)]
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        dirs = set()
        for f in files:
            if f.is_dir() and f.name not in {".git", "__pycache__", "node_modules"}:
                try:
                    dirs.add(str(f.relative_to(_WORKSPACE)).split("/")[0])
                except Exception as _exc:
                    log.warning("swallowed_exception", action="file_tool_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return (
            f"Workspace: {_WORKSPACE}\n"
            f"Total files: {len([f for f in files if f.is_file()])}\n"
            f"Python files: {len(py_files)}\n"
            f"Total size: {total_size / 1024 / 1024:.1f} MB\n"
            f"Top-level dirs: {', '.join(sorted(dirs))}"
        )
    except Exception as e:
        return f"error: {str(e)[:200]}"
