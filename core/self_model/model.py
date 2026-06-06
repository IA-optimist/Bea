"""
core/self_model/model.py — JarvisMax Self-Model data structures.

The Self-Model is a structured introspection layer that aggregates runtime
truth into a queryable internal model. It answers:

  - What can I do right now?
  - What is degraded / unavailable / requires approval?
  - What is safe vs unsafe for autonomous modification?
  - What components are missing or misconfigured?

All data is derived from real runtime sources — never invented.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum


# ── Status enums ──────────────────────────────────────────────────────────────

class CapabilityStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    APPROVAL_REQUIRED = "approval_required"
    EXPERIMENTAL = "experimental"
    NOT_CONFIGURED = "not_configured"


class ComponentStatus(str, Enum):
    READY = "ready"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    MISSING_SECRET = "missing_secret"  # nosec B105 — enum status label
    ERROR = "error"
    APPROVAL_REQUIRED = "approval_required"
    UNAVAILABLE = "unavailable"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class AutonomyMode(str, Enum):
    OBSERVE = "observe"
    PROPOSE_ONLY = "propose_only"
    SUPERVISED_EXECUTE = "supervised_execute"
    SANDBOX_SELF_IMPROVE = "sandbox_self_improve"
    RESTRICTED_AUTONOMOUS = "restricted_autonomous"


class ModificationZone(str, Enum):
    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    FORBIDDEN = "forbidden"


# ── Capability entry ──────────────────────────────────────────────────────────

@dataclass
class CapabilityEntry:
    """A single capability known to the system."""
    id: str                                          # e.g. "code.python.patch"
    name: str = ""                                   # Human-readable name
    status: CapabilityStatus = CapabilityStatus.UNAVAILABLE
    source: str = ""                                 # agent / tool / module / mcp
    confidence: float = 0.0                          # 0.0–1.0
    risk_level: str = "low"                          # low / medium / high / critical
    dependencies: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)  # e.g. ["requires_approval"]
    last_success_ts: float = 0.0                     # Unix timestamp
    last_failure_ts: float = 0.0
    usage_count: int = 0
    failure_count: int = 0
    error: str = ""

    @property
    def reliability(self) -> float:
        """Success rate based on usage history."""
        total = self.usage_count + self.failure_count
        if total == 0:
            return 0.0
        return self.usage_count / total

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reliability"] = round(self.reliability, 3)
        d["status"] = self.status.value
        return d


# ── Component entry (MCP / Tool / Connector) ─────────────────────────────────

@dataclass
class ComponentEntry:
    """A runtime component: MCP server, tool, or connector."""
    id: str                                          # e.g. "mcp-filesystem"
    type: str = ""                                   # mcp / tool / connector
    status: ComponentStatus = ComponentStatus.UNAVAILABLE
    reason: str = ""                                 # Why this status
    required_secrets: list[str] = field(default_factory=list)
    missing_secrets: list[str] = field(default_factory=list)
    health_check_ts: float = 0.0
    spawnable: bool = False
    trust_level: str = ""                            # official / vendor / managed / community
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ── Health signal ─────────────────────────────────────────────────────────────

@dataclass
class HealthSignal:
    """A system-level health indicator."""
    name: str                                        # e.g. "auth_system"
    status: HealthStatus = HealthStatus.UNKNOWN
    detail: str = ""
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "checked_at": self.checked_at,
        }


# ── Modification boundary ────────────────────────────────────────────────────

@dataclass
class ModificationBoundary:
    """What the system is allowed/restricted from modifying."""
    zone: ModificationZone
    description: str = ""
    paths: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "zone": self.zone.value,
            "description": self.description,
            "paths": self.paths,
            "examples": self.examples,
        }


# ── Autonomy envelope ────────────────────────────────────────────────────────

@dataclass
class AutonomyEnvelope:
    """Current autonomy boundaries for the system."""
    mode: AutonomyMode = AutonomyMode.SUPERVISED_EXECUTE
    requires_approval_for_tools: bool = True
    requires_approval_for_code_patch: bool = True
    requires_approval_for_external_calls: bool = True
    requires_approval_for_deployment: bool = True
    max_risk_auto_approve: str = "low"               # low / medium / high
    max_files_per_patch: int = 3
    max_steps_per_mission: int = 50

    def to_dict(self) -> dict:
        return asdict(self)


# ── Complete Self-Model ───────────────────────────────────────────────────────

@dataclass
class SelfModel:
    """
    The complete self-model of JarvisMax at a point in time.

    This is the single source of truth for "what can I do right now?"
    All fields are derived from real runtime sources via the Updater.
    """
    # Metadata
    version: str = "1.0.0"
    generated_at: float = field(default_factory=time.time)
    generation_duration_ms: float = 0.0

    # Dimensions
    capabilities: dict[str, CapabilityEntry] = field(default_factory=dict)
    components: dict[str, ComponentEntry] = field(default_factory=dict)
    health: dict[str, HealthSignal] = field(default_factory=dict)
    boundaries: list[ModificationBoundary] = field(default_factory=list)
    autonomy: AutonomyEnvelope = field(default_factory=AutonomyEnvelope)

    # Summaries (computed by serializer)
    summary: dict = field(default_factory=dict)

    # Extended metadata (canonical agents, specialist packs, etc.)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "generation_duration_ms": round(self.generation_duration_ms, 1),
            "capabilities": {k: v.to_dict() for k, v in self.capabilities.items()},
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "health": {k: v.to_dict() for k, v in self.health.items()},
            "boundaries": [b.to_dict() for b in self.boundaries],
            "autonomy": self.autonomy.to_dict(),
            "summary": self.summary,
        }
