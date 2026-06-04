"""
Objective Engine — Décomposition en sous-objectifs.
Réutilise difficulty_estimator et pattern_detector (fail-open si indisponibles).
Retourne toujours une liste de SubObjective valide.
"""
from __future__ import annotations

import structlog
import time
import uuid
from typing import List, Optional

from core.objectives.objective_models import Objective, SubObjective, SubObjectiveStatus

logger = structlog.get_logger("jarvis.objective_breakdown")
log = logger  # alias for M3 emitter

# ── Imports fail-open ──────────────────────────────────────────────────────────

try:
    from core.knowledge.difficulty_estimator import estimate_difficulty as _estimate_difficulty
    _DIFFICULTY_AVAILABLE = True
except ImportError:
    _DIFFICULTY_AVAILABLE = False

try:
    from core.knowledge.pattern_detector import detect_patterns as _detect_patterns
    _PATTERNS_AVAILABLE = True
except ImportError:
    _PATTERNS_AVAILABLE = False


# ── Templates par catégorie ────────────────────────────────────────────────────

_TEMPLATES: dict[str, list[dict]] = {
    "deploy": [
        {"title": "Vérification des prérequis", "tools": ["env_checker", "file_search"], "signal": "env OK"},
        {"title": "Préparation et tests",        "tools": ["run_unit_tests"],             "signal": "tests pass"},
        {"title": "Build / packaging",           "tools": ["docker_compose_build"],       "signal": "build success"},
        {"title": "Déploiement",                 "tools": ["docker_compose_up", "git_push"], "signal": "deployed"},
        {"title": "Vérification santé",          "tools": ["api_healthcheck"],            "signal": "health OK"},
    ],
    "bug_fix": [
        {"title": "Reproduction du bug",         "tools": ["run_unit_tests", "read_file"], "signal": "bug reproduced"},
        {"title": "Analyse de la cause racine",  "tools": ["file_search", "search_in_files"], "signal": "root cause found"},
        {"title": "Implémentation du correctif", "tools": ["replace_in_file"],            "signal": "fix applied"},
        {"title": "Validation du correctif",     "tools": ["run_unit_tests"],             "signal": "tests pass"},
    ],
    "coding_task": [
        {"title": "Analyse et conception",       "tools": ["memory_search_similar", "read_file"], "signal": "design ready"},
        {"title": "Implémentation",              "tools": ["file_create", "replace_in_file"],     "signal": "code written"},
        {"title": "Tests unitaires",             "tools": ["run_unit_tests"],                      "signal": "tests pass"},
        {"title": "Revue et nettoyage",          "tools": ["search_in_files"],                     "signal": "code reviewed"},
    ],
    "analysis": [
        {"title": "Collecte des données",        "tools": ["memory_search_similar", "http_get"], "signal": "data collected"},
        {"title": "Analyse",                     "tools": ["search_in_files"],                   "signal": "analysis done"},
        {"title": "Synthèse et rapport",         "tools": ["memory_store_solution"],             "signal": "report ready"},
    ],
    "research": [
        {"title": "Recherche initiale",          "tools": ["fetch_url", "doc_fetch"],     "signal": "sources found"},
        {"title": "Analyse et tri",              "tools": ["memory_search_similar"],      "signal": "relevant content identified"},
        {"title": "Synthèse",                    "tools": ["memory_store_solution"],      "signal": "synthesis done"},
    ],
    "general": [
        {"title": "Analyse de la demande",       "tools": [],                             "signal": "scope defined"},
        {"title": "Exécution principale",        "tools": [],                             "signal": "done"},
        {"title": "Validation",                  "tools": [],                             "signal": "validated"},
    ],
}


def _infer_category(title: str, description: str) -> str:
    """Infère la catégorie d'un objectif depuis son titre/description."""
    text = f"{title} {description}".lower()
    if any(w in text for w in ["deploy", "déploie", "docker", "production", "release"]):
        return "deploy"
    if any(w in text for w in ["bug", "fix", "corrig", "error", "erreur", "crash"]):
        return "bug_fix"
    if any(w in text for w in ["code", "implémente", "créer", "module", "class", "fonction"]):
        return "coding_task"
    if any(w in text for w in ["analyse", "analyze", "audit", "revue", "review"]):
        return "analysis"
    if any(w in text for w in ["recherche", "research", "doc", "documentation"]):
        return "research"
    return "general"


def breakdown_objective(
    obj: Objective,
    mission_type: Optional[str] = None,
) -> List[SubObjective]:
    """
    Décompose un objectif en sous-objectifs.
    Réutilise difficulty_estimator + pattern_detector si disponibles.
    Retourne toujours une liste non vide. Fail-open total.
    """
    try:
        category = mission_type or obj.category or _infer_category(obj.title, obj.description)

        # ── Estimation de difficulté (fail-open) ──────────────────────────
        difficulty_score = obj.difficulty_score
        if _DIFFICULTY_AVAILABLE:
            try:
                diff_result = _estimate_difficulty(
                    goal=f"{obj.title}: {obj.description}",
                    mission_type=category,
                )
                difficulty_score = float(diff_result.get("score", difficulty_score))
            except Exception as _exc:
                log.warning("swallowed_exception", action="objective_breakdown_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # ── Patterns similaires pour enrichir les outils (fail-open) ──────
        pattern_tools: List[str] = []
        if _PATTERNS_AVAILABLE:
            try:
                patterns = _detect_patterns(
                    goal=f"{obj.title}: {obj.description}",
                    mission_type=category,
                )
                if patterns.get("has_prior_knowledge"):
                    raw_pt = patterns.get("effective_tools", [])
                    pattern_tools = [t if isinstance(t, str) else (t.get("name","") if isinstance(t, dict) else str(t)) for t in raw_pt if t]
            except Exception as _exc:
                log.warning("swallowed_exception", action="objective_breakdown_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # ── Sélection du template ──────────────────────────────────────────
        template = _TEMPLATES.get(category, _TEMPLATES["general"])

        # Adapter le nombre d'étapes selon la difficulté
        if difficulty_score < 0.3:
            template = template[:2]      # tâche simple → 2 étapes max
        elif difficulty_score > 0.75:
            # tâche très difficile → ajouter une étape de rollback
            template = template + [{"title": "Rollback si nécessaire", "tools": [], "signal": "rollback ready"}]

        # ── Création des SubObjectives ─────────────────────────────────────
        sub_objs: List[SubObjective] = []
        for i, step in enumerate(template):
            tools = list(step.get("tools", []))
            # Enrichir avec les outils issus des patterns (si pas déjà présents)
            for pt in pattern_tools[:2]:
                if pt and pt not in tools:
                    tools.append(pt)

            node = SubObjective(
                node_id             = str(uuid.uuid4())[:8],
                parent_objective_id = obj.objective_id,
                title               = step["title"],
                description         = f"Étape {i+1} de '{obj.title}'",
                status              = SubObjectiveStatus.TODO if i > 0 else SubObjectiveStatus.READY,
                sequence_order      = i,
                difficulty          = round(min(1.0, difficulty_score * (0.8 + i * 0.05)), 3),
                recommended_tools   = tools,
                recommended_agents  = _suggest_agents(category),
                completion_signal   = step.get("signal", ""),
                last_updated        = time.time(),
            )
            sub_objs.append(node)

        logger.info(json_log("objective_breakdown", {
            "objective_id": obj.objective_id,
            "category":     category,
            "difficulty":   round(difficulty_score, 3),
            "sub_count":    len(sub_objs),
            "used_patterns": bool(pattern_tools),
        }))
        return sub_objs

    except Exception as e:
        logger.warning(f"[OBJECTIVE_BREAKDOWN] fallback single-step: {e}")
        # Fallback : sous-objectif unique
        return [SubObjective(
            node_id             = str(uuid.uuid4())[:8],
            parent_objective_id = obj.objective_id,
            title               = "Exécution directe",
            description         = obj.description,
            status              = SubObjectiveStatus.READY,
            sequence_order      = 0,
            difficulty          = obj.difficulty_score,
            last_updated        = time.time(),
        )]


def _suggest_agents(category: str) -> List[str]:
    """Suggère des agents selon la catégorie et l'étape."""
    mapping = {
        "deploy":       ["devops-agent", "docker-agent"],
        "bug_fix":      ["debug-agent", "code-agent"],
        "coding_task":  ["code-agent", "forge-builder"],
        "analysis":     ["analyst-agent"],
        "research":     ["research-agent"],
    }
    return mapping.get(category, [])


def json_log(event: str, data: dict) -> str:
    """Format de log JSON compact."""
    import json
    import time as _time
    data["event"] = event
    data["ts"] = round(_time.time(), 3)
    return json.dumps(data, ensure_ascii=False)
