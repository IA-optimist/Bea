"""
goal_registry.py — Système d'objectifs persistants pour JarvisMax
Architecture d'autonomie graduée — Niveau 2

Auteur: Jarvis (JarvisMax Research)
Date: 2026-04-09
"""

from __future__ import annotations

import json
import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger(__name__)

HORIZONS = {"immediate", "weekly", "monthly", "permanent"}


@dataclass
class ProactiveGoal:
    """Représente un objectif persistant de Jarvis."""

    id: str
    description: str
    horizon: str          # "immediate" | "weekly" | "monthly" | "permanent"
    priority: int         # 1 (bas) → 10 (critique)
    progress: float       # 0.0 → 1.0
    next_action: str
    created_at: float
    last_checked: float
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    completed: bool = False
    paused: bool = False

    # ── Helpers ──────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        return not self.completed and not self.paused

    def staleness_hours(self) -> float:
        """Combien d'heures depuis la dernière vérification."""
        return (time.time() - self.last_checked) / 3600

    def deadline_hours(self) -> Optional[float]:
        """
        Retourne les heures restantes avant échéance, si applicable.
        On stocke la deadline dans notes sous la forme "deadline:<epoch>".
        """
        for note in self.notes:
            if note.startswith("deadline:"):
                try:
                    deadline_ts = float(note.split(":", 1)[1])
                    return (deadline_ts - time.time()) / 3600
                except ValueError:
                    _silent_log.debug("suppressed_exception", src='goal_registry.py')
        return None

    def set_deadline(self, epoch: float) -> None:
        self.notes = [n for n in self.notes if not n.startswith("deadline:")]
        self.notes.append(f"deadline:{epoch}")

    # ── Sérialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProactiveGoal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class GoalRegistry:
    """
    Registre persistant des objectifs de Jarvis.

    Stockage JSON local. Thread-safe pour usage single-process.
    Pour multi-process, préférer une base SQLite ou Redis.
    """

    DEFAULT_PATH = Path("/root/.openclaw-bestclaw/workspace/Jarvismax-master/workspace/proactive_goals.json")

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._path = Path(storage_path or self.DEFAULT_PATH)
        self._goals: dict[str, ProactiveGoal] = {}
        self._load()

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_goal(self, goal: ProactiveGoal) -> ProactiveGoal:
        """Ajoute ou remplace un objectif."""
        if goal.horizon not in HORIZONS:
            raise ValueError(f"horizon doit être dans {HORIZONS}")
        if not (1 <= goal.priority <= 10):
            raise ValueError("priority doit être entre 1 et 10")
        self._goals[goal.id] = goal
        self.save()
        logger.info("Goal added: %s [%s]", goal.id, goal.description[:60])
        return goal

    def create_goal(
        self,
        description: str,
        horizon: str = "weekly",
        priority: int = 5,
        next_action: str = "",
        tags: Optional[list[str]] = None,
    ) -> ProactiveGoal:
        """Crée et enregistre un nouvel objectif avec ID auto-généré."""
        now = time.time()
        goal = ProactiveGoal(
            id=str(uuid.uuid4())[:8],
            description=description,
            horizon=horizon,
            priority=priority,
            progress=0.0,
            next_action=next_action,
            created_at=now,
            last_checked=now,
            tags=tags or [],
        )
        return self.add_goal(goal)

    def get_goal(self, goal_id: str) -> Optional[ProactiveGoal]:
        return self._goals.get(goal_id)

    def get_active_goals(self, horizon: Optional[str] = None) -> list[ProactiveGoal]:
        """Retourne les objectifs actifs, optionnellement filtrés par horizon."""
        goals = [g for g in self._goals.values() if g.is_active()]
        if horizon:
            goals = [g for g in goals if g.horizon == horizon]
        return sorted(goals, key=lambda g: (-g.priority, g.last_checked))

    def update_progress(
        self,
        goal_id: str,
        progress: float,
        notes: str = "",
        next_action: str = "",
    ) -> ProactiveGoal:
        """Met à jour la progression d'un objectif."""
        goal = self._goals.get(goal_id)
        if not goal:
            raise KeyError(f"Goal {goal_id} introuvable")

        goal.progress = max(0.0, min(1.0, progress))
        goal.last_checked = time.time()
        if notes:
            goal.notes.append(f"[{_ts()}] {notes}")
        if next_action:
            goal.next_action = next_action
        if goal.progress >= 1.0:
            goal.completed = True
            logger.info("Goal completed: %s", goal_id)

        self.save()
        return goal

    def mark_completed(self, goal_id: str) -> ProactiveGoal:
        return self.update_progress(goal_id, 1.0, notes="Marqué complété manuellement")

    def pause_goal(self, goal_id: str) -> ProactiveGoal:
        goal = self._goals[goal_id]
        goal.paused = True
        self.save()
        return goal

    def resume_goal(self, goal_id: str) -> ProactiveGoal:
        goal = self._goals[goal_id]
        goal.paused = False
        goal.last_checked = time.time()
        self.save()
        return goal

    def remove_goal(self, goal_id: str) -> bool:
        if goal_id in self._goals:
            del self._goals[goal_id]
            self.save()
            return True
        return False

    # ── Détection d'opportunités ──────────────────────────────────────────────

    def detect_opportunity(self, context: dict) -> list[ProactiveGoal]:
        """
        Retourne les objectifs qui peuvent avancer compte tenu du contexte actuel.

        context peut contenir :
          - "services_down": list[str]     → noms de services tombés
          - "files_changed": list[str]     → chemins de fichiers modifiés
          - "deadlines_soon": list[str]    → IDs d'objectifs à échéance proche
          - "hour": int                    → heure locale (0-23)
          - "tags_available": list[str]    → tags de capacités disponibles
        """
        opportunities: list[ProactiveGoal] = []
        active = self.get_active_goals()

        for goal in active:
            if self._goal_has_opportunity(goal, context):
                opportunities.append(goal)

        return sorted(opportunities, key=lambda g: -g.priority)

    def _goal_has_opportunity(self, goal: ProactiveGoal, context: dict) -> bool:
        services_down: list[str] = context.get("services_down", [])
        files_changed: list[str] = context.get("files_changed", [])
        hour: int = context.get("hour", 12)

        # Objectif de monitoring de service
        if "monitoring" in goal.tags and services_down:
            return True

        # Objectif de documentation
        if "documentation" in goal.tags and files_changed:
            return True

        # Deadline dans moins de 24h
        deadline_h = goal.deadline_hours()
        if deadline_h is not None and 0 < deadline_h <= 24:
            return True

        # Objectif immédiat non vérifié depuis 15 min
        if goal.horizon == "immediate" and goal.staleness_hours() > 0.25:
            return True

        # Objectif hebdomadaire non vérifié depuis 6h (fenêtre de travail)
        if goal.horizon == "weekly" and goal.staleness_hours() > 6 and 8 <= hour <= 22:
            return True

        return False

    # ── Persistance ───────────────────────────────────────────────────────────

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "goals": {gid: g.to_dict() for gid, g in self._goals.items()},
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        tmp.replace(self._path)  # écriture atomique
        logger.debug("GoalRegistry saved (%d goals)", len(self._goals))

    def _load(self) -> None:
        if not self._path.exists():
            logger.info("Aucun fichier goals existant — démarrage à vide")
            return
        try:
            data = json.loads(self._path.read_text())
            for gid, gdata in data.get("goals", {}).items():
                self._goals[gid] = ProactiveGoal.from_dict(gdata)
            logger.info("GoalRegistry chargé : %d objectifs", len(self._goals))
        except Exception as exc:  # noqa: BLE001
            logger.error("Erreur chargement goals.json : %s", exc)

    # ── Rapport ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        active = self.get_active_goals()
        lines = [f"📋 GoalRegistry — {len(active)} objectifs actifs\n"]
        for g in active:
            bar = _progress_bar(g.progress)
            lines.append(
                f"  [{g.id}] P{g.priority} {bar} {g.description[:50]}\n"
                f"    ↳ Prochaine action : {g.next_action}\n"
            )
        return "".join(lines) if lines else "Aucun objectif actif."


# Alias de compatibilité ascendante — évite de casser les imports existants
Goal = ProactiveGoal

# ── Utilitaires ───────────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _progress_bar(progress: float, width: int = 10) -> str:
    filled = int(progress * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {int(progress * 100)}%"
