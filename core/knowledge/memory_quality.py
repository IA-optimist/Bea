"""
memory_quality — Score de qualité d'une entrée mémoire (0.0–1.0).

Évalue si une expérience mérite d'être conservée, utilisée comme référence,
ou marquée comme anti-pattern.

Score :
  0.8–1.0 → haute valeur    : succès propre, rapide, sans retry ni rollback
  0.5–0.8 → valeur moyenne  : succès partiel ou quelques anomalies
  0.3–0.5 → faible valeur   : échec ou nombreux problèmes
  0.0–0.3 → anti-pattern    : combinaison à éviter

Fail-open : toutes les fonctions retournent une valeur par défaut sans exception.
"""
from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger("bea.knowledge.memory_quality")

# Seuils de classification
_THRESHOLD_HIGH = 0.8
_THRESHOLD_MEDIUM = 0.5
_THRESHOLD_LOW = 0.3

# Labels
QUALITY_HIGH = "high_value"
QUALITY_MEDIUM = "medium_value"
QUALITY_LOW = "low_value"
QUALITY_ANTI = "anti_pattern"

# Durée de référence par type de mission (secondes) — pénalité si dépassée
_REFERENCE_DURATIONS: Dict[str, float] = {
    "bug_fix": 120.0,
    "deploy": 180.0,
    "coding_task": 120.0,
    "code_generation": 90.0,
    "analysis": 60.0,
    "research": 90.0,
    "test": 60.0,
    "api_call": 30.0,
    "api_usage": 30.0,
    "improvement": 120.0,
    "saas_creation": 180.0,
    "ceo_planning": 60.0,
}
_DEFAULT_REFERENCE_DURATION = 120.0


def compute_memory_quality(mission_data: dict) -> float:
    """
    Calcule un score de qualité 0.0–1.0 pour une entrée mémoire.

    Args:
        mission_data : dict avec les champs suivants (tous optionnels) :
            - success         : bool — résultat final
            - result_status   : str — "success" / "failure" / "partial"
            - duration_s      : float — durée d'exécution en secondes
            - retry_count     : int — nombre de retries
            - rollback_count  : int — nombre de rollbacks déclenchés
            - error_count     : int — nombre d'erreurs
            - error_classes   : list[str] — types d'erreurs
            - tools_used      : list[str] — outils utilisés
            - mission_type    : str — type de mission pour normalisation durée
            - loop_detected   : bool — boucle détectée
            - timeout_count   : int — nombre de timeouts

    Returns:
        float in [0.0, 1.0]
    """
    try:
        success = _extract_success(mission_data)
        retry_count = int(mission_data.get("retry_count", 0) or 0)
        rollback_count = int(mission_data.get("rollback_count", 0) or 0)
        error_count = int(mission_data.get("error_count", 0) or 0)
        duration_s = float(mission_data.get("duration_s", 0.0) or 0.0)
        timeout_count = int(mission_data.get("timeout_count", 0) or 0)
        loop_detected = bool(mission_data.get("loop_detected", False))
        mission_type = str(mission_data.get("mission_type", "") or "")

        # ── Composante 1 : Résultat (40%) ─────────────────────────────────────
        result_status = str(mission_data.get("result_status", "") or "")
        if success or result_status == "success":
            score_result = 1.0
        elif result_status == "partial":
            score_result = 0.4
        else:
            score_result = 0.0

        # ── Composante 2 : Retries (20%) ──────────────────────────────────────
        # 0 retry → 1.0, 1-2 → 0.6, 3+ → 0.2
        if retry_count == 0:
            score_retry = 1.0
        elif retry_count <= 2:
            score_retry = 0.6
        elif retry_count <= 4:
            score_retry = 0.3
        else:
            score_retry = 0.1

        # ── Composante 3 : Rollbacks (20%) ────────────────────────────────────
        if rollback_count == 0:
            score_rollback = 1.0
        elif rollback_count == 1:
            score_rollback = 0.4
        else:
            score_rollback = 0.1

        # ── Composante 4 : Durée (10%) ────────────────────────────────────────
        ref_duration = _REFERENCE_DURATIONS.get(mission_type, _DEFAULT_REFERENCE_DURATION)
        if duration_s <= 0:
            score_duration = 0.7  # Inconnu → neutre
        elif duration_s <= ref_duration:
            score_duration = 1.0
        elif duration_s <= ref_duration * 2:
            score_duration = 0.6
        elif duration_s <= ref_duration * 4:
            score_duration = 0.3
        else:
            score_duration = 0.1

        # ── Composante 5 : Erreurs (10%) ──────────────────────────────────────
        if error_count == 0:
            score_errors = 1.0
        elif error_count <= 2:
            score_errors = 0.6
        elif error_count <= 5:
            score_errors = 0.3
        else:
            score_errors = 0.1

        # ── Score de base ──────────────────────────────────────────────────────
        score = (
            score_result * 0.40
            + score_retry * 0.20
            + score_rollback * 0.20
            + score_duration * 0.10
            + score_errors * 0.10
        )

        # ── Pénalités critiques ────────────────────────────────────────────────
        if loop_detected:
            score *= 0.3  # Boucle détectée : pénalité sévère

        if timeout_count >= 3:
            score *= 0.5  # Timeouts répétés

        # Clamp final
        return round(min(1.0, max(0.0, score)), 4)

    except Exception as exc:
        logger.warning(f"[MemoryQuality] compute_memory_quality error: {exc}")
        return 0.5  # Neutre en cas d'erreur


def classify_memory(score: float) -> str:
    """
    Classifie une entrée mémoire selon son score de qualité.

    Returns:
        "high_value" | "medium_value" | "low_value" | "anti_pattern"
    """
    try:
        score = float(score)
        if score >= _THRESHOLD_HIGH:
            return QUALITY_HIGH
        elif score >= _THRESHOLD_MEDIUM:
            return QUALITY_MEDIUM
        elif score >= _THRESHOLD_LOW:
            return QUALITY_LOW
        else:
            return QUALITY_ANTI
    except Exception:
        return QUALITY_MEDIUM


def should_store(score: float) -> bool:
    """
    Indique si une entrée mérite d'être stockée.
    Score < 0.3 → anti-pattern, pas de stockage positif (mais peut être stocké comme anti-pattern).

    Returns:
        True si la mémoire est utile comme référence positive
    """
    try:
        return float(score) >= _THRESHOLD_LOW
    except Exception:
        return True  # fail-open


def is_anti_pattern(mission_data: dict) -> bool:
    """
    Détecte si une mission représente un anti-pattern à éviter.

    Critères :
    - Échec + rollback déclenché
    - Boucle détectée
    - Timeouts répétés (≥ 3)
    - Retries excessifs (≥ 4) avec échec

    Returns:
        True si anti-pattern
    """
    try:
        success = _extract_success(mission_data)
        retry_count = int(mission_data.get("retry_count", 0) or 0)
        rollback_count = int(mission_data.get("rollback_count", 0) or 0)
        loop_detected = bool(mission_data.get("loop_detected", False))
        timeout_count = int(mission_data.get("timeout_count", 0) or 0)

        if loop_detected:
            return True
        if timeout_count >= 3:
            return True
        if not success and rollback_count >= 1:
            return True
        if not success and retry_count >= 4:
            return True
        return False
    except Exception:
        return False


def get_quality_report(mission_data: dict) -> dict:
    """
    Rapport complet de qualité pour une entrée mémoire.

    Returns:
        {
          "score": float,
          "label": str,
          "should_store": bool,
          "is_anti_pattern": bool,
          "reasons": list[str],
        }
    """
    try:
        score = compute_memory_quality(mission_data)
        label = classify_memory(score)
        anti = is_anti_pattern(mission_data)
        store = should_store(score)
        reasons = _build_reasons(mission_data, score)

        return {
            "score": score,
            "label": label,
            "should_store": store,
            "is_anti_pattern": anti,
            "reasons": reasons,
        }
    except Exception as exc:
        logger.warning(f"[MemoryQuality] get_quality_report error: {exc}")
        return {
            "score": 0.5,
            "label": QUALITY_MEDIUM,
            "should_store": True,
            "is_anti_pattern": False,
            "reasons": ["quality_check_failed"],
        }


# ── Helpers internes ──────────────────────────────────────────────────────────

def _extract_success(mission_data: dict) -> bool:
    """Extrait le succès depuis mission_data (plusieurs champs possibles)."""
    # Priorité : champ 'success' bool, puis 'result_status' string
    success = mission_data.get("success")
    if success is not None:
        return bool(success)
    result_status = str(mission_data.get("result_status", "") or "")
    return result_status == "success"


def _build_reasons(mission_data: dict, score: float) -> List[str]:
    """Construit la liste des raisons expliquant le score."""
    reasons = []
    try:
        success = _extract_success(mission_data)
        retry_count = int(mission_data.get("retry_count", 0) or 0)
        rollback_count = int(mission_data.get("rollback_count", 0) or 0)
        error_count = int(mission_data.get("error_count", 0) or 0)
        timeout_count = int(mission_data.get("timeout_count", 0) or 0)
        loop_detected = bool(mission_data.get("loop_detected", False))

        if success:
            reasons.append("success_confirmed")
        else:
            reasons.append("task_failed")

        if retry_count == 0:
            reasons.append("no_retries")
        elif retry_count >= 3:
            reasons.append(f"high_retry_count:{retry_count}")

        if rollback_count == 0:
            reasons.append("no_rollback")
        elif rollback_count >= 1:
            reasons.append(f"rollback_triggered:{rollback_count}")

        if error_count == 0:
            reasons.append("no_errors")
        elif error_count >= 3:
            reasons.append(f"high_error_count:{error_count}")

        if timeout_count >= 3:
            reasons.append(f"repeated_timeouts:{timeout_count}")

        if loop_detected:
            reasons.append("loop_detected")

        if score >= _THRESHOLD_HIGH:
            reasons.append("high_quality_memory")
        elif score < _THRESHOLD_LOW:
            reasons.append("anti_pattern_candidate")

    except Exception:
        reasons.append("reason_extraction_failed")

    return reasons
