"""Tests for rate limiting middleware runtime behavior.

The module no longer supports a RATE_LIMIT_ENABLED toggle — rate limiting is
always active. These tests verify the actual observable behavior: per-minute
configuration, the production fail-safe, and the limiter instance.
"""
from __future__ import annotations

import sys
from unittest.mock import patch


def test_rate_limit_limiter_created(monkeypatch):
    """Rate limiter must be created at module load."""
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    assert rlm.limiter is not None, "limiter must be initialised"


def test_rate_limit_per_minute_parse(monkeypatch):
    """BEA_RATE_LIMIT_PER_MINUTE should be parsed as int."""
    monkeypatch.setenv("BEA_RATE_LIMIT_PER_MINUTE", "30")
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    assert rlm._per_minute == 30


def test_rate_limit_per_minute_invalid_fallback(monkeypatch):
    """Invalid BEA_RATE_LIMIT_PER_MINUTE should fall back to 60."""
    monkeypatch.setenv("BEA_RATE_LIMIT_PER_MINUTE", "not-a-number")
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    assert rlm._per_minute == 60


def test_rate_limit_production_blocks_memory_storage(monkeypatch):
    """BEA_PRODUCTION=true + no reachable Redis must raise RuntimeError."""
    monkeypatch.setenv("BEA_PRODUCTION", "true")
    monkeypatch.delenv("REDIS_URL", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    try:
        import api.rate_limit_middleware  # noqa: F401
        assert False, "Should have raised RuntimeError in production without Redis"
    except RuntimeError as e:
        assert "PRODUCTION" in str(e) or "memory://" in str(e), (
            f"Expected production safety RuntimeError, got: {e}"
        )


def test_rate_limit_redis_url_used_when_reachable(monkeypatch):
    """When REDIS_URL is set and Redis is reachable, storage URI should use it."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    # Mock socket to simulate Redis reachable
    with patch("socket.create_connection"):
        if "api.rate_limit_middleware" in sys.modules:
            del sys.modules["api.rate_limit_middleware"]
        import api.rate_limit_middleware as rlm
    assert rlm._STORAGE_URI == "redis://127.0.0.1:6379/0", (
        f"Expected Redis URI, got: {rlm._STORAGE_URI}"
    )


def test_rate_limit_handler_returns_429_json(monkeypatch):
    """custom_rate_limit_handler should return 429 JSONResponse."""
    from unittest.mock import MagicMock
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    fake_exc = MagicMock()
    fake_exc.detail = "1 per 1 minute — Retry after 42 seconds"
    response = rlm.custom_rate_limit_handler(MagicMock(), fake_exc)
    assert response.status_code == 429
