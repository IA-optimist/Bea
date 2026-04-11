"""
core/self_improvement/improvement_loop.py — Controlled Self-Improvement Loop.

Orchestrates the full cycle:
  detect → propose → benchmark → compare → critique → adopt/reject → learn

All experiments run in isolated mode. No direct production modification.
"""
from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

log = logging.getLogger("jarvis.improvement.loop")


# ── Experiment Result ─────────────────────────────────────────────────────────

@dataclass
class ExperimentResult:
    """Result of a single improvement experiment."""
    experiment_id: str
    candidate_id: str
    hypothesis: str
    touched_modules: list[str] = field(default_factory=list)
    risk_level: str = "LOW"
    baseline_pass_rate: float = 0.0
    candidate_pass_rate: float = 0.0
    baseline_cost: float = 0.0
    candidate_cost: float = 0.0
    baseline_latency: float = 0.0
    candidate_latency: float = 0.0
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    schema_intact: bool = True
    trace_intact: bool = True
    safety_intact: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# ── Critic Review ─────────────────────────────────────────────────────────────

@dataclass
class CriticReview:
    """Independent review of an improvement candidate."""
    candidate_id: str
    verdict: Literal["ACCEPT", "REJECT", "INCONCLUSIVE"] = "INCONCLUSIVE"
    security_regression: bool = False
    policy_bypass_risk: bool = False
    executor_safety_regression: bool = False
    trace_integrity_regression: bool = False
    hidden_cost_inflation: bool = False
    benchmark_gaming: bool = False
    concerns: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return asdict(self)


# ── Adoption Decision ─────────────────────────────────────────────────────────

@dataclass
class AdoptionDecision:
    """Final adoption decision for an improvement candidate."""
    candidate_id: str
    outcome: Literal["REJECT", "APPROVE_FOR_REVIEW", "AUTO_ADOPT", "ARCHIVE"] = "REJECT"
    reason: str = ""
    requires_human_review: bool = True
    auto_adopt_eligible: bool = False
    review_report: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Improvement Entry (for memory) ───────────────────────────────────────────

@dataclass
class ImprovementEntry:
    """Persistent record of an improvement attempt."""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: float = field(default_factory=time.time)
    problem_detected: str = ""
    hypothesis: str = ""
    candidate_change: str = ""
    files_touched: list[str] = field(default_factory=list)
    benchmark_pass_rate: float = 0.0
    outcome: str = "PENDING"  # ACCEPTED, REJECTED, INCONCLUSIVE
    reason: str = ""
    lessons_learned: str = ""
    rollback_needed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ── Critic ────────────────────────────────────────────────────────────────────

class ImprovementCritic:
    """
    Independent reviewer that tries to INVALIDATE improvement proposals.
    Separate from the builder logic — adversarial by design.
    """

    def review(self, experiment: ExperimentResult) -> CriticReview:
        """Critically review an experiment result."""
        concerns = []
        review = CriticReview(candidate_id=experiment.candidate_id)

        # 1. Schema integrity
        if not experiment.schema_intact:
            concerns.append("Schema integrity violated — HARD REJECT")
            review.verdict = "REJECT"
            review.security_regression = True

        # 2. Trace integrity
        if not experiment.trace_intact:
            concerns.append("Trace integrity violated — trace_id propagation broken")
            review.trace_integrity_regression = True

        # 3. Safety
        if not experiment.safety_intact:
            concerns.append("Safety regression detected")
            review.executor_safety_regression = True
            review.verdict = "REJECT"

        # 4. Regressions vs improvements
        if len(experiment.regressions) > len(experiment.improvements):
            concerns.append(f"More regressions ({len(experiment.regressions)}) than improvements ({len(experiment.improvements)})")

        # 5. Cost inflation
        if experiment.candidate_cost > experiment.baseline_cost * 1.2:
            concerns.append(f"Cost increased by {((experiment.candidate_cost / max(experiment.baseline_cost, 0.001)) - 1) * 100:.0f}%")
            review.hidden_cost_inflation = True

        # 6. Pass rate
        if experiment.candidate_pass_rate < experiment.baseline_pass_rate:
            concerns.append(f"Pass rate dropped: {experiment.baseline_pass_rate:.1%} → {experiment.candidate_pass_rate:.1%}")

        # 7. Benchmark gaming (improvement only on easy scenarios)
        if experiment.candidate_pass_rate == 1.0 and experiment.baseline_pass_rate < 0.8:
            concerns.append("Suspicious 100% pass rate — possible benchmark gaming")
            review.benchmark_gaming = True

        # 8. High-risk module touches
        high_risk_modules = {"core/meta_orchestrator.py", "core/tool_executor.py",
                            "core/security/", "api/main.py"}
        for mod in experiment.touched_modules:
            for hr in high_risk_modules:
                if mod.startswith(hr) or mod == hr:
                    concerns.append(f"Touches high-risk module: {mod}")

        # Compute verdict
        review.concerns = concerns
        hard_rejects = [review.security_regression, review.executor_safety_regression]
        if any(hard_rejects):
            review.verdict = "REJECT"
            review.confidence = 0.9
        elif len(concerns) == 0:
            review.verdict = "ACCEPT"
            review.confidence = 0.8
        elif len(concerns) <= 2 and not review.hidden_cost_inflation:
            review.verdict = "ACCEPT"
            review.confidence = 0.6
        else:
            review.verdict = "INCONCLUSIVE"
            review.confidence = 0.4

        return review


# ── Adoption Gate ─────────────────────────────────────────────────────────────

class AdoptionGate:
    """
    Final gate for improvement adoption.

    Auto-adopt ONLY for low-risk, non-schema, non-security changes
    that pass all benchmarks and improve at least one metric.
    """

    # Modules that NEVER allow auto-adopt
    PROTECTED_SCOPES = {
        "core/schemas/", "core/security/", "core/meta_orchestrator.py",
        "core/tool_executor.py", "api/", ".env", "config/settings.py",
    }

    def decide(self, experiment: ExperimentResult, review: CriticReview) -> AdoptionDecision:
        """Make final adoption decision."""

        # Hard reject
        if review.verdict == "REJECT":
            return AdoptionDecision(
                candidate_id=experiment.candidate_id,
                outcome="REJECT",
                reason=f"Critic rejected: {'; '.join(review.concerns[:3])}",
                requires_human_review=False,
            )

        # Check auto-adopt eligibility
        auto_eligible = self._check_auto_eligible(experiment, review)

        if auto_eligible and review.verdict == "ACCEPT" and review.confidence >= 0.7:
            return AdoptionDecision(
                candidate_id=experiment.candidate_id,
                outcome="AUTO_ADOPT",
                reason="Low-risk, all benchmarks pass, critic accepts",
                requires_human_review=False,
                auto_adopt_eligible=True,
            )

        if review.verdict == "ACCEPT":
            return AdoptionDecision(
                candidate_id=experiment.candidate_id,
                outcome="APPROVE_FOR_REVIEW",
                reason="Improvement detected but requires human review",
                requires_human_review=True,
                review_report=self._build_review_report(experiment, review),
            )

        # INCONCLUSIVE
        return AdoptionDecision(
            candidate_id=experiment.candidate_id,
            outcome="ARCHIVE",
            reason=f"Inconclusive: {'; '.join(review.concerns[:2])}",
            requires_human_review=False,
        )

    def _check_auto_eligible(self, experiment: ExperimentResult, review: CriticReview) -> bool:
        """Auto-adopt only for low-risk changes outside protected scopes."""
        if experiment.risk_level not in ("LOW",):
            return False
        if not experiment.schema_intact or not experiment.trace_intact or not experiment.safety_intact:
            return False
        if experiment.candidate_pass_rate < experiment.baseline_pass_rate:
            return False
        if len(experiment.regressions) > 0:
            return False
        if len(experiment.improvements) == 0:
            return False
        # Check protected scopes
        for mod in experiment.touched_modules:
            for protected in self.PROTECTED_SCOPES:
                if mod.startswith(protected) or mod == protected:
                    return False
        return True

    def _build_review_report(self, experiment: ExperimentResult, review: CriticReview) -> str:
        """Build human-readable review report."""
        lines = [
            f"# Improvement Review: {experiment.candidate_id}",
            f"## Hypothesis: {experiment.hypothesis}",
            f"## Risk: {experiment.risk_level}",
            f"## Touched: {', '.join(experiment.touched_modules)}",
            f"## Benchmark: {experiment.baseline_pass_rate:.1%} → {experiment.candidate_pass_rate:.1%}",
            f"## Cost: {experiment.baseline_cost:.3f} → {experiment.candidate_cost:.3f}",
            f"## Improvements: {', '.join(experiment.improvements) or 'none'}",
            f"## Regressions: {', '.join(experiment.regressions) or 'none'}",
            f"## Critic: {review.verdict} (confidence {review.confidence:.1%})",
            f"## Concerns: {'; '.join(review.concerns) or 'none'}",
        ]
        return "\n".join(lines)


# ── Improvement Loop ──────────────────────────────────────────────────────────

class ImprovementLoop:
    """
    Controlled self-improvement orchestrator.

    Cycle: detect → propose → evaluate → critique → decide → record
    """

    def __init__(self):
        self.critic = ImprovementCritic()
        self.gate = AdoptionGate()
        self._history: list[ImprovementEntry] = []

    def evaluate_candidate(
        self,
        candidate_id: str,
        hypothesis: str,
        touched_modules: list[str],
        risk_level: str,
        baseline_report: dict,
        candidate_report: dict,
    ) -> AdoptionDecision:
        """
        Full evaluation pipeline for a candidate improvement.

        Returns AdoptionDecision.
        """
        experiment = ExperimentResult(
            experiment_id=str(uuid.uuid4())[:12],
            candidate_id=candidate_id,
            hypothesis=hypothesis,
            touched_modules=touched_modules,
            risk_level=risk_level,
            baseline_pass_rate=baseline_report.get("pass_rate", 0),
            candidate_pass_rate=candidate_report.get("pass_rate", 0),
            baseline_cost=baseline_report.get("total_cost", 0),
            candidate_cost=candidate_report.get("total_cost", 0),
            baseline_latency=baseline_report.get("total_duration", 0),
            candidate_latency=candidate_report.get("total_duration", 0),
            regressions=candidate_report.get("regressions", []),
            improvements=candidate_report.get("improvements", []),
            schema_intact=candidate_report.get("schema_intact", True),
            trace_intact=candidate_report.get("trace_intact", True),
            safety_intact=candidate_report.get("safety_intact", True),
        )

        # Critic review
        review = self.critic.review(experiment)

        # Adoption gate
        decision = self.gate.decide(experiment, review)

        # Record
        entry = ImprovementEntry(
            problem_detected=hypothesis,
            hypothesis=hypothesis,
            candidate_change=candidate_id,
            files_touched=touched_modules,
            benchmark_pass_rate=experiment.candidate_pass_rate,
            outcome=decision.outcome,
            reason=decision.reason,
            lessons_learned=f"Critic: {review.verdict}, concerns: {'; '.join(review.concerns[:3])}",
            rollback_needed=decision.outcome == "REJECT",
        )
        self._history.append(entry)

        # Emit event
        try:
            from core.observability.event_envelope import get_event_collector
            get_event_collector().emit_quick("improvement", "evaluation_complete", {
                "candidate_id": candidate_id,
                "outcome": decision.outcome,
                "pass_rate": experiment.candidate_pass_rate,
            })
        except Exception:
            _silent_log.debug("suppressed_exception", src='improvement_loop.py')

        log.info("improvement_evaluated",
                candidate_id=candidate_id,
                outcome=decision.outcome,
                reason=decision.reason[:100])

        return decision

    def get_history(self) -> list[dict]:
        return [e.to_dict() for e in self._history]

    def has_tried(self, hypothesis: str) -> bool:
        """Check if a similar hypothesis was already attempted."""
        for entry in self._history:
            if entry.hypothesis == hypothesis and entry.outcome == "REJECT":
                return True
        return False


_loop: ImprovementLoop | None = None

def get_improvement_loop() -> ImprovementLoop:
    global _loop
    if _loop is None:
        _loop = ImprovementLoop()
    return _loop
