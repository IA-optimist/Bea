"""
JARVIS MAX — GoalManager
Gestion des objectifs, missions en cours, priorités et historique.

Problème résolu :
    Jarvis traite chaque session comme isolée. GoalManager maintient
    une continuité entre les sessions :
    - quelles missions sont en cours
    - quelles sont terminées
    - quelles tâches longues sont planifiées
    - quel est l'historique des décisions

Architecture :
    GoalManager
    ├── ActiveGoal    : mission en cours (une seule à la fois)
    ├── GoalQueue     : missions en attente (FIFO avec priorités)
    └── GoalHistory   : historique persisté (workspace/goals.json)

Usage :
    manager = GoalManager(settings)

    # Démarrer une mission
    goal = manager.start(text="Analyse le pipeline self-improve", mode="auto", priority=2)

    # Marquer terminée
    manager.complete(goal.id, result="3 findings, 1 patch appliqué")

    # Voir l'historique
    recent = manager.history(n=10)
    active = manager.get_active()
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import structlog

log = structlog.get_logger()

_GOALS_FILE    = "goals.json"
_MAX_HISTORY   = 200


class GoalStatus(str, Enum):
    PENDING    = "pending"
    ACTIVE     = "active"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class GoalPriority(int, Enum):
    LOW      = 1
    NORMAL   = 2
    HIGH     = 3
    CRITICAL = 4


# ══════════════════════════════════════════════════════════════
# GOAL
# ══════════════════════════════════════════════════════════════

@dataclass
class Goal:
    """
    Représente un objectif/mission de Jarvis.
    """
    id:           str
    text:         str
    mode:         str          = "auto"
    priority:     int          = GoalPriority.NORMAL
    status:       GoalStatus   = GoalStatus.PENDING
    session_id:   str          = ""
    created_at:   float        = field(default_factory=time.time)
    started_at:   float        = 0.0
    completed_at: float        = 0.0
    result:       str          = ""
    error:        str          = ""
    tags:         list[str]    = field(default_factory=list)
    metadata:     dict         = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        if self.started_at and self.completed_at:
            return round(self.completed_at - self.started_at, 1)
        if self.started_at:
            return round(time.time() - self.started_at, 1)
        return 0.0

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELLED
        )

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "text":         self.text[:200],
            "mode":         self.mode,
            "priority":     self.priority,
            "status":       self.status.value if isinstance(self.status, GoalStatus) else self.status,
            "session_id":   self.session_id,
            "created_at":   self.created_at,
            "started_at":   self.started_at,
            "completed_at": self.completed_at,
            "duration_s":   self.duration_s,
            "result":       self.result,
            "error":        self.error,
            "tags":         self.tags[:10],
            "metadata":     self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        return cls(
            id           = d.get("id", str(uuid.uuid4())[:8]),
            text         = d.get("text", ""),
            mode         = d.get("mode", "auto"),
            priority     = d.get("priority", GoalPriority.NORMAL),
            status       = GoalStatus(d.get("status", "pending")),
            session_id   = d.get("session_id", ""),
            created_at   = d.get("created_at", time.time()),
            started_at   = d.get("started_at", 0.0),
            completed_at = d.get("completed_at", 0.0),
            result       = d.get("result", ""),
            error        = d.get("error", ""),
            tags         = d.get("tags", []),
            metadata     = d.get("metadata", {}),
        )


# ══════════════════════════════════════════════════════════════
# GOAL MANAGER
# ══════════════════════════════════════════════════════════════

class GoalManager:
    """
    Gestionnaire de missions JarvisMax.

    Persiste l'historique dans workspace/goals.json.
    Thread-safe pour usage dans l'orchestrateur async.
    """

    def __init__(self, settings):
        self.s        = settings
        self._path    = self._resolve_path()
        self._active: Goal | None          = None
        self._queue:  list[Goal]           = []
        self._history: list[Goal]          = []
        self._loaded  = False

    # ── Persistance ───────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / _GOALS_FILE

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text("utf-8"))
                self._history = [
                    Goal.from_dict(d) for d in data.get("history", [])
                ]
                # Restaurer les goals actifs/en attente depuis la persistance
                for d in data.get("queue", []):
                    g = Goal.from_dict(d)
                    if not g.is_terminal:
                        self._queue.append(g)
                log.debug("goal_manager_loaded",
                          history=len(self._history), queue=len(self._queue))
        except Exception as e:
            log.warning("goal_manager_load_error", err=str(e))

    def _save(self) -> None:
        try:
            data = {
                "history": [g.to_dict() for g in self._history[-_MAX_HISTORY:]],
                "queue":   [g.to_dict() for g in self._queue],
                "active":  self._active.to_dict() if self._active else None,
                "saved_at": time.time(),
            }
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("goal_manager_save_error", err=str(e))

    # ── API publique ──────────────────────────────────────

    def start(
        self,
        text:       str,
        mode:       str   = "auto",
        priority:   int   = GoalPriority.NORMAL,
        session_id: str   = "",
        tags:       list[str] | None = None,
        metadata:   dict  | None     = None,
    ) -> Goal:
        """
        Démarre un nouveau goal (le place en ACTIVE immédiatement).
        Si un goal est déjà actif, l'ancienne mission est annulée.
        """
        self._load()

        # Annuler le goal actif précédent s'il existe
        if self._active and not self._active.is_terminal:
            self._active.status       = GoalStatus.CANCELLED
            self._active.completed_at = time.time()
            self._history.append(self._active)
            log.info("goal_cancelled_by_new",
                     old=self._active.id[:8], old_text=self._active.text[:40])

        goal = Goal(
            id         = str(uuid.uuid4())[:8],
            text       = text,
            mode       = mode,
            priority   = priority,
            status     = GoalStatus.ACTIVE,
            session_id = session_id,
            created_at = time.time(),
            started_at = time.time(),
            tags       = tags or [],
            metadata   = metadata or {},
        )

        self._active = goal
        log.info("goal_started", id=goal.id, mode=mode, text=goal.text[:60])
        self._save()
        return goal

    def enqueue(
        self,
        text:     str,
        mode:     str = "auto",
        priority: int = GoalPriority.NORMAL,
        tags:     list[str] | None = None,
    ) -> Goal:
        """Ajoute un goal en file d'attente (ne démarre pas immédiatement)."""
        self._load()
        goal = Goal(
            id       = str(uuid.uuid4())[:8],
            text     = text,
            mode     = mode,
            priority = priority,
            status   = GoalStatus.PENDING,
            tags     = tags or [],
            created_at = time.time(),
        )
        # Insertion triée par priorité (CRITICAL en tête)
        self._queue.append(goal)
        self._queue.sort(key=lambda g: -g.priority)
        log.info("goal_enqueued", id=goal.id, priority=priority, text=text[:60])
        self._save()
        return goal

    def complete(
        self,
        goal_id: str,
        result:  str = "",
        metadata: dict | None = None,
    ) -> bool:
        """Marque un goal comme terminé avec succès."""
        goal = self._find_goal(goal_id)
        if not goal:
            return False

        goal.status       = GoalStatus.COMPLETED
        goal.completed_at = time.time()
        goal.result       = result if result else ""
        if metadata:
            goal.metadata.update(metadata)

        if goal is self._active:
            self._active = None

        self._archive(goal)
        log.info("goal_completed", id=goal.id, duration_s=goal.duration_s,
                 text=goal.text[:60])
        self._save()
        return True

    def fail(
        self,
        goal_id: str,
        error:   str = "",
    ) -> bool:
        """Marque un goal comme échoué."""
        goal = self._find_goal(goal_id)
        if not goal:
            return False

        goal.status       = GoalStatus.FAILED
        goal.completed_at = time.time()
        goal.error        = error[:200] if error else ""

        if goal is self._active:
            self._active = None

        self._archive(goal)
        log.warning("goal_failed", id=goal.id, error=error[:60])
        self._save()
        return True

    def get_active(self) -> Goal | None:
        """Retourne le goal actuellement actif."""
        self._load()
        return self._active

    def get_queue(self) -> list[Goal]:
        """Retourne la file d'attente (triée par priorité)."""
        self._load()
        return list(self._queue)

    def next_from_queue(self) -> Goal | None:
        """Prend le prochain goal de la file et le met en ACTIVE."""
        self._load()
        if not self._queue:
            return None
        goal = self._queue.pop(0)
        goal.status     = GoalStatus.ACTIVE
        goal.started_at = time.time()
        self._active    = goal
        log.info("goal_dequeued", id=goal.id, text=goal.text[:60])
        self._save()
        return goal

    def history(self, n: int = 20, mode: str = "", status: str = "") -> list[Goal]:
        """
        Retourne les N derniers goals de l'historique.
        Filtrable par mode et status.
        """
        self._load()
        items = self._history[-n * 3:]  # oversample puis filtrer

        if mode:
            items = [g for g in items if g.mode == mode]
        if status:
            items = [g for g in items if g.status.value == status]

        return items[-n:]

    def get_stats(self) -> dict:
        """Statistiques globales des goals."""
        self._load()
        total    = len(self._history)
        by_status: dict[str, int] = {}
        by_mode:   dict[str, int] = {}
        avg_duration = 0.0

        for g in self._history:
            s = g.status.value if isinstance(g.status, GoalStatus) else g.status
            by_status[s] = by_status.get(s, 0) + 1
            by_mode[g.mode] = by_mode.get(g.mode, 0) + 1

        completed = [g for g in self._history if g.status == GoalStatus.COMPLETED]
        if completed:
            avg_duration = sum(g.duration_s for g in completed) / len(completed)

        return {
            "total":         total,
            "active":        1 if self._active else 0,
            "queued":        len(self._queue),
            "by_status":     by_status,
            "by_mode":       by_mode,
            "avg_duration_s": round(avg_duration, 1),
        }

    def clear(self):
        """Vide l'historique et la file (pour tests)."""
        self._active  = None
        self._queue   = []
        self._history = []
        self._save()

    # ── Helpers ───────────────────────────────────────────

    def _find_goal(self, goal_id: str) -> Goal | None:
        """Cherche un goal par ID dans actif + queue."""
        if self._active and self._active.id == goal_id:
            return self._active
        for g in self._queue:
            if g.id == goal_id:
                return g
        return None

    def _archive(self, goal: Goal) -> None:
        """Déplace un goal dans l'historique et le retire de la queue."""
        if goal in self._queue:
            self._queue.remove(goal)
        if goal not in self._history:
            self._history.append(goal)
        # Limiter la taille
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[-_MAX_HISTORY:]
