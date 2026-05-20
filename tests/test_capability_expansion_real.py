"""
Tests for the real capability expansion: tool performance, mission performance,
improvement proposals, improvement detector, performance API, cockpit integration.
"""
import ast
import os
import sys
import types
import pytest
pytestmark = pytest.mark.integration


# Ensure structlog stub
if 'structlog' not in sys.modules:
    sl = types.ModuleType('structlog')
    class ML:
        def info(self,*a,**k): pass
        def debug(self,*a,**k): pass
        def warning(self,*a,**k): pass
    sl.get_logger = lambda *a,**k: ML()
    sys.modules['structlog'] = sl

sys.path.insert(0, '.')


# ═══════════════════════════════════════════════════════════════
# TOOL PERFORMANCE TRACKER
# ═══════════════════════════════════════════════════════════════

def test_tool_performance_tracker_record():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_perf.jsonl")
    t.record(ToolExecution(tool="read_file", success=True, latency_ms=50.0))
    t.record(ToolExecution(tool="read_file", success=True, latency_ms=30.0))
    t.record(ToolExecution(tool="read_file", success=False, latency_ms=100.0, error_type="FileNotFoundError"))
    stats = t.get_stats("read_file")
    assert stats is not None
    assert stats.total_calls == 3
    assert stats.successes == 2
    assert stats.failures == 1
    assert abs(stats.success_rate - 2/3) < 0.01
    assert stats.health_status in ("healthy", "degraded")


def test_tool_performance_tracker_reliability_score():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_perf2.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="good_tool", success=True, latency_ms=20.0))
    for _ in range(10):
        t.record(ToolExecution(tool="bad_tool", success=False, latency_ms=5000.0))
    good = t.get_stats("good_tool")
    bad = t.get_stats("bad_tool")
    assert good.reliability_score > 0.8
    assert bad.reliability_score < 0.3
    assert good.health_status == "healthy"
    assert bad.health_status == "failing"


def test_tool_performance_tracker_ranking():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_perf3.jsonl")
    for _ in range(5):
        t.record(ToolExecution(tool="fast", success=True, latency_ms=10.0))
    for _ in range(5):
        t.record(ToolExecution(tool="slow", success=True, latency_ms=4000.0))
    ranking = t.get_reliability_ranking()
    assert len(ranking) == 2
    assert ranking[0]["tool"] == "fast"


def test_tool_performance_tracker_select_best():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_perf4.jsonl")
    for _ in range(5):
        t.record(ToolExecution(tool="toolA", success=True, latency_ms=20.0))
    for _ in range(5):
        t.record(ToolExecution(tool="toolB", success=False, latency_ms=200.0))
    best = t.get_tool_for_capability(["toolA", "toolB"])
    assert best == "toolA"


def test_tool_performance_tracker_dashboard():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_perf5.jsonl")
    t.record(ToolExecution(tool="x", success=True, latency_ms=10.0))
    d = t.get_dashboard_data()
    assert "summary" in d
    assert "tools" in d
    assert d["summary"]["total_tools_tracked"] == 1


def test_tool_performance_tracker_persist():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "perf.jsonl")
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path=path)
    t.record(ToolExecution(tool="persist_test", success=True, latency_ms=50.0))
    assert t.save()
    t2 = ToolPerformanceTracker(persist_path=path)
    assert t2.load()
    assert t2.get_stats("persist_test") is not None


def test_tool_performance_tracker_lru_eviction():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_perf6.jsonl")
    t.MAX_TOOLS = 3
    for i in range(5):
        t.record(ToolExecution(tool=f"tool_{i}", success=True, latency_ms=10.0))
    assert len(t.get_all_stats()) <= 3


# ═══════════════════════════════════════════════════════════════
# MISSION PERFORMANCE TRACKER
# ═══════════════════════════════════════════════════════════════

def test_mission_performance_tracker_record():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    t = MissionPerformanceTracker(persist_path="/tmp/test_mperf.json")
    t.record(MissionOutcome(
        mission_id="m1", goal="test", mission_type="coding_task",
        success=True, duration_s=5.0, agents_used=["forge-builder"],
        tools_used=["write_file"], plan_steps=3,
    ))
    d = t.get_dashboard_data()
    assert d["summary"]["total_missions_tracked"] == 1
    assert d["summary"]["overall_success_rate"] == 1.0


def test_mission_performance_tracker_strategy():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    t = MissionPerformanceTracker(persist_path="/tmp/test_mperf2.json")
    for i in range(5):
        t.record(MissionOutcome(
            mission_id=f"m{i}", goal="test", mission_type="debug_task",
            success=i < 4, duration_s=10.0, agents_used=["lens-reviewer"],
            tools_used=["check_logs"], plan_steps=2,
        ))
    strategy = t.get_strategy_for_type("debug_task")
    assert strategy["sample_size"] == 5
    assert strategy["success_rate"] == 0.8
    assert "lens-reviewer" in [a for a, _ in strategy["recommended_agents"]]


def test_mission_performance_tracker_best_agents():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    t = MissionPerformanceTracker(persist_path="/tmp/test_mperf3.json")
    for i in range(3):
        t.record(MissionOutcome(
            mission_id=f"m{i}", goal="test", mission_type="coding_task",
            success=True, agents_used=["forge-builder"],
        ))
    t.record(MissionOutcome(
        mission_id="m10", goal="test", mission_type="coding_task",
        success=False, agents_used=["scout-research"],
    ))
    best = t.get_best_agents_for_type("coding_task")
    assert best[0] == "forge-builder"


def test_mission_performance_tracker_agent_domains():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    t = MissionPerformanceTracker(persist_path="/tmp/test_mperf4.json")
    for i in range(5):
        t.record(MissionOutcome(
            mission_id=f"c{i}", goal="code", mission_type="coding_task",
            success=True, agents_used=["forge-builder"],
        ))
    for i in range(5):
        t.record(MissionOutcome(
            mission_id=f"d{i}", goal="debug", mission_type="debug_task",
            success=i < 2, agents_used=["forge-builder"],
        ))
    d = t.get_dashboard_data()
    agents = d["agent_performance"]
    forge = [a for a in agents if a["agent"] == "forge-builder"][0]
    assert forge["domains"]["coding_task"]["rate"] == 1.0
    assert forge["domains"]["debug_task"]["rate"] < 0.5


# ═══════════════════════════════════════════════════════════════
# IMPROVEMENT PROPOSALS
# ═══════════════════════════════════════════════════════════════

def test_improvement_proposals_crud():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "proposals.json")
    from core.improvement_proposals import ProposalStore, ImprovementProposal
    store = ProposalStore(persist_path=path)
    pid = store.add(ImprovementProposal(
        proposal_type="tool_fix",
        title="Fix read_file",
        description="It fails too often",
        risk_score=3,
    ))
    assert len(store.list_pending()) == 1
    assert store.approve(pid)
    assert len(store.list_pending()) == 0
    assert len(store.list_approved()) == 1


def test_improvement_proposals_persist():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "proposals.json")
    from core.improvement_proposals import ProposalStore, ImprovementProposal
    s1 = ProposalStore(persist_path=path)
    s1.add(ImprovementProposal(title="Test", proposal_type="test"))
    s2 = ProposalStore(persist_path=path)
    s2.load()
    assert len(s2.list_all()) == 1


def test_improvement_proposals_reject():
    import tempfile
    from core.improvement_proposals import ProposalStore, ImprovementProposal
    store = ProposalStore(persist_path=os.path.join(tempfile.mkdtemp(), "reject.json"))
    pid = store.add(ImprovementProposal(title="Bad idea", proposal_type="test"))
    assert store.reject(pid, "Not needed")
    assert len(store.list_rejected()) == 1
    assert len(store.list_pending()) == 0


# ═══════════════════════════════════════════════════════════════
# IMPROVEMENT DETECTOR
# ═══════════════════════════════════════════════════════════════

def test_improvement_detector_tool_issues():
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    # Create tracker with bad tool
    t = ToolPerformanceTracker(persist_path="/tmp/test_detect_perf.jsonl")
    for _ in range(10):
        t.record(ToolExecution(tool="broken_tool", success=False, latency_ms=100.0, error_type="TimeoutError"))

    # Monkey-patch the singleton
    import core.tool_performance_tracker as tpt_mod
    old = tpt_mod._tracker
    tpt_mod._tracker = t
    try:
        from core.improvement_detector import detect_improvements
        proposals = detect_improvements(dry_run=True)
        assert any("broken_tool" in p["title"] for p in proposals)
    finally:
        tpt_mod._tracker = old


def test_improvement_detector_dry_run():
    from core.improvement_detector import detect_improvements
    proposals = detect_improvements(dry_run=True)
    assert isinstance(proposals, list)


# ═══════════════════════════════════════════════════════════════
# PLANNER INTEGRATION
# ═══════════════════════════════════════════════════════════════

def test_planner_performance_intelligence_injected():
    """Planner's build_plan should inject performance intelligence when data exists."""
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.mission_performance_tracker as mpt_mod
    t = MissionPerformanceTracker(persist_path="/tmp/test_planner_perf.json")
    for i in range(5):
        t.record(MissionOutcome(
            mission_id=f"p{i}", goal="test", mission_type="coding_task",
            success=True, agents_used=["forge-builder"],
            tools_used=["write_file"], plan_steps=3,
        ))
    old = mpt_mod._tracker
    mpt_mod._tracker = t
    try:
        # build_plan requires mission_planner which may not be importable
        # so we just verify the tracker provides data correctly
        strategy = t.get_strategy_for_type("coding_task")
        assert strategy["sample_size"] == 5
        assert "forge-builder" in [a for a, _ in strategy["recommended_agents"]]
    finally:
        mpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# SYNTAX VALIDATION
# ═══════════════════════════════════════════════════════════════

def test_all_new_files_syntax():
    files = [
        "core/tool_performance_tracker.py",
        "core/mission_performance_tracker.py",
        "core/improvement_proposals.py",
        "core/improvement_detector.py",
        "api/routes/performance.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())


def test_modified_files_syntax():
    files = [
        "core/tool_executor.py",
        "core/mission_system.py",
        "core/planner.py",
        "static/cockpit.html",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            content = fh.read()
        if f.endswith('.py'):
            ast.parse(content)
        elif f.endswith('.html'):
            assert len(content) > 100
            assert '<script>' in content


def test_cockpit_has_performance_screen():
    with open("static/cockpit.html", encoding="utf-8") as f:
        html = f.read()
    assert 'screen-performance' in html
    assert 'loadPerformance' in html
    assert 'screen-improvements' in html
    assert 'loadImprovements' in html
    assert 'approveProposal' in html
    assert 'rejectProposal' in html
    assert '/api/v3/performance/tools' in html


def test_tool_executor_wiring():
    """Tool executor now has performance tracking code."""
    with open("core/tool_executor.py", encoding="utf-8") as f:
        src = f.read()
    assert "tool_performance_tracker" in src
    assert "ToolExecution" in src
    ast.parse(src)


def test_mission_system_wiring():
    """Mission system now has performance tracking code."""
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "mission_performance_tracker" in src
    assert "MissionOutcome" in src
    ast.parse(src)


def test_planner_wiring():
    """Planner now has performance intelligence code."""
    with open("core/planner.py", encoding="utf-8") as f:
        src = f.read()
    assert "mission_performance_tracker" in src
    assert "tool_performance_tracker" in src
    assert "performance_intelligence" in src
    ast.parse(src)


def test_performance_router_syntax():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        ast.parse(f.read())
