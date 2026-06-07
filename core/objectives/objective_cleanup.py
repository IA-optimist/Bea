"""
Objective Engine — Archivage, TTL, rotation, anti-saturation disque.
Fail-open total. Tourne sans cron si appelé manuellement.
"""
from __future__ import annotations

import json
import logging
import time
from typing import List

from core.objectives.objective_models import Objective, ObjectiveStatus
from core.objectives.objective_store import ObjectiveStore, get_objective_store

logger = logging.getLogger("bea.objective_cleanup")

# ── Configuration (surchargeables via env) ─────────────────────────────────────

import os

TTL_COMPLETED_DAYS   = int(os.environ.get("OBJECTIVE_TTL_COMPLETED_DAYS", "7"))
TTL_FAILED_DAYS      = int(os.environ.get("OBJECTIVE_TTL_FAILED_DAYS", "3"))
TTL_STALE_DAYS       = int(os.environ.get("OBJECTIVE_TTL_STALE_DAYS", "14"))
MAX_HISTORY_ENTRIES  = int(os.environ.get("OBJECTIVE_MAX_HISTORY", "20"))
MAX_TOTAL_OBJECTIVES = int(os.environ.get("OBJECTIVE_MAX_TOTAL", "200"))


def _jlog(event: str, data: dict) -> None:
    data["event"] = event
    data["ts"] = round(time.time(), 3)
    logger.info(json.dumps(data, ensure_ascii=False))


class ObjectiveCleanup:
    """
    Gère l'archivage automatique, le TTL et la rotation des objectifs.
    Peut être appelé périodiquement ou à la création d'un objectif.
    """

    def __init__(self, store: ObjectiveStore | None = None):
        self._store = store or get_objective_store()

    def run(self) -> dict:
        """
        Lance le cycle de nettoyage complet.
        Retourne un rapport de ce qui a été fait.
        Fail-open : en cas d'erreur, retourne un rapport vide.
        """
        report = {
            "archived_completed": 0,
            "archived_failed":    0,
            "archived_stale":     0,
            "history_trimmed":    0,
            "total_remaining":    0,
            "ts":                 time.time(),
        }
        try:
            all_objs = self._store.get_all(include_archived=False)
            now = time.time()

            for obj in all_objs:
                age_days = (now - obj.updated_at) / 86400.0

                # Archiver les COMPLETED après TTL
                if obj.status == ObjectiveStatus.COMPLETED:
                    if age_days > TTL_COMPLETED_DAYS:
                        self._archive(obj, "ttl_completed")
                        report["archived_completed"] += 1
                        continue

                # Archiver les FAILED après TTL
                elif obj.status == ObjectiveStatus.FAILED:
                    if age_days > TTL_FAILED_DAYS:
                        self._archive(obj, "ttl_failed")
                        report["archived_failed"] += 1
                        continue

                # Archiver les objectifs stales (pas modifiés depuis longtemps)
                elif obj.status not in ObjectiveStatus.TERMINAL:
                    if age_days > TTL_STALE_DAYS:
                        obj.status = ObjectiveStatus.ARCHIVED
                        self._archive(obj, f"ttl_stale ({age_days:.0f}d)")
                        report["archived_stale"] += 1
                        continue

                # Trimmer l'historique
                if len(obj.history) > MAX_HISTORY_ENTRIES:
                    obj.history = obj.history[:5] + obj.history[-15:]
                    self._store.save(obj)
                    report["history_trimmed"] += 1

            # Rotation si trop d'objectifs au total
            self._rotate_if_overflow()

            report["total_remaining"] = self._store.count()
            total_cleaned = (
                report["archived_completed"]
                + report["archived_failed"]
                + report["archived_stale"]
            )
            if total_cleaned > 0:
                _jlog("objective_cleanup_done", {
                    "archived": total_cleaned,
                    "remaining": report["total_remaining"],
                })
        except Exception as e:
            logger.warning(f"[OBJECTIVE_CLEANUP] run error: {e}")

        return report

    def archive_completed(self) -> List[str]:
        """Archive immédiatement tous les COMPLETED."""
        archived_ids = []
        try:
            for obj in self._store.get_all(include_archived=False):
                if obj.status == ObjectiveStatus.COMPLETED:
                    self._archive(obj, "manual_archive_completed")
                    archived_ids.append(obj.objective_id)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_CLEANUP] archive_completed error: {e}")
        return archived_ids

    def _archive(self, obj: Objective, reason: str) -> None:
        """Archive un objectif avec résumé compact."""
        try:
            obj.archived = True
            if obj.status not in ObjectiveStatus.TERMINAL:
                obj.status = ObjectiveStatus.ARCHIVED
            # Résumé compact de l'historique avant archivage
            if len(obj.history) > 5:
                obj.last_execution_summary = (
                    f"Archivé après {len(obj.history)} événements. "
                    f"Dernier: {obj.history[-1].get('event', '')} — "
                    f"{obj.history[-1].get('detail', '')[:80]}"
                )
                obj.history = obj.history[:3] + obj.history[-2:]
            obj.add_history_entry("archived", reason)
            self._store.save(obj)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_CLEANUP] _archive error for {obj.objective_id}: {e}")

    def _rotate_if_overflow(self) -> None:
        """Supprime les objectifs archivés les plus anciens si dépassement."""
        try:
            all_objs = self._store.get_all(include_archived=True)
            if len(all_objs) <= MAX_TOTAL_OBJECTIVES:
                return
            # Trier par updated_at, supprimer les plus anciens archivés
            archived = sorted(
                [o for o in all_objs if o.archived],
                key=lambda o: o.updated_at,
            )
            excess = len(all_objs) - MAX_TOTAL_OBJECTIVES
            for obj in archived[:excess]:
                self._store.delete(obj.objective_id)
            _jlog("objective_rotated", {"deleted": min(excess, len(archived))})
        except Exception as e:
            logger.warning(f"[OBJECTIVE_CLEANUP] rotate error: {e}")


# ── Singleton & entrypoint ─────────────────────────────────────────────────────

_cleanup: ObjectiveCleanup | None = None


def get_cleanup() -> ObjectiveCleanup:
    global _cleanup
    if _cleanup is None:
        _cleanup = ObjectiveCleanup()
    return _cleanup


def run_cleanup() -> dict:
    """Entrypoint direct pour le nettoyage (appelable depuis n'importe où)."""
    try:
        return get_cleanup().run()
    except Exception as e:
        logger.warning(f"[OBJECTIVE_CLEANUP] run_cleanup error: {e}")
        return {}
