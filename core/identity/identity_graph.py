"""
JARVIS MAX — Identity Graph
===============================
Relationship graph between identities, services, and domains.

Allows Jarvis to:
- Understand dependencies between accounts
- Rotate secrets intelligently (cascading updates)
- Debug broken integrations (find which identity feeds which service)
- Visualize infrastructure
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class EdgeType(str):
    AUTHENTICATES = "authenticates"   # identity → service (login)
    DELEGATES_TO = "delegates_to"     # identity → identity (OAuth)
    OWNS_DOMAIN = "owns_domain"       # identity → domain
    RECEIVES_FROM = "receives_from"   # identity ← service (webhooks)
    PAYS_VIA = "pays_via"             # identity → payment identity
    DEPENDS_ON = "depends_on"         # service → identity (requires)


@dataclass
class GraphEdge:
    """Directed edge in the identity graph."""
    source: str          # identity_id or service name
    target: str          # identity_id, service name, or domain
    edge_type: str       # EdgeType value
    label: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "source": self.source, "target": self.target,
            "type": self.edge_type, "label": self.label,
        }


@dataclass
class GraphNode:
    """Node in the identity graph."""
    node_id: str
    node_type: str       # "identity", "service", "domain"
    label: str = ""
    provider: str = ""
    environment: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.node_id, "type": self.node_type,
            "label": self.label, "provider": self.provider,
            "env": self.environment,
        }


class IdentityGraph:
    """
    Directed graph of identity relationships.
    Nodes: identities, services, domains.
    Edges: authenticates, delegates, owns, receives, pays, depends.
    """

    def __init__(self):
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []

    def add_node(
        self,
        node_id: str,
        node_type: str = "identity",
        label: str = "",
        provider: str = "",
        environment: str = "",
    ) -> GraphNode:
        """Add a node to the graph."""
        node = GraphNode(
            node_id=node_id, node_type=node_type,
            label=label or node_id, provider=provider,
            environment=environment,
        )
        self._nodes[node_id] = node
        return node

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        label: str = "",
    ) -> GraphEdge:
        """Add a directed edge."""
        # Auto-create nodes if missing
        if source not in self._nodes:
            self.add_node(source, "unknown", source)
        if target not in self._nodes:
            self.add_node(target, "unknown", target)

        edge = GraphEdge(source=source, target=target, edge_type=edge_type, label=label)
        self._edges.append(edge)
        return edge

    def link_identity_to_service(
        self,
        identity_id: str,
        service_name: str,
        edge_type: str = "authenticates",
    ) -> GraphEdge:
        """Convenience: link an identity to a service."""
        if service_name not in self._nodes:
            self.add_node(service_name, "service", service_name)
        return self.add_edge(identity_id, service_name, edge_type)

    def link_identity_to_domain(self, identity_id: str, domain: str) -> GraphEdge:
        """Link an identity to a domain it owns/manages."""
        if domain not in self._nodes:
            self.add_node(domain, "domain", domain)
        return self.add_edge(identity_id, domain, EdgeType.OWNS_DOMAIN)

    def get_connections(self, node_id: str) -> dict:
        """Get all connections for a node."""
        outgoing = [e.to_dict() for e in self._edges if e.source == node_id]
        incoming = [e.to_dict() for e in self._edges if e.target == node_id]
        return {
            "node": self._nodes.get(node_id, GraphNode(node_id, "unknown")).to_dict(),
            "outgoing": outgoing,
            "incoming": incoming,
            "total": len(outgoing) + len(incoming),
        }

    def get_dependents(self, identity_id: str) -> list[str]:
        """Find all services/identities that depend on this identity."""
        return [
            e.target for e in self._edges
            if e.source == identity_id
        ]

    def get_dependencies(self, node_id: str) -> list[str]:
        """Find all identities a service depends on."""
        return [
            e.source for e in self._edges
            if e.target == node_id and e.edge_type == EdgeType.DEPENDS_ON
        ]

    def find_rotation_cascade(self, identity_id: str) -> list[str]:
        """
        Find all nodes affected if this identity's credentials rotate.
        BFS from identity through authenticates/delegates edges.
        """
        affected = []
        visited = {identity_id}
        queue = [identity_id]

        while queue:
            current = queue.pop(0)
            for edge in self._edges:
                if edge.source == current and edge.target not in visited:
                    affected.append(edge.target)
                    visited.add(edge.target)
                    queue.append(edge.target)

        return affected

    def to_dict(self) -> dict:
        """Export full graph."""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
        }

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)
