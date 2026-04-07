"""Tests live des tools — vérifie l'exécution réelle sur le VPS."""
import pytest
import sys, os
pytestmark = pytest.mark.integration

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_executor import (
    execute_python_snippet,
    read_file_content,
    write_file_safe,
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


def test_tool_http():
    result = execute_http_get("https://httpbin.org/json", timeout=8)
    print(f"{'✅' if result['ok'] else '⚠️'} http_get: {result['result'][:100] if result['ok'] else result['error']}")


def test_tool_python():
    result = execute_python_snippet("print(2 + 2)")
    assert result["ok"], f"python failed: {result['error']}"
    assert "4" in result["result"]
    print(f"✅ python_snippet OK: {result['result'][:100]}")


def test_tool_vector_search():
    # Test 1 : création collection
    ok = _ensure_collection("default_memory")
    print(f"{'✅' if ok else '⚠️'} collection ensure: {'created/ready' if ok else 'qdrant offline'}")

    # Test 2 : insertion d'un point de test
    try:
        import requests
        point = {
            "points": [{
                "id": 1,
                "vector": [0.1] * 768,
                "payload": {"test": "jarvis_vector_test", "source": "test_suite"}
            }]
        }
        r = requests.put("http://qdrant:6333/collections/default_memory/points", json=point, timeout=5)
        print(f"{'✅' if r.status_code in (200,201) else '⚠️'} insert test point: status={r.status_code}")
    except Exception as e:
        print(f"⚠️ insert skipped: {e}")

    # Test 3 : recherche
    result = query_vector_db("test query", collection="default_memory", top_k=1)
    print(f"{'✅' if result['ok'] else '⚠️'} vector_search: {result.get('result','')[:150] or result.get('error','')}")


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
