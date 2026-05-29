"""
core/execution/graph_repository.py — Execution graph persistence + history.

Design:
  - Save/load graphs to JSON files (workspace/graphs/)
  - Resume: load graph, find next buildable node, continue
  - History: query past graphs by schema, mission, status
  - Atomic writes via .tmp → rename
  - Fail-open: persistence failure never blocks execution
"""
from __future__ import annotations

import json
import structlog
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.execution.execution_graph import ExecutionGraph
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("execution.graph_repository")


@dataclass
class GraphSummary:
    """Lightweight graph summary for listing."""
    graph_id: str
    source_schema: str
    goal: str
    mission_id: str
    node_count: int
    progress: float
    created_at: float

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "source_schema": self.source_schema,
            "goal": self.goal[:200],
            "mission_id": self.mission_id,
            "node_count": self.node_count,
            "progress": round(self.progress, 3),
            "created_at": self.created_at,
        }


class GraphRepository:
    """
    Persistent storage for execution graphs.

    Storage: workspace/graphs/{graph_id}.json
    Index: workspace/graphs/_index.json (summaries)
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self._dir = base_dir or Path("workspace/graphs")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, GraphSummary] = {}
        self._load_index()

    def save(self, graph: ExecutionGraph) -> bool:
        """Save graph to disk. Returns True on success."""
        try:
            path = self._dir / f"{graph.graph_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(graph.to_dict(), indent=2))
            tmp.rename(path)
            self._update_index(graph)
            return True
        except Exception as e:
            log.warning("graph_save_failed", graph_id=graph.graph_id, err=str(e)[:100])
            return False

    def load(self, graph_id: str) -> Optional[ExecutionGraph]:
        """Load graph from disk."""
        try:
            path = self._dir / f"{graph_id}.json"
            if not path.exists():
                return None
            data = json.loads(path.read_text())
            return ExecutionGraph.from_dict(data)
        except Exception as e:
            log.warning("graph_load_failed", graph_id=graph_id, err=str(e)[:100])
            return None

    def delete(self, graph_id: str) -> bool:
        """Delete graph from disk."""
        try:
            path = self._dir / f"{graph_id}.json"
            if path.exists():
                path.unlink()
            self._index.pop(graph_id, None)
            self._save_index()
            return True
        except Exception:
            return False

    def list_graphs(
        self,
        schema: str = "",
        mission_id: str = "",
        limit: int = 50,
    ) -> list[dict]:
        """List graphs with optional filters."""
        results = list(self._index.values())
        if schema:
            results = [g for g in results if g.source_schema == schema]
        if mission_id:
            results = [g for g in results if g.mission_id == mission_id]
        results.sort(key=lambda g: g.created_at, reverse=True)
        return [g.to_dict() for g in results[:limit]]

    def get_resumable(self) -> list[dict]:
        """Get graphs that can be resumed (0 < progress < 1)."""
        return [
            g.to_dict() for g in self._index.values()
            if 0 < g.progress < 1.0
        ]

    def get_stats(self) -> dict:
        """Repository statistics."""
        total = len(self._index)
        completed = sum(1 for g in self._index.values() if g.progress >= 1.0)
        in_progress = sum(1 for g in self._index.values() if 0 < g.progress < 1.0)
        not_started = sum(1 for g in self._index.values() if g.progress == 0)
        schemas = {}
        for g in self._index.values():
            schemas[g.source_schema] = schemas.get(g.source_schema, 0) + 1
        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "not_started": not_started,
            "by_schema": schemas,
        }

    def _update_index(self, graph: ExecutionGraph) -> None:
        self._index[graph.graph_id] = GraphSummary(
            graph_id=graph.graph_id,
            source_schema=graph.source_schema,
            goal=graph.goal,
            mission_id=graph.mission_id,
            node_count=len(graph.nodes),
            progress=graph.progress,
            created_at=graph.created_at,
        )
        self._save_index()

    def _save_index(self) -> None:
        try:
            path = self._dir / "_index.json"
            tmp = path.with_suffix(".tmp")
            data = {
                "version": 1,
                "graphs": {gid: g.to_dict() for gid, g in self._index.items()},
            }
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(path)
        except Exception:
            _silent_log.debug("suppressed_exception", src='graph_repository.py')

    def _load_index(self) -> None:
        try:
            path = self._dir / "_index.json"
            if not path.exists():
                return
            data = json.loads(path.read_text())
            for gid, gd in data.get("graphs", {}).items():
                self._index[gid] = GraphSummary(
                    graph_id=gd.get("graph_id", gid),
                    source_schema=gd.get("source_schema", ""),
                    goal=gd.get("goal", ""),
                    mission_id=gd.get("mission_id", ""),
                    node_count=gd.get("node_count", 0),
                    progress=gd.get("progress", 0),
                    created_at=gd.get("created_at", 0),
                )
        except Exception:
            _silent_log.debug("suppressed_exception", src='graph_repository.py')


# ── Singleton ──────────────────────────────────────────────────

_repo: Optional[GraphRepository] = None


def get_graph_repository() -> GraphRepository:
    global _repo
    if _repo is None:
        _repo = GraphRepository()
    return _repo
