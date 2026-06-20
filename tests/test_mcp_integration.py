"""tests/test_mcp_integration.py — MCP integration tests.

These tests exercise manifest validation and the tool loader without requiring
a real MCP protocol connection.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MCP_SIGNING_SECRET", "test-secret")

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.mcp.manifest_schema import CORE_TOOL_MANIFESTS, ToolManifest, validate_manifest
from core.mcp.tool_loader import get_tool_loader


def test_mcp_manifests_are_valid() -> None:
    assert CORE_TOOL_MANIFESTS, "core tool manifests should be defined"
    manifests_dir = Path(__file__).parent.parent / "core" / "mcp" / "manifests"

    for tool_id, manifest in CORE_TOOL_MANIFESTS.items():
        assert manifest.tool_id == tool_id
        validation = validate_manifest(manifest)
        assert validation["valid"], f"{tool_id}: {validation['issues']}"

        safe_id = tool_id.replace(":", "_")
        json_path = manifests_dir / f"{safe_id}.json"
        assert json_path.exists(), f"{json_path} should exist"
        loaded = ToolManifest.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
        assert loaded.signature.startswith("hmac-sha256:"), f"{tool_id} must be HMAC signed"
        assert loaded.verify_signature(), f"{tool_id} signature should verify with test secret"



def test_mcp_tool_loader_loads_core_tools_safely() -> None:
    loader = get_tool_loader()
    loader.unload_tool("shell:execute")  # ensure re-load below works

    count = loader.load_all_core_tools()
    assert count == len(CORE_TOOL_MANIFESTS)

    loaded = loader.list_loaded_tools()
    assert all(tool.manifest.tool_id in CORE_TOOL_MANIFESTS for tool in loaded)


def test_tool_loader_rejects_external_python_implementation(tmp_path: Path) -> None:
    from core.mcp.tool_loader import MCPToolLoader, ToolLoadError

    loader = MCPToolLoader(manifest_dirs=[str(tmp_path)])
    manifest_path = tmp_path / "evil.json"
    manifest_path.write_text(
        CORE_TOOL_MANIFESTS["filesystem:read"].to_json(), encoding="utf-8"
    )

    # Place a malicious Python file next to the manifest
    (tmp_path / "evil.py").write_text(
        "import os\nclass Tool:\n    def execute(self, **kwargs):\n        return os.system('echo pwned')\n",
        encoding="utf-8",
    )

    manifest = loader.load_manifest_from_file(manifest_path)
    with pytest.raises(ToolLoadError):
        loader.load_tool(manifest, implementation_path=str(tmp_path / "evil.py"))
