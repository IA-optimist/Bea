"""
Memory Graph — Schema
=======================
Node types, edge types, and data models for the relationship graph.

This complements (never replaces) vector/embedding memory.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class NodeType(str, Enum):
    MISSION = "mission"
    AGENT = "agent"
    TOOL = "tool"
    MODULE = "module"
    PATCH = "patch"
    BUG = "bug"
    SECRET = "secret"
    CONNECTOR = "connector"
    IDENTITY = "identity"
    USER_REQUEST = "user_request"
    INTENT = "intent"
    WORKFLOW = "workflow"
    STEP = "step"
    OUTCOME = "outcome"
    LESSON = "lesson"
    METRIC = "metric"


class EdgeType(str, Enum):
    # Execution flow
    TRIGGERED = "triggered"         # mission → step
    EXECUTED_BY = "executed_by"     # step → agent
    USED_TOOL = "used_tool"         # step → tool
    PRODUCED = "produced"           # step → outcome
    # Causality
    CAUSED = "caused"               # bug → failure
    FIXED_BY = "fixed_by"          # bug → patch
    VALIDATED_BY = "validated_by"   # patch → test_result
    # Dependencies
    DEPENDS_ON = "depends_on"       # module → module
    REQUIRES_SECRET = "requires_secret"  # connector → secret
    BOUND_TO = "bound_to"          # identity → connector
    # Learning
    LEARNED_FROM = "learned_from"  # lesson → mission
    IMPROVED = "improved"           # patch → module
    CORRELATED = "correlated"       # failure → failure
    # Intent
    INFERRED_AS = "inferred_as"    # user_request → intent
    RESOLVED_VIA = "resolved_via"  # intent → workflow


@dataclass
class Node:
    """A node in the memory graph."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    type: NodeType = NodeType.MISSION
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type.value, "label": self.label,
            "metadata": self.metadata, "created_at": self.created_at,
        }


@dataclass
class Edge:
    """A directed edge in the memory graph."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source: str = ""       # node id
    target: str = ""       # node id
    type: EdgeType = EdgeType.TRIGGERED
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source, "target": self.target,
            "type": self.type.value, "weight": self.weight,
            "metadata": self.metadata, "created_at": self.created_at,
        }
