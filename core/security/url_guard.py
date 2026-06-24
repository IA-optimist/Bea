"""URL validation guard for outbound HTTP/HTTPS requests.

Prevents SSRF and protocol injection by validating URLs before they are passed
to urllib.request.urlopen or similar functions.

Usage:
    from core.security.url_guard import validate_outbound_url

    safe_url = validate_outbound_url(user_provided_url)
    with urllib.request.urlopen(safe_url, timeout=30) as resp:  # nosec B310
        ...
"""
from __future__ import annotations

from urllib.parse import urlparse

# Hosts that must never be reachable via outbound requests (metadata endpoints).
_BLOCKED_HOSTS: frozenset[str] = frozenset({
    "169.254.169.254",        # AWS / GCP / Azure instance metadata
    "metadata.google.internal",  # GCP metadata
    "metadata.aws.internal",     # AWS metadata alias
    "0.0.0.0",
    "::1",
    "[::1]",
})

# Localhost variants — blocked unless allow_localhost=True
_LOCAL_HOSTS: frozenset[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "[::1]",
})

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


def validate_outbound_url(
    url: str,
    *,
    allow_localhost: bool = False,
    allowed_schemes: tuple[str, ...] = ("https", "http"),
    allowed_hosts: set[str] | None = None,
) -> str:
    """Validate and normalize an outbound URL.

    Args:
        url: The URL to validate.
        allow_localhost: If True, allow localhost/127.0.0.1 (for internal health checks).
        allowed_schemes: Tuple of permitted URL schemes.
        allowed_hosts: If set, only these hosts are allowed (whitelist mode).

    Returns:
        The validated URL string.

    Raises:
        ValueError: If the URL is invalid, uses a blocked scheme, targets a
            blocked host, or fails any validation check.
    """
    if not url or not url.strip():
        raise ValueError("URL must not be empty")

    url = url.strip()
    parsed = urlparse(url)

    # Scheme check
    scheme = (parsed.scheme or "").lower()
    if scheme not in {s.lower() for s in allowed_schemes}:
        raise ValueError(
            f"URL scheme '{scheme}' is not allowed. "
            f"Permitted: {', '.join(allowed_schemes)}"
        )

    # Explicitly block dangerous schemes even if somehow in allowed list
    if scheme in ("file", "ftp", "data", "javascript", "gopher", "dict"):
        raise ValueError(f"URL scheme '{scheme}' is explicitly blocked")

    # Host check
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL must have a host")

    # Block metadata endpoints always
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"URL host '{host}' is blocked (metadata endpoint)")

    # Block localhost unless explicitly allowed
    if not allow_localhost and host in _LOCAL_HOSTS:
        raise ValueError(
            f"URL host '{host}' is blocked (localhost). "
            "Pass allow_localhost=True to allow local addresses."
        )

    # Whitelist mode
    if allowed_hosts is not None:
        if host not in {h.lower() for h in allowed_hosts}:
            raise ValueError(
                f"URL host '{host}' is not in the allowed hosts list"
            )

    return url
