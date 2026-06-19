"""
tests/test_mcp_server.py — Test MCP Server with Third-Party Client

Tests the Bea MCP server to ensure it can be called from external MCP clients
like Claude Desktop, Claude Code, or other MCP-compatible tools.
"""
import json
import subprocess
import sys
import threading
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Check MCP availability once at collection time ───────────────────────────
try:
    from core.mcp.bea.bea_mcp_server import _MCP_AVAILABLE
except ImportError:
    _MCP_AVAILABLE = False

_skip_mcp = pytest.mark.skipif(not _MCP_AVAILABLE, reason="mcp package not installed")

# Shared path
_SERVER_PATH = Path(__file__).parent.parent / "core" / "mcp" / "bea" / "bea_mcp_server.py"

_INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0.0"},
    },
}


def _start_server():
    """Helper: start the MCP server subprocess."""
    assert _SERVER_PATH.exists(), f"MCP server not found at {_SERVER_PATH}"
    proc = subprocess.Popen(
        [sys.executable, str(_SERVER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc


def _send(proc, obj):
    """Write a JSON-RPC request to the server stdin."""
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _recv(proc, timeout: float = 10.0):
    """Read one line from stdout and parse JSON.

    Uses a threading.Timer to kill the subprocess if readline blocks
    longer than *timeout* seconds, preventing the test from hanging.
    """
    result = [None]
    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    try:
        line = proc.stdout.readline()
    finally:
        timer.cancel()

    if timed_out.is_set():
        raise TimeoutError(f"_recv timed out after {timeout}s waiting for MCP server response")
    if not line:
        return None
    return json.loads(line)


@_skip_mcp
@pytest.mark.timeout(10)
def test_mcp_server_stdio():
    """Test that the MCP server can start and respond to stdio requests."""
    print("Testing MCP server stdio transport...")

    proc = _start_server()
    try:
        _send(proc, _INIT_REQUEST)
        response = _recv(proc)
        assert response is not None, "No response from server"
        assert "result" in response, f"Unexpected server response: {response}"
        server_info = response.get("result", {}).get("serverInfo", {})
        print(f"✓ Server initialized successfully: {server_info}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@_skip_mcp
@pytest.mark.timeout(10)
def test_mcp_tools_discovery():
    """Test that MCP tools can be discovered."""
    print("\nTesting MCP tools discovery...")

    proc = _start_server()
    try:
        _send(proc, _INIT_REQUEST)
        _recv(proc)  # consume init response

        _send(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        response = _recv(proc)
        assert response is not None, "No response to tools/list request"

        tools = response.get("result", {}).get("tools", [])
        tool_names = [tool.get("name") for tool in tools]

        expected_tools = ["memory_search", "mission_status", "list_missions", "run_mission"]
        missing = [name for name in expected_tools if name not in tool_names]
        assert not missing, f"Missing tools: {missing}. Found: {tool_names}"
        print(f"✓ All expected tools found: {expected_tools}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@_skip_mcp
@pytest.mark.timeout(10)
def test_mcp_tool_call():
    """Test that an MCP tool can be called."""
    print("\nTesting MCP tool call...")

    proc = _start_server()
    try:
        _send(proc, _INIT_REQUEST)
        _recv(proc)  # consume init response

        _send(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_missions", "arguments": {"limit": 5}},
        })
        response = _recv(proc)
        assert response is not None, "No response to tool call"
        assert "error" not in response, f"Tool call error: {response.get('error')}"

        result = response.get("result", {})
        content = result.get("content", [])
        assert len(content) > 0, f"Tool call returned no content: {result}"
        print("✓ Tool call successful: list_missions returned data")
    finally:
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

    for fn in (test_mcp_server_stdio, test_mcp_tools_discovery, test_mcp_tool_call):
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
        print("All tests passed! MCP server is ready for third-party clients.")
        sys.exit(0)
    else:
        print("Some tests failed. MCP server needs fixes.")
        sys.exit(1)
