"""
core/economic/strategy_evaluation.py — Strategy evaluation for self-improvement.

Phase D: Improve strategy selection quality over time.

Inputs:
  - Performance signals from kernel
  - Strategic memory records
  - Objective progress signals

Outputs:
  - Strategy recommendations
  - Playbook selection suggestions
  - Capability routing hints

Design:
  - Heuristic evaluation only (no RL, no LLM)
  - Deterministic scoring
  - Integrates with self-model metadata
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from typing import Optional

log = structlog.get_logger("economic.strategy_eval")


@dataclass
class StrategyRecommendation:
    """A recommended strategy action."""
    recommendation_type: str  # "use_playbook", "avoid_playbook", "try_chain", "investigate"
    playbook_id: str = ""
    chain_id: str = ""
    confidence: float = 0.5
    rationale: str = ""
    evidence_count: int = 0

    def to_dict(self) -> dict:
        return {
            "recommendation_type": self.recommendation_type,
            "playbook_id": self.playbook_id,
            "chain_id": self.chain_id,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "evidence_count": self.evidence_count,
        }


@dataclass
class StrategyEvaluation:
    """Evaluation of a strategy's effectiveness."""
    strategy_type: str
    score: float  # 0.0-1.0 overall effectiveness
    sample_count: int
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    trend: str = "unknown"  # improving, stable, degrading, unknown
    recommendations: list[StrategyRecommendation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_type": self.strategy_type,
            "score": round(self.score, 3),
            "sample_count": self.sample_count,
            "strengths": self.strengths[:5],
            "weaknesses": self.weaknesses[:5],
            "trend": self.trend,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


class StrategyEvaluator:
    """
    Evaluates strategy effectiveness from performance + memory signals.

    Rules-based evaluation:
      1. Aggregate outcome scores from strategic memory
      2. Check kernel performance signals for capabilities
      3. Check objective progress
      4. Generate recommendations
    """

    def evaluate(self, strategy_type: str) -> StrategyEvaluation:
        """Evaluate a specific strategy type."""
        # Get strategic memory stats
        stats = self._get_memory_stats(strategy_type)
        # Get capability health
        cap_health = self._get_capability_health(strategy_type)
        # Get objective alignment
        obj_progress = self._get_objective_progress()

        # Compute composite score
        memory_score = stats.get("avg_score", 0.0) if stats.get("count", 0) > 0 else 0.5
        health_score = cap_health.get("health", 0.5)
        progress_score = obj_progress

        # Weighted blend: memory (50%) + capability health (30%) + objective (20%)
        score = 0.5 * memory_score + 0.3 * health_score + 0.2 * progress_score

        # Detect strengths/weaknesses
        strengths, weaknesses = self._analyze(stats, cap_health, score)

        # Generate recommendations
        recommendations = self._recommend(strategy_type, stats, score)

        return StrategyEvaluation(
            strategy_type=strategy_type,
            score=round(score, 3),
            sample_count=stats.get("count", 0),
            strengths=strengths,
            weaknesses=weaknesses,
            trend=stats.get("recent_trend", "unknown"),
            recommendations=recommendations,
        )

    def evaluate_all(self) -> list[StrategyEvaluation]:
        """Evaluate all known strategy types."""
        from core.economic.economic_output import PLAYBOOK_SCHEMA_MAP
        types = set(PLAYBOOK_SCHEMA_MAP.keys())
        return [self.evaluate(t) for t in sorted(types)]

    def suggest_next_playbook(self, goal: str) -> Optional[StrategyRecommendation]:
        """
        Suggest the best playbook for a given goal based on past performance.

        Returns the highest-confidence recommendation, or None.
        """
        from core.economic.strategic_memory import get_strategic_memory
        mem = get_strategic_memory()

        # Find similar past strategies
        similar = mem.find_similar(goal, limit=10)

        if not similar:
            return StrategyRecommendation(
                recommendation_type="use_playbook",
                playbook_id="market_analysis",
                confidence=0.5,
                rationale="No prior context. Market analysis is a safe first step.",
                evidence_count=0,
            )

        # Find the best-performing playbook among similar strategies
        best_score = 0.0
        best_playbook = ""
        evidence = 0
        for entry in similar:
            rec = entry["record"]
            similarity = entry["similarity"]
            weighted_score = rec.get("outcome_score", 0) * similarity
            if weighted_score > best_score:
                best_score = weighted_score
                best_playbook = rec.get("playbook_id", "")
                evidence += 1

        if best_playbook:
            return StrategyRecommendation(
                recommendation_type="use_playbook",
                playbook_id=best_playbook,
                confidence=min(best_score, 0.9),
                rationale=f"Best-performing playbook for similar goals ({evidence} similar records).",
                evidence_count=evidence,
            )

        return None

    def get_routing_hints(self, strategy_type: str) -> dict:
        """
        Get capability routing hints from strategy evaluation.

        Returns hints that can enrich capability routing decisions.
        """
        eval_result = self.evaluate(strategy_type)
        hints: dict = {
            "strategy_score": eval_result.score,
            "trend": eval_result.trend,
        }

        # If strategy is degrading, suggest investigation
        if eval_result.trend == "degrading":
            hints["warning"] = "Strategy effectiveness declining"
            hints["suggested_action"] = "investigate"

        # If high score, boost routing confidence
        if eval_result.score >= 0.7:
            hints["routing_boost"] = 0.1
        elif eval_result.score <= 0.3:
            hints["routing_penalty"] = -0.1

        return hints

    def _get_memory_stats(self, strategy_type: str) -> dict:
        try:
            from core.economic.strategic_memory import get_strategic_memory
            return get_strategic_memory().get_strategy_stats(strategy_type)
        except Exception:
            return {"count": 0}

    def _get_capability_health(self, strategy_type: str) -> dict:
        try:
            from kernel.capabilities.registry import get_capability_registry

            # Map strategy → primary capability
            _STRATEGY_CAPS = {
                "market_analysis": "market_intelligence",
                "product_creation": "product_design",
                "offer_design": "product_design",
                "growth_experiment": "venture_planning",
                "content_strategy": "strategy_reasoning",
                "landing_page": "product_design",
            }
            cap_id = _STRATEGY_CAPS.get(strategy_type, "")
            reg = get_capability_registry()
            cap = reg.get(cap_id)
            if cap:
                return {
                    "health": 0.7,  # baseline — enriched by kernel perf when available
                    "providers": len(cap.providers),
                    "capability_id": cap_id,
                }
            return {"health": 0.5}
        except Exception:
            return {"health": 0.5}

    def _get_objective_progress(self) -> float:
        try:
            from core.objectives.objective_horizon import get_horizon_manager
            mgr = get_horizon_manager()
            # Average progress across all tracked objectives
            all_data = mgr.to_dict()
            metrics = all_data.get("metrics", {})
            if not metrics:
                return 0.5
            total = 0.0
            count = 0
            for oid, ms in metrics.items():
                for m in ms:
                    total += m.get("progress", 0)
                    count += 1
            return total / count if count > 0 else 0.5
        except Exception:
            return 0.5

    def _analyze(self, stats: dict, cap_health: dict, score: float) -> tuple:
        strengths: list[str] = []
        weaknesses: list[str] = []

        if stats.get("avg_score", 0) >= 0.7:
            strengths.append("High average outcome score")
        elif stats.get("avg_score", 0) <= 0.3 and stats.get("count", 0) >= 3:
            weaknesses.append("Low average outcome score")

        if stats.get("recent_trend") == "improving":
            strengths.append("Improving trend")
        elif stats.get("recent_trend") == "degrading":
            weaknesses.append("Degrading trend")

        if cap_health.get("providers", 0) >= 2:
            strengths.append("Multiple capability providers")

        if stats.get("count", 0) < 3:
            weaknesses.append("Insufficient data for reliable evaluation")

        return strengths, weaknesses

    def _recommend(self, strategy_type: str, stats: dict, score: float) -> list:
        recs: list[StrategyRecommendation] = []

        count = stats.get("count", 0)

        if count == 0:
            recs.append(StrategyRecommendation(
                recommendation_type="use_playbook",
                playbook_id=strategy_type,
                confidence=0.5,
                rationale="No data yet. Try this strategy to establish baseline.",
                evidence_count=0,
            ))
        elif score >= 0.7:
            recs.append(StrategyRecommendation(
                recommendation_type="use_playbook",
                playbook_id=strategy_type,
                confidence=min(score, 0.9),
                rationale=f"Strong performance ({score:.2f}) across {count} executions.",
                evidence_count=count,
            ))
        elif score <= 0.3:
            recs.append(StrategyRecommendation(
                recommendation_type="avoid_playbook",
                playbook_id=strategy_type,
                confidence=0.7,
                rationale=f"Poor performance ({score:.2f}) across {count} executions.",
                evidence_count=count,
            ))
            recs.append(StrategyRecommendation(
                recommendation_type="investigate",
                confidence=0.8,
                rationale="Review execution logs and skill outputs for failure patterns.",
            ))
        else:
            # Moderate performance (0.3 < score < 0.7)
            recs.append(StrategyRecommendation(
                recommendation_type="use_playbook",
                playbook_id=strategy_type,
                confidence=score,
                rationale=f"Moderate performance ({score:.2f}) across {count} executions. Room for improvement.",
                evidence_count=count,
            ))

        return recs


# ── Singleton ─────────────────────────────────────────────────

_evaluator: StrategyEvaluator | None = None


def get_strategy_evaluator() -> StrategyEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = StrategyEvaluator()
    return _evaluator
