"""
core/orchestration/pre_execution.py — Pre-execution intelligence.

Three checks BEFORE execution begins:
1. Confidence estimation (do we expect success?)
2. Tool health check (are suggested tools working?)
3. Failure pattern matching (have we failed at this before?)

Inspired by production agent patterns:
- Pre-flight checks prevent wasted execution
- Failure memory prevents repeated mistakes
- Tool health prevents using broken tools
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("orchestration.pre_execution")


@dataclass
class PreExecutionAssessment:
    """Result of pre-execution checks."""
    estimated_confidence: float = 0.5
    tool_health_ok: bool = True
    unhealthy_tools: list[str] = field(default_factory=list)
    similar_failures: list[str] = field(default_factory=list)
    strategy_suggestion: str = ""  # "", "cautious", "alternative", "decompose"
    proceed: bool = True

    def to_dict(self) -> dict:
        return {
            "estimated_confidence": self.estimated_confidence,
            "tool_health_ok": self.tool_health_ok,
            "unhealthy_tools": self.unhealthy_tools,
            "similar_failures_count": len(self.similar_failures),
            "strategy_suggestion": self.strategy_suggestion,
            "proceed": self.proceed,
        }


def assess_before_execution(
    goal: str,
    classification: dict,
    prior_skills: list[dict],
    relevant_memories: list[dict],
) -> PreExecutionAssessment:
    """
    Run pre-execution checks. Pure heuristics, no LLM call.
    """
    assessment = PreExecutionAssessment()

    # ── 1. Confidence estimation ──────────────────────
    confidence = 0.5

    # Skill match quality boost
    if prior_skills:
        best_conf = max(s.get("confidence", 0.5) for s in prior_skills)
        confidence += best_conf * 0.2

    # Complexity penalty
    complexity = classification.get("complexity", "simple")
    complexity_penalty = {"trivial": 0.1, "simple": 0.0, "moderate": -0.1, "complex": -0.2}
    confidence += complexity_penalty.get(complexity, 0.0)

    # Memory relevance boost
    if relevant_memories:
        confidence += 0.05

    assessment.estimated_confidence = round(max(0.1, min(1.0, confidence)), 3)

    # ── 2. Tool health check ─────────────────────────
    try:
        from executor.capability_health import CapabilityHealthTracker
        tracker = CapabilityHealthTracker()
        suggested_tools = classification.get("suggested_tools", [])
        for tool in suggested_tools:
            if not tracker.is_healthy(tool):
                assessment.unhealthy_tools.append(tool)
        if assessment.unhealthy_tools:
            assessment.tool_health_ok = False
            assessment.estimated_confidence -= 0.15
    except Exception:
        _silent_log.debug("suppressed_exception", src='pre_execution.py')

    # ── 3. Failure pattern matching ──────────────────
    try:
        from core.memory_facade import get_memory_facade
        facade = get_memory_facade()
        failures = facade.search(goal, content_type="failure", top_k=3)
        for f in failures:
            if hasattr(f, "score") and f.score > 0.4:
                assessment.similar_failures.append(
                    getattr(f, "content", str(f))[:100]
                )
    except Exception:
        _silent_log.debug("suppressed_exception", src='pre_execution.py')

    if assessment.similar_failures:
        assessment.estimated_confidence -= 0.1 * min(3, len(assessment.similar_failures))

    # ── Strategy suggestion ──────────────────────────
    assessment.estimated_confidence = round(
        max(0.1, assessment.estimated_confidence), 3
    )

    if assessment.estimated_confidence < 0.3:
        assessment.strategy_suggestion = "decompose"
    elif assessment.estimated_confidence < 0.5:
        assessment.strategy_suggestion = "cautious"
    elif not assessment.tool_health_ok:
        assessment.strategy_suggestion = "alternative"
    else:
        assessment.strategy_suggestion = ""

    assessment.proceed = assessment.estimated_confidence >= 0.15

    # Suggest early approval for low-confidence + medium+ risk
    risk = classification.get("risk_level", "low")
    if assessment.estimated_confidence < 0.4 and risk in ("medium", "high", "critical"):
        assessment.strategy_suggestion = "request_approval"

    log.info("pre_execution_assessment",
             confidence=assessment.estimated_confidence,
             tools_ok=assessment.tool_health_ok,
             failures=len(assessment.similar_failures),
             strategy=assessment.strategy_suggestion)

    return assessment
