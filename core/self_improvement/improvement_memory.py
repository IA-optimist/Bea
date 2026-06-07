"""
SelfImprovementMemory — persists improvement history and generates reports.

DISTINCTION (Cas B — deux fichiers coexistent intentionnellement) :
  Ce fichier (core/self_improvement/improvement_memory.py) :
    - Responsabilité : historique des tentatives du pipeline self-improve (candidate_type / outcome)
    - Backend : JSON file (workspace/self_improvement/history.json), SYNCHRONE
    - Utilisé par : core/self_improvement/safe_executor.py, api/routes/self_improvement.py
    - Classe : SelfImprovementMemory / get_improvement_memory() (sans settings)

  L'autre fichier (core/improvement_memory.py) :
    - Responsabilité : suivi des scores d'agents (score_before / score_after / feedback)
    - Backend : SQLite (primary) + asyncpg (upgrade path), ASYNC
    - Utilisé par : core/learning_loop.py, api/routes/learning.py, core/orchestrator_v2.py
    - Classe : ImprovementMemory / get_improvement_memory(settings)

  Ne pas fusionner — les deux servent des couches distinctes.

Storage: workspace/self_improvement/history.json

Each history entry:
  {
    "timestamp":      float,
    "candidate_type": str,      # PROMPT_TWEAK | TOOL_PREFERENCE | RETRY_STRATEGY | SKIP_PATTERN
    "description":    str,
    "score":          float,
    "outcome":        str,      # SUCCESS | FAILURE | ROLLED_BACK
    "applied_change": str,
  }
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("bea.self_improvement.improvement_memory")

_HISTORY_DIR = Path("workspace/self_improvement")
_HISTORY_PATH = _HISTORY_DIR / "history.json"

VALID_OUTCOMES = frozenset({"SUCCESS", "FAILURE", "ROLLED_BACK"})


class SelfImprovementMemory:
    """
    Append-only history log for self-improvement attempts.
    All I/O is synchronous + atomic.
    """

    def record(
        self,
        candidate_type: str,
        description: str,
        score: float,
        outcome: str,
        applied_change: str = "",
    ) -> dict:
        """
        Records one self-improvement attempt.

        Args:
            candidate_type: one of VALID_OUTCOMES
            description:    human-readable description of the candidate
            score:          computed score (0.0–1.0)
            outcome:        SUCCESS | FAILURE | ROLLED_BACK
            applied_change: description of what was changed (empty on failure)

        Returns:
            The recorded entry dict.
        """
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome {outcome!r}. Must be one of {VALID_OUTCOMES}")

        entry = {
            "timestamp": time.time(),
            "candidate_type": candidate_type,
            "description": description,
            "score": round(score, 4),
            "outcome": outcome,
            "applied_change": applied_change,
        }

        history = self._load()
        history.append(entry)
        self._save(history)

        logger.info("[ImprovementMemory] recorded %s → %s", candidate_type, outcome)
        return entry

    def get_history(self) -> List[dict]:
        """Returns full history list (newest last)."""
        return self._load()

    def get_improvement_report(self) -> Dict[str, Any]:
        """
        Returns:
          {
            total_attempts:      int,
            success_rate:        float,
            stats_by_type:       {type: {total, success, failure, rolled_back, success_rate}},
            last_improvement:    {timestamp, type, outcome, description} | None,
            consecutive_failures: int,
          }
        """
        # Ne compter que les VRAIES tentatives d'amélioration : un candidat existe
        # (candidate_type renseigné) et ce n'est pas une erreur d'infra / un skip de
        # sécurité (decision in error/skipped/gated). Sinon les records legacy vides
        # ({timestamp,outcome}) et les erreurs daemon gonflent faussement
        # consecutive_failures (44) et déclenchent à tort le circuit-breaker (MAX=3).
        history = [e for e in self._load()
                   if e.get("candidate_type")
                   and e.get("decision") not in ("error", "skipped", "gated")]

        if not history:
            return {
                "total_attempts": 0,
                "success_rate": 0.0,
                "stats_by_type": {},
                "last_improvement": None,
                "consecutive_failures": 0,
            }

        # Stats by type
        by_type: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"SUCCESS": 0, "FAILURE": 0, "ROLLED_BACK": 0}
        )
        for entry in history:
            ctype = entry.get("candidate_type", "UNKNOWN")
            outcome = entry.get("outcome", "FAILURE")
            by_type[ctype][outcome] = by_type[ctype].get(outcome, 0) + 1

        stats_by_type: Dict[str, Any] = {}
        for ctype, counts in by_type.items():
            total = sum(counts.values())
            stats_by_type[ctype] = {
                "total": total,
                "success": counts.get("SUCCESS", 0),
                "failure": counts.get("FAILURE", 0),
                "rolled_back": counts.get("ROLLED_BACK", 0),
                "success_rate": round(counts.get("SUCCESS", 0) / total, 2) if total else 0.0,
            }

        # Overall
        total = len(history)
        successes = sum(1 for e in history if e.get("outcome") == "SUCCESS")

        # Last improvement info
        last = history[-1]
        last_improvement = {
            "timestamp": last.get("timestamp"),
            "type": last.get("candidate_type"),
            "outcome": last.get("outcome"),
            "description": last.get("description", "")[:100],
        }

        # Consecutive failures (from most recent)
        consecutive = 0
        for entry in reversed(history):
            if entry.get("outcome") in ("FAILURE", "ROLLED_BACK"):
                consecutive += 1
            else:
                break

        return {
            "total_attempts": total,
            "success_rate": round(successes / total, 2) if total else 0.0,
            "stats_by_type": stats_by_type,
            "last_improvement": last_improvement,
            "consecutive_failures": consecutive,
        }

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> List[dict]:
        try:
            if _HISTORY_PATH.exists():
                return json.loads(_HISTORY_PATH.read_text("utf-8"))
        except Exception as e:
            logger.debug("_load error: %s", e)
        return []

    def _save(self, history: List[dict]) -> None:
        try:
            _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _HISTORY_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(history, indent=2), "utf-8")
            tmp.replace(_HISTORY_PATH)
        except Exception as e:
            logger.warning("[ImprovementMemory] _save failed — history not persisted: %s", e)


# ── Singleton ─────────────────────────────────────────────────────────────────

_memory: SelfImprovementMemory | None = None


def get_improvement_memory() -> SelfImprovementMemory:
    global _memory
    if _memory is None:
        _memory = SelfImprovementMemory()
    return _memory
