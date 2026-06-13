"""
core/execution/build_content.py — Content generation for the build pipeline.

Extracted from build_pipeline.py to keep the orchestrator under 400 lines.
Public API: generate_content(), build_generation_prompt(), get_output_schema(),
            content_to_files(), scaffold_content()
"""
from __future__ import annotations

import json
import structlog
from core.execution.artifacts import ExecutionArtifact, ArtifactType

log = structlog.get_logger("execution.build_content")


def generate_content(
    artifact: ExecutionArtifact,
    budget_mode: str = "normal",
) -> dict[str, str]:
    """
    Generate artifact content via LLM.

    Returns dict of filename → content.
    Fail-open: falls back to scaffold template if LLM unavailable.
    """
    try:
        from core.planning.skill_llm import invoke_skill_llm

        prompt = build_generation_prompt(artifact)
        output_schema = get_output_schema(artifact.artifact_type)

        result = invoke_skill_llm(
            prompt_context=prompt,
            output_schema=output_schema,
            skill_id=f"build.{artifact.artifact_type.value}",
            budget_mode=budget_mode,
        )

        if result.get("invoked") and result.get("content") and not result.get("error"):
            return content_to_files(artifact.artifact_type, result["content"])

    except Exception as e:
        log.debug("content_generation_failed", err=str(e)[:80])

    return scaffold_content(artifact)


def build_generation_prompt(artifact: ExecutionArtifact) -> str:
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


def get_output_schema(artifact_type: ArtifactType) -> list[dict]:
    """Get LLM output schema for artifact generation."""
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


def content_to_files(artifact_type: ArtifactType, content: dict) -> dict[str, str]:
    """Map LLM content output to filename→content dict."""
    files: dict[str, str] = {}

    type_file_map: dict[ArtifactType, dict[str, str | None]] = {
        ArtifactType.LANDING_PAGE: {
            "html": "index.html",
            "title": None,
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

    files["artifact_spec.json"] = json.dumps(content, indent=2, default=str)
    return files


def scaffold_content(artifact: ExecutionArtifact) -> dict[str, str]:
    """Generate minimal scaffold when LLM is unavailable."""
    scaffold: dict[ArtifactType, dict[str, str]] = {
        ArtifactType.LANDING_PAGE: {
            "index.html": (
                f"<!DOCTYPE html><html><head><title>{artifact.name}</title></head>"
                f"<body><h1>{artifact.name}</h1><p>{artifact.description}</p></body></html>"
            ),
        },
        ArtifactType.API_SERVICE: {
            "main.py": (
                f'"""API Service: {artifact.name}"""\n'
                f"from fastapi import FastAPI\n"
                f'app = FastAPI(title="{artifact.name}")\n\n'
                f"@app.get(\"/health\")\ndef health():\n    return {{\"status\": \"ok\"}}\n"
            ),
            "requirements.txt": "fastapi\nuvicorn\n",
        },
        ArtifactType.MVP_FEATURE: {
            "feature.py": f'"""{artifact.name}"""\n\ndef main():\n    pass\n',
            "SPEC.md": f"# {artifact.name}\n\n{artifact.description}\n",
        },
        ArtifactType.CONTENT_ASSET: {
            "content.md": f"# {artifact.name}\n\n{artifact.description}\n",
        },
        ArtifactType.MARKETING_EXPERIMENT: {
            "experiment.json": json.dumps({
                "name": artifact.name,
                "hypothesis": artifact.expected_outcome,
                "metrics": [],
            }, indent=2),
        },
        ArtifactType.AUTOMATION_WORKFLOW: {
            "workflow.json": json.dumps({
                "name": artifact.name,
                "nodes": [],
                "trigger": "manual",
            }, indent=2),
        },
        ArtifactType.OPERATIONAL_WORKFLOW: {
            "workflow.md": f"# {artifact.name}\n\n{artifact.description}\n",
            "runbook.md": (
                f"# Runbook: {artifact.name}\n\n"
                f"## Steps\n1. Review this workflow\n2. Validate with stakeholders\n"
            ),
        },
        ArtifactType.DATA_PIPELINE: {
            "pipeline.py": f'"""{artifact.name}"""\n\ndef run():\n    pass\n',
            "pipeline.json": json.dumps({"name": artifact.name, "stages": []}, indent=2),
        },
    }
    return scaffold.get(artifact.artifact_type, {
        "artifact.md": f"# {artifact.name}\n\n{artifact.description}\n",
    })
