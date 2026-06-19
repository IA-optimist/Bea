"""
Beta Completion Tests
========================
End-to-end lifecycle validation, execution reliability,
tool ecosystem intelligence, cockpit wiring, confidence.
"""
import ast
import os
import sys
import pytest
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
# LIFECYCLE TRACKER
# ═══════════════════════════════════════════════════════════════

def test_lifecycle_full_flow():
    """Simulate a complete mission lifecycle."""
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()
    lt.start("m1")
    lt.record("m1", "plan_generated")
    lt.record("m1", "agents_selected")
    lt.record("m1", "tools_executed")
    lt.record("m1", "results_evaluated")
    lt.record("m1", "memory_updated")
    lt.record("m1", "proposals_checked")
    rec = lt.finish("m1")
    assert rec is not None
    assert rec.is_complete
    assert rec.coverage == 1.0
    assert len(rec.stages) == 7


def test_lifecycle_partial():
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()
    lt.start("m2")
    lt.record("m2", "plan_generated")
    rec = lt.get("m2")
    assert not rec.is_complete
    assert rec.coverage < 0.5


def test_lifecycle_dashboard():
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()
    for i in range(5):
        lt.start(f"d{i}")
        lt.record(f"d{i}", "plan_generated")
        lt.record(f"d{i}", "agents_selected")
        lt.record(f"d{i}", "tools_executed")
        lt.record(f"d{i}", "results_evaluated")
        lt.record(f"d{i}", "memory_updated")
        lt.record(f"d{i}", "proposals_checked")
        lt.finish(f"d{i}")
    d = lt.get_dashboard_data()
    assert d["total"] == 5
    assert d["complete"] == 5
    assert d["complete_rate"] == 1.0
    assert all(v == 1.0 for v in d["stage_rates"].values())


def test_lifecycle_bounded():
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()
    lt.MAX_RECORDS = 10
    for i in range(20):
        lt.start(f"b{i}")
    assert len(lt._records) <= 10


def test_lifecycle_error_tracking():
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()
    lt.start("e1")
    lt.record_error("e1", "tools_executed", "TimeoutError")
    rec = lt.get("e1")
    assert len(rec.errors) == 1
    assert "TimeoutError" in rec.errors[0]


# ═══════════════════════════════════════════════════════════════
# VOLATILITY DETECTION
# ═══════════════════════════════════════════════════════════════

def test_should_retry_no_data():
    from core.execution_engine import should_retry
    assert should_retry("unknown_tool", 0)


def test_should_retry_volatile_tool():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt
    t = ToolPerformanceTracker(persist_path="/tmp/test_vol.jsonl")
    # Create highly volatile pattern: T F T F T F T F T F
    for i in range(10):
        t.record(ToolExecution(tool="volatile", success=i % 2 == 0, latency_ms=10))
    old = tpt._tracker
    tpt._tracker = t
    try:
        from core.execution_engine import should_retry
        # First attempt allowed, second should be denied
        assert should_retry("volatile", 0)
        assert not should_retry("volatile", 1)
    finally:
        tpt._tracker = old


def test_should_retry_stable_tool():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt
    t = ToolPerformanceTracker(persist_path="/tmp/test_stable.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="stable", success=True, latency_ms=10))
    old = tpt._tracker
    tpt._tracker = t
    try:
        from core.execution_engine import should_retry
        assert should_retry("stable", 0)
        assert should_retry("stable", 1)
    finally:
        tpt._tracker = old


def test_should_retry_failing_tool():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt
    t = ToolPerformanceTracker(persist_path="/tmp/test_fail.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="broken", success=False, latency_ms=10))
    old = tpt._tracker
    tpt._tracker = t
    try:
        from core.execution_engine import should_retry
        assert not should_retry("broken", 0)
    finally:
        tpt._tracker = old


# ═══════════════════════════════════════════════════════════════
# IMPACT SCORING
# ═══════════════════════════════════════════════════════════════

def test_impact_scoring():
    from core.improvement_detector import _compute_impact_score
    tool_fix = {"type": "tool_fix", "risk_score": 2}
    new_tool = {"type": "new_tool", "risk_score": 8}
    assert _compute_impact_score(tool_fix) > _compute_impact_score(new_tool)


def test_detector_produces_impact_scores():
    os.environ.pop("BEA_DISABLE_PROPOSALS", None)
    os.environ.pop("BEA_DISABLE_ALL_INTELLIGENCE", None)
    from core.improvement_detector import detect_improvements
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt
    t = ToolPerformanceTracker(persist_path="/tmp/test_impact.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="bad", success=False, latency_ms=100))
    old = tpt._tracker
    tpt._tracker = t
    try:
        proposals = detect_improvements(dry_run=True)
        if proposals:
            assert "impact_score" in proposals[0]
    finally:
        tpt._tracker = old


# ═══════════════════════════════════════════════════════════════
# END-TO-END SIMULATED MISSION
# ═══════════════════════════════════════════════════════════════

def test_e2e_mission_signals():
    """
    Simulate a complete mission lifecycle through all intelligence layers.
    Verify every signal is recorded correctly.
    """
    from core.lifecycle_tracker import LifecycleTracker
    import core.lifecycle_tracker as lt_mod

    # Fresh tracker
    lt = LifecycleTracker()
    lt_mod._tracker = lt

    # 1. Mission received
    lt.start("e2e-1")

    # 2. Plan generated
    lt.record("e2e-1", "plan_generated")

    # 3. Agents selected
    lt.record("e2e-1", "agents_selected")

    # 4. Tools executed
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt
    tracker = ToolPerformanceTracker(persist_path="/tmp/test_e2e.jsonl")
    tracker.record(ToolExecution(tool="read_file", success=True, latency_ms=30))
    tpt._tracker = tracker
    lt.record("e2e-1", "tools_executed")

    # 5. Results evaluated
    import core.execution_engine as ee
    ee._evaluations = []
    ev = ee.evaluate_mission(
        "e2e-1", True, "Analysis complete — here is the full detailed report of findings.",
        "Analyze code", ["forge-builder"], ["read_file"], 5.0, 2,
    )
    ee.store_evaluation(ev)
    lt.record("e2e-1", "results_evaluated")

    # 6. Memory updated
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.mission_performance_tracker as mpt
    mt = MissionPerformanceTracker(persist_path="/tmp/test_e2e_mp.json")
    mt.record(MissionOutcome(
        mission_id="e2e-1", mission_type="coding_task",
        success=True, agents_used=["forge-builder"], tools_used=["read_file"],
    ))
    mpt._tracker = mt
    lt.record("e2e-1", "memory_updated")

    # 7. Proposals checked
    lt.record("e2e-1", "proposals_checked")
    lt.finish("e2e-1")

    # Verify complete lifecycle
    rec = lt.get("e2e-1")
    assert rec.is_complete
    assert rec.coverage == 1.0
    assert len(rec.stages) == 7

    # Verify tool performance recorded
    assert tracker.get_stats("read_file").successes == 1

    # Verify evaluation recorded
    assert len(ee._evaluations) >= 1
    assert ee._evaluations[-1]["goal_completion"] == 1.0

    # Verify mission performance recorded
    assert mt._type_stats["coding_task"].successes == 1

    # Verify dashboard
    d = lt.get_dashboard_data()
    assert d["complete"] >= 1


def test_e2e_failure_recovery():
    """Simulate a mission with tool failure and recovery."""
    from core.lifecycle_tracker import LifecycleTracker
    import core.lifecycle_tracker as lt_mod

    lt = LifecycleTracker()
    lt_mod._tracker = lt

    lt.start("e2e-fail")
    lt.record("e2e-fail", "plan_generated")
    lt.record("e2e-fail", "agents_selected")

    # Tool fails
    lt.record_error("e2e-fail", "tools_executed", "TimeoutError on shell_command")
    lt.record("e2e-fail", "tools_executed")  # eventually succeeds via fallback

    lt.record("e2e-fail", "results_evaluated")
    lt.record("e2e-fail", "memory_updated")
    lt.record("e2e-fail", "proposals_checked")
    lt.finish("e2e-fail")

    rec = lt.get("e2e-fail")
    assert rec.is_complete
    assert len(rec.errors) == 1


# ═══════════════════════════════════════════════════════════════
# WIRING VERIFICATION
# ═══════════════════════════════════════════════════════════════

def test_mission_system_has_lifecycle():
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "lifecycle_tracker" in src
    assert "mission_received" in src
    assert "plan_generated" in src
    assert "results_evaluated" in src
    assert "memory_updated" in src
    assert "proposals_checked" in src
    ast.parse(src)


def test_tool_runner_has_lifecycle():
    with open("core/tool_runner.py", encoding="utf-8") as f:
        src = f.read()
    assert "tools_executed" in src
    assert "lifecycle_tracker" in src
    ast.parse(src)


def test_execution_engine_has_volatility():
    with open("core/execution_engine.py", encoding="utf-8") as f:
        src = f.read()
    assert "should_retry" in src
    assert "volatility" in src
    ast.parse(src)


def test_performance_api_has_lifecycle_endpoints():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "/lifecycle" in src
    assert "/confidence" in src
    ast.parse(src)


@pytest.mark.stale
@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_cockpit_has_confidence_panel():
    with open("static/cockpit.html", encoding="utf-8") as f:
        html = f.read()
    assert "confidence-panel" in html
    assert "safety-panel" in html
    assert "lifecycle-panel" in html
    assert "/api/v3/performance/confidence" in html
    assert "/api/v3/performance/safety" in html
    assert "/api/v3/performance/lifecycle" in html


def test_all_new_files_syntax():
    files = [
        "core/lifecycle_tracker.py",
        "core/execution_engine.py",
        "core/improvement_detector.py",
        "api/routes/performance.py",
        "core/mission_system.py",
        "core/tool_runner.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
