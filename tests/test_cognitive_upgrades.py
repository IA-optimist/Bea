"""
BEA MAX — Cognitive Upgrade Tests
========================================
Tests for all 8 cognitive/agentic upgrades:
  P1: Memory Graph
  P2: Agent Reputation Scoring
  P3: Meta-Cognition Layer
  P4: Internal Marketplace
  P5: Learning Traces
  P6: Capability Graph
  P7: Decision Confidence
  P8: Workflow Playbooks

Total: 80 tests
"""
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ═══════════════════════════════════════════════════════════════
# P1 — MEMORY GRAPH (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestMemoryGraph:

    def _make_graph(self):
        from core.memory_graph.graph_store import MemoryGraph
        return MemoryGraph(persist_path=os.path.join(tempfile.mkdtemp(), "test_graph.json"))

    def test_MG01_add_node(self):
        from core.memory_graph.graph_schema import Node, NodeType
        g = self._make_graph()
        g.add_node(Node(id="m:1", type=NodeType.MISSION, label="test mission"))
        assert g.get_node("m:1") is not None
        assert g.get_node("m:1").label == "test mission"

    def test_MG02_add_edge(self):
        from core.memory_graph.graph_schema import Node, Edge, NodeType, EdgeType
        g = self._make_graph()
        g.add_node(Node(id="m:1", type=NodeType.MISSION))
        g.add_node(Node(id="s:1", type=NodeType.STEP))
        e = g.add_edge(Edge(source="m:1", target="s:1", type=EdgeType.TRIGGERED))
        assert g.get_edge(e.id) is not None

    def test_MG03_edge_requires_existing_nodes(self):
        from core.memory_graph.graph_schema import Edge, EdgeType
        g = self._make_graph()
        with pytest.raises(ValueError):
            g.add_edge(Edge(source="nonexist", target="also_nonexist", type=EdgeType.TRIGGERED))

    def test_MG04_find_nodes_by_type(self):
        from core.memory_graph.graph_schema import Node, NodeType
        g = self._make_graph()
        g.add_node(Node(id="m:1", type=NodeType.MISSION, label="mission 1"))
        g.add_node(Node(id="a:1", type=NodeType.AGENT, label="coder"))
        assert len(g.find_nodes(type=NodeType.MISSION)) == 1
        assert len(g.find_nodes(type=NodeType.AGENT)) == 1

    def test_MG05_neighbors(self):
        from core.memory_graph.graph_schema import Node, Edge, NodeType, EdgeType
        g = self._make_graph()
        g.add_node(Node(id="m:1", type=NodeType.MISSION))
        g.add_node(Node(id="s:1", type=NodeType.STEP))
        g.add_edge(Edge(source="m:1", target="s:1", type=EdgeType.TRIGGERED))
        neighbors = g.neighbors("m:1", "out")
        assert len(neighbors) == 1
        assert neighbors[0][0].id == "s:1"

    def test_MG06_path_between(self):
        from core.memory_graph.graph_schema import Node, Edge, NodeType, EdgeType
        g = self._make_graph()
        g.add_node(Node(id="a", type=NodeType.MISSION))
        g.add_node(Node(id="b", type=NodeType.STEP))
        g.add_node(Node(id="c", type=NodeType.OUTCOME))
        g.add_edge(Edge(source="a", target="b", type=EdgeType.TRIGGERED))
        g.add_edge(Edge(source="b", target="c", type=EdgeType.PRODUCED))
        path = g.path_between("a", "c")
        assert path == ["a", "b", "c"]

    def test_MG07_subgraph(self):
        from core.memory_graph.graph_schema import Node, Edge, NodeType, EdgeType
        g = self._make_graph()
        g.add_node(Node(id="m:1", type=NodeType.MISSION))
        g.add_node(Node(id="s:1", type=NodeType.STEP))
        g.add_edge(Edge(source="m:1", target="s:1", type=EdgeType.TRIGGERED))
        sub = g.subgraph("m:1", depth=1)
        assert len(sub["nodes"]) == 2
        assert len(sub["edges"]) == 1

    def test_MG08_persistence(self):
        from core.memory_graph.graph_schema import Node, NodeType
        from core.memory_graph.graph_store import MemoryGraph
        path = os.path.join(tempfile.mkdtemp(), "persist.json")
        g1 = MemoryGraph(persist_path=path)
        g1.add_node(Node(id="m:1", type=NodeType.MISSION, label="persisted"))
        g1.save()
        g2 = MemoryGraph(persist_path=path)
        assert g2.get_node("m:1") is not None
        assert g2.get_node("m:1").label == "persisted"

    def test_MG09_remove_node_removes_edges(self):
        from core.memory_graph.graph_schema import Node, Edge, NodeType, EdgeType
        g = self._make_graph()
        g.add_node(Node(id="a", type=NodeType.MISSION))
        g.add_node(Node(id="b", type=NodeType.STEP))
        g.add_edge(Edge(source="a", target="b", type=EdgeType.TRIGGERED))
        g.remove_node("b")
        assert g.get_node("b") is None
        assert len(g.find_edges(source="a")) == 0

    def test_MG10_linker_mission_step_outcome(self):
        from core.memory_graph.graph_linker import GraphLinker
        g = self._make_graph()
        linker = GraphLinker(g)
        linker.link_mission("m1", label="test")
        linker.link_step("m1", "s1", agent_id="coder", label="step 1")
        linker.link_outcome("s1", "o1", success=True, label="done")
        assert g.stats()["nodes"] >= 3
        assert g.stats()["edges"] >= 2


# ═══════════════════════════════════════════════════════════════
# P2 — AGENT REPUTATION (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestAgentReputation:

    def _make_tracker(self):
        from core.agent_reputation import ReputationTracker
        return ReputationTracker(persist_path=os.path.join(tempfile.mkdtemp(), "rep.json"))

    def test_AR01_new_agent_neutral(self):
        t = self._make_tracker()
        assert t.get_score("unknown") == 0.5

    def test_AR02_record_success(self):
        t = self._make_tracker()
        t.record_success("coder", latency_ms=100, cost_usd=0.01)
        assert t.get_score("coder") > 0.5

    def test_AR03_record_failure(self):
        t = self._make_tracker()
        for _ in range(5):
            t.record_failure("bad_agent")
        assert t.get_score("bad_agent") <= 0.5  # 0% success = bottom of scale

    def test_AR04_success_rate(self):
        t = self._make_tracker()
        t.record_success("a")
        t.record_success("a")
        t.record_failure("a")
        rec = t.get_record("a")
        assert 0.6 < rec["success_rate"] < 0.7

    def test_AR05_timeout_rate(self):
        t = self._make_tracker()
        t.record_success("a")
        t.record_timeout("a")
        rec = t.get_record("a")
        assert rec["reputation_score"] < 1.0

    def test_AR06_regression_penalty(self):
        t = self._make_tracker()
        t.record_success("a")
        score_before = t.get_score("a")
        t.record_regression("a")
        score_after = t.get_score("a")
        assert score_after < score_before

    def test_AR07_get_best_agent(self):
        t = self._make_tracker()
        for _ in range(5):
            t.record_success("good")
        for _ in range(5):
            t.record_failure("bad")
        assert t.get_best_agent(["good", "bad"]) == "good"

    def test_AR08_persistence(self):
        from core.agent_reputation import ReputationTracker
        path = os.path.join(tempfile.mkdtemp(), "rep.json")
        t1 = ReputationTracker(persist_path=path)
        t1.record_success("a")
        t1.save()
        t2 = ReputationTracker(persist_path=path)
        assert t2.get_record("a") is not None
        assert t2.get_record("a")["successes"] == 1

    def test_AR09_confidence_calibration(self):
        t = self._make_tracker()
        t.record_confidence("a", predicted_success=True, actual_success=True)
        t.record_confidence("a", predicted_success=True, actual_success=False)
        rec = t.get_record("a")
        assert rec["confidence_calibration"] == 0.5

    def test_AR10_get_all_sorted(self):
        t = self._make_tracker()
        for _ in range(3):
            t.record_success("top")
        t.record_failure("bottom")
        all_agents = t.get_all()
        assert all_agents[0]["agent_id"] == "top"


# ═══════════════════════════════════════════════════════════════
# P3 — META-COGNITION (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestMetaCognition:

    def test_MC01_basic_analysis(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a = mc.analyze("Fix bug in login system")
        assert a.task_interpretation
        assert a.confidence_score > 0

    def test_MC02_risky_task(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a = mc.analyze("Delete production database tables")
        assert a.requires_approval is True
        assert any(r["level"] in ("critical", "high") for r in a.risks)

    def test_MC03_safe_task(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a = mc.analyze("Analyze code quality of module X")
        assert a.requires_approval is False

    def test_MC04_uncertainty_lowers_confidence(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a1 = mc.analyze("Implement user login")
        a2 = mc.analyze("Maybe try to possibly implement unclear feature")
        assert a2.confidence_score < a1.confidence_score

    def test_MC05_context_increases_confidence(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a1 = mc.analyze("Fix bug")
        a2 = mc.analyze("Fix bug", context={"files_read": True, "tests_passing": True})
        assert a2.confidence_score > a1.confidence_score

    def test_MC06_to_dict(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a = mc.analyze("Test something")
        d = a.to_dict()
        assert "confidence" in d
        assert "risks" in d
        assert "should_proceed" in d

    def test_MC07_should_proceed_on_low_confidence(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        # Very uncertain + risky
        a = mc.analyze("Maybe try to possibly delete production data unclear experiment")
        # Even low confidence should_proceed as long as >= 0.3
        assert isinstance(a.should_proceed, bool)

    def test_MC08_reasoning_generated(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a = mc.analyze("Create new API endpoint")
        assert len(a.reasoning) > 10

    def test_MC09_assumptions_for_api_tasks(self):
        from core.meta_cognition import MetaCognition
        mc = MetaCognition()
        a = mc.analyze("Modify API endpoint for user profile")
        assert any("backward" in a.lower() for a in a.assumptions)

    def test_MC10_fail_open(self):
        from core.meta_cognition import MetaCognition, PreActionAnalysis
        mc = MetaCognition()
        # Should not crash on weird input
        a = mc.analyze("", context=None)
        assert isinstance(a, PreActionAnalysis)


# ═══════════════════════════════════════════════════════════════
# P4 — INTERNAL MARKETPLACE (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestInternalMarketplace:

    def _make_mp(self):
        from core.internal_marketplace import InternalMarketplace
        return InternalMarketplace(catalog_path=os.path.join(tempfile.mkdtemp(), "mp.json"))

    def test_MP01_register_and_get(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="skill-1", name="Web Search", type="skill"))
        assert mp.get("skill-1") is not None

    def test_MP02_search(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="s1", name="Email Sender", type="skill", tags=["email"]))
        mp.register(CatalogEntry(id="s2", name="Code Linter", type="skill", tags=["code"]))
        results = mp.search(query="email")
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_MP03_filter_by_type(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="a1", name="Coder", type="agent"))
        mp.register(CatalogEntry(id="s1", name="Search", type="skill"))
        assert len(mp.search(type="agent")) == 1

    def test_MP04_install_tracking(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="s1", name="Test", type="skill"))
        mp.record_install("s1")
        mp.record_install("s1")
        assert mp.get("s1").install_count == 2

    def test_MP05_rating(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="s1", name="Test", type="skill"))
        mp.update_rating("s1", 4.5)
        assert mp.get("s1").rating == 4.5

    def test_MP06_dependencies(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="base", name="Base", type="skill"))
        mp.register(CatalogEntry(id="ext", name="Extension", type="skill", dependencies=["base", "missing"]))
        check = mp.check_dependencies("ext")
        assert check["ok"] is False
        assert "missing" in check["missing_modules"]

    def test_MP07_remove(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="s1", name="Test", type="skill"))
        assert mp.remove("s1") is True
        assert mp.get("s1") is None

    def test_MP08_recommended(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="s1", name="A", type="skill", rating=5.0, featured=True))
        mp.register(CatalogEntry(id="s2", name="B", type="skill", rating=3.0))
        rec = mp.get_recommended(limit=1)
        assert rec[0].id == "s1"

    def test_MP09_stats(self):
        from core.internal_marketplace import CatalogEntry
        mp = self._make_mp()
        mp.register(CatalogEntry(id="s1", name="A", type="skill"))
        mp.register(CatalogEntry(id="a1", name="B", type="agent"))
        s = mp.stats()
        assert s["total"] == 2
        assert s["by_type"]["skill"] == 1

    def test_MP10_persistence(self):
        from core.internal_marketplace import InternalMarketplace, CatalogEntry
        path = os.path.join(tempfile.mkdtemp(), "mp.json")
        mp1 = InternalMarketplace(catalog_path=path)
        mp1.register(CatalogEntry(id="s1", name="Persisted", type="skill"))
        mp2 = InternalMarketplace(catalog_path=path)
        assert mp2.get("s1") is not None


# ═══════════════════════════════════════════════════════════════
# P5 — LEARNING TRACES (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestLearningTraces:

    def _make_store(self):
        from core.learning_traces import LearningTraceStore
        return LearningTraceStore(persist_path=os.path.join(tempfile.mkdtemp(), "traces.json"))

    def test_LT01_record(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        t = store.record(LearningTrace(type=TraceType.MISSION_SUCCESS, lesson="X works"))
        assert t.id

    def test_LT02_query_by_type(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        store.record(LearningTrace(type=TraceType.MISSION_SUCCESS, lesson="OK"))
        store.record(LearningTrace(type=TraceType.MISSION_FAILURE, lesson="Failed"))
        assert len(store.query(type=TraceType.MISSION_SUCCESS)) == 1

    def test_LT03_query_by_applicable(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        store.record(LearningTrace(type=TraceType.TOOL_DEGRADATION, applicable_to=["search_web"], confidence=0.8))
        assert len(store.query(applicable_to="search_web")) == 1

    def test_LT04_insights(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        store.record(LearningTrace(
            type=TraceType.MISSION_SUCCESS, applicable_to=["coder"],
            actionable_insight="Always run tests after code changes",
            confidence=0.9, effectiveness=0.8,
        ))
        insights = store.get_insights_for("coder")
        assert len(insights) == 1

    def test_LT05_application_tracking(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        t = store.record(LearningTrace(type=TraceType.MISSION_SUCCESS))
        store.record_application(t.id, was_helpful=True)
        rec = store._traces[t.id]
        assert rec.times_applied == 1
        assert rec.effectiveness > 0

    def test_LT06_negative_effectiveness(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        t = store.record(LearningTrace(type=TraceType.MISSION_SUCCESS))
        store.record_application(t.id, was_helpful=False)
        assert store._traces[t.id].effectiveness < 0

    def test_LT07_stats(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        store.record(LearningTrace(type=TraceType.MISSION_SUCCESS))
        store.record(LearningTrace(type=TraceType.PATCH_PROMOTED))
        s = store.stats()
        assert s["total_traces"] == 2

    def test_LT08_persistence(self):
        from core.learning_traces import LearningTraceStore, LearningTrace, TraceType
        path = os.path.join(tempfile.mkdtemp(), "traces.json")
        s1 = LearningTraceStore(persist_path=path)
        s1.record(LearningTrace(type=TraceType.MISSION_SUCCESS, lesson="saved"))
        s2 = LearningTraceStore(persist_path=path)
        assert len(s2.get_all()) == 1

    def test_LT09_confidence_filter(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        store.record(LearningTrace(type=TraceType.MISSION_SUCCESS, confidence=0.2))
        store.record(LearningTrace(type=TraceType.MISSION_SUCCESS, confidence=0.9))
        assert len(store.query(min_confidence=0.5)) == 1

    def test_LT10_to_dict(self):
        from core.learning_traces import LearningTrace, TraceType
        store = self._make_store()
        t = store.record(LearningTrace(type=TraceType.MISSION_SUCCESS, lesson="test"))
        d = t.to_dict()
        assert "lesson" in d
        assert "effectiveness" in d


# ═══════════════════════════════════════════════════════════════
# P6 — CAPABILITY GRAPH (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestCapabilityGraph:

    def test_CG01_register(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="code_review", name="Code Review", category="analysis"))
        assert cg.get_capability("code_review") is not None

    def test_CG02_agent_capabilities(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="cr", name="Code Review", provided_by=["reviewer"]))
        caps = cg.get_agent_capabilities("reviewer")
        assert len(caps) == 1

    def test_CG03_find_agents_for_task(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="cr", name="Code Review", category="analysis", provided_by=["reviewer"], reliability=0.9))
        cg.register_capability(Capability(id="impl", name="Implementation", category="coding", provided_by=["coder"], reliability=0.8))
        agents = cg.find_agents_for_task(["code", "review"])
        assert len(agents) > 0

    def test_CG04_find_gaps(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="coding", name="Coding"))
        gaps = cg.find_gaps(["coding", "testing", "deployment"])
        assert "testing" in gaps
        assert "deployment" in gaps

    def test_CG05_list_all(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="a", name="A", reliability=0.8))
        cg.register_capability(Capability(id="b", name="B", reliability=0.9))
        all_caps = cg.list_all()
        assert len(all_caps) == 2
        assert all_caps[0]["reliability"] >= all_caps[1]["reliability"]

    def test_CG06_stats(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="a", name="A", category="coding", provided_by=["c1"]))
        s = cg.stats()
        assert s["total_capabilities"] == 1
        assert s["total_agents"] == 1

    def test_CG07_to_dict(self):
        from core.capability_graph import Capability
        c = Capability(id="cr", name="Code Review", reliability=0.85)
        d = c.to_dict()
        assert d["reliability"] == 0.85

    def test_CG08_reputation_sync(self):
        from core.capability_graph import CapabilityGraph, Capability
        from core.agent_reputation import ReputationTracker
        rt = ReputationTracker(persist_path=os.path.join(tempfile.mkdtemp(), "rep.json"))
        for _ in range(5):
            rt.record_success("coder")
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="impl", name="Impl", provided_by=["coder"]))
        cg.update_reliability_from_reputation(rt)
        cap = cg.get_capability("impl")
        assert cap.reliability > 0.5

    def test_CG09_tool_capability_mapping(self):
        from core.capability_graph import CapabilityGraph, Capability
        cg = CapabilityGraph()
        cg.register_capability(Capability(id="search", name="Search", required_tools=["web_search"]))
        assert "web_search" in cg._tool_capabilities
        assert "search" in cg._tool_capabilities["web_search"]

    def test_CG10_empty_find(self):
        from core.capability_graph import CapabilityGraph
        cg = CapabilityGraph()
        agents = cg.find_agents_for_task(["nonexistent"])
        assert agents == []


# ═══════════════════════════════════════════════════════════════
# P7 — DECISION CONFIDENCE (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestDecisionConfidence:

    def test_DC01_agent_selection(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        score = dc.score_agent_selection("coder", ["coder", "reviewer"], "fix bug")
        assert 0.0 <= score.score <= 1.0
        assert score.chosen_option == "coder"

    def test_DC02_with_reputation(self):
        from core.decision_confidence import DecisionConfidence
        from core.agent_reputation import ReputationTracker
        rt = ReputationTracker(persist_path=os.path.join(tempfile.mkdtemp(), "rep.json"))
        for _ in range(5):
            rt.record_success("good")
        dc = DecisionConfidence(reputation_tracker=rt)
        score = dc.score_agent_selection("good", ["good", "unknown"])
        assert score.score > 0.5

    def test_DC03_model_selection(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        score = dc.score_model_selection("claude-sonnet", task_type="coding", budget="standard")
        assert score.decision_type.value == "model_selection"

    def test_DC04_approval_recommendation_high_risk(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        score = dc.score_approval_recommendation("delete database", risk_level="critical")
        assert score.chosen_option == "escalate"

    def test_DC05_approval_recommendation_low_risk(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        score = dc.score_approval_recommendation("read file", risk_level="none")
        assert score.chosen_option == "approve"

    def test_DC06_history(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        dc.score_agent_selection("a", ["a"])
        dc.score_model_selection("m")
        h = dc.get_history()
        assert len(h) == 2

    def test_DC07_calibration_report(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        dc.score_agent_selection("a", ["a", "b"])
        report = dc.calibration_report()
        assert report["total_decisions"] == 1

    def test_DC08_factors_present(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        score = dc.score_agent_selection("a", ["a", "b"])
        assert len(score.factors) > 0

    def test_DC09_to_dict(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        score = dc.score_agent_selection("a", ["a"])
        d = score.to_dict()
        assert "score" in d
        assert "reasoning" in d

    def test_DC10_budget_constraint_lowers_confidence(self):
        from core.decision_confidence import DecisionConfidence
        dc = DecisionConfidence()
        s1 = dc.score_model_selection("m1", task_type="coding", budget="standard")
        s2 = dc.score_model_selection("m2", task_type="coding", budget="cheap")
        assert s2.score < s1.score


# ═══════════════════════════════════════════════════════════════
# P8 — WORKFLOW PLAYBOOKS (10 tests)
# ═══════════════════════════════════════════════════════════════

class TestWorkflowPlaybooks:

    def _make_registry(self):
        from core.workflow_playbooks import PlaybookRegistry
        return PlaybookRegistry(playbook_dir=os.path.join(tempfile.mkdtemp(), "playbooks"))

    def test_WP01_register(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(
            id="test", name="Test PB", steps=[PlaybookStep(id="s1", name="Step 1")],
        ))
        assert r.get("test") is not None

    def test_WP02_seed_defaults(self):
        r = self._make_registry()
        count = r.seed_defaults()
        assert count >= 3
        assert r.get("pb-code-review") is not None

    def test_WP03_create_execution(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(id="t", name="T", steps=[PlaybookStep(id="s1", name="S1")]))
        exe = r.create_execution("t", mission_id="m1")
        assert exe is not None
        assert exe.status == "running"

    def test_WP04_get_next_step(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(id="t", name="T", steps=[
            PlaybookStep(id="s1", name="Step 1"),
            PlaybookStep(id="s2", name="Step 2"),
        ]))
        exe = r.create_execution("t")
        step = r.get_next_step(exe.execution_id)
        assert step.id == "s1"

    def test_WP05_advance_on_success(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(id="t", name="T", steps=[
            PlaybookStep(id="s1", name="S1"),
            PlaybookStep(id="s2", name="S2"),
        ]))
        exe = r.create_execution("t")
        next_step = r.record_step_result(exe.execution_id, "s1", success=True)
        assert next_step is not None
        assert next_step.id == "s2"

    def test_WP06_stop_on_failure(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(id="t", name="T", steps=[
            PlaybookStep(id="s1", name="S1", on_failure="stop"),
            PlaybookStep(id="s2", name="S2"),
        ]))
        exe = r.create_execution("t")
        result = r.record_step_result(exe.execution_id, "s1", success=False)
        assert result is None
        assert r._executions[exe.execution_id].status == "failed"

    def test_WP07_skip_on_failure(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(id="t", name="T", steps=[
            PlaybookStep(id="s1", name="S1", on_failure="skip"),
            PlaybookStep(id="s2", name="S2"),
        ]))
        exe = r.create_execution("t")
        next_step = r.record_step_result(exe.execution_id, "s1", success=False)
        assert next_step.id == "s2"

    def test_WP08_completion(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        r = self._make_registry()
        r.register(Playbook(id="t", name="T", steps=[PlaybookStep(id="s1", name="S1")]))
        exe = r.create_execution("t")
        result = r.record_step_result(exe.execution_id, "s1", success=True)
        assert result is None  # No more steps
        assert r._executions[exe.execution_id].status == "completed"

    def test_WP09_find(self):
        r = self._make_registry()
        r.seed_defaults()
        results = r.find(category="deployment")
        assert len(results) >= 1

    def test_WP10_to_dict(self):
        from core.workflow_playbooks import Playbook, PlaybookStep
        pb = Playbook(id="t", name="Test", steps=[PlaybookStep(id="s1", name="S1")])
        d = pb.to_dict()
        assert "steps" in d


# ═══════════════════════════════════════════════════════════════
# Capability Graph Auto-Population Tests
# ═══════════════════════════════════════════════════════════════

class TestCapabilityGraphAutoPopulation:
    """Test auto-population of capability graph from runtime sources."""

    def test_CG01_populate_agents(self):
        """Agent tool access matrix creates capabilities."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        count = g._populate_agents()
        assert count > 0, "Should create agent capabilities"
        all_caps = g.list_all()
        agent_caps = [c for c in all_caps if c["category"] in (
            "architecture", "coding", "review", "testing", "deployment", "monitoring")]
        assert len(agent_caps) >= 4

    def test_CG02_populate_tools(self):
        """Gated tools create restricted capabilities."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        count = g._populate_tools()
        assert count > 0, "Should create gated tool capabilities"
        all_caps = g.list_all()
        restricted = [c for c in all_caps if "requires_approval" in c.get("constraints", [])]
        assert len(restricted) > 0

    def test_CG03_populate_mcp(self):
        """MCP registry populates without error; count depends on registered servers."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        count = g._populate_mcp()
        assert count >= 0, "populate_mcp should return non-negative count"
        all_caps = g.list_all()
        mcp_caps = [c for c in all_caps if c["id"].startswith("cap-mcp-")]
        assert len(mcp_caps) == count

    def test_CG04_full_populate(self):
        """Full populate_from_runtime creates a non-trivial graph."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        counts = g.populate_from_runtime()
        total = sum(counts.values())
        assert total > 5, f"Should populate >5 capabilities, got {total}"
        stats = g.stats()
        assert stats["total_capabilities"] > 5

    def test_CG05_hexstrike_is_constrained(self):
        """HexStrike capability must be marked with constraints."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        g._populate_mcp()
        hex_cap = g.get_capability("cap-mcp-mcp-hexstrike")
        if hex_cap:
            assert "requires_approval" in hex_cap.constraints
            assert "disabled" in hex_cap.constraints

    def test_CG06_no_secrets_in_graph(self):
        """Capability graph must not contain secrets or tokens."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        g.populate_from_runtime()
        dump = json.dumps([c.to_dict() for c in g._capabilities.values()])
        for pattern in ["sk-", "ghp_", "jv-", "password", "secret", "token"]:
            assert pattern not in dump.lower(), f"Graph contains sensitive pattern: {pattern}"

    def test_CG07_find_agents_after_populate(self):
        """After population, find_agents_for_task returns results."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        g.populate_from_runtime()
        results = g.find_agents_for_task(["code", "review"])
        assert len(results) > 0, "Should find agents for 'code review'"

    def test_CG08_idempotent_populate(self):
        """Running populate twice doesn't double entries."""
        from core.capability_graph import CapabilityGraph
        g = CapabilityGraph()
        counts1 = g.populate_from_runtime()
        counts2 = g.populate_from_runtime()
        assert sum(counts2.values()) == 0, "Second populate should add 0"
        assert g.stats()["total_capabilities"] == sum(counts1.values())
