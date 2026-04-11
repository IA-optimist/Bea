"""
JARVIS MAX — Canonical Types
==============================
Single source of truth for mission lifecycle, risk levels, and enum mappings.

This module defines the canonical enums and provides compatibility bridges
for all legacy enum definitions across the codebase.

Usage:
    from core.canonical_types import (
        CanonicalMissionStatus,
        CanonicalRiskLevel,
        map_legacy_mission_status,
        map_legacy_risk_level,
        LIFECYCLE_TRANSITIONS,
        validate_transition,
    )

Design:
    - Canonical enums are the authority.
    - Legacy enums remain untouched in their original modules.
    - Mapping functions bridge legacy → canonical (never the reverse in production).
    - Transition validator enforces deterministic lifecycle.

No imports from core.mission_system, core.meta_orchestrator, or core.state
to avoid circular dependencies. All mappings are string-based.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CANONICAL MISSION STATUS
# ═══════════════════════════════════════════════════════════════

class CanonicalMissionStatus(str, Enum):
    """
    Canonical mission lifecycle states.

    Deterministic transitions:
        CREATED → QUEUED → PLANNING → WAITING_APPROVAL → READY → RUNNING → REVIEW → COMPLETED
        Any non-terminal state → FAILED
        Any non-terminal state → CANCELLED

    Terminal states: COMPLETED, FAILED, CANCELLED
    """
    CREATED          = "CREATED"           # Mission submitted, not yet processed
    QUEUED           = "QUEUED"            # In queue, waiting for resources
    PLANNING         = "PLANNING"          # Intent detected, plan being built
    WAITING_APPROVAL = "WAITING_APPROVAL"  # Human approval required
    READY            = "READY"             # Approved, ready to execute
    RUNNING          = "RUNNING"           # Agents executing
    REVIEW           = "REVIEW"            # Execution complete, under review
    COMPLETED        = "COMPLETED"         # Terminal — success
    FAILED           = "FAILED"            # Terminal — failure
    CANCELLED        = "CANCELLED"         # Terminal — cancelled by user/system

    @property
    def is_terminal(self) -> bool:
        return self in (
            CanonicalMissionStatus.COMPLETED,
            CanonicalMissionStatus.FAILED,
            CanonicalMissionStatus.CANCELLED,
        )

    @property
    def is_active(self) -> bool:
        return self in (
            CanonicalMissionStatus.PLANNING,
            CanonicalMissionStatus.RUNNING,
            CanonicalMissionStatus.REVIEW,
        )

    @property
    def is_waiting(self) -> bool:
        return self in (
            CanonicalMissionStatus.QUEUED,
            CanonicalMissionStatus.WAITING_APPROVAL,
            CanonicalMissionStatus.READY,
        )


# ═══════════════════════════════════════════════════════════════
# LIFECYCLE TRANSITIONS (deterministic)
# ═══════════════════════════════════════════════════════════════

LIFECYCLE_TRANSITIONS: dict[CanonicalMissionStatus, set[CanonicalMissionStatus]] = {
    CanonicalMissionStatus.CREATED: {
        CanonicalMissionStatus.QUEUED,
        CanonicalMissionStatus.PLANNING,
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    CanonicalMissionStatus.QUEUED: {
        CanonicalMissionStatus.PLANNING,
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    CanonicalMissionStatus.PLANNING: {
        CanonicalMissionStatus.WAITING_APPROVAL,
        CanonicalMissionStatus.READY,
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    CanonicalMissionStatus.WAITING_APPROVAL: {
        CanonicalMissionStatus.READY,
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    CanonicalMissionStatus.READY: {
        CanonicalMissionStatus.RUNNING,
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    CanonicalMissionStatus.RUNNING: {
        CanonicalMissionStatus.REVIEW,
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    CanonicalMissionStatus.REVIEW: {
        CanonicalMissionStatus.COMPLETED,
        CanonicalMissionStatus.RUNNING,   # Re-run after review
        CanonicalMissionStatus.FAILED,
        CanonicalMissionStatus.CANCELLED,
    },
    # Terminal states — no outgoing transitions
    CanonicalMissionStatus.COMPLETED: set(),
    CanonicalMissionStatus.FAILED:    set(),
    CanonicalMissionStatus.CANCELLED: set(),
}


def validate_transition(
    current: CanonicalMissionStatus,
    target: CanonicalMissionStatus,
) -> bool:
    """
    Check if a status transition is valid.
    Returns True if allowed, False otherwise. Never raises.
    """
    try:
        allowed = LIFECYCLE_TRANSITIONS.get(current, set())
        return target in allowed
    except Exception:
        return False


class TransitionError(ValueError):
    """Raised when an invalid lifecycle transition is attempted."""
    def __init__(self, current: str, target: str, mission_id: str = ""):
        self.current = current
        self.target = target
        self.mission_id = mission_id
        super().__init__(
            f"Invalid transition: {current} → {target}"
            + (f" (mission={mission_id})" if mission_id else "")
        )


# ═══════════════════════════════════════════════════════════════
# CANONICAL RISK LEVEL
# ═══════════════════════════════════════════════════════════════

class CanonicalRiskLevel(str, Enum):
    """
    Canonical risk classification.

    Hierarchy (ascending risk):
        READ → WRITE_LOW → WRITE_HIGH → INFRA → DELETE → DEPLOY

    Approval rules:
        READ, WRITE_LOW    → auto-approve
        WRITE_HIGH+        → require human approval
    """
    READ       = "read"         # Pure observation — no side effects
    WRITE_LOW  = "write_low"    # Safe writes — new files, non-critical edits
    WRITE_HIGH = "write_high"   # Risky writes — core files, config changes
    INFRA      = "infra"        # Infrastructure — docker, services, ports
    DELETE     = "delete"       # Destructive — file deletion, data removal
    DEPLOY     = "deploy"       # Deployment — production-affecting actions

    @property
    def requires_approval(self) -> bool:
        return self not in (CanonicalRiskLevel.READ, CanonicalRiskLevel.WRITE_LOW)

    @property
    def severity_score(self) -> int:
        """Numeric severity 0-5 for comparison."""
        return {
            "read": 0, "write_low": 1, "write_high": 2,
            "infra": 3, "delete": 4, "deploy": 5,
        }.get(self.value, 2)


AUTO_APPROVE_LEVELS = frozenset({CanonicalRiskLevel.READ, CanonicalRiskLevel.WRITE_LOW})


# ═══════════════════════════════════════════════════════════════
# LEGACY ENUM MAPPINGS
# ═══════════════════════════════════════════════════════════════

# MissionSystem (core/mission_system.py) → Canonical
_MISSION_SYSTEM_STATUS_MAP: dict[str, CanonicalMissionStatus] = {
    "ANALYZING":          CanonicalMissionStatus.PLANNING,
    "PENDING_VALIDATION": CanonicalMissionStatus.WAITING_APPROVAL,
    "APPROVED":           CanonicalMissionStatus.READY,
    "EXECUTING":          CanonicalMissionStatus.RUNNING,
    "DONE":               CanonicalMissionStatus.COMPLETED,
    "REJECTED":           CanonicalMissionStatus.CANCELLED,
    "BLOCKED":            CanonicalMissionStatus.FAILED,
    "PLAN_ONLY":          CanonicalMissionStatus.COMPLETED,  # Plan created, no execution
}

# MetaOrchestrator (core/meta_orchestrator.py) → Canonical
_META_ORCHESTRATOR_STATUS_MAP: dict[str, CanonicalMissionStatus] = {
    "CREATED":  CanonicalMissionStatus.CREATED,
    "PLANNED":  CanonicalMissionStatus.READY,      # MetaOrch skips approval
    "RUNNING":  CanonicalMissionStatus.RUNNING,
    "REVIEW":   CanonicalMissionStatus.REVIEW,
    "DONE":     CanonicalMissionStatus.COMPLETED,
    "FAILED":   CanonicalMissionStatus.FAILED,
}

# WorkflowGraph (core/workflow_graph.py) → Canonical
_WORKFLOW_STAGE_MAP: dict[str, CanonicalMissionStatus] = {
    "PLANNING":          CanonicalMissionStatus.PLANNING,
    "SHADOW_CHECK":      CanonicalMissionStatus.PLANNING,
    "AWAITING_APPROVAL": CanonicalMissionStatus.WAITING_APPROVAL,
    "EXECUTING":         CanonicalMissionStatus.RUNNING,
    "DONE":              CanonicalMissionStatus.COMPLETED,
    "FAILED":            CanonicalMissionStatus.FAILED,
}

# core/state.py RiskLevel → Canonical
_STATE_RISK_MAP: dict[str, CanonicalRiskLevel] = {
    "low":    CanonicalRiskLevel.WRITE_LOW,
    "medium": CanonicalRiskLevel.WRITE_HIGH,
    "high":   CanonicalRiskLevel.INFRA,
}

# core/approval_queue.py RiskLevel → Canonical (already matches)
_APPROVAL_RISK_MAP: dict[str, CanonicalRiskLevel] = {
    "read":       CanonicalRiskLevel.READ,
    "write_low":  CanonicalRiskLevel.WRITE_LOW,
    "write_high": CanonicalRiskLevel.WRITE_HIGH,
    "infra":      CanonicalRiskLevel.INFRA,
    "delete":     CanonicalRiskLevel.DELETE,
    "deploy":     CanonicalRiskLevel.DEPLOY,
}


def map_legacy_mission_status(
    legacy_value: str,
    source: str = "mission_system",
) -> CanonicalMissionStatus:
    """
    Map a legacy mission status string to canonical status.

    Args:
        legacy_value: Status string from legacy system.
        source: Which legacy system ("mission_system", "meta_orchestrator", "workflow_graph").

    Returns:
        CanonicalMissionStatus. Defaults to CREATED if unknown. Never raises.
    """
    try:
        value = legacy_value.upper().strip()
        if source == "meta_orchestrator":
            return _META_ORCHESTRATOR_STATUS_MAP.get(value, CanonicalMissionStatus.CREATED)
        elif source == "workflow_graph":
            return _WORKFLOW_STAGE_MAP.get(value, CanonicalMissionStatus.CREATED)
        else:
            return _MISSION_SYSTEM_STATUS_MAP.get(value, CanonicalMissionStatus.CREATED)
    except Exception:
        return CanonicalMissionStatus.CREATED


def map_legacy_risk_level(
    legacy_value: str,
    source: str = "state",
) -> CanonicalRiskLevel:
    """
    Map a legacy risk level string to canonical risk.

    Args:
        legacy_value: Risk string from legacy system.
        source: Which legacy system ("state", "approval_queue").

    Returns:
        CanonicalRiskLevel. Defaults to WRITE_HIGH if unknown. Never raises.
    """
    try:
        value = legacy_value.lower().strip()
        if source == "approval_queue":
            return _APPROVAL_RISK_MAP.get(value, CanonicalRiskLevel.WRITE_HIGH)
        else:
            return _STATE_RISK_MAP.get(value, CanonicalRiskLevel.WRITE_HIGH)
    except Exception:
        return CanonicalRiskLevel.WRITE_HIGH


# ═══════════════════════════════════════════════════════════════
# CANONICAL MISSION CONTEXT
# ═══════════════════════════════════════════════════════════════

@dataclass
class CanonicalMissionContext:
    """
    Unified mission representation that all systems can produce/consume.

    This is the bridge type. Legacy systems convert their internal
    representation to/from this structure at boundary points.
    """
    mission_id:     str
    goal:           str
    status:         CanonicalMissionStatus = CanonicalMissionStatus.CREATED
    risk_level:     CanonicalRiskLevel = CanonicalRiskLevel.WRITE_LOW
    intent:         str = ""
    domain:         str = "general"
    plan_summary:   str = ""
    agents:         list[str] = field(default_factory=list)
    error:          str = ""
    result:         str = ""
    source_system:  str = ""      # "mission_system" | "meta_orchestrator" | "workflow_graph"
    created_at:     float = field(default_factory=time.time)
    updated_at:     float = field(default_factory=time.time)
    metadata:       dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal[:300],
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "intent": self.intent,
            "domain": self.domain,
            "plan_summary": self.plan_summary[:500],
            "agents": self.agents,
            "error": self.error,
            "result": self.result[:500],
            "source_system": self.source_system,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def transition(self, target: CanonicalMissionStatus) -> None:
        """
        Attempt a lifecycle transition. Raises TransitionError if invalid.
        """
        if not validate_transition(self.status, target):
            raise TransitionError(self.status.value, target.value, self.mission_id)
        prev = self.status
        self.status = target
        self.updated_at = time.time()
        try:
            log.info(
                "canonical_mission.transition",
                mission_id=self.mission_id,
                from_status=prev.value,
                to_status=target.value,
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='canonical_types.py')
