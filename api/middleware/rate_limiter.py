"""DEPRECATED — use ``api.rate_limiter`` instead.

Audit follow-up (Mo5): this module was the original FastAPI-decorator
implementation of rate limiting. The repo standardized on
``api/rate_limiter.py`` (canonical ``RateLimitMiddleware`` backed by
``InMemoryRateLimiter`` and ``RedisRateLimiter``). No production code
imports from this module — see audit grep evidence.

It is kept as a thin re-export shim with a runtime ``DeprecationWarning``
so any forgotten import surfaces loudly instead of running stale code.

Migration: change ``from api.middleware.rate_limiter import X`` to
``from api.rate_limiter import X`` (the symbols are not strictly identical
— see ``api/rate_limiter.py`` for the canonical API).
"""
from __future__ import annotations

import warnings

from api.rate_limiter import (  # noqa: F401 — re-exported for backward compat
    InMemoryRateLimiter,
    RateLimiter,
    RateLimitMiddleware,
    ROUTE_LIMITS,
    _trusted_proxy_ips,
)

warnings.warn(
    "api.middleware.rate_limiter is deprecated; import from api.rate_limiter "
    "instead. This shim will be removed in a future cleanup PR.",
    DeprecationWarning,
    stacklevel=2,
)
