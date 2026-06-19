"""
Tests for execution engine: health gate, adaptive retry, fallback chains,
telemetry, evaluation, recovery memory, tool runner wiring.
"""
import ast
import sys
import pytest
import time
import types

if 'structlog' not in sys.modules:
    sl = types.ModuleType('structlog')
    class ML:
        def info(self,*a,**k): pass
        def debug(self,*a,**k): pass
        def warning(self,*a,**k): pass
        def error(self,*a,**k): pass
    sl.get_logger = lambda *a,**k: ML()
    sys.modules['structlog'] = sl

sys.path.insert(0, '.')


# ═══════════════════════════════════════════════════════════════
# TOOL HEALTH GATE
# ═══════════════════════════════════════════════════════════════

def test_health_check_no_data():
    from core.execution_engine import check_tool_health
    health = check_tool_health("nonexistent_tool")
    assert health["healthy"]
    assert health["status"] == "insufficient_data" or health["status"] == "unknown"


def test_health_check_healthy_tool():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt_mod
    t = ToolPerformanceTracker(persist_path="/tmp/test_hc.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="good_tool", success=True, latency_ms=20))
    old = tpt_mod._tracker
    tpt_mod._tracker = t
    try:
        from core.execution_engine import check_tool_health
        health = check_tool_health("good_tool")
        assert health["healthy"]
        assert health["status"] == "healthy"
    finally:
        tpt_mod._tracker = old


def test_health_check_failing_tool():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt_mod
    t = ToolPerformanceTracker(persist_path="/tmp/test_hc2.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="bad_tool", success=False, latency_ms=100))
    old = tpt_mod._tracker
    tpt_mod._tracker = t
    try:
        from core.execution_engine import check_tool_health
        health = check_tool_health("bad_tool")
        assert not health["healthy"]
        assert health["recommendation"] == "skip_or_fallback"
    finally:
        tpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# FALLBACK CHAINS
# ═══════════════════════════════════════════════════════════════

def test_fallback_tool_exists():
    from core.execution_engine import get_fallback_tool
    fb = get_fallback_tool("shell_command")
    assert fb == "run_command_safe" or fb is not None


def test_fallback_tool_no_alternative():
    from core.execution_engine import get_fallback_tool
    fb = get_fallback_tool("totally_unknown_tool")
    assert fb is None


# ═══════════════════════════════════════════════════════════════
# ADAPTIVE RETRY
# ═══════════════════════════════════════════════════════════════

def test_adapt_params_timeout():
    from core.execution_engine import adapt_params
    params = {"timeout": 10, "url": "http://example.com"}
    adapted = adapt_params("test_endpoint", params, 1, "Request timed out")
    assert adapted["timeout"] == 20  # doubled


def test_adapt_params_path():
    from core.execution_engine import adapt_params
    params = {"path": "config.json"}
    adapted = adapt_params("read_file", params, 0, "No such file or directory")
    assert adapted["path"] == "workspace/config.json"


def test_adapt_params_no_change():
    from core.execution_engine import adapt_params
    params = {"query": "test"}
    adapted = adapt_params("vector_search", params, 0, "some random error")
    assert adapted == params


# ═══════════════════════════════════════════════════════════════
# TELEMETRY
# ═══════════════════════════════════════════════════════════════

def test_step_telemetry():
    from core.execution_engine import StepTelemetry
    s = StepTelemetry(step_id="s1", tool="read_file", success=True, duration_ms=50)
    d = s.to_dict()
    assert d["tool"] == "read_file"
    assert d["success"]


def test_execution_telemetry():
    from core.execution_engine import ExecutionTelemetry, StepTelemetry
    t = ExecutionTelemetry(mission_id="m1", started_at=time.time())
    t.steps.append(StepTelemetry(step_id="s1", tool="a", success=True))
    t.steps.append(StepTelemetry(step_id="s2", tool="b", success=False))
    t.total_retries = 1
    t.finished_at = time.time() + 1
    assert t.success_rate == 0.5
    assert t.stability_score < 0.5


def test_telemetry_buffer():
    from core.execution_engine import (
        record_telemetry, get_recent_telemetry, get_telemetry_summary,
        ExecutionTelemetry, StepTelemetry, _telemetry_buffer,
    )
    _telemetry_buffer.clear()
    t = ExecutionTelemetry(mission_id="test", started_at=time.time())
    t.steps.append(StepTelemetry(step_id="s1", tool="x", success=True))
    t.finished_at = time.time()
    t.total_tools_called = 1
    record_telemetry(t)
    assert len(get_recent_telemetry()) >= 1
    s = get_telemetry_summary()
    assert s["total_missions"] >= 1


# ═══════════════════════════════════════════════════════════════
# POST-MISSION EVALUATION
# ═══════════════════════════════════════════════════════════════

def test_evaluate_mission_success():
    from core.execution_engine import evaluate_mission
    ev = evaluate_mission(
        mission_id="m1", success=True,
        final_output="Here is the completed analysis...",
        goal="Analyze the codebase",
        agents_used=["lens-reviewer"], tools_used=["read_file"],
        duration_s=10.0, plan_steps=3,
    )
    assert ev.goal_completion == 1.0
    assert ev.overall_score >= 0.5


def test_evaluate_mission_failure():
    from core.execution_engine import evaluate_mission
    ev = evaluate_mission(
        mission_id="m2", success=False,
        final_output="", goal="Fix bug",
        agents_used=["forge-builder"], tools_used=[],
        duration_s=5.0, plan_steps=2,
    )
    assert ev.goal_completion == 0.0
    assert ev.overall_score < 0.3


def test_evaluate_with_telemetry():
    from core.execution_engine import evaluate_mission, ExecutionTelemetry, StepTelemetry
    tel = ExecutionTelemetry(mission_id="m3", started_at=time.time())
    tel.steps = [StepTelemetry(step_id="s1", tool="x", success=True)]
    tel.total_retries = 5
    tel.total_fallbacks = 2
    tel.finished_at = time.time()
    ev = evaluate_mission(
        mission_id="m3", success=True,
        final_output="Done", goal="test", agents_used=[], tools_used=[],
        duration_s=5.0, plan_steps=1, telemetry=tel,
    )
    assert ev.tool_efficiency < 0.7  # penalized for retries+fallbacks


def test_evaluation_history():
    from core.execution_engine import (
        evaluate_mission, store_evaluation, get_evaluation_history,
        get_evaluation_trends, _evaluations,
    )
    _evaluations.clear()
    ev = evaluate_mission("t1", True, "output", "goal", [], [], 1.0, 1)
    store_evaluation(ev)
    assert len(get_evaluation_history()) >= 1
    trends = get_evaluation_trends()
    assert trends["total"] >= 1


# ═══════════════════════════════════════════════════════════════
# RECOVERY MEMORY
# ═══════════════════════════════════════════════════════════════

def test_recovery_record_and_retrieve():
    from core.execution_engine import (
        record_recovery, get_best_recovery, _recovery_memory,
    )
    _recovery_memory.clear()
    record_recovery("read_file", "FileNotFoundError", "retry_adapted", success=True)
    record_recovery("read_file", "FileNotFoundError", "retry_adapted", success=True)
    best = get_best_recovery("read_file", "FileNotFoundError")
    assert best is not None
    assert best["success"]
    assert best["count"] >= 2


def test_recovery_stats():
    from core.execution_engine import get_recovery_stats, _recovery_memory
    _recovery_memory.clear()
    from core.execution_engine import record_recovery
    record_recovery("a", "err", "fallback", fallback_tool="b", success=True)
    stats = get_recovery_stats()
    assert stats["total_strategies"] >= 1
    assert stats["successful"] >= 1


# ═══════════════════════════════════════════════════════════════
# WIRING VERIFICATION
# ═══════════════════════════════════════════════════════════════

def test_all_files_syntax():
    files = [
        "core/execution_engine.py",
        "core/tool_runner.py",
        "core/mission_system.py",
        "api/routes/performance.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())


def test_tool_runner_uses_engine():
    with open("core/tool_runner.py", encoding="utf-8") as f:
        src = f.read()
    assert "execution_engine" in src
    assert "execute_tool_intelligently" in src
    assert "_run_with_engine" in src
    ast.parse(src)


def test_mission_system_has_evaluation():
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "evaluate_mission" in src
    assert "store_evaluation" in src
    ast.parse(src)


def test_performance_api_has_execution_endpoints():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "execution/telemetry" in src
    assert "execution/evaluations" in src
    assert "execution/recovery" in src
    ast.parse(src)


@pytest.mark.stale
@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_cockpit_has_telemetry_ui():
    with open("static/cockpit.html", encoding="utf-8") as f:
        html = f.read()
    assert "exec-telemetry" in html
    assert "eval-trend-stats" in html
    assert "Execution Telemetry" in html
    assert "Mission Quality Trends" in html
