"""
tests/test_capability_contracts.py — Tests for MCP, plugin, and capability dispatch.

All tests are sync-compatible (no pytest-asyncio required).
Async tests use asyncio.run().
"""
from __future__ import annotations
import asyncio
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor.capability_contracts import (
    CapabilityRequest, CapabilityResult, CapabilityType
)
from executor.capability_dispatch import CapabilityDispatcher
from integrations.mcp.mcp_models import MCPServer, MCPTool
from integrations.mcp.mcp_registry import MCPRegistry
from plugins.plugin_models import PluginMetadata
from plugins.plugin_registry import PluginRegistry


# ── Fixtures ─────────────────────────────────────────────────

class FakePlugin:
    metadata = PluginMetadata(
        plugin_id="test_plugin",
        name="Test Plugin",
        description="Plugin for testing",
        capability_type="tool",
        risk_level="low",
    )

    def invoke(self, action: str, params: dict, context: dict) -> dict:
        return {"action": action, "params": params, "status": "ok"}

    def health_check(self) -> str:
        return "ok"


class FailingPlugin:
    metadata = PluginMetadata(
        plugin_id="fail_plugin",
        name="Failing Plugin",
        description="Always fails",
        capability_type="tool",
        risk_level="low",
    )

    def invoke(self, action: str, params: dict, context: dict) -> dict:
        raise RuntimeError("intentional failure")

    def health_check(self) -> str:
        return "unavailable"


# ── CapabilityContracts ───────────────────────────────────────

class TestCapabilityContracts(unittest.TestCase):

    def test_capability_request_native(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.NATIVE_TOOL,
            capability_id="my_tool",
            params={"x": 1},
        )
        self.assertEqual(req.capability_type, CapabilityType.NATIVE_TOOL)
        self.assertEqual(req.capability_id, "my_tool")

    def test_capability_result_success(self):
        r = CapabilityResult.success(
            CapabilityType.NATIVE_TOOL, "my_tool", {"out": 42}, ms=5
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.result, {"out": 42})
        self.assertIsNone(r.error)

    def test_capability_result_failure(self):
        r = CapabilityResult.failure(
            CapabilityType.PLUGIN, "bad_plugin", "plugin crash", ms=3
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "plugin crash")
        self.assertIsNone(r.result)

    def test_to_dict(self):
        r = CapabilityResult.success(
            CapabilityType.MCP_TOOL, "mcp_search", "result_data", ms=10
        )
        d = r.to_dict()
        self.assertEqual(d["capability_type"], "mcp_tool")
        self.assertTrue(d["ok"])


# ── CapabilityDispatcher — native ────────────────────────────

class TestCapabilityDispatcherNative(unittest.TestCase):

    def setUp(self):
        self.dispatcher = CapabilityDispatcher()
        self.dispatcher.register_native_tool("add", lambda x, y: x + y)

    def test_native_tool_ok(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.NATIVE_TOOL,
            capability_id="add",
            params={"x": 3, "y": 4},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertTrue(result.ok)
        self.assertEqual(result.result, 7)

    def test_native_tool_not_registered(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.NATIVE_TOOL,
            capability_id="nonexistent",
            params={},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertFalse(result.ok)
        self.assertIn("not registered", result.error)


# ── CapabilityDispatcher — plugin ────────────────────────────

class TestCapabilityDispatcherPlugin(unittest.TestCase):

    def setUp(self):
        self.dispatcher = CapabilityDispatcher()
        self.registry = PluginRegistry()
        self.registry.register(FakePlugin())
        self.registry.register(FailingPlugin())
        # Patch singleton
        import plugins.plugin_registry as pr
        self._orig = pr._registry
        pr._registry = self.registry

    def tearDown(self):
        import plugins.plugin_registry as pr
        pr._registry = self._orig

    def test_plugin_invoke_ok(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.PLUGIN,
            capability_id="test_plugin",
            action="run",
            params={"key": "val"},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertTrue(result.ok)
        self.assertEqual(result.result["action"], "run")

    def test_plugin_invoke_failure_structured(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.PLUGIN,
            capability_id="fail_plugin",
            action="run",
            params={},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertFalse(result.ok)
        self.assertIn("intentional failure", result.error)

    def test_plugin_not_registered(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.PLUGIN,
            capability_id="ghost_plugin",
            action="run",
            params={},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertFalse(result.ok)
        self.assertIn("unavailable", result.error)

    def test_plugin_disabled_returns_failure(self):
        self.registry.disable("test_plugin")
        req = CapabilityRequest(
            capability_type=CapabilityType.PLUGIN,
            capability_id="test_plugin",
            action="run",
            params={},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertFalse(result.ok)


# ── CapabilityDispatcher — MCP ────────────────────────────────

class TestCapabilityDispatcherMCP(unittest.TestCase):

    def setUp(self):
        self.dispatcher = CapabilityDispatcher()

    def test_mcp_no_adapter(self):
        req = CapabilityRequest(
            capability_type=CapabilityType.MCP_TOOL,
            capability_id="mcp_search",
            params={},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertFalse(result.ok)
        self.assertIn("No MCP adapter", result.error)

    def test_mcp_with_fake_adapter(self):
        class FakeMCPAdapter:
            async def invoke_tool(self, tool_id, params, context):
                return {"ok": True, "result": {"answer": 42}, "ms": 5}

        self.dispatcher.set_mcp_adapter(FakeMCPAdapter())
        req = CapabilityRequest(
            capability_type=CapabilityType.MCP_TOOL,
            capability_id="mcp_search",
            params={"q": "test"},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertTrue(result.ok)
        self.assertEqual(result.result["answer"], 42)

    def test_mcp_adapter_failure_structured(self):
        class FailMCPAdapter:
            async def invoke_tool(self, tool_id, params, context):
                return {"ok": False, "result": None,
                        "error": "connection refused", "ms": 2}

        self.dispatcher.set_mcp_adapter(FailMCPAdapter())
        req = CapabilityRequest(
            capability_type=CapabilityType.MCP_TOOL,
            capability_id="mcp_search",
            params={},
        )
        result = asyncio.run(self.dispatcher.dispatch(req))
        self.assertFalse(result.ok)
        self.assertIn("connection refused", result.error)


# ── MCPRegistry ───────────────────────────────────────────────

class TestMCPRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = MCPRegistry()
        self.server = MCPServer(
            server_id="s1", name="Test MCP",
            endpoint="http://localhost:3001", transport="http"
        )
        self.tool = MCPTool(
            tool_id="t1", server_id="s1",
            name="search", description="Search tool"
        )

    def test_register_server(self):
        self.registry.register_server(self.server)
        s = self.registry.get_server("s1")
        self.assertIsNotNone(s)
        self.assertEqual(s.name, "Test MCP")

    def test_register_tool(self):
        self.registry.register_server(self.server)
        self.registry.register_tool(self.tool)
        t = self.registry.get_tool("t1")
        self.assertIsNotNone(t)
        self.assertEqual(t.name, "search")

    def test_update_health(self):
        self.registry.register_server(self.server)
        self.registry.update_health("s1", "ok")
        s = self.registry.get_server("s1")
        self.assertEqual(s.health_status, "ok")

    def test_unregister_removes_tools(self):
        self.registry.register_server(self.server)
        self.registry.register_tool(self.tool)
        self.registry.unregister_server("s1")
        self.assertIsNone(self.registry.get_server("s1"))
        self.assertIsNone(self.registry.get_tool("t1"))

    def test_list_healthy_only(self):
        self.registry.register_server(self.server)
        self.assertEqual(len(self.registry.list_servers(healthy_only=True)), 0)
        self.registry.update_health("s1", "ok")
        self.assertEqual(len(self.registry.list_servers(healthy_only=True)), 1)


# ── PluginRegistry ────────────────────────────────────────────

class TestPluginRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = PluginRegistry()

    def test_register_valid_plugin(self):
        ok = self.registry.register(FakePlugin())
        self.assertTrue(ok)
        self.assertEqual(len(self.registry.list_available()), 1)

    def test_register_invalid_plugin(self):
        class BadPlugin:
            pass
        ok = self.registry.register(BadPlugin())
        self.assertFalse(ok)

    def test_disable_plugin(self):
        self.registry.register(FakePlugin())
        self.registry.disable("test_plugin")
        self.assertFalse(self.registry.is_available("test_plugin"))
        self.assertEqual(len(self.registry.list_available()), 0)

    def test_enable_plugin(self):
        self.registry.register(FakePlugin())
        self.registry.disable("test_plugin")
        self.registry.enable("test_plugin")
        self.assertTrue(self.registry.is_available("test_plugin"))

    def test_health_status_update(self):
        self.registry.register(FakePlugin())
        self.registry.update_status("test_plugin", "degraded", "slow response")
        status = self.registry.get_status("test_plugin")
        self.assertEqual(status.health_status, "degraded")
        self.assertEqual(status.error, "slow response")

    def test_stats(self):
        self.registry.register(FakePlugin())
        stats = self.registry.stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["available"], 1)


if __name__ == "__main__":
    unittest.main()
