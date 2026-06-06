"""
kernel/convergence/performance_routing.py — Feed kernel performance into routing.

Conservative integration: adjusts provider reliability scores using real
execution outcomes before the existing scorer runs.

Rules:
  - Only adjusts reliability (0.0-1.0) — never overrides readiness/safety/policy
  - Uses EMA success rate as primary signal (weighted toward recent)
  - Requires minimum samples before adjusting (avoid noise)
  - Blends kernel data with existing reliability, doesn't replace
  - Degraded providers get a penalty, strong providers get a small bonus
  - All operations fail-open: if anything errors, provider keeps original reliability

Design:
  Before scoring:  enrich_providers(providers) → same list, mutated reliabilities
  After scoring:   untouched (scorer already uses reliability in weighted formula)
"""
from __future__ import annotations

import structlog

log = structlog.get_logger("kernel.convergence.performance_routing")

# Only adjust reliability if we have at least this many observations
_MIN_SAMPLES = 3

# Minimum samples for "confident" assessment (used in explanation)
_MIN_CONFIDENCE_SAMPLES = 5

# Maximum reliability shift per direction (±0.2)
# A tool with 100% success can shift reliability up by 0.2 max
# A tool with 0% success can shift reliability down by 0.2 max
_MAX_BOOST = 0.15
_MAX_PENALTY = 0.20

# Blend factor: how much weight kernel data gets vs existing reliability
# 0.4 = 40% kernel, 60% original
_BLEND_FACTOR = 0.4


def enrich_providers(providers: list) -> list:
    """
    Adjust provider reliability scores based on kernel performance data.

    Modifies providers in-place and returns the same list.
    Fail-open: any error → providers returned unchanged.

    Args:
        providers: list of ProviderSpec objects

    Returns:
        Same list (mutated in place)
    """
    try:
        from kernel.capabilities.performance import get_performance_store
        store = get_performance_store()

        for provider in providers:
            try:
                _enrich_single(provider, store)
            except Exception:
                log.debug("swallowed_exception", exc_info=True)

    except Exception as e:
        log.debug("performance_enrichment_failed", err=str(e)[:60])

    return providers


def _enrich_single(provider, store) -> None:
    """
    Enrich a single provider's reliability from kernel performance.

    Strategy:
      1. Look up provider-level performance (most specific)
      2. Fall back to tool-level if provider matches a tool
      3. Blend kernel EMA with existing reliability
      4. Clamp adjustments to ±MAX bounds
    """
    pid = provider.provider_id
    cap_id = getattr(provider, "capability_id", "")

    # Try provider-level performance first
    perf = store.get_provider_performance(pid)

    # Try capability-level as additional signal
    cap_perf = store.get_capability_performance(cap_id) if cap_id else None

    # Try tool-level (provider_id might be a tool)
    if not perf:
        perf = store.get_tool_performance(pid)

    if not perf or perf["total"] < _MIN_SAMPLES:
        # Not enough data — don't adjust
        return

    # Compute kernel reliability signal
    kernel_reliability = perf["ema_success"]

    # If capability performance also available, blend them
    if cap_perf and cap_perf["total"] >= _MIN_SAMPLES:
        # 70% provider-specific, 30% capability-level
        kernel_reliability = 0.7 * kernel_reliability + 0.3 * cap_perf["ema_success"]

    # Blend with existing reliability
    original = provider.reliability
    blended = (1 - _BLEND_FACTOR) * original + _BLEND_FACTOR * kernel_reliability

    # Clamp adjustment
    delta = blended - original
    if delta > _MAX_BOOST:
        blended = original + _MAX_BOOST
    elif delta < -_MAX_PENALTY:
        blended = original - _MAX_PENALTY

    # Final clamp to [0.05, 1.0] — never zero (zero = blocked in scorer)
    blended = max(0.05, min(1.0, blended))

    provider.reliability = round(blended, 3)

    # Build human-readable explanation
    adjustment = round(blended - original, 3)
    explanation_parts = []
    if adjustment > 0:
        explanation_parts.append(
            f"performance boost: +{adjustment:.3f} "
            f"(recent success rate {perf['ema_success']:.2f}, {perf['total']} samples)"
        )
    elif adjustment < 0:
        explanation_parts.append(
            f"performance penalty: {adjustment:.3f} "
            f"(recent success rate {perf['ema_success']:.2f}, {perf['total']} samples)"
        )

    if perf["total"] < _MIN_CONFIDENCE_SAMPLES:
        explanation_parts.append(
            f"low confidence: {perf['total']} samples < {_MIN_CONFIDENCE_SAMPLES} threshold"
        )

    if perf["trend"] == "degrading":
        explanation_parts.append("trend: degrading")
    elif perf["trend"] == "improving":
        explanation_parts.append("trend: improving")

    # Add metadata for observability + explainability
    provider.metadata["kernel_performance"] = {
        "original_reliability": round(original, 3),
        "adjusted_reliability": round(blended, 3),
        "kernel_ema": round(perf["ema_success"], 3),
        "adjustment": adjustment,
        "samples": perf["total"],
        "confidence": perf["confidence"],
        "trend": perf["trend"],
        "explanation": "; ".join(explanation_parts) if explanation_parts else "no adjustment",
    }
