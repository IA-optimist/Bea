"""
pattern_detector — Détection de patterns efficaces dans les expériences de Jarvis.

Identifie :
  - Tâches similaires aux nouvelles requêtes
  - Séquences d'actions efficaces par type de tâche
  - Tools souvent efficaces ensemble
  - Erreurs fréquentes à éviter
  - Améliorations possibles basées sur l'historique

S'appuie sur :
  - core.knowledge.knowledge_index  (Qdrant jarvis_knowledge)
  - core.knowledge_memory           (KnowledgeMemory locale, Jaccard)

Fail-open : tous imports en try/except.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("jarvis.knowledge.patterns")


# ── Imports fail-open ──────────────────────────────────────────────────────────

try:
    from core.knowledge.knowledge_index import search_similar_tasks, get_task_stats  # noqa: F401
    _INDEX_AVAILABLE = True
except ImportError:
    _INDEX_AVAILABLE = False
    logger.debug("[PatternDetector] knowledge_index unavailable")

try:
    from core.knowledge_memory import get_knowledge_memory
    _KM_AVAILABLE = True
except ImportError:
    _KM_AVAILABLE = False
    logger.debug("[PatternDetector] knowledge_memory unavailable")


# ── Détection de similarité ────────────────────────────────────────────────────

def find_similar_tasks(
    goal: str,
    task_type: str = "",
    top_k: int = 3,
) -> List[dict]:
    """
    Cherche des tâches similaires dans l'historique Qdrant.

    Returns:
        Liste de dicts {task_type, goal, tools_used, action_sequence,
                        success, duration_s, _score}
        Vide si aucun résultat ou Qdrant indisponible.
    """
    if not _INDEX_AVAILABLE:
        return []
    try:
        return search_similar_tasks(goal=goal, task_type=task_type, top_k=top_k)
    except Exception as exc:
        logger.warning(f"[PatternDetector] find_similar_tasks error: {exc}")
        return []


def find_similar_in_memory(
    goal: str,
    mission_type: str,
    threshold: float = 0.4,
) -> Optional[dict]:
    """
    Cherche une solution similaire dans KnowledgeMemory (matching Jaccard local).

    Returns:
        dict avec solution_summary, tools_used, confidence ou None
    """
    if not _KM_AVAILABLE:
        return None
    try:
        km = get_knowledge_memory()
        result = km.find_similar(goal=goal, mission_type=mission_type, threshold=threshold)
        if result is None:
            return None
        entry, score = result
        return {
            "problem_signature": entry.problem_signature,
            "solution_summary": entry.solution_summary,
            "tools_used": entry.tools_used,
            "agents_used": entry.agents_used,
            "confidence": entry.confidence,
            "usage_count": entry.usage_count,
            "similarity_score": score,
            "source": "knowledge_memory",
        }
    except Exception as exc:
        logger.warning(f"[PatternDetector] find_similar_in_memory error: {exc}")
        return None


# ── Séquences efficaces ────────────────────────────────────────────────────────

def get_effective_sequences(
    task_type: str,
    min_success_rate: float = 0.6,
    top_k: int = 5,
) -> List[dict]:
    """
    Identifie les séquences d'actions ayant le meilleur taux de réussite
    pour un type de tâche donné.

    Returns:
        Liste de dicts {sequence_hash, action_sequence, success_rate,
                        avg_duration_s, occurrences}
        Triée par success_rate décroissant.
    """
    if not _INDEX_AVAILABLE:
        return []
    try:
        similar = search_similar_tasks(goal=task_type, task_type=task_type, top_k=50)
        if not similar:
            return []

        # Grouper par séquence (hash de la liste d'actions)
        sequences: Dict[str, dict] = {}
        for task in similar:
            seq = task.get("action_sequence", [])
            seq_key = "|".join(seq[:5])  # max 5 premières actions pour signature
            if not seq_key:
                continue
            if seq_key not in sequences:
                sequences[seq_key] = {
                    "sequence_hash": seq_key[:80],
                    "action_sequence": seq,
                    "total": 0,
                    "successes": 0,
                    "durations": [],
                }
            sequences[seq_key]["total"] += 1
            if task.get("success"):
                sequences[seq_key]["successes"] += 1
            if task.get("duration_s"):
                sequences[seq_key]["durations"].append(task["duration_s"])

        results = []
        for data in sequences.values():
            total = data["total"]
            if total == 0:
                continue
            success_rate = data["successes"] / total
            if success_rate < min_success_rate:
                continue
            durations = data["durations"]
            results.append({
                "sequence_hash": data["sequence_hash"],
                "action_sequence": data["action_sequence"],
                "success_rate": round(success_rate, 3),
                "avg_duration_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
                "occurrences": total,
            })

        return sorted(results, key=lambda x: x["success_rate"], reverse=True)[:top_k]

    except Exception as exc:
        logger.warning(f"[PatternDetector] get_effective_sequences error: {exc}")
        return []


# ── Tools efficaces ────────────────────────────────────────────────────────────

def get_effective_tools(
    task_type: str = "",
    top_k: int = 5,
) -> List[dict]:
    """
    Identifie les tools les plus souvent utilisés dans les tâches réussies.

    Returns:
        Liste de dicts {tool_name, success_count, total_count, success_rate}
        Triée par success_rate × occurrences.
    """
    if not _INDEX_AVAILABLE:
        return []
    try:
        goal = task_type or "general"
        tasks = search_similar_tasks(goal=goal, task_type=task_type, top_k=100)
        if not tasks:
            return []

        tool_stats: Dict[str, dict] = defaultdict(lambda: {"success": 0, "total": 0})
        for task in tasks:
            tools = task.get("tools_used", [])
            is_success = task.get("success", False)
            for tool in tools:
                tool_stats[tool]["total"] += 1
                if is_success:
                    tool_stats[tool]["success"] += 1

        results = []
        for tool, stats in tool_stats.items():
            total = stats["total"]
            if total == 0:
                continue
            success_rate = stats["success"] / total
            results.append({
                "tool_name": tool,
                "success_count": stats["success"],
                "total_count": total,
                "success_rate": round(success_rate, 3),
                # Score composite : succès pondéré par occurrences
                "_rank_score": success_rate * min(total / 5, 1.0),
            })

        sorted_results = sorted(results, key=lambda x: x["_rank_score"], reverse=True)[:top_k]
        # Nettoyer le champ interne avant de retourner
        for r in sorted_results:
            r.pop("_rank_score", None)
        return sorted_results

    except Exception as exc:
        logger.warning(f"[PatternDetector] get_effective_tools error: {exc}")
        return []


def get_synergistic_tools(task_type: str = "", top_k: int = 3) -> List[Tuple[str, str, int]]:
    """
    Identifie les paires de tools souvent utilisées ensemble avec succès.

    Returns:
        Liste de (tool_a, tool_b, co_occurrence_count)
    """
    if not _INDEX_AVAILABLE:
        return []
    try:
        tasks = search_similar_tasks(goal=task_type or "general", task_type=task_type, top_k=100)
        pair_counts: Counter = Counter()
        for task in tasks:
            if not task.get("success"):
                continue
            tools = sorted(set(task.get("tools_used", [])))
            for i in range(len(tools)):
                for j in range(i + 1, len(tools)):
                    pair_counts[(tools[i], tools[j])] += 1

        return [(a, b, count) for (a, b), count in pair_counts.most_common(top_k)]

    except Exception as exc:
        logger.warning(f"[PatternDetector] get_synergistic_tools error: {exc}")
        return []


# ── Erreurs fréquentes ─────────────────────────────────────────────────────────

def get_frequent_errors(
    task_type: str = "",
    top_k: int = 5,
) -> List[dict]:
    """
    Identifie les erreurs les plus fréquentes pour un type de tâche.

    Returns:
        Liste de dicts {error_snippet, count, task_type}
        Triée par fréquence décroissante.
    """
    if not _INDEX_AVAILABLE:
        return []
    try:
        tasks = search_similar_tasks(goal=task_type or "general", task_type=task_type, top_k=100)
        error_counter: Counter = Counter()
        for task in tasks:
            for err in task.get("errors", []):
                # Normalise en truncant l'erreur à 60 chars
                snippet = str(err)[:60].strip()
                if snippet:
                    error_counter[snippet] += 1

        return [
            {"error_snippet": err, "count": count, "task_type": task_type or "all"}
            for err, count in error_counter.most_common(top_k)
        ]

    except Exception as exc:
        logger.warning(f"[PatternDetector] get_frequent_errors error: {exc}")
        return []


# ── Point d'entrée principal ───────────────────────────────────────────────────

def detect_patterns(
    goal: str,
    mission_type: str = "",
) -> dict:
    """
    Analyse complète pour une nouvelle tâche.
    Combine recherche Qdrant + KnowledgeMemory locale.

    Returns:
        {
          "similar_tasks"      : [...],   # tâches Qdrant similaires
          "memory_match"       : {...},   # match local KnowledgeMemory (ou None)
          "effective_tools"    : [...],   # tools recommandés
          "frequent_errors"    : [...],   # erreurs à éviter
          "effective_sequences": [...],   # séquences d'actions efficaces
          "has_prior_knowledge": bool,
        }
    """
    try:
        similar_tasks = find_similar_tasks(goal=goal, task_type=mission_type, top_k=3)
        memory_match = find_similar_in_memory(goal=goal, mission_type=mission_type)
        effective_tools = get_effective_tools(task_type=mission_type, top_k=5)
        frequent_errors = get_frequent_errors(task_type=mission_type, top_k=3)
        effective_sequences = get_effective_sequences(task_type=mission_type, top_k=3)

        has_prior = bool(similar_tasks or memory_match)

        return {
            "similar_tasks": similar_tasks,
            "memory_match": memory_match,
            "effective_tools": effective_tools,
            "frequent_errors": frequent_errors,
            "effective_sequences": effective_sequences,
            "has_prior_knowledge": has_prior,
        }

    except Exception as exc:
        logger.warning(f"[PatternDetector] detect_patterns error: {exc}")
        return {
            "similar_tasks": [],
            "memory_match": None,
            "effective_tools": [],
            "frequent_errors": [],
            "effective_sequences": [],
            "has_prior_knowledge": False,
        }
