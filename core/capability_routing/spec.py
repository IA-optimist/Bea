"""
core/capability_routing/spec.py — Canonical data contracts.

Every provider that can satisfy a capability must declare itself
using ProviderSpec. The router uses these to score and select.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderType(str, Enum):
    """What kind of execution backend is this provider?"""
    AGENT = "agent"
    TOOL = "tool"
    MCP = "mcp"
    MODULE = "module"
    CONNECTOR = "connector"


class ProviderStatus(str, Enum):
    """Current operational state."""
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    APPROVAL_REQUIRED = "approval_required"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"


@dataclass
class ProviderSpec:
    """
    Declaration of a capability provider.

    Every provider must at minimum declare: what capability it satisfies,
    what kind of backend it is, and its current readiness.
    """
    provider_id: str
    provider_type: ProviderType
    capability_id: str
    status: ProviderStatus = ProviderStatus.READY
    readiness: float = 1.0          # 0.0-1.0, from Self-Model or health probe
    reliability: float = 0.5        # 0.0-1.0, from past outcome history
    confidence: float = 0.5         # How well does this provider match the capability
    requires_approval: bool = False
    risk_level: str = "low"         # low / medium / high / critical
    dependencies: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    estimated_latency_ms: float = 0.0
    constraints: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        """Can this provider be used right now (ignoring approval)?"""
        return self.status in (ProviderStatus.READY, ProviderStatus.DEGRADED)

    @property
    def is_blocked(self) -> bool:
        """Is this provider completely blocked?"""
        return self.status in (
            ProviderStatus.UNAVAILABLE,
            ProviderStatus.NOT_CONFIGURED,
            ProviderStatus.DISABLED,
        )

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type.value,
            "capability_id": self.capability_id,
            "status": self.status.value,
            "readiness": round(self.readiness, 2),
            "reliability": round(self.reliability, 2),
            "confidence": round(self.confidence, 2),
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "dependencies": self.dependencies,
            "missing_dependencies": self.missing_dependencies,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "estimated_latency_ms": round(self.estimated_latency_ms, 1),
            "constraints": self.constraints,
        }


@dataclass
class RoutingDecision:
    """
    The output of capability routing.

    Contains the selected provider, scoring breakdown, and all candidates
    that were evaluated (for explainability + learning).
    """
    capability_id: str
    selected_provider: ProviderSpec | None
    score: float = 0.0
    reason: str = ""
    fallback_used: bool = False
    candidates_evaluated: int = 0
    all_candidates: list[dict] = field(default_factory=list)
    blocked_candidates: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.selected_provider is not None

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "selected": self.selected_provider.to_dict() if self.selected_provider else None,
            "score": round(self.score, 3),
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "candidates_evaluated": self.candidates_evaluated,
            "all_candidates": self.all_candidates,
            "blocked_candidates": self.blocked_candidates,
            "metadata": self.metadata,
        }


@dataclass
class CapabilityRequirement:
    """
    What a mission needs — extracted from goal classification.

    The router maps this to candidate providers via the registry.
    """
    capability_id: str
    required: bool = True           # False = nice-to-have
    min_reliability: float = 0.0    # Minimum acceptable reliability
    max_risk: str = "high"          # Maximum acceptable risk level
    prefer_type: ProviderType | None = None  # Preference, not hard constraint
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "required": self.required,
            "min_reliability": self.min_reliability,
            "max_risk": self.max_risk,
            "prefer_type": self.prefer_type.value if self.prefer_type else None,
        }
