"""core/resilience — Reliability guards for Bea v1.
Re-exports from _base for backward compatibility.
"""
from core.resilience._base import (  # noqa: F401
    BeaError,
    BeaExecutionError, 
    CircuitBreaker,
    guard_context,
    estimate_tokens,
    timeout_guard,
    idempotency_key,
    degrade_gracefully,
    get_circuit_breaker,
    MAX_CONTEXT_CHARS,
)
