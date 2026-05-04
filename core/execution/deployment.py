"""
core/execution/deployment.py — Deployment target model + pipeline + verification.

Phases 3-6 of Build Recovery + Deployment.

Design:
  - 5 deployment target types (all low-risk, workspace-scoped)
  - Deployment pipeline: eligibility → policy → deploy → verify → record
  - Real verification per target type (file checks, entrypoint checks)
  - Feedback into strategic memory + execution trace + performance
  - All fail-open, policy-governed, reversible
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import structlog
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("execution.deployment")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_DEPLOY_DIR = _WORKSPACE / "deployments"


# ── Phase 3: Deployment Target Model ──────────────────────────

class DeploymentTargetType(str, Enum):
    """Safe, low-complexity deployment targets."""
    LOCAL_PREVIEW    = "local_preview"        # Local output directory for preview
    STATIC_BUNDLE    = "static_bundle"        # Static site package (HTML/CSS/JS)
    API_PACKAGE      = "api_package"          # API service ready for deployment
    WEBHOOK_PACKAGE  = "webhook_package"      # Automation/webhook config package
    EXPORT_BUNDLE    = "export_bundle"        # Structured export (docs, data, specs)


class DeploymentStatus(str, Enum):
    PENDING      = "pending"
    ELIGIBLE     = "eligible"
    DEPLOYING    = "deploying"
    DEPLOYED     = "deployed"
    VERIFIED     = "verified"
    FAILED       = "failed"
    ROLLED_BACK  = "rolled_back"


@dataclass
class DeploymentTarget:
    """A deployment target with verification and rollback."""
    target_id: str = ""
    target_type: DeploymentTargetType = DeploymentTargetType.LOCAL_PREVIEW
    required_tools: list[str] = field(default_factory=lambda: ["file.workspace.write"])
    policy_level: str = "low"       # low, medium (no high/critical in this sprint)
    verification_method: str = "file_exists"
    rollback_strategy: str = "delete_output"  # delete_output, restore_backup, none
    output_dir: str = ""
    description: str = ""

    def __post_init__(self):
        if not self.target_id:
            self.target_id = f"deploy-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "target_type": self.target_type.value,
            "required_tools": self.required_tools,
            "policy_level": self.policy_level,
            "verification_method": self.verification_method,
            "rollback_strategy": self.rollback_strategy,
            "output_dir": self.output_dir,
            "description": self.description,
        }


# Target registry — safe targets only
DEPLOYMENT_TARGETS: dict[str, DeploymentTarget] = {
    "local_preview": DeploymentTarget(
        target_id="local_preview",
        target_type=DeploymentTargetType.LOCAL_PREVIEW,
        description="Local workspace directory for previewing artifacts",
        verification_method="file_exists",
        rollback_strategy="delete_output",
        policy_level="low",
    ),
    "static_bundle": DeploymentTarget(
        target_id="static_bundle",
        target_type=DeploymentTargetType.STATIC_BUNDLE,
        description="Static site bundle (index.html + assets) ready for hosting",
        verification_method="entrypoint_check",
        rollback_strategy="delete_output",
        policy_level="low",
    ),
    "api_package": DeploymentTarget(
        target_id="api_package",
        target_type=DeploymentTargetType.API_PACKAGE,
        description="API service package with main.py + requirements.txt",
        verification_method="package_check",
        rollback_strategy="delete_output",
        policy_level="low",
    ),
    "webhook_package": DeploymentTarget(
        target_id="webhook_package",
        target_type=DeploymentTargetType.WEBHOOK_PACKAGE,
        description="Webhook/automation configuration package",
        verification_method="config_check",
        rollback_strategy="delete_output",
        policy_level="low",
    ),
    "export_bundle": DeploymentTarget(
        target_id="export_bundle",
        target_type=DeploymentTargetType.EXPORT_BUNDLE,
        description="Structured document/data export bundle",
        verification_method="file_exists",
        rollback_strategy="delete_output",
        policy_level="low",
    ),
}

# Artifact type → recommended deployment target
ARTIFACT_DEPLOY_MAP: dict[str, str] = {
    "landing_page": "static_bundle",
    "content_asset": "export_bundle",
    "api_service": "api_package",
    "automation_workflow": "webhook_package",
    "mvp_feature": "api_package",
    "marketing_experiment": "export_bundle",
    "data_pipeline": "export_bundle",
    "operational_workflow": "webhook_package",
}


def get_deployment_target(artifact_type: str) -> DeploymentTarget:
    """Get recommended deployment target for an artifact type."""
    target_id = ARTIFACT_DEPLOY_MAP.get(artifact_type, "local_preview")
    template = DEPLOYMENT_TARGETS.get(target_id, DEPLOYMENT_TARGETS["local_preview"])
    # Return a copy with fresh ID
    return DeploymentTarget(
        target_type=template.target_type,
        required_tools=list(template.required_tools),
        policy_level=template.policy_level,
        verification_method=template.verification_method,
        rollback_strategy=template.rollback_strategy,
        description=template.description,
    )


# ── Phase 4: Deployment Pipeline ──────────────────────────────

@dataclass
class DeploymentResult:
    """Complete deployment result with verification."""
    deployment_id: str = ""
    artifact_id: str = ""
    target: dict = field(default_factory=dict)
    status: DeploymentStatus = DeploymentStatus.PENDING
    output_dir: str = ""
    output_files: list[str] = field(default_factory=list)
    verification_passed: bool = False
    verification_details: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    deploy_log: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.deployment_id:
            self.deployment_id = f"dep-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "artifact_id": self.artifact_id,
            "target": self.target,
            "status": self.status.value,
            "output_dir": self.output_dir,
            "output_files": self.output_files[:50],
            "verification_passed": self.verification_passed,
            "verification_details": self.verification_details,
            "error": self.error[:300],
            "duration_ms": round(self.duration_ms),
            "deploy_log": self.deploy_log[-20:],
        }


# Deployment store (in-memory, fail-open)
_deployments: list[DeploymentResult] = []


def get_deployments() -> list[DeploymentResult]:
    return list(_deployments)


class DeploymentPipeline:
    """
    Controlled deployment pipeline.

    Flow:
      1. ELIGIBILITY — check build is successful + complete
      2. POLICY — verify deployment is policy-safe
      3. DEPLOY — copy/package artifacts to target
      4. VERIFY — confirm deployment worked
      5. RECORD — log outcome to memory systems
    """

    def deploy(self, build_result, artifact, target: DeploymentTarget | None = None) -> DeploymentResult:
        """Deploy a successfully built artifact to a target."""
        t0 = time.time()
        result = DeploymentResult(artifact_id=artifact.artifact_id)

        try:
            # Auto-select target if not provided
            if target is None:
                target = get_deployment_target(artifact.artifact_type.value)

            result.target = target.to_dict()

            # Stage 1: ELIGIBILITY
            if not build_result.success:
                result.error = "Build not successful — cannot deploy"
                result.status = DeploymentStatus.FAILED
                result.deploy_log.append("ELIGIBILITY: FAILED — build not successful")
                result.duration_ms = (time.time() - t0) * 1000
                return result

            if not build_result.output_files:
                result.error = "No output files from build"
                result.status = DeploymentStatus.FAILED
                result.deploy_log.append("ELIGIBILITY: FAILED — no output files")
                result.duration_ms = (time.time() - t0) * 1000
                return result

            result.status = DeploymentStatus.ELIGIBLE
            result.deploy_log.append(f"ELIGIBILITY: OK ({len(build_result.output_files)} files)")

            # Stage 2: POLICY
            try:
                from core.execution.policy import get_policy_classification
                policy_class = get_policy_classification(artifact)
                if policy_class == "critical":
                    result.error = "Deployment blocked by policy (critical classification)"
                    result.status = DeploymentStatus.FAILED
                    result.deploy_log.append("POLICY: BLOCKED — critical")
                    result.duration_ms = (time.time() - t0) * 1000
                    return result
                result.deploy_log.append(f"POLICY: OK (class={policy_class})")
            except Exception:
                result.deploy_log.append("POLICY: SKIPPED (fail-open)")

            # Stage 3: DEPLOY
            result.status = DeploymentStatus.DEPLOYING
            deploy_dir = _DEPLOY_DIR / result.deployment_id
            deploy_dir.mkdir(parents=True, exist_ok=True)
            result.output_dir = str(deploy_dir)

            build_dir = Path(build_result.output_dir) if build_result.output_dir else None
            deployed_files = []

            if build_dir and build_dir.exists():
                for src_file in build_dir.iterdir():
                    if src_file.is_file():
                        dst = deploy_dir / src_file.name
                        shutil.copy2(str(src_file), str(dst))
                        deployed_files.append(src_file.name)
            else:
                # Fallback: create manifest
                manifest = {
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type.value,
                    "deployed_at": time.time(),
                    "source_files": build_result.output_files,
                }
                (deploy_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
                deployed_files.append("manifest.json")

            result.output_files = deployed_files
            result.deploy_log.append(f"DEPLOY: {len(deployed_files)} files to {deploy_dir}")

            # Stage 4: VERIFY
            verification = self._verify_deployment(deploy_dir, target, deployed_files)
            result.verification_passed = verification["passed"]
            result.verification_details = verification
            result.deploy_log.append(
                f"VERIFY: {'PASSED' if verification['passed'] else 'FAILED'} "
                f"({verification.get('method', 'unknown')})"
            )

            if verification["passed"]:
                result.status = DeploymentStatus.VERIFIED
                # Update artifact status
                try:
                    from core.execution.artifacts import ArtifactStatus
                    artifact.status = ArtifactStatus.DEPLOYED
                except Exception:
                    _silent_log.debug("suppressed_exception", src='deployment.py')
            else:
                result.status = DeploymentStatus.DEPLOYED  # Deployed but not verified

            # Stage 5: RECORD feedback
            self._record_feedback(result, artifact)
            result.deploy_log.append("RECORD: feedback recorded")

        except Exception as e:
            result.error = f"Deployment error: {str(e)[:200]}"
            result.status = DeploymentStatus.FAILED
            result.deploy_log.append(f"ERROR: {result.error}")

        result.duration_ms = (time.time() - t0) * 1000
        _deployments.append(result)
        return result

    def rollback(self, deployment_id: str) -> bool:
        """Rollback a deployment by removing output directory."""
        dep = next((d for d in _deployments if d.deployment_id == deployment_id), None)
        if not dep:
            return False
        try:
            deploy_dir = Path(dep.output_dir)
            if deploy_dir.exists():
                shutil.rmtree(str(deploy_dir))
            dep.status = DeploymentStatus.ROLLED_BACK
            dep.deploy_log.append("ROLLBACK: completed")
            return True
        except Exception as e:
            dep.deploy_log.append(f"ROLLBACK: failed — {str(e)[:100]}")
            return False

    # ── Phase 5: Verification ─────────────────────────────────

    def _verify_deployment(
        self, deploy_dir: Path, target: DeploymentTarget, files: list[str]
    ) -> dict:
        """Verify deployment based on target verification method."""
        method = target.verification_method
        result = {"passed": False, "method": method, "checks": []}

        try:
            if method == "file_exists":
                # All expected files exist
                exists = all((deploy_dir / f).exists() for f in files)
                non_empty = all((deploy_dir / f).stat().st_size > 0 for f in files if (deploy_dir / f).exists())
                result["checks"].append({"files_exist": exists, "non_empty": non_empty})
                result["passed"] = exists and non_empty

            elif method == "entrypoint_check":
                # Static bundle must have index.html
                has_entry = (deploy_dir / "index.html").exists()
                has_content = has_entry and (deploy_dir / "index.html").stat().st_size > 50
                result["checks"].append({"has_index_html": has_entry, "has_content": has_content})
                result["passed"] = has_entry and has_content

            elif method == "package_check":
                # API package must have main entry + requirements
                has_main = any(
                    (deploy_dir / f).exists()
                    for f in ["main.py", "app.py", "server.py"]
                )
                has_reqs = (deploy_dir / "requirements.txt").exists()
                result["checks"].append({"has_main": has_main, "has_requirements": has_reqs})
                result["passed"] = has_main  # requirements optional

            elif method == "config_check":
                # Webhook/automation package must have config
                has_config = any(
                    (deploy_dir / f).exists()
                    for f in ["config.json", "workflow.json", "manifest.json"]
                )
                result["checks"].append({"has_config": has_config})
                result["passed"] = has_config

            else:
                # Unknown method: check any files exist
                result["passed"] = len(files) > 0
                result["checks"].append({"files_count": len(files)})

        except Exception as e:
            result["error"] = str(e)[:100]

        return result

    # ── Phase 6: Feedback + Learning ──────────────────────────

    def _record_feedback(self, result: DeploymentResult, artifact) -> None:
        """Record deployment outcome to memory systems."""
        try:
            # Strategic memory
            from core.economic.strategic_memory import StrategicRecord, get_strategic_memory
            mem = get_strategic_memory()
            mem.record(StrategicRecord(
                record_type="deployment_outcome",
                score=1.0 if result.verification_passed else 0.3,
                context={
                    "artifact_type": artifact.artifact_type.value,
                    "target_type": result.target.get("target_type", "unknown"),
                    "verified": result.verification_passed,
                },
                findings={"status": result.status.value, "files": len(result.output_files)},
                failures={"error": result.error} if result.error else {},
            ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='deployment.py')

        try:
            # Kernel performance
            from kernel.runtime.boot import get_runtime
            rt = get_runtime()
            if rt:
                rt.performance.record_tool_outcome(
                    tool_id=f"deploy.{result.target.get('target_type', 'unknown')}",
                    success=result.verification_passed,
                    duration_ms=result.duration_ms,
                )
        except Exception:
            _silent_log.debug("suppressed_exception", src='deployment.py')

        try:
            # Cognitive journal
            from core.cognitive_events.emitter import ce_emit
            ce_emit.tool_completed(
                tool_id="deployment_pipeline",
                mission_id=artifact.source_mission_id or "",
                duration_ms=result.duration_ms,
                metadata={
                    "deployment_id": result.deployment_id,
                    "target": result.target.get("target_type", ""),
                    "verified": result.verification_passed,
                    "status": result.status.value,
                },
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='deployment.py')
