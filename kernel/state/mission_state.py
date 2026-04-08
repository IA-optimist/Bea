"""
kernel/state/mission_state.py — Canonical Mission State Machine
================================================================
KERNEL RULE K1: ZERO imports from core/, agents/, api/, tools/.
All state transitions are deterministic and side-effect-free.
Side effects (event emission, persistence) remain in MetaOrchestrator.

Pass 12: MissionStatus is now defined HERE as the kernel-canonical source.
core/state.py keeps its own identical MissionStatus definition — both are
interoperable via string comparison since (str, Enum) members hash and
compare as their string value.

Contents:
  MissionStatus         — lifecycle enum (kernel-canonical, Pass 12)
  MissionContext        — pure data snapshot (no business logic)
  VALID_TRANSITIONS     — deterministic transition table
  MissionStateMachine   — validates and applies transitions (no side effects)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── MissionStatus — kernel-canonical definition (Pass 12) ────────────────────
# Defined here. core/state.py has an identical definition (same string values).
# Interoperability: (str, Enum) members hash/compare by string value, so
# {kernel.MissionStatus.DONE} lookup accepts core.MissionStatus.DONE ("DONE").
# K1 RULE: no import from core/ anywhere in this module.
class MissionStatus(str, Enum):
    CREATED            = "CREATED"
    PLANNED            = "PLANNED"
    RUNNING            = "RUNNING"
    AWAITING_APPROVAL  = "AWAITING_APPROVAL"
    REVIEW             = "REVIEW"
    DONE               = "DONE"
    FAILED             = "FAILED"
    CANCELLED          = "CANCELLED"


# ── Deterministic transition table ───────────────────────────────────────────
# Source of truth for all valid state transitions.
# Any code that checks transitions must use this table.
VALID_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.CREATED:           {MissionStatus.PLANNED,  MissionStatus.FAILED},
    MissionStatus.PLANNED:           {MissionStatus.RUNNING,  MissionStatus.FAILED},
    MissionStatus.RUNNING:           {MissionStatus.REVIEW,   MissionStatus.FAILED,
                                      MissionStatus.AWAITING_APPROVAL},
    MissionStatus.AWAITING_APPROVAL: {MissionStatus.RUNNING,  MissionStatus.FAILED,
                                      MissionStatus.CANCELLED},
    MissionStatus.REVIEW:            {MissionStatus.DONE,     MissionStatus.RUNNING,
                                      MissionStatus.FAILED},
    MissionStatus.DONE:              set(),   # terminal
    MissionStatus.FAILED:            set(),   # terminal
    MissionStatus.CANCELLED:         set(),   # terminal
}


# ── Mission Context — pure data, no side effects ──────────────────────────────
@dataclass
class MissionContext:
    """
    Snapshot of a mission's state at a point in time.

    Pure data — no event emission, no persistence, no imports from core.
    Side effects (emit, persist) are the responsibility of the orchestrator
    that owns this context.
    """
    mission_id: str
    goal:       str
    mode:       str
    status:     MissionStatus
    created_at: float
    updated_at: float
    result:     str | None = None
    error:      str | None = None
    metadata:   dict       = field(default_factory=dict)
    project_id: str | None = None  # Phase 2: Multi-project isolation

    def get_output(self, agent: str) -> str:
        """Get agent output — compatibility with JarvisSession interface."""
        outputs = self.metadata.get("agent_outputs", {})
        if isinstance(outputs, dict):
            out = outputs.get(agent, "")
            return out if isinstance(out, str) else str(out) if out else ""
        return ""

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal":       self.goal[:200],
            "mode":       self.mode,
            "status":     self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result":     self.result or "",
            "error":      self.error,
            "metadata":   self.metadata,
        }

    def is_terminal(self) -> bool:
        """Return True if no further transitions are possible."""
        return not VALID_TRANSITIONS.get(self.status)

    def can_transition_to(self, target: MissionStatus) -> bool:
        """Return True if transitioning to target is valid from current status."""
        return target in VALID_TRANSITIONS.get(self.status, set())


# ── Mission State Machine — validates + applies transitions ───────────────────
class MissionStateMachine:
    """
    Validates and applies state transitions. Zero side effects.

    Usage:
      sm = MissionStateMachine()
      sm.apply(ctx, MissionStatus.PLANNED)   # raises ValueError if invalid
      sm.is_valid(ctx.status, MissionStatus.PLANNED)  # True/False

    Side effects (event emission, persistence) are NOT performed here.
    The orchestrator must handle those after calling apply().
    """

    def is_valid(self, current: MissionStatus, target: MissionStatus) -> bool:
        """Return True if transition current → target is allowed."""
        return target in VALID_TRANSITIONS.get(current, set())

    def apply(self, ctx: MissionContext, target: MissionStatus) -> MissionStatus:
        """
        Validate and apply a state transition.

        Updates ctx.status and ctx.updated_at in place.
        Returns the previous status.
        Raises ValueError if the transition is invalid.
        """
        if not self.is_valid(ctx.status, target):
            raise ValueError(
                f"Transition invalide: {ctx.status.value} → {target.value} "
                f"(mission={ctx.mission_id})"
            )
        prev = ctx.status
        ctx.status     = target
        ctx.updated_at = time.time()
        return prev

    def available_transitions(self, ctx: MissionContext) -> list[MissionStatus]:
        """Return the list of valid next statuses from ctx.status."""
        return list(VALID_TRANSITIONS.get(ctx.status, set()))


# ── Module-level singleton ────────────────────────────────────────────────────
_state_machine: MissionStateMachine | None = None


def get_state_machine() -> MissionStateMachine:
    """Return the singleton MissionStateMachine."""
    global _state_machine
    if _state_machine is None:
        _state_machine = MissionStateMachine()
    return _state_machine
