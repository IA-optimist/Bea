"""
JARVIS MAX — Decision Confidence Scoring
============================================
Scores the confidence of routing/execution decisions with structured reasoning.

Every significant decision (model selection, agent routing, tool choice, 
approval recommendation) gets a confidence score + justification.

Integrates with:
  - MetaCognition (pre-action analysis)
  - Agent Reputation (historical performance)
  - Learning Traces (past similar decisions)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

import structlog

log = structlog.get_logger()


class DecisionType(str, Enum):
    AGENT_SELECTION = "agent_selection"
    MODEL_SELECTION = "model_selection"
    TOOL_SELECTION = "tool_selection"
    APPROVAL_RECOMMENDATION = "approval_recommendation"
    ROUTING = "routing"
    RETRY = "retry"
    ESCALATION = "escalation"
    BUDGET_ALLOCATION = "budget_allocation"


@dataclass
class ConfidenceScore:
    """Structured confidence assessment for a decision."""
    decision_type: DecisionType = DecisionType.ROUTING
    chosen_option: str = ""
    alternatives_considered: List[str] = field(default_factory=list)
    score: float = 0.5  # 0.0-1.0
    factors: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "decision_type": self.decision_type.value,
            "chosen_option": self.chosen_option,
            "alternatives": self.alternatives_considered,
            "score": round(self.score, 3),
            "factors": self.factors,
            "reasoning": self.reasoning,
        }


class DecisionConfidence:
    """
    Scores decisions using multiple signals.

    Not a replacement for existing routing — it's an overlay that
    provides explainability and calibration feedback.
    """

    def __init__(self, reputation_tracker=None, learning_traces=None):
        self._reputation = reputation_tracker
        self._traces = learning_traces
        self._history: List[ConfidenceScore] = []
        self._max_history = 1000

    def score_agent_selection(
        self,
        chosen_agent: str,
        candidates: List[str],
        task_context: str = "",
    ) -> ConfidenceScore:
        """Score confidence in selecting a specific agent."""
        factors = []
        score = 0.5

        # Factor 1: Reputation
        if self._reputation:
            rep_score = self._reputation.get_score(chosen_agent)
            factors.append({"factor": "reputation", "value": rep_score, "weight": 0.3})
            score += (rep_score - 0.5) * 0.3

        # Factor 2: Alternatives available
        alt_count = len(candidates) - 1
        if alt_count == 0:
            factors.append({"factor": "no_alternatives", "value": 0, "weight": 0.1})
            score -= 0.1  # Single option = less confidence
        else:
            factors.append({"factor": "alternatives", "value": alt_count, "weight": 0.1})

        # Factor 3: Historical success for similar tasks
        if self._traces:
            insights = self._traces.get_insights_for(chosen_agent)
            if insights:
                factors.append({"factor": "past_insights", "value": len(insights), "weight": 0.2})
                score += 0.1

        score = max(0.0, min(1.0, score))

        result = ConfidenceScore(
            decision_type=DecisionType.AGENT_SELECTION,
            chosen_option=chosen_agent,
            alternatives_considered=candidates,
            score=score,
            factors=factors,
            reasoning=f"Selected {chosen_agent} from {len(candidates)} candidates. "
                      f"Score: {score:.2f}. Context: {task_context[:80]}",
        )
        self._record(result)
        return result

    def score_model_selection(
        self,
        chosen_model: str,
        task_type: str = "",
        budget: str = "",
    ) -> ConfidenceScore:
        """Score confidence in model selection."""
        factors = []
        score = 0.6  # Models are generally well-matched by routing policy

        if budget in ("cheap", "nano"):
            factors.append({"factor": "budget_constraint", "value": budget, "weight": 0.2})
            score -= 0.1  # Budget-constrained = less optimal model

        factors.append({"factor": "task_type", "value": task_type, "weight": 0.3})

        result = ConfidenceScore(
            decision_type=DecisionType.MODEL_SELECTION,
            chosen_option=chosen_model,
            score=max(0.0, min(1.0, score)),
            factors=factors,
            reasoning=f"Model {chosen_model} for {task_type} (budget: {budget})",
        )
        self._record(result)
        return result

    def score_approval_recommendation(
        self,
        action: str,
        risk_level: str,
        agent_id: str = "",
    ) -> ConfidenceScore:
        """Score confidence in whether to auto-approve or escalate."""
        score = 0.5
        factors = []

        risk_scores = {"none": 0.9, "low": 0.7, "medium": 0.5, "high": 0.3, "critical": 0.1}
        risk_val = risk_scores.get(risk_level, 0.5)
        factors.append({"factor": "risk_level", "value": risk_level, "weight": 0.4})
        score = risk_val * 0.4

        if self._reputation and agent_id:
            rep = self._reputation.get_score(agent_id)
            factors.append({"factor": "agent_reputation", "value": rep, "weight": 0.3})
            score += rep * 0.3

        should_approve = score >= 0.35
        factors.append({"factor": "recommendation", "value": "approve" if should_approve else "escalate", "weight": 0.0})

        result = ConfidenceScore(
            decision_type=DecisionType.APPROVAL_RECOMMENDATION,
            chosen_option="approve" if should_approve else "escalate",
            score=max(0.0, min(1.0, score)),
            factors=factors,
            reasoning=f"Action '{action}' risk={risk_level} → {'approve' if should_approve else 'escalate'} "
                      f"(confidence: {score:.2f})",
        )
        self._record(result)
        return result

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._history[-limit:]]

    def calibration_report(self) -> Dict[str, Any]:
        """How well-calibrated are our confidence scores?"""
        if not self._history:
            return {"total_decisions": 0, "avg_confidence": 0}
        return {
            "total_decisions": len(self._history),
            "avg_confidence": round(
                sum(s.score for s in self._history) / len(self._history), 3
            ),
            "by_type": {
                dt.value: {
                    "count": sum(1 for s in self._history if s.decision_type == dt),
                    "avg_score": round(
                        sum(s.score for s in self._history if s.decision_type == dt) /
                        max(sum(1 for s in self._history if s.decision_type == dt), 1), 3
                    ),
                }
                for dt in DecisionType
                if any(s.decision_type == dt for s in self._history)
            },
        }

    def _record(self, score: ConfidenceScore) -> None:
        self._history.append(score)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
