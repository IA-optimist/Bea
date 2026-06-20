# BeaMax — Typed Inter-Agent Contracts
"""
core/contracts.py

Schémas Pydantic v2 pour tous les échanges inter-agents.
Ces contrats remplacent les strings brutes dans session.set_output().

Usage :
    from core.contracts import AgentResult, TaskContract, ErrorReport

    # Dans un agent :
    result = AgentResult(
        task_id="...",
        agent="scout-research",
        success=True,
        content="## Synthèse...",
        duration_ms=1820,
    )
    session.set_typed_output(self.name, result)
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════

class TaskState(str, Enum):
    PENDING   = "pending"
    ASSIGNED  = "assigned"
    RUNNING   = "running"
    RETRYING  = "retrying"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    SKIPPED   = "skipped"


class ErrorSeverity(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class RootCauseType(str, Enum):
    TIMEOUT       = "timeout"
    LLM_ERROR     = "llm_error"
    PARSE_ERROR   = "parse_error"
    SECURITY      = "security"
    CONFIGURATION = "configuration"
    LOGIC         = "logic"
    NETWORK       = "network"
    UNKNOWN       = "unknown"


class HealthStatus(str, Enum):
    OK        = "ok"
    DEGRADED  = "degraded"
    DOWN      = "down"
    UNKNOWN   = "unknown"


class AdvisoryDecision(str, Enum):
    GO      = "GO"
    IMPROVE = "IMPROVE"
    NO_GO   = "NO-GO"


# ═══════════════════════════════════════════════════════════════
# TASK CONTRACT — Définition d'une tâche agent
# ═══════════════════════════════════════════════════════════════

class RetryConfig(BaseModel):  # type: ignore[misc]
    """Configuration du retry pour une tâche agent."""
    max_attempts:   int   = Field(default=3, ge=1, le=10)
    base_delay_s:   float = Field(default=2.0, ge=0.1)
    max_delay_s:    float = Field(default=30.0, ge=1.0)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    jitter:         bool  = True
    retryable_errors: list[str] = Field(
        default=["TimeoutError", "ConnectError", "ConnectionRefusedError"]
    )


class TaskContract(BaseModel):  # type: ignore[misc]
    """Contrat de tâche inter-agents — définition standardisée d'une tâche."""
    task_id:      str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    mission_id:   str = ""
    agent:        str
    task:         str
    priority:     int = Field(default=2, ge=1, le=4)
    timeout_s:    int = Field(default=120, ge=5)
    retry_config: RetryConfig = Field(default_factory=RetryConfig)
    depends_on:   list[str] = Field(default_factory=list)  # task_ids
    metadata:     dict[str, Any] = Field(default_factory=dict)
    created_at:   float = Field(default_factory=time.time)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    model_config = {"use_enum_values": True}


# ═══════════════════════════════════════════════════════════════
# AGENT RESULT — Sortie typée d'un agent
# ═══════════════════════════════════════════════════════════════

class AgentResult(BaseModel):  # type: ignore[misc]
    """Résultat structuré d'un agent — remplace les strings brutes."""
    task_id:      str = ""
    agent:        str
    success:      bool
    content:      str = ""         # sortie principale (markdown, JSON string, etc.)
    error:        str = ""         # message d'erreur si success=False
    duration_ms:  int = 0
    retry_count:  int = 0
    metadata:     dict[str, Any] = Field(default_factory=dict)
    created_at:   float = Field(default_factory=time.time)
    correlation_id: str = ""

    @property
    def is_empty(self) -> bool:
        return not bool(self.content)

    def short_summary(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"[{status}] {self.agent} ({self.duration_ms}ms): {self.content[:100]}"

    model_config = {"use_enum_values": True}


# ═══════════════════════════════════════════════════════════════
# AGENT MESSAGE — Échange direct entre agents
# ═══════════════════════════════════════════════════════════════

class AgentMessage(BaseModel):  # type: ignore[misc]
    """Message tracé entre deux agents."""
    message_id:     str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    sender:         str
    recipient:      str
    payload:        dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""
    mission_id:     str = ""
    timestamp:      float = Field(default_factory=time.time)
    message_type:   str = "generic"  # generic | task_result | error | handoff


# ═══════════════════════════════════════════════════════════════
# ERROR REPORT — Rapport d'erreur structuré
# ═══════════════════════════════════════════════════════════════

class ErrorReport(BaseModel):  # type: ignore[misc]
    """Rapport d'erreur structuré pour DebugAgent."""
    error_id:       str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent:          str
    task_id:        str = ""
    mission_id:     str = ""
    error_type:     str
    message:        str
    traceback:      str = ""
    context:        dict[str, Any] = Field(default_factory=dict)
    severity:       ErrorSeverity = ErrorSeverity.MEDIUM
    root_cause:     RootCauseType = RootCauseType.UNKNOWN
    retry_count:    int = 0
    max_retries:    int = 3
    timestamp:      float = Field(default_factory=time.time)
    correlation_id: str = ""
    is_retryable:   bool = True

    model_config = {"use_enum_values": True}

    @classmethod
    def from_exception(
        cls,
        e: Exception,
        agent: str,
        task_id: str = "",
        mission_id: str = "",
        retry_count: int = 0,
        correlation_id: str = "",
    ) -> "ErrorReport":
        import traceback as tb
        error_type = type(e).__name__
        is_retryable = error_type in (
            "TimeoutError", "asyncio.TimeoutError", "ConnectError",
            "ConnectionRefusedError", "OSError"
        )
        root_cause = (
            RootCauseType.TIMEOUT if "timeout" in error_type.lower()
            else RootCauseType.NETWORK if "connect" in error_type.lower()
            else RootCauseType.UNKNOWN
        )
        return cls(
            agent=agent,
            task_id=task_id,
            mission_id=mission_id,
            error_type=error_type,
            message=str(e)[:500],
            traceback=tb.format_exc()[:2000],
            root_cause=root_cause,
            is_retryable=is_retryable,
            retry_count=retry_count,
            correlation_id=correlation_id,
        )


# ═══════════════════════════════════════════════════════════════
# HEALTH REPORT — Rapport de santé d'un composant
# ═══════════════════════════════════════════════════════════════

class ComponentHealth(BaseModel):  # type: ignore[misc]
    """Santé d'un composant individuel."""
    name:       str
    status:     HealthStatus = HealthStatus.UNKNOWN
    latency_ms: int = 0
    error:      str = ""
    metadata:   dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class HealthReport(BaseModel):  # type: ignore[misc]
    """Rapport de santé global du système."""
    status:     HealthStatus = HealthStatus.UNKNOWN
    components: dict[str, ComponentHealth] = Field(default_factory=dict)
    checked_at: float = Field(default_factory=time.time)
    version:    str = "2.0"

    def is_healthy(self) -> bool:
        return self.status == HealthStatus.OK

    def summary(self) -> str:
        ok = sum(1 for c in self.components.values() if c.status == HealthStatus.OK)
        total = len(self.components)
        return f"status={self.status} ({ok}/{total} composants OK)"

    model_config = {"use_enum_values": True}


# ═══════════════════════════════════════════════════════════════
# EXECUTION RESULT — Résultat d'une action concrète
# ═══════════════════════════════════════════════════════════════

class ExecutionResultSchema(BaseModel):  # type: ignore[misc]
    """Schéma Pydantic pour les résultats d'exécution d'actions."""
    success:     bool
    action_type: str
    target:      str
    output:      str = ""
    error:       str = ""
    backup_path: str = ""
    duration_ms: int = 0
    risk:        str = "LOW"
    session_id:  str = ""
    agent:       str = ""
    correlation_id: str = ""
    timestamp:   float = Field(default_factory=time.time)

    def is_rejected_by_whitelist(self) -> bool:
        return "whitelist" in self.error.lower()

    def summary_format(self) -> str:
        icon = "OK" if self.success else "ERREUR"
        lines = [f"[{icon}] {self.action_type}", f"Cible : {self.target[:80]}"]
        if self.backup_path:
            from pathlib import Path
            lines.append(f"Backup : {Path(self.backup_path).name}")
        if self.output:
            preview = self.output[:500] + ("..." if len(self.output) > 500 else "")
            lines.append(f"\n{preview}")
        if self.error:
            lines.append(f"Erreur : {self.error[:200]}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# MISSION LIFECYCLE — État d'une mission avec historique
# ═══════════════════════════════════════════════════════════════

class MissionTransition(BaseModel):  # type: ignore[misc]
    """Une transition d'état dans le cycle de vie d'une mission."""
    from_state: str
    to_state:   str
    timestamp:  float = Field(default_factory=time.time)
    reason:     str = ""
    agent:      str = ""


class MissionLifecycle(BaseModel):  # type: ignore[misc]
    """Cycle de vie complet d'une mission avec historique des transitions."""
    mission_id:   str
    current_state: str = "intake"
    transitions:  list[MissionTransition] = Field(default_factory=list)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at:   float = Field(default_factory=time.time)
    updated_at:   float = Field(default_factory=time.time)

    def transition(self, to_state: str, reason: str = "", agent: str = "") -> None:
        t = MissionTransition(
            from_state=self.current_state,
            to_state=to_state,
            reason=reason,
            agent=agent,
        )
        self.transitions.append(t)
        self.current_state = to_state
        self.updated_at = time.time()

    def duration_s(self) -> float:
        return time.time() - self.created_at

    def history_summary(self) -> str:
        return " → ".join(t.to_state for t in self.transitions)

    model_config = {"use_enum_values": True}


# ═══════════════════════════════════════════════════════════════
# ADVISORY REPORT — Rapport ShadowAdvisor standardisé
# ═══════════════════════════════════════════════════════════════

class BlockingIssue(BaseModel):  # type: ignore[misc]
    type:        str
    description: str
    severity:    str = "medium"
    evidence:    str = ""


class RiskItem(BaseModel):  # type: ignore[misc]
    type:        str
    description: str
    severity:    str = "medium"
    probability: str = "medium"
    impact:      str = "medium"


class AdvisoryReport(BaseModel):  # type: ignore[misc]
    """Rapport structuré du ShadowAdvisor."""
    decision:        AdvisoryDecision = AdvisoryDecision.IMPROVE
    confidence:      float = Field(default=0.5, ge=0.0, le=1.0)
    blocking_issues: list[BlockingIssue] = Field(default_factory=list)
    risks:           list[RiskItem] = Field(default_factory=list)
    weak_points:     list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    missing_proofs:  list[str] = Field(default_factory=list)
    improvements:    list[str] = Field(default_factory=list)
    tests_required:  list[str] = Field(default_factory=list)
    final_score:     float = Field(default=5.0, ge=0.0, le=10.0)
    justification:   str = ""

    def blocking_count(self) -> int:
        return len(self.blocking_issues)

    def is_go(self) -> bool:
        return self.decision == AdvisoryDecision.GO

    model_config = {"use_enum_values": True}
