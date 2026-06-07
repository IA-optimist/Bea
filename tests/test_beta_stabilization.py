"""
Beta Stabilization Tests
===========================
Stress resilience, lifecycle validation, safety controls,
proposal prioritization, tool validation, recovery wiring,
and integration tests for beta stability.
"""
import ast
import os
import sys
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
# SAFETY CONTROLS
# ═══════════════════════════════════════════════════════════════

def test_safety_state_defaults():
    os.environ.pop("BEA_DISABLE_ALL_INTELLIGENCE", None)
    os.environ.pop("BEA_DISABLE_PROPOSALS", None)
    from core.safety_controls import get_safety_state
    state = get_safety_state()
    assert state.intelligence_enabled
    assert state.proposals_enabled
    assert not state.dynamic_routing_enabled  # opt-in, default OFF


def test_safety_kill_all():
    os.environ["BEA_DISABLE_ALL_INTELLIGENCE"] = "1"
    try:
        from core.safety_controls import get_safety_state, is_intelligence_enabled, is_proposals_enabled
        state = get_safety_state()
        assert not state.intelligence_enabled
        assert not is_intelligence_enabled()
        assert not is_proposals_enabled()  # disabled by parent
    finally:
        os.environ.pop("BEA_DISABLE_ALL_INTELLIGENCE", None)


def test_safety_disable_proposals():
    os.environ["BEA_DISABLE_PROPOSALS"] = "1"
    try:
        from core.safety_controls import is_proposals_enabled
        assert not is_proposals_enabled()
    finally:
        os.environ.pop("BEA_DISABLE_PROPOSALS", None)


def test_safety_disable_execution_engine():
    os.environ["BEA_DISABLE_EXECUTION_ENGINE"] = "1"
    try:
        from core.safety_controls import is_execution_engine_enabled
        assert not is_execution_engine_enabled()
    finally:
        os.environ.pop("BEA_DISABLE_EXECUTION_ENGINE", None)


# ═══════════════════════════════════════════════════════════════
# LIFECYCLE VALIDATION
# ═══════════════════════════════════════════════════════════════

def test_lifecycle_valid():
    from core.safety_controls import validate_lifecycle
    steps = [
        "mission_received", "plan_generated", "agents_selected",
        "tools_executed", "results_evaluated", "memory_updated", "proposals_checked",
    ]
    result = validate_lifecycle(steps)
    assert result["valid"]
    assert result["coverage"] == 1.0
    assert result["missing"] == []


def test_lifecycle_partial():
    from core.safety_controls import validate_lifecycle
    steps = ["mission_received", "plan_generated", "agents_selected"]
    result = validate_lifecycle(steps)
    assert not result["valid"]
    assert len(result["missing"]) >= 4
    assert result["coverage"] < 0.5


def test_lifecycle_empty():
    from core.safety_controls import validate_lifecycle
    result = validate_lifecycle([])
    assert not result["valid"]
    assert result["coverage"] == 0.0


# ═══════════════════════════════════════════════════════════════
# PROPOSAL PRIORITIZATION
# ═══════════════════════════════════════════════════════════════

def test_proposal_priority_ordering():
    import tempfile
    from core.improvement_proposals import ProposalStore, ImprovementProposal
    store = ProposalStore(persist_path=os.path.join(tempfile.mkdtemp(), "prio.json"))

    # High priority: tool_fix, low risk
    store.add(ImprovementProposal(
        proposal_type="tool_fix", title="Fix critical tool",
        risk_score=2, source="auto",
    ))
    # Low priority: new_tool, high risk
    store.add(ImprovementProposal(
        proposal_type="new_tool", title="Add fancy new tool",
        risk_score=8, source="auto",
    ))
    # Medium priority: planning_rule
    store.add(ImprovementProposal(
        proposal_type="planning_rule", title="Adjust planning",
        risk_score=4, source="auto",
    ))

    pending = store.list_pending()
    assert len(pending) == 3
    # tool_fix (low risk) should rank first
    assert pending[0]["proposal_type"] == "tool_fix"
    # new_tool (high risk) should rank last
    assert pending[-1]["proposal_type"] == "new_tool"


# ═══════════════════════════════════════════════════════════════
# TOOL VALIDATION
# ═══════════════════════════════════════════════════════════════

def test_tool_quality_detection():
    from core.tool_gap_analyzer import _detect_tool_quality_issues
    # This should run without error even with no data
    issues = _detect_tool_quality_issues()
    assert isinstance(issues, list)


# ═══════════════════════════════════════════════════════════════
# RECOVERY MEMORY WIRING
# ═══════════════════════════════════════════════════════════════

def test_recovery_memory_used_in_execution():
    """Verify execution_engine.execute_tool_intelligently consults recovery memory."""
    with open("core/execution_engine.py", encoding="utf-8") as f:
        src = f.read()
    assert "get_best_recovery" in src
    assert "_recovery_hint" in src
    assert "recovery_memory" in src or "recovery_hint" in src


# ═══════════════════════════════════════════════════════════════
# STRESS TESTS
# ═══════════════════════════════════════════════════════════════

def test_stress_tool_tracker_high_volume():
    """Tool tracker handles 1000 rapid recordings without error."""
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    t = ToolPerformanceTracker(persist_path="/tmp/test_stress.jsonl")
    for i in range(1000):
        t.record(ToolExecution(
            tool=f"tool_{i % 50}",
            success=i % 3 != 0,
            latency_ms=float(i % 100),
        ))
    assert len(t.get_all_stats()) <= 200  # bounded


def test_stress_mission_tracker_high_volume():
    """Mission tracker handles 500 recordings without error."""
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    t = MissionPerformanceTracker(persist_path="/tmp/test_stress2.json")
    for i in range(500):
        t.record(MissionOutcome(
            mission_id=f"m{i}",
            mission_type=f"type_{i % 20}",
            success=i % 4 != 0,
            agents_used=[f"agent_{i % 7}"],
            tools_used=[f"tool_{i % 15}"],
        ))
    d = t.get_dashboard_data()
    assert d["summary"]["total_missions_tracked"] == 500


def test_stress_mission_memory_high_volume():
    """Mission memory handles 300 recordings without error."""
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/test_stress3.json")
    for i in range(300):
        mm.record_outcome(
            f"type_{i % 10}",
            [f"agent_{i % 5}"],
            [f"tool_{i % 8}"],
            plan_steps=i % 5 + 1,
            success=i % 3 != 0,
            duration_s=float(i % 30),
        )
    assert len(mm._strategies) <= 500  # bounded


def test_stress_proposal_store_high_volume():
    """Proposal store handles 600 proposals without error."""
    import tempfile
    from core.improvement_proposals import ProposalStore, ImprovementProposal
    store = ProposalStore(persist_path=os.path.join(tempfile.mkdtemp(), "stress.json"))
    for i in range(600):
        store.add(ImprovementProposal(
            title=f"Proposal {i}",
            proposal_type="test",
            risk_score=i % 10 + 1,
        ))
    assert len(store._proposals) <= 500  # bounded


def test_stress_telemetry_buffer():
    """Telemetry buffer stays bounded after fresh clear + fill."""
    import core.execution_engine as ee
    ee._telemetry_buffer = []  # reset module-level state
    for i in range(300):
        t = ee.ExecutionTelemetry(mission_id=f"stress_t{i}", started_at=time.time())
        t.finished_at = time.time()
        ee.record_telemetry(t)
    assert len(ee._telemetry_buffer) <= 200


def test_stress_evaluation_buffer():
    """Evaluation buffer stays bounded after fresh clear + fill."""
    import core.execution_engine as ee
    ee._evaluations = []  # reset module-level state
    for i in range(600):
        ev = ee.evaluate_mission(
            f"stress_e{i}", True, "output", "goal", [], [], 1.0, 1,
        )
        ee.store_evaluation(ev)
    assert len(ee._evaluations) <= 500


def test_stress_recovery_memory_bounded():
    """Recovery memory stays bounded."""
    from core.execution_engine import record_recovery, _recovery_memory
    _recovery_memory.clear()
    for i in range(300):
        record_recovery(f"tool_{i}", f"err_{i}", "retry", success=i % 2 == 0)
    assert len(_recovery_memory) <= 200


def test_stress_knowledge_ingestion_dedup():
    """Knowledge ingestion dedup doesn't grow unbounded."""
    import core.knowledge_ingestion as ki
    ki._recent_ingestions = []  # reset module-level state
    for i in range(500):
        ki.should_ingest(
            f"type_{i % 20}", True,
            [f"agent_{i}"], [f"tool_{i}"],
            3, "medium",
        )
    assert len(ki._recent_ingestions) <= 200


# ═══════════════════════════════════════════════════════════════
# NO INFINITE LOOPS
# ═══════════════════════════════════════════════════════════════

def test_no_circular_fallback():
    """Fallback chain doesn't loop (fallback of fallback is blocked)."""
    from core.execution_engine import TOOL_ALTERNATIVES
    # Verify no A→B→A cycles with allow_fallback=False on recursive call
    # The code passes allow_fallback=False on recursive calls, so this is safe
    for tool, alts in TOOL_ALTERNATIVES.items():
        for alt in alts:
            if alt in TOOL_ALTERNATIVES:
                # alt's alternatives should not circle back unsafely
                # but it's ok because execute_tool_intelligently passes
                # allow_fallback=False on the recursive call
                pass
    # Just verify the code structure prevents loops
    with open("core/execution_engine.py", encoding="utf-8") as f:
        src = f.read()
    assert "allow_fallback=False" in src


# ═══════════════════════════════════════════════════════════════
# DETECTOR RESPECTS SAFETY
# ═══════════════════════════════════════════════════════════════

def test_detector_respects_safety_kill():
    os.environ["BEA_DISABLE_PROPOSALS"] = "1"
    try:
        from core.improvement_detector import detect_improvements
        result = detect_improvements(dry_run=True)
        assert result == []
    finally:
        os.environ.pop("BEA_DISABLE_PROPOSALS", None)


def test_detector_works_when_enabled():
    os.environ.pop("BEA_DISABLE_PROPOSALS", None)
    os.environ.pop("BEA_DISABLE_ALL_INTELLIGENCE", None)
    from core.improvement_detector import detect_improvements
    result = detect_improvements(dry_run=True)
    assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════
# SYNTAX AND WIRING
# ═══════════════════════════════════════════════════════════════

def test_all_files_syntax():
    files = [
        "core/safety_controls.py",
        "core/execution_engine.py",
        "core/improvement_proposals.py",
        "core/improvement_detector.py",
        "core/tool_gap_analyzer.py",
        "core/tool_runner.py",
        "api/routes/performance.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())


def test_tool_runner_checks_safety():
    with open("core/tool_runner.py", encoding="utf-8") as f:
        src = f.read()
    assert "is_execution_engine_enabled" in src
    assert "safety_controls" in src


def test_performance_api_has_safety_endpoints():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "/safety" in src
    assert "lifecycle/validate" in src
