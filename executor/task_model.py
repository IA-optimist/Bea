"""
BEA MAX — ExecutionTask & ExecutionResult models
Modèles de données pour la couche d'exécution v2.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from executor.retry_policy import RetryPolicy

# ── Statuts ───────────────────────────────────────────────────────────────────

STATUS_PENDING   = "PENDING"
STATUS_RUNNING   = "RUNNING"
STATUS_SUCCEEDED = "SUCCEEDED"
STATUS_FAILED    = "FAILED"
STATUS_CANCELLED = "CANCELLED"
STATUS_TIMED_OUT = "TIMED_OUT"

TERMINAL_STATUSES = frozenset({
    STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED, STATUS_TIMED_OUT
})


# ── ExecutionTask ──────────────────────────────────────────────────────────────

@dataclass
class ExecutionTask:
    """
    Tâche d'exécution dans le moteur BeaMax.

    Cycle de vie : PENDING → RUNNING → SUCCEEDED / FAILED / CANCELLED / TIMED_OUT
    """
    # Identité
    id:             str   = field(default_factory=lambda: str(uuid.uuid4())[:12])
    mission_id:     str   = ""
    correlation_id: str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description:    str   = ""

    # Planification
    priority:       int   = 5        # 1 = haute, 9 = basse
    handler_name:   str   = "generic"
    payload:        dict[str, object] = field(default_factory=dict)

    # Retry / timeout
    max_attempts:   int   = 3
    timeout_seconds: float = 30.0
    retry_policy:   "RetryPolicy | None" = None  # injecté par l'appelant

    # État (géré par le moteur)
    status:         str   = STATUS_PENDING
    created_at:     float = field(default_factory=time.time)
    started_at:     float | None = None
    finished_at:    float | None = None
    attempts:       int   = 0
    result:         str   = ""
    error:          str   = ""

    # ── Méthodes ──────────────────────────────────────────────────────────────

    def __lt__(self, other: "ExecutionTask") -> bool:
        # Départage stable pour le heap (priority, created_at, task) quand priority
        # ET created_at sont égaux (collision de time.time()) — sinon heapq lève
        # TypeError en comparant deux ExecutionTask.
        if not isinstance(other, ExecutionTask):
            return NotImplemented
        return (self.created_at, self.id) < (other.created_at, other.id)

    def to_dict(self) -> dict[str, object]:
        rp = None
        if self.retry_policy is not None:
            rp = {
                "max_attempts":    self.retry_policy.max_attempts,
                "base_delay":      self.retry_policy.base_delay,
                "max_delay":       self.retry_policy.max_delay,
                "backoff_factor":  self.retry_policy.backoff_factor,
            }
        return {
            "id":              self.id,
            "mission_id":      self.mission_id,
            "correlation_id":  self.correlation_id,
            "description":     self.description,
            "priority":        self.priority,
            "handler_name":    self.handler_name,
            "payload":         self.payload,
            "max_attempts":    self.max_attempts,
            "timeout_seconds": self.timeout_seconds,
            "status":          self.status,
            "created_at":      self.created_at,
            "started_at":      self.started_at,
            "finished_at":     self.finished_at,
            "attempts":        self.attempts,
            "result":          self.result,
            "error":           self.error,
            "retry_policy":    rp,
        }

    def elapsed(self) -> float | None:
        """Durée d'exécution en secondes si la tâche est terminée."""
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at

    def is_terminal(self) -> bool:
        """True si la tâche est dans un état terminal (plus de transitions)."""
        return self.status in TERMINAL_STATUSES


# ── ExecutionResult ────────────────────────────────────────────────────────────
# CANONICAL model lives in executor/contracts.py.
# Re-exported here for backward compatibility.
from executor.contracts import ExecutionResult  # noqa: F401
