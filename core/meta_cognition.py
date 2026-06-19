"""
BEA MAX — Meta-Cognition Layer
=====================================
Structured pre-action analysis for important missions or risky steps.

Before acting, generates:
  - Task interpretation
  - Assumptions made
  - Risks identified
  - Missing information
  - Confidence level
  - Recommended approach

Design:
  - Lightweight dataclass-based (no LLM call needed for basic analysis)
  - Can be enriched by LLM for complex cases
  - Fail-open: if analysis fails, action proceeds with default confidence
  - Integrates with decision_memory and memory_graph
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger()


class ConfidenceLevel(str, Enum):
    VERY_HIGH = "very_high"    # 90-100%: clear, well-understood task
    HIGH = "high"              # 70-89%: good understanding, minor unknowns
    MEDIUM = "medium"          # 50-69%: some uncertainty, assumptions needed
    LOW = "low"                # 30-49%: significant unknowns
    VERY_LOW = "very_low"      # 0-29%: mostly guessing


class RiskLevel(str, Enum):
    CRITICAL = "critical"    # Could break production
    HIGH = "high"            # Could cause significant issues
    MEDIUM = "medium"        # Manageable risk
    LOW = "low"              # Minimal risk
    NONE = "none"            # No risk


@dataclass
class PreActionAnalysis:
    """Structured reasoning before executing a mission step."""
    task_interpretation: str = ""
    assumptions: list[str] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)  # [{risk, level, mitigation}]
    missing_information: list[str] = field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    confidence_score: float = 0.5  # 0.0-1.0
    recommended_approach: str = ""
    should_proceed: bool = True
    requires_approval: bool = False
    reasoning: str = ""
    analyzed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_interpretation": self.task_interpretation,
            "assumptions": self.assumptions,
            "risks": self.risks,
            "missing_information": self.missing_information,
            "confidence": self.confidence.value,
            "confidence_score": round(self.confidence_score, 2),
            "recommended_approach": self.recommended_approach,
            "should_proceed": self.should_proceed,
            "requires_approval": self.requires_approval,
            "reasoning": self.reasoning,
        }


class MetaCognition:
    """
    Generates pre-action analysis for missions and steps.

    Rule-based first pass (fast, no LLM). Can be extended with LLM
    enrichment for complex cases.
    """

    # Keywords that increase risk assessment
    RISK_KEYWORDS = {
        "critical": ["delete", "drop", "destroy", "production", "deploy", "migrate"],
        "high": ["modify", "update", "overwrite", "send", "publish", "payment"],
        "medium": ["create", "install", "configure", "connect"],
    }

    # Keywords that lower confidence
    UNCERTAINTY_KEYWORDS = [
        "maybe", "possibly", "not sure", "unclear", "ambiguous",
        "try", "attempt", "experiment", "guess",
    ]

    def analyze(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        agent_id: str = "",
        tools_available: list[str] | None = None,
    ) -> PreActionAnalysis:
        """Generate a pre-action analysis for a task."""
        try:
            analysis = PreActionAnalysis()
            analysis.task_interpretation = self._interpret_task(task)
            analysis.assumptions = self._identify_assumptions(task, context)
            analysis.risks = self._assess_risks(task, context)
            analysis.missing_information = self._find_gaps(task, context, tools_available)
            analysis.confidence, analysis.confidence_score = self._calculate_confidence(
                task, context, analysis
            )
            analysis.recommended_approach = self._recommend_approach(analysis)
            analysis.should_proceed = analysis.confidence_score >= 0.3
            analysis.requires_approval = any(
                r.get("level") in ("critical", "high") for r in analysis.risks
            )
            analysis.reasoning = self._generate_reasoning(analysis)
            return analysis
        except Exception as e:
            log.warning("meta_cognition_failed", err=str(e))
            return PreActionAnalysis(
                task_interpretation=task,
                reasoning=f"Analysis failed: {e}",
            )

    def _interpret_task(self, task: str) -> str:
        task_lower = task.lower()
        if any(w in task_lower for w in ["fix", "bug", "error", "crash"]):
            return f"Bug fix / error resolution: {task[:100]}"
        if any(w in task_lower for w in ["create", "build", "implement", "add"]):
            return f"Feature creation: {task[:100]}"
        if any(w in task_lower for w in ["test", "verify", "validate", "check"]):
            return f"Validation / testing: {task[:100]}"
        if any(w in task_lower for w in ["deploy", "release", "publish"]):
            return f"Deployment / release: {task[:100]}"
        if any(w in task_lower for w in ["analyze", "investigate", "review"]):
            return f"Analysis / investigation: {task[:100]}"
        return f"General task: {task[:100]}"

    def _identify_assumptions(self, task: str, context: dict[str, Any] | None = None) -> list[str]:
        assumptions = []
        if not context or not context.get("files_read"):
            assumptions.append("Assuming current codebase state is up to date")
        if not context or not context.get("tests_passing"):
            assumptions.append("Assuming existing tests pass before changes")
        if "api" in task.lower():
            assumptions.append("Assuming backward compatibility required")
        if "database" in task.lower() or "migration" in task.lower():
            assumptions.append("Assuming data preservation required")
        return assumptions

    def _assess_risks(self, task: str, context: dict[str, Any] | None = None) -> list[dict[str, str]]:
        risks = []
        task_lower = task.lower()
        for level, keywords in self.RISK_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower:
                    risks.append({
                        "risk": f"Task involves '{kw}' operation",
                        "level": level,
                        "mitigation": self._suggest_mitigation(kw, level),
                    })
        if not risks:
            risks.append({"risk": "No significant risks identified", "level": "none", "mitigation": "Standard execution"})
        return risks

    def _suggest_mitigation(self, keyword: str, level: str) -> str:
        mitigations = {
            "delete": "Create backup before deletion",
            "drop": "Verify target before dropping",
            "production": "Test in staging first",
            "deploy": "Use canary deployment",
            "payment": "Require explicit approval",
            "send": "Preview before sending",
            "modify": "Create snapshot before modification",
        }
        return mitigations.get(keyword, f"Extra caution for {level}-risk operation")

    def _find_gaps(self, task: str, context: dict[str, Any] | None, tools: list[str] | None) -> list[str]:
        gaps = []
        if not context:
            gaps.append("No context provided — operating with task description only")
        elif not context.get("previous_attempts"):
            gaps.append("No history of previous attempts for this task")
        if tools is not None and len(tools) == 0:
            gaps.append("No tools available for this task")
        return gaps

    def _calculate_confidence(
        self, task: str, context: dict[str, Any] | None, analysis: PreActionAnalysis
    ) -> tuple[ConfidenceLevel, float]:
        score = 0.7  # Base confidence
        task_lower = task.lower()
        # Uncertainty keywords lower confidence
        for kw in self.UNCERTAINTY_KEYWORDS:
            if kw in task_lower:
                score -= 0.1
        # More risks lower confidence
        critical_risks = sum(1 for r in analysis.risks if r.get("level") == "critical")
        high_risks = sum(1 for r in analysis.risks if r.get("level") == "high")
        score -= critical_risks * 0.15 + high_risks * 0.1
        # Missing info lowers confidence
        score -= len(analysis.missing_information) * 0.05
        # Context increases confidence
        if context and context.get("files_read"):
            score += 0.1
        if context and context.get("tests_passing"):
            score += 0.1
        score = max(0.0, min(1.0, score))
        # Map to level
        if score >= 0.9:
            level = ConfidenceLevel.VERY_HIGH
        elif score >= 0.7:
            level = ConfidenceLevel.HIGH
        elif score >= 0.5:
            level = ConfidenceLevel.MEDIUM
        elif score >= 0.3:
            level = ConfidenceLevel.LOW
        else:
            level = ConfidenceLevel.VERY_LOW
        return level, score

    def _recommend_approach(self, analysis: PreActionAnalysis) -> str:
        if analysis.confidence_score >= 0.8:
            return "Proceed directly with standard execution"
        if analysis.confidence_score >= 0.5:
            return "Proceed with extra validation steps"
        if analysis.confidence_score >= 0.3:
            return "Proceed cautiously — request human review before critical steps"
        return "Recommend pausing for human guidance before proceeding"

    def _generate_reasoning(self, analysis: PreActionAnalysis) -> str:
        parts = [f"Task: {analysis.task_interpretation}"]
        if analysis.assumptions:
            parts.append(f"Assumptions: {', '.join(analysis.assumptions[:3])}")
        risk_summary = [f"{r['level']}: {r['risk']}" for r in analysis.risks[:3]]
        if risk_summary:
            parts.append(f"Risks: {'; '.join(risk_summary)}")
        parts.append(f"Confidence: {analysis.confidence.value} ({analysis.confidence_score:.0%})")
        parts.append(f"Recommendation: {analysis.recommended_approach}")
        return " | ".join(parts)
