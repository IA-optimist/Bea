"""
BEA MAX — Token Parsing Utilities
========================================
Central, reusable token extraction functions.

Rules:
  - Only strip the "Bearer " PREFIX (first occurrence, at position 0)
  - Case-insensitive prefix match ("bearer ", "BEARER ", etc.)
  - Strip leading/trailing whitespace from the result
  - Never mutilate a token that contains "Bearer " elsewhere in the string
  - If input is None or empty after stripping → return None
"""
from __future__ import annotations


def strip_bearer(raw: str | None) -> str | None:
    """
    Strip an optional "Bearer " prefix from a token string.

    Returns:
        The token without the prefix, stripped of whitespace.
        None if input is None/empty or only whitespace after stripping.

    Examples:
        strip_bearer("Bearer abc123")     → "abc123"
        strip_bearer("bearer abc123")     → "abc123"
        strip_bearer("  Bearer abc123 ")  → "abc123"
        strip_bearer("abc123")            → "abc123"
        strip_bearer("")                  → None
        strip_bearer(None)                → None
        strip_bearer("myBearer token")    → "myBearer token"  # no prefix match
    """
    if not raw:
        return None

    # Work on the raw input (preserve internal spaces) but trim outer whitespace
    token = raw.strip()
    if not token:
        return None

    # Case-insensitive prefix strip — only at position 0
    # Check raw (pre-strip) to preserve the space in "Bearer <token>"
    if len(token) >= 7 and token[:7].lower() == "bearer ":
        token = token[7:].strip()
    elif token.lower() in ("bearer", "bearer "):
        # Just the word "Bearer" with no actual token value
        return None

    return token if token else None
