"""
Tests for CORS + rate-limiting hardening (public beta readiness).

All tests are unit-level - no real HTTP server, no real Redis, no real LLM calls.
"""
from __future__ import annotations

import pytest


# -- CORS settings tests -------------------------------------------------------

class TestCorsSettings:
    def test_wildcard_replaced_by_localhost_defaults(self):
        """BEA_CORS_ORIGINS='*' must never produce ['*'] when credentials=True."""
        from config.settings import Settings
        s = Settings(bea_cors_origins="*")
        origins = s.cors_origins_list
        assert "*" not in origins
        assert any("localhost" in o for o in origins)

    def test_empty_origins_returns_localhost_defaults(self):
        from config.settings import Settings
        s = Settings(bea_cors_origins="")
        origins = s.cors_origins_list
        assert len(origins) > 0
        assert all("localhost" in o or "127.0.0.1" in o or "10.0.2.2" in o for o in origins)

    def test_env_origins_parsed_correctly(self):
        from config.settings import Settings
        s = Settings(bea_cors_origins="https://example.com,https://app.example.com")
        origins = s.cors_origins_list
        assert "https://example.com" in origins
        assert "https://app.example.com" in origins
        assert len(origins) == 2

    def test_trailing_spaces_stripped(self):
        from config.settings import Settings
        s = Settings(bea_cors_origins=" https://a.com , https://b.com ")
        origins = s.cors_origins_list
        assert "https://a.com" in origins
        assert "https://b.com" in origins

    def test_empty_tokens_in_csv_ignored(self):
        from config.settings import Settings
        s = Settings(bea_cors_origins="https://a.com,,https://b.com,")
        origins = s.cors_origins_list
        assert "" not in origins
        assert len(origins) == 2

    def test_localhost_explicitly_allowed_in_dev(self):
        from config.settings import Settings
        s = Settings(bea_cors_origins="")
        origins = s.cors_origins_list
        assert any("localhost:3000" in o for o in origins)

    def test_bea_cors_origins_takes_precedence_over_cors_origins(self, monkeypatch):
        """BEA_CORS_ORIGINS overrides the legacy CORS_ORIGINS var."""
        monkeypatch.setenv("BEA_CORS_ORIGINS", "https://new.example.com")
        monkeypatch.setenv("CORS_ORIGINS", "https://old.example.com")
        from config.settings import Settings
        s = Settings(bea_cors_origins="https://new.example.com")
        origins = s.cors_origins_list
        assert "https://new.example.com" in origins
        assert "https://old.example.com" not in origins


# -- Rate-limit settings tests -------------------------------------------------

class TestRateLimitSettings:
    def test_default_per_minute_is_60(self):
        from config.settings import Settings
        s = Settings()
        assert s.bea_rate_limit_per_minute == 60

    def test_default_enabled_is_true(self):
        from config.settings import Settings
        s = Settings()
        assert s.bea_rate_limit_enabled is True

    def test_disabled_flag(self):
        from config.settings import Settings
        s = Settings(bea_rate_limit_enabled=False)
        assert s.bea_rate_limit_enabled is False

    def test_per_minute_configurable(self):
        from config.settings import Settings
        s = Settings(bea_rate_limit_per_minute=120)
        assert s.bea_rate_limit_per_minute == 120

    def test_per_minute_from_env(self, monkeypatch):
        monkeypatch.setenv("BEA_RATE_LIMIT_PER_MINUTE", "30")
        # Reinstantiate to pick up env
        import importlib
        import config.settings as cs
        importlib.reload(cs)
        s = cs.Settings()
        assert s.bea_rate_limit_per_minute == 30
        importlib.reload(cs)  # restore

    def test_rate_limit_disabled_from_env(self, monkeypatch):
        monkeypatch.setenv("BEA_RATE_LIMIT_ENABLED", "false")
        import importlib
        import config.settings as cs
        importlib.reload(cs)
        s = cs.Settings()
        assert s.bea_rate_limit_enabled is False
        importlib.reload(cs)


# -- Rate-limit middleware unit tests ------------------------------------------

class TestRateLimitMiddlewareUnit:
    """Unit-test the in-memory logic of RateLimitMiddleware without HTTP."""

    def _make_middleware(self, *, enabled=True, per_minute=5):
        """Instantiate the middleware with a dummy ASGI app."""
        from starlette.applications import Starlette

        async def dummy_app(scope, receive, send):
            from starlette.responses import JSONResponse
            await JSONResponse({"ok": True})(scope, receive, send)

        # Import locally to avoid circular issues at module level
        try:
            from api.middleware.rate_limit import RateLimitMiddleware
            return RateLimitMiddleware(dummy_app, enabled=enabled, per_minute=per_minute)
        except ImportError:
            pytest.skip("api.middleware.rate_limit not present (using slowapi instead)")

    def test_middleware_instantiates(self):
        mw = self._make_middleware(per_minute=10)
        assert mw is not None

    def test_disabled_middleware_skips_limiting(self):
        mw = self._make_middleware(enabled=False, per_minute=2)
        assert not mw._enabled

    def test_exempt_paths_not_counted(self):
        mw = self._make_middleware(per_minute=3)
        exempt = mw.EXEMPT_PATHS
        assert "/health" in exempt or "/api/v3/system/health" in exempt


# -- Structural assertions on api/main.py -------------------------------------

class TestMainPyStructure:
    def _content(self):
        from pathlib import Path
        return Path("api/main.py").read_text(encoding="utf-8")

    def test_cors_uses_settings_cors_origins_list(self):
        content = self._content()
        assert "cors_origins_list" in content

    def test_no_hardcoded_wildcard_in_cors(self):
        content = self._content()
        # allow_origins=["*"] with credentials is forbidden
        assert 'allow_origins=["*"]' not in content

    def test_cors_allow_credentials_true(self):
        content = self._content()
        assert "allow_credentials=True" in content

    def test_production_guard_present(self):
        """Production mode must fail hard if no CORS origins configured."""
        content = self._content()
        assert "PRODUCTION STARTUP BLOCKED" in content
        assert "BEA_CORS_ORIGINS" in content

    def test_slowapi_still_mounted(self):
        content = self._content()
        assert "app.state.limiter = limiter" in content
        assert "app.add_exception_handler(RateLimitExceeded" in content

    def test_no_rate_limit_middleware_import(self):
        """slowapi is the single rate limiter - no legacy RateLimitMiddleware."""
        content = self._content()
        assert "from api.rate_limiter import RateLimitMiddleware" not in content
        assert "app.add_middleware(RateLimitMiddleware)" not in content


# -- rate_limit_middleware.py structural test ----------------------------------

class TestRateLimitMiddlewareFile:
    def test_default_limit_uses_env_variable(self):
        from pathlib import Path
        content = Path("api/rate_limit_middleware.py").read_text(encoding="utf-8")
        assert "BEA_RATE_LIMIT_PER_MINUTE" in content
        # No hardcoded 100/minute - it is now configurable
        assert "100/minute" not in content

    def test_configurable_limit_present(self):
        from pathlib import Path
        content = Path("api/rate_limit_middleware.py").read_text(encoding="utf-8")
        assert "_per_minute" in content
