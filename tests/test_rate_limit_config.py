"""Tests for BEA_RATE_LIMIT_ENABLED runtime behavior."""
from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch


def test_rate_limit_enabled_default_true(monkeypatch):
    """By default, rate-limiting should be enabled."""
    monkeypatch.delenv("BEA_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    # Re-import to pick up env
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    assert rlm.RATE_LIMIT_ENABLED is True


def test_rate_limit_disabled_via_env(monkeypatch):
    """BEA_RATE_LIMIT_ENABLED=false should disable rate-limiting."""
    monkeypatch.setenv("BEA_RATE_LIMIT_ENABLED", "false")
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    assert rlm.RATE_LIMIT_ENABLED is False


def test_rate_limit_production_blocks_disabled(monkeypatch):
    """BEA_PRODUCTION=true + BEA_RATE_LIMIT_ENABLED=false should raise RuntimeError."""
    monkeypatch.setenv("BEA_PRODUCTION", "true")
    monkeypatch.setenv("BEA_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # We need to mock redis reachability to avoid the memory:// guard
    # But the rate-limit-disabled guard runs before the redis guard
    # Actually, the redis guard runs first. Let's mock it.
    with patch("socket.create_connection"):
        if "api.rate_limit_middleware" in sys.modules:
            del sys.modules["api.rate_limit_middleware"]
        try:
            import api.rate_limit_middleware  # noqa: F401
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "BEA_RATE_LIMIT_ENABLED" in str(e)


def test_rate_limit_per_minute_parse(monkeypatch):
    """BEA_RATE_LIMIT_PER_MINUTE should be parsed as int."""
    monkeypatch.setenv("BEA_RATE_LIMIT_PER_MINUTE", "30")
    monkeypatch.setenv("BEA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    # The limiter should have been created with 30/minute
    assert rlm._per_minute == 30


def test_rate_limit_per_minute_invalid_fallback(monkeypatch):
    """Invalid BEA_RATE_LIMIT_PER_MINUTE should fall back to 60."""
    monkeypatch.setenv("BEA_RATE_LIMIT_PER_MINUTE", "not-a-number")
    monkeypatch.setenv("BEA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.delenv("BEA_PRODUCTION", raising=False)
    if "api.rate_limit_middleware" in sys.modules:
        del sys.modules["api.rate_limit_middleware"]
    import api.rate_limit_middleware as rlm
    assert rlm._per_minute == 60


def test_rate_limit_enabled_variants(monkeypatch):
    """Various truthy values should enable rate-limiting."""
    for val in ("true", "1", "yes", "on", "TRUE", "True"):
        monkeypatch.setenv("BEA_RATE_LIMIT_ENABLED", val)
        monkeypatch.delenv("BEA_PRODUCTION", raising=False)
        if "api.rate_limit_middleware" in sys.modules:
            del sys.modules["api.rate_limit_middleware"]
        importlib.import_module("api.rate_limit_middleware")
        assert importlib.import_module("api.rate_limit_middleware").RATE_LIMIT_ENABLED is True, \
            f"BEA_RATE_LIMIT_ENABLED={val} should be True"
