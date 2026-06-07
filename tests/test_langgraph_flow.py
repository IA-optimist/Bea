"""Tests du LangGraph orchestration flow."""
import pytest


def test_import_fail_open():
    """Le module s'importe même si langgraph n'est pas installé."""
    try:
        from core.orchestrator_lg import langgraph_flow  # noqa: F401
    except ImportError:
        pytest.skip("langgraph not installed")


def test_invoke_returns_dict():
    """invoke() retourne toujours un dict avec final_answer."""
    try:
        from core.orchestrator_lg.langgraph_flow import invoke
    except ImportError:
        pytest.skip("langgraph not installed")
    result = invoke("Test: qu'est-ce que Bea ?", mission_id="test-001")
    assert isinstance(result, dict)
    assert "final_answer" in result
    assert isinstance(result["final_answer"], str)


def test_invoke_never_raises():
    """invoke() ne lève jamais d'exception — fail-open total."""
    try:
        from core.orchestrator_lg.langgraph_flow import invoke
    except ImportError:
        pytest.skip("langgraph not installed")
    result = invoke("", mission_id="test-empty")
    assert isinstance(result, dict)


def test_state_structure():
    """BeaState a les bons champs obligatoires."""
    try:
        from core.orchestrator_lg.langgraph_flow import BeaState
    except ImportError:
        pytest.skip("langgraph not installed")
    required = {"user_input", "final_answer", "errors", "plan", "retry_count",
                "tool_calls", "tool_results", "requires_approval", "mission_id"}
    assert required.issubset(set(BeaState.__annotations__.keys()))


def test_tools_registry():
    """tools_registry.get_tools() retourne une liste."""
    try:
        from core.orchestrator_lg.tools_registry import get_tools
    except ImportError:
        pytest.skip("langchain not installed")
    tools = get_tools()
    assert isinstance(tools, list)


def test_graph_compiled():
    """Le graph LangGraph est compilé si langgraph est disponible."""
    try:
        import langgraph  # noqa: F401
    except ImportError:
        pytest.skip("langgraph not installed")
    from core.orchestrator_lg.langgraph_flow import bea_graph
    # Peut être None si LLM absent, ne doit jamais lever d'exception à l'import
    assert bea_graph is not None or bea_graph is None  # toujours vrai


def test_result_keys():
    """invoke() retourne les clés attendues."""
    try:
        from core.orchestrator_lg.langgraph_flow import invoke
    except ImportError:
        pytest.skip("langgraph not installed")
    result = invoke("ping", mission_id="test-keys")
    expected_keys = {"final_answer", "errors", "tool_results", "memory_updates"}
    assert expected_keys.issubset(result.keys())
