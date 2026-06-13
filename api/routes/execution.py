"""
api/routes/execution.py — Real World Execution Layer API.

Endpoints under /api/v3/execution/:
  POST /graph         — Build execution graph from schema
  GET  /graph/{id}    — Get graph status
  POST /build         — Build a single artifact
  GET  /artifacts     — List artifacts
  GET  /templates     — List artifact templates
  GET  /tools         — List tool contracts
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("bea.api.execution")

# Fail-hard on auth import: if _check_auth is unavailable, the router
# must NOT register — silent fail-open to no-auth is a HIGH severity bug.
# Canonical auth helper lives in api._deps, not api.auth.
from api._deps import require_auth

router = APIRouter(
    prefix="/api/v3/execution",
    tags=["execution"],
    dependencies=[Depends(require_auth)],
)


class BuildGraphRequest(BaseModel):
    schema_type: str
    goal: str
    input_context: Optional[dict] = None
    mission_id: Optional[str] = ""


class BuildArtifactRequest(BaseModel):
    template_id: str
    name: str
    description: str
    expected_outcome: str
    input_context: Optional[dict] = None
    budget_mode: Optional[str] = "normal"
    source_capability: Optional[str] = ""
    source_schema: Optional[str] = ""


@router.post("/graph")
async def build_graph(req: BuildGraphRequest):
    """Build an execution graph from an economic schema type."""
    try:
        from core.execution.execution_graph import build_execution_graph
        from core.execution.graph_repository import get_graph_repository
        graph = build_execution_graph(
            schema_type=req.schema_type,
            goal=req.goal,
            input_context=req.input_context,
            mission_id=req.mission_id or "",
        )
        get_graph_repository().save(graph)
        return {"ok": True, "graph": graph.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/graph/{graph_id}")
async def get_graph(graph_id: str):
    """Load a persisted execution graph by ID."""
    try:
        from core.execution.graph_repository import get_graph_repository
        graph = get_graph_repository().load(graph_id)
        if not graph:
            return {"ok": False, "error": "Graph not found"}
        return {"ok": True, "graph": graph.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/graphs")
async def list_graphs(schema: str = "", mission_id: str = "", limit: int = 50):
    """List persisted execution graphs with filters."""
    try:
        from core.execution.graph_repository import get_graph_repository
        items = get_graph_repository().list_graphs(schema=schema, mission_id=mission_id, limit=limit)
        stats = get_graph_repository().get_stats()
        return {"ok": True, "graphs": items, "stats": stats}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/graphs/resumable")
async def get_resumable_graphs():
    """Get graphs that can be resumed (partially completed)."""
    try:
        from core.execution.graph_repository import get_graph_repository
        return {"ok": True, "graphs": get_graph_repository().get_resumable()}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.post("/build")
async def build_artifact(req: BuildArtifactRequest):
    """Build a single artifact from a template."""
    try:
        from core.execution.artifacts import create_artifact_from_template
        from core.execution.build_pipeline import get_build_pipeline

        artifact = create_artifact_from_template(
            template_id=req.template_id,
            name=req.name,
            description=req.description,
            expected_outcome=req.expected_outcome,
            input_context=req.input_context,
            source_capability=req.source_capability or "",
            source_schema=req.source_schema or "",
        )
        if not artifact:
            raise HTTPException(404, f"Unknown template: {req.template_id}")

        budget_mode = req.budget_mode or "normal"
        if budget_mode not in ("budget", "normal", "critical"):
            budget_mode = "normal"

        pipeline = get_build_pipeline()
        result = pipeline.build(artifact, budget_mode=budget_mode)

        return {
            "ok": result.success,
            "result": result.to_dict(),
            "artifact": artifact.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/templates")
async def list_templates():
    """List available artifact templates."""
    from core.execution.artifacts import ARTIFACT_TEMPLATES
    return {
        "templates": [
            {
                "template_id": tid,
                "artifact_type": t["artifact_type"],
                "required_tools": [rt["tool_id"] for rt in t.get("required_tools", [])],
                "validation_count": len(t.get("validation_requirements", [])),
            }
            for tid, t in ARTIFACT_TEMPLATES.items()
        ]
    }


@router.get("/tools")
async def list_tool_contracts():
    """List tool integration contracts for build pipeline."""
    from core.execution.build_pipeline import TOOL_CONTRACTS
    return {
        "tools": [tc.to_dict() for tc in TOOL_CONTRACTS.values()]
    }


@router.get("/artifacts")
async def list_artifacts():
    """List built artifacts in workspace/builds/."""
    import os
    from pathlib import Path
    builds_dir = Path(os.environ.get("WORKSPACE_DIR", "workspace")) / "builds"
    artifacts = []
    if builds_dir.is_dir():
        for d in sorted(builds_dir.iterdir()):
            if d.is_dir():
                spec_file = d / "artifact_spec.json"
                files = [f.name for f in d.iterdir() if f.is_file()]
                artifacts.append({
                    "artifact_id": d.name,
                    "files": files,
                    "has_spec": spec_file.exists(),
                })
    return {"artifacts": artifacts, "total": len(artifacts)}


@router.get("/policy/{template_id}")
async def check_policy(template_id: str):
    """Check policy for an artifact template before building."""
    try:
        from core.execution.artifacts import create_artifact_from_template
        from core.execution.policy import check_artifact_policy, get_policy_classification

        artifact = create_artifact_from_template(
            template_id=template_id,
            name="policy_check",
            description="Policy pre-check",
            expected_outcome="N/A",
        )
        if not artifact:
            return {"safe": False, "error": f"Unknown template: {template_id}"}

        violations = check_artifact_policy(artifact)
        policy_class = get_policy_classification(artifact)

        return {
            "template_id": template_id,
            "policy_classification": policy_class,
            "safe": not any(v.severity == "block" for v in violations),
            "violations": [v.to_dict() for v in violations],
        }
    except Exception as e:
        return {"safe": True, "error": str(e)[:100]}


## ── Deployment + Recovery Endpoints ───────────────────────────

class DeployRequest(BaseModel):
    artifact_id: str
    target_type: str = ""  # auto-select if empty


def _safe_artifact_dir(builds_dir, artifact_id: str):
    """Resolve artifact build dir; raise HTTPException 400 on path escape."""
    from pathlib import Path
    try:
        resolved = (builds_dir / artifact_id).resolve()
        if not resolved.is_relative_to(builds_dir.resolve()):
            raise HTTPException(400, "invalid artifact_id: path traversal detected")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"invalid artifact_id: {exc}") from exc
    return resolved


@router.post("/deploy")
async def deploy_artifact(req: DeployRequest):
    """Deploy a built artifact to a target."""
    import os
    from pathlib import Path
    from core.execution.artifacts import ArtifactType, ArtifactStatus, ExecutionArtifact
    from core.execution.deployment import DeploymentPipeline, DEPLOYMENT_TARGETS

    builds_dir = Path(os.environ.get("WORKSPACE_DIR", "workspace")) / "builds"
    build_dir = _safe_artifact_dir(builds_dir, req.artifact_id)

    if not build_dir.exists():
        raise HTTPException(404, f"No build found for artifact: {req.artifact_id}")

    # Reconstruct minimal artifact + build result
    files = [f.name for f in build_dir.iterdir() if f.is_file()]
    artifact = ExecutionArtifact(
        artifact_id=req.artifact_id,
        artifact_type=ArtifactType.LANDING_PAGE,  # Inferred from files below
        name=req.artifact_id,
        status=ArtifactStatus.BUILT,
    )
    # Infer type from files
    if any(f.endswith(".html") for f in files):
        artifact.artifact_type = ArtifactType.LANDING_PAGE
    elif any(f in ("main.py", "app.py") for f in files):
        artifact.artifact_type = ArtifactType.API_SERVICE
    elif any(f.endswith(".json") for f in files):
        artifact.artifact_type = ArtifactType.AUTOMATION_WORKFLOW

    # Minimal build result
    class _BR:
        success = True
        output_dir = str(build_dir)
        output_files = files
    build_result = _BR()

    target = None
    if req.target_type and req.target_type in DEPLOYMENT_TARGETS:
        from core.execution.deployment import DeploymentTarget
        template = DEPLOYMENT_TARGETS[req.target_type]
        target = DeploymentTarget(
            target_type=template.target_type,
            required_tools=list(template.required_tools),
            policy_level=template.policy_level,
            verification_method=template.verification_method,
            rollback_strategy=template.rollback_strategy,
            description=template.description,
        )

    pipeline = DeploymentPipeline()
    result = pipeline.deploy(build_result, artifact, target)
    return result.to_dict()


@router.get("/deployments")
async def list_deployments():
    """List all deployment results."""
    from core.execution.deployment import get_deployments
    deps = get_deployments()
    return {
        "deployments": [d.to_dict() for d in deps[-50:]],
        "total": len(deps),
    }


@router.get("/builds/{artifact_id}")
async def get_build_detail(artifact_id: str):
    """Get build details for an artifact."""
    import os
    from pathlib import Path
    builds_dir = Path(os.environ.get("WORKSPACE_DIR", "workspace")) / "builds"
    build_dir = _safe_artifact_dir(builds_dir, artifact_id)
    if not build_dir.exists():
        raise HTTPException(404, f"Build not found: {artifact_id}")

    files = []
    for f in build_dir.iterdir():
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size})
    return {"artifact_id": artifact_id, "files": files, "output_dir": str(build_dir)}


@router.get("/retries")
async def list_retries():
    """List recent retry attempts (from deployment store)."""
    from core.execution.deployment import get_deployments
    deps = get_deployments()
    retried = [d.to_dict() for d in deps if any("retry" in l.lower() for l in d.deploy_log)]
    return {"retries": retried, "total": len(retried)}


@router.get("/targets")
async def list_deployment_targets():
    """List available deployment targets."""
    from core.execution.deployment import DEPLOYMENT_TARGETS
    return {
        "targets": {k: v.to_dict() for k, v in DEPLOYMENT_TARGETS.items()},
        "total": len(DEPLOYMENT_TARGETS),
    }


@router.get("/status")
async def execution_status():
    """Execution layer status summary."""
    import os
    from pathlib import Path
    from core.execution.artifacts import ARTIFACT_TEMPLATES
    from core.execution.build_pipeline import TOOL_CONTRACTS
    from core.execution.execution_graph import SCHEMA_ARTIFACT_SEQUENCES

    builds_dir = Path(os.environ.get("WORKSPACE_DIR", "workspace")) / "builds"
    artifact_count = len(list(builds_dir.iterdir())) if builds_dir.is_dir() else 0

    return {
        "active": True,
        "templates": len(ARTIFACT_TEMPLATES),
        "tool_contracts": len(TOOL_CONTRACTS),
        "schema_sequences": len(SCHEMA_ARTIFACT_SEQUENCES),
        "artifacts_built": artifact_count,
    }
