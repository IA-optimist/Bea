"""
Scheduler du Night Worker — tourne en arrière-plan.
Toutes les 6 heures :
  1. Lit les actions FAILED de la journée depuis SQLite
  2. Les envoie dans learning_loop() comme échecs
  3. Consolide le vault (prune_expired + boost les succès)
  4. Génère un rapport JSON dans workspace/night_reports/
  5. Remet à zéro les compteurs d'erreurs

Lance avec : python -m night_worker.scheduler
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger()

INTERVAL_HOURS = 6
_REPORTS_DIR = Path("workspace/night_reports")


class NightScheduler:
    """Scheduler du Night Worker."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._last_run: datetime | None = None
        self._last_report: dict | None = None

    # ── API publique ──────────────────────────────────────────────────────────

    def start_background(self) -> threading.Thread:
        """Lance le scheduler dans un thread daemon."""
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="bea-night-scheduler",
        )
        self._thread.start()
        log.info("night_scheduler_started", interval_hours=INTERVAL_HOURS)
        return self._thread

    def stop(self) -> None:
        """Arrête le scheduler."""
        self._running = False

    def run_now(self) -> dict:
        """Force un cycle immédiat, retourne le rapport."""
        return self._run_cycle()

    def get_last_report(self) -> dict | None:
        """Retourne le dernier rapport."""
        if self._last_report:
            return self._last_report
        # Try to load from disk
        try:
            reports = sorted(_REPORTS_DIR.glob("night_report_*.json"), reverse=True)
            if reports:
                return json.loads(reports[0].read_text("utf-8"))
        except Exception as _exc:
            log.warning("swallowed_exception", action="scheduler_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return None

    def get_next_run(self) -> str | None:
        """Retourne l'heure du prochain cycle."""
        if self._last_run is None:
            return None
        next_ts = self._last_run.timestamp() + INTERVAL_HOURS * 3600
        return datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Boucle principale du scheduler."""
        interval_sec = INTERVAL_HOURS * 3600
        while self._running:
            try:
                self._run_cycle()
            except Exception as exc:
                log.error("night_scheduler_cycle_error", err=str(exc))
            # Sleep in small increments to allow clean shutdown
            for _ in range(interval_sec):
                if not self._running:
                    break
                time.sleep(1)

    def _run_cycle(self) -> dict:
        """Exécute un cycle complet du night worker."""
        start_ts = time.time()
        now = datetime.now(tz=timezone.utc)
        report: dict = {
            "ts": now.isoformat(),
            "failed_actions_processed": 0,
            "learning_reports": [],
            "vault_pruned": 0,
            "errors": [],
        }

        # 1. Load failed actions from SQLite
        failed_actions = self._load_failed_actions()
        report["failed_actions_count"] = len(failed_actions)

        # 2. Send to learning_loop as failures
        learning_count = 0
        for action in failed_actions:
            try:
                from core.learning.learning_loop import learning_loop
                lr = learning_loop(
                    agent_name="night-worker",
                    output=f"FAILED action: {action.get('description', '')} — {action.get('result', '')}",
                    context=f"target:{action.get('target', '')}",
                    success=False,
                )
                learning_count += getattr(lr, 'stored', 0)  # defensive
                report["failed_actions_processed"] += 1
            except Exception as exc:
                report["errors"].append(f"learning_loop: {exc}")

        report["learning_stored"] = learning_count

        # 3. Vault consolidation (prune_expired + boost successes)
        pruned = 0
        try:
            from memory.vault_memory import get_vault_memory
            vm = get_vault_memory()
            pruned = vm.prune_expired()
            # Boost entries used recently
            self._boost_successful_vault_entries(vm)
        except Exception as exc:
            report["errors"].append(f"vault_consolidation: {exc}")
        report["vault_pruned"] = pruned

        # 4. Generate JSON report
        report["duration_s"] = round(time.time() - start_ts, 2)
        self._save_report(report)
        self._last_run = now
        self._last_report = report

        log.info(
            "night_cycle_complete",
            ts=now.isoformat(),
            failed_processed=report["failed_actions_processed"],
            vault_pruned=pruned,
        )
        return report

    def _load_failed_actions(self) -> list[dict]:
        """Charge les actions FAILED de la journée depuis SQLite."""
        try:
            from core import db as _db_mod
            # Actions failed in last 24h
            since = time.time() - 86400
            rows = _db_mod.fetchall(
                "SELECT * FROM actions WHERE status='FAILED' AND created_at >= ?",
                (since,)
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            log.warning("night_load_failed_actions", err=str(exc))
            return []

    def _boost_successful_vault_entries(self, vm) -> None:
        """Booste les entrées vault très utilisées (succès)."""
        try:
            for entry in list(vm._entries.values()):
                if entry.usage_count > 5 and entry.is_active():
                    entry.boost(success=True)
        except Exception as _exc:
            log.warning("swallowed_exception", action="scheduler_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _save_report(self, report: dict) -> None:
        """Sauvegarde le rapport JSON dans workspace/night_reports/."""
        try:
            _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            ts_str = report.get("ts", datetime.now(tz=timezone.utc).isoformat()).replace(":", "-").replace("+", "")[:19]
            path = _REPORTS_DIR / f"night_report_{ts_str}.json"
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
            log.info("night_report_saved", path=str(path))
        except Exception as exc:
            log.warning("night_report_save_failed", err=str(exc))


# ── Singleton ─────────────────────────────────────────────────────────────────

_scheduler_instance: NightScheduler | None = None


def get_night_scheduler() -> NightScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = NightScheduler()
    return _scheduler_instance


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scheduler = NightScheduler()
    print("[NightScheduler] Démarrage...")
    scheduler.start_background()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.stop()
        print("[NightScheduler] Arrêté.")
