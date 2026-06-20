"""
core/orchestration/reflection.py — Post-execution reflection.

Inspired by LangGraph's observe→reflect→replan cycle.
Evaluates result quality before marking a mission DONE.
Decides: accept, retry with feedback, or mark as low-confidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger("orchestration.reflection")


class ReflectionVerdict(str, Enum):
    ACCEPT = "accept"               # result is good
    LOW_CONFIDENCE = "low_confidence"  # result exists but quality is uncertain
    RETRY_SUGGESTED = "retry_suggested"  # result is weak, retry recommended
    EMPTY = "empty"                  # no result at all


@dataclass
class ReflectionResult:
    verdict: ReflectionVerdict
    confidence: float      # 0.0-1.0
    reasoning: str
    quality_signals: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "quality_signals": self.quality_signals,
        }


def reflect(
    goal: str,
    result: str,
    duration_ms: int = 0,
    retries: int = 0,
) -> ReflectionResult:
    """
    Evaluate execution result quality. Pure heuristics — no LLM call.

    Checks:
    - Result is non-empty
    - Result length is proportional to goal complexity
    - Result doesn't look like an error message
    - Result has some relevance to the goal
    """
    signals: dict[str, Any] = {}

    # 1. Empty check
    if not result or not result.strip():
        return ReflectionResult(
            verdict=ReflectionVerdict.EMPTY,
            confidence=0.0,
            reasoning="No result produced",
            quality_signals={"empty": True},
        )

    result_len = len(result.strip())
    goal_len = len(goal.strip())

    # 2. Length proportionality
    signals["result_length"] = result_len
    signals["goal_length"] = goal_len

    # Very short result for a long goal → suspicious
    length_ratio = result_len / max(goal_len, 1)
    signals["length_ratio"] = round(length_ratio, 2)

    # 3. Error indicators
    error_patterns = [
        r"error:", r"traceback", r"exception", r"failed to",
        r"could not", r"unable to", r"internal server error",
    ]
    error_count = sum(1 for p in error_patterns if re.search(p, result.lower()))
    signals["error_indicators"] = error_count

    # 4. Goal-result word overlap (relevance signal)
    goal_words = set(re.findall(r"[a-z]+", goal.lower()))
    result_words = set(re.findall(r"[a-z]+", result.lower()))
    if goal_words:
        overlap = len(goal_words & result_words) / len(goal_words)
    else:
        overlap = 0.0
    signals["word_overlap"] = round(overlap, 2)

    # 5. Duration/retry penalty
    signals["retries"] = retries
    signals["duration_ms"] = duration_ms

    # ── Score ──────────────────────────────────────
    confidence = 0.5

    # Length bonus
    if result_len > 200:
        confidence += 0.1
    if result_len > 500:
        confidence += 0.1

    # Error penalty
    confidence -= error_count * 0.15

    # Relevance bonus
    confidence += overlap * 0.2

    # Retry penalty
    confidence -= retries * 0.1

    # Very short → penalty
    if result_len < 20:
        confidence -= 0.3

    confidence = max(0.0, min(1.0, round(confidence, 3)))

    # ── Verdict ───────────────────────────────────
    if confidence >= 0.6:
        verdict = ReflectionVerdict.ACCEPT
        reasoning = f"Result accepted (confidence={confidence})"
    elif confidence >= 0.3:
        verdict = ReflectionVerdict.LOW_CONFIDENCE
        reasoning = f"Result exists but quality uncertain (confidence={confidence})"
    else:
        verdict = ReflectionVerdict.RETRY_SUGGESTED
        reasoning = f"Result is weak, retry recommended (confidence={confidence})"

    log.debug("reflection",
              verdict=verdict.value, confidence=confidence,
              result_len=result_len, overlap=overlap)

    return ReflectionResult(
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        quality_signals=signals,
    )
