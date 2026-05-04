"""
Objective Engine — Logique principale.
CRUD + breakdown + next_best_action + détection blocages.
Fail-open total : si le module échoue, Jarvis continue comme avant.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import List, Optional

from core.objectives.objective_models import (
    Objective,
    ObjectiveStatus,
    SubObjective,
    SubObjectiveStatus,
)
from core.objectives.objective_store import ObjectiveStore, get_objective_store
from core.objectives.objective_scoring import compute_priority_score
from core.objectives.objective_breakdown import breakdown_objective

logger = logging.getLogger("jarvis.objective_engine")

# ── Constantes ─────────────────────────────────────────────────────────────────

MAX_RETRIES_BEFORE_BLOCK = 3
MAX_OBJECTIVES_ACTIVE    = 20   # anti-saturation


# ── Helpers logs structurés ────────────────────────────────────────────────────

def _jlog(event: str, data: dict) -> None:
    data["event"] = event
    data["ts"] = round(time.time(), 3)
    logger.info(json.dumps(data, ensure_ascii=False))


# ── ObjectiveEngine ────────────────────────────────────────────────────────────

class ObjectiveEngine:
    """
    Moteur principal de gestion des objectifs.
    Toutes les méthodes sont fail-open : exception → log + valeur par défaut.
    """

    def __init__(self, store: Optional[ObjectiveStore] = None):
        self._store = store or get_objective_store()

    # ─────────────────────────────────────────────────────────────────────
    # Création
    # ─────────────────────────────────────────────────────────────────────

    def create(
        self,
        title: str,
        description: str = "",
        category: str = "general",
        priority_score: float = 0.5,
        source: str = "user",
        owner: str = "jarvis",
        success_criteria: str = "",
        depends_on: List[str] | None = None,
        auto_breakdown: bool = True,
    ) -> Optional[Objective]:
        """
        Crée un nouvel objectif, l'enregistre et lance le breakdown automatique.
        Retourne None en cas d'échec (fail-open).
        """
        try:
            # Vérifier limite anti-saturation
            active = self._store.get_active()
            if len(active) >= MAX_OBJECTIVES_ACTIVE:
                logger.warning(
                    f"[OBJECTIVE_ENGINE] max active objectives reached ({MAX_OBJECTIVES_ACTIVE})"
                )

            # Estimation de difficulté (fail-open)
            difficulty = _estimate_difficulty_safe(title, description, category)

            obj = Objective(
                objective_id    = str(uuid.uuid4())[:12],
                title           = title[:200],
                description     = description[:1000],
                category        = category,
                status          = ObjectiveStatus.NEW,
                priority_score  = max(0.0, min(1.0, priority_score)),
                difficulty_score = difficulty,
                source          = source,
                owner           = owner,
                success_criteria = success_criteria,
                depends_on      = list(depends_on or []),
            )

            # Calculer et mettre à jour le score de priorité
            score_result = compute_priority_score(obj)
            obj.priority_score = score_result["score"]

            # Breakdown automatique
            if auto_breakdown:
                obj.sub_objectives = breakdown_objective(obj, mission_type=category)

            # Identifier outils et patterns
            obj.related_tools = _extract_tools_from_subs(obj.sub_objectives)

            obj.add_history_entry("created", f"source={source}")
            self._store.save(obj)

            _jlog("objective_created", {
                "objective_id": obj.objective_id,
                "title":        obj.title[:60],
                "category":     obj.category,
                "priority":     obj.priority_score,
                "sub_count":    len(obj.sub_objectives),
            })
            return obj

        except Exception as e:
            logger.error(f"[OBJECTIVE_ENGINE] create failed: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────
    # Lecture
    # ─────────────────────────────────────────────────────────────────────

    def get(self, objective_id: str) -> Optional[Objective]:
        try:
            return self._store.get(objective_id)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] get failed: {e}")
            return None

    def get_all(self, include_archived: bool = False) -> List[Objective]:
        try:
            return self._store.get_all(include_archived)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] get_all failed: {e}")
            return []

    def get_active(self) -> List[Objective]:
        try:
            return self._store.get_active()
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] get_active failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # Mise à jour du statut
    # ─────────────────────────────────────────────────────────────────────

    def update_status(
        self,
        objective_id: str,
        new_status: str,
        reason: str = "",
    ) -> bool:
        """Change le statut d'un objectif. Loggue la transition."""
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                logger.warning(f"[OBJECTIVE_ENGINE] update_status: not found {objective_id}")
                return False

            old_status = obj.status
            obj.status = new_status
            obj.add_history_entry("status_changed", f"{old_status}→{new_status} {reason}")

            self._store.save(obj)
            _jlog("objective_status_changed", {
                "objective_id": objective_id,
                "old_status":   old_status,
                "new_status":   new_status,
                "reason":       reason[:100],
            })
            return True
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] update_status failed: {e}")
            return False

    def activate(self, objective_id: str) -> bool:
        return self.update_status(objective_id, ObjectiveStatus.ACTIVE, "activated")

    def pause(self, objective_id: str, reason: str = "") -> bool:
        return self.update_status(objective_id, ObjectiveStatus.PAUSED, reason or "paused by user")

    def resume(self, objective_id: str) -> bool:
        obj = self._store.get(objective_id)
        if obj and obj.status == ObjectiveStatus.PAUSED:
            return self.update_status(objective_id, ObjectiveStatus.ACTIVE, "resumed")
        return False

    def archive(self, objective_id: str, reason: str = "") -> bool:
        """Archive un objectif (ne supprime pas les données)."""
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                return False
            obj.archived = True
            obj.add_history_entry("archived", reason or "archived")
            # Conserver le statut mais marquer archived
            if obj.status not in ObjectiveStatus.TERMINAL:
                obj.status = ObjectiveStatus.ARCHIVED
            self._store.save(obj)
            _jlog("objective_archived", {"objective_id": objective_id, "reason": reason[:80]})
            return True
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] archive failed: {e}")
            return False

    def complete(self, objective_id: str, summary: str = "") -> bool:
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                return False
            obj.status = ObjectiveStatus.COMPLETED
            obj.current_progress = 1.0
            obj.last_execution_summary = summary
            obj.add_history_entry("completed", summary[:200])
            self._store.save(obj)
            _jlog("objective_completed", {"objective_id": objective_id})
            return True
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] complete failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────
    # Breakdown
    # ─────────────────────────────────────────────────────────────────────

    def breakdown(self, objective_id: str) -> List[SubObjective]:
        """
        (Re)décompose un objectif en sous-objectifs.
        Remplace les sous-objectifs existants si tous en TODO.
        """
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                return []
            # Ne pas re-décomposer si des sous-objectifs sont déjà en cours
            has_progress = any(
                s.status not in (SubObjectiveStatus.TODO,)
                for s in obj.sub_objectives
            )
            if has_progress and obj.sub_objectives:
                logger.info("[OBJECTIVE_ENGINE] breakdown: already has progress, skip re-breakdown")
                return obj.sub_objectives

            new_subs = breakdown_objective(obj)
            obj.sub_objectives = new_subs
            obj.add_history_entry("breakdown", f"{len(new_subs)} sub-objectives")
            self._store.save(obj)
            return new_subs
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] breakdown failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # Détection de blocages
    # ─────────────────────────────────────────────────────────────────────

    def detect_and_mark_blockers(self, objective_id: str) -> List[str]:
        """
        Détecte les blocages et met à jour les statuts.
        Retourne une liste de raisons de blocage.
        """
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                return []

            blockers: List[str] = []
            changed = False

            for sub in obj.sub_objectives:
                if sub.status in SubObjectiveStatus.TERMINAL:
                    continue

                # Trop de retries
                if sub.retry_count >= MAX_RETRIES_BEFORE_BLOCK:
                    if sub.status != SubObjectiveStatus.BLOCKED:
                        sub.status = SubObjectiveStatus.BLOCKED
                        sub.blocker_reason = f"max retries atteint ({sub.retry_count})"
                        changed = True
                    blockers.append(f"sub:{sub.node_id} retry_limit ({sub.retry_count})")

                # Même erreur répétée dans last_result
                if sub.retry_count >= 2 and sub.last_result and "error" in sub.last_result.lower():
                    if sub.status != SubObjectiveStatus.BLOCKED:
                        sub.status = SubObjectiveStatus.BLOCKED
                        sub.blocker_reason = f"erreur répétée: {sub.last_result[:80]}"
                        changed = True
                    blockers.append(f"sub:{sub.node_id} repeated_error")

            # Vérifier les dépendances d'objectif
            for dep_id in obj.depends_on:
                dep = self._store.get(dep_id)
                if dep and dep.status not in ObjectiveStatus.TERMINAL:
                    blockers.append(f"depends_on:{dep_id} not completed (status={dep.status})")

            # Mettre à jour le statut de l'objectif parent
            if blockers and obj.status == ObjectiveStatus.ACTIVE:
                obj.status = ObjectiveStatus.BLOCKED
                obj.blocked_by = [b for b in blockers][:10]
                obj.add_history_entry("blocked", f"blockers: {'; '.join(blockers[:3])}")
                changed = True

            if changed:
                self._store.save(obj)
                _jlog("objective_blocked", {
                    "objective_id": objective_id,
                    "blockers":     blockers[:5],
                })

            return blockers
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] detect_blockers failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # Next Best Action
    # ─────────────────────────────────────────────────────────────────────

    def get_next_best_action(self, goal_hint: str = "") -> dict:
        """
        Retourne la prochaine action recommandée parmi tous les objectifs actifs.

        Retourne :
            {
                "objective_id": str,
                "node_id": str | None,
                "action_type": str,
                "rationale": str,
                "confidence": float,
                "required_tools": list,
                "requires_human_approval": bool,
                "suggested_agent": str,
            }
        Si aucun objectif actif → retourne dict avec action_type="no_active_objectives".
        Fail-open.
        """
        try:
            active_objs = self._store.get_active()
            if not active_objs:
                return _no_action("Aucun objectif actif")

            # Scorer et trier tous les objectifs actifs
            scored: List[tuple[float, Objective]] = []
            for obj in active_objs:
                score_r = compute_priority_score(obj)
                scored.append((score_r["score"], obj))
            scored.sort(key=lambda x: x[0], reverse=True)

            # Chercher le premier sous-objectif actionnable
            for score, obj in scored:
                next_sub = _find_next_actionable_sub(obj)
                if next_sub is not None:
                    # Détecter les blocages avant
                    blockers = self.detect_and_mark_blockers(obj.objective_id)
                    if blockers:
                        # Cet objectif est bloqué → passer au suivant
                        continue

                    requires_approval = (
                        obj.status == ObjectiveStatus.WAITING_APPROVAL
                        or next_sub.difficulty > 0.75
                    )
                    return {
                        "objective_id":           obj.objective_id,
                        "objective_title":        obj.title,
                        "node_id":                next_sub.node_id,
                        "node_title":             next_sub.title,
                        "action_type":            _infer_action_type(next_sub),
                        "rationale":              (
                            f"Objectif '{obj.title[:60]}' (score={score:.2f}) — "
                            f"prochaine étape: {next_sub.title}"
                        ),
                        "confidence":             round(min(score, obj.confidence), 3),
                        "required_tools":         next_sub.recommended_tools[:5],
                        "requires_human_approval": requires_approval,
                        "suggested_agent":        next_sub.recommended_agents[0]
                                                  if next_sub.recommended_agents else "jarvis",
                        "objective_status":       obj.status,
                        "objective_priority":     round(score, 3),
                    }

            # Tous les objectifs actifs sont bloqués ou sans sous-objectifs
            if scored:
                best = scored[0][1]
                return {
                    "objective_id":            best.objective_id,
                    "objective_title":         best.title,
                    "node_id":                 None,
                    "action_type":             "review_blocked",
                    "rationale":               "Tous les objectifs actifs semblent bloqués. Revue recommandée.",
                    "confidence":              0.3,
                    "required_tools":          [],
                    "requires_human_approval": True,
                    "suggested_agent":         "jarvis",
                    "objective_status":        best.status,
                    "objective_priority":      round(scored[0][0], 3),
                }

            return _no_action("Aucune action disponible")

        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] get_next_best_action failed: {e}")
            return _no_action(f"error: {str(e)[:80]}")

    # ─────────────────────────────────────────────────────────────────────
    # Historique & Résumés
    # ─────────────────────────────────────────────────────────────────────

    def get_history(self, objective_id: str) -> List[dict]:
        """Retourne l'historique d'un objectif."""
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                return []
            return list(obj.history)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] get_history failed: {e}")
            return []

    def get_history_summary(self, objective_id: str) -> str:
        """Résumé compact de l'historique."""
        try:
            history = self.get_history(objective_id)
            if not history:
                return "Aucun historique disponible."
            lines = []
            for h in history[-10:]:
                ts = h.get("ts", 0)
                age = round((time.time() - ts) / 3600, 1)
                lines.append(f"  [{age}h] {h.get('event','')} — {h.get('detail','')[:60]}")
            return "\n".join(lines)
        except Exception as e:
            return f"[history_error: {e}]"

    def update_progress(self, objective_id: str) -> float:
        """Recalcule et met à jour la progression basée sur les sous-objectifs."""
        try:
            obj = self._store.get(objective_id)
            if obj is None:
                return 0.0
            total = len(obj.sub_objectives)
            if total == 0:
                return obj.current_progress
            done = sum(1 for s in obj.sub_objectives if s.status == SubObjectiveStatus.DONE)
            progress = done / total
            obj.current_progress = progress
            # Auto-complétion si tous les sous-objectifs sont DONE
            if progress >= 1.0 and obj.status == ObjectiveStatus.ACTIVE:
                obj.status = ObjectiveStatus.COMPLETED
                obj.add_history_entry("auto_completed", "all sub-objectives done")
            self._store.save(obj)
            return progress
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] update_progress failed: {e}")
            return 0.0

    # ─────────────────────────────────────────────────────────────────────
    # Champs pour decision_trace (valeurs par défaut sûres)
    # ─────────────────────────────────────────────────────────────────────

    def get_trace_fields(self, goal: str = "", session_id: str = "") -> dict:
        """
        Retourne les champs à injecter dans decision_trace.
        Toujours des valeurs par défaut sûres. Fail-open total.
        """
        defaults = {
            "objective_id":             None,
            "objective_status":         None,
            "objective_priority_score": None,
            "objective_difficulty":     None,
            "objective_match":          False,
            "next_best_action":         None,
            "blocker_detected":         False,
            "blocker_reason":           None,
        }
        try:
            # Chercher un objectif actif lié au goal
            if goal:
                similar = self._store.search_similar(goal, top_k=1)
                if similar:
                    match = similar[0]
                    obj = self._store.get(match.get("objective_id", ""))
                    if obj:
                        nba = self.get_next_best_action(goal_hint=goal)
                        blockers = self.detect_and_mark_blockers(obj.objective_id)
                        defaults.update({
                            "objective_id":             obj.objective_id,
                            "objective_status":         obj.status,
                            "objective_priority_score": round(obj.priority_score, 3),
                            "objective_difficulty":     round(obj.difficulty_score, 3),
                            "objective_match":          True,
                            "next_best_action":         nba.get("action_type"),
                            "blocker_detected":         bool(blockers),
                            "blocker_reason":           blockers[0][:100] if blockers else None,
                        })
        except Exception as e:
            logger.debug(f"[OBJECTIVE_ENGINE] get_trace_fields error: {e}")
        return defaults

    # ─────────────────────────────────────────────────────────────────────
    # Réutilisation patterns similaires
    # ─────────────────────────────────────────────────────────────────────

    def find_similar(self, title: str, description: str = "") -> List[dict]:
        """Cherche des objectifs similaires existants."""
        try:
            query = f"{title} {description}"
            return self._store.search_similar(query, top_k=5)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_ENGINE] find_similar failed: {e}")
            return []


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_next_actionable_sub(obj: Objective) -> Optional[SubObjective]:
    """Retourne le prochain sous-objectif actionnable (READY ou TODO avec seq=0)."""
    for sub in sorted(obj.sub_objectives, key=lambda s: s.sequence_order):
        if sub.status in SubObjectiveStatus.ACTIONABLE:
            return sub
    return None


def _infer_action_type(sub: SubObjective) -> str:
    """Infère le type d'action depuis les outils recommandés."""
    tools = [t.lower() for t in sub.recommended_tools]
    if any("test" in t for t in tools):
        return "run_tests"
    if any("deploy" in t or "docker" in t for t in tools):
        return "deploy"
    if any("git" in t for t in tools):
        return "git_operation"
    if any("file" in t or "replace" in t or "create" in t for t in tools):
        return "code_write"
    if any("search" in t or "fetch" in t or "http" in t for t in tools):
        return "research"
    return "execute_step"


def _no_action(reason: str) -> dict:
    return {
        "objective_id":            None,
        "objective_title":         None,
        "node_id":                 None,
        "node_title":              None,
        "action_type":             "no_active_objectives",
        "rationale":               reason,
        "confidence":              0.0,
        "required_tools":          [],
        "requires_human_approval": False,
        "suggested_agent":         "jarvis",
        "objective_status":        None,
        "objective_priority":      0.0,
    }


def _estimate_difficulty_safe(title: str, description: str, category: str) -> float:
    """Estimation de difficulté avec fallback à 0.5."""
    try:
        from core.knowledge.difficulty_estimator import estimate_difficulty
        result = estimate_difficulty(
            goal=f"{title}: {description}",
            mission_type=category,
        )
        return float(result.get("score", 0.5))
    except Exception:
        return 0.5


def _extract_tools_from_subs(subs: List[SubObjective]) -> List[str]:
    """Extrait une liste dédupliquée des outils recommandés dans les sous-objectifs."""
    seen = set()
    tools = []
    for sub in subs:
        for t in sub.recommended_tools:
            if t and t not in seen:
                seen.add(t)
                tools.append(t)
    return tools[:10]


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[ObjectiveEngine] = None


def get_objective_engine(store: Optional[ObjectiveStore] = None) -> ObjectiveEngine:
    global _engine
    if _engine is None:
        _engine = ObjectiveEngine(store)
    return _engine


def reset_engine() -> None:
    """Reset le singleton (pour les tests)."""
    global _engine
    _engine = None
