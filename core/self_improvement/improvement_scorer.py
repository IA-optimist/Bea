"""
ImprovementScorer — scores and ranks improvement candidates.

Scoring formula:
  score = expected_gain * (1 - risk_penalty) * novelty_factor

Risk penalties:
  LOW    = 0.0
  MEDIUM = 0.2
  HIGH   = 0.5

Novelty factors (based on prior history):
  1.0  — never tried this candidate type+description
  0.5  — tried and succeeded
  0.0  — tried and failed/rolled_back
"""
from __future__ import annotations

import logging
from typing import List, Tuple

logger = logging.getLogger("bea.self_improvement.improvement_scorer")

_RISK_PENALTIES = {"LOW": 0.0, "MEDIUM": 0.2, "HIGH": 0.5}


class ImprovementScorer:
    """
    Scores ImprovementCandidate objects and returns them sorted by score desc.
    """

    def score_and_rank(
        self, candidates: list, history: list = None
    ) -> List[Tuple[object, float]]:
        """
        Args:
            candidates: List[ImprovementCandidate]
            history:    List of prior history entries (dicts with candidate_type,
                        description, outcome keys)

        Returns:
            List of (candidate, score) tuples, sorted by score descending.
        """
        if history is None:
            history = []

        scored = [
            (candidate, self._compute_score(candidate, history))
            for candidate in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ── Scoring internals ─────────────────────────────────────────────────────

    def _compute_score(self, candidate, history: list) -> float:
        expected_gain = getattr(candidate, "expected_gain", 0.5)
        risk = getattr(candidate, "risk", "MEDIUM")
        ctype = getattr(candidate, "type", "")
        description = getattr(candidate, "description", "")

        risk_penalty = _RISK_PENALTIES.get(risk, 0.2)
        novelty = self._compute_novelty(ctype, description, history)

        score = expected_gain * (1.0 - risk_penalty) * novelty
        return round(max(0.0, min(1.0, score)), 4)

    def _compute_novelty(self, ctype: str, description: str, history: list) -> float:
        """
        Returns:
          1.0 if never tried
          0.5 if tried with SUCCESS outcome
          0.0 if tried with FAILURE or ROLLED_BACK outcome
        """
        if not history:
            return 1.0

        for entry in reversed(history):
            entry_type = entry.get("candidate_type", "")
            entry_desc = entry.get("description", "")
            entry_outcome = entry.get("outcome", "")

            if entry_type == ctype and self._similar(description, entry_desc):
                if entry_outcome == "SUCCESS":
                    return 0.5
                if entry_outcome in ("FAILURE", "ROLLED_BACK"):
                    return 0.0

        return 1.0

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """Jaccard similarity on word tokens; threshold = 0.4."""
        if not a or not b:
            return False
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        union = wa | wb
        if not union:
            return False
        return len(wa & wb) / len(union) >= 0.4


# ── Singleton ─────────────────────────────────────────────────────────────────

_scorer: ImprovementScorer | None = None


def get_improvement_scorer() -> ImprovementScorer:
    global _scorer
    if _scorer is None:
        _scorer = ImprovementScorer()
    return _scorer
