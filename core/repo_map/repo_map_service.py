"""
core/repo_map/repo_map_service.py — Operational repo-map for agent coders.

Wraps the existing AST repo-map (core.coding_agent.repo_map) and persists
the most useful facts as MemoryItem objects:
    - repo_fact   : file type, key symbols, import footprint
    - test_map    : likely tests for a source file

No heavy refactoring: build_repo_map is reused as-is. This layer only adds
memory storage and simple lookups.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.coding_agent.repo_map import RepoMap, SymbolInfo, build_repo_map
from core.memory.memory_item import MemoryItem, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


# File categories used as tags / repo_fact source
def _categorize_file(path: str) -> str:
    name = Path(path).name
    if "test" in path.lower() or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if "routes" in path.lower() or name == "routes.py":
        return "api_router"
    if "model" in path.lower():
        return "model"
    if path.startswith("core/"):
        return "core"
    if path.startswith("api/"):
        return "api"
    return "module"


def _guess_tests_for_file(path: str, repo_files: list[str]) -> list[str]:
    """Heuristic: find tests that likely cover a source file."""
    stem = Path(path).stem
    candidates: list[str] = []
    for f in repo_files:
        if "test" not in f.lower():
            continue
        name = Path(f).stem
        # Direct match: test_<stem>.py or <stem>_test.py
        if name == f"test_{stem}" or name == f"{stem}_test":
            candidates.append(f)
            continue
        # Parent directory hints
        path_parts = Path(path).parts
        file_parts = Path(f).parts
        if any(part and part in path_parts for part in file_parts[:-1] if part):
            candidates.append(f)
    # Deduplicate while preserving order
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def repo_fact_for_file(path: str, repo_map: RepoMap) -> MemoryItem:
    """Build a repo_fact MemoryItem for a single source file."""
    symbols = [s for s in repo_map.symbols if s.path == path]
    category = _categorize_file(path)
    top_symbols = [f"{s.kind} {s.name}" for s in symbols[:10]]
    imports = [f"{i.module or '<relative>'} ({', '.join(i.names)})" for i in repo_map.imports if i.path == path][:10]

    content_parts = [f"File {path} is a {category}."]
    if top_symbols:
        content_parts.append("Symbols: " + "; ".join(top_symbols))
    if imports:
        content_parts.append("Imports: " + "; ".join(imports))

    return MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title=f"{path} ({category})",
        content=" ".join(content_parts),
        related_files=[path],
        related_tests=_guess_tests_for_file(path, list(repo_map.files)),
        tags=[category, "repo_fact", "python"] + (["api"] if category == "api_router" else []),
        source="repo_map",
        confidence=0.9,
        metadata={"symbol_count": len(symbols), "category": category},
    )


def test_map_for_file(source_path: str, repo_map: RepoMap) -> MemoryItem | None:
    """Build a test_map MemoryItem when tests are detected for a source file."""
    tests = _guess_tests_for_file(source_path, list(repo_map.files))
    if not tests:
        return None
    return MemoryItem(
        type=MemoryItemType.TEST_MAP,
        title=f"Tests for {source_path}",
        content=f"Likely tests covering {source_path}: " + ", ".join(tests),
        related_files=[source_path],
        related_tests=tests,
        tags=["test_map", "tests", "python"],
        source="repo_map",
        confidence=0.75,
        metadata={"test_count": len(tests)},
    )


class RepoMapService:
    """
    Build a repo map and persist the useful atoms as MemoryItem.

    The full map can also be obtained as a RepoMap for prompt injection.
    """

    def __init__(
        self,
        root: str | Path = ".",
        store: OperationalMemoryStore | None = None,
        max_files: int = 1000,
    ) -> None:
        self.root = Path(root).resolve()
        self.store = store or get_operational_memory_store()
        self.max_files = max_files
        self._repo_map: RepoMap | None = None
        self._built_at: float = 0.0

    def build(self, force: bool = False) -> RepoMap:
        """Build or return cached RepoMap."""
        if not force and self._repo_map is not None:
            return self._repo_map
        self._repo_map = build_repo_map(self.root, max_files=self.max_files)
        self._built_at = time.time()
        return self._repo_map

    def persist(self, force: bool = False) -> dict[str, Any]:
        """Build repo map and store repo_fact + test_map items."""
        repo_map = self.build(force=force)
        self.store.add(self._root_fact(repo_map))

        source_files = [f for f in repo_map.files if not f.lower().startswith("test") and "test" not in Path(f).stem.lower()]
        stored_facts = 0
        stored_tests = 0
        for path in source_files:
            fact = repo_fact_for_file(path, repo_map)
            self.store.add(fact)
            stored_facts += 1
            tm = test_map_for_file(path, repo_map)
            if tm:
                self.store.add(tm)
                stored_tests += 1

        return {
            "root": str(self.root),
            "files": len(repo_map.files),
            "symbols": len(repo_map.symbols),
            "repo_facts_stored": stored_facts,
            "test_maps_stored": stored_tests,
            "built_at": self._built_at,
        }

    def _root_fact(self, repo_map: RepoMap) -> MemoryItem:
        return MemoryItem(
            type=MemoryItemType.REPO_FACT,
            title=f"Repo map of {self.root.name}",
            content=f"Repository {repo_map.root} contains {len(repo_map.files)} files and {len(repo_map.symbols)} symbols.",
            related_files=[],
            tags=["repo_map", "root", "python"],
            source="repo_map",
            confidence=0.99,
            metadata={"root": repo_map.root, "files": len(repo_map.files), "symbols": len(repo_map.symbols)},
        )

    def find_tests_for_file(self, path: str) -> list[str]:
        """Return likely tests for a source file using stored test_map memories."""
        results = self.store.search(
            type=MemoryItemType.TEST_MAP,
            related_files=[path],
            limit=5,
        )
        tests: list[str] = []
        for item in results:
            for t in item.related_tests:
                if t not in tests:
                    tests.append(t)
        return tests

    def find_symbols_for_file(self, path: str) -> list[SymbolInfo]:
        """Return symbols for a file from the cached repo map."""
        return [s for s in self.build().symbols if s.path == path]

    def get_repo_map(self) -> RepoMap:
        return self.build()

    def render(self, query: str = "", max_tokens: int = 12000, max_symbols: int = 80) -> str:
        return self.build().render(query, max_tokens=max_tokens, max_symbols=max_symbols)


_service: RepoMapService | None = None


def get_repo_map_service(root: str | Path = ".") -> RepoMapService:
    global _service
    if _service is None:
        _service = RepoMapService(root=root)
    return _service
