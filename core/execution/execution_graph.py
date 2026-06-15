"""
core/execution/execution_graph.py — Execution graph for artifact production.

Maps economic schemas → artifact sequences and provides a simple,
deterministic execution graph from opportunity to deployable outputs.

Design:
  - Graph is a simple ordered list of artifact production steps
  - Each step maps to an artifact type + source capability
  - Graph is deterministic: same schema → same graph
  - No heavy DAG engine — just ordered list with dependency tracking
  - Fail-open: missing mappings produce empty graph
"""
from __future__ import annotations

import time
import uuid
import structlog
from dataclasses import dataclass, field

from core.execution.artifacts import (
    ExecutionArtifact, create_artifact_from_template,
)

log = structlog.get_logger("execution.graph")


# ── Capability → Artifact mapping ─────────────────────────────

# Which capability produces which artifact type(s)
CAPABILITY_ARTIFACT_MAP: dict[str, list[str]] = {
    "market_intelligence": ["content_asset"],
    "product_design": ["mvp_feature", "api_service"],
    "financial_reasoning": ["content_asset"],
    "strategy_reasoning": ["operational_workflow", "marketing_experiment"],
    "venture_planning": ["mvp_feature", "landing_page", "automation_workflow"],
    "compliance_reasoning": ["content_asset"],
    "risk_assessment": ["content_asset"],
}

# Schema → artifact sequence (the execution graph templates)
SCHEMA_ARTIFACT_SEQUENCES: dict[str, list[dict]] = {
    "OpportunityReport": [
        {
            "template": "content_asset",
            "name": "Opportunity Analysis Report",
            "capability": "market_intelligence",
            "phase": "thinking",
        },
    ],
    "BusinessConcept": [
        {
            "template": "mvp_feature",
            "name": "MVP Feature Spec",
            "capability": "product_design",
            "phase": "planning",
        },
        {
            "template": "landing_page",
            "name": "Product Landing Page",
            "capability": "venture_planning",
            "phase": "building",
        },
    ],
    "VenturePlan": [
        {
            "template": "mvp_feature",
            "name": "Core MVP Implementation",
            "capability": "product_design",
            "phase": "building",
        },
        {
            "template": "landing_page",
            "name": "Launch Landing Page",
            "capability": "venture_planning",
            "phase": "building",
        },
        {
            "template": "automation_workflow",
            "name": "Lead Capture Workflow",
            "capability": "venture_planning",
            "phase": "building",
        },
        {
            "template": "marketing_experiment",
            "name": "Launch Growth Experiment",
            "capability": "strategy_reasoning",
            "phase": "deploying",
        },
    ],
    "FinancialModel": [
        {
            "template": "content_asset",
            "name": "Financial Analysis Report",
            "capability": "financial_reasoning",
            "phase": "thinking",
        },
        {
            "template": "operational_workflow",
            "name": "Revenue Tracking Workflow",
            "capability": "strategy_reasoning",
            "phase": "building",
        },
    ],
    # Lowercase aliases matching ARTIFACT_TEMPLATES keys (used directly as schema_type)
    "landing_page": [
        {"template": "landing_page", "name": "Landing Page", "capability": "venture_planning", "phase": "building"},
    ],
    "automation_workflow": [
        {"template": "automation_workflow", "name": "Automation Workflow", "capability": "strategy_reasoning", "phase": "building"},
    ],
    "api_service": [
        {"template": "api_service", "name": "API Service", "capability": "product_design", "phase": "building"},
    ],
    "mvp_feature": [
        {"template": "mvp_feature", "name": "MVP Feature", "capability": "product_design", "phase": "building"},
    ],
    "marketing_experiment": [
        {"template": "marketing_experiment", "name": "Marketing Experiment", "capability": "strategy_reasoning", "phase": "building"},
    ],
    "content_asset": [
        {"template": "content_asset", "name": "Content Asset", "capability": "market_intelligence", "phase": "thinking"},
    ],
    "data_pipeline": [
        {"template": "data_pipeline", "name": "Data Pipeline", "capability": "product_design", "phase": "building"},
    ],
    "operational_workflow": [
        {"template": "operational_workflow", "name": "Operational Workflow", "capability": "strategy_reasoning", "phase": "building"},
    ],
}


# ── Execution Graph ───────────────────────────────────────────

@dataclass
class GraphNode:
    """A single node in the execution graph."""
    node_id: str = ""
    artifact_template: str = ""
    artifact_name: str = ""
    source_capability: str = ""
    phase: str = "building"         # thinking, planning, building, deploying
    depends_on: list[str] = field(default_factory=list)
    artifact: ExecutionArtifact | None = None

    def __post_init__(self):
        if not self.node_id:
            self.node_id = f"gn-{uuid.uuid4().hex[:6]}"

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "artifact_template": self.artifact_template,
            "artifact_name": self.artifact_name,
            "source_capability": self.source_capability,
            "phase": self.phase,
            "depends_on": self.depends_on,
            "artifact_id": self.artifact.artifact_id if self.artifact else "",
            "artifact_status": self.artifact.status.value if self.artifact else "",
        }


@dataclass
class ExecutionGraph:
    """
    Ordered graph of artifact production steps.

    Simple and explicit — not a heavy DAG engine.
    Nodes are ordered: each depends on all previous nodes.
    """
    graph_id: str = ""
    source_schema: str = ""
    goal: str = ""
    mission_id: str = ""
    nodes: list[GraphNode] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.graph_id:
            self.graph_id = f"eg-{uuid.uuid4().hex[:8]}"

    @property
    def phase_summary(self) -> dict[str, int]:
        """Count of nodes per phase."""
        counts: dict[str, int] = {}
        for n in self.nodes:
            counts[n.phase] = counts.get(n.phase, 0) + 1
        return counts

    @property
    def progress(self) -> float:
        """Fraction of artifacts built or verified."""
        if not self.nodes:
            return 0.0
        done = sum(1 for n in self.nodes
                   if n.artifact and n.artifact.status.value in ("built", "verified", "deployed"))
        return round(done / len(self.nodes), 3)

    def get_next_buildable(self) -> GraphNode | None:
        """Get the next node whose dependencies are satisfied."""
        completed_ids = {
            n.node_id for n in self.nodes
            if n.artifact and n.artifact.status.value in ("built", "verified", "deployed")
        }
        for node in self.nodes:
            if node.artifact and node.artifact.status.value == "spec":
                # Check if all dependencies are completed
                if all(dep in completed_ids for dep in node.depends_on):
                    return node
        return None

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "source_schema": self.source_schema,
            "goal": self.goal,
            "mission_id": self.mission_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "node_count": len(self.nodes),
            "phase_summary": self.phase_summary,
            "progress": self.progress,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionGraph":
        nodes = []
        for nd in d.get("nodes", []):
            node = GraphNode(
                node_id=nd.get("node_id", ""),
                artifact_template=nd.get("artifact_template", ""),
                artifact_name=nd.get("artifact_name", ""),
                source_capability=nd.get("source_capability", ""),
                phase=nd.get("phase", "building"),
                depends_on=nd.get("depends_on", []),
            )
            nodes.append(node)
        return cls(
            graph_id=d.get("graph_id", ""),
            source_schema=d.get("source_schema", ""),
            goal=d.get("goal", ""),
            mission_id=d.get("mission_id", ""),
            nodes=nodes,
            created_at=d.get("created_at", time.time()),
        )


def build_execution_graph(
    schema_type: str,
    goal: str,
    input_context: dict | None = None,
    mission_id: str = "",
) -> ExecutionGraph:
    """
    Build an execution graph from an economic schema type.

    Maps schema → ordered artifact sequence, creates artifact specs
    for each node with proper dependency chains.

    Args:
        schema_type: Economic schema (OpportunityReport, VenturePlan, etc.)
        goal: Human-readable goal description
        input_context: Data from economic cognition pipeline
        mission_id: Source mission ID for traceability

    Returns:
        ExecutionGraph with nodes and artifact specs.
        Empty graph if schema has no known artifact sequence.
    """
    sequence = SCHEMA_ARTIFACT_SEQUENCES.get(schema_type, [])
    graph = ExecutionGraph(
        source_schema=schema_type,
        goal=goal,
        mission_id=mission_id,
    )

    prev_node_id = ""
    for step_def in sequence:
        template_id = step_def["template"]
        artifact = create_artifact_from_template(
            template_id=template_id,
            name=step_def.get("name", template_id),
            description=f"{step_def.get('name', '')} for: {goal[:100]}",
            expected_outcome=f"Deployable {template_id} artifact",
            input_context=input_context or {},
            source_capability=step_def.get("capability", ""),
            source_mission_id=mission_id,
            source_schema=schema_type,
        )

        node = GraphNode(
            artifact_template=template_id,
            artifact_name=step_def.get("name", template_id),
            source_capability=step_def.get("capability", ""),
            phase=step_def.get("phase", "building"),
            depends_on=[prev_node_id] if prev_node_id else [],
            artifact=artifact,
        )
        graph.nodes.append(node)
        prev_node_id = node.node_id

    log.debug("execution_graph_built",
              schema=schema_type, nodes=len(graph.nodes),
              phases=graph.phase_summary)
    return graph
