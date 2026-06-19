"""
tests/test_mcp_server.py — Test MCP Server with Third-Party Client

Tests the Bea MCP server to ensure it can be called from external MCP clients
like Claude Desktop, Claude Code, or other MCP-compatible tools.
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def test_mcp_server_stdio():
    """Test that the MCP server can start and respond to stdio requests."""
    print("Testing MCP server stdio transport...")
    
    # Start the MCP server in stdio mode
    server_path = Path(__file__).parent.parent / "core" / "mcp" / "bea" / "bea_mcp_server.py"
    
    try:
        # Send a simple initialization request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        
        # Start the server process
        proc = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        # Send initialization request
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()
        
        # Wait for response with timeout
        try:
            response_line = proc.stdout.readline()
            if response_line:
                response = json.loads(response_line)
                print(f"✓ Server initialized successfully: {response.get('result', {}).get('serverInfo', {})}")
                return True
            else:
                print("✗ No response from server")
                return False
        except subprocess.TimeoutExpired:
            print("✗ Server response timeout")
            proc.terminate()
            return False
        except json.JSONDecodeError as e:
            print(f"✗ Invalid JSON response: {e}")
            proc.terminate()
            return False
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                
    except FileNotFoundError:
        print(f"✗ MCP server not found at {server_path}")
        return False
    except Exception as e:
        print(f"✗ Error testing MCP server: {e}")
        return False


def test_mcp_tools_discovery():
    """Test that MCP tools can be discovered."""
    print("\nTesting MCP tools discovery...")
    
    server_path = Path(__file__).parent.parent / "core" / "mcp" / "bea" / "bea_mcp_server.py"
    
    try:
        proc = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        # Initialize first
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()
        proc.stdout.readline()  # Consume init response
        
        # Request tools list
        tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        proc.stdin.write(json.dumps(tools_request) + "\n")
        proc.stdin.flush()
        
        response_line = proc.stdout.readline()
        if response_line:
            response = json.loads(response_line)
            tools = response.get('result', {}).get('tools', [])
            tool_names = [tool.get('name') for tool in tools]
            
            expected_tools = ['memory_search', 'mission_status', 'list_missions', 'run_mission']
            found_tools = [name for name in expected_tools if name in tool_names]
            
            if len(found_tools) == len(expected_tools):
                print(f"✓ All expected tools found: {found_tools}")
                return True
            else:
                print(f"✗ Missing tools: {set(expected_tools) - set(found_tools)}")
                return False
        else:
            print("✗ No response to tools/list request")
            return False
            
    except Exception as e:
        print(f"✗ Error testing tools discovery: {e}")
        return False
    finally:
        if 'proc' in locals():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_mcp_tool_call():
    """Test that an MCP tool can be called."""
    print("\nTesting MCP tool call...")
    
    server_path = Path(__file__).parent.parent / "core" / "mcp" / "bea" / "bea_mcp_server.py"
    
    try:
        proc = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        # Initialize
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()
        proc.stdout.readline()
        
        # Call list_missions tool
        tool_call_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "list_missions",
                "arguments": {"limit": 5}
            }
        }
        proc.stdin.write(json.dumps(tool_call_request) + "\n")
        proc.stdin.flush()
        
        response_line = proc.stdout.readline()
        if response_line:
            response = json.loads(response_line)
            if 'result' in response:
                result = response['result']
                if 'content' in result and len(result['content']) > 0:
                    print(f"✓ Tool call successful: list_missions returned data")
                    return True
                else:
                    print(f"✗ Tool call returned no content: {result}")
                    return False
            else:
                print(f"✗ Tool call error: {response.get('error')}")
                return False
        else:
            print("✗ No response to tool call")
            return False
            
    except Exception as e:
        print(f"✗ Error testing tool call: {e}")
        return False
    finally:
        if 'proc' in locals():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    print("=" * 60)
    print("MCP Server Third-Party Client Test")
    print("=" * 60)
    
    results = []
    
    results.append(("Server Initialization", test_mcp_server_stdio()))
    results.append(("Tools Discovery", test_mcp_tools_discovery()))
    results.append(("Tool Call", test_mcp_tool_call()))
    
    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name}: {status}")
    
    all_passed = all(passed for _, passed in results)
    
    print("=" * 60)
    if all_passed:
        print("All tests passed! MCP server is ready for third-party clients.")
        sys.exit(0)
    else:
        print("Some tests failed. MCP server needs fixes.")
        sys.exit(1)
