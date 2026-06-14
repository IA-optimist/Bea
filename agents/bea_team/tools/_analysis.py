"""Code analysis tools for bea-team agents."""
from __future__ import annotations

import ast
from pathlib import Path

import structlog

from ._base import REPO_ROOT, ToolResult, _timed

log = structlog.get_logger(__name__)


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

    mod_graph: dict[str, set[str]] = {}
    for file_path, deps in graph.items():
        mod = file_path.replace("/", ".").replace(".py", "")
        mod_graph[mod] = set(deps)

    cycles = []
    visited: set[str] = set()
    path_stack: list[str] = []

    def dfs(node: str) -> None:
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
    defined: dict[str, str] = {}
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
                complexity = 1
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
