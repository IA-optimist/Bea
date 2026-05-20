"""
Real-World Readiness Tests
=============================
Verifies Jarvis can handle actual usage scenarios.
"""
import ast
import os
import sys
import tempfile
import types
import pytest
pytestmark = pytest.mark.integration


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
# SCENARIO 1: MULTI-STEP CODING MISSION
# ═══════════════════════════════════════════════════════════════

def test_scenario_coding_mission():
    """
    Simulate: user asks to fix a bug in a Python module.
    Expected flow: plan → read_file → analyze → write_file → test → report
    """
    from core.lifecycle_tracker import LifecycleTracker
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.execution_engine as ee

    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path="/tmp/rw_coding_t.jsonl")
    ee._evaluations = []

    mid = "coding-fix-001"
    lt.start(mid)
    lt.record(mid, "plan_generated")
    lt.record(mid, "agents_selected")

    # Step 1: read_file (success)
    tpt.record(ToolExecution(tool="read_file", success=True, latency_ms=45))
    # Step 2: shell_command for analysis (success)
    tpt.record(ToolExecution(tool="shell_command", success=True, latency_ms=320))
    # Step 3: write_file (success)
    tpt.record(ToolExecution(tool="write_file", success=True, latency_ms=85))
    # Step 4: shell_command for tests (success)
    tpt.record(ToolExecution(tool="shell_command", success=True, latency_ms=1500))

    lt.record(mid, "tools_executed")

    ev = ee.evaluate_mission(
        mid, True,
        "Fixed the NoneType error in config parser. Changed line 45 to add null check. All 12 tests passing.",
        "Fix the NoneType error in config.py",
        ["forge-builder", "lens-reviewer"],
        ["read_file", "shell_command", "write_file"],
        4.2, 4,
    )
    ee.store_evaluation(ev)
    lt.record(mid, "results_evaluated")
    lt.record(mid, "memory_updated")
    lt.record(mid, "proposals_checked")
    lt.finish(mid)

    rec = lt.get(mid)
    assert rec.is_complete
    assert ev.goal_completion >= 0.7
    assert ev.tool_efficiency > 0


# ═══════════════════════════════════════════════════════════════
# SCENARIO 2: TOOL FAILURE RECOVERY
# ═══════════════════════════════════════════════════════════════

def test_scenario_tool_failure_recovery():
    """
    Simulate: shell_command fails repeatedly, system should:
    1. Detect failure via should_retry
    2. Suggest fallback tool
    3. Record recovery for future missions
    """
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.execution_engine import should_retry, get_fallback_tool, get_best_recovery
    import core.tool_performance_tracker as tpt_mod

    tpt = ToolPerformanceTracker(persist_path="/tmp/rw_failure_t.jsonl")
    # Record consistent failures (9 fail, 1 success = 10% success rate)
    for _ in range(9):
        tpt.record(ToolExecution(tool="shell_command", success=False, latency_ms=100, error_type="TimeoutError"))
    tpt.record(ToolExecution(tool="shell_command", success=True, latency_ms=50))

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        # System should refuse to retry
        assert not should_retry("shell_command", 0)

        # Fallback should be available
        fallback = get_fallback_tool("shell_command")
        assert fallback is not None

        # Recovery hint should work
        hint = get_best_recovery("shell_command", "TimeoutError")
        # hint may be None if no recovery memory, but function shouldn't crash
        assert hint is None or isinstance(hint, dict)
    finally:
        tpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# SCENARIO 3: MULTIMODAL INPUT
# ═══════════════════════════════════════════════════════════════

def test_scenario_multimodal_image():
    """User asks to analyze an image — system routes to correct agents."""
    from core.dynamic_agent_router import detect_multimodal_type, get_multimodal_agents

    goal = "Analyze this screenshot and tell me what's wrong with the UI layout"
    modal = detect_multimodal_type(goal)
    assert modal == "image"

    agents = get_multimodal_agents(modal)
    assert len(agents) >= 1
    # forge-builder should be included (can generate/analyze)
    assert "forge-builder" in agents


def test_scenario_multimodal_mixed():
    """User asks about both image and text — detect primary modal."""
    from core.dynamic_agent_router import detect_multimodal_type

    # Image takes priority (checked first)
    assert detect_multimodal_type("Transcribe the audio and generate an image summary") == "image"
    # Pure audio
    assert detect_multimodal_type("Transcribe this podcast recording") == "audio"
    # Pure document
    assert detect_multimodal_type("Summarize this pdf report") == "document"


# ═══════════════════════════════════════════════════════════════
# SCENARIO 4: LONG HORIZON PLANNING
# ═══════════════════════════════════════════════════════════════

def test_scenario_long_horizon():
    """
    Simulate a mission that spans many steps over "time".
    Verify lifecycle tracking stays consistent and bounded.
    """
    from core.lifecycle_tracker import LifecycleTracker
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.execution_engine as ee

    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path="/tmp/rw_long_t.jsonl")
    ee._evaluations = []

    # 20-step mission
    mid = "long-horizon-001"
    lt.start(mid)
    lt.record(mid, "plan_generated")
    lt.record(mid, "agents_selected")

    for step in range(20):
        tool = ["read_file", "shell_command", "write_file", "http_get", "vector_search"][step % 5]
        success = step % 7 != 0
        tpt.record(ToolExecution(tool=tool, success=success, latency_ms=float(step * 100 + 50)))

    lt.record(mid, "tools_executed")

    ev = ee.evaluate_mission(
        mid, True,
        "Long horizon mission complete. 20 steps executed, 17 successful, 3 failed and recovered.",
        "Refactor the entire authentication module",
        ["forge-builder", "lens-reviewer", "map-planner"],
        ["read_file", "shell_command", "write_file", "http_get", "vector_search"],
        45.0, 20,
    )
    ee.store_evaluation(ev)
    lt.record(mid, "results_evaluated")
    lt.record(mid, "memory_updated")
    lt.record(mid, "proposals_checked")
    lt.finish(mid)

    rec = lt.get(mid)
    assert rec.is_complete


# ═══════════════════════════════════════════════════════════════
# SCENARIO 5: CONCURRENT MISSIONS
# ═══════════════════════════════════════════════════════════════

def test_scenario_concurrent_missions():
    """3 missions running simultaneously — no state corruption."""
    from core.lifecycle_tracker import LifecycleTracker
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.execution_engine as ee

    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path="/tmp/rw_conc_t.jsonl")
    mpt = MissionPerformanceTracker(persist_path="/tmp/rw_conc_m.json")
    ee._evaluations = []

    missions = {
        "conc-A": ("coding_task", "forge-builder", True),
        "conc-B": ("research_task", "scout-research", True),
        "conc-C": ("debug_task", "forge-builder", False),
    }

    # Start all 3
    for mid in missions:
        lt.start(mid)

    # Interleave stages
    for mid in missions:
        lt.record(mid, "plan_generated")
    for mid in missions:
        lt.record(mid, "agents_selected")

    # Execute tools interleaved
    for mid, (mtype, agent, success) in missions.items():
        tpt.record(ToolExecution(tool="read_file", success=True, latency_ms=50))
        lt.record(mid, "tools_executed")

    for mid, (mtype, agent, success) in missions.items():
        ev = ee.evaluate_mission(mid, success, "output" * 5, "goal", [agent], ["read_file"], 5.0, 2)
        ee.store_evaluation(ev)
        lt.record(mid, "results_evaluated")
        mpt.record(MissionOutcome(mission_id=mid, mission_type=mtype, success=success, agents_used=[agent]))
        lt.record(mid, "memory_updated")
        lt.record(mid, "proposals_checked")
        lt.finish(mid)

    d = lt.get_dashboard_data()
    assert d["complete"] == 3
    assert d["complete_rate"] == 1.0
    # Verify each mission has independent state
    for mid in missions:
        rec = lt.get(mid)
        assert rec.is_complete


# ═══════════════════════════════════════════════════════════════
# SCENARIO 6: TOOL DISCOVERY
# ═══════════════════════════════════════════════════════════════

def test_scenario_tool_discovery():
    """Verify tool registry validation catches issues."""
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    result = reg.validate_all()
    assert result["total"] > 0
    # Report issues clearly
    for issue in result["issues"]:
        assert isinstance(issue, str)
        assert len(issue) > 5


# ═══════════════════════════════════════════════════════════════
# PRIORITY 6: MEMORY PERSISTENCE ACROSS SESSIONS
# ═══════════════════════════════════════════════════════════════

def test_persistence_tool_performance():
    """Save and reload tool performance data."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
        tmppath = f.name

    try:
        from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
        # Write session
        t1 = ToolPerformanceTracker(persist_path=tmppath)
        for i in range(10):
            t1.record(ToolExecution(tool="persist_tool", success=i % 3 != 0, latency_ms=float(i * 20)))
        t1.save()

        # Read session (simulating restart)
        t2 = ToolPerformanceTracker(persist_path=tmppath)
        t2.load()
        stats = t2.get_stats("persist_tool")
        assert stats is not None
        assert stats.total_calls == 10
    finally:
        os.unlink(tmppath)


def test_persistence_mission_performance():
    """Save and reload mission performance data."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tmppath = f.name

    try:
        from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
        t1 = MissionPerformanceTracker(persist_path=tmppath)
        for i in range(5):
            t1.record(MissionOutcome(
                mission_id=f"persist-{i}", mission_type="coding_task",
                success=True, agents_used=["forge-builder"],
            ))
        t1.save()

        t2 = MissionPerformanceTracker(persist_path=tmppath)
        t2.load()
        assert "coding_task" in t2._type_stats
        assert t2._type_stats["coding_task"].total >= 5
    finally:
        os.unlink(tmppath)


def test_persistence_mission_memory():
    """Save and reload mission memory strategies."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tmppath = f.name

    try:
        from core.mission_memory import MissionMemory
        m1 = MissionMemory(persist_path=tmppath)
        for i in range(5):
            m1.record_outcome("coding_task", ["forge-builder"], ["read_file"], 3, True)
        m1.save()

        m2 = MissionMemory(persist_path=tmppath)
        m2.load()
        assert len(m2._strategies) >= 1
        best = m2.get_best_strategy("coding_task")
        assert best is not None
    finally:
        os.unlink(tmppath)


# ═══════════════════════════════════════════════════════════════
# PRIORITY 7: IMPROVEMENT PROPOSALS DON'T LOOP
# ═══════════════════════════════════════════════════════════════

def test_improvement_detection_rate_limited():
    """Detect improvements is rate-limited (no self-amplifying loops)."""
    import core.improvement_detector as det
    det._last_detection_time = 0  # reset
    os.environ.pop("JARVIS_DISABLE_PROPOSALS", None)
    os.environ.pop("JARVIS_DISABLE_ALL_INTELLIGENCE", None)

    # First call: should run
    r1 = det.detect_improvements(dry_run=False)
    assert isinstance(r1, list)

    # Immediate second call: should be rate-limited (empty)
    r2 = det.detect_improvements(dry_run=False)
    assert r2 == []

    # dry_run calls bypass rate limiter
    r3 = det.detect_improvements(dry_run=True)
    assert isinstance(r3, list)


def test_improvement_proposals_bounded():
    """Proposal store doesn't grow unbounded."""
    from core.improvement_proposals import ProposalStore, ImprovementProposal
    store = ProposalStore(persist_path="/tmp/rw_props.json")
    for i in range(600):
        store.add(ImprovementProposal(
            proposal_type="tool_fix",
            title=f"Fix tool {i}",
            description=f"Tool {i} is failing",
        ))
    assert len(store._proposals) <= 500


# ═══════════════════════════════════════════════════════════════
# PRIORITY 8: PLANNER DETERMINISM
# ═══════════════════════════════════════════════════════════════

def test_planner_deterministic():
    """Same input produces same plan structure."""
    from core.mission_system import MissionSystem, MissionIntent
    ms1 = MissionSystem.__new__(MissionSystem)
    ms1._missions = {}
    ms1._db_conn = None
    ms1._mission_goals = {}

    plan1 = ms1._build_plan("Fix the login bug", MissionIntent.ANALYZE)
    plan2 = ms1._build_plan("Fix the login bug", MissionIntent.ANALYZE)
    assert len(plan1.steps) == len(plan2.steps)
    for s1, s2 in zip(plan1.steps, plan2.steps):
        assert s1.agent == s2.agent
        assert s1.priority == s2.priority


# ═══════════════════════════════════════════════════════════════
# PRIORITY 10: BOUNDED UNDER LONG HORIZON
# ═══════════════════════════════════════════════════════════════

def test_long_horizon_bounded():
    """1000-step mission doesn't blow memory."""
    from core.lifecycle_tracker import LifecycleTracker
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.execution_engine as ee

    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path="/tmp/rw_longbound_t.jsonl")
    ee._evaluations = []
    ee._telemetry_buffer = []

    for i in range(1000):
        mid = f"long-{i}"
        lt.start(mid)
        for stage in ["plan_generated", "agents_selected", "tools_executed",
                       "results_evaluated", "memory_updated", "proposals_checked"]:
            lt.record(mid, stage)
        lt.finish(mid)
        tpt.record(ToolExecution(tool=f"t{i%100}", success=i%5!=0, latency_ms=float(i%300)))

    assert len(lt._records) <= 500
    assert len(tpt.get_all_stats()) <= 200
    assert len(ee._evaluations) <= 500
    assert len(ee._telemetry_buffer) <= 200


# ═══════════════════════════════════════════════════════════════
# CONSISTENCY: SAME BEHAVIOR ACROSS RUNS
# ═══════════════════════════════════════════════════════════════

def test_consistent_safety_state():
    """Safety state is consistent across queries."""
    from core.safety_controls import get_safety_state
    s1 = get_safety_state()
    s2 = get_safety_state()
    assert s1.intelligence_enabled == s2.intelligence_enabled
    assert s1.proposals_enabled == s2.proposals_enabled
    assert s1.execution_engine_enabled == s2.execution_engine_enabled


def test_consistent_execution_limits():
    """Execution limits don't change between calls."""
    from core.execution_engine import get_execution_limits
    l1 = get_execution_limits()
    l2 = get_execution_limits()
    assert l1 == l2


def test_all_modified_files_syntax():
    """Final syntax check on all files modified in this batch."""
    files = [
        "core/improvement_detector.py",
        "core/tool_performance_tracker.py",
        "core/mission_performance_tracker.py",
        "core/mission_memory.py",
        "core/improvement_proposals.py",
        "core/mission_system.py",
        "core/execution_engine.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
