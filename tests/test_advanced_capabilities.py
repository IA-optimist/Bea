"""
Tests for advanced capability integration:
- Dynamic agent routing
- Knowledge ingestion filter
- Enhanced improvement detection
- Planner intelligence wiring
- Cockpit updates
"""
import ast
import os
import sys
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
# DYNAMIC AGENT ROUTER
# ═══════════════════════════════════════════════════════════════

def test_router_disabled_by_default():
    """Router returns static candidates when flag is OFF."""
    os.environ.pop("BEA_DYNAMIC_ROUTING", None)
    from core.dynamic_agent_router import route_agents
    result = route_agents(
        goal="fix bug", mission_type="debug_task", complexity="medium",
        risk_level="LOW", static_candidates=["forge-builder", "lens-reviewer"],
    )
    assert result == ["forge-builder", "lens-reviewer"]


def test_router_enabled_no_data():
    """Router falls back to static when no performance data exists."""
    os.environ["BEA_DYNAMIC_ROUTING"] = "1"
    # Isolate from sibling tests (and any persisted workspace/*.jsonl) that
    # leave debug_task data in the performance tracker singleton. With leaked
    # data the router enters its rerank path (which iterates a set →
    # non-deterministic order); injecting a fresh empty tracker guarantees the
    # "no performance data" precondition this test actually asserts.
    import core.mission_performance_tracker as mpt_mod
    saved_tracker = mpt_mod._tracker
    mpt_mod._tracker = mpt_mod.MissionPerformanceTracker(
        persist_path="/tmp/test_router_no_data.json"
    )
    try:
        from core.dynamic_agent_router import route_agents
        result = route_agents(
            goal="fix bug", mission_type="debug_task", complexity="medium",
            risk_level="LOW", static_candidates=["forge-builder", "lens-reviewer"],
        )
        assert result == ["forge-builder", "lens-reviewer"]
    finally:
        os.environ.pop("BEA_DYNAMIC_ROUTING", None)
        mpt_mod._tracker = saved_tracker


def test_router_with_performance_data():
    """Router reranks agents based on real performance data."""
    os.environ["BEA_DYNAMIC_ROUTING"] = "1"
    try:
        from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
        import core.mission_performance_tracker as mpt_mod

        t = MissionPerformanceTracker(persist_path="/tmp/test_route.json")
        # forge-builder: 90% success on debug
        for i in range(10):
            t.record(MissionOutcome(
                mission_id=f"d{i}", mission_type="debug_task",
                success=i < 9, agents_used=["forge-builder"],
            ))
        # lens-reviewer: 40% success on debug
        for i in range(10):
            t.record(MissionOutcome(
                mission_id=f"r{i}", mission_type="debug_task",
                success=i < 4, agents_used=["lens-reviewer"],
            ))

        old = mpt_mod._tracker
        mpt_mod._tracker = t
        try:
            from core.dynamic_agent_router import route_agents
            result = route_agents(
                goal="fix crash", mission_type="debug_task", complexity="high",
                risk_level="LOW",
                static_candidates=["lens-reviewer", "forge-builder"],
            )
            # forge-builder should be ranked first (90% > 40%)
            assert result[0] == "forge-builder"
        finally:
            mpt_mod._tracker = old
    finally:
        os.environ.pop("BEA_DYNAMIC_ROUTING", None)


def test_router_complexity_cap():
    """Router respects complexity caps when data exists."""
    os.environ["BEA_DYNAMIC_ROUTING"] = "1"
    try:
        from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
        import core.mission_performance_tracker as mpt_mod

        t = MissionPerformanceTracker(persist_path="/tmp/test_cap.json")
        for i in range(8):
            t.record(MissionOutcome(
                mission_id=f"q{i}", mission_type="info_query",
                success=True, agents_used=["scout-research"],
            ))
        old = mpt_mod._tracker
        mpt_mod._tracker = t
        try:
            from core.dynamic_agent_router import route_agents
            result = route_agents(
                goal="quick check", mission_type="info_query", complexity="low",
                risk_level="LOW",
                static_candidates=["scout-research", "lens-reviewer", "map-planner"],
            )
            assert len(result) <= 1
        finally:
            mpt_mod._tracker = old
    finally:
        os.environ.pop("BEA_DYNAMIC_ROUTING", None)


def test_agent_specialization_map():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.mission_performance_tracker as mpt_mod
    t = MissionPerformanceTracker(persist_path="/tmp/test_spec.json")
    for i in range(8):
        t.record(MissionOutcome(
            mission_id=f"s{i}", mission_type="coding_task",
            success=True, agents_used=["forge-builder"],
        ))
    for i in range(4):
        t.record(MissionOutcome(
            mission_id=f"f{i}", mission_type="debug_task",
            success=i < 1, agents_used=["forge-builder"],
        ))
    old = mpt_mod._tracker
    mpt_mod._tracker = t
    try:
        from core.dynamic_agent_router import get_agent_specialization_map
        smap = get_agent_specialization_map()
        assert len(smap["agents"]) >= 1
        forge = [a for a in smap["agents"] if a["agent"] == "forge-builder"][0]
        assert forge["best_domain"] == "coding_task"
    finally:
        mpt_mod._tracker = old


def test_routing_explanation():
    from core.dynamic_agent_router import get_routing_explanation
    exp = get_routing_explanation("coding_task", "medium", ["forge-builder"])
    assert exp["mission_type"] == "coding_task"
    assert len(exp["agents"]) >= 1


# ═══════════════════════════════════════════════════════════════
# KNOWLEDGE INGESTION FILTER
# ═══════════════════════════════════════════════════════════════

def test_filter_trivial_queries():
    from core.knowledge_ingestion import should_ingest
    ok, reason = should_ingest("info_query", True, ["scout-research"], [], 1, "low")
    assert not ok
    assert reason == "trivial_query"


def test_filter_complex_success():
    from core.knowledge_ingestion import should_ingest
    ok, reason = should_ingest(
        "coding_task", True, ["forge-builder", "lens-reviewer"],
        ["write_file"], 5, "high",
    )
    assert ok
    assert "complex" in reason or "novel" in reason


def test_filter_uninformative_failure():
    from core.knowledge_ingestion import should_ingest
    ok, reason = should_ingest(
        "unknown", False, [], [], 0, "low",
    )
    assert not ok


def test_filter_informative_failure():
    from core.knowledge_ingestion import should_ingest, _recent_ingestions
    _recent_ingestions.clear()  # clear dedup state from prior tests
    ok, reason = should_ingest(
        "coding_task", False, ["forge-builder"], ["write_file"],
        3, "high", error_category="TimeoutError",
    )
    assert ok
    assert "failure" in reason


def test_filter_dedup():
    from core.knowledge_ingestion import should_ingest, _recent_ingestions
    _recent_ingestions.clear()
    # First: should ingest
    ok1, _ = should_ingest(
        "coding_task", True, ["forge-builder"], ["write_file"], 3, "medium",
    )
    # Second: same combo, should be deduped
    ok2, reason = should_ingest(
        "coding_task", True, ["forge-builder"], ["write_file"], 3, "medium",
    )
    assert ok1
    assert not ok2
    assert reason == "duplicate_within_24h"


# ═══════════════════════════════════════════════════════════════
# ENHANCED IMPROVEMENT DETECTOR
# ═══════════════════════════════════════════════════════════════

def test_detector_routing_optimization():
    from core.mission_performance_tracker import MissionPerformanceTracker, MissionOutcome
    import core.mission_performance_tracker as mpt_mod
    t = MissionPerformanceTracker(persist_path="/tmp/test_detect2.json")
    # Agent consistently fails on a domain
    for i in range(8):
        t.record(MissionOutcome(
            mission_id=f"x{i}", mission_type="system_task",
            success=i < 2, agents_used=["forge-builder"],
        ))
    # Better agent exists
    for i in range(5):
        t.record(MissionOutcome(
            mission_id=f"y{i}", mission_type="system_task",
            success=True, agents_used=["pulse-ops"],
        ))
    old = mpt_mod._tracker
    mpt_mod._tracker = t
    try:
        from core.improvement_detector import detect_improvements
        proposals = detect_improvements(dry_run=True)
        routing = [p for p in proposals if p["type"] == "routing_optimization"]
        assert len(routing) >= 1
        assert "pulse-ops" in routing[0]["description"] or "forge-builder" in routing[0]["title"]
    finally:
        mpt_mod._tracker = old


# ═══════════════════════════════════════════════════════════════
# WIRING VERIFICATION
# ═══════════════════════════════════════════════════════════════

def test_crew_has_dynamic_routing():
    """M1: AgentSelector + routing extracted to agents/selector.py.
    The combined surface still contains dynamic_agent_router."""
    chunks = []
    for rel in ("agents/crew.py", "agents/selector.py"):
        try:
            with open(rel, encoding="utf-8") as f:
                chunks.append(f.read())
        except FileNotFoundError:
            pass
    src = "\n".join(chunks)
    assert "dynamic_agent_router" in src
    assert "route_agents" in src
    # Syntax check on crew.py specifically (the file that still owns BaseAgent).
    with open("agents/crew.py", encoding="utf-8") as f:
        ast.parse(f.read())


def test_planner_has_knowledge_context():
    with open("core/planner.py", encoding="utf-8") as f:
        src = f.read()
    assert "knowledge_graph_context" in src
    assert "routing_intelligence" in src
    ast.parse(src)


def test_mission_system_has_knowledge_ingestion():
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "knowledge_ingestion" in src
    assert "ingest_mission_outcome" in src
    ast.parse(src)


def test_all_new_files_syntax():
    files = [
        "core/dynamic_agent_router.py",
        "core/knowledge_ingestion.py",
        "core/improvement_detector.py",
        "api/routes/performance.py",
    ]
    for f in files:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())


def test_cockpit_specialization_screen():
    """DEPRECATED: static/cockpit.html moved to frontend/ React app."""
    import pytest
    pytest.skip("UI moved to frontend/ — cockpit.html no longer in static/")


def test_performance_router_specialization_endpoints():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "agents/specialization" in src
    assert "routing/explain" in src
    ast.parse(src)
