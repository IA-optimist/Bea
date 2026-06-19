"""tests/test_mcp_server.py — Bea MCP server tests.

Requires the ``mcp`` package to be installed. If it is absent, the whole module is
skipped.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MCP_SIGNING_SECRET", "test-secret")

mcp_module = pytest.importorskip("mcp.server.fastmcp")

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.mcp.bea.bea_mcp_server import _build_server, _MCP_AVAILABLE


def test_mcp_server_builds() -> None:
    assert _MCP_AVAILABLE, "mcp package should be available after importorskip"
    server = _build_server()
    assert server.name == "bea"
    tools = getattr(server, "_tools", {})
    assert "run_mission" in tools
    assert "memory_search" in tools
    assert "mission_status" in tools
    assert "list_missions" in tools


def test_run_mission_tool_creates_mission_file(monkeypatch, tmp_path: Path) -> None:
    missions_dir = tmp_path / "missions"
    monkeypatch.setattr(
        "core.mcp.bea.bea_mcp_server._MISSIONS_DIR",
        missions_dir,
    )
    server = _build_server()
    run_mission = server._tools["run_mission"].fn
    result = run_mission(goal="integration test")

    assert "mission_" in result
    assert '"status": "submitted"' in result
    assert missions_dir.exists()
    assert any(missions_dir.glob("mission_*.json"))
