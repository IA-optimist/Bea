"""
knowledge_index — Enregistrement et indexation des expériences de Jarvis dans Qdrant.

Collection Qdrant : "jarvis_knowledge" (dim=768, Cosine)
Séparée de "jarvis_solutions" — dédiée aux patterns d'exécution de tâches.

Chaque entrée enregistre :
  - task_type       : catégorie de la tâche (ex: "bug_fix", "deploy")
  - tools_used      : liste de tools utilisés
  - action_sequence : séquence d'actions (liste de strings)
  - success         : bool — résultat final
  - duration_s      : durée d'exécution en secondes
  - errors          : liste d'erreurs rencontrées
  - complexity      : "low" / "medium" / "high"
  - pattern_tag     : tag libre pour regrouper des patterns similaires

Tous les appels Qdrant sont non-bloquants (timeout=3s).
Si Qdrant indisponible → log warning + retour sans exception.
"""
from __future__ import annotations

import logging
import random
import time
from typing import List, Optional

logger = logging.getLogger("jarvis.knowledge.index")

QDRANT_URL = "http://qdrant:6333"
KNOWLEDGE_COLLECTION = "jarvis_knowledge"
_VECTOR_DIM = 768


# ── Helpers internes ──────────────────────────────────────────────────────────

def _pseudo_vector(text: str) -> list:
    """Vecteur pseudo-aléatoire déterministe basé sur hash(text)."""
    seed = hash(text) % (2 ** 32)
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(_VECTOR_DIM)]


def _ensure_knowledge_collection() -> bool:
    """Crée la collection jarvis_knowledge si elle n'existe pas. Timeout=3s."""
    try:
        import requests as _req
        r = _req.get(f"{QDRANT_URL}/collections/{KNOWLEDGE_COLLECTION}", timeout=3)
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            payload = {"vectors": {"size": _VECTOR_DIM, "distance": "Cosine"}}
            cr = _req.put(
                f"{QDRANT_URL}/collections/{KNOWLEDGE_COLLECTION}",
                json=payload, timeout=3,
            )
            return cr.status_code in (200, 201)
        return False
    except Exception as exc:
        logger.warning(f"[KnowledgeIndex] qdrant unavailable: {exc}")
        return False


def _upsert_knowledge_point(point_id: int, vector: list, payload: dict) -> bool:
    """Upsert un point dans jarvis_knowledge. Timeout=3s."""
    try:
        import requests as _req
        body = {"points": [{"id": point_id, "vector": vector, "payload": payload}]}
        r = _req.put(
            f"{QDRANT_URL}/collections/{KNOWLEDGE_COLLECTION}/points",
            json=body, timeout=3,
        )
        return r.status_code in (200, 201)
    except Exception as exc:
        logger.warning(f"[KnowledgeIndex] upsert failed: {exc}")
        return False


# ── API publique ──────────────────────────────────────────────────────────────

def record_task(
    task_type: str,
    tools_used: List[str],
    action_sequence: List[str],
    success: bool,
    duration_s: float = 0.0,
    errors: List[str] = None,
    complexity: str = "medium",
    pattern_tag: str = "",
    goal: str = "",
) -> bool:
    """
    Enregistre une expérience d'exécution de tâche dans Qdrant jarvis_knowledge.

    Args:
        task_type       : type de tâche (ex: "bug_fix", "deploy", "coding_task")
        tools_used      : tools utilisés pendant l'exécution
        action_sequence : séquence d'actions effectuées
        success         : True si la tâche s'est terminée avec succès
        duration_s      : durée totale en secondes
        errors          : erreurs rencontrées (liste de strings)
        complexity      : "low" / "medium" / "high"
        pattern_tag     : tag libre pour regrouper (ex: "docker_deploy", "python_debug")
        goal            : objectif textuel de la tâche (pour la recherche vectorielle)

    Returns:
        True si enregistré, False si Qdrant indisponible ou erreur
    """
    try:
        if not _ensure_knowledge_collection():
            return False

        text_for_vector = f"{task_type} {goal} {' '.join(tools_used)} {pattern_tag}"
        vector = _pseudo_vector(text_for_vector)
        point_id = abs(hash(text_for_vector + str(time.time()))) % (2 ** 31)

        payload = {
            "task_type": task_type,
            "goal": goal[:300],
            "tools_used": list(tools_used or []),
            "action_sequence": [str(a)[:100] for a in (action_sequence or [])[:20]],
            "success": bool(success),
            "duration_s": round(float(duration_s), 3),
            "errors": [str(e)[:200] for e in (errors or [])[:10]],
            "error_count": len(errors or []),
            "complexity": complexity,
            "pattern_tag": pattern_tag[:100],
            "timestamp": time.time(),
        }

        ok = _upsert_knowledge_point(point_id, vector, payload)
        if ok:
            logger.debug(
                f"[KnowledgeIndex] recorded task_type={task_type} success={success} "
                f"duration={duration_s:.1f}s id={point_id}"
            )
        return ok

    except Exception as exc:
        logger.warning(f"[KnowledgeIndex] record_task failed: {exc}")
        return False


def search_similar_tasks(
    goal: str,
    task_type: str = "",
    top_k: int = 3,
) -> list:
    """
    Recherche des tâches similaires dans jarvis_knowledge.

    Args:
        goal      : objectif textuel de la tâche courante
        task_type : filtre optionnel par type de tâche
        top_k     : nombre de résultats maximum

    Returns:
        Liste de dicts avec les champs de payload + score.
        Liste vide si Qdrant indisponible.
    """
    try:
        if not _ensure_knowledge_collection():
            return []

        import requests as _req
        text_for_vector = f"{task_type} {goal}"
        vector = _pseudo_vector(text_for_vector)

        body = {"vector": vector, "limit": top_k, "with_payload": True}
        resp = _req.post(
            f"{QDRANT_URL}/collections/{KNOWLEDGE_COLLECTION}/points/search",
            json=body, timeout=3,
        )
        if resp.status_code != 200:
            logger.warning(f"[KnowledgeIndex] search failed: status={resp.status_code}")
            return []

        results = resp.json().get("result", [])
        tasks = []
        for r in results:
            entry = dict(r.get("payload", {}))
            entry["_score"] = r.get("score", 0.0)
            # Filtre optionnel par task_type
            if task_type and entry.get("task_type") != task_type:
                continue
            tasks.append(entry)

        return tasks

    except Exception as exc:
        logger.warning(f"[KnowledgeIndex] search_similar_tasks failed: {exc}")
        return []


def get_task_stats(task_type: str = "") -> dict:
    """
    Récupère statistiques agrégées depuis jarvis_knowledge via scroll.

    Args:
        task_type : si fourni, filtre par ce type de tâche

    Returns:
        dict avec total, success_rate, avg_duration, common_errors
    """
    try:
        import requests as _req
        if not _ensure_knowledge_collection():
            return {"total": 0, "error": "qdrant_unavailable"}

        total = 0
        successes = 0
        durations = []
        error_counts = []
        offset = None

        for _ in range(20):  # max 20 pages × 100 = 2000 entrées
            body = {"limit": 100, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset

            resp = _req.post(
                f"{QDRANT_URL}/collections/{KNOWLEDGE_COLLECTION}/points/scroll",
                json=body, timeout=3,
            )
            if resp.status_code != 200:
                break

            data = resp.json().get("result", {})
            points = data.get("points", [])
            next_offset = data.get("next_page_offset")

            for p in points:
                pl = p.get("payload", {})
                if task_type and pl.get("task_type") != task_type:
                    continue
                total += 1
                if pl.get("success"):
                    successes += 1
                if pl.get("duration_s") is not None:
                    durations.append(pl["duration_s"])
                error_counts.append(pl.get("error_count", 0))

            if not next_offset or not points:
                break
            offset = next_offset

        return {
            "total": total,
            "success_rate": round(successes / total, 3) if total > 0 else 0.0,
            "avg_duration_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "avg_errors": round(sum(error_counts) / len(error_counts), 2) if error_counts else 0.0,
            "task_type_filter": task_type or "all",
        }

    except Exception as exc:
        logger.warning(f"[KnowledgeIndex] get_task_stats failed: {exc}")
        return {"total": 0, "error": str(exc)}
