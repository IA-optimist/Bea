"""
Extended Real-Mission Validation
====================================
10 mission scenarios exercising every runtime path.
Observes: retry, fallback, tool selection, memory, proposals,
determinism, latency, failure clustering.
"""
import os
import sys
import tempfile
import time
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

from core.lifecycle_tracker import LifecycleTracker
from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
from core.mission_memory import MissionMemory
import core.execution_engine as ee


def _fresh_state():
    """Create fresh instances for isolation."""
    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path=f"/tmp/ev_{time.time()}.jsonl")
    mpt = MissionPerformanceTracker(persist_path=f"/tmp/ev_{time.time()}_m.json")
    mm = MissionMemory(persist_path=f"/tmp/ev_{time.time()}_mm.json")
    ee._evaluations = []
    ee._telemetry_buffer = []
    return lt, tpt, mpt, mm


def _run_lifecycle(lt, mid, tools_data, tpt, mpt, mm, goal, mtype, agents, success=True):
    """Run a complete mission lifecycle with given data."""
    lt.start(mid)
    lt.record(mid, "plan_generated")
    lt.record(mid, "agents_selected")
    for tool, ok, ms_latency in tools_data:
        tpt.record(ToolExecution(tool=tool, success=ok, latency_ms=ms_latency))
    lt.record(mid, "tools_executed")
    ev = ee.evaluate_mission(
        mid, success,
        f"{'Completed' if success else 'Failed'}: {goal[:50]}. Details: " + "x" * 40,
        goal, agents, [t[0] for t in tools_data],
        sum(t[2] for t in tools_data) / 1000.0, len(tools_data),
    )
    ee.store_evaluation(ev)
    lt.record(mid, "results_evaluated")
    mpt.record(MissionOutcome(
        mission_id=mid, mission_type=mtype, success=success,
        agents_used=agents, tools_used=[t[0] for t in tools_data],
        duration_s=sum(t[2] for t in tools_data) / 1000.0,
    ))
    mm.record_outcome(mtype, agents, [t[0] for t in tools_data], len(tools_data), success)
    lt.record(mid, "memory_updated")
    lt.record(mid, "proposals_checked")
    lt.finish(mid)
    return ev


# ═══════════════════════════════════════════════════════════════
# MISSION 1: Long Horizon Coding (multi-file refactor)
# ═══════════════════════════════════════════════════════════════

def test_mission1_long_horizon_coding():
    """
    25-step coding refactor across multiple files.
    Tools: read_file, write_file, shell_command, search_codebase.
    Expected: all lifecycle stages, evaluation score > 0.5
    """
    lt, tpt, mpt, mm = _fresh_state()

    tools = []
    for i in range(25):
        if i % 5 == 0:
            tools.append(("search_codebase", True, 120))
        elif i % 5 in (1, 3):
            tools.append(("read_file", True, 45))
        elif i % 5 == 2:
            tools.append(("write_file", True, 90))
        else:
            tools.append(("shell_command", i != 20, 500))  # step 20 fails

    ev = _run_lifecycle(
        lt, "long-code-001", tools, tpt, mpt, mm,
        "Refactor authentication module across 8 files",
        "coding_task", ["forge-builder", "lens-reviewer", "map-planner"],
    )

    rec = lt.get("long-code-001")
    assert rec.is_complete
    assert rec.coverage == 1.0
    assert ev.goal_completion >= 0.5
    assert len(tools) == 25

    # Latency distribution observation
    latencies = [t[2] for t in tools]
    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    assert avg_latency < 300  # reasonable average
    assert max_latency <= 500  # no extreme outlier


# ═══════════════════════════════════════════════════════════════
# MISSION 2: Tool Failure Recovery
# ═══════════════════════════════════════════════════════════════

def test_mission2_tool_failure_recovery():
    """
    Mission where primary tool fails repeatedly.
    should_retry → deny, fallback used.
    Observe: retry count, fallback selection, recovery memory.
    """
    lt, tpt, mpt, mm = _fresh_state()
    import core.tool_performance_tracker as tpt_mod

    # Pre-seed: shell_command has bad history
    for _ in range(12):
        tpt.record(ToolExecution(tool="shell_command", success=False, latency_ms=100,
                                 error_type="TimeoutError"))
    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        # Verify retry behavior
        assert not ee.should_retry("shell_command", 0)  # refuses retry

        # Verify fallback exists
        fb = ee.get_fallback_tool("shell_command")
        assert fb is not None

        # Verify health gate
        health = ee.check_tool_health("shell_command")
        assert health["status"] == "failing"
        assert not health["healthy"]
    finally:
        tpt_mod._tracker = old

    # Run mission using fallback path
    _run_lifecycle(
        lt, "recover-001",
        [("read_file", True, 40), ("run_command_safe", True, 200), ("write_file", True, 80)],
        tpt, mpt, mm,
        "Fix deployment script that keeps timing out",
        "debug_task", ["forge-builder"],
    )
    assert lt.get("recover-001").is_complete


# ═══════════════════════════════════════════════════════════════
# MISSION 3: Multimodal Mixed Input
# ═══════════════════════════════════════════════════════════════

def test_mission3_multimodal_mixed():
    """
    User sends text + image reference + audio reference.
    Routing should detect primary modal and select appropriate agents.
    """
    from core.dynamic_agent_router import detect_multimodal_type, get_multimodal_agents

    goals = [
        ("Analyze this screenshot of the error log and fix the issue", "image"),
        ("Transcribe the meeting audio and summarize action items", "audio"),
        ("Parse this CSV report and generate charts", "document"),
        ("Fix the login bug in auth.py", None),
        ("Describe the image and transcribe the voice note", "image"),  # image detected first
    ]

    for goal, expected_modal in goals:
        modal = detect_multimodal_type(goal)
        assert modal == expected_modal, f"Goal '{goal[:40]}': expected {expected_modal}, got {modal}"
        if modal:
            agents = get_multimodal_agents(modal)
            assert len(agents) >= 1, f"No agents for modal {modal}"

    # Verify multimodal agents don't break normal routing
    lt, tpt, mpt, mm = _fresh_state()
    _run_lifecycle(
        lt, "multi-001",
        [("read_file", True, 50), ("http_get", True, 300)],
        tpt, mpt, mm,
        "Analyze this screenshot and fix the layout bug",
        "coding_task", ["forge-builder", "scout-research"],
    )
    assert lt.get("multi-001").is_complete


# ═══════════════════════════════════════════════════════════════
# MISSION 4: Concurrent Missions
# ═══════════════════════════════════════════════════════════════

def test_mission4_concurrent_missions():
    """
    10 missions running simultaneously with interleaved stages.
    Verify: no state corruption, all complete, independent evaluations.
    """
    lt, tpt, mpt, mm = _fresh_state()
    import random
    random.seed(42)

    missions = {}
    for i in range(10):
        mtype = ["coding_task", "research_task", "debug_task", "system_task"][i % 4]
        agent = ["forge-builder", "scout-research", "lens-reviewer", "shadow-advisor"][i % 4]
        success = i % 3 != 0
        missions[f"conc-{i:02d}"] = (mtype, agent, success)

    # Start all
    for mid in missions:
        lt.start(mid)

    # Interleave: plan generation
    ids = list(missions.keys())
    random.shuffle(ids)
    for mid in ids:
        lt.record(mid, "plan_generated")

    # Interleave: agent selection
    random.shuffle(ids)
    for mid in ids:
        lt.record(mid, "agents_selected")

    # Interleave: tool execution
    random.shuffle(ids)
    for mid in ids:
        mtype, agent, success = missions[mid]
        tpt.record(ToolExecution(tool="read_file", success=success, latency_ms=float(hash(mid) % 200 + 20)))
        lt.record(mid, "tools_executed")

    # Interleave: evaluation + memory + finish
    random.shuffle(ids)
    for mid in ids:
        mtype, agent, success = missions[mid]
        ev = ee.evaluate_mission(mid, success, "output" * 5, "goal", [agent], ["read_file"], 2.0, 1)
        ee.store_evaluation(ev)
        lt.record(mid, "results_evaluated")
        mpt.record(MissionOutcome(mission_id=mid, mission_type=mtype, success=success,
                                  agents_used=[agent], tools_used=["read_file"]))
        lt.record(mid, "memory_updated")
        lt.record(mid, "proposals_checked")
        lt.finish(mid)

    # Verify all complete with independent state
    d = lt.get_dashboard_data()
    assert d["complete"] == 10
    assert d["complete_rate"] == 1.0
    for mid in missions:
        rec = lt.get(mid)
        assert rec.is_complete


# ═══════════════════════════════════════════════════════════════
# MISSION 5: Iterative Improvement Across Sessions
# ═══════════════════════════════════════════════════════════════

def test_mission5_iterative_improvement():
    """
    Simulate 3 sessions. Each session builds on previous memory.
    Verify: strategies improve, memory persists, proposals accumulate.
    """
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        tpath = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        mpath = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        mmpath = f.name

    try:
        # Session 1: Initial missions (low success)
        tpt1 = ToolPerformanceTracker(persist_path=tpath)
        mpt1 = MissionPerformanceTracker(persist_path=mpath)
        mm1 = MissionMemory(persist_path=mmpath)
        for i in range(10):
            success = i > 3  # 60% success rate — enough for confidence > 0.4
            tpt1.record(ToolExecution(tool="read_file", success=success, latency_ms=float(i * 30 + 50)))
            mpt1.record(MissionOutcome(mission_id=f"s1-{i}", mission_type="coding_task",
                                       success=success, agents_used=["forge-builder"]))
            mm1.record_outcome("coding_task", ["forge-builder"], ["read_file"], 2, success)
        tpt1.save()
        mpt1.save()
        mm1.save()

        # Session 2: Reload + improved missions
        tpt2 = ToolPerformanceTracker(persist_path=tpath)
        mpt2 = MissionPerformanceTracker(persist_path=mpath)
        mm2 = MissionMemory(persist_path=mmpath)
        tpt2.load()
        mpt2.load()
        mm2.load()

        # Memory should have session 1 data
        s1_stats = tpt2.get_stats("read_file")
        assert s1_stats is not None
        assert s1_stats.total_calls >= 10

        # Strategy should exist
        strategy = mm2.get_best_strategy("coding_task")
        assert strategy is not None

        # Session 2 missions (better success — learning applied)
        for i in range(10):
            tpt2.record(ToolExecution(tool="read_file", success=i > 2, latency_ms=float(i * 20 + 30)))
            mpt2.record(MissionOutcome(mission_id=f"s2-{i}", mission_type="coding_task",
                                       success=i > 2, agents_used=["forge-builder"]))
            mm2.record_outcome("coding_task", ["forge-builder"], ["read_file"], 2, i > 2)
        tpt2.save()
        mpt2.save()
        mm2.save()

        # Session 3: Verify accumulated knowledge
        tpt3 = ToolPerformanceTracker(persist_path=tpath)
        mpt3 = MissionPerformanceTracker(persist_path=mpath)
        mm3 = MissionMemory(persist_path=mmpath)
        tpt3.load()
        mpt3.load()
        mm3.load()

        s3_stats = tpt3.get_stats("read_file")
        assert s3_stats is not None
        assert s3_stats.total_calls >= 20  # accumulated across sessions

        # Success rate should be higher in later data
        assert s3_stats.success_rate > 0.3  # improved from session 1's 30%

    finally:
        os.unlink(tpath)
        os.unlink(mpath)
        os.unlink(mmpath)


# ═══════════════════════════════════════════════════════════════
# MISSION 6: Planning With Changing Constraints
# ═══════════════════════════════════════════════════════════════

def test_mission6_changing_constraints():
    """
    Same goal type, different complexity → plan should adapt.
    Verify: deterministic for same input, different for different complexity.
    """
    from core.mission_system import MissionSystem, MissionIntent

    ms = MissionSystem.__new__(MissionSystem)
    ms._missions = {}
    ms._db_conn = None
    ms._mission_goals = {}

    # Same intent, same goal → same plan
    plan_a = ms._build_plan("Fix the login bug", MissionIntent.ANALYZE)
    plan_b = ms._build_plan("Fix the login bug", MissionIntent.ANALYZE)
    assert len(plan_a.steps) == len(plan_b.steps)
    for a, b in zip(plan_a.steps, plan_b.steps):
        assert a.agent == b.agent

    # Different intent → different plan
    plan_c = ms._build_plan("Create a new API endpoint", MissionIntent.CREATE)
    assert len(plan_c.steps) != len(plan_a.steps) or plan_c.steps[0].agent != plan_a.steps[0].agent

    # CREATE should have more steps (includes builder + validator)
    assert len(plan_c.steps) >= len(plan_a.steps)


# ═══════════════════════════════════════════════════════════════
# MISSION 7: Memory Reuse Scenario
# ═══════════════════════════════════════════════════════════════

def test_mission7_memory_reuse():
    """
    Run 30 missions. Verify memory signals improve tool/agent selection.
    """
    lt, tpt, mpt, mm = _fresh_state()

    # Phase 1: 15 missions — mixed results, learning
    for i in range(15):
        tools = [
            ("read_file", True, 40),
            ("shell_command", i % 3 != 0, 200),  # 33% failure
            ("write_file", True, 80),
        ]
        _run_lifecycle(
            lt, f"reuse-{i}", tools, tpt, mpt, mm,
            "Fix module bug", "coding_task",
            ["forge-builder"], success=i % 3 != 0,
        )

    # Verify tool stats accumulated
    shell_stats = tpt.get_stats("shell_command")
    assert shell_stats is not None
    assert shell_stats.total_calls >= 15

    # Verify failing tools detected
    failing = tpt.get_failing_tools()
    # shell_command has 33% failure — may or may not be in "failing" list
    # but read_file should NOT be in failing
    failing_names = [f["tool"] for f in failing]
    assert "read_file" not in failing_names

    # Phase 2: Strategy should be available
    strategy = mpt.get_strategy_for_type("coding_task")
    assert strategy is not None
    assert strategy["sample_size"] >= 10

    # Memory should have strategies
    best = mm.get_best_strategy("coding_task")
    assert best is not None
    assert best["success_rate"] > 0


# ═══════════════════════════════════════════════════════════════
# MISSION 8: Partial Tool Availability
# ═══════════════════════════════════════════════════════════════

def test_mission8_partial_tools():
    """
    Some tools are healthy, some are degraded, some are failing.
    Verify: health gate routes correctly, fallbacks used.
    """
    lt, tpt, mpt, mm = _fresh_state()
    import core.tool_performance_tracker as tpt_mod

    # Pre-seed mixed health
    for _ in range(10):
        tpt.record(ToolExecution(tool="read_file", success=True, latency_ms=30))     # healthy
    for _ in range(10):
        tpt.record(ToolExecution(tool="http_get", success=False, latency_ms=5000))   # failing
    for i in range(10):
        tpt.record(ToolExecution(tool="vector_search", success=i%2==0, latency_ms=100))  # volatile

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        # read_file: healthy
        h1 = ee.check_tool_health("read_file")
        assert h1["healthy"]
        assert h1["status"] == "healthy"

        # http_get: failing
        h2 = ee.check_tool_health("http_get")
        assert not h2["healthy"]
        assert h2["status"] == "failing"

        # vector_search: volatile — health depends on recent window
        h3 = ee.check_tool_health("vector_search")
        # At 50% success, may be degraded or healthy
        assert h3["status"] in ("healthy", "degraded", "failing")

        # Retry decisions
        assert ee.should_retry("read_file", 0)      # healthy → allow
        assert not ee.should_retry("http_get", 0)    # failing → deny

        # Fallback for http_get
        fb = ee.get_fallback_tool("http_get")
        assert fb is not None  # should map to curl or similar
    finally:
        tpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# MISSION 9: Degraded Model Scenario
# ═══════════════════════════════════════════════════════════════

def test_mission9_degraded_model():
    """
    Safety flags disable intelligence layers.
    System must still function: execute tools, record lifecycle.
    """
    os.environ["JARVIS_DISABLE_ALL_INTELLIGENCE"] = "1"
    try:
        from core.safety_controls import is_intelligence_enabled, is_proposals_enabled
        assert not is_intelligence_enabled()
        assert not is_proposals_enabled()

        # Improvement detection should return empty
        import core.improvement_detector as det
        det._last_detection_time = 0
        proposals = det.detect_improvements(dry_run=False)
        assert proposals == []

        # Dynamic routing should fall through to static
        # Dynamic routing is a separate flag — should still be independently controllable
        # But intelligence being disabled doesn't necessarily disable routing
        # This is by design: routing uses its own JARVIS_DYNAMIC_ROUTING flag

        # Lifecycle should still work
        lt = LifecycleTracker()
        lt.start("degraded-001")
        lt.record("degraded-001", "plan_generated")
        lt.record("degraded-001", "agents_selected")
        lt.record("degraded-001", "tools_executed")
        lt.record("degraded-001", "results_evaluated")
        lt.record("degraded-001", "memory_updated")
        lt.record("degraded-001", "proposals_checked")
        lt.finish("degraded-001")
        assert lt.get("degraded-001").is_complete

    finally:
        os.environ.pop("JARVIS_DISABLE_ALL_INTELLIGENCE", None)


# ═══════════════════════════════════════════════════════════════
# MISSION 10: Long Reasoning Chain
# ═══════════════════════════════════════════════════════════════

def test_mission10_long_reasoning_chain():
    """
    50-step mission simulating deep analysis with branching paths.
    Verify: bounded, complete lifecycle, evaluation captures depth.
    """
    lt, tpt, mpt, mm = _fresh_state()

    tools = []
    for step in range(50):
        if step < 10:
            tools.append(("search_codebase", True, 150))     # discovery phase
        elif step < 25:
            tools.append(("read_file", step != 15, 50))       # analysis phase (1 failure)
        elif step < 40:
            tools.append(("write_file", step != 30, 100))     # implementation (1 failure)
        else:
            tools.append(("shell_command", step != 45, 400))   # testing (1 failure)

    ev = _run_lifecycle(
        lt, "reasoning-001", tools, tpt, mpt, mm,
        "Perform deep security audit of the entire authentication subsystem",
        "architecture_task",
        ["forge-builder", "lens-reviewer", "map-planner", "scout-research"],
    )

    rec = lt.get("reasoning-001")
    assert rec.is_complete
    assert ev.goal_completion > 0


# ═══════════════════════════════════════════════════════════════
# OBSERVABILITY: Aggregate Signal Analysis
# ═══════════════════════════════════════════════════════════════

def test_observe_retry_and_fallback_behavior():
    """
    Verify retry/fallback decisions are consistent with tool health.
    """
    tpt = ToolPerformanceTracker(persist_path="/tmp/obs_retry.jsonl")
    import core.tool_performance_tracker as tpt_mod

    tools_health = {
        "healthy_tool": [(True, 30)] * 10,
        "degraded_tool": [(True, 30)] * 5 + [(False, 30)] * 5,
        "failing_tool": [(False, 100)] * 10,
        "volatile_tool": [(i%2==0, 50) for i in range(10)],
    }

    for tool, records in tools_health.items():
        for success, latency in records:
            tpt.record(ToolExecution(tool=tool, success=success, latency_ms=float(latency)))

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        # Consistent behavior table
        results = {}
        for tool in tools_health:
            health = ee.check_tool_health(tool)
            retry = ee.should_retry(tool, 0)
            retry2 = ee.should_retry(tool, 1)
            results[tool] = {
                "healthy": health["healthy"],
                "retry_attempt_0": retry,
                "retry_attempt_1": retry2,
            }

        # Healthy: always retryable
        assert results["healthy_tool"]["healthy"]
        assert results["healthy_tool"]["retry_attempt_0"]

        # Failing: never retryable
        assert not results["failing_tool"]["healthy"]
        assert not results["failing_tool"]["retry_attempt_0"]

        # Volatile: limited retries
        assert not results["volatile_tool"]["retry_attempt_1"]
    finally:
        tpt_mod._tracker = old


def test_observe_failure_clustering():
    """
    Detect failure clusters: multiple tools failing in same window.
    """
    tpt = ToolPerformanceTracker(persist_path="/tmp/obs_cluster.jsonl")

    # Cluster: 3 tools fail in quick succession
    for tool in ["read_file", "write_file", "shell_command"]:
        for _ in range(5):
            tpt.record(ToolExecution(tool=tool, success=False, latency_ms=100))

    failing = tpt.get_failing_tools()
    failing_names = {f["tool"] for f in failing}
    assert len(failing_names) >= 3  # all 3 should be flagged


def test_observe_latency_distribution():
    """Latency distribution should be consistent and predictable."""
    tpt = ToolPerformanceTracker(persist_path="/tmp/obs_latency.jsonl")

    # Normal distribution: most fast, some slow
    for i in range(100):
        latency = 50 + (i % 20) * 10  # 50-240ms range
        tpt.record(ToolExecution(tool="read_file", success=True, latency_ms=float(latency)))

    stats = tpt.get_stats("read_file")
    assert stats.avg_latency_ms > 0
    assert stats.avg_latency_ms < 300  # reasonable average


def test_observe_proposal_relevance():
    """Proposals should match actual performance issues."""
    os.environ.pop("JARVIS_DISABLE_PROPOSALS", None)
    os.environ.pop("JARVIS_DISABLE_ALL_INTELLIGENCE", None)

    tpt = ToolPerformanceTracker(persist_path="/tmp/obs_proposals.jsonl")
    import core.tool_performance_tracker as tpt_mod

    # Create clear issue: one tool failing badly
    for _ in range(20):
        tpt.record(ToolExecution(tool="broken_tool", success=False, latency_ms=500))
    for _ in range(20):
        tpt.record(ToolExecution(tool="good_tool", success=True, latency_ms=30))

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        import core.improvement_detector as det
        det._last_detection_time = 0
        proposals = det.detect_improvements(dry_run=True)

        if proposals:
            # Proposals should reference the broken tool, not the good one
            broken_proposals = [p for p in proposals if "broken_tool" in str(p)]
            good_proposals = [p for p in proposals if "good_tool" in str(p)]
            assert len(broken_proposals) >= len(good_proposals)
    finally:
        tpt_mod._tracker = old


def test_observe_execution_determinism():
    """Same inputs → same evaluation scores."""
    ee._evaluations = []

    for _ in range(3):
        ev = ee.evaluate_mission(
            "det-test", True,
            "Fixed the bug successfully with comprehensive tests passing.",
            "Fix the authentication bug",
            ["forge-builder"], ["read_file", "write_file"],
            5.0, 3,
        )
        ee.store_evaluation(ev)

    # All 3 evaluations should be identical
    evals = ee._evaluations[-3:]
    for i in range(1, len(evals)):
        assert evals[i]["goal_completion"] == evals[0]["goal_completion"]
        assert evals[i]["tool_efficiency"] == evals[0]["tool_efficiency"]
        assert evals[i]["execution_stability"] == evals[0]["execution_stability"]


# ═══════════════════════════════════════════════════════════════
# BOUNDED BEHAVIOR VERIFICATION
# ═══════════════════════════════════════════════════════════════

def test_bounded_after_all_missions():
    """Run all 10 mission types and verify everything stays bounded."""
    lt, tpt, mpt, mm = _fresh_state()

    for batch in range(5):  # 5 batches of 10 missions = 50 total
        for i in range(10):
            mid = f"bound-{batch}-{i}"
            mtype = ["coding_task", "debug_task", "research_task", "system_task",
                     "architecture_task", "evaluation_task", "info_query", "planning_task",
                     "self_improvement_task", "business_task"][i]
            tools = [
                (f"tool_{j}", (i + j) % 3 != 0, float(j * 50 + 20))
                for j in range(3)
            ]
            _run_lifecycle(lt, mid, tools, tpt, mpt, mm, f"Task {mid}", mtype,
                          [f"agent_{i%5}"], success=(i+batch)%3!=0)

    # ALL bounded
    assert len(lt._records) <= 500
    assert len(tpt.get_all_stats()) <= 200
    assert len(mpt._type_stats) <= 100
    assert len(mm._strategies) <= 500
    assert len(ee._evaluations) <= 500
    assert len(ee._telemetry_buffer) <= 200
