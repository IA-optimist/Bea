"""
difficulty_estimator — Estimation de la difficulté d'une tâche avant planification.

Score 0.0–1.0 + label : LOW / MEDIUM / HIGH / VERY_HIGH

Facteurs analysés :
  - Longueur et ambiguïté de l'objectif
  - Mots-clés signalant des opérations complexes
  - Type de mission (mission_type)
  - Besoin estimé de réseau, fichiers, docker, git
  - Historique de taux d'échec sur missions similaires
  - Dépendances multiples et niveau de risque

Exemples :
  "lire un fichier"               → LOW   (0.1–0.25)
  "comparer deux fichiers"        → LOW/MEDIUM (0.25–0.45)
  "patcher module + tests"        → MEDIUM/HIGH (0.45–0.70)
  "déployer + rebuild + restart"  → HIGH  (0.65–0.85)
  "créer outil + routing + deploy"→ VERY_HIGH (0.80–1.0)

Fail-open : toutes les fonctions retournent une valeur par défaut sans exception.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger("bea.knowledge.difficulty")

# ── Labels ─────────────────────────────────────────────────────────────────────
LABEL_LOW = "LOW"
LABEL_MEDIUM = "MEDIUM"
LABEL_HIGH = "HIGH"
LABEL_VERY_HIGH = "VERY_HIGH"

_THRESHOLD_MEDIUM = 0.30
_THRESHOLD_HIGH = 0.55
_THRESHOLD_VERY_HIGH = 0.75

# ── Facteurs de base par mission_type ─────────────────────────────────────────
_MISSION_TYPE_BASE_SCORES: dict = {
    # Très simple
    "analysis": 0.15,
    "research": 0.20,
    # Simple/moyen
    "bug_fix": 0.35,
    "coding_task": 0.35,
    "code_generation": 0.30,
    "test": 0.30,
    "api_call": 0.25,
    "api_usage": 0.25,
    # Moyen/complexe
    "improvement": 0.45,
    "ceo_planning": 0.40,
    # Complexe
    "saas_creation": 0.60,
    "deploy": 0.65,
    "deployment": 0.65,
    # Très complexe
    "cybersecurity": 0.70,
}
_DEFAULT_BASE_SCORE = 0.40

# ── Mots-clés et leurs poids ───────────────────────────────────────────────────
_KEYWORDS_HIGH_COMPLEXITY: List[Tuple[str, float]] = [
    # Infrastructure / déploiement
    (r"\bdocker\b", 0.12),
    (r"\bkubernetes\b|\bk8s\b", 0.15),
    (r"\bdeploy\b|\bdéployer\b", 0.10),
    (r"\brebuild\b|\brestart\b", 0.08),
    (r"\binfra\b|\binfrastructure\b", 0.10),
    # VCS
    (r"\bgit\s+push\b|\bgit\s+merge\b|\bgit\s+rebase\b", 0.08),
    (r"\bpull\s+request\b|\bpr\b", 0.07),
    # Réseau/API externe
    (r"\bapi\s+externe\b|\bexternal\s+api\b", 0.08),
    (r"\bwebhook\b|\bauth\b|\boauth\b|\bjwt\b", 0.08),
    # Création / auto-modification
    (r"\bcréer\s+outil\b|\bcreate\s+tool\b|\bnew\s+tool\b", 0.15),
    (r"\bauto.?(modif|patch|improve)\b", 0.12),
    (r"\bself.?improv\b|\bauto.?updat\b", 0.12),
    # Plusieurs étapes explicites
    (r"\bet\s+(ensuite|puis|après)\b|\band\s+then\b", 0.05),
    (r"\bétapes?\b|\bsteps?\b|\bworkflow\b|\bpipeline\b", 0.06),
    # Risque / fichiers critiques
    (r"\bproduction\b|\bprod\b", 0.10),
    (r"\bbase\s+de\s+données\b|\bdatabase\b|\bdb\b", 0.08),
    (r"\bmigration\b", 0.08),
    # Incertitude
    (r"\b(peut.être|probablement|unclear|ambigu)\b", 0.06),
    (r"\b(plusieurs|multiple|divers)\s+\w+", 0.04),
]

_KEYWORDS_LOW_COMPLEXITY: List[Tuple[str, float]] = [
    (r"\blire\b|\bread\b|\bafficher\b|\bdisplay\b|\bshow\b", -0.10),
    (r"\blister\b|\blist\b|\bchercher\b|\bsearch\b", -0.08),
    (r"\bcomparer\b|\bcompare\b", -0.05),
    (r"\bsimple\b|\bquick\b|\brapide\b|\bpetit\b", -0.08),
    (r"\bun\s+seul?\b|\bone\s+file\b|\bun\s+fichier\b", -0.06),
]


def estimate_difficulty(
    goal: str,
    mission_type: str = "",
    context: Optional[dict] = None,
) -> dict:
    """
    Estime la difficulté d'une tâche.

    Args:
        goal         : objectif textuel de la tâche
        mission_type : type de mission (pour le score de base)
        context      : contexte optionnel avec données historiques
                       {
                         "historical_failure_rate": float,  # 0–1
                         "similar_task_avg_retries": float,
                         "tools_count_estimate": int,
                       }

    Returns:
        {
          "score":   float (0.0–1.0),
          "label":   str ("LOW"|"MEDIUM"|"HIGH"|"VERY_HIGH"),
          "reasons": list[str],
        }
    """
    try:
        goal_lower = (goal or "").lower()
        context = context or {}
        reasons: List[str] = []

        # ── 1. Score de base par mission_type ─────────────────────────────────
        base = _MISSION_TYPE_BASE_SCORES.get(mission_type, _DEFAULT_BASE_SCORE)
        if mission_type and mission_type in _MISSION_TYPE_BASE_SCORES:
            reasons.append(f"mission_type:{mission_type}")

        # ── 2. Analyse de l'objectif textuel ─────────────────────────────────
        text_delta = 0.0

        # Longueur de l'objectif (objectif long = plus ambigu)
        goal_len = len(goal_lower.split())
        if goal_len > 30:
            text_delta += 0.08
            reasons.append("long_objective")
        elif goal_len > 15:
            text_delta += 0.04

        # Mots-clés haute complexité
        for pattern, weight in _KEYWORDS_HIGH_COMPLEXITY:
            if re.search(pattern, goal_lower):
                text_delta += weight
                keyword_name = pattern.replace(r"\b", "").split(r"\b")[0][:20]
                reasons.append(f"keyword:{keyword_name.strip()}")

        # Mots-clés basse complexité
        for pattern, weight in _KEYWORDS_LOW_COMPLEXITY:
            if re.search(pattern, goal_lower):
                text_delta += weight  # weight est négatif
                reasons.append("simple_operation")
                break  # un seul bonus simplicité

        # Nombre d'actions multiples (+ et puis)
        conjunction_count = len(re.findall(r"\b(et|puis|ensuite|then|and|after)\b", goal_lower))
        if conjunction_count >= 3:
            text_delta += 0.08
            reasons.append("multi_step_objective")
        elif conjunction_count >= 2:
            text_delta += 0.04

        # ── 3. Facteurs contextuels ───────────────────────────────────────────
        context_delta = 0.0

        # Taux d'échec historique
        failure_rate = float(context.get("historical_failure_rate", 0.0) or 0.0)
        if failure_rate > 0.5:
            context_delta += 0.12
            reasons.append(f"high_historical_failure:{failure_rate:.0%}")
        elif failure_rate > 0.25:
            context_delta += 0.06

        # Retries moyens sur missions similaires
        avg_retries = float(context.get("similar_task_avg_retries", 0.0) or 0.0)
        if avg_retries >= 3:
            context_delta += 0.08
            reasons.append(f"high_avg_retries:{avg_retries:.1f}")

        # Nombre d'outils estimés
        tools_count = int(context.get("tools_count_estimate", 0) or 0)
        if tools_count >= 6:
            context_delta += 0.10
            reasons.append(f"many_tools_needed:{tools_count}")
        elif tools_count >= 3:
            context_delta += 0.05

        # ── 4. Score final ─────────────────────────────────────────────────────
        score = base + text_delta + context_delta
        score = round(min(1.0, max(0.0, score)), 4)
        label = _score_to_label(score)

        if not reasons:
            reasons.append("default_estimation")

        return {
            "score": score,
            "label": label,
            "reasons": reasons[:10],  # limiter à 10 raisons max
        }

    except Exception as exc:
        logger.warning(f"[DifficultyEstimator] estimate_difficulty error: {exc}")
        return {
            "score": 0.5,
            "label": LABEL_MEDIUM,
            "reasons": ["estimation_failed"],
        }


def get_planning_guidance(difficulty_label: str) -> dict:
    """
    Retourne des recommandations de planification selon le label de difficulté.

    Returns:
        {
          "max_steps":           int,
          "require_feasibility": bool,
          "require_fallback":    bool,
          "suggest_human_review": bool,
          "note":                str,
        }
    """
    try:
        label = (difficulty_label or LABEL_MEDIUM).upper()
        if label == LABEL_LOW:
            return {
                "max_steps": 3,
                "require_feasibility": False,
                "require_fallback": False,
                "suggest_human_review": False,
                "note": "Simple task — direct execution recommended",
            }
        elif label == LABEL_MEDIUM:
            return {
                "max_steps": 5,
                "require_feasibility": False,
                "require_fallback": True,
                "suggest_human_review": False,
                "note": "Standard task — include basic fallback",
            }
        elif label == LABEL_HIGH:
            return {
                "max_steps": 8,
                "require_feasibility": True,
                "require_fallback": True,
                "suggest_human_review": False,
                "note": "Complex task — validate feasibility before execution",
            }
        else:  # VERY_HIGH
            return {
                "max_steps": 10,
                "require_feasibility": True,
                "require_fallback": True,
                "suggest_human_review": True,
                "note": "Very complex task — human validation recommended",
            }
    except Exception as exc:
        logger.warning(f"[DifficultyEstimator] get_planning_guidance error: {exc}")
        return {
            "max_steps": 5,
            "require_feasibility": False,
            "require_fallback": True,
            "suggest_human_review": False,
            "note": "guidance_fallback",
        }


# ── Helper interne ─────────────────────────────────────────────────────────────

def _score_to_label(score: float) -> str:
    """Convertit un score float en label string."""
    if score >= _THRESHOLD_VERY_HIGH:
        return LABEL_VERY_HIGH
    elif score >= _THRESHOLD_HIGH:
        return LABEL_HIGH
    elif score >= _THRESHOLD_MEDIUM:
        return LABEL_MEDIUM
    else:
        return LABEL_LOW
