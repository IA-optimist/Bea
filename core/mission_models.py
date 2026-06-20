"""Mission dataclasses shared by the mission system and API layers."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from core.state import MissionStatus
# ── Modèles ───────────────────────────────────────────────────────────────────

@dataclass
class MissionStep:
    """Étape proposée dans le plan."""
    agent:       str    # "scout-research", "forge-builder", etc.
    task:        str    # description de la tâche
    priority:    int    = 1
    risk:        str    = "LOW"
    action_type: str    = "analyze"  # analyze | create | modify | review
    target:      str    = ""         # fichier / service cible


@dataclass
class MissionPlan:
    """Plan structuré pour une mission."""
    intent:      str
    summary:     str
    steps:       list[MissionStep] = field(default_factory=list)
    estimated_risk: str = "LOW"
    rationale:   str    = ""


@dataclass
class MissionResult:
    """Résultat complet d'une mission (de l'analyse à l'exécution)."""
    mission_id:     str
    user_input:     str
    intent:         str
    status:         str

    # Plan
    plan_summary:   str               = ""
    plan_steps:     list[dict]        = field(default_factory=list)
    plan_risk:      str               = "LOW"

    # Advisory
    advisory_score:    float          = 0.0
    advisory_decision: str            = "UNKNOWN"
    advisory_issues:   list[dict]     = field(default_factory=list)
    advisory_risks:    list[dict]     = field(default_factory=list)
    advisory_text:     str            = ""

    # Actions générées
    action_ids:     list[str]         = field(default_factory=list)

    # Risk scoring numérique (Phase 4)
    risk_score:     int               = 0   # 0-10
    complexity:     str               = "medium"  # "low" | "medium" | "high"

    # Trace d'exécution agents (Phase 2)
    execution_trace: list[dict]       = field(default_factory=list)

    # Decision trace unifié (Phase DQ v2)
    decision_trace: dict              = field(default_factory=dict)

    # Champs V1 standardisés
    final_output:     str             = ""    # toujours présent (lens-reviewer ou summary)
    summary:          str             = ""    # résumé 500 chars max
    agents_selected:  list[str]       = field(default_factory=list)
    domain:           str             = "general"

    # Phase checkpointing (ADR-003): last completed phase, empty if not started.
    # Written at each phase boundary by MetaOrchestrator for crash recovery.
    phase_cursor: str                 = ""

    # Méta
    requires_validation: bool         = True
    created_at:   float               = field(default_factory=time.time)
    updated_at:   float               = field(default_factory=time.time)
    error:        str                 = ""

    def is_blocked(self)   -> bool: return self.status == MissionStatus.BLOCKED
    def is_done(self)      -> bool: return self.status == MissionStatus.DONE
    def is_pending(self)   -> bool: return self.status == MissionStatus.PENDING_VALIDATION
    def is_executing(self) -> bool: return self.status == MissionStatus.EXECUTING

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        status_icon = {
            "ANALYZING": "🔍", "PENDING_VALIDATION": "⏳", "APPROVED": "✅",
            "EXECUTING": "🚀", "DONE": "🎯", "REJECTED": "❌", "BLOCKED": "🚫",
        }.get(self.status, "?")
        return (
            f"{status_icon} [{self.mission_id[:8]}] {self.intent} — "
            f"{self.plan_summary[:50]} | "
            f"advisory={self.advisory_decision} ({self.advisory_score:.1f})"
        )

    @classmethod
    def from_dict(cls, d: dict) -> "MissionResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
