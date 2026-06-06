"""
Memory Graph — Store
======================
In-memory directed graph with JSON persistence.
Thread-safe, fail-open, singleton access via get_memory_graph().

Design:
  - Adjacency list (dict of sets) for O(1) neighbor lookups
  - Nodes and edges stored in dicts for O(1) access by ID
  - Optional JSON persistence (auto-save on write, lazy-load on start)
  - No external dependencies (no networkx, no neo4j)
  - Complements vector memory — stores relationships, not embeddings
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from core.memory_graph.graph_schema import Edge, EdgeType, Node, NodeType

log = structlog.get_logger()

_DEFAULT_PERSIST_PATH = os.environ.get(
    "MEMORY_GRAPH_PATH", "data/memory_graph.json"
)
_MAX_NODES = 10_000
_MAX_EDGES = 50_000

_singleton: Optional["MemoryGraph"] = None
_lock = threading.Lock()


def get_memory_graph() -> "MemoryGraph":
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = MemoryGraph(persist_path=_DEFAULT_PERSIST_PATH)
    return _singleton


class MemoryGraph:
    """Thread-safe in-memory directed graph with JSON persistence."""

    def __init__(self, persist_path: str = _DEFAULT_PERSIST_PATH):
        self._lock = threading.RLock()
        self._nodes: Dict[str, Node] = {}
        self._edges: Dict[str, Edge] = {}
        self._outgoing: Dict[str, Set[str]] = {}  # node_id → set of edge_ids
        self._incoming: Dict[str, Set[str]] = {}  # node_id → set of edge_ids
        self._persist_path = Path(persist_path)
        self._dirty = False
        self._load()

    # ── Node operations ──

    def add_node(self, node: Node) -> Node:
        """Add a node. If id exists, update metadata."""
        with self._lock:
            if len(self._nodes) >= _MAX_NODES and node.id not in self._nodes:
                self._evict_oldest_nodes(100)
            self._nodes[node.id] = node
            self._outgoing.setdefault(node.id, set())
            self._incoming.setdefault(node.id, set())
            self._dirty = True
        return node

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def find_nodes(self, type: Optional[NodeType] = None, label_contains: str = "") -> List[Node]:
        """Find nodes by type and/or label substring."""
        results = []
        for n in self._nodes.values():
            if type and n.type != type:
                continue
            if label_contains and label_contains.lower() not in n.label.lower():
                continue
            results.append(n)
        return results

    def remove_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id not in self._nodes:
                return False
            # Remove connected edges
            for eid in list(self._outgoing.get(node_id, [])):
                self._remove_edge_internal(eid)
            for eid in list(self._incoming.get(node_id, [])):
                self._remove_edge_internal(eid)
            del self._nodes[node_id]
            self._outgoing.pop(node_id, None)
            self._incoming.pop(node_id, None)
            self._dirty = True
            return True

    # ── Edge operations ──

    def add_edge(self, edge: Edge) -> Edge:
        """Add a directed edge. Source and target nodes must exist."""
        with self._lock:
            if edge.source not in self._nodes or edge.target not in self._nodes:
                raise ValueError(
                    f"Both source ({edge.source}) and target ({edge.target}) must exist"
                )
            if len(self._edges) >= _MAX_EDGES:
                self._evict_oldest_edges(200)
            self._edges[edge.id] = edge
            self._outgoing[edge.source].add(edge.id)
            self._incoming[edge.target].add(edge.id)
            self._dirty = True
        return edge

    def get_edge(self, edge_id: str) -> Optional[Edge]:
        return self._edges.get(edge_id)

    def find_edges(
        self,
        source: Optional[str] = None,
        target: Optional[str] = None,
        type: Optional[EdgeType] = None,
    ) -> List[Edge]:
        """Find edges by source, target, and/or type."""
        results = []
        candidates = self._edges.values()
        if source:
            eids = self._outgoing.get(source, set())
            candidates = [self._edges[eid] for eid in eids if eid in self._edges]
        for e in candidates:
            if target and e.target != target:
                continue
            if type and e.type != type:
                continue
            results.append(e)
        return results

    def remove_edge(self, edge_id: str) -> bool:
        with self._lock:
            return self._remove_edge_internal(edge_id)

    def _remove_edge_internal(self, edge_id: str) -> bool:
        edge = self._edges.pop(edge_id, None)
        if not edge:
            return False
        self._outgoing.get(edge.source, set()).discard(edge_id)
        self._incoming.get(edge.target, set()).discard(edge_id)
        self._dirty = True
        return True

    # ── Query operations ──

    def neighbors(self, node_id: str, direction: str = "out") -> List[Tuple[Node, Edge]]:
        """Get neighbors of a node. direction: 'out', 'in', or 'both'."""
        results = []
        if direction in ("out", "both"):
            for eid in self._outgoing.get(node_id, []):
                edge = self._edges.get(eid)
                if edge:
                    target = self._nodes.get(edge.target)
                    if target:
                        results.append((target, edge))
        if direction in ("in", "both"):
            for eid in self._incoming.get(node_id, []):
                edge = self._edges.get(eid)
                if edge:
                    source = self._nodes.get(edge.source)
                    if source:
                        results.append((source, edge))
        return results

    def path_between(self, start: str, end: str, max_depth: int = 5) -> Optional[List[str]]:
        """BFS shortest path between two nodes. Returns list of node IDs or None."""
        if start == end:
            return [start]
        visited = {start}
        queue = [(start, [start])]
        for _ in range(max_depth * len(self._nodes)):
            if not queue:
                return None
            current, path = queue.pop(0)
            for eid in self._outgoing.get(current, []):
                edge = self._edges.get(eid)
                if not edge:
                    continue
                if edge.target == end:
                    return path + [end]
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, path + [edge.target]))
        return None

    def subgraph(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        """Extract a subgraph around a node up to N hops."""
        nodes_found: Dict[str, Node] = {}
        edges_found: Dict[str, Edge] = {}
        frontier = {node_id}
        for _ in range(depth):
            next_frontier = set()
            for nid in frontier:
                node = self._nodes.get(nid)
                if not node or nid in nodes_found:
                    continue
                nodes_found[nid] = node
                for neighbor, edge in self.neighbors(nid, "both"):
                    edges_found[edge.id] = edge
                    next_frontier.add(neighbor.id)
            frontier = next_frontier - set(nodes_found.keys())
        # Add remaining frontier nodes
        for nid in frontier:
            node = self._nodes.get(nid)
            if node:
                nodes_found[nid] = node
        return {
            "nodes": [n.to_dict() for n in nodes_found.values()],
            "edges": [e.to_dict() for e in edges_found.values()],
        }

    # ── Stats ──

    def stats(self) -> Dict[str, Any]:
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "node_types": {
                t.value: sum(1 for n in self._nodes.values() if n.type == t)
                for t in NodeType if any(n.type == t for n in self._nodes.values())
            },
            "edge_types": {
                t.value: sum(1 for e in self._edges.values() if e.type == t)
                for t in EdgeType if any(e.type == t for e in self._edges.values())
            },
        }

    # ── Persistence ──

    def save(self) -> None:
        """Save graph to JSON file."""
        with self._lock:
            if not self._dirty:
                return
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "nodes": [n.to_dict() for n in self._nodes.values()],
                    "edges": [e.to_dict() for e in self._edges.values()],
                    "saved_at": time.time(),
                }
                tmp = self._persist_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2))
                tmp.replace(self._persist_path)
                self._dirty = False
            except Exception as e:
                log.warning("memory_graph_save_failed", err=str(e))

    def _load(self) -> None:
        """Load graph from JSON file if it exists."""
        try:
            if not self._persist_path.exists():
                return
            data = json.loads(self._persist_path.read_text())
            for nd in data.get("nodes", []):
                node = Node(
                    id=nd["id"], type=NodeType(nd["type"]),
                    label=nd.get("label", ""), metadata=nd.get("metadata", {}),
                    created_at=nd.get("created_at", 0),
                )
                self._nodes[node.id] = node
                self._outgoing.setdefault(node.id, set())
                self._incoming.setdefault(node.id, set())
            for ed in data.get("edges", []):
                edge = Edge(
                    id=ed["id"], source=ed["source"], target=ed["target"],
                    type=EdgeType(ed["type"]), weight=ed.get("weight", 1.0),
                    metadata=ed.get("metadata", {}), created_at=ed.get("created_at", 0),
                )
                if edge.source in self._nodes and edge.target in self._nodes:
                    self._edges[edge.id] = edge
                    self._outgoing[edge.source].add(edge.id)
                    self._incoming[edge.target].add(edge.id)
            log.info("memory_graph_loaded", nodes=len(self._nodes), edges=len(self._edges))
        except Exception as e:
            log.warning("memory_graph_load_failed", err=str(e))

    # ── Eviction ──

    def _evict_oldest_nodes(self, count: int) -> None:
        sorted_nodes = sorted(self._nodes.values(), key=lambda n: n.created_at)
        for node in sorted_nodes[:count]:
            self.remove_node(node.id)

    def _evict_oldest_edges(self, count: int) -> None:
        sorted_edges = sorted(self._edges.values(), key=lambda e: e.created_at)
        for edge in sorted_edges[:count]:
            self._remove_edge_internal(edge.id)
