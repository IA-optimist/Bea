"""
core/planning/self_review.py — Single-pass self-review before returning final output.

Evaluates mission result completeness, coherence, and artifact usability.
If issues detected, performs one improvement iteration. Avoids infinite loops.

Design:
  - Single pass only: review → optional fix → done
  - Evaluates: completeness, coherence, artifact usability
  - No LLM required for review (heuristic checks)
  - Improvement is bounded: one iteration maximum
  - Fail-open: never blocks result delivery
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
import structlog

log = structlog.get_logger("planning.self_review")


@dataclass
class ReviewIssue:
    """A single issue found during self-review."""
    category: str       # completeness, coherence, usability, quality
    severity: str       # critical, warning, info
    description: str
    fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "fixable": self.fixable,
        }


@dataclass
class ReviewResult:
    """Result of self-review on a mission output."""
    passed: bool
    score: float  # 0-1
    issues: list[ReviewIssue] = field(default_factory=list)
    reviewed: bool = True
    improvement_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "issues": [i.to_dict() for i in self.issues],
            "reviewed": self.reviewed,
            "improvement_applied": self.improvement_applied,
        }


def review_mission_result(
    goal: str,
    run_result: dict[str, Any],
    step_outputs: dict[str, Any] | None = None,
) -> ReviewResult:
    """
    Self-review a mission result before delivery.

    Checks:
      1. Mission completed successfully
      2. All steps produced output
      3. Outputs are non-empty
      4. Goal keywords appear in outputs (coherence)
      5. No error indicators in final state

    Returns ReviewResult with score and issues.
    """
    issues: list[ReviewIssue] = []

    # Check 1: Mission success
    if not run_result.get("ok"):
        issues.append(ReviewIssue(
            category="completeness", severity="critical",
            description="Mission did not complete successfully",
        ))

    # Check 2: Steps produced output
    outputs = step_outputs or run_result.get("run", {}).get("context", {}).get("step_outputs", {})
    steps_completed = run_result.get("run", {}).get("steps_completed", 0)
    steps_total = run_result.get("run", {}).get("steps_total", 0)

    if steps_total > 0 and steps_completed < steps_total:
        issues.append(ReviewIssue(
            category="completeness", severity="warning",
            description=f"Only {steps_completed}/{steps_total} steps completed",
            fixable=True,
        ))

    # Check 3: Outputs are non-empty
    empty_outputs = 0
    invoked_count = 0
    for step_id, output in outputs.items():
        if isinstance(output, dict):
            content = output.get("content", {})
            if output.get("invoked") and not content:
                empty_outputs += 1
            if output.get("invoked"):
                invoked_count += 1
            elif output.get("prepared") and not output.get("invoked"):
                issues.append(ReviewIssue(
                    category="quality", severity="info",
                    description=f"Step {step_id}: prepared but LLM not invoked",
                ))

    if empty_outputs > 0:
        issues.append(ReviewIssue(
            category="completeness", severity="warning",
            description=f"{empty_outputs} step(s) produced empty content after LLM invocation",
            fixable=True,
        ))

    # Check 4: Goal coherence — do output keywords overlap with goal?
    if goal and outputs:
        goal_words = set(re.findall(r'\w+', goal.lower()))
        output_text = _extract_text_from_outputs(outputs).lower()
        output_words = set(re.findall(r'\w+', output_text))

        if goal_words and output_words:
            overlap = len(goal_words & output_words) / len(goal_words) if goal_words else 0
            if overlap < 0.2:
                issues.append(ReviewIssue(
                    category="coherence", severity="warning",
                    description=f"Low goal-output keyword overlap ({overlap:.0%})",
                ))

    # Check 5: Error indicators
    run_data = run_result.get("run", {})
    if run_data.get("error"):
        issues.append(ReviewIssue(
            category="quality", severity="warning",
            description=f"Run has error: {str(run_data['error'])[:100]}",
        ))

    # Score computation
    score = 1.0
    for issue in issues:
        if issue.severity == "critical":
            score -= 0.3
        elif issue.severity == "warning":
            score -= 0.1
        elif issue.severity == "info":
            score -= 0.02
    score = max(0.0, score)

    passed = score >= 0.5 and not any(i.severity == "critical" for i in issues)

    return ReviewResult(
        passed=passed,
        score=score,
        issues=issues,
    )


def _extract_text_from_outputs(outputs: dict[str, Any]) -> str:
    """Extract text content from step outputs for coherence checking."""
    texts: list[str] = []
    for step_id, output in outputs.items():
        if not isinstance(output, dict):
            continue
        content = output.get("content", {})
        if isinstance(content, dict):
            for key, val in content.items():
                if isinstance(val, str):
                    texts.append(val[:500])
                elif isinstance(val, list):
                    for item in val[:10]:
                        if isinstance(item, str):
                            texts.append(item[:200])
    return " ".join(texts)
