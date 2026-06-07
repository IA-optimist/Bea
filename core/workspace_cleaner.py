"""
BEA MAX — Workspace Cleaner V1
Nettoyage périodique des ressources en mémoire et sur disque.
Appelé au démarrage de l'API (api/main.py startup).
"""
from __future__ import annotations

import structlog

log = structlog.get_logger()


def run_cleanup() -> dict:
    """
    Nettoie :
    - VaultMemory : expiration des layers par TTL
    - MissionStateStore : purge des logs anciens (>1h)

    Retourne un dict de métriques { "vault_expired": int, "mission_logs_removed": int }.
    """
    metrics: dict = {}

    # 1. VaultMemory — cleanup_expired() sur les layers
    try:
        from memory.vault_memory import get_vault_memory
        vm = get_vault_memory()
        removed = vm.cleanup_expired()
        metrics["vault_expired"] = removed
        log.info("workspace_cleaner_vault", removed=removed)
    except Exception as exc:
        log.warning("workspace_cleaner_vault_failed", err=str(exc)[:80])
        metrics["vault_expired"] = 0

    # 2. MissionStateStore — purge des logs anciens
    try:
        from api.mission_store import MissionStateStore
        store = MissionStateStore.get()
        removed_logs = store.clear_old_logs(older_than_s=3600)
        metrics["mission_logs_removed"] = removed_logs
        log.info("workspace_cleaner_store", removed=removed_logs)
    except Exception as exc:
        log.warning("workspace_cleaner_store_failed", err=str(exc)[:80])
        metrics["mission_logs_removed"] = 0

    log.info("workspace_cleaner_done", **metrics)
    return metrics
