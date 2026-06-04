"""
kernel/evaluation/scorer.py — Kernel Evaluator (Cognitive Convergence Point)
=============================================================================
Phase 8: kernel.evaluator becomes the SINGLE evaluation authority for
mission outcomes. MetaOrchestrator calls kernel.evaluate() — not
core.orchestration.reflection nor core.orchestration.reasoning_engine.

DESIGN PRINCIPLES
-----------------
1. Single authority: one call, one KernelScore, all downstream reads it.
2. Core as enrichment: reflect() and critique_output() run via registration,
   enrich the score — they are not the source of truth.
3. Backward compat: KernelScore.critique_dict and .reflection_dict are
   populated so existing code that reads ctx.metadata["critique"] still works.
4. Future extensibility: KernelScore is structured to support
   skill scoring, tool scoring, agent scoring, and improvement signals
   without further interface changes.

EXTENSION POINTS (designed now, implemented later)
-------------------------------------------------
  register_skill_evaluator(fn)  — evaluate tool/skill quality
  register_agent_evaluator(fn)  — evaluate agent selection quality
  register_improvement_scorer(fn) — evaluate improvement cycle outcomes
  These slots are reserved in the registry below.

KERNEL RULE: Zero imports from core/, agents/, api/, tools/.
Registration at boot:
  from kernel.evaluation.scorer import register_core_reflection, register_core_critique
  from core.orchestration.reflection import reflect
  from core.orchestration.reasoning_engine import critique_output
  register_core_reflection(reflect)
  register_core_critique(critique_output)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import structlog
    _log = structlog.get_logger("kernel.evaluation")
except ImportError:
    _log = structlog.get_logger("kernel.evaluation")


# ── KernelScore — unified evaluation result ───────────────────────────────────

@dataclass
class KernelScore:
    """
    The kernel's complete evaluation of a mission outcome.

    Downstream consumers:
      result_confidence  ← .confidence
      retry decision     ← .retry_recommended + .score vs threshold
      retry goal         ← .weaknesses + .improvement_suggestion
      learning loop      ← .verdict + .confidence + .failure_class
      improvement signals← .improvement_signals
      skill recording    ← .score + .confidence
      ctx.metadata       ← .to_dict(), .critique_dict, .reflection_dict
    """
    # ── Primary quality signal ────────────────────────────────────────────────
    score:       float         # 0.0–1.0 composite quality score
    passed:      bool          # score >= threshold AND not retry_recommended

    # ── Confidence (calibrated, used as result_confidence downstream) ─────────
    confidence:  float = 0.7   # 0.0–1.0

    # ── Retry authority ───────────────────────────────────────────────────────
    retry_recommended:    bool  = False
    retry_threshold_used: float = 0.25

    # ── Weakness signals (feed retry goal + learning + improvement) ───────────
    weaknesses:             list[str] = field(default_factory=list)
    improvement_signals:    list[str] = field(default_factory=list)
    improvement_suggestion: str       = ""

    # ── Verdict (maps to reflection.verdict for learning_loop compat) ─────────
    verdict: str = "accept"    # "accept" | "low_confidence" | "retry_suggested" | "empty"

    # ── Diagnostics ───────────────────────────────────────────────────────────
    failure_class: str        = ""
    signals:       list[str]  = field(default_factory=list)
    source:        str        = "kernel_heuristic"

    # ── Backward-compat dicts for ctx.metadata["critique"] / ["reflection"] ───
    # Populated when core reflection/critique ran as enrichment.
    critique_dict:   dict = field(default_factory=dict)
    reflection_dict: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score":                  round(self.score, 3),
            "passed":                 self.passed,
            "confidence":             round(self.confidence, 3),
            "retry_recommended":      self.retry_recommended,
            "retry_threshold_used":   round(self.retry_threshold_used, 3),
            "weaknesses":             self.weaknesses,
            "improvement_signals":    self.improvement_signals,
            "improvement_suggestion": self.improvement_suggestion,
            "verdict":                self.verdict,
            "failure_class":          self.failure_class,
            "signals":                self.signals,
            "source":                 self.source,
        }


# ── Registration slots ────────────────────────────────────────────────────────

_core_reflect_fn:       Optional[Callable[..., Any]] = None
_core_critique_fn:      Optional[Callable[..., Any]] = None
# Extension points — reserved
_skill_evaluator_fn:    Optional[Callable[..., Any]] = None
_agent_evaluator_fn:    Optional[Callable[..., Any]] = None
_improvement_scorer_fn: Optional[Callable[..., Any]] = None


def register_core_reflection(fn: Callable[..., Any]) -> None:
    """Register core.orchestration.reflection.reflect — called at boot."""
    global _core_reflect_fn
    _core_reflect_fn = fn
    _log.debug("kernel_evaluator_reflection_registered")


def register_core_critique(fn: Callable[..., Any]) -> None:
    """Register core.orchestration.reasoning_engine.critique_output — called at boot."""
    global _core_critique_fn
    _core_critique_fn = fn
    _log.debug("kernel_evaluator_critique_registered")


def register_core_evaluator(fn: Callable[..., Any]) -> None:
    """
    Legacy single-function registration (backward compat with main.py boot).
    Stored as critique evaluator.
    """
    global _core_critique_fn
    _core_critique_fn = fn
    _log.debug("kernel_evaluator_legacy_registered")


def register_skill_evaluator(fn: Callable[..., Any]) -> None:
    global _skill_evaluator_fn; _skill_evaluator_fn = fn

def register_agent_evaluator(fn: Callable[..., Any]) -> None:
    global _agent_evaluator_fn; _agent_evaluator_fn = fn

def register_improvement_scorer(fn: Callable[..., Any]) -> None:
    global _improvement_scorer_fn; _improvement_scorer_fn = fn


# ── Shape-aware retry thresholds (kernel-authoritative) ──────────────────────
_RETRY_THRESHOLDS: dict[str, float] = {
    "direct_answer": 0.20,
    "patch":         0.30,
    "diagnosis":     0.30,
    "plan":          0.30,
    "report":        0.35,
    "warning":       0.20,
}
_DEFAULT_RETRY_THRESHOLD = 0.25
PASS_THRESHOLD = 0.50


# ── Kernel heuristic scorer ───────────────────────────────────────────────────

def _heuristic_score(goal: str, result: str, task_type: str = "") -> KernelScore:
    """
    Deterministic heuristic scorer. Used when core evaluators are unavailable.
    Always produces a valid KernelScore. Zero external dependencies.
    """
    if not result or not result.strip():
        return KernelScore(
            score=0.0, passed=False, confidence=0.0,
            retry_recommended=True, retry_threshold_used=_DEFAULT_RETRY_THRESHOLD,
            weaknesses=["Empty result"],
            improvement_signals=["Produce any output"],
            improvement_suggestion="Produce any output",
            verdict="empty", failure_class="empty_result",
            signals=["empty"], source="kernel_heuristic",
        )

    signals: list[str] = []
    score = 0.5

    error_kws = ("error:", "exception:", "traceback", "failed:", "cannot", "unable to")
    error_count = sum(1 for kw in error_kws if kw in result.lower())
    if error_count:
        score -= error_count * 0.12
        signals.append(f"error_markers:{error_count}")

    length = len(result.strip())
    if length < 50:
        score -= 0.2; signals.append("very_short")
    elif length < 200:
        score -= 0.05; signals.append("short")
    elif length > 500:
        score += 0.1; signals.append("substantial")

    goal_words  = set(w.lower() for w in goal.split() if len(w) > 4)
    result_words = set(w.lower() for w in result.split() if len(w) > 4)
    overlap = len(goal_words & result_words) / max(len(goal_words), 1)
    if overlap < 0.1:
        score -= 0.15; signals.append("no_goal_overlap")
    elif overlap > 0.3:
        score += 0.1; signals.append("goal_overlap")

    if task_type in ("implementation", "debugging", "deployment"):
        has_code = any(kw in result for kw in ("def ", "class ", "import ", "```"))
        if has_code:
            score += 0.1; signals.append("code_present")
        else:
            score -= 0.1; signals.append("no_code_for_impl_task")

    score     = round(max(0.0, min(1.0, score)), 3)
    threshold = _RETRY_THRESHOLDS.get(task_type, _DEFAULT_RETRY_THRESHOLD)
    is_weak   = score < threshold
    weaknesses = [s for s in signals if any(
        kw in s for kw in ("short", "no_goal", "no_code", "error")
    )]
    verdict = "accept" if score >= 0.6 else (
        "retry_suggested" if score < 0.3 else "low_confidence"
    )

    return KernelScore(
        score=score, passed=score >= PASS_THRESHOLD and not is_weak,
        confidence=round(min(1.0, score + 0.1), 3),
        retry_recommended=is_weak, retry_threshold_used=threshold,
        weaknesses=weaknesses, improvement_signals=weaknesses,
        improvement_suggestion="Provide more specific and complete output" if is_weak else "",
        verdict=verdict, failure_class="low_quality" if is_weak else "",
        signals=signals, source="kernel_heuristic",
    )


# ── KernelEvaluator ───────────────────────────────────────────────────────────

class KernelEvaluator:
    """
    The kernel's single evaluation authority for mission outcomes.

    Evaluation order:
      1. Run registered reflect()         → reflection_dict
      2. Run registered critique_output() → critique_dict
      3. Heuristic fills gaps
      4. Synthesize → KernelScore

    All downstream decisions (retry, confidence, learning, signals) are
    driven from this single score. Fail-open on all core calls.
    """
    PASS_THRESHOLD: float = PASS_THRESHOLD

    def evaluate(
        self,
        goal:            str,
        result:          str,
        task_type:       str = "",
        mission_id:      str = "",
        duration_ms:     int = 0,
        retries:         int = 0,
        output_shape:    str = "",
        reasoning_frame: Any = None,
    ) -> KernelScore:
        """Evaluate a mission result. Never raises."""
        reflection_dict: dict = {}
        critique_dict:   dict = {}

        # 1 — Core reflection (fail-open)
        if _core_reflect_fn is not None:
            try:
                refl = _core_reflect_fn(
                    goal=goal, result=result,
                    duration_ms=duration_ms, retries=retries,
                )
                reflection_dict = (
                    refl.to_dict() if hasattr(refl, "to_dict") else dict(refl)
                )
            except Exception as _re:
                _log.debug("kernel_evaluator_reflection_failed", err=str(_re)[:80])

        # 2 — Core critique (fail-open)
        if _core_critique_fn is not None:
            try:
                crit = _core_critique_fn(
                    goal=goal, output=result,
                    output_shape=output_shape or None,
                    frame=reasoning_frame,
                )
                if hasattr(crit, "to_dict"):
                    critique_dict = crit.to_dict()
                elif isinstance(crit, dict):
                    critique_dict = crit
            except Exception as _ce:
                _log.debug("kernel_evaluator_critique_failed", err=str(_ce)[:80])

        # 3 — Heuristic baseline
        heuristic = _heuristic_score(goal, result, task_type)

        # 4 — Synthesize
        return self._synthesize(
            heuristic, reflection_dict, critique_dict, output_shape, mission_id,
        )

    def _synthesize(
        self,
        heuristic:       KernelScore,
        reflection_dict: dict,
        critique_dict:   dict,
        output_shape:    str,
        mission_id:      str,
    ) -> KernelScore:
        """
        Merge heuristic + reflection + critique into one authoritative KernelScore.

        Priority:
          confidence ← reflection > critique.overall > heuristic
          score      ← critique.overall > reflection.confidence > heuristic
          weaknesses ← critique (richest signals) > heuristic
          verdict    ← reflection (canonical vocabulary) > heuristic
        """
        # Confidence
        confidence = heuristic.confidence
        if reflection_dict.get("confidence") is not None:
            confidence = float(reflection_dict["confidence"])

        # Score
        score = heuristic.score
        if critique_dict.get("overall") is not None:
            score = float(critique_dict["overall"])
        elif reflection_dict.get("confidence") is not None:
            score = float(reflection_dict["confidence"])
        if critique_dict.get("is_weak"):
            confidence = min(confidence, score + 0.05)

        score      = round(max(0.0, min(1.0, score)), 3)
        confidence = round(max(0.0, min(1.0, confidence)), 3)

        # Weaknesses + improvement signals
        weaknesses = (
            critique_dict.get("weaknesses", []) or heuristic.weaknesses
        )
        improvement_suggestion = (
            critique_dict.get("improvement_suggestion", "") or
            heuristic.improvement_suggestion
        )
        improvement_signals = list(weaknesses)
        if improvement_suggestion:
            improvement_signals.append(improvement_suggestion)

        # Retry decision
        threshold = _RETRY_THRESHOLDS.get(output_shape, _DEFAULT_RETRY_THRESHOLD)
        is_weak   = bool(critique_dict.get("is_weak", score < threshold))
        retry_recommended = is_weak and score < threshold

        # Verdict (for learning_loop compat)
        verdict = reflection_dict.get("verdict") or heuristic.verdict

        # Passed
        passed = score >= self.PASS_THRESHOLD and not retry_recommended

        # Source
        if critique_dict and reflection_dict:
            source = "core_full"
        elif critique_dict:
            source = "core_critique"
        elif reflection_dict:
            source = "core_reflection"
        else:
            source = "kernel_heuristic"

        _log.debug(
            "kernel_evaluator_synthesized",
            mission_id=mission_id,
            score=score, confidence=confidence,
            retry=retry_recommended, source=source,
        )

        return KernelScore(
            score=score, passed=passed, confidence=confidence,
            retry_recommended=retry_recommended, retry_threshold_used=threshold,
            weaknesses=weaknesses[:6], improvement_signals=improvement_signals[:6],
            improvement_suggestion=improvement_suggestion,
            verdict=verdict,
            failure_class=heuristic.failure_class if not passed else "",
            signals=heuristic.signals, source=source,
            critique_dict=critique_dict, reflection_dict=reflection_dict,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
_evaluator: KernelEvaluator | None = None


def get_evaluator() -> KernelEvaluator:
    """Return singleton KernelEvaluator."""
    global _evaluator
    if _evaluator is None:
        _evaluator = KernelEvaluator()
    return _evaluator
