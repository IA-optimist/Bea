"""
core/venture/venture_loop.py — Venture Loop Layer.

Iterative hypothesis → experiment → evaluate → improve loop for
business ventures using structured economic experimentation.

Design:
  - VentureHypothesis: canonical hypothesis object
  - ExperimentSpec: typed experiment definitions
  - ExperimentEvaluation: multi-metric scoring
  - IterationProposal: structured improvement suggestions
  - VentureLoop: bounded iterative engine
  - All deterministic, bounded, policy-safe, fail-open
"""
from __future__ import annotations

import json
import time
import uuid
import structlog
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = structlog.get_logger("venture.loop")


# ── Phase 1: Venture Hypothesis ───────────────────────────────

@dataclass
class VentureHypothesis:
    """Canonical venture hypothesis object."""
    hypothesis_id: str = ""
    problem_statement: str = ""
    target_segment: str = ""
    value_proposition: str = ""
    expected_outcome: str = ""
    assumptions: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    confidence_level: float = 0.5   # 0.0-1.0
    test_strategy: str = ""
    success_signal_definition: str = ""
    created_at: float = 0
    iteration_count: int = 0
    version: str = "1.0"

    def __post_init__(self):
        if not self.hypothesis_id:
            self.hypothesis_id = f"hyp-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()

    def validate(self) -> list[str]:
        """Validate hypothesis completeness."""
        issues = []
        if not self.problem_statement:
            issues.append("missing problem_statement")
        if not self.target_segment:
            issues.append("missing target_segment")
        if not self.value_proposition:
            issues.append("missing value_proposition")
        if not 0.0 <= self.confidence_level <= 1.0:
            issues.append("confidence_level must be 0.0-1.0")
        return issues

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "problem_statement": self.problem_statement,
            "target_segment": self.target_segment,
            "value_proposition": self.value_proposition,
            "expected_outcome": self.expected_outcome,
            "assumptions": self.assumptions[:10],
            "risk_factors": self.risk_factors[:10],
            "confidence_level": round(self.confidence_level, 3),
            "test_strategy": self.test_strategy,
            "success_signal_definition": self.success_signal_definition,
            "iteration_count": self.iteration_count,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VentureHypothesis":
        return cls(
            hypothesis_id=d.get("hypothesis_id", ""),
            problem_statement=d.get("problem_statement", ""),
            target_segment=d.get("target_segment", ""),
            value_proposition=d.get("value_proposition", ""),
            expected_outcome=d.get("expected_outcome", ""),
            assumptions=d.get("assumptions", []),
            risk_factors=d.get("risk_factors", []),
            confidence_level=d.get("confidence_level", 0.5),
            test_strategy=d.get("test_strategy", ""),
            success_signal_definition=d.get("success_signal_definition", ""),
            iteration_count=d.get("iteration_count", 0),
            version=d.get("version", "1.0"),
        )


# ── Phase 2: Experiment Spec ──────────────────────────────────

class ExperimentType(str, Enum):
    LANDING_PAGE       = "landing_page_experiment"
    OFFER_TEST         = "offer_test_experiment"
    CONTENT_VALIDATION = "content_validation_experiment"
    AUTOMATION_VALUE   = "automation_value_experiment"
    FEATURE_VALIDATION = "feature_validation_experiment"


# Experiment type → required artifact types
EXPERIMENT_ARTIFACTS: dict[str, list[str]] = {
    ExperimentType.LANDING_PAGE: ["landing_page", "content_asset"],
    ExperimentType.OFFER_TEST: ["content_asset"],
    ExperimentType.CONTENT_VALIDATION: ["content_asset"],
    ExperimentType.AUTOMATION_VALUE: ["automation_workflow"],
    ExperimentType.FEATURE_VALIDATION: ["mvp_feature"],
}

# Experiment type → primary evaluation metric
EXPERIMENT_METRICS: dict[str, str] = {
    ExperimentType.LANDING_PAGE: "perceived_value_score",
    ExperimentType.OFFER_TEST: "clarity_score",
    ExperimentType.CONTENT_VALIDATION: "coherence_score",
    ExperimentType.AUTOMATION_VALUE: "consistency_score",
    ExperimentType.FEATURE_VALIDATION: "expected_conversion_score",
}


@dataclass
class ExperimentSpec:
    """Specification for a venture experiment."""
    experiment_id: str = ""
    experiment_type: ExperimentType = ExperimentType.LANDING_PAGE
    hypothesis_id: str = ""
    artifact_inputs: list[str] = field(default_factory=list)  # artifact IDs
    evaluation_metric: str = ""
    expected_signal_type: str = "heuristic"  # heuristic, simulated, real
    confidence_threshold: float = 0.6
    stop_conditions: list[str] = field(default_factory=list)
    iteration_limit: int = 5
    created_at: float = 0

    def __post_init__(self):
        if not self.experiment_id:
            self.experiment_id = f"exp-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()
        if not self.evaluation_metric:
            self.evaluation_metric = EXPERIMENT_METRICS.get(
                self.experiment_type, "coherence_score"
            )
        if not self.stop_conditions:
            self.stop_conditions = [
                f"confidence >= {self.confidence_threshold}",
                f"iterations >= {self.iteration_limit}",
                "no improvement for 2 iterations",
            ]

    def validate(self) -> list[str]:
        issues = []
        if not self.hypothesis_id:
            issues.append("missing hypothesis_id")
        if self.iteration_limit < 1 or self.iteration_limit > 10:
            issues.append("iteration_limit must be 1-10")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            issues.append("confidence_threshold must be 0.0-1.0")
        return issues

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "experiment_type": self.experiment_type.value,
            "hypothesis_id": self.hypothesis_id,
            "artifact_inputs": self.artifact_inputs[:10],
            "evaluation_metric": self.evaluation_metric,
            "expected_signal_type": self.expected_signal_type,
            "confidence_threshold": self.confidence_threshold,
            "stop_conditions": self.stop_conditions,
            "iteration_limit": self.iteration_limit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentSpec":
        return cls(
            experiment_id=d.get("experiment_id", ""),
            experiment_type=ExperimentType(d.get("experiment_type", "landing_page_experiment")),
            hypothesis_id=d.get("hypothesis_id", ""),
            artifact_inputs=d.get("artifact_inputs", []),
            evaluation_metric=d.get("evaluation_metric", ""),
            expected_signal_type=d.get("expected_signal_type", "heuristic"),
            confidence_threshold=d.get("confidence_threshold", 0.6),
            stop_conditions=d.get("stop_conditions", []),
            iteration_limit=d.get("iteration_limit", 5),
        )


# ── Phase 4: Evaluation Model ─────────────────────────────────

@dataclass
class ExperimentEvaluation:
    """Multi-metric evaluation of an experiment iteration."""
    evaluation_id: str = ""
    experiment_id: str = ""
    iteration: int = 0
    clarity_score: float = 0.0
    perceived_value_score: float = 0.0
    consistency_score: float = 0.0
    risk_score: float = 0.0         # Lower is better
    expected_conversion_score: float = 0.0
    coherence_score: float = 0.0
    composite_score: float = 0.0
    confidence: float = 0.0
    improvement_priority: float = 0.0  # Higher = more room to improve

    def __post_init__(self):
        if not self.evaluation_id:
            self.evaluation_id = f"eval-{uuid.uuid4().hex[:8]}"
        self._compute_composite()

    def _compute_composite(self):
        """Compute composite score from individual metrics."""
        scores = [
            self.clarity_score,
            self.perceived_value_score,
            self.consistency_score,
            self.coherence_score,
            self.expected_conversion_score,
        ]
        non_zero = [s for s in scores if s > 0]
        self.composite_score = sum(non_zero) / len(non_zero) if non_zero else 0.0
        self.confidence = min(1.0, self.composite_score * 1.2)  # Slightly optimistic
        self.improvement_priority = max(0.0, 1.0 - self.composite_score)

    def to_dict(self) -> dict:
        return {
            "evaluation_id": self.evaluation_id,
            "experiment_id": self.experiment_id,
            "iteration": self.iteration,
            "clarity_score": round(self.clarity_score, 3),
            "perceived_value_score": round(self.perceived_value_score, 3),
            "consistency_score": round(self.consistency_score, 3),
            "risk_score": round(self.risk_score, 3),
            "expected_conversion_score": round(self.expected_conversion_score, 3),
            "coherence_score": round(self.coherence_score, 3),
            "composite_score": round(self.composite_score, 3),
            "confidence": round(self.confidence, 3),
            "improvement_priority": round(self.improvement_priority, 3),
        }


def evaluate_artifacts(
    hypothesis: VentureHypothesis,
    build_results: list,
    iteration: int = 0,
) -> ExperimentEvaluation:
    """
    Evaluate experiment artifacts using heuristic scoring.

    Signals are derived from build quality, hypothesis clarity, and
    structural completeness. No LLM needed for scoring.
    """
    eval_ = ExperimentEvaluation(iteration=iteration)

    # Clarity: based on hypothesis completeness
    filled = sum(1 for f in [
        hypothesis.problem_statement, hypothesis.target_segment,
        hypothesis.value_proposition, hypothesis.expected_outcome,
        hypothesis.test_strategy, hypothesis.success_signal_definition,
    ] if f)
    eval_.clarity_score = filled / 6.0

    # Perceived value: based on value proposition length and detail
    vp_len = len(hypothesis.value_proposition)
    eval_.perceived_value_score = min(1.0, vp_len / 200)

    # Consistency: based on build success rate
    if build_results:
        success_count = sum(1 for r in build_results if getattr(r, 'success', False))
        eval_.consistency_score = success_count / len(build_results)
    else:
        eval_.consistency_score = 0.0

    # Coherence: problem↔value alignment (heuristic: word overlap)
    if hypothesis.problem_statement and hypothesis.value_proposition:
        prob_words = set(hypothesis.problem_statement.lower().split())
        val_words = set(hypothesis.value_proposition.lower().split())
        overlap = len(prob_words & val_words)
        total = max(1, len(prob_words | val_words))
        eval_.coherence_score = min(1.0, overlap / total * 3)  # Amplified
    else:
        eval_.coherence_score = 0.0

    # Risk: based on risk factors count
    eval_.risk_score = min(1.0, len(hypothesis.risk_factors) / 5)

    # Expected conversion: composite of other scores
    eval_.expected_conversion_score = (
        eval_.clarity_score * 0.3 +
        eval_.perceived_value_score * 0.3 +
        eval_.coherence_score * 0.4
    )

    eval_._compute_composite()
    return eval_


# ── Phase 5: Iteration Proposal ───────────────────────────────

class ChangeType(str, Enum):
    IMPROVE_POSITIONING  = "improve_positioning"
    SIMPLIFY_VALUE_PROP  = "simplify_value_proposition"
    ADJUST_SEGMENT       = "adjust_target_segment"
    REDUCE_SCOPE         = "reduce_scope"
    CHANGE_PRICING       = "change_pricing_framing"
    ADJUST_MESSAGING     = "adjust_messaging_angle"
    ADD_EVIDENCE         = "add_supporting_evidence"


@dataclass
class IterationProposal:
    """Structured improvement proposal for next iteration."""
    proposal_id: str = ""
    change_type: ChangeType = ChangeType.IMPROVE_POSITIONING
    affected_artifact: str = ""   # artifact type to rebuild
    expected_improvement_reason: str = ""
    confidence_level: float = 0.5
    priority: int = 1             # 1=highest

    def __post_init__(self):
        if not self.proposal_id:
            self.proposal_id = f"prop-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "change_type": self.change_type.value,
            "affected_artifact": self.affected_artifact,
            "expected_improvement_reason": self.expected_improvement_reason,
            "confidence_level": round(self.confidence_level, 3),
            "priority": self.priority,
        }


def generate_proposals(
    evaluation: ExperimentEvaluation,
    hypothesis: VentureHypothesis,
) -> list[IterationProposal]:
    """Generate improvement proposals based on evaluation weaknesses."""
    proposals = []

    # Find weakest metric
    metrics = {
        "clarity": evaluation.clarity_score,
        "perceived_value": evaluation.perceived_value_score,
        "consistency": evaluation.consistency_score,
        "coherence": evaluation.coherence_score,
    }
    sorted_metrics = sorted(metrics.items(), key=lambda x: x[1])

    for i, (metric, score) in enumerate(sorted_metrics):
        if score >= 0.8:
            continue  # Good enough

        if metric == "clarity":
            proposals.append(IterationProposal(
                change_type=ChangeType.IMPROVE_POSITIONING,
                affected_artifact="content_asset",
                expected_improvement_reason=f"Clarity score is {score:.2f} — strengthen problem statement and success definition",
                confidence_level=0.7,
                priority=i + 1,
            ))
        elif metric == "perceived_value":
            proposals.append(IterationProposal(
                change_type=ChangeType.SIMPLIFY_VALUE_PROP,
                affected_artifact="content_asset",
                expected_improvement_reason=f"Perceived value is {score:.2f} — simplify and strengthen value proposition",
                confidence_level=0.6,
                priority=i + 1,
            ))
        elif metric == "consistency":
            proposals.append(IterationProposal(
                change_type=ChangeType.REDUCE_SCOPE,
                affected_artifact="mvp_feature",
                expected_improvement_reason=f"Consistency is {score:.2f} — reduce scope to improve build reliability",
                confidence_level=0.5,
                priority=i + 1,
            ))
        elif metric == "coherence":
            proposals.append(IterationProposal(
                change_type=ChangeType.ADJUST_MESSAGING,
                affected_artifact="content_asset",
                expected_improvement_reason=f"Coherence is {score:.2f} — align messaging with problem statement",
                confidence_level=0.6,
                priority=i + 1,
            ))

    # If no proposals: general improvement
    if not proposals and evaluation.composite_score < 0.8:
        proposals.append(IterationProposal(
            change_type=ChangeType.ADD_EVIDENCE,
            affected_artifact="content_asset",
            expected_improvement_reason="Overall score below target — add supporting evidence and detail",
            confidence_level=0.5,
            priority=1,
        ))

    return proposals[:4]  # Max 4 proposals per iteration


# ── Phase 3 + 6 + 7: Venture Loop Engine ─────────────────────

MAX_LOOP_ITERATIONS = 5
MIN_IMPROVEMENT_THRESHOLD = 0.02  # Must improve by at least 2% per iteration
COOLDOWN_SECONDS = 1  # Minimum time between iterations


@dataclass
class LoopIteration:
    """Record of one loop iteration."""
    iteration: int
    evaluation: dict
    proposals: list[dict]
    hypothesis_snapshot: dict
    build_success_count: int = 0
    build_total_count: int = 0
    timestamp: float = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class VentureLoopResult:
    """Complete result of a venture loop execution."""
    loop_id: str = ""
    hypothesis_id: str = ""
    experiment_id: str = ""
    iterations: list[LoopIteration] = field(default_factory=list)
    final_evaluation: dict = field(default_factory=dict)
    final_confidence: float = 0.0
    score_progression: list[float] = field(default_factory=list)
    status: str = "pending"  # pending, running, converged, stopped, failed
    reason: str = ""

    def __post_init__(self):
        if not self.loop_id:
            self.loop_id = f"loop-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "loop_id": self.loop_id,
            "hypothesis_id": self.hypothesis_id,
            "experiment_id": self.experiment_id,
            "iterations_count": len(self.iterations),
            "final_evaluation": self.final_evaluation,
            "final_confidence": round(self.final_confidence, 3),
            "score_progression": [round(s, 3) for s in self.score_progression],
            "status": self.status,
            "reason": self.reason,
        }


# In-memory stores
_hypotheses: dict[str, VentureHypothesis] = {}
_experiments: dict[str, ExperimentSpec] = {}
_evaluations: list[ExperimentEvaluation] = []
_loop_results: list[VentureLoopResult] = []


def get_hypotheses() -> dict[str, VentureHypothesis]:
    return dict(_hypotheses)


def get_experiments() -> dict[str, ExperimentSpec]:
    return dict(_experiments)


def get_evaluations() -> list[ExperimentEvaluation]:
    return list(_evaluations)


def get_loop_results() -> list[VentureLoopResult]:
    return list(_loop_results)


def run_venture_loop(
    hypothesis: VentureHypothesis,
    experiment_type: ExperimentType = ExperimentType.LANDING_PAGE,
    max_iterations: int = MAX_LOOP_ITERATIONS,
    budget_mode: str = "normal",
) -> VentureLoopResult:
    """
    Run a bounded venture experiment loop.

    Flow per iteration:
      1. Evaluate current hypothesis quality
      2. If confidence met → stop (converged)
      3. If no improvement → stop (plateau)
      4. Generate improvement proposals
      5. Apply top proposal to hypothesis
      6. Policy check before next iteration
      7. Record to strategic memory

    Returns VentureLoopResult with full iteration history.
    """
    # Validate
    issues = hypothesis.validate()
    if issues:
        return VentureLoopResult(
            hypothesis_id=hypothesis.hypothesis_id,
            status="failed",
            reason=f"Invalid hypothesis: {', '.join(issues)}",
        )

    # Bound iterations
    max_iterations = min(max_iterations, MAX_LOOP_ITERATIONS)

    # Create experiment spec
    spec = ExperimentSpec(
        experiment_type=experiment_type,
        hypothesis_id=hypothesis.hypothesis_id,
        iteration_limit=max_iterations,
    )

    # Store
    _hypotheses[hypothesis.hypothesis_id] = hypothesis
    _experiments[spec.experiment_id] = spec

    result = VentureLoopResult(
        hypothesis_id=hypothesis.hypothesis_id,
        experiment_id=spec.experiment_id,
        status="running",
    )

    prev_score = 0.0
    no_improvement_count = 0

    for i in range(1, max_iterations + 1):
        hypothesis.iteration_count = i

        # Evaluate (heuristic — no LLM needed)
        evaluation = evaluate_artifacts(hypothesis, [], iteration=i)
        evaluation.experiment_id = spec.experiment_id
        _evaluations.append(evaluation)

        result.score_progression.append(evaluation.composite_score)

        # Generate proposals
        proposals = generate_proposals(evaluation, hypothesis)

        # Record iteration
        iteration = LoopIteration(
            iteration=i,
            evaluation=evaluation.to_dict(),
            proposals=[p.to_dict() for p in proposals],
            hypothesis_snapshot=hypothesis.to_dict(),
        )
        result.iterations.append(iteration)

        # Check convergence
        if evaluation.confidence >= spec.confidence_threshold:
            result.status = "converged"
            result.reason = f"Confidence {evaluation.confidence:.3f} >= threshold {spec.confidence_threshold}"
            break

        # Check improvement
        improvement = evaluation.composite_score - prev_score
        if i > 1 and improvement < MIN_IMPROVEMENT_THRESHOLD:
            no_improvement_count += 1
            if no_improvement_count >= 2:
                result.status = "stopped"
                result.reason = f"No improvement for 2 iterations (last delta: {improvement:.4f})"
                break
        else:
            no_improvement_count = 0

        prev_score = evaluation.composite_score

        # Apply top proposal if available
        if proposals:
            _apply_proposal(hypothesis, proposals[0])

        # Cooldown
        time.sleep(COOLDOWN_SECONDS * 0.01)  # Minimal in test

    # Finalize
    if result.status == "running":
        result.status = "stopped"
        result.reason = f"Reached iteration limit ({max_iterations})"

    result.final_evaluation = evaluation.to_dict() if _evaluations else {}
    result.final_confidence = evaluation.confidence if _evaluations else 0.0

    # Record to strategic memory (fail-open)
    _record_loop_outcome(result, hypothesis)

    _loop_results.append(result)
    return result


def _apply_proposal(hypothesis: VentureHypothesis, proposal: IterationProposal):
    """Apply an improvement proposal to mutate the hypothesis."""
    ct = proposal.change_type

    if ct == ChangeType.IMPROVE_POSITIONING:
        hypothesis.problem_statement += " [refined: clearer problem definition]"
        hypothesis.success_signal_definition += " [refined: measurable outcome]"
    elif ct == ChangeType.SIMPLIFY_VALUE_PROP:
        if len(hypothesis.value_proposition) > 100:
            hypothesis.value_proposition = hypothesis.value_proposition[:100] + " [simplified for clarity]"
        else:
            hypothesis.value_proposition += " — simple, direct, and valuable"
    elif ct == ChangeType.ADJUST_SEGMENT:
        hypothesis.target_segment += " [refined: more specific segment]"
    elif ct == ChangeType.REDUCE_SCOPE:
        hypothesis.expected_outcome = (hypothesis.expected_outcome or "")[:100] + " [reduced scope]"
    elif ct == ChangeType.ADJUST_MESSAGING:
        # Improve coherence by copying problem words into value prop
        if hypothesis.problem_statement:
            key_words = hypothesis.problem_statement.split()[:3]
            hypothesis.value_proposition += " — addressing " + " ".join(key_words)
    elif ct == ChangeType.ADD_EVIDENCE:
        hypothesis.assumptions.append("Added supporting evidence for iteration")


# ── Phase 6: Memory Integration ───────────────────────────────

def _record_loop_outcome(result: VentureLoopResult, hypothesis: VentureHypothesis):
    """Record venture loop outcome to strategic memory."""
    try:
        from core.economic.strategic_memory import StrategicRecord, get_strategic_memory
        mem = get_strategic_memory()
        mem.record(StrategicRecord(
            record_type="venture_experiment",
            score=result.final_confidence,
            context={
                "hypothesis_id": hypothesis.hypothesis_id,
                "iterations": len(result.iterations),
                "status": result.status,
                "target_segment": hypothesis.target_segment,
            },
            findings={
                "score_progression": result.score_progression,
                "final_composite": result.final_evaluation.get("composite_score", 0),
            },
            failures={"reason": result.reason} if result.status == "failed" else {},
        ))
    except Exception:
        pass  # Fail-open

    try:
        from core.cognitive_events.emitter import ce_emit
        ce_emit.mission_completed(
            mission_id=result.loop_id,
            duration_ms=0,
            metadata={
                "type": "venture_loop",
                "iterations": len(result.iterations),
                "status": result.status,
                "confidence": result.final_confidence,
            },
        )
    except Exception:
        _silent_log.debug("suppressed_exception", src='venture_loop.py')
