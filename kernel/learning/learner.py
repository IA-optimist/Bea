"""
kernel/learning/learner.py — Kernel Learning Engine
=====================================================
The kernel decides when to learn, what to learn, and where to store it.

KERNEL RULE: This module does NOT import from core/, agents/, api/, tools/.
Core lesson storage (core/orchestration/learning_loop.store_lesson) registers
itself here via register_lesson_store(). If no store is registered, the kernel
logs the lesson (fail-open — never blocks mission completion).

Why this exists (Pass 10):
  Previously, core/meta_orchestrator.py called core.orchestration.learning_loop
  directly, re-deriving lesson content from raw metadata (verdict string, float
  confidence). The kernel already owned this data via KernelScore (Pass 8) but
  had no control over the learning decision.

  KernelLearner closes the cognitive loop:
    kernel.evaluate() → KernelScore → kernel.learn(score) → KernelLesson stored

Registration (at app startup — in main.py):
  kernel.learning.learner.register_lesson_store(
      core.orchestration.learning_loop.store_lesson
  )
"""
from __future__ import annotations

import structlog
from typing import Callable, Optional

from kernel.learning.lesson import KernelLesson

log = structlog.get_logger("kernel.learning")

# ── Registration slot ─────────────────────────────────────────────────────────
_lesson_store_fn: Optional[Callable[..., bool]] = None


def register_lesson_store(fn: Callable[..., bool]) -> None:
    """
    Register a lesson store function (e.g. core.orchestration.learning_loop.store_lesson).
    Called at app startup. kernel/learning never imports core directly.
    """
    global _lesson_store_fn
    _lesson_store_fn = fn
    log.debug("kernel_lesson_store_registered")


# ── Learning threshold (kernel-owned) ─────────────────────────────────────────
# Mirrors the condition in core/orchestration/learning_loop.extract_lesson():
#   learn when NOT (verdict == "accept" AND confidence >= 0.8)
_LEARN_CONFIDENCE_THRESHOLD = 0.8


class KernelLearner:
    """
    Extracts and stores lessons from completed missions.

    Priority:
      1. KernelScore fields (from kernel.evaluator — Pass 8): verdict, confidence,
         weaknesses, improvement_suggestion
      2. Fallback heuristic based on verdict alone (when score unavailable)

    Storage:
      - Calls registered store_fn (core lesson store, uses memory_facade)
      - Falls back to kernel-native log.info if store_fn unavailable
    """

    def should_learn(self, verdict: str, confidence: float) -> bool:
        """
        Kernel-owned decision: is this mission worth storing as a lesson?
        Learn when the result was imperfect (not a clean accept at high confidence).
        """
        return not (verdict == "accept" and confidence >= _LEARN_CONFIDENCE_THRESHOLD)

    def extract(
        self,
        goal: str,
        result: str,
        mission_id: str,
        verdict: str = "accept",
        confidence: float = 0.7,
        weaknesses: list[str] | None = None,
        improvement_suggestion: str = "",
        retries: int = 0,
        error_class: str = "",
    ) -> KernelLesson | None:
        """
        Extract a lesson from mission outcome data.
        Returns None if nothing to learn (clean success).
        """
        if not self.should_learn(verdict, confidence):
            return None

        weaknesses = weaknesses or []

        # what_happened: derived from kernel signals (not re-derived in core)
        if verdict == "empty":
            what_happened = "Mission produced no output"
        elif verdict == "retry_suggested":
            what_happened = f"Result was weak (confidence={confidence:.2f})"
        elif error_class and error_class not in ("none", ""):
            what_happened = f"Error class: {error_class}"
        elif retries > 0:
            what_happened = f"Required {retries} retries to complete"
        else:
            what_happened = f"Low confidence result (confidence={confidence:.2f})"

        if weaknesses:
            what_happened += f"; weaknesses: {'; '.join(weaknesses[:2])}"

        # what_to_do_differently: kernel uses improvement_suggestion when available
        if improvement_suggestion:
            what_to_do = improvement_suggestion
        elif verdict == "empty":
            what_to_do = "Verify tool availability and input format before execution"
        elif verdict == "retry_suggested":
            what_to_do = "Try alternative approach or decompose into smaller steps"
        elif error_class == "timeout":
            what_to_do = "Increase timeout or break task into smaller chunks"
        elif error_class == "tool_not_available":
            what_to_do = "Check tool availability before planning execution"
        elif retries > 0:
            what_to_do = "Investigate root cause of transient failures"
        else:
            what_to_do = "Consider more specific goal formulation"

        goal_summary = goal[:100] + ("..." if len(goal) > 100 else "")

        return KernelLesson(
            mission_id=mission_id,
            goal_summary=goal_summary,
            what_happened=what_happened,
            what_to_do_differently=what_to_do,
            confidence=confidence,
            verdict=verdict,
            weaknesses=list(weaknesses),
            improvement_suggestion=improvement_suggestion,
        )

    def store(self, lesson: KernelLesson) -> bool:
        """
        Store a lesson. Calls registered core store first; logs if unavailable.
        Returns True if stored via core, False if logged only.
        """
        if _lesson_store_fn is not None:
            try:
                # core.orchestration.learning_loop.store_lesson expects a Lesson
                # object with .to_dict() or .goal_summary etc. We pass a compat
                # object (KernelLesson has all required attributes).
                result = _lesson_store_fn(lesson)
                log.debug("kernel_lesson_stored",
                          mission_id=lesson.mission_id,
                          verdict=lesson.verdict,
                          confidence=lesson.confidence,
                          source="core_store")
                return bool(result)
            except Exception as e:
                log.warning("kernel_lesson_store_failed", err=str(e)[:80])

        # Kernel-native fallback: log the lesson (always available)
        log.info("kernel_lesson_learned",
                 mission_id=lesson.mission_id,
                 verdict=lesson.verdict,
                 confidence=lesson.confidence,
                 what_to_do=lesson.what_to_do_differently[:80],
                 weaknesses=lesson.weaknesses[:2],
                 source="kernel_log")
        return False

    def learn(
        self,
        goal: str,
        result: str,
        mission_id: str,
        verdict: str = "accept",
        confidence: float = 0.7,
        weaknesses: list[str] | None = None,
        improvement_suggestion: str = "",
        retries: int = 0,
        error_class: str = "",
    ) -> KernelLesson | None:
        """
        Full learning cycle: extract + store. Returns lesson if one was created.
        Never raises — fail-open so mission completion is never blocked.
        """
        try:
            lesson = self.extract(
                goal=goal, result=result, mission_id=mission_id,
                verdict=verdict, confidence=confidence,
                weaknesses=weaknesses or [], improvement_suggestion=improvement_suggestion,
                retries=retries, error_class=error_class,
            )
            if lesson is None:
                return None
            self.store(lesson)
            return lesson
        except Exception as e:
            log.warning("kernel_learn_failed", err=str(e)[:80])
            return None


# ── Module-level singleton ────────────────────────────────────────────────────
_learner: KernelLearner | None = None


def get_learner() -> KernelLearner:
    """Return the singleton KernelLearner."""
    global _learner
    if _learner is None:
        _learner = KernelLearner()
    return _learner
