"""Filesystem tools for bea-team agents."""
from __future__ import annotations

import ast
from pathlib import Path

from ._base import REPO_ROOT, ToolResult, _timed, is_protected


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
        local_imports = [i for i in imports if not i["module"].startswith((
            "os", "sys", "re", "json", "time", "uuid", "pathlib", "enum", "typing",
            "dataclasses", "abc", "asyncio", "logging", "subprocess", "shutil",
            "hashlib", "collections", "functools", "importlib", "inspect",
            "traceback", "datetime", "copy", "math", "random", "socket",
            "pydantic", "structlog", "langchain", "openai", "httpx", "pytest",
        ))]
        return ToolResult(
            success=True, tool="detect_file_dependencies",
            data={"path": str(p.relative_to(REPO_ROOT)), "imports": local_imports, "total": len(imports)},
        )
    except SyntaxError as e:
        return ToolResult(success=False, tool="detect_file_dependencies", error=f"Syntax error: {e}")
    except FileNotFoundError:
        return ToolResult(success=False, tool="detect_file_dependencies", error=f"File not found: {path}")
