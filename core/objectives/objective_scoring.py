"""
Objective Engine — Priority Scoring.
Score numérique 0-1 avec raisons explicites.
Fail-open : retourne toujours un score valide.
"""
from __future__ import annotations

import logging
import time
from typing import List

from core.objectives.objective_models import Objective, ObjectiveStatus, SubObjectiveStatus

logger = logging.getLogger("bea.objective_scoring")

# ── Poids des facteurs ─────────────────────────────────────────────────────────

_W_IMPORTANCE  = 0.30   # importance déclarée (priority_score initial)
_W_URGENCY     = 0.20   # ancienneté / délai (plus vieux → plus urgent)
_W_PROGRESS    = 0.15   # sous-objectifs déjà avancés → continuer
_W_DIFFICULTY  = 0.15   # difficulté inversée (tâches faciles prioritaires)
_W_TOOLS       = 0.10   # outils disponibles
_W_CONFIDENCE  = 0.10   # confiance de l'agent dans la réalisation

_URGENCY_MAX_AGE_DAYS = 7.0   # après 7 jours sans mise à jour → urgence max


def compute_priority_score(obj: Objective, available_tools: List[str] | None = None) -> dict:
    """
    Calcule le score de priorité d'un objectif (0.0 → 1.0).

    Retourne :
        {
            "score": float,
            "reasons": [str, ...],
            "factors": { factor_name: float }
        }
    Fail-open : retourne toujours un dict valide.
    """
    try:
        reasons: List[str] = []
        factors: dict = {}

        # ── Facteur importance (basé sur priority_score actuel, normalisé) ──
        f_importance = max(0.0, min(1.0, obj.priority_score))
        factors["importance"] = round(f_importance, 3)
        if f_importance > 0.7:
            reasons.append(f"haute importance déclarée ({f_importance:.2f})")

        # ── Facteur urgence (ancienneté du dernier update) ──
        age_days = (time.time() - obj.updated_at) / 86400.0
        f_urgency = min(1.0, age_days / _URGENCY_MAX_AGE_DAYS)
        factors["urgency"] = round(f_urgency, 3)
        if f_urgency > 0.5:
            reasons.append(f"pas mis à jour depuis {age_days:.1f} jours")

        # ── Facteur progression (sous-objectifs déjà commencés) ──
        total_sub = len(obj.sub_objectives)
        if total_sub > 0:
            done_sub = sum(1 for s in obj.sub_objectives if s.status == SubObjectiveStatus.DONE)
            in_progress = sum(1 for s in obj.sub_objectives if s.status == SubObjectiveStatus.RUNNING)
            # Encourager la continuité : 30-70% done → score max
            ratio = done_sub / total_sub
            if 0.3 <= ratio <= 0.7:
                f_progress = 1.0
                reasons.append(f"sous-objectifs en cours ({done_sub}/{total_sub})")
            else:
                f_progress = max(0.2, 1.0 - abs(ratio - 0.5))
            if in_progress > 0:
                f_progress = min(1.0, f_progress + 0.2)
                reasons.append("sous-objectif en cours d'exécution")
        else:
            f_progress = 0.5  # neutre si pas de sous-objectifs définis
        factors["progress"] = round(f_progress, 3)

        # ── Facteur difficulté (inversée : tâches faciles prioritaires) ──
        f_difficulty = 1.0 - max(0.0, min(1.0, obj.difficulty_score))
        factors["difficulty"] = round(f_difficulty, 3)
        if obj.difficulty_score < 0.3:
            reasons.append(f"tâche facile (diff={obj.difficulty_score:.2f})")
        elif obj.difficulty_score > 0.7:
            reasons.append(f"tâche difficile → priorité réduite (diff={obj.difficulty_score:.2f})")

        # ── Facteur outils disponibles ──
        if available_tools and obj.related_tools:
            overlap = len(set(obj.related_tools) & set(available_tools))
            f_tools = min(1.0, overlap / max(1, len(obj.related_tools)))
            if f_tools > 0.5:
                reasons.append(f"outils disponibles ({overlap}/{len(obj.related_tools)})")
        else:
            f_tools = 0.5  # neutre
        factors["tools"] = round(f_tools, 3)

        # ── Facteur confiance ──
        f_confidence = max(0.0, min(1.0, obj.confidence))
        factors["confidence"] = round(f_confidence, 3)
        if f_confidence < 0.3:
            reasons.append(f"confiance faible ({f_confidence:.2f}) → révision recommandée")

        # ── Pénalités ──
        penalty = 0.0
        if obj.status == ObjectiveStatus.BLOCKED:
            penalty += 0.3
            reasons.append("objectif bloqué → priorité réduite de 30%")
        if obj.status == ObjectiveStatus.PAUSED:
            penalty += 0.2
            reasons.append("objectif en pause → priorité réduite de 20%")
        if len(obj.blocked_by) > 0:
            penalty += 0.15
            reasons.append(f"dépend de {len(obj.blocked_by)} objectif(s) non résolu(s)")

        # ── Calcul final ──
        raw_score = (
            _W_IMPORTANCE * f_importance
            + _W_URGENCY   * f_urgency
            + _W_PROGRESS  * f_progress
            + _W_DIFFICULTY * f_difficulty
            + _W_TOOLS     * f_tools
            + _W_CONFIDENCE * f_confidence
        )
        final_score = max(0.0, min(1.0, raw_score - penalty))

        if not reasons:
            reasons.append(f"score calculé automatiquement ({final_score:.2f})")

        return {
            "score":   round(final_score, 3),
            "reasons": reasons,
            "factors": factors,
        }

    except Exception as e:
        logger.warning(f"[OBJECTIVE_SCORING] compute_priority_score error: {e}")
        return {
            "score":   obj.priority_score if hasattr(obj, "priority_score") else 0.5,
            "reasons": [f"scoring error (fallback): {str(e)[:80]}"],
            "factors": {},
        }


def rank_objectives(objectives: List[Objective], available_tools: List[str] | None = None) -> List[dict]:
    """
    Trie une liste d'objectifs par score décroissant.
    Retourne une liste de dicts avec le score enrichi.
    """
    try:
        ranked = []
        for obj in objectives:
            score_result = compute_priority_score(obj, available_tools)
            entry = obj.to_dict()
            entry["computed_priority"] = score_result["score"]
            entry["priority_reasons"]  = score_result["reasons"]
            entry["priority_factors"]  = score_result["factors"]
            ranked.append(entry)
        ranked.sort(key=lambda x: x["computed_priority"], reverse=True)
        return ranked
    except Exception as e:
        logger.warning(f"[OBJECTIVE_SCORING] rank_objectives error: {e}")
        return [o.to_dict() for o in objectives]
