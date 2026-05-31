"""
RollbackManager — sauvegarde et restauration automatique de fichiers.
Utilisé avant toute modification de code par tool_executor.

Format backup : {filepath}.bak.{timestamp_ms}
Format diff   : {filepath}.diff.{timestamp_ms}
RAM : < 1KB au repos (pas de buffer en mémoire)
"""
from __future__ import annotations

import difflib
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.rollback")
log = logger  # M3 emitter alias

# Dossier de sauvegarde (relatif au cwd du container)
import os as _os
import tempfile as _tempfile
_BACKUP_DIR = Path(_os.environ.get("JARVIS_ROLLBACK_DIR",
    _os.path.join(_tempfile.gettempdir(), "jarvismax_rollbacks")))
_MAX_BACKUPS_PER_FILE = 5  # évite accumulation infinie


def _ts() -> str:
    return str(int(time.time() * 1000))


def _backup_path(filepath: str, ts: str) -> Path:
    safe = filepath.replace("/", "_").replace("\\", "_").lstrip("_")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return _BACKUP_DIR / f"{safe}.bak.{ts}"


def _diff_path(filepath: str, ts: str) -> Path:
    safe = filepath.replace("/", "_").replace("\\", "_").lstrip("_")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return _BACKUP_DIR / f"{safe}.diff.{ts}"


def _cleanup_old_backups(filepath: str) -> None:
    """Garde uniquement les N backups les plus récents."""
    try:
        safe = filepath.replace("/", "_").replace("\\", "_").lstrip("_")
        backups = sorted(_BACKUP_DIR.glob(f"{safe}.bak.*"))
        for old in backups[:-_MAX_BACKUPS_PER_FILE]:
            old.unlink(missing_ok=True)
    except Exception as _exc:
        log.warning("swallowed_exception", action="rollback_manager_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


class RollbackContext:
    """Context manager : sauvegarde avant, restaure en cas d'exception."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.ts = _ts()
        self.backup: Optional[Path] = None
        self.original_content: Optional[str] = None
        self.success = False

    def __enter__(self) -> "RollbackContext":
        self.backup = backup_file(self.filepath, self.ts)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None and self.backup:
            ok = restore_file(self.filepath, self.backup)
            if ok:
                logger.warning(
                    "rollback_success",
                    extra={"file": self.filepath, "backup": str(self.backup), "error": str(exc_val)},
                )
            else:
                logger.error(
                    "rollback_failed",
                    extra={"file": self.filepath, "backup": str(self.backup), "error": str(exc_val)},
                )
        return False  # ne supprime pas l'exception


def backup_file(filepath: str, ts: Optional[str] = None) -> Optional[Path]:
    """
    Crée une copie de sauvegarde du fichier.
    Retourne le chemin du backup, ou None si fichier inexistant.
    """
    ts = ts or _ts()
    src = Path(filepath)
    if not src.exists():
        logger.debug("backup_skipped_not_found", extra={"file": filepath})
        return None
    try:
        dst = _backup_path(filepath, ts)
        shutil.copy2(str(src), str(dst))
        _cleanup_old_backups(filepath)
        logger.info("backup_created", extra={"file": filepath, "backup": str(dst)})
        return dst
    except Exception as e:
        logger.warning("backup_failed", extra={"file": filepath, "error": str(e)})
        return None


def save_diff(filepath: str, old_content: str, new_content: str, ts: Optional[str] = None) -> Optional[Path]:
    """Enregistre le diff entre ancienne et nouvelle version."""
    ts = ts or _ts()
    try:
        diff = list(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{filepath}.before",
            tofile=f"{filepath}.after",
        ))
        if not diff:
            return None
        dst = _diff_path(filepath, ts)
        dst.write_text("".join(diff), encoding="utf-8")
        logger.info("diff_saved", extra={"file": filepath, "diff": str(dst), "lines": len(diff)})
        return dst
    except Exception as e:
        logger.warning("diff_failed", extra={"file": filepath, "error": str(e)})
        return None


def restore_file(filepath: str, backup_path: Path) -> bool:
    """Restaure un fichier depuis son backup."""
    try:
        if not backup_path.exists():
            logger.error("restore_backup_missing", extra={"backup": str(backup_path)})
            return False
        shutil.copy2(str(backup_path), filepath)
        logger.warning("rollback_success", extra={"file": filepath, "restored_from": str(backup_path)})
        return True
    except Exception as e:
        logger.error("rollback_failed", extra={"file": filepath, "error": str(e)})
        return False


def restore_latest(filepath: str) -> bool:
    """Restaure la version la plus récente disponible."""
    try:
        safe = filepath.replace("/", "_").replace("\\", "_").lstrip("_")
        backups = sorted(_BACKUP_DIR.glob(f"{safe}.bak.*"))
        if not backups:
            logger.error("restore_no_backup_found", extra={"file": filepath})
            return False
        return restore_file(filepath, backups[-1])
    except Exception as e:
        logger.error("restore_latest_failed", extra={"file": filepath, "error": str(e)})
        return False


def list_backups(filepath: str) -> list[str]:
    """Liste les backups disponibles pour un fichier."""
    try:
        safe = filepath.replace("/", "_").replace("\\", "_").lstrip("_")
        return [str(p) for p in sorted(_BACKUP_DIR.glob(f"{safe}.bak.*"))]
    except Exception:
        return []


# Singleton léger
_manager_instance: Optional["RollbackManager"] = None

class RollbackManager:
    """Interface principale."""
    def backup(self, filepath: str) -> Optional[Path]:
        return backup_file(filepath)
    def restore_latest(self, filepath: str) -> bool:
        return restore_latest(filepath)
    def list_backups(self, filepath: str) -> list[str]:
        return list_backups(filepath)
    def context(self, filepath: str) -> RollbackContext:
        return RollbackContext(filepath)

def get_rollback_manager() -> RollbackManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = RollbackManager()
    return _manager_instance
