"""
core/skills/domain_executor.py — Execute domain skills and chains.

Builds structured prompts from skill definitions, runs quality checks,
and supports refinement loops.
"""
from __future__ import annotations

import time
import structlog

from core.skills.domain_schema import DomainSkill, QualityCheck
from core.skills.domain_loader import get_domain_registry

log = structlog.get_logger("skills.domain_executor")


class SkillResult:
    """Result of executing a domain skill."""

    def __init__(
        self,
        skill_id: str,
        output: dict,
        quality_score: float = 1.0,
        quality_details: list[dict] | None = None,
        refined: bool = False,
        duration_ms: float = 0,
        error: str = "",
    ):
        self.skill_id = skill_id
        self.output = output
        self.quality_score = quality_score
        self.quality_details = quality_details or []
        self.refined = refined
        self.duration_ms = duration_ms
        self.error = error
        self.ok = not bool(error)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "ok": self.ok,
            "output": self.output,
            "quality_score": self.quality_score,
            "quality_details": self.quality_details,
            "refined": self.refined,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class DomainSkillExecutor:
    """
    Execute domain skills by building structured prompts and validating output.

    Does NOT call LLMs directly — returns the prompt context + validation.
    The calling agent is responsible for LLM invocation.
    """

    def prepare(self, skill_id: str, inputs: dict) -> dict:
        """
        Prepare a skill execution context.

        Returns:
            {
                "skill_id": str,
                "prompt_context": str,  # structured prompt for the agent
                "output_schema": list,  # expected output fields
                "quality_checks": list, # checks to run on output
            }
        """
        skill = get_domain_registry().get(skill_id)
        if not skill:
            return {"skill_id": skill_id, "error": f"Skill not found: {skill_id}"}

        # Validate required inputs
        missing = []
        for inp in skill.inputs:
            if inp.required and inp.name not in inputs:
                missing.append(inp.name)
        if missing:
            return {"skill_id": skill_id, "error": f"Missing inputs: {', '.join(missing)}"}

        return {
            "skill_id": skill_id,
            "skill_name": skill.name,
            "prompt_context": skill.build_prompt_context(inputs),
            "output_schema": [o.to_dict() if hasattr(o, 'to_dict') else
                            {"name": o.name, "type": o.type, "description": o.description}
                            for o in skill.outputs],
            "quality_checks": [{"name": q.name, "check_type": q.check_type,
                               "threshold": q.threshold} for q in skill.quality_checks],
        }

    def validate(self, skill_id: str, output: dict) -> SkillResult:
        """
        Validate skill output against quality checks.

        Returns SkillResult with quality_score and details.
        """
        t0 = time.time()
        skill = get_domain_registry().get(skill_id)
        if not skill:
            return SkillResult(skill_id=skill_id, output=output, error="Skill not found")

        checks = []
        total_score = 0.0
        check_count = 0

        for qc in skill.quality_checks:
            result = self._run_quality_check(qc, output, skill)
            checks.append(result)
            total_score += result["score"]
            check_count += 1

        avg_score = total_score / check_count if check_count else 1.0
        duration = round((time.time() - t0) * 1000)

        return SkillResult(
            skill_id=skill_id,
            output=output,
            quality_score=round(avg_score, 3),
            quality_details=checks,
            duration_ms=duration,
        )

    def execute_chain(
        self, skill_ids: list[str], initial_inputs: dict
    ) -> list[SkillResult]:
        """
        Prepare a chain of skills, passing outputs forward.

        Returns preparation contexts for each skill in the chain.
        The calling agent executes each and feeds output to the next.
        """
        chain = get_domain_registry().get_chain(skill_ids)
        if not chain:
            return []

        results = []
        current_inputs = dict(initial_inputs)

        for skill in chain:
            prep = self.prepare(skill.id, current_inputs)
            if "error" in prep:
                results.append(SkillResult(
                    skill_id=skill.id, output={}, error=prep["error"]
                ))
                break
            results.append(SkillResult(
                skill_id=skill.id,
                output={"prepared": True, "prompt_context": prep["prompt_context"][:200]},
            ))
            # Chain outputs: skill outputs become inputs for next skill
            # (actual LLM output would be merged here by the calling agent)

        return results

    def _run_quality_check(
        self, qc: QualityCheck, output: dict, skill: DomainSkill
    ) -> dict:
        """Run a single quality check against output."""
        if qc.check_type == "completeness":
            return self._check_completeness(qc, output, skill)
        elif qc.check_type == "structure":
            return self._check_structure(qc, output, skill)
        elif qc.check_type == "coherence":
            return self._check_coherence(qc, output)
        elif qc.check_type == "contradiction":
            return self._check_contradiction(qc, output)
        return {"name": qc.name, "check_type": qc.check_type, "score": 1.0, "passed": True}

    def _check_completeness(self, qc: QualityCheck, output: dict, skill: DomainSkill) -> dict:
        """Check that all expected output fields are present and non-empty."""
        expected = {o.name for o in skill.outputs}
        present = {k for k, v in output.items() if v}
        missing = expected - present
        score = len(present & expected) / len(expected) if expected else 1.0
        return {
            "name": qc.name,
            "check_type": "completeness",
            "score": round(score, 3),
            "passed": score >= qc.threshold,
            "missing": list(missing),
        }

    def _check_structure(self, qc: QualityCheck, output: dict, skill: DomainSkill) -> dict:
        """Check that output fields have correct types."""
        errors = []
        for o in skill.outputs:
            val = output.get(o.name)
            if val is None:
                continue
            if o.type == "list" and not isinstance(val, list):
                errors.append(f"{o.name} should be list")
            elif o.type == "json" and not isinstance(val, dict):
                errors.append(f"{o.name} should be dict")
            elif o.type == "number" and not isinstance(val, (int, float)):
                errors.append(f"{o.name} should be number")
        score = 1.0 - (len(errors) / max(len(skill.outputs), 1))
        return {
            "name": qc.name,
            "check_type": "structure",
            "score": round(max(0, score), 3),
            "passed": score >= qc.threshold,
            "errors": errors,
        }

    def _check_coherence(self, qc: QualityCheck, output: dict) -> dict:
        """Basic coherence: no empty strings in top-level values."""
        total = len(output)
        empty = sum(1 for v in output.values() if v == "" or v == [] or v == {})
        score = 1.0 - (empty / max(total, 1))
        return {
            "name": qc.name,
            "check_type": "coherence",
            "score": round(max(0, score), 3),
            "passed": score >= qc.threshold,
        }

    def _check_contradiction(self, qc: QualityCheck, output: dict) -> dict:
        """Placeholder for contradiction detection."""
        return {
            "name": qc.name,
            "check_type": "contradiction",
            "score": 1.0,
            "passed": True,
            "note": "basic_check_only",
        }


# Singleton
_executor: DomainSkillExecutor | None = None


def get_skill_executor() -> DomainSkillExecutor:
    global _executor
    if _executor is None:
        _executor = DomainSkillExecutor()
    return _executor
