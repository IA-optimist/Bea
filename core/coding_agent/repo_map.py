"""Repository map for coding agents.

This Sprint 3 MVP indexes Python symbols and imports without requiring a new
runtime dependency. It is deliberately AST-based today, with a small extension
point so a future tree-sitter parser can replace `_analyze_file` while keeping
the same `RepoMap` contract used by agents and the SWE-lite harness.
"""
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
import sys

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".venv-c4-prep",
    "venv",
    "env",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".dart_tool",
}


@dataclass(frozen=True)
class SymbolInfo:
    path: str
    name: str
    kind: str
    lineno: int
    end_lineno: int
    token_estimate: int
    docstring: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportInfo:
    path: str
    module: str
    names: tuple[str, ...]
    lineno: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoMap:
    root: str
    files: tuple[str, ...]
    symbols: tuple[SymbolInfo, ...]
    imports: tuple[ImportInfo, ...]
    token_budget: int = 12000
    parser: str = "ast"

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": list(self.files),
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": [i.to_dict() for i in self.imports],
            "token_budget": self.token_budget,
            "parser": self.parser,
        }

    def rank_symbols(self, query: str, max_symbols: int = 80) -> list[SymbolInfo]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return list(self.symbols[:max_symbols])

        scored: list[tuple[float, int, SymbolInfo]] = []
        for index, symbol in enumerate(self.symbols):
            symbol_terms = _symbol_terms(symbol.name)
            haystack = " ".join([symbol.name, symbol.path, symbol.kind, symbol.docstring]).lower()
            score = 0.0
            for token in query_tokens:
                if token in symbol_terms:
                    score += 12.0
                elif token in symbol.name.lower():
                    score += 8.0
                if token in symbol.path.lower():
                    score += 3.0
                if token in symbol.docstring.lower():
                    score += 2.0
                if token in haystack:
                    score += 1.0
            if query_tokens.issubset(symbol_terms):
                extra_terms = max(0, len(symbol_terms - query_tokens))
                score += max(1.0, 8.0 - float(extra_terms))
            if "." not in symbol.name:
                score += 10.0
            else:
                score -= 4.0
            scored.append((score, -index, symbol))

        ranked = [item[2] for item in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)]
        return ranked[:max_symbols]

    def render(self, query: str = "", max_tokens: int = 12000, max_symbols: int = 80) -> str:
        ranked = self.rank_symbols(query, max_symbols=max_symbols)
        lines = [
            f"# Repo map ({self.parser}, budget={max_tokens} tokens)",
            f"root={self.root}",
            f"files={len(self.files)} symbols={len(self.symbols)} imports={len(self.imports)}",
            "",
        ]
        used = sum(len(line) for line in lines)

        lines.append("## Import graph")
        used += len(lines[-1])
        for import_info in self.imports[:120]:
            names = ", ".join(import_info.names)
            line = f"- {import_info.path}:{import_info.lineno} -> {import_info.module or '<relative>'} ({names})"
            if used + len(line) > max_tokens:
                break
            lines.append(line)
            used += len(line)

        lines.append("")
        lines.append("## Ranked symbols")
        used += 2
        for symbol in ranked:
            doc = _compact(symbol.docstring, 120)
            line = (
                f"- {symbol.path}:{symbol.lineno} {symbol.kind} {symbol.name} "
                f"({symbol.token_estimate} tokens)"
            )
            if doc:
                line += f" — {doc}"
            if used + len(line) > max_tokens:
                break
            lines.append(line)
            used += len(line)

        return "\n".join(lines)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", value.lower()) if len(token) >= 3}


def _symbol_terms(value: str) -> set[str]:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", value.replace(".", " ").replace("_", " "))
    return {token for token in re.findall(r"[a-z0-9]+", spaced.lower()) if len(token) >= 3}


def _compact(value: str, max_chars: int) -> str:
    text = " ".join(value.strip().split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _estimate_tokens(text: str) -> int:
    return max(1, len(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+|.", text)) // 2)


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _iter_python_files(root: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if _is_excluded(path):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())[:max_files]


def _docstring(node: ast.AST) -> str:
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return ast.get_docstring(node) or ""
    return ""


def _analyze_file(root: Path, path: Path) -> tuple[list[SymbolInfo], list[ImportInfo]]:
    rel = path.relative_to(root).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return [], []

    symbols: list[SymbolInfo] = []
    imports: list[ImportInfo] = []
    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            names = tuple(alias.name for alias in node.names)
            imports.append(ImportInfo(rel, "", names, node.lineno))
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            names = tuple(alias.name for alias in node.names)
            imports.append(ImportInfo(rel, node.module or "", names, node.lineno))
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            name = ".".join([*stack, node.name])
            symbols.append(_symbol(rel, name, "class", node))
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            name = ".".join([*stack, node.name])
            symbols.append(_symbol(rel, name, "function", node))
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            name = ".".join([*stack, node.name])
            symbols.append(_symbol(rel, name, "async_function", node))
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

    Visitor().visit(tree)
    return symbols, imports


def _symbol(path: str, name: str, kind: str, node: ast.AST) -> SymbolInfo:
    return SymbolInfo(
        path=path,
        name=name,
        kind=kind,
        lineno=getattr(node, "lineno", 0),
        end_lineno=getattr(node, "end_lineno", getattr(node, "lineno", 0)),
        token_estimate=_estimate_tokens(ast.unparse(node) if hasattr(ast, "unparse") else repr(node)),
        docstring=_docstring(node),
    )


def build_repo_map(root: str | Path = ".", max_files: int = 1000, token_budget: int = 12000) -> RepoMap:
    root_path = Path(root).resolve()
    files = _iter_python_files(root_path, max_files=max_files)
    symbols: list[SymbolInfo] = []
    imports: list[ImportInfo] = []
    for path in files:
        file_symbols, file_imports = _analyze_file(root_path, path)
        symbols.extend(file_symbols)
        imports.extend(file_imports)
    return RepoMap(
        root=root_path.as_posix(),
        files=tuple(path.relative_to(root_path).as_posix() for path in files),
        symbols=tuple(symbols),
        imports=tuple(imports),
        token_budget=token_budget,
    )


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a coding-agent repo map.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--max-files", type=int, default=1000)
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--max-symbols", type=int, default=80)
    parser.add_argument("--query", default="", help="Optional relevance query.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_map = build_repo_map(args.root, max_files=args.max_files, token_budget=args.max_tokens)
    sys.stdout.write(repo_map.render(args.query, max_tokens=args.max_tokens, max_symbols=args.max_symbols) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
