"""
DEPRECATED: Use core.actions.action_model.CanonicalAction for new code.

JARVIS MAX — Action Queue v1
File d'attente centrale des actions de Jarvis.

Chaque action est un ordre concret que Jarvis veut exécuter.
L'utilisateur approuve, rejette ou laisse Jarvis décider selon le mode.

Cycle de vie :
  PENDING → APPROVED → EXECUTED
  PENDING → REJECTED
  PENDING → APPROVED → FAILED  (erreur à l'exécution)

Persistance : SQLite (workspace/jarvismax.db) avec fallback JSON
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()

_STORAGE = Path("workspace/action_queue.json")
_MAX_HISTORY = 500   # entrées max conservées


# ── Enums ─────────────────────────────────────────────────────────────────────

class ActionRisk(str, Enum):
    LOW      = "LOW"       # sans danger, réversible
    MEDIUM   = "MEDIUM"    # impact limité, rollback possible
    HIGH     = "HIGH"      # impact significatif
    CRITICAL = "CRITICAL"  # irréversible ou risque majeur


class ActionStatus(str, Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED   = "FAILED"


# ── Modèle d'action ───────────────────────────────────────────────────────────

@dataclass
class Action:
    """
    Une action concrète que Jarvis veut exécuter.

    Champs obligatoires : description, risk, target, impact
    """
    description: str       # "Créer fichier workspace/report.md"
    risk:        str       # ActionRisk
    target:      str       # fichier, URL, service, concept
    impact:      str       # "Crée un nouveau fichier de rapport"

    # Optionnels
    diff:        str = ""  # diff code si applicable
    rollback:    str = ""  # comment annuler
    mission_id:  str = ""  # mission parente

    # Auto-générés
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    status:      str   = ActionStatus.PENDING
    created_at:  float = field(default_factory=time.time)
    approved_at: float|None = None
    rejected_at: float|None = None
    executed_at: float|None = None
    result:      str   = ""   # résultat d'exécution
    note:        str   = ""   # note humaine (raison de rejet, etc.)

    def __post_init__(self):
        r = str(self.risk).upper()
        self.risk = r if r in {e.value for e in ActionRisk} else ActionRisk.MEDIUM
        s = str(self.status).upper()
        self.status = s if s in {e.value for e in ActionStatus} else ActionStatus.PENDING

    # ── Properties ────────────────────────────────────────────────────────────

    def is_pending(self)  -> bool: return self.status == ActionStatus.PENDING
    def is_approved(self) -> bool: return self.status == ActionStatus.APPROVED
    def is_done(self)     -> bool: return self.status in {ActionStatus.EXECUTED, ActionStatus.FAILED, ActionStatus.REJECTED}
    def is_critical(self) -> bool: return self.risk == ActionRisk.CRITICAL
    def is_high_risk(self)-> bool: return self.risk in {ActionRisk.HIGH, ActionRisk.CRITICAL}
    def has_rollback(self)-> bool: return bool(self.rollback)

    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    def to_summary(self) -> str:
        """Ligne de résumé lisible."""
        risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(self.risk, "⚪")
        status_icon = {"PENDING": "⏳", "APPROVED": "✅", "REJECTED": "❌", "EXECUTED": "🚀", "FAILED": "💥"}.get(self.status, "?")
        return f"{status_icon} [{self.id}] {risk_icon}{self.risk} — {self.description[:60]}"

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ── File d'attente ────────────────────────────────────────────────────────────

class ActionQueue:
    """
    File d'attente centrale des actions.

    Usage :
        q = ActionQueue()
        a = q.enqueue("Créer rapport", risk="LOW", target="workspace/report.md",
                       impact="Nouveau fichier créé")
        q.approve(a.id)
        q.mark_executed(a.id, result="Fichier créé avec succès")
    """

    def __init__(self, storage: Path|str = _STORAGE):
        self._path    = Path(storage)
        self._actions: dict[str, Action] = {}
        self._use_sqlite: bool = False
        self._load()

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def enqueue(
        self,
        description: str,
        risk:        str,
        target:      str,
        impact:      str,
        diff:        str = "",
        rollback:    str = "",
        mission_id:  str = "",
    ) -> Action:
        """Ajoute une nouvelle action en attente."""
        action = Action(
            description=description,
            risk=risk,
            target=target,
            impact=impact,
            diff=diff,
            rollback=rollback,
            mission_id=mission_id,
        )
        self._actions[action.id] = action
        self._rotate()
        if self._use_sqlite:
            self._sqlite_insert(action)
        else:
            self._save()
        log.info("action_queued", id=action.id, risk=action.risk,
                 description=description[:50])
        return action

    def approve(self, action_id: str, note: str = "") -> Action|None:
        """Approuve une action PENDING."""
        a = self._actions.get(action_id)
        if not a or not a.is_pending():
            return None
        a.status      = ActionStatus.APPROVED
        a.approved_at = time.time()
        a.note        = note
        if self._use_sqlite:
            self._sqlite_update_status(a)
        else:
            self._save()
        log.info("action_approved", id=action_id)
        return a

    def reject(self, action_id: str, note: str = "") -> Action|None:
        """Rejette une action PENDING ou APPROVED."""
        a = self._actions.get(action_id)
        if not a or a.is_done():
            return None
        a.status      = ActionStatus.REJECTED
        a.rejected_at = time.time()
        a.note        = note
        if self._use_sqlite:
            self._sqlite_update_status(a)
        else:
            self._save()
        log.info("action_rejected", id=action_id, reason=note[:50])
        return a

    def mark_executed(self, action_id: str, result: str = "") -> Action|None:
        """Marque une action APPROVED comme exécutée."""
        a = self._actions.get(action_id)
        if not a or not a.is_approved():
            return None
        a.status      = ActionStatus.EXECUTED
        a.executed_at = time.time()
        a.result      = result
        if self._use_sqlite:
            self._sqlite_update_status(a)
        else:
            self._save()
        log.info("action_executed", id=action_id)
        return a

    def mark_failed(self, action_id: str, result: str = "") -> Action|None:
        """Marque une action APPROVED comme échouée."""
        a = self._actions.get(action_id)
        if not a or not a.is_approved():
            return None
        a.status      = ActionStatus.FAILED
        a.executed_at = time.time()
        a.result      = result
        if self._use_sqlite:
            self._sqlite_update_status(a)
        else:
            self._save()
        log.warning("action_failed", id=action_id, result=result[:100])
        return a

    # ── Requêtes ──────────────────────────────────────────────────────────────

    def get(self, action_id: str) -> Action|None:
        return self._actions.get(action_id)

    def pending(self) -> list[Action]:
        return self._by_status(ActionStatus.PENDING)

    def approved(self) -> list[Action]:
        return self._by_status(ActionStatus.APPROVED)

    def executed(self) -> list[Action]:
        return self._by_status(ActionStatus.EXECUTED)

    def rejected(self) -> list[Action]:
        return self._by_status(ActionStatus.REJECTED)

    def all(self, limit: int = 50) -> list[Action]:
        return sorted(self._actions.values(),
                      key=lambda a: a.created_at, reverse=True)[:limit]

    def for_mission(self, mission_id: str) -> list[Action]:
        return [a for a in self._actions.values()
                if a.mission_id == mission_id]

    def stats(self) -> dict:
        all_a = list(self._actions.values())
        by_status: dict[str, int] = {}
        for a in all_a:
            by_status[a.status] = by_status.get(a.status, 0) + 1
        return {
            "total":   len(all_a),
            "pending": len(self.pending()),
            "approved":len(self.approved()),
            "executed":len(self.executed()),
            "rejected":len(self.rejected()),
            "by_status": by_status,
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _by_status(self, status: str) -> list[Action]:
        return sorted(
            [a for a in self._actions.values() if a.status == status],
            key=lambda a: a.created_at,
        )

    def _rotate(self) -> None:
        if len(self._actions) > _MAX_HISTORY:
            done = sorted(
                [a for a in self._actions.values() if a.is_done()],
                key=lambda a: a.created_at,
            )
            for a in done[:20]:
                del self._actions[a.id]

    def _load(self) -> None:
        # Try SQLite first
        try:
            from core import db as _db_mod
            db = _db_mod.get_db()
            if db is not None:
                rows = _db_mod.fetchall(
                    "SELECT * FROM actions ORDER BY created_at DESC LIMIT 500"
                )
                for row in rows:
                    try:
                        a = Action(
                            description=row["description"] or "",
                            risk=row["risk"] or "MEDIUM",
                            target=row["target"] or "",
                            impact=row["impact"] or "",
                            diff=row["diff"] or "",
                            rollback=row["rollback"] or "",
                            mission_id=row["mission_id"] or "",
                            id=row["id"],
                            status=row["status"] or ActionStatus.PENDING,
                            created_at=row["created_at"] or time.time(),
                            approved_at=row["approved_at"],
                            rejected_at=row["rejected_at"],
                            executed_at=row["executed_at"],
                            result=row["result"] or "",
                            note=row["note"] or "",
                        )
                        self._actions[a.id] = a
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='action_queue.py')
                self._use_sqlite = True
                log.debug("action_queue_loaded_sqlite", count=len(self._actions))
                return
        except Exception as exc:
            log.warning("action_queue_sqlite_load_failed", err=str(exc))
        # Fallback JSON
        self._use_sqlite = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text("utf-8"))
            for item in data.get("actions", []):
                try:
                    a = Action.from_dict(item)
                    self._actions[a.id] = a
                except Exception:
                    _silent_log.debug("suppressed_exception", src='action_queue.py')
        except Exception as exc:
            log.warning("action_queue_load_failed", err=str(exc))

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version":  1,
                "saved_at": time.time(),
                "actions":  [a.to_dict() for a in self._actions.values()],
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception as exc:
            log.warning("action_queue_save_failed", err=str(exc))

    def _sqlite_insert(self, action: Action) -> None:
        try:
            from core import db as _db_mod
            _db_mod.execute(
                """INSERT OR IGNORE INTO actions
                   (id, description, risk, target, impact, diff, rollback, mission_id,
                    status, created_at, approved_at, rejected_at, executed_at, result, note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    action.id, action.description, action.risk, action.target,
                    action.impact, action.diff, action.rollback, action.mission_id,
                    action.status, action.created_at,
                    action.approved_at, action.rejected_at, action.executed_at,
                    action.result, action.note,
                )
            )
        except Exception as exc:
            log.warning("action_sqlite_insert_failed", err=str(exc))
            self._save()

    def _sqlite_update_status(self, action: Action) -> None:
        try:
            from core import db as _db_mod
            _db_mod.execute(
                """UPDATE actions SET status=?, approved_at=?, rejected_at=?,
                   executed_at=?, result=?, note=? WHERE id=?""",
                (
                    action.status, action.approved_at, action.rejected_at,
                    action.executed_at, action.result, action.note, action.id,
                )
            )
        except Exception as exc:
            log.warning("action_sqlite_update_failed", err=str(exc))
            self._save()


# ── Singleton ─────────────────────────────────────────────────────────────────

_queue_instance: ActionQueue|None = None


def get_action_queue() -> ActionQueue:
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = ActionQueue()
    return _queue_instance
