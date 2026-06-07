"""
Objective Engine — Modèles de données.
Dataclasses pour Objective et SubObjective avec statuts normalisés.
Aucune dépendance externe. Fail-safe total.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional


# ── Statuts normalisés ─────────────────────────────────────────────────────────

class ObjectiveStatus:
    NEW               = "NEW"
    ACTIVE            = "ACTIVE"
    BLOCKED           = "BLOCKED"
    WAITING_APPROVAL  = "WAITING_APPROVAL"
    PAUSED            = "PAUSED"
    COMPLETED         = "COMPLETED"
    FAILED            = "FAILED"
    ARCHIVED          = "ARCHIVED"

    TERMINAL = {COMPLETED, FAILED, ARCHIVED}
    ACTIVE_STATES = {NEW, ACTIVE, WAITING_APPROVAL}


class SubObjectiveStatus:
    TODO    = "TODO"
    READY   = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    DONE    = "DONE"
    FAILED  = "FAILED"
    SKIPPED = "SKIPPED"

    ACTIONABLE = {TODO, READY}
    TERMINAL   = {DONE, FAILED, SKIPPED}


# ── SubObjective ───────────────────────────────────────────────────────────────

@dataclass
class SubObjective:
    node_id:              str
    parent_objective_id:  str
    title:                str
    description:          str  = ""
    status:               str  = SubObjectiveStatus.TODO
    sequence_order:       int  = 0
    difficulty:           float = 0.5
    recommended_tools:    List[str] = field(default_factory=list)
    recommended_agents:   List[str] = field(default_factory=list)
    completion_signal:    str  = ""
    blocker_reason:       str  = ""
    retry_count:          int  = 0
    last_result:          str  = ""
    last_updated:         float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "node_id":             self.node_id,
            "parent_objective_id": self.parent_objective_id,
            "title":               self.title,
            "description":         self.description,
            "status":              self.status,
            "sequence_order":      self.sequence_order,
            "difficulty":          round(self.difficulty, 3),
            "recommended_tools":   self.recommended_tools,
            "recommended_agents":  self.recommended_agents,
            "completion_signal":   self.completion_signal,
            "blocker_reason":      self.blocker_reason,
            "retry_count":         self.retry_count,
            "last_result":         self.last_result[:200] if self.last_result else "",
            "last_updated":        self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SubObjective":
        return cls(
            node_id             = d.get("node_id", str(uuid.uuid4())[:8]),
            parent_objective_id = d.get("parent_objective_id", ""),
            title               = d.get("title", ""),
            description         = d.get("description", ""),
            status              = d.get("status", SubObjectiveStatus.TODO),
            sequence_order      = int(d.get("sequence_order", 0)),
            difficulty          = float(d.get("difficulty", 0.5)),
            recommended_tools   = list(d.get("recommended_tools", [])),
            recommended_agents  = list(d.get("recommended_agents", [])),
            completion_signal   = d.get("completion_signal", ""),
            blocker_reason      = d.get("blocker_reason", ""),
            retry_count         = int(d.get("retry_count", 0)),
            last_result         = d.get("last_result", ""),
            last_updated        = float(d.get("last_updated", time.time())),
        )


# ── Objective ──────────────────────────────────────────────────────────────────

@dataclass
class Objective:
    objective_id:             str
    title:                    str
    description:              str   = ""
    category:                 str   = "general"
    status:                   str   = ObjectiveStatus.NEW
    priority_score:           float = 0.5
    difficulty_score:         float = 0.5
    created_at:               float = field(default_factory=time.time)
    updated_at:               float = field(default_factory=time.time)
    source:                   str   = "user"
    owner:                    str   = "bea"
    parent_objective_id:      Optional[str] = None
    blocked_by:               List[str] = field(default_factory=list)
    depends_on:               List[str] = field(default_factory=list)
    success_criteria:         str   = ""
    current_progress:         float = 0.0
    next_recommended_action:  str   = ""
    last_execution_summary:   str   = ""
    related_patterns:         List[str] = field(default_factory=list)
    related_tools:            List[str] = field(default_factory=list)
    related_domains:          List[str] = field(default_factory=list)
    confidence:               float = 0.5
    archived:                 bool  = False
    sub_objectives:           List[SubObjective] = field(default_factory=list)
    history:                  List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "objective_id":            self.objective_id,
            "title":                   self.title,
            "description":             self.description,
            "category":                self.category,
            "status":                  self.status,
            "priority_score":          round(self.priority_score, 3),
            "difficulty_score":        round(self.difficulty_score, 3),
            "created_at":              self.created_at,
            "updated_at":              self.updated_at,
            "source":                  self.source,
            "owner":                   self.owner,
            "parent_objective_id":     self.parent_objective_id,
            "blocked_by":              self.blocked_by,
            "depends_on":              self.depends_on,
            "success_criteria":        self.success_criteria,
            "current_progress":        round(self.current_progress, 3),
            "next_recommended_action": self.next_recommended_action,
            "last_execution_summary":  self.last_execution_summary[:500] if self.last_execution_summary else "",
            "related_patterns":        self.related_patterns,
            "related_tools":           self.related_tools,
            "related_domains":         self.related_domains,
            "confidence":              round(self.confidence, 3),
            "archived":                self.archived,
            "sub_objectives":          [s.to_dict() for s in self.sub_objectives],
            "history":                 self.history[-20:],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Objective":
        sub_objs = [SubObjective.from_dict(s) for s in d.get("sub_objectives", [])]
        return cls(
            objective_id            = d.get("objective_id", str(uuid.uuid4())[:8]),
            title                   = d.get("title", ""),
            description             = d.get("description", ""),
            category                = d.get("category", "general"),
            status                  = d.get("status", ObjectiveStatus.NEW),
            priority_score          = float(d.get("priority_score", 0.5)),
            difficulty_score        = float(d.get("difficulty_score", 0.5)),
            created_at              = float(d.get("created_at", time.time())),
            updated_at              = float(d.get("updated_at", time.time())),
            source                  = d.get("source", "user"),
            owner                   = d.get("owner", "bea"),
            parent_objective_id     = d.get("parent_objective_id"),
            blocked_by              = list(d.get("blocked_by", [])),
            depends_on              = list(d.get("depends_on", [])),
            success_criteria        = d.get("success_criteria", ""),
            current_progress        = float(d.get("current_progress", 0.0)),
            next_recommended_action = d.get("next_recommended_action", ""),
            last_execution_summary  = d.get("last_execution_summary", ""),
            related_patterns        = list(d.get("related_patterns", [])),
            related_tools           = list(d.get("related_tools", [])),
            related_domains         = list(d.get("related_domains", [])),
            confidence              = float(d.get("confidence", 0.5)),
            archived                = bool(d.get("archived", False)),
            sub_objectives          = sub_objs,
            history                 = list(d.get("history", [])),
        )

    def add_history_entry(self, event: str, detail: str = "") -> None:
        """Ajoute une entrée dans l'historique (max 50, compressé si > 40)."""
        self.history.append({
            "ts":     time.time(),
            "event":  event,
            "detail": detail[:200] if detail else "",
        })
        if len(self.history) > 50:
            # Garder les 5 premières (contexte initial) + les 30 dernières
            self.history = self.history[:5] + self.history[-30:]

    def progress_summary(self) -> str:
        """Résumé compact de la progression."""
        total = len(self.sub_objectives)
        if total == 0:
            return f"status={self.status} progress={self.current_progress:.0%}"
        done  = sum(1 for s in self.sub_objectives if s.status in SubObjectiveStatus.TERMINAL)
        blocked = sum(1 for s in self.sub_objectives if s.status == SubObjectiveStatus.BLOCKED)
        return (
            f"status={self.status} sub={done}/{total}"
            + (f" blocked={blocked}" if blocked else "")
            + f" score={self.priority_score:.2f}"
        )
