"""
BEA MAX — Cognitive Integration Tests
=============================================
Tests for:
  - CognitiveBridge wiring (all 8 modules)
  - API routes (/api/v3/cognitive/*)
  - MetaCognition → orchestration trace integration
  - DecisionConfidence → approval request integration
  - LearningTraces → self-improvement scoring integration
  - Marketplace → modules catalog enhancement
  - End-to-end pre_mission → post_step → post_mission flow

Total: 50 tests
"""
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "test-hash")
os.environ.setdefault("BEAMAX_DATA_DIR", tempfile.mkdtemp())

import pytest


# ═══════════════════════════════════════════════════════════════
# COGNITIVE BRIDGE TESTS (20 tests)
# ═══════════════════════════════════════════════════════════════

class TestCognitiveBridge:

    def setup_method(self):
        os.environ["BEAMAX_DATA_DIR"] = tempfile.mkdtemp()
        from core.cognitive_bridge import CognitiveBridge
        CognitiveBridge.reset()

    def test_CB01_singleton(self):
        from core.cognitive_bridge import get_bridge
        b1 = get_bridge()
        b2 = get_bridge()
        assert b1 is b2

    def test_CB02_all_modules_init(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        s = b.stats()
        assert s["modules_available"] == 8

    def test_CB03_pre_mission_returns_analysis(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.pre_mission("Fix login bug in auth module", agent_id="coder")
        assert "meta_cognition" in result
        assert result["meta_cognition"]["confidence_score"] > 0

    def test_CB04_pre_mission_with_candidates(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.pre_mission("Fix bug", agent_id="coder", candidates=["coder", "reviewer"])
        assert "agent_confidence" in result

    def test_CB05_post_step_success(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        # Should not raise
        b.post_step("m1", "s1", "coder", success=True, latency_ms=100)
        rep = b.reputation
        assert rep.get_score("coder") > 0.5

    def test_CB06_post_step_failure(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        for i in range(5):
            b.post_step("m1", f"s{i}", "bad_agent", success=False, error="timeout")
        rep = b.reputation
        assert rep.get_score("bad_agent") <= 0.5

    def test_CB07_post_mission_creates_trace(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        b.post_mission("m1", "Fix login", success=True, agent_id="coder")
        lt = b.learning_traces
        all_traces = lt.get_all()
        assert len(all_traces) >= 1

    def test_CB08_post_mission_failure_trace(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        b.post_mission("m2", "Deploy", success=False, error="timeout", agent_id="devops")
        lt = b.learning_traces
        from core.learning_traces import TraceType
        failures = lt.query(type=TraceType.MISSION_FAILURE)
        assert len(failures) >= 1

    def test_CB09_score_decision_agent(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.score_decision("agent", "coder", ["coder", "reviewer"], context="coding task")
        assert "score" in result
        assert 0 <= result["score"] <= 1

    def test_CB10_score_decision_model(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.score_decision("model", "claude-sonnet", context="coding", budget="standard")
        assert "score" in result

    def test_CB11_score_decision_approval(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.score_decision("approval", "delete database", risk_level="critical")
        assert result.get("chosen_option") == "escalate"

    def test_CB12_find_playbook(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        results = b.find_playbook(category="deployment")
        assert len(results) >= 1

    def test_CB13_start_playbook(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.start_playbook("pb-code-review")
        assert result is not None
        assert result["status"] == "running"

    def test_CB14_marketplace_search(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        # Empty marketplace initially
        results = b.marketplace_search(query="email")
        assert isinstance(results, list)

    def test_CB15_stats_complete(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        s = b.stats()
        for key in ["memory_graph", "reputation", "meta_cognition", "marketplace",
                     "learning_traces", "capability_graph", "confidence", "playbooks"]:
            assert key in s

    def test_CB16_fail_open_on_module_error(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        # Even with bad input, should not crash
        result = b.pre_mission("")
        assert isinstance(result, dict)

    def test_CB17_full_lifecycle(self):
        """End-to-end: pre_mission → post_step → post_mission"""
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        # Pre
        pre = b.pre_mission("Test lifecycle", agent_id="coder", candidates=["coder"])
        assert "meta_cognition" in pre
        # Step
        b.post_step("life1", "s1", "coder", success=True, latency_ms=50)
        # Post
        b.post_mission("life1", "Test lifecycle", success=True, agent_id="coder",
                       lessons_learned=["Always test before commit"])
        # Verify reputation updated
        assert b.reputation.get_score("coder") > 0.5
        # Verify trace recorded
        assert len(b.learning_traces.get_all()) >= 1

    def test_CB18_reset_clears_singleton(self):
        from core.cognitive_bridge import CognitiveBridge, get_bridge
        b1 = get_bridge()
        CognitiveBridge.reset()
        b2 = get_bridge()
        assert b1 is not b2

    def test_CB19_direct_module_access(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        assert b.memory_graph is not None
        assert b.reputation is not None
        assert b.meta_cognition is not None
        assert b.marketplace is not None
        assert b.learning_traces is not None
        assert b.capability_graph is not None
        assert b.confidence is not None
        assert b.playbooks is not None

    def test_CB20_score_unknown_type(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.score_decision("unknown_type", "something")
        assert "score" in result
        assert result["reasoning"].startswith("unknown decision type")


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATION TRACE INTEGRATION (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestOrchestrationIntegration:

    def setup_method(self):
        os.environ["BEAMAX_DATA_DIR"] = tempfile.mkdtemp()
        from core.cognitive_bridge import CognitiveBridge
        CognitiveBridge.reset()

    def test_OI01_meta_cognition_for_risky_task(self):
        """MetaCognition should flag risky tasks."""
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.pre_mission("Delete production database and migrate")
        mc = result.get("meta_cognition", {})
        assert mc.get("requires_approval") is True

    def test_OI02_meta_cognition_for_safe_task(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        result = b.pre_mission("Read and analyze the codebase")
        mc = result.get("meta_cognition", {})
        assert mc.get("requires_approval") is False

    def test_OI03_confidence_affects_approval(self):
        """Low confidence on high-risk → escalate."""
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        score = b.score_decision("approval", "deploy to production", risk_level="high")
        assert score["chosen_option"] == "escalate"

    def test_OI04_confidence_allows_low_risk(self):
        """Low risk → approve."""
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        score = b.score_decision("approval", "read file", risk_level="none")
        assert score["chosen_option"] == "approve"

    def test_OI05_memory_graph_linked_after_mission(self):
        """Memory graph should have nodes after mission lifecycle."""
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        b.pre_mission("Graph test mission")
        b.post_step("graph1", "s1", "coder", success=True)
        g = b.memory_graph
        assert g.stats()["nodes"] > 0


# ═══════════════════════════════════════════════════════════════
# SELF-IMPROVEMENT SCORING INTEGRATION (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestSIIntegration:

    def setup_method(self):
        os.environ["BEAMAX_DATA_DIR"] = tempfile.mkdtemp()
        from core.cognitive_bridge import CognitiveBridge
        CognitiveBridge.reset()

    def test_SI01_traces_from_failed_mission(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        b.post_mission("m1", "Fix flaky test", success=False, error="timeout",
                       lessons_learned=["Increase test timeout"])
        from core.learning_traces import TraceType
        traces = b.learning_traces.query(type=TraceType.MISSION_FAILURE)
        assert len(traces) >= 1

    def test_SI02_traces_from_success_with_lessons(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        b.post_mission("m2", "Deploy v2", success=True,
                       lessons_learned=["Always run tests before deploy", "Check env vars"])
        traces = b.learning_traces.get_all()
        assert len(traces) >= 1
        # get_all() returns dicts
        lessons = [t.get("lesson", "") for t in traces]
        assert any("Always run tests" in l for l in lessons)

    def test_SI03_reputation_improves_with_success(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        for i in range(5):
            b.post_step("m1", f"s{i}", "reliable_agent", success=True)
        assert b.reputation.get_score("reliable_agent") > 0.5

    def test_SI04_reputation_degrades_with_failure(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        for i in range(5):
            b.post_step("m1", f"s{i}", "flaky_agent", success=False, error="crash")
        assert b.reputation.get_score("flaky_agent") <= 0.5

    def test_SI05_agent_selection_prefers_reputable(self):
        from core.cognitive_bridge import get_bridge
        b = get_bridge()
        for i in range(5):
            b.post_step("m1", f"s{i}", "star", success=True)
        b.post_step("m1", "sx", "mediocre", success=False)
        best = b.reputation.get_best_agent(["star", "mediocre"])
        assert best == "star"


# ═══════════════════════════════════════════════════════════════
# MARKETPLACE / CATALOG INTEGRATION (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestMarketplaceIntegration:

    def test_MI01_catalog_entry_has_marketplace_fields(self):
        from core.modules.module_manager import CatalogEntry
        entry = CatalogEntry(
            "test-1", "Test Agent", "agent",
            dependencies=["base-tools"],
            required_secrets=["OPENAI_API_KEY"],
            trust_level="verified",
            installable=True,
        )
        d = entry.to_dict()
        assert d["dependencies"] == ["base-tools"]
        assert d["required_secrets"] == ["OPENAI_API_KEY"]
        assert d["trust"] == "verified"
        assert d["installable"] is True

    def test_MI02_catalog_install_checks_deps(self):
        from core.modules.module_manager import ModuleManager, CatalogEntry
        mm = ModuleManager(data_dir=os.path.join(tempfile.mkdtemp(), "mods"))
        mm._catalog["dep-missing"] = CatalogEntry(
            "dep-missing", "Needs Dep", "agent",
            dependencies=["nonexistent-module"],
            blueprint={"name": "test"},
        )
        result = mm.install_from_catalog("dep-missing")
        assert result["success"] is False
        assert "Missing dependencies" in result["error"]

    def test_MI03_catalog_blocks_untrusted(self):
        from core.modules.module_manager import ModuleManager, CatalogEntry
        mm = ModuleManager(data_dir=os.path.join(tempfile.mkdtemp(), "mods"))
        mm._catalog["untrusted-1"] = CatalogEntry(
            "untrusted-1", "Suspicious", "agent",
            trust_level="untrusted",
            blueprint={"name": "test"},
        )
        result = mm.install_from_catalog("untrusted-1")
        assert result["success"] is False
        assert "untrusted" in result["error"]

    def test_MI04_install_increments_count(self):
        from core.modules.module_manager import ModuleManager, CatalogEntry
        mm = ModuleManager(data_dir=os.path.join(tempfile.mkdtemp(), "mods"))
        mm._catalog["safe-1"] = CatalogEntry(
            "safe-1", "Safe Agent", "agent",
            trust_level="internal",
            blueprint={"name": "Safe", "description": "A safe agent"},
        )
        result = mm.install_from_catalog("safe-1")
        assert result.get("success") is True
        assert mm._catalog["safe-1"].install_count == 1

    def test_MI05_catalog_to_dict_complete(self):
        from core.modules.module_manager import CatalogEntry
        entry = CatalogEntry(
            "full-1", "Full Entry", "skill",
            description="A skill",
            health_status="healthy",
            compatibility=["beamax>=1.0"],
            install_count=42,
        )
        d = entry.to_dict()
        assert d["health"] == "healthy"
        assert d["compatibility"] == ["beamax>=1.0"]
        assert d["install_count"] == 42


# ═══════════════════════════════════════════════════════════════
# API ROUTE TESTS (15 tests)
# ═══════════════════════════════════════════════════════════════

class TestCognitiveAPI:

    @pytest.fixture(autouse=True)
    def setup(self):
        os.environ["BEAMAX_DATA_DIR"] = tempfile.mkdtemp()
        from core.cognitive_bridge import CognitiveBridge
        CognitiveBridge.reset()

    def _get_client(self):
        from fastapi.testclient import TestClient
        from api.routes.cognitive import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_API01_stats_requires_auth(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/stats")
        assert resp.status_code == 401

    def test_API02_stats_ok(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/stats", headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "modules_available" in data

    def test_API03_analyze(self):
        c = self._get_client()
        resp = c.post("/api/v3/cognitive/analyze",
                       json={"goal": "Fix login bug", "agent_id": "coder"},
                       headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert "meta_cognition" in resp.json()

    def test_API04_score_agent(self):
        c = self._get_client()
        resp = c.post("/api/v3/cognitive/score",
                       json={"decision_type": "agent", "chosen": "coder",
                             "alternatives": ["coder", "reviewer"]},
                       headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert "score" in resp.json()

    def test_API05_reputation_leaderboard(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/reputation",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert "agents" in resp.json()

    def test_API06_reputation_single(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/reputation/coder",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200

    def test_API07_graph_stats(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/graph/stats",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200

    def test_API08_traces(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/traces",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert "traces" in resp.json()

    def test_API09_capabilities(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/capabilities",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200

    def test_API10_capabilities_find(self):
        c = self._get_client()
        resp = c.post("/api/v3/cognitive/capabilities/find",
                       json={"keywords": ["code", "review"]},
                       headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200

    def test_API11_playbooks_list(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/playbooks",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "playbooks" in data

    def test_API12_playbooks_start(self):
        c = self._get_client()
        resp = c.post("/api/v3/cognitive/playbooks/start",
                       json={"playbook_id": "pb-code-review"},
                       headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_API13_marketplace(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/marketplace",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_API14_confidence_report(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/confidence",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200

    def test_API15_confidence_history(self):
        c = self._get_client()
        resp = c.get("/api/v3/cognitive/confidence/history",
                      headers={"Authorization": "Bearer test"})
        assert resp.status_code == 200
        assert "decisions" in resp.json()
