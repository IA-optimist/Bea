"""
Tests for Batch 3: Mission memory, tool gap analysis, router registration, cockpit.
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
# MISSION MEMORY
# ═══════════════════════════════════════════════════════════════

def test_mission_memory_record_and_retrieve():
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/test_mm.json")
    mm.record_outcome("coding_task", ["forge-builder"], ["write_file"], 3, True, 10.0)
    mm.record_outcome("coding_task", ["forge-builder"], ["write_file"], 3, True, 8.0)
    mm.record_outcome("coding_task", ["forge-builder"], ["write_file"], 3, False, 15.0)
    strategy = mm.get_best_strategy("coding_task")
    assert strategy is not None
    assert strategy["success_rate"] > 0.5
    assert "forge-builder" in strategy["agents"]


def test_mission_memory_effective_sequences():
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/test_mm2.json")
    mm.record_outcome("debug_task", ["lens-reviewer"], ["check_logs", "read_file"], 2, True)
    mm.record_outcome("debug_task", ["lens-reviewer"], ["check_logs", "read_file"], 2, True)
    seqs = mm.get_effective_sequences("debug_task")
    assert len(seqs) >= 1
    assert seqs[0]["success"]
    assert seqs[0]["count"] >= 2


def test_mission_memory_failing_patterns():
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/test_mm3.json")
    for i in range(5):
        mm.record_outcome("system_task", ["pulse-ops"], ["test_endpoint"], 1, False)
    failing = mm.get_failing_patterns(min_failures=3)
    assert len(failing) >= 1
    assert failing[0]["success_rate"] < 0.1


def test_mission_memory_persist():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "mm.json")
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path=path)
    mm.record_outcome("test", ["a"], ["b"], 1, True)
    assert mm.save()
    mm2 = MissionMemory(persist_path=path)
    assert mm2.load()


def test_mission_memory_dashboard():
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/test_mm5.json")
    mm.record_outcome("coding_task", ["forge-builder"], ["write_file"], 3, True)
    d = mm.get_dashboard_data()
    assert "total_strategies" in d
    assert d["total_strategies"] >= 1


def test_mission_memory_strategy_confidence():
    from core.mission_memory import MissionMemory
    mm = MissionMemory(persist_path="/tmp/test_mm6.json")
    # 1 use: low confidence
    mm.record_outcome("t1", ["a"], ["b"], 1, True)
    s = mm.get_best_strategy("t1", min_confidence=0.0)
    assert s["confidence"] <= 0.5

    # 10 uses, all success: high confidence
    for i in range(9):
        mm.record_outcome("t1", ["a"], ["b"], 1, True)
    s = mm.get_best_strategy("t1")
    assert s["confidence"] > 0.8


# ═══════════════════════════════════════════════════════════════
# TOOL GAP ANALYZER
# ═══════════════════════════════════════════════════════════════

def test_tool_gap_analyzer_runs():
    from core.tool_gap_analyzer import analyze_tool_gaps
    gaps = analyze_tool_gaps()
    assert isinstance(gaps, list)


def test_tool_gap_unmet_needs():
    """Detects unmet needs when mission type has low success + few tools."""
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.mission_performance_tracker as mpt_mod

    t = MissionPerformanceTracker(persist_path="/tmp/test_gap.json")
    for i in range(5):
        t.record(MissionOutcome(
            mission_id=f"g{i}", mission_type="new_type",
            success=i < 1, tools_used=["read_file"],
        ))
    old = mpt_mod._tracker
    mpt_mod._tracker = t
    try:
        from core.tool_gap_analyzer import _detect_unmet_mission_needs
        gaps = _detect_unmet_mission_needs()
        unmet = [g for g in gaps if g["type"] == "unmet_need"]
        assert len(unmet) >= 1
        assert unmet[0]["mission_type"] == "new_type"
    finally:
        mpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# WIRING
# ═══════════════════════════════════════════════════════════════

def test_api_main_registers_routers():
    # After M1 refactor, routers are mounted via api/router_mount.py
    with open("api/router_mount.py", encoding="utf-8") as f:
        mount_src = f.read()
    assert "convergence_router" in mount_src
    assert "performance_router" in mount_src
    # cockpit is integrated inline (not a named router variable)
    with open("api/main.py", encoding="utf-8") as f:
        src = f.read()
    assert "cockpit" in src
    ast.parse(src)


def test_planner_has_mission_memory():
    with open("core/planner.py", encoding="utf-8") as f:
        src = f.read()
    assert "mission_memory" in src
    assert "proven_strategy" in src
    assert "effective_tool_sequences" in src
    assert "known_failing_patterns" in src
    ast.parse(src)


def test_mission_system_has_mission_memory():
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "mission_memory" in src
    assert "record_outcome" in src
    ast.parse(src)


@pytest.mark.stale
@pytest.mark.xfail(reason="static/cockpit.html removed", strict=False)
def test_cockpit_has_intelligence_overview():
    with open("static/cockpit.html", encoding="utf-8") as f:
        html = f.read()
    assert "intelligence-overview" in html
    assert "Strategy Memory" in html
    assert "Tool Intelligence" in html
    assert "/api/v3/performance/overview" in html


def test_performance_api_has_new_endpoints():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "tools/gaps" in src
    assert "memory/strategies" in src
    ast.parse(src)


def test_all_new_files_syntax():
    files = [
        "core/mission_memory.py",
        "core/tool_gap_analyzer.py",
        "api/routes/performance.py",
        "api/main.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
