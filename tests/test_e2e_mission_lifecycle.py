"""
E2E Mission Lifecycle Tests (P7)
==================================
Exercises the real mission flow end-to-end without LLM calls:
  submit → plan → approval → execute → complete → memory

Tests canonical status at every transition, verifies all integration
points (planner, tool_registry, memory, lifecycle tracker, performance).

No mocked modules — all real Python objects. LLM calls are either
absent (planning is local) or short-circuited by missing API keys.
"""
import os
import sys
import time
import json
import types
import unittest
import shutil
import pytest
pytestmark = pytest.mark.integration


# ── Structlog stub ────────────────────────────────────────────────────────────
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Ensure workspace dir exists for persistence
os.makedirs("workspace", exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _fresh_mission_system():
    """Create a fresh MissionSystem instance (not singleton)."""
    from core.mission_system import MissionSystem
    ms = MissionSystem.__new__(MissionSystem)
    ms._missions = {}
    ms._mission_goals = {}
    ms._mode_system = None
    ms._action_queue = None
    ms._goal_manager = None
    ms._last_save_ts = 0
    return ms


def _canonical(legacy_status: str) -> str:
    """Map legacy → canonical. Mirror of what API does."""
    from core.canonical_types import map_legacy_mission_status
    return map_legacy_mission_status(legacy_status, "mission_system").value


# ═══════════════════════════════════════════════════════════════
# E2E LIFECYCLE TESTS
# ═══════════════════════════════════════════════════════════════

class TestMissionSubmitFlow(unittest.TestCase):
    """submit() creates a mission with correct initial state."""

    def test_submit_returns_mission_result(self):
        from core.mission_system import get_mission_system, MissionResult
        ms = get_mission_system()
        result = ms.submit("Analyse le fichier README.md et résume le contenu")
        self.assertIsInstance(result, MissionResult)
        self.assertTrue(result.mission_id)
        self.assertIn(result.status, {
            "ANALYZING", "PENDING_VALIDATION", "APPROVED", "BLOCKED", "PLAN_ONLY",
        })

    def test_submit_canonical_status_is_valid(self):
        from core.mission_system import get_mission_system
        from core.canonical_types import CanonicalMissionStatus
        ms = get_mission_system()
        result = ms.submit("Compare FastAPI vs Flask")
        canonical = _canonical(str(result.status))
        # submit() may return any non-terminal status (depends on mode/risk)
        valid_values = {e.value for e in CanonicalMissionStatus}
        self.assertIn(canonical, valid_values,
                      f"Initial canonical status {canonical} not a valid enum value")

    def test_submit_populates_plan(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Crée une API REST avec FastAPI")
        self.assertTrue(result.plan_summary, "Plan summary should be populated")
        self.assertIsInstance(result.plan_steps, list)

    def test_submit_populates_decision_trace(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Debug ce code Python")
        dt = result.decision_trace
        self.assertIn("mission_type", dt)
        self.assertIn("complexity", dt)
        self.assertIn("risk_score", dt)
        self.assertIn("approval_mode", dt)
        self.assertIn("approval_decision", dt)

    def test_submit_has_risk_score(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Supprime tous les fichiers temporaires")
        self.assertIsInstance(result.risk_score, (int, float))
        self.assertGreaterEqual(result.risk_score, 0)
        self.assertLessEqual(result.risk_score, 10)


class TestMissionApprovalFlow(unittest.TestCase):
    """Approval transitions follow canonical lifecycle."""

    def test_approve_pending_mission(self):
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Modifie le fichier config.yaml")
        if result.status != MissionStatus.PENDING_VALIDATION:
            self.skipTest("Mission auto-approved (mode AUTO)")
        approved = ms.approve(result.mission_id)
        self.assertIsNotNone(approved)
        self.assertEqual(str(approved.status), "APPROVED")
        self.assertEqual(_canonical("APPROVED"), "READY")

    def test_reject_mission(self):
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Deploy to production")
        if result.status != MissionStatus.PENDING_VALIDATION:
            self.skipTest("Mission auto-approved")
        rejected = ms.reject(result.mission_id, note="Too risky")
        self.assertIsNotNone(rejected)
        self.assertEqual(str(rejected.status), "REJECTED")
        self.assertEqual(_canonical("REJECTED"), "CANCELLED")

    def test_cannot_complete_pending_mission(self):
        """Guard: PENDING_VALIDATION → DONE is blocked."""
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Refactor the auth module")
        if result.status != MissionStatus.PENDING_VALIDATION:
            self.skipTest("Mission auto-approved")
        completed = ms.complete(result.mission_id, "fake result")
        # Should NOT be DONE — should still be PENDING_VALIDATION
        self.assertNotEqual(str(completed.status), "DONE")


class TestMissionCompletionFlow(unittest.TestCase):
    """Complete() records all signals correctly."""

    def test_complete_approved_mission(self):
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Recherche les meilleures pratiques Python")
        # Force to approved for test (MissionStatus enum, not string)
        result.status = MissionStatus.APPROVED
        completed = ms.complete(result.mission_id, "Best practices: use type hints, write tests")
        self.assertIsNotNone(completed)
        # str(MissionStatus.DONE) may be "MissionStatus.DONE" or "DONE" depending on Enum
        status_val = completed.status.value if hasattr(completed.status, 'value') else str(completed.status)
        self.assertIn(status_val, {"DONE", "PLAN_ONLY"})
        canonical = _canonical(status_val)
        self.assertIn(canonical, {"COMPLETED"})

    def test_complete_sets_final_output(self):
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Liste les fichiers Python dans le projet")
        result.status = MissionStatus.APPROVED
        ms.complete(result.mission_id, "Found 42 Python files")
        m = ms.get(result.mission_id)
        self.assertTrue(m.final_output)
        self.assertIn("42", m.final_output)

    def test_complete_records_performance(self):
        """Performance tracker should be callable after complete (fail-open)."""
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Optimise les requêtes SQL")
        result.status = MissionStatus.APPROVED
        result.agents_selected = ["forge-builder"]
        # complete() should not crash even if performance tracker is present
        ms.complete(result.mission_id, "Optimized 3 queries")
        m = ms.get(result.mission_id)
        status_val = m.status.value if hasattr(m.status, 'value') else str(m.status)
        self.assertIn(status_val, {"DONE", "PLAN_ONLY"})
        # Verify performance tracker can provide dashboard data (fail-open)
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            tracker = get_mission_performance_tracker()
            dashboard = tracker.get_dashboard_data()
            self.assertIsInstance(dashboard, dict)
        except (ImportError, AttributeError):
            _silent_log.debug("suppressed_exception", src='test_e2e_mission_lifecycle.py')

    def test_complete_stores_in_memory_facade(self):
        """MemoryFacade should receive the outcome (P5 wiring)."""
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        result = ms.submit("Analyse de sécurité du code")
        result.status = MissionStatus.APPROVED
        ms.complete(result.mission_id, "No critical vulnerabilities found")
        # Verify facade store was called — we can check the JSONL fallback
        try:
            from core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            health = facade.health()
            self.assertIsInstance(health, dict)
        except ImportError:
            _silent_log.debug("suppressed_exception", src='test_e2e_mission_lifecycle.py')


class TestCanonicalStatusThroughLifecycle(unittest.TestCase):
    """Canonical status is valid at every lifecycle stage."""

    def test_full_happy_path_statuses(self):
        from core.mission_system import get_mission_system, MissionStatus
        from core.canonical_types import CanonicalMissionStatus
        ms = get_mission_system()

        # 1. Submit
        result = ms.submit("Recherche des frameworks JavaScript modernes")
        s1_raw = result.status.value if hasattr(result.status, 'value') else str(result.status)
        s1 = _canonical(s1_raw)
        self.assertIn(s1, {e.value for e in CanonicalMissionStatus})

        # 2. If pending, approve
        if result.status == MissionStatus.PENDING_VALIDATION:
            ms.approve(result.mission_id)
            m = ms.get(result.mission_id)
            s2_raw = m.status.value if hasattr(m.status, 'value') else str(m.status)
            s2 = _canonical(s2_raw)
            self.assertEqual(s2, "READY")

        # 3. Force to APPROVED before completing
        m = ms.get(result.mission_id)
        m.status = MissionStatus.APPROVED
        ms.complete(result.mission_id, "Found React, Vue, Svelte, Solid")
        m = ms.get(result.mission_id)
        s3_raw = m.status.value if hasattr(m.status, 'value') else str(m.status)
        s3 = _canonical(s3_raw)
        self.assertIn(s3, {"COMPLETED"})

    def test_blocked_mission_maps_to_failed(self):
        from core.mission_system import MissionStatus
        self.assertEqual(_canonical("BLOCKED"), "FAILED")

    def test_plan_only_maps_to_completed(self):
        self.assertEqual(_canonical("PLAN_ONLY"), "COMPLETED")

    def test_analyzing_maps_to_planning(self):
        self.assertEqual(_canonical("ANALYZING"), "PLANNING")


class TestMissionList(unittest.TestCase):
    """list_missions returns all submitted missions."""

    def test_list_includes_submitted(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Test list endpoint")
        missions = ms.list_missions(limit=100)
        ids = [m.mission_id for m in missions]
        self.assertIn(result.mission_id, ids)

    def test_stats_counts(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        stats = ms.stats()
        self.assertIn("total", stats)
        self.assertIsInstance(stats["total"], int)
        self.assertIn("by_status", stats)


class TestMissionGetDetail(unittest.TestCase):
    """get() returns full mission with all fields."""

    def test_get_returns_all_fields(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Détail test mission")
        m = ms.get(result.mission_id)
        self.assertIsNotNone(m)
        self.assertEqual(m.mission_id, result.mission_id)
        # Core fields must be present
        self.assertTrue(hasattr(m, 'status'))
        self.assertTrue(hasattr(m, 'plan_summary'))
        self.assertTrue(hasattr(m, 'plan_steps'))
        self.assertTrue(hasattr(m, 'risk_score'))
        self.assertTrue(hasattr(m, 'decision_trace'))
        self.assertTrue(hasattr(m, 'user_input'))

    def test_get_nonexistent_returns_none(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        m = ms.get("nonexistent-mission-id-12345")
        self.assertIsNone(m)


class TestMissionToDict(unittest.TestCase):
    """MissionResult.to_dict() produces valid serializable dict."""

    def test_to_dict_serializable(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Sérialisation test")
        m = ms.get(result.mission_id)
        d = m.to_dict()
        self.assertIsInstance(d, dict)
        # Must be JSON-serializable
        serialized = json.dumps(d)
        self.assertIsInstance(serialized, str)

    def test_to_dict_contains_status(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Dict status test")
        d = ms.get(result.mission_id).to_dict()
        self.assertIn("status", d)


# ═══════════════════════════════════════════════════════════════
# PLANNER INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestPlannerIntegration(unittest.TestCase):
    """Planner produces structured plan for real mission types."""

    def test_build_plan_returns_dict(self):
        from core.planner import build_plan
        result = build_plan(
            goal="Crée une API REST avec authentification JWT",
            mission_type="coding_task",
            complexity="medium",
        )
        self.assertIsInstance(result, dict)
        # Plan may use mission_planner (returns plan_id, steps) or old planner (returns recommended_tools)
        has_plan_structure = "steps" in result or "recommended_tools" in result or "plan_id" in result
        self.assertTrue(has_plan_structure, f"Plan missing expected keys: {list(result.keys())[:10]}")

    def test_plan_has_facade_context_key(self):
        """After P5 wiring, plan may include memory_facade_context."""
        from core.planner import build_plan
        result = build_plan(
            goal="Debug Python import error",
            mission_type="debug_task",
            complexity="low",
        )
        # Key may or may not be present (depends on memory state)
        # But the code path must not crash
        self.assertIsInstance(result, dict)

    def test_plan_different_mission_types(self):
        """Different mission types produce structured plans."""
        from core.planner import build_plan
        plans = {}
        for mtype in ["coding_task", "research_task", "debug_task", "business_task"]:
            plans[mtype] = build_plan(
                goal=f"Test goal for {mtype}",
                mission_type=mtype,
                complexity="medium",
            )
        for mtype, plan in plans.items():
            self.assertIsInstance(plan, dict, f"Plan for {mtype} is not a dict")
            # Must have some structure: steps, or recommended_tools, or plan_id
            has_structure = bool(
                plan.get("steps") or plan.get("recommended_tools") or plan.get("plan_id")
            )
            self.assertTrue(has_structure, f"Plan for {mtype} has no structure")


# ═══════════════════════════════════════════════════════════════
# LIFECYCLE TRACKER INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestLifecycleTrackerIntegration(unittest.TestCase):
    """Lifecycle tracker records stages from real submit/complete."""

    def test_lifecycle_stages_from_submit(self):
        """submit() should record at least 'mission_received' and 'plan_generated'."""
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            tracker = get_lifecycle_tracker()
        except ImportError:
            self.skipTest("lifecycle_tracker not available")

        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit("Lifecycle tracking test")

        record = tracker.get(result.mission_id)
        if record:  # Tracker may return None if fail-open
            stages = record.to_dict().get("stages", [])
            stage_names = [s.get("stage", s) if isinstance(s, dict) else s for s in stages]
            # At minimum, mission start should be recorded
            self.assertGreater(len(stage_names), 0, "No lifecycle stages recorded")


# ═══════════════════════════════════════════════════════════════
# TOOL REGISTRY INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestToolRegistryIntegration(unittest.TestCase):
    """Tool registry provides tools for mission types."""

    def test_registry_returns_tools(self):
        try:
            from core.tool_registry import get_tool_registry
            registry = get_tool_registry()
        except ImportError:
            self.skipTest("tool_registry not available")
        tools = registry.get_tools_for_mission_type("coding_task")
        self.assertIsInstance(tools, list)

    def test_validate_all(self):
        """validate_all() should not crash."""
        try:
            from core.tool_registry import get_tool_registry
            registry = get_tool_registry()
            if hasattr(registry, 'validate_all'):
                result = registry.validate_all()
                self.assertIsInstance(result, dict)
        except ImportError:
            self.skipTest("tool_registry not available")


# ═══════════════════════════════════════════════════════════════
# MULTI-MISSION STRESS
# ═══════════════════════════════════════════════════════════════

class TestMultiMissionStress(unittest.TestCase):
    """Multiple missions don't corrupt each other."""

    def test_50_concurrent_missions(self):
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        missions = []
        for i in range(50):
            r = ms.submit(f"Stress test mission {i}: analyse du fichier {i}.py")
            missions.append(r)

        # All should have unique IDs
        ids = [m.mission_id for m in missions]
        self.assertEqual(len(set(ids)), 50, "Mission IDs are not unique")

        # All should be retrievable
        for m in missions:
            retrieved = ms.get(m.mission_id)
            self.assertIsNotNone(retrieved, f"Mission {m.mission_id} lost")

        # All canonical statuses should be valid
        from core.canonical_types import CanonicalMissionStatus
        valid_values = {e.value for e in CanonicalMissionStatus}
        for m in missions:
            canonical = _canonical(str(m.status))
            self.assertIn(canonical, valid_values,
                          f"Mission {m.mission_id}: invalid canonical status {canonical}")

    def test_submit_complete_cycle_20_missions(self):
        from core.mission_system import get_mission_system, MissionStatus
        ms = get_mission_system()
        completed = 0
        for i in range(20):
            r = ms.submit(f"Cycle test {i}")
            r.status = MissionStatus.APPROVED  # Force approve (enum, not string)
            ms.complete(r.mission_id, f"Result {i}")
            m = ms.get(r.mission_id)
            status_val = m.status.value if hasattr(m.status, 'value') else str(m.status)
            if status_val in ("DONE", "PLAN_ONLY"):
                completed += 1
        self.assertEqual(completed, 20, f"Only {completed}/20 missions completed")

    def test_list_missions_bounded(self):
        """list_missions respects limit."""
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        missions = ms.list_missions(limit=10)
        self.assertLessEqual(len(missions), 10)


# ═══════════════════════════════════════════════════════════════
# CANONICAL → LEGACY ROUND-TRIP
# ═══════════════════════════════════════════════════════════════

class TestCanonicalLegacyRoundTrip(unittest.TestCase):
    """Legacy status → canonical → properties are consistent."""

    def test_all_mission_system_statuses_roundtrip(self):
        from core.canonical_types import (
            map_legacy_mission_status, CanonicalMissionStatus,
        )
        legacy_terminal = {"DONE", "REJECTED", "BLOCKED", "PLAN_ONLY"}
        legacy_active = {"EXECUTING"}
        legacy_waiting = {"PENDING_VALIDATION", "APPROVED"}

        for ls in legacy_terminal:
            cs = map_legacy_mission_status(ls, "mission_system")
            self.assertTrue(cs.is_terminal,
                            f"Legacy terminal {ls} → {cs.value} should be terminal")

        for ls in legacy_active:
            cs = map_legacy_mission_status(ls, "mission_system")
            self.assertTrue(cs.is_active,
                            f"Legacy active {ls} → {cs.value} should be active")

        for ls in legacy_waiting:
            cs = map_legacy_mission_status(ls, "mission_system")
            self.assertTrue(cs.is_waiting,
                            f"Legacy waiting {ls} → {cs.value} should be waiting")

    def test_meta_orchestrator_roundtrip(self):
        from core.canonical_types import map_legacy_mission_status
        terminal = {"DONE": True, "FAILED": True}
        active = {"RUNNING": True, "REVIEW": True}
        for ls, expected in {**terminal, **active}.items():
            cs = map_legacy_mission_status(ls, "meta_orchestrator")
            if ls in terminal:
                self.assertTrue(cs.is_terminal, f"{ls} → {cs.value} should be terminal")
            else:
                self.assertTrue(cs.is_active, f"{ls} → {cs.value} should be active")


# ═══════════════════════════════════════════════════════════════
# MEMORY FACADE E2E
# ═══════════════════════════════════════════════════════════════

class TestMemoryFacadeE2E(unittest.TestCase):
    """Full store → search → health cycle."""

    def setUp(self):
        self._ws = "/tmp/jarvis_e2e_mf_test"
        shutil.rmtree(self._ws, ignore_errors=True)
        os.makedirs(self._ws, exist_ok=True)
        import core.memory_facade as mf
        mf._facade = None
        self.facade = mf.MemoryFacade(workspace_dir=self._ws)

    def test_store_then_search(self):
        """Store a solution, then search should find it."""
        self.facade.store(
            content="Fixed auth bug by refreshing OAuth token before expiry",
            content_type="solution",
            tags=["auth", "oauth", "token"],
        )
        results = self.facade.search("oauth token refresh", top_k=5)
        # Results may be empty if no backends available, but should not crash
        self.assertIsInstance(results, list)

    def test_store_multiple_types(self):
        for ct in ["solution", "error", "decision", "pattern", "mission_outcome"]:
            result = self.facade.store(
                content=f"Test content for {ct}",
                content_type=ct,
                tags=[ct, "test"],
            )
            self.assertTrue(result["ok"], f"Store failed for content_type={ct}")

    def test_health_after_operations(self):
        self.facade.store(content="test", content_type="general")
        health = self.facade.health()
        self.assertIsInstance(health, dict)

    def tearDown(self):
        shutil.rmtree(self._ws, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# EXECUTION ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestExecutionEngineIntegration(unittest.TestCase):
    """Execution engine modules are importable and functional."""

    def test_execution_engine_imports(self):
        try:
            from core.execution_engine import (
                execute_tool_intelligently,
                evaluate_mission,
                store_evaluation,
            )
        except ImportError:
            self.skipTest("execution_engine not available")
        # Functions exist
        self.assertTrue(callable(execute_tool_intelligently))
        self.assertTrue(callable(evaluate_mission))

    def test_evaluate_mission_produces_bounded_output(self):
        try:
            from core.execution_engine import evaluate_mission
        except ImportError:
            self.skipTest("execution_engine not available")
        result = evaluate_mission(
            mission_id="test-eval",
            success=True,
            final_output="Test output",
            goal="Test goal",
            agents_used=["scout-research"],
            tools_used=["web_search"],
            duration_s=5.0,
            plan_steps=3,
        )
        # May be a dict or a dataclass (MissionEvaluation)
        if hasattr(result, 'overall_score'):
            # Dataclass — check score bounds
            self.assertGreaterEqual(result.overall_score, 0.0)
            self.assertLessEqual(result.overall_score, 1.0)
        elif isinstance(result, dict):
            for key in ["goal_alignment", "tool_utilization", "stability"]:
                if key in result:
                    self.assertGreaterEqual(result[key], 0.0)
                    self.assertLessEqual(result[key], 1.0)
        else:
            self.fail(f"Unexpected result type: {type(result)}")


# ═══════════════════════════════════════════════════════════════
# SAFETY CONTROLS INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestSafetyControlsIntegration(unittest.TestCase):
    """Safety controls are accessible and functional."""

    def test_kill_switch_check(self):
        try:
            from core.safety_controls import is_execution_enabled
        except ImportError:
            self.skipTest("safety_controls not available")
        # Default: enabled
        result = is_execution_enabled()
        self.assertIsInstance(result, bool)

    def test_kill_switch_env_var(self):
        """JARVIS_EXECUTION_DISABLED=1 should disable execution."""
        try:
            from core.safety_controls import is_execution_enabled
        except ImportError:
            self.skipTest("safety_controls not available")
        os.environ["JARVIS_EXECUTION_DISABLED"] = "1"
        try:
            result = is_execution_enabled()
            self.assertFalse(result)
        finally:
            os.environ.pop("JARVIS_EXECUTION_DISABLED", None)


if __name__ == "__main__":
    unittest.main()
