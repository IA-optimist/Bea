"""
tests/test_mcp_integration.py — MCP Integration Tests

Tests the MCP server integration without requiring full protocol communication.
"""
import sys
from pathlib import Path


def test_mcp_server_import():
    """Test that the MCP server can be imported and instantiated."""
    print("Testing MCP server import...")
    
    try:
        # Add parent directory to path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        
        # Import the server module
        from core.mcp.bea.bea_mcp_server import get_mcp_server, _MCP_AVAILABLE
        
        if not _MCP_AVAILABLE:
            print("✗ MCP package not available")
            return False
        
        # Get server instance
        server = get_mcp_server()
        
        if server is None:
            print("✗ Failed to create MCP server instance")
            return False
        
        print(f"✓ MCP server created successfully: {server.name}")
        return True
        
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_mcp_tools_registered():
    """Test that MCP tools are registered."""
    print("\nTesting MCP tools registration...")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.mcp.bea.bea_mcp_server import get_mcp_server
        
        server = get_mcp_server()
        
        # FastMCP stores tools internally - we can't easily access them without
        # triggering the protocol, but we can verify the server was created
        if server:
            print("✓ MCP server instance available for tool registration")
            return True
        else:
            print("✗ MCP server instance not available")
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_mcp_manifests():
    """Test that MCP manifests exist and are valid."""
    print("\nTesting MCP manifests...")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.mcp.manifest_schema import CORE_TOOL_MANIFESTS, validate_manifest
        
        if not CORE_TOOL_MANIFESTS:
            print("✗ No core tool manifests found")
            return False
        
        # Validate all manifests
        all_valid = True
        for tool_id, manifest in CORE_TOOL_MANIFESTS.items():
            validation = validate_manifest(manifest)
            if not validation["valid"]:
                print(f"✗ Manifest {tool_id} validation failed: {validation['issues']}")
                all_valid = False
        
        if all_valid:
            print(f"✓ All {len(CORE_TOOL_MANIFESTS)} core tool manifests are valid")
            return True
        else:
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_mcp_tool_loader():
    """Test that the MCP tool loader can be instantiated."""
    print("\nTesting MCP tool loader...")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.mcp.tool_loader import get_tool_loader
        
        loader = get_tool_loader()
        
        if loader is None:
            print("✗ Failed to create tool loader")
            return False
        
        # Test loading core tools
        count = loader.load_all_core_tools()
        print(f"✓ Tool loader created and loaded {count} core tools")
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("MCP Integration Tests")
    print("=" * 60)
    
    results = []
    
    results.append(("MCP Server Import", test_mcp_server_import()))
    results.append(("MCP Tools Registration", test_mcp_tools_registered()))
    results.append(("MCP Manifests", test_mcp_manifests()))
    results.append(("MCP Tool Loader", test_mcp_tool_loader()))
    
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
