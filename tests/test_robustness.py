"""
Tests de robustesse — retry, validation params, planner fallback.
Couvre les 3 nouvelles fonctionnalités de la mission auto-amélioration niveau 2.
"""
import sys
import os
import pytest
pytestmark = pytest.mark.integration

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch
from core.tool_executor import ToolExecutor, get_tool_executor
from core.planner import build_plan, get_planner


# ── Test 1 : Retry automatique ─────────────────────────────────────────────────

def test_tool_retry():
    """Un tool qui échoue une fois doit être retenté — ok=True au 2ème essai."""
    ex = ToolExecutor()
    call_count = 0

    def flaky_tool(cmd: str, timeout: int = 10) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"ok": False, "result": "", "error": "transient_error"}
        return {"ok": True, "result": "success_on_retry", "error": None}

    ex._tools["shell_command"] = flaky_tool

    result = ex._execute_with_retry("shell_command", {"cmd": "echo test"}, max_retries=1)
    assert result["ok"], f"expected ok=True after retry, got: {result}"
    assert call_count == 2, f"expected 2 calls (1 fail + 1 retry), got: {call_count}"
    print(f"✅ test_tool_retry OK: {result['result']} (calls={call_count})")


# ── Test 2 : Validation paramètre manquant ─────────────────────────────────────

def test_tool_missing_param():
    """Appel sans param requis → ok=False avec error 'missing param: X'."""
    ex = get_tool_executor()

    # shell_command requiert 'cmd'
    result = ex.execute("shell_command", {})
    assert not result["ok"], "expected ok=False for missing param"
    assert "missing param" in result.get("error", ""), f"unexpected error: {result['error']}"
    assert result.get("blocked_by_policy") is False
    print(f"✅ test_tool_missing_param OK: {result['error']}")

    # http_get requiert 'url'
    result2 = ex.execute("http_get", {})
    assert not result2["ok"]
    assert "missing param" in result2.get("error", "")
    print(f"✅ test_tool_missing_param (http_get) OK: {result2['error']}")


# ── Test 3 : Planner fallback ───────────────────────────────────────────────────

def test_planner_fallback():
    """Si MissionPlanner lève une exception → plan minimal retourné, jamais d'exception."""
    with patch("core.mission_planner.get_mission_planner") as mock_factory:
        mock_factory.side_effect = RuntimeError("simulated planner crash")
        result = build_plan(goal="deploy broken", mission_type="system_task")

    assert "steps" in result, "fallback plan must have 'steps' key"
    assert result["steps"] == ["fallback: direct execution"]
    assert result["error"] is not None
    assert "simulated planner crash" in result["error"]
    print(f"✅ test_planner_fallback OK: steps={result['steps']} error={result['error'][:50]}")


def test_planner_normal():
    """Appel normal du planner — retourne un plan ou exécution directe, jamais d'exception."""
    result = build_plan(goal="créer une api REST", mission_type="coding_task", complexity="medium")
    assert "steps" in result, "plan must have 'steps' key"
    assert isinstance(result["steps"], list)
    print(f"✅ test_planner_normal OK: steps_count={len(result['steps'])}")


def test_planner_singleton():
    p1 = get_planner()
    p2 = get_planner()
    assert p1 is p2, "get_planner() should return singleton"
    print("✅ test_planner_singleton OK")


if __name__ == "__main__":
    print("=== TEST ROBUSTNESS ===")
    test_tool_retry()
    test_tool_missing_param()
    test_planner_fallback()
    test_planner_normal()
    test_planner_singleton()
    print("=== ALL TESTS PASSED ===")
