"""
JARVIS MAX — System Observer
Surveille atlas_workspace, analyse les logs, détecte les changements.
"""
from __future__ import annotations
import asyncio
import json
import os
import structlog
from datetime import datetime, timezone as _timezone
UTC = _timezone.utc  # Python 3.10 compat: datetime.UTC added in 3.11
from pathlib import Path

log = structlog.get_logger()

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/app/workspace"))
LOGS_DIR  = Path(os.getenv("LOGS_DIR", "/app/logs"))


class SystemObserver:

    def __init__(self, settings=None):
        self.s = settings

    async def snapshot_workspace(self) -> str:
        """Retourne un résumé de l'état actuel du workspace."""
        lines = [f"📁 *Workspace snapshot* — {datetime.now(UTC).strftime('%H:%M:%S UTC')}"]

        for sub in ["projects", "reports", "missions", "patches"]:
            d = WORKSPACE / sub
            if d.exists():
                files = list(d.rglob("*"))
                file_count = sum(1 for f in files if f.is_file())
                total_size = sum(f.stat().st_size for f in files if f.is_file())
                lines.append(f"  {sub}/: {file_count} fichier(s) — {total_size:,} bytes")

        # Derniers fichiers modifiés
        recent = await self._recent_files(5)
        if recent:
            lines.append("\nDerniers fichiers modifiés :")
            for name, ts in recent:
                lines.append(f"  📄 {name} — {ts}")

        return "\n".join(lines)

    async def recent_actions(self, n: int = 10) -> list[dict]:
        """Lit les n dernières entrées du log executor."""
        log_file = LOGS_DIR / "executor.jsonl"
        if not log_file.exists():
            return []
        lines = log_file.read_text().strip().splitlines()
        result = []
        for line in lines[-n:]:
            try:
                result.append(json.loads(line))
            except Exception as _exc:
                log.warning("swallowed_exception", action="watcher_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return result

    async def detect_changes(self, since_minutes: int = 60) -> list[str]:
        """Détecte les fichiers modifiés dans les N dernières minutes."""
        import time
        cutoff  = time.time() - (since_minutes * 60)
        changed = []
        for p in WORKSPACE.rglob("*"):
            if p.is_file() and p.stat().st_mtime > cutoff:
                changed.append(str(p.relative_to(WORKSPACE)))
        return sorted(changed)

    async def analyze_logs(self, n: int = 50) -> str:
        """Analyse les logs d'exécution et retourne un résumé."""
        log_file = LOGS_DIR / "executor.jsonl"
        if not log_file.exists():
            return "Aucun log d'exécution disponible."

        lines = log_file.read_text().strip().splitlines()
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except Exception as _exc:
                log.warning("swallowed_exception", action="watcher_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        if not entries:
            return "Logs vides."

        total     = len(entries)
        successes = sum(1 for e in entries if e.get("success"))
        failures  = total - successes
        actions   = {}
        for e in entries:
            a = e.get("action", "unknown")
            actions[a] = actions.get(a, 0) + 1

        top_actions = sorted(actions.items(), key=lambda x: -x[1])[:5]
        return (
            f"📊 Analyse de {total} actions récentes :\n"
            f"✅ Succès : {successes} | ❌ Échecs : {failures}\n\n"
            f"Top actions :\n"
            + "\n".join(f"  {a}: {c}" for a, c in top_actions)
        )

    async def watch_file(self, path: str, callback, interval: float = 5.0):
        """Surveille un fichier et appelle callback si modifié."""
        p    = Path(path)
        last = p.stat().st_mtime if p.exists() else 0
        while True:
            await asyncio.sleep(interval)
            if p.exists():
                mtime = p.stat().st_mtime
                if mtime != last:
                    last = mtime
                    try:
                        await callback(path, p.read_text("utf-8", errors="replace"))
                    except Exception as e:
                        log.warning("watch_callback_error", err=str(e))

    # ── Internals ─────────────────────────────────────────────

    async def _recent_files(self, n: int) -> list[tuple[str, str]]:
        files = [
            (p, p.stat().st_mtime)
            for p in WORKSPACE.rglob("*")
            if p.is_file() and not p.name.startswith(".")
        ]
        files.sort(key=lambda x: -x[1])
        result = []
        for p, mtime in files[:n]:
            ts = datetime.fromtimestamp(mtime).strftime("%d/%m %H:%M")
            result.append((str(p.relative_to(WORKSPACE)), ts))
        return result
