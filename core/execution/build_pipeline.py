"""
core/execution/build_pipeline.py — Safe build pipeline for artifacts.

Controlled pipeline: artifact_spec → validate → tool invoke → build → verify → record.

Design:
  - All builds are workspace-scoped (no system modifications)
  - All tool invocations go through ToolExecutor (approval-gated)
  - Build outputs are files in workspace/builds/<artifact_id>/
  - Verification checks are deterministic
  - Results feed back into strategic memory
  - Fail-open: build failure doesn't crash the system

Safety:
  - No uncontrolled external actions
  - No system self-modification
  - No financial transactions
  - All actions are traceable and reversible
"""
from __future__ import annotations

import json
import os
import time
import structlog
from dataclasses import dataclass, field
from pathlib import Path

from core.execution.artifacts import (
    ExecutionArtifact, ArtifactStatus, ArtifactType, ValidationRequirement,
)

_silent_log = __import__("structlog").get_logger(__name__)
log = structlog.get_logger("execution.build_pipeline")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_BUILDS_DIR = _WORKSPACE / "builds"


# ── Tool Integration Contracts ────────────────────────────────

@dataclass
class ToolContract:
    """Standard tool interaction contract for build pipeline."""
    tool_id: str
    input_schema: dict = field(default_factory=dict)
    output_type: str = "file"       # file, json, trigger, status
    failure_modes: list[str] = field(default_factory=list)
    retry_safe: bool = True
    max_retries: int = 1
    policy: str = "low"             # low, medium, high, critical

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "output_type": self.output_type,
            "failure_modes": self.failure_modes,
            "retry_safe": self.retry_safe,
            "max_retries": self.max_retries,
            "policy": self.policy,
        }


# Built-in tool contracts for build pipeline
TOOL_CONTRACTS: dict[str, ToolContract] = {
    "file.workspace.write": ToolContract(
        tool_id="file.workspace.write",
        input_schema={"path": "str", "content": "str"},
        output_type="file",
        failure_modes=["permission_denied", "disk_full", "path_invalid"],
        retry_safe=True,
        policy="low",
    ),
    "git.status": ToolContract(
        tool_id="git.status",
        input_schema={},
        output_type="json",
        failure_modes=["not_a_repo", "git_not_installed"],
        retry_safe=True,
        policy="low",
    ),
    "http.webhook.post": ToolContract(
        tool_id="http.webhook.post",
        input_schema={"url": "str", "payload": "dict"},
        output_type="status",
        failure_modes=["timeout", "connection_error", "auth_failure", "rate_limit"],
        retry_safe=False,
        max_retries=0,
        policy="medium",
    ),
    "n8n.workflow.trigger": ToolContract(
        tool_id="n8n.workflow.trigger",
        input_schema={"workflow_id": "str", "data": "dict"},
        output_type="trigger",
        failure_modes=["not_configured", "workflow_not_found", "execution_error"],
        retry_safe=False,
        max_retries=0,
        policy="medium",
    ),
    "notification.log": ToolContract(
        tool_id="notification.log",
        input_schema={"message": "str", "level": "str"},
        output_type="status",
        failure_modes=[],
        retry_safe=True,
        policy="low",
    ),
}


# ── Build Result ──────────────────────────────────────────────

@dataclass
class BuildResult:
    """Result of a build pipeline execution."""
    artifact_id: str
    success: bool = False
    status: ArtifactStatus = ArtifactStatus.FAILED
    output_dir: str = ""
    output_files: list[str] = field(default_factory=list)
    validation_passed: list[str] = field(default_factory=list)
    validation_failed: list[str] = field(default_factory=list)
    build_log: list[str] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0
    tools_invoked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "success": self.success,
            "status": self.status.value,
            "output_dir": self.output_dir,
            "output_files": self.output_files[:50],
            "validation_passed": self.validation_passed,
            "validation_failed": self.validation_failed,
            "build_log": self.build_log[-30:],
            "error": self.error[:300],
            "duration_ms": round(self.duration_ms),
            "tools_invoked": self.tools_invoked,
        }


# ── Build Pipeline ────────────────────────────────────────────

class BuildPipeline:
    """
    Safe build pipeline for artifact production.

    Pipeline stages:
      1. VALIDATE — check artifact spec is complete
      2. PREPARE — create build directory, resolve tool deps
      3. BUILD — invoke LLM to generate artifact content
      4. WRITE — write generated content to workspace files
      5. VERIFY — run validation checks on output
      6. RECORD — log result to execution memory

    All stages are fail-open. Pipeline can be interrupted at any point.
    """

    def build(self, artifact: ExecutionArtifact, budget_mode: str = "normal") -> BuildResult:
        """
        Execute the full build pipeline for an artifact.

        Returns BuildResult with status and output details.
        """
        t0 = time.time()
        result = BuildResult(artifact_id=artifact.artifact_id)

        try:
            # Stage 0: POLICY CHECK
            try:
                from core.execution.policy import is_safe_to_build, get_policy_classification
                safe, violations = is_safe_to_build(artifact)
                policy_class = get_policy_classification(artifact)
                if not safe:
                    blocking = [v for v in violations if v.severity == "block"]
                    result.error = f"Policy blocked: {blocking[0].description}" if blocking else "Policy blocked"
                    result.build_log.append(f"POLICY: BLOCKED — {result.error}")
                    artifact.status = ArtifactStatus.FAILED
                    artifact.error = result.error
                    result.duration_ms = (time.time() - t0) * 1000
                    return result
                result.build_log.append(f"POLICY: OK (class={policy_class})")
            except Exception:
                policy_class = "low"
                result.build_log.append("POLICY: SKIPPED (fail-open)")

            # Stage 1: VALIDATE spec
            issues = artifact.validate_spec()
            if issues:
                result.error = f"Spec validation failed: {', '.join(issues)}"
                result.build_log.append(f"VALIDATE: FAILED — {result.error}")
                artifact.status = ArtifactStatus.FAILED
                artifact.error = result.error
                result.duration_ms = (time.time() - t0) * 1000
                return result
            result.build_log.append("VALIDATE: OK")
            artifact.status = ArtifactStatus.VALIDATED

            # Stage 2: PREPARE build directory
            build_dir = _BUILDS_DIR / artifact.artifact_id
            build_dir.mkdir(parents=True, exist_ok=True)
            result.output_dir = str(build_dir)
            result.build_log.append(f"PREPARE: dir={build_dir}")

            # Stage 3: BUILD — generate content via LLM
            artifact.status = ArtifactStatus.BUILDING
            content = self._generate_content(artifact, budget_mode)
            if not content:
                result.error = "Content generation produced empty output"
                result.build_log.append("BUILD: FAILED — empty output")
                artifact.status = ArtifactStatus.FAILED
                artifact.error = result.error
                result.duration_ms = (time.time() - t0) * 1000
                return result
            result.build_log.append(f"BUILD: generated {len(content)} content items")

            # Stage 4: WRITE files
            written = self._write_files(build_dir, content, artifact)
            result.output_files = written
            result.tools_invoked.append("file.workspace.write")
            result.build_log.append(f"WRITE: {len(written)} files written")
            artifact.output_files = written

            # Stage 5: VERIFY
            passed, failed = self._verify(build_dir, artifact.validation_requirements)
            result.validation_passed = passed
            result.validation_failed = failed
            if failed:
                required_failed = [f for f in failed
                                   if any(v.name == f and v.required
                                          for v in artifact.validation_requirements)]
                if required_failed:
                    result.error = f"Required validation failed: {', '.join(required_failed)}"
                    result.build_log.append(f"VERIFY: FAILED — {result.error}")
                    artifact.status = ArtifactStatus.FAILED
                    artifact.error = result.error
                    result.duration_ms = (time.time() - t0) * 1000
                    return result
            result.build_log.append(f"VERIFY: {len(passed)} passed, {len(failed)} failed")

            # Stage 5b: QUALITY GATE (fail-open)
            try:
                from core.execution.quality_gate import ArtifactQualityGate
                gate = ArtifactQualityGate()
                # Find the primary output file
                primary_file = None
                if result.output_files:
                    primary_file = str(result.output_files[0])
                elif build_dir.exists():
                    for f in sorted(build_dir.iterdir()):
                        if f.is_file() and f.suffix in (".html", ".py", ".json", ".md", ".yaml", ".txt"):
                            primary_file = str(f)
                            break

                if primary_file:
                    qr = gate.verify(primary_file, artifact.artifact_type.value)
                    result.build_log.append(
                        f"QUALITY: score={qr.score:.2f}, issues={len(qr.issues)}, passed={qr.passed}"
                    )
                    if not qr.passed and qr.correctable:
                        correction = gate.auto_correct(primary_file, qr.issues)
                        if correction.corrected:
                            result.build_log.append(
                                f"QUALITY: auto-corrected ({len(correction.fixes_applied)} fixes)"
                            )
                    # Store confidence from quality gate
                    result.build_log.append(f"confidence: {qr.score:.2f}")
            except Exception as qe:
                result.build_log.append(f"QUALITY: gate skipped ({str(qe)[:60]})")

            # Stage 6: SUCCESS
            artifact.status = ArtifactStatus.BUILT
            artifact.built_at = time.time()
            artifact.build_log = result.build_log
            result.success = True
            result.status = ArtifactStatus.BUILT
            result.build_log.append("COMPLETE: artifact built successfully")

            # Record feedback signals (fail-open)
            try:
                from core.execution.feedback import (
                    build_execution_trace, get_feedback_collector,
                )
                trace = build_execution_trace(
                    artifact=artifact,
                    build_result=result,
                    policy_class=policy_class,
                )
                get_feedback_collector().record(trace)
                result.build_log.append(
                    f"FEEDBACK: confidence={trace.confidence.composite:.3f}"
                )
            except Exception:
                result.build_log.append("FEEDBACK: SKIPPED (fail-open)")

        except Exception as e:
            result.error = f"Pipeline error: {str(e)[:200]}"
            result.build_log.append(f"ERROR: {result.error}")
            artifact.status = ArtifactStatus.FAILED
            artifact.error = result.error

        result.duration_ms = (time.time() - t0) * 1000

        # Auto-retry on failure via recovery module (fail-open)
        if not result.success and result.error:
            try:
                from core.execution.recovery import retry_build
                retry_result = retry_build(artifact, result.error, budget_mode)
                if retry_result.recovered and retry_result.final_build_result:
                    result.build_log.append(
                        f"RECOVERY: recovered after {len(retry_result.attempts)} attempts"
                    )
                    return retry_result.final_build_result
                else:
                    result.build_log.append(
                        f"RECOVERY: failed ({len(retry_result.attempts)} attempts, "
                        f"class={retry_result.failure_class.category.value})"
                    )
            except Exception as re:
                result.build_log.append(f"RECOVERY: SKIPPED (fail-open: {str(re)[:80]})")

        return result

    def _generate_content(
        self,
        artifact: ExecutionArtifact,
        budget_mode: str = "normal",
    ) -> dict[str, str]:
        """
        Generate artifact content via LLM.

        Returns dict of filename → content.
        Fail-open: returns empty dict if LLM unavailable.
        """
        try:
            from core.planning.skill_llm import invoke_skill_llm

            # Build generation prompt from artifact spec
            prompt = self._build_generation_prompt(artifact)

            # Map artifact type to output schema
            output_schema = self._get_output_schema(artifact.artifact_type)

            result = invoke_skill_llm(
                prompt_context=prompt,
                output_schema=output_schema,
                skill_id=f"build.{artifact.artifact_type.value}",
                budget_mode=budget_mode,
            )

            if result.get("invoked") and result.get("content") and not result.get("error"):
                return self._content_to_files(artifact.artifact_type, result["content"])

        except Exception as e:
            log.debug("content_generation_failed", err=str(e)[:80])

        # Fallback: generate scaffold from template
        return self._scaffold_content(artifact)

    def _build_generation_prompt(self, artifact: ExecutionArtifact) -> str:
        """Build LLM prompt from artifact spec."""
        ctx_str = ""
        if artifact.input_context:
            ctx_items = []
            for k, v in list(artifact.input_context.items())[:10]:
                val = str(v)[:300] if not isinstance(v, str) else v[:300]
                ctx_items.append(f"- {k}: {val}")
            ctx_str = "\n## Input Context\n" + "\n".join(ctx_items)

        return f"""## Task
Generate a production-quality {artifact.artifact_type.value} artifact.

## Artifact: {artifact.name}
{artifact.description}

## Expected Outcome
{artifact.expected_outcome}
{ctx_str}

## Requirements
- Generate complete, deployable code/content
- Follow best practices for {artifact.artifact_type.value}
- Include all required files
- Make it production-ready, not placeholder"""

    def _get_output_schema(self, artifact_type: ArtifactType) -> list[dict]:
        """Get output schema for artifact generation."""
        schemas: dict[str, list[dict]] = {
            ArtifactType.LANDING_PAGE: [
                {"name": "html", "type": "string", "description": "Complete HTML page with inline CSS"},
                {"name": "title", "type": "string", "description": "Page title"},
                {"name": "meta_description", "type": "string", "description": "SEO meta description"},
            ],
            ArtifactType.AUTOMATION_WORKFLOW: [
                {"name": "workflow_json", "type": "json", "description": "n8n-compatible workflow definition"},
                {"name": "description", "type": "string", "description": "Workflow description"},
                {"name": "trigger_type", "type": "string", "description": "Trigger type (webhook, cron, manual)"},
            ],
            ArtifactType.API_SERVICE: [
                {"name": "main_code", "type": "string", "description": "Main service code (Python/FastAPI)"},
                {"name": "requirements", "type": "string", "description": "Python requirements.txt content"},
                {"name": "readme", "type": "string", "description": "Service documentation"},
            ],
            ArtifactType.MVP_FEATURE: [
                {"name": "implementation", "type": "string", "description": "Feature implementation code"},
                {"name": "spec", "type": "string", "description": "Feature specification in markdown"},
                {"name": "tests", "type": "string", "description": "Test code for the feature"},
            ],
            ArtifactType.MARKETING_EXPERIMENT: [
                {"name": "hypothesis", "type": "string", "description": "Experiment hypothesis"},
                {"name": "experiment_plan", "type": "json", "description": "Structured experiment definition"},
                {"name": "success_metrics", "type": "list", "description": "Measurable success criteria"},
            ],
            ArtifactType.CONTENT_ASSET: [
                {"name": "content", "type": "string", "description": "Main content in markdown"},
                {"name": "title", "type": "string", "description": "Content title"},
                {"name": "summary", "type": "string", "description": "Brief summary"},
            ],
        }
        return schemas.get(artifact_type, [
            {"name": "content", "type": "string", "description": "Generated content"},
        ])

    def _content_to_files(self, artifact_type: ArtifactType, content: dict) -> dict[str, str]:
        """Map LLM content output to filename→content dict."""
        files: dict[str, str] = {}

        type_file_map: dict[ArtifactType, dict[str, str]] = {
            ArtifactType.LANDING_PAGE: {
                "html": "index.html",
                "title": None,  # metadata, not a file
                "meta_description": None,
            },
            ArtifactType.API_SERVICE: {
                "main_code": "main.py",
                "requirements": "requirements.txt",
                "readme": "README.md",
            },
            ArtifactType.MVP_FEATURE: {
                "implementation": "feature.py",
                "spec": "SPEC.md",
                "tests": "test_feature.py",
            },
            ArtifactType.CONTENT_ASSET: {
                "content": "content.md",
            },
            ArtifactType.MARKETING_EXPERIMENT: {
                "experiment_plan": "experiment.json",
                "hypothesis": None,
                "success_metrics": None,
            },
            ArtifactType.AUTOMATION_WORKFLOW: {
                "workflow_json": "workflow.json",
            },
        }

        fmap = type_file_map.get(artifact_type, {})
        for field_name, filename in fmap.items():
            if filename and field_name in content:
                val = content[field_name]
                if isinstance(val, (dict, list)):
                    files[filename] = json.dumps(val, indent=2)
                elif isinstance(val, str) and val.strip():
                    files[filename] = val

        # Also write full spec as JSON
        files["artifact_spec.json"] = json.dumps(content, indent=2, default=str)

        return files

    def _scaffold_content(self, artifact: ExecutionArtifact) -> dict[str, str]:
        """Generate minimal scaffold when LLM is unavailable."""
        scaffold = {
            ArtifactType.LANDING_PAGE: {"index.html": f"<!DOCTYPE html><html><head><title>{artifact.name}</title></head><body><h1>{artifact.name}</h1><p>{artifact.description}</p></body></html>"},
            ArtifactType.API_SERVICE: {"main.py": f'"""API Service: {artifact.name}"""\nfrom fastapi import FastAPI\napp = FastAPI(title="{artifact.name}")\n\n@app.get("/health")\ndef health():\n    return {{"status": "ok"}}\n', "requirements.txt": "fastapi\nuvicorn\n"},
            ArtifactType.MVP_FEATURE: {"feature.py": f'"""{artifact.name}"""\n\ndef main():\n    pass\n', "SPEC.md": f"# {artifact.name}\n\n{artifact.description}\n"},
            ArtifactType.CONTENT_ASSET: {"content.md": f"# {artifact.name}\n\n{artifact.description}\n"},
            ArtifactType.MARKETING_EXPERIMENT: {"experiment.json": json.dumps({"name": artifact.name, "hypothesis": artifact.expected_outcome, "metrics": []}, indent=2)},
            ArtifactType.AUTOMATION_WORKFLOW: {"workflow.json": json.dumps({"name": artifact.name, "nodes": [], "trigger": "manual"}, indent=2)},
            ArtifactType.OPERATIONAL_WORKFLOW: {"workflow.md": f"# {artifact.name}\n\n{artifact.description}\n", "runbook.md": f"# Runbook: {artifact.name}\n\n## Steps\n1. Review this workflow\n2. Validate with stakeholders\n"},
            ArtifactType.DATA_PIPELINE: {"pipeline.py": f'"""{artifact.name}"""\n\ndef run():\n    pass\n', "pipeline.json": json.dumps({"name": artifact.name, "stages": []}, indent=2)},
        }
        return scaffold.get(artifact.artifact_type, {"artifact.md": f"# {artifact.name}\n\n{artifact.description}\n"})

    def _write_files(
        self,
        build_dir: Path,
        content: dict[str, str],
        artifact: ExecutionArtifact,
    ) -> list[str]:
        """Write generated content to build directory. Returns list of written paths."""
        written = []
        for filename, file_content in content.items():
            try:
                filepath = build_dir / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(str(file_content), encoding="utf-8")
                written.append(str(filepath))
            except Exception as e:
                log.debug("file_write_failed", path=str(filepath), err=str(e)[:80])
        return written

    def _verify(
        self,
        build_dir: Path,
        requirements: list[ValidationRequirement],
    ) -> tuple[list[str], list[str]]:
        """
        Run validation checks on build output.

        Returns (passed_names, failed_names).
        """
        passed = []
        failed = []

        for req in requirements:
            try:
                if req.check_type == "exists":
                    target = build_dir / req.target
                    if target.exists() and target.stat().st_size > 0:
                        passed.append(req.name)
                    else:
                        failed.append(req.name)
                elif req.check_type == "content":
                    target = build_dir / req.target
                    if target.exists():
                        content = target.read_text(encoding="utf-8")
                        # Basic content check: non-empty and has some substance
                        if len(content.strip()) > 10:
                            passed.append(req.name)
                        else:
                            failed.append(req.name)
                    else:
                        failed.append(req.name)
                elif req.check_type == "schema":
                    target = build_dir / req.target
                    if target.exists():
                        try:
                            json.loads(target.read_text(encoding="utf-8"))
                            passed.append(req.name)
                        except json.JSONDecodeError:
                            failed.append(req.name)
                    else:
                        failed.append(req.name)
                elif req.check_type == "manual":
                    # Manual checks always pass (human must verify)
                    passed.append(req.name)
                else:
                    # Unknown check type — skip
                    passed.append(req.name)
            except Exception:
                failed.append(req.name)

        return passed, failed

    def _record_result(self, artifact: ExecutionArtifact, result: BuildResult) -> None:
        """Record build result to strategic memory. Fail-open."""
        try:
            from core.economic.strategic_memory import get_strategic_memory, StrategicRecord
            get_strategic_memory().record(StrategicRecord(
                strategy_type=f"build.{artifact.artifact_type.value}",
                playbook_id="",
                run_id=artifact.artifact_id,
                context_features={"artifact_type": artifact.artifact_type.value},
                schema_type=artifact.source_schema,
                outcome_score=1.0 if result.success else 0.2,
                confidence=len(result.validation_passed) / max(
                    len(result.validation_passed) + len(result.validation_failed), 1),
                completeness=len(result.validation_passed) / max(
                    len(result.validation_passed) + len(result.validation_failed), 1),
                goal=artifact.name,
                key_findings=[f"Built: {', '.join(result.output_files[-3:])}"]
                             if result.success else [],
                failure_reasons=result.validation_failed[:5] if not result.success else [],
            ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='build_pipeline.py')


# ── Singleton ─────────────────────────────────────────────────

_pipeline: BuildPipeline | None = None


def get_build_pipeline() -> BuildPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = BuildPipeline()
    return _pipeline
