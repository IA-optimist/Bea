"""
core/tools/file_tool.py — Structured file read/write tool.

LOW risk for read, MEDIUM for write.
Sandboxed to workspace directory.
"""
from __future__ import annotations

import json
import os
import logging
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


# ──────────────────────────────────────────────────────────────────────────────
# Legacy function-based tools (imported by tool_executor.py)
# ──────────────────────────────────────────────────────────────────────────────

def _ok_legacy(output: str, logs: list = None) -> dict:
    """Helper for legacy function return format."""
    return {
        "ok": True,
        "status": "ok",
        "output": output,
        "result": output,
        "error": None,
        "logs": logs or [],
        "risk_level": "low",
    }


def _err_legacy(error: str, logs: list = None) -> dict:
    """Helper for legacy function error format."""
    return {
        "ok": False,
        "status": "error",
        "output": "",
        "result": "",
        "error": error,
        "logs": logs or [],
        "risk_level": "low",
    }


def search_in_files(directory: str, pattern: str) -> dict:
    """
    Search for pattern in files recursively within directory.
    Uses grep -r for recursive search within workspace sandbox.
    
    Args:
        directory: Directory path (relative to workspace)
        pattern: Search pattern (string literal, not regex)
    
    Returns:
        dict with ok/error/output/logs fields
    """
    import subprocess
    
    logs = [f"search_in_files: directory={directory}, pattern={pattern}"]
    
    if not directory:
        return _err_legacy("missing_directory", logs=logs)
    if not pattern:
        return _err_legacy("missing_pattern", logs=logs)
    
    # Sandbox check
    safe = _safe_path(directory)
    if safe is None:
        return _err_legacy(f"path_escape: {directory} must stay within workspace", logs=logs)
    
    if not safe.exists():
        return _err_legacy(f"directory_not_found: {directory}", logs=logs)
    
    if not safe.is_dir():
        return _err_legacy(f"not_a_directory: {directory}", logs=logs)
    
    try:
        # Use grep -r (recursive) with fixed-string mode for safety
        # -n: line numbers
        # -H: show filename
        # -I: skip binary files
        # -F: fixed string (not regex)
        cmd = ["grep", "-rnHIF", pattern, str(safe)]
        
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_WORKSPACE)
        )
        
        # grep returns 0 if matches found, 1 if no matches, >1 for errors
        if proc.returncode > 1:
            return _err_legacy(
                f"grep_error: rc={proc.returncode}, stderr={proc.stderr[:200]}",
                logs=logs
            )
        
        output = proc.stdout
        if not output:
            return _ok_legacy("no_matches_found", logs=logs + ["matches=0"])
        
        # Truncate if too large
        lines = output.split("\n")
        match_count = len([l for l in lines if l.strip()])
        
        if len(output) > _MAX_READ_CHARS:
            output = output[:_MAX_READ_CHARS] + f"\n\n[truncated at {_MAX_READ_CHARS} chars, {match_count} matches]"
        
        logs.append(f"matches={match_count}")
        return _ok_legacy(output, logs=logs)
        
    except subprocess.TimeoutExpired:
        return _err_legacy("timeout_exceeded", logs=logs)
    except FileNotFoundError:
        return _err_legacy("grep_not_found: grep not available", logs=logs)
    except Exception as e:
        return _err_legacy(f"search_error: {str(e)[:200]}", logs=logs)


def replace_in_file(path: str, old_text: str, new_text: str) -> dict:
    """
    Replace old_text with new_text in file.
    
    Args:
        path: File path (relative to workspace)
        old_text: Text to find
        new_text: Replacement text
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = [f"replace_in_file: path={path}"]
    
    if not path or not old_text:
        return _err_legacy("missing_required_params", logs=logs)
    
    safe = _safe_path(path)
    if safe is None:
        return _err_legacy(f"path_escape: {path}", logs=logs)
    
    if not safe.exists():
        return _err_legacy(f"file_not_found: {path}", logs=logs)
    
    try:
        content = safe.read_text(encoding="utf-8")
        
        if old_text not in content:
            return _err_legacy(f"text_not_found: '{old_text[:50]}...'", logs=logs)
        
        new_content = content.replace(old_text, new_text)
        safe.write_text(new_content, encoding="utf-8")
        
        count = content.count(old_text)
        logs.append(f"replaced={count}_occurrences")
        return _ok_legacy(f"replaced {count} occurrence(s)", logs=logs)
        
    except Exception as e:
        return _err_legacy(f"replace_error: {str(e)[:200]}", logs=logs)


def create_directory(path: str) -> dict:
    """
    Create directory (and parents if needed).
    
    Args:
        path: Directory path (relative to workspace)
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = [f"create_directory: path={path}"]
    
    if not path:
        return _err_legacy("missing_path", logs=logs)
    
    safe = _safe_path(path)
    if safe is None:
        return _err_legacy(f"path_escape: {path}", logs=logs)
    
    try:
        safe.mkdir(parents=True, exist_ok=True)
        logs.append("created")
        return _ok_legacy(f"created directory: {path}", logs=logs)
    except Exception as e:
        return _err_legacy(f"mkdir_error: {str(e)[:200]}", logs=logs)


def list_project_structure(directory: str = ".") -> dict:
    """
    List directory structure as tree.
    
    Args:
        directory: Directory path (relative to workspace)
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = [f"list_project_structure: directory={directory}"]
    
    safe = _safe_path(directory)
    if safe is None:
        return _err_legacy(f"path_escape: {directory}", logs=logs)
    
    if not safe.exists():
        return _err_legacy(f"directory_not_found: {directory}", logs=logs)
    
    try:
        lines = []
        for root, dirs, files in os.walk(safe):
            level = root.replace(str(safe), "").count(os.sep)
            indent = " " * 2 * level
            lines.append(f"{indent}{os.path.basename(root)}/")
            sub_indent = " " * 2 * (level + 1)
            for file in files:
                lines.append(f"{sub_indent}{file}")
        
        output = "\n".join(lines[:1000])  # Limit to 1000 lines
        if len(lines) > 1000:
            output += f"\n\n[truncated at 1000 lines, total={len(lines)}]"
        
        return _ok_legacy(output, logs=logs)
    except Exception as e:
        return _err_legacy(f"list_error: {str(e)[:200]}", logs=logs)


def count_lines(path: str) -> dict:
    """
    Count lines in file.
    
    Args:
        path: File path (relative to workspace)
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = [f"count_lines: path={path}"]
    
    if not path:
        return _err_legacy("missing_path", logs=logs)
    
    safe = _safe_path(path)
    if safe is None:
        return _err_legacy(f"path_escape: {path}", logs=logs)
    
    if not safe.exists():
        return _err_legacy(f"file_not_found: {path}", logs=logs)
    
    try:
        with open(safe, 'r', encoding='utf-8') as f:
            lines = sum(1 for _ in f)
        
        logs.append(f"lines={lines}")
        return _ok_legacy(f"{lines} lines", logs=logs)
    except Exception as e:
        return _err_legacy(f"count_error: {str(e)[:200]}", logs=logs)


def file_create(path: str, content: str = "") -> dict:
    """
    Create new file with optional content.
    
    Args:
        path: File path (relative to workspace)
        content: Initial content (optional)
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = [f"file_create: path={path}"]
    
    if not path:
        return _err_legacy("missing_path", logs=logs)
    
    safe = _safe_path(path)
    if safe is None:
        return _err_legacy(f"path_escape: {path}", logs=logs)
    
    if safe.exists():
        return _err_legacy(f"file_already_exists: {path}", logs=logs)
    
    try:
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")
        logs.append(f"created_size={len(content)}")
        return _ok_legacy(f"created file: {path}", logs=logs)
    except Exception as e:
        return _err_legacy(f"create_error: {str(e)[:200]}", logs=logs)


def file_delete_safe(path: str) -> dict:
    """
    Delete file (with confirmation via logs).
    
    Args:
        path: File path (relative to workspace)
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = [f"file_delete_safe: path={path}"]
    
    if not path:
        return _err_legacy("missing_path", logs=logs)
    
    safe = _safe_path(path)
    if safe is None:
        return _err_legacy(f"path_escape: {path}", logs=logs)
    
    if not safe.exists():
        return _err_legacy(f"file_not_found: {path}", logs=logs)
    
    if not safe.is_file():
        return _err_legacy(f"not_a_file: {path}", logs=logs)
    
    try:
        safe.unlink()
        logs.append("deleted")
        return _ok_legacy(f"deleted file: {path}", logs=logs)
    except Exception as e:
        return _err_legacy(f"delete_error: {str(e)[:200]}", logs=logs)


def workspace_snapshot() -> dict:
    """
    Generate snapshot of workspace state.
    
    Returns:
        dict with ok/error/output/logs fields
    """
    logs = ["workspace_snapshot"]
    
    try:
        stats = {
            "total_files": 0,
            "total_size": 0,
            "file_types": {},
        }
        
        for root, _, files in os.walk(_WORKSPACE):
            for file in files:
                stats["total_files"] += 1
                file_path = Path(root) / file
                try:
                    stats["total_size"] += file_path.stat().st_size
                    ext = file_path.suffix or "(no_ext)"
                    stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
                except (OSError, PermissionError) as e:
                    logger.debug(f"Cannot stat {file_path}: {e}")
        
        output = f"Workspace: {_WORKSPACE}\n"
        output += f"Total files: {stats['total_files']}\n"
        output += f"Total size: {stats['total_size'] / 1024:.2f} KB\n"
        output += "File types:\n"
        for ext, count in sorted(stats["file_types"].items(), key=lambda x: -x[1])[:20]:
            output += f"  {ext}: {count}\n"
        
        return _ok_legacy(output, logs=logs)
    except Exception as e:
        return _err_legacy(f"snapshot_error: {str(e)[:200]}", logs=logs)
