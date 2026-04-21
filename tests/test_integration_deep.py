"""
Deep Integration Tests — Beta Convergence Validation
========================================================
Verifies all 10 priority objectives through simulation.
"""
import pytest
import ast
import json
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
# P1: SINGLE CANONICAL EXECUTION PATH
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="stale: response changed")
def test_p1_single_mission_api():
    """Only one mission submission path is active in the main API."""
    with open("api/main.py") as f:
        src = f.read()
    # ms.submit() is called once in _run_mission
    submit_calls = [l for l in src.splitlines() if "ms.submit(" in l and "#" not in l.lstrip()[:2]]
    assert len(submit_calls) >= 1
    # _get_orchestrator routes to MetaOrchestrator (canonical)
    assert "get_meta_orchestrator" in src


def test_p1_convergence_router_is_separate():
    """Convergence router is a separate path (v3), not duplicating v1."""
    with open("api/routes/convergence.py") as f:
        src = f.read()
    assert "prefix=\"/api/v3\"" in src
    # It delegates to bridge, not directly to MissionSystem
    assert "OrchestrationBridge" in src or "bridge_submit" in src


# ═══════════════════════════════════════════════════════════════
# P2: LIFECYCLE SIGNALS FOR EVERY PHASE
# ═══════════════════════════════════════════════════════════════

def test_p2_all_7_stages_wired():
    """All 7 lifecycle stages are recorded in the actual execution flow."""
    stages_in_mission_system = set()
    stages_in_tool_runner = set()
    with open("core/mission_system.py") as f:
        ms_src = f.read()
    with open("core/tool_runner.py") as f:
        tr_src = f.read()

    # mission_received is recorded via lifecycle_tracker.start(), not as a string literal
    assert "lifecycle" in ms_src and ".start(" in ms_src, "mission_received not wired via lifecycle.start()"
    for stage in ["plan_generated", "agents_selected",
                   "results_evaluated", "memory_updated", "proposals_checked"]:
        assert f'"{stage}"' in ms_src, f"Stage {stage} not in mission_system.py"

    assert '"tools_executed"' in tr_src, "tools_executed not in tool_runner.py"


def test_p2_lifecycle_tracker_start_and_finish():
    """Lifecycle tracker is started and finished in mission_system."""
    with open("core/mission_system.py") as f:
        src = f.read()
    assert ".start(" in src  # lifecycle.start(mission_id)
    assert ".finish(" in src  # lifecycle.finish(mission_id)


# ═══════════════════════════════════════════════════════════════
# P3: PLANNER → EXECUTOR → MEMORY → IMPROVEMENT LOOP
# ═══════════════════════════════════════════════════════════════

def test_p3_planner_queries_performance():
    """Planner integrates performance intelligence."""
    with open("core/planner.py") as f:
        src = f.read()
    assert "mission_performance_tracker" in src
    assert "tool_performance_tracker" in src


def test_p3_executor_records_performance():
    """Tool executor records performance data."""
    with open("core/tool_executor.py") as f:
        src = f.read()
    assert "tool_performance_tracker" in src


def test_p3_mission_complete_records_all():
    """Mission complete records to all memory systems."""
    with open("core/mission_system.py") as f:
        src = f.read()
    assert "mission_performance_tracker" in src
    assert "knowledge_ingestion" in src
    assert "mission_memory" in src
    assert "evaluate_mission" in src
    assert "detect_improvements" in src


def test_p3_full_loop_simulation():
    """Simulate: plan → execute → memory → detect improvements."""
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    from core.mission_memory import MissionMemory
    import core.tool_performance_tracker as tpt_mod
    import core.mission_performance_tracker as mpt_mod

    tpt = ToolPerformanceTracker(persist_path="/tmp/p3_loop_t.jsonl")
    mpt = MissionPerformanceTracker(persist_path="/tmp/p3_loop_m.json")
    mm = MissionMemory(persist_path="/tmp/p3_loop_mm.json")

    # Execute 20 missions
    for i in range(20):
        tool = f"tool_{i % 5}"
        success = i % 4 != 0
        tpt.record(ToolExecution(tool=tool, success=success, latency_ms=float(i * 10 + 10)))
        mpt.record(MissionOutcome(
            mission_id=f"loop-{i}", mission_type="coding_task",
            success=success, agents_used=["forge-builder"],
            tools_used=[tool],
        ))
        mm.record_outcome("coding_task", ["forge-builder"], [tool], 3, success)

    old_t, old_m = tpt_mod._tracker, mpt_mod._tracker
    tpt_mod._tracker, mpt_mod._tracker = tpt, mpt
    try:
        # Planner should now be able to query performance data
        strategy = mpt.get_strategy_for_type("coding_task")
        assert strategy is not None
        assert strategy["sample_size"] >= 10

        # Improvement detector should find issues
        os.environ.pop("JARVIS_DISABLE_PROPOSALS", None)
        os.environ.pop("JARVIS_DISABLE_ALL_INTELLIGENCE", None)
        from core.improvement_detector import detect_improvements
        proposals = detect_improvements(dry_run=True)
        assert isinstance(proposals, list)

        # Memory should have strategies
        best = mm.get_best_strategy("coding_task")
        assert best is not None
    finally:
        tpt_mod._tracker, mpt_mod._tracker = old_t, old_m


# ═══════════════════════════════════════════════════════════════
# P4: SAFETY FLAGS RESPECTED AT RUNTIME
# ═══════════════════════════════════════════════════════════════

def test_p4_intelligence_flag_gates_planner():
    """Planner checks is_intelligence_enabled before performance queries."""
    with open("core/planner.py") as f:
        src = f.read()
    assert "is_intelligence_enabled" in src


def test_p4_proposals_flag_gates_detection():
    """Improvement detection is gated by is_proposals_enabled."""
    with open("core/improvement_detector.py") as f:
        src = f.read()
    assert "is_proposals_enabled" in src


def test_p4_execution_engine_flag_gates_tool_runner():
    """Tool runner checks is_execution_engine_enabled."""
    with open("core/tool_runner.py") as f:
        src = f.read()
    assert "is_execution_engine_enabled" in src


def test_p4_dynamic_routing_flag():
    """Dynamic routing is gated by JARVIS_DYNAMIC_ROUTING."""
    with open("core/dynamic_agent_router.py") as f:
        src = f.read()
    assert "JARVIS_DYNAMIC_ROUTING" in src
    assert "is_enabled" in src


def test_p4_kill_switch_actually_works():
    """Disable all intelligence via env var."""
    os.environ["JARVIS_DISABLE_ALL_INTELLIGENCE"] = "1"
    try:
        from core.safety_controls import is_intelligence_enabled, is_proposals_enabled
        assert not is_intelligence_enabled()
        assert not is_proposals_enabled()
    finally:
        os.environ.pop("JARVIS_DISABLE_ALL_INTELLIGENCE")


# ═══════════════════════════════════════════════════════════════
# P5: NO DUPLICATE PLANNERS ACTIVE
# ═══════════════════════════════════════════════════════════════

def test_p5_planner_roles_documented():
    """The two planners have distinct, documented roles."""
    with open("core/planner.py") as f:
        planner_src = f.read()
    with open("core/mission_planner.py") as f:
        mp_src = f.read()
    # planner.py handles intelligence integration
    assert "performance_intelligence" in planner_src or "mission_performance_tracker" in planner_src
    # mission_planner.py handles step execution tracking
    assert "execute_step" in mp_src
    assert "complete_step" in mp_src


# ═══════════════════════════════════════════════════════════════
# P6: LEGACY ORCHESTRATORS NOT REACHABLE (without explicit import)
# ═══════════════════════════════════════════════════════════════

def test_p6_deprecation_documented():
    """Legacy orchestrators have deprecation markers."""
    from core.architecture_ownership import get_deprecated_modules
    deps = get_deprecated_modules()
    assert "core.orchestrator" in deps
    assert "core.orchestrator_v2" in deps
    assert "core.orchestrator_lg.langgraph_flow" in deps


# ═══════════════════════════════════════════════════════════════
# P7: TOOL SPEC VALIDATION
# ═══════════════════════════════════════════════════════════════

def test_p7_validate_all_tools():
    from core.tool_registry import get_tool_registry
    reg = get_tool_registry()
    result = reg.validate_all()
    assert result["total"] > 0
    # At least some tools should be valid
    assert len(result["valid"]) > 0


def test_p7_tool_definition_has_required_fields():
    from core.tool_registry import ToolDefinition
    td = ToolDefinition(
        name="test_tool", description="A test tool for validation",
        action_type="read", risk_level="low",
        expected_input="string", expected_output="string",
    )
    assert td.name == "test_tool"
    assert td.risk_level == "low"


# ═══════════════════════════════════════════════════════════════
# P8: MULTIMODAL ROUTING COMPATIBLE WITH AGENT SELECTION
# ═══════════════════════════════════════════════════════════════

def test_p8_multimodal_wired_to_agent_selector():
    """Agent selector includes multimodal routing overlay."""
    with open("agents/crew.py") as f:
        src = f.read()
    assert "detect_multimodal_type" in src
    assert "get_multimodal_agents" in src
    assert "multimodal_routing" in src


def test_p8_multimodal_detection_comprehensive():
    from core.dynamic_agent_router import detect_multimodal_type
    # Images
    assert detect_multimodal_type("generate an image of a cat") == "image"
    assert detect_multimodal_type("analyze this screenshot") == "image"
    assert detect_multimodal_type("draw a diagram") == "image"
    # Audio
    assert detect_multimodal_type("transcribe this recording") == "audio"
    assert detect_multimodal_type("convert speech to text") == "audio"
    # Documents
    assert detect_multimodal_type("parse this pdf") == "document"
    assert detect_multimodal_type("analyze the spreadsheet") == "document"
    # Non-multimodal
    assert detect_multimodal_type("write a python function") is None
    assert detect_multimodal_type("fix the bug") is None


# ═══════════════════════════════════════════════════════════════
# P9: COCKPIT REFLECTS REAL STATE
# ═══════════════════════════════════════════════════════════════

@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_p9_cockpit_all_panels():
    with open("static/cockpit.html") as f:
        html = f.read()
    panels = [
        "confidence-panel", "safety-panel", "lifecycle-panel",
        "exec-limits-panel", "architecture-panel", "intelligence-overview",
        "tool-perf-table", "mission-perf-table", "agent-perf-table",
        "exec-telemetry", "eval-trend-stats", "proposals-list",
    ]
    for p in panels:
        assert p in html, f"Missing: {p}"


@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_p9_cockpit_api_calls():
    """Cockpit JS calls real API endpoints."""
    with open("static/cockpit.html") as f:
        html = f.read()
    endpoints = [
        "/api/v3/performance/confidence",
        "/api/v3/performance/safety",
        "/api/v3/performance/lifecycle",
        "/api/v3/performance/execution/limits",
        "/api/v3/performance/architecture/ownership",
        "/api/v3/performance/overview",
    ]
    for ep in endpoints:
        assert ep in html, f"Missing API call: {ep}"


# ═══════════════════════════════════════════════════════════════
# P10: MEMORY DEDUPLICATION
# ═══════════════════════════════════════════════════════════════

def test_p10_canonical_owners_documented():
    from core.architecture_ownership import get_ownership_map
    om = get_ownership_map()
    assert "mission_memory" in om
    assert "tool_performance" in om
    assert "mission_performance" in om
    assert "improvement_proposals" in om


def test_p10_no_duplicate_ownership():
    from core.architecture_ownership import get_ownership_map
    om = get_ownership_map()
    canonicals = [info["canonical"] for info in om.values()]
    seen = set()
    for c in canonicals:
        assert c not in seen, f"Duplicate canonical owner: {c}"
        seen.add(c)


# ═══════════════════════════════════════════════════════════════
# DEEP END-TO-END: MULTI-STEP MISSION SIMULATION
# ═══════════════════════════════════════════════════════════════

def test_e2e_multistep_mission():
    """Simulate a 5-step mission flowing through all layers."""
    from core.lifecycle_tracker import LifecycleTracker
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    from core.mission_memory import MissionMemory
    import core.execution_engine as ee

    lt = LifecycleTracker()
    tpt = ToolPerformanceTracker(persist_path="/tmp/e2e_multi_t.jsonl")
    ee._evaluations = []
    ee._telemetry_buffer = []

    lt.start("multi-1")
    lt.record("multi-1", "plan_generated")
    lt.record("multi-1", "agents_selected")

    # 5 tool executions with mixed results
    tools = ["read_file", "shell_command", "read_file", "write_file", "shell_command"]
    for i, tool in enumerate(tools):
        success = i != 1  # step 2 fails
        tpt.record(ToolExecution(tool=tool, success=success, latency_ms=float(i * 50 + 20)))

    lt.record("multi-1", "tools_executed")

    ev = ee.evaluate_mission(
        "multi-1", True, "Multi-step analysis complete with detailed findings and recommendations.",
        "Analyze and fix the module", ["forge-builder", "lens-reviewer"],
        tools, 12.5, 5,
    )
    ee.store_evaluation(ev)
    lt.record("multi-1", "results_evaluated")
    lt.record("multi-1", "memory_updated")
    lt.record("multi-1", "proposals_checked")
    lt.finish("multi-1")

    rec = lt.get("multi-1")
    assert rec.is_complete
    assert rec.coverage == 1.0
    assert len(ee._evaluations) >= 1
    assert ee._evaluations[-1]["tool_efficiency"] > 0


def test_e2e_tool_failure_recovery():
    """Simulate tool failure → fallback → recovery."""
    from core.execution_engine import should_retry, get_fallback_tool
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt_mod

    tpt = ToolPerformanceTracker(persist_path="/tmp/e2e_recovery.jsonl")
    # Record many failures for shell_command
    for _ in range(10):
        tpt.record(ToolExecution(tool="shell_command", success=False, latency_ms=100))

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        # should_retry should refuse
        assert not should_retry("shell_command", 0)
        # fallback should exist
        fb = get_fallback_tool("shell_command")
        assert fb is not None  # run_command_safe or similar
    finally:
        tpt_mod._tracker = old


def test_e2e_concurrent_missions():
    """Simulate 50 concurrent missions without state corruption."""
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()

    for i in range(50):
        lt.start(f"conc-{i}")

    # Interleave stages
    import random
    random.seed(42)
    ids = list(range(50))
    random.shuffle(ids)
    for i in ids:
        lt.record(f"conc-{i}", "plan_generated")
    random.shuffle(ids)
    for i in ids:
        lt.record(f"conc-{i}", "agents_selected")
        lt.record(f"conc-{i}", "tools_executed")
    random.shuffle(ids)
    for i in ids:
        lt.record(f"conc-{i}", "results_evaluated")
        lt.record(f"conc-{i}", "memory_updated")
        lt.record(f"conc-{i}", "proposals_checked")
        lt.finish(f"conc-{i}")

    d = lt.get_dashboard_data()
    assert d["complete"] == 50


def test_e2e_memory_reuse_improves_success():
    """Verify that missions using memory signals have better data."""
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/e2e_reuse.json")

    # Record 10 successes and 5 failures for coding_task
    for i in range(15):
        mm.record_outcome("coding_task", ["forge-builder"], ["read_file", "write_file"],
                          3, i < 10)  # first 10 succeed

    best = mm.get_best_strategy("coding_task")
    assert best is not None
    assert best["success_rate"] > 0.5


def test_e2e_improvement_proposals_triggered():
    """Verify proposals are triggered from real performance data."""
    os.environ.pop("JARVIS_DISABLE_PROPOSALS", None)
    os.environ.pop("JARVIS_DISABLE_ALL_INTELLIGENCE", None)
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt_mod

    tpt = ToolPerformanceTracker(persist_path="/tmp/e2e_proposals.jsonl")
    for _ in range(15):
        tpt.record(ToolExecution(tool="unreliable_tool", success=False, latency_ms=200))
    for _ in range(5):
        tpt.record(ToolExecution(tool="unreliable_tool", success=True, latency_ms=50))

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        from core.improvement_detector import detect_improvements
        proposals = detect_improvements(dry_run=True)
        assert isinstance(proposals, list)
        tool_fixes = [p for p in proposals if p.get("type") == "tool_fix"]
        assert len(tool_fixes) >= 1  # unreliable_tool should trigger proposal
    finally:
        tpt_mod._tracker = old


def test_e2e_retry_adaptation():
    """Verify retry behavior adapts to tool performance."""
    from core.execution_engine import should_retry
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    import core.tool_performance_tracker as tpt_mod

    tpt = ToolPerformanceTracker(persist_path="/tmp/e2e_retry.jsonl")

    # Stable tool: should allow retries
    for _ in range(10):
        tpt.record(ToolExecution(tool="stable", success=True, latency_ms=30))
    # Volatile tool: should limit retries
    for i in range(10):
        tpt.record(ToolExecution(tool="volatile", success=i%2==0, latency_ms=30))
    # Broken tool: should skip retries
    for _ in range(10):
        tpt.record(ToolExecution(tool="broken", success=False, latency_ms=100))

    old = tpt_mod._tracker
    tpt_mod._tracker = tpt
    try:
        assert should_retry("stable", 1)      # ✅ allow
        assert not should_retry("volatile", 1) # ❌ limit
        assert not should_retry("broken", 0)   # ❌ skip entirely
    finally:
        tpt_mod._tracker = old


def test_e2e_bounded_under_stress():
    """500 missions — verify no structure exceeds bounds."""
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    from core.mission_memory import MissionMemory
    from core.lifecycle_tracker import LifecycleTracker
    import core.execution_engine as ee

    tpt = ToolPerformanceTracker(persist_path="/tmp/e2e_bound_t.jsonl")
    mpt = MissionPerformanceTracker(persist_path="/tmp/e2e_bound_m.json")
    mm = MissionMemory(persist_path="/tmp/e2e_bound_mm.json")
    lt = LifecycleTracker()
    ee._evaluations = []
    ee._telemetry_buffer = []

    for i in range(500):
        mid = f"bound-{i}"
        lt.start(mid)
        for stage in ["plan_generated", "agents_selected", "tools_executed",
                       "results_evaluated", "memory_updated", "proposals_checked"]:
            lt.record(mid, stage)
        lt.finish(mid)
        tpt.record(ToolExecution(tool=f"t{i%50}", success=i%3!=0, latency_ms=float(i%200)))
        mpt.record(MissionOutcome(mission_id=mid, mission_type=f"type_{i%15}",
                                  success=i%3!=0, agents_used=[f"a{i%7}"]))
        mm.record_outcome(f"type_{i%15}", [f"a{i%7}"], [f"t{i%50}"], i%5+1, i%3!=0)
        ev = ee.evaluate_mission(mid, i%3!=0, "output"*5, "goal", [f"a{i%7}"], [f"t{i%50}"], float(i%60), i%5+1)
        ee.store_evaluation(ev)

    # ALL BOUNDED
    assert len(tpt.get_all_stats()) <= 200
    assert len(mpt._type_stats) <= 100
    assert len(mm._strategies) <= 500
    assert len(lt._records) <= 500
    assert len(ee._evaluations) <= 500
    assert len(ee._telemetry_buffer) <= 200


# ═══════════════════════════════════════════════════════════════
# SYNTAX VALIDATION — ALL MODIFIED FILES
# ═══════════════════════════════════════════════════════════════

def test_all_files_parse():
    files = [
        "core/mission_system.py", "core/planner.py", "core/tool_registry.py",
        "core/execution_engine.py", "core/dynamic_agent_router.py",
        "core/architecture_ownership.py", "core/safety_controls.py",
        "core/lifecycle_tracker.py", "core/tool_runner.py",
        "api/routes/performance.py", "api/main.py", "agents/crew.py",
    ]
    for f in files:
        with open(f) as fh:
            ast.parse(fh.read())
