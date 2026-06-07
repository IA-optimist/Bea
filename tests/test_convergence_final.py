"""
Final Convergence Tests
==========================
Layer-by-layer validation against target architecture.
"""
import pytest
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
# LAYER 1: META ORCHESTRATION
# ═══════════════════════════════════════════════════════════════

def test_single_active_orchestrator():
    """Only MissionSystem is the active API orchestrator."""
    with open("api/main.py", encoding="utf-8") as f:
        src = f.read()
    # MissionSystem is initialized
    assert "MissionSystem" in src or "mission_system" in src
    # MetaOrchestrator is NOT directly instantiated (only via bridge)
    lines_with_meta = [
        l.strip() for l in src.splitlines()
        if "MetaOrchestrator(" in l and "import" not in l and "#" not in l.lstrip()[:2]
    ]
    assert len(lines_with_meta) == 0, f"MetaOrchestrator directly instantiated in api/main.py: {lines_with_meta}"


@pytest.mark.skip(reason="stale: layout changed")
def test_legacy_orchestrators_deprecated():
    """Legacy orchestrators have deprecation markers."""
    for path in ["core/orchestrator.py", "core/orchestrator_v2.py"]:
        with open(path, encoding="utf-8") as f:
            first_line = f.readline()
        assert "DEPRECATED" in first_line.upper(), f"{path} missing DEPRECATED marker"


def test_deprecation_registry():
    from core.architecture_ownership import get_deprecated_modules
    deps = get_deprecated_modules()
    assert "core.orchestrator" in deps
    assert "core.orchestrator_v2" in deps
    for mod, info in deps.items():
        assert "replacement" in info
        assert "reason" in info


def test_mission_cancel():
    """MissionSystem supports mission cancellation."""
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "def cancel(" in src
    assert "cancelled" in src
    ast.parse(src)


def test_mission_cancel_logic():
    """Cancel transitions a mission to REJECTED."""
    from core.mission_system import MissionSystem
    ms = MissionSystem.__new__(MissionSystem)
    ms._missions = {}
    ms._db_conn = None
    ms._mission_goals = {}
    # Simulating — create a minimal mission record
    from core.mission_system import MissionResult, MissionStatus
    r = MissionResult.__new__(MissionResult)
    r.id = "test-cancel"
    r.status = MissionStatus.EXECUTING
    r.updated_at = time.time()
    r.decision_trace = {}
    r.user_input = "test"
    ms._missions["test-cancel"] = r
    ms._save_mission = lambda _r: None  # stub
    result = ms.cancel("test-cancel", reason="test cancellation")
    assert result is not None
    assert result.status == MissionStatus.REJECTED
    assert result.decision_trace.get("cancelled") is True


# ═══════════════════════════════════════════════════════════════
# LAYER 3: EXECUTION ENGINE
# ═══════════════════════════════════════════════════════════════

def test_execution_limits_configurable():
    from core.execution_engine import get_execution_limits
    limits = get_execution_limits()
    assert "max_tool_timeout_s" in limits
    assert "max_retries" in limits
    assert "max_mission_duration_s" in limits
    assert "max_mission_steps" in limits
    assert limits["max_tool_timeout_s"] > 0
    assert limits["max_retries"] > 0


def test_execution_limits_env_override():
    """Execution limits can be overridden via environment."""
    import importlib
    os.environ["BEA_MAX_RETRIES"] = "7"
    import core.execution_engine as ee
    importlib.reload(ee)
    assert ee.MAX_RETRIES == 7
    os.environ.pop("BEA_MAX_RETRIES")
    importlib.reload(ee)


# ═══════════════════════════════════════════════════════════════
# LAYER 5: MEMORY ARCHITECTURE
# ═══════════════════════════════════════════════════════════════

def test_memory_modules_bounded():
    """All memory modules have bounded storage."""
    from core.tool_performance_tracker import ToolPerformanceTracker
    from core.mission_performance_tracker import MissionPerformanceTracker
    from core.mission_memory import MissionMemory
    from core.lifecycle_tracker import LifecycleTracker

    # Verify MAX constants exist
    assert hasattr(ToolPerformanceTracker, 'MAX_TOOLS')
    assert hasattr(MissionPerformanceTracker, 'MAX_TYPES')
    assert hasattr(MissionMemory, 'MAX_STRATEGIES')
    assert hasattr(LifecycleTracker, 'MAX_RECORDS')


# ═══════════════════════════════════════════════════════════════
# LAYER 6: SELF IMPROVEMENT
# ═══════════════════════════════════════════════════════════════

def test_auto_detection_wired_to_lifecycle():
    """Improvement detection is triggered in mission complete()."""
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "detect_improvements" in src
    assert "is_proposals_enabled" in src


# ═══════════════════════════════════════════════════════════════
# LAYER 7: COCKPIT COMPLETENESS
# ═══════════════════════════════════════════════════════════════

@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_cockpit_all_12_panels():
    """Cockpit covers all target system views."""
    with open("static/cockpit.html", encoding="utf-8") as f:
        html = f.read()
    required = [
        "confidence-panel",
        "safety-panel",
        "lifecycle-panel",
        "exec-limits-panel",
        "architecture-panel",
        "intelligence-overview",
        "tool-perf-table",
        "mission-perf-table",
        "agent-perf-table",
        "exec-telemetry",
        "eval-trend-stats",
        "proposals-list",
    ]
    for panel in required:
        assert panel in html, f"Missing cockpit panel: {panel}"


# ═══════════════════════════════════════════════════════════════
# LAYER 8: SAFETY
# ═══════════════════════════════════════════════════════════════

def test_safety_controls_complete():
    from core.safety_controls import get_safety_state
    state = get_safety_state()
    assert hasattr(state, 'intelligence_enabled')
    assert hasattr(state, 'proposals_enabled')
    assert hasattr(state, 'execution_engine_enabled')


# ═══════════════════════════════════════════════════════════════
# LAYER 9: CAPABILITY EXPANSION
# ═══════════════════════════════════════════════════════════════

def test_tool_definition_spec():
    """ToolDefinition has required metadata fields."""
    from core.tool_registry import ToolDefinition
    td = ToolDefinition(
        name="test", description="test tool",
        action_type="read", risk_level="low",
        expected_input="str", expected_output="str",
    )
    assert hasattr(td, 'name')
    assert hasattr(td, 'description')
    assert hasattr(td, 'risk_level')
    assert hasattr(td, 'action_type')


# ═══════════════════════════════════════════════════════════════
# LAYER 10: MULTIMODAL
# ═══════════════════════════════════════════════════════════════

def test_multimodal_detection():
    from core.dynamic_agent_router import detect_multimodal_type, get_multimodal_agents
    assert detect_multimodal_type("Analyze this image") == "image"
    assert detect_multimodal_type("Transcribe this audio") == "audio"
    assert detect_multimodal_type("Parse this document") == "document"
    assert detect_multimodal_type("Write a function") is None

    agents = get_multimodal_agents("image")
    assert len(agents) >= 1
    assert "forge-builder" in agents or "scout-research" in agents


def test_multimodal_modules_exist():
    """Multimodal modules exist and parse cleanly."""
    for path in ["modules/multimodal/__init__.py", "modules/multimodal/image.py",
                  "modules/multimodal/voice.py", "modules/multimodal/video.py"]:
        with open(path, encoding="utf-8") as f:
            ast.parse(f.read())


# ═══════════════════════════════════════════════════════════════
# API COMPLETENESS
# ═══════════════════════════════════════════════════════════════

def test_api_cancel_endpoint():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "/missions/{mission_id}/cancel" in src
    assert "/execution/limits" in src
    assert "/architecture/ownership" in src


# ═══════════════════════════════════════════════════════════════
# FULL ARCHITECTURE SYNTAX CHECK
# ═══════════════════════════════════════════════════════════════

def test_all_modified_files_parse():
    files = [
        "core/mission_system.py",
        "core/execution_engine.py",
        "core/dynamic_agent_router.py",
        "core/architecture_ownership.py",
        "api/routes/performance.py",
        "core/safety_controls.py",
        "core/lifecycle_tracker.py",
        "core/tool_runner.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())


# ═══════════════════════════════════════════════════════════════
# STRESS: FULL SYSTEM CONVERGENCE
# ═══════════════════════════════════════════════════════════════

def test_stress_300_missions_full_flow():
    """300 missions through all 10 layers — no crash, all bounded."""
    from core.tool_performance_tracker import ToolPerformanceTracker, ToolExecution
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    from core.mission_memory import MissionMemory
    from core.lifecycle_tracker import LifecycleTracker
    import core.execution_engine as ee

    tpt = ToolPerformanceTracker(persist_path="/tmp/stress300_t.jsonl")
    mpt = MissionPerformanceTracker(persist_path="/tmp/stress300_m.json")
    mm = MissionMemory(persist_path="/tmp/stress300_mm.json")
    lt = LifecycleTracker()
    ee._evaluations = []
    ee._telemetry_buffer = []

    types = ["coding_task", "debug_task", "research_task", "system_task",
             "architecture_task", "evaluation_task", "info_query", "planning_task",
             "image_task", "audio_task"]
    agents = ["forge-builder", "scout-research", "shadow-advisor",
              "map-planner", "lens-reviewer", "vault-memory", "pulse-ops"]
    tools = ["read_file", "shell_command", "http_get", "vector_search",
             "write_file", "search_codebase", "run_command_safe"]

    for i in range(300):
        mid = f"conv-{i}"
        mtype = types[i % len(types)]
        agent = agents[i % len(agents)]
        tool = tools[i % len(tools)]
        success = i % 7 != 0

        lt.start(mid)
        lt.record(mid, "plan_generated")
        lt.record(mid, "agents_selected")
        tpt.record(ToolExecution(tool=tool, success=success, latency_ms=float(i % 500 + 10)))
        lt.record(mid, "tools_executed")
        ev = ee.evaluate_mission(mid, success, "output" * 5, "goal", [agent], [tool], float(i % 60), i % 5 + 1)
        ee.store_evaluation(ev)
        lt.record(mid, "results_evaluated")
        mpt.record(MissionOutcome(mission_id=mid, mission_type=mtype, success=success, agents_used=[agent], tools_used=[tool]))
        mm.record_outcome(mtype, [agent], [tool], i % 5 + 1, success)
        lt.record(mid, "memory_updated")
        lt.record(mid, "proposals_checked")
        lt.finish(mid)

    # Verify ALL bounded
    assert len(tpt.get_all_stats()) <= 200
    assert len(mpt._type_stats) <= 100
    assert len(mm._strategies) <= 500
    assert len(lt._records) <= 500
    assert len(ee._evaluations) <= 500
    assert len(ee._telemetry_buffer) <= 200

    # Verify completeness
    d = lt.get_dashboard_data()
    assert d["complete"] == 300
    assert d["complete_rate"] == 1.0

    # Verify all 10 mission types tracked
    assert len(mpt._type_stats) == 10


def test_stress_cancel_then_restart():
    """Cancelled missions don't corrupt lifecycle state."""
    from core.lifecycle_tracker import LifecycleTracker
    lt = LifecycleTracker()

    # Mission 1: normal flow
    lt.start("m1")
    lt.record("m1", "plan_generated")
    lt.record("m1", "agents_selected")
    lt.record("m1", "tools_executed")
    lt.record("m1", "results_evaluated")
    lt.record("m1", "memory_updated")
    lt.record("m1", "proposals_checked")
    lt.finish("m1")

    # Mission 2: cancelled mid-flight
    lt.start("m2")
    lt.record("m2", "plan_generated")
    lt.record_error("m2", "cancelled", "user_cancel")
    # Not finished — partial

    # Mission 3: normal after cancel
    lt.start("m3")
    lt.record("m3", "plan_generated")
    lt.record("m3", "agents_selected")
    lt.record("m3", "tools_executed")
    lt.record("m3", "results_evaluated")
    lt.record("m3", "memory_updated")
    lt.record("m3", "proposals_checked")
    lt.finish("m3")

    d = lt.get_dashboard_data()
    assert d["total"] == 3
    assert d["complete"] == 2
