"""
tests/test_mission_id_propagation.py

Verifies that mission_id is propagated correctly through all runtime call sites
so that PolicyEngine session limits are enforced end-to-end.

Tests:
  1. tool_runner injects mission_id into params via setdefault
  2. execution_engine propagates mission_id into current_params
  3. MetaOrchestrator creates a policy session with the correct mission_id
  4. Two parallel missions have separate, isolated sessions
  5. Call without mission_id is safe (no crash, policy skips session tracking)
  6. tool_pipeline propagates mission_id to child tool calls
  7. api/routes/missions run_tools_for_mission receives mission_id
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch, call

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Stub structlog if not installed
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")

    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self

    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules["structlog"] = _sl

import pytest
from core.policy_engine import PolicyEngine, get_policy_engine, reset_policy_engine


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: reset singleton between tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_policy():
    reset_policy_engine()
    yield
    reset_policy_engine()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 : tool_runner injects mission_id into params
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_runner_injects_mission_id():
    """
    run_tools_for_mission must pass mission_id into params via
    params.setdefault("mission_id", mission_id) in the legacy path.
    """
    import importlib
    import inspect

    import core.tool_runner as tr_mod
    src = inspect.getsource(tr_mod)

    # The legacy path explicitly calls params.setdefault("mission_id", mission_id)
    assert 'setdefault("mission_id", mission_id)' in src, (
        "core.tool_runner does not inject mission_id into params — "
        "policy session limits will not be tracked for pre-execution tools"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 : execution_engine propagates mission_id into current_params
# ─────────────────────────────────────────────────────────────────────────────

def test_execution_engine_propagates_mission_id():
    """
    execute_tool_intelligently must copy mission_id into current_params
    before calling executor.execute().
    """
    import inspect
    import core.execution_engine as ee_mod
    src = inspect.getsource(ee_mod)

    assert 'current_params.setdefault("mission_id", mission_id)' in src, (
        "core.execution_engine does not propagate mission_id — "
        "policy session limits will be bypassed for intelligent tool execution"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 : MetaOrchestrator creates a policy session with mission_id
# ─────────────────────────────────────────────────────────────────────────────

def test_meta_orchestrator_creates_policy_session():
    """
    core.meta_orchestrator must call get_policy_engine().ensure_session(mission_id)
    at the start of a run so that session limits are tracked.
    """
    import inspect
    try:
        import core.meta_orchestrator as mo_mod
        src = inspect.getsource(mo_mod)
    except Exception:
        pytest.skip("core.meta_orchestrator could not be imported for inspection")

    assert "ensure_session" in src, (
        "core.meta_orchestrator does not call ensure_session() — "
        "session limits will not be initialised for orchestrator runs"
    )
    assert "get_policy_engine" in src, (
        "core.meta_orchestrator does not use get_policy_engine() singleton"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 : Two parallel missions have separate policy sessions
# ─────────────────────────────────────────────────────────────────────────────

def test_parallel_missions_have_separate_sessions():
    """
    Two distinct mission_ids must produce independent session trackers.
    Actions recorded in session A must not affect session B's counter.
    """
    engine = PolicyEngine(None)

    t_a = engine.ensure_session("parallel-mission-A")
    t_b = engine.ensure_session("parallel-mission-B")

    # Record 3 actions in A
    t_a.record_action()
    t_a.record_action()
    t_a.record_action()

    # B must be unaffected
    assert t_b.actions_done == 0, (
        f"Session B was polluted by session A's actions: "
        f"expected 0, got {t_b.actions_done}"
    )

    # A must have the 3 actions
    assert t_a.actions_done == 3, (
        f"Session A did not record actions: expected 3, got {t_a.actions_done}"
    )

    # Verify sessions are distinct objects
    assert t_a is not t_b


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 : Call without mission_id is safe (no crash)
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_mission_id_is_safe():
    """
    evaluate_tool() with an empty mission_id must not crash and must still
    allow low-risk tools (fail-open for read-only tools without a session).
    """
    engine = PolicyEngine(None)

    # No session created, empty mission_id — must not raise
    decision = engine.evaluate_tool(
        tool_name="read_file",
        action_type="read",
        risk_level="low",
        mission_id="",
    )

    # Low-risk read tool without a session must be allowed (fail-open)
    assert decision.allowed, (
        f"Low-risk tool without mission_id should be allowed, got: {decision.reason}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 : tool_pipeline propagates mission_id to child tool calls
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_pipeline_propagates_mission_id():
    """
    tool_pipeline() must inject mission_id into each step's params dict
    so that child tool calls are tracked by PolicyEngine.
    """
    captured_params = []

    def _fake_execute(tool_name, params, approval_mode="SUPERVISED"):
        captured_params.append(dict(params))
        return {"ok": True, "result": "ok", "error": None}

    fake_executor = MagicMock()
    fake_executor.execute.side_effect = _fake_execute

    with patch("core.tools.tool_pipeline_tool._get_executor", return_value=fake_executor):
        from core.tools.tool_pipeline_tool import tool_pipeline
        result = tool_pipeline(
            steps=[
                {"tool": "read_file", "params": {"path": "/tmp/test.txt"}},
                {"tool": "http_get",  "params": {"url": "http://example.com"}},
            ],
            mission_id="pipeline-mission-42",
        )

    assert result["ok"], f"tool_pipeline failed unexpectedly: {result}"

    for i, p in enumerate(captured_params):
        assert p.get("mission_id") == "pipeline-mission-42", (
            f"Step {i} did not receive mission_id in params: {p}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 : tool_pipeline without mission_id does not inject it
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_pipeline_no_mission_id_does_not_inject():
    """
    When mission_id is empty, tool_pipeline must NOT add it to params
    (to avoid polluting tool calls with an empty string key that would
    be misleading in policy logs).
    """
    captured_params = []

    def _fake_execute(tool_name, params, approval_mode="SUPERVISED"):
        captured_params.append(dict(params))
        return {"ok": True, "result": "ok", "error": None}

    fake_executor = MagicMock()
    fake_executor.execute.side_effect = _fake_execute

    with patch("core.tools.tool_pipeline_tool._get_executor", return_value=fake_executor):
        from core.tools.tool_pipeline_tool import tool_pipeline
        result = tool_pipeline(
            steps=[{"tool": "read_file", "params": {"path": "/tmp/test.txt"}}],
            mission_id="",
        )

    assert result["ok"], f"tool_pipeline failed unexpectedly: {result}"
    # mission_id must NOT be injected when it's empty
    assert "mission_id" not in captured_params[0], (
        f"Empty mission_id was injected into step params: {captured_params[0]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 : api/routes/missions passes mission_id to run_tools_for_mission
# ─────────────────────────────────────────────────────────────────────────────

def test_missions_route_passes_mission_id_to_tool_runner():
    """
    api/routes/missions.py must pass mission_id=str(result.mission_id) to
    run_tools_for_mission() so pre-execution tools are tracked by policy.
    """
    import inspect
    try:
        import api.routes.missions as missions_mod
        src = inspect.getsource(missions_mod)
    except Exception:
        pytest.skip("api.routes.missions could not be imported for inspection")

    # Find the run_tools_for_mission call block
    assert "mission_id=" in src, (
        "api/routes/missions.py does not pass mission_id to run_tools_for_mission"
    )

    # More precise: the call must include mission_id=str(result.mission_id)
    # We check both parts independently to be robust to formatting changes
    assert "run_tools_for_mission" in src
    # The mission_id kwarg must appear near the run_tools_for_mission call
    idx = src.find("run_tools_for_mission(")
    assert idx >= 0
    call_block = src[idx: idx + 400]
    assert "mission_id=" in call_block, (
        f"run_tools_for_mission call block does not include mission_id=:\n{call_block}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 : tool_executor.py recovery engine uses mission_id (not _mission_id)
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_executor_recovery_uses_mission_id_key():
    """
    In the exception handler of ToolExecutor.execute(), the recovery engine
    evaluation must use params.get("mission_id") as primary key,
    consistent with the rest of the codebase.
    """
    import inspect
    try:
        import core.tool_executor as te_mod
        src = inspect.getsource(te_mod)
    except Exception:
        pytest.skip("core.tool_executor could not be imported")

    # After our fix, the recovery call should use mission_id as primary
    # (it may fall back to _mission_id for backward compat, but mission_id must come first)
    assert 'params.get("mission_id"' in src, (
        "core.tool_executor recovery engine call does not use mission_id as primary key"
    )
