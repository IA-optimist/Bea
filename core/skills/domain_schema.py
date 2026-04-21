"""
core/skills/domain_schema.py — Domain Skill schema and types.

A domain skill is a structured professional capability module.
It defines inputs, outputs, reasoning steps, quality checks,
and few-shot examples. Skills are composable — agents chain
multiple skills to produce comprehensive outputs.

NOT a prompt. NOT a template. A structured reasoning module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
_silent_log = __import__("structlog").get_logger(__name__)


@dataclass
class SkillInput:
    """A named input parameter for a skill."""
    name: str
    type: str = "string"  # string, json, list, number
    required: bool = True
    description: str = ""
    default: Any = None


@dataclass
class SkillOutput:
    """A named output field from a skill."""
    name: str
    type: str = "string"
    description: str = ""


@dataclass
class QualityCheck:
    """A quality gate for skill output validation."""
    name: str
    description: str
    check_type: str = "completeness"  # completeness, structure, coherence, contradiction
    threshold: float = 0.7
    required: bool = True


@dataclass
class DomainSkill:
    """
    A structured professional capability module.

    Loaded from a skill directory containing:
      - skill.json: metadata, inputs, outputs, quality checks
      - logic.md: step-by-step reasoning structure
      - examples.json: few-shot structured examples
      - evaluation.md: criteria for good output
    """
    id: str
    version: str = "1.0"
    name: str = ""
    description: str = ""
    domain: str = ""  # market_research, offer_design, etc.
    inputs: list[SkillInput] = field(default_factory=list)
    outputs: list[SkillOutput] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    quality_checks: list[QualityCheck] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Loaded content (not serialized in skill.json)
    logic: str = ""  # from logic.md
    examples: list[dict] = field(default_factory=list)  # from examples.json
    evaluation: str = ""  # from evaluation.md

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "inputs": [{"name": i.name, "type": i.type, "required": i.required,
                        "description": i.description} for i in self.inputs],
            "outputs": [{"name": o.name, "type": o.type,
                        "description": o.description} for o in self.outputs],
            "dependencies": self.dependencies,
            "quality_checks": [{"name": q.name, "check_type": q.check_type,
                               "threshold": q.threshold} for q in self.quality_checks],
            "tags": self.tags,
            "has_logic": bool(self.logic),
            "has_examples": len(self.examples) > 0,
            "has_evaluation": bool(self.evaluation),
        }

    @classmethod
    def from_directory(cls, path: str | Path) -> "DomainSkill":
        """Load a skill from a directory containing skill.json + supporting files."""
        p = Path(path)
        skill_json = p / "skill.json"
        if not skill_json.is_file():
            raise FileNotFoundError(f"No skill.json in {path}")

        data = json.loads(skill_json.read_text("utf-8"))

        skill = cls(
            id=data["id"],
            version=data.get("version", "1.0"),
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            domain=data.get("domain", ""),
            dependencies=data.get("dependencies", []),
            tags=data.get("tags", []),
        )

        # Parse inputs
        for inp in data.get("inputs", []):
            skill.inputs.append(SkillInput(
                name=inp["name"],
                type=inp.get("type", "string"),
                required=inp.get("required", True),
                description=inp.get("description", ""),
                default=inp.get("default"),
            ))

        # Parse outputs
        for out in data.get("outputs", []):
            skill.outputs.append(SkillOutput(
                name=out["name"],
                type=out.get("type", "string"),
                description=out.get("description", ""),
            ))

        # Parse quality checks
        for qc in data.get("quality_checks", []):
            skill.quality_checks.append(QualityCheck(
                name=qc["name"],
                description=qc.get("description", ""),
                check_type=qc.get("check_type", "completeness"),
                threshold=qc.get("threshold", 0.7),
                required=qc.get("required", True),
            ))

        # Load supporting files
        logic_md = p / "logic.md"
        if logic_md.is_file():
            skill.logic = logic_md.read_text("utf-8")

        examples_json = p / "examples.json"
        if examples_json.is_file():
            try:
                skill.examples = json.loads(examples_json.read_text("utf-8"))
            except json.JSONDecodeError:
                _silent_log.debug("suppressed_exception", src='domain_schema.py')

        eval_md = p / "evaluation.md"
        if eval_md.is_file():
            skill.evaluation = eval_md.read_text("utf-8")

        return skill

    def build_prompt_context(self, inputs: dict) -> str:
        """Build a structured prompt context from skill definition + inputs."""
        parts = []
        parts.append(f"## Skill: {self.name}")
        parts.append(f"**Goal:** {self.description}\n")

        if self.logic:
            parts.append("## Reasoning Structure")
            parts.append(self.logic)

        if self.examples:
            parts.append("\n## Examples")
            for i, ex in enumerate(self.examples[:3], 1):
                parts.append(f"\n### Example {i}")
                parts.append(f"**Input:** {json.dumps(ex.get('input', {}), indent=2)}")
                parts.append(f"**Output:** {json.dumps(ex.get('output', {}), indent=2)}")

        if self.evaluation:
            parts.append("\n## Quality Criteria")
            parts.append(self.evaluation)

        parts.append("\n## Your Input")
        for inp in self.inputs:
            val = inputs.get(inp.name, inp.default or "")
            parts.append(f"- **{inp.name}:** {val}")

        parts.append("\n## Required Output Format")
        parts.append("Return a JSON object with these fields:")
        for out in self.outputs:
            parts.append(f"- `{out.name}` ({out.type}): {out.description}")

        return "\n".join(parts)
