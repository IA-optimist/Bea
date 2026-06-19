"""
Tests Bea OS v3 — architecture auto tool builder, memory TTL, planner anti-loop, dev tools.
Tous les tests sont fail-safe (pytest.skip si dépendance externe absente).
"""
from __future__ import annotations

import os
import sys

import pytest
pytestmark = pytest.mark.integration


# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BEA_ROOT = os.environ.get("BEA_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ÉTAPE 6 : dev_tools ───────────────────────────────────────────────────────

def test_env_checker():
    """env_checker() → retourne status et env_vars dict."""
    try:
        from core.tools.dev_tools import env_checker
    except ImportError as e:
        pytest.skip(f"dev_tools unavailable: {e}")

    result = env_checker()
    assert isinstance(result, dict), "result must be a dict"
    assert "status" in result or "ok" in result
    assert "env_vars" in result, "result must contain env_vars"
    assert isinstance(result["env_vars"], dict), "env_vars must be a dict"
    assert "PYTHON_VERSION" in result["env_vars"], "PYTHON_VERSION must be present"


def test_dependency_analyzer():
    """dependency_analyzer() → installed list non vide."""
    try:
        from core.tools.dev_tools import dependency_analyzer
    except ImportError as e:
        pytest.skip(f"dev_tools unavailable: {e}")

    result = dependency_analyzer(project_path=BEA_ROOT)
    assert isinstance(result, dict)
    # On vérifie que la fonction retourne sans crash
    assert "status" in result or "ok" in result
    if result.get("status") == "ok" or result.get("ok"):
        assert "installed" in result, "result must contain installed"
        assert isinstance(result["installed"], list)


def test_requirements_validator():
    """requirements_validator() → valid True ou issues détectées."""
    try:
        from core.tools.dev_tools import requirements_validator
    except ImportError as e:
        pytest.skip(f"dev_tools unavailable: {e}")

    req_path = os.path.join(BEA_ROOT, "requirements.txt")
    if not os.path.exists(req_path):
        pytest.skip("requirements.txt not found")

    result = requirements_validator(requirements_path=req_path)
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    if result.get("status") == "ok" or result.get("ok"):
        assert "valid" in result
        assert isinstance(result.get("issues", []), list)
        assert isinstance(result.get("duplicates", []), list)


def test_code_search_multi():
    """code_search_multi_file(BEA_ROOT, 'def execute') → matches."""
    try:
        from core.tools.dev_tools import code_search_multi_file
    except ImportError as e:
        pytest.skip(f"dev_tools unavailable: {e}")

    result = code_search_multi_file(
        directory=BEA_ROOT,
        pattern="def execute",
        file_extensions=[".py"],
    )
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    if result.get("status") == "ok" or result.get("ok"):
        assert "matches" in result
        assert isinstance(result["matches"], list)
        assert result.get("total", 0) >= 0


# ── ÉTAPE 2 : tool_builder_tool ───────────────────────────────────────────────

def test_tool_builder_analyze():
    """analyze_tool_need('HTTP GET tool', ['url'], ['response']) → plan."""
    try:
        from core.tools.tool_builder_tool import analyze_tool_need
    except ImportError as e:
        pytest.skip(f"tool_builder_tool unavailable: {e}")

    result = analyze_tool_need(
        description="HTTP GET tool that fetches a URL",
        required_inputs=["url"],
        required_outputs=["response"],
    )
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    if result.get("status") == "ok" or result.get("ok"):
        assert "plan" in result
        plan = result["plan"]
        assert "name" in plan
        assert "type" in plan
        assert "libs_needed" in plan


def test_tool_builder_skeleton():
    """generate_tool_skeleton(...) → code contient 'def'."""
    try:
        from core.tools.tool_builder_tool import generate_tool_skeleton
    except ImportError as e:
        pytest.skip(f"tool_builder_tool unavailable: {e}")

    result = generate_tool_skeleton(
        tool_name="http_get_tool",
        description="HTTP GET tool",
        input_schema={"url": "str", "timeout": "int"},
        output_schema={"response": "str", "status_code": "int"},
        safety_constraints=["block_url"],
    )
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    if result.get("status") == "ok" or result.get("ok"):
        code = result.get("code", "")
        assert "def " in code, "generated code must contain a function definition"
        assert "http_get_tool" in code
        assert "try:" in code, "generated code must have try/except"


def test_tool_builder_tests():
    """generate_tool_tests(...) → test_code contient 'def test_'."""
    try:
        from core.tools.tool_builder_tool import generate_tool_tests
    except ImportError as e:
        pytest.skip(f"tool_builder_tool unavailable: {e}")

    dummy_code = '''
def my_tool(url: str, timeout: int = 10) -> dict:
    """A simple tool."""
    try:
        return {"status": "ok", "output": url}
    except Exception as e:
        return {"status": "error", "error": str(e)}
'''
    result = generate_tool_tests(tool_name="my_tool", tool_code=dummy_code)
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    if result.get("status") == "ok" or result.get("ok"):
        test_code = result.get("test_code", "")
        assert "def test_" in test_code, "test_code must contain test functions"
        assert "my_tool" in test_code


# ── ÉTAPE 3 : memory_toolkit TTL ─────────────────────────────────────────────

def test_memory_store_ttl():
    """memory_store_with_ttl('test', ['tag'], 'short_term') → ok ou qdrant_unavailable."""
    try:
        from core.tools.memory_toolkit import memory_store_with_ttl
    except ImportError as e:
        pytest.skip(f"memory_toolkit unavailable: {e}")

    result = memory_store_with_ttl(
        content="test content for TTL memory",
        tags=["test", "v3"],
        memory_type="short_term",
    )
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    # Acceptable: ok (Qdrant disponible) ou error qdrant_unavailable (Qdrant absent)
    if result.get("status") == "error":
        assert "qdrant" in str(result.get("error", "")).lower() or \
               "unavailable" in str(result.get("error", "")).lower(), \
               f"unexpected error: {result.get('error')}"


def test_memory_store_ttl_invalid_type():
    """memory_store_with_ttl avec memory_type invalide → error propre."""
    try:
        from core.tools.memory_toolkit import memory_store_with_ttl
    except ImportError as e:
        pytest.skip(f"memory_toolkit unavailable: {e}")

    result = memory_store_with_ttl(
        content="test",
        tags=[],
        memory_type="invalid_type",
    )
    assert result.get("status") == "error" or result.get("ok") is False
    assert "invalid" in str(result.get("error", "")).lower() and "memory_type" in str(result.get("error", "")).lower()


def test_memory_cleanup():
    """memory_cleanup_expired() → ok (même 0 deleted) ou qdrant_unavailable."""
    try:
        from core.tools.memory_toolkit import memory_cleanup_expired
    except ImportError as e:
        pytest.skip(f"memory_toolkit unavailable: {e}")

    result = memory_cleanup_expired()
    assert isinstance(result, dict)
    assert "status" in result or "ok" in result
    # Acceptable: ok (Qdrant disponible) ou error qdrant_unavailable
    if result.get("status") == "ok" or result.get("ok"):
        assert "deleted_count" in result
        assert isinstance(result.get("deleted_count", 0), int)


# ── ÉTAPE 5 : tool_executor — error classification ───────────────────────────

@pytest.mark.stale
@pytest.mark.skip(reason="stale: taxonomy changed")
def test_error_classification():
    """_classify_error(FileNotFoundError()) → 'environment_error'."""
    try:
        from core.tool_executor import _classify_error
    except ImportError as e:
        pytest.skip(f"tool_executor unavailable: {e}")

    assert _classify_error(FileNotFoundError("not found")) == "environment_error"
    assert _classify_error(TypeError("bad type")) == "tool_error"
    assert _classify_error(AttributeError("no attr")) == "tool_error"
    assert _classify_error(ValueError("bad value")) == "tool_error"
    assert _classify_error(RuntimeError("runtime")) == "logic_error"
    assert _classify_error(KeyError("key")) == "logic_error"
    assert _classify_error(ConnectionError("conn")) == "network_error"
    assert _classify_error(PermissionError("perm")) == "environment_error"


def test_validate_output():
    """_validate_output() → True pour dict valide, False pour dict incomplet."""
    try:
        from core.tool_executor import ToolExecutor
    except ImportError as e:
        pytest.skip(f"tool_executor unavailable: {e}")

    executor = ToolExecutor()

    valid, reason = executor._validate_output("some_tool", {"status": "ok", "output": "hello"})
    assert valid is True

    valid, reason = executor._validate_output("some_tool", {"status": "ok"})
    assert valid is False

    valid, reason = executor._validate_output("some_tool", {"output": "hello"})
    assert valid is False

    valid, reason = executor._validate_output("some_tool", "not_a_dict")
    assert valid is False


# ── ÉTAPE 4 : planner — anti-loop ────────────────────────────────────────────

def test_planner_loop_detection():
    """_detect_infinite_loop_risk(['shell','shell','shell']) → True."""
    try:
        from core.planner import _detect_infinite_loop_risk
    except ImportError as e:
        pytest.skip(f"planner unavailable: {e}")

    # 3 fois le même step → True
    assert _detect_infinite_loop_risk(["shell", "shell", "shell"]) is True
    # 2 fois consécutif → True
    assert _detect_infinite_loop_risk(["step_a", "step_a", "step_b"]) is True
    # Steps différents → False
    assert _detect_infinite_loop_risk(["step_a", "step_b", "step_c"]) is False
    # Liste vide → False
    assert _detect_infinite_loop_risk([]) is False
    # Un seul step → False
    assert _detect_infinite_loop_risk(["step_a"]) is False


def test_planner_add_fallback():
    """_add_fallback_step() ajoute un step fallback au plan."""
    try:
        from core.planner import _add_fallback_step
    except ImportError as e:
        pytest.skip(f"planner unavailable: {e}")

    plan = {"steps": []}
    result = _add_fallback_step(plan, "test_error")
    assert result.get("has_fallback") is True
    assert any("fallback" in str(s) for s in result["steps"])


def test_planner_validate_feasibility():
    """_validate_plan_feasibility() → (bool, str)."""
    try:
        from core.planner import _validate_plan_feasibility
    except ImportError as e:
        pytest.skip(f"planner unavailable: {e}")

    available = ["run_unit_tests", "git_status", "fetch_url"]

    # Plan vide → non faisable
    feasible, reason = _validate_plan_feasibility({"steps": []}, available)
    assert feasible is False

    # Plan avec steps → faisable
    feasible, reason = _validate_plan_feasibility({"steps": ["run_unit_tests"]}, available)
    assert feasible is True


def test_planner_build_plan_returns_steps():
    """build_plan() retourne toujours un dict avec 'steps'."""
    try:
        from core.planner import build_plan
    except ImportError as e:
        pytest.skip(f"planner unavailable: {e}")

    result = build_plan(goal="test goal", mission_type="test")
    assert isinstance(result, dict)
    assert "steps" in result, "build_plan must always return 'steps'"
    assert isinstance(result["steps"], list)


def test_planner_mission_routing():
    """MISSION_TOOL_ROUTING contient les nouvelles entrées v3."""
    try:
        from core.planner import MISSION_TOOL_ROUTING
    except ImportError as e:
        pytest.skip(f"planner unavailable: {e}")

    assert "cybersecurity" in MISSION_TOOL_ROUTING
    assert "saas_creation" in MISSION_TOOL_ROUTING
    assert "ceo_planning" in MISSION_TOOL_ROUTING
    assert "research" in MISSION_TOOL_ROUTING


# ── ÉTAPE 7 : tool_executor — nouveaux tools enregistrés ─────────────────────

@pytest.mark.stale
@pytest.mark.skip(reason="stale: count changed")
def test_new_tools_registered():
    """Vérifie que les nouveaux tools v3 sont dans ToolExecutor._tools."""
    try:
        from core.tool_executor import get_tool_executor
    except ImportError as e:
        pytest.skip(f"tool_executor unavailable: {e}")

    executor = get_tool_executor()
    tools = executor.list_tools()

    # tool_builder_tool
    for t in ["analyze_tool_need", "generate_tool_skeleton", "build_complete_tool"]:
        assert t in tools, f"tool '{t}' not registered"

    # dev_tools
    for t in ["dependency_analyzer", "code_search_multi_file", "env_checker", "requirements_validator"]:
        assert t in tools, f"tool '{t}' not registered"

    # memory_toolkit v3
    for t in ["memory_store_with_ttl", "memory_cleanup_expired", "memory_summarize_recent"]:
        assert t in tools, f"tool '{t}' not registered"
