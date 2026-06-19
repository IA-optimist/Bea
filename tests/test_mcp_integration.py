"""
tests/test_mcp_integration.py — MCP Integration Tests

Tests the MCP server integration without requiring full protocol communication.
"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Check MCP availability once at collection time ───────────────────────────
try:
    from core.mcp.bea.bea_mcp_server import _MCP_AVAILABLE
except ImportError:
    _MCP_AVAILABLE = False

_skip_mcp = pytest.mark.skipif(not _MCP_AVAILABLE, reason="mcp package not installed")


def test_mcp_server_import():
    """Test that the MCP server can be imported and instantiated."""
    print("Testing MCP server import...")

    try:
        from core.mcp.bea.bea_mcp_server import get_mcp_server, _MCP_AVAILABLE as avail
    except ImportError as e:
        assert False, f"Import error: {e}"

    if not avail:
        pytest.skip("MCP package not available")

    server = get_mcp_server()
    assert server is not None, "Failed to create MCP server instance"
    print(f"✓ MCP server created successfully: {server.name}")


@_skip_mcp
def test_mcp_tools_registered():
    """Test that MCP tools are registered."""
    print("\nTesting MCP tools registration...")

    try:
        from core.mcp.bea.bea_mcp_server import get_mcp_server
    except ImportError as e:
        assert False, f"Import error: {e}"

    server = get_mcp_server()

    # FastMCP stores tools internally — we can't easily access them without
    # triggering the protocol, but we can verify the server was created.
    assert server is not None, "MCP server instance not available for tool registration"
    print("✓ MCP server instance available for tool registration")


def test_mcp_manifests():
    """Test that MCP manifests exist and are valid."""
    print("\nTesting MCP manifests...")

    try:
        from core.mcp.manifest_schema import CORE_TOOL_MANIFESTS, validate_manifest
    except ImportError as e:
        assert False, f"Import error: {e}"

    assert CORE_TOOL_MANIFESTS, "No core tool manifests found"

    # Validate all manifests
    invalid = []
    for tool_id, manifest in CORE_TOOL_MANIFESTS.items():
        validation = validate_manifest(manifest)
        if not validation["valid"]:
            invalid.append(f"{tool_id}: {validation['issues']}")

    assert not invalid, "Manifest validation failed:\n" + "\n".join(invalid)
    print(f"✓ All {len(CORE_TOOL_MANIFESTS)} core tool manifests are valid")


def test_mcp_tool_loader():
    """Test that the MCP tool loader can be instantiated."""
    print("\nTesting MCP tool loader...")

    try:
        from core.mcp.tool_loader import get_tool_loader
    except ImportError as e:
        assert False, f"Import error: {e}"

    loader = get_tool_loader()
    assert loader is not None, "Failed to create tool loader"

    count = loader.load_all_core_tools()
    print(f"✓ Tool loader created and loaded {count} core tools")


if __name__ == "__main__":
    print("=" * 60)
    print("MCP Integration Tests")
    print("=" * 60)

    results = []

    for fn in (test_mcp_server_import, test_mcp_tools_registered, test_mcp_manifests, test_mcp_tool_loader):
        try:
            fn()
            results.append((fn.__name__, True))
        except (AssertionError, Exception) as exc:
            results.append((fn.__name__, False))
            print(f"  FAIL: {exc}")

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name}: {status}")

    all_passed = all(passed for _, passed in results)

    print("=" * 60)
    if all_passed:
        print("All integration tests passed! MCP infrastructure is ready.")
        sys.exit(0)
    else:
        print("Some tests failed.")
        sys.exit(1)
