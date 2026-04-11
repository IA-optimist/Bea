"""
JARVIS MAX — État de session partagé
Source unique pour tous les types : RiskLevel, ActionSpec, JarvisSession.
Règle : aucun autre module ne redéfinit RiskLevel.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
_silent_log = __import__("structlog").get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# ENUMS — source unique, importés partout
# ══════════════════════════════════════════════════════════════

class SessionStatus(str, Enum):
    PENDING            = "pending"            # Session créée, pas encore démarrée
    RUNNING            = "running"
    WAITING_VALIDATION = "waiting_validation"
    DONE               = "done"               # Alias strict DONE (= COMPLETED)
    COMPLETED          = "completed"          # Rétrocompatibilité
    FAILED             = "failed"             # Alias strict FAILED (= ERROR)
    CANCELLED          = "cancelled"
    ERROR              = "error"              # Rétrocompatibilité


class MissionStatus(str, Enum):
    """
    SINGLE SOURCE OF TRUTH for mission lifecycle status.
    All other MissionStatus definitions MUST import from here.
    """
    CREATED             = "CREATED"
    ANALYZING           = "ANALYZING"
    PENDING_VALIDATION  = "PENDING_VALIDATION"
    APPROVED            = "APPROVED"
    EXECUTING           = "EXECUTING"
    DONE                = "DONE"
    REJECTED            = "REJECTED"
    BLOCKED             = "BLOCKED"
    PLAN_ONLY           = "PLAN_ONLY"
    # MetaOrchestrator statuses
    PLANNED             = "PLANNED"
    RUNNING             = "RUNNING"
    AWAITING_APPROVAL   = "AWAITING_APPROVAL"
    REVIEW              = "REVIEW"
    FAILED              = "FAILED"
    CANCELLED           = "CANCELLED"


class RiskLevel(str, Enum):
    """
    SOURCE UNIQUE. risk/engine.py importe depuis ici.
    Ne jamais redéfinir dans un autre module.
    """
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class TaskMode(str, Enum):
    """Mode de traitement détecté par le TaskRouter."""
    CHAT      = "chat"
    RESEARCH  = "research"
    PLAN      = "plan"
    CODE      = "code"
    AUTO      = "auto"
    NIGHT     = "night"
    IMPROVE   = "improve"
    BUSINESS  = "business"   # Business Layer : venture, offer, workflow, saas, trade_ops


# ══════════════════════════════════════════════════════════════
# AGENT OUTPUT
# ══════════════════════════════════════════════════════════════

@dataclass
class AgentOutput:
    agent:       str
    content:     str
    success:     bool
    error:       str | None = None
    duration_ms: int        = 0


# ══════════════════════════════════════════════════════════════
# ACTION SPEC
# ══════════════════════════════════════════════════════════════

@dataclass
class ActionSpec:
    """
    Action concrète préparée par PulseOps, classifiée par RiskEngine.
    Tous les champs sont des types simples pour sérialisation facile.
    """
    id:            str
    action_type:   str
    target:        str       = ""
    content:       str       = ""
    command:       str       = ""
    old_str:       str       = ""
    new_str:       str       = ""
    description:   str       = ""
    risk:          RiskLevel = RiskLevel.MEDIUM
    impact:        str       = ""
    backup_needed: bool      = False
    reversible:    bool      = True

    def brief(self) -> str:
        t = self.target or self.command
        return f"`{self.action_type}` -> `{t[:60]}`"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "target": self.target,
            "command": self.command,
            "description": self.description,
            "risk": self.risk.value,
            "impact": self.impact,
            "backup_needed": self.backup_needed,
            "reversible": self.reversible,
        }


# ══════════════════════════════════════════════════════════════
# JARVIS SESSION
# ══════════════════════════════════════════════════════════════

@dataclass
class JarvisSession:
    """
    Etat complet d une session. Passe a travers tout le pipeline.
    Tous les attributs doivent etre declares ici (pas d attributs dynamiques).
    """
    session_id:       str
    user_input:       str
    mode:             str      = "auto"
    created_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # API_chat_id: removed — use API approval instead
    event_stream:     Any      = field(default=None)  # Type Any pour éviter import circulaire direct
    metadata:         dict     = field(default_factory=dict)  # Ajout de metadata (manquant mais utilisé)

    # Planning
    mission_summary: str        = ""
    agents_plan:     list[dict] = field(default_factory=list)
    needs_actions:   bool       = False
    task_mode:       TaskMode   = TaskMode.AUTO

    # Agent outputs (cle = agent name)
    outputs: dict[str, AgentOutput] = field(default_factory=dict)

    # Actions
    actions_pending:  list[ActionSpec] = field(default_factory=list)
    actions_executed: list[dict]       = field(default_factory=list)
    actions_rejected: list[dict]       = field(default_factory=list)
    auto_count:       int              = 0

    # Night worker
    night_cycle:       int       = 0
    night_productions: list[str] = field(default_factory=list)

    # Self-improve (declare explicitement, pas d attribut dynamique)
    improve_pending: list[Any] = field(default_factory=list)

    # Output final
    final_report: str           = ""
    status:       SessionStatus = SessionStatus.RUNNING
    error:        str | None    = None

    # Internal raw actions avant classification risque
    _raw_actions: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.event_stream is None:
            # Lazy import pour éviter la circularité
            from core.event_stream import EventStream
            self.event_stream = EventStream(self.session_id)

    def set_output(self, agent: str, content: str, success: bool = True,
                   error: str | None = None, ms: int = 0):
        self.outputs[agent] = AgentOutput(
            agent=agent, content=content,
            success=success, error=error, duration_ms=ms,
        )
        
        # Emission de l'événement vers la v3
        try:
            from core.events import Observation
            import asyncio
            evt = Observation(
                source=agent,
                observation_type="agent_output",
                content=str(content)[:10000],  # Troncature sécurité
                is_error=not success,
                metadata={"duration_ms": ms, "error": error}
            )
            # Ajout sincrone au tableau interne + tentative notification async
            self.event_stream._events.append(evt)
            try:
                asyncio.get_running_loop().create_task(self._notify_subscribers(evt))
            except RuntimeError:
                pass  # Pas de boucle en cours — contexte synchrone
        except Exception:
            _silent_log.debug("suppressed_exception", src='state.py')

    async def _notify_subscribers(self, evt):
        for sub in self.event_stream._subscribers:
            try:
                await sub(evt)
            except Exception:
                _silent_log.debug("suppressed_exception", src='state.py')

    def get_output(self, agent: str) -> str:
        o = self.outputs.get(agent)
        return o.content if (o and o.success) else ""

    def context_snapshot(self, limit: int = 700) -> dict[str, str]:
        """Dict propre utilisable dans les prompts agents."""
        return {
            k: v.content[:limit]
            for k, v in self.outputs.items()
            if v.success and v.content
        }

    def ctx_block(self, skip: set | None = None, limit: int = 700) -> str:
        sk = skip or set()
        parts = [
            f"### {k}\n{v[:limit]}"
            for k, v in self.context_snapshot(limit).items()
            if k not in sk
        ]
        return "\n\n".join(parts)

    def summary_dict(self) -> dict:
        """Resume serialisable pour logs et persistance."""
        return {
            "session_id":   self.session_id,
            "mode":         self.mode,
            "status":       self.status.value,
            "mission":      self.mission_summary[:200],
            "agents_run":   list(self.outputs.keys()),
            "auto_actions": self.auto_count,
            "pending":      len(self.actions_pending),
            "executed":     len(self.actions_executed),
            "created_at":   self.created_at.isoformat(),
        }
