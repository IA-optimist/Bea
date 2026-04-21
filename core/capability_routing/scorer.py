"""
core/capability_routing/scorer.py — Provider scoring.

Scores candidate providers for a capability requirement using weighted
dimensions from real runtime data. Deterministic, explainable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.capability_routing.spec import (
    ProviderSpec, CapabilityRequirement,
)


# ── Scoring weights (tunable) ────────────────────────────────

@dataclass
class ScoringWeights:
    """Weights for each scoring dimension. Must sum to ~1.0."""
    readiness: float = 0.25
    reliability: float = 0.30
    confidence: float = 0.15
    risk_penalty: float = 0.10
    cost_penalty: float = 0.05
    latency_penalty: float = 0.05
    type_preference: float = 0.10


DEFAULT_WEIGHTS = ScoringWeights()


# ── Risk scoring map ─────────────────────────────────────────

_RISK_SCORES = {
    "low": 1.0,
    "medium": 0.7,
    "high": 0.4,
    "critical": 0.1,
}

_RISK_LEVELS = ("low", "medium", "high", "critical")


@dataclass
class ScoredProvider:
    """A provider with its computed score and breakdown."""
    provider: ProviderSpec
    total_score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    blocked: bool = False
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider.provider_id,
            "provider_type": self.provider.provider_type.value,
            "total_score": round(self.total_score, 3),
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "breakdown": {k: round(v, 3) for k, v in self.breakdown.items()},
        }


def score_provider(
    provider: ProviderSpec,
    requirement: CapabilityRequirement,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> ScoredProvider:
    """
    Score a single provider against a requirement.

    Returns ScoredProvider with total_score (0.0-1.0) and breakdown.
    Blocked providers get score=0.0 and blocked_reason.
    """
    result = ScoredProvider(provider=provider)

    # ── Hard blocks ───────────────────────────────────────────

    # 1. Provider is unavailable/disabled/not_configured
    if provider.is_blocked:
        result.blocked = True
        result.blocked_reason = f"status={provider.status.value}"
        return result

    # 2. Risk exceeds requirement max
    provider_risk_idx = _RISK_LEVELS.index(provider.risk_level) \
        if provider.risk_level in _RISK_LEVELS else 0
    max_risk_idx = _RISK_LEVELS.index(requirement.max_risk) \
        if requirement.max_risk in _RISK_LEVELS else 2
    if provider_risk_idx > max_risk_idx:
        result.blocked = True
        result.blocked_reason = f"risk={provider.risk_level} exceeds max={requirement.max_risk}"
        return result

    # 3. Reliability below minimum
    if requirement.min_reliability > 0 and provider.reliability < requirement.min_reliability:
        result.blocked = True
        result.blocked_reason = (
            f"reliability={provider.reliability:.2f} < min={requirement.min_reliability:.2f}"
        )
        return result

    # ── Soft scoring ──────────────────────────────────────────

    # Readiness (0.0-1.0, directly from self-model/health)
    s_readiness = provider.readiness
    result.breakdown["readiness"] = s_readiness

    # Reliability (0.0-1.0, from historical outcomes)
    s_reliability = provider.reliability
    result.breakdown["reliability"] = s_reliability

    # Confidence (0.0-1.0, how well this provider matches the capability)
    s_confidence = provider.confidence
    result.breakdown["confidence"] = s_confidence

    # Risk (lower risk = higher score)
    s_risk = _RISK_SCORES.get(provider.risk_level, 0.5)
    result.breakdown["risk"] = s_risk

    # Cost penalty (normalize: $0 = 1.0, $1+ = 0.1)
    cost = provider.estimated_cost_usd
    s_cost = max(0.1, 1.0 - min(cost, 1.0))
    result.breakdown["cost"] = s_cost

    # Latency penalty (normalize: 0ms = 1.0, 5000ms+ = 0.1)
    latency = provider.estimated_latency_ms
    s_latency = max(0.1, 1.0 - min(latency / 5000.0, 0.9))
    result.breakdown["latency"] = s_latency

    # Type preference bonus
    s_type = 1.0
    if requirement.prefer_type is not None:
        s_type = 1.0 if provider.provider_type == requirement.prefer_type else 0.5
    result.breakdown["type_preference"] = s_type

    # ── Weighted sum ──────────────────────────────────────────

    result.total_score = (
        weights.readiness * s_readiness
        + weights.reliability * s_reliability
        + weights.confidence * s_confidence
        + weights.risk_penalty * s_risk
        + weights.cost_penalty * s_cost
        + weights.latency_penalty * s_latency
        + weights.type_preference * s_type
    )

    # Approval penalty: reduce score slightly to prefer non-gated providers
    if provider.requires_approval:
        result.total_score *= 0.85
        result.breakdown["approval_penalty"] = 0.85

    return result


def rank_providers(
    providers: list[ProviderSpec],
    requirement: CapabilityRequirement,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> list[ScoredProvider]:
    """
    Score and rank all providers for a requirement.

    Returns sorted list (best first), including blocked providers.
    """
    scored = [score_provider(p, requirement, weights) for p in providers]
    # Sort: available first (by score desc), blocked last
    scored.sort(key=lambda s: (not s.blocked, s.total_score), reverse=True)
    return scored
