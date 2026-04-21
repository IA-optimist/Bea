"""
Operating Super Assistant — Extended Validation
===================================================
Economic model, portfolio, opportunities, workflows, approval gating.
"""
import ast
import os
import sys
import pytest
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
# ECONOMIC MODEL
# ═══════════════════════════════════════════════════════════════

def test_economics_basic():
    from core.operating_primitives import compute_economics
    e = compute_economics("Fix the bug", "coding_task", "low", 2, 1)
    assert e.estimated_cost > 0
    assert e.estimated_value > 0
    assert e.expected_return > 0
    assert 0 <= e.priority_score <= 1
    assert e.reasoning


def test_economics_high_value_low_cost():
    from core.operating_primitives import compute_economics
    e = compute_economics("Deploy the fix", "coding_task", "low", 1, 0)
    assert e.estimated_value >= 7  # coding + deploy keyword
    assert e.expected_return > 1


def test_economics_low_value_high_cost():
    from core.operating_primitives import compute_economics
    e = compute_economics("Browse something", "info_query", "critical", 15, 9)
    assert e.estimated_value <= 3
    assert e.estimated_cost >= 7
    assert e.expected_return < 1


def test_economics_risk_reduces_return():
    from core.operating_primitives import compute_economics
    low_risk = compute_economics("Task", "coding_task", "medium", 3, 1)
    high_risk = compute_economics("Task", "coding_task", "medium", 3, 9)
    assert low_risk.expected_return > high_risk.expected_return


def test_economics_time_estimation():
    from core.operating_primitives import compute_economics
    e_low = compute_economics("Task", "coding_task", "low", 2, 0)
    e_high = compute_economics("Task", "coding_task", "high", 10, 0)
    assert e_high.time_to_value_hours > e_low.time_to_value_hours


def test_economics_deterministic():
    from core.operating_primitives import compute_economics
    e1 = compute_economics("Fix bug", "coding_task", "medium", 3, 2, ["read_file"])
    e2 = compute_economics("Fix bug", "coding_task", "medium", 3, 2, ["read_file"])
    assert e1.expected_return == e2.expected_return
    assert e1.priority_score == e2.priority_score


# ═══════════════════════════════════════════════════════════════
# PORTFOLIO MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def test_portfolio_summary():
    from core.operating_primitives import ObjectiveTracker, ObjectivePortfolio
    ot = ObjectiveTracker(persist_path=f"/tmp/pf_sum_{time.time()}.json")
    ot.create("Project A", mission_type="coding_task")
    ot.create("Project B", mission_type="research_task")
    pf = ObjectivePortfolio(ot)
    summary = pf.get_portfolio_summary()
    assert summary["total_objectives"] == 2
    assert summary["active"] == 2
    assert "coding_task" in summary["by_domain"]


def test_portfolio_prioritize():
    from core.operating_primitives import ObjectiveTracker, ObjectivePortfolio
    ot = ObjectiveTracker(persist_path=f"/tmp/pf_pri_{time.time()}.json")
    obj1 = ot.create("Old project")
    obj1.created_at = time.time() - 86400 * 10
    obj2 = ot.create("Recent project")
    ot.record_mission(obj2.objective_id, "m1", True)

    pf = ObjectivePortfolio(ot)
    prioritized = pf.prioritize()
    assert len(prioritized) == 2
    # Recent with success should rank higher
    assert prioritized[0].objective_id == obj2.objective_id


def test_portfolio_stalled_detection():
    from core.operating_primitives import ObjectiveTracker, ObjectivePortfolio
    ot = ObjectiveTracker(persist_path=f"/tmp/pf_stall_{time.time()}.json")
    obj = ot.create("Stalled project")
    obj.updated_at = time.time() - 86400 * 3  # 3 days ago

    pf = ObjectivePortfolio(ot)
    stalled = pf.detect_stalled(stale_hours=48)
    assert len(stalled) == 1
    assert stalled[0].objective_id == obj.objective_id


def test_portfolio_termination_suggestions():
    from core.operating_primitives import ObjectiveTracker, ObjectivePortfolio
    ot = ObjectiveTracker(persist_path=f"/tmp/pf_term_{time.time()}.json")
    obj = ot.create("Failing project")
    for i in range(6):
        ot.record_mission(obj.objective_id, f"m{i}", False)  # all fail
    ot.record_mission(obj.objective_id, "m6", True)  # 1 success

    pf = ObjectivePortfolio(ot)
    suggestions = pf.suggest_termination()
    assert len(suggestions) >= 1
    assert suggestions[0]["recommendation"] == "terminate"


def test_portfolio_slot_allocation():
    from core.operating_primitives import ObjectiveTracker, ObjectivePortfolio
    ot = ObjectiveTracker(persist_path=f"/tmp/pf_slot_{time.time()}.json")
    for i in range(8):
        ot.create(f"Project {i}")
    pf = ObjectivePortfolio(ot)
    slots = pf.allocate_slots(total_slots=3)
    assert len(slots) == 3
    assert all("objective_id" in s for s in slots)


# ═══════════════════════════════════════════════════════════════
# OPPORTUNITY DETECTION
# ═══════════════════════════════════════════════════════════════

def test_opportunity_detection_bounded():
    import core.operating_primitives as op
    op._last_opportunity_scan = 0  # reset rate limiter
    suggestions = op.detect_opportunities()
    assert isinstance(suggestions, list)
    assert len(suggestions) <= op._MAX_SUGGESTIONS


def test_opportunity_rate_limited():
    import core.operating_primitives as op
    op._last_opportunity_scan = 0
    r1 = op.detect_opportunities()
    r2 = op.detect_opportunities()
    # Second call should be rate-limited
    assert r2 == []


def test_opportunity_with_failure_data():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.mission_performance_tracker as mpt_mod
    import core.operating_primitives as op

    mpt = MissionPerformanceTracker(persist_path=f"/tmp/opp_fail_{time.time()}.json")
    for i in range(10):
        mpt.record(MissionOutcome(mission_id=f"of-{i}", mission_type="failing_type",
                                  success=i > 8, agents_used=["a"]))

    old = mpt_mod._tracker
    mpt_mod._tracker = mpt
    op._last_opportunity_scan = 0
    try:
        suggestions = op.detect_opportunities()
        failure_sug = [s for s in suggestions if s.source == "failure_pattern"]
        assert len(failure_sug) >= 1  # failing_type should trigger
    finally:
        mpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# WORKFLOW TEMPLATES
# ═══════════════════════════════════════════════════════════════

def test_workflow_record_and_retrieve():
    from core.operating_primitives import WorkflowTemplateStore
    ws = WorkflowTemplateStore(persist_path=f"/tmp/wf_{time.time()}.json")
    ws.record_successful_workflow("coding_task", ["read_file", "write_file"],
                                  ["research", "execution", "verification"])
    ws.record_successful_workflow("coding_task", ["read_file", "write_file"],
                                  ["research", "execution", "verification"])
    best = ws.get_best_template("coding_task")
    assert best is not None
    assert best.uses >= 2
    assert "research" in best.phases


def test_workflow_persistence():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmppath = f.name
    try:
        from core.operating_primitives import WorkflowTemplateStore
        ws1 = WorkflowTemplateStore(persist_path=tmppath)
        ws1.record_successful_workflow("debug_task", ["shell_command"],
                                       ["research", "execution"])
        ws1.record_successful_workflow("debug_task", ["shell_command"],
                                       ["research", "execution"])

        ws2 = WorkflowTemplateStore(persist_path=tmppath)
        ws2.load()
        assert len(ws2._templates) >= 1
        best = ws2.get_best_template("debug_task")
        assert best is not None
    finally:
        os.unlink(tmppath)


def test_workflow_bounded():
    from core.operating_primitives import WorkflowTemplateStore
    ws = WorkflowTemplateStore(persist_path=f"/tmp/wf_bound_{time.time()}.json")
    ws.MAX_TEMPLATES = 5
    for i in range(10):
        ws.record_successful_workflow(f"type_{i}", ["tool"], ["phase"])
    assert len(ws._templates) <= 5


# ═══════════════════════════════════════════════════════════════
# APPROVAL GATING
# ═══════════════════════════════════════════════════════════════

def test_approval_required_for_external():
    from core.operating_primitives import requires_approval
    assert requires_approval("external_api")
    assert requires_approval("financial")
    assert requires_approval("publish")
    assert requires_approval("deploy")
    assert requires_approval("communicate")


def test_approval_not_required_for_internal():
    from core.operating_primitives import requires_approval
    assert not requires_approval("read_file")
    assert not requires_approval("analyze")
    assert not requires_approval("plan")


def test_approval_required_for_high_risk():
    from core.operating_primitives import requires_approval
    assert requires_approval("any_action", risk_level="high")
    assert requires_approval("any_action", risk_level="critical")


def test_approval_status():
    from core.operating_primitives import get_approval_status
    status = get_approval_status()
    assert "approval_required_actions" in status
    assert len(status["approval_required_actions"]) >= 5


# ═══════════════════════════════════════════════════════════════
# MULTI-OBJECTIVE ECONOMIC SCENARIOS
# ═══════════════════════════════════════════════════════════════

def test_scenario_multi_objective_prioritization():
    """Multiple objectives compete for execution slots."""
    from core.operating_primitives import (
        ObjectiveTracker, ObjectivePortfolio, compute_economics
    )
    ot = ObjectiveTracker(persist_path=f"/tmp/sc_multi_{time.time()}.json")
    # Create objectives with different profiles
    obj_high = ot.create("Launch MVP", "Critical product launch", "coding_task")
    for _ in range(5): ot.record_mission(obj_high.objective_id, f"h{_}", True)

    obj_medium = ot.create("Research competitors", "", "research_task")
    for _ in range(3): ot.record_mission(obj_medium.objective_id, f"m{_}", _ > 0)

    obj_stalled = ot.create("Old project", "", "general")
    obj_stalled.updated_at = time.time() - 86400 * 5

    pf = ObjectivePortfolio(ot)
    prioritized = pf.prioritize()
    assert prioritized[0].objective_id == obj_high.objective_id  # highest success + recency

    stalled = pf.detect_stalled()
    assert obj_stalled in stalled


def test_scenario_economic_scoring_consistency():
    """Same mission scored identically in multiple contexts."""
    from core.operating_primitives import compute_economics
    params = ("Build API", "coding_task", "medium", 4, 2, ["read_file", "write_file"])
    scores = [compute_economics(*params).expected_return for _ in range(5)]
    assert all(s == scores[0] for s in scores)


def test_scenario_priority_no_oscillation():
    """Mission priority remains stable without new data."""
    from core.operating_primitives import prioritize_missions
    missions = [
        {"goal": "Task A", "mission_type": "coding_task", "complexity": "medium", "tools": [], "risk_score": 2},
        {"goal": "Task B", "mission_type": "research_task", "complexity": "low", "tools": [], "risk_score": 1},
        {"goal": "Task C", "mission_type": "debug_task", "complexity": "high", "tools": [], "risk_score": 5},
    ]
    order1 = [m["goal"] for m in prioritize_missions(list(missions))]
    order2 = [m["goal"] for m in prioritize_missions(list(missions))]
    assert order1 == order2  # deterministic ordering


# ═══════════════════════════════════════════════════════════════
# INTEGRATION VERIFICATION
# ═══════════════════════════════════════════════════════════════

def test_mission_system_has_economics():
    with open("core/mission_system.py") as f:
        src = f.read()
    assert "compute_economics" in src
    assert "get_workflow_store" in src


def test_api_has_all_endpoints():
    with open("api/routes/performance.py") as f:
        src = f.read()
    endpoints = ["/operating/economics", "/operating/portfolio",
                 "/operating/opportunities", "/operating/workflows",
                 "/operating/approval"]
    for ep in endpoints:
        assert ep in src, f"Missing: {ep}"


@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_cockpit_has_new_panels():
    with open("static/cockpit.html") as f:
        html = f.read()
    panels = ["portfolio-panel", "opportunities-panel", "workflows-panel"]
    for p in panels:
        assert p in html, f"Missing: {p}"


def test_all_files_parse():
    for f in ["core/operating_primitives.py", "core/mission_system.py",
              "core/planner.py", "api/routes/performance.py"]:
        with open(f) as fh:
            ast.parse(fh.read())
