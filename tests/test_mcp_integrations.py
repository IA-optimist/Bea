"""
tests/test_mcp_integrations.py — Smoke tests for MCP/connector integrations.

Tests:
  1. Settings: new feature flags load correctly
  2. MCPRegistry: Qdrant adapter registers correctly
  3. MCPRegistry: GitHub adapter registers correctly
  4. MCPAdapter: tool lookup works for both adapters
  5. Composio: is_configured() returns False when flag is off
  6. Composio: is_configured() returns False when key is missing
  7. MCP server: get_mcp_server() builds without error if mcp installed
  8. Qdrant adapter: unregister cleans up correctly
  9. GitHub adapter: high-risk tools have requires_approval=True
 10. Feature flags: all default to False/disabled

Run:
    pytest tests/test_mcp_integrations.py -v
"""
from __future__ import annotations

import os
import sys
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def fresh_registry():
    """A clean MCPRegistry instance (not the global singleton)."""
    from integrations.mcp.mcp_registry import MCPRegistry
    return MCPRegistry()


@pytest.fixture()
def settings_with_qdrant_mcp(monkeypatch):
    """Settings with QDRANT_MCP_ENABLED=true."""
    monkeypatch.setenv("QDRANT_MCP_ENABLED", "true")
    monkeypatch.setenv("QDRANT_MCP_URL", "http://qdrant-mcp-test:8000")
    from config.settings import Settings
    return Settings()


@pytest.fixture()
def settings_with_github_mcp(monkeypatch):
    """Settings with GITHUB_MCP_ENABLED=true."""
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "true")
    monkeypatch.setenv("GITHUB_MCP_URL", "http://github-mcp-test:3000")
    from config.settings import Settings
    return Settings()


# ── Test 1: Settings flags ────────────────────────────────────────────────────


def test_settings_feature_flags_default_false():
    """All new integration flags default to False."""
    # Ensure flags are NOT set in env
    for key in ("MCP_SERVER_ENABLED", "QDRANT_MCP_ENABLED",
                "COMPOSIO_ENABLED", "GITHUB_MCP_ENABLED"):
        os.environ.pop(key, None)

    from config.settings import Settings
    s = Settings()

    assert s.mcp_server_enabled is False,   "MCP_SERVER_ENABLED should default False"
    assert s.qdrant_mcp_enabled is False,   "QDRANT_MCP_ENABLED should default False"
    assert s.composio_enabled is False,     "COMPOSIO_ENABLED should default False"
    assert s.github_mcp_enabled is False,   "GITHUB_MCP_ENABLED should default False"


def test_settings_feature_flags_can_be_enabled(monkeypatch):
    """Feature flags can be enabled via environment variables."""
    monkeypatch.setenv("MCP_SERVER_ENABLED", "true")
    monkeypatch.setenv("QDRANT_MCP_ENABLED", "true")
    monkeypatch.setenv("COMPOSIO_ENABLED", "true")
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "1")

    from config.settings import Settings
    s = Settings()

    assert s.mcp_server_enabled is True
    assert s.qdrant_mcp_enabled is True
    assert s.composio_enabled is True
    assert s.github_mcp_enabled is True


def test_settings_mcp_defaults():
    """MCP server settings have sane defaults."""
    os.environ.pop("MCP_SERVER_PORT", None)
    os.environ.pop("MCP_SERVER_HOST", None)

    from config.settings import Settings
    s = Settings()

    assert s.mcp_server_port == 8765
    assert s.mcp_server_host == "0.0.0.0"


# ── Test 2+3: Qdrant + GitHub MCPRegistry registration ───────────────────────


def test_qdrant_mcp_registration(fresh_registry, settings_with_qdrant_mcp):
    """Qdrant MCP adapter registers server + tools in registry."""
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp

    result = register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)

    assert result is True
    # Server registered
    server = fresh_registry.get_server("qdrant-mcp")
    assert server is not None
    assert server.name == "Qdrant Vector Memory (MCP)"
    assert server.endpoint == "http://qdrant-mcp-test:8000"
    assert server.transport == "http"

    # Tools registered
    search_tool = fresh_registry.get_tool("qdrant::search")
    assert search_tool is not None
    assert search_tool.risk_level == "low"
    assert search_tool.requires_approval is False
    assert "memory" in search_tool.tags

    upsert_tool = fresh_registry.get_tool("qdrant::upsert")
    assert upsert_tool is not None
    assert upsert_tool.risk_level == "medium"


def test_qdrant_mcp_disabled_by_default(fresh_registry):
    """Qdrant MCP registration skipped when flag is off."""
    os.environ.pop("QDRANT_MCP_ENABLED", None)
    from config.settings import Settings
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp

    s = Settings()
    result = register_qdrant_mcp(fresh_registry, s)

    assert result is False
    assert fresh_registry.get_server("qdrant-mcp") is None


def test_qdrant_mcp_no_double_registration(fresh_registry, settings_with_qdrant_mcp):
    """Qdrant MCP adapter does not double-register."""
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp

    r1 = register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)
    r2 = register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)

    assert r1 is True
    assert r2 is True  # idempotent
    assert len(fresh_registry.list_servers()) == 1


def test_github_mcp_registration(fresh_registry, settings_with_github_mcp):
    """GitHub MCP adapter registers server + all 5 tools."""
    from core.mcp.bea.github_mcp_adapter import register_github_mcp

    result = register_github_mcp(fresh_registry, settings_with_github_mcp)

    assert result is True
    server = fresh_registry.get_server("github-mcp")
    assert server is not None
    assert server.risk_level == "high"

    # All 5 tools present
    for tool_id in [
        "github::search_code",
        "github::list_issues",
        "github::create_issue",
        "github::create_pr",
        "github::push_files",
    ]:
        t = fresh_registry.get_tool(tool_id)
        assert t is not None, f"Tool {tool_id!r} not registered"


def test_github_mcp_high_risk_tools_require_approval(
    fresh_registry, settings_with_github_mcp
):
    """Write tools (create_pr, push_files) require approval."""
    from core.mcp.bea.github_mcp_adapter import register_github_mcp

    register_github_mcp(fresh_registry, settings_with_github_mcp)

    # Low-risk read tools: no approval
    assert fresh_registry.get_tool("github::search_code").requires_approval is False
    assert fresh_registry.get_tool("github::list_issues").requires_approval is False

    # High-risk write tools: approval required
    assert fresh_registry.get_tool("github::create_pr").requires_approval is True
    assert fresh_registry.get_tool("github::push_files").requires_approval is True


# ── Test 4: MCPAdapter tool lookup ────────────────────────────────────────────


def test_mcp_adapter_resolves_qdrant_tool(
    fresh_registry, settings_with_qdrant_mcp
):
    """MCPAdapter can resolve a registered Qdrant tool."""
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp
    from integrations.mcp.mcp_adapter import MCPAdapter

    register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)
    adapter = MCPAdapter(registry=fresh_registry)

    tool = fresh_registry.get_tool("qdrant::search")
    assert tool is not None
    assert tool.server_id == "qdrant-mcp"

    # Adapter should be able to look it up
    assert adapter._registry.get_tool("qdrant::search") is not None


# ── Test 5+6: Composio adapter ────────────────────────────────────────────────


# Skip si connectors.composio_adapter retiré (feature désactivée).
import importlib.util as _ilu
_HAS_COMPOSIO = _ilu.find_spec("connectors.composio_adapter") is not None

@pytest.mark.skipif(not _HAS_COMPOSIO, reason="connectors.composio_adapter absent (feature drift)")
def test_composio_disabled_by_default():
    """Composio is_configured() returns False when flag is off."""
    os.environ.pop("COMPOSIO_ENABLED", None)
    os.environ.pop("COMPOSIO_API_KEY", None)

    from connectors.composio_adapter import ComposioAdapter
    adapter = ComposioAdapter()
    assert adapter.is_configured() is False


@pytest.mark.skipif(not _HAS_COMPOSIO, reason="connectors.composio_adapter absent (feature drift)")
def test_composio_disabled_without_key(monkeypatch):
    """Composio is_configured() returns False when API key is missing."""
    monkeypatch.setenv("COMPOSIO_ENABLED", "true")
    os.environ.pop("COMPOSIO_API_KEY", None)

    from connectors.composio_adapter import ComposioAdapter
    adapter = ComposioAdapter()
    assert adapter.is_configured() is False


@pytest.mark.skipif(not _HAS_COMPOSIO, reason="connectors.composio_adapter absent (feature drift)")
def test_composio_execute_when_disabled():
    """Composio.execute() returns structured error when not configured."""
    os.environ.pop("COMPOSIO_ENABLED", None)

    from connectors.composio_adapter import ComposioAdapter
    adapter = ComposioAdapter()
    result = adapter.execute("gmail_send_email", {"to": "test@test.com"})

    assert result.success is False
    assert "not configured" in result.error.lower() or "composio" in result.error.lower()


# ── Test 7: MCP server build ──────────────────────────────────────────────────


def test_mcp_server_build_without_mcp_sdk():
    """get_mcp_server() raises RuntimeError if mcp SDK is not installed."""
    # Patch _MCP_AVAILABLE to False
    import core.mcp.bea.bea_mcp_server as srv_module

    original = srv_module._MCP_AVAILABLE
    srv_module._MCP_AVAILABLE = False
    try:
        with pytest.raises(RuntimeError, match="mcp package not installed"):
            srv_module._build_server()
    finally:
        srv_module._MCP_AVAILABLE = original


# ── Test 8: Unregister cleanup ────────────────────────────────────────────────


def test_qdrant_mcp_unregister(fresh_registry, settings_with_qdrant_mcp):
    """Qdrant MCP unregister removes server and all its tools."""
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp, unregister_qdrant_mcp

    register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)
    assert fresh_registry.get_server("qdrant-mcp") is not None

    unregister_qdrant_mcp(fresh_registry)
    assert fresh_registry.get_server("qdrant-mcp") is None
    # Tools should also be gone
    assert fresh_registry.get_tool("qdrant::search") is None
    assert fresh_registry.get_tool("qdrant::upsert") is None


# ── Test 9: Tag-based tool discovery ─────────────────────────────────────────


def test_find_tools_by_tag(fresh_registry, settings_with_qdrant_mcp):
    """MCPRegistry.find_tools_by_tag works for Qdrant memory tools."""
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp

    register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)

    memory_tools = fresh_registry.find_tools_by_tag("memory")
    assert len(memory_tools) >= 2

    qdrant_tools = fresh_registry.find_tools_by_tag("qdrant")
    assert len(qdrant_tools) == 2


# ── Test 10: Registry stats ──────────────────────────────────────────────────


def test_registry_stats(
    fresh_registry, settings_with_qdrant_mcp, settings_with_github_mcp
):
    """MCPRegistry.stats() reflects registered servers and tools."""
    from core.mcp.bea.qdrant_mcp_adapter import register_qdrant_mcp
    from core.mcp.bea.github_mcp_adapter import register_github_mcp

    register_qdrant_mcp(fresh_registry, settings_with_qdrant_mcp)
    register_github_mcp(fresh_registry, settings_with_github_mcp)

    stats = fresh_registry.stats()
    assert stats["servers"] == 2
    assert stats["tools"] == 7  # 2 qdrant + 5 github
