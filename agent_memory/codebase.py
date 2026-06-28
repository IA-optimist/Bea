"""
agent_memory/codebase.py — CodebaseMemoryService: AST + grep v1.

Wraps the existing core/coding_agent/repo_map.py with a stable interface
for codebase-memory-mcp adapter compatibility.  The interface is intentionally
simple so future upgrades (tree-sitter, LSP) are drop-in replacements.

This is a READ-ONLY service: no writes, no patches.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger("bea.agent_memory.codebase")


@dataclass
class SymbolInfo:
    """A single symbol found in the codebase."""

    name: str
    kind: str        # "function", "class", "method", "constant", etc.
    file_path: str
    line: int
    module: str = ""
    docstring: str = ""
    rank: float = 0.0  # repo-map rank (higher = more referenced)


@dataclass
class CodebaseSnapshot:
    """Snapshot of the codebase structure at a point in time."""

    root: str
    symbols: list[SymbolInfo]
    file_count: int
    total_lines: int
    top_symbols: list[str]  # top N by rank

    def find(self, name: str) -> list[SymbolInfo]:
        """Find symbols by name (case-insensitive)."""
        q = name.lower()
        return [s for s in self.symbols if q in s.name.lower()]

    def symbols_in_file(self, file_path: str) -> list[SymbolInfo]:
        p = file_path.replace("\\", "/")
        return [s for s in self.symbols if s.file_path.replace("\\", "/") == p]


class CodebaseMemoryService:
    """
    Stable interface for codebase analysis.

    Wraps core.coding_agent.repo_map.build_repo_map when available,
    falls back to a lightweight AST scan for testing / offline mode.
    Caches the snapshot per-session (call invalidate() to refresh).
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = str(root or Path.cwd())
        self._snapshot: CodebaseSnapshot | None = None

    def invalidate(self) -> None:
        self._snapshot = None

    def snapshot(self, force: bool = False) -> CodebaseSnapshot:
        if self._snapshot and not force:
            return self._snapshot
        self._snapshot = self._build_snapshot()
        return self._snapshot

    def _build_snapshot(self) -> CodebaseSnapshot:
        try:
            return self._build_via_repo_map()
        except Exception as exc:
            log.debug("codebase_repo_map_unavailable", reason=str(exc)[:120])
            return self._build_via_ast_scan()

    def _build_via_repo_map(self) -> CodebaseSnapshot:
        from core.coding_agent.repo_map import build_repo_map
        repo_map = build_repo_map(self.root)
        symbols: list[SymbolInfo] = []
        for file_entry in repo_map.files:
            for sym in file_entry.symbols:
                symbols.append(SymbolInfo(
                    name=sym.name,
                    kind=sym.kind,
                    file_path=file_entry.path,
                    line=sym.line,
                    module=file_entry.module or "",
                    rank=sym.rank,
                ))
        top = sorted(symbols, key=lambda s: s.rank, reverse=True)[:20]
        return CodebaseSnapshot(
            root=self.root,
            symbols=symbols,
            file_count=len(repo_map.files),
            total_lines=sum(f.line_count for f in repo_map.files),
            top_symbols=[s.name for s in top],
        )

    def _build_via_ast_scan(self) -> CodebaseSnapshot:
        """Lightweight AST scan fallback (no external deps)."""
        import ast as _ast
        symbols: list[SymbolInfo] = []
        root = Path(self.root)
        file_count = 0
        total_lines = 0
        for py_file in root.rglob("*.py"):
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
                lines = source.count("\n") + 1
                total_lines += lines
                file_count += 1
                tree = _ast.parse(source, filename=str(py_file))
                rel = str(py_file.relative_to(root)).replace("\\", "/")
                for node in _ast.walk(tree):
                    if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                        symbols.append(SymbolInfo(
                            name=node.name,
                            kind="function",
                            file_path=rel,
                            line=node.lineno,
                        ))
                    elif isinstance(node, _ast.ClassDef):
                        symbols.append(SymbolInfo(
                            name=node.name,
                            kind="class",
                            file_path=rel,
                            line=node.lineno,
                        ))
            except Exception:
                pass
        top = sorted(symbols, key=lambda s: s.name)[:20]
        return CodebaseSnapshot(
            root=self.root,
            symbols=symbols,
            file_count=file_count,
            total_lines=total_lines,
            top_symbols=[s.name for s in top],
        )

    def find_symbol(self, name: str) -> list[SymbolInfo]:
        return self.snapshot().find(name)

    def symbols_in_file(self, file_path: str) -> list[SymbolInfo]:
        return self.snapshot().symbols_in_file(file_path)

    def grep(self, pattern: str, *, file_glob: str = "*.py") -> list[dict[str, Any]]:
        """
        Grep for pattern in the codebase.  Returns list of
        {file, line, content} dicts.  Read-only.
        """
        import re
        import fnmatch
        results: list[dict[str, Any]] = []
        root = Path(self.root)
        try:
            compiled = re.compile(pattern)
        except re.error:
            compiled = re.compile(re.escape(pattern))
        for py_file in root.rglob("*"):
            if not fnmatch.fnmatch(py_file.name, file_glob):
                continue
            try:
                for i, line in enumerate(py_file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if compiled.search(line):
                        rel = str(py_file.relative_to(root)).replace("\\", "/")
                        results.append({"file": rel, "line": i, "content": line.rstrip()})
                        if len(results) >= 500:
                            return results
            except Exception:
                pass
        return results
