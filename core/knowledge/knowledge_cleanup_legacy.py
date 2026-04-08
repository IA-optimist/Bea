"""
knowledge_cleanup — Maintenance de la collection jarvis_knowledge dans Qdrant.

Opérations :
  merge_similar_patterns   — fusionne patterns avec overlap Jaccard élevé
  remove_stale_patterns    — supprime patterns anciens ou peu performants
  summarize_experiences    — garde seulement les N meilleures entrées

S'appuie sur :
  - Qdrant jarvis_knowledge (scroll + delete)
  - core.knowledge_memory   (deduplicate local)

Fail-open : aucun appel ne peut planter le système.
Timeouts : max 3s par requête Qdrant.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("jarvis.knowledge.cleanup")

QDRANT_URL = "http://qdrant:6333"
KNOWLEDGE_COLLECTION = "jarvis_knowledge"


# ── Imports fail-open ──────────────────────────────────────────────────────────

try:
    from core.knowledge.knowledge_index import _ensure_knowledge_collection
    _INDEX_AVAILABLE = True
except ImportError:
    _INDEX_AVAILABLE = False
    logger.debug("[KnowledgeCleanup] knowledge_index unavailable")

try:
    from core.knowledge_memory import get_knowledge_memory
    _KM_AVAILABLE = True
except ImportError:
    _KM_AVAILABLE = False
    logger.debug("[KnowledgeCleanup] knowledge_memory unavailable")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _scroll_all_points(collection: str = KNOWLEDGE_COLLECTION) -> List[dict]:
    """
    Récupère tous les points de la collection via scroll paginé.
    Retourne [] si Qdrant indisponible.
    """
    try:
        import requests as _req
        points = []
        offset = None

        for _ in range(50):  # max 5000 entrées (50 × 100)
            body = {"limit": 100, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset

            resp = _req.post(
                f"{QDRANT_URL}/collections/{collection}/points/scroll",
                json=body, timeout=3,
            )
            if resp.status_code != 200:
                logger.warning(f"[KnowledgeCleanup] scroll error: status={resp.status_code}")
                break

            data = resp.json().get("result", {})
            batch = data.get("points", [])
            points.extend(batch)
            next_offset = data.get("next_page_offset")

            if not next_offset or not batch:
                break
            offset = next_offset

        return points

    except Exception as exc:
        logger.warning(f"[KnowledgeCleanup] _scroll_all_points error: {exc}")
        return []


def _delete_points(point_ids: List[int], collection: str = KNOWLEDGE_COLLECTION) -> int:
    """
    Supprime les points par IDs. Retourne le nombre supprimés.
    Timeout=3s.
    """
    if not point_ids:
        return 0
    try:
        import requests as _req
        resp = _req.post(
            f"{QDRANT_URL}/collections/{collection}/points/delete",
            json={"points": point_ids},
            timeout=3,
        )
        if resp.status_code in (200, 201):
            return len(point_ids)
        return 0
    except Exception as exc:
        logger.warning(f"[KnowledgeCleanup] _delete_points error: {exc}")
        return 0


def _jaccard_overlap(seq_a: List[str], seq_b: List[str]) -> float:
    """Jaccard sur deux listes de strings (outils ou actions)."""
    set_a = set(seq_a)
    set_b = set(seq_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


# ── Merge patterns similaires ──────────────────────────────────────────────────

def merge_similar_patterns(
    similarity_threshold: float = 0.8,
    collection: str = KNOWLEDGE_COLLECTION,
) -> dict:
    """
    Fusionne les entrées avec overlap Jaccard élevé sur tools_used.

    Stratégie :
      - Pour chaque paire avec Jaccard(tools_used) ≥ threshold :
        - Garder le point avec le meilleur success_rate ou le plus récent
        - Supprimer le doublon

    Returns:
        {merged_count, examined_count, error}
    """
    if not _INDEX_AVAILABLE:
        return {"merged_count": 0, "examined_count": 0, "error": "index_unavailable"}
    try:
        if not _ensure_knowledge_collection():
            return {"merged_count": 0, "examined_count": 0, "error": "qdrant_unavailable"}

        points = _scroll_all_points(collection)
        if not points:
            return {"merged_count": 0, "examined_count": 0}

        examined = len(points)
        to_delete = set()

        # Comparaison O(n²) — acceptable si < 500 points
        for i in range(len(points)):
            if points[i]["id"] in to_delete:
                continue
            pl_i = points[i].get("payload", {})
            tools_i = pl_i.get("tools_used", [])
            tt_i = pl_i.get("task_type", "")
            ts_i = pl_i.get("timestamp", 0)
            success_i = int(pl_i.get("success", False))

            for j in range(i + 1, len(points)):
                if points[j]["id"] in to_delete:
                    continue
                pl_j = points[j].get("payload", {})
                tools_j = pl_j.get("tools_used", [])
                tt_j = pl_j.get("task_type", "")

                # Même type de tâche requis
                if tt_i != tt_j:
                    continue

                overlap = _jaccard_overlap(tools_i, tools_j)
                if overlap >= similarity_threshold:
                    ts_j = pl_j.get("timestamp", 0)
                    success_j = int(pl_j.get("success", False))
                    # Garder le plus réussi, ou le plus récent en cas d'égalité
                    if success_i > success_j or (success_i == success_j and ts_i >= ts_j):
                        to_delete.add(points[j]["id"])
                    else:
                        to_delete.add(points[i]["id"])
                        break  # points[i] supprimé — passer au suivant

        merged_count = _delete_points(list(to_delete), collection)
        logger.info(
            f"[KnowledgeCleanup] merge_similar: examined={examined} merged={merged_count}"
        )
        return {"merged_count": merged_count, "examined_count": examined}

    except Exception as exc:
        logger.warning(f"[KnowledgeCleanup] merge_similar_patterns error: {exc}")
        return {"merged_count": 0, "examined_count": 0, "error": str(exc)}


# ── Suppression patterns obsolètes ────────────────────────────────────────────

def remove_stale_patterns(
    min_success_rate: float = 0.1,
    max_age_days: float = 30.0,
    collection: str = KNOWLEDGE_COLLECTION,
) -> dict:
    """
    Supprime les entrées obsolètes ou peu performantes.

    Critères de suppression :
      - Âge > max_age_days ET success=False
      - Ou (task_type connu ET error_count élevé ET success=False)

    Note : les entrées réussies sont conservées même si anciennes.

    Returns:
        {removed_count, examined_count, error}
    """
    if not _INDEX_AVAILABLE:
        return {"removed_count": 0, "examined_count": 0, "error": "index_unavailable"}
    try:
        if not _ensure_knowledge_collection():
            return {"removed_count": 0, "examined_count": 0, "error": "qdrant_unavailable"}

        points = _scroll_all_points(collection)
        if not points:
            return {"removed_count": 0, "examined_count": 0}

        now = time.time()
        max_age_s = max_age_days * 86400
        to_delete = []

        for point in points:
            pl = point.get("payload", {})
            success = pl.get("success", False)
            timestamp = pl.get("timestamp", now)
            age_s = now - timestamp
            error_count = pl.get("error_count", 0)

            # Ne jamais supprimer les entrées réussies
            if success:
                continue

            # Supprimer si vieux ET échec
            if age_s > max_age_s:
                to_delete.append(point["id"])
                continue

            # Supprimer si beaucoup d'erreurs ET pas de succès
            if error_count >= 5:
                to_delete.append(point["id"])

        removed_count = _delete_points(to_delete, collection)
        logger.info(
            f"[KnowledgeCleanup] remove_stale: examined={len(points)} removed={removed_count}"
        )
        return {"removed_count": removed_count, "examined_count": len(points)}

    except Exception as exc:
        logger.warning(f"[KnowledgeCleanup] remove_stale_patterns error: {exc}")
        return {"removed_count": 0, "examined_count": 0, "error": str(exc)}


# ── Résumé (conserver les N meilleures) ───────────────────────────────────────

def summarize_experiences(
    max_entries: int = 100,
    collection: str = KNOWLEDGE_COLLECTION,
) -> dict:
    """
    Garde seulement les max_entries meilleures entrées dans la collection.

    Critère de tri : success DESC, timestamp DESC.
    Supprime les entrées en excès avec les pires scores.

    Returns:
        {kept_count, removed_count, examined_count, error}
    """
    if not _INDEX_AVAILABLE:
        return {"kept_count": 0, "removed_count": 0, "examined_count": 0, "error": "index_unavailable"}
    try:
        if not _ensure_knowledge_collection():
            return {"kept_count": 0, "removed_count": 0, "examined_count": 0, "error": "qdrant_unavailable"}

        points = _scroll_all_points(collection)
        examined = len(points)

        if examined <= max_entries:
            return {"kept_count": examined, "removed_count": 0, "examined_count": examined}

        # Trier : succès d'abord, puis timestamp décroissant
        def _sort_key(p):
            pl = p.get("payload", {})
            success_score = 1 if pl.get("success") else 0
            return (success_score, pl.get("timestamp", 0))

        sorted_points = sorted(points, key=_sort_key, reverse=True)
        to_keep = sorted_points[:max_entries]
        to_remove = sorted_points[max_entries:]
        ids_to_remove = [p["id"] for p in to_remove]

        removed_count = _delete_points(ids_to_remove, collection)
        logger.info(
            f"[KnowledgeCleanup] summarize: examined={examined} "
            f"kept={max_entries} removed={removed_count}"
        )
        return {
            "kept_count": max_entries,
            "removed_count": removed_count,
            "examined_count": examined,
        }

    except Exception as exc:
        logger.warning(f"[KnowledgeCleanup] summarize_experiences error: {exc}")
        return {"kept_count": 0, "removed_count": 0, "examined_count": 0, "error": str(exc)}


# ── Cleanup local KnowledgeMemory ─────────────────────────────────────────────

def cleanup_local_memory() -> dict:
    """
    Nettoie la KnowledgeMemory locale (Jaccard-based).
    Retire les entrées avec confidence < 0.3 et usage_count == 1.

    Returns:
        {removed_count, total_before, total_after}
    """
    if not _KM_AVAILABLE:
        return {"removed_count": 0, "total_before": 0, "total_after": 0, "error": "km_unavailable"}
    try:
        km = get_knowledge_memory()
        total_before = len(km._entries)

        to_remove = [
            sig for sig, entry in km._entries.items()
            if entry.confidence < 0.3 and entry.usage_count <= 1
        ]
        for sig in to_remove:
            del km._entries[sig]

        if to_remove:
            km._persist()

        total_after = len(km._entries)
        removed = total_before - total_after
        logger.info(
            f"[KnowledgeCleanup] local_memory: before={total_before} "
            f"removed={removed} after={total_after}"
        )
        return {
            "removed_count": removed,
            "total_before": total_before,
            "total_after": total_after,
        }

    except Exception as exc:
        logger.warning(f"[KnowledgeCleanup] cleanup_local_memory error: {exc}")
        return {"removed_count": 0, "total_before": 0, "total_after": 0, "error": str(exc)}


# ── Run complet ────────────────────────────────────────────────────────────────

def run_full_cleanup(
    similarity_threshold: float = 0.8,
    max_age_days: float = 30.0,
    max_entries: int = 100,
) -> dict:
    """
    Lance le cycle complet de nettoyage :
      1. Supprime patterns obsolètes
      2. Fusionne patterns similaires
      3. Résume à max_entries si trop grand
      4. Nettoie la mémoire locale

    Returns:
        Rapport consolidé de toutes les opérations.
    """
    stale = remove_stale_patterns(max_age_days=max_age_days)
    merge = merge_similar_patterns(similarity_threshold=similarity_threshold)
    summarize = summarize_experiences(max_entries=max_entries)
    local = cleanup_local_memory()

    report = {
        "stale_removed": stale.get("removed_count", 0),
        "merged": merge.get("merged_count", 0),
        "summarize_removed": summarize.get("removed_count", 0),
        "local_memory_removed": local.get("removed_count", 0),
        "total_removed": (
            stale.get("removed_count", 0)
            + merge.get("merged_count", 0)
            + summarize.get("removed_count", 0)
            + local.get("removed_count", 0)
        ),
        "details": {
            "stale": stale,
            "merge": merge,
            "summarize": summarize,
            "local_memory": local,
        },
    }
    logger.info(f"[KnowledgeCleanup] full_cleanup done: {report['total_removed']} total removed")
    return report
