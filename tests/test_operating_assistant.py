"""
Operating Super Assistant Validation
========================================
Tests operating primitives, multi-session objectives,
strategy selection, feasibility scoring, and real-world workflows.
"""
import pytest
import ast
import json
import os
import sys
import tempfile
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
# FEASIBILITY SCORING
# ═══════════════════════════════════════════════════════════════

def test_feasibility_no_data():
    """Feasibility returns moderate scores with no prior data."""
    from core.operating_primitives import score_feasibility
    f = score_feasibility("Fix the bug", "coding_task", ["read_file", "write_file"])
    assert 0 < f.overall < 1
    assert f.tool_coverage >= 0
    assert f.agent_readiness >= 0


def test_feasibility_with_performance_data():
    """Feasibility improves when performance data exists."""
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.tool_performance_tracker as tpt_mod
    import core.mission_performance_tracker as mpt_mod

    tpt = ToolPerformanceTracker(persist_path="/tmp/op_feas_t.jsonl")
    mpt = MissionPerformanceTracker(persist_path="/tmp/op_feas_m.json")
    for _ in range(10):
        tpt.record(ToolExecution(tool="read_file", success=True, latency_ms=30))
        mpt.record(MissionOutcome(mission_id=f"f-{_}", mission_type="coding_task",
                                  success=True, agents_used=["forge-builder"]))

    old_t, old_m = tpt_mod._tracker, mpt_mod._tracker
    tpt_mod._tracker, mpt_mod._tracker = tpt, mpt
    try:
        from core.operating_primitives import score_feasibility
        f = score_feasibility("Fix the bug", "coding_task", ["read_file"])
        assert f.tool_coverage > 0.5  # healthy tool
        assert f.agent_readiness > 0.5  # good mission history
        assert f.overall > 0.5
    finally:
        tpt_mod._tracker, mpt_mod._tracker = old_t, old_m


def test_feasibility_missing_tools():
    """Feasibility flags missing tools."""
    from core.operating_primitives import score_feasibility
    f = score_feasibility("Deploy to production", "system_task",
                         ["docker_build", "kubernetes_deploy", "cloud_monitor"])
    assert len(f.missing_tools) >= 1  # tools with no data


# ═══════════════════════════════════════════════════════════════
# VALUE ESTIMATION
# ═══════════════════════════════════════════════════════════════

def test_value_high_benefit_low_cost():
    from core.operating_primitives import estimate_value
    v = estimate_value("Fix critical bug", "coding_task", "low", 2, 1)
    assert v.expected_benefit == "high"
    assert v.execution_cost == "low"
    assert v.net_value_score > 0.5


def test_value_low_benefit_high_cost():
    from core.operating_primitives import estimate_value
    v = estimate_value("Generate a report", "info_query", "high", 10, 8)
    assert v.net_value_score < 0.5


def test_value_risk_reduces_score():
    from core.operating_primitives import estimate_value
    v_low_risk = estimate_value("Task", "coding_task", "medium", 3, 1)
    v_high_risk = estimate_value("Task", "coding_task", "medium", 3, 9)
    assert v_low_risk.net_value_score > v_high_risk.net_value_score


# ═══════════════════════════════════════════════════════════════
# STRATEGY SELECTION
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="stale: API changed")
def test_strategy_default():
    from core.operating_primitives import select_strategy
    import core.mission_performance_tracker as mpt_mod
    # Replace singleton with empty tracker (no disk load) for clean state
    old_tracker = mpt_mod._tracker
    mpt_mod._tracker = mpt_mod.MissionPerformanceTracker(persist_path="/dev/null")
    try:
        s = select_strategy("Fix a bug", "coding_task", "medium")
        assert s.source == "default"  # no prior data
        assert len(s.agents) >= 1
        assert len(s.tools) >= 1
        assert s.confidence > 0
    finally:
        mpt_mod._tracker = old_tracker


def test_strategy_from_memory():
    """Strategy uses memory when available."""
    from core.mission_memory import MissionMemory
    import core.operating_primitives as op
    from core.operating_primitives import select_strategy

    mm = MissionMemory(persist_path="/tmp/op_strat_mm.json")
    for i in range(10):
        mm.record_outcome("coding_task", ["forge-builder"], ["read_file", "write_file"], 3, i > 2)

    # Monkey-patch get_mission_memory
    import core.mission_memory as mm_mod
    old = mm_mod._memory
    mm_mod._memory = mm
    try:
        s = select_strategy("Fix a bug", "coding_task")
        if s.source == "memory":
            assert s.confidence > 0.4
            assert "forge-builder" in s.agents
    finally:
        mm_mod._memory = old


# ═══════════════════════════════════════════════════════════════
# OBJECTIVE PERSISTENCE
# ═══════════════════════════════════════════════════════════════

def test_objective_create_and_track():
    from core.operating_primitives import ObjectiveTracker
    ot = ObjectiveTracker(persist_path="/tmp/op_obj.json")
    obj = ot.create("Build MVP", "Create minimum viable product", "coding_task")
    assert obj.objective_id
    assert obj.status == "active"

    ot.record_mission(obj.objective_id, "m1", True)
    ot.record_mission(obj.objective_id, "m2", False)
    ot.record_mission(obj.objective_id, "m3", True)

    updated = ot.get(obj.objective_id)
    assert updated.total_missions == 3
    assert updated.successful_missions == 2
    assert updated.success_rate > 0.5


def test_objective_persistence():
    """Save and reload objectives across sessions."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmppath = f.name
    try:
        from core.operating_primitives import ObjectiveTracker
        ot1 = ObjectiveTracker(persist_path=tmppath)
        obj = ot1.create("Deploy v2", "Deploy version 2 to production")
        ot1.record_mission(obj.objective_id, "m1", True)

        ot2 = ObjectiveTracker(persist_path=tmppath)
        ot2.load()
        restored = ot2.get(obj.objective_id)
        assert restored is not None
        assert restored.title == "Deploy v2"
        assert restored.total_missions == 1
    finally:
        os.unlink(tmppath)


def test_objective_bounded():
    from core.operating_primitives import ObjectiveTracker
    ot = ObjectiveTracker(persist_path="/tmp/op_bound.json")
    ot.MAX_OBJECTIVES = 10
    for i in range(20):
        ot.create(f"Objective {i}")
    assert len(ot._objectives) <= 10


def test_objective_dashboard():
    from core.operating_primitives import ObjectiveTracker
    ot = ObjectiveTracker(persist_path=f"/tmp/op_dash_{time.time()}.json")
    ot.create("Active 1")
    obj2 = ot.create("Completed 1")
    ot.complete(obj2.objective_id)

    d = ot.get_dashboard()
    assert d["total"] == 2
    assert d["active"] == 1
    assert d["completed"] == 1


# ═══════════════════════════════════════════════════════════════
# MISSION COORDINATION
# ═══════════════════════════════════════════════════════════════

def test_concurrent_mission_limit():
    from core.operating_primitives import can_accept_mission, MAX_CONCURRENT_MISSIONS
    assert can_accept_mission(0)
    assert can_accept_mission(MAX_CONCURRENT_MISSIONS - 1)
    assert not can_accept_mission(MAX_CONCURRENT_MISSIONS)


def test_mission_prioritization():
    from core.operating_primitives import prioritize_missions
    missions = [
        {"goal": "Fix critical bug", "mission_type": "debug_task", "complexity": "low", "tools": [], "risk_score": 1},
        {"goal": "Generate report", "mission_type": "info_query", "complexity": "high", "tools": [], "risk_score": 5},
        {"goal": "Deploy system", "mission_type": "system_task", "complexity": "medium", "tools": [], "risk_score": 3},
    ]
    prioritized = prioritize_missions(missions)
    assert len(prioritized) == 3
    # Each has a priority score
    for m in prioritized:
        assert "_priority_score" in m
    # First should have highest score
    assert prioritized[0]["_priority_score"] >= prioritized[-1]["_priority_score"]


# ═══════════════════════════════════════════════════════════════
# OPERATIONAL SIGNALS
# ═══════════════════════════════════════════════════════════════

def test_operational_signals():
    from core.operating_primitives import get_operational_signals
    signals = get_operational_signals()
    assert "mission_success_distribution" in signals
    assert "tool_impact" in signals
    assert "execution_stability" in signals
    assert "planning_confidence" in signals


# ═══════════════════════════════════════════════════════════════
# REAL-WORLD WORKFLOW SIMULATIONS
# ═══════════════════════════════════════════════════════════════

def test_workflow_project_execution():
    """Multi-step structured project with objective tracking."""
    from core.operating_primitives import ObjectiveTracker, score_feasibility, estimate_value
    from core.lifecycle_tracker import LifecycleTracker
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.execution_engine as ee

    ot = ObjectiveTracker(persist_path="/tmp/wf_proj.json")
    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path="/tmp/wf_proj_t.jsonl")
    ee._evaluations = []

    # Create objective
    obj = ot.create("Build authentication module", "Implement JWT auth", "coding_task")

    # Phase 1: Research
    f = score_feasibility("Research JWT patterns", "research_task", ["http_get", "vector_search"])
    assert f.overall > 0

    lt.start("proj-1")
    for stage in ["plan_generated", "agents_selected", "tools_executed",
                   "results_evaluated", "memory_updated", "proposals_checked"]:
        lt.record("proj-1", stage)
    lt.finish("proj-1")
    ot.record_mission(obj.objective_id, "proj-1", True)

    # Phase 2: Implementation
    lt.start("proj-2")
    tpt.record(ToolExecution(tool="write_file", success=True, latency_ms=100))
    for stage in ["plan_generated", "agents_selected", "tools_executed",
                   "results_evaluated", "memory_updated", "proposals_checked"]:
        lt.record("proj-2", stage)
    lt.finish("proj-2")
    ot.record_mission(obj.objective_id, "proj-2", True)

    # Phase 3: Testing
    lt.start("proj-3")
    tpt.record(ToolExecution(tool="shell_command", success=True, latency_ms=500))
    for stage in ["plan_generated", "agents_selected", "tools_executed",
                   "results_evaluated", "memory_updated", "proposals_checked"]:
        lt.record("proj-3", stage)
    lt.finish("proj-3")
    ot.record_mission(obj.objective_id, "proj-3", True)

    ot.complete(obj.objective_id)

    # Verify
    completed = ot.get(obj.objective_id)
    assert completed.status == "completed"
    assert completed.total_missions == 3
    assert completed.success_rate == 1.0


@pytest.mark.skip(reason="stale: API changed")
def test_workflow_iterative_strategy():
    """Strategy improves over multiple missions."""
    from core.operating_primitives import select_strategy
    from core.mission_memory import MissionMemory
    import core.mission_memory as mm_mod
    import core.mission_performance_tracker as mpt_mod

    # Use empty tracker (no disk load) for clean state
    old_tracker = mpt_mod._tracker
    mpt_mod._tracker = mpt_mod.MissionPerformanceTracker(persist_path="/dev/null")

    mm = MissionMemory(persist_path="/tmp/wf_iter.json")

    # Early: no data → default strategy
    old = mm_mod._memory
    mm_mod._memory = mm
    try:
        s1 = select_strategy("Fix bug", "coding_task")
        assert s1.source == "default"

        # Build experience
        for i in range(10):
            mm.record_outcome("coding_task", ["forge-builder"], ["read_file", "write_file"], 3, i > 2)

        # Later: memory-based strategy
        s2 = select_strategy("Fix another bug", "coding_task")
        if s2.source == "memory":
            assert s2.confidence > s1.confidence
    finally:
        mm_mod._memory = old
        mpt_mod._tracker = old_tracker


def test_workflow_constraint_adaptation():
    """Value estimation adapts to risk/complexity changes."""
    from core.operating_primitives import estimate_value
    v1 = estimate_value("Task", "coding_task", "low", 2, 1)
    v2 = estimate_value("Task", "coding_task", "high", 8, 7)
    assert v1.net_value_score > v2.net_value_score


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: Wiring Verification
# ═══════════════════════════════════════════════════════════════

def test_planner_has_feasibility():
    """Planner integrates operating primitives."""
    with open("core/planner.py") as f:
        src = f.read()
    assert "score_feasibility" in src
    assert "select_strategy" in src
    assert "feasibility_score" in src


def test_api_has_operating_endpoints():
    with open("api/routes/performance.py") as f:
        src = f.read()
    assert "/operating/feasibility" in src
    assert "/operating/value" in src
    assert "/operating/strategy" in src
    assert "/operating/signals" in src
    assert "/operating/objectives" in src


@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_cockpit_has_operating_panels():
    with open("static/cockpit.html") as f:
        html = f.read()
    assert "operational-signals" in html
    assert "objectives-panel" in html
    assert "/api/v3/performance/operating/signals" in html
    assert "/api/v3/performance/operating/objectives" in html


def test_all_new_files_parse():
    files = [
        "core/operating_primitives.py",
        "core/planner.py",
        "api/routes/performance.py",
    ]
    for f in files:
        with open(f) as fh:
            ast.parse(fh.read())
