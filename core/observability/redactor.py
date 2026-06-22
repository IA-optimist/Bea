"""Privacy-safe redaction for structured logs.

Never logs: API keys, Bearer tokens, bea-tokens, emails, long opaque strings.
Always preserves: mission_id, provider_used, model_used, score, error_category.
"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "[API_KEY_REDACTED]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{16,}", re.IGNORECASE), "Bearer [TOKEN_REDACTED]"),
    (re.compile(r"bea-[a-zA-Z0-9_\-]{16,}"), "[BEA_TOKEN_REDACTED]"),
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[EMAIL_REDACTED]"),
    (re.compile(r"[a-zA-Z0-9_\-]{40,}"), "[LONG_STRING_REDACTED]"),
]

_SAFE_KEYS = {
    "mission_id", "run_id", "trace_id", "mission_type", "status",
    "provider_used", "model_used", "agent_used", "duration_ms",
    "error_category", "artifact_status", "validation_status",
    "rate_limited", "timestamp", "role", "score", "passed",
    "success", "fallback_used",
}

_REDACT_KEYS = {
    "api_key", "token", "password", "secret", "bearer",
    "authorization", "prompt", "response", "content",
}


def redact(value: str) -> str:
    """Redact secrets from a string value. Non-strings returned unchanged."""
    if not isinstance(value, str):
        return value
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact_dict(d: dict) -> dict:
    """Recursively redact secrets from a dict. Preserves observability metadata."""
    out: dict = {}
    for k, v in d.items():
        k_lower = k.lower()
        if any(r in k_lower for r in _REDACT_KEYS):
            out[k] = "[REDACTED]"
        elif k in _SAFE_KEYS:
            out[k] = v
        elif isinstance(v, dict):
            out[k] = redact_dict(v)
        elif isinstance(v, str):
            out[k] = redact(v)
        else:
            out[k] = v
    return out
