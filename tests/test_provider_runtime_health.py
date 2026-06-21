"""Tests for core/providers/runtime_health.py (PR #92).

All network calls are mocked — tests require neither OpenRouter nor Ollama.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.providers.runtime_health import (
    ProviderHealth,
    _key_looks_valid,
    check_provider_health,
    check_provider_health_sync,
)


# ── _key_looks_valid ──────────────────────────────────────────────────────────

class TestKeyLooksValid:
    def test_none_is_invalid(self) -> None:
        assert not _key_looks_valid(None)

    def test_empty_is_invalid(self) -> None:
        assert not _key_looks_valid("")

    def test_short_key_is_invalid(self) -> None:
        assert not _key_looks_valid("sk-short")

    def test_placeholder_change_me_invalid(self) -> None:
        assert not _key_looks_valid("CHANGE_ME_openssl_rand_hex_32")

    def test_placeholder_replace_me_invalid(self) -> None:
        assert not _key_looks_valid("REPLACE_ME_this_is_a_placeholder_key")

    def test_valid_key(self) -> None:
        assert _key_looks_valid("sk-or-v1-" + "a" * 30)


# ── Helpers for async tests ───────────────────────────────────────────────────

def _make_http_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    return resp


class _FakeAsyncClient:
    """Context-manager mock for httpx.AsyncClient."""

    def __init__(self, responses: dict[str, Any]) -> None:
        # responses maps URL substring → response object
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get(self, url: str, **_kwargs):
        for key, resp in self._responses.items():
            if key in url:
                return resp
        raise ConnectionError(f"No mock for URL: {url}")


# ── check_provider_health ─────────────────────────────────────────────────────

class TestCheckProviderHealth:

    @pytest.mark.asyncio
    async def test_openrouter_key_absent_ollama_reachable(self) -> None:
        """No OR key + Ollama up → DEGRADED, default=ollama."""
        ollama_version = _make_http_response(200, {"version": "0.30.0"})
        ollama_tags = _make_http_response(200, {"models": [{"name": "gemma4:12b"}]})
        responses = {
            "/api/version": ollama_version,
            "/api/tags": ollama_tags,
        }

        with (
            patch("os.environ.get", side_effect=lambda k, d="": "" if k == "OPENROUTER_API_KEY" else d),
            patch("core.providers.runtime_health.httpx.AsyncClient", side_effect=lambda **kw: _FakeAsyncClient(responses)),
        ):
            result = await check_provider_health(settings=None)

        assert result.status == "DEGRADED"
        assert result.default_provider == "ollama"
        assert result.fallback_provider == "none"
        assert result.ollama_reachable is True
        assert "gemma4:12b" in result.ollama_models
        assert result.openrouter_usable is False

    @pytest.mark.asyncio
    async def test_openrouter_key_absent_ollama_absent(self) -> None:
        """No key, no Ollama → UNAVAILABLE."""

        class _AlwaysFail(_FakeAsyncClient):
            async def get(self, url: str, **_kwargs):
                raise ConnectionError("unreachable")

        with (
            patch("os.environ.get", return_value=""),
            patch("core.providers.runtime_health.httpx.AsyncClient", side_effect=lambda **kw: _AlwaysFail({})),
        ):
            result = await check_provider_health(settings=None)

        assert result.status == "UNAVAILABLE"
        assert result.default_provider == "none"
        assert result.openrouter_usable is False
        assert result.ollama_reachable is False

    @pytest.mark.asyncio
    async def test_openrouter_key_present_selects_cloud(self) -> None:
        """Valid OR key + Ollama up → READY, default=openrouter."""
        valid_key = "sk-or-v1-" + "z" * 32
        or_resp = _make_http_response(200, {"data": []})
        ollama_version = _make_http_response(200)
        ollama_tags = _make_http_response(200, {"models": [{"name": "gemma4:12b"}]})

        def _fake_client(**kw):
            return _FakeAsyncClient({
                "openrouter.ai": or_resp,
                "/api/version": ollama_version,
                "/api/tags": ollama_tags,
            })

        settings = MagicMock()
        settings.openrouter_api_key = valid_key
        settings.ollama_host = "http://127.0.0.1:11434"

        with patch("core.providers.runtime_health.httpx.AsyncClient", side_effect=_fake_client):
            result = await check_provider_health(settings=settings)

        assert result.status == "READY"
        assert result.default_provider == "openrouter"
        assert result.openrouter_key_present is True
        assert result.openrouter_usable is True

    @pytest.mark.asyncio
    async def test_no_secret_in_hints(self) -> None:
        """Secret key must never appear in hints or logs."""
        secret = "sk-or-v1-supersecret" + "x" * 20

        settings = MagicMock()
        settings.openrouter_api_key = secret
        settings.ollama_host = "http://127.0.0.1:11434"

        or_resp = _make_http_response(200, {"data": []})
        ollama_version = _make_http_response(200)
        ollama_tags = _make_http_response(200, {"models": []})

        def _fake_client(**kw):
            return _FakeAsyncClient({
                "openrouter.ai": or_resp,
                "/api/version": ollama_version,
                "/api/tags": ollama_tags,
            })

        with patch("core.providers.runtime_health.httpx.AsyncClient", side_effect=_fake_client):
            result = await check_provider_health(settings=settings)

        for hint in result.hints:
            assert secret not in hint, "Secret key leaked into hints"
        result_str = str(result.to_dict())
        assert secret not in result_str, "Secret key leaked into to_dict()"

    @pytest.mark.asyncio
    async def test_to_dict_has_stable_keys(self) -> None:
        """to_dict() must always contain the documented keys."""
        result = ProviderHealth()
        d = result.to_dict()
        required = {
            "openrouter_key_present",
            "openrouter_usable",
            "ollama_reachable",
            "ollama_host_used",
            "ollama_models",
            "default_provider",
            "fallback_provider",
            "status",
            "hints",
        }
        assert required <= set(d.keys())

    @pytest.mark.asyncio
    async def test_ollama_host_autodiscovery(self) -> None:
        """When Docker Ollama host fails, try localhost alternatives."""
        call_log: list[str] = []
        ollama_version = _make_http_response(200)
        ollama_tags = _make_http_response(200, {"models": [{"name": "gemma4:12b"}]})

        class _DiscoveryClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            async def get(self, url: str, **_kwargs):
                call_log.append(url)
                # Docker host fails, localhost works
                if "ollama:11434" in url:
                    raise ConnectionError("docker not reachable")
                if "127.0.0.1" in url and "/api/version" in url:
                    return ollama_version
                if "127.0.0.1" in url and "/api/tags" in url:
                    return ollama_tags
                raise ConnectionError(f"unexpected: {url}")

        settings = MagicMock()
        settings.openrouter_api_key = ""
        settings.ollama_host = "http://ollama:11434"

        with patch("core.providers.runtime_health.httpx.AsyncClient", _DiscoveryClient):
            result = await check_provider_health(settings=settings)

        assert result.ollama_reachable is True
        assert "127.0.0.1" in result.ollama_host_used
        # Verify it tried the Docker host first
        assert any("ollama:11434" in u for u in call_log)

    @pytest.mark.asyncio
    async def test_unavailable_status_has_clear_hint(self) -> None:
        """When UNAVAILABLE, hints must explain how to fix."""

        class _AlwaysFail:
            def __init__(self, **kw):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def get(self, url: str, **kw):
                raise ConnectionError("nothing works")

        settings = MagicMock()
        settings.openrouter_api_key = ""
        settings.ollama_host = "http://127.0.0.1:11434"

        with patch("core.providers.runtime_health.httpx.AsyncClient", _AlwaysFail):
            result = await check_provider_health(settings=settings)

        assert result.status == "UNAVAILABLE"
        combined = " ".join(result.hints).lower()
        assert "openrouter" in combined or "ollama" in combined


# ── check_provider_health_sync ────────────────────────────────────────────────

class TestCheckProviderHealthSync:

    def test_sync_wrapper_returns_provider_health(self) -> None:
        async def _stub(settings=None):
            return ProviderHealth(status="READY", default_provider="openrouter")

        with patch("core.providers.runtime_health.check_provider_health", _stub):
            result = check_provider_health_sync()

        assert isinstance(result, ProviderHealth)
        assert result.status == "READY"
