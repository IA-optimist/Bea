"""
core/execution/artifacts.py — Canonical artifact types for real-world outputs.

An artifact is a concrete, deployable output produced by Bea from
structured cognition. Artifacts bridge the gap between reasoning
(OpportunityReport, VenturePlan) and real-world deliverables
(landing pages, APIs, automation workflows).

Design:
  - Typed: each artifact has a canonical ArtifactType
  - Traceable: links back to source capability + mission + plan
  - Validatable: validation_requirements define what "done" means
  - Storable: serializable to JSON, persists in mission context
  - Safe: all artifacts are specs until explicitly built
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class ArtifactType(str, Enum):
    """Canonical artifact types producible by Bea."""
    LANDING_PAGE = "landing_page"
    AUTOMATION_WORKFLOW = "automation_workflow"
    API_SERVICE = "api_service"
    MVP_FEATURE = "mvp_feature"
    DATA_PIPELINE = "data_pipeline"
    MARKETING_EXPERIMENT = "marketing_experiment"
    CONTENT_ASSET = "content_asset"
    OPERATIONAL_WORKFLOW = "operational_workflow"


class ArtifactStatus(str, Enum):
    """Lifecycle status of an artifact."""
    SPEC = "spec"                     # specification defined
    VALIDATED = "validated"           # spec passed validation
    BUILDING = "building"             # build pipeline active
    BUILT = "built"                   # build completed
    VERIFIED = "verified"             # post-build verification passed
    FAILED = "failed"                 # build or verification failed
    DEPLOYED = "deployed"             # live in target environment


@dataclass
class ValidationRequirement:
    """A single validation check for an artifact."""
    name: str
    check_type: str = "exists"  # exists, schema, content, test, manual
    target: str = ""            # file path, URL, field name
    description: str = ""
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "check_type": self.check_type,
            "target": self.target,
            "description": self.description,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ValidationRequirement":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ToolDependency:
    """A tool required to build this artifact."""
    tool_id: str
    purpose: str = ""           # what the tool does in this context
    required: bool = True       # hard dep vs nice-to-have
    fallback: str = ""          # fallback tool if primary unavailable

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "purpose": self.purpose,
            "required": self.required,
            "fallback": self.fallback,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolDependency":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ExecutionArtifact:
    """
    A concrete, deployable output specification.

    This is NOT the built output itself — it's the spec that defines
    what to build, how to validate it, and what tools are needed.
    The actual build happens through the build pipeline.
    """
    artifact_id: str = ""
    artifact_type: ArtifactType = ArtifactType.CONTENT_ASSET
    name: str = ""
    description: str = ""

    # Traceability
    source_capability: str = ""     # which capability produced this
    source_mission_id: str = ""     # mission that triggered creation
    source_plan_id: str = ""        # plan that contains this
    source_schema: str = ""         # economic schema that fed this (OpportunityReport, etc.)

    # Context
    input_context: dict = field(default_factory=dict)  # data from prior steps
    generation_rationale: str = ""  # why this artifact was chosen

    # Build requirements
    required_tools: list[ToolDependency] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # other artifact_ids
    validation_requirements: list[ValidationRequirement] = field(default_factory=list)
    expected_outcome: str = ""      # what success looks like

    # Build output
    output_files: list[str] = field(default_factory=list)
    output_data: dict = field(default_factory=dict)
    build_log: list[str] = field(default_factory=list)

    # Status
    status: ArtifactStatus = ArtifactStatus.SPEC
    error: str = ""

    # Timing
    created_at: float = field(default_factory=time.time)
    built_at: float = 0.0
    verified_at: float = 0.0

    def __post_init__(self):
        if not self.artifact_id:
            self.artifact_id = f"art-{uuid.uuid4().hex[:8]}"
        if isinstance(self.artifact_type, str):
            self.artifact_type = ArtifactType(self.artifact_type)
        if isinstance(self.status, str):
            self.status = ArtifactStatus(self.status)

    def validate_spec(self) -> list[str]:
        """Validate the artifact spec itself (not the output)."""
        issues = []
        if not self.name:
            issues.append("name is required")
        if not self.description:
            issues.append("description is required")
        if not self.expected_outcome:
            issues.append("expected_outcome is required")
        return issues

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "name": self.name,
            "description": self.description[:500],
            "source_capability": self.source_capability,
            "source_mission_id": self.source_mission_id,
            "source_plan_id": self.source_plan_id,
            "source_schema": self.source_schema,
            "input_context": {k: str(v)[:200] for k, v in
                              list(self.input_context.items())[:20]},
            "generation_rationale": self.generation_rationale[:300],
            "required_tools": [t.to_dict() for t in self.required_tools],
            "dependencies": self.dependencies[:20],
            "validation_requirements": [v.to_dict() for v in self.validation_requirements],
            "expected_outcome": self.expected_outcome[:300],
            "output_files": self.output_files[:50],
            "output_data": {k: str(v)[:200] for k, v in
                            list(self.output_data.items())[:20]},
            "build_log": self.build_log[-20:],
            "status": self.status.value,
            "error": self.error[:300],
            "created_at": self.created_at,
            "built_at": self.built_at,
            "verified_at": self.verified_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionArtifact":
        return cls(
            artifact_id=d.get("artifact_id", ""),
            artifact_type=d.get("artifact_type", "content_asset"),
            name=d.get("name", ""),
            description=d.get("description", ""),
            source_capability=d.get("source_capability", ""),
            source_mission_id=d.get("source_mission_id", ""),
            source_plan_id=d.get("source_plan_id", ""),
            source_schema=d.get("source_schema", ""),
            input_context=d.get("input_context", {}),
            generation_rationale=d.get("generation_rationale", ""),
            required_tools=[ToolDependency.from_dict(t) for t in d.get("required_tools", [])],
            dependencies=d.get("dependencies", []),
            validation_requirements=[ValidationRequirement.from_dict(v)
                                     for v in d.get("validation_requirements", [])],
            expected_outcome=d.get("expected_outcome", ""),
            output_files=d.get("output_files", []),
            output_data=d.get("output_data", {}),
            build_log=d.get("build_log", []),
            status=d.get("status", "spec"),
            error=d.get("error", ""),
            created_at=d.get("created_at", time.time()),
            built_at=d.get("built_at", 0),
            verified_at=d.get("verified_at", 0),
        )


# ── Artifact templates ────────────────────────────────────────
# Pre-defined artifact specs for common output types.

ARTIFACT_TEMPLATES: dict[str, dict] = {
    "landing_page": {
        "artifact_type": "landing_page",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write HTML/CSS files", "required": True},
        ],
        "validation_requirements": [
            {"name": "html_exists", "check_type": "exists", "target": "index.html"},
            {"name": "has_headline", "check_type": "content", "target": "index.html",
             "description": "Page contains a headline"},
            {"name": "has_cta", "check_type": "content", "target": "index.html",
             "description": "Page contains a call-to-action"},
        ],
    },
    "automation_workflow": {
        "artifact_type": "automation_workflow",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write workflow JSON", "required": True},
            {"tool_id": "n8n.workflow.trigger", "purpose": "Deploy to n8n", "required": False,
             "fallback": "file.workspace.write"},
        ],
        "validation_requirements": [
            {"name": "workflow_json", "check_type": "exists", "target": "workflow.json"},
            {"name": "has_trigger", "check_type": "content", "target": "workflow.json",
             "description": "Workflow has at least one trigger node"},
        ],
    },
    "api_service": {
        "artifact_type": "api_service",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write service code", "required": True},
        ],
        "validation_requirements": [
            {"name": "main_file", "check_type": "exists", "target": "main.py"},
            {"name": "requirements", "check_type": "exists", "target": "requirements.txt"},
            {"name": "has_endpoint", "check_type": "content", "target": "main.py",
             "description": "Service defines at least one API endpoint"},
        ],
    },
    "mvp_feature": {
        "artifact_type": "mvp_feature",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write feature code", "required": True},
        ],
        "validation_requirements": [
            {"name": "implementation", "check_type": "exists", "target": "feature.py"},
            {"name": "spec_doc", "check_type": "exists", "target": "SPEC.md"},
        ],
    },
    "marketing_experiment": {
        "artifact_type": "marketing_experiment",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write experiment plan", "required": True},
        ],
        "validation_requirements": [
            {"name": "experiment_plan", "check_type": "exists", "target": "experiment.json"},
            {"name": "has_hypothesis", "check_type": "content", "target": "experiment.json",
             "description": "Experiment defines a testable hypothesis"},
        ],
    },
    "content_asset": {
        "artifact_type": "content_asset",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write content files", "required": True},
        ],
        "validation_requirements": [
            {"name": "content_file", "check_type": "exists", "target": "content.md"},
        ],
    },
    "data_pipeline": {
        "artifact_type": "data_pipeline",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write pipeline code", "required": True},
        ],
        "validation_requirements": [
            {"name": "pipeline_file", "check_type": "exists", "target": "pipeline.py"},
            {"name": "config_file", "check_type": "exists", "target": "pipeline.json"},
        ],
    },
    "operational_workflow": {
        "artifact_type": "operational_workflow",
        "required_tools": [
            {"tool_id": "file.workspace.write", "purpose": "Write workflow spec", "required": True},
        ],
        "validation_requirements": [
            {"name": "workflow_spec", "check_type": "exists", "target": "workflow.md"},
            {"name": "runbook", "check_type": "exists", "target": "runbook.md"},
        ],
    },
}


def create_artifact_from_template(
    template_id: str,
    name: str,
    description: str,
    expected_outcome: str,
    input_context: dict | None = None,
    source_capability: str = "",
    source_mission_id: str = "",
    source_schema: str = "",
) -> ExecutionArtifact | None:
    """Create an artifact from a template. Returns None if template unknown."""
    template = ARTIFACT_TEMPLATES.get(template_id)
    if not template:
        return None

    return ExecutionArtifact(
        artifact_type=template["artifact_type"],
        name=name,
        description=description,
        expected_outcome=expected_outcome,
        input_context=input_context or {},
        source_capability=source_capability,
        source_mission_id=source_mission_id,
        source_schema=source_schema,
        required_tools=[ToolDependency.from_dict(t) for t in template.get("required_tools", [])],
        validation_requirements=[ValidationRequirement.from_dict(v)
                                  for v in template.get("validation_requirements", [])],
    )
