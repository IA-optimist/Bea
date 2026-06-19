from __future__ import annotations


import pytest


@pytest.mark.xfail(reason="manifest_version field not wired yet", strict=False)
def test_integrations_mcp_manifest_has_fingerprint() -> None:
    from integrations.mcp.mcp_models import MCPServer, MCPTool

    server = MCPServer(server_id="s1", name="Server", endpoint="http://localhost")
    tool = MCPTool(tool_id="t1", server_id="s1", name="Tool", description="desc")

    server_data = server.to_dict()
    tool_data = tool.to_dict()

    assert server_data["manifest_version"] == "1.0"
    assert tool_data["manifest_version"] == "1.0"
    assert len(server_data["manifest_fingerprint"]) == 64
    assert len(tool_data["manifest_fingerprint"]) == 64


@pytest.mark.xfail(reason="manifest_version field not wired yet", strict=False)
def test_core_mcp_manifest_has_fingerprint() -> None:
    from core.mcp.mcp_registry import MCPServerEntry

    entry = MCPServerEntry(id="m1", name="M", description="desc")
    data = entry.to_dict()

    assert data["manifest_version"] == "1.0"
    assert len(data["manifest_fingerprint"]) == 64

