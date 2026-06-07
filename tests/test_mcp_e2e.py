"""
tests/test_mcp_e2e.py — Cycle 2 E2E + regression tests.

Tests:
  1.  Regression: all MCP flags=false → register_mcp_adapters() returns both False
  2.  Regression: clean startup with all flags=false → no MCP tools in registry
  3.  E2E Qdrant path: MCPAdapter resolves tool, sidecar unreachable → structured error
  4.  E2E GitHub path: MCPAdapter resolves tool, sidecar unreachable → structured error
  5.  Observability: mcp_adapter imports without error (langfuse guard present)
  6.  Factory: get_vector_memory returns VectorMemory when QDRANT_MEMORY_ENABLED=false
  7.  Factory: get_vector_memory returns QdrantVectorMemory when QDRANT_MEMORY_ENABLED=true
  8.  QdrantVectorMemory: add() falls back to local memory when Qdrant unreachable
  9.  QdrantVectorMemory: search() falls back to local memory when Qdrant unreachable
 10.  register_mcp_adapters: importable, returns dict with expected keys
 11.  MCPAdapter: invoke_tool returns structured error (never raises) on bad endpoint
 12.  Startup flags: register_mcp_adapters respects QDRANT_MCP_ENABLED env var

Run:
    pytest tests/test_mcp_e2e.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_registry():
    from integrations.mcp.mcp_registry import MCPRegistry
    return MCPRegistry()


@pytest.fixture()
def settings_all_mcp_on(monkeypatch):
    monkeypatch.setenv("QDRANT_MCP_ENABLED", "true")
    monkeypatch.setenv("QDRANT_MCP_URL", "http://qdrant-mcp-test:8000")
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "true")
    monkeypatch.setenv("GITHUB_MCP_URL", "http://github-mcp-test:3000")
    from config.settings import Settings
    return Settings()


@pytest.fixture()
def settings_all_mcp_off(monkeypatch):
    monkeypatch.delenv("QDRANT_MCP_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_MCP_ENABLED", raising=False)
    from config.settings import Settings
    return Settings()


@pytest.fixture()
def populated_registry(fresh_registry, settings_all_mcp_on):
    """Registry with both Qdrant + GitHub adapters registered."""
    from bea_mcp.qdrant_mcp_adapter import register_qdrant_mcp
    from bea_mcp.github_mcp_adapter import register_github_mcp
    register_qdrant_mcp(fresh_registry, settings_all_mcp_on)
    register_github_mcp(fresh_registry, settings_all_mcp_on)
    return fresh_registry


@pytest.fixture()
def mock_settings_for_register(monkeypatch):
    """Minimal settings mock for register_mcp_adapters tests."""
    monkeypatch.delenv("QDRANT_MCP_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_MCP_ENABLED", raising=False)


# ── Test 1: Regression — all flags off ───────────────────────────────────────

def test_register_mcp_adapters_all_flags_off(mock_settings_for_register):
    """register_mcp_adapters returns False for both when flags are off."""
    from api.startup_checks import register_mcp_adapters
    from config.settings import Settings

    result = register_mcp_adapters(Settings())
    assert result["qdrant_mcp"] is False, "qdrant_mcp should be False when flag is off"
    assert result["github_mcp"] is False, "github_mcp should be False when flag is off"


# ── Test 2: Regression — clean registry with flags off ───────────────────────

def test_clean_registry_flags_off(monkeypatch):
    """No MCP tools registered when all flags are off."""
    monkeypatch.delenv("QDRANT_MCP_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_MCP_ENABLED", raising=False)

    from integrations.mcp.mcp_registry import MCPRegistry
    from bea_mcp.qdrant_mcp_adapter import register_qdrant_mcp
    from bea_mcp.github_mcp_adapter import register_github_mcp
    from config.settings import Settings

    reg = MCPRegistry()
    s = Settings()

    register_qdrant_mcp(reg, s)
    register_github_mcp(reg, s)

    assert reg.stats()["servers"] == 0, "No servers should be registered"
    assert reg.stats()["tools"] == 0, "No tools should be registered"


# ── Test 3: E2E Qdrant — structured error when sidecar unreachable ────────────

def test_e2e_qdrant_tool_unreachable_sidecar(populated_registry):
    """MCPAdapter returns structured error when qdrant-mcp sidecar is unreachable."""
    from integrations.mcp.mcp_adapter import MCPAdapter

    adapter = MCPAdapter(registry=populated_registry)

    # Sidecar is not running in tests — expect structured error, never a raised exception
    result = asyncio.get_event_loop().run_until_complete(
        adapter.invoke_tool("qdrant::search", {"query": "test", "top_k": 3})
    )

    assert isinstance(result, dict), "invoke_tool must return a dict"
    assert "ok" in result, "result must have 'ok' key"
    assert "error" in result, "result must have 'error' key"
    assert "tool_id" in result, "result must have 'tool_id' key"
    assert "ms" in result, "result must have 'ms' key"
    assert result["ok"] is False, "should be False — sidecar not running"
    assert result["tool_id"] == "qdrant::search"


# ── Test 4: E2E GitHub — structured error when sidecar unreachable ────────────

def test_e2e_github_tool_unreachable_sidecar(populated_registry):
    """MCPAdapter returns structured error when github-mcp sidecar is unreachable."""
    from integrations.mcp.mcp_adapter import MCPAdapter

    adapter = MCPAdapter(registry=populated_registry)

    result = asyncio.get_event_loop().run_until_complete(
        adapter.invoke_tool("github::list_issues", {"repo": "owner/repo"})
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["tool_id"] == "github::list_issues"
    assert isinstance(result["ms"], int)
    assert result["ms"] >= 0


# ── Test 5: Observability — mcp_adapter imports cleanly ───────────────────────

def test_mcp_adapter_observability_imports():
    """_trace_mcp_langfuse function exists and is importable."""
    from integrations.mcp import mcp_adapter
    assert hasattr(mcp_adapter, "_trace_mcp_langfuse"), \
        "_trace_mcp_langfuse should be defined in mcp_adapter module"


def test_trace_langfuse_noop_when_disabled(monkeypatch, populated_registry):
    """_trace_mcp_langfuse does nothing when LANGFUSE_ENABLED is off."""
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)

    from integrations.mcp.mcp_adapter import _trace_mcp_langfuse
    from integrations.mcp.mcp_models import MCPTool, MCPServer

    tool = MCPTool(
        tool_id="test::tool", server_id="test-server",
        name="test_tool", description="test",
    )
    server = MCPServer(
        server_id="test-server", name="Test", endpoint="http://localhost:9999",
        metadata={"provider": "test"},
    )
    # Should not raise
    _trace_mcp_langfuse(tool, server, {"query": "x"}, None, 10, False, "err")


# ── Test 6+7: Vector memory factory ──────────────────────────────────────────

def test_get_vector_memory_returns_local_when_disabled(monkeypatch, tmp_path):
    """get_vector_memory returns VectorMemory when QDRANT_MEMORY_ENABLED=false."""
    monkeypatch.delenv("QDRANT_MEMORY_ENABLED", raising=False)

    from memory.vector_memory import get_vector_memory, VectorMemory

    class _MockSettings:
        workspace_dir = str(tmp_path)
        embedding_provider = "local"
        huggingface_api_key = ""

    vm = get_vector_memory(_MockSettings())
    assert isinstance(vm, VectorMemory), \
        "Should return VectorMemory when QDRANT_MEMORY_ENABLED is not set"


def test_get_vector_memory_returns_qdrant_when_enabled(monkeypatch, tmp_path):
    """get_vector_memory returns QdrantVectorMemory when QDRANT_MEMORY_ENABLED=true."""
    monkeypatch.setenv("QDRANT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-unreachable-test:6333")

    from memory.vector_memory import get_vector_memory, QdrantVectorMemory

    class _MockSettings:
        workspace_dir = str(tmp_path)
        embedding_provider = "local"
        huggingface_api_key = ""
        qdrant_url = "http://qdrant-unreachable-test:6333"
        qdrant_api_key = ""

    vm = get_vector_memory(_MockSettings())
    assert isinstance(vm, QdrantVectorMemory), \
        "Should return QdrantVectorMemory when QDRANT_MEMORY_ENABLED=true"


# ── Test 8+9: QdrantVectorMemory fallback ────────────────────────────────────

def test_qdrant_vector_memory_add_falls_back(monkeypatch, tmp_path):
    """QdrantVectorMemory.add() falls back to local VectorMemory on Qdrant error."""
    monkeypatch.setenv("QDRANT_URL", "http://qdrant-unreachable-test:6333")

    from memory.vector_memory import VectorMemory, QdrantVectorMemory

    class _MockSettings:
        workspace_dir = str(tmp_path)
        embedding_provider = "local"
        huggingface_api_key = ""
        qdrant_url = "http://qdrant-unreachable-test:6333"
        qdrant_api_key = ""

    fallback = VectorMemory(_MockSettings())
    qvm = QdrantVectorMemory.__new__(QdrantVectorMemory)
    qvm.s = _MockSettings()
    qvm._fallback = fallback
    qvm._encoder = None
    qvm._qdrant_url = "http://qdrant-unreachable-test:6333"
    qvm._qdrant_key = None
    qvm.COLLECTION = "bea_memory"
    qvm.VECTOR_DIM = 384

    # Should not raise — falls back to local
    doc_id = qvm.add("test document about memory", {"type": "test"})
    assert isinstance(doc_id, str)
    assert doc_id.startswith("vm_")


def test_qdrant_vector_memory_search_falls_back(monkeypatch, tmp_path):
    """QdrantVectorMemory.search() falls back to local VectorMemory on Qdrant error."""
    from memory.vector_memory import VectorMemory, QdrantVectorMemory

    class _MockSettings:
        workspace_dir = str(tmp_path)
        embedding_provider = "local"
        huggingface_api_key = ""
        qdrant_url = "http://qdrant-unreachable-test:6333"
        qdrant_api_key = ""

    fallback = VectorMemory(_MockSettings())
    qvm = QdrantVectorMemory.__new__(QdrantVectorMemory)
    qvm.s = _MockSettings()
    qvm._fallback = fallback
    qvm._encoder = None
    qvm._qdrant_url = "http://qdrant-unreachable-test:6333"
    qvm._qdrant_key = None
    qvm.COLLECTION = "bea_memory"
    qvm.VECTOR_DIM = 384

    # Should not raise — falls back to local (empty list, no docs added)
    results = qvm.search("test query")
    assert isinstance(results, list)


# ── Test 10: register_mcp_adapters contract ───────────────────────────────────

def test_register_mcp_adapters_returns_dict():
    """register_mcp_adapters() is importable and returns a dict with expected keys."""
    from api.startup_checks import register_mcp_adapters
    from config.settings import Settings

    # Ensure flags are off
    os.environ.pop("QDRANT_MCP_ENABLED", None)
    os.environ.pop("GITHUB_MCP_ENABLED", None)

    result = register_mcp_adapters(Settings())
    assert isinstance(result, dict)
    assert "qdrant_mcp" in result
    assert "github_mcp" in result
    assert isinstance(result["qdrant_mcp"], bool)
    assert isinstance(result["github_mcp"], bool)


# ── Test 11: MCPAdapter never raises ─────────────────────────────────────────

def test_mcp_adapter_invoke_tool_never_raises(fresh_registry):
    """invoke_tool returns structured dict even for unknown tools (never raises)."""
    from integrations.mcp.mcp_adapter import MCPAdapter

    adapter = MCPAdapter(registry=fresh_registry)

    result = asyncio.get_event_loop().run_until_complete(
        adapter.invoke_tool("nonexistent::tool", {"key": "value"})
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["tool_id"] == "nonexistent::tool"
    assert "error" in result
    assert "not found" in result["error"].lower()


# ── Test 12: Startup adapter respects env flag ────────────────────────────────

def test_register_mcp_adapters_qdrant_on(monkeypatch):
    """register_mcp_adapters registers qdrant when QDRANT_MCP_ENABLED=true."""
    monkeypatch.setenv("QDRANT_MCP_ENABLED", "true")
    monkeypatch.setenv("QDRANT_MCP_URL", "http://qdrant-mcp-test:8000")
    monkeypatch.delenv("GITHUB_MCP_ENABLED", raising=False)

    from config.settings import Settings
    from api.startup_checks import register_mcp_adapters

    result = register_mcp_adapters(Settings())
    assert result["qdrant_mcp"] is True, "qdrant_mcp should be True when flag is on"
    assert result["github_mcp"] is False, "github_mcp should be False when flag is off"
