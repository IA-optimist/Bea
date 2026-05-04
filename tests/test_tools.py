"""Tests live des tools — vérifie l'exécution réelle sur le VPS."""
import pytest
import sys
import os
pytestmark = pytest.mark.integration

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_executor import (
    execute_python_snippet,
    read_file_content,
    run_shell_command,
    # query_vector_db,  # LEGACY désactivé
    get_tool_executor,
    # _ensure_collection,  # LEGACY désactivé
)


@pytest.mark.skip(reason="stale: shell disabled in container")
def test_tool_shell():
    result = run_shell_command("echo hello_jarvis && date")
    assert result["ok"], f"shell failed: {result['error']}"
    assert "hello_jarvis" in result["result"]
    print(f"✅ shell_command OK: {result['result'][:100]}")


def test_tool_read_file():
    with open("/tmp/jarvis_test.txt", "w") as f:
        f.write("test_content_jarvis\n")
    result = read_file_content("/tmp/jarvis_test.txt")
    assert result["ok"], f"read_file failed: {result['error']}"
    assert "test_content_jarvis" in result["result"]
    print(f"✅ read_file OK: {result['result'][:100]}")


@pytest.mark.skip(reason="execute_http_get removed (LEGACY désactivé in core.tool_executor)")
def test_tool_http():
    pass


def test_tool_python():
    result = execute_python_snippet("print(2 + 2)")
    assert result["ok"], f"python failed: {result['error']}"
    assert "4" in result["result"]
    print(f"✅ python_snippet OK: {result['result'][:100]}")


@pytest.mark.skip(reason="_ensure_collection / query_vector_db removed (LEGACY désactivé in core.tool_executor)")
def test_tool_vector_search():
    pass


def test_executor_singleton():
    ex = get_tool_executor()
    tools = ex.list_tools()
    assert "shell_command" in tools
    assert "http_get" in tools
    print(f"✅ ToolExecutor singleton OK: {tools}")


if __name__ == "__main__":
    print("=== TEST TOOLS LIVE ===")
    test_tool_shell()
    test_tool_read_file()
    test_tool_http()
    test_tool_python()
    test_tool_vector_search()
    test_executor_singleton()
    print("=== FIN TESTS ===")
